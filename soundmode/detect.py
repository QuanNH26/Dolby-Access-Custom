"""Read-only scan of every audio-processing layer on each playback device, and the overlaps between them.

Layers looked at, per render endpoint:
  spatial   Windows Spatial sound (Dolby Atmos for Headphones / DTS / Windows Sonic), via ISpatialAudioClient
  eapo      Equalizer APO attached to the endpoint AND a config that actually processes it (HeSuVi active, device match)
  sysfx     Windows enhancements (Loudness Equalization, Bass Boost, Virtual Surround, Room Correction)
  vendor    third-party APOs registered on the endpoint (Realtek, Nahimic, Dolby DAX driver, ...)
  app       user-mode processors (Peace, FxSound, Boom 3D, SteelSeries Sonar, Voicemeeter, ...) - global

Nothing here changes the system.
"""
import json, re, subprocess, winreg
from dataclasses import dataclass, field, asdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
HELPER = HERE / "native" / "audiohelper.exe"
RENDER = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render"
EAPO_DIR = Path(r"C:\Program Files\EqualizerAPO")
EAPO_CFG = EAPO_DIR / "config"
HESUVI = EAPO_CFG / "HeSuVi"

PK_NAME = "{a45c254e-df1c-4efd-8020-67d146a850e0},2"
PK_IFACE = "{b3f8fa53-0004-438e-9003-51a46e139bfc},6"
PK_DISABLE_SYSFX = "{1da5d803-d492-4edd-8c23-e0c0ffee7f0e},5"
_FX = "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d}"
FX_SLOTS = {  # PKEY_FX_*EffectClsid: legacy single slots and the Win10+ composite (list) slots
    f"{_FX},1": "pre-mix", f"{_FX},2": "post-mix", f"{_FX},5": "SFX", f"{_FX},6": "MFX", f"{_FX},7": "EFX",
    f"{_FX},13": "SFX", f"{_FX},14": "MFX", f"{_FX},15": "EFX",
}
OFFLOAD_SLOTS = {  # hardware-offload path: only used by offloaded streams (never by Bluetooth / USB headphones)
    f"{_FX},11": "offload SFX", f"{_FX},12": "offload MFX", f"{_FX},19": "offload SFX", f"{_FX},20": "offload MFX",
}
# NOTE: {d3993a3f-...},5/6/7 are the *processing modes* an effect supports (DEFAULT / MEDIA / MOVIE / RAW ...),
# not APOs - reading them as APOs showed Realtek "vendor APOs" that do not exist.
EAPO_CLSIDS = {"eacd2258-fcac-4ff4-b36d-419e924a6d79", "ec1cc9ce-faed-4822-828a-82a81a6f018f"}
MS_CLSIDS = {  # inbox Windows APOs: not a second "sound mode" on their own
    "637c490d-eee3-4c0a-973f-371958802da2",  # WM GFX APO (older id)
    "c9453e73-8c5c-4463-9984-af8bab2f5447",  # WM LFX APO (hosts the Windows enhancements, idle when all are off)
    "13ab3ebd-137e-4903-9d89-60be8277fd17",  # WM GFX APO (same)
    "62dc1a93-ae24-464c-a43e-452f824c4250",  # WMALFXGFXDSP
    "5860e1c5-f95c-4a7a-8ec8-8aef24f379a1",  # CplPage (UI only)
    "889c03c8-abad-4004-bf0a-bc7bb825e166",  # Microsoft Audio Proxy Discover Effects (Bluetooth hands-free)
    "00000000-0000-0000-0000-000000000000",
}
SYSFX_TOGGLES = {  # Microsoft enhancement on/off flags kept in FxProperties (PROPVARIANT VT_BOOL)
    "{fc52a749-4be9-4510-896e-966ba6525980},3": "Loudness Equalization",
    "{9c00eeed-edce-4cd8-ae08-cb05e8ef57a0},3": "Bass Boost",
    "{1b0e2a1c-56b1-4fc8-a6d8-28b8b4d1c4d3},3": "Virtual Surround",
    "{e0f158e1-cb04-43d5-b6cc-3eb27e4db2a1},3": "Room Correction",
}
APPS = {  # process name (lower, no .exe) -> product
    "peace": "Peace (EAPO GUI)", "fxsound": "FxSound", "dfx": "FxSound/DFX", "boom3d": "Boom 3D",
    "steelseriessonar": "SteelSeries Sonar", "sonar": "SteelSeries Sonar", "voicemeeter": "Voicemeeter",
    "voicemeeterpro": "Voicemeeter Banana", "voicemeeter8": "Voicemeeter Potato", "voicemeeter8x64": "Voicemeeter Potato",
    "sonicstudio3": "ASUS Sonic Studio", "dtsx": "DTS Sound Unbound",
    "dtssoundunbound": "DTS Sound Unbound", "razersynapse": "Razer THX Spatial", "thxspatial": "Razer THX Spatial",
    "hesuvi": "HeSuVi GUI (ghi de cau hinh khi chinh)",
}
VENDOR_ALIAS = {"rtk": "Realtek Audio Effects", "nahimic": "Nahimic", "dax3": "Dolby DAX (driver)", "dax2": "Dolby DAX (driver)"}
KNOWN_APOS = {  # APOs whose COM class is not readable from HKCR (driver-store only)
    "0eac8ea6-00ae-4f8a-b222-f4f3196eab21": "AISpeech (Lenovo speaker DSP)",
}
INFO_APPS = {"dolbyaccess": "Dolby Access (chi la giao dien, xu ly nam o Spatial sound)",
             "nahimic3": "Nahimic app (effects run in its APO on each device)"}
