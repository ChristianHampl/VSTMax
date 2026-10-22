"""Erzeugt dsp/core/aime_params_gen.h aus integration/protocol/plugin_params.json.

Aufruf:  python scripts/gen_params.py          (schreibt die Datei)
         python scripts/gen_params.py --check  (Exit-Code 1, wenn die Datei veraltet ist)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from integration.protocol import params as P  # noqa: E402

OUT = ROOT / "dsp" / "core" / "aime_params_gen.h"
TYPES = {"linear": "Type::Linear", "log": "Type::Log", "bool": "Type::Bool", "choice": "Type::Choice"}


def camel(key: str) -> str:
    return "k" + "".join(part[:1].upper() + part[1:] for part in key.split("_"))


def cstr(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def num(v: float) -> str:
    r = repr(float(v))
    return r if ("." in r or "e" in r) else r + ".0"


def generate() -> str:
    d = P.definitions()
    lines = [
        "// AUTOMATISCH ERZEUGT von scripts/gen_params.py aus integration/protocol/plugin_params.json.",
        "// Nicht von Hand bearbeiten.",
        "#pragma once",
        "",
        "#include <cmath>",
        "#include <cstdint>",
        "",
        "namespace aime::params {",
        "",
        "enum class Type : uint8_t { Linear, Log, Bool, Choice };",
        "",
        "struct Info",
        "{",
        "\tuint32_t id;",
        "\tconst char* key;",
        "\tconst char* name;",
        "\tconst char* unit;",
        "\tType type;",
        "\tdouble min, max, def;",
        "\tbool readonly;",
        "\tint stepCount;",
        "\tconst char* const* choices;",
        "};",
        "",
        "inline double clampD (double v, double lo, double hi) { return v < lo ? lo : (v > hi ? hi : v); }",
        "",
        "// Identisch zu integration/protocol/params.py (to_normalized/from_normalized)",
        "inline double toNormalized (const Info& p, double plain)",
        "{",
        "\tconst double v = clampD (plain, p.min, p.max);",
        "\tswitch (p.type)",
        "\t{",
        "\t\tcase Type::Log: return std::log (v / p.min) / std::log (p.max / p.min);",
        "\t\tcase Type::Bool: return v >= 0.5 ? 1.0 : 0.0;",
        "\t\tcase Type::Choice: return p.max > 0 ? std::round (v) / p.max : 0.0;",
        "\t\tdefault: return (v - p.min) / (p.max - p.min);",
        "\t}",
        "}",
        "",
        "inline double fromNormalized (const Info& p, double norm)",
        "{",
        "\tconst double n = clampD (norm, 0.0, 1.0);",
        "\tswitch (p.type)",
        "\t{",
        "\t\tcase Type::Log: return p.min * std::exp (n * std::log (p.max / p.min));",
        "\t\tcase Type::Bool: return n >= 0.5 ? 1.0 : 0.0;",
        "\t\tcase Type::Choice: return std::round (n * p.max);",
        "\t\tdefault: return p.min + n * (p.max - p.min);",
        "\t}",
        "}",
        "",
        "inline const Info* find (const Info* list, int count, uint32_t id)",
        "{",
        "\tfor (int i = 0; i < count; ++i)",
        "\t\tif (list[i].id == id)",
        "\t\t\treturn &list[i];",
        "\treturn nullptr;",
        "}",
        "",
    ]
    for plugin, pd in d["plugins"].items():
        ps = P.expand(plugin)
        lines.append(f"namespace {plugin} {{")
        lines.append("")
        lines.append(f"inline constexpr const char* kName = {cstr(pd['name'])};")
        lines.append(f"inline constexpr const char* kSubcategory = {cstr(pd['subcategory'])};")
        for nm, uid in (("kProcessorUid", pd["processor_uid"]), ("kControllerUid", pd["controller_uid"])):
            lines.append(f"inline constexpr uint32_t {nm}[4] = {{" + ", ".join(f"0x{u.upper()}u" for u in uid) + "};")
        lines.append(f"inline constexpr const char* kClassIdString = {cstr(P.class_id_string(pd['processor_uid']))};")
        lines.append("")
        lines.append("enum Id : uint32_t")
        lines.append("{")
        for p in ps:
            lines.append(f"\t{camel(p['key'])} = {p['id']},")
        lines.append("};")
        lines.append("")
        choice_sets = {}
        for p in ps:
            if p["type"] == "choice":
                name = "kChoices" + camel(p["key"].split("_", 1)[1] if p["key"][0:2] in ("eq",) else p["key"])[1:]
                choice_sets.setdefault(tuple(p["choices"]), name)
        for ch, name in choice_sets.items():
            lines.append(f"inline constexpr const char* {name}[] = {{" + ", ".join(cstr(c) for c in ch) + "};")
        if choice_sets:
            lines.append("")
        lines.append(f"inline constexpr int kCount = {len(ps)};")
        lines.append(f"inline constexpr uint32_t kMaxId = {max(p['id'] for p in ps)};")
        lines.append("inline constexpr Info kParams[kCount] = {")
        for p in ps:
            if p["type"] == "bool":
                steps = 1
            elif p["type"] == "choice":
                steps = len(p["choices"]) - 1
            else:
                steps = 0
            choices = choice_sets[tuple(p["choices"])] if p["type"] == "choice" else "nullptr"
            lines.append(
                f"\t{{{p['id']}, {cstr(p['key'])}, {cstr(p['name'])}, {cstr(p['unit'])}, {TYPES[p['type']]}, "
                f"{num(p['min'])}, {num(p['max'])}, {num(p['default'])}, {'true' if p.get('readonly') else 'false'}, "
                f"{steps}, {choices}}},"
            )
        lines.append("};")
        lines.append("")
        lines.append(f"}} // namespace {plugin}")
        lines.append("")
    lines.append("} // namespace aime::params")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    text = generate()
    if "--check" in sys.argv:
        cur = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if cur != text:
            print(f"{OUT} ist veraltet - 'python scripts/gen_params.py' ausführen", file=sys.stderr)
            return 1
        print("aime_params_gen.h ist aktuell")
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"geschrieben: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
