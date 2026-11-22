"""Combines the per-runtime results into one job summary: the 12-cell table, the binding table and the decompiled invokers."""
import glob
import json
import os
import sys

root = sys.argv[1]
il_folder = sys.argv[2] if len(sys.argv) > 2 else None
out = []

cells = []
for path in sorted(glob.glob(f"{root}/*/results.json")):
    cells += json.load(open(path))["cells"]

out.append("## Deterministic check (5 iterations per cell; expected for every cell is what the table's Expected column says)\n")
out.append("| Runtime | Binding | Code | Expected | Observed | kept / collected / replaced | Match | Stress calls | NPE (Runnable) | Crash |")
out.append("|---|---|---|---|---|---|---|---|---|---|")
for cell in cells:
    summary, stress = cell.get("summary") or {}, cell.get("stress") or {}
    out.append(f"| {cell['runtime']} | {cell['app']} | {cell['code']} | {cell['expected']} | {cell['observed']} | "
               f"{summary.get('kept', '?')} / {summary.get('collected', '?')} / {summary.get('replaced', '?')} | {'yes' if cell['match'] else 'NO'} | "
               f"{stress.get('calls', '?')} | {stress.get('npeRunnable', '?')} | {'SIGSEGV' if cell.get('stressCrashed') else 'no'} |")

out.append("\n## Binding proof\n")
out.append("| Runtime | App | Resolved | Guava | KeepAlive calls in AddListener (per copy) | Compiler input | Keep-alive step ran |")
out.append("|---|---|---|---|---|---|---|")
for path in sorted(glob.glob(f"{root}/*/*-inspect.json")):
    inspect = json.load(open(path))
    copies = ", ".join(f"{os.path.basename(os.path.dirname(c['path']))}: {c['keepAliveCallsInAddListener']}" for c in inspect["copies"])
    compiler = "; ".join("9999.0.0 package copy" if "9999.0.0" in i["line"] else "rebuilt binding" if "Rebuilt" in i["line"] else i["line"] for i in inspect["compilerInputs"]) or "n/a (no rsp names it)"
    out.append(f"| {inspect['runtime']} | {inspect['app']} | {inspect['listenableFutureResolved']} | {inspect['guavaVersion']} | {copies} | {compiler} | {inspect['keepAliveStep'].get('ran')} |")

if il_folder:
    out.append("\n<details><summary>Decompiled invokers</summary>\n\n```csharp")
    for path in sorted(glob.glob(f"{il_folder}/*.txt")):
        out.append(open(path).read())
    out.append("```\n</details>")

print("\n".join(out))
