[文档首页](../README.md) · [项目首页](../../README.md)

# 开发计划与验收

`[x]` 表示实现或对应主机检查已完成，`[ ]` 表示待开发或待验证。主机测试、Android 实机测试与真实 IPTV 验收分别记录，不能互相替代。

使用方式见 [项目首页](../../README.md)，配置/API 契约见 [HTTP 管理说明](../usage/configuration.md)，环境要求与写入边界见 [ENVIRONMENT.md](environment.md)。

## 范围与约束

- 面向长期通电的 ARM32/ARM64、API 26+ 机顶盒，不增加手机电池优化申请流程。
- 同一个前台服务承载管理监听与原生核心；核心失败或停止时管理入口保留。
- 管理功能须显式启用，管理页/API 无身份认证，管理端口与流媒体端口分离；保留原有 ADB 参数及默认值。
- YAML 由统一配置模型解析后生成独立 argv，核心固定 --noconfig/--workers 1；不接受任意命令、可执行路径或文件编辑。
- 网页资源内置，依赖有版本锁/哈希/许可证，Gradle 与 SDK-only 产物一致。
- 不自动安装、升级或修改使用者的开发工具和永久环境；默认缓存与输出留在项目目录。

## 阶段任务

### P0：Git 与基线固定

- [x] `GIT-01` 在项目根目录初始化标准 Git 仓库，默认分支 main，创建包含现有源码和本计划的首次提交。
- [x] `GIT-02` 忽略构建缓存、下载的上游仓库、APK/原生构建输出、本机 SDK 配置、IDE 缓存、签名密钥及本地配置。
- [x] `GIT-03` 检查首次提交只包含项目源码、Gradle Wrapper、脚本、文档和版本锁；确认根仓库与 build/upstream 缓存互不混淆。
- [x] `GIT-04` 验证干净工作区、可查首次提交与分支；没有远程仓库地址时仅完成本地版本管理。

基线提交为 89180b6，HTTP 开发开始时 main 工作区干净；构建产物与凭据不受跟踪。

### P1：统一配置模型与 YAML 持久化

- [x] `CFG-01` 引入统一不可变配置模型，区分 management 与 relay；复用现有参数校验。
- [x] `CFG-02` 确定轻量 YAML 解析/序列化方案，记录依赖、许可证与 APK 体积变化。
- [x] `CFG-03` 使用 getFilesDir() 存储 config.yml；不写死 /data/user/0 路径，不使用 cacheDir 保存持久配置，不要求 Root 或外部存储权限。
- [x] `CFG-04` 设计原子写入及持久化协议：校验后写临时文件，成功应用后提交；保留上一份可用配置 config.yml.bak；处理中断时可恢复。
- [ ] `CFG-05` 实现首次安装默认配置、文件缺失、损坏、磁盘不足、写入失败和不支持 schema 的处理；错误不得覆盖上一份可用配置。
- [x] `CFG-06` 从现有 relay SharedPreferences 一次性迁移；保留迁移完成标记，避免每次启动重复覆盖 YAML。
- [x] `CFG-07` 实现默认值/YAML/显式 Intent 合并，并保持原有 ADB 参数名和取值边界。
- [x] `CFG-08` 定义配置 revision：读写带版本，拒绝网页多标签页或并发请求覆盖更新后的配置。
- [x] `CFG-09` 提供纯数据的 YAML 示例和字段说明；明确重启/覆盖升级保留配置，卸载与清除数据删除配置，网页导出用于备份。

验收：保存端口 8080 后，重建服务仍为 8080；未传 port 的 Intent 不会还原为 5140；旧配置可迁移；非法 YAML 和写入失败保留原数据；应用在无存储权限、无 Root 下可完成读写。

### P2：管理 HTTP 与服务状态控制

