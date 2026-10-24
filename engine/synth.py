"""Synthetische Rock/Metal-Testspuren (keine fremden Aufnahmen nötig).

Erzeugt einen kurzen Song mit Kick, Snare, Toms, Overheads, Room, Bass, zwei echten
Rhythmusgitarren-Doubles, Leadgitarre, Lead-Vocal (mit Sibilanten) und optionalen
Problemspuren (Clipping, DC-Offset, gegenphasiges Stereo).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy.signal import lfilter

from .audio_io import write_audio
from .dsp import biquad_coeffs, convolve_stereo, make_reverb_ir


def _env(n: int, sr: int, attack_s: float, decay_s: float) -> np.ndarray:
    t = np.arange(n) / sr
    a = np.clip(t / max(attack_s, 1e-4), 0, 1)
    return a * np.exp(-t / max(decay_s, 1e-4))


def _filt(x, kind, f, sr, q=0.707, g=0.0):
    b, a = biquad_coeffs(kind, f, sr, g, q)
    return lfilter(b, a, x)


def _place(buf: np.ndarray, sig: np.ndarray, pos: int):
    if pos >= len(buf):
        return
    if pos < 0:
        sig = sig[-pos:]
        pos = 0
    end = min(len(buf), pos + len(sig))
    buf[pos:end] += sig[: end - pos]


class SongSynth:
    def __init__(self, sr: int = 48000, bpm: float = 120.0, bars: int = 8, seed: int = 1):
        self.sr = sr
        self.bpm = bpm
        self.bars = bars
        self.beat = 60.0 / bpm
        self.n = int(sr * self.beat * 4 * bars) + sr  # +1 s Ausklang
        self.rng = np.random.default_rng(seed)
        # Akkordfolge (Grundton in Hz) pro Takt: E, E, C, D ...
        roots = [41.20, 41.20, 32.70, 36.71]
        self.bar_roots = [roots[i % 4] for i in range(bars)]

    def t(self, beat_index: float) -> int:
        return int(beat_index * self.beat * self.sr)

    # ---------------------------------------------------------------- Drums
    def kick_hit(self) -> np.ndarray:
        sr = self.sr
        n = int(0.35 * sr)
        t = np.arange(n) / sr
        f = 50 + 110 * np.exp(-t / 0.025)
        body = np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t / 0.12)
        click = _filt(self.rng.standard_normal(n), "bandpass", 4000, sr, 0.9) * np.exp(-t / 0.004)
        return 0.9 * body + 0.5 * click

    def snare_hit(self) -> np.ndarray:
        sr = self.sr
        n = int(0.3 * sr)
        t = np.arange(n) / sr
        body = np.sin(2 * np.pi * 190 * t) * np.exp(-t / 0.05)
        noise = _filt(self.rng.standard_normal(n), "bandpass", 2500, sr, 0.5) * np.exp(-t / 0.09)
        return 0.6 * body + 0.7 * noise

    def tom_hit(self, f0: float) -> np.ndarray:
        sr = self.sr
        n = int(0.6 * sr)
        t = np.arange(n) / sr
        f = f0 * (1 + 0.3 * np.exp(-t / 0.03))
        return np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t / 0.25) * 0.8

    def hat_hit(self, open_: bool = False) -> np.ndarray:
        sr = self.sr
        n = int((0.4 if open_ else 0.08) * sr)
        t = np.arange(n) / sr
        x = _filt(self.rng.standard_normal(n), "hpf", 7000, sr)
        return x * np.exp(-t / (0.15 if open_ else 0.02)) * 0.35

    def crash_hit(self) -> np.ndarray:
        sr = self.sr
        n = int(2.0 * sr)
        t = np.arange(n) / sr
        x = _filt(self.rng.standard_normal(n), "hpf", 3500, sr)
        return x * np.exp(-t / 0.8) * 0.3

    def drums(self) -> dict[str, np.ndarray]:
        n, sr = self.n, self.sr
        kick, snare, toms = np.zeros(n), np.zeros(n), np.zeros(n)
        hats, cym = np.zeros(n), np.zeros(n)
        total_beats = self.bars * 4
        for b in range(total_beats):
            bar = b // 4
            fill = bar == self.bars - 1 and (b % 4) >= 2
            if not fill:
                _place(kick, self.kick_hit() * self.rng.uniform(0.9, 1.0), self.t(b))
                if bar >= self.bars // 2:  # Chorus: Double-Kick-Achtel
                    _place(kick, self.kick_hit() * 0.85, self.t(b + 0.5))
                if b % 2 == 1:
                    _place(snare, self.snare_hit() * self.rng.uniform(0.9, 1.0), self.t(b))
                for e in range(2):
                    _place(hats, self.hat_hit(open_=(e == 1 and b % 4 == 3)), self.t(b + e * 0.5))
            else:
                for k, f0 in enumerate([150, 120, 95, 80]):
                    _place(toms, self.tom_hit(f0), self.t(b + k * 0.25 - (b % 4 - 2) * 0))
            if b % 16 == 0:
                _place(cym, self.crash_hit(), self.t(b))
        # Overheads: Becken + gedämpftes Übersprechen von Kick/Snare/Toms, Stereo
        oh_l = cym * 0.9 + hats * 0.7 + 0.25 * snare + 0.12 * kick + 0.2 * toms
        oh_r = cym * 0.7 + hats * 1.0 + 0.22 * snare + 0.12 * kick + 0.15 * toms
        d = int(0.0025 * sr)
        oh = np.column_stack([oh_l, np.concatenate([np.zeros(d), oh_r[:-d]])])
        oh[:, 0] += 0.02 * self.rng.standard_normal(n) * 0.05
        oh = np.column_stack([_filt(oh[:, 0], "hpf", 150, sr), _filt(oh[:, 1], "hpf", 150, sr)])
        room_src = np.column_stack([kick + snare + toms + 0.5 * hats + cym, kick + snare + toms + 0.5 * hats + cym])
        room = convolve_stereo(room_src, make_reverb_ir(sr, 0.9, 8, 5000, seed=3)) * 0.25
        # leichtes Übersprechen auf Tom-Spur (Gate-relevant)
        toms = toms + 0.01 * (snare + kick)
        return {"kick": kick, "snare": snare, "toms": toms, "overheads": oh, "room": room}

    # ----------------------------------------------------------------- Bass/Git
    def _saw(self, f: float, n: int, phase: float = 0.0, harmonics: int = 30) -> np.ndarray:
        t = np.arange(n) / self.sr
        x = np.zeros(n)
        for k in range(1, harmonics + 1):
            if f * k > 0.45 * self.sr:
                break
            x += np.sin(2 * np.pi * f * k * t + phase * k) / k
        return x

    def bass(self) -> np.ndarray:
        n, sr = self.n, self.sr
        out = np.zeros(n)
        for bar, root in enumerate(self.bar_roots):
            for e in range(8):
                ln = int(self.beat * 0.5 * sr * 0.95)
                note = self._saw(root, ln, harmonics=40) * _env(ln, sr, 0.003, 0.4)
                _place(out, note, self.t(bar * 4 + e * 0.5))
        out = _filt(out, "lpf", 1800, sr)
        return _filt(np.tanh(out * 1.5), "hpf", 25, sr) * 0.6

    def guitar(self, seed: int, detune: float) -> np.ndarray:
        n, sr = self.n, self.sr
        rng = np.random.default_rng(seed)
        out = np.zeros(n)
        for bar, root in enumerate(self.bar_roots):
            chorus = bar >= self.bars // 2
            f = root * 2 * detune
            for e in range(8):
                ln = int(self.beat * 0.5 * sr)
                jitter = int(rng.uniform(0, 0.008) * sr)
                chord = self._saw(f, ln, rng.uniform(0, 6)) + self._saw(f * 1.4983, ln, rng.uniform(0, 6)) \
                    + 0.6 * self._saw(f * 2, ln, rng.uniform(0, 6))
                palm = (not chorus) and e % 2 == 1
                env = _env(ln, sr, 0.002, 0.08 if palm else 2.0)
                _place(out, chord * env, self.t(bar * 4 + e * 0.5) + jitter)
        out = _filt(np.tanh(_filt(out, "hpf", 90, sr) * 12.0), "hpf", 60, sr)
        out = _filt(out, "bell", 2700, sr, 1.2, 5.0)  # etwas Härte, die der Mix korrigieren soll
        out = _filt(out, "lpf", 7500, sr)
        out += 0.003 * rng.standard_normal(n)
        return out * 0.35

    def lead_guitar(self) -> np.ndarray:
        n, sr = self.n, self.sr
        out = np.zeros(n)
        melody = [329.6, 392.0, 440.0, 493.9, 440.0, 392.0, 329.6, 293.7]
        start_bar = self.bars // 2
        for i in range((self.bars - start_bar) * 4):
            f = melody[i % len(melody)]
            ln = int(self.beat * sr)
            t = np.arange(ln) / sr
            vib = 1 + 0.004 * np.sin(2 * np.pi * 5.5 * t)
            ph = 2 * np.pi * np.cumsum(f * vib) / sr
            note = sum(np.sin(k * ph) / k ** 1.3 for k in range(1, 12)) * _env(ln, sr, 0.01, 1.5)
            _place(out, note, self.t(start_bar * 4 + i))
        return _filt(np.tanh(out * 4.0), "hpf", 120, sr) * 0.25

    def vocal(self) -> np.ndarray:
        n, sr = self.n, self.sr
        out = np.zeros(n)
        phrase = [220.0, 246.9, 261.6, 293.7, 261.6, 246.9]
        for bar in range(self.bars):
            if bar % 2 == 1 and bar < self.bars // 2:
                continue  # Pausen in der Strophe
            for k, f in enumerate(phrase[:4]):
                ln = int(self.beat * 0.9 * sr)
                t = np.arange(ln) / sr
                vib = 1 + 0.012 * np.sin(2 * np.pi * 5.0 * t)
                ph = 2 * np.pi * np.cumsum(f * (1.5 if bar >= self.bars // 2 else 1.0) * vib) / sr
                src = sum(np.sin(h * ph) / h for h in range(1, 25))
                env = _env(ln, sr, 0.03, 0.8)
                _place(out, src * env, self.t(bar * 4 + k))
                if k == 0:  # Sibilant "s" am Phrasenanfang
                    sl = int(0.09 * sr)
                    s = _filt(self.rng.standard_normal(sl), "bandpass", 7000, sr, 1.5) * _env(sl, sr, 0.01, 0.05)
                    _place(out, s * 2.2, self.t(bar * 4 + k) - sl // 2)
        for fc, g in [(700, 9), (1200, 6), (2600, 5)]:
            out = _filt(out, "bell", fc, sr, 2.0, g)
        out = _filt(out, "hpf", 100, sr)
        return out / (np.max(np.abs(out)) + 1e-9) * 0.5

    def synth_pad(self, invert_right: bool = True) -> np.ndarray:
        n, sr = self.n, self.sr
        t = np.arange(n) / sr
        x = 0.1 * (np.sin(2 * np.pi * 164.8 * t) + np.sin(2 * np.pi * 246.9 * t) + 0.5 * np.sin(2 * np.pi * 329.6 * t))
        r = -x if invert_right else x
        return np.column_stack([x, r])

    def render(self, with_problems: bool = True) -> dict[str, np.ndarray]:
        d = self.drums()

        def norm(x, peak_db):
            return x / (np.max(np.abs(x)) + 1e-12) * 10 ** (peak_db / 20)

        tracks = {
            "Kick In": norm(d["kick"], -3.0),
            "Snare Top": norm(d["snare"], -4.0),
            "Toms": norm(d["toms"], -6.0),
            "OH": norm(d["overheads"], -8.0),
            "Room": norm(d["room"], -10.0),
            "Bass DI": norm(self.bass(), -6.0),
            "Gtr Rhythm L": norm(self.guitar(11, 1.0), -6.0),
            "Gtr Rhythm R": norm(self.guitar(23, 1.0015), -6.0),
            "Gtr Lead": norm(self.lead_guitar(), -9.0),
            "Vox Lead": norm(self.vocal(), -6.0),
        }
        if with_problems:
            tracks["Synth Pad"] = self.synth_pad(invert_right=True)
            clip = self.guitar(31, 0.999) * 4.0
            tracks["Gtr Clipped"] = np.clip(clip, -1.0, 1.0)
            tracks["Noise DC"] = 0.02 + 0.001 * self.rng.standard_normal(self.n)
        return tracks


def write_song(out_dir: str | Path, sr: int = 48000, bars: int = 8, with_problems: bool = False,
               neutral_names: bool = False, bit_depth: int = 24, seed: int = 1) -> list[str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tracks = SongSynth(sr=sr, bars=bars, seed=seed).render(with_problems=with_problems)
    paths = []
    for i, (name, x) in enumerate(tracks.items(), start=1):
        fname = f"Track {i:02d}.wav" if neutral_names else f"{name}.wav"
        p = out / fname
        write_audio(p, x, sr, bit_depth, dither=False, overwrite=True)
        paths.append(str(p))
    return paths