# Nahimic is NOT counted from its process: its sound processing is an APO, detected per device like any vendor APO.


@dataclass
class Layer:
    kind: str          # spatial | eapo | sysfx | vendor | app
    name: str
    active: bool       # actually shaping the sound right now
    detail: str = ""
    certain: bool = True   # False = inferred, not verified on this machine yet


@dataclass
class Endpoint:
    guid: str
    name: str
    iface: str
    state: int
    default: bool = False
    default_comm: bool = False
    layers: list = field(default_factory=list)
    sysfx_disabled: bool = False   # "Audio enhancements: Off" for this device
    channels: int = 0              # shared-mode format Windows runs the device at
    rate: int = 0
    speaker_mask: int = 0          # physical speaker layout (KSAUDIO_SPEAKER_*), 0 = not reported
    bus: str = ""                  # bluetooth | usb | virtual | builtin

    @property
    def label(self): return f"{self.name} ({self.iface})" if self.iface else self.name

    @property
    def surround(self):
        """How 7.1 reaches this device:
        native     the device itself takes 6+ channels (USB 7.1 headset, AV receiver, virtual cable set to 7.1)
        call       Bluetooth Hands-Free (mono call link) - never use for listening
        virtual    stereo device: 7.1 only through the app's virtualizer (CABLE Input -> HRIR -> bridge)"""
        if self.bus == "bluetooth" and ("hands-free" in self.iface.lower() or self.name.lower() == "headset"):
            return "call"
        if self.channels >= 6 or self.speaker_mask & 0x630:    # BL/BR or SL/SR present
            return "native"
        return "virtual"

    @property
    def shaping(self): return [l for l in self.layers if l.active]

    @property
    def conflict(self): return len(self.shaping) >= 2


def _reg_values(path):
    out = {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
            i = 0
            while True:
                try: n, v, _ = winreg.EnumValue(k, i)
                except OSError: break
                out[n.lower()] = v; i += 1
    except OSError: pass
    return out


def clsid_name(clsid):
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"CLSID\{{{clsid}}}") as k:
            return winreg.QueryValueEx(k, "")[0]
    except OSError: return f"{{{clsid}}}"


def vendor_name(clsid):
    if clsid in KNOWN_APOS: return KNOWN_APOS[clsid]
    raw = clsid_name(clsid)
    if raw.startswith("{"): return f"Unknown APO {raw}"
    nm = re.sub(r"\s*\(.*\)\s*$", "", raw)
    nm = re.sub(r"\s*(S|M|E|G|L)FX|\s*Class$|\s*Audio Effects$|APO(SFX|MFX|EFX)?", "", nm).strip() or raw
    low = nm.lower()
    for k, v in VENDOR_ALIAS.items():
        if low == k or low.startswith(k): return v
    return nm


