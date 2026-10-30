# Android rtp2httpd

面向长期通电机顶盒的 IPTV 后台转发服务。无 Activity、无 AndroidX/Kotlin 等第三方运行时依赖，仅 ARM64，最低 Android 8.0 / API 26。

构建流程从固定上游源码编译 Android 原生核心，再将它与前台服务一起打包。已完成 ARM64/API 26 原生编译和 SDK 工具链的 Release 打包验证，APK 包含约 614 KiB 的核心；实际机顶盒转发仍待验证。

后续 HTTP 管理网页与 YAML 配置的完整任务、阶段和验收标准见 [开发计划](docs/DEVELOPMENT_PLAN.md)。这些管理功能目前尚未实现。

构建输出、本机配置与签名密钥已加入 Git 忽略规则。

环境要求、配置方式及写入边界见 [构建环境说明](docs/ENVIRONMENT.md)，历史初始化行为核查见 [环境改动核查](docs/ENVIRONMENT_AUDIT.md)。构建只使用已有工具，缺少时提示使用者准备，不自动安装或更新系统/SDK 组件。

## 一键 Release 构建

macOS/Linux 预先准备 JDK 17、Python 3.9+、Git、make、CMake 3.22+，以及包含 platform 34、Build Tools 35.0.0、NDK 28.2.13676358 的已有 Android SDK。配置只读查找用的 `ANDROID_HOME`，或人工在不提交的 `local.properties` 中写入 `sdk.dir`。

```sh
./scripts/build-release.sh --check-only
./scripts/build-release.sh
```

脚本执行以下步骤，任一步失败都会停止：

