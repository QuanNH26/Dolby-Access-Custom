// bridge.exe CAPTURE_GUID [RENDER_GUID] - forward a capture endpoint (VB-Audio "CABLE Output") to a render endpoint
// (default: the default playback device) with ~30 ms latency. Replaces Windows "Listen to this device".
// Build: build.cmd (Windows' own csc, no downloads). Runs until killed.
using System;
using System.Runtime.InteropServices;
using System.Threading;

[StructLayout(LayoutKind.Sequential, Pack = 2)]
struct WFX {
    public ushort wFormatTag, nChannels; public uint nSamplesPerSec, nAvgBytesPerSec;
    public ushort nBlockAlign, wBitsPerSample, cbSize, wValidBitsPerSample; public uint dwChannelMask; public Guid SubFormat;
}
[ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator { int NotImpl1(); [PreserveSig] int GetDefaultAudioEndpoint(int flow, int role, out IMMDevice d); [PreserveSig] int GetDevice([MarshalAs(UnmanagedType.LPWStr)] string id, out IMMDevice d); }
[ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice { [PreserveSig] int Activate(ref Guid iid, int ctx, IntPtr p, [MarshalAs(UnmanagedType.IUnknown)] out object o); }
[ComImport, Guid("1CB9AD4C-DBFA-4c32-B178-C2F568A703B2"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioClient {
    [PreserveSig] int Initialize(int shareMode, uint flags, long bufferDuration, long periodicity, ref WFX fmt, IntPtr session);
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
[ComImport, Guid("C8ADBD64-E71E-48a0-A4DE-185C395CD317"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioCaptureClient {
    [PreserveSig] int GetBuffer(out IntPtr data, out uint frames, out uint flags, out ulong pos, out ulong qpc);
    [PreserveSig] int ReleaseBuffer(uint frames);
    [PreserveSig] int GetNextPacketSize(out uint frames);
}
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumerator { }

static class Bridge {
    static void Check(int hr, string what) { if (hr != 0) throw new Exception(what + " failed 0x" + hr.ToString("X8")); }
    static IAudioClient Open(IMMDeviceEnumerator en, string guid, int flow) {
        IMMDevice d;
        if (guid != null) Check(en.GetDevice("{0.0." + flow + ".00000000}.{" + guid.Trim('{', '}') + "}", out d), "GetDevice");
        else Check(en.GetDefaultAudioEndpoint(flow, 1, out d), "GetDefaultAudioEndpoint");
        Guid iid = typeof(IAudioClient).GUID; object o; Check(d.Activate(ref iid, 0x17, IntPtr.Zero, out o), "Activate");
        return (IAudioClient)o;
    }

    static int Main(string[] args) {
        if (args.Length < 1) { Console.Error.WriteLine("usage: bridge CAPTURE_GUID [RENDER_GUID]"); return 2; }
        var en = (IMMDeviceEnumerator)new MMDeviceEnumerator();
        while (true) {
            try { Run(en, args[0], args.Length > 1 ? args[1] : null); }
            catch (Exception e) { Console.Error.WriteLine(DateTime.Now.ToString("s") + " " + e.Message + " - retry in 3 s"); }
            Thread.Sleep(3000);   // device lost (BT reconnect, default changed): reopen
        }
    }

    static void Run(IMMDeviceEnumerator en, string capGuid, string renGuid) {
        var cap = Open(en, capGuid, 1); var ren = Open(en, renGuid, 0);
        IntPtr pf; Check(cap.GetMixFormat(out pf), "GetMixFormat");
        var f = (WFX)Marshal.PtrToStructure(pf, typeof(WFX)); Marshal.FreeCoTaskMem(pf);
        Check(cap.Initialize(0, 0, 200000, 0, ref f, IntPtr.Zero), "capture Initialize");                     // 20 ms
        Check(ren.Initialize(0, 0x80000000 | 0x08000000, 300000, 0, ref f, IntPtr.Zero), "render Initialize");  // 30 ms, autoconvert
        Guid ic = typeof(IAudioCaptureClient).GUID, ir = typeof(IAudioRenderClient).GUID; object o;
        Check(cap.GetService(ref ic, out o), "capture GetService"); var cc = (IAudioCaptureClient)o;
        Check(ren.GetService(ref ir, out o), "render GetService"); var rc = (IAudioRenderClient)o;
        uint rbuf; ren.GetBufferSize(out rbuf);
        int fb = f.nBlockAlign; var tmp = new byte[fb * 48000];
        Check(cap.Start(), "capture Start"); Check(ren.Start(), "render Start");
        Console.WriteLine("bridging " + f.nChannels + " ch " + f.nSamplesPerSec + " Hz");
        while (true) {
            Thread.Sleep(5);
            uint n; Check(cc.GetNextPacketSize(out n), "GetNextPacketSize");
            while (n > 0) {
                IntPtr data; uint frames, flags; ulong p1, p2;
                Check(cc.GetBuffer(out data, out frames, out flags, out p1, out p2), "capture GetBuffer");
                int bytes = (int)frames * fb;
                if ((flags & 2) != 0) Array.Clear(tmp, 0, bytes); else Marshal.Copy(data, tmp, 0, bytes);   // SILENT flag
                cc.ReleaseBuffer(frames);
                uint pad; ren.GetCurrentPadding(out pad);
                uint room = rbuf - pad, w = Math.Min(frames, room);                  // drop if the render side is full
                if (w > 0) { IntPtr rp; Check(rc.GetBuffer(w, out rp), "render GetBuffer"); Marshal.Copy(tmp, 0, rp, (int)w * fb); rc.ReleaseBuffer(w, 0); }
                Check(cc.GetNextPacketSize(out n), "GetNextPacketSize");
            }
        }
    }
}
