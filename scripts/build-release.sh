#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

if [[ -z "${JAVA_HOME:-}" && -x /usr/libexec/java_home ]]; then
  JAVA_HOME="$(/usr/libexec/java_home -v 17)"
  export JAVA_HOME
fi

sdk_only=false
check_only=false
while true; do
  case "${1:-}" in
    --sdk-only) sdk_only=true; shift ;;
    --check-only) check_only=true; shift ;;
    *) break ;;
  esac
done
export PYTHONDONTWRITEBYTECODE=1
# Read installed SDKs; changes to these environment variables affect this process only.
if [[ "$sdk_only" == true ]]; then
  ANDROID_HOME="$(python3 scripts/package_release.py --print-sdk-path "$@")"
else
  ANDROID_HOME="$(python3 scripts/package_release.py --print-sdk-path)"
fi
ANDROID_SDK_ROOT="$ANDROID_HOME"
export ANDROID_HOME ANDROID_SDK_ROOT
python3 scripts/check_environment.py --sdk-root "$ANDROID_HOME"
if [[ "$check_only" == true ]]; then exit 0; fi

# Only project outputs are prepared. Missing system tools stop the build above.
python3 scripts/build_core.py
ANDROID_NDK_HOME="$(python3 scripts/build_core.py --print-ndk-path)"
export ANDROID_NDK_HOME
if [[ "$sdk_only" == true ]]; then
  python3 scripts/package_release.py "$@"
else
  export GRADLE_USER_HOME="${GRADLE_USER_HOME:-$project_dir/build/tool-cache/gradle}"
  export ANDROID_USER_HOME="${ANDROID_USER_HOME:-$project_dir/build/tool-cache/android}"
  ./gradlew :app:assembleRelease "$@"
fi
printf '%s\n' 'Release APK: app/build/outputs/apk/release/app-release-unsigned.apk'
printf '%s\n' 'Distribute the corresponding source from build/outputs/native/ with the APK.'
