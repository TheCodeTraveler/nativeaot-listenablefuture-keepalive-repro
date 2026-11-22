#!/usr/bin/env bash
# Runs every cell of one runtime on the booted emulator. A crash in one cell must never stop the others, so there is no `set -e`.
set -u -o pipefail

runtime="${1:?usage: run-cells.sh <runtime> <stress-seconds>}"
stress_seconds="${2:-45}"
[[ $stress_seconds =~ ^[0-9]+$ ]] || { echo "stress-seconds must be a whole number, got '$stress_seconds'."; exit 2; }
artifacts="artifacts/$runtime/runs"
mkdir -p "$artifacts"

# A stress run's bridge-round Java GC lines overflow the 256 KB default and push out ENV and STRESS_PROGRESS
adb logcat -G 16M

install_apk() {
    local apk="$1" output="$2"
    timeout 300 adb install -r "$apk" > "$output" 2>&1 && return 0
    sleep 10
    timeout 300 adb install -r "$apk" > "$output" 2>&1
}

wait_for_done() {
    local package="$1" timeout_seconds="$2" waited=0
    while [ "$waited" -lt "$timeout_seconds" ]; do
        if adb logcat -d -s KeepAliveRepro:I | grep -q ' DONE '; then
            return 0
        fi
        if [ -z "$(adb shell pidof "$package" | tr -d '\r')" ] && [ "$waited" -gt 15 ]; then
            echo "Process $package is gone without DONE: it crashed."
            return 1
        fi
        sleep 2
        waited=$((waited + 2))
    done
    echo "Timed out after ${timeout_seconds}s."
    return 1
}

run_cell() {
    local app="$1" package="$2" scenario="$3" code="$4" timeout_seconds="$5"
    local folder="$artifacts/$app-$scenario-$code"
    mkdir -p "$folder"

    adb logcat -c
    adb logcat -b crash -c
    timeout 60 adb shell am start -W -n "$package/com.example.keepaliverepro.MainActivity" \
        --es scenario "$scenario" --es code "$code" --ei seconds "$stress_seconds" > "$folder/am-start.txt" 2>&1

    wait_for_done "$package" "$timeout_seconds" > "$folder/wait.txt" 2>&1
    echo "wait result $? for $folder: $(cat "$folder/wait.txt")"

    adb logcat -d > "$folder/logcat.txt"
    adb logcat -d -s KeepAliveRepro:I > "$folder/repro.txt"
    adb logcat -d -b crash > "$folder/crash.txt"
    adb shell am force-stop "$package"
}

for app in Shipped RebuiltBinding; do
    package="com.example.keepaliverepro.$(echo "$app" | sed 's/RebuiltBinding/rebuilt/;s/Shipped/shipped/')"
    apk=$(ls src/Repro."$app"/bin/Release/*/android-x64/*-Signed.apk | head -1)
    install_apk "$apk" "$artifacts/install-$app.txt" || { echo "Install of $app failed"; cat "$artifacts/install-$app.txt"; continue; }

    for code in plain keepalive; do
        run_cell "$app" "$package" deterministic "$code" 180
    done
    for code in plain keepalive; do
        run_cell "$app" "$package" stress "$code" $((stress_seconds + 90))
    done
done
