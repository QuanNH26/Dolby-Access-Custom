"""Adaptive treble model ("Intelligent EQ") - Python twin of the IEQ stage in native/leveler.c.

Per 20 ms frame:
  Ph, Pm  power of the input through a 2nd-order high-pass at 3 kHz and a band-pass at 1 kHz (RBJ biquads)
  F       = 10*log10(Ph/Pm)                     spectral tilt feature
  S       = EMA of F, time constant ts_q        fast estimate
  R       = EMA of S, rising tr_up, falling tr_dn (slow memory)
  T       = clamp(b0 - a*(S - f0) - c*(R - f0), gmin, gmax)
  g       follows T with tg (dB), applied as a high shelf at fh Hz
  python -m soundmode.ieqmodel fit LABEL   (LABEL = ieq probe run, e.g. dolby_mw)
"""
import json, sys
import numpy as np
from scipy.optimize import minimize
from scipy.signal import lfilter
from . import ieqprobe, levprobe

FS = levprobe.FS
FR = levprobe.FRAME
KEYS = ["ts_q", "tr_up", "tr_dn", "b0", "a", "c", "f0", "gmin", "gmax", "tg"]
DEFAULT = {"ts_q": 0.5, "tr_up": 30.0, "tr_dn": 30.0, "b0": -1.5, "a": 0.6, "c": 0.6, "f0": 0.0,
           "gmin": -4.7, "gmax": 4.8, "tg": 0.3}


def rbj(kind, f0, q, fs=FS):
    w = 2 * np.pi * f0 / fs; al = np.sin(w) / (2 * q); cw = np.cos(w)
    if kind == "hp": b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
    elif kind == "lp": b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]
    else: b = [al, 0, -al]                                 # band-pass, 0 dB peak
    a = [1 + al, -2 * cw, 1 - al]
    return np.array(b) / a[0], np.array(a) / a[0]


def feature(x, fs=FS, band="high"):
    """tilt feature per 20 ms frame (same filters as the plugin): high = HP 3 kHz / BP 1 kHz, low = LP 200 Hz / BP 1 kHz."""
    bh, ah = rbj("hp", 3000, 0.7071, fs) if band == "high" else rbj("lp", 200, 0.7071, fs)
    bm, am = rbj("bp", 1000, 0.7071, fs)
    h = lfilter(bh, ah, x); m = lfilter(bm, am, x)
    n = int(round(FR * fs)); k = len(x) // n
    Ph = np.mean(h[:k * n].reshape(k, n) ** 2, 1); Pm = np.mean(m[:k * n].reshape(k, n) ** 2, 1)
    return 10 * np.log10((Ph + 1e-20) / (Pm + 1e-20))


def simulate(F, P):
    co = lambda tau: np.exp(-FR / max(tau, 1e-3))
    aq, au, ad, ag = co(P["ts_q"]), co(P["tr_up"]), co(P["tr_dn"]), co(P["tg"])
    S = R = P["f0"]; g = P["b0"]; out = np.empty(len(F))
    for i, f in enumerate(F):
        S = aq * S + (1 - aq) * f
        a = au if S > R else ad
        R = a * R + (1 - a) * S
        T = min(max(P["b0"] - P["a"] * (S - P["f0"]) - P["c"] * (R - P["f0"]), P["gmin"]), P["gmax"])
        g = ag * g + (1 - ag) * T
        out[i] = g
    return out


def target(label):
    d = np.load(levprobe.RUNS / f"ieq_{label}.npz")
    x, tilt = ieqprobe.stimulus()
    return d, x, tilt


def fit(label, iters=3000, band="high", x0=None):
    d, x, _ = target(label)
    F = feature(x, band=band); tf = (np.arange(len(F)) + 0.5) * FR
    hi = np.interp(tf, d["t"], d[band])
    w = np.ones(len(F)); w[tf < 1] = 0
    tl = np.interp(tf, d["t"], d["tilt"]); w[tl < -4] = 0.2           # the -6 dB/oct segment has little treble: noisy
    free = [k for k in KEYS if k != "f0"]
    P0 = dict(DEFAULT); P0.update(x0 or {}); P0["f0"] = float(np.median(F[(tf > 1) & (tf < 14)]))
    def unpack(v): P = dict(P0); P.update(dict(zip(free, v))); return P
    def err(v):
        g = simulate(F, unpack(v)); return float(np.sqrt(np.sum(w * (g - hi) ** 2) / w.sum()))
    best = minimize(err, [P0[k] for k in free], method="Nelder-Mead",
                    options={"maxiter": iters, "maxfev": iters, "adaptive": True, "xatol": 1e-3, "fatol": 1e-4})
    return unpack(best.x), err(best.x)


if __name__ == "__main__":
    if sys.argv[1] == "fit":
        band = sys.argv[3] if len(sys.argv) > 3 else "high"
        x0 = {"b0": 4.5, "gmin": 0.0, "gmax": 6.0} if band == "low" else None
        P, e = fit(sys.argv[2], band=band, x0=x0)
        print(f"rms error {e:.2f} dB"); print(json.dumps({k: round(v, 4) for k, v in P.items()}))
