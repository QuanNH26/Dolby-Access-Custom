"""Bridge between the web UI (gui/web) and the soundmode backend.

Every public method takes/returns plain JSON values and is called from the page as window.pywebview.api.<name>.
Nothing here changes DSP / mode logic: it only calls soundmode.engine / guard / detect / measure.

Slow work (device scan, live check, Dolby measurement) runs in background threads; the UI polls state()
about once a second and gets the cached scan plus any new events since its cursor.
"""
import datetime, re, subprocess, sys, threading, time
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from soundmode import detect, engine, guard  # noqa: E402

SCAN_EVERY = 5.0
KIND = {"spatial": "Spatial sound", "eapo": "Equalizer APO", "sysfx": "Windows Enhancements",
        "vendor": "Vendor APO", "app": "Audio app"}


# soundmode keeps its messages in ASCII Vietnamese; translate them to English for display only
_VI = [
    (r"Phat hien (.+?) dang xu ly (.+?)\. Da tam TAT che do cua app de tranh chong\. Tat (.+?) thi app tu bat lai\.",
     r"\1 is processing \2. Paused this app's mode to avoid double processing. Turn \3 off and the mode comes back on."),
    (r"CHONG CHEO tren (.+?): Equalizer APO \+ (.+)", r"Double processing on \1: Equalizer APO + \2"),
    (r"(.+?): khong con lop xu ly khac, da BAT lai che do cua app\.", r"\1: no other processing left, mode switched back on."),
    (r"(.+?) con co APO cua hang \((.+?)\)\. Neu nghe thay xu ly hai lop, tat Enhancements trong Sound settings\.",
     r"\1 also has a vendor APO (\2). If it sounds double-processed, turn off Enhancements in Sound settings."),
    (r"^Do (.+?) / (.+?) tren (.+?) \(~90 s, dung chinh volume, tat app phat nhac khac\)\.\.\.",
     r"Measuring \1 / \2 on \3 (~90 s, don't touch the volume, stop other playback)..."),
    (r"^Xong: che do '(.+?)' -> modes\\(\S+)\. crossfeed", r"Done: mode '\1' -> modes\\\2. crossfeed"),
    (r"HeSuVi BAT", "HeSuVi on"), (r"HeSuVi TAT", "HeSuVi off"), (r"khong co HeSuVi", "no HeSuVi"),
    (r"\(cau hinh nham thiet bi khac\)", "(config targets another device)"),
    (r"\(enhancements dang bi tat\)", "(Enhancements disabled)"), (r"^dang chay$", "running"),
    (r"\(chi la giao dien, xu ly nam o Spatial sound\)", "(UI only, processing lives in Spatial sound)"),
    (r"\(ghi de cau hinh khi chinh\)", "(overwrites the config when edited)"),
    (r"RESULT=FAIL khong thu duoc am thanh \(thiet bi mac dinh co dung tai nghe khong\?\)",
     "RESULT=FAIL nothing recorded (is the default device really the headphones?)"),
    (r"\(so voi 1 kHz\)  -> do nghieng Warm", "(vs 1 kHz)  -> Warm tilt"),
    (r"=> KHONG co xu ly nao \(HeSuVi tat / APO khong chay\)\.", "=> NO processing (HeSuVi off / APO not running)."),
    (r"=> Dang co 1 lop Warm - dung nhu mong doi khi HeSuVi bat\.", "=> One Warm layer - as expected with HeSuVi on."),
    (r"=> Co 2 LOP xu ly chong nhau: hay tat Spatial sound \(Dolby\) khi dung HeSuVi!",
     "=> TWO layers stacked: turn Spatial sound (Dolby) off while using HeSuVi!"),
]


def _vi(text):
    for a, b in _VI: text = re.sub(a, b, text)
    return text


def _read(p):
    try: return Path(p).read_text(encoding="utf-8-sig", errors="replace")
    except OSError: return ""


