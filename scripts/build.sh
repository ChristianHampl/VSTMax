#!/usr/bin/env bash
# Baut DSP-Kern + Tests und die VST3-Plug-ins (inkl. Steinberg-Validator) unter Linux/macOS.
# VST3_SDK_ROOT=<pfad> überschreibt external/vst3sdk.
set -euo pipefail
cd "$(dirname "$0")/.."
JOBS="${JOBS:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)}"

cmake -S dsp -B build/dsp -DCMAKE_BUILD_TYPE=Release
cmake --build build/dsp -j "$JOBS"
ctest --test-dir build/dsp --output-on-failure

if [ -z "${VST3_SDK_ROOT:-}" ] && [ ! -d external/vst3sdk/pluginterfaces ]; then
  echo "VST3 SDK fehlt - scripts/fetch_vst3sdk.sh ausführen oder VST3_SDK_ROOT setzen." >&2
  exit 1
fi
cmake -S plugins -B build/plugins -DCMAKE_BUILD_TYPE=Release
cmake --build build/plugins --config Release -j "$JOBS" 2>&1 | tee build/plugins/build.log
if grep -Eq "Result: [0-9]+ tests passed, [1-9][0-9]* tests failed" build/plugins/build.log; then
  echo "Steinberg-Validator meldet Fehler (siehe build/plugins/build.log)" >&2
  exit 1
fi
echo "Fertig: build/plugins/VST3/Release/AIME.vst3"
