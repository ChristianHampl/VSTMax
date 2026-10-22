// AI Mix Engineer - DSP-Kern (header-only, C++17)
//
// Regeln für alle Klassen:
//  - prepare() darf Speicher anfordern, process*() niemals.
//  - Alle Ausgänge werden gegen NaN/Inf geschützt (sanitize).
//  - Parameteränderungen werden geglättet (keine hörbaren Sprünge).
#pragma once

#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace aime {

constexpr double kPi = 3.14159265358979323846;

inline double dbToLin (double db) { return std::pow (10.0, db / 20.0); }
inline double linToDb (double x, double floorDb = -150.0)
{
	const double a = std::fabs (x);
	return a > 1e-20 ? std::max (20.0 * std::log10 (a), floorDb) : floorDb;
}
inline float sanitize (float x)
{
	if (!std::isfinite (x))
		return 0.f;
	if (std::fabs (x) < 1e-30f) // Denormale vermeiden
		return 0.f;
	return x;
}
inline double timeCoef (double ms, double sr)
{
	ms = std::max (ms, 0.01);
	return std::exp (-1.0 / (ms * 0.001 * sr));
}

//------------------------------------------------------------------------
// Lineare Parameter-Glättung (Rampe über eine feste Zeit)
class LinearSmoother
{
public:
	void prepare (double sr, double rampMs = 20.0)
	{
		steps = std::max (1, int (sr * rampMs * 0.001));
		current = target;
		remaining = 0;
	}
	void setTarget (double t)
	{
		if (t == target)
			return;
		target = t;
		inc = (target - current) / steps;
		remaining = steps;
	}
	void reset (double v) { current = target = v; remaining = 0; }
	double next ()
	{
		if (remaining > 0)
		{
			current += inc;
			if (--remaining == 0)
				current = target;
		}
		return current;
	}
	bool isSmoothing () const { return remaining > 0; }
	double value () const { return current; }
	double targetValue () const { return target; }

private:
	double current = 0.0, target = 0.0, inc = 0.0;
	int steps = 1, remaining = 0;
};

//------------------------------------------------------------------------
// Biquad (RBJ Audio EQ Cookbook), Transposed Direct Form II, bis 2 Kanäle
enum class FilterType { Off = 0, Bell = 1, LowShelf = 2, HighShelf = 3, HighPass = 4, LowPass = 5, BandPass = 6 };

struct BiquadCoeffs
{
	double b0 = 1, b1 = 0, b2 = 0, a1 = 0, a2 = 0;

	static BiquadCoeffs make (FilterType type, double freq, double sr, double gainDb, double q)
	{
		BiquadCoeffs c;
		if (type == FilterType::Off || sr <= 0)
			return c;
		freq = std::clamp (freq, 10.0, 0.49 * sr);
		q = std::max (q, 0.05);
		const double A = std::pow (10.0, gainDb / 40.0);
		const double w0 = 2.0 * kPi * freq / sr;
		const double cw = std::cos (w0), sw = std::sin (w0);
		const double alpha = sw / (2.0 * q);
		double b0, b1, b2, a0, a1, a2;
		switch (type)
		{
			case FilterType::Bell:
				b0 = 1 + alpha * A; b1 = -2 * cw; b2 = 1 - alpha * A;
				a0 = 1 + alpha / A; a1 = -2 * cw; a2 = 1 - alpha / A;
				break;
			case FilterType::LowShelf:
			{
				const double sq = 2 * std::sqrt (A) * alpha;
				b0 = A * ((A + 1) - (A - 1) * cw + sq); b1 = 2 * A * ((A - 1) - (A + 1) * cw);
				b2 = A * ((A + 1) - (A - 1) * cw - sq); a0 = (A + 1) + (A - 1) * cw + sq;
				a1 = -2 * ((A - 1) + (A + 1) * cw); a2 = (A + 1) + (A - 1) * cw - sq;
				break;
			}
			case FilterType::HighShelf:
			{
				const double sq = 2 * std::sqrt (A) * alpha;
				b0 = A * ((A + 1) + (A - 1) * cw + sq); b1 = -2 * A * ((A - 1) + (A + 1) * cw);
				b2 = A * ((A + 1) + (A - 1) * cw - sq); a0 = (A + 1) - (A - 1) * cw + sq;
				a1 = 2 * ((A - 1) - (A + 1) * cw); a2 = (A + 1) - (A - 1) * cw - sq;
				break;
			}
			case FilterType::HighPass:
				b0 = (1 + cw) / 2; b1 = -(1 + cw); b2 = (1 + cw) / 2;
				a0 = 1 + alpha; a1 = -2 * cw; a2 = 1 - alpha;
				break;
			case FilterType::LowPass:
				b0 = (1 - cw) / 2; b1 = 1 - cw; b2 = (1 - cw) / 2;
				a0 = 1 + alpha; a1 = -2 * cw; a2 = 1 - alpha;
				break;
			case FilterType::BandPass:
				b0 = alpha; b1 = 0; b2 = -alpha;
				a0 = 1 + alpha; a1 = -2 * cw; a2 = 1 - alpha;
				break;
			default: return c;
		}
		c.b0 = b0 / a0; c.b1 = b1 / a0; c.b2 = b2 / a0; c.a1 = a1 / a0; c.a2 = a2 / a0;
		return c;
	}

