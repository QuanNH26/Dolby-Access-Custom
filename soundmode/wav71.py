"""Write a 7.1 WAVE_FORMAT_EXTENSIBLE file (mask 0x63F: FL FR FC LFE BL BR SL SR) and play it through Windows'
own player (PlaySound / System.Media.SoundPlayer), so the 7.1 stream reaches the spatial renderer like a game would."""
import struct, subprocess
import numpy as np

MASK_71 = 0x63F
KSDATAFORMAT_SUBTYPE_IEEE_FLOAT = bytes.fromhex("0300000000001000800000aa00389b71")


def write(path, x, fs):
    x = np.asarray(x, np.float32); n, ch = x.shape
    data = x.tobytes()
    fmt = struct.pack("<HHIIHHHHI16s", 0xFFFE, ch, fs, fs * ch * 4, ch * 4, 32, 22, 32, MASK_71,
                      KSDATAFORMAT_SUBTYPE_IEEE_FLOAT)
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 4 + 8 + len(fmt) + 8 + len(data)) + b"WAVE")
        f.write(b"fmt " + struct.pack("<I", len(fmt)) + fmt)
        f.write(b"data" + struct.pack("<I", len(data)) + data)


def play(path):
    ps = f"$p = New-Object System.Media.SoundPlayer '{path}'; $p.PlaySync()"
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
