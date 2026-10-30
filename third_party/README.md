# rtp2httpd source dependency

The upstream source is pinned in `rtp2httpd.lock.json`:

- Repository: https://github.com/stackia/rtp2httpd
- Release: v3.17.2
- Commit: ec7808b813d4595dff890713993bc46b82f72fc2
- License: GPL-2.0, copied unchanged from upstream during the build.

`scripts/build_core.py` fetches that exact Git object, exports a pristine tree and adapts a separate build copy. It does not substitute an upstream OpenWrt package or Linux binary. It uses the generated web resources already present in the release source, without editing `embedded_web_data.h` or requiring a frontend dependency installation.

The APK contains `assets/rtp2httpd/LICENSE` and `assets/rtp2httpd/BUILD-INFO.json`. The build also creates `build/outputs/native/rtp2httpd-3.17.2-source.tar.gz`, containing pristine upstream source plus this Android project's source, adaptation scripts and native entry point. Include this corresponding source bundle when distributing the APK.

To rebuild from the source bundle without fetching GitHub again:

```sh
cd rtp2httpd-source/android-rtp2httpd
export RTP2HTTPD_SOURCE_DIR="$(cd ../upstream && pwd)"
./scripts/build-release.sh
```

This explicit local source override is recorded in build metadata. Android SDK/NDK and Gradle dependencies are still required.
