# PostManage v2.0 (Go 高性能企业级 API 调试与压测平台)

> **基于全新产品设计说明书 (`PRODUCT.md`) 全量用 Go 重构打造的独立高性能明星产品。**
> **【架构模式】：方案二 · 原生 Win32 桌面宿主窗口直接内嵌 Edge WebView2 运行时 (Single-Process Native App)**，纯单进程运行，彻底告别外部浏览器！同时保持 **Zero CGO / 零外部 C 编译器依赖**，编译为单一独立可执行文件 `postmanage.exe`，双击直接启动独立原生软件窗口！

---

## 🌟 核心特性与创新功能

### 1. 极简高并发压测引擎 (Feature 1 - 基于 Go 原生高并发协程池)
- **极高吞吐性能**：基于 Go 原生 Goroutine 轻量级协程池，单机轻松支撑数千至数万并发。
- **平滑步进升压 (Ramp-up)**：支持阶梯式加压，真实模拟业务流量爬坡过程。
- **专业级聚合分析大盘**：
  - 秒级滑动窗口统计：**平均 TPS** 与 **峰值 Peak TPS**。
  - 精准耗时分位数：**P50 / P90 / P99 延迟分位数**。
  - 阶梯耗时区间柱状分布：`< 50ms (优)`、`50-200ms (良)`、`200-500ms (中)`、`> 500ms (慢)`。
  - HTTP 状态码分布统计与带宽吞吐计算。
- **智能性能瓶颈诊断**：根据压测指标，自动输出长尾延迟原因分析（连接池耗尽、服务端排队等）并提供针对性调优建议。

### 2. 页面接口智能嗅探与健康巡检 (Feature 2 - 一键发现并巡检后端 API)
- **一键全量发现**：输入任意 Web 页面 URL，自动获取 HTML 源码并并发拉取其引用的外链 JavaScript 脚本。
- **多引擎正则挖掘**：智能匹配并提取页面中的 `fetch(...)`、`axios(...)`、`$.ajax(...)`、RESTful API 路径。
- **并发健康巡检**：对提取出的所有后端接口进行毫秒级轻量并发探测。
- **红黄绿三色健康大盘**：
  - 🟢 **健康 (Healthy)**：HTTP 2xx 正常响应。
  - 🟡 **告警 (Warning)**：HTTP 401/403 权限限制，或响应耗时较长。
  - 🔴 **严重 (Critical)**：HTTP 404 资源缺失、500 服务端内部错误或连接超时。
- **无缝联动**：支持一键将嗅探到的接口导入到 API 调试器或直接发起高并发压测。

### 3. 全链路网络耗时瀑布流拆解 (Feature 3 - 对标 Chrome DevTools Waterfall)
- 基于 Go `net/http/httptrace` 底层精准 Hook 机制，精确记录每次请求的微秒/毫秒级耗时：
  - **DNS Lookup**：域名解析耗时。
  - **TCP Connect**：TCP 三次握手建连耗时。
  - **TLS Handshake**：HTTPS 证书握手与密钥交换耗时。
  - **Request Send**：客户端将请求头与请求体写入 socket 发送耗时。
  - **TTFB (Time To First Byte)**：等待服务器处理并返回首字节耗时。
  - **Content Download**：响应数据包体完整读取下载耗时。
- **动态占比条形图**：直观展示全链路耗时中哪个环节是主要瓶颈。

### 4. 完整的 API 调试与集合管理 (参考原系统并深度升级)
- **多方法与参数**：支持 GET / POST / PUT / DELETE / PATCH / HEAD / OPTIONS，支持 Params / Headers / Cookies。
- **多格式请求体**：支持 JSON、x-www-form-urlencoded、multipart/form-data、raw 纯文本。
- **多模式认证**：支持 Bearer Token、HTTP Basic Auth、API Key 认证。
- **全局请求头 (Global Headers)**：
  - 放置在顶部操作栏 cURL 旁，全局生效。
  - **大小写不敏感覆盖优先级**：单请求若配置了与全局同名 Key，则单请求优先覆盖！