- [x] `HTTP-01` 在现有前台服务中增加独立的管理 HTTP 监听器，支持配置管理地址/端口，区分管理端口和转发端口。
- [x] `HTTP-02` 管理监听不依赖核心成功启动；未配置上游网卡、核心缺失、核心退出和重试时仍可访问配置/状态页。
- [x] `HTTP-03` 定义显式启用管理功能的 ADB extra；兼容未启用时原有行为。启用后即可直接访问，无需令牌。
- [x] `HTTP-04` 按当前需求移除管理令牌、登录、会话及身份认证接口；旧凭据在服务启动时清理。
- [x] `HTTP-05` 防止跨站写操作，验证 Origin/Host 与会话，禁用开放式 CORS；限制请求体、请求头、读取超时和并发数。
- [x] `HTTP-06` 统一管理 STOPPED、WAITING_CONFIG、STARTING、RUNNING、RETRY_WAIT、APPLYING、ERROR 等状态，单一控制通道串行修改核心状态。
- [x] `HTTP-07` 核心停止、启动、重试和新配置应用互斥；旧进程结束前不得启动替代进程，旧退出回调不得停止新实例。
- [x] `HTTP-08` 提供有界日志缓冲与最近错误；限制内存和响应大小，敏感字段脱敏。
- [x] `HTTP-09` 主动停止整个 Android 服务时关闭管理端口、取消队列/重试、清理进程并释放锁；单独停止转发时保留管理入口。
- [ ] `HTTP-10` 管理地址/端口修改单独处理：成功绑定新监听器后再切换，失败保留旧入口；页面显示新地址，避免普通转发参数修改导致失联。

API 路径与请求契约统一维护在 [HTTP 管理说明](../usage/configuration.md)。

验收：核心崩溃和非法配置不会导致管理页退出；停止转发仍能修改配置；停止整个服务后无监听端口和重试；直接访问即可读写配置，跨站浏览器请求被拒绝。

### P3：配置应用、回滚与恢复

- [x] `APPLY-01` 完成“读取 → 编辑 → 校验 → 暂存 → 应用 → 提交有效配置”的流程，不将解析成功当作运行成功。
- [x] `APPLY-02` 实现候选配置启动检测、超时与失败判定；启动失败时恢复上一份可用配置，并保留失败原因给管理页。
- [ ] `APPLY-03` 为暂存、上次成功和当前应用状态保存必要元数据，覆盖写入中断、核心退出、Java 被杀和系统重建的恢复顺序。
- [x] `APPLY-04` 转发参数采用受控重启；所有操作直接执行，无确认、进度、成功或离页提示，仅出错时提示；不承诺无缝热重载。
- [x] `APPLY-05` 防止回滚和自动重试形成无限切换；失败状态可见，用户可手动修复或停止转发。
- [x] `APPLY-06` 保持原有 START_STICKY、CPU 锁续租和网卡恢复行为；管理页空闲时不意外启动已被主动停止的核心。
- [x] `APPLY-07` 迁移后 YAML 成为持久配置来源，清理重复的 SharedPreferences 读写路径，必要恢复元数据除外。

验收：端口占用、网卡无地址、核心启动后立即退出、保存时断电等情况下，管理入口可达，已保存与实际运行状态可区分，能够回滚到上一份可用配置。

### P4：管理网页

- [x] `WEB-01` 静态 HTML/CSS/JS 内置 APK，离线可加载；按手机单列布局提供，宽度自适应且最大 1024px，宽屏居中，桌面原生入口显示状态、管理地址、代理地址及启动、重启、停止三个按钮，配置仍在网页完成。
- [x] `WEB-02` 页面直接进入工作区，连接异常时提示并重试，不再显示登录和退出入口。
- [x] `WEB-03` 总览显示核心状态、监听地址、上游网卡、版本及最近失败原因；右上角状态点按灰色未启用、红色报错、绿色正常显示。
- [x] `WEB-04` 常用参数表单与网卡选择，提供字段范围、当前值和默认值提示。
- [x] `WEB-05` 高级 YAML 文本编辑、校验、格式化、导入和导出；表单与 YAML 使用同一配置模型，切换不丢失修改。
- [x] `WEB-06` 保存并应用、恢复上一份配置、启动/停止/重启转发均直接执行；只有错误提示，状态在页面显示。
- [ ] `WEB-07` 显示有界日志，处理断线重连、API 超时、过期 revision 和管理地址切换。
- [x] `WEB-08` 页面展示文本安全转义；不直接将日志、配置字段插入可执行 HTML。