1. 检查已安装的 JDK、SDK、NDK、CMake 等工具；缺少或版本不符时停止并提示，不安装、不升级、不接受许可证。
2. 拉取 [rtp2httpd v3.17.2](https://github.com/stackia/rtp2httpd/releases/tag/v3.17.2) 的固定提交 `ec7808b813d4595dff890713993bc46b82f72fc2`，复用项目内源码缓存。
3. 在独立构建副本中适配 Android 平台检测、链接库、临时路径、BSD 字符串函数和进程入口，交叉编译 ARM64/API 26 PIE 可执行核心并 strip。API 26 使用上游普通发送路径，不依赖 API 30 才提供的 memfd_create 优化。
4. 打包 Release，并校验 APK 内真实存在 ARM64 核心、Android linker64、16KB 页对齐、正确哈希和上游许可证。缺少核心的包会明确失败。

成功后的产物：

- `app/build/outputs/apk/release/app-release-unsigned.apk`：未签名 Release，安装前需签名；项目未包含发布密钥。
- `build/outputs/native/rtp2httpd-3.17.2-source.tar.gz`：对应源码、Android 封装及构建/适配脚本，分发 APK 时一并提供。
- `app/build/generated/native-core/jniLibs/arm64-v8a/librtp2httpd.so`：生成的 Android 核心，不提交二进制。

常规 `./gradlew :app:assembleRelease` 也已接入原生构建与 APK 校验；一键脚本先检查已有环境。没有配置 `JAVA_HOME` 的 macOS 上，脚本仅为本次进程选择已安装的 JDK 17，不修改系统默认 Java。
首次构建可能访问 GitHub、Gradle 和 Maven 仓库；SDK 组件需用户事先准备。Release 入口默认将 Gradle/Android 工具缓存放在项目 build/tool-cache/，详情见环境说明。
NDK 会优先复用当前 SDK、`ANDROID_NDK_HOME` 或 Homebrew SDK 中已完整安装的同版本工具；Python 脚本和 Gradle 使用同一路径，避免因为 SDK 分散在不同目录而重复下载。只有目录而没有 `source.properties` 的安装不会被当作完成。

若环境无法运行 Gradle，可显式使用项目专用的 SDK 打包路径：

```sh
./scripts/build-release.sh --sdk-only
```

此路径直接调用 javac、aapt2、R8 和 zipalign，读取当前 Manifest/Java 源码及生成的核心，输出同路径未签名 Release，并执行相同的核心校验；它仅支持当前无自定义资源、无运行时依赖的服务工程，不代替 Gradle lint 或设备测试。
脚本会先检查 Android 34 和 Build Tools 35.0.0 是否完整；环境变量指向不完整 SDK 时，会复用其他已安装的完整 SDK，并让核心构建与打包使用同一路径。显式传入 `--sdk-root` 时严格使用指定目录，缺少组件则在编译前报错。

只下载源码或只构建核心：

```sh
python3 scripts/build_core.py --fetch-only
python3 scripts/build_core.py
```

锁定信息见 [third_party/rtp2httpd.lock.json](third_party/rtp2httpd.lock.json)。源码包离线重建方式见 [第三方源码说明](third_party/README.md)。上游 Release 的 `.apk` 是 OpenWrt 软件包，不能作为 Android 应用安装。

## 启停

开发安装可用 `./gradlew :app:assembleDebug` 生成自动开发签名的 APK；Debug 同样必须构建并包含核心。

```sh
adb install app/build/outputs/apk/debug/app-debug.apk
adb shell am start-foreground-service -n local.rtp2httpd/.RelayService \
  --es upstream_interface eth0 \
  --es listen_interface wlan0 \
  --ei port 5140 --ei maxclients 5 --ei verbose 2
adb shell am stopservice -n local.rtp2httpd/.RelayService
adb logcat -s Rtp2httpd
```

| Intent extra | 类型 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `upstream_interface` | string | 必填 | 上游网卡，转为 `--upstream-interface` |
| `listen_interface` | string | 不指定 | 使用该网卡首个 IPv4 地址监听；省略则为 0.0.0.0 |
| `port` | int | 5140 | HTTP 端口，允许 1024–65535 |
| `maxclients` | int | 5 | 最大客户端数，必须大于 0 |
| `verbose` | int | 2 | 日志级别 0–4 |

输入通过 ProcessBuilder 的独立 argv 传入，始终附带 `--noconfig` 和 `--workers 1`。
服务入口使用系统 DUMP 权限，仅允许 ADB shell/root 等授权调用方。核心从安装器提取的 nativeLibraryDir 启动，工作目录及 TMPDIR 是应用私有缓存；不从缓存目录执行程序。

监听指定网卡的 IP 不等于强制响应走该网卡。每次启动核心都会重新解析 IPv4；核心仍运行时地址变化需停止后重启。运行中或等待重试时再次启动不会更新参数，请先停止再启动。

## 机顶盒长期运行

- 合法启动参数在确认核心可执行后同步保存到私有存储。系统回收后以 `START_STICKY` 重建服务，空 Intent 读取保存参数；显式启动仍需传完整参数。
- 核心退出（包括退出码 0）、启动 I/O 失败、网卡或 IPv4 暂不可用时，按 1、2、4、8、16、32、60 秒退避重试，之后每 60 秒重试；连续运行至少 60 秒后重置。
- 参数格式错误、无保存配置或核心缺失/不可执行时停止，避免持续无效启动。
- 服务期间持有 CPU 部分唤醒锁和可用的 Wi-Fi 组播锁；CPU 锁每 5 分钟续租 10 分钟，不保持屏幕常亮，不增加电池优化申请界面。
- 主动停止会取消重试、释放锁，并在后台终止直接子进程，5 秒未退出则强制终止，再等最多 1 秒；保留配置不会自行触发启动。
- Android 原生入口为 supervisor 设置父进程死亡信号并检查启动竞态；worker 使用上游的父进程死亡处理。仍须在实际 Android 固件验证整个进程树的退出行为。

没有开机自启、远程配置界面或核心存活时的流量健康检测。前台服务无法保证永不被杀，也不能阻止用户强行停止。若盒子固件仍限制待机联网，可按设备配置后台运行权限；支持标准命令的设备可用 `adb shell dumpsys deviceidle whitelist +local.rtp2httpd`。

## 验证与继续开发

```sh
python3 -m unittest discover -s scripts/tests -v
./gradlew :app:testDebugUnitTest :app:lintDebug :app:assembleDebug :app:assembleRelease
```

脚本测试覆盖固定提交拉取、Android 源码适配、ELF/包完整性检查；它们不能替代真实 NDK 编译和设备转发验证。JVM 测试覆盖参数与进程生命周期。

迁移信息见 [开发交接说明](docs/HANDOFF.md)，机顶盒验收见 [长期运行验证](docs/RELIABILITY_TESTING.md)。当前已通过真实 NDK 编译、SDK/R8 Release 打包、ELF/包内容及 zipalign 检查；完整 Gradle 构建与机顶盒转发尚未验证。
