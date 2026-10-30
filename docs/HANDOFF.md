# 迁移与开发交接

## 产品目标

面向长期通电的 Android 机顶盒，轻量 IPTV 后台转发服务。只支持 ARM64 起步，不做 Android Activity、原生设置界面或 Android 播放器。当前无第三方运行时依赖，通过 ADB Intent 传入网卡、端口、并发数及日志级别，核心使用 `--noconfig --workers 1`。

后续计划增加 HTTP 管理网页和私有 YAML 配置，保留默认参数与 ADB 兼容。完整任务清单、配置优先级、迁移/回滚、鉴权、依赖和验收标准以 [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md) 为准；当前尚未实施这些新增功能。

当前保留上游 Release 源码内已有的嵌入式 Web 资源，没有手改生成头文件或引入前端构建依赖；进一步裁剪网页应在基础转发验证后单独处理。

## 实现与验证状态

- Android 服务已有参数保存、START_STICKY 回收恢复、核心退出退避重试、CPU/组播锁与主动停止清理。
- 已接入脚本和 Gradle 原生构建依赖，锁定上游 v3.17.2 / `ec7808b813d4595dff890713993bc46b82f72fc2`，NDK `28.2.13676358`，目标 ARM64/API 26。
- 已实现 Android 平台/epoll 选择、跳过 librt、相对临时路径、index/rindex 到 strchr/strrchr 的转换、API 26 关闭 memfd_create 优化以及 Java 宿主死亡时通知 supervisor 的原生入口。原始上游 checkout 不修改，只改独立构建副本。
- Release 构建增加核心 ELF、哈希、许可证检查；旧的约 8K 服务壳会被检查器拒绝。
- 已完成真实 NDK 编译，核心 629248 字节，并通过 SDK 工具链的 aapt2/R8/zipalign Release 打包，APK 约 478 KiB。完整 Gradle 构建仍受执行环境权限限制，机顶盒转发尚未验证。
- 现有 Release APK 已包含真实核心、构建元数据和许可证；不要把编译/打包通过当作设备转发正常的证明。

## 文件导航

- `docs/DEVELOPMENT_PLAN.md`：后续开发的任务清单和验收依据。
- `scripts/check_environment.py`、`docs/ENVIRONMENT.md`：只检查已有环境，列出准备方式与写入边界。
- `docs/ENVIRONMENT_AUDIT.md`：已确认的历史环境改动与证据范围。
- `scripts/build-release.sh`：完整 Release 入口，先准备核心/工具，再运行 Gradle。
- `scripts/package_release.py`：显式 `--sdk-only` 模式，直接用 SDK 工具打包当前无运行时依赖、无自定义资源的工程。
- `scripts/build_core.py`：固定 Git 提交下载、源码适配、NDK 构建、strip、许可证及对应源码包生成。
- `scripts/elf_utils.py`、`scripts/verify_apk.py`：Android ARM64 PIE、linker64、16KB 对齐、依赖库、包内哈希及许可证检查。
- `scripts/tests/`：下载固定提交、适配和产物检查的主机测试。
- `third_party/rtp2httpd.lock.json`：源码和 NDK 版本锁；`third_party/README.md`：来源及源码包说明。
- `native/`：CMake Android 入口、supervisor 父进程死亡处理。
- `app/src/main/java/local/rtp2httpd/`：RelayService、RelayConfig、RelayRunner。
- `app/src/test/java/local/rtp2httpd/`：参数与 Java 进程生命周期测试。
- `docs/RELIABILITY_TESTING.md`：设备长期运行验收。

## 迁移与构建

复制项目源码、Gradle Wrapper、native、scripts 和 third_party；不需要复制 `.gradle/`、`build/`、`app/build/`，不要沿用其他机器的 local.properties。

macOS/Linux 使用 JDK 17、Python 3.9+、Git、make、Android SDK Command-line Tools，安装 platform 34 与 Build Tools 35.0.0。配置 ANDROID_HOME 或 local.properties 的 sdk.dir，执行 `./scripts/build-release.sh`。
SDK Platform 34、Build Tools 35.0.0、NDK 28.2.13676358 和 CMake 3.22+ 必须预先安装。脚本不运行安装器、不更新用户 SDK；先执行 --check-only，缺失时按 docs/ENVIRONMENT.md 自行准备并选择路径。
Gradle 无法运行时可显式执行 `./scripts/build-release.sh --sdk-only`；该模式已用于验证本项目 Release 打包，不运行 Gradle lint 或设备检查。

工程使用 AGP 8.12.2 / Gradle 8.13，minSdk 26、compileSdk/targetSdk 34。升级 targetSdk 时同时检查后台启动和前台服务限制。

成功产物为 `app/build/outputs/apk/release/app-release-unsigned.apk`，安装前需签名。没有发布密钥或发布签名配置，Debug 可用于开发安装。Debug 也依赖真实核心构建。
APK 内应包含 `lib/arm64-v8a/librtp2httpd.so`、上游 LICENSE 和 BUILD-INFO.json。分发时附带 `build/outputs/native/rtp2httpd-3.17.2-source.tar.gz`，其中含上游原始源码及 Android 封装和构建脚本。

生成核心位于 `app/build/generated/native-core/`，不再从 src/main/jniLibs 手工取二进制。useLegacyPackaging=true 让安装器提取核心，keepDebugSymbols 保留脚本已 strip 并校验的字节；它是独立 PIE 进程，不是 JNI 共享库。

## 参数与生命周期

完整参数表和 ADB 命令见 README。显式启动必须提供 upstream_interface；listen_interface 可选；port 默认5140，maxclients 默认5，verbose 默认2。运行中和等待重试时不接受修改，请先停止再启动。

参数格式通过且核心可执行后同步保存。服务使用 START_STICKY；系统空 Intent 重建时恢复保存参数。没有开机自启。主动停止取消重试，保留参数本身不会触发启动。

核心退出或临时网卡/IPv4 缺失后按 1、2、4、8、16、32、60 秒退避；运行至少60秒后重置。缺少核心、无保存配置和非法参数会停止。监听IP在每次启动核心时解析，不提供核心仍活着时的地址切换或流量健康检查。

服务使用 connectedDevice 前台类型和 DUMP 调用权限。CPU 部分唤醒锁及组播锁在服务期间持有，停止时释放；原生进程工作目录和 TMPDIR 为应用私有缓存。supervisor 入口检查 Java 父 PID 并设置 PR_SET_PDEATHSIG，worker 保留上游父进程死亡逻辑。

## 必须继续验证的边界

1. 真实 NDK 编译及 SDK/R8 Release 打包已通过；继续在 Gradle 正常运行的环境验证完整任务图、Debug/Release 与 lint。
2. 检查安装后 nativeLibraryDir 提取、权限、ELF 执行和前台服务启动。
3. 在真实 IPTV 网络验证组播、FCC、RTSP/HTTP 的实际可用范围；仅端口可访问不代表转发成功。
4. 输入网卡选择不负责运营商鉴权、VLAN 或路由；监听某网卡IP不等于强制回包走该网卡，免Root网络绑定行为必须实测。
5. 杀死Java宿主、停止supervisor、强制终止和系统回收恢复时，核对全部worker、端口、共享内存文件和锁释放情况。
6. 验证熄屏、待机、断网恢复和至少24小时转发，记录APK大小、安装占用、核心大小和运行内存。

上游 Release 中的 `.apk` 来自 OpenWrt SDK，不是 Android 应用；也不能把 Linux/musl ARM64 二进制直接当成通过Android验证的核心。
