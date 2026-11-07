"""Black-box probe for headphone virtualizers (Dolby Atmos for Headphones, HeSuVi, ...).

Plays a stimulus sequence to the default output and records the same endpoint through
WASAPI loopback, then extracts:
  * static binaural responses (log sweeps) at several levels  -> HRTF + EQ, level dependence
  * steady-state transfer function for differently tilted noises -> content-adaptive (dynamic) EQ
  * gain trajectory across level steps                         -> leveler/compressor attack, release, ratio

Usage:
  python probe.py measure LABEL [--bypass-hesuvi]   # record + analyse one condition
  python probe.py compare TARGET BASE               # TARGET/BASE difference -> EAPO GraphicEQ
"""
import argparse, json, threading, time, warnings
from pathlib import Path
import numpy as np
from scipy.io import wavfile
from scipy.signal import csd, welch, fftconvolve

warnings.filterwarnings("ignore")
FS = 44100
OUT = Path(__file__).resolve().parent / "runs"
HESUVI_HRIR = Path(r"C:\Program Files\EqualizerAPO\config\HeSuVi\hrir\44\atmos.wav")
HESUVI_DEACT = Path(r"C:\Program Files\EqualizerAPO\config\HeSuVi\deact.txt")
BANDS = [31, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 12000, 16000]
GEQ_F = np.round(np.geomspace(20, 20000, 61)).astype(int)  # 1/6-oct points for GraphicEQ
SWEEP_LEVELS = [-36, -28, -20, -12]                          # dBFS peak, both channels
NOISE_DB = -22                                               # dBFS RMS for adaptive-EQ test
STEP_DB = (-40, -14)                                         # level-step test


# ---------------------------------------------------------------- stimulus
def db(x): return 10 ** (x / 20)

def log_sweep(T=3.0, f1=20, f2=20000):
    t = np.arange(int(T * FS)) / FS
    R = np.log(f2 / f1)
    s = np.sin(2 * np.pi * f1 * T / R * (np.exp(t * R / T) - 1))
    fade = int(0.01 * FS); s[:fade] *= np.hanning(2 * fade)[:fade]; s[-fade:] *= np.hanning(2 * fade)[fade:]
    inv = s[::-1] * np.exp(-t * R / T)                       # Farina inverse filter
    norm = np.abs(fftconvolve(s, inv)).max()
    return s, inv / norm

def shaped_noise(n, tilt, rng):
    X = np.fft.rfft(rng.standard_normal(n)); f = np.fft.rfftfreq(n, 1 / FS); f[0] = f[1]
    g = 1 / np.sqrt(f)                                       # pink
    if tilt == "bass":  g *= 1 + (db(9) - 1) / (1 + (f / 200) ** 2)
    if tilt == "bright": g *= 1 + (db(9) - 1) / (1 + (3000 / f) ** 2)
    x = np.fft.irfft(X * g, n); return x / np.sqrt(np.mean(x ** 2))

def build_stimulus():
    rng = np.random.default_rng(7)
    seg, mark = [], {}
    def add(name, x):
        start = sum(len(s) for s in seg); seg.append(x); mark[name] = (start, start + len(x))
    gap = lambda s: np.zeros((int(s * FS), 2))
    add("lead", gap(1.0))
    add("sync", np.repeat(rng.standard_normal((int(0.4 * FS), 1)), 2, 1) * db(-26))  # unique burst for alignment
    sw, inv = log_sweep()
    for name, gl, gr, lvl in [("sweep_L", 1, 0, -20), ("sweep_R", 0, 1, -20)] + \
                             [(f"sweep_C{l}", 1, 1, l) for l in SWEEP_LEVELS]:
        add("gap_" + name, gap(1.0)); add(name, np.stack([sw * gl, sw * gr], 1) * db(lvl))
    add("gap_noise", gap(1.0))
    for tilt in ["pink", "bass", "bright", "pink2"]:
        x = shaped_noise(int(8 * FS), tilt.rstrip("2"), rng) * db(NOISE_DB)
        add("noise_" + tilt, np.stack([x, x], 1))
    lo, hi = STEP_DB
    base = shaped_noise(int(18 * FS), "pink", rng)
    env = np.r_[np.full(6 * FS, db(lo)), np.full(6 * FS, db(hi)), np.full(6 * FS, db(lo))]
    add("steps", np.stack([base * env, base * env], 1))
    add("tail", gap(1.5))
    x = np.concatenate(seg)
    x += rng.standard_normal(x.shape) * db(-84)              # keeps WASAPI loopback stream alive
    return x.astype(np.float32), mark, inv


