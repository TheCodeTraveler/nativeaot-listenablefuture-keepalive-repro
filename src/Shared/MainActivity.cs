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
            Log.Line("ERROR", ("app", app), ("runtime", runtime), ("exception", e.GetType().FullName), ("message", e.Message));
        }

        Log.Line("DONE", ("app", app), ("runtime", runtime));
        RunOnUiThread(FinishAndRemoveTask);
    }

    static void LogEnvironment(string app, string runtime)
    {
        var assembly = typeof(IListenableFuture).Assembly;
        var detected = !RuntimeFeature.IsDynamicCodeSupported ? "nativeaot" : Type.GetType("Mono.Runtime") is not null ? "mono" : "coreclr";

        Log.Line("ENV", ("app", app), ("runtime", runtime), ("detected", detected), ("framework", System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription),
            ("api", (int)Build.VERSION.SdkInt), ("abi", Build.SupportedAbis?.FirstOrDefault() ?? ""),
            ("listenableFutureAssembly", assembly.GetName().Name), ("listenableFutureVersion", assembly.GetName().Version),
            ("listenableFutureInformationalVersion", assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion));
    }
}