验收：局域网浏览器可完成首次配置和后续修改，无需修改盒子文件；网络错误有明确反馈，失败后仍能回到管理页；页面不依赖外网资源。

### P5：参数覆盖扩展

第一版管理功能先完整覆盖现有五个参数。以下是后续可配置能力清单，按真实网络需求逐组实现，不直接透传任意命令。

- [ ] `PARAM-01` 性能：UDP 接收缓冲区、缓冲池大小；记录单位、范围和内核限制。
- [ ] `PARAM-02` 专用上游网卡：组播、FCC、RTSP、HTTP 分别指定，保留通用网卡作为回退。
- [ ] `PARAM-03` FCC UDP 监听端口范围。
- [ ] `PARAM-04` HTTP/RTSP User-Agent 与 RTSP STUN。
- [ ] `PARAM-05` 转发核心自身的 Host 校验、CORS，按实际网络需求独立评估。
- [ ] `PARAM-06` IPv6、直接监听 IP、多监听地址；同时验证 Android 网卡与路由行为。
- [ ] `PARAM-07` 上游 INI、频道列表、M3U/EPG 的配置兼容方案；先确认外部下载工具在 Android 中的可用性，不能承诺上游所有功能直接可用。
- [ ] `PARAM-08` 访问日志文件与格式、状态/播放器路径、代理路径前缀等低频高级选项。
- [ ] `PARAM-09` 多 worker 仅在机顶盒实测有收益且进程清理可靠时开放；首版保持 1。

每组参数均须同时更新 schema、表单/编辑器提示、argv 或 INI 映射、迁移规则、文档和有效/无效输入测试。

### P6：构建、依赖与发布

- [x] `BUILD-01` HTTP/YAML 如引入运行时依赖，同步调整 Gradle 与 SDK-only 打包，不能让 SDK-only 静默漏包；无法支持时明确限制该模式。
- [x] `BUILD-02` 管理网页资源放入打包 assets，并确认源码包、两种构建路径、R8 keep 规则和 APK 验证器包含新增文件。
- [ ] `BUILD-03` 在可正常运行 Gradle 的环境验证依赖解析、Debug/Release、lint、单元测试与安装包内容。
- [ ] `BUILD-04` 记录 APK 压缩体积、核心大小、安装占用、空闲/转发内存与管理 API 开销，相对现有基线比较。
- [ ] `BUILD-05` 配置通过本地文件/环境注入的发布签名流程；密钥、密码、设备配置不进入 Git 或源码包。
- [x] `BUILD-06` 分发 APK 同时生成匹配的上游/Android 源码包、许可证、版本锁和构建信息。
- [x] `BUILD-07` README 更新首次启动、管理入口、默认参数、配置优先级、导入导出、重置/升级、日志与故障恢复说明。

验收：干净环境能按文档构建；产物内真实包含核心、网页与必要依赖；签名安装成功；源码包与二进制版本匹配。

### P7：机顶盒与回归验收

- [ ] `TEST-01` 配置模型：默认值、部分覆盖、旧数据迁移、未知字段、类型/范围和 schema 版本。
- [x] `TEST-02` YAML：损坏输入、别名/嵌套限制、大文件、导入导出、敏感字段处理。
- [ ] `TEST-03` 存储：无 Root/无存储权限、文件缺失、写失败、磁盘不足、原子替换中断与备份恢复。
- [ ] `TEST-04` HTTP：直接访问读写、旧会话接口移除、跨站请求、并发写入、版本冲突、请求大小和慢连接限制。
- [ ] `TEST-05` 生命周期：重复启动、启动与停止竞态、网页应用与自动重试并发、旧回调隔离、整个服务停止清理。
- [ ] `TEST-06` 设备安装与 nativeLibraryDir 提取/可执行权限；Android 8/API 26 与至少一台较新 Android 盒子验证。
- [ ] `TEST-07` 真实网络组播/FCC/RTSP/HTTP 功能及输入输出网卡组合；不以端口可访问代替流媒体验证。
- [ ] `TEST-08` 核心退出、Java 宿主被杀、系统回收、前台服务重建和全部 worker/端口释放。
- [ ] `TEST-09` 网卡临时消失、IP 变化、断网恢复、待机/熄屏和至少 24 小时转发。
- [ ] `TEST-10` 覆盖升级保留 YAML 与迁移版本；清除数据/卸载后的初始状态符合文档。
- [ ] `TEST-11` 分别记录单元测试、主机打包验证、Android 设备测试与真实 IPTV 验收结果。

