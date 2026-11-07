"""Offline check of the plugin's adaptive-bass stage against soundmode/ieqmodel.py (band="low")."""
import sys
from pathlib import Path
import numpy as np
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent.parent))
from test_leveler import run
from soundmode import ieqmodel, ieqprobe

L = {"l_ts": 5.3411, "l_tru": 0.6121, "l_trd": 63.5109, "l_b0": 4.0431, "l_a": 0.4953, "l_c": -0.4408, "l_f0": 6.5073,
     "l_gmin": -0.0203, "l_gmax": 4.1277, "l_tg": 0.001, "l_base": 3.3, "l_fl": 200}
LEV = "ts=0.01;gate=6;tiu=40;tid=6;g0=0;k=0;L0=-30;gmin=0;gmax=0;thr=99;rf=1;tfa=0.1;tfr=0.2;i0=-30"
chunk = LEV + ";bass=1;" + ";".join(f"{k}={v}" for k, v in L.items())
x, tilt = ieqprobe.stimulus()
y = run(chunk, x)
t, _, lo, hi = ieqprobe.analyse(x, y, tilt)
P = {"ts_q": L["l_ts"], "tr_up": L["l_tru"], "tr_dn": L["l_trd"], "b0": L["l_b0"], "a": L["l_a"], "c": L["l_c"],
     "f0": L["l_f0"], "gmin": L["l_gmin"], "gmax": L["l_gmax"], "tg": L["l_tg"]}
g = ieqmodel.simulate(ieqmodel.feature(x, band="low"), P) - L["l_base"]
tf = (np.arange(len(g)) + 0.5) * ieqmodel.FR
gm = np.interp(t, tf, g); s = t > 2; d = lo - gm
print(f"plugin low shelf vs model (63-250 Hz): mean {d[s].mean():+.2f} dB, rms {np.sqrt(np.mean(d[s]**2)):.2f} dB; treble untouched rms {np.sqrt(np.mean(hi[s]**2)):.2f}")
