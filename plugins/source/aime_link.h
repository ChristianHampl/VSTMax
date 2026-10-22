// AIME Plugin-Link: eine gemeinsame localhost-TCP-Verbindung aller Plugin-Instanzen eines
// Moduls zur AIME-App (integration/plugin_link/server.py).
//
// Rahmen: u32 Länge (Typ + Nutzdaten, Little Endian) | u8 Typ | Nutzdaten
// Plugin -> App: Hello, InstanceAdd/Update (JSON), InstanceRemove, Audio (binär)
// App -> Plugin: SetParams (binär), Capture (u8), Ping
//
// Echtzeitregeln: Der Audio-Thread schreibt ausschließlich in den lock-freien Ringpuffer seines
// Slots und liest ein atomares Flag. Netzwerk, Locks und Allokationen laufen im Link-Thread.
#pragma once

#include "aime_dsp.h"

#include <atomic>
#include <cstdint>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace aime::link {

inline constexpr uint16_t kDefaultPort = 47800;
inline constexpr uint32_t kProtocolVersion = 1;
inline constexpr int kChunkFrames = 256;
inline constexpr uint32_t kMaxMessageBytes = 16u * 1024u * 1024u;

enum MsgType : uint8_t
{
	kHello = 1,
	kInstanceAdd = 2,
	kInstanceUpdate = 3,
	kInstanceRemove = 4,
	kAudio = 5,
	kSetParams = 20,
	kCapture = 21,
	kPing = 22,
};

struct AudioChunk
{
	int64_t pos = 0;
	uint32_t frames = 0;
	uint16_t channels = 0;
	uint8_t playing = 0;
	float data[2 * kChunkFrames] {};
};

struct InstanceInfo
{
	std::string plugin; // "channel" | "bus" | "master"
	std::string channelName, channelUid, label;
	double sampleRate = 0;
	int channels = 0;
	int latency = 0;
};

// Vom Audio-Thread benutzt (nur push + Flag lesen)
struct ProcessorSlot
{
	SpscRing<AudioChunk> ring;
	std::atomic<bool> capture {false};
};

// Empfänger für Parameterbefehle (Controller); enqueue wird im Link-Thread aufgerufen
struct ParamSink
{
	virtual ~ParamSink () = default;
	virtual void enqueueParams (const std::vector<std::pair<uint32_t, double>>& values) = 0;
};

class Hub
{
public:
	static Hub& instance ();

	// Prozessor-Seite (UI-/Host-Thread, nicht Audio-Thread)
	std::shared_ptr<ProcessorSlot> registerProcessor (uint64_t id, const InstanceInfo& info);
	void unregisterProcessor (uint64_t id);
	void updateInfo (uint64_t id, const std::function<void (InstanceInfo&)>& fn);

	// Controller-Seite
	void registerController (uint64_t id, ParamSink* sink);
	void unregisterController (uint64_t id, ParamSink* sink);

	bool isConnected () const { return connected.load (); }
	static uint16_t configuredPort ();

	// Für Tests: Kodierung/Dekodierung ohne Netzwerk
	static std::string instanceJson (uint64_t id, const InstanceInfo& info);
	static bool parseSetParams (const uint8_t* p, size_t n, uint64_t& id, std::vector<std::pair<uint32_t, double>>& out);

	~Hub ();

private:
	Hub () = default;
	struct Entry
	{
		InstanceInfo info;
		std::shared_ptr<ProcessorSlot> slot;
		ParamSink* sink = nullptr;
		bool announced = false, dirty = false;
	};
	void ensureThread ();
	void run ();
	bool connectOnce ();
	void closeSocket ();
	bool sendMsg (uint8_t type, const void* payload, size_t n);
	bool pumpAudio ();
	bool pumpInfo ();
	bool receive (int timeoutMs);
	void handle (uint8_t type, const uint8_t* p, size_t n);
	void setCaptureAll (bool on);

	std::mutex mtx;
	std::map<uint64_t, Entry> entries;
	std::vector<uint64_t> removed;
	std::thread thread;
	std::atomic<bool> running {false}, connected {false};
	bool captureOn = false;
	intptr_t sock = -1;
	std::vector<uint8_t> rx, tx;
};

} // namespace aime::link
