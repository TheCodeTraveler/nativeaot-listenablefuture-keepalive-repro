#!/usr/bin/env bash
set -uo pipefail

output="${1:-artifacts/binding-il}"
rm -rf "$output"
mkdir -p "$output"
work=$(mktemp -d)
export DOTNET_ROLL_FORWARD=Major

fetch_package() {
    local id="$1" version="$2" sha256="$3"
    local lower
    lower=$(echo "$id" | tr '[:upper:]' '[:lower:]')
    curl -fsSL "https://api.nuget.org/v3-flatcontainer/$lower/$version/$lower.$version.nupkg" -o "$work/$lower.$version.nupkg"
    echo "$sha256  $work/$lower.$version.nupkg" | shasum -a 256 -c - || exit 1
    mkdir -p "$work/$lower.$version"
    unzip -q -o "$work/$lower.$version.nupkg" -d "$work/$lower.$version"
}

decompile_method() {
    local dll="$1" type_name="$2" method="$3" label="$4"
    {
        echo "=== $label ($dll)"
        dotnet tool run ilspycmd -t "$type_name" "$dll" | awk -v method="$method" '
            $0 ~ "(void|bool|object|IListenableFuture)[^;]* " method "\\(" { printing = 1 }
            printing { print }
            printing && /^\t}$/ { exit }'
    } >> "$output/$label.txt"
}

fetch_package Xamarin.Google.Guava.ListenableFuture 9999.0.0 "$(cat ci/hashes/listenablefuture-9999.0.0.sha256)"
fetch_package Xamarin.Google.Guava.ListenableFuture 1.0.0.32 "$(cat ci/hashes/listenablefuture-1.0.0.32.sha256)"

invoker="Google.Common.Util.Concurrent.IListenableFutureInvoker"
decompile_method "$work/xamarin.google.guava.listenablefuture.9999.0.0/lib/net6.0-android31.0/Xamarin.Google.Guava.ListenableFuture.dll" "$invoker" AddListener shipped-9999.0.0
decompile_method "$work/xamarin.google.guava.listenablefuture.1.0.0.32/lib/net10.0-android36.0/Xamarin.Google.Guava.ListenableFuture.dll" "$invoker" AddListener listenablefuture-1.0.0.32
decompile_method "bindings/ListenableFuture.Rebuilt/bin/Release/net11.0-android/Xamarin.Google.Guava.ListenableFuture.dll" "$invoker" AddListener rebuilt
fetch_package GoogleGson 2.13.1.1 "$(cat ci/hashes/googlegson-2.13.1.1.sha256)"
gson="GoogleGson.IExclusionStrategyInvoker"
decompile_method "$work/googlegson.2.13.1.1/lib/net8.0-android34.0/GoogleGson.dll" "$gson" ShouldSkipClass gson-2.13.1.1-net8
decompile_method "$work/googlegson.2.13.1.1/lib/net10.0-android36.0/GoogleGson.dll" "$gson" ShouldSkipClass gson-2.13.1.1-net10
cat "$output"/*.txt
