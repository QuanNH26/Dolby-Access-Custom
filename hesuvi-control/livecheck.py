"""Live check: play ~5 s of quiet pink noise to the default output, record it back through WASAPI loopback
(post Equalizer APO) and measure the "Warm" tilt = (63-200 Hz) - (4-12 kHz) relative gain.

  ~0 dB    -> nothing is processing the audio
  ~4-5 dB  -> one Warm layer (HeSuVi on, Dolby off: expected; or HeSuVi off with Dolby on)
  ~8+ dB   -> two layers: HeSuVi AND Dolby Spatial sound are both on
"""
import threading, time, warnings
import numpy as np
from scipy.signal import csd, welch, fftconvolve
warnings.filterwarnings("ignore")
FS = 44100

def main():
    import soundcard as sc
    spk = sc.default_speaker(); mic = sc.get_microphone(spk.name, include_loopback=True)
    rng = np.random.default_rng(1)
    n = int(5 * FS); X = np.fft.rfft(rng.standard_normal(n)); f = np.fft.rfftfreq(n, 1 / FS); f[0] = f[1]
    x = np.fft.irfft(X / np.sqrt(f), n); x *= 10 ** (-30 / 20) / x.std()
    fade = FS // 20; x[:fade] *= np.linspace(0, 1, fade); x[-fade:] *= np.linspace(1, 0, fade)
    stim = np.stack([x, x], 1).astype(np.float32)
    chunks, stop = [], threading.Event()
    def rec():
        with mic.recorder(samplerate=FS, channels=2, blocksize=1024) as r:
            while not stop.is_set(): chunks.append(r.record(numframes=2048))
    th = threading.Thread(target=rec); th.start(); time.sleep(0.4)
    with spk.player(samplerate=FS, channels=2) as p: p.play(stim)
    time.sleep(0.6); stop.set(); th.join()
    y = np.concatenate(chunks)[:, 0].astype(float)
    c = fftconvolve(y, x[FS: FS + FS // 2][::-1], "valid") if len(y) > FS else np.array([0])
    lag = int(np.argmax(np.abs(c))) - FS
    a = x[FS: 4 * FS]; b = y[lag + FS: lag + 4 * FS]
    if len(b) < len(a) or np.std(b) < 1e-6:
        print(f"output: {spk.name}\nRESULT=FAIL khong thu duoc am thanh (thiet bi mac dinh co dung tai nghe khong?)"); return
    fr, P = csd(a, b, fs=FS, nperseg=8192); _, Q = welch(a, fs=FS, nperseg=8192); H = np.abs(P / Q)
    band = lambda lo, hi: 10 * np.log10(np.mean(H[(fr >= lo) & (fr < hi)] ** 2))
    low, mid, high = band(63, 200), band(800, 1250), band(4000, 12000)
    tilt = (low - mid) - (high - mid)
    print(f"output: {spk.name}")
    print(f"bass {low - mid:+.1f} dB, treble {high - mid:+.1f} dB (so voi 1 kHz)  -> do nghieng Warm {tilt:+.1f} dB")
    if tilt < 1.5:   print("=> KHONG co xu ly nao (HeSuVi tat / APO khong chay).  RESULT=OFF")
    elif tilt < 7:   print("=> Dang co 1 lop Warm - dung nhu mong doi khi HeSuVi bat.  RESULT=ONE")
    else:            print("=> Co 2 LOP xu ly chong nhau: hay tat Spatial sound (Dolby) khi dung HeSuVi!  RESULT=FAIL")

if __name__ == "__main__":
    main()
