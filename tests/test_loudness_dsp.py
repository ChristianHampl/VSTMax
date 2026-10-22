import math

import numpy as np
import pytest

from engine import dsp
from engine import loudness as L
from tests.conftest import SR, sine


@pytest.mark.parametrize("sr", [44100, 48000])
def test_ebu_1khz_sine_minus23(sr):
    x = sine(1000, 10 ** (-23 / 20), 20, sr)
    r = L.measure(x, sr)
    assert abs(r.integrated_lufs + 23.0) < 0.1
    assert abs(r.momentary_max_lufs + 23.0) < 0.1
    assert abs(r.short_term_max_lufs + 23.0) < 0.1


def test_ebu_gating_relative():
    # EBU Tech 3341 Fall 3/4-artig: lauter Teil dominiert, leiser Teil < -10 LU wird ausgeblendet
    loud = sine(1000, 10 ** (-23 / 20), 10)
    quiet = sine(1000, 10 ** (-43 / 20), 10)
    r = L.measure(np.concatenate([quiet, loud, quiet]), SR)
    assert abs(r.integrated_lufs + 23.0) < 0.15


def test_true_peak_exceeds_sample_peak_for_intersample_signal():
    # fs/4-Sinus mit 45°-Phase: Samples bei +-0.707*A, wahre Spitze A
    n = np.arange(48000)
    x = np.sin(2 * np.pi * n / 4 + np.pi / 4)
    x2 = np.column_stack([x, x])
    tp = dsp.true_peak(x2, SR)
    assert np.max(np.abs(x2)) < 0.72
    assert tp > 0.98


def test_biquad_bell_gain():
    b, a = dsp.biquad_coeffs("bell", 1000, SR, 6.0, 1.0)
    assert abs(dsp.magnitude_db(b, a, 1000, SR) - 6.0) < 0.01


def test_compressor_static_curve():
    x = np.full((SR, 1), 0.5)
    y, st = dsp.compress(x, SR, -20.0, 4.0, 1.0, 50.0, 0.0, 0.0)
    expect = 0.75 * (20 * math.log10(0.5) + 20)
    assert abs(st["max_gr_db"] - expect) < 0.1


def test_deesser_attenuates_highs_not_lows():
    hi = sine(9000, 0.3, 1.0)
    lo = sine(200, 0.3, 1.0)
    yh, st = dsp.deess(hi, SR, 5000, -40, 10)
    yl, _ = dsp.deess(lo, SR, 5000, -40, 10)
    gh = 20 * np.log10(np.std(yh[SR // 2:]) / np.std(hi[SR // 2:]))
    gl = 20 * np.log10(np.std(yl[SR // 2:]) / np.std(lo[SR // 2:]))
    assert gh < -8.0
    assert abs(gl) < 0.1
    assert st["max_gr_db"] == pytest.approx(10.0, abs=0.01)


def test_true_peak_limiter_respects_ceiling(rng):
    x = rng.normal(0, 0.3, (SR * 3, 2))
    y, st = dsp.true_peak_limiter(x * 4, SR, -1.0)
    assert 20 * math.log10(dsp.true_peak(y, SR)) <= -1.0 + 0.01
    assert st["max_gr_db"] > 3


def test_sanitize_removes_nan_inf():
    x = np.array([[np.nan, 1.0], [np.inf, -np.inf]])
    y = dsp.sanitize(x)
    assert np.all(np.isfinite(y))