	double magnitudeDb (double freq, double sr) const
	{
		const double w = 2 * kPi * freq / sr;
		const double cr1 = std::cos (w), ci1 = -std::sin (w);
		const double cr2 = std::cos (2 * w), ci2 = -std::sin (2 * w);
		const double nr = b0 + b1 * cr1 + b2 * cr2, ni = b1 * ci1 + b2 * ci2;
		const double dr = 1 + a1 * cr1 + a2 * cr2, di = a1 * ci1 + a2 * ci2;
		return 10 * std::log10 ((nr * nr + ni * ni) / std::max (dr * dr + di * di, 1e-30));
	}
};

class Biquad
{
public:
	void setCoeffs (const BiquadCoeffs& c) { k = c; }
	void reset () { z1.fill (0); z2.fill (0); }
	inline double process (double x, int ch)
	{
		const double y = k.b0 * x + z1[ch];
		z1[ch] = k.b1 * x - k.a1 * y + z2[ch];
		z2[ch] = k.b2 * x - k.a2 * y;
		if (!std::isfinite (y))
		{
			z1[ch] = z2[ch] = 0;
			return 0;
		}
		return y;
	}
	const BiquadCoeffs& coeffs () const { return k; }

private:
	BiquadCoeffs k;
	std::array<double, 2> z1 {}, z2 {};
};

//------------------------------------------------------------------------
// Glättender EQ-Bandfilter: Frequenz/Gain/Q werden über 32-Sample-Blöcke
// angenähert und die Koeffizienten neu berechnet (keine Zipper-Geräusche).
class SmoothedBand
{
public:
	void prepare (double sampleRate)
	{
		sr = sampleRate;
		gain.prepare (sr, 30.0);
		logFreq.prepare (sr, 30.0);
		q.prepare (sr, 30.0);
		gain.reset (tGain);
		logFreq.reset (std::log (tFreq));
		q.reset (tQ);
		update ();
		filter.reset ();
	}
	void set (FilterType t, double f, double g, double qq)
	{
		if (t != type)
		{
			type = t;
			filter.reset ();
		}
		tFreq = f; tGain = g; tQ = qq;
		gain.setTarget (g);
		logFreq.setTarget (std::log (std::max (f, 1.0)));
		q.setTarget (qq);
		pending = true;
	}
	// Springt ohne Glättung auf die Zielwerte (z. B. beim Laden eines Zustands vor der Wiedergabe)
	void snap ()
	{
		gain.reset (tGain);
		logFreq.reset (std::log (std::max (tFreq, 1.0)));
		q.reset (tQ);
		update ();
		pending = false;
	}
	inline void processBlock (float** ch, int nch, int n)
	{
		if (type == FilterType::Off)
			return;
		for (int i = 0; i < n; ++i)
		{
			if ((counter++ & 31) == 0 && pending)
			{
				// Nach Ende der Rampe noch einmal exakt auf den Zielwert rechnen
				pending = gain.isSmoothing () || logFreq.isSmoothing () || q.isSmoothing ();
				update ();
			}
			gain.next (); logFreq.next (); q.next ();
			for (int c = 0; c < nch; ++c)
				ch[c][i] = float (filter.process (ch[c][i], c));
		}
	}
	FilterType filterType () const { return type; }
	const BiquadCoeffs& coeffs () const { return filter.coeffs (); }

private:
	void update ()
	{
		filter.setCoeffs (BiquadCoeffs::make (type, std::exp (logFreq.value ()), sr, gain.value (), q.value ()));
	}
	Biquad filter;
	FilterType type = FilterType::Off;
	double sr = 48000, tFreq = 1000, tGain = 0, tQ = 0.7071;
	LinearSmoother gain, logFreq, q;
	uint32_t counter = 0;
	bool pending = false;
};

