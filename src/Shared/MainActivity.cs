using System.Reflection;
using System.Runtime.CompilerServices;
using Android.App;
using Android.OS;
using Google.Common.Util.Concurrent;

namespace Repro;

[Activity(Name = "com.example.keepaliverepro.MainActivity", MainLauncher = true, Exported = true)]
public class MainActivity : Activity
{
    protected override void OnCreate(Bundle? savedInstanceState)
    {
        base.OnCreate(savedInstanceState);

        var scenario = Intent?.GetStringExtra("scenario") ?? "deterministic";
        var useKeepAliveWorkaround = Intent?.GetStringExtra("code") == "keepalive";
        var seconds = Intent?.GetIntExtra("seconds", 45) ?? 45;

        // The main thread must stay free: the scenarios block for minutes and would trigger an ANR
        new Thread(() => RunScenario(scenario, useKeepAliveWorkaround, seconds)) { IsBackground = false }.Start();
    }

    void RunScenario(string scenario, bool useKeepAliveWorkaround, int seconds)
    {
        var app = PackageName?.Split('.').LastOrDefault() ?? "unknown";
        var runtime = typeof(MainActivity).Assembly.GetCustomAttributes<AssemblyMetadataAttribute>().FirstOrDefault(a => a.Key == "ReproRuntime")?.Value ?? "unknown";

        try
        {
            LogEnvironment(app, runtime);

            if (scenario == "stress")
            {
                StressCheck.Run(app, runtime, useKeepAliveWorkaround, seconds);
            }
            else
            {
                DeterministicCheck.Run(app, runtime, useKeepAliveWorkaround);
            }
        }
        catch (Exception e)
        {
            var inner = e.GetBaseException();
            Log.Line("ERROR", ("app", app), ("runtime", runtime), ("exception", e.GetType().FullName), ("inner", inner.GetType().FullName), ("message", inner.Message));
            Android.Util.Log.Error(Log.Tag, e.ToString());
        }

        Log.Line("DONE", ("app", app), ("runtime", runtime), ("scenario", scenario), ("code", useKeepAliveWorkaround ? "keepalive" : "plain"));
        RunOnUiThread(FinishAndRemoveTask);
    }

    // Mono.Runtime does not exist in the .NET 10 Mono CoreLib, so the loaded native runtime library is the reliable signal
    static string DetectRuntime()
    {
        if (!RuntimeFeature.IsDynamicCodeSupported)
        {
            return "nativeaot";
        }

        var maps = File.ReadAllText("/proc/self/maps");
        if (maps.Contains("libmonosgen-2.0.so", StringComparison.Ordinal))
        {
            return "mono";
        }

        return maps.Contains("libcoreclr.so", StringComparison.Ordinal) ? "coreclr" : "unknown";
    }

    static void LogEnvironment(string app, string runtime)
    {
        var assembly = typeof(IListenableFuture).Assembly;
        var guavaAssembly = typeof(Google.Common.Collect.ImmutableList).Assembly;
        var detected = DetectRuntime();

        Log.Line("ENV", ("app", app), ("runtime", runtime), ("detected", detected), ("framework", System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription),
            ("api", (int)Build.VERSION.SdkInt), ("abi", Build.SupportedAbis?.FirstOrDefault() ?? ""),
            ("listenableFutureAssembly", assembly.GetName().Name), ("listenableFutureVersion", assembly.GetName().Version),
            ("guavaAssembly", guavaAssembly.GetName().Name), ("guavaVersion", guavaAssembly.GetName().Version),
            ("listenableFutureInformationalVersion", assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion));
    }
}
