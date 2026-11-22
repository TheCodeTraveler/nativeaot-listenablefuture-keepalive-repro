using Java.Util.Concurrent;

namespace Repro;

sealed class GarbageCollectingExecutor : Java.Lang.Object, IExecutor
{
    public bool CollectGarbage { get; set; }

    public bool IsAddingListener { get; set; }

    public bool WasExecutedWhileAddingListener { get; private set; }

    public void Execute(Java.Lang.IRunnable? command)
    {
        WasExecutedWhileAddingListener = IsAddingListener;

        if (CollectGarbage)
        {
            // The GC bridge swaps JNI references on its own thread after the GC returns, and a round takes ~30-60 ms on CI emulators
            for (var round = 0; round < 3; round++)
            {
                GC.Collect();
                GC.WaitForPendingFinalizers();
                Thread.Sleep(TimeSpan.FromMilliseconds(250));
            }
        }

        command?.Run();
    }
}