//------------------------------------------------------------------------
// Pegeldetektoren über ein Fenster von kEnvWindow Samples. Entspricht der blockweisen
// Erkennung der Offline-Engine (engine/dsp.py: ENV_BLOCK, block_peak, block_rms).
constexpr int kEnvWindow = 32;

class SlidingMax
{
public:
	void reset () { buf.fill (0); pos = 0; cur = 0; age = 0; }
	inline double push (double v)
	{
		buf[size_t (pos)] = v;
		pos = (pos + 1) % kEnvWindow;
		if (v >= cur)
		{
			cur = v;
			age = 0;
		}
		else if (++age >= kEnvWindow)
		{
			cur = 0;
			for (int k = 0; k < kEnvWindow; ++k)
			{
				const int idx = (pos - 1 - k + 2 * kEnvWindow) % kEnvWindow;
				if (buf[size_t (idx)] > cur)
				{
					cur = buf[size_t (idx)];
					age = k;
				}
			}
		}
		return cur;
	}

private:
	std::array<double, kEnvWindow> buf {};
	int pos = 0, age = 0;
	double cur = 0;
};

class SlidingMean
{
public:
	void reset () { buf.fill (0); pos = 0; sum = 0; count = 0; }
	inline double push (double v)
	{
		sum += v - buf[size_t (pos)];
		buf[size_t (pos)] = v;
		pos = (pos + 1) % kEnvWindow;
		if (++count >= 4096) // Rundungsdrift begrenzen
		{
			count = 0;
			sum = 0;
			for (double b : buf)
				sum += b;
		}
		return std::max (sum, 0.0) / kEnvWindow;
	}

private:
	std::array<double, kEnvWindow> buf {};
	int pos = 0, count = 0;
	double sum = 0;
};

//------------------------------------------------------------------------
// Statische Kompressor-Kennlinie (Gain Reduction in dB >= 0)
inline double compressorGainReduction (double levelDb, double thrDb, double ratio, double kneeDb)
{
	ratio = std::max (ratio, 1.0);
	const double slope = 1.0 - 1.0 / ratio;
	const double over = levelDb - thrDb;
	if (kneeDb > 0.0)
	{
		const double half = kneeDb * 0.5;
		if (over <= -half)
			return 0.0;
		if (over < half)
			return slope * (over + half) * (over + half) / (2.0 * kneeDb);
		return slope * over;
	}
	return over > 0 ? slope * over : 0.0;
}

//------------------------------------------------------------------------
// Feed-forward-Kompressor mit Peak-Detektor (Max über Kanäle), Soft-Knee,
// Attack/Release auf der Gain Reduction, Makeup und Dry/Wet.
class Compressor
{
public:
	struct Params { double thresholdDb = -20, ratio = 4, attackMs = 10, releaseMs = 100, kneeDb = 6, makeupDb = 0, mix = 1; };

	void prepare (double sampleRate)
	{
		sr = sampleRate;
		gr = 0;
		peak.reset ();
		makeup.prepare (sr, 20.0);
		mix.prepare (sr, 20.0);
		makeup.reset (dbToLin (p.makeupDb));
		mix.reset (p.mix);
		setParams (p);
	}
	void setParams (const Params& np)
	{
		p = np;
		att = timeCoef (p.attackMs, sr);
		rel = timeCoef (p.releaseMs, sr);
		makeup.setTarget (dbToLin (p.makeupDb));
		mix.setTarget (std::clamp (p.mix, 0.0, 1.0));
	}
	// Liefert die Gain Reduction (dB) für einen Detektorwert
	inline double computeGr (double detector)
	{
		const double target = compressorGainReduction (linToDb (detector), p.thresholdDb, p.ratio, p.kneeDb);
		const double c = target > gr ? att : rel;
		gr = target + c * (gr - target);
		return gr;
	}
	inline void processBlock (float** ch, int nch, int n, float** sidechain = nullptr, int scCh = 0)
	{
		for (int i = 0; i < n; ++i)
		{
			double det = 0;
			if (sidechain)
				for (int c = 0; c < scCh; ++c)
					det = std::max (det, double (std::fabs (sidechain[c][i])));
			else
				for (int c = 0; c < nch; ++c)
					det = std::max (det, double (std::fabs (ch[c][i])));
			const double g = dbToLin (-computeGr (peak.push (det))) * makeup.next ();
			const double m = mix.next ();
			for (int c = 0; c < nch; ++c)
			{
				const double x = ch[c][i];
				ch[c][i] = sanitize (float (m * x * g + (1 - m) * x));
			}
			maxGr = std::max (maxGr, gr);
		}
	}
	double currentGr () const { return gr; }
	double takeMaxGr () { double m = maxGr; maxGr = 0; return m; }
	void reset () { gr = 0; peak.reset (); }

private:
	Params p;
	double sr = 48000, att = 0, rel = 0, gr = 0, maxGr = 0;
	SlidingMax peak;
	LinearSmoother makeup, mix;
};

