# Android rtp2httpd

用于长期通电机顶盒的 IPTV 转发服务：把 RTP/UDP 等上游流转为 HTTP 访问，提供电视桌面入口、手机网页管理和私有 YAML 配置。

支持 ARM32（armeabi-v7a）和 ARM64（arm64-v8a），最低 Android 8.0；x86/x86_64 不在当前支持范围。原生核心版本由 [版本锁](third_party/rtp2httpd.lock.json) 固定；自动发布构建跟随上游正式 Release。

## 安装后怎么用

1. 安装已签名 APK，可通过 U 盘或文件管理器完成。
2. 从电视应用列表打开 rtp2httpd，点击“启动”。
3. 用同一局域网的手机访问首页显示的管理地址，选择上游网卡并保存。
4. 使用代理地址和对应的流路径播放。默认管理端口为 5141，代理端口为 5140。

首页提供运行状态、管理/代理地址及启动、重启、停止按钮；配置在网页完成。首次通过桌面启动时启用局域网管理；已有配置按原设置恢复。保存和控制操作直接执行，仅错误时提示。

## 中文文档

从[文档首页](docs/README.md)选择所需内容：

| 要做的事情 | 文档 |
| --- | --- |
| 安装、首次启动、重启恢复、排查无法访问 | [安装与使用](docs/usage/installation.md) |
| 网页管理、YAML 字段、启动参数和 HTTP API | [配置与管理接口](docs/usage/configuration.md) |
| 准备 JDK/SDK/NDK，了解构建写入边界 | [开发环境](docs/development/environment.md) |
| 本地编译、签名、测试、离线重建 | [构建与签名](docs/development/building.md) |
| 在线 Actions 构建、签名 Secrets、跟随上游发布 | [GitHub 自动化](docs/development/github-actions.md) |
| 当前进度、验证记录和后续任务 | [开发计划与验收](docs/development/roadmap.md) |
| 上游版本、依赖来源及许可证 | [第三方依赖](third_party/README.md) |

## 本地构建快捷入口

先按[开发环境说明](docs/development/environment.md)准备已有工具。项目脚本不自动安装或修改本机工具。

```sh
python3 scripts/android.py check
python3 scripts/android.py build --backend sdk
```

默认生成 ARM32、ARM64 独立包及双架构通用包，均需签名后安装。完整命令、输出位置及签名步骤见[构建说明](docs/development/building.md)。

当前 26 项 JVM 和 30 项 Python 测试、SDK-only 多架构及离线源码构建通过，ARM64 电视模拟器已验证。GitHub 在线构建及签名发布已通过，可[下载 v3.17.2 安装包](https://github.com/1021683053/android-rtp2httpd/releases/tag/android-v3.17.2)；后续每 6 小时检查上游正式 Release。ARM32 实机、真实 IPTV 长跑及完整 Gradle 仍待验收，详见开发计划。
