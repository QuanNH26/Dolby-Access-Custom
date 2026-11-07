// play71.exe FILE.wav [ENDPOINT_GUID] - play a float32 multichannel WAV (e.g. 7.1, mask 0x63F) on the default output through WASAPI
// shared mode with a proper WAVEFORMATEXTENSIBLE, so Windows Spatial sound (Dolby) renders it like game audio.
// Build: build.cmd (Windows' own csc, no downloads).
using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;

[StructLayout(LayoutKind.Sequential, Pack = 2)]
struct WAVEFORMATEXTENSIBLE {
    public ushort wFormatTag, nChannels; public uint nSamplesPerSec, nAvgBytesPerSec;
    public ushort nBlockAlign, wBitsPerSample, cbSize, wValidBitsPerSample; public uint dwChannelMask; public Guid SubFormat;
}

[ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator { int NotImpl1(); [PreserveSig] int GetDefaultAudioEndpoint(int flow, int role, out IMMDevice d); [PreserveSig] int GetDevice([MarshalAs(UnmanagedType.LPWStr)] string id, out IMMDevice d); }
[ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice { [PreserveSig] int Activate(ref Guid iid, int ctx, IntPtr p, [MarshalAs(UnmanagedType.IUnknown)] out object o); }
[ComImport, Guid("1CB9AD4C-DBFA-4c32-B178-C2F568A703B2"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioClient {
    [PreserveSig] int Initialize(int shareMode, uint flags, long bufferDuration, long periodicity, ref WAVEFORMATEXTENSIBLE fmt, IntPtr session);
    [PreserveSig] int GetBufferSize(out uint frames);
    [PreserveSig] int GetStreamLatency(out long lat);
    [PreserveSig] int GetCurrentPadding(out uint frames);
    [PreserveSig] int IsFormatSupported(int mode, IntPtr fmt, IntPtr closest);
    [PreserveSig] int GetMixFormat(out IntPtr fmt);
    [PreserveSig] int GetDevicePeriod(out long def, out long min);
    [PreserveSig] int Start();
    [PreserveSig] int Stop();
    [PreserveSig] int Reset();
    [PreserveSig] int SetEventHandle(IntPtr h);
    [PreserveSig] int GetService(ref Guid iid, [MarshalAs(UnmanagedType.IUnknown)] out object o);
}
[ComImport, Guid("F294ACFC-3146-4483-A7BF-ADDCA7C260E2"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioRenderClient { [PreserveSig] int GetBuffer(uint frames, out IntPtr data); [PreserveSig] int ReleaseBuffer(uint frames, uint flags); }
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumerator { }

static class Play71 {
    static void Check(int hr, string what) { if (hr != 0) throw new Exception(what + " failed 0x" + hr.ToString("X8")); }

    static int Main(string[] args) {
        if (args.Length < 1) { Console.Error.WriteLine("usage: play71 file.wav"); return 2; }
        byte[] wav = File.ReadAllBytes(args[0]);
        int pos = 12, fmtAt = -1, dataAt = -1, dataLen = 0;
        while (pos + 8 <= wav.Length) {
            string id = System.Text.Encoding.ASCII.GetString(wav, pos, 4); int len = BitConverter.ToInt32(wav, pos + 4);
            if (id == "fmt ") fmtAt = pos + 8; else if (id == "data") { dataAt = pos + 8; dataLen = len; break; }
            pos += 8 + len + (len & 1);
        }
        if (fmtAt < 0 || dataAt < 0) { Console.Error.WriteLine("bad wav"); return 2; }
        var f = new WAVEFORMATEXTENSIBLE();
        f.wFormatTag = 0xFFFE; f.nChannels = BitConverter.ToUInt16(wav, fmtAt + 2); f.nSamplesPerSec = BitConverter.ToUInt32(wav, fmtAt + 4);
        f.wBitsPerSample = 32; f.nBlockAlign = (ushort)(f.nChannels * 4); f.nAvgBytesPerSec = f.nSamplesPerSec * f.nBlockAlign;
        f.cbSize = 22; f.wValidBitsPerSample = 32;
        f.dwChannelMask = BitConverter.ToUInt16(wav, fmtAt) == 0xFFFE ? BitConverter.ToUInt32(wav, fmtAt + 20) : 0x63F;
        f.SubFormat = new Guid("00000003-0000-0010-8000-00aa00389b71");

        var en = (IMMDeviceEnumerator)new MMDeviceEnumerator(); IMMDevice dev;
        if (args.Length > 1) Check(en.GetDevice("{0.0.0.00000000}.{" + args[1].Trim('{', '}') + "}", out dev), "GetDevice");
        else Check(en.GetDefaultAudioEndpoint(0, 1, out dev), "GetDefaultAudioEndpoint");
        Guid iidClient = typeof(IAudioClient).GUID; object o;
        Check(dev.Activate(ref iidClient, 0x17, IntPtr.Zero, out o), "Activate");
        var ac = (IAudioClient)o;
        Check(ac.Initialize(0, 0x80000000 | 0x08000000, 10000000, 0, ref f, IntPtr.Zero), "Initialize");   // AUTOCONVERTPCM | SRC_DEFAULT_QUALITY
        uint bufFrames; Check(ac.GetBufferSize(out bufFrames), "GetBufferSize");
        Guid iidRender = typeof(IAudioRenderClient).GUID; Check(ac.GetService(ref iidRender, out o), "GetService");
        var rc = (IAudioRenderClient)o;
        int frameBytes = f.nBlockAlign, total = dataLen / frameBytes, done = 0;
        Action fill = () => {
            uint pad; ac.GetCurrentPadding(out pad);
            int n = (int)Math.Min(bufFrames - pad, (uint)(total - done)); if (n <= 0) return;
            IntPtr p; Check(rc.GetBuffer((uint)n, out p), "GetBuffer");
            Marshal.Copy(wav, dataAt + done * frameBytes, p, n * frameBytes);
            Check(rc.ReleaseBuffer((uint)n, 0), "ReleaseBuffer"); done += n;
        };
        fill(); Check(ac.Start(), "Start");
        while (done < total) { Thread.Sleep(20); fill(); }
        uint left; do { Thread.Sleep(20); ac.GetCurrentPadding(out left); } while (left > 0);
        ac.Stop();
        Console.WriteLine("played " + total + " frames, " + f.nChannels + " ch, mask 0x" + f.dwChannelMask.ToString("X"));
        return 0;
    }
}