//------------------------------------------------------------------------
// Gate/Expander mit Hold
class Gate
{
public:
	struct Params { double thresholdDb = -60, rangeDb = 40, attackMs = 0.5, holdMs = 40, releaseMs = 100; };
	void prepare (double sampleRate) { sr = sampleRate; grDb = p.rangeDb; holdCount = 0; peak.reset (); setParams (p); }
	void setParams (const Params& np)
	{
		p = np;
		att = timeCoef (p.attackMs, sr);
		rel = timeCoef (p.releaseMs, sr);
		holdSamples = int (p.holdMs * 0.001 * sr);
		thrLin = dbToLin (p.thresholdDb);
	}
	inline void processBlock (float** ch, int nch, int n)
	{
		for (int i = 0; i < n; ++i)
		{
			double det = 0;
			for (int c = 0; c < nch; ++c)
				det = std::max (det, double (std::fabs (ch[c][i])));
			if (peak.push (det) > thrLin)
				holdCount = holdSamples;
			const bool open = holdCount > 0;
			if (holdCount > 0)
				--holdCount;
			const double target = open ? 0.0 : p.rangeDb;
			const double c = target < grDb ? att : rel; // öffnen = Attack
			grDb = target + c * (grDb - target);
			const double g = dbToLin (-grDb);
			for (int k = 0; k < nch; ++k)
				ch[k][i] = sanitize (float (ch[k][i] * g));
		}
	}

private:
	Params p;
	double sr = 48000, att = 0, rel = 0, grDb = 40, thrLin = 0.001;
	int holdSamples = 0, holdCount = 0;
	SlidingMax peak;
};

//------------------------------------------------------------------------
// De-Esser: Detektor = Hochpass, Wirkung = Überblendung trocken <-> High-Shelf (-range dB).
// Oberhalb von freq entspricht die Absenkung exakt der momentanen Gain Reduction
// (gleiches Verfahren wie engine/dsp.py deess).
class DeEsser
{
public:
	struct Params { double freq = 5500, thresholdDb = -30, rangeDb = 8; };
	void prepare (double sampleRate)
	{
		sr = sampleRate;
		gr = 0;
		att = timeCoef (1.0, sr);
		rel = timeCoef (60.0, sr);
		setParams (p);
		hp.reset ();
		shelf.reset ();
		peak.reset ();
	}
	void setParams (const Params& np)
	{
		p = np;
		hp.setCoeffs (BiquadCoeffs::make (FilterType::HighPass, p.freq, sr, 0, 0.7071));
		shelf.setCoeffs (BiquadCoeffs::make (FilterType::HighShelf, p.freq, sr, -std::max (p.rangeDb, 0.0), 0.7071));
		floorLin = dbToLin (-std::max (p.rangeDb, 0.0));
	}
	inline void processBlock (float** ch, int nch, int n)
	{
		for (int i = 0; i < n; ++i)
		{
			double sh[2] = {0, 0};
			double det = 0;
			for (int c = 0; c < nch && c < 2; ++c)
			{
				det = std::max (det, std::fabs (hp.process (ch[c][i], c)));
				sh[c] = shelf.process (ch[c][i], c);
			}
			const double target = std::min (compressorGainReduction (linToDb (peak.push (det)), p.thresholdDb, 4.0, 3.0), p.rangeDb);
			const double k = target > gr ? att : rel;
			gr = target + k * (gr - target);
			const double mix = p.rangeDb > 0.01 ? (1.0 - dbToLin (-gr)) / (1.0 - floorLin) : 0.0;
			for (int c = 0; c < nch && c < 2; ++c)
				ch[c][i] = sanitize (float (ch[c][i] + mix * (sh[c] - ch[c][i])));
		}
	}
	double currentGr () const { return gr; }

private:
	Params p;
	Biquad hp, shelf;
	SlidingMax peak;
	double sr = 48000, gr = 0, att = 0, rel = 0, floorLin = 0.4;
};

