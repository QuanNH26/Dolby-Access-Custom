"""Surround probe: measure a headphone virtualizer (Dolby Atmos for Headphones) for each 7.1 speaker.

Plays a log sweep on one channel of an 8-channel (7.1) stream at a time, records the stereo result through WASAPI
loopback and deconvolves, keeping the common time base so interaural and inter-speaker delays survive.

  python -m soundmode.surprobe LABEL [--bypass-hesuvi]
-> dolby-probe/runs/sur_LABEL.npz  irs[8, N, 2] (speaker, sample, ear L/R), order FL FR FC LFE BL BR SL SR
"""
import argparse, threading, time, warnings
from pathlib import Path
import numpy as np
from scipy.signal import fftconvolve

warnings.filterwarnings("ignore")
FS = 48000
RUNS = Path(__file__).resolve().parent.parent / "dolby-probe" / "runs"
DEACT = Path(r"C:\Program Files\EqualizerAPO\config\HeSuVi\deact.txt")
CH = ["FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR"]
SWEEP_T, GAP, LEVEL = 3.0, 1.2, -20.0
PRE, N = 512, 8192


def log_sweep(T=SWEEP_T, f1=20, f2=20000):
    t = np.arange(int(T * FS)) / FS; R = np.log(f2 / f1)
    s = np.sin(2 * np.pi * f1 * T / R * (np.exp(t * R / T) - 1))
    fade = int(0.01 * FS); s[:fade] *= np.hanning(2 * fade)[:fade]; s[-fade:] *= np.hanning(2 * fade)[fade:]
    inv = s[::-1] * np.exp(-t * R / T); inv /= np.abs(fftconvolve(s, inv)).max()
    return s, inv


def stimulus():
    rng = np.random.default_rng(3); sw, inv = log_sweep()
    lead, sync = int(1.0 * FS), int(0.4 * FS)
    starts, pos = [], lead + sync
    for _ in CH: pos += int(GAP * FS); starts.append(pos); pos += len(sw)
    x = np.zeros((pos + int(1.5 * FS), 8))
    burst = rng.standard_normal(sync) * 10 ** (-26 / 20)
    x[lead: lead + sync, 0] = burst; x[lead: lead + sync, 1] = burst          # sync on FL + FR
    for c, s0 in enumerate(starts): x[s0: s0 + len(sw), c] = sw * 10 ** (LEVEL / 20)
    x += rng.standard_normal(x.shape) * 10 ** (-90 / 20)
    return x.astype(np.float32), starts, (lead, lead + sync), sw, inv


def play_record(x, device=None):
    """Plays through native/play71.exe (WASAPI, WAVEFORMATEXTENSIBLE 7.1) - the soundcard library only feeds channel 1."""
    import subprocess, tempfile, soundcard as sc
    from . import wav71
    spk = sc.default_speaker()
    if device:   # custom 7.1 path: record the virtual cable's capture side (the binaural result, before "Listen")
        mic = next(m for m in sc.all_microphones() if "CABLE Output" in m.name)
    else:
        mic = sc.get_microphone(spk.name, include_loopback=True)
    chunks, stop = [], threading.Event()
    def rec():
        with mic.recorder(samplerate=FS, channels=2, blocksize=1024) as r:
            while not stop.is_set(): chunks.append(r.record(numframes=2048))
    th = threading.Thread(target=rec, daemon=True); th.start(); time.sleep(0.5)
    with tempfile.TemporaryDirectory() as d:
        w = str(Path(d) / "probe71.wav"); wav71.write(w, x, FS)
        subprocess.run([str(Path(__file__).resolve().parent / "native" / "play71.exe"), w] + ([device] if device else []), check=True,
                       capture_output=True, timeout=len(x) / FS + 30, creationflags=subprocess.CREATE_NO_WINDOW)
    time.sleep(1.0); stop.set(); th.join(5)
    return mic.name, np.concatenate(chunks).astype(np.float64)


def main(label, bypass, device=None):
    x, starts, (s0, s1), sw, inv = stimulus()
    print(f"phat {len(x)/FS:.0f} s sweep tung loa 7.1 (dung chinh volume)...", flush=True)
    old = DEACT.read_text() if bypass else None
    try:
        if bypass: DEACT.write_text("Eval: active=false"); time.sleep(1.5)
        dev, y = play_record(x, device)
    finally:
        if bypass: DEACT.write_text(old)
    a = x[s0:s1, 0].astype(float); b = y[: s1 + 10 * FS].sum(1)
    lag = int(np.argmax(np.abs(fftconvolve(b, a[::-1], "valid")))) - s0
    y = y[lag:]
    irs = np.zeros((8, N, 2))
    for c, st in enumerate(starts):
        seg = y[st - PRE: st + len(sw) + int(GAP * FS)]
        for e in (0, 1):
            d = fftconvolve(seg[:, e], inv) / 10 ** (LEVEL / 20)
            z = len(sw) - 1 + PRE                          # sample of zero delay relative to the sweep start
            irs[c, :, e] = d[z - PRE: z - PRE + N]
    RUNS.mkdir(exist_ok=True); np.savez(RUNS / f"sur_{label}.npz", irs=irs, fs=FS, pre=PRE)
    print(f"output {dev}, lag {lag}")
    f = np.fft.rfftfreq(N, 1 / FS); band = (f > 700) & (f < 1400)
    for c, name in enumerate(CH):
        H = np.fft.rfft(irs[c], axis=0)
        lv = [10 * np.log10(np.mean(np.abs(H[band, e]) ** 2) + 1e-20) for e in (0, 1)]
        pk = [int(np.argmax(np.abs(irs[c, :, e]))) for e in (0, 1)]
        print(f"  {name:<4} L ear {lv[0]:6.1f} dB  R ear {lv[1]:6.1f} dB   peak L {(pk[0]-PRE)/FS*1000:6.2f} ms  R {(pk[1]-PRE)/FS*1000:6.2f} ms")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("label"); ap.add_argument("--bypass-hesuvi", action="store_true")
    ap.add_argument("--device", help="render endpoint GUID to play into (default: default device); recording is always the default device loopback")
    a = ap.parse_args(); main(a.label, a.bypass_hesuvi, a.device)
