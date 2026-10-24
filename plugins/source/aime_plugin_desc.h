// Beschreibung der drei AIME-Plugins für Prozessor/Controller-Templates
#pragma once

#include "aime_strips.h"
#include "pluginterfaces/base/funknown.h"

namespace aime::vst {

struct ChannelDesc
{
	using Strip = ChannelStrip;
	static constexpr const char* kKey = "channel";
	static constexpr bool kSidechain = true;
	static constexpr const params::Info* params () { return params::channel::kParams; }
	static constexpr int count () { return params::channel::kCount; }
	static constexpr uint32_t kMaxId = params::channel::kMaxId;
	static constexpr uint32_t kBypassId = params::channel::kBypass;
	static Steinberg::FUID processorUid ()
	{
		const auto* u = params::channel::kProcessorUid;
		return Steinberg::FUID (u[0], u[1], u[2], u[3]);
	}
	static Steinberg::FUID controllerUid ()
	{
		const auto* u = params::channel::kControllerUid;
		return Steinberg::FUID (u[0], u[1], u[2], u[3]);
	}
	template <typename F>
	static void meters (const Strip& s, F&& out)
	{
		out (params::channel::kMeterGrDb, s.meterGrDb ());
		out (params::channel::kMeterOutDb, s.meterOutDb ());
	}
	static int latency (const Strip&) { return Strip::latencySamples (); }
};

struct BusDesc
{
	using Strip = BusStrip;
	static constexpr const char* kKey = "bus";
	static constexpr bool kSidechain = false;
	static constexpr const params::Info* params () { return params::bus::kParams; }
	static constexpr int count () { return params::bus::kCount; }
	static constexpr uint32_t kMaxId = params::bus::kMaxId;
	static constexpr uint32_t kBypassId = params::bus::kBypass;
	static Steinberg::FUID processorUid ()
	{
		const auto* u = params::bus::kProcessorUid;
		return Steinberg::FUID (u[0], u[1], u[2], u[3]);
	}
	static Steinberg::FUID controllerUid ()
	{
		const auto* u = params::bus::kControllerUid;
		return Steinberg::FUID (u[0], u[1], u[2], u[3]);
	}
	template <typename F>
	static void meters (const Strip& s, F&& out)
	{
		out (params::bus::kMeterGrDb, s.meterGrDb ());
	}
	static int latency (const Strip&) { return Strip::latencySamples (); }
};

struct MasterDesc
{
	using Strip = MasterStrip;
	static constexpr const char* kKey = "master";
	static constexpr bool kSidechain = false;
	static constexpr const params::Info* params () { return params::master::kParams; }
	static constexpr int count () { return params::master::kCount; }
	static constexpr uint32_t kMaxId = params::master::kMaxId;
	static constexpr uint32_t kBypassId = params::master::kBypass;
	static Steinberg::FUID processorUid ()
	{
		const auto* u = params::master::kProcessorUid;
		return Steinberg::FUID (u[0], u[1], u[2], u[3]);
	}
	static Steinberg::FUID controllerUid ()
	{
		const auto* u = params::master::kControllerUid;
		return Steinberg::FUID (u[0], u[1], u[2], u[3]);
	}
	template <typename F>
	static void meters (const Strip& s, F&& out)
	{
		out (params::master::kMeterMomentary, float (s.momentaryLufs ()));
		out (params::master::kMeterShortterm, float (s.shortTermLufs ()));
		out (params::master::kMeterTruePeak, s.meterTruePeakDb ());
		out (params::master::kMeterGrDb, s.meterGrDb ());
	}
	static int latency (const Strip& s) { return s.latencySamples (); }
};

} // namespace aime::vst
