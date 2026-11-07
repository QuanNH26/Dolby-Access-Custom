"""Offline check: run MemLeveler.dll (via ctypes, acting as a minimal VST host) on the leveler-probe stimulus and
compare its gain per 20 ms frame with the Python model.  python -I test_leveler.py "<chunk string>" """
import ctypes as C, sys
from pathlib import Path
import numpy as np
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
from soundmode import levmodel, levprobe

Disp = C.CFUNCTYPE(C.c_ssize_t, C.c_void_p, C.c_int32, C.c_int32, C.c_ssize_t, C.c_void_p, C.c_float)
Proc = C.CFUNCTYPE(None, C.c_void_p, C.POINTER(C.POINTER(C.c_float)), C.POINTER(C.POINTER(C.c_float)), C.c_int32)


class AEffect(C.Structure):
    _fields_ = [("magic", C.c_int32), ("dispatcher", Disp), ("process", C.c_void_p), ("setParameter", C.c_void_p),
                ("getParameter", C.c_void_p), ("numPrograms", C.c_int32), ("numParams", C.c_int32),
                ("numInputs", C.c_int32), ("numOutputs", C.c_int32), ("flags", C.c_int32),
                ("resvd1", C.c_ssize_t), ("resvd2", C.c_ssize_t), ("initialDelay", C.c_int32),
                ("realQualities", C.c_int32), ("offQualities", C.c_int32), ("ioRatio", C.c_float),
                ("object", C.c_void_p), ("user", C.c_void_p), ("uniqueID", C.c_int32), ("version", C.c_int32),
                ("processReplacing", Proc), ("processDoubleReplacing", C.c_void_p), ("future", C.c_char * 56)]


def run(chunk, x, fs=44100, block=441, dll_path=None):
    dll = C.CDLL(str(dll_path or HERE / "MemLeveler.dll"))
    dll.VSTPluginMain.restype = C.POINTER(AEffect)
    e = dll.VSTPluginMain(None); fx = e.contents
    assert fx.magic == 0x56737450
    fx.dispatcher(e, 10, 0, 0, None, float(fs))                    # effSetSampleRate
    b = chunk.encode(); buf = C.create_string_buffer(b)
    fx.dispatcher(e, 24, 0, len(b), buf, 0.0)                        # effSetChunk
    fx.dispatcher(e, 12, 0, 1, None, 0.0)                            # effMainsChanged on
    out = np.zeros_like(x, dtype=np.float32); xs = x.astype(np.float32)
    for i in range(0, len(x), block):
        a = np.ascontiguousarray(xs[i:i + block]); n = len(a)
        o = np.zeros(n, np.float32)
        ins = (C.POINTER(C.c_float) * 2)(a.ctypes.data_as(C.POINTER(C.c_float)), a.ctypes.data_as(C.POINTER(C.c_float)))
        o2 = np.zeros(n, np.float32)
        outs = (C.POINTER(C.c_float) * 2)(o.ctypes.data_as(C.POINTER(C.c_float)), o2.ctypes.data_as(C.POINTER(C.c_float)))
        fx.processReplacing(e, ins, outs, n); out[i:i + n] = o
    p = C.c_void_p(); n = fx.dispatcher(e, 23, 0, 0, C.byref(p), 0.0)  # effGetChunk
    print("chunk back:", C.string_at(p, n).decode())
    fx.dispatcher(e, 1, 0, 0, None, 0.0)
    return out


if __name__ == "__main__":
    chunk = sys.argv[1]
    P = {k: float(v) for k, v in (kv.split("=") for kv in chunk.split(";"))}
    x, _ = levprobe.stimulus()
    y = run(chunk, x)
    g_dll = levprobe.frames_db(y) - levprobe.frames_db(x)
    g_py = levmodel.simulate_frames(levprobe.frames_db(x), P)
    n = min(len(g_dll), len(g_py)) - 1
    d = g_dll[1:n + 1] - g_py[:n]            # plugin applies a frame's gain one frame later
    print(f"plugin vs model: mean {d.mean():+.3f} dB, rms {np.sqrt(np.mean(d**2)):.3f} dB, max {np.abs(d).max():.2f} dB")
