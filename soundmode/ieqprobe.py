"""Intelligent-EQ probe: ~2 min of noise at a constant -22 dBFS rms whose spectral tilt steps between pink,
brighter and darker, to expose an adaptive EQ (how much it cuts/boosts treble and bass, and how fast).

  python -m soundmode.ieqprobe LABEL [--bypass-hesuvi]
-> dolby-probe/runs/ieq_LABEL.npz with t, tilt (dB/oct of the input), low/high (dB, band gain relative to 500-2k)
"""
import argparse, time, warnings
import numpy as np
from scipy.signal import csd, welch
from . import levprobe

warnings.filterwarnings("ignore")
FS = levprobe.FS
SCHEDULE = [(0, 15), (3, 15), (0, 10), (-3, 15), (0, 10), (3, 4), (0, 8), (6, 15), (0, 10), (-6, 15), (0, 10)]
LEVEL = -22.0
WIN, HOP = 0.5, 0.25
BANDS = {"low": (63, 250), "mid": (500, 2000), "high": (4000, 12000)}


def stimulus(seed=11):
    rng = np.random.default_rng(seed); parts = []
    for tilt, sec in SCHEDULE:
        n = int(sec * FS)
        X = np.fft.rfft(rng.standard_normal(n)); f = np.fft.rfftfreq(n, 1 / FS); f[0] = f[1]
        shape = 1 / np.sqrt(f) * 10 ** (tilt * np.log2(f / 1000) / 20)
        x = np.fft.irfft(X * shape, n); x *= 10 ** (LEVEL / 20) / x.std(); parts.append(x)
    k = int(0.05 * FS)
    for i in range(1, len(parts)):                       # 50 ms crossfade between segments
        a, b = parts[i - 1], parts[i]; r = np.linspace(0, 1, k)
        b[:k] = a[-k:] * (1 - r) + b[:k] * r; parts[i - 1] = a[:-k]
    x = np.concatenate(parts)
    tilt = np.concatenate([np.full(int(s * FS), float(t)) for t, s in SCHEDULE])[: len(x)]
    return x, tilt


def analyse(x, y, tilt):
    w, h = int(WIN * FS), int(HOP * FS); t, lo, hi = [], [], []
    for i in range(0, len(x) - w, h):
        f, P = csd(x[i:i + w], y[i:i + w], fs=FS, nperseg=4096); _, Q = welch(x[i:i + w], fs=FS, nperseg=4096)
        H = np.abs(P / Q) ** 2
        b = {k: 10 * np.log10(np.mean(H[(f >= a) & (f < c)])) for k, (a, c) in BANDS.items()}
        t.append((i + w / 2) / FS); lo.append(b["low"] - b["mid"]); hi.append(b["high"] - b["mid"])
    t = np.array(t); return t, tilt[(t * FS).astype(int)], np.array(lo), np.array(hi)


def main(label, bypass):
    x, tilt = stimulus()
    print(f"phat {len(x)/FS:.0f} s noise doi mau am (dung chinh volume)...", flush=True)
    old = levprobe.DEACT.read_text() if bypass else None
    try:
        if bypass: levprobe.DEACT.write_text("Eval: active=false"); time.sleep(1.5)
        y = levprobe.play_record(x)
    finally:
        if bypass: levprobe.DEACT.write_text(old)
    y = levprobe.align(x, y)
    if len(y) < len(x): print("thu thieu du lieu"); return
    t, tl, lo, hi = analyse(x, y, tilt)
    np.savez(levprobe.RUNS / f"ieq_{label}.npz", t=t, tilt=tl, low=lo, high=hi)
    t0 = 0
    for tv, sec in SCHEDULE:
        s = (t >= t0 + 0.5) & (t < t0 + sec)
        early = s & (t < t0 + 1.5); late = s & (t >= t0 + sec - 3)
        print(f"  {t0:5.0f}s tilt {tv:+d} dB/oct: high {np.median(hi[early]):+5.1f} -> {np.median(hi[late]):+5.1f}   "
              f"low {np.median(lo[early]):+5.1f} -> {np.median(lo[late]):+5.1f}")
        t0 += sec


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("label"); ap.add_argument("--bypass-hesuvi", action="store_true")
    a = ap.parse_args(); main(a.label, a.bypass_hesuvi)
