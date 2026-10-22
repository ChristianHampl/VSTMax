"""Erzeugt .vstpreset-Dateien für die AIME-Plugins.

Dateiformat laut Steinberg VST3 SDK (public.sdk/source/vst/vstpresetfile.cpp):
Header 'VST3' + int32 Version (1) + 32 Byte ASCII-Klassen-ID + int64 Offset der
Chunk-Liste; danach Datenchunks ('Comp' = Komponenten-Zustand); am Ende 'List' +
int32 Anzahl + Einträge (ID, int64 Offset, int64 Größe). Little Endian.

Der Komponenten-Zustand ist das eigene AIME-Format (siehe plugins/common/aime_state.h):
'AIMS' + uint32 Version + uint32 Anzahl + Anzahl x (uint32 Param-ID, float64 Klartextwert)
+ uint32 Länge + UTF-8 Instanz-Label.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path

from integration.protocol import params as P

STATE_MAGIC = b"AIMS"
STATE_VERSION = 1


def encode_state(plugin: str, values: dict[str, float], label: str = "") -> bytes:
    pk = P.by_key(plugin)
    items = sorted((pk[k]["id"], float(v)) for k, v in values.items() if not pk[k].get("readonly"))
    out = bytearray(STATE_MAGIC)
    out += struct.pack("<II", STATE_VERSION, len(items))
    for pid, val in items:
        out += struct.pack("<Id", pid, val)
    lb = label.encode("utf-8")[:255]
    out += struct.pack("<I", len(lb)) + lb
    return bytes(out)


def decode_state(data: bytes) -> tuple[dict[int, float], str]:
    if data[:4] != STATE_MAGIC:
        raise ValueError("Kein AIME-Zustand")
    ver, n = struct.unpack_from("<II", data, 4)
    if ver != STATE_VERSION:
        raise ValueError(f"Unbekannte Zustandsversion {ver}")
    off = 12
    vals = {}
    for _ in range(n):
        pid, val = struct.unpack_from("<Id", data, off)
        vals[pid] = val
        off += 12
    (ln,) = struct.unpack_from("<I", data, off)
    label = data[off + 4: off + 4 + ln].decode("utf-8", "replace")
    return vals, label


def build_preset(plugin: str, values: dict[str, float], label: str = "") -> bytes:
    d = P.definitions()["plugins"][plugin]
    cid = P.class_id_string(d["processor_uid"]).encode("ascii")
    assert len(cid) == 32
    comp = encode_state(plugin, values, label)
    header_size = 4 + 4 + 32 + 8
    body = bytearray()
    body += b"VST3" + struct.pack("<i", 1) + cid + struct.pack("<q", 0)
    comp_off = len(body)
    body += comp
    list_off = len(body)
    body += b"List" + struct.pack("<i", 1) + b"Comp" + struct.pack("<qq", comp_off, len(comp))
    struct.pack_into("<q", body, header_size - 8, list_off)
    return bytes(body)


def parse_preset(data: bytes) -> dict:
    if data[:4] != b"VST3":
        raise ValueError("Keine .vstpreset-Datei")
    (ver,) = struct.unpack_from("<i", data, 4)
    cid = data[8:40].decode("ascii")
    (list_off,) = struct.unpack_from("<q", data, 40)
    if data[list_off:list_off + 4] != b"List":
        raise ValueError("Chunk-Liste fehlt")
    (n,) = struct.unpack_from("<i", data, list_off + 4)
    chunks = {}
    off = list_off + 8
    for _ in range(n):
        cid_ = data[off:off + 4].decode("ascii")
        o, s = struct.unpack_from("<qq", data, off + 4)
        chunks[cid_] = data[o:o + s]
        off += 20
    return {"version": ver, "class_id": cid, "chunks": chunks}


def _safe(name: str) -> str:
    return re.sub(r"[^\w\- ]+", "_", name).strip() or "track"


def export_plan_presets(plan: dict, out_dir: str | Path) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = {"tracks": {}, "buses": {}, "notes": {}}
    for t in plan["tracks"]:
        if not t.get("enabled"):
            continue
        vals, notes = P.channel_params(t)
        p = out / f"AIME Channel - {_safe(t['name'])}.vstpreset"
        p.write_bytes(build_preset("channel", vals, t["name"]))
        written["tracks"][t["id"]] = str(p)
        if notes:
            written["notes"][t["id"]] = notes
    for gid, b in plan.get("buses", {}).items():
        vals, notes = P.bus_params(b)
        p = out / f"AIME Bus - {_safe(gid)}.vstpreset"
        p.write_bytes(build_preset("bus", vals, gid))
        written["buses"][gid] = str(p)
    mvals, mnotes = P.master_params(plan.get("_master_report"), plan.get("master", {}))
    p = out / "AIME Master.vstpreset"
    p.write_bytes(build_preset("master", mvals, "master"))
    written["master"] = str(p)
    if mnotes:
        written["notes"]["master"] = mnotes
    return written