- **双向 cURL 导入与导出**：一键生成标准多行美化 cURL 命令（自动合并全局 Header 与 Cookie），支持粘贴解析 cURL。
- **低饱和度护眼配色**：浅色背景杜绝荧光炫目刺眼，采用柔和高级灰调；支持一键切换深色暗黑主题。
- **双语国际化 (i18n)**：中英文一键无缝切换。
- **多层级集合与历史管理**：支持创建集合、接口保存与最近 500 条历史请求回溯。

---

## 📁 目录结构

```
postmanage-go/
├── cmd/
│   └── postmanage/
│       └── main.go                 # 应用程序主入口 (服务启动、优雅停机、浏览器自动拉起)
├── internal/
│   ├── api/
│   │   ├── server.go               # REST API 控制器与静态资源处理器
│   │   └── web/
│   │       └── index.html          # 纯原生、响应式 Web 控制台界面 (go:embed 内嵌)
│   ├── config/
│   │   └── config.go               # 全局配置管理 (主题、语言、全局请求头)
│   └── core/
│       ├── client/
│       │   └── http_client.go      # 高性能 HTTP 客户端 (httptrace 全链路耗时 + 全局头覆盖)
│       ├── curl/
│       │   └── curl.go             # 双向 cURL 命令行导出与解析器
│       ├── db/
│       │   └── storage.go          # 纯 Go 原子 JSON 存储引擎 (集合、接口、历史)
│       ├── models/
│       │   └── models.go           # 核心领域数据模型
│       ├── runner/
│       │   └── load_runner.go      # 极简高并发压测引擎 (Goroutine 协程池 + P50/P90/P99)
│       └── sniffer/
│           └── page_sniffer.go     # 页面接口自动嗅探与巡检引擎
├── tests/
│   ├── client_test.go              # 网络耗时拆解与全局请求头优先级测试
│   ├── runner_test.go              # 并发压测、TPS 与分位数计算测试
│   ├── sniffer_test.go             # 页面接口嗅探与健康巡检测试
│   └── curl_test.go                # cURL 导出与解析双向转换测试
├── go.mod                          # Go 模块定义文件 (纯标准库，无外部三方依赖)
└── README.md                       # 项目说明文档
```

---

## 🚀 快速开始

### 1. 编译构建可执行文件
本工程依赖 Go 1.20+（开发环境位于 `D:\apps\Go`）：

```bash
# 编译生成单二进制可执行文件
D:\apps\Go\bin\go.exe build -o postmanage.exe ./cmd/postmanage
```

### 2. 运行 PostManage
```bash
# 直接双击或命令行启动 (默认监听 8088 端口并自动唤起浏览器)
.\postmanage.exe

# 自定义端口与数据持久化目录
.\postmanage.exe -port=9000 -data=./my_data -open=false
```

启动后在浏览器打开控制台：
👉 **http://127.0.0.1:8088**

### 3. 执行自动化测试套件
```bash
D:\apps\Go\bin\go.exe test ./tests -v
```

测试覆盖全链路网络耗时拆解、全局请求头大小写不敏感覆盖、并发压测 TPS 与 P50/P90/P99 分位数、页面接口嗅探与 cURL 双向转换。

---

## 🛡️ 技术优势对比

| 对比维度 | 原 Python + Qt 方案 | 新 Go 原生方案 (`postmanage-go`) |
| :--- | :--- | :--- |
| **运行时依赖** | 需要 Python 解释器、PyQt6、第三方库等数百兆依赖 | **单二进制文件 (`~11MB`)，完全零环境依赖** |
| **并发压测性能** | 受 Python GIL 锁限制，多进程消耗资源巨大 | **基于轻量级 Goroutine 协程，单机轻松支撑万级 TPS** |
| **全链路耗时追踪** | requests 库难以获取 DNS、TCP 握手等底层指标 | **原生 `httptrace` 微秒级精准捕获各阶段网络耗时** |
| **前端呈现** | 本地 UI 渲染受限，跨平台打包易碎 | **嵌入式现代化 Web UI，全端自适应响应式布局** |
| **维护与交付** | 源码分发脆弱，打包体积巨大且容易报环境缺失 | **一键交叉编译 Windows/Linux/macOS，即拷即用** |
