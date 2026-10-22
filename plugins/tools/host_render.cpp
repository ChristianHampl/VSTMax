// aime_host_render: lädt das gebaute AIME.vst3 über die offiziellen SDK-Hosting-Klassen, setzt den
// Zustand aus einer .vstpreset-Datei (wie von der AIME-App exportiert) und verarbeitet rohes float32-Audio.
// Dient als Ende-zu-Ende-Nachweis: Python-Export -> VST3-Binary -> Audio (tests/test_vst3_host.py).
//
// aime_host_render --module AIME.vst3 --class "AIME Channel" --preset p.vstpreset --sr 48000 --channels 2
//                  --in in.f32 --out out.f32 [--block 512]
#include "public.sdk/source/common/memorystream.h"
#include "public.sdk/source/vst/hosting/hostclasses.h"
#include "public.sdk/source/vst/hosting/module.h"
#include "public.sdk/source/vst/hosting/plugprovider.h"
#include "public.sdk/source/vst/hosting/processdata.h"
#include "pluginterfaces/vst/ivstaudioprocessor.h"
#include "pluginterfaces/vst/ivstcomponent.h"
#include "pluginterfaces/vst/ivsteditcontroller.h"

#include <cstdio>
#include <cstring>
#include <fstream>
#include <iterator>
#include <map>
#include <string>
#include <vector>

using namespace Steinberg;
using namespace Steinberg::Vst;
using namespace VST3::Hosting;

static std::vector<uint8_t> readFile (const std::string& p)
{
	std::ifstream f (p, std::ios::binary);
	return std::vector<uint8_t> ((std::istreambuf_iterator<char> (f)), std::istreambuf_iterator<char> ());
}

static bool presetChunk (const std::vector<uint8_t>& d, const char* id, std::vector<uint8_t>& out)
{
	if (d.size () < 48 || std::memcmp (d.data (), "VST3", 4) != 0)
		return false;
	int64_t listOff;
	std::memcpy (&listOff, d.data () + 40, 8);
	if (listOff < 0 || size_t (listOff) + 8 > d.size () || std::memcmp (d.data () + listOff, "List", 4) != 0)
		return false;
	int32_t n;
	std::memcpy (&n, d.data () + listOff + 4, 4);
	for (int i = 0; i < n; ++i)
	{
		const size_t e = size_t (listOff) + 8 + size_t (i) * 20;
		if (e + 20 > d.size ())
			return false;
		int64_t o, s;
		std::memcpy (&o, d.data () + e + 4, 8);
		std::memcpy (&s, d.data () + e + 12, 8);
		if (std::memcmp (d.data () + e, id, 4) == 0 && o >= 0 && s >= 0 && size_t (o + s) <= d.size ())
		{
			out.assign (d.begin () + o, d.begin () + o + s);
			return true;
		}
	}
	return false;
}

int main (int argc, char** argv)
{
	std::map<std::string, std::string> a;
	for (int i = 1; i + 1 < argc; i += 2)
		a[argv[i]] = argv[i + 1];
	for (const char* k : {"--module", "--class", "--sr", "--in", "--out"})
		if (!a.count (k))
		{
			std::fprintf (stderr, "Parameter fehlt: %s\n", k);
			return 2;
		}
	const double sr = std::stod (a["--sr"]);
	const int nch = a.count ("--channels") ? std::stoi (a["--channels"]) : 2;
	const int block = a.count ("--block") ? std::stoi (a["--block"]) : 512;

	auto host = owned (new HostApplication ());
	PluginContextFactory::instance ().setPluginContext (host);

	std::string err;
	auto module = Module::create (a["--module"], err);
	if (!module)
	{
		std::fprintf (stderr, "Modul nicht ladbar: %s\n", err.c_str ());
		return 3;
	}
	const auto& factory = module->getFactory ();
	IPtr<PlugProvider> provider;
	for (auto& ci : factory.classInfos ())
		if (ci.category () == kVstAudioEffectClass && ci.name () == a["--class"])
			provider = owned (new PlugProvider (factory, ci, true));
	if (!provider || !provider->initialize ())
	{
		std::fprintf (stderr, "Klasse nicht gefunden/initialisierbar: %s\n", a["--class"].c_str ());
		return 3;
	}
	auto component = provider->getComponentPtr ();
	auto controller = provider->getControllerPtr ();
	FUnknownPtr<IAudioProcessor> processor (component);
	if (!processor)
		return 3;

	int params = 0;
	if (a.count ("--preset"))
	{
		std::vector<uint8_t> comp;
		if (!presetChunk (readFile (a["--preset"]), "Comp", comp))
		{
			std::fprintf (stderr, "Preset ohne Comp-Chunk\n");
			return 4;
		}
		auto stream = owned (new MemoryStream (comp.data (), TSize (comp.size ())));
		if (component->setState (stream) != kResultOk)
		{
			std::fprintf (stderr, "setState fehlgeschlagen\n");
			return 4;
		}
		if (controller)
		{
			stream->seek (0, IBStream::kIBSeekSet, nullptr);
			controller->setComponentState (stream);
			params = controller->getParameterCount ();
		}
	}

	SpeakerArrangement arr = nch == 1 ? SpeakerArr::kMono : SpeakerArr::kStereo;
	std::vector<SpeakerArrangement> ins (size_t (component->getBusCount (kAudio, kInput)), SpeakerArr::kStereo);
	ins[0] = arr;
	SpeakerArrangement outs[1] = {arr};
	if (processor->setBusArrangements (ins.data (), int32 (ins.size ()), outs, 1) != kResultTrue)
	{
		std::fprintf (stderr, "Busanordnung abgelehnt\n");
		return 5;
	}
	ProcessSetup setup {kOffline, kSample32, block, sr};
	if (processor->setupProcessing (setup) != kResultOk)
		return 5;
	component->setActive (true);
	processor->setProcessing (true);

	HostProcessData data;
	data.prepare (*component, block, kSample32);
	auto raw = readFile (a["--in"]);
	std::vector<float> audio (raw.size () / 4);
	std::memcpy (audio.data (), raw.data (), audio.size () * 4);
	const int frames = int (audio.size ()) / nch;
	for (int o = 0; o < frames; o += block)
	{
		const int m = std::min (block, frames - o);
		data.numSamples = m;
		for (int c = 0; c < nch; ++c)
		{
			for (int i = 0; i < m; ++i)
				data.inputs[0].channelBuffers32[c][i] = audio[size_t ((o + i) * nch + c)];
		}
		for (int b = 1; b < data.numInputs; ++b)
			for (int c = 0; c < data.inputs[b].numChannels; ++c)
				std::fill (data.inputs[b].channelBuffers32[c], data.inputs[b].channelBuffers32[c] + m, 0.f);
		if (processor->process (data) != kResultOk)
		{
			std::fprintf (stderr, "process fehlgeschlagen\n");
			return 6;
		}
		for (int c = 0; c < nch; ++c)
			for (int i = 0; i < m; ++i)
				audio[size_t ((o + i) * nch + c)] = data.outputs[0].channelBuffers32[c][i];
	}
	const uint32 latency = processor->getLatencySamples ();
	processor->setProcessing (false);
	component->setActive (false);
	data.unprepare ();

	std::ofstream f (a["--out"], std::ios::binary);
	f.write (reinterpret_cast<const char*> (audio.data ()), std::streamsize (audio.size () * 4));
	std::printf ("{\"class\": \"%s\", \"latency_samples\": %u, \"controller_params\": %d}\n", a["--class"].c_str (), latency,
	             params);
	return 0;
}
