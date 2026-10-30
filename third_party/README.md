# 第三方依赖与许可证

[项目首页](../README.md) · [中文文档](../docs/README.md) · [构建与离线重建](../docs/development/building.md)

## rtp2httpd 原生核心

固定来源见 [rtp2httpd.lock.json](rtp2httpd.lock.json)：

| 项目 | 当前版本锁 |
| --- | --- |
| 上游仓库 | [stackia/rtp2httpd](https://github.com/stackia/rtp2httpd) |
| Release | v3.17.2 |
| 提交 | ec7808b813d4595dff890713993bc46b82f72fc2 |
| 许可证 | GPL-2.0；构建时从上游原样复制 |

`python3 scripts/android.py native` 拉取固定 Git 提交，导出原始源码，并在独立构建副本中进行 Android 适配。核心由 Android NDK 实际编译，不使用 OpenWrt 包或桌面 Linux 可执行文件。上游预生成网页资源保持原样，无需重新安装前端依赖。

APK 中包含 `assets/rtp2httpd/LICENSE` 和 `assets/rtp2httpd/BUILD-INFO.json`。元数据按 `cores[abi]` 记录每个核心的 ELF 信息、大小及 SHA-256。通用包包含两种 ARM 架构，独立包只包含一种；Gradle 分包共享全部已编译核心的构建元数据，验证时按每个 APK 的实际 ABI 检查。

构建同时生成 `build/outputs/native/rtp2httpd-<版本>-source.tar.gz`，包含原始上游源码、Android 工程、适配脚本、测试、工作流及文档。分发 APK 时一并提供对应源码包。使用归档内源码重建的方法见[构建说明](../docs/development/building.md)。显式本地源码覆盖会记录到构建元数据中，仍需已有构建工具。

## SnakeYAML

[java/snakeyaml-2.6.jar](java/snakeyaml-2.6.jar) 对应 `org.yaml:snakeyaml:2.6`，兼容 Java 8，使用 Apache-2.0 许可证。

- 坐标、下载地址和 SHA-256：[java/dependencies.json](java/dependencies.json)。
- 原始许可证：[java/LICENSE-SnakeYAML.txt](java/LICENSE-SnakeYAML.txt)，APK 内包含对应副本。
- [上游仓库](https://github.com/snakeyaml/snakeyaml)与 [LoaderOptions API](https://javadoc.io/static/org.yaml/snakeyaml/2.6/org/yaml/snakeyaml/LoaderOptions.html)。

Gradle 和 SDK-only 使用同一份本地锁定 JAR，不在运行时下载依赖。SDK-only 排除 Java 9 多版本类。应用使用 SafeConstructor 和严格 schema，拒绝类型标签、锚点及别名；使用 FIELD 字段访问以避开 Android 缺失的 JavaBeans API。R8 仅忽略未使用的 Bean 路径中缺失的 java.beans 诊断。

更新依赖时需同步版本锁、校验和、许可证、Gradle 声明和打包方式，并执行：

```sh
python3 scripts/android.py dependencies check
```

本文为中文说明，第三方许可证文件保持原文，不修改其法律文本。
