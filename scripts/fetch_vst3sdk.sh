#!/usr/bin/env bash
# Lädt das offizielle Steinberg VST3 SDK (MIT-Lizenz) nach external/vst3sdk.
# Getesteter Stand: Tag v3.8.1_build_84
set -euo pipefail
cd "$(dirname "$0")/.."
TAG="${VST3_SDK_TAG:-v3.8.1_build_84}"
if [ -d external/vst3sdk/pluginterfaces ]; then
  echo "external/vst3sdk ist bereits vorhanden - nichts zu tun."
  exit 0
fi
mkdir -p external
git clone --branch "$TAG" --depth 1 --recurse-submodules --shallow-submodules \
  https://github.com/steinbergmedia/vst3sdk.git external/vst3sdk
echo "VST3 SDK $TAG liegt in external/vst3sdk"
