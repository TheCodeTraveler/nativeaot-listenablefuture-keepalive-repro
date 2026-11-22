using Google.Common.Util.Concurrent;
using Java.Util.Concurrent;

namespace Repro;

static class ListenableFutureExtensions
{
    // The workaround apps can use today: the 2022 binding keeps neither the future nor its arguments alive during the JNI call
    public static void AddListenerOnExecutor(this IListenableFuture future, IExecutor? executor, Action listener)
    {
        var runnable = new Java.Lang.Runnable(() =>
        {
            try
            {
                listener();
            }
            finally
            {
                GC.KeepAlive(future);
            }
        });

        future.AddListener(runnable, executor);

        GC.KeepAlive(future);
        GC.KeepAlive(runnable);
        GC.KeepAlive(executor);
    }
}