设备操作步骤见下方验收清单。

## 验证状态

当前汇总：26 项 JVM 测试、30 项 Python 测试及 ARM32/ARM64/通用 SDK-only 构建通过，离线源码构建通过；ARM64 电视模拟器已验证首页、管理功能及重启恢复。ARM32 实机、真实 IPTV、24 小时长跑、完整 Gradle 尚未完成验收；GitHub 云端签名发布已验证通过。以下带日期和包体积的内容是历史批次记录，不代表当前产物大小。

- [x] ARM32/ARM64 构建：支持 armeabi-v7a 与 arm64-v8a 的独立 APK 和双架构通用 APK，按架构验证 ELF、Android 动态链接器及核心哈希；`--abi` 支持单独选择架构，防止混入缓存的其他架构核心。
- [ ] ARM32 实机验收：在 API 26+、支持 armeabi-v7a/NEON 的盒子上验证安装、核心启动、真实组播转发及重启恢复；现有模拟器仅支持 arm64-v8a，不能代替此项。

2026-10-31 多架构验证：25 项 Python 构建测试通过；ARM32 核心 555904 字节、ARM64 核心 629248 字节，均为 API 26 的 Android PIE。分别执行 ARM32、ARM64 单架构构建，确认清除另一架构的缓存输出；再完成通用及两种独立 APK 的 SDK-only 构建与同一密钥签名。签名包大小分别为通用 1193582、ARM64 738849、ARM32 722467 字节。通用包覆盖安装至 ARM64 电视模拟器后，primaryCpuAbi=arm64-v8a，核心 /status 返回 200，管理配置及 revision 完全保留。完整 Gradle 检查仍在 FileLockContentionHandler 创建 socket 时受沙箱限制，尚未完成 Gradle 分包构建验收。

- [x] 电视桌面入口：普通 Launcher 与 Leanback Launcher 图标可发现，原生界面左上角显示管理地址和代理地址，中央保留状态及启动、重启、停止三个按钮；遥控器导航、控制与网页状态同步已验证，无配置项、确认框或成功提示。启用与停止两种状态分别实际重启，图标/入口/按钮仍有效，后台由 BOOT_COMPLETED 自动恢复，配置完全一致；退出原生页不停止后台。

2026-10-31 主机记录：24 项 JVM 测试、22 项 Python 构建测试通过；NDK ARM64/API 26 编译及 SDK-only aapt2/R8/zipalign Release 通过。APK 约 545.0 KiB，核心 629248 字节。具体覆盖范围由 app/src/test 和 scripts/tests 中的测试维护。

网页已用模拟接口验证表单设置端口 8080、保存完成、YAML 往返及桌面/手机布局，无脚本异常或横向溢出；不代表浏览器到 Android 服务的真实联调。

完整 Gradle 此前在沙箱的文件锁通信 socket 处失败；主机监听套接字仍受限。模拟器经 ADB 转发的真实 HTTP 已验证，慢连接与压力测试仍未执行。旧 SharedPreferences 实际迁移、覆盖升级、断电/磁盘不足、原生进程树、真实 IPTV 及 24 小时长跑仍待验证。

