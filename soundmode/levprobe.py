"""Leveler probe: ~3 min of pink noise with a level schedule built to expose a leveler's time behaviour and
"memory" (loud bursts of 1/3/10/30 s with quiet gaps, a mid plateau, a slow ramp, a loud plateau).

  python -m soundmode.levprobe LABEL [--bypass-hesuvi]
-> dolby-probe/runs/lev_LABEL.npz  with t (s), in_db (input level dBFS rms per 20 ms frame), gain_db (out/in)
"""
import argparse, threading, time, warnings
from pathlib import Path
import numpy as np
from scipy.signal import fftconvolve

warnings.filterwarnings("ignore")
FS = 44100
FRAME = 0.02
RUNS = Path(__file__).resolve().parent.parent / "dolby-probe" / "runs"
DEACT = Path(r"C:\Program Files\EqualizerAPO\config\HeSuVi\deact.txt")
# (level dBFS rms, seconds); a tuple level (a, b) = linear ramp in dB
SCHEDULE = [(-40, 15), (-16, 1), (-40, 8), (-16, 3), (-40, 10), (-16, 10), (-40, 15), (-16, 30), (-40, 20),
            (-28, 15), ((-40, -10), 20), (-10, 10), (-22, 15), (-34, 10)]


def level_curve():
    parts = []
    for lv, sec in SCHEDULE:
        n = int(sec * FS)
        parts.append(np.linspace(lv[0], lv[1], n) if isinstance(lv, tuple) else np.full(n, float(lv)))
    db = np.concatenate(parts)
    k = int(0.01 * FS); db = np.convolve(db, np.ones(k) / k, "same")   # 10 ms smoothing of the steps
    db[:k] = db[k]; db[-k:] = db[-k - 1]
    return db


def stimulus(seed=7):
    db = level_curve(); n = len(db)
    rng = np.random.default_rng(seed)
    X = np.fft.rfft(rng.standard_normal(n)); f = np.fft.rfftfreq(n, 1 / FS); f[0] = f[1]
    x = np.fft.irfft(X / np.sqrt(f), n); x /= x.std()
    return x * 10 ** (db / 20), db


def frames_db(x):
    fr = int(FRAME * FS); m = len(x) // fr
    return 10 * np.log10(np.mean(x[:m * fr].reshape(m, fr) ** 2, 1) + 1e-20)


def play_record(x):
    import soundcard as sc
    spk = sc.default_speaker(); mic = sc.get_microphone(spk.name, include_loopback=True)
    chunks, stop = [], threading.Event()
    def rec():
        with mic.recorder(samplerate=FS, channels=2, blocksize=1024) as r:
            while not stop.is_set(): chunks.append(r.record(numframes=2048))
    th = threading.Thread(target=rec); th.start(); time.sleep(0.5)
    with spk.player(samplerate=FS, channels=2) as p: p.play(np.stack([x, x], 1).astype(np.float32))
    time.sleep(1.0); stop.set(); th.join()
    return np.concatenate(chunks)[:, 0].astype(float)


def align(x, y):
    i0 = int(np.argmax(np.abs(x))) - 2 * FS; seg = x[i0: i0 + 4 * FS]
    c = fftconvolve(y, seg[::-1], "valid"); lag = int(np.argmax(np.abs(c))) - i0
    return y[lag: lag + len(x)]


def main(label, bypass):
    x, _ = stimulus()
    print(f"phat {len(x)/FS:.0f} s noise theo lich muc (dung chinh volume)...", flush=True)
    old = DEACT.read_text() if bypass else None
    try:
        if bypass: DEACT.write_text("Eval: active=false"); time.sleep(1.5)
        y = play_record(x)
    finally:
        if bypass: DEACT.write_text(old)
    y = align(x, y)
    if len(y) < len(x): print("thu thieu du lieu"); return
    ind, outd = frames_db(x), frames_db(y)
    t = np.arange(len(ind)) * FRAME
    RUNS.mkdir(exist_ok=True)
    np.savez(RUNS / f"lev_{label}.npz", t=t, in_db=ind, gain_db=outd - ind)
    g = outd - ind
    for a, b, name in [(10, 14.5, "quiet start"), (15.2, 15.9, "1 s burst"), (16.5, 23.5, "after 1 s"), (38, 46.5, "10 s burst"),
                       (48, 61.5, "after 10 s"), (63, 91.5, "30 s burst"), (93, 111.5, "after 30 s"), (113, 126.5, "-28 plateau"),
                       (148, 156.5, "-10 plateau"), (173, 181.5, "-34 end")]:
        s = (t >= a) & (t < b); print(f"  {name:<14} gain {np.median(g[s]):+6.1f} dB")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("label"); ap.add_argument("--bypass-hesuvi", action="store_true")
    a = ap.parse_args(); main(a.label, a.bypass_hesuvi)
