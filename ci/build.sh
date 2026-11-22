#!/usr/bin/env bash
# Builds both apps for one runtime, proves what each one compiled, and checks that the APK holds the runtime it should.
set -uo pipefail

runtime="${1:?usage: build.sh <nativeaot|coreclr|mono> [artifacts-dir]}"
artifacts="${2:-artifacts/$runtime}"
mkdir -p "$artifacts"

extra_arguments=()
if [ -n "${ANDROID_HOME:-}" ]; then
    extra_arguments+=("-p:AndroidSdkDirectory=$ANDROID_HOME")
fi

status=0
for app in Shipped RebuiltBinding; do
    # A stale obj folder from another runtime would be reused by an incremental build
    rm -rf "src/Repro.$app/obj" "src/Repro.$app/bin"

    dotnet build "src/Repro.$app" -c Release -p:ReproRuntime="$runtime" -p:RuntimeIdentifier=android-x64 ${extra_arguments[@]+"${extra_arguments[@]}"} \
        -bl:"$artifacts/build-$app.binlog" | tee "$artifacts/build-$app.txt"
    if [ "${PIPESTATUS[0]}" -ne 0 ]; then
        echo "::error::Build of $app for $runtime failed."
        status=1
        continue
    fi

    # The diag log is big, so only its summary is kept
    dotnet msbuild "$artifacts/build-$app.binlog" -noconlog -flp:"v=diag;logfile=$artifacts/diag-$app.log" > /dev/null 2>&1
    python3 -I ci/inspect-binding.py --runtime "$runtime" --app "$app" --output "$artifacts" --diag-log "$artifacts/diag-$app.log" || status=1
    rm -f "$artifacts/diag-$app.log"

    bash ci/check-apk.sh "$runtime" "$app" || status=1
done

exit $status
