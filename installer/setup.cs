// DolbyAccessCustom-Setup.exe - per-user installer (no admin). build.ps1 appends the app as a zip after this exe:
//   [setup.exe][payload.zip][8-byte payload length][8-byte magic "DACSETUP"]
// A classic Next/Next wizard: Welcome -> License -> Install folder -> Options -> Ready -> Installing -> Finish.
// Default folder is %LOCALAPPDATA%\Programs\Dolby Access Custom (an update reuses the folder of the earlier install).
// The user's state.json / backups are kept on update. "Launch after install" is on by default.
//   DolbyAccessCustom-Setup.exe                               wizard
//   DolbyAccessCustom-Setup.exe /silent [/dir="D:\Apps\DAC"]  no questions (desktop shortcut, then start the app)
//   <install dir>\uninstall.exe /uninstall [/silent]          remove (called from Apps & features)
// Must compile with the C# 5 compiler that ships with Windows (no $"..", ?., => members).
using System;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.IO.Compression;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: System.Reflection.AssemblyTitle("Dolby Access Custom Setup")]
[assembly: System.Reflection.AssemblyProduct("Dolby Access Custom")]

static class Setup
{
    public const string App = "Dolby Access Custom";
    public const string Exe = "Dolby Access Custom.exe";
    const string UninstKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\DolbyAccessCustom";
    static readonly string[] Keep = { "state.json", "backups" };   // user data, never overwritten or removed on update
    public static string DefaultDir { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", App); } }
    public static string StartMenu { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), App + ".lnk"); } }
    public static string Desktop { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), App + ".lnk"); } }

    [DllImport("user32.dll")] static extern bool SetProcessDPIAware();

    [STAThread]
    static int Main(string[] args)
    {
        bool silent = HasArg(args, "/silent");
        if (HasArg(args, "/uninstall")) return Uninstall(silent);
        try { SetProcessDPIAware(); } catch { }
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        string zip = null;
        try
        {
            try { zip = Payload(); }
            catch (Exception ex) { if (!silent) MessageBox.Show(ex.Message, App + " Setup", MessageBoxButtons.OK, MessageBoxIcon.Error); return 1; }
            var prev = Previous();
            if (silent)
            {
                var o = new Options { Dir = ArgValue(args, "/dir=") ?? (prev.Dir ?? DefaultDir), Desktop = true, StartMenu = true, Launch = true };
                try { Install(zip, o, null); return 0; } catch { return 1; }
            }
            var w = new Wizard(zip, prev);
            Application.Run(w);
            return w.ExitCode;
        }
        finally { if (zip != null) try { File.Delete(zip); } catch { } }
    }

    static bool HasArg(string[] args, string a) { return Array.Exists(args, x => x.Equals(a, StringComparison.OrdinalIgnoreCase)); }
    static string ArgValue(string[] args, string prefix)
    {
        foreach (var a in args) if (a.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) return a.Substring(prefix.Length).Trim('"');
        return null;
    }

    public class Options { public string Dir; public bool Desktop, StartMenu, Launch; }
    public class Prev { public string Dir, Version; public bool Desktop = true; }

    public static Prev Previous()   // an earlier install of this app, from its Apps & features entry
    {
        var p = new Prev();
        try
        {
            using (var k = Registry.CurrentUser.OpenSubKey(UninstKey))
            {
                if (k == null) return p;
                string d = k.GetValue("InstallLocation") as string;
                if (!string.IsNullOrEmpty(d) && File.Exists(Path.Combine(d, Exe))) { p.Dir = d; p.Version = k.GetValue("DisplayVersion") as string; }
                object ds = k.GetValue("DesktopShortcut");
                if (ds is int) p.Desktop = (int)ds != 0;
            }
        }
        catch { }
        return p;
    }

    static void StopApp(string dir)
    {
        // the window runs as runtime\pythonw.exe inside the install dir
        string d = dir.TrimEnd('\\') + "\\";
        foreach (var p in Process.GetProcessesByName("pythonw"))
        {
            try { if (p.MainModule.FileName.StartsWith(d, StringComparison.OrdinalIgnoreCase)) { p.Kill(); p.WaitForExit(5000); } }
            catch { }
        }
    }

    static string Self { get { return System.Reflection.Assembly.GetEntryAssembly().Location; } }

    static string Payload()
    {
        using (var fs = File.OpenRead(Self))
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
        using (var fs = File.OpenRead(Self))
        using (var o = File.Create(dst))
        {
            var tail = new byte[16]; fs.Seek(-16, SeekOrigin.End); fs.Read(tail, 0, 16);
            long stub = fs.Length - 16 - BitConverter.ToInt64(tail, 0);
            fs.Seek(0, SeekOrigin.Begin);
            var buf = new byte[1 << 16]; long left = stub;
            while (left > 0) { int n = fs.Read(buf, 0, (int)Math.Min(buf.Length, left)); if (n <= 0) break; o.Write(buf, 0, n); left -= n; }
        }
    }

    // Reads small text files (VERSION, LICENSE) and the unpacked size from the payload.
    public static string ZipText(string zip, string name)
    {
        try
        {
            using (var z = ZipFile.OpenRead(zip))
            {
                var e = z.GetEntry(name);
                if (e == null) return null;
                using (var r = new StreamReader(e.Open())) return r.ReadToEnd();
            }
        }
        catch { return null; }
    }
    public static long ZipSize(string zip)
    {
        long n = 0;
        try { using (var z = ZipFile.OpenRead(zip)) foreach (var e in z.Entries) n += e.Length; } catch { }
        return n;
    }

    // progress(percent, text) is called from this (worker) thread; null in silent mode.
    public static void Install(string zip, Options o, Action<int, string> progress)
    {
        Action<int, string> say = progress ?? ((a, b) => { });
        string dir = o.Dir;
        say(0, "Closing " + App + " if it is running...");
        StopApp(dir);
        Directory.CreateDirectory(dir);
        string ver = (ZipText(zip, "VERSION") ?? "").Trim();
        using (var z = ZipFile.OpenRead(zip))
        {
            int i = 0, total = z.Entries.Count;
            foreach (var en in z.Entries)
            {
                i++;
                string rel = en.FullName.Replace('/', '\\');
                string top = rel.Split('\\')[0];
                string dst = Path.Combine(dir, rel);
                if (i % 25 == 0 || i == total) say(i * 90 / total, "Extracting: " + rel);
                if (Array.Exists(Keep, k => k.Equals(top, StringComparison.OrdinalIgnoreCase)) && File.Exists(dst)) continue;
                if (rel.EndsWith("\\")) { Directory.CreateDirectory(dst); continue; }
                Directory.CreateDirectory(Path.GetDirectoryName(dst));
                en.ExtractToFile(dst, true);
            }
        }
        say(92, "Creating the uninstaller...");
        CopyStub(Path.Combine(dir, "uninstall.exe"));
        string exe = Path.Combine(dir, Exe);
        say(95, "Creating shortcuts...");
        // a shortcut that cannot be made is not worth failing the install for
        try { if (o.StartMenu) Shortcut(StartMenu, exe); else TryDelete(StartMenu); } catch { say(95, "Could not create the Start menu shortcut."); }
        try { if (o.Desktop) Shortcut(Desktop, exe); else TryDelete(Desktop); } catch { say(96, "Could not create the desktop shortcut."); }
        say(98, "Registering in Apps & features...");
        using (var k = Registry.CurrentUser.CreateSubKey(UninstKey))
        {
            k.SetValue("DisplayName", App);
            if (ver.Length > 0) k.SetValue("DisplayVersion", ver);
            k.SetValue("DisplayIcon", exe + ",0");
            k.SetValue("Publisher", "QuanNH26");
            k.SetValue("URLInfoAbout", "https://github.com/QuanNH26/Dolby-Access-Custom");
            k.SetValue("InstallLocation", dir);
            k.SetValue("InstallDate", DateTime.Now.ToString("yyyyMMdd"));
            k.SetValue("EstimatedSize", (int)(DirSize(dir) / 1024), RegistryValueKind.DWord);
            k.SetValue("UninstallString", "\"" + Path.Combine(dir, "uninstall.exe") + "\" /uninstall");
            k.SetValue("QuietUninstallString", "\"" + Path.Combine(dir, "uninstall.exe") + "\" /uninstall /silent");
            k.SetValue("NoModify", 1, RegistryValueKind.DWord); k.SetValue("NoRepair", 1, RegistryValueKind.DWord);
            k.SetValue("DesktopShortcut", o.Desktop ? 1 : 0, RegistryValueKind.DWord);
        }
        say(100, "Done.");
        if (o.Launch) LaunchApp(dir);
    }

    public static void LaunchApp(string dir)
    {
        try { Process.Start(new ProcessStartInfo(Path.Combine(dir, Exe)) { WorkingDirectory = dir, UseShellExecute = true }); } catch { }
    }

    static long DirSize(string dir)
    {
        long n = 0;
        try { foreach (var f in new DirectoryInfo(dir).GetFiles("*", SearchOption.AllDirectories)) n += f.Length; } catch { }
        return n;
    }

    static void TryDelete(string f) { try { if (File.Exists(f)) File.Delete(f); } catch { } }

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
        // uninstall.exe sits in the install folder, wherever the user put it
        string dir = Path.GetDirectoryName(Self);
        if (!silent && MessageBox.Show("Remove " + App + " from " + dir + "?\n\nAudio devices you connected stay connected; use Disconnect in the app first if you want them back as before.",
                                       App, MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return 1;
        StopApp(dir);
        foreach (var l in new[] { StartMenu, Desktop }) TryDelete(l);
        try { Registry.CurrentUser.DeleteSubKeyTree(UninstKey, false); } catch { }
        // only remove a folder that really is ours (never a drive root or a folder holding other things)
        bool ours = File.Exists(Path.Combine(dir, Exe)) && Path.GetPathRoot(dir).TrimEnd('\\') != dir.TrimEnd('\\');
        if (ours)
        {
            // uninstall.exe cannot delete its own folder while running: hand that to cmd after we exit
            Process.Start(new ProcessStartInfo("cmd.exe", "/c timeout /t 2 /nobreak >nul & rmdir /s /q \"" + dir + "\"")
                          { CreateNoWindow = true, UseShellExecute = false, WorkingDirectory = Path.GetTempPath() });
        }
        if (!silent) MessageBox.Show(App + " was removed.", App, MessageBoxButtons.OK, MessageBoxIcon.Information);
        return 0;
    }
}

