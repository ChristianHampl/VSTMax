// aime_render: verarbeitet rohe float32-Audiodaten (interleaved) mit einem AIME-Kanalzug.
// Dient dem Abgleich Offline-Engine (Python) <-> Plugin-DSP (C++), z. B. für exportierte Presets.
//
// aime_render --plugin channel|bus|master --state datei.aims|datei.vstpreset --sr 48000 --channels 2
//             --in eingang.f32 --out ausgang.f32 [--sidechain sc.f32 --sc-channels 2] [--block 512]
// Ausgabe auf stdout (JSON): Latenz, Meterwerte.
#include "aime_state.h"
#include "aime_strips.h"

#include <cstdio>
#include <cstring>
#include <fstream>
#include <iterator>
#include <map>
#include <string>
#include <type_traits>
#include <vector>

static std::vector<uint8_t> readFile (const std::string& p)
{
	std::ifstream f (p, std::ios::binary);
	return std::vector<uint8_t> ((std::istreambuf_iterator<char> (f)), std::istreambuf_iterator<char> ());
}

// Sucht im .vstpreset den 'Comp'-Chunk (Format siehe integration/presets/vstpreset.py)
static bool extractState (const std::vector<uint8_t>& d, std::vector<uint8_t>& out)
{
	if (d.size () >= 4 && std::memcmp (d.data (), "AIMS", 4) == 0)
	{
		out = d;
		return true;
	}
	if (d.size () < 48 || std::memcmp (d.data (), "VST3", 4) != 0)
		return false;
	int64_t listOff;
	std::memcpy (&listOff, d.data () + 40, 8);
	if (listOff < 0 || size_t (listOff) + 8 > d.size () || std::memcmp (d.data () + listOff, "List", 4) != 0)
		return false;
	int32_t n;
	std::memcpy (&n, d.data () + listOff + 4, 4);
	size_t off = size_t (listOff) + 8;
	for (int i = 0; i < n && off + 20 <= d.size (); ++i, off += 20)
	{
		int64_t o, s;
		std::memcpy (&o, d.data () + off + 4, 8);
		std::memcpy (&s, d.data () + off + 12, 8);
		if (std::memcmp (d.data () + off, "Comp", 4) == 0 && o >= 0 && s >= 0 && size_t (o + s) <= d.size ())
		{
			out.assign (d.begin () + o, d.begin () + o + s);
			return true;
		}
	}
	return false;
}

template <typename Strip>
static int run (Strip& strip, const std::vector<aime::state::Entry>& entries, double sr, int nch, std::vector<float>& audio,
                const std::vector<float>* sc, int scCh, int block, bool sidechainCapable)
{
	for (const auto& e : entries)
		strip.setParam (e.id, e.value);
	strip.prepare (sr);
	const int frames = int (audio.size ()) / nch;
	const size_t bs = static_cast<size_t> (block);
	std::vector<float> a (bs), b (bs), s0 (bs), s1 (bs);
	for (int o = 0; o < frames; o += block)
	{
		const int m = std::min (block, frames - o);
		for (int i = 0; i < m; ++i)
		{
			a[size_t (i)] = audio[size_t ((o + i) * nch)];
			if (nch > 1)
				b[size_t (i)] = audio[size_t ((o + i) * nch + 1)];
			if (sc)
			{
				s0[size_t (i)] = (*sc)[size_t ((o + i) * scCh)];
				if (scCh > 1)
					s1[size_t (i)] = (*sc)[size_t ((o + i) * scCh + 1)];
			}
		}
		float* p[2] = {a.data (), b.data ()};
		float* q[2] = {s0.data (), s1.data ()};
		if constexpr (std::is_same_v<Strip, aime::ChannelStrip>)
			strip.process (p, nch, m, (sc && sidechainCapable) ? q : nullptr, sc ? scCh : 0);
		else
			strip.process (p, nch, m);
		for (int i = 0; i < m; ++i)
		{
			audio[size_t ((o + i) * nch)] = a[size_t (i)];
			if (nch > 1)
				audio[size_t ((o + i) * nch + 1)] = b[size_t (i)];
		}
	}
	return 0;
}

