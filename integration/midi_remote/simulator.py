"""TESTDOUBLE: simuliert das Verhalten des MIDI-Remote-Skripts samt MixConsole.

Dient ausschließlich automatisierten Tests der Bridge-Logik (Kodierung, Bisektion, Bank-Navigation).
Die Fader-/Send-Kurven sind frei erfunden und bewusst NICHT die von Cubase. Ein bestandener Test mit
diesem Simulator ist kein Nachweis, dass Cubase sich genauso verhält.
"""

from __future__ import annotations

import math

from .bridge import MidiRemoteBridge, encode_text, load_mapping


def _fake_fader_db(n: float) -> float:
    if n <= 0:
        return float("-inf")
    return 6.0 + 40.0 * math.log10(n) if n > 0.25 else 6.0 + 40.0 * math.log10(0.25) - (0.25 - n) * 200


class CubaseSimulator:
    def __init__(self, channel_names: list[str], mapping: dict | None = None):
        self.map = mapping or load_mapping()
        self.channels = [{"name": n, "volume": 0.8, "pan": 0.5, "mute": 0.0, "solo": 0.0, "send1": 0.0, "send2": 0.0}
                         for n in channel_names]
        self.offset = 0
        self.transport: list[str] = []
        self.bridge: MidiRemoteBridge | None = None

    def attach(self, bridge: MidiRemoteBridge):
        self.bridge = bridge
        self._emit(self.map["sysex"]["hello"], 0, self.map["version"], encode_text("AIME Bridge (Simulator)"))
        self._bank_changed()

    # Port-Schnittstelle der Bridge (App -> "Cubase")
    def send(self, data: list[int]):
        st, d1 = data[0], data[1]
        ch = st & 0x0F
        if st & 0xF0 == 0xE0:
            self._set(ch - self.map["strip_channel_base"], "volume", ((data[2] << 7) | d1) / 16383)
        elif st & 0xF0 == 0xB0 and ch == self.map["global_channel"]:
            if data[2] < 64:
                return
            name = {v: k for k, v in self.map["global_cc"].items()}.get(d1)
            if name == "next_bank" and self.offset + self.map["strips"] < len(self.channels):
                self.offset += self.map["strips"]
                self._bank_changed()
            elif name == "prev_bank" and self.offset > 0:
                self.offset = max(0, self.offset - self.map["strips"])
                self._bank_changed()
            elif name in ("start", "stop", "record", "cycle"):
                self.transport.append(name)
        elif st & 0xF0 == 0xB0:
            names = {v: k for k, v in self.map["cc"].items()}
            if self.map["volume"]["type"] != "pitchbend":
                names[self.map["volume"]["fallback_cc"]] = "volume"
            if d1 in names:
                self._set(ch - self.map["strip_channel_base"], names[d1], data[2] / 127)

    def _channel(self, strip: int):
        i = self.offset + strip
        return self.channels[i] if 0 <= strip < self.map["strips"] and i < len(self.channels) else None

    def _set(self, strip: int, param: str, v: float):
        c = self._channel(strip)
        if c is None:
            return
        if param in ("mute", "solo"):
            v = 1.0 if v >= 0.5 else 0.0
        changed = c[param] != v
        c[param] = v
        if changed:
            self._feedback(strip, param)

    def display_text(self, c: dict, param: str) -> str:
        v = c[param]
        if param == "volume" or param.startswith("send"):
            db = _fake_fader_db(v)
            return "-oo dB" if db == float("-inf") else f"{db:.2f} dB"
        if param == "pan":
            p = round((v - 0.5) * 200)
            return "C" if p == 0 else (f"L{-p}" if p < 0 else f"R{p}")
        return "On" if v >= 0.5 else "Off"

    def _feedback(self, strip: int, param: str):
        c = self._channel(strip)
        pid = self.map["params"][param]
        self._emit(self.map["sysex"]["display"], strip, pid, encode_text(self.display_text(c, param)))
        iv = int(round(c[param] * 16383))
        self._emit(self.map["sysex"]["value"], strip, pid, [(iv >> 7) & 0x7F, iv & 0x7F])

    def _bank_changed(self):
        for s in range(self.map["strips"]):
            c = self._channel(s)
            self._emit(self.map["sysex"]["title"], s, 0, encode_text(c["name"] if c else ""))
            if c:
                for p in self.map["params"]:
                    self._feedback(s, p)

    def _emit(self, kind: int, strip: int, param: int, payload: list[int]):
        if self.bridge:
            self.bridge.on_midi(self.map["sysex"]["header"] + [kind, strip, param] + payload + [0xF7])

    def channel(self, name: str) -> dict:
        return next(c for c in self.channels if c["name"] == name)
