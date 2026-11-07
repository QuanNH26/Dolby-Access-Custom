"""Closed-loop refit of MemLeveler: python -m soundmode.levrefit DOLBY_LABEL LIVE_LABEL "<chunk used live>" OFFSET
chain error = live gain - (model(chunk with L0/i0 un-shifted) + offset), smoothed over 1 s, then refit to Dolby minus it."""
import sys
import numpy as np
from scipy.ndimage import median_filter
from . import levmodel, levprobe

dl, ll, ch, off = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
P = {k: float(v) for k, v in (kv.split("=") for kv in ch.split(";"))}
P["L0"] -= off; P["i0"] -= off                     # back to probe-input reference
d = np.load(levprobe.RUNS / f"lev_{dl}.npz"); c = np.load(levprobe.RUNS / f"lev_{ll}.npz")
pred = levmodel.simulate_frames(d["in_db"], P) + off
ce = median_filter(c["gain_db"] - pred, size=int(1 / levprobe.FRAME))
print(f"chain error: mean {ce.mean():+.2f} dB, rms {np.sqrt(np.mean(ce**2)):.2f}")
P2, e = levmodel.fit(dl, off, x0=P, iters=3000, corr=ce)
print(f"refit rms (per frame) {e:.2f} dB")
P2["L0"] += off; P2["i0"] += off
print(levmodel.chunk(P2))