//------------------------------------------------------------------------
// Dynamisches EQ-Band: x + (g - 1) * bandpass(x), optional externer Sidechain
class DynamicBand
{
public:
	struct Params { bool on = false; double freq = 1000, q = 1.4, thresholdDb = -30, rangeDb = 3; };
	void prepare (double sampleRate)
	{
		sr = sampleRate;
		gr = 0;
		att = timeCoef (5.0, sr);
		rel = timeCoef (120.0, sr);
		ms.reset ();
		setParams (p);
		bp.reset ();
		bpSc.reset ();
	}
	void setParams (const Params& np)
	{
		p = np;
		auto c = BiquadCoeffs::make (FilterType::BandPass, p.freq, sr, 0, p.q);
		bp.setCoeffs (c);
		bpSc.setCoeffs (c);
	}
	inline void processBlock (float** ch, int nch, int n, float** sc = nullptr, int scCh = 0)
	{
		if (!p.on)
			return;
		for (int i = 0; i < n; ++i)
		{
			double band[2] = {0, 0};
			double e = 0;
			const int nc = std::min (nch, 2);
			for (int c = 0; c < nc; ++c)
				band[c] = bp.process (ch[c][i], c);
			if (sc && scCh > 0)
			{
				const int sn = std::min (scCh, 2);
				for (int c = 0; c < sn; ++c)
				{
					const double s = bpSc.process (sc[c][i], c);
					e += s * s;
				}
				e /= sn;
			}
			else
			{
				for (int c = 0; c < nc; ++c)
					e += band[c] * band[c];
				e /= std::max (nc, 1);
			}
			const double env = ms.push (e); // Mittelwert über Kanäle und Fenster wie block_rms
			const double target = std::min (compressorGainReduction (10 * std::log10 (env + 1e-20), p.thresholdDb, 3.0, 6.0), p.rangeDb);
			const double k = target > gr ? att : rel;
			gr = target + k * (gr - target);
			const double g = dbToLin (-gr);
			for (int c = 0; c < nch && c < 2; ++c)
				ch[c][i] = sanitize (float (ch[c][i] + (g - 1.0) * band[c]));
		}
	}

private:
	Params p;
	Biquad bp, bpSc;
	SlidingMean ms;
	double sr = 48000, gr = 0, att = 0, rel = 0;
};

//------------------------------------------------------------------------
// Halbband-FIR für 2x Oversampling (Fenster-Sinc, 31 Taps, Kaiser-ähnlich)
template <int Taps>
struct FirKernel
{
	std::array<double, Taps> h {};
	void designLowpass (double cutoff /* relativ zu fs, z. B. 0.25 */, double beta = 8.0)
	{
		const int M = Taps - 1;
		double sum = 0;
		for (int n = 0; n < Taps; ++n)
		{
			const double m = n - M / 2.0;
			const double sinc = (m == 0) ? 2 * cutoff : std::sin (2 * kPi * cutoff * m) / (kPi * m);
			const double r = 2.0 * n / M - 1.0;
			const double w = besselI0 (beta * std::sqrt (std::max (0.0, 1 - r * r))) / besselI0 (beta);
			h[n] = sinc * w;
			sum += h[n];
		}
		for (auto& v : h)
			v /= sum;
	}
	static double besselI0 (double x)
	{
		double s = 1, t = 1;
		for (int k = 1; k < 30; ++k)
		{
			t *= (x / (2 * k)) * (x / (2 * k));
			s += t;
		}
		return s;
	}
};

