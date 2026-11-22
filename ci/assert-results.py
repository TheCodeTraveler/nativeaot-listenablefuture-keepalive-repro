import argparse
import json
import os
import re
import sys

APPS = ["Shipped", "RebuiltBinding"]
CODES = ["plain", "keepalive"]


def fields(line):
    return {key: value.strip('"') for key, value in re.findall(r'(\w+)=("[^"]*"|\S+)', line)}


def lines_starting_with(path, key):
    if not os.path.exists(path):
        return []
    with open(path, errors="replace") as file:
        return [fields(line) for line in file if re.search(rf"\s{key}\s", line)]


def native_failures(folder):
    signals = []
    crash_path = f"{folder}/crash.txt"
    if os.path.exists(crash_path):
        signals += re.findall(r"Fatal signal \d+ \((SIG\w+)\)", open(crash_path, errors="replace").read())
    logcat_path = f"{folder}/logcat.txt"
    if os.path.exists(logcat_path) and "JNI DETECTED ERROR" in open(logcat_path, errors="replace").read():
        signals.append("JNI DETECTED ERROR")
    return list(dict.fromkeys(signals))


def consistency_problems(runtime, summary, results, env):
    problems = []
    if not env:
        problems.append("no ENV line")
    elif env.get("detected") != runtime:
        problems.append(f"ENV detected {env.get('detected')}, expected {runtime}")
    if summary and len(results) != 5:
        problems.append(f"{len(results)} RESULT lines, expected 5")
    if summary:
        total = sum(int(summary.get(key, -1)) for key in ("kept", "collected", "replaced", "invalid"))
        if total != 5:
            problems.append(f"kept+collected+replaced+invalid is {total}, expected 5")
    return problems


def read_cell(results_dir, runtime, app, code):
    deterministic = f"{results_dir}/runs/{app}-deterministic-{code}"
    summaries = lines_starting_with(f"{deterministic}/repro.txt", "SUMMARY")
    results = lines_starting_with(f"{deterministic}/repro.txt", "RESULT")
    envs = lines_starting_with(f"{deterministic}/repro.txt", "ENV")
    stress_folder = f"{results_dir}/runs/{app}-stress-{code}"
    stress = lines_starting_with(f"{stress_folder}/repro.txt", "STRESS")
    summary = summaries[-1] if summaries else None
    env = envs[0] if envs else None
    return {
        "summary": summary,
        "results": results,
        "env": env,
        "stress": stress[-1] if stress else None,
        "deterministicNativeFailures": native_failures(deterministic),
        "stressNativeFailures": native_failures(stress_folder),
        "crashMessage": crash_message(deterministic),
        "consistencyProblems": consistency_problems(runtime, summary, results, env),
    }


def crash_message(folder):
    path = f"{folder}/crash.txt"
    if not os.path.exists(path):
        return ""
    text = open(path, errors="replace").read()
    match = re.search(r"Abort message: '?(.*)", text) or re.search(r"F\s.*?\.cc:\d+\]\s*(.*)", text)
    return match.group(1).strip("'")[:160] if match else ""


def binding_failures(results_dir, runtime):
    failures = []
    for app in APPS:
        path = f"{results_dir}/{runtime}-{app}-inspect.json"
        if not os.path.exists(path):
            failures.append(f"{app}: no inspect.json")
            continue
        with open(path) as file:
            inspect = json.load(file)
        for copy in inspect["copies"]:
            if app == "Shipped" and copy["keepAliveCallsInAddListener"] != 0:
                failures.append(f"Shipped copy {copy['path']} has keep-alives")
            if app == "RebuiltBinding" and "Rebuilt" in copy["path"] and copy["keepAliveCallsInAddListener"] < 2:
                failures.append(f"Rebuilt copy {copy['path']} lacks keep-alives")
        if app == "Shipped" and inspect["listenableFutureResolved"] != "9999.0.0":
            failures.append(f"Shipped resolved {inspect['listenableFutureResolved']}")
    return failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--expected", required=True)
    parser.add_argument("--results", required=True)
    arguments = parser.parse_args()

    with open(arguments.expected) as file:
        expected = json.load(file)[arguments.runtime]

    cells, mismatches = [], []
    for app in APPS:
        for code in CODES:
            cell = read_cell(arguments.results, arguments.runtime, app, code)
            observed = cell["summary"]["verdict"] if cell["summary"] else "CRASH_BEFORE_RESULT" if cell["results"] == [] else "NO SUMMARY"
            match = observed == expected[app][code]
            if not match:
                mismatches.append(f"{app}/{code}: expected {expected[app][code]}, observed {observed}")
            mismatches += [f"{app}/{code}: {problem}" for problem in cell["consistencyProblems"]]
            mismatches += [f"{app}/{code}: deterministic run hit {failure}" for failure in cell["deterministicNativeFailures"]]
            cells.append({"runtime": arguments.runtime, "app": app, "code": code, "expected": expected[app][code], "observed": observed, "match": match, **cell})

    failures = binding_failures(arguments.results, arguments.runtime)

    with open(f"{arguments.results}/results.json", "w") as file:
        json.dump({"runtime": arguments.runtime, "cells": cells, "mismatches": mismatches, "bindingFailures": failures}, file, indent=2)

    rows = ["| Runtime | App | Code | Predicted | Observed | kept / collected / replaced | Match | Stress calls | NPE (Runnable) | Crash |", "|---|---|---|---|---|---|---|---|---|---|"]
    for cell in cells:
        summary, stress = cell["summary"] or {}, cell["stress"] or {}
        rows.append(f"| {cell['runtime']} | {cell['app']} | {cell['code']} | {cell['expected']} | {cell['observed']} | "
                    f"{summary.get('kept', '?')} / {summary.get('collected', '?')} / {summary.get('replaced', '?')} | {'yes' if cell['match'] else 'NO'} | "
                    f"{stress.get('calls', '?')} | {stress.get('npeRunnable', '?')} | {', '.join(cell['stressNativeFailures'] + cell['deterministicNativeFailures'] + ([cell['crashMessage']] if cell['crashMessage'] else [])) or 'no'} |")
    table = "\n".join(rows)
    print(table)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a") as file:
            file.write(f"## {arguments.runtime}\n\n{table}\n\n")
            for failure in failures + mismatches:
                file.write(f"- MISMATCH: {failure}\n")

    return 1 if mismatches or failures else 0


sys.exit(main())
