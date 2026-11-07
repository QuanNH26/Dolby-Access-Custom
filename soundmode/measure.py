"""Measure one Dolby Access mode (black box, via dolby-probe) and turn it into a library mode.

Flow: user picks the profile / Intelligent EQ in Dolby Access with Spatial sound = Dolby Atmos for Headphones,
then measure(profile, ieq) plays ~80 s of test signals, records post-Dolby audio through WASAPI loopback
(HeSuVi bypassed during the run) and writes modes/dolby-<profile>-<ieq>/.

What the mode contains:
  EQ        GraphicEQ (61 pts, 1/6 oct, 0 dB at 1 kHz) = average transfer of the probe's noise sections, fresh and
            adapted (same recipe that reproduces the hand-tuned Music Warm curve within 0.4 dB rms)
  leveler   TDR Nova pair copied from the Music Warm preset (fitted to Dolby's leveler, which is the same engine in
            every profile); the measured attack / release / ratio of this profile are stored in mode.json for a later refit
Dolby does not virtualise stereo (crossfeed ~ -79 dB), so no HRIR is needed for music/video in stereo.
"""
import json, re, subprocess, sys
from pathlib import Path
import numpy as np
from . import detect, engine

PROBE_DIR = engine.ROOT / "dolby-probe"
RUNS = PROBE_DIR / "runs"
PROFILES = ["Game", "Movie", "Music", "Voice", "Custom 1", "Custom 2", "Custom 3"]   # as listed in Dolby Access
IEQS = ["Detailed", "Balanced", "Warm", "Off", "Performance", "Default"]   # Performance = Game with performance mode (IEQ disabled)
PLAN = [("Music", "Balanced"), ("Music", "Detailed"), ("Music", "Off"), ("Movie", "Balanced"),
        ("Game", "Balanced"), ("Voice", "Balanced")]   # Music/Warm already measured (linked preset)


def slug(profile, ieq): return f"dolby-{profile}-{ieq}".lower().replace(" ", "")


def spatial_on():
    for e in detect.scan()["endpoints"]:
        if e.default and e.state == 1:
            return any(l.kind == "spatial" and l.active for l in e.layers), e.label
    return False, "?"


def run_probe(label, log=print):
    """Blocking ~90 s. Streams probe output lines to log()."""
    p = subprocess.Popen([sys.executable.replace("pythonw", "python"), "-I", "-W", "ignore", str(PROBE_DIR / "probe.py"),
                          "measure", label, "--bypass-hesuvi"], cwd=PROBE_DIR, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    for line in p.stdout: log(line.rstrip())
    if p.wait() != 0: raise RuntimeError(f"probe loi (ma {p.returncode})")


def noise_geq(label, absolute=False):
    """Average noise transfer (fresh + adapted halves of every noise section) as 61-pt dB curve, 0 dB at 1 kHz."""
    sys.path.insert(0, str(PROBE_DIR))
    import probe
    from scipy.io import wavfile
    from scipy.signal import csd, welch
    stim, mark, _ = probe.build_stimulus()
    _, y = wavfile.read(RUNS / f"{label}_rec.wav"); y = y.astype(float)
    i1k = int(np.argmin(np.abs(probe.GEQ_F - 1000))); curves = []
    for t in ["pink", "pink2", "bass", "bright"]:
        s0, s1 = mark["noise_" + t]; a, b = stim[s0:s1, 0], y[s0:s1, 0]
        for s, e in [(0, len(a) // 4), (len(a) // 2, len(a))]:
            f, P = csd(a[s:e], b[s:e], fs=probe.FS, nperseg=8192); _, Q = welch(a[s:e], fs=probe.FS, nperseg=8192)
            g = np.array(probe.smooth_db(f, P / Q)); curves.append(g if absolute else g - g[i1k])
    return probe.GEQ_F, np.mean(curves, 0)


def leveler_lines():
    t = (detect.HESUVI / "music-warm.txt").read_text(encoding="utf-8-sig")
    lines = [l.strip() for l in t.splitlines() if re.match(r"\s*#?\s*VSTPlugin:", l)]
    return [re.sub(r'Library "[^"]*\\VST\\', 'Library "%VST%\\\\', l.lstrip("# ")) for l in lines]


def build_mode(label, profile, ieq):
    res = json.loads((RUNS / f"{label}.json").read_text())
    F, g = noise_geq(label)
    pre = -round(float(max(g.max(), 0)) + 0.1, 1)
    mid = slug(profile, ieq); d = engine.MODES / mid; d.mkdir(parents=True, exist_ok=True)
    body = [f"# Dolby Atmos for Headphones - {profile} / IEQ {ieq}, measured by soundmode (run {label}).",
            f"Preamp: {pre} dB",
            "GraphicEQ: " + "; ".join(f"{f} {v:.1f}" for f, v in zip(F, g)),
            ]
    has_lev = abs(res["release"].get("gain_change_dB") or 0) >= 1.0 or abs(res["attack"].get("gain_change_dB") or 0) >= 1.0
    body += (["# leveler + peak safety (TDR Nova, from the Music Warm fit)"] + leveler_lines()) if has_lev else             ["# no leveler: Dolby showed no level-dependent gain in this profile"]
    (d / "mode.txt").write_text("\n".join(body) + "\n", encoding="utf-8")
    meta = {"name": f"{profile} - {ieq}", "dolby": {"profile": profile, "ieq": ieq}, "measured": f"dolby-probe/runs/{label}",
            "probe": {"crossfeed_dB_1k": round(res["crossfeed_dB_1k"], 1), "attack": res["attack"],
                      "release": res["release"], "steady_ratio": res["steady_ratio"]},
            "notes": "EQ measured for this profile; " + ("leveler copied from Music Warm (refit pending)." if has_lev else "no leveler.")}
    (d / "mode.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return mid, meta, g


def measure(profile, ieq, log=print):
    on, dev = spatial_on()
    if not on: raise RuntimeError(f"Spatial sound (Dolby) chua bat tren {dev}. Bat Dolby Atmos for Headphones roi do lai.")
    label = slug(profile, ieq).replace("-", "_")
    log(f"Do {profile} / {ieq} tren {dev} (~90 s, dung chinh volume, tat app phat nhac khac)...")
    run_probe(label, log)
    mid, meta, g = build_mode(label, profile, ieq)
    xf = meta["probe"]["crossfeed_dB_1k"]
    log(f"Xong: che do '{meta['name']}' -> modes\\{mid}. crossfeed {xf} dB"
        + (" (Dolby co xu ly khong gian, can them HRIR!)" if xf > -40 else ""))
    return mid
