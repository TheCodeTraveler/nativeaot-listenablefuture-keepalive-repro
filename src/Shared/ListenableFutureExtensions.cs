using Google.Common.Util.Concurrent;
using Java.Util.Concurrent;

namespace Repro;

static class ListenableFutureExtensions
{
    // The 2022 binding keeps neither the future nor its arguments alive during the JNI call, so the caller has to
    public static void AddListenerKeepingArgumentsAlive(this IListenableFuture future, Java.Lang.IRunnable runnable, IExecutor? executor)
    {
        future.AddListener(runnable, executor);

        GC.KeepAlive(future);
        GC.KeepAlive(runnable);
        GC.KeepAlive(executor);
    }
}
