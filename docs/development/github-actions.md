[文档首页](../README.md) · [项目首页](../../README.md)

# GitHub 在线构建与自动发布

本项目提供两份工作流，职责分别如下：

| 工作流 | 触发方式 | 上游版本 | 输出位置 |
| --- | --- | --- | --- |
| Build Android APK | 手动、main/master 推送、Pull Request | 当前分支版本锁 | 本次运行的 Artifacts |
| Build upstream release | 每 6 小时检查、手动 | 上游最新正式 Release | GitHub Releases |

工作流文件位于 [.github/workflows](../../.github/workflows)。它们必须先推送到 GitHub 仓库；本地存在 YAML 不代表云端已启用。手动构建需要工作流存在于默认分支；首次使用时在仓库 Actions 页面检查是否允许运行。

## GitHub 自动跟随上游 Release

`.github/workflows/upstream-release.yml` 每 6 小时检查一次 stackia/rtp2httpd 的最新正式 Release，也可手动运行。已发布的 `android-v<上游版本>` 会跳过。工作流解析 tag 对应提交，更新临时构建副本中的版本锁、应用版本及状态版本，生成 ARM32、ARM64、通用签名包、对应源码和 SHA256SUMS，再发布 GitHub Release。版本码按 major×1000000 + minor×1000 + patch 递增；不自动修改仓库默认分支。 签名前逐一检查三种 APK 的 Manifest 应用版本和版本码，以及核心构建元数据的版本与提交；不匹配时停止发布。

先将仓库推送到 GitHub，并在 Settings → Secrets and variables → Actions 配置：

- `RELEASE_KEYSTORE_BASE64`：现有 PKCS12 签名文件的 Base64 内容。
- `RELEASE_KEYSTORE_PASSWORD`：签名文件密码。
- `RELEASE_KEY_ALIAS`：密钥别名，本地现有别名为 rtp2httpd。

必须复用现有签名才能覆盖升级。Secrets 的值不能写入仓库、工作流 YAML 或构建日志。工作流不会随机创建密钥；缺少 Secret、上游适配失败或验证失败时停止发布。SDK 安装仅发生在 GitHub 临时 runner，不修改开发者电脑。GitHub 定时任务在默认分支运行，执行时间可能延迟；需确保 Actions 已启用。

## GitHub 在线手动构建

推送工作流到默认分支后，打开 Actions → Build Android APK → Run workflow，选择分支及 `universal`、`armeabi-v7a` 或 `arm64-v8a`。构建使用所选分支中锁定的上游版本；跟随最新上游发布使用另一个 Build upstream release 工作流。

构建成功后在该次运行的 Artifacts 下载 APK、对应源码和校验和，保留 30 天。默认输出未签名 APK，安装前需签名；勾选签名选项会使用上述三个 Release Secrets，同时提供 signed.apk。缺少 Secrets 时签名构建明确失败，不创建临时随机签名。main/master 推送及 Pull Request 也会自动构建未签名包进行检查，不会发布 GitHub Release。

## 第一次使用的顺序

1. 将项目推送到自己的 GitHub 仓库默认分支，启用 Actions。
2. 先运行 Build Android APK，使用 universal、不勾选签名，确认能够生成未签名产物。
3. 在仓库 Actions Secrets 配置现有签名信息，再手动运行签名构建。
4. 下载 signed.apk 并在目标盒子测试覆盖升级；同时保存对应源码和 SHA256SUMS。
5. 确认自动发布工作流可运行，由定时检查跟随上游版本。

## 失败时检查哪里

- 未出现 Run workflow：检查工作流是否已在默认分支、是否启用 Actions、账号是否具有运行权限。
- SDK/原生适配失败：展开 Prepare CI SDK / Test and build 日志；上游代码结构变化可能需要人工调整 source.py 的适配，失败时不会发布。
- 签名失败：检查三个 Secret 是否齐全，别名和密码是否属于同一个 PKCS12 文件。
- 定时任务没有新 Release：相同 android-v 版本会跳过；还需检查定时任务是否启用及最近一次执行日志。
- 下载未签名包无法安装：选择 signed.apk，或按[本地签名说明](building.md)签名后安装。

2026-10-31 已完成[云端构建与签名发布验收](https://github.com/1021683053/android-rtp2httpd/actions/runs/41161753130)，上游最新正式版 v3.17.2 对应的[Android Release 已发布](https://github.com/1021683053/android-rtp2httpd/releases/tag/android-v3.17.2)。ARM32、ARM64、通用包均已下载复核：Manifest 版本 3.17.2、版本码 3017002、核心版本与提交均匹配，签名证书与本地已有签名相同，SHA256SUMS 校验通过；对应源码不含签名文件。

Runner 初始化显式安装 platform-tools，避免请求已下架的 tools 包；后续步骤显式选择 NDK 28.2.13676358，避免误用 Runner 预设的其他 NDK。普通推送构建同样已通过。三个 Release Secrets 已配置，定时发布工作流处于 active 状态。
