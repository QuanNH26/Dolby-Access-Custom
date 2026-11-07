"""7.1 surround status/control for the GUI, on top of the backend the soundmode side built:

  CABLE Input (VB-Audio, set to 7.1)  -- Equalizer APO runs soundmode/surround71.txt on it (14-ch HRIR -> binaural)
  CABLE Output -> soundmode/native/bridge.exe -> default playback device (the headphones)
  task "Dolby Access Custom 7.1 Bridge" starts the bridge at logon; play71.exe plays the 7.1 test sweep.

Only apps sent to "CABLE Input" are virtualised; normal stereo playback to the headphones never passes here.
Read-only except bridge start/stop and the test sweep. Never touches the Bluetooth Hands-Free endpoint.
"""
import re, subprocess, winreg
from pathlib import Path
from soundmode import detect

ROOT = Path(__file__).resolve().parent.parent
NATIVE = ROOT / "soundmode" / "native"
BRIDGE = NATIVE / "bridge.exe"
PLAY71 = NATIVE / "play71.exe"
TEST_WAV = NATIVE / "test71_vong_quanh.wav"
TASK = "Dolby Access Custom 7.1 Bridge"
CAPTURE = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture"
PK_FORMAT = "{f19f064d-082c-4e27-bc73-6882a1bb8e4c},0"   # PKEY_AudioEngine_DeviceFormat (WAVEFORMATEX blob)
POLICY = r"Software\Microsoft\Internet Explorer\LowRegistry\Audio\PolicyConfig\PropertyStore"   # per-app output choices
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _endpoint(flow_key, name):
    """(guid, state, props) of the first endpoint whose friendly name is `name`."""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, flow_key) as root:
            i = 0
            while True:
                try: sub = winreg.EnumKey(root, i)
                except OSError: return None
                i += 1
                p = detect._reg_values(rf"{flow_key}\{sub}\Properties")
                if p.get(detect.PK_NAME.lower()) == name:
                    st = detect._reg_values(rf"{flow_key}\{sub}").get("devicestate", 0)
                    return sub.strip("{}").lower(), st, p
    except OSError:
        return None


def _format(props):
    blob = props.get(PK_FORMAT.lower())
    if not isinstance(blob, bytes) or len(blob) < 16: return None, None
    # the registry blob is an 8-byte PROPVARIANT header (VT_BLOB + size) followed by the WAVEFORMATEX
    ch = int.from_bytes(blob[10:12], "little"); sr = int.from_bytes(blob[12:16], "little")
    return ch, sr


def _eapo_on(guid):
    fx = detect._reg_values(rf"{detect.RENDER}\{{{guid}}}\FxProperties")
    for key in detect.FX_SLOTS:
        v = fx.get(key.lower())
        for c in (v if isinstance(v, list) else [v] if v else []):
            if c.strip("{}").lower() in detect.EAPO_CLSIDS: return True
    return False


def _config_text(path, depth=0, seen=None):
    """EAPO config with its Include: files inlined (to find the 7.1 virtualiser wherever it is included)."""
    seen = seen if seen is not None else set()
    if depth > 6 or path in seen: return ""
    seen.add(path)
    text = detect._read(path); out = [text]
    for inc in re.findall(r"(?mi)^\s*Include:\s*(.+?)\s*$", text):
        out.append(_config_text((path.parent / inc).resolve(), depth + 1, seen))
    return "\n".join(out)


def _virtualizer():
    text = _config_text(detect.EAPO_CFG / "config.txt")
    on = "outputchannelcount == 8" in text.lower()
    hrir = sorted({h for h in re.findall(r"(?mi)^\s*Convolution:\s*(\S+\.wav)", text) if "sur_" in h.lower()})
    # Convolution paths are relative to the file that includes them (e.g. config\soundmode\surround71.txt)
    def found(h):
        if (detect.EAPO_CFG / h).exists() or (detect.HESUVI / h).exists(): return True
        try: return any(detect.EAPO_CFG.rglob(Path(h).name))
        except OSError: return False
    missing = [h for h in hrir if not found(h)]
    return {"configured": on, "hrir": hrir, "hrir_missing": missing}