def _parse(text):
    """Preamp, GraphicEQ points and the dynamics stages used by one EAPO mode body."""
    pre = 0.0; pts = []
    for line in text.splitlines():
        s = line.strip()
        if s.lower().startswith("preamp:"):
            m = re.search(r"-?\d+(\.\d+)?", s); pre = float(m.group()) if m else 0.0
        elif s.lower().startswith("graphiceq:"):
            pts = []
            for pair in s.split(":", 1)[1].split(";"):
                try: f, g = pair.split(); pts.append([float(f), float(g)])
                except ValueError: pass
    plugins = [l for l in text.splitlines() if l.strip().lower().startswith("vstplugin")]
    nova = sum("TDR Nova" in l for l in plugins)
    stages = []
    if any("MemLeveler" in l for l in plugins):
        stages.append("Memory leveler (Dolby-matched)")
        if re.search(r"\bieq=1\b", text): stages.append("Adaptive IEQ")
        if re.search(r"\bbass=1\b", text): stages.append("Adaptive bass")
    elif nova:
        stages.append("Leveler TDR Nova"); nova -= 1
    if nova: stages.append("Peak limiter")
    return pre, pts, stages


def _mode_info(m):
    d = m.meta.get("dolby") or {}
    text = _read(engine.HSV / m.include) if m.include else _read(m.dir / "mode.txt")
    pre, pts, stages = _parse(text)
    if m.meta.get("regulator"): stages.insert(len(stages) - ("Peak limiter" in stages), "Loud-level treble control")
    name = m.name
    variant = re.search(r"\((.*)\)\s*$", name)
    return {"id": m.id, "name": name, "profile": d.get("profile") or "Flat", "ieq": d.get("ieq") or "",
            "variant": variant.group(1) if variant else ("Original HeSuVi preset" if m.include else
                                                         ("Raw measurement" if m.meta.get("measured") else "")),
            "linked": bool(m.include), "notes": m.meta.get("notes", ""), "preamp": pre, "curve": pts,
            "stages": stages, "measured": bool(m.meta.get("measured")), "probe": m.meta.get("probe")}


def _layer(l):
    return {"kind": l.kind, "kind_label": KIND.get(l.kind, l.kind), "name": _vi(l.name), "active": l.active,
            "detail": _vi(l.detail), "certain": l.certain}


def _endpoint(e):
    off = engine.state().get("fx_off", {})
    extra = [l for l in e.layers if l.active and l.kind in ("vendor", "sysfx")]
    return {"guid": e.guid, "name": e.name, "iface": e.iface, "label": e.label, "connected": e.state == 1,
            "default": e.default, "default_comm": e.default_comm, "conflict": e.conflict,
            "shaping": len(e.shaping), "layers": [_layer(l) for l in e.layers],
            "sysfx_disabled": e.sysfx_disabled, "extra": [_vi(l.name) for l in extra],
            "has_eapo": any(l.kind == "eapo" for l in e.layers), "off_by_app": e.guid in off,
            "auto_off": bool(off.get(e.guid, {}).get("auto")), "headphones": _is_headphones(e)}


def _is_headphones(e):
    """Stereo headphones the mode may follow. Never a Bluetooth Hands-Free (call) endpoint, never speakers / virtual cables."""
    text = f"{e.name} {e.iface}".lower()
    if "hands-free" in text or "handsfree" in text or "cable" in text or "virtual" in text: return False
    return bool(re.search(r"headphone|headset|tai nghe|earphone|earbud|airpods|buds", text))


