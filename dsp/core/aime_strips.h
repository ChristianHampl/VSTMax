// AIME-Kanalzüge: dieselbe Signalkette wie die Offline-Engine (engine/mixing.py, engine/mastering.py).
// Parameter werden als Klartextwerte über setParam(id, wert) gesetzt (IDs aus aime_params_gen.h).
// prepare() reserviert Speicher; process() ist allokationsfrei und für den Audio-Thread geeignet.
#pragma once

#include "aime_dsp.h"
#include "aime_params_gen.h"

#include <array>
#include <atomic>
#include <vector>

namespace aime {

//------------------------------------------------------------------------
// Ganzzahlige Verzögerung (bis 2 Kanäle), Länge zur Laufzeit wählbar bis zum Maximum aus prepare()
class DelayLine
{
public:
	void prepare (int maxDelay)
	{
		for (auto& b : buf)
			b.assign (size_t (std::max (1, maxDelay) + 1), 0.f);
		pos = 0;
	}
	void setDelay (int d) { delay = std::clamp (d, 0, int (buf[0].size ()) - 1); }
	int getDelay () const { return delay; }
	void clear ()
	{
		for (auto& b : buf)
			std::fill (b.begin (), b.end (), 0.f);
	}
	inline void processBlock (float** ch, int nch, int n)
	{
		if (delay == 0 || buf[0].empty ())
			return;
		const int len = int (buf[0].size ());
		for (int i = 0; i < n; ++i)
		{
			const int rd = (pos - delay + len) % len;
			for (int c = 0; c < nch && c < 2; ++c)
			{
				auto& b = buf[size_t (c)];
				b[size_t (pos)] = ch[c][i];
				ch[c][i] = b[size_t (rd)];
			}
			pos = (pos + 1) % len;
		}
	}

private:
	std::array<std::vector<float>, 2> buf;
	int pos = 0, delay = 0;
};

// Gemeinsame Infrastruktur: Parameterwerte, Blockaufteilung, latenzkompensierter Bypass
template <int MaxId>
class StripBase
{
public:
	static constexpr int kMaxBlock = 512;

	double param (uint32_t id) const { return id <= uint32_t (MaxId) ? values[id] : 0.0; }
	void setParam (uint32_t id, double plain)
	{
		if (id > uint32_t (MaxId) || !std::isfinite (plain))
			return;
		if (values[id] != plain)
		{
			values[id] = plain;
			dirty = true;
		}
	}
	float meterGrDb () const { return meterGr.load (std::memory_order_relaxed); }
	float meterOutDb () const { return meterOut.load (std::memory_order_relaxed); }

protected:
	void loadDefaults (const params::Info* list, int count)
	{
		values.fill (0.0);
		for (int i = 0; i < count; ++i)
			values[list[i].id] = list[i].def;
		dirty = true;
	}
	void prepareBase (double sampleRate, int latency)
	{
		sr = sampleRate;
		for (auto& b : dryBuf)
			b.assign (kMaxBlock, 0.f);
		dryDelay.prepare (latency);
		dryDelay.setDelay (latency);
		bypassMix.prepare (sr, 20.0);
		bypassMix.reset (values[0] >= 0.5 ? 1.0 : 0.0);
	}
	// Verarbeitet in Teilblöcken <= kMaxBlock; F(ch, nch, n, scOffset)
	template <typename F>
	void runBlocks (float** io, int nch, int n, F&& body)
	{
		nch = std::min (nch, 2);
		bypassMix.setTarget (values[0] >= 0.5 ? 1.0 : 0.0);
		int done = 0;
		while (done < n)
		{
			const int m = std::min (kMaxBlock, n - done);
			float* ch[2] = {io[0] + done, nch > 1 ? io[1] + done : nullptr};
			float* dry[2] = {dryBuf[0].data (), dryBuf[1].data ()};
			const bool needDry = bypassMix.isSmoothing () || bypassMix.targetValue () > 0.0;
			for (int c = 0; c < nch; ++c)
				std::copy (ch[c], ch[c] + m, dry[c]);
			dryDelay.processBlock (dry, nch, m);
			body (ch, nch, m, done);
			if (needDry)
			{
				for (int i = 0; i < m; ++i)
				{
					const double b = bypassMix.next ();
					for (int c = 0; c < nch; ++c)
						ch[c][i] = float (b * dry[c][i] + (1.0 - b) * ch[c][i]);
				}
			}
			float pk = 0.f;
			for (int c = 0; c < nch; ++c)
				for (int i = 0; i < m; ++i)
					pk = std::max (pk, std::fabs (ch[c][i]));
			peakHold = std::max (peakHold, pk);
			done += m;
		}
		meterOut.store (float (linToDb (peakHold, -90.0)), std::memory_order_relaxed);
		peakHold *= 0.5f;
	}

