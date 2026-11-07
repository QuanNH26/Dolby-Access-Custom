"""Offline check of the plugin's adaptive-treble stage against soundmode/ieqmodel.py on the IEQ probe stimulus."""
import sys
from pathlib import Path
import numpy as np
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent.parent))
from test_leveler import run
from soundmode import ieqmodel, ieqprobe

Q = {"q_ts": 0.001, "q_tru": 3.1644, "q_trd": 36.0675, "q_b0": -1.7752, "q_a": 0.1817, "q_c": 0.4652, "q_f0": 1.1707,
     "q_gmin": -4.2124, "q_gmax": 2.5558, "q_tg": 0.1631, "q_base": -1.6, "q_fh": 3000}
LEV = "ts=0.01;gate=6;tiu=40;tid=6;g0=0;k=0;L0=-30;gmin=0;gmax=0;thr=99;rf=1;tfa=0.1;tfr=0.2;i0=-30"   # leveler = unity
chunk = LEV + ";ieq=1;" + ";".join(f"{k}={v}" for k, v in Q.items())
x, tilt = ieqprobe.stimulus()
y = run(chunk, x)
t, _, lo, hi = ieqprobe.analyse(x, y, tilt)
P = {k[2:]: v for k, v in Q.items() if k not in ("q_base", "q_fh")}; P["ts_q"] = Q["q_ts"]; P["tr_up"] = Q["q_tru"]; P["tr_dn"] = Q["q_trd"]
g = ieqmodel.simulate(ieqmodel.feature(x), P) - Q["q_base"]
tf = (np.arange(len(g)) + 0.5) * ieqmodel.FR
gm = np.interp(t, tf, g)
d = hi - gm
s = t > 2
print(f"plugin shelf vs model (high band): mean {d[s].mean():+.2f} dB, rms {np.sqrt(np.mean(d[s]**2)):.2f} dB")
for a in range(0, 126, 10):
    k = (t >= a) & (t < a + 2); print(f"{a:3d}s plugin {np.median(hi[k]):+5.2f} model {np.median(gm[k]):+5.2f}")
