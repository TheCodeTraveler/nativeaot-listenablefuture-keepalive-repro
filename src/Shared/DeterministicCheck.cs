using System.Runtime.CompilerServices;
using Google.Common.Util.Concurrent;

namespace Repro;

enum Outcome { Kept, Collected, HandleReplaced, Invalid }

static class DeterministicCheck
{
    const int MinimumWarmUpCalls = 200;
    static readonly TimeSpan MinimumWarmUpDuration = TimeSpan.FromSeconds(3);
    const int MeasuredIterations = 5;

    public static void Run(string app, string runtime, bool useKeepAliveWorkaround)
    {
        var code = useKeepAliveWorkaround ? "keepalive" : "plain";

        // CoreCLR's Tier-0 code keeps every local and `this` alive, which would hide the bug until the invoker tiers up.
        // Time-based so the invoker has time to tier up in the background, like in the long stress run.
        var warmUpTimer = System.Diagnostics.Stopwatch.StartNew();
        for (var i = 0; i < MinimumWarmUpCalls || warmUpTimer.Elapsed < MinimumWarmUpDuration; i++)
        {
            _ = Measure(new GarbageCollectingExecutor(), i, useKeepAliveWorkaround);
        }

        Thread.Sleep(TimeSpan.FromSeconds(1));

        int kept = 0, collected = 0, replaced = 0, invalid = 0, controlsCollected = 0;
        for (var iteration = 1; iteration <= MeasuredIterations; iteration++)
        {
            var executor = new GarbageCollectingExecutor { CollectGarbage = true };
            var controlReference = CreateUnreferencedPeer(iteration);
            var (futureReference, originalHandle, peerType) = Measure(executor, iteration, useKeepAliveWorkaround);

            var outcome = Classify(executor, futureReference, originalHandle, peerType);
            switch (outcome)
            {
                case Outcome.Kept: kept++; break;
                case Outcome.Collected: collected++; break;
                case Outcome.HandleReplaced: replaced++; break;
                default: invalid++; break;
            }

            var controlCollected = !controlReference.TryGetTarget(out _);
            if (controlCollected)
            {
                controlsCollected++;
            }

            Log.Line("RESULT", ("app", app), ("runtime", runtime), ("code", code), ("iteration", iteration), ("outcome", outcome.ToString().ToLowerInvariant()), ("controlCollected", controlCollected),
                ("executedInsideAddListener", executor.WasExecutedWhileAddingListener), ("peerType", peerType));
        }

        var verdict = invalid > 0 ? "INVALID" : kept == MeasuredIterations ? "SAFE" : "BUG";
        Log.Line("SUMMARY", ("app", app), ("runtime", runtime), ("code", code), ("iterations", MeasuredIterations),
            ("kept", kept), ("collected", collected), ("replaced", replaced), ("invalid", invalid), ("controlsCollected", controlsCollected), ("verdict", verdict));
    }

    // Positive control: proves the GC rounds in the executor can collect an unreferenced peer on this runtime
    [MethodImpl(MethodImplOptions.NoInlining | MethodImplOptions.AggressiveOptimization)]
    static WeakReference<Java.Lang.Object> CreateUnreferencedPeer(int value) =>
        new(Java.Lang.Integer.ValueOf(value));

    static Outcome Classify(GarbageCollectingExecutor executor, WeakReference<IListenableFuture> futureReference, nint originalHandle, string peerType)
    {
        if (!executor.WasExecutedWhileAddingListener || !peerType.EndsWith("IListenableFutureInvoker", StringComparison.Ordinal))
        {
            return Outcome.Invalid;
        }

        if (!futureReference.TryGetTarget(out var future))
        {
            return Outcome.Collected;
        }

        return future.Handle == originalHandle ? Outcome.Kept : Outcome.HandleReplaced;
    }

    // NoInlining keeps the future unreferenced by the caller; AggressiveOptimization keeps this method out of Tier-0
    [MethodImpl(MethodImplOptions.NoInlining | MethodImplOptions.AggressiveOptimization)]
    static (WeakReference<IListenableFuture> FutureReference, nint OriginalHandle, string PeerType) Measure(GarbageCollectingExecutor executor, int value, bool useKeepAliveWorkaround) =>
        useKeepAliveWorkaround ? MeasureWithWorkaround(executor, value) : MeasurePlain(executor, value);

    [MethodImpl(MethodImplOptions.NoInlining | MethodImplOptions.AggressiveOptimization)]
    static (WeakReference<IListenableFuture>, nint, string) MeasurePlain(GarbageCollectingExecutor executor, int value)
    {
        var future = GuavaFutures.ImmediateFuture(Java.Lang.Integer.ValueOf(value));
        var futureReference = new WeakReference<IListenableFuture>(future);
        var originalHandle = future.Handle;
        var peerType = future.GetType().FullName ?? "";

        var runnable = new Java.Lang.Runnable(static () => { });

        executor.IsAddingListener = true;
        future.AddListener(runnable, executor);
        executor.IsAddingListener = false;

        return (futureReference, originalHandle, peerType);
    }

    [MethodImpl(MethodImplOptions.NoInlining | MethodImplOptions.AggressiveOptimization)]
    static (WeakReference<IListenableFuture>, nint, string) MeasureWithWorkaround(GarbageCollectingExecutor executor, int value)
    {
        var future = GuavaFutures.ImmediateFuture(Java.Lang.Integer.ValueOf(value));
        var futureReference = new WeakReference<IListenableFuture>(future);
        var originalHandle = future.Handle;
        var peerType = future.GetType().FullName ?? "";

        var runnable = new Java.Lang.Runnable(static () => { });

        executor.IsAddingListener = true;
        future.AddListenerKeepingArgumentsAlive(runnable, executor);
        executor.IsAddingListener = false;

        return (futureReference, originalHandle, peerType);
    }
}
