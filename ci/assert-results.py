"""Compares each cell's observed verdict with ci/expected.json and writes results.json plus a markdown table."""
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


def read_cell(results_dir, app, code):
    deterministic = f"{results_dir}/runs/{app}-deterministic-{code}"
    summaries = lines_starting_with(f"{deterministic}/repro.txt", "SUMMARY")
    stress_folder = f"{results_dir}/runs/{app}-stress-{code}"
    stress = lines_starting_with(f"{stress_folder}/repro.txt", "STRESS")
    crash_path = f"{stress_folder}/crash.txt"
    crashed = os.path.exists(crash_path) and "SIGSEGV" in open(crash_path, errors="replace").read()
    return {
        "summary": summaries[-1] if summaries else None,
        "results": lines_starting_with(f"{deterministic}/repro.txt", "RESULT"),
        "stress": stress[-1] if stress else None,
        "stressCrashed": crashed,
    }


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
            if app == "RebuiltBinding" and "Rebuilt" in copy["path"] + copy["sha256"] and copy["keepAliveCallsInAddListener"] < 2:
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
            cell = read_cell(arguments.results, app, code)
            observed = cell["summary"]["verdict"] if cell["summary"] else "NO SUMMARY"
            match = observed == expected[app][code]
            if not match:
                mismatches.append(f"{app}/{code}: expected {expected[app][code]}, observed {observed}")
            cells.append({"runtime": arguments.runtime, "app": app, "code": code, "expected": expected[app][code], "observed": observed, "match": match, **cell})

    failures = binding_failures(arguments.results, arguments.runtime)

    with open(f"{arguments.results}/results.json", "w") as file:
        json.dump({"runtime": arguments.runtime, "cells": cells, "mismatches": mismatches, "bindingFailures": failures}, file, indent=2)

    rows = ["| Runtime | App | Code | Expected | Observed | kept / collected / replaced | Match | Stress calls | NPE (Runnable) | Crash |", "|---|---|---|---|---|---|---|---|---|---|"]
    for cell in cells:
        summary, stress = cell["summary"] or {}, cell["stress"] or {}
        rows.append(f"| {cell['runtime']} | {cell['app']} | {cell['code']} | {cell['expected']} | {cell['observed']} | "
                    f"{summary.get('kept', '?')} / {summary.get('collected', '?')} / {summary.get('replaced', '?')} | {'yes' if cell['match'] else 'NO'} | "
                    f"{stress.get('calls', '?')} | {stress.get('npeRunnable', '?')} | {'SIGSEGV' if cell['stressCrashed'] else 'no'} |")
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
