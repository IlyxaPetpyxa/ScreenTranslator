// Tiny launcher: starts the bundled Python with src\main.py. Compiled by install.bat.
using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

static class Launcher
{
    [STAThread]
    static void Main()
    {
        string dir = AppDomain.CurrentDomain.BaseDirectory;
        string py = Path.Combine(dir, "python", "pythonw.exe");
        string main = Path.Combine(dir, "src", "main.py");

        if (!File.Exists(py))
        {
            MessageBox.Show("Python is not installed yet. Run install.bat first.\n\nСначала запустите install.bat.",
                            "Screen Translator");
            return;
        }

        var psi = new ProcessStartInfo(py, "\"" + main + "\"");
        psi.WorkingDirectory = dir;
        psi.UseShellExecute = false;
        Process.Start(psi);
    }
}
