// Plug-in-Factory: ein Modul (AIME.vst3) mit drei Effekten
#include "aime_controller.h"
#include "aime_processor.h"
#include "version.h"

#include "public.sdk/source/main/pluginfactory.h"

using namespace Steinberg;
using namespace Steinberg::Vst;

using ChannelProcessor = aime::vst::Processor<aime::vst::ChannelDesc>;
using ChannelController = aime::vst::Controller<aime::vst::ChannelDesc>;
using BusProcessor = aime::vst::Processor<aime::vst::BusDesc>;
using BusController = aime::vst::Controller<aime::vst::BusDesc>;
using MasterProcessor = aime::vst::Processor<aime::vst::MasterDesc>;
using MasterController = aime::vst::Controller<aime::vst::MasterDesc>;

BEGIN_FACTORY_DEF (AIME_VENDOR, AIME_URL, AIME_EMAIL)

	DEF_CLASS2 (INLINE_UID_FROM_FUID (aime::vst::ChannelDesc::processorUid ()), PClassInfo::kManyInstances,
	            kVstAudioEffectClass, "AIME Channel", Vst::kDistributable, "Fx|Dynamics|EQ", AIME_VERSION_STR,
	            kVstVersionString, ChannelProcessor::createInstance)
	DEF_CLASS2 (INLINE_UID_FROM_FUID (aime::vst::ChannelDesc::controllerUid ()), PClassInfo::kManyInstances,
	            kVstComponentControllerClass, "AIME Channel Controller", 0, "", AIME_VERSION_STR, kVstVersionString,
	            ChannelController::createInstance)

	DEF_CLASS2 (INLINE_UID_FROM_FUID (aime::vst::BusDesc::processorUid ()), PClassInfo::kManyInstances,
	            kVstAudioEffectClass, "AIME Bus", Vst::kDistributable, "Fx|Dynamics", AIME_VERSION_STR,
	            kVstVersionString, BusProcessor::createInstance)
	DEF_CLASS2 (INLINE_UID_FROM_FUID (aime::vst::BusDesc::controllerUid ()), PClassInfo::kManyInstances,
	            kVstComponentControllerClass, "AIME Bus Controller", 0, "", AIME_VERSION_STR, kVstVersionString,
	            BusController::createInstance)

	DEF_CLASS2 (INLINE_UID_FROM_FUID (aime::vst::MasterDesc::processorUid ()), PClassInfo::kManyInstances,
	            kVstAudioEffectClass, "AIME Master", Vst::kDistributable, "Fx|Mastering", AIME_VERSION_STR,
	            kVstVersionString, MasterProcessor::createInstance)
	DEF_CLASS2 (INLINE_UID_FROM_FUID (aime::vst::MasterDesc::controllerUid ()), PClassInfo::kManyInstances,
	            kVstComponentControllerClass, "AIME Master Controller", 0, "", AIME_VERSION_STR, kVstVersionString,
	            MasterController::createInstance)

END_FACTORY