	std::array<double, MaxId + 1> values {};
	bool dirty = true;
	double sr = 48000;
	std::array<std::vector<float>, 2> dryBuf;
	DelayLine dryDelay;
	LinearSmoother bypassMix;
	float peakHold = 0.f;
	std::atomic<float> meterGr {0.f}, meterOut {-90.f};
};

//------------------------------------------------------------------------
class ChannelStrip : public StripBase<params::channel::kMaxId>
{
public:
	static constexpr double kMaxAlignMs = 50.0;

	ChannelStrip () { loadDefaults (params::channel::kParams, params::channel::kCount); }

	void prepare (double sampleRate)
	{
		prepareBase (sampleRate, latencySamples ());
		alignDelay.prepare (int (std::ceil (kMaxAlignMs * 0.001 * sampleRate)) + 1);
		dc.reset ();
		dc.setCoeffs (BiquadCoeffs::make (FilterType::HighPass, 10.0, sampleRate, 0, 0.7071));
		for (auto& b : hpf)
			b.prepare (sampleRate);
		lpf.prepare (sampleRate);
		for (auto& b : eq)
			b.prepare (sampleRate);
		for (auto& d : dyn)
			d.prepare (sampleRate);
		gate.prepare (sampleRate);
		comp.prepare (sampleRate);
		deess.prepare (sampleRate);
		sat.prepare (sampleRate);
		trim.prepare (sampleRate, 20.0);
		out.prepare (sampleRate, 20.0);
		widthS.prepare (sampleRate, 20.0);
		panS.prepare (sampleRate, 20.0);
		dirty = true;
		applyParams (true);
	}
	static constexpr int latencySamples () { return Saturator::latencySamples (); }

	// io: 1 oder 2 Kanäle (in-place). sc: optionaler Sidechain (gleiche Blocklänge) oder nullptr.
	void process (float** io, int nch, int n, float** sc = nullptr, int scCh = 0)
	{
		applyParams (false);
		runBlocks (io, nch, n, [&] (float** ch, int nc, int m, int off) {
			float* scp[2] = {nullptr, nullptr};
			const int scc = (sc && scCh > 0) ? std::min (scCh, 2) : 0;
			for (int c = 0; c < scc; ++c)
				scp[c] = sc[c] + off;
			processChain (ch, nc, m, scc ? scp : nullptr, scc);
		});
		meterGr.store (float (comp.takeMaxGr ()), std::memory_order_relaxed);
	}

private:
	using P = params::channel::Id;

	bool on (uint32_t id) const { return values[id] >= 0.5; }