// ---------------------------------------------------------------------------------------------------------------
// The wizard window. Layout is in 96-dpi pixels and scaled with S() so it stays crisp on high-DPI screens.
class Wizard : Form
{
    public int ExitCode = 1;
    readonly string zip;
    readonly Setup.Prev prev;
    readonly string version, license;
    readonly long needBytes;
    readonly float k;
    readonly Font fTitle, fBig, fBold, fBody;
    Icon appIcon;

    enum P { Welcome, License, Folder, Options, Ready, Installing, Finish }
    P page;
    readonly Panel[] pages = new Panel[7];
    Panel header, banner;
    Label hTitle, hSub;
    Button back, next, cancel;

    // page controls
    RadioButton accept, decline;
    TextBox dirBox;
    Label spaceNeed, spaceFree, folderNote;
    CheckBox cbDesktop, cbStart, cbLaunch;
    TextBox readyText;
    ProgressBar bar;
    Label status, finTitle, finText;
    TextBox detail;
    bool installed, launched;

    int S(int v) { return (int)Math.Round(v * k); }

    public Wizard(string zip, Setup.Prev prev)
    {
        this.zip = zip; this.prev = prev;
        version = (Setup.ZipText(zip, "VERSION") ?? "").Trim();
        license = Setup.ZipText(zip, "LICENSE") ?? "See LICENSE in the install folder.";
        needBytes = Setup.ZipSize(zip);
        using (var g = CreateGraphics()) k = g.DpiX / 96f;
        AutoScaleMode = AutoScaleMode.None;
        fBody = new Font("Segoe UI", 9f);
        fBold = new Font("Segoe UI", 9f, FontStyle.Bold);
        fBig = new Font("Segoe UI", 15f, FontStyle.Bold);
        fTitle = new Font("Segoe UI", 9.75f, FontStyle.Bold);
        Font = fBody;
        Text = Setup.App + " " + version + " Setup";
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false; MinimizeBox = true;
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size(S(560), S(400));
        BackColor = SystemColors.Control;
        try { appIcon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); Icon = appIcon; } catch { }

