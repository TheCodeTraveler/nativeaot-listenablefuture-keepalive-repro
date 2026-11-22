# NativeAOT ListenableFuture keep-alive repro

Repro for the upstream issue: _link added when filed_.

Every `Xamarin.Google.Guava` (33.8.0 included) depends on `Xamarin.Google.Guava.ListenableFuture` 9999.0.0, an unlisted 2022 binding. Its `IListenableFutureInvoker` passes `this.Handle` and the argument handles to JNI with no `GC.KeepAlive`. On a runtime with a precise GC (NativeAOT, CoreCLR), the GC bridge can collect the future, or swap its JNI reference, while Java is still inside `addListener`. That is a SIGSEGV in ART, or a null argument. `AndroidAddKeepAlives` does not fix it up (see [Why](#why)).

## What the app does

- Plain .NET for Android. No MAUI. Only `Xamarin.Google.Guava` 33.8.0.
- `Futures.immediateFuture` returns a completed future, so Guava runs the executor synchronously inside `addListener`.
- The executor forces garbage collections there, then the app checks the future's `WeakReference` and `Handle`.

## Run it

CI runs everything on an emulator: see the Actions tab, the job summary of the newest run, and `.github/workflows/repro.yml`.

Locally (builds only need the .NET 11 SDK and the Android workload):

```bash
dotnet workload install android
dotnet build src/Repro.Shipped -c Release -p:ReproRuntime=nativeaot -p:RuntimeIdentifier=android-x64
adb install -r src/Repro.Shipped/bin/Release/net11.0-android/android-x64/com.example.keepaliverepro.shipped-Signed.apk
adb logcat -c
adb shell am start -W -n com.example.keepaliverepro.shipped/com.example.keepaliverepro.MainActivity --es scenario deterministic --es code plain
adb logcat -d -s KeepAliveRepro
```

- `ReproRuntime`: `nativeaot`, `coreclr` or `mono`. Mono builds for `net10.0-android`, because .NET 11 Android removed Mono (NETSDK1242).
- Extras: `scenario` (`deterministic` or `stress`), `code` (`plain` or `keepalive`), `seconds` (stress only).
- Use `Repro.RebuiltBinding` and `com.example.keepaliverepro.rebuilt` for the fixed binding.
- Look for `SUMMARY ... verdict=BUG|SAFE`.

## Scenarios

- **Deterministic** (asserted). 200 warm-up calls, then 5 measured calls. Each is `kept`, `collected` (the peer was collected) or `handle-replaced` (the peer lives, but its JNI reference was replaced).
- **Stress** (reported only). One thread adds listeners in a loop while another calls `GC.Collect()`. A crash shows up as a missing `STRESS` line and a SIGSEGV in the crash buffer.
- **Code**:
  - `plain`: `future.AddListener(runnable, executor)`.
  - `keepalive`: the [workaround](#workaround).
- **Binding**:
  - `Repro.Shipped`: resolves ListenableFuture 9999.0.0.
  - `Repro.RebuiltBinding`: excludes 9999.0.0 and references `bindings/ListenableFuture.Rebuilt`, built with the current generator from the Maven jar (checked by SHA256, bound but not embedded). It is what android-libraries should publish.

## Expected and actual

Expected: every cell is `kept`.

Actual: see the table in the job summary of the confirming run (_run link added after CI_).

| Runtime | Binding | Code | Expected by this repro |
|---|---|---|---|
| NativeAOT | shipped 9999.0.0 | plain | BUG |
| NativeAOT | shipped 9999.0.0 | keepalive | SAFE |
| NativeAOT | rebuilt | plain, keepalive | SAFE |
| CoreCLR | shipped 9999.0.0 | plain | BUG (prediction) |
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

`AndroidAddKeepAlives` (on by default in Release) is meant to add these for old bindings, but it does not reach this one:

- **NativeAOT never runs it.** `PublishAot` selects the trimmable type map, which has no `_PostTrimmingPipeline` target. The build log has `AndroidAddKeepAlives=True` and no mention of the step.
- **The guard skips the assembly.** `AddKeepAlivesHelper` returns early for any assembly with an `android*` `TargetPlatform`, and 9999.0.0 is `Android31.0`. CoreCLR and Mono run the step, and the DLL stays unchanged.
- **Invokers and `this` are never covered.** Invoker methods have no `[Register]` attribute, which the step requires, and it only keeps parameters alive.

The build job proves this per cell: `inspect.json` lists the DLL that ILC or crossgen read, its hash, and the `GC.KeepAlive` count in `AddListener`. The summary also decompiles `GoogleGson` 2.13.1.1 for net8 and net10: the net8 generator emitted no keep-alives in interface invokers either.

Source of the step at tag 37.2.31: `src/Xamarin.Android.Build.Tasks/Linker/MonoDroid.Tuner/AddKeepAlivesHelper.cs` in `dotnet/android`.

## Workaround

Keep the future, the runnable and the executor alive after the call:

```csharp
public static void AddListenerOnExecutor(this IListenableFuture future, IExecutor? executor, Action listener)
{
    var runnable = new Java.Lang.Runnable(() => { try { listener(); } finally { GC.KeepAlive(future); } });
    future.AddListener(runnable, executor);
    GC.KeepAlive(future);
    GC.KeepAlive(runnable);
    GC.KeepAlive(executor);
}
```

## Fix

- **dotnet/android-libraries**: publish a jar-less ListenableFuture built with the current generator under a new version, point `Xamarin.Google.Guava` at it, and republish Guava. `Repro.RebuiltBinding` shows the shape works.
- **dotnet/android**: run the keep-alive step for every runtime, and cover interface invokers and `this`.

## Licensing

MIT. `listenablefuture-1.0.jar` (Apache-2.0) is downloaded from Maven Central at build time and is not committed.
