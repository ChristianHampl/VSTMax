"""Abgleich Offline-Engine (Python) <-> Plugin-DSP (C++) über das Werkzeug aime_render.

Die Presets werden genau so erzeugt wie beim Export (integration/presets), danach verarbeitet
der C++-Kanalzug dasselbe Audio. Unterschiede in der Hüllkurvenerkennung (Python blockweise,
C++ je Sample) sind bei Dynamikprozessoren erwartbar; die Toleranzen sind entsprechend gewählt.
"""

import json
import math
import subprocess

import numpy as np
import pytest

from engine import dsp
from engine import loudness as L
from engine.audio_io import load_audio
from engine.mastering import MasterSettings, master
from integration.presets import vstpreset as V
from integration.protocol import params as P
from tests.conftest import SR

pytestmark = pytest.mark.native


def render(exe, plugin, values, x, tmp_path, label="t"):
    st = tmp_path / f"{plugin}.vstpreset"
    st.write_bytes(V.build_preset(plugin, values, label))
    src, dst = tmp_path / "in.f32", tmp_path / "out.f32"
    np.ascontiguousarray(x, dtype=np.float32).tofile(src)
    r = subprocess.run([str(exe), "--plugin", plugin, "--sr", str(SR), "--channels", str(x.shape[1]), "--in", str(src),
                        "--out", str(dst), "--state", str(st)], capture_output=True, text=True, check=True)
    info = json.loads(r.stdout)
    y = np.fromfile(dst, dtype=np.float32).reshape(-1, x.shape[1]).astype(np.float64)
    lat = info["latency_samples"]
    return np.vstack([y[lat:], np.zeros((lat, x.shape[1]))]), info


def test_filters_and_gain_match_exactly(aime_render, tmp_path, song_dir):
    x = load_audio(song_dir / "Gtr Rhythm L.wav").samples
    x = np.column_stack([x[:, 0], x[:, 0] * 0.8]) if x.shape[1] == 1 else x
    t = {"trim_db": -2.0, "fader_db": -3.5, "pan": 0.0, "width": 1.0, "hpf": {"freq": 90.0, "order": 4},
         "eq": [{"type": "bell", "freq": 400, "gain_db": -3.0, "q": 1.5},
                {"type": "highshelf", "freq": 6000, "gain_db": 2.0, "q": 0.7071}],
         "gate": {}, "comp": {}, "deesser": {}, "saturation": {}, "dyn_eq": []}
    vals, _ = P.channel_params(t, SR)
    y_cpp, info = render(aime_render, "channel", vals, x, tmp_path)
    ref = x * dsp.db_to_lin(t["trim_db"])
    ref = dsp.apply_eq_band(ref, SR, {"type": "hpf", "freq": 90.0, "order": 4})
    for b in t["eq"]:
        ref = dsp.apply_eq_band(ref, SR, b)
    ref = ref * dsp.db_to_lin(t["fader_db"])
    n = len(x) - info["latency_samples"] - 10
    err = np.max(np.abs(y_cpp[:n] - ref[:n]))
    assert info["latency_samples"] == 15
    assert err < 1e-4, err


def _stereo(song_dir, name):
    x = load_audio(song_dir / f"{name}.wav").samples
    return np.column_stack([x[:, 0]] * 2) if x.shape[1] == 1 else x


@pytest.mark.parametrize("name", ["Snare Top", "Kick In", "Bass DI", "Vox Lead"])
def test_compressor_loudness_close(aime_render, tmp_path, song_dir, name):
    x = _stereo(song_dir, name)
    c = {"enabled": True, "threshold_db": -24.0, "ratio": 4.0, "attack_ms": 5.0, "release_ms": 80.0, "knee_db": 6.0,
         "makeup_db": 0.0}
    vals, _ = P.channel_params({"trim_db": 0, "fader_db": 0, "comp": c}, SR)
    y_cpp, _ = render(aime_render, "channel", vals, x, tmp_path)
    y_py, st = dsp.compress(x, SR, c["threshold_db"], c["ratio"], c["attack_ms"], c["release_ms"], c["knee_db"], 0.0)
    l_cpp, l_py, l_in = (L.integrated_loudness(v, SR) for v in (y_cpp, y_py, x))
    assert l_in - l_py > 3.0  # es wird tatsächlich komprimiert
    assert abs(l_cpp - l_py) < 0.5, (l_cpp, l_py)


