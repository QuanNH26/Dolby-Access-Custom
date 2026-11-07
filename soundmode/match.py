"""Closed-loop match: compare a measured reconstruction (HeSuVi on, Dolby off) with the Dolby run it copies.

  python -m soundmode.match DOLBY_LABEL CUSTOM_LABEL
prints absolute level per sweep level, gain-trajectory difference and the residual EQ (Dolby - custom),
and writes runs/match_<CUSTOM>.json with {"trim_dB", "residual_geq"} for the next iteration.
"""
import json, sys
import numpy as np
from . import measure

RUNS = measure.RUNS


def compare(dl, cl):
    d = json.loads((RUNS / f"{dl}.json").read_text()); c = json.loads((RUNS / f"{cl}.json").read_text())
    print("muc tuyet doi o 1 kHz (sweep giua, L ear):   Dolby   custom   chenh")
    diffs = []
    for k in d["static"]:
        if not k.startswith("sweep_C"): continue
        a, b = d["static"][k]["Lear"][5], c["static"][k]["Lear"][5]; diffs.append(a - b)
        print(f"  {k:<12}                              {a:6.1f}  {b:6.1f}  {a - b:+6.1f}")
    gd, gc = np.array(d["step_gain_dB"]), np.array(c["step_gain_dB"]); n = min(len(gd), len(gc))
    traj = gd[:n] - gc[:n]
    print(f"quy dao gain buoc muc: lech trung binh {np.mean(traj):+.1f} dB, rms sau bu muc {np.std(traj):.2f} dB")
    F, gD = measure.noise_geq(dl, absolute=True); _, gC = measure.noise_geq(cl, absolute=True)
    res = gD - gC; trim = float(np.median(res[(F >= 200) & (F <= 4000)]))
    shape = res - trim
    print(f"noise (nhac thuc te): Dolby to hon custom {trim:+.1f} dB; lech hinh dang EQ rms {np.sqrt(np.mean(shape**2)):.2f} dB")
    print("  lech theo dai: " + "; ".join(f"{f} {v:+.1f}" for f, v in list(zip(F, shape))[::6]))
    out = {"trim_dB": round(trim, 2), "residual_geq": [round(float(v), 2) for v in shape], "freqs": [int(f) for f in F],
           "sweep_diff_1k": [round(x, 2) for x in diffs], "traj_mean": round(float(np.mean(traj)), 2)}
    (RUNS / f"match_{cl}.json").write_text(json.dumps(out))
    return out


if __name__ == "__main__":
    compare(sys.argv[1], sys.argv[2])
