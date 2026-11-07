// "Dolby Access Custom.exe": tiny portable launcher for gui\main.py.
// Built with the C# compiler that ships with Windows (.NET Framework 4.x), see build.cmd. No install, no registry.
// Python is taken from .\runtime\ (portable copy inside this folder) first, then from PATH.
using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("Dolby Access Custom")]
[assembly: System.Reflection.AssemblyProduct("Dolby Access Custom")]
[assembly: System.Reflection.AssemblyVersion("1.0.0.0")]

static class Launcher
{
    const string Title = "Dolby Access Custom";

    static string FindOnPath(string exe)
    {
        foreach (var dir in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(';'))
        {
            try
            {
                var p = Path.Combine(dir.Trim().Trim('"'), exe);
                if (dir.Trim().Length > 0 && File.Exists(p) && !p.ToLower().Contains("windowsapps")) return p;
            }
            catch (ArgumentException) { }
        }
        return null;
    }

    [STAThread]
    static int Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
        string script = Path.Combine(root, "gui", "main.py");
        if (!File.Exists(script))
        {
            MessageBox.Show("gui\\main.py was not found next to the exe.\nKeep the exe inside the Dolby Access Custom folder.", Title,
                            MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }

        string py = Path.Combine(root, "runtime", "pythonw.exe");
        if (!File.Exists(py)) py = FindOnPath("pythonw.exe") ?? FindOnPath("pyw.exe");
        if (py == null)
        {
            MessageBox.Show("Python was not found.\n\nThe runtime\\ folder (bundled Python) is missing and this PC has no Python installed.\n" +
                            "Run launcher\\make-runtime.ps1 or copy the whole Dolby Access Custom folder again.", Title,
                            MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }

        var psi = new ProcessStartInfo(py, "\"" + script + "\" " + string.Join(" ", args))
        {
            WorkingDirectory = root,
            UseShellExecute = false,
        };
        psi.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"] = "1";   // keep the synced folder free of __pycache__ churn
        psi.EnvironmentVariables["PYTHONUTF8"] = "1";
        Process p;
        try { p = Process.Start(psi); }
        catch (Exception ex)
        {
            MessageBox.Show("Could not start Python:\n" + py + "\n\n" + ex.Message, Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }

        // surface a crash during start-up (main.py writes its traceback to gui.log)
        if (p.WaitForExit(8000) && p.ExitCode != 0)
        {
            string log = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "DolbyAccessCustom", "gui.log");
            string tail = "";
            try { var t = File.ReadAllText(log); tail = t.Length > 1500 ? t.Substring(t.Length - 1500) : t; } catch (IOException) { }
            MessageBox.Show("The app stopped during start-up (code " + p.ExitCode + ").\n\n" + tail, Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
            return p.ExitCode;
        }
        return 0;
    }
}
