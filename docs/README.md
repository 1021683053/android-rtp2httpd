# 中文文档中心

[返回项目首页](../README.md)

本文档按使用者的任务组织。先安装使用，再按需要阅读配置说明；自行构建或维护项目时进入开发文档。

## 普通使用者

1. [安装与使用](usage/installation.md)：选安装包、电视首页、手机管理、开机恢复及常见问题。
2. [配置与管理接口](usage/configuration.md)：YAML 持久化、参数优先级、端口、配置应用与 HTTP API。
3. [YAML 示例](usage/config.example.yml)：字段示例。示例管理地址为回环地址，导入时需保留自己设备的 management 段。

## 构建与维护者

1. [开发环境](development/environment.md)：需要哪些已有工具、如何选择路径、构建写入哪里。
2. [本地构建与签名](development/building.md)：统一命令入口、架构选择、产物、签名、测试及离线重建。
3. [GitHub 在线构建与自动发布](development/github-actions.md)：手动构建、下载产物、签名 Secrets 与上游版本跟随。
4. [开发计划与验收](development/roadmap.md)：任务状态、验证边界、历史记录及设备测试清单。
5. [第三方依赖](../third_party/README.md)：上游锁定方式、原生适配、YAML 依赖及许可证位置。

## 文档目录约定

```text
docs/
├── README.md
├── usage/
│   ├── installation.md
│   ├── configuration.md
│   └── config.example.yml
└── development/
    ├── environment.md
    ├── building.md
    ├── github-actions.md
    └── roadmap.md
```

文档标题和说明统一使用中文，路径使用小写英文便于链接与跨平台使用。项目 README 只提供简介和快捷导航；操作步骤、配置契约与验证记录各维护一处。命令默认从项目根目录执行；API、文件名、标准协议名和第三方原始许可证保留原名。
