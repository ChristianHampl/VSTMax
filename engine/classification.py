"""Instrumentenrollen-Erkennung mit Konfidenz.

Hybrid:
1. Merkmalsbasierte Prototypen (deterministisch, aus ``analysis.TrackAnalysis``).
2. Dateiname als *schwaches* Indiz (kann Merkmale nicht überstimmen).
3. Optional ein lokales ML-Modell (ONNX), das der Nutzer selbst bereitstellt.
4. Kontextregeln über alle Spuren (Lead- vs. Backing-Vocal, Lead- vs. Rhythmusgitarre).
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from .analysis import TrackAnalysis

ROLES = [
    "kick", "snare", "toms", "hihat", "overheads", "room",
    "bass", "rhythm_guitar", "lead_guitar", "clean_guitar",
    "lead_vocal", "scream_vocal", "backing_vocal", "synth", "other",
]

ROLE_LABELS_DE = {
    "kick": "Kick", "snare": "Snare", "toms": "Toms", "hihat": "Hi-Hat", "overheads": "Overheads",
    "room": "Room", "bass": "Bass", "rhythm_guitar": "Rhythmusgitarre", "lead_guitar": "Leadgitarre",
    "clean_guitar": "Clean-Gitarre", "lead_vocal": "Lead-Vocal (clean)", "scream_vocal": "Vocal (verzerrt/Scream)",
    "backing_vocal": "Backing-Vocal", "synth": "Synth/Keys", "other": "Sonstiges",
}

ROLE_GROUP = {
    "kick": "drums", "snare": "drums", "toms": "drums", "hihat": "drums", "overheads": "drums", "room": "drums",
    "bass": "bass", "rhythm_guitar": "guitars", "lead_guitar": "guitars", "clean_guitar": "guitars",
    "lead_vocal": "vocals", "scream_vocal": "vocals", "backing_vocal": "vocals", "synth": "keys", "other": "other",
}

NAME_HINTS: dict[str, list[str]] = {
    "kick": [r"kick", r"\bbd\b", r"bassdrum", r"bass drum", r"kik"],
    "snare": [r"snare", r"\bsn\b", r"\bsd\b"],
    "toms": [r"\btom", r"floor", r"rack"],
    "hihat": [r"hi.?hat", r"\bhh\b", r"\bhat\b"],
    "overheads": [r"\boh\b", r"overhead", r"cymbal", r"\boh ?[lr]\b"],
    "room": [r"room", r"amb", r"\bkit\b"],
    "bass": [r"bass(?!.?drum)", r"\bbs\b", r"\bdi\b"],
    "rhythm_guitar": [r"rhythm", r"rhy", r"\bgtr\b", r"guit", r"git"],
    "lead_guitar": [r"lead.?g", r"solo", r"gtr.?lead", r"lead gtr"],
    "clean_guitar": [r"clean", r"acoustic", r"akustik"],
    "lead_vocal": [r"vox", r"vocal", r"vocals", r"\blv\b", r"lead.?vox", r"gesang", r"sing"],
    "scream_vocal": [r"scream", r"growl", r"harsh", r"shout"],
    "backing_vocal": [r"\bbv\b", r"backing", r"\bbgv\b", r"choir", r"chor", r"double", r"harm"],
    "synth": [r"synth", r"pad", r"keys", r"piano", r"orch", r"string"],
}


def _m(v: float, lo: float, hi: float, soft: float) -> float:
    """Zugehörigkeit 1 innerhalb [lo, hi], gaußförmiger Abfall außerhalb."""
    if v is None or not math.isfinite(v):
        return 0.0
    if lo <= v <= hi:
        return 1.0
    d = (lo - v) if v < lo else (v - hi)
    return math.exp(-((d / max(soft, 1e-9)) ** 2))


def _lg(f: float) -> float:
    return math.log2(max(f, 1.0))


def features(a: TrackAnalysis) -> dict[str, float]:
    b = a.band_db
    low = 10 * math.log10(10 ** (b.get("sub", -60) / 10) + 10 ** (b.get("bass", -60) / 10))
    return {
        "low_db": low,
        "centroid_oct": _lg(a.centroid_hz),
        "crest": a.crest_db,
        "silence": a.silence_ratio,
        "sustain": a.sustain_ratio,
        "harm": a.harmonicity,
        "f0": a.f0_median_hz,
        "f0_spread": a.f0_spread,
        "onsets": a.onset_rate,
        "flat": a.flatness,
        "stereo": a.side_mid_db if a.channels > 1 else -120.0,
        "dyn": a.dynamic_range_db,
    }


# (Merkmal, untere Grenze, obere Grenze, Weichheit, Gewicht)
L = _lg
PROTOTYPES: dict[str, list[tuple[str, float, float, float, float]]] = {
    "kick": [("low_db", -4, 0, 3, 2), ("centroid_oct", L(40), L(400), 1.0, 1.5), ("crest", 12, 32, 4, 1),
             ("sustain", 0, 0.5, 0.15, 1.5), ("onsets", 1, 16, 2, 1), ("stereo", -200, -30, 10, 0.5)],
    "snare": [("centroid_oct", L(900), L(5000), 0.7, 1.5), ("crest", 15, 35, 4, 1), ("sustain", 0, 0.35, 0.15, 1.5),
              ("flat", 0.15, 0.8, 0.1, 1), ("silence", 0.3, 0.95, 0.2, 0.5), ("low_db", -60, -2, 2, 0.5),
              ("stereo", -200, -30, 10, 0.5)],
    "toms": [("low_db", -4, 0, 3, 1.5), ("centroid_oct", L(60), L(300), 1, 1), ("silence", 0.45, 1.0, 0.15, 2),
             ("sustain", 0, 0.2, 0.1, 1.5), ("onsets", 0.05, 3, 1, 1), ("stereo", -200, -30, 10, 0.5)],
    "hihat": [("centroid_oct", L(5000), L(16000), 0.6, 2), ("low_db", -80, -15, 5, 1), ("sustain", 0, 0.5, 0.2, 1),
              ("flat", 0.3, 1, 0.15, 1), ("stereo", -200, -30, 10, 0.5)],
    "overheads": [("stereo", -18, 3, 4, 2), ("centroid_oct", L(2500), L(16000), 0.8, 1.5), ("crest", 15, 35, 4, 1),
                  ("flat", 0.2, 1, 0.15, 0.5), ("sustain", 0, 0.45, 0.2, 0.5)],
    "room": [("stereo", -15, 0, 4, 2), ("crest", 10, 25, 4, 1), ("centroid_oct", L(300), L(3000), 0.8, 1),
             ("sustain", 0.2, 0.6, 0.2, 1), ("low_db", -8, 0, 4, 0.5)],
    "bass": [("low_db", -3, 0, 2, 2), ("centroid_oct", L(40), L(300), 0.8, 1.5), ("sustain", 0.6, 1, 0.2, 2),
             ("crest", 2, 12, 3, 1), ("silence", 0, 0.4, 0.2, 0.5), ("stereo", -200, -30, 10, 0.5)],
    "rhythm_guitar": [("centroid_oct", L(300), L(2000), 0.7, 1.5), ("sustain", 0.7, 1, 0.15, 1.5),
                      ("crest", 2, 10, 3, 1.5), ("low_db", -10, -1, 3, 0.5), ("harm", 0, 0.6, 0.2, 1),
                      ("silence", 0, 0.3, 0.2, 1)],
    "lead_guitar": [("centroid_oct", L(400), L(3000), 0.7, 1), ("harm", 0.7, 1, 0.15, 1.5), ("crest", 2, 12, 3, 1),
                    ("silence", 0.2, 0.85, 0.2, 1), ("f0", 150, 1200, 80, 1), ("low_db", -80, -12, 4, 1),
                    ("f0_spread", 1.0, 8, 1.5, 0.5)],
    "clean_guitar": [("harm", 0.6, 1, 0.15, 1), ("crest", 10, 20, 3, 1.5), ("centroid_oct", L(300), L(2000), 0.7, 1),
                     ("sustain", 0.3, 0.8, 0.15, 1), ("low_db", -30, -5, 4, 0.5), ("flat", 0, 0.1, 0.05, 0.5)],
    "lead_vocal": [("f0", 80, 700, 60, 1), ("harm", 0.6, 1, 0.15, 1.5), ("f0_spread", 2, 12, 1.5, 1.5),
                   ("silence", 0.1, 0.6, 0.15, 1), ("crest", 10, 20, 3, 1), ("centroid_oct", L(500), L(3000), 0.7, 1),
                   ("low_db", -80, -8, 3, 1), ("stereo", -200, -30, 10, 0.3)],
    "scream_vocal": [("flat", 0.15, 0.6, 0.1, 1.5), ("harm", 0.1, 0.55, 0.15, 1), ("silence", 0.1, 0.7, 0.2, 1),
                     ("crest", 8, 18, 3, 1), ("centroid_oct", L(800), L(3500), 0.7, 1), ("low_db", -80, -10, 3, 1),
                     ("sustain", 0.3, 0.85, 0.2, 0.5)],
    "backing_vocal": [("f0", 80, 900, 60, 1), ("harm", 0.6, 1, 0.15, 1.2), ("f0_spread", 1.5, 12, 1.5, 1),
                      ("silence", 0.35, 0.95, 0.15, 1.5), ("crest", 10, 22, 3, 0.8),
                      ("centroid_oct", L(500), L(3500), 0.7, 0.8), ("low_db", -80, -8, 3, 1)],
    "synth": [("harm", 0.6, 1, 0.15, 1), ("sustain", 0.8, 1, 0.1, 1.5), ("crest", 2, 9, 3, 1),
              ("f0_spread", 0, 1.5, 1.0, 1), ("centroid_oct", L(150), L(5000), 1, 0.5), ("dyn", 0, 6, 3, 0.5)],
}

OTHER_BASELINE = 0.3
SOFTMAX_TEMP = 0.07


@dataclass
class Classification:
    role: str
    confidence: float
    alternatives: list[tuple[str, float]]
    reasons: list[str] = field(default_factory=list)
    uncertain: bool = False
    source: str = "features"
    probabilities: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "role_label": ROLE_LABELS_DE.get(self.role, self.role),
            "confidence": round(self.confidence, 3),
            "alternatives": [[r, round(p, 3)] for r, p in self.alternatives],
            "reasons": self.reasons,
            "uncertain": self.uncertain,
            "source": self.source,
        }


def name_hints(name: str) -> dict[str, float]:
    n = name.lower().replace("_", " ").replace("-", " ")
    hits: dict[str, float] = {}
    for role, pats in NAME_HINTS.items():
        for p in pats:
            if re.search(p, n):
                hits[role] = max(hits.get(role, 0.0), 1.0)
    # Spezifischere Treffer gewinnen ("lead gtr" schlägt "gtr")
    if "lead_guitar" in hits:
        hits.pop("rhythm_guitar", None)
    if "scream_vocal" in hits or "backing_vocal" in hits:
        hits.pop("lead_vocal", None)
    if "kick" in hits:
        hits.pop("bass", None)
    return hits


def feature_scores(a: TrackAnalysis) -> dict[str, float]:
    f = features(a)
    scores = {}
    for role, proto in PROTOTYPES.items():
        tot, wsum = 0.0, 0.0
        for feat, lo, hi, soft, w in proto:
            tot += w * _m(f[feat], lo, hi, soft)
            wsum += w
        scores[role] = tot / wsum
    scores["other"] = OTHER_BASELINE
    return scores


def _softmax(scores: dict[str, float], temp: float = SOFTMAX_TEMP) -> dict[str, float]:
    mx = max(scores.values())
    ex = {k: math.exp((v - mx) / temp) for k, v in scores.items()}
    s = sum(ex.values())
    return {k: v / s for k, v in ex.items()}


ExternalModel = Callable[[np.ndarray, int], dict[str, float]]


def classify(a: TrackAnalysis, name: str = "", samples: np.ndarray | None = None,
             model: ExternalModel | None = None, model_weight: float = 0.6) -> Classification:
    if a.is_silent:
        return Classification("other", 0.0, [], ["Spur ist stumm - keine Klassifizierung möglich"], True)
    fs = feature_scores(a)
    reasons = []
    hints = name_hints(name or a.name)
    combined = dict(fs)
    for role in hints:
        combined[role] = combined.get(role, 0.0) + 0.12
    if hints:
        reasons.append("Dateiname deutet auf " + ", ".join(ROLE_LABELS_DE[r] for r in hints) + " hin (schwaches Indiz)")
    probs = _softmax(combined)
    source = "features+name" if hints else "features"
    if model is not None and samples is not None:
        try:
            mp = model(samples, a.sample_rate)
            tot = sum(mp.values()) or 1.0
            mp = {k: v / tot for k, v in mp.items() if k in ROLES}
            probs = {r: (1 - model_weight) * probs.get(r, 0.0) + model_weight * mp.get(r, 0.0) for r in ROLES}
            source += "+ml"
            reasons.append("Lokales ML-Modell einbezogen")
        except Exception as exc:  # Modellfehler dürfen die Analyse nicht stoppen
            reasons.append(f"ML-Modell fehlgeschlagen, nur Heuristik verwendet: {exc}")
    ranked = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)
    role, conf = ranked[0]
    fscore = fs.get(role, 0.0)
    if role != "other" and fscore < 0.45:
        conf *= 0.6
        reasons.append(f"Audio-Merkmale passen nur schwach zu {ROLE_LABELS_DE[role]} ({fscore:.2f})")
    if hints and role not in hints:
        reasons.append("Audio-Merkmale widersprechen dem Dateinamen")
    conf = min(conf, 0.95)
    f = features(a)
    reasons.append(
        f"Schwerpunkt {a.centroid_hz:.0f} Hz, Crest {a.crest_db:.1f} dB, Sustain {f['sustain']:.2f}, "
        f"Harmonizität {f['harm']:.2f}, Pausenanteil {f['silence']:.2f}"
    )
    return Classification(role, conf, ranked[1:4], reasons, conf < 0.5, source, probs)


def apply_context(results: dict[str, Classification], analyses: dict[str, TrackAnalysis],
                  pair_info: dict[tuple[str, str], dict] | None = None) -> list[str]:
    """Korrigiert Rollen anhand des gesamten Arrangements. Gibt Protokolleinträge zurück."""
    log = []
    vocals = [k for k, c in results.items() if c.role in ("lead_vocal", "backing_vocal")]
    if vocals:
        lead = max(vocals, key=lambda k: (1 - analyses[k].silence_ratio) * 10 + analyses[k].lufs / 10)
        for k in vocals:
            want = "lead_vocal" if k == lead else "backing_vocal"
            if results[k].role != want:
                log.append(f"{k}: {ROLE_LABELS_DE[results[k].role]} -> {ROLE_LABELS_DE[want]} (Kontext: aktivste Vocal-Spur ist Lead)")
                results[k].role = want
                results[k].reasons.append("Rolle per Arrangement-Kontext angepasst")
    guitars = [k for k, c in results.items() if c.role in ("rhythm_guitar", "lead_guitar")]
    if pair_info:
        for (a, b), info in pair_info.items():
            if info.get("double_track") and a in results and b in results:
                for k in (a, b):
                    if results[k].role == "lead_guitar" and analyses[k].silence_ratio < 0.2:
                        results[k].role = "rhythm_guitar"
                        log.append(f"{k}: als Rhythmus-Double erkannt (Partner {b if k == a else a})")
    if len(guitars) == 1 and results[guitars[0]].role == "lead_guitar" and analyses[guitars[0]].silence_ratio < 0.1:
        results[guitars[0]].role = "rhythm_guitar"
        log.append(f"{guitars[0]}: durchgehend aktiv -> Rhythmusgitarre")
    return log


# ------------------------------------------------------------------ ML-Hook

def log_mel(samples: np.ndarray, sr: int, n_mels: int = 64, n_fft: int = 2048, hop: int = 512,
            max_s: float = 10.0) -> np.ndarray:
    """Log-Mel-Spektrogramm (NumPy), Eingabe für optionale lokale Modelle."""
    x = samples.mean(axis=1) if samples.ndim == 2 else samples
    x = x[: int(max_s * sr)]
    if len(x) < n_fft:
        x = np.pad(x, (0, n_fft - len(x)))
    frames = 1 + (len(x) - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(frames)[:, None]
    spec = np.abs(np.fft.rfft(x[idx] * np.hanning(n_fft), axis=1)) ** 2
    fmax = sr / 2
    mel = lambda f: 2595 * np.log10(1 + f / 700)  # noqa: E731
    imel = lambda m: 700 * (10 ** (m / 2595) - 1)  # noqa: E731
    pts = imel(np.linspace(mel(20), mel(fmax), n_mels + 2))
    bins = np.floor((n_fft + 1) * pts / sr).astype(int)
    fb = np.zeros((n_mels, n_fft // 2 + 1))
    for i in range(n_mels):
        l, c, r = bins[i], bins[i + 1], bins[i + 2]
        if c > l:
            fb[i, l:c] = (np.arange(l, c) - l) / (c - l)
        if r > c:
            fb[i, c:r] = (r - np.arange(c, r)) / (r - c)
    return np.log(spec @ fb.T + 1e-10).astype(np.float32)


def load_onnx_model(model_path: str | Path, labels_path: str | Path | None = None) -> ExternalModel:
    """Lädt ein vom Nutzer bereitgestelltes ONNX-Modell (Eingabe: [1, frames, 64] Log-Mel).

    Es wird kein Modell mitgeliefert. ``labels.json`` enthält die Liste der Rollen in
    Ausgabereihenfolge. Benötigt das optionale Paket ``onnxruntime``.
    """
    import onnxruntime as ort  # optional

    model_path = Path(model_path)
    labels_path = Path(labels_path) if labels_path else model_path.with_suffix(".labels.json")
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    sess = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0].name

    def run(samples: np.ndarray, sr: int) -> dict[str, float]:
        feats = log_mel(samples, sr)[None, ...]
        out = sess.run(None, {inp: feats})[0].reshape(-1)
        e = np.exp(out - out.max())
        p = e / e.sum()
        return {labels[i]: float(p[i]) for i in range(min(len(labels), len(p)))}

    return run