int main (int argc, char** argv)
{
	std::map<std::string, std::string> a;
	for (int i = 1; i + 1 < argc; i += 2)
		a[argv[i]] = argv[i + 1];
	if (!a.count ("--plugin") || !a.count ("--in") || !a.count ("--out") || !a.count ("--sr"))
	{
		std::fprintf (stderr, "Aufruf: aime_render --plugin channel|bus|master --sr SR --channels N --in IN.f32 --out OUT.f32 "
		                      "[--state STATE] [--sidechain SC.f32 --sc-channels N] [--block N]\n");
		return 2;
	}
	const double sr = std::stod (a["--sr"]);
	const int nch = a.count ("--channels") ? std::stoi (a["--channels"]) : 2;
	const int block = a.count ("--block") ? std::stoi (a["--block"]) : 512;
	if (nch < 1 || nch > 2 || block < 1 || sr < 8000)
	{
		std::fprintf (stderr, "Ungültige Parameter\n");
		return 2;
	}
	std::vector<aime::state::Entry> entries;
	std::string label;
	if (a.count ("--state"))
	{
		std::vector<uint8_t> st;
		if (!extractState (readFile (a["--state"]), st) || !aime::state::decode (st.data (), st.size (), entries, label))
		{
			std::fprintf (stderr, "Zustand nicht lesbar: %s\n", a["--state"].c_str ());
			return 3;
		}
	}
	auto raw = readFile (a["--in"]);
	std::vector<float> audio (raw.size () / 4);
	std::memcpy (audio.data (), raw.data (), audio.size () * 4);
	std::vector<float> sc;
	int scCh = 0;
	if (a.count ("--sidechain"))
	{
		scCh = a.count ("--sc-channels") ? std::stoi (a["--sc-channels"]) : 2;
		auto r = readFile (a["--sidechain"]);
		sc.resize (r.size () / 4);
		std::memcpy (sc.data (), r.data (), sc.size () * 4);
		if (sc.size () / size_t (scCh) < audio.size () / size_t (nch))
			sc.resize (audio.size () / size_t (nch) * size_t (scCh), 0.f);
	}
	const std::string plugin = a["--plugin"];
	int latency = 0;
	double gr = 0, mom = -150, st = -150, tp = -70;
	if (plugin == "channel")
	{
		aime::ChannelStrip s;
		run (s, entries, sr, nch, audio, sc.empty () ? nullptr : &sc, scCh, block, true);
		latency = aime::ChannelStrip::latencySamples ();
		gr = s.meterGrDb ();
	}
	else if (plugin == "bus")
	{
		aime::BusStrip s;
		run (s, entries, sr, nch, audio, nullptr, 0, block, false);
		latency = aime::BusStrip::latencySamples ();
		gr = s.meterGrDb ();
	}
	else if (plugin == "master")
	{
		aime::MasterStrip s;
		run (s, entries, sr, nch, audio, nullptr, 0, block, false);
		latency = s.latencySamples ();
		gr = s.meterGrDb ();
		mom = s.momentaryLufs ();
		st = s.shortTermLufs ();
		tp = s.meterTruePeakDb ();
	}
	else
	{
		std::fprintf (stderr, "Unbekanntes Plugin: %s\n", plugin.c_str ());
		return 2;
	}
	std::ofstream f (a["--out"], std::ios::binary);
	f.write (reinterpret_cast<const char*> (audio.data ()), std::streamsize (audio.size () * 4));
	std::printf ("{\"plugin\": \"%s\", \"label\": \"%s\", \"params\": %zu, \"latency_samples\": %d, \"last_gr_db\": %.3f, "
	             "\"momentary_lufs\": %.3f, \"short_term_lufs\": %.3f, \"true_peak_dbtp\": %.3f}\n",
	             plugin.c_str (), label.c_str (), entries.size (), latency, gr, mom, st, tp);
	return f.good () ? 0 : 4;
}
