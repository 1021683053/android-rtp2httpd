# 初始化与构建环境改动核查

核查依据是项目脚本、现有 Git 状态、用户提供的执行日志和当前文件时间信息。没有初始化前的完整系统快照，因此本报告区分已确认事项与无法完整追溯的缓存/元数据，不声称列出了系统中的每一次写入。

## 已确认的行为

| 内容 | 位置与证据 | 性质 |
| --- | --- | --- |
| 根 Git 仓库已创建，文件已暂存，首次提交尚未完成 | git status 显示 No commits yet on main，32 个新增暂存文件；没有远程地址 | 只涉及项目 .git 和索引 |
| 安装 NDK 28.2.13676358 | 用户日志包含 sdkmanager --sdk_root=/opt/homebrew/share/android-commandlinetools ndk;28.2.13676358；该目录 source.properties 创建于 2026-10-30 11:03:29 | 旧构建脚本向共享 SDK 增加工具，确实改变了项目外目录 |
| SDK 管理元数据和安装临时目录存在本次时间的更新 | /opt/homebrew/share/android-commandlinetools/.knownPackages 修改于 2026-10-30 10:41:14，.temp 目录修改于 11:03 | 与 SDK 安装过程相符；无前后内容快照，不能列出每个内部元数据字节的变化 |
| 生成源码缓存和编译/打包输出 | 项目 build/、app/build/、.gradle/ | 项目内部构建数据 |
| 使用临时构建/验证目录 | /private/tmp/android-rtp2httpd-check、/private/tmp/android-rtp2httpd-gradle 等测试/构建临时目录 | 临时输出；不是系统软件升级 |

NDK 中的 Clang、链接器、strip 和配套头文件属于新增 NDK 目录，不表示替换了 /usr/bin/clang 或系统 C 库。

## 不应混淆的事项

- Git 初始化过程没有调用 SDK 安装器。共享 SDK 的新增 NDK 来自旧版构建脚本的 --install-tools 路径。
- 脚本中的 export 仅作用于脚本及子进程。它没有向 .zshrc、.zprofile、.bashrc 或系统环境设置写入配置，也没有执行 git config --global。
- 当前 SDK 35/36、Build Tools 35.0.0、platform-tools 的所查 package.xml 时间早于本次 NDK 安装；现有记录没有显示这些版本被本项目升级。
- 所查 SDK 许可证文件的修改时间为 2026-10-18/19；脚本没有自动接受许可证的命令。不能据此推断用户在其他操作中从未处理过许可证。
- ~/.android/cli/bundles/lock 的所查时间为 2026-10-19。代理尝试调用 Android CLI 帮助时遇到该锁的权限拒绝，没有成功执行 CLI 更新命令。
- Gradle 正常执行可能写 ~/.gradle 等缓存；代理多次执行在用户缓存写锁或本地 socket 处失败。用户在本机运行过的 Gradle 构建可能产生缓存，现有记录不足以精确归属每个文件。
- 脚本没有执行 sudo、系统包升级、Homebrew 安装/升级或自动卸载 SDK 组件。

## 本次修正

- 删除自动安装 SDK/NDK/CMake 的代码与 --install-tools 入口，缺少组件时只报告要求和文档位置。
- 增加 --check-only 检查，先验证环境，再拉源码和开始编译。
- 缺失工具测试确认不会调用安装器，也不会先创建源码下载缓存。
- 关闭 AGP SDK 自动下载与 Gradle JDK 工具链自动下载。
- 项目 Release 入口将默认 Gradle/Android 工具缓存放在项目 build/tool-cache/，不主动改写用户已有 SDK 或永久环境配置。
- 环境要求、单次变量配置、用户自行选择独立 SDK 的准备方法见 [ENVIRONMENT.md](ENVIRONMENT.md)。

已安装的共享 NDK 在本次核查中保留；没有自动删除或回滚项目外目录。

修正后实际执行了完整 SDK-only 构建并通过 APK 核心校验。构建前后对比了 18 个选定路径的存在状态、大小、mtime/ctime，覆盖共享 SDK 包元数据、许可证、常见 shell 配置、全局 Git 配置与 Android CLI 锁文件，未观察到变化。20 项脚本测试通过。这些检查不等于全盘文件系统审计，也不补足历史初始化前缺失的快照。
