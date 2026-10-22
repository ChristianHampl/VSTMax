#include "aime_link.h"

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#if defined(_WIN32)
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <winsock2.h>
#include <ws2tcpip.h>
using SockLen = int;
#else
#include <arpa/inet.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

namespace aime::link {

namespace {

#if defined(_WIN32)
using Socket = SOCKET;
constexpr Socket kInvalid = INVALID_SOCKET;
inline void closeRaw (Socket s) { closesocket (s); }
struct WsaInit
{
	bool ok = false;
	WsaInit ()
	{
		WSADATA d;
		ok = WSAStartup (MAKEWORD (2, 2), &d) == 0;
	}
	~WsaInit ()
	{
		if (ok)
			WSACleanup ();
	}
};
#else
using Socket = int;
constexpr Socket kInvalid = -1;
inline void closeRaw (Socket s) { ::close (s); }
#endif

#if defined(MSG_NOSIGNAL)
constexpr int kSendFlags = MSG_NOSIGNAL;
#else
constexpr int kSendFlags = 0;
#endif

void putU32 (std::vector<uint8_t>& o, uint32_t v)
{
	for (int i = 0; i < 4; ++i)
		o.push_back (uint8_t (v >> (8 * i)));
}
void putU64 (std::vector<uint8_t>& o, uint64_t v)
{
	for (int i = 0; i < 8; ++i)
		o.push_back (uint8_t (v >> (8 * i)));
}
uint32_t getU32 (const uint8_t* p)
{
	return uint32_t (p[0]) | (uint32_t (p[1]) << 8) | (uint32_t (p[2]) << 16) | (uint32_t (p[3]) << 24);
}
uint64_t getU64 (const uint8_t* p) { return uint64_t (getU32 (p)) | (uint64_t (getU32 (p + 4)) << 32); }

std::string jsonEscape (const std::string& s)
{
	std::string o;
	for (unsigned char c : s)
	{
		switch (c)
		{
			case '"': o += "\\\""; break;
			case '\\': o += "\\\\"; break;
			case '\n': o += "\\n"; break;
			case '\r': o += "\\r"; break;
			case '\t': o += "\\t"; break;
			default:
				if (c < 0x20)
				{
					char b[8];
					std::snprintf (b, sizeof (b), "\\u%04x", c);
					o += b;
				}
				else
					o += char (c);
		}
	}
	return o;
}

std::string hexId (uint64_t id)
{
	char b[20];
	std::snprintf (b, sizeof (b), "%016llx", static_cast<unsigned long long> (id));
	return b;
}

} // namespace

//------------------------------------------------------------------------
Hub& Hub::instance ()
{
	static Hub hub;
	return hub;
}

Hub::~Hub ()
{
	running = false;
	if (thread.joinable ())
		thread.join ();
	closeSocket ();
}

uint16_t Hub::configuredPort ()
{
	if (const char* e = std::getenv ("AIME_LINK_PORT"))
	{
		const long v = std::strtol (e, nullptr, 10);
		if (v > 0 && v < 65536)
			return uint16_t (v);
	}
	return kDefaultPort;
}

std::string Hub::instanceJson (uint64_t id, const InstanceInfo& i)
{
	char num[160];
	std::snprintf (num, sizeof (num), "\"sample_rate\":%.1f,\"channels\":%d,\"latency\":%d", i.sampleRate, i.channels,
	               i.latency);
	return "{\"instance\":\"" + hexId (id) + "\",\"plugin\":\"" + jsonEscape (i.plugin) + "\",\"channel_name\":\"" +
	       jsonEscape (i.channelName) + "\",\"channel_uid\":\"" + jsonEscape (i.channelUid) + "\",\"label\":\"" +
	       jsonEscape (i.label) + "\"," + num + "}";
}

bool Hub::parseSetParams (const uint8_t* p, size_t n, uint64_t& id, std::vector<std::pair<uint32_t, double>>& out)
{
	out.clear ();
	if (n < 12)
		return false;
	id = getU64 (p);
	const uint32_t count = getU32 (p + 8);
	if (count > 4096 || n < 12 + size_t (count) * 12)
		return false;
	for (uint32_t k = 0; k < count; ++k)
	{
		const uint8_t* q = p + 12 + size_t (k) * 12;
		double v;
		const uint64_t bits = getU64 (q + 4);
		std::memcpy (&v, &bits, 8);
		if (std::isfinite (v))
			out.emplace_back (getU32 (q), v);
	}
	return true;
}

//------------------------------------------------------------------------
std::shared_ptr<ProcessorSlot> Hub::registerProcessor (uint64_t id, const InstanceInfo& info)
{
	auto slot = std::make_shared<ProcessorSlot> ();
	slot->ring.prepare (1024); // 1024 x 256 Frames ~ 5,4 s bei 48 kHz
	{
		std::lock_guard<std::mutex> l (mtx);
		auto& e = entries[id];
		e.info = info;
		e.slot = slot;
		e.dirty = true;
		slot->capture = captureOn;
	}
	ensureThread ();
	return slot;
}

void Hub::unregisterProcessor (uint64_t id)
{
	bool stop = false;
	{
		std::lock_guard<std::mutex> l (mtx);
		auto it = entries.find (id);
		if (it != entries.end ())
		{
			it->second.slot.reset ();
			if (!it->second.sink)
			{
				entries.erase (it);
				removed.push_back (id);
			}
		}
		stop = entries.empty ();
	}
	if (stop && running.exchange (false) && thread.joinable ())
		thread.join ();
}

void Hub::updateInfo (uint64_t id, const std::function<void (InstanceInfo&)>& fn)
{
	std::lock_guard<std::mutex> l (mtx);
	auto it = entries.find (id);
	if (it == entries.end ())
		return;
	fn (it->second.info);
	it->second.dirty = true;
}

void Hub::registerController (uint64_t id, ParamSink* sink)
{
	{
		std::lock_guard<std::mutex> l (mtx);
		entries[id].sink = sink;
	}
	ensureThread ();
}

void Hub::unregisterController (uint64_t id, ParamSink* sink)
{
	bool stop = false;
	{
		std::lock_guard<std::mutex> l (mtx);
		auto it = entries.find (id);
		if (it != entries.end () && it->second.sink == sink)
		{
			it->second.sink = nullptr;
			if (!it->second.slot)
			{
				entries.erase (it);
				removed.push_back (id);
			}
		}
		stop = entries.empty ();
	}
	if (stop && running.exchange (false) && thread.joinable ())
		thread.join ();
}

void Hub::ensureThread ()
{
	if (running.exchange (true))
		return;
	if (thread.joinable ())
		thread.join ();
	thread = std::thread ([this] { run (); });
}

//------------------------------------------------------------------------
void Hub::closeSocket ()
{
	if (sock != -1)
		closeRaw (Socket (sock));
	sock = -1;
	connected = false;
}

bool Hub::connectOnce ()
{
	Socket s = ::socket (AF_INET, SOCK_STREAM, IPPROTO_TCP);
	if (s == kInvalid)
		return false;
	sockaddr_in a {};
	a.sin_family = AF_INET;
	a.sin_port = htons (configuredPort ());
	a.sin_addr.s_addr = htonl (INADDR_LOOPBACK); // ausschließlich lokal
	if (::connect (s, reinterpret_cast<sockaddr*> (&a), sizeof (a)) != 0)
	{
		closeRaw (s);
		return false;
	}
	int one = 1;
	::setsockopt (s, IPPROTO_TCP, TCP_NODELAY, reinterpret_cast<const char*> (&one), sizeof (one));
#if defined(SO_NOSIGPIPE)
	::setsockopt (s, SOL_SOCKET, SO_NOSIGPIPE, &one, sizeof (one));
#endif
	sock = intptr_t (s);
	connected = true;
	rx.clear ();
	const std::string hello = "{\"protocol\":" + std::to_string (kProtocolVersion) + ",\"client\":\"AIME VST3\"}";
	return sendMsg (kHello, hello.data (), hello.size ());
}

bool Hub::sendMsg (uint8_t type, const void* payload, size_t n)
{
	if (sock == -1)
		return false;
	tx.clear ();
	putU32 (tx, uint32_t (n + 1));
	tx.push_back (type);
	const auto* b = static_cast<const uint8_t*> (payload);
	tx.insert (tx.end (), b, b + n);
	size_t off = 0;
	while (off < tx.size ())
	{
		const auto r = ::send (Socket (sock), reinterpret_cast<const char*> (tx.data () + off), int (tx.size () - off),
		                       kSendFlags);
		if (r <= 0)
		{
			closeSocket ();
			return false;
		}
		off += size_t (r);
	}
	return true;
}

bool Hub::pumpInfo ()
{
	struct Out
	{
		uint8_t type;
		std::string payload;
	};
	std::vector<Out> out;
	{
		std::lock_guard<std::mutex> l (mtx);
		for (auto id : removed)
			out.push_back ({kInstanceRemove, "{\"instance\":\"" + hexId (id) + "\"}"});
		removed.clear ();
		for (auto& [id, e] : entries)
			if (e.slot && (e.dirty || !e.announced))
			{
				out.push_back ({uint8_t (e.announced ? kInstanceUpdate : kInstanceAdd), instanceJson (id, e.info)});
				e.dirty = false;
				e.announced = true;
			}
	}
	for (auto& o : out)
		if (!sendMsg (o.type, o.payload.data (), o.payload.size ()))
			return false;
	return true;
}

bool Hub::pumpAudio ()
{
	std::vector<std::pair<uint64_t, std::shared_ptr<ProcessorSlot>>> slots;
	{
		std::lock_guard<std::mutex> l (mtx);
		for (auto& [id, e] : entries)
			if (e.slot && e.announced)
				slots.emplace_back (id, e.slot);
	}
	std::vector<uint8_t> msg;
	AudioChunk c;
	for (auto& [id, slot] : slots)
	{
		for (int k = 0; k < 64 && slot->ring.pop (&c, 1) == 1; ++k)
		{
			if (c.frames == 0 || c.channels == 0 || c.channels > 2 || c.frames > uint32_t (kChunkFrames))
				continue;
			msg.clear ();
			putU64 (msg, id);
			putU64 (msg, uint64_t (c.pos));
			putU32 (msg, c.frames);
			msg.push_back (uint8_t (c.channels & 0xFF));
			msg.push_back (uint8_t (c.channels >> 8));
			msg.push_back (c.playing);
			msg.push_back (0);
			const size_t bytes = size_t (c.frames) * c.channels * sizeof (float);
			const auto* f = reinterpret_cast<const uint8_t*> (c.data);
			msg.insert (msg.end (), f, f + bytes);
			if (!sendMsg (kAudio, msg.data (), msg.size ()))
				return false;
		}
	}
	return true;
}

void Hub::setCaptureAll (bool on)
{
	std::lock_guard<std::mutex> l (mtx);
	captureOn = on;
	for (auto& [id, e] : entries)
		if (e.slot)
			e.slot->capture = on;
}

void Hub::handle (uint8_t type, const uint8_t* p, size_t n)
{
	switch (type)
	{
		case kSetParams:
		{
			uint64_t id = 0;
			std::vector<std::pair<uint32_t, double>> vals;
			if (!parseSetParams (p, n, id, vals))
				return;
			std::lock_guard<std::mutex> l (mtx);
			auto it = entries.find (id);
			if (it != entries.end () && it->second.sink)
				it->second.sink->enqueueParams (vals);
			return;
		}
		case kCapture:
			if (n >= 1)
				setCaptureAll (p[0] != 0);
			return;
		case kPing: sendMsg (kPing, nullptr, 0); return;
		default: return; // unbekannte Typen ignorieren (Vorwärtskompatibilität)
	}
}

bool Hub::receive (int timeoutMs)
{
	if (sock == -1)
		return false;
#if defined(_WIN32)
	fd_set rs;
	FD_ZERO (&rs);
	FD_SET (Socket (sock), &rs);
	timeval tv {0, timeoutMs * 1000};
	const int r = ::select (0, &rs, nullptr, nullptr, &tv);
#else
	pollfd pf {int (sock), POLLIN, 0};
	const int r = ::poll (&pf, 1, timeoutMs);
#endif
	if (r < 0)
	{
		closeSocket ();
		return false;
	}
	if (r == 0)
		return true;
	uint8_t buf[65536];
	const auto got = ::recv (Socket (sock), reinterpret_cast<char*> (buf), int (sizeof (buf)), 0);
	if (got <= 0)
	{
		closeSocket ();
		return false;
	}
	rx.insert (rx.end (), buf, buf + got);
	size_t off = 0;
	while (rx.size () - off >= 5)
	{
		const uint32_t len = getU32 (rx.data () + off);
		if (len == 0 || len > kMaxMessageBytes)
		{
			closeSocket ();
			return false;
		}
		if (rx.size () - off - 4 < len)
			break;
		handle (rx[off + 4], rx.data () + off + 5, len - 1);
		if (sock == -1)
			return false;
		off += 4 + len;
	}
	rx.erase (rx.begin (), rx.begin () + long (off));
	return true;
}

void Hub::run ()
{
#if defined(_WIN32)
	WsaInit wsa;
#endif
	auto nextTry = std::chrono::steady_clock::now ();
	while (running.load ())
	{
		if (sock == -1)
		{
			if (captureOn)
				setCaptureAll (false);
			if (std::chrono::steady_clock::now () >= nextTry)
			{
				if (connectOnce ())
				{
					std::lock_guard<std::mutex> l (mtx);
					for (auto& [id, e] : entries)
						e.announced = false;
					removed.clear ();
				}
				nextTry = std::chrono::steady_clock::now () + std::chrono::seconds (1);
			}
			std::this_thread::sleep_for (std::chrono::milliseconds (50));
			continue;
		}
		if (!pumpInfo () || !pumpAudio () || !receive (5))
			continue;
	}
	closeSocket ();
}

} // namespace aime::link
