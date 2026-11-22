"""Records which Xamarin.Google.Guava.ListenableFuture.dll an app resolved, compiled and shipped, and whether its AddListener keeps anything alive."""
import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import sys

TYPE_NAME = "Google.Common.Util.Concurrent.IListenableFutureInvoker"
DLL_NAME = "Xamarin.Google.Guava.ListenableFuture.dll"
KEEP_ALIVE_STEP_TARGETS = ["_PostTrimmingPipeline", "PostTrimmingPipeline", "_LinkAssembliesNoShrink"]


def sha256(path):
    with open(path, "rb") as file:
        return hashlib.sha256(file.read()).hexdigest()


def run_ilspy(dll, *arguments):
    environment = dict(os.environ, DOTNET_ROLL_FORWARD="Major")
    result = subprocess.run(["dotnet", "tool", "run", "ilspycmd", *arguments, dll], capture_output=True, text=True, env=environment)
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"ilspycmd failed for {dll}: {result.stderr[:500]}")
    return result.stdout


def add_listener_il(dll):
    il = run_ilspy(dll, "-il", "-t", TYPE_NAME)
    match = re.search(r"(?s)\n\s*[^\n]*instance void AddListener \(.*?end of method IListenableFutureInvoker::AddListener\n", il)
    if match:
        return match.group(0)
    raise RuntimeError(f"No AddListener method found in {dll}")


def describe_copy(path, nupkg_hash):
    il = add_listener_il(path)
    return {
        "path": path,
        "sha256": sha256(path),
        "identicalToNupkg": sha256(path) == nupkg_hash if nupkg_hash else None,
        "targetPlatform": "".join(re.findall(r"Android\d+\.\d+", open(path, "rb").read().decode("latin-1")))[:20] or None,
        "keepAliveCallsInAddListener": il.count("System.GC::KeepAlive"),
        "passesThisToInvokeAbstractVoidMethod": "InvokeAbstractVoidMethod" in il,
        "addListenerIl": il,
    }


def package_version(assets_path, package):
    with open(assets_path) as file:
        libraries = json.load(file)["libraries"]
    for key in libraries:
        if key.lower().startswith(package.lower() + "/"):
            return key.split("/", 1)[1]
    return None


def nupkg_dll(version):
    pattern = os.path.expanduser(f"~/.nuget/packages/xamarin.google.guava.listenablefuture/{version}/lib/*/{DLL_NAME}")
    matches = sorted(glob.glob(pattern), key=lambda path: "monoandroid" in path)
    return matches[0] if matches else None


def compiler_inputs(app_dir):
    inputs = []
    for rsp in glob.glob(os.path.join(app_dir, "obj", "**", "*.rsp"), recursive=True):
        with open(rsp) as file:
            for line in file:
                if DLL_NAME in line and not line.startswith("--"):
                    inputs.append({"rsp": os.path.relpath(rsp, app_dir), "line": line.strip()})
    return inputs


def keep_alive_step_report(diag_log):
    if not diag_log or not os.path.exists(diag_log):
        return {"available": False}
    counts = {name: 0 for name in KEEP_ALIVE_STEP_TARGETS}
    skipped = {name: 0 for name in KEEP_ALIVE_STEP_TARGETS}
    add_keep_alives = None
    with open(diag_log, errors="replace") as file:
        for line in file:
            for name in KEEP_ALIVE_STEP_TARGETS:
                if name in line:
                    counts[name] += 1
                    if "skipped" in line.lower():
                        skipped[name] += 1
            if add_keep_alives is None:
                match = re.search(r"AndroidAddKeepAlives\s*=\s*(\w+)", line)
                if match:
                    add_keep_alives = match.group(1)
    return {"available": True, "mentions": counts, "skippedMentions": skipped, "androidAddKeepAlives": add_keep_alives,
            "ran": any(counts[name] > skipped[name] for name in counts)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--app", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--diag-log")
    arguments = parser.parse_args()

    app_dir = f"src/Repro.{arguments.app}"
    assets = os.path.join(app_dir, "obj", "project.assets.json")
    resolved = package_version(assets, "Xamarin.Google.Guava.ListenableFuture")
    package_dll = nupkg_dll(resolved) if resolved else None
    package_hash = sha256(package_dll) if package_dll else None

    candidates = []
    if package_dll:
        candidates.append(package_dll)
    for root in ("obj", "bin"):
        candidates += glob.glob(os.path.join(app_dir, root, "**", DLL_NAME), recursive=True)
    if arguments.app == "RebuiltBinding":
        framework = "net10.0-android" if arguments.runtime == "mono" else "net11.0-android"
        candidates += glob.glob(os.path.join("bindings", "ListenableFuture.Rebuilt", "bin", "Release", framework, "**", DLL_NAME), recursive=True)
        candidates += glob.glob(os.path.join("bindings", "ListenableFuture.Rebuilt", "bin", "Release", framework, DLL_NAME))

    report = {
        "runtime": arguments.runtime,
        "app": arguments.app,
        "guavaVersion": package_version(assets, "Xamarin.Google.Guava"),
        "listenableFutureResolved": resolved,
        "excludedFromApp": arguments.app == "RebuiltBinding",
        "nupkgDll": package_dll,
        "compilerInputs": compiler_inputs(app_dir),
        "copies": [describe_copy(path, package_hash) for path in dict.fromkeys(candidates)],
        "keepAliveStep": keep_alive_step_report(arguments.diag_log),
    }

    os.makedirs(arguments.output, exist_ok=True)
    stem = f"{arguments.output}/{arguments.runtime}-{arguments.app}"
    with open(stem + "-inspect.json", "w") as file:
        json.dump({key: value for key, value in report.items()}, file, indent=2)
    with open(stem + "-il.txt", "w") as file:
        for copy in report["copies"]:
            file.write(f"=== {copy['path']}\nsha256={copy['sha256']} keepAlive={copy['keepAliveCallsInAddListener']}\n{copy['addListenerIl']}\n")

    failures = []
    shipped = arguments.app == "Shipped"
    for copy in report["copies"]:
        if shipped and copy["keepAliveCallsInAddListener"] != 0:
            failures.append(f"{copy['path']} has keep-alives")
        if not shipped and "Rebuilt" in copy["path"] and (copy["keepAliveCallsInAddListener"] < 2 or not copy["passesThisToInvokeAbstractVoidMethod"]):
            failures.append(f"{copy['path']} lacks keep-alives")
    if shipped and resolved != "9999.0.0":
        failures.append(f"resolved {resolved}, expected 9999.0.0")
    if not report["copies"]:
        failures.append("no copies found")
    print(json.dumps({"app": arguments.app, "resolved": resolved, "copies": [(c["path"], c["keepAliveCallsInAddListener"]) for c in report["copies"]], "failures": failures}, indent=1))
    return 1 if failures else 0


sys.exit(main())
