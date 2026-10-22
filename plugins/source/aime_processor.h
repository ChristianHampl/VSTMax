// AIME-Prozessor (Audio-Teil) für Channel, Bus und Master
#pragma once

#include "aime_link.h"
#include "aime_plugin_desc.h"
#include "aime_state.h"

#include "pluginterfaces/base/ibstream.h"
#include "pluginterfaces/vst/ivstparameterchanges.h"
#include "pluginterfaces/vst/ivstprocesscontext.h"
#include "public.sdk/source/vst/vstaudioeffect.h"

#include <array>
#include <mutex>
#include <random>
#include <string>
#include <vector>

namespace aime::vst {

inline constexpr const char* kPairMessageId = "aime.pair";
inline constexpr const char* kPairAttrId = "id";

inline uint64_t randomInstanceId ()
{
	std::random_device rd;
	return (uint64_t (rd ()) << 32) ^ uint64_t (rd ()) ^ (uint64_t (rd ()) << 16);
}

// Liest einen kompletten IBStream ab der aktuellen Position
inline bool readAll (Steinberg::IBStream* s, std::vector<uint8_t>& out)
{
	out.clear ();
	if (!s)
		return false;
	uint8_t buf[4096];
	for (int guard = 0; guard < 4096; ++guard)
	{
		Steinberg::int32 got = 0;
		if (s->read (buf, sizeof (buf), &got) != Steinberg::kResultOk && got == 0)
			break;
		if (got <= 0)
			break;
		out.insert (out.end (), buf, buf + got);
	}
	return !out.empty ();
}

template <class Desc>
class Processor : public Steinberg::Vst::AudioEffect
{
public:
	using Strip = typename Desc::Strip;
	static constexpr uint32_t kMaxId = Desc::kMaxId;

	Processor ()
	{
		setControllerClass (Desc::controllerUid ());
		infoById.fill (nullptr);
		for (int i = 0; i < Desc::count (); ++i)
		{
			const auto& p = Desc::params ()[i];
			infoById[p.id] = &p;
			stateValues[p.id] = p.def;
		}
		processContextRequirements.needTransportState ();
	}
	~Processor () override = default;

	static Steinberg::FUnknown* createInstance (void*)
	{
		return static_cast<Steinberg::Vst::IAudioProcessor*> (new Processor<Desc>);
	}

	Steinberg::tresult PLUGIN_API initialize (Steinberg::FUnknown* context) override
	{
		using namespace Steinberg;
		using namespace Steinberg::Vst;
		const tresult r = AudioEffect::initialize (context);
		if (r != kResultOk)
			return r;
		addAudioInput (STR16 ("Stereo In"), SpeakerArr::kStereo);
		addAudioOutput (STR16 ("Stereo Out"), SpeakerArr::kStereo);
		if constexpr (Desc::kSidechain)
			addAudioInput (STR16 ("Sidechain"), SpeakerArr::kStereo, kAux, 0);
		link::InstanceInfo info;
		info.plugin = Desc::kKey;
		slot = link::Hub::instance ().registerProcessor (instanceId, info);
		return kResultOk;
	}

	Steinberg::tresult PLUGIN_API terminate () override
	{
		link::Hub::instance ().unregisterProcessor (instanceId);
		slot.reset ();
		return AudioEffect::terminate ();
	}

	Steinberg::tresult PLUGIN_API connect (Steinberg::Vst::IConnectionPoint* other) override
	{
		const auto r = AudioEffect::connect (other);
		if (r == Steinberg::kResultOk)
		{
			if (auto* msg = allocateMessage ())
			{
				msg->setMessageID (kPairMessageId);
				msg->getAttributes ()->setInt (kPairAttrId, Steinberg::int64 (instanceId));
				sendMessage (msg);
				msg->release ();
			}
		}
		return r;
	}

	Steinberg::tresult PLUGIN_API setBusArrangements (Steinberg::Vst::SpeakerArrangement* inputs, Steinberg::int32 numIns,
	                                                  Steinberg::Vst::SpeakerArrangement* outputs,
	                                                  Steinberg::int32 numOuts) override
	{
		using namespace Steinberg;
		using namespace Steinberg::Vst;
		if (numIns < 1 || numOuts != 1)
			return kResultFalse;
		const auto in = inputs[0], out = outputs[0];
		const bool mono = in == SpeakerArr::kMono && out == SpeakerArr::kMono;
		const bool stereo = in == SpeakerArr::kStereo && out == SpeakerArr::kStereo;
		if (!mono && !stereo)
			return kResultFalse;
		if (numIns > 1)
		{
			if (!Desc::kSidechain || numIns > 2)
				return kResultFalse;
			if (inputs[1] != SpeakerArr::kMono && inputs[1] != SpeakerArr::kStereo)
				return kResultFalse;
		}
		return AudioEffect::setBusArrangements (inputs, numIns, outputs, numOuts);
	}

