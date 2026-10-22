// Testclient für den Plugin-Link: simuliert Plugin-Instanzen (ohne Host) mit dem echten Hub-Code.
// aime_link_client --names "Kick In,Vox Lead" --seconds 4 [--sr 48000]
// Gibt empfangene Parameter als JSON-Zeilen auf stdout aus.
#include "aime_link.h"

#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <map>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

using namespace aime::link;

struct PrintSink : ParamSink
{
	uint64_t id = 0;
	std::mutex* out = nullptr;
	void enqueueParams (const std::vector<std::pair<uint32_t, double>>& v) override
	{
		std::lock_guard<std::mutex> l (*out);
		for (auto& [pid, val] : v)
			std::printf ("{\"instance\": \"%016llx\", \"id\": %u, \"value\": %.6f}\n", static_cast<unsigned long long> (id), pid,
			             val);
		std::fflush (stdout);
	}
};

int main (int argc, char** argv)
{
	std::string names = "Kick In,Vox Lead";
	double seconds = 4, sr = 48000;
	for (int i = 1; i + 1 < argc; i += 2)
	{
		if (!std::strcmp (argv[i], "--names"))
			names = argv[i + 1];
		else if (!std::strcmp (argv[i], "--seconds"))
			seconds = std::stod (argv[i + 1]);
		else if (!std::strcmp (argv[i], "--sr"))
			sr = std::stod (argv[i + 1]);
	}
	std::vector<std::string> list;
	std::stringstream ss (names);
	for (std::string s; std::getline (ss, s, ',');)
		list.push_back (s);

	auto& hub = Hub::instance ();
	std::mutex outMtx;
	std::vector<std::shared_ptr<ProcessorSlot>> slots;
	std::vector<PrintSink> sinks (list.size ());
	for (size_t k = 0; k < list.size (); ++k)
	{
		const uint64_t id = 0x1000 + k;
		InstanceInfo info;
		info.plugin = "channel";
		info.channelName = list[k];
		info.sampleRate = sr;
		info.channels = 2;
		info.latency = 15;
		slots.push_back (hub.registerProcessor (id, info));
		sinks[k].id = id;
		sinks[k].out = &outMtx;
		hub.registerController (id, &sinks[k]);
	}
	// Echtzeit-Simulation: je 256 Frames ein Chunk pro Instanz, Projektposition fortlaufend
	const auto t0 = std::chrono::steady_clock::now ();
	int64_t pos = 0;
	AudioChunk c;
	while (std::chrono::duration<double> (std::chrono::steady_clock::now () - t0).count () < seconds)
	{
		for (size_t k = 0; k < slots.size (); ++k)
		{
			if (!slots[k]->capture.load ())
				continue;
			c.pos = pos;
			c.frames = kChunkFrames;
			c.channels = 2;
			c.playing = 1;
			const double f = 100.0 * double (k + 1);
			for (int i = 0; i < kChunkFrames; ++i)
			{
				const float v = float (0.5 * std::sin (2 * aime::kPi * f * double (pos + i) / sr));
				c.data[2 * i] = v;
				c.data[2 * i + 1] = v;
			}
			slots[k]->ring.push (&c, 1);
		}
		pos += kChunkFrames;
		std::this_thread::sleep_for (std::chrono::microseconds (int64_t (1e6 * kChunkFrames / sr)));
	}
	for (size_t k = 0; k < list.size (); ++k)
	{
		hub.unregisterController (0x1000 + k, &sinks[k]);
		hub.unregisterProcessor (0x1000 + k);
	}
	return 0;
}