def test_deesser_dynband_gate_close(aime_render, tmp_path, song_dir):
    vox, gtr, toms = _stereo(song_dir, "Vox Lead"), _stereo(song_dir, "Gtr Rhythm L"), _stereo(song_dir, "Toms")
    vals, _ = P.channel_params({"deesser": {"enabled": True, "freq": 5000, "threshold_db": -45, "range_db": 8}}, SR)
    y_cpp, _ = render(aime_render, "channel", vals, vox, tmp_path)
    y_py, _ = dsp.deess(vox, SR, 5000, -45, 8)
    assert abs(L.integrated_loudness(y_cpp, SR) - L.integrated_loudness(y_py, SR)) < 0.1

    st = tmp_path / "sc.f32"
    np.ascontiguousarray(vox, dtype=np.float32).tofile(st)
    vals, _ = P.channel_params({"dyn_eq": [{"freq": 2500, "q": 1.4, "threshold_db": -40, "range_db": 4,
                                            "sidechain": "vox"}]}, SR)
    pre = tmp_path / "d.vstpreset"
    pre.write_bytes(V.build_preset("channel", vals, "g"))
    np.ascontiguousarray(gtr, dtype=np.float32).tofile(tmp_path / "g.f32")
    info = json.loads(subprocess.run([str(aime_render), "--plugin", "channel", "--sr", str(SR), "--channels", "2",
                                      "--in", str(tmp_path / "g.f32"), "--out", str(tmp_path / "go.f32"), "--state",
                                      str(pre), "--sidechain", str(st), "--sc-channels", "2"],
                                     capture_output=True, text=True, check=True).stdout)
    yc = np.fromfile(tmp_path / "go.f32", dtype=np.float32).reshape(-1, 2).astype(np.float64)[info["latency_samples"]:]
    yp, _ = dsp.dynamic_band(gtr, SR, 2500, 1.4, -40, 4, vox)
    n = len(yc)
    assert np.max(np.abs(yc - yp[:n])) < 0.02
    assert L.integrated_loudness(yp, SR) < L.integrated_loudness(gtr, SR) - 0.1  # Sidechain wirkt

    vals, _ = P.channel_params({"gate": {"enabled": True, "threshold_db": -30, "range_db": 30, "attack_ms": 0.5,
                                         "hold_ms": 40, "release_ms": 100}}, SR)
    y_cpp, _ = render(aime_render, "channel", vals, toms, tmp_path)
    y_py, _ = dsp.gate(toms, SR, -30, 30, 0.5, 40, 100)
    assert abs(L.integrated_loudness(y_cpp, SR) - L.integrated_loudness(y_py, SR)) < 0.1


def test_master_chain_matches_offline(aime_render, tmp_path, song_dir):
    names = ["Kick In", "Snare Top", "Bass DI", "Gtr Rhythm L", "Gtr Rhythm R", "Vox Lead", "OH"]
    mix = None
    for nm in names:
        a = load_audio(song_dir / f"{nm}.wav").samples
        a = np.column_stack([a[:, 0]] * 2) if a.shape[1] == 1 else a
        mix = a * 0.3 if mix is None else mix + a * 0.3
    mix *= 0.5 / np.max(np.abs(mix))
    s = MasterSettings(target_lufs=-12.0, true_peak_db=-1.0, max_limiter_gr_db=6.0, min_plr_db=6.0)
    y_py, rep = master(mix, SR, s)
    vals, _ = P.master_params(rep, {"true_peak_db": -1.0})
    y_cpp, info = render(aime_render, "master", vals, mix, tmp_path)
    l_py, l_cpp = L.integrated_loudness(y_py, SR), L.integrated_loudness(y_cpp, SR)
    tp_cpp = 20 * math.log10(dsp.true_peak(y_cpp, SR))
    assert abs(l_cpp - l_py) < 0.75, (l_cpp, l_py)
    assert tp_cpp <= -1.0 + 0.15, tp_cpp