// tanh-Sättigung mit 2x Oversampling (allokationsfrei)
class Saturator
{
public:
	static constexpr int kTaps = 31;
	void prepare (double sampleRate)
	{
		kernel.designLowpass (0.25);
		for (auto& b : up)
			b.fill (0);
		for (auto& b : down)
			b.fill (0);
		for (auto& b : dry)
			b.fill (0);
		dryPos = 0;
		drive.prepare (sampleRate, 20);
		wet.prepare (sampleRate, 20);
		drive.reset (drive.targetValue ());
		wet.reset (wet.targetValue ());
	}
	// driveDb <= 0.01 entspricht der Offline-Engine (kein Effekt). Der Pfad läuft trotzdem
	// weiter, damit die gemeldete Latenz konstant bleibt; Dry wird phasengleich verzögert.
	void setParams (double driveDb, double mixAmount)
	{
		const bool active = driveDb > 0.01;
		drive.setTarget (dbToLin (std::max (0.01, driveDb)));
		wet.setTarget (active ? std::clamp (mixAmount, 0.0, 1.0) : 0.0);
	}
	inline void processBlock (float** ch, int nch, int n)
	{
		for (int i = 0; i < n; ++i)
		{
			const double d = drive.next ();
			const double m = wet.next ();
			const double norm = 1.0 / std::tanh (d);
			for (int c = 0; c < nch && c < 2; ++c)
			{
				const double x = ch[c][i];
				// Upsampling: Nullen einfügen, FIR (Verstärkung 2), Formung, Dezimation
				const double y0 = shapeUp (c, x * 2.0, d, norm);
				const double y1 = shapeUp (c, 0.0, d, norm);
				const double out = pushDown (c, y0);
				pushDown (c, y1);
				const double xd = dry[size_t (c)][size_t (dryPos)];
				dry[size_t (c)][size_t (dryPos)] = x;
				ch[c][i] = sanitize (float (m * out + (1 - m) * xd));
			}
			dryPos = (dryPos + 1) % kLatency;
		}
	}
	// Auf- und Abwärtsfilter je (kTaps - 1) / 2 Samples bei 2x-Rate, zusammen (kTaps - 1) / 2 bei Basisrate
	static constexpr int kLatency = (kTaps - 1) / 2;
	static constexpr int latencySamples () { return kLatency; }

private:
	inline double shapeUp (int c, double x, double d, double norm)
	{
		auto& b = up[c];
		std::move_backward (b.begin (), b.end () - 1, b.end ());
		b[0] = x;
		double s = 0;
		for (int k = 0; k < kTaps; ++k)
			s += kernel.h[k] * b[k];
		return std::tanh (s * d) * norm;
	}
	inline double pushDown (int c, double x)
	{
		auto& b = down[c];
		std::move_backward (b.begin (), b.end () - 1, b.end ());
		b[0] = x;
		double s = 0;
		for (int k = 0; k < kTaps; ++k)
			s += kernel.h[k] * b[k];
		return s;
	}
	FirKernel<kTaps> kernel;
	std::array<std::array<double, kTaps>, 2> up {}, down {};
	std::array<std::array<double, kLatency>, 2> dry {};
	int dryPos = 0;
	LinearSmoother drive, wet;

public:
	Saturator () { drive.reset (1.0); wet.reset (0.0); }
};

//------------------------------------------------------------------------
// True-Peak-Schätzung: 4x Oversampling (Polyphasen-FIR, 24 Taps je Phase)
class TruePeakDetector
{
public:
	static constexpr int kPhases = 4, kTapsPerPhase = 24, kTaps = kPhases * kTapsPerPhase;
	void prepare (double)
	{
		FirKernel<kTaps> k;
		k.designLowpass (0.5 / kPhases, 7.0);
		for (int p = 0; p < kPhases; ++p)
			for (int t = 0; t < kTapsPerPhase; ++t)
				poly[p][t] = k.h[t * kPhases + p] * kPhases;
		for (auto& h : hist)
			h.fill (0);
	}
	// Liefert den maximalen Betrag der interpolierten Samples
	inline double process (double x, int ch)
	{
		auto& h = hist[ch];
		std::move_backward (h.begin (), h.end () - 1, h.end ());
		h[0] = x;
		double m = std::fabs (x);
		for (int p = 0; p < kPhases; ++p)
		{
			double s = 0;
			for (int t = 0; t < kTapsPerPhase; ++t)
				s += poly[p][t] * h[t];
			m = std::max (m, std::fabs (s));
		}
		return m;
	}
	static constexpr int delay () { return kTapsPerPhase / 2; }

private:
	std::array<std::array<double, kTapsPerPhase>, kPhases> poly {};
	std::array<std::array<double, kTapsPerPhase>, 2> hist {};
};