def _helper(*args):
    import json
    out = subprocess.run([str(detect.HELPER), *args], capture_output=True, text=True, timeout=20,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    try: return json.loads(out.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError): return {"ok": False, "error": (out.stderr or out.stdout or "no output").strip()}


def _run_elevated(exe, params, timeout_ms=120000, cwd=None):
    """ShellExecuteEx 'runas' + wait. Returns exit code, or None if the user said No to UAC."""
    import ctypes
    from ctypes import wintypes as w

    class SEI(ctypes.Structure):
        _fields_ = [("cbSize", w.DWORD), ("fMask", w.ULONG), ("hwnd", w.HWND), ("lpVerb", w.LPCWSTR),
                    ("lpFile", w.LPCWSTR), ("lpParameters", w.LPCWSTR), ("lpDirectory", w.LPCWSTR), ("nShow", ctypes.c_int),
                    ("hInstApp", w.HINSTANCE), ("lpIDList", ctypes.c_void_p), ("lpClass", w.LPCWSTR), ("hkeyClass", w.HKEY),
                    ("dwHotKey", w.DWORD), ("hIcon", w.HANDLE), ("hProcess", w.HANDLE)]
    sei = SEI(cbSize=ctypes.sizeof(SEI), fMask=0x40, lpVerb="runas", lpFile=exe, lpParameters=params,
              lpDirectory=cwd, nShow=1 if cwd else 0)   # NOCLOSEPROCESS
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)):
        if ctypes.GetLastError() == 1223: return None   # ERROR_CANCELLED
        raise ctypes.WinError()
    k32 = ctypes.windll.kernel32
    k32.WaitForSingleObject(sei.hProcess, timeout_ms)
    code = w.DWORD(); k32.GetExitCodeProcess(sei.hProcess, ctypes.byref(code)); k32.CloseHandle(sei.hProcess)
    return code.value


