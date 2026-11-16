// The Windows launcher of INSTAT Explorer. It is compiled by packaging/build_release.py with the csc.exe that comes with .NET Framework 4
// (so nothing but Windows is needed to build it) and has two jobs:
//
//   * Portable: if a folder "python" lies next to the .exe, run the program from there.
//   * Stand-alone: otherwise unpack the zip that is embedded in the .exe (an embeddable Python with pandas, numpy, xlrd and the program),
//     once, into %LOCALAPPDATA%\Programs\INSTAT-Explorer\<version>, and run it from there. A newer version removes the older ones.
//
// What follows on the command line is passed on: "INSTAT-Explorer.exe serve --share" runs "python -m instatkit serve --share".
// INSTAT_APP_DIR chooses another place to unpack to (keep it short: Windows refuses paths of more than 260 characters).
// The messages are in Albanian when Windows is.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;

static class Launcher
{
    [DllImport("kernel32.dll")]
    static extern uint GetConsoleProcessList(uint[] processList, uint processCount);

    static bool Albanian { get { return CultureInfo.CurrentUICulture.TwoLetterISOLanguageName == "sq"; } }
    static string T(string english, string albanian) { return Albanian ? albanian : english; }

    static int Main(string[] args)
    {
        try { Console.OutputEncoding = new UTF8Encoding(false); } catch (IOException) { }
        string exeDir = AppDomain.CurrentDomain.BaseDirectory;
        string portable = Path.Combine(exeDir, "python", "python.exe");
        string python, workDir;
        var environment = new Dictionary<string, string>();
        try
        {
            if (File.Exists(portable))
            {
                python = portable;
                workDir = exeDir;
                if (Environment.GetEnvironmentVariable("INSTAT_DATA_DIR") == null)
                    environment["INSTAT_DATA_DIR"] = Path.Combine(exeDir, "data");  // the whole folder can be copied to a USB stick
            }
            else
            {
                string version = Version();
                string home = Environment.GetEnvironmentVariable("INSTAT_APP_DIR");
                string root = string.IsNullOrEmpty(home)
                    ? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "INSTAT-Explorer")
                    : home;
                workDir = Path.Combine(root, version);
                python = Path.Combine(workDir, "python", "python.exe");
                if (!File.Exists(Path.Combine(workDir, "unpacked.txt")) || !File.Exists(python))
                {
                    if (Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip") == null)
                        return Fail(T("The program files were not found: " + portable,
                                      "Skedarët e programit nuk u gjetën: " + portable) + "\n " +
                                    T("Unzip the whole download first, then open this file from the new folder.",
                                      "Shpaketo më parë gjithë zip-in dhe pastaj hape këtë skedar nga dosja e re."));
                    using (var mutex = new Mutex(false, @"Local\INSTAT-Explorer-" + version))
                    {
                        mutex.WaitOne();  // a second start while the first one is unpacking waits for it
                        try { if (!File.Exists(Path.Combine(workDir, "unpacked.txt"))) Unpack(workDir, version); }
                        finally { mutex.ReleaseMutex(); }
                    }
                }
                RemoveOlder(root, version);
            }
        }
        catch (Exception ex)
        {
            return Fail(T("INSTAT Explorer could not be prepared: ", "INSTAT Explorer nuk u përgatit dot: ") + ex.Message);
        }

        var start = new ProcessStartInfo(python, "-m instatkit " + (args.Length == 0 ? "serve" : Join(args)))
        {
            UseShellExecute = false,
            WorkingDirectory = workDir
        };
        foreach (var pair in environment) start.EnvironmentVariables[pair.Key] = pair.Value;
        try
        {
            using (var child = Process.Start(start))
            {
                child.WaitForExit();
                return child.ExitCode;
            }
        }
        catch (Exception ex)
        {
            return Fail(T("The program could not be started: ", "Programi nuk u nis dot: ") + ex.Message);
        }
    }

    static string Version()
    {
        Version v = Assembly.GetExecutingAssembly().GetName().Version;
        return v.Major + "." + v.Minor + "." + v.Build;
    }

    static void Unpack(string target, string version)
    {
        string part = target + ".part";
        if (Directory.Exists(part)) Directory.Delete(part, true);
        if (Directory.Exists(target)) Directory.Delete(target, true);  // an unpacking that was interrupted
        Directory.CreateDirectory(part);
        Console.WriteLine();
        Console.WriteLine(" " + string.Format(T("First start of INSTAT Explorer {0}: unpacking the program (once, about a minute).",
                                                "Nisja e parë e INSTAT Explorer {0}: po shpaketohet programi (një herë, rreth një minutë)."), version));
        string full = Path.GetFullPath(part) + Path.DirectorySeparatorChar;
        using (Stream payload = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip"))
        using (var zip = new ZipArchive(payload, ZipArchiveMode.Read))
        {
            long total = 0, done = 0;
            foreach (var e in zip.Entries) total += e.Length;
            int shown = -1;
            foreach (var e in zip.Entries)
            {
                string path = Path.GetFullPath(Path.Combine(part, e.FullName.Replace('/', Path.DirectorySeparatorChar)));
                if (!path.StartsWith(full, StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("Unexpected path in the payload: " + e.FullName);
                if (e.FullName.EndsWith("/")) { Directory.CreateDirectory(path); continue; }
                Directory.CreateDirectory(Path.GetDirectoryName(path));
                using (Stream input = e.Open())
                using (FileStream output = File.Create(path))
                    input.CopyTo(output);
                done += e.Length;
                int percent = total == 0 ? 100 : (int)(done * 100 / total);
                if (percent != shown)
                {
                    shown = percent;
                    Console.Write("\r " + string.Format(T("Unpacking... {0}%", "Po shpaketohet... {0}%"), percent));
                }
            }
        }
        Console.WriteLine();
        Directory.Move(part, target);
        File.WriteAllText(Path.Combine(target, "unpacked.txt"), version);
    }

    static void RemoveOlder(string root, string version)
    {
        if (!Directory.Exists(root)) return;
        foreach (string dir in Directory.GetDirectories(root))
        {
            string name = Path.GetFileName(dir);
            if (name != version && Regex.IsMatch(name, @"^\d+\.\d+\.\d+$"))
            {
                try { Directory.Delete(dir, true); } catch (Exception) { }  // still in use: leave it for next time
            }
        }
    }

    static string Join(string[] args)
    {
        var parts = new List<string>();
        foreach (string a in args) parts.Add(a.IndexOfAny(new[] { ' ', '\t', '"' }) < 0 ? a : "\"" + a.Replace("\"", "\\\"") + "\"");
        return string.Join(" ", parts.ToArray());
    }

    // Say what went wrong. Started by a double-click the window would close at once, so wait for Enter then.
    static int Fail(string message)
    {
        Console.Error.WriteLine();
        Console.Error.WriteLine(" " + message);
        uint[] list = new uint[2];
        bool ownWindow = false;
        try { ownWindow = GetConsoleProcessList(list, 2) <= 1; } catch (Exception) { }
        if (ownWindow)
        {
            Console.Error.WriteLine();
            Console.Error.Write(T(" Press Enter to close. ", " Shtyp Enter për ta mbyllur. "));
            try { Console.ReadLine(); } catch (Exception) { }
        }
        return 1;
    }
}
