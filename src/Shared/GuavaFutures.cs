using Android.Runtime;
using Google.Common.Util.Concurrent;
using Java.Util.Concurrent;

namespace Repro;

// Futures and MoreExecutors are reached through JNI so the repro depends on nothing but the IListenableFuture binding under test
static unsafe class GuavaFutures
{
    static readonly nint futuresClass = NewGlobalClassRef("com/google/common/util/concurrent/Futures");
    static readonly nint immediateFutureMethod = JNIEnv.GetStaticMethodID(futuresClass, "immediateFuture", "(Ljava/lang/Object;)Lcom/google/common/util/concurrent/ListenableFuture;");
    static readonly nint moreExecutorsClass = NewGlobalClassRef("com/google/common/util/concurrent/MoreExecutors");
    static readonly nint directExecutorMethod = JNIEnv.GetStaticMethodID(moreExecutorsClass, "directExecutor", "()Ljava/util/concurrent/Executor;");

    public static IExecutor DirectExecutor { get; } = CreateDirectExecutor();

    // immediateFuture(null) returns a singleton that Java keeps alive forever, so a fresh value is what makes every future collectible
    public static IListenableFuture ImmediateFuture(Java.Lang.Object value)
    {
        var argument = stackalloc JValue[1];
        argument[0] = new JValue(value);

        var handle = JNIEnv.CallStaticObjectMethod(futuresClass, immediateFutureMethod, argument);

        // The value's handle is read above, so the managed peer has to outlive the call
        GC.KeepAlive(value);

        return Java.Lang.Object.GetObject<IListenableFuture>(handle, JniHandleOwnership.TransferLocalRef)
            ?? throw new InvalidOperationException("Futures.immediateFuture returned null.");
    }

    static IExecutor CreateDirectExecutor()
    {
        var handle = JNIEnv.CallStaticObjectMethod(moreExecutorsClass, directExecutorMethod);
        return Java.Lang.Object.GetObject<IExecutor>(handle, JniHandleOwnership.TransferLocalRef)
            ?? throw new InvalidOperationException("MoreExecutors.directExecutor returned null.");
    }

    static nint NewGlobalClassRef(string name)
    {
        var local = JNIEnv.FindClass(name);
        var global = JNIEnv.NewGlobalRef(local);
        JNIEnv.DeleteLocalRef(local);
        return global;
    }
}
