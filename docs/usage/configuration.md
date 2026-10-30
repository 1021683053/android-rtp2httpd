[文档首页](../README.md) · [项目首页](../../README.md)

# HTTP 管理与 YAML 配置

同一个前台服务内运行独立管理监听器和原生核心。默认管理功能关闭；启用后即使没有上游网卡、核心缺失或转发失败，管理入口仍保留。网页和资源内置 APK，无 CDN 或前端构建依赖。

页面以手机单列布局为基础，宽度随屏幕伸缩，最大 1024px，宽屏时整体居中。右上角状态点：灰色为未启用/等待启动，红色为服务报错或连接异常，绿色为转发核心正常运行。

## 首次启用

安装签名 APK 后，可从电视桌面打开 rtp2httpd，点击“启动”。原生页面显示状态、管理地址、代理地址及启动、重启、停止三个按钮，首次无配置时自动启用 0.0.0.0:5141 管理入口；参数继续在网页配置。地址按当前配置端口展示，监听所有地址时优先显示当前网络 IP；指定代理监听网卡时显示该网卡 IPv4 地址。地址不附加“仅本机”等说明文字，未启动、未启用及等待网络时显示对应状态。

也可用下列 ADB 方式启动：先停止旧服务，将监听地址改为盒子的实际局域网 IP，无需令牌。

```sh
adb shell am stopservice -n local.rtp2httpd/.RelayService
adb shell am start-foreground-service -n local.rtp2httpd/.RelayService \
  --ez management_enabled true \
  --es management_listen 192.168.1.100 \
  --ei management_port 5141
```

浏览器打开 `http://192.168.1.100:5141/`，直接选择上游网卡，保存并应用。首次无上游网卡时显示 WAITING_CONFIG。绑定指定 IP 前应确保该地址已分配；`0.0.0.0` 表示所有 IPv4 地址，浏览器仍使用盒子的实际 IP。管理支持 IPv6 字面地址，转发核心当前仍按原有 IPv4 监听方式工作。

只在本机维护时，可省略 management_listen，默认 `127.0.0.1`，再执行 `adb forward tcp:5141 tcp:5141`，浏览器访问 `http://127.0.0.1:5141/`。

管理页和 API 已移除身份认证，不再提供令牌、登录、Cookie 会话或 CSRF Token。能连接到管理监听地址的设备可以查看配置、修改配置和控制核心；Host/Origin 校验用于阻止浏览器跨站请求，不作为访问者身份验证。无需身份认证也无需外网资源。

## 启动参数与优先级

默认值 → 私有 YAML（缺失时进行一次旧 SharedPreferences 迁移）→ 本次实际存在的 Intent extra。省略 port 不会覆盖已保存的端口。START_STICKY 的空 Intent 从 YAML 恢复。成功迁移后不再读取旧转发参数；缺失或损坏 YAML 时保留独立存储的管理绑定信息，便于修复。

| extra | 类型 | 初始默认值 |
| --- | --- | --- |
| management_enabled | `--ez` | false |
| management_listen | `--es` | 127.0.0.1 |
| management_port | `--ei` | 5141 |
| relay_enabled | `--ez` | true |
| upstream_interface | `--es` | 未设置；启用管理时允许等待配置 |
| listen_interface | `--es` | 未设置，监听所有 IPv4 |
| port / maxclients / verbose | `--ei` | 5140 / 5 / 2 |

已配置应用在 BOOT_COMPLETED 后自动启动同一个前台服务，恢复已保存 YAML；不会把已关闭的 relay.enabled 改为 true。管理 IP 尚未分配时保留前台服务并退避重试监听。首次安装尚未启动/配置的应用不自动启动，系统强行停止后的限制仍由 Android 决定。stopservice 停止本次运行，正常重启后重新按配置启动。

运行中重复 start 不替换配置。ADB 修改参数或管理入口须先 stopservice，再 start-foreground-service；网页修改转发参数不需要重启 Android 服务。停止转发通过网页完成，管理入口保留；`am stopservice` 停止整个应用服务。

## 文件与配置契约

文件均位于 `getFilesDir()` 返回的应用私有目录，无需 Root、外部存储权限或固定 `/data/...` 路径。

- `config.yml`：当前持久配置。
- `config.yml.bak`：上一次变更前的有效配置。未变更的服务重建不覆盖备份。
- `config.pending.yml`：候选暂存；重建时丢弃，绝不自动提升为有效配置。
- `.tmp`：原子替换前的写入临时文件，写入后执行文件描述符同步。