	Steinberg::tresult PLUGIN_API canProcessSampleSize (Steinberg::int32 s) override
	{
		return s == Steinberg::Vst::kSample32 ? Steinberg::kResultTrue : Steinberg::kResultFalse;
	}

	Steinberg::tresult PLUGIN_API setupProcessing (Steinberg::Vst::ProcessSetup& setup) override
	{
		const auto r = AudioEffect::setupProcessing (setup);
		strip.prepare (setup.sampleRate);
		latency = Desc::latency (strip);
		const int nch = mainChannels ();
		link::Hub::instance ().updateInfo (instanceId, [&] (link::InstanceInfo& i) {
			i.sampleRate = setup.sampleRate;
			i.channels = nch;
			i.latency = latency;
		});
		return r;
	}

	Steinberg::uint32 PLUGIN_API getLatencySamples () override { return Steinberg::uint32 (latency); }

	Steinberg::tresult PLUGIN_API setActive (Steinberg::TBool state) override
	{
		if (state)
		{
			// Inaktiv läuft kein process(): geladenen Zustand vor prepare() übernehmen, damit die Glättung
			// direkt auf den Zielwerten startet statt von den Defaults zu rampen
			{
				std::lock_guard<std::mutex> l (stateMtx);
				takePending ();
			}
			strip.prepare (processSetup.sampleRate);
		}
		return AudioEffect::setActive (state);
	}

	Steinberg::tresult PLUGIN_API process (Steinberg::Vst::ProcessData& data) override
	{
		using namespace Steinberg;
		using namespace Steinberg::Vst;
		applyPendingState ();
		if (auto* changes = data.inputParameterChanges)
		{
			const int32 n = changes->getParameterCount ();
			for (int32 i = 0; i < n; ++i)
			{
				auto* q = changes->getParameterData (i);
				if (!q)
					continue;
				const ParamID id = q->getParameterId ();
				int32 off = 0;
				ParamValue v = 0;
				const int32 pts = q->getPointCount ();
				if (id <= kMaxId && infoById[id] && pts > 0 && q->getPoint (pts - 1, off, v) == kResultOk)
				{
					const double plain = params::fromNormalized (*infoById[id], v);
					strip.setParam (id, plain);
					stateDirty = true;
				}
			}
		}
		syncStateValues ();
		if (data.numSamples <= 0 || data.numInputs < 1 || data.numOutputs < 1)
			return kResultOk;
		if (processSetup.symbolicSampleSize != kSample32)
			return kResultOk;
		auto& in = data.inputs[0];
		auto& out = data.outputs[0];
		const int nch = std::min (std::min (in.numChannels, out.numChannels), int32 (2));
		const int n = data.numSamples;
		if (nch <= 0)
			return kResultOk;
		float* io[2] = {nullptr, nullptr};
		for (int c = 0; c < nch; ++c)
		{
			if (in.channelBuffers32[c] != out.channelBuffers32[c])
				std::copy (in.channelBuffers32[c], in.channelBuffers32[c] + n, out.channelBuffers32[c]);
			io[c] = out.channelBuffers32[c];
		}
		capture (io, nch, n, data.processContext);
		float* sc[2] = {nullptr, nullptr};
		int scCh = 0;
		if constexpr (Desc::kSidechain)
		{
			if (data.numInputs > 1 && data.inputs[1].numChannels > 0 && data.inputs[1].channelBuffers32)
			{
				scCh = std::min (data.inputs[1].numChannels, int32 (2));
				for (int c = 0; c < scCh; ++c)
					sc[c] = data.inputs[1].channelBuffers32[c];
			}
			strip.process (io, nch, n, scCh ? sc : nullptr, scCh);
		}
		else
			strip.process (io, nch, n);
		out.silenceFlags = 0;
		if (auto* outChanges = data.outputParameterChanges)
		{
			Desc::meters (strip, [&] (uint32_t id, float plain) {
				if (id > kMaxId || !infoById[id])
					return;
				int32 idx = 0;
				if (auto* q = outChanges->addParameterData (id, idx))
					q->addPoint (0, params::toNormalized (*infoById[id], plain), idx);
			});
		}
		return kResultOk;
	}