//------------------------------------------------------------------------
// Lookahead-True-Peak-Limiter. Latenz = lookahead-Samples (an Host melden).
class Limiter
{
public:
	void prepare (double sampleRate, double lookaheadMs = 1.5)
	{
		sr = sampleRate;
		la = std::max (1, int (lookaheadMs * 0.001 * sr));
		// Ein Sample s erscheint im Detektor zum Zeitpunkt s + delay(); das Minimum-Fenster
		// umfasst la + 1 Detektorwerte. Ausgabe von s erfolgt, wenn s gerade das Fenster
		// verlässt -> gleitender Mittelwert ist dann vollständig auf das Minimum abgesunken.
		const int delayLen = la + TruePeakDetector::delay ();
		for (auto& d : delay)
			d.assign (size_t (delayLen), 0.f);
		reqBuf.assign (size_t (la + 2), 1.0);
		dq.assign (size_t (la + 2) * 2, 0);
		smoothBuf.assign (size_t (la + 1), 1.0);
		smoothSum = la + 1;
		pos = 0;
		smoothPos = 0;
		gain = 1.0;
		dqHead = dqTail = 0;
		idx = 0;
		tp.prepare (sr);
		setRelease (60.0);
	}
	void setCeilingDb (double db) { ceiling = dbToLin (std::min (db, 0.0)); }
	// Deaktiviert: keine Pegeländerung, aber gleiche Latenz (konstante Host-Kompensation)
	void setEnabled (bool on) { enabled = on; }
	void setRelease (double ms) { rel = timeCoef (ms, sr); }
	int latencySamples () const { return la + TruePeakDetector::delay (); }

	inline void processBlock (float** ch, int nch, int n)
	{
		const int cap = int (reqBuf.size ());
		const int delayLen = int (delay[0].size ());
		for (int i = 0; i < n; ++i)
		{
			double pk = 0;
			for (int c = 0; c < nch && c < 2; ++c)
				pk = std::max (pk, tp.process (ch[c][i], c));
			const double req = (enabled && pk > ceiling) ? ceiling / pk : 1.0;
			// gleitendes Minimum über das Lookahead-Fenster (monotone Deque, fest dimensioniert)
			reqBuf[size_t (idx % cap)] = req;
			while (dqTail > dqHead && reqBuf[size_t (dq[size_t ((dqTail - 1) % dq.size ())] % cap)] >= req)
				--dqTail;
			dq[size_t (dqTail % dq.size ())] = idx;
			++dqTail;
			while (dq[size_t (dqHead % dq.size ())] <= idx - la - 1)
				++dqHead;
			const double winMin = reqBuf[size_t (dq[size_t (dqHead % dq.size ())] % cap)];
			// gleitender Mittelwert (weiche Absenkung) + Release
			smoothSum += winMin - smoothBuf[size_t (smoothPos)];
			smoothBuf[size_t (smoothPos)] = winMin;
			smoothPos = (smoothPos + 1) % int (smoothBuf.size ());
			double target = std::min (winMin, smoothSum / double (smoothBuf.size ()));
			gain = target < gain ? target : target + rel * (gain - target);
			const double g = std::min (gain, winMin);
			grDb = std::max (grDb, -linToDb (g));
			for (int c = 0; c < nch && c < 2; ++c)
			{
				auto& d = delay[size_t (c)];
				const float delayed = d[size_t (pos)];
				d[size_t (pos)] = ch[c][i];
				float y = sanitize (float (delayed * g));
				// harte Sicherheitsgrenze (Sample-Peak)
				ch[c][i] = enabled ? std::clamp (y, float (-ceiling), float (ceiling)) : y;
			}
			pos = (pos + 1) % delayLen;
			++idx;
		}
	}
	double takeMaxGr () { double g = grDb; grDb = 0; return g; }

private:
	double sr = 48000, ceiling = 0.891, rel = 0.999, gain = 1.0, smoothSum = 1.0, grDb = 0;
	int la = 72, pos = 0, smoothPos = 0;
	bool enabled = true;
	int64_t idx = 0, dqHead = 0, dqTail = 0;
	std::array<std::vector<float>, 2> delay;
	std::vector<double> reqBuf, smoothBuf;
	std::vector<int64_t> dq;
	TruePeakDetector tp;
};

