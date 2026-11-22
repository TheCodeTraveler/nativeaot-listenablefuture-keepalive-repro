# NativeAOT ListenableFuture keep-alive repro

[![Repro](https://github.com/TheCodeTraveler/nativeaot-listenablefuture-keepalive-repro/actions/workflows/repro.yml/badge.svg)](https://github.com/TheCodeTraveler/nativeaot-listenablefuture-keepalive-repro/actions/workflows/repro.yml)

Repro for [dotnet/android-libraries#1585](https://github.com/dotnet/android-libraries/issues/1585).

Every `Xamarin.Google.Guava` since 31.1.0.2 (May 2022), 33.8.0 included, depends on `Xamarin.Google.Guava.ListenableFuture` 9999.0.0, an unlisted 2022 binding. Its `IListenableFutureInvoker` passes `this.Handle` and the argument handles to JNI with no `GC.KeepAlive`. `AndroidAddKeepAlives` does not fix it up (see [Why](#why)).

On a runtime with a precise GC, a collection can hit two windows:

- **Between reading `Handle` and ART decoding it.** The handle dangles: a SIGSEGV for the receiver, or a `Runnable was null.` NullPointerException for an argument.
- **While Java is inside `addListener`.** The GC bridge collects the peer or swaps its JNI reference. This is what the deterministic check measures.

NativeAOT is observed. CoreCLR is measured and reported, not asserted.

## What the app does

- Plain .NET for Android. No MAUI. Only `Xamarin.Google.Guava` 33.8.0.
- `Futures.immediateFuture` returns a completed future, so Guava runs the executor synchronously inside `addListener`.
- The executor forces garbage collections there, then the app checks the future's `WeakReference` and `Handle`.

## Run it

CI runs everything on an emulator: see the Actions tab, the job summary of the newest run, and `.github/workflows/repro.yml`.

Locally (builds need the .NET 11 SDK, the Android workload, an Android SDK and JDK 21; `-t:InstallAndroidDependencies` can fetch the SDK and JDK):

```bash
dotnet workload install android
dotnet build src/Repro.Shipped -c Release -p:ReproRuntime=nativeaot -p:RuntimeIdentifier=android-x64
adb install -r src/Repro.Shipped/bin/Release/net11.0-android/android-x64/com.example.keepaliverepro.shipped-Signed.apk
adb logcat -c
adb shell am start -W -n com.example.keepaliverepro.shipped/com.example.keepaliverepro.MainActivity --es scenario deterministic --es code plain
adb logcat -d -s KeepAliveRepro   # once the DONE line appears (about 10 s)
```

- Delete `src/*/bin` and `obj` before switching `ReproRuntime`; a stale `obj` is reused by an incremental build.
- `android-x64` needs an x86_64 emulator; for an arm64 device or Apple Silicon emulator use `android-arm64` and its output folder (not run in CI).
- `ReproRuntime`: `nativeaot`, `coreclr` or `mono`. Mono builds for `net10.0-android`, because .NET 11 Android removed Mono (NETSDK1242).
- Extras: `scenario` (`deterministic` or `stress`), `code` (`plain` or `keepalive`), `seconds` (stress only).
- Use `Repro.RebuiltBinding` and `com.example.keepaliverepro.rebuilt` for the fixed binding.
- Look for `SUMMARY ... verdict=BUG|SAFE`.

## Scenarios

- **Deterministic** (asserted). At least 200 warm-up calls and 3 s, then 5 measured calls. Each is `kept`, `collected` (the peer was collected) or `handle-replaced` (the peer lives, but its JNI reference was replaced).
- **Stress** (reported only). One thread adds listeners in a loop while another calls `GC.Collect()`. A crash shows up as a missing `STRESS` line and a SIGSEGV in the crash buffer.
- **Valid calls only.** A call counts only if Guava ran the executor inside `addListener` and the peer is the binding's `IListenableFutureInvoker`. Otherwise the cell is `INVALID`.
- **Positive control.** Each measured call checks that the GC rounds collected an unreferenced peer. A SAFE cell with no collected control fails.
- **Code**:
  - `plain`: `future.AddListener(runnable, executor)`.
  - `keepalive`: the same call, followed by `GC.KeepAlive` of the future, the runnable and the executor (the [workaround](#workaround)). Both paths create the runnable the same way.
- **Binding**:
  - `Repro.Shipped`: resolves ListenableFuture 9999.0.0.
  - `Repro.RebuiltBinding`: replaces 9999.0.0 with `bindings/ListenableFuture.Rebuilt` (a `ProjectReference`), built with the current generator from the Maven jar (checked by SHA256, bound but not embedded). It is what android-libraries should publish.

## Expected and actual

Expected (correct behavior): every cell is `kept`.

Actual: see the table in the job summary of the confirming run ([run 45002779122](https://github.com/TheCodeTraveler/nativeaot-listenablefuture-keepalive-repro/actions/runs/45002779122)). A green run means every asserted cell matched (the NativeAOT BUG cell reproduced, and every SAFE cell kept its future while the controls were collected); a REPORT cell only has to be valid.

| Runtime | Binding | Code | Predicted (asserted by CI) |
|---|---|---|---|
| NativeAOT | shipped 9999.0.0 | plain | BUG (observed) |
| NativeAOT | shipped 9999.0.0 | keepalive | SAFE |
| NativeAOT | rebuilt | plain, keepalive | SAFE |
| CoreCLR | shipped 9999.0.0 | plain | REPORT (measured, not asserted) |
| CoreCLR | shipped 9999.0.0 | keepalive | SAFE |
| CoreCLR | rebuilt | plain, keepalive | SAFE |
| Mono | all | all | SAFE (control: Mono scans stacks conservatively) |

## Why

The 9999.0.0 invoker reads `this.Handle` and calls JNI, and nothing keeps `this` or the arguments alive afterwards:

```csharp
// 9999.0.0 (2022)
JNIEnv.CallVoidMethod(((Object)this).Handle, id_addListener_..., ptr);

// rebuilt with the current generator
try { /* ... */ InvokeAbstractVoidMethod("addListener...", (IJavaPeerable)this, ptr); }
finally { GC.KeepAlive(p0); GC.KeepAlive(p1); }
```

`InvokeAbstractVoidMethod` keeps `self` alive in its own `finally` (Java.Interop `JniPeerMembers.JniInstanceMethods`), so the excerpt needs no extra call for the receiver.

`AndroidAddKeepAlives` (on by default in Release) is meant to add these for old bindings, but it does not reach this one:

- **NativeAOT never runs it.** `PublishAot` selects the trimmable type map, which has no `_PostTrimmingPipeline` target. The build log has `AndroidAddKeepAlives=True` and no mention of the step.
- **The guard skips the assembly.** [`AddKeepAlivesHelper`](https://github.com/dotnet/android/blob/37.2.31/src/Xamarin.Android.Build.Tasks/Linker/MonoDroid.Tuner/AddKeepAlivesHelper.cs#L19) returns early for any assembly with an `android*` `TargetPlatform`, and 9999.0.0 is `Android31.0`. CoreCLR and Mono run the step, and the DLL stays unchanged.
- **Invokers and `this` are never covered.** Invoker methods have no `[Register]` attribute, which [the step requires](https://github.com/dotnet/android/blob/37.2.31/src/Xamarin.Android.Build.Tasks/Linker/MonoDroid.Tuner/AddKeepAlivesHelper.cs#L57). It [skips parameterless methods](https://github.com/dotnet/android/blob/37.2.31/src/Xamarin.Android.Build.Tasks/Linker/MonoDroid.Tuner/AddKeepAlivesHelper.cs#L54) and only keeps parameters alive.

The build job proves this per cell: `inspect.json` lists the DLL that ILC read (NativeAOT) or the R2R copy crossgen produced (CoreCLR), its hash, and the `GC.KeepAlive` count in `AddListener`. The summary also decompiles `GoogleGson` 2.13.1.1 for net8 and net10: the net8 generator emitted no keep-alives in interface invokers either.


## Workaround

Keep the future, the runnable and the executor alive after the call:

```csharp
public static void AddListenerKeepingArgumentsAlive(this IListenableFuture future, Java.Lang.IRunnable runnable, IExecutor? executor)
{
    future.AddListener(runnable, executor);
    GC.KeepAlive(future);
    GC.KeepAlive(runnable);
    GC.KeepAlive(executor);
}
```

If the listener calls `future.Get()`, also keep the future alive inside the listener.

## Fix

- **dotnet/android-libraries**: publish a jar-less ListenableFuture built with the current generator under a new version, point `Xamarin.Google.Guava` at it, and republish Guava. `Repro.RebuiltBinding` shows the shape works.
- **dotnet/android**: run the keep-alive step for every runtime, and cover interface invokers and `this`.

## Licensing

MIT. `listenablefuture-1.0.jar` (Apache-2.0) is downloaded from Maven Central at build time and is not committed.
