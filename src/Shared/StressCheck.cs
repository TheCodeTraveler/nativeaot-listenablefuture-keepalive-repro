using Google.Common.Util.Concurrent;

namespace Repro;

// Report only: a native crash here cannot be asserted in-process, so the CI script reads the crash buffer instead
static class StressCheck
{
    public static void Run(string app, string runtime, bool useKeepAliveWorkaround, int seconds)
    {
        var code = useKeepAliveWorkaround ? "keepalive" : "plain";
        var deadline = DateTime.UtcNow.AddSeconds(seconds);
        long calls = 0, npeRunnable = 0, npeExecutor = 0, otherErrors = 0;

        var collector = new Thread(() =>
        {
            while (DateTime.UtcNow < deadline)
            {
                GC.Collect();
                Thread.Sleep(2);
            }
        }) { IsBackground = true };
        collector.Start();

        var nextProgress = DateTime.UtcNow.AddSeconds(10);
        var executor = GuavaFutures.DirectExecutor;
        while (DateTime.UtcNow < deadline)
        {
            try
            {
                var future = GuavaFutures.ImmediateFuture(Java.Lang.Integer.ValueOf((int)calls));
                if (useKeepAliveWorkaround)
                {
                    future.AddListenerOnExecutor(executor, static () => { });
                }
                else
                {
                    future.AddListener(new Java.Lang.Runnable(static () => { }), executor);
                }
            }
            catch (Java.Lang.NullPointerException e)
            {
                if (e.Message?.Contains("Runnable", StringComparison.Ordinal) is true)
                {
                    npeRunnable++;
                }
                else if (e.Message?.Contains("Executor", StringComparison.Ordinal) is true)
                {
                    npeExecutor++;
                }
                else
                {
                    otherErrors++;
                }
            }
            catch (Java.Lang.Throwable)
            {
                otherErrors++;
            }

            calls++;

            if (DateTime.UtcNow >= nextProgress)
            {
                Log.Line("STRESS_PROGRESS", ("app", app), ("code", code), ("calls", calls), ("npeRunnable", npeRunnable), ("npeExecutor", npeExecutor), ("otherErrors", otherErrors));
                nextProgress = DateTime.UtcNow.AddSeconds(10);
            }
        }

        collector.Join();
        Log.Line("STRESS", ("app", app), ("runtime", runtime), ("code", code), ("seconds", seconds), ("calls", calls),
            ("npeRunnable", npeRunnable), ("npeExecutor", npeExecutor), ("otherErrors", otherErrors));
    }
}