Android 14/API 34 ARM64 电视模拟器已安装本地签名 Release，确认前台服务、管理页面可用。已实现 BOOT_COMPLETED 接收器及保存配置恢复。真实 adb reboot 后确认 sys.boot_completed=1，系统记录 allowStartForeground=BOOT_COMPLETED、recentCallingPackage=local.rtp2httpd、isForeground=true；仅重建 ADB 端口转发后 API 返回 200，重启前后完整配置及 revision 一致，无手动启动服务。该次测试保存的上游为空，后台恢复后保持 WAITING_CONFIG。START_STICKY 的系统回收恢复与整机重启分别验收。

- [x] 修复 Release 的 SnakeYAML NodeId 枚举 values() 被 R8 裁剪导致的配置应用错误；增加枚举反射方法保留规则，模拟器上真实 YAML 校验/保存通过。
- [x] 按当前需求移除令牌认证：24 项 JVM、22 项 Python 测试通过；真实浏览器直接进入工作区，YAML 格式化及保存成功；无 Cookie 的读取返回 200，旧会话接口返回 404，跨站 API 写请求返回 403。

HTTP-10 暂未实现，网页明确拒绝修改 management 段，现通过 ADB 停止后修改。CFG-05、APPLY-03、WEB-07、BUILD-04 和 TEST-01/03/04/05 已有部分实现或主机覆盖，待相应完整验收后再勾选。

## 设备验收步骤

1. 安装签名 APK，核对 nativeLibraryDir 提取及执行权限；启用管理后先不配置上游，确认能直接打开并保存。核心缺失或失败时管理页仍应可达。
2. 运行中及等待重试时重复 start，只保留原配置和一组 supervisor/worker。网页保存/启停/回滚应互斥，旧核心未结束前不创建替代进程。
3. 使用临时不可用的网卡启动，确认 1、2、4、8、16、32、60 秒退避，网卡和 IPv4 恢复后启动；连续运行 60 秒后重试间隔重置。
4. 占用候选端口、使用无地址的网卡或令候选核心立即退出，确认应用失败、旧 YAML 保留、旧核心恢复且管理页可用。另测主文件损坏读备份、写满磁盘和保存期间断电。
5. 在可调试/root 测试盒子中杀死 Java 宿主来模拟系统回收，不使用 force-stop/stopservice 代替。确认 supervisor/worker 随宿主结束，START_STICKY 重建后读取 YAML；恢复延迟由固件决定。
6. 分别在运行、重试和启动期间执行 stopservice，观察至少 70 秒，无新进程或重试，管理/转发端口及锁均释放；通过 dumpsys power/wifi 核对 CPU/组播锁。网页只停止转发时管理入口继续可用。
7. 持续拉取真实组播/FCC/RTSP/HTTP 流，验证输入/监听网卡组合、待机/熄屏、断网恢复和至少 24 小时运行，记录内存、丢包及进程数。监听某网卡 IP 不等于强制回包走该网卡；端口可访问不等于流媒体正常。
8. 覆盖升级保留配置，清除数据/卸载后回到初始状态；正常重启后按保存配置自动恢复，已关闭的转发保持关闭；用户强行停止遵循 Android 的广播投递限制。

## 后续候选

以下已纳入规划记录，但不属于首版默认交付，也不因此自动扩大实施范围：

- [x] 开机自启：配置过的应用在 BOOT_COMPLETED 后自动恢复同一前台服务，使用已保存的启用状态和参数；管理 IP 未就绪时退避重试。Android 14 电视模拟器重启验证通过，其他固件/API 26 及真实 IPTV 继续按设备验收清单验证。
- [ ] 核心存活但无流量的健康检测：区分无人观看、上游静默和真实故障，避免误重启。
- [ ] 网络地址变化后的自动重新绑定与路由适配。
- [ ] 裁剪上游内置播放器/网页，保留管理页和必要状态能力，重新测量体积。
- [ ] 视频快照/FFmpeg：仅在明确需要时考虑，不作为轻量服务默认依赖。
- [ ] 在线升级、外网管理、多人角色与设备集中管理：另行设计后再决定，不混入首版管理接口。

## scripts 重构实施记录