YAML 格式见 [config.example.yml](config.example.yml)。解析使用锁定的 SnakeYAML 2.6 SafeConstructor，并明确使用 Android 字段访问模式。拒绝未知键、重复键、类型标签、锚点、别名、合并键、非映射根、未知 schema、多文档及过深嵌套；最大 32 KiB，嵌套深度最大 5。配置导出是统一模型的规范化结果，注释和原始格式不会保留。

端口为 1024–65535，管理端口与转发端口不能相同；maxclients 为大于零的 32 位整数，verbose 为 0–4，workers 固定为 1。网卡名称为空值表示尚未选择或监听所有 IPv4；指定名称后暂不可用会进入重试，网页应用候选时则判定启动失败并恢复原配置。

网页首版只应用 relay 段，management 段可查看和导出；修改其启用状态、绑定地址或端口会被拒绝。管理入口切换保留在开发计划 HTTP-10，当前通过 ADB 停止后修改，避免网页操作造成失联。

覆盖安装和系统重建保留私有配置；清除应用数据或卸载会删除它们。导出 YAML 可备份转发设置；导入其他盒子的文件前，需保留当前设备的 management 段并检查网卡名。

## 应用和恢复

网页表单与 YAML 编辑器使用同一模型，切换前调用服务端校验。保存、校验、导入、恢复、重新读取及启停操作均直接执行，不显示确认框、进度或成功提示，也不在刷新/离开页面时拦截确认；只有出错时显示原因。每个写操作携带读取时的 revision，过期返回 409；操作进行中禁用按钮并拒绝其他写操作。

候选先暂存，串行停止旧核心（正常 5 秒、强制 1 秒），确认清理完成后启动新核心。10 秒内检查进程存活及本机 `/status` 返回 200，连续至少 750 ms 通过才提交。未启用转发或尚无上游网卡时保存为 STOPPED / WAITING_CONFIG。此检测证明核心启动和状态端口可用，不能证明 IPTV 转发成功。

失败时丢弃候选，恢复旧配置并按原有退避策略运行；管理页面显示失败原因。主文件损坏时读取备份，两者均损坏时仅保留管理入口等待修复。写入失败不会有意替换主文件。文件同步和原子改名已实现，真实固件断电时的文件系统持久性仍须设备验收。

ADB 启动配置按旧行为在格式校验后保存，核心网卡暂不可用可持续重试；网页候选采用上述更严格的启动检查。RUNNING 表示核心进程运行，不表示有 IPTV 流量。

## HTTP 契约

| 方法和路径 | 内容 |
| --- | --- |
| GET /api/status | 核心状态、版本、revision、操作结果、重试时间与最近错误 |
| GET /api/interfaces | 网卡及地址 |
| GET /api/config | config 对象、规范 YAML 与 revision |
| POST /api/config/validate | 原始 UTF-8 YAML，返回规范化结果，不写文件 |
| POST /api/config/apply | 原始 YAML，异步应用，202 返回 operation_id |
| POST /api/config/rollback | 应用备份，202 返回 operation_id |
| GET /api/config/export | 当前 YAML 下载 |
| POST /api/relay/start、stop、restart | 受控操作核心；停止/启动状态会保存 |
| GET /api/logs | 最近 256 行，每行最多 512 字符，常见凭据字段脱敏 |

所有接口均可直接访问，不要求 Authorization、Cookie 或 X-CSRF-Token。应用、回滚及核心控制仍需要 `If-Match`，值为 GET config 返回的 revision（不带引号）。202 仅表示接受，轮询 status 中相同 operation.id 的 done/outcome 判断最终结果。旧 /api/session 接口已移除，返回 404。

Host 必须是当前本地监听 IP 和端口（本机也可用 localhost），Origin 如果存在必须与 HTTP Host 同源；拒绝跨站 API 请求、DNS 主机名与开放 CORS；允许从外部链接正常导航到管理首页。第一版不支持域名反向代理。请求头最大 8 KiB、单行 2 KiB、请求体 32 KiB，读取期限 5 秒，连接总期限 10 秒。最多 4 个处理线程与 16 个排队请求。拒绝重复头、Transfer-Encoding、Expect 及非法 UTF-8。

## 验证

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/android.py test
python3 scripts/android.py build --backend sdk
```

主机测试需要已有 JDK 17，以及 Gradle 缓存中的 JUnit 4.13.2 / Hamcrest 1.3，不会自动下载或更改安装环境。测试范围及设备待验项集中维护在 [开发计划与验收](../development/roadmap.md)。

电视首页的“管理地址”和“代理地址”后各有独立状态灯：绿色表示管理监听已建立或代理核心运行，红色表示管理监听失败或代理报错/重试，灰色表示未启用、未运行或等待启动。停止代理时管理灯可以保持绿色。
