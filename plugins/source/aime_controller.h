// AIME-Controller: Parameter, Zustandsübernahme, Kanalname (IInfoListener) und
// Parameter-Push aus der AIME-App (Plugin-Link).
#pragma once

#include "aime_link.h"
#include "aime_plugin_desc.h"
#include "aime_processor.h"

#include "base/source/timer.h"
#include "pluginterfaces/base/ustring.h"
#include "pluginterfaces/vst/ivstchannelcontextinfo.h"
#include "public.sdk/source/vst/utility/stringconvert.h"
#include "public.sdk/source/vst/vsteditcontroller.h"

#include <cstdio>
#include <cstdlib>
#include <deque>
#include <mutex>

namespace aime::vst {

class AimeParameter : public Steinberg::Vst::Parameter
{
public:
	AimeParameter (const params::Info& p, bool isBypass) : def (p)
	{
		using namespace Steinberg::Vst;
		info.id = p.id;
		Steinberg::Vst::StringConvert::convert (p.name, info.title);
		Steinberg::Vst::StringConvert::convert (p.key, info.shortTitle);
		Steinberg::Vst::StringConvert::convert (p.unit, info.units);
		info.stepCount = p.stepCount;
		info.defaultNormalizedValue = params::toNormalized (p, p.def);
		info.unitId = kRootUnitId;
		if (p.readonly)
			info.flags = ParameterInfo::kIsReadOnly;
		else
			info.flags = ParameterInfo::kCanAutomate;
		if (p.type == params::Type::Choice)
			info.flags |= ParameterInfo::kIsList;
		if (isBypass)
			info.flags |= ParameterInfo::kIsBypass;
		valueNormalized = info.defaultNormalizedValue;
		precision = 2;
	}
	Steinberg::Vst::ParamValue toPlain (Steinberg::Vst::ParamValue n) const override { return params::fromNormalized (def, n); }
	Steinberg::Vst::ParamValue toNormalized (Steinberg::Vst::ParamValue v) const override { return params::toNormalized (def, v); }
	void toString (Steinberg::Vst::ParamValue n, Steinberg::Vst::String128 out) const override
	{
		const double v = toPlain (n);
		char buf[64];
		if (def.type == params::Type::Choice && def.choices)
			std::snprintf (buf, sizeof (buf), "%s", def.choices[int (std::lround (v))]);
		else if (def.type == params::Type::Bool)
			std::snprintf (buf, sizeof (buf), "%s", v >= 0.5 ? "On" : "Off");
		else if (std::fabs (v) >= 1000)
			std::snprintf (buf, sizeof (buf), "%.0f", v);
		else
			std::snprintf (buf, sizeof (buf), "%.2f", v);
		Steinberg::Vst::StringConvert::convert (buf, out);
	}
	bool fromString (const Steinberg::Vst::TChar* s, Steinberg::Vst::ParamValue& n) const override
	{
		const std::string u8 = Steinberg::Vst::StringConvert::convert (s, 128);
		if (def.type == params::Type::Choice && def.choices)
			for (int i = 0; i <= int (def.max); ++i)
				if (u8 == def.choices[i])
				{
					n = toNormalized (i);
					return true;
				}
		if (def.type == params::Type::Bool && (u8 == "On" || u8 == "Off"))
		{
			n = u8 == "On" ? 1.0 : 0.0;
			return true;
		}
		char* end = nullptr;
		const double v = std::strtod (u8.c_str (), &end);
		if (end == u8.c_str ())
			return false;
		n = toNormalized (v);
		return true;
	}

private:
	const params::Info& def;
};

template <class Desc>
class Controller : public Steinberg::Vst::EditControllerEx1,
                   public Steinberg::Vst::ChannelContext::IInfoListener,
                   public Steinberg::ITimerCallback,
                   public link::ParamSink
{
public:
	static Steinberg::FUnknown* createInstance (void*)
	{
		return static_cast<Steinberg::Vst::IEditController*> (new Controller<Desc>);
	}

	Steinberg::tresult PLUGIN_API initialize (Steinberg::FUnknown* context) override
	{
		const auto r = EditControllerEx1::initialize (context);
		if (r != Steinberg::kResultOk)
			return r;
		for (int i = 0; i < Desc::count (); ++i)
		{
			const auto& p = Desc::params ()[i];
			parameters.addParameter (new AimeParameter (p, p.id == Desc::kBypassId));
		}
		// Timer::create liefert nur auf Windows/macOS einen Timer (Linux: nullptr -> kein Parameter-Push)
		timer = Steinberg::owned (Steinberg::Timer::create (this, 30));
		return Steinberg::kResultOk;
	}

	Steinberg::tresult PLUGIN_API terminate () override
	{
		if (timer)
			timer->stop ();
		timer = nullptr;
		if (instanceId)
			link::Hub::instance ().unregisterController (instanceId, this);
		return EditControllerEx1::terminate ();
	}

	Steinberg::tresult PLUGIN_API setComponentState (Steinberg::IBStream* s) override
	{
		std::vector<uint8_t> bytes;
		std::vector<state::Entry> entries;
		std::string label;
		if (!readAll (s, bytes) || !state::decode (bytes.data (), bytes.size (), entries, label))
			return Steinberg::kResultFalse;
		for (const auto& e : entries)
			if (auto* p = getParameterObject (e.id))
				setParamNormalized (e.id, p->toNormalized (e.value));
		return Steinberg::kResultOk;
	}

	Steinberg::tresult PLUGIN_API notify (Steinberg::Vst::IMessage* msg) override
	{
		if (msg && msg->getMessageID () && std::string (msg->getMessageID ()) == kPairMessageId)
		{
			Steinberg::int64 id = 0;
			if (msg->getAttributes ()->getInt (kPairAttrId, id) == Steinberg::kResultOk && id != 0)
			{
				if (instanceId && instanceId != uint64_t (id))
					link::Hub::instance ().unregisterController (instanceId, this);
				instanceId = uint64_t (id);
				link::Hub::instance ().registerController (instanceId, this);
				publishChannelInfo ();
			}
			return Steinberg::kResultOk;
		}
		return EditControllerEx1::notify (msg);
	}

	// ChannelContext::IInfoListener: Cubase meldet Name/UID der Spur, auf der das Plugin sitzt
	Steinberg::tresult PLUGIN_API setChannelContextInfos (Steinberg::Vst::IAttributeList* list) override
	{
		using namespace Steinberg::Vst;
		if (!list)
			return Steinberg::kResultFalse;
		String128 buf {};
		if (list->getString (ChannelContext::kChannelNameKey, buf, sizeof (buf)) == Steinberg::kResultTrue)
			channelName = Steinberg::Vst::StringConvert::convert (buf, 128);
		String128 uid {};
		if (list->getString (ChannelContext::kChannelUIDKey, uid, sizeof (uid)) == Steinberg::kResultTrue)
			channelUid = Steinberg::Vst::StringConvert::convert (uid, 128);
		publishChannelInfo ();
		return Steinberg::kResultTrue;
	}

	// Link-Thread
	void enqueueParams (const std::vector<std::pair<uint32_t, double>>& values) override
	{
		std::lock_guard<std::mutex> l (queueMtx);
		for (const auto& v : values)
			queue.push_back (v);
	}

	// UI-Thread: Werte wie eine Bedienung im Editor an den Host melden (Automation/Undo/Prozessor)
	void onTimer (Steinberg::Timer*) override
	{
		std::deque<std::pair<uint32_t, double>> todo;
		{
			std::lock_guard<std::mutex> l (queueMtx);
			todo.swap (queue);
		}
		for (const auto& [id, plain] : todo)
		{
			auto* p = getParameterObject (id);
			if (!p || (p->getInfo ().flags & Steinberg::Vst::ParameterInfo::kIsReadOnly))
				continue;
			const auto n = p->toNormalized (plain);
			beginEdit (id);
			setParamNormalized (id, n);
			performEdit (id, n);
			endEdit (id);
		}
	}

	OBJ_METHODS (Controller, EditControllerEx1)
	DEFINE_INTERFACES
		DEF_INTERFACE (Steinberg::Vst::ChannelContext::IInfoListener)
	END_DEFINE_INTERFACES (EditControllerEx1)
	DELEGATE_REFCOUNT (EditControllerEx1)

private:
	void publishChannelInfo ()
	{
		if (!instanceId)
			return;
		const auto name = channelName, uid = channelUid;
		link::Hub::instance ().updateInfo (instanceId, [&] (link::InstanceInfo& i) {
			if (!name.empty ())
				i.channelName = name;
			if (!uid.empty ())
				i.channelUid = uid;
		});
	}

	uint64_t instanceId = 0;
	std::string channelName, channelUid;
	Steinberg::IPtr<Steinberg::Timer> timer;
	std::mutex queueMtx;
	std::deque<std::pair<uint32_t, double>> queue;
};

} // namespace aime::vst
