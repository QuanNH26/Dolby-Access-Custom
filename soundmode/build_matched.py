"""Build a Dolby-matched mode: base EQ + TDR Nova leveler (makeup, ratio) + optional "audio regulator"
(3rd Nova, one dynamic high-shelf band) + the Music Warm safety limiter.

  python -m soundmode.build_matched BASE OUT NAME GAIN RATIO [REG_THR REG_RATIO REG_FREQ REG_ATT REG_REL]
  BASE = music-warm (live HeSuVi\\music-warm.txt) or a measured mode id (modes\\BASE\\mode.txt)
e.g. python -m soundmode.build_matched music-warm music-warm-dolby "Music - Warm (khop Dolby)" 9.0 1.1 -12 1.45 1500 50 500
"""
import json, re, sys
from . import nova, engine, detect, measure


def base_eq(base):
    p = detect.HESUVI / "music-warm.txt" if base == "music-warm" else engine.MODES / base / "mode.txt"
    lines = [l.strip() for l in p.read_text(encoding="utf-8-sig").splitlines()]
    return [l for l in lines if l.startswith("Preamp:")][0], [l for l in lines if l.startswith("GraphicEQ:")][0]


def mem_line(chunk):
    import base64
    return f'VSTPlugin: Library "%VST%\\MemLeveler.dll" ChunkData "{base64.b64encode(chunk.encode()).decode()}"'


def build(base, out, name, gain, ratio, reg=(), mem=None, reg2=()):
    """mem: MemLeveler chunk string ('k=v;...'); replaces the Nova leveler (gain/ratio then ignored)."""
    pre, geq = base_eq(base)
    vst = measure.leveler_lines()
    c0 = re.search(r'ChunkData "([^"]+)"', vst[0]).group(1)
    assert nova.encode(nova.decode(c0)) == c0, "round trip"
    if mem:
        body = [pre, geq, mem_line(mem)]
        comment = f"# EQ from {base}; MemLeveler (fitted to Dolby) {mem}"
    else:
        body = [pre, geq, nova.set_params(vst[0], bandGain_wide=gain, bandDynRatio_wide=ratio)]
        comment = f"# EQ from {base}; leveler ratio {ratio}, makeup {gain} dB"
    if reg:
        thr, rr, fq, att, rel = reg
        line = nova.set_params(vst[1], bandDynActive_wide=("Off", "0.0"), bandGain_wide="0.0",
                    bandActive_4=("On", "1.0"), bandSelected_4=("Off", "0.0"), bandGain_4="0.0",
                    bandFreq_4=(fq, fq + ".0"), bandType_4=("High S", "2.0"), bandQ_4=("0.60", "0.6"),
                    bandDynActive_4=("On", "1.0"), bandDynSplit_4=("On", "1.0"), bandDynThreshold_4=thr,
                    bandDynRatio_4=rr, bandDynAttack_4=att, bandDynRelease_4=rel)
        comment += f"; regulator: dynamic high shelf {fq} Hz thr {thr} ratio {rr} att {att} rel {rel}"
        if reg2:   # second dynamic high shelf (band 3) for the top octave
            t2, r2, f2 = reg2
            line = nova.set_params(line, bandActive_3=("On", "1.0"), bandSelected_3=("Off", "0.0"), bandGain_3="0.0",
                    bandFreq_3=(f2, f2 + ".0"), bandType_3=("High S", "2.0"), bandQ_3=("0.60", "0.6"),
                    bandDynActive_3=("On", "1.0"), bandDynSplit_3=("On", "1.0"), bandDynThreshold_3=t2,
                    bandDynRatio_3=r2, bandDynAttack_3=att, bandDynRelease_3=rel)
            comment += f" + {f2} Hz thr {t2} ratio {r2}"
        body.append(line)
    body.append(vst[1])
    d = engine.MODES / out; d.mkdir(exist_ok=True)
    (d / "mode.txt").write_text("\n".join([f"# {name}: matched to Dolby by closed-loop measurement.",
                                           comment + "; safety limiter -1 dBFS."] + body) + "\n", encoding="utf-8")
    old = {}
    try: old = json.loads((engine.MODES / base / "mode.json").read_text(encoding="utf-8"))
    except OSError: pass
    meta = {"name": name, "dolby": old.get("dolby") or {"profile": "Music", "ieq": "Warm"},
            "leveler": {"memleveler": mem} if mem else {"makeup_dB": float(gain), "ratio": float(ratio)},
            "notes": f"Closed-loop match of {base}: Dolby loudness + loud-level treble regulator."}
    if reg: meta["regulator"] = dict(zip(["threshold_dB", "ratio", "freq_Hz", "attack_ms", "release_ms"], map(float, reg)))
    (d / "mode.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    a = sys.argv[1:]
    mem = None
    reg2 = ()
    if "--mem" in a: i = a.index("--mem"); mem = a[i + 1]; del a[i:i + 2]
    if "--reg2" in a: i = a.index("--reg2"); reg2 = tuple(a[i + 1:i + 4]); del a[i:i + 4]
    build(a[0], a[1], a[2], a[3], a[4], tuple(a[5:10]), mem, reg2)
    print("written", a[1])