# ---------------------------------------------------------------- play + record
def play_record(x):
    import soundcard as sc
    spk = sc.default_speaker()
    mic = sc.get_microphone(spk.name, include_loopback=True)
    print(f"output/loopback: {spk.name}")
    chunks, stop = [], threading.Event()
    def rec():
        with mic.recorder(samplerate=FS, channels=2, blocksize=1024) as r:
            while not stop.is_set(): chunks.append(r.record(numframes=2048))
    th = threading.Thread(target=rec); th.start(); time.sleep(0.5)
    with spk.player(samplerate=FS, channels=2) as p: p.play(x)
    time.sleep(1.0); stop.set(); th.join()
    return np.concatenate(chunks).astype(np.float64)

def align(stim, rec, mark):
    s0, s1 = mark["sync"]
    a, b = stim[s0:s1].sum(1), rec[: s0 + 10 * FS].sum(1)   # search the first ~10 s only
    c = fftconvolve(b, a[::-1], mode="valid")
    lag = int(np.argmax(np.abs(c))) - s0
    y = rec[lag:lag + len(stim)]
    if len(y) < len(stim): y = np.vstack([y, np.zeros((len(stim) - len(y), 2))])
    return y, lag


# ---------------------------------------------------------------- analysis
def band_db(f, H):
    return [10 * np.log10(np.mean(np.abs(H[(f >= b / 2 ** (1 / 6)) & (f < b * 2 ** (1 / 6))]) ** 2) + 1e-30) for b in BANDS]

def smooth_db(f, H, pts=GEQ_F, frac=6):
    out = []
    for p in pts:
        m = (f >= p / 2 ** (0.5 / frac)) & (f < p * 2 ** (0.5 / frac))
        v = np.abs(H[m]) ** 2 if m.any() else np.abs(H[np.argmin(np.abs(f - p))]) ** 2  # nearest bin at low f
        out.append(10 * np.log10(np.mean(v) + 1e-30))
    return np.array(out)

def ir_from_sweep(y, inv, lvl):
    ir = np.stack([fftconvolve(y[:, c], inv) for c in (0, 1)], 1) / db(lvl)
    pk = np.argmax(np.abs(ir).sum(1))
    return ir[pk - 256: pk - 256 + 8192]                     # ~185 ms window incl. pre-ringing