统一入口为 `python3 scripts/android.py`，内部模块位于 `scripts/android_build/`，测试按职责位于 `scripts/tests/`。Python 文件统一 snake_case，删除旧 Shell/Python 命令入口，不保留转发脚本。

| 任务 | 当前命令 |
| --- | --- |
| 检查已有环境 | `python3 scripts/android.py check` |
| 默认 Gradle Release | `python3 scripts/android.py build` |
| SDK-only Release | `python3 scripts/android.py build --backend sdk` |
| 单独 ARM32 | `python3 scripts/android.py build --backend sdk --abi armeabi-v7a` |
| 仅编译核心 | `python3 scripts/android.py native` |
| 仅打包已有核心 | `python3 scripts/android.py package` |
| 查找路径 | `python3 scripts/android.py locate sdk` / `locate ndk` |
| 拉取固定源码 | `python3 scripts/android.py source fetch` |
| 校验 APK | `python3 scripts/android.py verify <APK>` |
| 校验 Java 依赖 | `python3 scripts/android.py dependencies check` |
| 全部主机测试 | `python3 scripts/android.py test` |
| 仅 Python 测试 | `python3 scripts/android.py test --python-only` |

Gradle 参数通过 `build -- --offline` 传递；保留 SDK/NDK/JDK 环境变量及 `--sdk-root`、`--source-dir`、`--abi`。模块导入不读取版本锁、不创建目录、不启动外部工具，入口显式创建 Project 上下文。版本锁为 ABI 支持集合的唯一来源。

- [x] `SCRIPT-01` 沿用 26 项 JVM 与 25 项 Python 既有行为测试及现有 APK 内容校验。
- [x] `SCRIPT-02` 提取 project/environment/dependencies/elf，环境发现不再依赖打包或编译模块。
- [x] `SCRIPT-03` 拆分 source/native/apk/verification，源码缓存指纹覆盖全部新模块及原生适配文件。
- [x] `SCRIPT-04` 用单一 Python CLI 编排流程、控制子进程环境与项目缓存。
- [x] `SCRIPT-05` 拆分测试并增加跨工作目录、空格路径、非法 ABI/后端参数、无 SDK 帮助及模块导入无副作用检查。
- [x] `SCRIPT-06` 同步迁移 Gradle task、两份 Actions、文档、错误提示和源码归档。
- [ ] `SCRIPT-07` 完成所有环境验收：本地主机测试、SDK-only 分包、离线源码及单 ABI 切换逐项记录；完整 Gradle 与 GitHub 云端构建需分别实际执行通过，不能用 SDK-only 替代。

内部职责：project 负责上下文/版本锁及命令执行，environment 负责工具发现，source 负责固定源码/适配/归档，native 负责原生编译，apk 负责 SDK 打包，dependencies/elf/verification 各自执行校验，testing 运行主机测试。用户入口与内部模块不再混放。

签名文件、设备 YAML 与系统工具均不属于重构迁移对象。回退应针对重构变更，不改变设备配置或签名。当前改动尚未生成独立 Git 提交。

本地验收记录：26 项 JVM、29 项 Python 测试通过；真实 NDK ARM32/ARM64 编译、SDK-only 三包构建、离线源码构建及单 ABI 缓存清理通过。两份 Actions 已迁移，YAML 与 Shell 语法检查通过。Gradle 实际执行仍因 FileLockContentionHandler socket 的沙箱权限失败；GitHub SSH remote 和签名 Secrets 已配置，云端执行及签名发布已验收。旧脚本已删除，新入口与所需模块均纳入对应源码包。

GitHub 在线验收：2026-10-31，[自动跟随上游工作流](https://github.com/1021683053/android-rtp2httpd/actions/runs/41161753130) 成功拉取 v3.17.2，编译三包、校验版本、复用现有证书签名并[发布 Release](https://github.com/1021683053/android-rtp2httpd/releases/tag/android-v3.17.2)。三种下载包的 ABI、版本码、签名及 SHA-256 均复核通过。普通推送构建也通过；完整 Gradle 的验收仍保持未完成。
