"""soundmode command line.

  python -m soundmode status [--json]   list every audio-processing layer per playback device and flag overlaps
  python -m soundmode modes             list the mode library and the live mode
  python -m soundmode use ID [--yes]    switch mode (without --yes: only show what would be written)
  python -m soundmode guard [--interval 5]  run the overlap guard forever (started hidden at logon)
  python -m soundmode measure PROFILE IEQ   measure the Dolby Access mode currently selected (Dolby must be on)
"""
import argparse, sys
import difflib
from . import detect, engine

KIND = {"spatial": "Spatial sound", "eapo": "Equalizer APO", "sysfx": "Enhancements", "vendor": "APO hang", "app": "App"}


def cmd_status(a):
    res = detect.scan()
    if a.json: print(detect.as_json(res)); return 0
    bad = 0
    for e in res["endpoints"]:
        if e.state != 1 and not a.all: continue
        tag = " [MAC DINH]" if e.default else (" [LIEN LAC]" if e.default_comm else "")
        st = "" if e.state == 1 else " (khong ket noi)"
        print(f"\n== {e.label}{tag}{st}")
        if not e.layers: print("   (khong co lop xu ly nao)")
        for l in e.layers:
            mark = "ON " if l.active else "off"
            unsure = "" if l.certain else " ?"
            print(f"   [{mark}] {KIND[l.kind]:<14} {l.name}  - {l.detail}{unsure}")
        n = len(e.shaping)
        if n >= 2:
            bad += 1
            print(f"   => CHONG CHEO: {n} lop cung xu ly: " + " + ".join(l.name for l in e.shaping))
        elif n == 1: print(f"   => OK, 1 lop: {e.shaping[0].name}")
        else: print("   => am thanh goc")
    for i in res["info"]: print(f"\n(i) {i}")
    print("\n'?' = suy ra, chua kiem chung tren may nay.")
    return 1 if bad else 0


def cmd_modes(a):
    cur = engine.current()
    for m in engine.modes():
        d = m.meta.get("dolby") or {}
        src = f"Dolby {d.get('profile')} / IEQ {d.get('ieq')}" if d else "tham chieu"
        print(f"{'*' if m.id == cur else ' '} {m.id:<16} {m.name:<24} {src}")
    if not engine.migrated(): print("\n(chua chuyen sang soundmode.txt: dang dung truc tiep music-warm.txt)")
    return 0


def cmd_use(a):
    m = engine.get(a.id)
    files = engine.plan(m)
    for p, new in files.items():
        old = p.read_text(encoding="utf-8-sig").splitlines() if p.exists() else []
        diff = list(difflib.unified_diff(old, new.splitlines(), str(p), str(p), lineterm="", n=1))
        print("\n".join(l[:160] for l in diff) or f"(khong doi) {p}")
    if not a.yes:
        print("\nChua ghi gi. Them --yes de ap dung."); return 0
    _, bk = engine.apply(m)
    print(f"\nDa chuyen sang '{m.name}'. Ban cu luu o {bk}")
    return 0


def cmd_measure(a):
    from . import measure
    measure.measure(a.profile, a.ieq); return 0


def cmd_guard(a):
    import time, datetime
    from . import guard
    log = engine.ROOT / "guard.log"
    g = guard.Guard(engine.state().get("guard_policy", "auto")); seen = set()
    while True:
        try:
            g.policy = engine.state().get("guard_policy", "auto")   # follow the GUI setting
            _, ev = g.check()
            for e in ev:
                if e.text in seen: continue
                seen.add(e.text)
                with open(log, "a", encoding="utf-8") as f: f.write(f"{datetime.datetime.now():%Y-%m-%dT%H:%M:%S}  {e.text}\n")
            if not ev: seen.clear()
        except Exception as ex:
            with open(log, "a", encoding="utf-8") as f: f.write(f"{datetime.datetime.now():%Y-%m-%dT%H:%M:%S}  loi: {ex}\n")
        time.sleep(a.interval)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="soundmode"); sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status"); s.add_argument("--json", action="store_true"); s.add_argument("--all", action="store_true")
    sub.add_parser("modes")
    u = sub.add_parser("use"); u.add_argument("id"); u.add_argument("--yes", action="store_true")
    gd = sub.add_parser("guard"); gd.add_argument("--interval", type=float, default=5)
    me = sub.add_parser("measure"); me.add_argument("profile"); me.add_argument("ieq")
    a = ap.parse_args(argv)
    return {"status": cmd_status, "modes": cmd_modes, "use": cmd_use, "measure": cmd_measure, "guard": cmd_guard}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
