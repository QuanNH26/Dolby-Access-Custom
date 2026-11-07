"""Dolby Access Custom - window entry point (started by "Dolby Access Custom.exe").

One native window (pywebview on Edge WebView2, which ships with Windows 10/11) showing gui/web and exposing
gui/api.py:Api to it. Only one window per PC: a second start just focuses the first.
"""
import ctypes, os, sys, threading, time
from ctypes import wintypes as wt
from pathlib import Path

HERE = Path(__file__).resolve().parent
WEB = HERE / "web"
TITLE = "Dolby Access Custom"
APP_ID = "DolbyAccessCustom.Gui"
LAUNCHER = HERE.parent / "Dolby Access Custom.exe"
LOCAL = Path(os.environ.get("LOCALAPPDATA", HERE)) / "DolbyAccessCustom"   # browser cache: per PC, never in the synced folder
sys.path.insert(0, str(HERE))


PIDFILE = LOCAL / "gui.pid"


def _window_of(pid):
    """Top-level window titled TITLE that belongs to process pid (Explorer shows a folder with the same title)."""
    u32 = ctypes.windll.user32; found = []
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def cb(hwnd, _):
        owner = ctypes.c_ulong()
        u32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(owner))
        if owner.value == pid:
            buf = ctypes.create_unicode_buffer(256); u32.GetWindowTextW(ctypes.c_void_p(hwnd), buf, 256)
            if buf.value == TITLE: found.append(hwnd); return False
        return True
    u32.EnumWindows(proto(cb), None)
    return found[0] if found else None


def _bring_to_front(hwnd):
    u32 = ctypes.windll.user32; h = ctypes.c_void_p(hwnd)
    if u32.IsIconic(h): u32.ShowWindow(h, 9)   # SW_RESTORE
    u32.keybd_event(0x12, 0, 0, 0); u32.keybd_event(0x12, 0, 2, 0)   # Alt tap: lets a background process take focus
    u32.SetForegroundWindow(h)


def _single_instance():
    k32 = ctypes.windll.kernel32
    k32.CreateMutexW(None, False, "Local\\DolbyAccessCustomGui")
    if k32.GetLastError() != 183:   # ERROR_ALREADY_EXISTS
        LOCAL.mkdir(parents=True, exist_ok=True); PIDFILE.write_text(str(os.getpid()))
        return True
    try: hwnd = _window_of(int(PIDFILE.read_text()))
    except (OSError, ValueError): hwnd = None
    if hwnd: _bring_to_front(hwnd)
    return False


def _error(text):
    ctypes.windll.user32.MessageBoxW(None, text, TITLE, 0x10)


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", ctypes.c_byte * 16), ("pid", wt.DWORD)]


class _PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("p", ctypes.c_void_p), ("p2", ctypes.c_void_p)]


def _pin_as_launcher(hwnd):
    """Taskbar pin/relaunch target = our launcher exe with its icon, not pythonw.exe (which showed the Python logo).
    Sets the window's AppUserModel relaunch properties (SHGetPropertyStoreForWindow)."""
    if not LAUNCHER.exists(): return
    import uuid
    ole32 = ctypes.windll.ole32; ole32.CoInitialize(None)
    iid = (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99").bytes_le)   # IPropertyStore
    store = ctypes.c_void_p()
    if ctypes.windll.shell32.SHGetPropertyStoreForWindow(wt.HWND(hwnd), ctypes.byref(iid), ctypes.byref(store)) != 0: return
    vtbl = ctypes.cast(ctypes.cast(store, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    set_value = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_PROPERTYKEY), ctypes.POINTER(_PROPVARIANT))(vtbl[6])
    commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtbl[7])
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])
    fmt = uuid.UUID("9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3").bytes_le   # PKEY_AppUserModel_*
    keep = []
    for pid, text in ((2, f'"{LAUNCHER}"'), (3, f"{LAUNCHER},0"), (4, TITLE), (5, APP_ID)):   # RelaunchCommand, Icon, Name, ID
        buf = ctypes.create_unicode_buffer(text); keep.append(buf)
        key = _PROPERTYKEY((ctypes.c_byte * 16).from_buffer_copy(fmt), pid)
        var = _PROPVARIANT(31, 0, 0, 0, ctypes.cast(buf, ctypes.c_void_p), None)   # VT_LPWSTR
        set_value(store, ctypes.byref(key), ctypes.byref(var))
    commit(store); release(store)


def _set_icon():
    """Own taskbar entry + our icon instead of python's (the window belongs to pythonw.exe)."""
    u32 = ctypes.windll.user32; vp = ctypes.c_void_p
    u32.LoadImageW.restype = vp
    u32.SendMessageW.argtypes = [vp, ctypes.c_uint, vp, vp]
    for _ in range(50):
        hwnd = _window_of(os.getpid())
        if hwnd: break
        time.sleep(0.1)
    else: return
    for size, kind in ((16, 0), (32, 1), (256, 1)):   # ICON_SMALL=0, ICON_BIG=1
        h = u32.LoadImageW(None, str(HERE / "app.ico"), 1, size, size, 0x10)   # IMAGE_ICON, LR_LOADFROMFILE
        if h: u32.SendMessageW(hwnd, 0x80, kind, h)   # WM_SETICON
    try: _pin_as_launcher(hwnd)
    except Exception: pass


def run_webview(api):
    import webview
    try: ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception: pass
    w = webview.create_window(TITLE, url=str(WEB / "index.html"), js_api=api, width=1240, height=800,
                              min_size=(980, 640), background_color="#0a0c11", text_select=False)
    w.events.shown += lambda: threading.Thread(target=_set_icon, daemon=True).start()
    LOCAL.mkdir(parents=True, exist_ok=True)
    # the page is served over pywebview's local HTTP server and WebView2 keeps an HTTP cache in storage_path:
    # drop it on every start so an updated app.js / app.css is always picked up (settings in Local Storage stay)
    import shutil
    for d in ("Cache", "Code Cache", "GPUCache"):
        shutil.rmtree(LOCAL / "webview" / "EBWebView" / "Default" / d, ignore_errors=True)
    webview.start(gui="edgechromium", private_mode=False, storage_path=str(LOCAL / "webview"))
    return w


def main():
    if os.name == "nt" and not _single_instance(): return
    from api import Api
    run_webview(Api())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        LOCAL.mkdir(parents=True, exist_ok=True)
        with open(LOCAL / "gui.log", "a", encoding="utf-8") as f:
            f.write(time.strftime("\n%Y-%m-%d %H:%M:%S\n") + traceback.format_exc())
        sys.exit(1)
