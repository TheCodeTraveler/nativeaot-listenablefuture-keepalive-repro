#!/usr/bin/env bash
# Fails when an APK does not hold the runtime the matrix cell claims, so a mislabeled cell cannot pass as evidence.
set -uo pipefail

runtime="$1"
app="$2"
apk=$(ls src/Repro."$app"/bin/Release/*/android-x64/*-Signed.apk | head -1)
listing=$(unzip -l "$apk")

has() { grep -q "$1" <<< "$listing"; }
fail() { echo "::error::$app $runtime APK: $1"; exit 1; }

case "$runtime" in
    nativeaot)
        has "lib/x86_64/libRepro.$app.so" || fail "missing the NativeAOT library"
        has "libcoreclr.so" && fail "contains CoreCLR"
        has "libmonosgen-2.0.so" && fail "contains Mono"
        ;;
    coreclr)
        has "libcoreclr.so" || fail "missing CoreCLR"
        ;;
    mono)
        has "libmonosgen-2.0.so" || fail "missing Mono"
        ;;
esac
echo "APK check passed: $app $runtime ($apk)"
