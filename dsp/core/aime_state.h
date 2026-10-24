// AIME-Plugin-Zustand: 'AIMS' + u32 Version + u32 Anzahl + Anzahl x (u32 ID, f64 Klartextwert)
// + u32 Labellänge + UTF-8-Label. Little Endian. Gegenstück: integration/presets/vstpreset.py
#pragma once

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

namespace aime::state {

inline constexpr uint32_t kVersion = 1;

struct Entry
{
	uint32_t id;
	double value;
};

namespace detail {
inline void putU32 (std::vector<uint8_t>& o, uint32_t v)
{
	for (int i = 0; i < 4; ++i)
		o.push_back (uint8_t ((v >> (8 * i)) & 0xFF));
}
inline void putF64 (std::vector<uint8_t>& o, double d)
{
	uint64_t v;
	std::memcpy (&v, &d, 8);
	for (int i = 0; i < 8; ++i)
		o.push_back (uint8_t ((v >> (8 * i)) & 0xFF));
}
inline bool getU32 (const uint8_t* p, size_t n, size_t& off, uint32_t& v)
{
	if (off + 4 > n)
		return false;
	v = 0;
	for (int i = 0; i < 4; ++i)
		v |= uint32_t (p[off + size_t (i)]) << (8 * i);
	off += 4;
	return true;
}
inline bool getF64 (const uint8_t* p, size_t n, size_t& off, double& d)
{
	if (off + 8 > n)
		return false;
	uint64_t v = 0;
	for (int i = 0; i < 8; ++i)
		v |= uint64_t (p[off + size_t (i)]) << (8 * i);
	std::memcpy (&d, &v, 8);
	off += 8;
	return true;
}
} // namespace detail

inline std::vector<uint8_t> encode (const std::vector<Entry>& entries, const std::string& label)
{
	std::vector<uint8_t> o {'A', 'I', 'M', 'S'};
	detail::putU32 (o, kVersion);
	detail::putU32 (o, uint32_t (entries.size ()));
	for (const auto& e : entries)
	{
		detail::putU32 (o, e.id);
		detail::putF64 (o, e.value);
	}
	const size_t len = std::min<size_t> (label.size (), 255);
	detail::putU32 (o, uint32_t (len));
	o.insert (o.end (), label.begin (), label.begin () + long (len));
	return o;
}

// Liefert false bei ungültigen/abgeschnittenen Daten; entries/label bleiben dann unvollständig.
inline bool decode (const uint8_t* p, size_t n, std::vector<Entry>& entries, std::string& label)
{
	entries.clear ();
	label.clear ();
	if (n < 12 || std::memcmp (p, "AIMS", 4) != 0)
		return false;
	size_t off = 4;
	uint32_t ver = 0, count = 0;
	if (!detail::getU32 (p, n, off, ver) || ver != kVersion || !detail::getU32 (p, n, off, count))
		return false;
	if (count > 4096)
		return false;
	for (uint32_t i = 0; i < count; ++i)
	{
		Entry e {};
		if (!detail::getU32 (p, n, off, e.id) || !detail::getF64 (p, n, off, e.value))
			return false;
		entries.push_back (e);
	}
	uint32_t len = 0;
	if (!detail::getU32 (p, n, off, len) || off + len > n)
		return false;
	label.assign (reinterpret_cast<const char*> (p + off), len);
	return true;
}

} // namespace aime::state
