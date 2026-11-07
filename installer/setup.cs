// DolbyAccessCustom-Setup.exe - per-user installer (no admin). build.ps1 appends the app as a zip after this exe:
//   [setup.exe][payload.zip][8-byte payload length][8-byte magic "DACSETUP"]
// Installs to %LOCALAPPDATA%\Programs\Dolby Access Custom, keeps the user's state.json / backups on update,
// adds Start menu + Desktop shortcuts and an "Apps & features" entry, then starts the app.
//   DolbyAccessCustom-Setup.exe            install / update (window with progress)
//   DolbyAccessCustom-Setup.exe /silent    same, no questions
//   <install dir>\uninstall.exe /uninstall remove (called from Apps & features)
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: System.Reflection.AssemblyTitle("Dolby Access Custom Setup")]
[assembly: System.Reflection.AssemblyProduct("Dolby Access Custom")]

static class Setup
{
    const string App = "Dolby Access Custom";
    const string Exe = "Dolby Access Custom.exe";
    const string UninstKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\DolbyAccessCustom";
    static readonly string[] Keep = { "state.json", "backups" };   // user data, never overwritten or removed on update
    static string Dir { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", App); } }
    static string StartMenu { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), App + ".lnk"); } }
    static string Desktop { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), App + ".lnk"); } }

    [STAThread]
    static int Main(string[] args)
    {
        bool silent = Array.Exists(args, a => a.Equals("/silent", StringComparison.OrdinalIgnoreCase));
        if (Array.Exists(args, a => a.Equals("/uninstall", StringComparison.OrdinalIgnoreCase))) return Uninstall(silent);
        Application.EnableVisualStyles();
        return Install(silent);
    }

    static void StopApp()
    {
        // the window runs as runtime\pythonw.exe inside the install dir
        foreach (var p in Process.GetProcessesByName("pythonw"))
        {
            try { if (p.MainModule.FileName.StartsWith(Dir, StringComparison.OrdinalIgnoreCase)) { p.Kill(); p.WaitForExit(5000); } }
            catch { }
        }
    }

    static string Payload()
    {
        string self = Process.GetCurrentProcess().MainModule.FileName;
        using (var fs = File.OpenRead(self))
        {
            var tail = new byte[16];
            fs.Seek(-16, SeekOrigin.End); fs.Read(tail, 0, 16);
            if (Encoding.ASCII.GetString(tail, 8, 8) != "DACSETUP") throw new Exception("This setup file is incomplete (no app inside). Download it again.");
            long len = BitConverter.ToInt64(tail, 0);
            string tmp = Path.Combine(Path.GetTempPath(), "DolbyAccessCustom-" + Guid.NewGuid().ToString("N") + ".zip");
            fs.Seek(-16 - len, SeekOrigin.End);
            using (var o = File.Create(tmp))
            {
                var buf = new byte[1 << 20]; long left = len;
                while (left > 0) { int n = fs.Read(buf, 0, (int)Math.Min(buf.Length, left)); if (n <= 0) break; o.Write(buf, 0, n); left -= n; }
            }
            return tmp;
        }
    }

    static void CopyStub(string dst)   // the setup exe without the app payload, for uninstalling
    {
        using (var fs = File.OpenRead(Process.GetCurrentProcess().MainModule.FileName))
        using (var o = File.Create(dst))
        {
            var tail = new byte[16]; fs.Seek(-16, SeekOrigin.End); fs.Read(tail, 0, 16);
            long stub = fs.Length - 16 - BitConverter.ToInt64(tail, 0);
            fs.Seek(0, SeekOrigin.Begin);
            var buf = new byte[1 << 16]; long left = stub;
            while (left > 0) { int n = fs.Read(buf, 0, (int)Math.Min(buf.Length, left)); if (n <= 0) break; o.Write(buf, 0, n); left -= n; }
        }
    }

    static int Install(bool silent)
    {
        var form = new Form { Text = App + " Setup", Width = 460, Height = 170, FormBorderStyle = FormBorderStyle.FixedDialog,
                              MaximizeBox = false, MinimizeBox = false, StartPosition = FormStartPosition.CenterScreen };
        try { form.Icon = Icon.ExtractAssociatedIcon(Process.GetCurrentProcess().MainModule.FileName); } catch { }
        var label = new Label { Left = 20, Top = 20, Width = 410, Height = 40, Text = "Installing " + App + " for this Windows user..." };
        var bar = new ProgressBar { Left = 20, Top = 70, Width = 405, Height = 20, Minimum = 0, Maximum = 100 };
        form.Controls.Add(label); form.Controls.Add(bar);
        int code = 0;
        form.Shown += (s, e) => new Thread(() =>
        {
            string zip = null;
            try
            {
                StopApp();
                zip = Payload();
                Directory.CreateDirectory(Dir);
                using (var z = ZipFile.OpenRead(zip))
                {
                    int i = 0, total = z.Entries.Count;
                    foreach (var en in z.Entries)
                    {
                        i++;
                        string rel = en.FullName.Replace('/', '\\');
                        string top = rel.Split('\\')[0];
                        string dst = Path.Combine(Dir, rel);
                        if (Array.Exists(Keep, k => k.Equals(top, StringComparison.OrdinalIgnoreCase)) && File.Exists(dst)) continue;
                        if (rel.EndsWith("\\")) { Directory.CreateDirectory(dst); continue; }
                        Directory.CreateDirectory(Path.GetDirectoryName(dst));
                        en.ExtractToFile(dst, true);
                        if (i % 50 == 0) form.BeginInvoke((Action)(() => bar.Value = i * 100 / total));
                    }
                }
                CopyStub(Path.Combine(Dir, "uninstall.exe"));
                string exe = Path.Combine(Dir, Exe);
                Shortcut(StartMenu, exe); Shortcut(Desktop, exe);
                using (var k = Registry.CurrentUser.CreateSubKey(UninstKey))
                {
                    k.SetValue("DisplayName", App);
                    k.SetValue("DisplayIcon", exe + ",0");
                    k.SetValue("Publisher", "QuanNH26");
                    k.SetValue("InstallLocation", Dir);
                    k.SetValue("UninstallString", "\"" + Path.Combine(Dir, "uninstall.exe") + "\" /uninstall");
                    k.SetValue("NoModify", 1, RegistryValueKind.DWord); k.SetValue("NoRepair", 1, RegistryValueKind.DWord);
                }
                Process.Start(new ProcessStartInfo(exe) { WorkingDirectory = Dir, UseShellExecute = true });
            }
            catch (Exception ex)
            {
                code = 1;
                form.BeginInvoke((Action)(() => MessageBox.Show(form, "Setup failed:\n\n" + ex.Message, App, MessageBoxButtons.OK, MessageBoxIcon.Error)));
            }
            finally
            {
                if (zip != null) try { File.Delete(zip); } catch { }
                form.BeginInvoke((Action)(() => form.Close()));
            }
        }) { IsBackground = true }.Start();
        Application.Run(form);
        return code;
    }

    static void Shortcut(string lnk, string target)
    {
        var t = Type.GetTypeFromProgID("WScript.Shell");
        object sh = Activator.CreateInstance(t);
        object s = t.InvokeMember("CreateShortcut", System.Reflection.BindingFlags.InvokeMethod, null, sh, new object[] { lnk });
        var st = s.GetType();
        st.InvokeMember("TargetPath", System.Reflection.BindingFlags.SetProperty, null, s, new object[] { target });
        st.InvokeMember("WorkingDirectory", System.Reflection.BindingFlags.SetProperty, null, s, new object[] { Path.GetDirectoryName(target) });
        st.InvokeMember("IconLocation", System.Reflection.BindingFlags.SetProperty, null, s, new object[] { target + ",0" });
        st.InvokeMember("Save", System.Reflection.BindingFlags.InvokeMethod, null, s, null);
    }

    static int Uninstall(bool silent)
    {
        if (!silent && MessageBox.Show("Remove " + App + "?\n\nAudio devices you connected stay connected; use Disconnect in the app first if you want them back as before.",
                                       App, MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return 1;
        StopApp();
        foreach (var l in new[] { StartMenu, Desktop }) try { File.Delete(l); } catch { }
        try { Registry.CurrentUser.DeleteSubKeyTree(UninstKey, false); } catch { }
        // uninstall.exe cannot delete its own folder while running: hand that to cmd after we exit
        Process.Start(new ProcessStartInfo("cmd.exe", "/c timeout /t 2 /nobreak >nul & rmdir /s /q \"" + Dir + "\"")
                      { CreateNoWindow = true, UseShellExecute = false, WorkingDirectory = Path.GetTempPath() });
        return 0;
    }
}