class Api:
    def __init__(self):
        self._lock = threading.Lock()
        self._events = deque(maxlen=200); self._seq = 0
        self._scan = None; self._scan_at = 0.0; self._scanning = False
        self._task = None   # {"kind": "measure"|"listen", "started": t, "label": str}
        self._guard = guard.Guard(engine.state().get("guard_policy", "auto"))
        self._seen = set()
        self._modes_cache = None
        self._last_follow = None
        threading.Thread(target=self._scan_loop, daemon=True).start()

    # ---------------------------------------------------------------- events
    def _event(self, level, text, kind="log"):
        with self._lock:
            self._seq += 1
            self._events.append({"seq": self._seq, "level": level, "kind": kind, "text": _vi(text),
                                 "time": datetime.datetime.now().strftime("%H:%M:%S")})

    # ---------------------------------------------------------------- scanning
    def _scan_loop(self):
        while True:
            self._do_scan()
            time.sleep(SCAN_EVERY)

    def _do_scan(self):
        if self._scanning: return
        self._scanning = True
        try:
            self._guard.policy = engine.state().get("guard_policy", "auto")
            res, ev = self._guard.check()
            if self._follow(res): res, ev2 = self._guard.check(); ev += ev2
            eps = [_endpoint(e) for e in res["endpoints"]]
            self._scan = {"endpoints": eps, "info": [_vi(i) for i in res["info"]], "eapo": res["eapo"],
                          "nahimic": self.nahimic_status()}
            self._scan_at = time.time()
            for e in ev:
                if e.text in self._seen: continue
                self._seen.add(e.text); self._event(e.level, e.text, "guard")
            if not ev: self._seen.clear()
        except Exception as ex:
            self._event("warn", f"Device scan failed: {ex}")
        finally:
            self._scanning = False

    def _follow(self, res):
        """When other headphones become the default output, move the mode to them. Returns True if it moved."""
        eps = [e for e in res["endpoints"] if e.state == 1]
        dflt = next((e for e in eps if e.default), None)
        target = res["eapo"].get("hesuvi_device")
        if not dflt or not _is_headphones(dflt) or dflt.guid == target: return False
        if not any(l.kind == "eapo" for l in dflt.layers): return False   # EAPO not attached there: shown as a notice instead
        if self._last_follow == dflt.guid: return False                    # one attempt per device change
        self._last_follow = dflt.guid
        try:
            engine.retarget(dflt.guid)
        except Exception as ex:
            self._event("warn", f"Could not move the mode to {dflt.iface or dflt.name}: {ex}", "device"); return False
        self._event("info", f"Headphones changed: the mode now runs on {dflt.iface or dflt.name}", "device")
        if engine.is_active(): self._quiet(dflt.guid, restore_others=True)
        return True

    # "while On, only this app shapes the headphones": turn the other layers off, put them back when switched Off
    def _quiet(self, guid, restore_others=False):
        off = dict(engine.state().get("fx_off", {}))
        if restore_others:
            for g, info in list(off.items()):
                if info.get("auto") and g != guid: self._sysfx_restore(g, off)
        if guid in off: engine._save_state(fx_off=off); return
        res = detect.scan()
        ep = next((e for e in res["endpoints"] if e.guid == guid and e.state == 1), None)
        if not ep: engine._save_state(fx_off=off); return
        extra = [l.name for l in ep.layers if l.active and l.kind in ("vendor", "sysfx")]
        has_eapo = any(l.kind == "eapo" for l in ep.layers)
        if extra and has_eapo:
            # "Audio enhancements: Off" would also bypass Equalizer APO (= this app's mode): leave it, say why
            self._event("warn", f"{', '.join(extra)} still process {ep.iface or ep.name} next to Equalizer APO. Untick "
                                f"'Use original APO' for it in Equalizer APO's Device Selector to drop it.", "layers")
        elif extra:
            before = _helper("sysfx", guid)
            r = _helper("sysfx", guid, "1")
            if r.get("ok"):
                off[guid] = {"name": ep.iface or ep.name, "prev": bool(before.get("disabled_before")), "auto": True}
                self._event("info", f"{ep.iface or ep.name}: {', '.join(extra)} turned off while the mode is On", "layers")
        engine._save_state(fx_off=off)

    def _sysfx_restore(self, guid, off):
        info = off.get(guid) or {}
        r = _helper("sysfx", guid, "1" if info.get("prev") else "0")
        if r.get("ok") or "not found" in str(r.get("error")):
            off.pop(guid, None)
            if r.get("ok"): self._event("info", f"{info.get('name', guid)}: audio enhancements back as before", "layers")
        return r

    def _unquiet(self):
        off = dict(engine.state().get("fx_off", {}))
        for g, info in list(off.items()):
            if info.get("auto"): self._sysfx_restore(g, off)
        engine._save_state(fx_off=off)

    def rescan(self):
        threading.Thread(target=self._do_scan, daemon=True).start(); return True

    # ---------------------------------------------------------------- state for the UI
    def modes(self):
        self._modes_cache = [_mode_info(m) for m in engine.modes()]
        return self._modes_cache

    def state(self, since=0):
        st = engine.state()
        try: cur = engine.current()
        except Exception: cur = None
        try: active = engine.is_active()
        except Exception: active = False
        scan = self._scan or {}
        dflt = next((e for e in scan.get("endpoints", []) if e["default"] and e["connected"]), None)
        hp = (scan.get("eapo") or {}).get("hesuvi_device")
        target = next((e for e in scan.get("endpoints", []) if e["guid"] == hp), None)
        with self._lock: ev = [e for e in self._events if e["seq"] > since]
        task = None
        if self._task:
            task = dict(self._task, elapsed=round(time.time() - self._task["started"], 1))
        eapo = scan.get("eapo") or {}
        notice = None
        if scan.get("endpoints") is not None:
            if not eapo.get("installed"):
                notice = {"kind": "no-eapo", "text": "Equalizer APO is not installed on this PC, so the sound modes cannot run here.",
                          "setup": self.setup_status()}
            elif not (detect.HESUVI / "hesuvi.txt").exists():
                notice = {"kind": "no-eapo", "text": "HeSuVi is not installed on this PC, so the sound modes cannot run here.",
                          "setup": self.setup_status()}
            elif dflt and dflt.get("headphones") and not dflt.get("has_eapo"):
                notice = {"kind": "not-attached", "guid": dflt["guid"], "device": dflt["iface"] or dflt["name"],
                          "text": f"{dflt['iface'] or dflt['name']} is the default output but Equalizer APO is not attached to it, so the mode cannot process it yet."}
        return {"current": cur, "active": active, "policy": st.get("guard_policy", "auto"), "notice": notice,
                "paused_by_guard": bool(st.get("paused_by_guard")), "applied": st.get("applied"),
                "pref": st.get("gui_pref", {}), "scan": scan, "scan_age": round(time.time() - self._scan_at, 1) if self._scan_at else None,
                "default_device": dflt, "target_device": target, "events": ev, "task": task,
                "pc": engine.os.environ.get("COMPUTERNAME", "pc"), "root": str(engine.ROOT)}

    # ---------------------------------------------------------------- actions
    def use_mode(self, mode_id):
        try:
            m = engine.get(mode_id)
            _, bk = engine.apply(m)
            d = m.meta.get("dolby") or {}
            pref = dict(engine.state().get("gui_pref", {}))
            pref[f"{d.get('profile') or 'Flat'}|{d.get('ieq') or ''}"] = m.id
            pref[f"{d.get('profile') or 'Flat'}"] = m.id
            engine._save_state(gui_pref=pref)
            self._event("info", f"Switched to {m.name}", "mode")
            return {"ok": True, "backup": bk.name}
        except Exception as ex:
            self._event("warn", f"Could not switch mode: {ex}", "mode")
            return {"ok": False, "error": str(ex)}

    def set_active(self, on):
        if on and not (detect.EAPO_DIR.joinpath("EqualizerAPO.dll").exists() and (detect.HESUVI / "hesuvi.txt").exists()):
            return {"ok": False, "need_install": True,
                    "error": "Equalizer APO / HeSuVi are not installed on this PC yet, so there is nothing to switch on."}
        if not detect.EAPO_DIR.joinpath("EqualizerAPO.dll").exists(): return {"ok": True}
        try:
            engine.set_active(bool(on))
            if engine.state().get("paused_by_guard"): self._guard._remember(False)   # the user took over
            if on:
                t = detect.eapo_state().get("hesuvi_device")
                if t: self._quiet(t, restore_others=True)
            else:
                self._unquiet()
            threading.Thread(target=self._do_scan, daemon=True).start()
            self._event("info", "Sound mode ON" if on else "Sound mode OFF, original sound", "power")
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def set_policy(self, policy):
        policy = "warn" if policy == "warn" else "auto"
        self._guard.policy = policy; engine._save_state(guard_policy=policy)
        return {"ok": True}

    def _busy(self):
        if self._task: raise RuntimeError("Another task is running, wait for it to finish")

    def listen(self):
        try: self._busy()
        except RuntimeError as ex: return {"ok": False, "error": str(ex)}
        self._task = {"kind": "listen", "started": time.time(), "label": "Live check", "expected": 7}

        def run():
            try:
                out = subprocess.run([sys.executable.replace("pythonw", "python"), "-I", "-W", "ignore",
                                      str(engine.ROOT / "hesuvi-control" / "livecheck.py")], capture_output=True,
                                     text=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
                self._event("info", _vi((out.stdout or out.stderr).strip()) or "Live check failed", "listen")
            except Exception as ex:
                self._event("warn", f"Live check failed: {ex}", "listen")
            finally:
                self._task = None
        threading.Thread(target=run, daemon=True).start()
        return {"ok": True}

    def measure_options(self):
        from soundmode import measure
        return {"profiles": measure.PROFILES, "ieqs": measure.IEQS}

    def measure(self, profile, ieq):
        try: self._busy()
        except RuntimeError as ex: return {"ok": False, "error": str(ex)}
        self._task = {"kind": "measure", "started": time.time(), "label": f"Measuring Dolby {profile} / {ieq}", "expected": 95}

        def run():
            try:
                from soundmode import measure
                measure.measure(profile, ieq, lambda t: self._event("info", t, "measure"))
                self._event("info", "Measurement done, the new mode is in the list", "measure-done")
            except Exception as ex:
                self._event("warn", f"Measurement failed: {ex}", "measure-done")
            finally:
                self._task = None
        threading.Thread(target=run, daemon=True).start()
        return {"ok": True}

    # ---------------------------------------------------------------- 7.1 surround (gui/surround.py)
    def surround_status(self):
        import surround
        st = surround.status(); st["test_seconds"] = surround.test_seconds()
        return st

    def surround_bridge(self, on):
        import surround
        try:
            surround.bridge(bool(on))
            self._event("info", "7.1 bridge started" if on else "7.1 bridge stopped", "surround")
            return {"ok": True}
        except Exception as ex:
            self._event("warn", f"7.1 bridge: {ex}", "surround")
            return {"ok": False, "error": str(ex)}

    def surround_test(self):
        import surround
        try: self._busy()
        except RuntimeError as ex: return {"ok": False, "error": str(ex)}
        st = surround.status()
        if not st.get("cable"): return {"ok": False, "error": "CABLE Input (VB-Audio) was not found"}
        secs = surround.test_seconds()
        self._task = {"kind": "surround", "started": time.time(), "label": "7.1 speaker sweep", "expected": secs}

        def run():
            try:
                out = surround.play_test(st["cable"]["guid"])
                if out.returncode: self._event("warn", f"7.1 test failed: {(out.stderr or out.stdout).strip()}", "surround")
                else: self._event("info", "7.1 test finished", "surround")
            except Exception as ex:
                self._event("warn", f"7.1 test failed: {ex}", "surround")
            finally:
                self._task = None
        threading.Thread(target=run, daemon=True).start()
        return {"ok": True, "seconds": secs}

    # ---------------------------------------------------------------- extra processing layers (guard page)
    def _ep(self, guid):
        return next((e for e in (self._scan or {}).get("endpoints", []) if e["guid"] == guid), None)

    def layers_off(self, guid):
        """'Audio enhancements: Off' on one device: bypasses every vendor APO (Nahimic, Realtek, ...) and the Windows
        enhancements there. Same switch as Sound settings, reversible with layers_restore. No admin needed."""
        e = self._ep(guid)
        if not e or not e["connected"]: return {"ok": False, "error": "Device not found, rescan"}
        before = _helper("sysfx", guid)
        r = _helper("sysfx", guid, "1")
        if not r.get("ok"): return {"ok": False, "error": f"Could not change {e['iface'] or e['name']}: {r.get('error')}"}
        off = dict(engine.state().get("fx_off", {}))
        if guid not in off: off[guid] = {"name": e["iface"] or e["name"], "prev": bool(before.get("disabled_before"))}
        engine._save_state(fx_off=off)
        self._event("info", f"{e['iface'] or e['name']}: audio enhancements turned off ({', '.join(e['extra']) or 'vendor effects'} bypassed)", "layers")
        self._do_scan(); return {"ok": True}

    def layers_restore(self, guid):
        off = dict(engine.state().get("fx_off", {}))
        info = off.get(guid, {"name": guid, "prev": False})
        r = _helper("sysfx", guid, "1" if info.get("prev") else "0")
        if not r.get("ok"): return {"ok": False, "error": f"Could not restore {info['name']}: {r.get('error')}"}
        off.pop(guid, None); engine._save_state(fx_off=off)
        self._event("info", f"{info['name']}: audio enhancements restored", "layers")
        self._do_scan(); return {"ok": True}

    def nahimic_status(self):
        st = engine.state().get("nahimic_off")
        try:
            out = subprocess.run(["sc", "query", "NahimicService"], capture_output=True, text=True, timeout=10,
                                 creationflags=subprocess.CREATE_NO_WINDOW).stdout
        except Exception: out = ""
        installed = "SERVICE_NAME" in out
        procs = {p for p in detect.processes() if p.startswith("nahimic")}
        return {"installed": installed or bool(procs), "running": "RUNNING" in out or bool(procs), "off_by_app": bool(st)}

    def nahimic(self, action):
        """Stop / start the Nahimic background app (needs admin: one UAC prompt). Its sound effects are APOs per
        device, so layers_off already bypasses them; this only stops the service, tray app and startup tasks."""
        import json
        action = "start" if action == "start" else "stop"
        out = engine.ROOT / "backups" / "nahimic-last.json"; out.parent.mkdir(exist_ok=True)
        out.unlink(missing_ok=True)
        prev = engine.state().get("nahimic_off") or {}
        script = engine.ROOT / "soundmode" / "native" / "nahimic.ps1"
        args = f'-NoProfile -ExecutionPolicy Bypass -File "{script}" -Action {action} -Out "{out}"'
        if action == "start":
            args += f' -StartType {prev.get("start_type") or "Automatic"} -Tasks "{"|".join(prev.get("tasks") or [])}"'
        try: code = _run_elevated("powershell.exe", args)
        except OSError as ex: return {"ok": False, "error": f"Could not start the admin step: {ex}"}
        if code is None: return {"ok": False, "error": "Cancelled at the Windows admin prompt, nothing changed"}
        try: r = json.loads(out.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError): return {"ok": False, "error": f"Admin step failed (exit {code})"}
        bad = [f"{x['step']}: {x.get('error')}" for x in r.get("steps", []) if not x.get("ok")]
        if action == "stop":
            engine._save_state(nahimic_off={"start_type": r.get("start_type") or "Automatic",
                                            "tasks": r.get("tasks") or []} if not prev else prev)
        elif not bad:
            engine._save_state(nahimic_off=None)
        self._event("warn" if bad else "info", ("Nahimic stopped" if action == "stop" else "Nahimic started again")
                    + (f" (problems: {'; '.join(bad)})" if bad else ""), "layers")
        self._do_scan(); return {"ok": not bad, "error": "; ".join(bad)}

    def eapo_attach(self):
        """Open Equalizer APO's Device Selector as admin: tick the headphones there, then restart when it asks."""
        exe = detect.EAPO_DIR / "DeviceSelector.exe"
        if not exe.exists(): return {"ok": False, "error": "Equalizer APO is not installed"}
        try: code = _run_elevated(str(exe), "", 3600000, cwd=str(detect.EAPO_DIR))   # Qt finds its plugins from here
        except OSError as ex: return {"ok": False, "error": str(ex)}
        if code is None: return {"ok": False, "error": "Cancelled at the Windows admin prompt"}
        self._last_follow = None; self._do_scan(); return {"ok": True}

    def setup_status(self):
        apo = detect.EAPO_DIR
        inst = engine.ROOT / "vendor" / "installers"
        return {"eapo": (apo / "EqualizerAPO.dll").exists(), "hesuvi": (apo / "config" / "HeSuVi" / "hesuvi.txt").exists(),
                "vst": all((apo / "config" / "VST" / f.name).exists() for f in (engine.ROOT / "vendor" / "VST").glob("*.dll")),
                "installers": (inst / "EqualizerAPO-x64-1.4.2.exe").exists() and (inst / "HeSuVi_2.0.0.1.exe").exists()}

    def setup_devices(self):
        """Playback devices the user can pick for the sound modes (never Hands-Free / virtual cables)."""
        out = []
        for e in (self._scan or {}).get("endpoints", []):
            text = f"{e['name']} {e['iface']}".lower()
            if not e["connected"] or "hands-free" in text or "cable" in text: continue
            out.append({"guid": e["guid"], "name": e["iface"] or e["name"], "kind": e["name"], "default": e["default"],
                        "headphones": e["headphones"], "has_eapo": e["has_eapo"], "extra": e["extra"]})
        out.sort(key=lambda d: (not d["headphones"], not d["default"], d["name"]))
        return out

    def _attach_script(self, action, guid, keep=False):
        import json
        out = engine.ROOT / "backups" / "attach-last.json"; out.parent.mkdir(exist_ok=True); out.unlink(missing_ok=True)
        script = engine.ROOT / "soundmode" / "native" / "attach.ps1"
        args = (f'-NoProfile -ExecutionPolicy Bypass -File "{script}" -Action {action} -Device {guid} '
                f'-Root "{engine.ROOT}" -Out "{out}"' + (" -KeepOriginal" if keep else ""))
        code = _run_elevated("powershell.exe", args, 180000)
        if code is None: return {"ok": False, "error": "Cancelled at the Windows admin prompt, nothing changed"}
        try: return json.loads(out.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError): return {"ok": False, "error": f"The admin step failed (exit {code})"}

    def attach(self, guid, keep=False):
        """Connect Equalizer APO to one device (what Device Selector does), restart Windows Audio, point the mode at it."""
        try: self._busy()
        except RuntimeError as ex: return {"ok": False, "error": str(ex)}
        self._task = {"kind": "attach", "started": time.time(), "label": "Connecting the sound modes to your device", "expected": 15}
        try:
            r = self._attach_script("attach", guid, bool(keep))
            if not r.get("ok"): self._event("warn", f"Could not connect: {r.get('error')}", "attach"); return r
            self._event("info", f"Sound modes connected to {r.get('name', guid)}", "attach")
            time.sleep(2)   # Windows Audio coming back
            try:
                if _is_headphones(next(e for e in detect.scan()["endpoints"] if e.guid == guid)): engine.retarget(guid)
            except Exception as ex: self._event("warn", f"Connected, but could not move the mode yet: {ex}", "attach")
            return {"ok": True}
        finally:
            self._task = None; self._last_follow = None; self._do_scan()

    def detach(self, guid):
        try: self._busy()
        except RuntimeError as ex: return {"ok": False, "error": str(ex)}
        self._task = {"kind": "attach", "started": time.time(), "label": "Disconnecting the sound modes", "expected": 15}
        try:
            r = self._attach_script("detach", guid)
            self._event("info" if r.get("ok") else "warn",
                        f"Sound modes disconnected from {r.get('name', guid)}" if r.get("ok") else f"Could not disconnect: {r.get('error')}", "attach")
            return r
        finally:
            self._task = None; self._do_scan()

    def install(self, device=None, keep=False):
        """Install what is missing (Equalizer APO, HeSuVi, plugins, config) with one UAC prompt; progress shows as events."""
        import json
        try: self._busy()
        except RuntimeError as ex: return {"ok": False, "error": str(ex)}
        out = engine.ROOT / "backups" / "install-progress.jsonl"; out.parent.mkdir(exist_ok=True)
        out.write_text("", encoding="utf-8")
        script = engine.ROOT / "soundmode" / "native" / "install.ps1"
        self._task = {"kind": "install", "started": time.time(), "label": "Installing sound mode parts", "expected": 120}

        def tail(seen):
            try: lines = out.read_text(encoding="utf-8-sig").splitlines()
            except OSError: return seen
            for l in lines[seen:]:
                try: d = json.loads(l)
                except ValueError: continue
                if d["state"] != "run" or d["step"] == "attach":
                    self._event("warn" if d["state"] == "fail" else "info", d["text"], "install")
                self._task["label"] = d["text"] if d["state"] == "run" else self._task["label"]
            return len(lines)

        def run():
            seen = 0
            try:
                box = {}
                t = threading.Thread(target=lambda: box.update(code=_run_elevated(
                    "powershell.exe", f'-NoProfile -ExecutionPolicy Bypass -File "{script}" -Root "{engine.ROOT}" -Out "{out}"'
                    + (f" -Device {device}" if device else "") + (" -KeepOriginal" if keep else ""), 3600000)))
                t.start()
                while t.is_alive(): seen = tail(seen); time.sleep(1)
                seen = tail(seen)
                if box.get("code", 0) is None: self._event("warn", "Cancelled at the Windows admin prompt, nothing was installed", "install")
            except Exception as ex:
                self._event("warn", f"Install failed: {ex}", "install")
            finally:
                self._task = None; self._last_follow = None
                self._do_scan()
                if device and (detect.HESUVI / "hesuvi.txt").exists():
                    try: engine.retarget(device); self._do_scan()
                    except Exception as ex: self._event("warn", f"Installed, but could not point the mode at the device yet: {ex}", "install")
        threading.Thread(target=run, daemon=True).start()
        return {"ok": True}

    def open(self, what):
        targets = {"sound": ["control", "mmsys.cpl"], "spatial": ["control", "mmsys.cpl"],
                   "folder": ["explorer", str(engine.ROOT)], "backups": ["explorer", str(engine.BACKUPS)],
                   "eapo": ["explorer", str(engine.HSV)],
                   "apps-volume": ["explorer", "ms-settings:apps-volume"], "recording": ["control", "mmsys.cpl,,1"]}
        if what not in targets: return {"ok": False}
        subprocess.Popen(targets[what], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)); return {"ok": True}
