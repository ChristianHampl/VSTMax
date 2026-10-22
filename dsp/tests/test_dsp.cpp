// DSP-Tests für den AIME-Kern (ohne externe Test-Bibliothek, Ausführung über CTest).
#include "aime_dsp.h"
#include "aime_state.h"
#include "aime_strips.h"

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <functional>
#include <new>
#include <random>
#include <string>
#include <vector>

//------------------------------------------------------------------------ Allokationszähler
#if defined(__GNUC__) && !defined(__clang__)
#pragma GCC diagnostic ignored "-Wmismatched-new-delete"
#endif
static std::atomic<long> gAllocs {0};
static std::atomic<bool> gCount {false};
void* operator new (std::size_t n)
{
	if (gCount.load ())
		++gAllocs;
	if (void* p = std::malloc (n ? n : 1))
		return p;
	throw std::bad_alloc ();
}
void operator delete (void* p) noexcept { std::free (p); }
void operator delete (void* p, std::size_t) noexcept { std::free (p); }

//------------------------------------------------------------------------ Mini-Framework
static int gFailed = 0, gChecks = 0;
#define CHECK(cond, ...)                                                                   \
	do                                                                                     \
	{                                                                                      \
		++gChecks;                                                                         \
		if (!(cond))                                                                       \
		{                                                                                  \
			++gFailed;                                                                     \
			std::printf ("  FEHLER %s:%d: %s -- ", __FILE__, __LINE__, #cond);            \
			std::printf (__VA_ARGS__);                                                     \
			std::printf ("\n");                                                            \
		}                                                                                  \
	} while (0)

using namespace aime;
using Buf = std::vector<std::vector<float>>;

static Buf make (int nch, int n, float v = 0.f) { return Buf (size_t (nch), std::vector<float> (size_t (n), v)); }
static std::vector<float*> ptrs (Buf& b)
{
	std::vector<float*> p;
	for (auto& c : b)
		p.push_back (c.data ());
	return p;
}
static Buf sine (int nch, int n, double f, double amp, double sr)
{
	auto b = make (nch, n);
	for (int c = 0; c < nch; ++c)
		for (int i = 0; i < n; ++i)
			b[size_t (c)][size_t (i)] = float (amp * std::sin (2 * kPi * f * i / sr));
	return b;
}
static double rmsDb (const std::vector<float>& x, size_t from, size_t to)
{
	double s = 0;
	for (size_t i = from; i < to; ++i)
		s += double (x[i]) * x[i];
	return 10 * std::log10 (s / double (to - from) + 1e-30);
}
template <typename Strip>
static void runStrip (Strip& s, Buf& b, int block = 256)
{
	const int n = int (b[0].size ());
	for (int o = 0; o < n; o += block)
	{
		const int m = std::min (block, n - o);
		float* p[2] = {b[0].data () + o, b.size () > 1 ? b[1].data () + o : nullptr};
		s.process (p, int (b.size ()), m);
	}
}

// Unabhängige True-Peak-Referenz: 16x Oversampling mit langem Kaiser-Sinc (nur Test)
static double referenceTruePeak (const std::vector<float>& x)
{
	const int L = 16, half = 64;
	double peak = 0;
	std::vector<double> h (size_t (2 * half * L + 1));
	for (size_t k = 0; k < h.size (); ++k)
	{
		const double t = (double (k) - half * L) / L;
		const double sinc = t == 0 ? 1.0 : std::sin (kPi * t) / (kPi * t);
		const double r = (double (k) - half * L) / (half * L);
		h[k] = sinc * FirKernel<1>::besselI0 (10.0 * std::sqrt (std::max (0.0, 1 - r * r))) / FirKernel<1>::besselI0 (10.0);
	}
	const int n = int (x.size ());
	for (int i = half; i < n - half; ++i)
		for (int p = 0; p < L; ++p)
		{
			double s = 0;
			for (int k = -half + 1; k <= half; ++k)
				s += x[size_t (i + k)] * h[size_t ((half - k) * L + p)];
			peak = std::max (peak, std::fabs (s));
		}
	return peak;
}

//------------------------------------------------------------------------ Tests
static void testBiquadResponse ()
{
	for (double sr : {44100.0, 48000.0, 96000.0})
	{
		auto c = BiquadCoeffs::make (FilterType::Bell, 1000, sr, 6.0, 1.0);
		CHECK (std::fabs (c.magnitudeDb (1000, sr) - 6.0) < 0.01, "Bell-Gain bei %.0f Hz: %.3f", sr, c.magnitudeDb (1000, sr));
		auto hp = BiquadCoeffs::make (FilterType::HighPass, 100, sr, 0, 0.7071);
		CHECK (std::fabs (hp.magnitudeDb (100, sr) + 3.01) < 0.05, "HPF -3 dB: %.3f", hp.magnitudeDb (100, sr));
		CHECK (hp.magnitudeDb (10000, sr) > -0.01, "HPF Durchlass");
		// Gemessene Antwort (Sinus durch SmoothedBand) == analytische Antwort
		SmoothedBand band;
		band.set (FilterType::Bell, 1000, 6.0, 1.0);
		band.prepare (sr);
		for (double f : {200.0, 1000.0, 3000.0})
		{
			auto b = sine (2, int (sr), f, 0.1, sr);
			const double inDb = rmsDb (b[0], size_t (sr / 2), size_t (sr));
			auto p = ptrs (b);
			band.processBlock (p.data (), 2, int (sr));
			const double outDb = rmsDb (b[0], size_t (sr / 2), size_t (sr));
			const double expect = BiquadCoeffs::make (FilterType::Bell, 1000, sr, 6.0, 1.0).magnitudeDb (f, sr);
			CHECK (std::fabs ((outDb - inDb) - expect) < 0.05, "sr %.0f f %.0f: gemessen %.3f erwartet %.3f", sr, f, outDb - inDb, expect);
		}
	}
}

static void testCompressorCurve ()
{
	CHECK (compressorGainReduction (-30, -20, 4, 0) == 0.0, "unter Schwelle");
	CHECK (std::fabs (compressorGainReduction (-10, -20, 4, 0) - 7.5) < 1e-9, "10 dB über Schwelle bei 4:1");
	CHECK (std::fabs (compressorGainReduction (-20, -20, 4, 6) - 0.75 * 9.0 / 12.0) < 1e-9, "Knie-Mitte");
	// Dynamisch: Rechteck-Hüllkurve (konstanter Peak) -> GR konvergiert gegen Kennlinie
	const double sr = 48000;
	Compressor c;
	c.setParams ({-20, 4, 1, 50, 0, 0, 1});
	c.prepare (sr);
	auto b = make (1, int (sr), 0.5f); // -6.02 dBFS konstant
	auto p = ptrs (b);
	c.processBlock (p.data (), 1, int (sr));
	const double expectGr = 0.75 * (linToDb (0.5) + 20);
	CHECK (std::fabs (c.currentGr () - expectGr) < 0.05, "GR %.3f erwartet %.3f", c.currentGr (), expectGr);
	CHECK (std::fabs (linToDb (b[0].back ()) - (linToDb (0.5) - expectGr)) < 0.05, "Ausgangspegel");
}

// Bandbegrenztes, musikähnliches Testsignal (Kick, Snare, verzerrte Gitarre, Rauschen, Tiefpass 9 kHz)
static Buf musicLike (double sr, double seconds, unsigned seed)
{
	std::mt19937 rng (seed);
	std::normal_distribution<double> nd (0, 0.1);
	const int n = int (sr * seconds);
	auto b = make (2, n);
	Biquad lp1, lp2;
	lp1.setCoeffs (BiquadCoeffs::make (FilterType::LowPass, 9000, sr, 0, 0.7071));
	lp2.setCoeffs (BiquadCoeffs::make (FilterType::LowPass, 9000, sr, 0, 0.7071));
	for (int i = 0; i < n; ++i)
	{
		const double t = i / sr, tk = std::fmod (t, 0.5), ts = std::fmod (t + 0.25, 0.5);
		const double kick = tk < 0.08 ? 0.8 * std::sin (2 * kPi * 55 * t) * std::exp (-tk * 30) : 0;
		const double snare = ts < 0.05 ? nd (rng) * 3 * std::exp (-ts * 40) : 0;
		const double gtr = std::tanh (3 * std::sin (2 * kPi * 110 * t) + 2 * std::sin (2 * kPi * 164.8 * t)) * 0.25;
		const double x = kick + snare + gtr + nd (rng) * 0.05;
		b[0][size_t (i)] = float (lp2.process (lp1.process (x, 0), 0));
		b[1][size_t (i)] = float (lp2.process (lp1.process (x * 0.9 + nd (rng) * 0.05, 1), 1));
	}
	return b;
}

// Breitbandiges Rauschen mit +14 dB Drive: Extremfall mit viel Energie nahe Nyquist
static Buf noiseStress (double sr, double seconds)
{
	std::mt19937 rng (7);
	std::normal_distribution<double> nd (0, 0.15);
	const int n = int (sr * seconds);
	auto b = make (2, n);
	double lp = 0;
	for (int i = 0; i < n; ++i)
	{
		lp = 0.6 * lp + nd (rng);
		const double burst = (i / int (sr * 0.25)) % 2 ? 1.0 : 0.3;
		b[0][size_t (i)] = float (lp * burst);
		b[1][size_t (i)] = float (-lp * burst * 0.9 + nd (rng) * 0.05);
	}
	return b;
}

static void testLimiterTruePeak ()
{
	struct Case
	{
		const char* name;
		double driveDb, tolerance;
		bool stress;
	};
	// Toleranzen: realistisches Material streng; Rausch-Extremfall mit dokumentierter Restabweichung
	// der 4x-Detektion (BS.1770-Verfahren) gegenüber der 16x-Referenz.
	for (const Case& k : {Case {"musikähnlich", 10.0, 0.1, false}, Case {"Rausch-Extremfall", 14.0, 0.7, true}})
		for (double sr : {44100.0, 48000.0})
		{
			MasterStrip m;
			m.setParam (params::master::kLimiterGainDb, k.driveDb);
			m.setParam (params::master::kCeilingDbtp, -1.0);
			m.prepare (sr);
			auto b = k.stress ? noiseStress (sr, 4) : musicLike (sr, 6, 3);
			runStrip (m, b, 333);
			const double tp = std::max (linToDb (referenceTruePeak (b[0])), linToDb (referenceTruePeak (b[1])));
			std::printf ("  Limiter %s sr=%.0f: Referenz-True-Peak (16x) %.3f dBTP bei Ceiling -1.0\n", k.name, sr, tp);
			CHECK (tp <= -1.0 + k.tolerance, "True Peak %.3f dBTP über Ceiling+%.2f", tp, k.tolerance);
			float sp = 0;
			for (auto& c : b)
				for (float v : c)
					sp = std::max (sp, std::fabs (v));
			CHECK (linToDb (sp) <= -1.0 + 1e-4, "Sample-Peak %.4f", linToDb (sp));
		}
}

static void testLatencyAndBypass ()
{
	const double sr = 48000;
	auto impulseDelay = [] (auto& strip, int nch) {
		auto b = make (nch, 4096);
		for (auto& c : b)
			c[100] = 0.5f;
		runStrip (strip, b, 128);
		int best = -1;
		float bv = 0;
		for (int i = 0; i < 4096; ++i)
			if (std::fabs (b[0][size_t (i)]) > bv)
			{
				bv = std::fabs (b[0][size_t (i)]);
				best = i;
			}
		return best - 100;
	};
	{
		ChannelStrip s;
		s.prepare (sr);
		CHECK (impulseDelay (s, 2) == ChannelStrip::latencySamples (), "Channel-Latenz %d", impulseDelay (s, 2));
	}
	{
		BusStrip s;
		s.prepare (sr);
		CHECK (impulseDelay (s, 2) == BusStrip::latencySamples (), "Bus-Latenz");
	}
	{
		MasterStrip s;
		s.setParam (params::master::kLimiterOn, 0);
		s.prepare (sr);
		const int d = impulseDelay (s, 2);
		CHECK (d == s.latencySamples (), "Master-Latenz %d gemeldet %d", d, s.latencySamples ());
	}
	// Bypass: Ausgang == um Latenz verzögerter Eingang
	{
		ChannelStrip s;
		s.setParam (params::channel::kTrimDb, 12);
		s.setParam (params::channel::kBypass, 1);
		s.prepare (sr);
		auto b = sine (2, 8192, 440, 0.3, sr);
		auto ref = b;
		runStrip (s, b);
		const int L = ChannelStrip::latencySamples ();
		double err = 0;
		for (int i = L + 2000; i < 8192; ++i)
			err = std::max (err, double (std::fabs (b[0][size_t (i)] - ref[0][size_t (i - L)])));
		CHECK (err < 1e-6, "Bypass-Abweichung %.3g", err);
	}
}

static void testGainAccuracyAndSmoothing ()
{
	const double sr = 48000;
	ChannelStrip s;
	s.setParam (params::channel::kTrimDb, 6.0);
	s.setParam (params::channel::kOutputDb, -3.0);
	s.prepare (sr);
	auto b = sine (2, 24000, 1000, 0.1, sr);
	const double in = rmsDb (b[0], 4000, 24000);
	runStrip (s, b);
	CHECK (std::fabs (rmsDb (b[0], 4000, 24000) - in - 3.0) < 0.02, "Gain %.3f dB", rmsDb (b[0], 4000, 24000) - in);
	// Sprungantwort: Output -20 dB bei laufendem Signal -> keine Sprünge (max. Änderung je Sample begrenzt)
	ChannelStrip t;
	t.prepare (sr);
	auto d = make (2, 9600, 0.5f);
	auto p1 = ptrs (d);
	t.process (p1.data (), 2, 4800);
	t.setParam (params::channel::kOutputDb, -20.0);
	float* p2[2] = {d[0].data () + 4800, d[1].data () + 4800};
	t.process (p2, 2, 4800);
	double maxStep = 0;
	for (int i = 4801; i < 9600; ++i)
		maxStep = std::max (maxStep, double (std::fabs (d[0][size_t (i)] - d[0][size_t (i - 1)])));
	CHECK (maxStep < 0.5 * 0.9 / 960 * 1.5, "Sprung je Sample %.5f", maxStep);
	CHECK (std::fabs (d[0].back () - 0.05f) < 1e-3, "Endwert %.4f", d[0].back ());
	// EQ-Frequenzsprung: keine Ausreißer
	ChannelStrip e;
	e.setParam (params::channel::kEq1Type, 1);
	e.setParam (params::channel::kEq1GainDb, 12);
	e.setParam (params::channel::kEq1Freq, 200);
	e.prepare (sr);
	auto x = sine (2, 48000, 500, 0.2, sr);
	float* q1[2] = {x[0].data (), x[1].data ()};
	e.process (q1, 2, 24000);
	e.setParam (params::channel::kEq1Freq, 5000);
	float* q2[2] = {x[0].data () + 24000, x[1].data () + 24000};
	e.process (q2, 2, 24000);
	float mx = 0;
	for (float v : x[0])
		mx = std::max (mx, std::fabs (v));
	CHECK (mx < 1.0f, "EQ-Sweep Peak %.3f", mx);
}

static void testNaNProtection ()
{
	const double sr = 48000;
	ChannelStrip s;
	s.setParam (params::channel::kCompOn, 1);
	s.setParam (params::channel::kEq1Type, 1);
	s.setParam (params::channel::kEq1GainDb, 6);
	s.setParam (params::channel::kGateOn, 1);
	s.setParam (params::channel::kDeessOn, 1);
	s.setParam (params::channel::kSatDriveDb, 6);
	s.setParam (params::channel::kTrimDb, std::nan ("")); // wird ignoriert
	s.prepare (sr);
	auto b = sine (2, 4800, 300, 0.5, sr);
	b[0][100] = std::numeric_limits<float>::quiet_NaN ();
	b[1][200] = std::numeric_limits<float>::infinity ();
	b[0][300] = -std::numeric_limits<float>::infinity ();
	runStrip (s, b);
	auto c = sine (2, 48000, 300, 0.5, sr);
	runStrip (s, c);
	bool finite = true;
	for (auto* buf : {&b, &c})
		for (auto& ch : *buf)
			for (float v : ch)
				finite = finite && std::isfinite (v);
	CHECK (finite, "NaN/Inf im Ausgang");
	CHECK (rmsDb (c[0], 24000, 48000) > -40, "Signal nach NaN wiederhergestellt: %.1f dB", rmsDb (c[0], 24000, 48000));
	MasterStrip m;
	m.prepare (sr);
	auto d = make (2, 4800, std::numeric_limits<float>::quiet_NaN ());
	runStrip (m, d);
	bool ok = true;
	for (auto& ch : d)
		for (float v : ch)
			ok = ok && std::isfinite (v);
	CHECK (ok, "Master NaN");
}

static void testSilenceAndMonoStereo ()
{
	const double sr = 44100;
	ChannelStrip s;
	s.setParam (params::channel::kCompOn, 1);
	s.setParam (params::channel::kSatDriveDb, 3);
	s.prepare (sr);
	auto z = make (1, 44100);
	runStrip (s, z);
	float mx = 0;
	for (float v : z[0])
		mx = std::max (mx, std::fabs (v));
	CHECK (mx == 0.f, "Stille mono -> %.3g", mx);
	// Stereo mit identischen Kanälen, Mitte, Breite 1 -> L == R
	ChannelStrip t;
	t.setParam (params::channel::kEq2Type, 2);
	t.setParam (params::channel::kEq2GainDb, 3);
	t.prepare (sr);
	auto b = sine (2, 20000, 220, 0.3, sr);
	runStrip (t, b);
	double d = 0;
	for (int i = 0; i < 20000; ++i)
		d = std::max (d, double (std::fabs (b[0][size_t (i)] - b[1][size_t (i)])));
	CHECK (d < 1e-6, "L != R: %.3g", d);
	// Breite 0 -> Mono
	ChannelStrip w;
	w.setParam (params::channel::kWidth, 0);
	w.prepare (sr);
	auto c = sine (2, 20000, 220, 0.3, sr);
	for (auto& v : c[1])
		v *= -0.5f;
	runStrip (w, c);
	d = 0;
	for (int i = 2000; i < 20000; ++i)
		d = std::max (d, double (std::fabs (c[0][size_t (i)] - c[1][size_t (i)])));
	CHECK (d < 1e-6, "Breite 0: L-R %.3g", d);
	// Pan hart links -> rechts stumm
	ChannelStrip p;
	p.setParam (params::channel::kPan, -1);
	p.prepare (sr);
	auto e = sine (2, 20000, 220, 0.3, sr);
	runStrip (p, e);
	CHECK (rmsDb (e[1], 4000, 20000) < -100, "Pan links: rechts %.1f dB", rmsDb (e[1], 4000, 20000));
}

static void testSampleRateChange ()
{
	ChannelStrip s;
	s.setParam (params::channel::kEq1Type, 1);
	s.setParam (params::channel::kEq1GainDb, -6);
	s.setParam (params::channel::kEq1Freq, 2000);
	s.setParam (params::channel::kEq1Q, 1.0);
	for (double sr : {44100.0, 96000.0, 48000.0})
	{
		s.prepare (sr);
		auto b = sine (2, int (sr), 2000, 0.1, sr);
		const double in = rmsDb (b[0], size_t (sr / 2), size_t (sr));
		runStrip (s, b);
		const double g = rmsDb (b[0], size_t (sr / 2), size_t (sr)) - in;
		CHECK (std::fabs (g + 6.0) < 0.1, "sr %.0f: EQ %.3f dB", sr, g);
	}
}

static void testSaturatorAlignment ()
{
	// Kleine Drive-Werte mit 50 % Mix dürfen keinen Kammfilter erzeugen (Dry phasengleich verzögert)
	const double sr = 48000;
	ChannelStrip s;
	s.setParam (params::channel::kSatDriveDb, 0.5);
	s.setParam (params::channel::kSatMix, 0.5);
	s.prepare (sr);
	// Kleinsignal: tanh(x*d)/tanh(d) ~ x*d/tanh(d) (pegelkompensiert auf Vollaussteuerung wie engine/dsp.py)
	const double d = dbToLin (0.5);
	const double expect = linToDb (0.5 * d / std::tanh (d) + 0.5);
	for (double f : {1000.0, 8000.0, 15000.0})
	{
		auto b = sine (2, 24000, f, 0.01, sr);
		const double in = rmsDb (b[0], 4000, 24000);
		runStrip (s, b);
		const double g = rmsDb (b[0], 4000, 24000) - in;
		CHECK (std::fabs (g - expect) < 0.05, "Sättigung %0.f Hz: %.3f dB, erwartet %.3f (Kammfilter?)", f, g, expect);
	}
}

static void testLoudnessMeter ()
{
	// EBU Tech 3341: 1-kHz-Stereo-Sinus mit -23 dBFS je Kanal -> -23,0 LUFS (M und S)
	for (double sr : {44100.0, 48000.0})
	{
		LoudnessMeter m;
		m.prepare (sr);
		auto b = sine (2, int (sr * 4), 1000, dbToLin (-23.0), sr);
		const float* p[2] = {b[0].data (), b[1].data ()};
		m.processBlock (p, 2, int (sr * 4));
		CHECK (std::fabs (m.momentaryLufs () + 23.0) < 0.1, "M %.3f", m.momentaryLufs ());
		CHECK (std::fabs (m.shortTermLufs () + 23.0) < 0.1, "S %.3f", m.shortTermLufs ());
	}
}

static void testDynamicsUnits ()
{
	const double sr = 48000;
	// Gate schließt bei Stille unter Schwelle um range dB
	Gate g;
	g.setParams ({-40, 30, 0.5, 10, 20});
	g.prepare (sr);
	auto b = make (1, 48000, 0.001f); // -60 dBFS
	auto p = ptrs (b);
	g.processBlock (p.data (), 1, 48000);
	CHECK (std::fabs (linToDb (b[0].back ()) - (-60 - 30)) < 0.2, "Gate %.2f", linToDb (b[0].back ()));
	// De-Esser: tiefe Frequenzen unverändert, hohe abgesenkt
	DeEsser d;
	d.setParams ({5000, -40, 10});
	d.prepare (sr);
	auto lo = sine (1, 48000, 200, 0.3, sr);
	const double loIn = rmsDb (lo[0], 24000, 48000);
	auto pl = ptrs (lo);
	d.processBlock (pl.data (), 1, 48000);
	CHECK (std::fabs (rmsDb (lo[0], 24000, 48000) - loIn) < 0.3, "De-Esser Tiefen %.2f", rmsDb (lo[0], 24000, 48000) - loIn);
	DeEsser d2;
	d2.setParams ({5000, -40, 10});
	d2.prepare (sr);
	auto hi = sine (1, 48000, 9000, 0.3, sr);
	const double hiIn = rmsDb (hi[0], 24000, 48000);
	auto ph = ptrs (hi);
	d2.processBlock (ph.data (), 1, 48000);
	CHECK (rmsDb (hi[0], 24000, 48000) - hiIn < -5, "De-Esser Höhen %.2f", rmsDb (hi[0], 24000, 48000) - hiIn);
	// Dynamisches Band mit Sidechain: nur bei aktivem Sidechain wird abgesenkt
	for (bool scActive : {false, true})
	{
		DynamicBand db;
		db.setParams ({true, 2000, 1.4, -40, 6});
		db.prepare (sr);
		auto x = sine (1, 48000, 2000, 0.1, sr);
		auto sc = sine (1, 48000, 2000, scActive ? 0.5 : 0.0, sr);
		const double in = rmsDb (x[0], 24000, 48000);
		auto px = ptrs (x);
		auto ps = ptrs (sc);
		db.processBlock (px.data (), 1, 48000, ps.data (), 1);
		const double gdb = rmsDb (x[0], 24000, 48000) - in;
		if (scActive)
			CHECK (gdb < -4.0 && gdb > -6.5, "Dyn-Band mit Sidechain %.2f", gdb);
		else
			CHECK (std::fabs (gdb) < 0.1, "Dyn-Band ohne Sidechain %.2f", gdb);
	}
}

static void testStateRoundtrip ()
{
	std::vector<state::Entry> e {{1, -3.5}, {20, 1}, {21, 1234.5}, {92, 1.25}};
	auto bytes = state::encode (e, "Vox Lead");
	std::vector<state::Entry> out;
	std::string label;
	CHECK (state::decode (bytes.data (), bytes.size (), out, label), "decode");
	CHECK (out.size () == 4 && out[2].id == 21 && out[2].value == 1234.5 && label == "Vox Lead", "Inhalt");
	CHECK (!state::decode (bytes.data (), bytes.size () - 3, out, label), "abgeschnitten erkannt");
	bytes[0] = 'X';
	CHECK (!state::decode (bytes.data (), bytes.size (), out, label), "Magic erkannt");
	// Normalisierung: Hin- und Rückweg
	for (int i = 0; i < params::channel::kCount; ++i)
	{
		const auto& p = params::channel::kParams[i];
		const double v = p.def;
		const double back = params::fromNormalized (p, params::toNormalized (p, v));
		CHECK (std::fabs (back - v) < 1e-9 * std::max (1.0, std::fabs (v)), "%s: %.6f -> %.6f", p.key, v, back);
	}
}

static void testNoAllocationAndCpu ()
{
	const double sr = 48000;
	ChannelStrip s;
	BusStrip b;
	MasterStrip m;
	using namespace params;
	for (auto id : {channel::kCompOn, channel::kGateOn, channel::kDeessOn, channel::kDyn1On, channel::kDyn2On, channel::kDcRemove,
	                channel::kHpfSteep})
		s.setParam (id, 1);
	for (int k = 0; k < 8; ++k)
	{
		s.setParam (channel::kEq1Type + uint32_t (k) * 4, 1);
		s.setParam (channel::kEq1GainDb + uint32_t (k) * 4, 2);
	}
	s.setParam (channel::kHpfFreq, 80);
	s.setParam (channel::kLpfFreq, 15000);
	s.setParam (channel::kSatDriveDb, 4);
	s.setParam (channel::kAlignDelayMs, 3);
	b.setParam (bus::kCompOn, 1);
	b.setParam (bus::kParAmount, 0.3);
	b.setParam (bus::kSatDriveDb, 2);
	m.setParam (master::kCompOn, 1);
	m.setParam (master::kEq1Type, 2);
	m.setParam (master::kEq1GainDb, 1);
	m.setParam (master::kLimiterGainDb, 6);
	s.prepare (sr);
	b.prepare (sr);
	m.prepare (sr);
	const int block = 256, seconds = 10, n = int (sr) * seconds;
	auto x = sine (2, block, 110, 0.4, sr);
	auto sc = sine (2, block, 2000, 0.2, sr);
	float* p[2] = {x[0].data (), x[1].data ()};
	float* q[2] = {sc[0].data (), sc[1].data ()};
	gAllocs = 0;
	gCount = true;
	double tCh = 0, tBus = 0, tMa = 0;
	for (int o = 0; o < n; o += block)
	{
		if (o == n / 2)
			s.setParam (channel::kEq3Freq, 3000); // Automation während des Laufs
		auto t0 = std::chrono::steady_clock::now ();
		s.process (p, 2, block, q, 2);
		auto t1 = std::chrono::steady_clock::now ();
		b.process (p, 2, block);
		auto t2 = std::chrono::steady_clock::now ();
		m.process (p, 2, block);
		auto t3 = std::chrono::steady_clock::now ();
		tCh += std::chrono::duration<double> (t1 - t0).count ();
		tBus += std::chrono::duration<double> (t2 - t1).count ();
		tMa += std::chrono::duration<double> (t3 - t2).count ();
	}
	gCount = false;
	CHECK (gAllocs.load () == 0, "%ld Allokationen in process()", gAllocs.load ());
	std::printf ("  CPU (10 s Stereo 48 kHz, Block 256, alle Module aktiv):\n");
	std::printf ("    Channel %.3f s (%.2f %% Echtzeit), Bus %.3f s (%.2f %%), Master %.3f s (%.2f %%)\n", tCh, 100 * tCh / seconds,
	             tBus, 100 * tBus / seconds, tMa, 100 * tMa / seconds);
	std::printf ("  Latenz: Channel %d, Bus %d, Master %d Samples\n", ChannelStrip::latencySamples (), BusStrip::latencySamples (),
	             m.latencySamples ());
	CHECK (tCh < seconds * 0.5, "Channel langsamer als halbe Echtzeit");
}

int main ()
{
	const std::pair<const char*, std::function<void ()>> tests[] = {
	    {"Biquad-Frequenzgang", testBiquadResponse},
	    {"Kompressor-Kennlinie", testCompressorCurve},
	    {"Gate/De-Esser/Dyn-Band", testDynamicsUnits},
	    {"Limiter True Peak", testLimiterTruePeak},
	    {"Latenz und Bypass", testLatencyAndBypass},
	    {"Gain-Genauigkeit und Glättung", testGainAccuracyAndSmoothing},
	    {"NaN/Inf-Schutz", testNaNProtection},
	    {"Stille, Mono, Stereo, Pan", testSilenceAndMonoStereo},
	    {"Samplerate-Wechsel", testSampleRateChange},
	    {"Sättigung phasengleich", testSaturatorAlignment},
	    {"Lautheitsmessung EBU", testLoudnessMeter},
	    {"Zustand und Normalisierung", testStateRoundtrip},
	    {"Keine Allokation, CPU", testNoAllocationAndCpu},
	};
	for (auto& [name, fn] : tests)
	{
		const int before = gFailed;
		std::printf ("[ RUN ] %s\n", name);
		fn ();
		std::printf ("[%s] %s\n", gFailed == before ? "  OK " : "FAIL ", name);
	}
	std::printf ("\n%d Prüfungen, %d fehlgeschlagen\n", gChecks, gFailed);
	return gFailed == 0 ? 0 : 1;
}
