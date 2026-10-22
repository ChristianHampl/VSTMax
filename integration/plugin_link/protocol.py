"""Plugin-Link-Protokoll (Gegenstück zu plugins/source/aime_link.h).

Rahmen: u32 Länge (Typ + Nutzdaten, Little Endian) | u8 Typ | Nutzdaten.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass

import numpy as np

DEFAULT_PORT = 47800
PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 16 * 1024 * 1024

HELLO, INSTANCE_ADD, INSTANCE_UPDATE, INSTANCE_REMOVE, AUDIO = 1, 2, 3, 4, 5
SET_PARAMS, CAPTURE, PING = 20, 21, 22

_AUDIO_HDR = struct.Struct("<QqIHBB")


class ProtocolError(ValueError):
    pass


def frame(msg_type: int, payload: bytes = b"") -> bytes:
    return struct.pack("<IB", len(payload) + 1, msg_type) + payload


class FrameReader:
    """Zerlegt einen Bytestrom in (Typ, Nutzdaten)-Nachrichten."""

    def __init__(self):
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[tuple[int, bytes]]:
        self._buf += data
        out = []
        while len(self._buf) >= 5:
            (n,) = struct.unpack_from("<I", self._buf, 0)
            if n == 0 or n > MAX_MESSAGE_BYTES:
                raise ProtocolError(f"ungültige Rahmenlänge {n}")
            if len(self._buf) - 4 < n:
                break
            out.append((self._buf[4], bytes(self._buf[5:4 + n])))
            del self._buf[:4 + n]
        return out


def encode_set_params(instance: int, values: dict[int, float]) -> bytes:
    items = sorted(values.items())
    body = struct.pack("<QI", instance, len(items))
    body += b"".join(struct.pack("<Id", int(k), float(v)) for k, v in items)
    return frame(SET_PARAMS, body)


def encode_capture(on: bool) -> bytes:
    return frame(CAPTURE, bytes([1 if on else 0]))


@dataclass
class AudioChunk:
    instance: int
    pos: int
    playing: bool
    samples: np.ndarray  # (frames, channels) float32


def decode_audio(payload: bytes) -> AudioChunk:
    if len(payload) < _AUDIO_HDR.size:
        raise ProtocolError("Audio-Nachricht zu kurz")
    inst, pos, frames, ch, playing, _ = _AUDIO_HDR.unpack_from(payload, 0)
    if ch not in (1, 2) or len(payload) != _AUDIO_HDR.size + frames * ch * 4:
        raise ProtocolError("Audio-Nachricht inkonsistent")
    data = np.frombuffer(payload, dtype="<f4", offset=_AUDIO_HDR.size).reshape(frames, ch)
    return AudioChunk(inst, pos, bool(playing), data)


def encode_audio(instance: int, pos: int, samples: np.ndarray, playing: bool = True) -> bytes:
    """Nur für Tests/Simulation (die echte Gegenseite ist das Plug-in)."""
    s = np.ascontiguousarray(samples, dtype="<f4")
    return frame(AUDIO, _AUDIO_HDR.pack(instance, pos, s.shape[0], s.shape[1], int(playing), 0) + s.tobytes())


def decode_json(payload: bytes) -> dict:
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"ungültiges JSON: {exc}") from exc


def instance_int(hex_id: str) -> int:
    return int(hex_id, 16)
