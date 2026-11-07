// audiohelper.exe - tiny Core Audio probe for soundmode (build: build.cmd, .NET Framework csc, no downloads)
//   audiohelper list   -> one JSON object per render endpoint (active + unplugged): state, default roles, Windows Spatial sound state
//   (names/FX come from the registry on the Python side)
//   audiohelper sysfx <endpoint-guid> [0|1] -> read / set "Audio enhancements" off (PKEY_AudioEndpoint_Disable_SysFx)
//                                             for one render endpoint. Setting needs admin. Only the property store is
//                                             opened (no audio client), so it is safe on Bluetooth Hands-Free endpoints.
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;


[ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator {
    int EnumAudioEndpoints(int dataFlow, int stateMask, out IMMDeviceCollection devices);
    int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice device);
    int GetDevice([MarshalAs(UnmanagedType.LPWStr)] string id, out IMMDevice device);
}
[StructLayout(LayoutKind.Sequential)] struct PROPERTYKEY { public Guid fmtid; public int pid; }
[StructLayout(LayoutKind.Explicit, Size = 24)] struct PROPVARIANT { [FieldOffset(0)] public ushort vt; [FieldOffset(8)] public uint u4; [FieldOffset(8)] public long i8; }
[ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IPropertyStore {
    [PreserveSig] int GetCount(out int n);
    [PreserveSig] int GetAt(int i, out PROPERTYKEY k);
    [PreserveSig] int GetValue(ref PROPERTYKEY k, out PROPVARIANT v);
    [PreserveSig] int SetValue(ref PROPERTYKEY k, ref PROPVARIANT v);
    [PreserveSig] int Commit();
}
[ComImport, Guid("0BD7A1BE-7A1A-44DB-8397-CC5392387B5E"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceCollection { int GetCount(out int n); int Item(int i, out IMMDevice d); }
[ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice {
    [PreserveSig] int Activate(ref Guid iid, int clsCtx, IntPtr activationParams, [MarshalAs(UnmanagedType.IUnknown)] out object o);
    int OpenPropertyStore(int access, out IntPtr store);
    int GetId([MarshalAs(UnmanagedType.LPWStr)] out string id);
    int GetState(out int state);
}
[ComImport, Guid("BBF8E066-AAAA-49BE-9A4D-FD2A858EA27F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface ISpatialAudioClient {
    [PreserveSig] int GetStaticObjectPosition(int type, out float x, out float y, out float z);
    [PreserveSig] int GetNativeStaticObjectTypeMask(out int mask);
    [PreserveSig] int GetMaxDynamicObjectCount(out int n);
}
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumerator { }

static class Program {
    static string Esc(string s) {
        var b = new StringBuilder();
        foreach (char c in s ?? "") { if (c == '"' || c == '\\') b.Append('\\').Append(c); else if (c < 32) b.AppendFormat("\\u{0:x4}", (int)c); else b.Append(c); }
        return b.ToString();
    }
    static int SysFx(IMMDeviceEnumerator en, string guid, string set) {
        IMMDevice d;
        try { en.GetDevice("{0.0.0.00000000}.{" + guid.Trim('{', '}') + "}", out d); }
        catch (Exception e) { Console.WriteLine("{{\"ok\":false,\"error\":\"device not found: {0}\"}}", Esc(e.Message)); return 2; }
        var key = new PROPERTYKEY { fmtid = new Guid("1da5d803-d492-4edd-8c23-e0c0ffee7f0e"), pid = 5 };
        IntPtr ps; int hr;
        try { d.OpenPropertyStore(set == null ? 0 : 2, out ps); }   // STGM_READ / STGM_READWRITE
        catch (Exception e) { Console.WriteLine("{{\"ok\":false,\"error\":\"{0}\",\"hr\":{1}}}", Esc(e.Message), Marshal.GetHRForException(e)); return 5; }
        var store = (IPropertyStore)Marshal.GetObjectForIUnknown(ps); Marshal.Release(ps);
        PROPVARIANT v; hr = store.GetValue(ref key, out v);
        bool before = hr == 0 && ((v.vt == 19 || v.vt == 3) ? v.u4 != 0 : v.vt == 11 ? (v.u4 & 0xffff) != 0 : false);
        if (set != null) {
            var nv = new PROPVARIANT { vt = 19, u4 = set == "1" ? 1u : 0u };   // VT_UI4, ENDPOINT_SYSFX_DISABLED = 1
            hr = store.SetValue(ref key, ref nv);
            if (hr == 0) hr = store.Commit();
            if (hr != 0) { Console.WriteLine("{{\"ok\":false,\"error\":\"SetValue failed\",\"hr\":{0}}}", hr); return 3; }
        }
        Console.WriteLine("{{\"ok\":true,\"disabled_before\":{0},\"disabled\":{1}}}", before ? "true" : "false",
            set == null ? (before ? "true" : "false") : (set == "1" ? "true" : "false"));
        return 0;
    }
    static int Main(string[] args) {
        Console.OutputEncoding = Encoding.UTF8;
        var en = (IMMDeviceEnumerator)new MMDeviceEnumerator();
        if (args.Length >= 2 && args[0] == "sysfx") return SysFx(en, args[1], args.Length >= 3 ? args[2] : null);
        var defaults = new string[3];
        for (int role = 0; role < 3; role++) {   // console, multimedia, communications
            IMMDevice d; try { en.GetDefaultAudioEndpoint(0, role, out d); string id; d.GetId(out id); defaults[role] = id; } catch { }
        }
        IMMDeviceCollection col; en.EnumAudioEndpoints(0, 0x1 | 0x8, out col);   // ACTIVE | UNPLUGGED
        int n; col.GetCount(out n);
        for (int i = 0; i < n; i++) {
            IMMDevice d; col.Item(i, out d);
            string id; d.GetId(out id); int state; d.GetState(out state);
            int spMax = -1, spMask = -1, spHr = 0;
            // Only the default playback device: activating any audio client on a Bluetooth Hands-Free endpoint opens the
            // call (SCO) link and silences the headset's stereo endpoint. Others report -1 (unknown).
            if (state == 1 && (id == defaults[0] || id == defaults[1])) {
                var iid = typeof(ISpatialAudioClient).GUID; object o;
                spHr = d.Activate(ref iid, 0x17, IntPtr.Zero, out o);   // CLSCTX_ALL
                if (spHr == 0) {
                    var sac = (ISpatialAudioClient)o;
                    if (sac.GetMaxDynamicObjectCount(out spMax) != 0) spMax = -1;
                    if (sac.GetNativeStaticObjectTypeMask(out spMask) != 0) spMask = -1;
                    Marshal.ReleaseComObject(sac);
                }
            }
            Console.WriteLine("{{\"id\":\"{0}\",\"state\":{1},\"default\":{2},\"default_comm\":{3},\"spatial_hr\":{4},\"spatial_max_dyn\":{5},\"spatial_mask\":{6}}}",
                Esc(id), state, id == defaults[1] ? "true" : "false", id == defaults[2] ? "true" : "false",
                spHr, spMax, spMask);
        }
        return 0;
    }
}
