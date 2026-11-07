"""Export a surround-probe run to a HeSuVi 14-channel HRIR (48 kHz and 44.1 kHz).

  python -m soundmode.surexport LABEL   -> dolby-probe/runs/sur_LABEL_48.wav / _44.wav
HeSuVi 14-channel order (speaker -> ear): FL->L FL->R SL->L SL->R BL->L BL->R C->L FR->R FR->L SR->R SR->L BR->R BR->L C->R
(HeSuVi names them L0 R1 SL0 SR1 RL0 RR1 C0 R0 L1 SR0 SL1 RR0 RL1 C1; mix.txt sums the left-ear ones into L)
"""
import sys
import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly
from .surprobe import RUNS, CH

# HeSuVi slot -> (speaker, ear)
ORDER = [("FL", 0), ("FL", 1), ("SL", 0), ("SL", 1), ("BL", 0), ("BL", 1), ("FC", 0),
         ("FR", 1), ("FR", 0), ("SR", 1), ("SR", 0), ("BR", 1), ("BR", 0), ("FC", 1)]


def export(label, length=4096):
    d = np.load(RUNS / f"sur_{label}.npz"); irs, fs, pre = d["irs"], int(d["fs"]), int(d["pre"])
    start = max(pre - 64, 0)                                  # keep a little pre-ringing, drop the rest of the lead
    win = np.r_[np.ones(length - 512), np.hanning(1024)[512:]]
    h = np.stack([irs[CH.index(s), start:start + length, e] * win for s, e in ORDER], 1)
    peak = max(np.abs(np.fft.rfft(h[:, [0, 8]].sum(1), 16384)).max(), np.abs(np.fft.rfft(h, 16384, axis=0)).max())
    g = 10 ** (-1 / 20) / peak; h *= g                        # loudest path peaks at -1 dB
    out48 = RUNS / f"sur_{label}_48.wav"; out44 = RUNS / f"sur_{label}_44.wav"
    if fs == 48000:
        wavfile.write(out48, 48000, h.astype(np.float32)); wavfile.write(out44, 44100, resample_poly(h, 147, 160, axis=0).astype(np.float32))
    else:
        wavfile.write(out44, 44100, h.astype(np.float32)); wavfile.write(out48, 48000, resample_poly(h, 160, 147, axis=0).astype(np.float32))
    print(f"gain {20*np.log10(g):+.1f} dB -> {out48.name}, {out44.name}")
    return out48, out44


if __name__ == "__main__":
    export(sys.argv[1])
