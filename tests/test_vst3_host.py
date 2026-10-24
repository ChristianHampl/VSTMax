"""Ende-zu-Ende: von Python exportierte .vstpreset -> gebautes AIME.vst3 (über SDK-Hosting-Klassen) -> Audio.

Vergleicht die Ausgabe des echten Plug-in-Binaries mit dem DSP-Werkzeug aime_render (gleicher C++-Kern)
und mit der Python-Offline-Engine. Läuft nur, wenn build/plugins gebaut wurde; ersetzt keinen Test in Cubase.
"""

import json
import subprocess

import numpy as np
import pytest

from engine import dsp
from engine.audio_io import load_audio
from integration.presets import vstpreset as V
from integration.protocol import params as P
from tests.conftest import SR

pytestmark = pytest.mark.native

CLASSES = {"channel": "AIME Channel", "bus": "AIME Bus", "master": "AIME Master"}


def host(exe, module, plugin, values, x, tmp_path):
    pre = tmp_path / f"h_{plugin}.vstpreset"
    pre.write_bytes(V.build_preset(plugin, values, "host"))
    src, dst = tmp_path / "hin.f32", tmp_path / "hout.f32"
    np.ascontiguousarray(x, dtype=np.float32).tofile(src)
    r = subprocess.run([str(exe), "--module", str(module), "--class", CLASSES[plugin], "--preset", str(pre),
                        "--sr", str(SR), "--channels", str(x.shape[1]), "--in", str(src), "--out", str(dst)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    info = json.loads(r.stdout.strip().splitlines()[-1])
    return np.fromfile(dst, dtype=np.float32).reshape(-1, x.shape[1]).astype(np.float64), info


def direct(exe, plugin, values, x, tmp_path):
    pre = tmp_path / f"d_{plugin}.vstpreset"
    pre.write_bytes(V.build_preset(plugin, values, "direct"))
    src, dst = tmp_path / "din.f32", tmp_path / "dout.f32"
    np.ascontiguousarray(x, dtype=np.float32).tofile(src)
    r = subprocess.run([str(exe), "--plugin", plugin, "--sr", str(SR), "--channels", str(x.shape[1]), "--in", str(src),
                        "--out", str(dst), "--state", str(pre)], capture_output=True, text=True, check=True)
    return np.fromfile(dst, dtype=np.float32).reshape(-1, x.shape[1]).astype(np.float64), json.loads(r.stdout)


def _stereo(song_dir, name):
    x = load_audio(song_dir / f"{name}.wav").samples
    return np.column_stack([x[:, 0]] * 2) if x.shape[1] == 1 else x


def test_channel_plugin_applies_exported_preset(host_render, aime_vst3, tmp_path, song_dir):
    x = _stereo(song_dir, "Gtr Rhythm L")
    t = {"trim_db": -2.0, "fader_db": -3.5, "hpf": {"freq": 90.0, "order": 4},
         "eq": [{"type": "bell", "freq": 400, "gain_db": -3.0, "q": 1.5}]}
    vals, _ = P.channel_params(t, SR)
    y, info = host(host_render, aime_vst3, "channel", vals, x, tmp_path)
    assert info["latency_samples"] == 15
    assert info["controller_params"] > 20
    lat = info["latency_samples"]
    ref = dsp.apply_eq_band(x * dsp.db_to_lin(-2.0), SR, {"type": "hpf", "freq": 90.0, "order": 4})
    ref = dsp.apply_eq_band(ref, SR, t["eq"][0]) * dsp.db_to_lin(-3.5)
    n = len(x) - lat - 10
    assert np.max(np.abs(y[lat:lat + n] - ref[:n])) < 1e-4


@pytest.mark.parametrize("plugin", ["channel", "bus", "master"])
def test_plugin_binary_matches_dsp_tool(host_render, aime_vst3, aime_render, tmp_path, song_dir, plugin):
    x = _stereo(song_dir, "Snare Top") * 0.7 + _stereo(song_dir, "Bass DI") * 0.5
    if plugin == "channel":
        vals, _ = P.channel_params({"comp": {"enabled": True, "threshold_db": -24, "ratio": 4, "attack_ms": 5,
                                             "release_ms": 80, "knee_db": 6, "makeup_db": 2},
                                    "saturation": {"enabled": True, "drive_db": 6, "mix": 0.5}}, SR)
    elif plugin == "bus":
        vals, _ = P.bus_params({"comp": {"enabled": True, "threshold_db": -18, "ratio": 2, "attack_ms": 10,
                                         "release_ms": 100},
                                "parallel": {"amount": 0.3, "saturation_db": 4.0,
                                             "comp": {"threshold_db": -35, "ratio": 8, "attack_ms": 3, "release_ms": 60}},
                                "saturation": {"drive_db": 3}})
    else:
        vals, _ = P.master_params({"eq": [{"type": "lowshelf", "freq": 100, "gain_db": 1.5, "q": 0.7}],
                                   "bus_comp": {"threshold_db": -16, "ratio": 2, "attack_ms": 30, "release_ms": 150,
                                                "knee_db": 6, "makeup_db": 1},
                                   "gain_db": 4.0}, {"true_peak_db": -1.0})
    y_host, ih = host(host_render, aime_vst3, plugin, vals, x, tmp_path)
    y_dir, idr = direct(aime_render, plugin, vals, x, tmp_path)
    assert ih["latency_samples"] == idr["latency_samples"]
    n = min(len(y_host), len(y_dir))
    # Unterschiedliche Blockgrößen (Host 512, aime_render eigene) dürfen am Ergebnis nichts ändern
    assert np.max(np.abs(y_host[:n] - y_dir[:n])) < 2e-4
    assert np.max(np.abs(y_host - x[:len(y_host)])) > 1e-3  # Preset wirkt tatsächlich