def _bridge_running():
    try:
        out = subprocess.run(["tasklist", "/fi", "imagename eq bridge.exe", "/fo", "csv", "/nh"], capture_output=True,
                             text=True, timeout=10, creationflags=NOWIN).stdout
    except Exception: return False
    return "bridge.exe" in out.lower()


def _task():
    try:
        out = subprocess.run(["schtasks", "/query", "/tn", TASK, "/fo", "csv", "/nh"], capture_output=True, text=True,
                             timeout=10, creationflags=NOWIN)
    except Exception: return None
    if out.returncode != 0: return None
    cols = [c.strip('"') for c in out.stdout.strip().splitlines()[-1].split('","')]
    return {"name": TASK, "status": cols[-1] if cols else "", "next_run": cols[1] if len(cols) > 2 else ""}


def _routed_apps(cable_guid):
    """Apps whose output device is set to CABLE Input in Windows' per-app sound settings."""
    apps = set()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, POLICY) as root:
            i = 0
            while True:
                try: sub = winreg.EnumKey(root, i)
                except OSError: break
                i += 1
                vals = []
                try:
                    with winreg.OpenKey(root, sub) as k:
                        j = 0
                        while True:
                            try: vals.append(winreg.EnumValue(k, j)); j += 1
                            except OSError: break
                except OSError: continue
                blob = " ".join(f"{n} {v}" for n, v, _ in vals if isinstance(v, str))
                if cable_guid in blob.lower():
                    for exe in re.findall(r"([^\\/|%]+\.exe)", blob, re.I): apps.add(exe)
    except OSError: pass
    return sorted(apps, key=str.lower)


def status():
    render = _endpoint(detect.RENDER, "CABLE Input")
    capture = _endpoint(CAPTURE, "CABLE Output")
    out = {"installed": bool(render and capture), "bridge_running": _bridge_running(), "task": _task(),
           "test_available": PLAY71.exists() and TEST_WAV.exists()}
    if render:
        guid, st, props = render
        ch, sr = _format(props)
        out["cable"] = {"guid": guid, "connected": st == 1, "channels": ch, "rate": sr, "eapo": _eapo_on(guid)}
        out["apps"] = _routed_apps(guid)
    if capture: out["capture_guid"] = capture[0]
    out["virtualizer"] = _virtualizer()
    v, c = out["virtualizer"], out.get("cable") or {}
    out["ready"] = bool(out["installed"] and c.get("channels") == 8 and c.get("eapo") and v["configured"]
                        and not v["hrir_missing"] and out["bridge_running"])
    return out


def bridge(on):
    if on:
        if _bridge_running(): return True
        if _task():
            subprocess.run(["schtasks", "/run", "/tn", TASK], capture_output=True, timeout=10, creationflags=NOWIN)
        else:
            cap = _endpoint(CAPTURE, "CABLE Output")
            if not cap: raise RuntimeError("VB-CABLE is not installed (no CABLE Output device)")
            subprocess.Popen([str(BRIDGE), cap[0]], creationflags=NOWIN | subprocess.DETACHED_PROCESS)
        return True
    subprocess.run(["taskkill", "/im", "bridge.exe", "/f"], capture_output=True, timeout=10, creationflags=NOWIN)
    return False


def test_seconds():
    """Length of the test sweep from its RIFF header (float 7.1, which the wave module cannot open)."""
    try:
        head = TEST_WAV.open("rb").read(64)
        rate = int.from_bytes(head[28:32], "little")   # nAvgBytesPerSec
        return max(1, round((TEST_WAV.stat().st_size - 68) / rate))
    except (OSError, ZeroDivisionError): return 15


def play_test(cable_guid):
    return subprocess.run([str(PLAY71), str(TEST_WAV), cable_guid], capture_output=True, text=True, timeout=120,
                          creationflags=NOWIN)