	void applyParams (bool initial)
	{
		if (!dirty)
			return;
		dirty = false;
		const auto& v = values;
		alignDelay.setDelay (int (std::lround (v[P::kAlignDelayMs] * 0.001 * sr)));
		const double hf = v[P::kHpfFreq];
		const auto hpType = hf > 10.5 ? FilterType::HighPass : FilterType::Off;
		hpf[0].set (hpType, hf, 0.0, 0.7071);
		hpf[1].set (on (P::kHpfSteep) ? hpType : FilterType::Off, hf, 0.0, 0.7071);
		const double lf = v[P::kLpfFreq];
		lpf.set (lf < std::min (21900.0, 0.45 * sr) ? FilterType::LowPass : FilterType::Off, lf, 0.0, 0.7071);
		for (int b = 0; b < 8; ++b)
		{
			const uint32_t base = P::kEq1Type + uint32_t (b) * 4;
			static constexpr FilterType map[4] = {FilterType::Off, FilterType::Bell, FilterType::LowShelf, FilterType::HighShelf};
			const int t = std::clamp (int (std::lround (v[base])), 0, 3);
			const double g = v[base + 2];
			eq[size_t (b)].set (std::fabs (g) > 0.01 ? map[t] : FilterType::Off, v[base + 1], g, v[base + 3]);
		}
		for (int b = 0; b < 2; ++b)
		{
			const uint32_t base = P::kDyn1On + uint32_t (b) * 5;
			DynamicBand::Params dp;
			dp.on = on (base);
			dp.freq = v[base + 1];
			dp.q = v[base + 2];
			dp.thresholdDb = v[base + 3];
			dp.rangeDb = v[base + 4];
			dyn[size_t (b)].setParams (dp);
		}
		dynSc[0] = on (P::kDyn1Sidechain);
		dynSc[1] = on (P::kDyn2Sidechain);
		Gate::Params gp {v[P::kGateThresholdDb], v[P::kGateRangeDb], v[P::kGateAttackMs], v[P::kGateHoldMs], v[P::kGateReleaseMs]};
		gate.setParams (gp);
		Compressor::Params cp {v[P::kCompThresholdDb], v[P::kCompRatio], v[P::kCompAttackMs], v[P::kCompReleaseMs],
		                       v[P::kCompKneeDb], v[P::kCompMakeupDb], v[P::kCompMix]};
		comp.setParams (cp);
		DeEsser::Params dsp {v[P::kDeessFreq], v[P::kDeessThresholdDb], v[P::kDeessRangeDb]};
		deess.setParams (dsp);
		sat.setParams (v[P::kSatDriveDb], v[P::kSatMix]);
		trim.setTarget (dbToLin (v[P::kTrimDb]));
		out.setTarget (dbToLin (v[P::kOutputDb]));
		widthS.setTarget (v[P::kWidth]);
		panS.setTarget (v[P::kPan]);
		if (initial)
		{
			for (auto& b : hpf)
				b.snap ();
			lpf.snap ();
			for (auto& b : eq)
				b.snap ();
			trim.reset (trim.targetValue ());
			out.reset (out.targetValue ());
			widthS.reset (widthS.targetValue ());
			panS.reset (panS.targetValue ());
			comp.snap ();
			sat.prepare (sr);
		}
	}

	void processChain (float** ch, int nch, int n, float** sc, int scCh)
	{
		const auto& v = values;
		if (on (P::kDcRemove))
			for (int c = 0; c < nch; ++c)
				for (int i = 0; i < n; ++i)
					ch[c][i] = float (dc.process (ch[c][i], c));
		if (nch > 1 && on (P::kInvertRight))
			for (int i = 0; i < n; ++i)
				ch[1][i] = -ch[1][i];
		if (on (P::kPolarityInvert))
			for (int c = 0; c < nch; ++c)
				for (int i = 0; i < n; ++i)
					ch[c][i] = -ch[c][i];
		alignDelay.processBlock (ch, nch, n);
		for (int i = 0; i < n; ++i)
		{
			const double g = trim.next ();
			for (int c = 0; c < nch; ++c)
				ch[c][i] = float (ch[c][i] * g);
		}
		if (on (P::kGateOn))
			gate.processBlock (ch, nch, n);
		hpf[0].processBlock (ch, nch, n);
		hpf[1].processBlock (ch, nch, n);
		lpf.processBlock (ch, nch, n);
		for (auto& b : eq)
			b.processBlock (ch, nch, n);
		for (int b = 0; b < 2; ++b)
			dyn[size_t (b)].processBlock (ch, nch, n, dynSc[b] ? sc : nullptr, dynSc[b] ? scCh : 0);
		if (on (P::kCompOn))
			comp.processBlock (ch, nch, n);
		if (on (P::kDeessOn))
			deess.processBlock (ch, nch, n);
		sat.processBlock (ch, nch, n);
		for (int i = 0; i < n; ++i)
		{
			const double g = out.next ();
			const double w = widthS.next ();
			const double p = panS.next ();
			if (nch > 1)
			{
				const double l = ch[0][i] * g, r = ch[1][i] * g;
				const double mid = 0.5 * (l + r), side = 0.5 * (l - r) * w;
				// Konstante Leistung, Mitte = Einheitsverstärkung (wie engine/dsp.py pan_stereo für Stereo)
				const double th = (std::clamp (p, -1.0, 1.0) + 1.0) * kPi / 4.0;
				const double gl = std::cos (th) * 1.4142135623730951, gr = std::sin (th) * 1.4142135623730951;
				ch[0][i] = sanitize (float ((mid + side) * gl));
				ch[1][i] = sanitize (float ((mid - side) * gr));
			}
			else
				ch[0][i] = sanitize (float (ch[0][i] * g));
		}
		(void)v;
	}