PK_DEVICE_FORMAT = "{f19f064d-082c-4e27-bc73-6882a1bb8e4c},0"    # PKEY_AudioEngine_DeviceFormat (PROPVARIANT blob)
PK_PHYS_SPEAKERS = "{1da5d803-d492-4edd-8c23-e0c0ffee7f0e},3"    # PKEY_AudioEndpoint_PhysicalSpeakers
PK_ENUMERATOR = "{a45c254e-df1c-4efd-8020-67d146a850e0},24"      # BTHENUM / USB / HDAUDIO / ROOT ...


def _fill_format(ep, p):
    import struct
    v = p.get(PK_DEVICE_FORMAT.lower())
    if isinstance(v, bytes) and len(v) >= 16:
        f = v[8:]                                   # skip the PROPVARIANT header (vt + reserved + size)
        ep.channels, ep.rate = struct.unpack("<HI", f[2:8])
        if struct.unpack("<H", f[:2])[0] == 0xFFFE and len(f) >= 24 and not ep.speaker_mask:
            ep.speaker_mask = struct.unpack("<I", f[20:24])[0]
    phys = p.get(PK_PHYS_SPEAKERS.lower())
    if isinstance(phys, int): ep.speaker_mask = phys
    enum = str(p.get(PK_ENUMERATOR.lower(), "")).upper()
    ep.bus = ("bluetooth" if "BTH" in enum else "usb" if "USB" in enum else
              "virtual" if "VB-AUDIO" in ep.iface.upper() or enum.startswith("ROOT") or "SWD" in enum else "builtin")


def _vt_bool(v):
    return isinstance(v, bytes) and len(v) >= 10 and v[0] == 0x0B and v[8:10] != b"\x00\x00"


def _helper():
    if not HELPER.exists(): return {}
    try:
        out = subprocess.run([str(HELPER)], capture_output=True, text=True, timeout=15,
                             creationflags=subprocess.CREATE_NO_WINDOW).stdout
    except Exception: return {}
    res = {}
    for line in out.splitlines():
        try: d = json.loads(line)
        except ValueError: continue
        res[d["id"].split("}.{")[-1].strip("{}").lower()] = d
    return res


def processes():
    try:
        out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True, timeout=15,
                             creationflags=subprocess.CREATE_NO_WINDOW).stdout
    except Exception: return set()
    return {l.split('","')[0].strip('"').lower().removesuffix(".exe") for l in out.splitlines() if l}


# ---------------------------------------------------------------- Equalizer APO config
def _read(p):
    try: return Path(p).read_text(encoding="utf-8-sig", errors="replace")
    except OSError: return ""


def eapo_state():
    """What the EAPO config does: which includes are live, HeSuVi on/off, which devices it targets."""
    cfg = _read(EAPO_CFG / "config.txt")
    lines = [l.strip() for l in cfg.splitlines() if l.strip() and not l.strip().startswith("#")]
    includes = [l.split(":", 1)[1].strip() for l in lines if l.lower().startswith("include:")]
    devices = [l.split(":", 1)[1].strip() for l in lines if l.lower().startswith("device:")]
    filters = [l for l in lines if not l.lower().startswith(("include:", "device:"))]
    hesuvi = any("hesuvi" in i.lower() for i in includes)
    active = "active=true" in _read(HESUVI / "deact.txt").replace(" ", "").lower() if hesuvi else False
    m = re.search(r'"([0-9a-f-]{36})"', _read(HESUVI / "devna.txt").lower())
    # the app's own file decides which headphones the mode runs on (it follows the default output); devna.txt is
    # HeSuVi's original binding and only the fallback before the first switch
    t = re.search(r'regexsearch\("([0-9a-f-]{36})"', _read(HESUVI / "soundmode.txt").lower())
    return {"installed": (EAPO_DIR / "EqualizerAPO.dll").exists(), "includes": includes, "device_filters": devices,
            "own_filters": len(filters), "hesuvi": hesuvi, "hesuvi_active": active,
            "hesuvi_device": t.group(1) if t else (m.group(1) if m else None),
            "devna_device": m.group(1) if m else None}


