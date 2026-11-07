"""Speech probe: measure what the current sound chain does to real speech (for modes that only react to dialogue).

Uses Windows' built-in text-to-speech (System.Speech, nothing downloaded) to make ~30 s of speech, plays it
quiet (-32 dBFS rms) then loud (-16 dBFS rms) on the default output, records WASAPI loopback and prints:
  * gain out/in for the quiet and the loud half (a leveler shows up as quiet gain > loud gain)
  * transfer function per band relative to 1 kHz, over speech-active frames only

  python -m soundmode.speechprobe LABEL     -> dolby-probe/runs/speech_LABEL.json
"""
import json, subprocess, sys, tempfile, threading, time, warnings
from pathlib import Path
import numpy as np
from scipy.io import wavfile
from scipy.signal import csd, welch, fftconvolve, resample_poly

warnings.filterwarnings("ignore")
FS = 44100
RUNS = Path(__file__).resolve().parent.parent / "dolby-probe" / "runs"
BANDS = [125, 250, 500, 1000, 2000, 3000, 4000, 6000, 8000, 12000]
TEXT = ("Good evening, and welcome to the news. Tonight we look at the weather across the region, where heavy rain is "
        "expected through the weekend. In other news, the city council has approved a new plan for public transport. "
        "Officials say the first buses will run early next year. Now, let us turn to sports. The home team won "
        "last night's match by two goals, after a slow start in the first half. That is all for now, thank you for watching.")


def tts(path):
    ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          f"$s.Rate = 0; $s.SetOutputToWaveFile('{path}'); $s.Speak(@'\n{TEXT}\n'@); $s.Dispose()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, capture_output=True,
                   creationflags=subprocess.CREATE_NO_WINDOW)
    fs, x = wavfile.read(path); x = x.astype(float)
    if x.ndim > 1: x = x.mean(1)
    if fs != FS: x = resample_poly(x, FS, fs)
    return x / (np.sqrt(np.mean(x ** 2)) + 1e-12)


def play_record(stim):
    import soundcard as sc
    spk = sc.default_speaker(); mic = sc.get_microphone(spk.name, include_loopback=True)
    chunks, stop = [], threading.Event()
    def rec():
        with mic.recorder(samplerate=FS, channels=2, blocksize=1024) as r:
            while not stop.is_set(): chunks.append(r.record(numframes=2048))
    th = threading.Thread(target=rec); th.start(); time.sleep(0.5)
    with spk.player(samplerate=FS, channels=2) as p: p.play(np.stack([stim, stim], 1).astype(np.float32))
    time.sleep(0.8); stop.set(); th.join()
    return spk.name, np.concatenate(chunks)[:, 0].astype(float)


def main(label):
    with tempfile.TemporaryDirectory() as d:
        sp = tts(str(Path(d) / "speech.wav"))
    gap = np.zeros(FS)
    q, l = sp * 10 ** (-32 / 20), sp * 10 ** (-16 / 20)
    stim = np.concatenate([gap, q, gap, l, gap])
    n = len(sp); segs = {"quiet": (FS, FS + n), "loud": (2 * FS + n, 2 * FS + 2 * n)}
    print(f"phat {len(stim)/FS:.0f} s tieng noi (nho roi to)...", flush=True)
    dev, y = play_record(stim)
    c = fftconvolve(y, stim[::-1], "valid") if len(y) > len(stim) else np.array([0])
    lag = int(np.argmax(np.abs(c))); y = y[lag: lag + len(stim)]
    if len(y) < len(stim) or np.std(y) < 1e-7: print("khong thu duoc am thanh"); return
    res = {"device": dev, "gain_dB": {}, "bands": BANDS, "eq_dB": {}}
    for k, (a, b) in segs.items():
        x0, y0 = stim[a:b], y[a:b]
        fr = 1024; m = len(x0) // fr
        e = np.mean(x0[:m * fr].reshape(m, fr) ** 2, 1); act = e > 0.05 * np.median(e[e > 0])
        xa = x0[:m * fr].reshape(m, fr)[act].ravel(); ya = y0[:m * fr].reshape(m, fr)[act].ravel()
        res["gain_dB"][k] = round(10 * np.log10(np.mean(ya ** 2) / np.mean(xa ** 2)), 2)
        f, P = csd(xa, ya, fs=FS, nperseg=4096); _, Q = welch(xa, fs=FS, nperseg=4096); H = np.abs(P / Q)
        bd = [10 * np.log10(np.mean(H[(f >= b0 / 2 ** .25) & (f < b0 * 2 ** .25)] ** 2)) for b0 in BANDS]
        ref = bd[BANDS.index(1000)]; res["eq_dB"][k] = [round(v - ref, 2) for v in bd]
    RUNS.mkdir(exist_ok=True); (RUNS / f"speech_{label}.json").write_text(json.dumps(res))
    print(f"output: {dev}")
    print(f"gain tieng noi: nho {res['gain_dB']['quiet']:+.1f} dB, to {res['gain_dB']['loud']:+.1f} dB "
          f"(chenh {res['gain_dB']['quiet'] - res['gain_dB']['loud']:+.1f} dB = muc leveler)")
    print("bands Hz   " + " ".join(f"{b:>6}" for b in BANDS))
    for k, v in res["eq_dB"].items(): print(f"{k:<10} " + " ".join(f"{x:6.1f}" for x in v))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "test")