	DelayLine alignDelay;
	Biquad dc;
	std::array<SmoothedBand, 2> hpf;
	SmoothedBand lpf;
	std::array<SmoothedBand, 8> eq;
	std::array<DynamicBand, 2> dyn;
	bool dynSc[2] = {false, false};
	Gate gate;
	Compressor comp;
	DeEsser deess;
	Saturator sat;
	LinearSmoother trim, out, widthS, panS;
};

//------------------------------------------------------------------------
// Gruppen-/Mixbus: Input -> (Parallelkompression + Sättigung) -> Bus-Kompressor -> Sättigung -> Output
class BusStrip : public StripBase<params::bus::kMaxId>
{
public:
	BusStrip () { loadDefaults (params::bus::kParams, params::bus::kCount); }

	void prepare (double sampleRate)
	{
		prepareBase (sampleRate, latencySamples ());
		for (auto& b : parBuf)
			b.assign (kMaxBlock, 0.f);
		mainDelay.prepare (Saturator::latencySamples ());
		mainDelay.setDelay (Saturator::latencySamples ());
		parComp.prepare (sampleRate);
		parSat.prepare (sampleRate);
		comp.prepare (sampleRate);
		sat.prepare (sampleRate);
		in.prepare (sampleRate, 20.0);
		out.prepare (sampleRate, 20.0);
		parAmt.prepare (sampleRate, 20.0);
		dirty = true;
		applyParams (true);
	}
	static constexpr int latencySamples () { return 2 * Saturator::latencySamples (); }

	void process (float** io, int nch, int n)
	{
		applyParams (false);
		runBlocks (io, nch, n, [&] (float** ch, int nc, int m, int) { processChain (ch, nc, m); });
		meterGr.store (float (comp.takeMaxGr ()), std::memory_order_relaxed);
	}

private:
	using P = params::bus::Id;
	void applyParams (bool initial)
	{
		if (!dirty)
			return;
		dirty = false;
		const auto& v = values;
		comp.setParams ({v[P::kCompThresholdDb], v[P::kCompRatio], v[P::kCompAttackMs], v[P::kCompReleaseMs],
		                 v[P::kCompKneeDb], v[P::kCompMakeupDb], 1.0});
		parComp.setParams ({v[P::kParThresholdDb], v[P::kParRatio], v[P::kParAttackMs], v[P::kParReleaseMs], 6.0,
		                    v[P::kParMakeupDb], 1.0});
		parSat.setParams (v[P::kParDriveDb], 1.0);
		sat.setParams (v[P::kSatDriveDb], 1.0);
		in.setTarget (dbToLin (v[P::kInputDb]));
		out.setTarget (dbToLin (v[P::kOutputDb]));
		parAmt.setTarget (v[P::kParAmount]);
		if (initial)
		{
			in.reset (in.targetValue ());
			out.reset (out.targetValue ());
			parAmt.reset (parAmt.targetValue ());
			parComp.snap ();
			comp.snap ();
			parSat.prepare (sr);
			sat.prepare (sr);
		}
	}
	void processChain (float** ch, int nch, int n)
	{
		for (int i = 0; i < n; ++i)
		{
			const double g = in.next ();
			for (int c = 0; c < nch; ++c)
				ch[c][i] = float (ch[c][i] * g);
		}
		float* par[2] = {parBuf[0].data (), parBuf[1].data ()};
		for (int c = 0; c < nch; ++c)
			std::copy (ch[c], ch[c] + n, par[c]);
		parComp.processBlock (par, nch, n);
		parSat.processBlock (par, nch, n);
		mainDelay.processBlock (ch, nch, n);
		for (int i = 0; i < n; ++i)
		{
			const double a = parAmt.next ();
			for (int c = 0; c < nch; ++c)
				ch[c][i] = float (ch[c][i] + a * par[c][i]);
		}
		if (values[P::kCompOn] >= 0.5)
			comp.processBlock (ch, nch, n);
		sat.processBlock (ch, nch, n);
		for (int i = 0; i < n; ++i)
		{
			const double g = out.next ();
			for (int c = 0; c < nch; ++c)
				ch[c][i] = sanitize (float (ch[c][i] * g));
		}
	}
	std::array<std::vector<float>, 2> parBuf;
	DelayLine mainDelay;
	Compressor parComp, comp;
	Saturator parSat, sat;
	LinearSmoother in, out, parAmt;
};

//------------------------------------------------------------------------
// Master: Input -> EQ (4) -> Glue-Kompressor -> Limiter-Drive -> True-Peak-Limiter -> Output + Meter
class MasterStrip : public StripBase<params::master::kMaxId>
{
public:
	static constexpr double kLookaheadMs = 1.5;

