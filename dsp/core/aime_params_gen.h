// AUTOMATISCH ERZEUGT von scripts/gen_params.py aus integration/protocol/plugin_params.json.
// Nicht von Hand bearbeiten.
#pragma once

#include <cmath>
#include <cstdint>

namespace aime::params {

enum class Type : uint8_t { Linear, Log, Bool, Choice };

struct Info
{
	uint32_t id;
	const char* key;
	const char* name;
	const char* unit;
	Type type;
	double min, max, def;
	bool readonly;
	int stepCount;
	const char* const* choices;
};

inline double clampD (double v, double lo, double hi) { return v < lo ? lo : (v > hi ? hi : v); }

// Identisch zu integration/protocol/params.py (to_normalized/from_normalized)
inline double toNormalized (const Info& p, double plain)
{
	const double v = clampD (plain, p.min, p.max);
	switch (p.type)
	{
		case Type::Log: return std::log (v / p.min) / std::log (p.max / p.min);
		case Type::Bool: return v >= 0.5 ? 1.0 : 0.0;
		case Type::Choice: return p.max > 0 ? std::round (v) / p.max : 0.0;
		default: return (v - p.min) / (p.max - p.min);
	}
}

inline double fromNormalized (const Info& p, double norm)
{
	const double n = clampD (norm, 0.0, 1.0);
	switch (p.type)
	{
		case Type::Log: return p.min * std::exp (n * std::log (p.max / p.min));
		case Type::Bool: return n >= 0.5 ? 1.0 : 0.0;
		case Type::Choice: return std::round (n * p.max);
		default: return p.min + n * (p.max - p.min);
	}
}

inline const Info* find (const Info* list, int count, uint32_t id)
{
	for (int i = 0; i < count; ++i)
		if (list[i].id == id)
			return &list[i];
	return nullptr;
}

namespace channel {

inline constexpr const char* kName = "AIME Channel";
inline constexpr const char* kSubcategory = "Fx|Dynamics|EQ";
inline constexpr uint32_t kProcessorUid[4] = {0x6A1C3E21u, 0x4B7D4F10u, 0x9E2A51C3u, 0x7D0B11A1u};
inline constexpr uint32_t kControllerUid[4] = {0x6A1C3E22u, 0x4B7D4F10u, 0x9E2A51C3u, 0x7D0B11A2u};
inline constexpr const char* kClassIdString = "6A1C3E214B7D4F109E2A51C37D0B11A1";

enum Id : uint32_t
{
	kBypass = 0,
	kTrimDb = 1,
	kPolarityInvert = 2,
	kInvertRight = 3,
	kDcRemove = 4,
	kGateOn = 5,
	kGateThresholdDb = 6,
	kGateRangeDb = 7,
	kGateAttackMs = 8,
	kGateHoldMs = 9,
	kGateReleaseMs = 10,
	kHpfFreq = 11,
	kHpfSteep = 12,
	kLpfFreq = 13,
	kDyn1Sidechain = 14,
	kDyn2Sidechain = 15,
	kAlignDelayMs = 16,
	kEq1Type = 20,
	kEq1Freq = 21,
	kEq1GainDb = 22,
	kEq1Q = 23,
	kEq2Type = 24,
	kEq2Freq = 25,
	kEq2GainDb = 26,
	kEq2Q = 27,
	kEq3Type = 28,
	kEq3Freq = 29,
	kEq3GainDb = 30,
	kEq3Q = 31,
	kEq4Type = 32,
	kEq4Freq = 33,
	kEq4GainDb = 34,
	kEq4Q = 35,
	kEq5Type = 36,
	kEq5Freq = 37,
	kEq5GainDb = 38,
	kEq5Q = 39,
	kEq6Type = 40,
	kEq6Freq = 41,
	kEq6GainDb = 42,
	kEq6Q = 43,
	kEq7Type = 44,
	kEq7Freq = 45,
	kEq7GainDb = 46,
	kEq7Q = 47,
	kEq8Type = 48,
	kEq8Freq = 49,
	kEq8GainDb = 50,
	kEq8Q = 51,
	kDyn1On = 60,
	kDyn1Freq = 61,
	kDyn1Q = 62,
	kDyn1ThresholdDb = 63,
	kDyn1RangeDb = 64,
	kDyn2On = 65,
	kDyn2Freq = 66,
	kDyn2Q = 67,
	kDyn2ThresholdDb = 68,
	kDyn2RangeDb = 69,
	kCompOn = 70,
	kCompThresholdDb = 71,
	kCompRatio = 72,
	kCompAttackMs = 73,
	kCompReleaseMs = 74,
	kCompKneeDb = 75,
	kCompMakeupDb = 76,
	kCompMix = 77,
	kDeessOn = 80,
	kDeessFreq = 81,
	kDeessThresholdDb = 82,
	kDeessRangeDb = 83,
	kSatDriveDb = 85,
	kSatMix = 86,
	kOutputDb = 90,
	kPan = 91,
	kWidth = 92,
	kMeterGrDb = 100,
	kMeterOutDb = 101,
};

inline constexpr const char* kChoicesType[] = {"Off", "Bell", "Low Shelf", "High Shelf"};

inline constexpr int kCount = 78;
inline constexpr uint32_t kMaxId = 101;
inline constexpr Info kParams[kCount] = {
	{0, "bypass", "Bypass", "", Type::Bool, 0.0, 1.0, 0.0, false, 1, nullptr},
	{1, "trim_db", "Input Trim", "dB", Type::Linear, -30.0, 30.0, 0.0, false, 0, nullptr},
	{2, "polarity_invert", "Phase Invert", "", Type::Bool, 0.0, 1.0, 0.0, false, 1, nullptr},
	{3, "invert_right", "Invert Right", "", Type::Bool, 0.0, 1.0, 0.0, false, 1, nullptr},
	{4, "dc_remove", "DC Filter", "", Type::Bool, 0.0, 1.0, 0.0, false, 1, nullptr},
	{5, "gate_on", "Gate On", "", Type::Bool, 0.0, 1.0, 0.0, false, 1, nullptr},
	{6, "gate_threshold_db", "Gate Threshold", "dB", Type::Linear, -90.0, 0.0, -60.0, false, 0, nullptr},
	{7, "gate_range_db", "Gate Range", "dB", Type::Linear, 0.0, 80.0, 40.0, false, 0, nullptr},
	{8, "gate_attack_ms", "Gate Attack", "ms", Type::Log, 0.1, 50.0, 0.5, false, 0, nullptr},
	{9, "gate_hold_ms", "Gate Hold", "ms", Type::Linear, 0.0, 500.0, 40.0, false, 0, nullptr},
	{10, "gate_release_ms", "Gate Release", "ms", Type::Log, 5.0, 2000.0, 100.0, false, 0, nullptr},
	{11, "hpf_freq", "HPF Freq", "Hz", Type::Log, 10.0, 1000.0, 10.0, false, 0, nullptr},
	{12, "hpf_steep", "HPF 24 dB/oct", "", Type::Bool, 0.0, 1.0, 0.0, false, 1, nullptr},
	{13, "lpf_freq", "LPF Freq", "Hz", Type::Log, 1000.0, 22000.0, 22000.0, false, 0, nullptr},
	{14, "dyn1_sidechain", "Dyn 1 Sidechain", "", Type::Bool, 0.0, 1.0, 0.0, false, 1, nullptr},
	{15, "dyn2_sidechain", "Dyn 2 Sidechain", "", Type::Bool, 0.0, 1.0, 0.0, false, 1, nullptr},
	{16, "align_delay_ms", "Align Delay", "ms", Type::Linear, 0.0, 50.0, 0.0, false, 0, nullptr},
	{20, "eq1_type", "EQ 1 Type", "", Type::Choice, 0.0, 3.0, 0.0, false, 3, kChoicesType},
	{21, "eq1_freq", "EQ 1 Freq", "Hz", Type::Log, 20.0, 20000.0, 1000.0, false, 0, nullptr},
	{22, "eq1_gain_db", "EQ 1 Gain", "dB", Type::Linear, -18.0, 18.0, 0.0, false, 0, nullptr},
	{23, "eq1_q", "EQ 1 Q", "", Type::Log, 0.1, 10.0, 1.0, false, 0, nullptr},
	{24, "eq2_type", "EQ 2 Type", "", Type::Choice, 0.0, 3.0, 0.0, false, 3, kChoicesType},
	{25, "eq2_freq", "EQ 2 Freq", "Hz", Type::Log, 20.0, 20000.0, 1000.0, false, 0, nullptr},
	{26, "eq2_gain_db", "EQ 2 Gain", "dB", Type::Linear, -18.0, 18.0, 0.0, false, 0, nullptr},
	{27, "eq2_q", "EQ 2 Q", "", Type::Log, 0.1, 10.0, 1.0, false, 0, nullptr},
	{28, "eq3_type", "EQ 3 Type", "", Type::Choice, 0.0, 3.0, 0.0, false, 3, kChoicesType},
	{29, "eq3_freq", "EQ 3 Freq", "Hz", Type::Log, 20.0, 20000.0, 1000.0, false, 0, nullptr},
	{30, "eq3_gain_db", "EQ 3 Gain", "dB", Type::Linear, -18.0, 18.0, 0.0, false, 0, nullptr},
	{31, "eq3_q", "EQ 3 Q", "", Type::Log, 0.1, 10.0, 1.0, false, 0, nullptr},
	{32, "eq4_type", "EQ 4 Type", "", Type::Choice, 0.0, 3.0, 0.0, false, 3, kChoicesType},
	{33, "eq4_freq", "EQ 4 Freq", "Hz", Type::Log, 20.0, 20000.0, 1000.0, false, 0, nullptr},
	{34, "eq4_gain_db", "EQ 4 Gain", "dB", Type::Linear, -18.0, 18.0, 0.0, false, 0, nullptr},
	{35, "eq4_q", "EQ 4 Q", "", Type::Log, 0.1, 10.0, 1.0, false, 0, nullptr},
	{36, "eq5_type", "EQ 5 Type", "", Type::Choice, 0.0, 3.0, 0.0, false, 3, kChoicesType},
	{37, "eq5_freq", "EQ 5 Freq", "Hz", Type::Log, 20.0, 20000.0, 1000.0, false, 0, nullptr},
	{38, "eq5_gain_db", "EQ 5 Gain", "dB", Type::Linear, -18.0, 18.0, 0.0, false, 0, nullptr},
	{39, "eq5_q", "EQ 5 Q", "", Type::Log, 0.1, 10.0, 1.0, false, 0, nullptr},
	{40, "eq6_type", "EQ 6 Type", "", Type::Choice, 0.0, 3.0, 0.0, false, 3, kChoicesType},
	{41, "eq6_freq", "EQ 6 Freq", "Hz", Type::Log, 20.0, 20000.0, 1000.0, false, 0, nullptr},
	{42, "eq6_gain_db", "EQ 6 Gain", "dB", Type::Linear, -18.0, 18.0, 0.0, false, 0, nullptr},
	{43, "eq6_q", "EQ 6 Q", "", Type::Log, 0.1, 10.0, 1.0, false, 0, nullptr},
	{44, "eq7_type", "EQ 7 Type", "", Type::Choice, 0.0, 3.0, 0.0, false, 3, kChoicesType},
	{45, "eq7_freq", "EQ 7 Freq", "Hz", Type::Log, 20.0, 20000.0, 1000.0, false, 0, nullptr},
	{46, "eq7_gain_db", "EQ 7 Gain", "dB", Type::Linear, -18.0, 18.0, 0.0, false, 0, nullptr},
	{47, "eq7_q", "EQ 7 Q", "", Type::Log, 0.1, 10.0, 1.0, false, 0, nullptr},
	{48, "eq8_type", "EQ 8 Type", "", Type::Choice, 0.0, 3.0, 0.0, false, 3, kChoicesType},
	{49, "eq8_freq", "EQ 8 Freq", "Hz", Type::Log, 20.0, 20000.0, 1000.0, false, 0, nullptr},
	{50, "eq8_gain_db", "EQ 8 Gain", "dB", Type::Linear, -18.0, 18.0, 0.0, false, 0, nullptr},
	{51, "eq8_q", "EQ 8 Q", "", Type::Log, 0.1, 10.0, 1.0, false, 0, nullptr},
	{60, "dyn1_on", "DYN 1 On", "", Type::Bool, 0.0, 1.0, 0.0, false, 1, nullptr},
	{61, "dyn1_freq", "DYN 1 Freq", "Hz", Type::Log, 20.0, 20000.0, 1000.0, false, 0, nullptr},
	{62, "dyn1_q", "DYN 1 Q", "", Type::Log, 0.1, 10.0, 1.4, false, 0, nullptr},
	{63, "dyn1_threshold_db", "DYN 1 Threshold", "dB", Type::Linear, -80.0, 0.0, -30.0, false, 0, nullptr},
	{64, "dyn1_range_db", "DYN 1 Range", "dB", Type::Linear, 0.0, 12.0, 3.0, false, 0, nullptr},
	{65, "dyn2_on", "DYN 2 On", "", Type::Bool, 0.0, 1.0, 0.0, false, 1, nullptr},
	{66, "dyn2_freq", "DYN 2 Freq", "Hz", Type::Log, 20.0, 20000.0, 1000.0, false, 0, nullptr},
	{67, "dyn2_q", "DYN 2 Q", "", Type::Log, 0.1, 10.0, 1.4, false, 0, nullptr},
	{68, "dyn2_threshold_db", "DYN 2 Threshold", "dB", Type::Linear, -80.0, 0.0, -30.0, false, 0, nullptr},
	{69, "dyn2_range_db", "DYN 2 Range", "dB", Type::Linear, 0.0, 12.0, 3.0, false, 0, nullptr},
	{70, "comp_on", "Comp On", "", Type::Bool, 0.0, 1.0, 0.0, false, 1, nullptr},
	{71, "comp_threshold_db", "Comp Threshold", "dB", Type::Linear, -60.0, 0.0, -20.0, false, 0, nullptr},
	{72, "comp_ratio", "Comp Ratio", ":1", Type::Log, 1.0, 20.0, 4.0, false, 0, nullptr},
	{73, "comp_attack_ms", "Comp Attack", "ms", Type::Log, 0.1, 200.0, 10.0, false, 0, nullptr},
	{74, "comp_release_ms", "Comp Release", "ms", Type::Log, 5.0, 2000.0, 120.0, false, 0, nullptr},
	{75, "comp_knee_db", "Comp Knee", "dB", Type::Linear, 0.0, 24.0, 6.0, false, 0, nullptr},
	{76, "comp_makeup_db", "Comp Makeup", "dB", Type::Linear, -12.0, 24.0, 0.0, false, 0, nullptr},
	{77, "comp_mix", "Comp Mix", "", Type::Linear, 0.0, 1.0, 1.0, false, 0, nullptr},
	{80, "deess_on", "DeEsser On", "", Type::Bool, 0.0, 1.0, 0.0, false, 1, nullptr},
	{81, "deess_freq", "DeEsser Freq", "Hz", Type::Log, 2000.0, 12000.0, 5500.0, false, 0, nullptr},
	{82, "deess_threshold_db", "DeEsser Threshold", "dB", Type::Linear, -60.0, 0.0, -30.0, false, 0, nullptr},
	{83, "deess_range_db", "DeEsser Range", "dB", Type::Linear, 0.0, 20.0, 8.0, false, 0, nullptr},
	{85, "sat_drive_db", "Saturation Drive", "dB", Type::Linear, 0.0, 24.0, 0.0, false, 0, nullptr},
	{86, "sat_mix", "Saturation Mix", "", Type::Linear, 0.0, 1.0, 1.0, false, 0, nullptr},
	{90, "output_db", "Output", "dB", Type::Linear, -60.0, 24.0, 0.0, false, 0, nullptr},
	{91, "pan", "Pan (Stereo)", "", Type::Linear, -1.0, 1.0, 0.0, false, 0, nullptr},
	{92, "width", "Width", "", Type::Linear, 0.0, 2.0, 1.0, false, 0, nullptr},
	{100, "meter_gr_db", "GR Meter", "dB", Type::Linear, 0.0, 40.0, 0.0, true, 0, nullptr},
	{101, "meter_out_db", "Output Meter", "dB", Type::Linear, -90.0, 6.0, -90.0, true, 0, nullptr},
};

} // namespace channel

namespace bus {

inline constexpr const char* kName = "AIME Bus";
inline constexpr const char* kSubcategory = "Fx|Dynamics";
inline constexpr uint32_t kProcessorUid[4] = {0x6A1C3E31u, 0x4B7D4F10u, 0x9E2A51C3u, 0x7D0B11B1u};
inline constexpr uint32_t kControllerUid[4] = {0x6A1C3E32u, 0x4B7D4F10u, 0x9E2A51C3u, 0x7D0B11B2u};
inline constexpr const char* kClassIdString = "6A1C3E314B7D4F109E2A51C37D0B11B1";

enum Id : uint32_t
{
	kBypass = 0,
	kInputDb = 1,
	kCompOn = 2,
	kCompThresholdDb = 3,
	kCompRatio = 4,
	kCompAttackMs = 5,
	kCompReleaseMs = 6,
	kCompKneeDb = 7,
	kCompMakeupDb = 8,
	kParAmount = 10,
	kParThresholdDb = 11,
	kParRatio = 12,
	kParAttackMs = 13,
	kParReleaseMs = 14,
	kParMakeupDb = 15,
	kParDriveDb = 16,
	kSatDriveDb = 20,
	kOutputDb = 21,
	kMeterGrDb = 100,
};

inline constexpr int kCount = 19;
inline constexpr uint32_t kMaxId = 100;
inline constexpr Info kParams[kCount] = {
	{0, "bypass", "Bypass", "", Type::Bool, 0.0, 1.0, 0.0, false, 1, nullptr},
	{1, "input_db", "Input", "dB", Type::Linear, -30.0, 30.0, 0.0, false, 0, nullptr},
	{2, "comp_on", "Comp On", "", Type::Bool, 0.0, 1.0, 0.0, false, 1, nullptr},
	{3, "comp_threshold_db", "Comp Threshold", "dB", Type::Linear, -60.0, 0.0, -20.0, false, 0, nullptr},
	{4, "comp_ratio", "Comp Ratio", ":1", Type::Log, 1.0, 20.0, 2.0, false, 0, nullptr},
	{5, "comp_attack_ms", "Comp Attack", "ms", Type::Log, 0.1, 200.0, 30.0, false, 0, nullptr},
	{6, "comp_release_ms", "Comp Release", "ms", Type::Log, 5.0, 2000.0, 200.0, false, 0, nullptr},
	{7, "comp_knee_db", "Comp Knee", "dB", Type::Linear, 0.0, 24.0, 6.0, false, 0, nullptr},
	{8, "comp_makeup_db", "Comp Makeup", "dB", Type::Linear, -12.0, 24.0, 0.0, false, 0, nullptr},
	{10, "par_amount", "Parallel Amount", "", Type::Linear, 0.0, 1.0, 0.0, false, 0, nullptr},
	{11, "par_threshold_db", "Parallel Threshold", "dB", Type::Linear, -60.0, 0.0, -30.0, false, 0, nullptr},
	{12, "par_ratio", "Parallel Ratio", ":1", Type::Log, 1.0, 20.0, 10.0, false, 0, nullptr},
	{13, "par_attack_ms", "Parallel Attack", "ms", Type::Log, 0.1, 200.0, 1.0, false, 0, nullptr},
	{14, "par_release_ms", "Parallel Release", "ms", Type::Log, 5.0, 2000.0, 80.0, false, 0, nullptr},
	{15, "par_makeup_db", "Parallel Makeup", "dB", Type::Linear, -12.0, 24.0, 10.0, false, 0, nullptr},
	{16, "par_drive_db", "Parallel Drive", "dB", Type::Linear, 0.0, 24.0, 3.0, false, 0, nullptr},
	{20, "sat_drive_db", "Saturation Drive", "dB", Type::Linear, 0.0, 24.0, 0.0, false, 0, nullptr},
	{21, "output_db", "Output", "dB", Type::Linear, -60.0, 24.0, 0.0, false, 0, nullptr},
	{100, "meter_gr_db", "GR Meter", "dB", Type::Linear, 0.0, 40.0, 0.0, true, 0, nullptr},
};

} // namespace bus

namespace master {

inline constexpr const char* kName = "AIME Master";
inline constexpr const char* kSubcategory = "Fx|Mastering";
inline constexpr uint32_t kProcessorUid[4] = {0x6A1C3E41u, 0x4B7D4F10u, 0x9E2A51C3u, 0x7D0B11C1u};
inline constexpr uint32_t kControllerUid[4] = {0x6A1C3E42u, 0x4B7D4F10u, 0x9E2A51C3u, 0x7D0B11C2u};
inline constexpr const char* kClassIdString = "6A1C3E414B7D4F109E2A51C37D0B11C1";

enum Id : uint32_t
{
	kBypass = 0,
	kInputDb = 1,
	kEq1Type = 10,
	kEq1Freq = 11,
	kEq1GainDb = 12,
	kEq1Q = 13,
	kEq2Type = 14,
	kEq2Freq = 15,
	kEq2GainDb = 16,
	kEq2Q = 17,
	kEq3Type = 18,
	kEq3Freq = 19,
	kEq3GainDb = 20,
	kEq3Q = 21,
	kEq4Type = 22,
	kEq4Freq = 23,
	kEq4GainDb = 24,
	kEq4Q = 25,
	kCompOn = 30,
	kCompThresholdDb = 31,
	kCompRatio = 32,
	kCompAttackMs = 33,
	kCompReleaseMs = 34,
	kCompKneeDb = 35,
	kCompMakeupDb = 36,
	kLimiterGainDb = 39,
	kLimiterOn = 40,
	kCeilingDbtp = 41,
	kLimiterReleaseMs = 42,
	kOutputDb = 50,
	kMeterMomentary = 100,
	kMeterShortterm = 101,
	kMeterTruePeak = 102,
	kMeterGrDb = 103,
};

inline constexpr const char* kChoicesType[] = {"Off", "Bell", "Low Shelf", "High Shelf"};

inline constexpr int kCount = 34;
inline constexpr uint32_t kMaxId = 103;
inline constexpr Info kParams[kCount] = {
	{0, "bypass", "Bypass", "", Type::Bool, 0.0, 1.0, 0.0, false, 1, nullptr},
	{1, "input_db", "Input Gain", "dB", Type::Linear, -30.0, 30.0, 0.0, false, 0, nullptr},
	{10, "eq1_type", "EQ 1 Type", "", Type::Choice, 0.0, 3.0, 0.0, false, 3, kChoicesType},
	{11, "eq1_freq", "EQ 1 Freq", "Hz", Type::Log, 20.0, 20000.0, 1000.0, false, 0, nullptr},
	{12, "eq1_gain_db", "EQ 1 Gain", "dB", Type::Linear, -6.0, 6.0, 0.0, false, 0, nullptr},
	{13, "eq1_q", "EQ 1 Q", "", Type::Log, 0.1, 10.0, 0.7, false, 0, nullptr},
	{14, "eq2_type", "EQ 2 Type", "", Type::Choice, 0.0, 3.0, 0.0, false, 3, kChoicesType},
	{15, "eq2_freq", "EQ 2 Freq", "Hz", Type::Log, 20.0, 20000.0, 1000.0, false, 0, nullptr},
	{16, "eq2_gain_db", "EQ 2 Gain", "dB", Type::Linear, -6.0, 6.0, 0.0, false, 0, nullptr},
	{17, "eq2_q", "EQ 2 Q", "", Type::Log, 0.1, 10.0, 0.7, false, 0, nullptr},
	{18, "eq3_type", "EQ 3 Type", "", Type::Choice, 0.0, 3.0, 0.0, false, 3, kChoicesType},
	{19, "eq3_freq", "EQ 3 Freq", "Hz", Type::Log, 20.0, 20000.0, 1000.0, false, 0, nullptr},
	{20, "eq3_gain_db", "EQ 3 Gain", "dB", Type::Linear, -6.0, 6.0, 0.0, false, 0, nullptr},
	{21, "eq3_q", "EQ 3 Q", "", Type::Log, 0.1, 10.0, 0.7, false, 0, nullptr},
	{22, "eq4_type", "EQ 4 Type", "", Type::Choice, 0.0, 3.0, 0.0, false, 3, kChoicesType},
	{23, "eq4_freq", "EQ 4 Freq", "Hz", Type::Log, 20.0, 20000.0, 1000.0, false, 0, nullptr},
	{24, "eq4_gain_db", "EQ 4 Gain", "dB", Type::Linear, -6.0, 6.0, 0.0, false, 0, nullptr},
	{25, "eq4_q", "EQ 4 Q", "", Type::Log, 0.1, 10.0, 0.7, false, 0, nullptr},
	{30, "comp_on", "Comp On", "", Type::Bool, 0.0, 1.0, 0.0, false, 1, nullptr},
	{31, "comp_threshold_db", "Comp Threshold", "dB", Type::Linear, -60.0, 0.0, -20.0, false, 0, nullptr},
	{32, "comp_ratio", "Comp Ratio", ":1", Type::Log, 1.0, 10.0, 1.8, false, 0, nullptr},
	{33, "comp_attack_ms", "Comp Attack", "ms", Type::Log, 0.1, 200.0, 30.0, false, 0, nullptr},
	{34, "comp_release_ms", "Comp Release", "ms", Type::Log, 5.0, 2000.0, 250.0, false, 0, nullptr},
	{35, "comp_knee_db", "Comp Knee", "dB", Type::Linear, 0.0, 24.0, 8.0, false, 0, nullptr},
	{36, "comp_makeup_db", "Comp Makeup", "dB", Type::Linear, -12.0, 24.0, 0.0, false, 0, nullptr},
	{39, "limiter_gain_db", "Limiter Drive", "dB", Type::Linear, -12.0, 30.0, 0.0, false, 0, nullptr},
	{40, "limiter_on", "Limiter On", "", Type::Bool, 0.0, 1.0, 1.0, false, 1, nullptr},
	{41, "ceiling_dbtp", "Ceiling (dBTP)", "dB", Type::Linear, -6.0, 0.0, -1.0, false, 0, nullptr},
	{42, "limiter_release_ms", "Limiter Release", "ms", Type::Log, 5.0, 1000.0, 60.0, false, 0, nullptr},
	{50, "output_db", "Output", "dB", Type::Linear, -30.0, 6.0, 0.0, false, 0, nullptr},
	{100, "meter_momentary", "Momentary LUFS", "LUFS", Type::Linear, -70.0, 0.0, -70.0, true, 0, nullptr},
	{101, "meter_shortterm", "Short-term LUFS", "LUFS", Type::Linear, -70.0, 0.0, -70.0, true, 0, nullptr},
	{102, "meter_true_peak", "True Peak Max", "dBTP", Type::Linear, -70.0, 6.0, -70.0, true, 0, nullptr},
	{103, "meter_gr_db", "Limiter GR", "dB", Type::Linear, 0.0, 40.0, 0.0, true, 0, nullptr},
};

} // namespace master

} // namespace aime::params
