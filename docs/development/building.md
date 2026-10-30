[文档首页](../README.md) · [项目首页](../../README.md)

# 本地构建、签名与测试

本文命令均在项目根目录运行；从其他目录运行时，使用 android.py 的绝对路径。先完成[环境准备](environment.md)。

## 编译与打包


先按 [环境说明](environment.md) 准备已有 JDK 17、Python 3.9+、Git、make、CMake 3.22+、Android Platform 34、Build Tools 35.0.0 和 NDK 28.2.13676358。脚本只检查和使用现有工具，不自动安装、升级或修改永久环境配置。

```sh
python3 scripts/android.py check
python3 scripts/android.py build
```

无法运行 Gradle 时，可使用现有 SDK 的 javac/aapt2/R8/zipalign 打包：

```sh
python3 scripts/android.py build --backend sdk
```

默认同时生成 ARM32、ARM64 独立包及包含两种架构的通用包。通用包安装时由 Android 选择适合系统的核心；64 位 CPU 配 32 位系统时使用 ARM32 核心。只构建一种架构可指定：

```sh
python3 scripts/android.py build --backend sdk --abi armeabi-v7a
python3 scripts/android.py build --backend sdk --abi arm64-v8a
# 恢复默认的双架构构建
python3 scripts/android.py build --backend sdk --abi universal
```

普通 Gradle 路径同样支持 `--abi`；直接使用 Gradle 时可传 `-Pabi=armeabi-v7a` 或 `-Pabi=arm64-v8a`。ARM32 指 ARMv7/NEON，不支持 ARMv5/v6；x86/x86_64 未纳入当前构建。

构建工具统一由 `scripts/android.py` 进入，内部模块位于 `scripts/android_build/`，使用 `python3 scripts/android.py --help` 查看子命令；额外 Gradle 参数通过 `build -- --offline` 传递。

两条路径均构建真实 Android 原生核心，编译桌面图标资源，打包内置网页及锁定的本地 YAML 依赖，并校验 ELF、哈希、资源和许可证。SDK-only 不代替 Gradle lint 或设备测试。

产物：

- `app/build/outputs/apk/release/app-release-unsigned.apk`：默认是 ARM32 + ARM64 通用包；指定单一 `--abi` 时为所选架构包。
- `app/build/outputs/apk/release/app-armeabi-v7a-release-unsigned.apk`：ARM32 独立包。
- `app/build/outputs/apk/release/app-arm64-v8a-release-unsigned.apk`：ARM64 独立包。
- `build/outputs/native/rtp2httpd-3.17.2-source.tar.gz`：对应源码，分发 APK 时一并提供。

APK 均需签名后安装；三种包使用相同应用 ID，覆盖安装应复用同一签名。`output-metadata.json` 列出本次构建的产物；输出目录中其他架构的旧文件不代表本次已重新构建。

原生核心由脚本生成到 `app/build/generated/native-core/`，不向 src/main/jniLibs 手工放二进制。[第三方来源及离线重建](../../third_party/README.md) 包含版本锁、许可证与源码包说明。

## Release 签名


使用已有 JDK 的 keytool 生成一次签名密钥，密码交互输入；后续构建复用同一文件和别名。以下假定 JDK 及 SDK Build Tools 已在 PATH 中：

```sh
keytool -genkeypair -keystore rtp2httpd-release.p12 -storetype PKCS12 \
  -alias rtp2httpd -keyalg RSA -keysize 3072 -validity 10000 -dname "CN=rtp2httpd"

apksigner sign --ks rtp2httpd-release.p12 --ks-key-alias rtp2httpd \
  --out app/build/outputs/apk/release/app-release-signed.apk \
  app/build/outputs/apk/release/app-release-unsigned.apk

apksigner verify --verbose --print-certs app/build/outputs/apk/release/app-release-signed.apk
```

apksigner 位于选定 SDK 的 `build-tools/35.0.0/`。构建已完成 zipalign，签名后不要再修改 APK。备份密钥和密码；密钥已被 Git 忽略，不随源码分发。

## 构建入口与内部模块

所有命令通过 `python3 scripts/android.py` 调用，内部模块不作为命令直接执行：

| 命令 | 用途 |
| --- | --- |
| `check` | 只读检查现有构建环境 |
| `locate sdk` / `locate ndk` | 仅输出发现的工具路径 |
| `source fetch` | 拉取版本锁指定的上游提交 |
| `native --abi universal` | 编译两种架构的原生核心 |
| `package --abi universal` | 使用已有核心进行 SDK-only 打包 |
| `build --backend sdk` | 检查环境、编译核心、完成 SDK-only 打包 |
| `build` | 检查环境、编译核心、调度 Gradle Release |
| `verify <APK>` | 校验 APK 内核心、元数据、资源和许可证 |
| `dependencies check` | 校验锁定的 Java 依赖 |
| `test --python-only` | 执行 Python 构建工具测试 |
| `test` | 执行 JVM 与 Python 测试 |

使用 `python3 scripts/android.py <命令> --help` 查看该命令参数。构建/原生编译可通过 `--source-dir` 指向原始上游源码；SDK/NDK 路径优先级见[环境说明](environment.md)。重构后的模块职责和任务验收见[开发计划](roadmap.md)。

## 测试与当前验证边界

```sh
python3 scripts/android.py test --python-only
python3 scripts/android.py test
python3 scripts/android.py verify app/build/outputs/apk/release/app-release-unsigned.apk --abi universal
```

完整主机测试使用现有 JDK 17 及 Gradle 缓存中的 JUnit 4.13.2、Hamcrest 1.3；缺失时明确报错，不自动下载。Python-only 测试不要求 JUnit，但测试源码拉取逻辑需要已有 Git。

Gradle 专项检查可在已配置的环境执行：

```sh
./gradlew :app:testDebugUnitTest :app:lintDebug :app:assembleDebug :app:assembleRelease
```

直接运行 gradlew 使用其自身缓存选择规则；需要项目内缓存时显式设置 GRADLE_USER_HOME、ANDROID_USER_HOME。SDK-only 成功不代表 lint 或设备测试已通过。当前完整 Gradle 受本地沙箱 socket 限制，仍待可用环境验证。

## 从对应源码包重建

解压分发的 `rtp2httpd-<版本>-source.tar.gz` 后：

```sh
cd rtp2httpd-source/android-rtp2httpd
python3 scripts/android.py build --backend sdk --source-dir ../upstream
```

此方式复用归档中的原始上游源码，不再从 GitHub 拉取核心；仍需准备 Android SDK/NDK、JDK 和 CMake。源码包包含应用、脚本、工作流、文档和第三方依赖，排除签名密钥及本机配置。更多来源与许可证信息见[第三方依赖](../../third_party/README.md)。