        BuildChrome();
        BuildWelcome(); BuildLicense(); BuildFolder(); BuildOptions(); BuildReady(); BuildInstalling(); BuildFinish();
        Show(P.Welcome);
    }

    // ---- frame: header (inner pages), side banner (welcome/finish), bottom buttons -----------------------------
    void BuildChrome()
    {
        int bottom = S(52);
        var line = new Label { BorderStyle = BorderStyle.Fixed3D, Left = 0, Top = ClientSize.Height - bottom, Width = ClientSize.Width, Height = 2 };
        Controls.Add(line);
        var brand = new Label { Text = Setup.App + " " + version, ForeColor = SystemColors.GrayText, AutoSize = true, Left = S(12), Top = ClientSize.Height - bottom + S(18) };
        Controls.Add(brand);
        int bw = S(88), bh = S(27), by = ClientSize.Height - bottom + S(13);
        cancel = new Button { Text = "Cancel", Width = bw, Height = bh, Left = ClientSize.Width - S(12) - bw, Top = by };
        next = new Button { Text = "&Next >", Width = bw, Height = bh, Left = cancel.Left - S(12) - bw, Top = by };
        back = new Button { Text = "< &Back", Width = bw, Height = bh, Left = next.Left - bw, Top = by };
        Controls.Add(back); Controls.Add(next); Controls.Add(cancel);
        AcceptButton = next;
        back.Click += (s, e) => Go(-1);
        next.Click += (s, e) => Go(+1);
        cancel.Click += (s, e) => Close();

        header = new Panel { Left = 0, Top = 0, Width = ClientSize.Width, Height = S(62), BackColor = Color.White };
        hTitle = new Label { Font = fTitle, AutoSize = false, Left = S(20), Top = S(12), Width = S(440), Height = S(20) };
        hSub = new Label { AutoSize = false, Left = S(34), Top = S(33), Width = S(430), Height = S(26) };
        var hIcon = new PictureBox { Left = header.Width - S(58), Top = S(9), Width = S(44), Height = S(44), SizeMode = PictureBoxSizeMode.Zoom };
        if (appIcon != null) try { hIcon.Image = new Icon(appIcon, 48, 48).ToBitmap(); } catch { }
        header.Controls.Add(hTitle); header.Controls.Add(hSub); header.Controls.Add(hIcon);
        var hLine = new Label { BorderStyle = BorderStyle.Fixed3D, Left = 0, Top = S(62), Width = ClientSize.Width, Height = 2 };
        Controls.Add(header); Controls.Add(hLine);
        header.Tag = hLine;

        banner = new Panel { Left = 0, Top = 0, Width = S(170), Height = ClientSize.Height - bottom };
        banner.Paint += PaintBanner;
        Controls.Add(banner);
    }

    void PaintBanner(object s, PaintEventArgs e)
    {
        var r = banner.ClientRectangle;
        var g = e.Graphics;
        g.SmoothingMode = SmoothingMode.AntiAlias;
        using (var b = new LinearGradientBrush(r, Color.FromArgb(10, 14, 22), Color.FromArgb(28, 44, 72), LinearGradientMode.Vertical)) g.FillRectangle(b, r);
        // soft rings, a nod to sound waves
        using (var pen = new Pen(Color.FromArgb(40, 120, 170, 255), Math.Max(1f, k)))
            for (int i = 1; i <= 5; i++) { int d = S(60 + i * 34); g.DrawEllipse(pen, r.Width / 2 - d / 2, S(118) - d / 2, d, d); }
        if (appIcon != null) try { using (var ic = new Icon(appIcon, 256, 256)) g.DrawImage(ic.ToBitmap(), new Rectangle(r.Width / 2 - S(40), S(78), S(80), S(80))); } catch { }
        using (var f = new Font("Segoe UI", 11f, FontStyle.Bold))
        using (var f2 = new Font("Segoe UI", 8.5f))
        using (var sf = new StringFormat { Alignment = StringAlignment.Center })
        {
            g.DrawString("Dolby Access", f, Brushes.White, new RectangleF(0, S(176), r.Width, S(22)), sf);
            g.DrawString("Custom", f, Brushes.White, new RectangleF(0, S(196), r.Width, S(22)), sf);
            using (var gb = new SolidBrush(Color.FromArgb(150, 170, 200)))
                g.DrawString("Version " + version, f2, gb, new RectangleF(0, S(226), r.Width, S(18)), sf);
        }
    }

    Panel NewPage(bool withBanner)
    {
        int bottom = S(52);
        var p = withBanner
            ? new Panel { Left = S(170), Top = 0, Width = ClientSize.Width - S(170), Height = ClientSize.Height - bottom - 2, BackColor = Color.White }
            : new Panel { Left = 0, Top = S(64), Width = ClientSize.Width, Height = ClientSize.Height - bottom - S(64) - 2 };
        p.Visible = false;
        Controls.Add(p);
        return p;
    }

    Label Text_(Panel p, string text, int x, int y, int w, int h)
    {
        var l = new Label { Text = text, Left = S(x), Top = S(y), Width = S(w), Height = S(h), AutoSize = false };
        p.Controls.Add(l);
        return l;
    }

    // ---- pages --------------------------------------------------------------------------------------------------
    void BuildWelcome()
    {
        var p = pages[(int)P.Welcome] = NewPage(true);
        var t = Text_(p, "Welcome to the " + Setup.App + " Setup Wizard", 20, 18, 350, 60); t.Font = fBig;
        string body = "This wizard will install " + Setup.App + " " + version + " on this computer.\n\n" +
                      Setup.App + " gives your headphones Dolby-style sound modes (Music, Movie, Game, Voice) and 7.1 virtual surround, " +
                      "using Equalizer APO and HeSuVi.\n\n" +
                      "It is installed for your Windows user only, so no administrator rights are needed.";
        if (prev.Dir != null)
            body += "\n\nAn earlier version" + (string.IsNullOrEmpty(prev.Version) ? "" : " (" + prev.Version + ")") +
                    " is installed. Setup will update it in place and keep your settings.";
        Text_(p, body, 20, 88, 350, 190);
        Text_(p, "Click Next to continue, or Cancel to exit Setup.", 20, 300, 350, 20);
    }

    void BuildLicense()
    {
        var p = pages[(int)P.License] = NewPage(false);
        Text_(p, "Please read the following license agreement. Press Page Down to see the rest.", 20, 10, 520, 18);
        var box = new TextBox { Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Vertical, Left = S(20), Top = S(32), Width = S(520), Height = S(176),
                                Text = Reflow(license), BackColor = Color.White };
        p.Controls.Add(box);
        accept = new RadioButton { Text = "I &accept the agreement", Left = S(20), Top = S(214), Width = S(400), Height = S(22) };
        decline = new RadioButton { Text = "I &do not accept the agreement", Left = S(20), Top = S(236), Width = S(400), Height = S(22), Checked = true };
        accept.CheckedChanged += (s, e) => UpdateButtons();
        p.Controls.Add(accept); p.Controls.Add(decline);
    }

    // LICENSE is hard-wrapped at ~80 columns: join each paragraph so the box can word-wrap it to its own width
    static string Reflow(string t)
    {
        var paras = System.Text.RegularExpressions.Regex.Split(t.Replace("\r\n", "\n").Trim(), @"\n\s*\n");
        for (int i = 0; i < paras.Length; i++) paras[i] = System.Text.RegularExpressions.Regex.Replace(paras[i].Trim(), @"\s*\n\s*", " ");
        return string.Join("\r\n\r\n", paras);
    }

    void BuildFolder()
    {
        var p = pages[(int)P.Folder] = NewPage(false);
        Text_(p, "Setup will install " + Setup.App + " into the following folder.", 20, 14, 520, 18);
        Text_(p, "To continue, click Next. To pick a different folder, click Browse.", 20, 40, 520, 18);
        dirBox = new TextBox { Left = S(20), Top = S(72), Width = S(420), Text = prev.Dir ?? Setup.DefaultDir };
        var browse = new Button { Text = "B&rowse...", Left = S(450), Top = S(70), Width = S(90), Height = S(26) };
        browse.Click += (s, e) => Browse();
        dirBox.TextChanged += (s, e) => UpdateSpace();
        p.Controls.Add(dirBox); p.Controls.Add(browse);
        folderNote = Text_(p, "", 20, 104, 520, 50); folderNote.ForeColor = SystemColors.GrayText;
        folderNote.Text = prev.Dir != null
            ? "This is where the earlier version is installed. Keep it to update in place (your settings stay)."
            : "Pick any folder you can write to, for example on another drive. Folders that need administrator rights (like Program Files) will not work.";
        spaceNeed = Text_(p, "", 20, 210, 520, 18);
        spaceFree = Text_(p, "", 20, 230, 520, 18);
        UpdateSpace();
    }

    void BuildOptions()
    {
        var p = pages[(int)P.Options] = NewPage(false);
        Text_(p, "Select the additional tasks you would like Setup to perform, then click Next.", 20, 14, 520, 18);
        var g1 = Text_(p, "Shortcuts:", 20, 46, 520, 18); g1.Font = fBold;
        cbDesktop = new CheckBox { Text = "Create a &desktop shortcut", Left = S(36), Top = S(68), Width = S(480), Height = S(22), Checked = prev.Desktop };
        cbStart = new CheckBox { Text = "Create a &Start menu shortcut", Left = S(36), Top = S(92), Width = S(480), Height = S(22), Checked = true };
        p.Controls.Add(cbDesktop); p.Controls.Add(cbStart);
        var n = Text_(p, "You can always start the app again from the install folder, or with Windows search if the Start menu shortcut is on.", 36, 124, 500, 36);
        n.ForeColor = SystemColors.GrayText;
    }

    void BuildReady()
    {
        var p = pages[(int)P.Ready] = NewPage(false);
        Text_(p, "Setup is ready to install " + Setup.App + ". Click Install to continue, or Back to change anything.", 20, 14, 520, 34);
        readyText = new TextBox { Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Vertical, Left = S(20), Top = S(52), Width = S(520), Height = S(200), BackColor = Color.White };
        p.Controls.Add(readyText);
    }

    void BuildInstalling()
    {
        var p = pages[(int)P.Installing] = NewPage(false);
        status = Text_(p, "Preparing...", 20, 20, 520, 18);
        bar = new ProgressBar { Left = S(20), Top = S(44), Width = S(520), Height = S(20), Minimum = 0, Maximum = 100 };
        p.Controls.Add(bar);
        detail = new TextBox { Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Vertical, Left = S(20), Top = S(78), Width = S(520), Height = S(170), BackColor = Color.White };
        p.Controls.Add(detail);
    }

    void BuildFinish()
    {
        var p = pages[(int)P.Finish] = NewPage(true);
        finTitle = Text_(p, "", 20, 18, 350, 60); finTitle.Font = fBig;
        finText = Text_(p, "", 20, 88, 350, 120);
        cbLaunch = new CheckBox { Text = "&Launch " + Setup.App + " now", Left = S(20), Top = S(214), Width = S(350), Height = S(22), Checked = true, BackColor = Color.White };
        p.Controls.Add(cbLaunch);
    }

    // ---- navigation ---------------------------------------------------------------------------------------------
    static readonly string[,] Titles = {
        { "", "" },
        { "License Agreement", "Please read the following important information before continuing." },
        { "Select Destination Location", "Where should " + Setup.App + " be installed?" },
        { "Select Additional Tasks", "Which additional tasks should be performed?" },
        { "Ready to Install", "Setup is ready to begin installing " + Setup.App + "." },
        { "Installing", "Please wait while Setup installs " + Setup.App + " on your computer." },
        { "", "" } };

    void Show(P to)
    {
        page = to;
        for (int i = 0; i < pages.Length; i++) pages[i].Visible = i == (int)to;
        bool side = to == P.Welcome || to == P.Finish;
        banner.Visible = side; header.Visible = !side; ((Control)header.Tag).Visible = !side;
        hTitle.Text = Titles[(int)to, 0]; hSub.Text = Titles[(int)to, 1];
        if (to == P.Ready) readyText.Text = Summary();
        UpdateButtons();
        if (to == P.Installing) StartInstall();
        if (to == P.Finish) next.Focus();
    }

    void UpdateButtons()
    {
        back.Visible = page != P.Finish;
        back.Enabled = page != P.Welcome && page != P.Installing;
        next.Text = page == P.Ready ? "&Install" : page == P.Finish ? "&Finish" : "&Next >";
        next.Enabled = page != P.Installing && (page != P.License || accept.Checked);
        cancel.Enabled = page != P.Installing && page != P.Finish;
        cancel.Visible = page != P.Finish;
    }

    void Go(int d)
    {
        if (page == P.Finish) { Finish(); return; }
        if (d > 0 && page == P.Folder && !CheckFolder()) return;
        Show((P)((int)page + d));
    }

    string Dir { get { return dirBox.Text.Trim().TrimEnd('\\'); } }

    void Browse()
    {
        using (var f = new FolderBrowserDialog { Description = "Choose where to install " + Setup.App + ". A \"" + Setup.App + "\" folder is created inside it.", ShowNewFolderButton = true })
        {
            string cur = Dir;
            while (cur.Length > 0 && !Directory.Exists(cur)) cur = Path.GetDirectoryName(cur) ?? "";
            if (cur.Length > 0) f.SelectedPath = cur;
            if (f.ShowDialog(this) != DialogResult.OK) return;
            string d = f.SelectedPath.TrimEnd('\\');
            // keep the app in its own folder so uninstall never touches anything else
            if (!Path.GetFileName(d).Equals(Setup.App, StringComparison.OrdinalIgnoreCase)) d = Path.Combine(d, Setup.App);
            dirBox.Text = d;
        }
    }

    void UpdateSpace()
    {
        spaceNeed.Text = "At least " + Mb(needBytes) + " of free disk space is required.";
        try { spaceFree.Text = "Free space on " + Path.GetPathRoot(Path.GetFullPath(Dir)) + ": " + Mb(new DriveInfo(Path.GetPathRoot(Path.GetFullPath(Dir))).AvailableFreeSpace) + "."; }
        catch { spaceFree.Text = ""; }
    }

    static string Mb(long b) { return b >= 1L << 30 ? (b / (double)(1L << 30)).ToString("0.0") + " GB" : (b / (double)(1 << 20)).ToString("0.0") + " MB"; }

    bool Warn(string msg) { MessageBox.Show(this, msg, Text, MessageBoxButtons.OK, MessageBoxIcon.Warning); return false; }

    bool CheckFolder()
    {
        string d = Dir;
        if (d.Length == 0 || !Path.IsPathRooted(d) || d.IndexOfAny(Path.GetInvalidPathChars()) >= 0 || d.StartsWith("\\\\"))
            return Warn("Please enter a full folder path on a local drive, for example " + Setup.DefaultDir + ".");
        try { d = Path.GetFullPath(d).TrimEnd('\\'); } catch { return Warn("That folder path is not valid."); }
        if (Path.GetPathRoot(d).TrimEnd('\\') == d) return Warn("Please pick a folder, not the root of a drive.");
        try { var di = new DriveInfo(Path.GetPathRoot(d)); if (di.AvailableFreeSpace < needBytes + (50L << 20)) return Warn("There is not enough free space on " + di.Name + "."); } catch { }
        // non-empty folder that is not an earlier install: confirm (uninstall removes the whole folder)
        if (Directory.Exists(d) && !File.Exists(Path.Combine(d, Setup.Exe)) && Directory.GetFileSystemEntries(d).Length > 0)
        {
            if (MessageBox.Show(this, "The folder\n\n" + d + "\n\nalready contains other files. Uninstalling later removes this whole folder.\n\nInstall into a new \"" + Setup.App + "\" folder inside it instead?",
                                Text, MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return false;
            d = Path.Combine(d, Setup.App);
        }
        // no admin: make sure we can write there
        bool made = !Directory.Exists(d);
        try
        {
            Directory.CreateDirectory(d);
            string t = Path.Combine(d, ".setup-write-test");
            File.WriteAllText(t, "ok"); File.Delete(t);
            if (made) Directory.Delete(d);
        }
        catch
        {
            return Warn("Setup cannot write to\n\n" + d + "\n\nwithout administrator rights. Please pick a folder inside your user profile or on another drive.");
        }
        dirBox.Text = d;
        return true;
    }

    string Summary()
    {
        var sb = new StringBuilder();
        sb.Append(prev.Dir != null && prev.Dir.Equals(Dir, StringComparison.OrdinalIgnoreCase) ? "Update in place (settings are kept):" : "Destination location:").Append("\r\n      ").Append(Dir).Append("\r\n\r\n");
        sb.Append("Additional tasks:\r\n");
        sb.Append("      ").Append(cbDesktop.Checked ? "Create a desktop shortcut" : "No desktop shortcut").Append("\r\n");
        sb.Append("      ").Append(cbStart.Checked ? "Create a Start menu shortcut" : "No Start menu shortcut").Append("\r\n\r\n");
        sb.Append("Install for:\r\n      ").Append(Environment.UserName).Append(" only (no administrator rights needed)\r\n\r\n");
        sb.Append("Disk space needed:\r\n      ").Append(Mb(needBytes));
        if (prev.Dir != null && !prev.Dir.Equals(Dir, StringComparison.OrdinalIgnoreCase))
            sb.Append("\r\n\r\nNote: the earlier install in ").Append(prev.Dir).Append(" is left where it is. Its Apps & features entry will point to the new folder.");
        return sb.ToString();
    }

    void StartInstall()
    {
        var o = new Setup.Options { Dir = Dir, Desktop = cbDesktop.Checked, StartMenu = cbStart.Checked, Launch = false };
        new Thread(() =>
        {
            string err = null;
            try
            {
                string last = null;
                Setup.Install(zip, o, (pct, msg) => BeginInvoke((Action)(() =>
                {
                    bar.Value = Math.Max(0, Math.Min(100, pct));
                    status.Text = msg.Length > 90 ? msg.Substring(0, 87) + "..." : msg;
                    if (msg != last) { detail.AppendText(msg + "\r\n"); last = msg; }
                })));
            }
            catch (Exception ex) { err = ex.Message; }
            BeginInvoke((Action)(() => Done(err)));
        }) { IsBackground = true }.Start();
    }

    void Done(string err)
    {
        installed = err == null;
        ExitCode = installed ? 0 : 1;
        if (installed)
        {
            finTitle.Text = "Completing the " + Setup.App + " Setup Wizard";
            finText.Text = "Setup has finished installing " + Setup.App + " on your computer." +
                           (cbDesktop.Checked ? " You can start it from the desktop shortcut" + (cbStart.Checked ? " or the Start menu." : ".") :
                            cbStart.Checked ? " You can start it from the Start menu." : "") +
                           "\n\nOn first start, use Install everything in the app to set up Equalizer APO and HeSuVi.\n\nClick Finish to exit Setup.";
            cbLaunch.Visible = true;
        }
        else
        {
            finTitle.Text = "Setup was not completed";
            finText.Text = "Something went wrong:\n\n" + err + "\n\nClose " + Setup.App + " if it is open and run Setup again.";
            cbLaunch.Visible = false; cbLaunch.Checked = false;
        }
        Show(P.Finish);
    }

    void Finish() { Close(); }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        if (page == P.Installing) { e.Cancel = true; return; }
        if (page != P.Finish && e.CloseReason == CloseReason.UserClosing &&
            MessageBox.Show(this, "Setup is not complete. If you exit now, " + Setup.App + " will not be installed.\n\nExit Setup?",
                            Text, MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes)
        { e.Cancel = true; return; }
        // Finish button or the window's X on the last page: start the app if the box is ticked (on by default)
        if (page == P.Finish && installed && cbLaunch.Checked && !launched) { launched = true; Setup.LaunchApp(Dir); }
        base.OnFormClosing(e);
    }
}
