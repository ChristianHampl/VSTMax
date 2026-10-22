"""App-Seite der MIDI-Remote-Bridge (Gegenstück zu AIME/Bridge/AIME_Bridge.js).

Cubase legt nicht offen, wie normierte Fader-/Send-Werte auf dB abgebildet werden. Die Bridge rät
deshalb keine Kurve, sondern regelt über die Anzeige-Rückmeldung des Skripts (z. B. "-6.02 dB")
per Bisektion nach. Ohne Rückmeldung wird ein Wert als "nicht kalibriert" gemeldet statt geraten.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

MAPPING_PATH = Path(__file__).with_name("mapping.json")


def load_mapping() -> dict:
    return json.loads(MAPPING_PATH.read_text(encoding="utf-8"))


class OutPort(Protocol):
    def send(self, data: list[int]) -> None: ...


# --------------------------------------------------------------------------- Kodierung
def encode_text(text: str) -> list[int]:
    out: list[int] = []
    for ch in text[:48]:
        c = ord(ch)
        if c > 0xFFFF:
            c = ord("?")
        out += [(c >> 14) & 0x03, (c >> 7) & 0x7F, c & 0x7F]
    return out


def decode_text(data: list[int]) -> str:
    return "".join(chr((data[i] << 14) | (data[i + 1] << 7) | data[i + 2]) for i in range(0, len(data) - 2, 3))


def parse_db(text: str) -> float | None:
    t = text.strip().lower().replace(",", ".").replace("\u2212", "-")
    if t.startswith("-oo") or t.startswith("-inf") or "∞" in t:
        return float("-inf")
    m = re.search(r"[-+]?\d+(\.\d+)?", t)
    return float(m.group(0)) if m else None


def parse_pan(text: str) -> float | None:
    """Cubase-Panoramaanzeige ("C", "L50", "R100", auch "<C>") -> -1..1."""
    t = text.strip().upper().strip("<>").replace(" ", "")
    if t in ("C", "CENTER", "MITTE"):
        return 0.0
    m = re.match(r"([LR])(\d+(\.\d+)?)", t)
    if not m:
        return None
    v = float(m.group(2)) / 100.0
    return -v if m.group(1) == "L" else v


@dataclass
class SetResult:
    ok: bool
    calibrated: bool
    target: float
    reached: float | None
    normalized: float
    steps: int
    message: str = ""


class MidiRemoteBridge:
    def __init__(self, out_port: OutPort, mapping: dict | None = None, feedback_timeout: float = 0.5):
        self.map = mapping or load_mapping()
        self.out = out_port
        self.timeout = feedback_timeout
        self.titles: dict[int, str] = {}
        self.display: dict[tuple[int, int], str] = {}
        self.values: dict[tuple[int, int], float] = {}
        self.hello: str | None = None
        self._seq = 0
        self._display_seq: dict[tuple[int, int], int] = {}
        self._title_seq = 0
        self._cv = threading.Condition()
        self.sent: list[list[int]] = []

    # ---------------------------------------------------------------- Eingang (vom Skript)
    def on_midi(self, data: list[int]):
        """Von der MIDI-Eingangs-Callback-Funktion aufrufen (beliebiger Thread)."""
        h = self.map["sysex"]["header"]
        if len(data) < len(h) + 4 or list(data[:len(h)]) != h or data[-1] != 0xF7:
            return
        kind, strip, param = data[len(h)], data[len(h) + 1], data[len(h) + 2]
        payload = list(data[len(h) + 3:-1])
        sx = self.map["sysex"]
        with self._cv:
            self._seq += 1
            if kind == sx["title"]:
                self.titles[strip] = decode_text(payload)
                self._title_seq = self._seq
            elif kind == sx["display"]:
                self.display[(strip, param)] = decode_text(payload)
                self._display_seq[(strip, param)] = self._seq
            elif kind == sx["value"] and len(payload) >= 2:
                self.values[(strip, param)] = ((payload[0] << 7) | payload[1]) / 16383.0
            elif kind == sx["hello"]:
                self.hello = decode_text(payload)
            self._cv.notify_all()

    def _wait(self, pred: Callable[[], bool], timeout: float) -> bool:
        end = time.monotonic() + timeout
        with self._cv:
            while not pred():
                left = end - time.monotonic()
                if left <= 0:
                    return False
                self._cv.wait(left)
        return True

    # ---------------------------------------------------------------- Ausgang (zum Skript)
    def _send(self, data: list[int]):
        self.sent.append(list(data))
        self.out.send(list(data))

    def _strip_ch(self, strip: int) -> int:
        if not 0 <= strip < self.map["strips"]:
            raise ValueError(f"Strip {strip} außerhalb 0..{self.map['strips'] - 1}")
        return self.map["strip_channel_base"] + strip

    def set_normalized(self, strip: int, param: str, value: float):
        v = min(1.0, max(0.0, float(value)))
        ch = self._strip_ch(strip)
        if param == "volume" and self.map["volume"]["type"] == "pitchbend":
            iv = int(round(v * 16383))
            self._send([0xE0 | ch, iv & 0x7F, (iv >> 7) & 0x7F])
        else:
            cc = self.map["volume"]["fallback_cc"] if param == "volume" else self.map["cc"][param]
            self._send([0xB0 | ch, cc, int(round(v * 127))])

    def _global(self, name: str, value: int = 127):
        self._send([0xB0 | self.map["global_channel"], self.map["global_cc"][name], value])

    def transport(self, action: str):
        if action not in ("start", "stop", "record", "cycle"):
            raise ValueError(action)
        self._global(action, 127)
        self._global(action, 0)

    def bank(self, direction: int):
        name = "next_bank" if direction > 0 else "prev_bank"
        self._global(name, 127)
        self._global(name, 0)

    def set_switch(self, strip: int, param: str, on: bool):
        if param not in ("mute", "solo"):
            raise ValueError(param)
        self.set_normalized(strip, param, 1.0 if on else 0.0)

    # ---------------------------------------------------------------- kalibriertes Setzen
    def _probe(self, strip: int, param: str, norm: float, parse: Callable[[str], float | None]) -> float | None:
        key = (strip, self.map["params"][param])
        with self._cv:
            before = self._seq
        self.set_normalized(strip, param, norm)
        if not self._wait(lambda: self._display_seq.get(key, 0) > before, self.timeout):
            # Kein neuer Anzeigewert: entweder unverändert (gleicher Rasterwert) oder keine Rückmeldung
            txt = self.display.get(key)
            return parse(txt) if txt is not None and self._display_seq.get(key, 0) else None
        return parse(self.display[key])

    def set_calibrated(self, strip: int, param: str, target: float, tol: float,
                       parse: Callable[[str], float | None], max_steps: int = 18) -> SetResult:
        steps_res = 16383 if (param == "volume" and self.map["volume"]["type"] == "pitchbend") else 127
        lo, hi = 0, steps_res
        best: tuple[float, int, float] | None = None
        n = 0
        for n in range(1, max_steps + 1):
            mid = (lo + hi) // 2
            got = self._probe(strip, param, mid / steps_res, parse)
            if got is None:
                return SetResult(False, False, target, None, mid / steps_res, n,
                                 "Keine Anzeige-Rückmeldung von Cubase (MIDI-Remote-Skript aktiv? Ports korrekt?)")
            err = abs(got - target) if got != float("-inf") else float("inf")
            if best is None or err < best[0]:
                best = (err, mid, got)
            if err <= tol or hi - lo <= 1:
                break
            if got < target:
                lo = mid
            else:
                hi = mid
        err, iv, got = best
        if iv != mid:
            self._probe(strip, param, iv / steps_res, parse)
        ok = err <= max(tol, 0.0) or (hi - lo <= 1)
        return SetResult(ok, True, target, got, iv / steps_res, n,
                         "" if err <= tol else f"Rasterauflösung erreicht (Abweichung {err:.2f})")

    def set_volume_db(self, strip: int, db: float, tol: float = 0.1) -> SetResult:
        return self.set_calibrated(strip, "volume", db, tol, parse_db)

    def set_send_db(self, strip: int, index: int, db: float, tol: float = 0.5) -> SetResult:
        return self.set_calibrated(strip, f"send{index}", db, tol, parse_db)

    def set_pan(self, strip: int, pan: float, tol: float = 0.02) -> SetResult:
        return self.set_calibrated(strip, "pan", pan, tol, parse_pan, max_steps=10)

    # ---------------------------------------------------------------- Navigation
    def bank_titles(self, settle: float | None = None) -> dict[int, str]:
        self._wait(lambda: False, settle if settle is not None else min(self.timeout, 0.2))
        with self._cv:
            return dict(self.titles)

    def locate(self, name: str, max_banks: int = 32) -> int | None:
        """Blättert, bis ein Kanal mit diesem Namen im Bank-Fenster liegt; liefert den Strip-Index."""
        want = name.strip().lower()

        def find():
            for s, t in self.titles.items():
                if t.strip().lower() == want:
                    return s
            return None

        s = find()
        if s is not None:
            return s
        for direction in (-1, +1):
            last = None
            for _ in range(max_banks):
                with self._cv:
                    seq = self._title_seq
                self.bank(direction)
                self._wait(lambda: self._title_seq > seq, self.timeout)
                s = find()
                if s is not None:
                    return s
                snap = tuple(sorted(self.titles.items()))
                if snap == last:
                    break
                last = snap
        return None


# --------------------------------------------------------------------------- echte Ports (optional)
class MidoPorts:
    """Virtuelle Ports über mido + python-rtmidi (z. B. loopMIDI unter Windows)."""

    def __init__(self, mapping: dict | None = None):
        self.map = mapping or load_mapping()

    @staticmethod
    def available() -> dict[str, list[str]]:
        try:
            import mido

            return {"inputs": mido.get_input_names(), "outputs": mido.get_output_names()}
        except Exception as exc:  # Backend (python-rtmidi) fehlt
            return {"error": [str(exc)]}

    def open(self) -> MidiRemoteBridge:
        import mido

        names = self.map["ports"]
        outs, ins = mido.get_output_names(), mido.get_input_names()
        out_name = next((n for n in outs if names["to_cubase"].lower() in n.lower()), None)
        in_name = next((n for n in ins if names["from_cubase"].lower() in n.lower()), None)
        if not out_name or not in_name:
            raise RuntimeError(f"MIDI-Ports '{names['to_cubase']}' / '{names['from_cubase']}' nicht gefunden "
                               f"(vorhanden: {outs} / {ins}). Bitte in loopMIDI anlegen.")
        out = mido.open_output(out_name)

        class _Out:
            def send(self, data):
                out.send(mido.Message.from_bytes(data))

        bridge = MidiRemoteBridge(_Out(), self.map)
        self._in = mido.open_input(in_name, callback=lambda m: bridge.on_midi(m.bytes()))
        self._out = out
        return bridge

    def close(self):
        for p in (getattr(self, "_in", None), getattr(self, "_out", None)):
            if p is not None:
                p.close()
