"""Python twin of native/leveler.c (MemLeveler) + fitting to a leveler-probe measurement.

Model, evaluated once per 20 ms frame (the plugin does exactly the same per 882/960-sample frame):
  S     short-term power, one-pole over frame powers (ts)           L = 10*log10(S)
  I     long-term "memory" level; updated only when L >= I - gate (quiet passages far below the memory are
        ignored, which is what makes the gain stay put after a long loud passage); rises with tiu, falls with tid
  Gs    slow gain  = clamp(g0 + k*(L0 - I), gmin, gmax)
  F     fast reduction toward (1-1/rf)*max(0, L - I - thr), attack tfa, release tfr
  G     = Gs - F  (dB), interpolated across the frame

  python -m soundmode.levmodel fit LABEL [OFFSET_DB]
"""
import json, sys
import numpy as np
from scipy.optimize import minimize
from . import levprobe

KEYS = ["ts", "gate", "tiu", "tid", "g0", "k", "L0", "gmin", "gmax", "thr", "rf", "tfa", "tfr", "i0"]
DEFAULT = {"ts": 0.4, "gate": 15.0, "tiu": 10.0, "tid": 20.0, "g0": 6.0, "k": 0.4, "L0": -30.0, "gmin": -3.0,
           "gmax": 12.0, "thr": 3.0, "rf": 2.0, "tfa": 0.3, "tfr": 0.8, "i0": -40.0}
FR = levprobe.FRAME


def simulate_frames(Lraw, P):
    """Lraw: frame levels dBFS (20 ms). Returns gain dB per frame."""
    co = lambda tau: np.exp(-FR / max(tau, 1e-3))
    a_s, aiu, aid, afa, afr = co(P["ts"]), co(P["tiu"]), co(P["tid"]), co(P["tfa"]), co(P["tfr"])
    pw = 10 ** (Lraw / 10)
    S = 10 ** (P["i0"] / 10); I = P["i0"]; F = 0.0
    G = np.empty(len(Lraw))
    for n, p in enumerate(pw):
        S = a_s * S + (1 - a_s) * p
        L = 10 * np.log10(S + 1e-20)
        if L >= I - P["gate"]:
            a = aiu if L > I else aid
            I = a * I + (1 - a) * L
        Gs = min(max(P["g0"] + P["k"] * (P["L0"] - I), P["gmin"]), P["gmax"])
        Ft = (1 - 1 / max(P["rf"], 1.0)) * max(0.0, L - I - P["thr"])
        a = afa if Ft > F else afr
        F = a * F + (1 - a) * Ft
        G[n] = Gs - F
    return G


def fit(label, offset=0.0, x0=None, iters=4000, corr=None):
    """corr: per-frame chain error (live chain minus model), subtracted from the target (closed-loop refit)."""
    d = np.load(levprobe.RUNS / f"lev_{label}.npz")
    Lraw, target = d["in_db"], d["gain_db"] - offset
    if corr is not None: target = target - corr[: len(target)]
    w = np.ones(len(target)); w[: int(1 / FR)] = 0
    P0 = dict(DEFAULT); P0.update(x0 or {})
    free = [k for k in KEYS if k != "L0"]
    def unpack(v): P = dict(P0); P.update(dict(zip(free, v))); return P
    def err(v):
        g = simulate_frames(Lraw, unpack(v))
        # gain shown with one frame of lag in the measurement (gain applied to the frame it was computed from)
        return float(np.sqrt(np.sum(w * (g - target) ** 2) / w.sum()))
    best = minimize(err, [P0[k] for k in free], method="Nelder-Mead",
                    options={"maxiter": iters, "maxfev": iters, "xatol": 1e-3, "fatol": 1e-4, "adaptive": True})
    P = unpack(best.x); return P, err(best.x)


def chunk(P):
    return ";".join(f"{k}={P[k]:.5g}" for k in KEYS)


if __name__ == "__main__":
    if sys.argv[1] == "fit":
        P, e = fit(sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else 0.0)
        print(f"rms error {e:.2f} dB"); print(json.dumps({k: round(v, 4) for k, v in P.items()})); print(chunk(P))