def analyse(stim, y, mark, inv):
    res = {"bands": BANDS}
    seg = lambda k, pad=0: y[mark[k][0]: mark[k][1] + pad]
    ins = lambda k: stim[mark[k][0]: mark[k][1]]
    # 1. static responses
    irs = {}
    for k in mark:
        if not k.startswith("sweep_"): continue
        lvl = -20 if k in ("sweep_L", "sweep_R") else int(k[7:])
        irs[k] = ir_from_sweep(seg(k, int(1.0 * FS)), inv, lvl)
    f = np.fft.rfftfreq(16384, 1 / FS)
    spec = {k: np.fft.rfft(v, 16384, axis=0) for k, v in irs.items()}
    res["static"] = {k: {"Lear": band_db(f, H[:, 0]), "Rear": band_db(f, H[:, 1])} for k, H in spec.items()}
    sl = res["static"]["sweep_L"]
    res["crossfeed_dB_1k"] = float(sl["Rear"][5] - sl["Lear"][5])
    ref = f"sweep_C{SWEEP_LEVELS[-2]}"
    res["centre_geq_dB"] = smooth_db(f, spec[ref][:, 0]).tolist()
    res["level_dependence"] = {k: (np.array(res["static"][k]["Lear"]) - np.array(res["static"][ref]["Lear"])).round(2).tolist()
                               for k in spec if k.startswith("sweep_C")}
    # 2. content-adaptive EQ: steady-state H for each noise (last 4 s) relative to pink
    Hn = {}
    for t in ["pink", "bass", "bright", "pink2"]:
        a, b = ins("noise_" + t)[:, 0], seg("noise_" + t)[:, 0]
        s = len(a) // 2
        fw, Pab = csd(a[s:], b[s:], fs=FS, nperseg=8192); _, Paa = welch(a[s:], fs=FS, nperseg=8192)
        Hn[t] = Pab / Paa
    res["adaptive_vs_pink"] = {t: (np.array(band_db(fw, Hn[t])) - np.array(band_db(fw, Hn["pink"]))).round(2).tolist()
                               for t in ["bass", "bright", "pink2"]}
    # adaptation over time inside "bright" (first 4 s, 0.5 s windows) vs its own steady state
    a, b = ins("noise_bright")[:, 0], seg("noise_bright")[:, 0]
    traj = []
    for i in range(0, len(a) - FS // 2, FS // 4):
        fw2, Pab = csd(a[i:i + FS // 2], b[i:i + FS // 2], fs=FS, nperseg=4096); _, Paa = welch(a[i:i + FS // 2], fs=FS, nperseg=4096)
        traj.append(band_db(fw2, Pab / Paa))
    traj = np.array(traj); res["bright_traj_dB"] = (traj - traj[-1]).round(2).tolist()
    # 3. level steps: broadband gain (out/in) per 20 ms frame
    a, b = ins("steps").sum(1), seg("steps").sum(1)
    fr = int(0.02 * FS); n = len(a) // fr
    ga = 10 * np.log10(np.mean(b[:n * fr].reshape(n, fr) ** 2, 1) / np.mean(a[:n * fr].reshape(n, fr) ** 2, 1) + 1e-30)
    res["step_gain_dB"] = ga.round(2).tolist()
    def tconst(seg_g, t0):
        g0, g1 = np.median(seg_g[:10]), np.median(seg_g[-25:])
        if abs(g1 - g0) < 1.0: return None, round(float(g1 - g0), 2)
        k = np.argmax(np.abs(seg_g - g0) >= 0.632 * abs(g1 - g0)) - 10  # 10 pre-step frames
        return round(float(k) * 0.02, 3), round(float(g1 - g0), 2)
    s1, s2 = 6 * 50, 12 * 50
    res["attack"] = dict(zip(["tau_s", "gain_change_dB"], tconst(ga[s1 - 10: s2], 0)))
    res["release"] = dict(zip(["tau_s", "gain_change_dB"], tconst(ga[s2 - 10:], 0)))
    lo, hi = np.median(ga[s1 - 60: s1 - 5]), np.median(ga[s2 - 60: s2 - 5])
    din = STEP_DB[1] - STEP_DB[0]; dout = din + (hi - lo)
    res["steady_ratio"] = round(din / dout, 2) if dout > 0 else None
    return res, irs

def report(res, label):
    L = [f"# {label}", "", "bands Hz          " + " ".join(f"{b:>6}" for b in BANDS)]
    for k, v in res["static"].items():
        L.append(f"{k:12s} Lear  " + " ".join(f"{x:6.1f}" for x in v["Lear"]))
        L.append(f"{'':12s} Rear  " + " ".join(f"{x:6.1f}" for x in v["Rear"]))
    L += ["", f"crossfeed @1k (L-only, R ear - L ear): {res['crossfeed_dB_1k']:.1f} dB  (~-inf/very low = no virtualizer)", "",
          "level dependence (centre sweep vs -20 dBFS, L ear):"]
    for k, v in res["level_dependence"].items(): L.append(f"  {k:12s}" + " ".join(f"{x:6.1f}" for x in v))
    L += ["", "content-adaptive EQ, steady state vs pink (0 everywhere = static EQ):"]
    for k, v in res["adaptive_vs_pink"].items(): L.append(f"  {k:12s}" + " ".join(f"{x:6.1f}" for x in v))
    L += ["", f"level steps {STEP_DB[0]} -> {STEP_DB[1]} dBFS: attack {res['attack']}  release {res['release']}  steady ratio {res['steady_ratio']}"]
    return "\n".join(L)

def geq_line(db_vals):
    return "GraphicEQ: " + "; ".join(f"{f} {v:.1f}" for f, v in zip(GEQ_F, db_vals))


# ---------------------------------------------------------------- commands
def cmd_measure(label, bypass):
    OUT.mkdir(exist_ok=True)
    stim, mark, inv = build_stimulus()
    print(f"stimulus {len(stim)/FS:.0f} s - close other audio apps, keep volume moderate")
    old = HESUVI_DEACT.read_text() if bypass else None
    try:
        if bypass:
            HESUVI_DEACT.write_text("Eval: active=false"); time.sleep(1.5)
        rec = play_record(stim)
    finally:
        if bypass: HESUVI_DEACT.write_text(old)
    y, lag = align(stim, rec, mark)
    wavfile.write(OUT / f"{label}_rec.wav", FS, y.astype(np.float32))
    finish(label, stim, y, mark, inv, lag)

def cmd_reanalyse(label):
    stim, mark, inv = build_stimulus()
    _, y = wavfile.read(OUT / f"{label}_rec.wav")
    finish(label, stim, y.astype(np.float64), mark, inv, None)

def finish(label, stim, y, mark, inv, lag):
    res, irs = analyse(stim, y, mark, inv); res["lag"] = lag
    np.savez(OUT / f"{label}_irs.npz", **irs)
    (OUT / f"{label}.json").write_text(json.dumps(res))
    txt = report(res, label); (OUT / f"{label}.txt").write_text(txt, encoding="utf-8"); print(txt)

def centre_from_hrir(path=HESUVI_HRIR):
    _, h = wavfile.read(path); h = h.astype(np.float64)
    if h.shape[1] == 7: h = np.concatenate([h, h], 1)
    f = np.fft.rfftfreq(16384, 1 / FS)
    return smooth_db(f, np.fft.rfft(h[:, 0] + h[:, 8], 16384))   # L spk + R spk -> left ear

def cmd_compare(target, base):
    """GraphicEQ that turns BASE into TARGET. BASE = run label, or 'atmos_hrir' (HeSuVi's atmos.wav)."""
    a = json.loads((OUT / f"{target}.json").read_text())
    b = centre_from_hrir() if base == "atmos_hrir" else np.array(json.loads((OUT / f"{base}.json").read_text())["centre_geq_dB"])
    d = np.array(a["centre_geq_dB"]) - b
    peak = d.max(); d -= peak                                 # never boost -> no clipping
    line = geq_line(d)
    (OUT / f"{target}_minus_{base}_geq.txt").write_text(
        f"# {target} relative to {base}; overall level offset removed: {peak:+.1f} dB\n{line}\n")
    print(f"level offset {peak:+.1f} dB (applied as cut)\n{line}")

def cmd_export_hrir(label):
    """HeSuVi 14ch HRIR: front L/R pairs from the measurement, other speakers from atmos.wav."""
    from scipy.signal import resample_poly
    irs = np.load(OUT / f"{label}_irs.npz"); L, R = irs["sweep_L"], irs["sweep_R"]
    n = 4096; win = np.r_[np.ones(n - 1024), np.hanning(2048)[1024:]]
    _, base = wavfile.read(HESUVI_HRIR); base = base.astype(np.float64)
    if base.shape[1] == 7: base = np.concatenate([base, base], 1)
    h = np.zeros((n, 14)); m = min(n, len(base)); h[:m] = base[:m]
    # order: L0 R1 SL0 SR1 RL0 RR1 C0 | R0 L1 SR0 SL1 RR0 RL1 C1
    h[:, 0], h[:, 1] = L[:n, 0] * win, L[:n, 1] * win          # L speaker -> left / right ear
    h[:, 7], h[:, 8] = R[:n, 1] * win, R[:n, 0] * win          # R speaker -> right / left ear
    Hc = np.abs(np.fft.rfft(h[:, 0] + h[:, 8], 16384))          # centre-panned, left ear
    g = db(-1) / Hc.max(); h *= g                               # headroom: centre peak at -1 dB
    for sub, fs, x in [("44", FS, h), ("48", 48000, resample_poly(h, 160, 147, axis=0))]:
        out = OUT / f"{label}_{sub}.wav"; wavfile.write(out, fs, x.astype(np.float32)); print("wrote", out)
    print(f"gain applied {20*np.log10(g):+.1f} dB. Copy: _48.wav -> hrir/{label}.wav, _44.wav -> hrir/44/{label}.wav")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("measure"); m.add_argument("label"); m.add_argument("--bypass-hesuvi", action="store_true")
    c = sub.add_parser("compare"); c.add_argument("target"); c.add_argument("base")
    r = sub.add_parser("reanalyse"); r.add_argument("label")
    e = sub.add_parser("export-hrir"); e.add_argument("label")
    a = ap.parse_args()
    if a.cmd == "measure": cmd_measure(a.label, a.bypass_hesuvi)
    elif a.cmd == "reanalyse": cmd_reanalyse(a.label)
    elif a.cmd == "export-hrir": cmd_export_hrir(a.label)
    else: cmd_compare(a.target, a.base)
