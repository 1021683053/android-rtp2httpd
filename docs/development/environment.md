[文档首页](../README.md) · [项目首页](../../README.md)

# 构建环境与写入边界

项目脚本只使用已有工具。缺少依赖时给出错误与配置说明，不自动安装、更新或卸载 Android SDK/NDK、JDK、CMake、Homebrew 软件，不接受许可证，不修改 shell 启动文件或全局 Git 配置。

## 必备工具

| 项目 | 要求 |
| --- | --- |
| JDK | 17，完整 JDK，包含 java、javac 与 release 版本文件 |
| Python | 3.9 或更高，无需额外 pip 包 |
| Git | 已安装；拉取固定上游源码与本地版本管理 |
| make | 已安装；CMake 的 Unix Makefiles 构建后端 |
| Android SDK Platform | android-34；不是 android-35/36 的替代选择 |
| Android Build Tools | 35.0.0，包含 aapt2、zipalign、R8/D8 与 core-lambda-stubs.jar |
| Android NDK | 28.2.13676358，目标 ARM32/ARM64，API 26 |
| CMake | 3.22 或更新，来自现有 PATH 或 SDK 的 cmake/3.22.1 |
| Gradle | Wrapper 固定 8.13，仅普通 Gradle 路径需要；SDK-only 路径不需要 |

Android CLI 是可选的人工环境准备工具，不是构建时自动调用的安装器。项目构建不会执行 android sdk install 或 sdkmanager。

## 先检查，不开始构建

```sh
python3 scripts/android.py check
```

检查会读取本地工具路径和版本，打印实际选中的 JDK、SDK、NDK、CMake。它不拉源码、不生成 APK、不安装组件。也可直接运行 `python3 scripts/android.py check --sdk-root /your/sdk`。

SDK 选择优先读取 ANDROID_HOME、ANDROID_SDK_ROOT、项目 local.properties 和已知安装目录。如果首选 SDK 不完整，会只读搜索已安装的完整 SDK；NDK 可以来自另一套已安装的 SDK。显式传入 --sdk-root 时严格使用指定目录，缺少组件即报错。

## 为单次命令指定环境

以下变量只传给本次进程及其子进程，不修改终端的永久配置。路径换成实际已经安装的位置：

```sh
env JAVA_HOME=/path/to/jdk-17 \
    ANDROID_HOME=/path/to/sdk \
    ANDROID_NDK_HOME=/path/to/ndk/28.2.13676358 \
    python3 scripts/android.py build --backend sdk
```

macOS 若没有 JAVA_HOME，脚本通过 `/usr/libexec/java_home -v 17` 查询已有 JDK 17。它不会安装 Java，也不会切换系统默认 Java。若显式选择的 JDK 版本不正确，检查会失败，用户自行选择。

也可以人工创建项目 local.properties，写入 `sdk.dir=/path/to/sdk`；该文件已忽略，不提交到 Git。脚本不会代写这份配置或用户的 .zshrc/.zprofile。

## 缺少组件时如何准备

用户自行决定安装位置和工具。可使用 Android Studio SDK Manager 或已经安装的 Android CLI。建议使用独立 SDK，避免向其他项目共用的 SDK 添加组件。

下面只是供用户按需主动执行的示例；运行它会修改指定的 SDK 目录，项目脚本不会替用户执行：

```sh
# 示例：在本项目的 .tools 中准备独立 SDK；此目录已被 Git 忽略。
android --sdk="$PWD/.tools/android-sdk" sdk install \
  platforms/android-34 build-tools/35.0.0 ndk/28.2.13676358 cmake/3.22.1
```

SDK 许可证由使用者自行处理。JDK/Python/Git/make 的安装同样由使用者选择，不提供自动执行的系统包管理命令。

准备后通过单次 ANDROID_HOME 指向新 SDK，再运行 `python3 scripts/android.py check`。已有所需版本时直接复用，无需重新安装。

## 构建会写入哪里

| 入口或目录 | 行为 |
| --- | --- |
| build/upstream/ | 缓存固定提交的上游 Git 仓库，仅修改项目内部的仓库 |
| build/native-source/ | 导出并适配上游构建副本，原始上游 checkout 不修改 |
| build/native/、app/build/、build/outputs/ | 原生编译、Java/R8、APK、映射与对应源码包 |
| .gradle/ | Gradle 的项目级状态，已被忽略 |
| build/tool-cache/gradle、build/tool-cache/android | 通过项目 Release 脚本运行 Gradle 时的默认工具缓存 |
| 操作系统临时目录 | 编译器/JVM 与临时测试可能使用普通临时文件，不代表修改系统工具安装 |

Release 入口只在本次进程及子进程中设置 JAVA_HOME、ANDROID_HOME、ANDROID_SDK_ROOT、ANDROID_NDK_HOME 和缓存路径。通过 `python3 scripts/android.py ...` 执行后不会改变调用终端的环境。

用户若显式设置 GRADLE_USER_HOME 或 ANDROID_USER_HOME，脚本尊重该路径；希望完全留在项目目录时不要将它们指向共享位置。

首次 Gradle 构建可能下载 Gradle 发行包和 Maven 构建依赖到所选缓存，它们与系统安装是两回事。使用 `build --backend sdk` 不启动 Gradle。直接运行 `./gradlew` 会使用 Gradle 自身的缓存选择规则，可能写入 ~/.gradle；应优先使用项目 Release 入口。

项目 gradle.properties 已关闭 AGP 的 SDK 自动下载和 Gradle 的 JDK 工具链自动下载。缺少 Android Platform/Build Tools/NDK/JDK 时由使用者准备，不由项目自动更改已有 SDK。


## 历史环境改动

2026-10-30 的旧版构建脚本曾在 `/opt/homebrew/share/android-commandlinetools/ndk/28.2.13676358` 安装 NDK，并更新相关 SDK 元数据。未替换系统编译器，也没有自动卸载该 NDK；后续已删除自动安装入口并关闭 SDK/JDK 自动下载。

现有记录未显示项目修改 shell 启动文件、全局 Git 配置或执行 Homebrew 安装/升级。修正后的 SDK-only 构建对选定的 SDK 元数据、许可证及常见用户配置路径进行前后对比，未观察到变化；没有初始化前的全盘快照，不能将其视为完整系统审计。