//------------------------------------------------------------------------
// Lautheitsmessung (BS.1770-4): K-Filter, Momentary (400 ms), Short-term (3 s)
class LoudnessMeter
{
public:
	void prepare (double sampleRate)
	{
		sr = sampleRate;
		// Stufe 1: High-Shelf, Stufe 2: RLB-Hochpass (gleiche Herleitung wie Python-Engine)
		{
			const double f0 = 1681.974450955533, G = 3.999843853973347, Q = 0.7071752369554196;
			const double K = std::tan (kPi * f0 / sr), Vh = std::pow (10.0, G / 20.0), Vb = std::pow (Vh, 0.4996667741545416);
			const double a0 = 1.0 + K / Q + K * K;
			BiquadCoeffs c;
			c.b0 = (Vh + Vb * K / Q + K * K) / a0; c.b1 = 2.0 * (K * K - Vh) / a0; c.b2 = (Vh - Vb * K / Q + K * K) / a0;
			c.a1 = 2.0 * (K * K - 1.0) / a0; c.a2 = (1.0 - K / Q + K * K) / a0;
			s1.setCoeffs (c);
		}
		{
			const double f0 = 38.13547087602444, Q = 0.5003270373238773;
			const double K = std::tan (kPi * f0 / sr), den = 1.0 + K / Q + K * K;
			BiquadCoeffs c;
			c.b0 = 1.0; c.b1 = -2.0; c.b2 = 1.0;
			c.a1 = 2.0 * (K * K - 1.0) / den; c.a2 = (1.0 - K / Q + K * K) / den;
			s2.setCoeffs (c);
		}
		s1.reset (); s2.reset ();
		blockLen = std::max (1, int (0.1 * sr)); // 100-ms-Teilblöcke
		blocks.assign (30, 0.0);
		blockAcc = 0; blockCount = 0; nBlocks = 0; head = 0;
	}
	inline void processBlock (const float* const* ch, int nch, int n)
	{
		for (int i = 0; i < n; ++i)
		{
			double e = 0;
			for (int c = 0; c < nch && c < 2; ++c)
			{
				const double y = s2.process (s1.process (ch[c][i], c), c);
				e += y * y;
			}
			blockAcc += e;
			if (++blockCount >= blockLen)
			{
				blocks[size_t (head)] = blockAcc / blockLen;
				head = (head + 1) % 30;
				nBlocks = std::min (nBlocks + 1, 30);
				blockAcc = 0; blockCount = 0;
				momentary.store (energyToLufs (mean (4)), std::memory_order_relaxed);
				shortTerm.store (energyToLufs (mean (30)), std::memory_order_relaxed);
			}
		}
	}
	double momentaryLufs () const { return momentary.load (std::memory_order_relaxed); }
	double shortTermLufs () const { return shortTerm.load (std::memory_order_relaxed); }

private:
	double mean (int count) const
	{
		const int c = std::min (count, nBlocks);
		if (c == 0)
			return 0;
		double s = 0;
		for (int k = 1; k <= c; ++k)
			s += blocks[size_t ((head - k + 30) % 30)];
		return s / c;
	}
	static double energyToLufs (double e) { return e > 1e-20 ? -0.691 + 10 * std::log10 (e) : -150.0; }
	double sr = 48000;
	Biquad s1, s2;
	std::vector<double> blocks;
	double blockAcc = 0;
	int blockLen = 4800, blockCount = 0, nBlocks = 0, head = 0;
	std::atomic<double> momentary {-150.0}, shortTerm {-150.0};
};

//------------------------------------------------------------------------
// Lock-freier Single-Producer/Single-Consumer-Ringpuffer (Audio-Thread -> Sender-Thread)
template <typename T>
class SpscRing
{
public:
	void prepare (size_t capacityPow2)
	{
		size_t c = 1;
		while (c < capacityPow2)
			c <<= 1;
		buf.assign (c, T {});
		mask = c - 1;
		w.store (0); r.store (0);
	}
	// Audio-Thread: schreibt so viel wie Platz ist, gibt Anzahl geschriebener Elemente zurück
	size_t push (const T* data, size_t n)
	{
		const size_t wr = w.load (std::memory_order_relaxed), rd = r.load (std::memory_order_acquire);
		const size_t free = buf.size () - (wr - rd);
		const size_t m = std::min (n, free);
		for (size_t i = 0; i < m; ++i)
			buf[(wr + i) & mask] = data[i];
		w.store (wr + m, std::memory_order_release);
		dropped += (n - m);
		return m;
	}
	size_t pop (T* out, size_t n)
	{
		const size_t rd = r.load (std::memory_order_relaxed), wr = w.load (std::memory_order_acquire);
		const size_t m = std::min (n, wr - rd);
		for (size_t i = 0; i < m; ++i)
			out[i] = buf[(rd + i) & mask];
		r.store (rd + m, std::memory_order_release);
		return m;
	}
	size_t available () const { return w.load (std::memory_order_acquire) - r.load (std::memory_order_acquire); }
	size_t droppedCount () const { return dropped.load (); }

private:
	std::vector<T> buf;
	size_t mask = 0;
	std::atomic<size_t> w {0}, r {0}, dropped {0};
};

} // namespace aime