	MasterStrip () { loadDefaults (params::master::kParams, params::master::kCount); }

	void prepare (double sampleRate)
	{
		sr = sampleRate;
		limiter.prepare (sampleRate, kLookaheadMs);
		prepareBase (sampleRate, latencySamples ());
		for (auto& b : eq)
			b.prepare (sampleRate);
		comp.prepare (sampleRate);
		loud.prepare (sampleRate);
		tp.prepare (sampleRate);
		in.prepare (sampleRate, 20.0);
		drive.prepare (sampleRate, 20.0);
		out.prepare (sampleRate, 20.0);
		tpHold = 0;
		dirty = true;
		applyParams (true);
	}
	int latencySamples () const { return limiter.latencySamples (); }

	void process (float** io, int nch, int n)
	{
		applyParams (false);
		runBlocks (io, nch, n, [&] (float** ch, int nc, int m, int) { processChain (ch, nc, m); });
		meterGr.store (float (limiter.takeMaxGr ()), std::memory_order_relaxed);
		meterTp.store (float (linToDb (tpHold, -70.0)), std::memory_order_relaxed);
	}
	double momentaryLufs () const { return loud.momentaryLufs (); }
	double shortTermLufs () const { return loud.shortTermLufs (); }
	float meterTruePeakDb () const { return meterTp.load (std::memory_order_relaxed); }
	void resetTruePeakHold () { tpHold = 0; }

private:
	using P = params::master::Id;
	void applyParams (bool initial)
	{
		if (!dirty)
			return;
		dirty = false;
		const auto& v = values;
		for (int b = 0; b < 4; ++b)
		{
			const uint32_t base = P::kEq1Type + uint32_t (b) * 4;
			static constexpr FilterType map[4] = {FilterType::Off, FilterType::Bell, FilterType::LowShelf, FilterType::HighShelf};
			const int t = std::clamp (int (std::lround (v[base])), 0, 3);
			const double g = v[base + 2];
			eq[size_t (b)].set (std::fabs (g) > 0.01 ? map[t] : FilterType::Off, v[base + 1], g, v[base + 3]);
		}
		comp.setParams ({v[P::kCompThresholdDb], v[P::kCompRatio], v[P::kCompAttackMs], v[P::kCompReleaseMs],
		                 v[P::kCompKneeDb], v[P::kCompMakeupDb], 1.0});
		limiter.setEnabled (v[P::kLimiterOn] >= 0.5);
		limiter.setCeilingDb (v[P::kCeilingDbtp]);
		limiter.setRelease (v[P::kLimiterReleaseMs]);
		in.setTarget (dbToLin (v[P::kInputDb]));
		drive.setTarget (dbToLin (v[P::kLimiterGainDb]));
		out.setTarget (dbToLin (v[P::kOutputDb]));
		if (initial)
		{
			for (auto& b : eq)
				b.snap ();
			in.reset (in.targetValue ());
			drive.reset (drive.targetValue ());
			out.reset (out.targetValue ());
			comp.snap ();
		}
	}
	void processChain (float** ch, int nch, int n)
	{
		for (int i = 0; i < n; ++i)
		{
			const double g = in.next ();
			for (int c = 0; c < nch; ++c)
				ch[c][i] = float (ch[c][i] * g);
		}
		for (auto& b : eq)
			b.processBlock (ch, nch, n);
		if (values[P::kCompOn] >= 0.5)
			comp.processBlock (ch, nch, n);
		for (int i = 0; i < n; ++i)
		{
			const double g = drive.next ();
			for (int c = 0; c < nch; ++c)
				ch[c][i] = float (ch[c][i] * g);
		}
		limiter.processBlock (ch, nch, n);
		for (int i = 0; i < n; ++i)
		{
			const double g = out.next ();
			for (int c = 0; c < nch; ++c)
			{
				ch[c][i] = sanitize (float (ch[c][i] * g));
				tpHold = std::max (tpHold, tp.process (ch[c][i], c));
			}
		}
		loud.processBlock (ch, nch, n);
	}
	std::array<SmoothedBand, 4> eq;
	Compressor comp;
	Limiter limiter;
	LoudnessMeter loud;
	TruePeakDetector tp;
	LinearSmoother in, drive, out;
	double tpHold = 0;
	std::atomic<float> meterTp {-70.f};
};

} // namespace aime