	Steinberg::tresult PLUGIN_API setState (Steinberg::IBStream* s) override
	{
		std::vector<uint8_t> bytes;
		std::vector<state::Entry> entries;
		std::string label;
		if (!readAll (s, bytes) || !state::decode (bytes.data (), bytes.size (), entries, label))
			return Steinberg::kResultFalse;
		{
			std::lock_guard<std::mutex> l (stateMtx);
			for (const auto& e : entries)
				if (e.id <= kMaxId && infoById[e.id] && !infoById[e.id]->readonly && std::isfinite (e.value))
				{
					pendingValues[e.id] = params::clampD (e.value, infoById[e.id]->min, infoById[e.id]->max);
					pendingMask[e.id] = true;
					stateValues[e.id] = pendingValues[e.id];
				}
			hasPending = true;
			instanceLabel = label;
		}
		link::Hub::instance ().updateInfo (instanceId, [&] (link::InstanceInfo& i) { i.label = label; });
		return Steinberg::kResultOk;
	}

	Steinberg::tresult PLUGIN_API getState (Steinberg::IBStream* s) override
	{
		if (!s)
			return Steinberg::kResultFalse;
		std::vector<state::Entry> entries;
		std::string label;
		{
			std::lock_guard<std::mutex> l (stateMtx);
			for (int i = 0; i < Desc::count (); ++i)
			{
				const auto& p = Desc::params ()[i];
				if (!p.readonly)
					entries.push_back ({p.id, stateValues[p.id]});
			}
			label = instanceLabel;
		}
		const auto bytes = state::encode (entries, label);
		Steinberg::int32 written = 0;
		return s->write (const_cast<uint8_t*> (bytes.data ()), Steinberg::int32 (bytes.size ()), &written);
	}

private:
	int mainChannels () const
	{
		if (auto* bus = const_cast<Processor*> (this)->getAudioInput (0))
			return Steinberg::Vst::SpeakerArr::getChannelCount (bus->getArrangement ());
		return 2;
	}

	// Audio-Thread: Zustand aus setState übernehmen, ohne zu blockieren
	void applyPendingState ()
	{
		if (!hasPending.load (std::memory_order_acquire))
			return;
		std::unique_lock<std::mutex> l (stateMtx, std::try_to_lock);
		if (!l.owns_lock ())
			return;
		takePending ();
	}

	// Aufrufer hält stateMtx
	void takePending ()
	{
		for (uint32_t id = 0; id <= kMaxId; ++id)
			if (pendingMask[id])
			{
				strip.setParam (id, pendingValues[id]);
				pendingMask[id] = false;
			}
		hasPending = false;
	}

	// Audio-Thread: für getState gespiegelte Werte aktualisieren (nicht blockierend)
	void syncStateValues ()
	{
		if (!stateDirty)
			return;
		std::unique_lock<std::mutex> l (stateMtx, std::try_to_lock);
		if (!l.owns_lock ())
			return;
		for (int i = 0; i < Desc::count (); ++i)
		{
			const auto id = Desc::params ()[i].id;
			if (!pendingMask[id])
				stateValues[id] = strip.param (id);
		}
		stateDirty = false;
	}

	void capture (float** io, int nch, int n, const Steinberg::Vst::ProcessContext* ctx)
	{
		if (!slot || !slot->capture.load (std::memory_order_relaxed))
			return;
		const bool playing = ctx && (ctx->state & Steinberg::Vst::ProcessContext::kPlaying);
		const int64_t pos = ctx ? ctx->projectTimeSamples : -1;
		for (int o = 0; o < n; o += link::kChunkFrames)
		{
			link::AudioChunk& c = chunk;
			c.frames = uint32_t (std::min (link::kChunkFrames, n - o));
			c.channels = uint16_t (nch);
			c.playing = playing ? 1 : 0;
			c.pos = pos >= 0 ? pos + o : -1;
			for (uint32_t i = 0; i < c.frames; ++i)
				for (int ch = 0; ch < nch; ++ch)
					c.data[i * uint32_t (nch) + uint32_t (ch)] = io[ch][o + int (i)];
			slot->ring.push (&c, 1);
		}
	}

	Strip strip;
	int latency = 0;
	const uint64_t instanceId = randomInstanceId ();
	std::shared_ptr<link::ProcessorSlot> slot;
	link::AudioChunk chunk;
	std::array<const params::Info*, kMaxId + 1> infoById {};
	std::array<double, kMaxId + 1> stateValues {}, pendingValues {};
	std::array<bool, kMaxId + 1> pendingMask {};
	std::atomic<bool> hasPending {false};
	bool stateDirty = false;
	std::mutex stateMtx;
	std::string instanceLabel;
};

} // namespace aime::vst