# ---------------------------------------------------------------- scan
def scan():
    native = _helper()
    eapo = eapo_state()
    procs = processes()
    eps = []
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, RENDER) as root:
        i = 0
        while True:
            try: sub = winreg.EnumKey(root, i)
            except OSError: break
            i += 1
            base = rf"{RENDER}\{sub}"
            state = _reg_values(base).get("devicestate", 0)
            if state not in (1, 8): continue   # active or unplugged
            p = _reg_values(base + r"\Properties"); fx = _reg_values(base + r"\FxProperties")
            g = sub.strip("{}").lower(); n = native.get(g, {})
            ep = Endpoint(g, p.get(PK_NAME.lower(), "?"), p.get(PK_IFACE.lower(), ""), state,
                          n.get("default", False), n.get("default_comm", False))
            _fill_format(ep, p)
            # Windows Spatial sound
            mx = n.get("spatial_max_dyn", -1)
            if state == 1 and mx >= 0:
                ep.layers.append(Layer("spatial", "Windows Spatial sound", mx > 0,
                                       f"{mx} dynamic objects" if mx > 0 else "Off"))
            # APOs registered on the endpoint
            disabled = _vt_bool(fx.get(PK_DISABLE_SYSFX.lower())) or p.get(PK_DISABLE_SYSFX.lower()) == 1
            ep.sysfx_disabled = disabled
            clsids, offload = {}, {}
            for slots_map, dst in ((FX_SLOTS, clsids), (OFFLOAD_SLOTS, offload)):
                for key, slot in slots_map.items():
                    v = fx.get(key.lower())
                    for c in (v if isinstance(v, list) else [v] if v else []):
                        c = c.strip("{}").lower(); dst.setdefault(c, []).append(slot)
            has_eapo = bool(EAPO_CLSIDS & clsids.keys())
            if has_eapo:
                targets = g == eapo["hesuvi_device"] if eapo["hesuvi_device"] else True
                on = eapo["hesuvi"] and eapo["hesuvi_active"] and targets
                own = eapo["own_filters"] > 0 and not eapo["device_filters"]
                detail = ("HeSuVi " + ("BAT" if eapo["hesuvi_active"] else "TAT")) if eapo["hesuvi"] else "khong co HeSuVi"
                if eapo["hesuvi"] and not targets: detail += " (cau hinh nham thiet bi khac)"
                ep.layers.append(Layer("eapo", "Equalizer APO", on or own, detail))
            vendors = {}   # one layer per vendor package (Realtek SFX+MFX+EFX = one product)
            for src, is_off in ((clsids, False), (offload, True)):
                for c, slots in src.items():
                    if c in EAPO_CLSIDS or c in MS_CLSIDS: continue
                    nm = vendor_name(c)
                    v = vendors.setdefault(nm, {"slots": set(), "main": False})
                    v["slots"].update(slots); v["main"] |= not is_off
            for nm, v in vendors.items():
                slots = "/".join(sorted(v["slots"]))
                if not v["main"]:   # registered only for offloaded streams: not in the normal playback path
                    ep.layers.append(Layer("vendor", nm, False, slots + " (offload path only, normally unused)", certain=False))
                    continue
                ep.layers.append(Layer("vendor", nm, not disabled, slots
                                       + (" (enhancements dang bi tat)" if disabled else ""), certain=False))
            on_fx = [nm for k, nm in SYSFX_TOGGLES.items() if _vt_bool(fx.get(k.lower()))]
            if on_fx:
                ep.layers.append(Layer("sysfx", "Windows Enhancements", not disabled, ", ".join(on_fx)))
            eps.append(ep)
    # user-mode processors act on whatever the default device is
    apps = sorted({v for k, v in APPS.items() if k in procs})
    for ep in eps:
        if ep.default:
            for a in apps: ep.layers.append(Layer("app", a, True, "dang chay", certain=False))
    info = sorted({v for k, v in INFO_APPS.items() if k in procs})
    eps.sort(key=lambda e: (e.state != 1, not e.default, e.name))
    return {"endpoints": eps, "eapo": eapo, "info": info}


def as_json(res):
    return json.dumps({"endpoints": [dict(asdict(e), conflict=e.conflict, label=e.label, surround=e.surround) for e in res["endpoints"]],
                       "eapo": res["eapo"], "info": res["info"]}, ensure_ascii=False, indent=1)
