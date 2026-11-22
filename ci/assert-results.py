import argparse
import json
import os
import re
import sys

APPS = ["Shipped", "RebuiltBinding"]
CODES = ["plain", "keepalive"]
# MainActivity logs the last segment of the package name, not the cell name
LOG_APP_NAMES = {"Shipped": "shipped", "RebuiltBinding": "rebuilt"}


def fields(line):
    return {key: value.strip('"') for key, value in re.findall(r'(\w+)=("[^"]*"|\S+)', line)}


def lines_starting_with(path, key, app=None, code=None):
    if not os.path.exists(path):
        return []
    with open(path, errors="replace") as file:
        parsed = [fields(line) for line in file if re.search(rf"\s{key}\s", line)]
    parsed = [line for line in parsed if app is None or line.get("app") == LOG_APP_NAMES[app]]
    if code is not None and key in ("RESULT", "SUMMARY"):
        parsed = [line for line in parsed if line.get("code") == code]
    return parsed


def error_texts(lines):
    return [f"ERROR {line.get('inner', line.get('exception', ''))}: {line.get('message', '')}" for line in lines]


def native_failures(folder):
    signals = []
    crash_path = f"{folder}/crash.txt"
    if os.path.exists(crash_path):
        signals += re.findall(r"Fatal signal \d+ \((SIG\w+)\)", open(crash_path, errors="replace").read())
    logcat_path = f"{folder}/logcat.txt"
    if os.path.exists(logcat_path) and "JNI DETECTED ERROR" in open(logcat_path, errors="replace").read():
        signals.append("JNI DETECTED ERROR")
    return list(dict.fromkeys(signals))


def consistency_problems(runtime, summary, results, env, env_count=1):
    problems = []
    if env_count > 1:
        problems.append(f"scenario ran {env_count} times in one process")
    if not env:
        problems.append("no ENV line")
    elif env.get("detected") != runtime:
        problems.append(f"ENV detected {env.get('detected')}, expected {runtime}")
    if summary and len(results) != 5:
        problems.append(f"{len(results)} RESULT lines, expected 5")
    if summary and "controlsCollected" not in summary:
        problems.append("SUMMARY has no controlsCollected (the app predates the positive control)")
    elif summary and summary.get("verdict") == "SAFE" and int(summary["controlsCollected"]) == 0:
        problems.append("SAFE with controlsCollected=0: the GC collected nothing, so SAFE is not proven")
    if summary:
        total = sum(int(summary.get(key, -1)) for key in ("kept", "collected", "replaced", "invalid"))
        if total != 5:
            problems.append(f"kept+collected+replaced+invalid is {total}, expected 5")
    return problems


def read_cell(results_dir, runtime, app, code):
    deterministic = f"{results_dir}/runs/{app}-deterministic-{code}"
    summaries = lines_starting_with(f"{deterministic}/repro.txt", "SUMMARY", app, code)
    results = lines_starting_with(f"{deterministic}/repro.txt", "RESULT", app, code)
    envs = lines_starting_with(f"{deterministic}/repro.txt", "ENV", app)
    stress_folder = f"{results_dir}/runs/{app}-stress-{code}"
    stress = lines_starting_with(f"{stress_folder}/repro.txt", "STRESS", app, code)
    errors = error_texts(lines_starting_with(f"{deterministic}/repro.txt", "ERROR", app) + lines_starting_with(f"{stress_folder}/repro.txt", "ERROR", app))
    wait_path = f"{deterministic}/wait.txt"
    timed_out = os.path.exists(wait_path) and "Timed out" in open(wait_path, errors="replace").read()
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
        "errors": errors,
        "timedOut": timed_out,
        "consistencyProblems": consistency_problems(runtime, summary, results, env, len(envs)),
    }


def observed_label(cell):
    if cell["summary"]:
        return cell["summary"]["verdict"]
    if cell["errors"]:
        return "ERROR"
    if not cell["results"]:
        return "TIMEOUT_BEFORE_RESULT" if cell["timedOut"] else "CRASH_BEFORE_RESULT"
    return "NO SUMMARY"


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
    parser.add_argument("--output")
    arguments = parser.parse_args()

    with open(arguments.expected) as file:
        expected = json.load(file)[arguments.runtime]

    cells, mismatches = [], []
    for app in APPS:
        for code in CODES:
            cell = read_cell(arguments.results, arguments.runtime, app, code)
            observed = observed_label(cell)
            expectation = expected[app][code]
            match = observed in ("SAFE", "BUG") if expectation == "REPORT" else observed == expectation
            if not match:
                mismatches.append(f"{app}/{code}: expected {expectation}, observed {observed}")
            mismatches += [f"{app}/{code}: {problem}" for problem in cell["consistencyProblems"]]
            mismatches += [f"{app}/{code}: deterministic run hit {failure}" for failure in cell["deterministicNativeFailures"]]
            cells.append({"runtime": arguments.runtime, "app": app, "code": code, "expected": expectation, "observed": observed, "match": match, **cell})

    failures = binding_failures(arguments.results, arguments.runtime)

    with open(arguments.output or f"{arguments.results}/results.json", "w") as file:
        json.dump({"runtime": arguments.runtime, "cells": cells, "mismatches": mismatches, "bindingFailures": failures}, file, indent=2)

    rows = ["| Runtime | App | Code | Predicted | Observed | kept / collected / replaced | Controls collected | Match | Stress calls | NPE (Runnable) | Crash |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for cell in cells:
        summary, stress = cell["summary"] or {}, cell["stress"] or {}
        rows.append(f"| {cell['runtime']} | {cell['app']} | {cell['code']} | {cell['expected']} | {cell['observed']} | "
                    f"{summary.get('kept', '?')} / {summary.get('collected', '?')} / {summary.get('replaced', '?')} | {summary.get('controlsCollected', '?')} | {'yes' if cell['match'] else 'NO'} | "
                    f"{stress.get('calls', '?')} | {stress.get('npeRunnable', '?')} | {', '.join(cell['stressNativeFailures'] + cell['deterministicNativeFailures'] + ([cell['crashMessage']] if cell['crashMessage'] else []) + cell['errors']) or 'no'} |")
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
