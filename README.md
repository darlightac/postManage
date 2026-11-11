# PostManage — 现代化本地优先、Go双引擎高并发 API 研发与性能工程工作台

[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11%20(x64)-blue.svg)](https://github.com/)
[![Local--First](https://img.shields.io/badge/Architecture-Local--First%20%7C%20Zero--Cloud-success.svg)](https://github.com/)
[![Engine](https://img.shields.io/badge/Core-Python3.14%20%2B%20Go%20Goroutine-orange.svg)](https://github.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> **告别云端绑架与内存黑洞：** 一款将 **「API 精细调试 + 真机浏览器动态嗅探 + Go 协程万级并发压测 + 本地 Mock 中心」** 融为一体的现代化本地优先桌面工作台。数据完全私有，纯离线可用。

---

## 📖 核心文档导航

- 📘 **[软件全景产品介绍与核心特色详述 (SOFTWARE_INTRO.md)](file:///c:/Users/18335/PycharmProjects/postManage/SOFTWARE_INTRO.md)**：包含抓眼标题方案库、8 大核心杀手级特性、主流工具深度横向对比及典型业务场景。
- 📗 **[全功能产品设计说明书 (PRODUCT.md)](file:///c:/Users/18335/PycharmProjects/postManage/PRODUCT.md)**：包含完整技术架构、Go 内核工程规范与各子系统深度设计。

---

## 🌟 核心功能一览

- **⚡ Local-First 数据纯私有** — 零注册登录，无任何公有云依赖与遥测，所有请求、历史与凭据均存储在本地 SQLite 数据库中。
- **🚀 Python + Go 混合双引擎** — 前端 PyQt6 提供丝滑细腻的桌面交互，底层内嵌 Go 原生协程引擎，微秒级调度，单机秒开万级并发压测。
- **🔍 CDP 真实浏览器动态嗅探** — 免配证书、免改全局代理，一键唤起真实 Edge / Chrome 浏览器登录，自动拦截并继承 SPA 页面全量 API、Post 数据与 HttpOnly Cookie 凭据。
- **🎯 首创全页面事务级压测** — 以真实用户页面访问为事务单位，严格统计页面平均加载时长、整页成功率与慢接口耗时排行。
- **📊 工业级压测分析看板与离线 HTML 报告** — 实时呈现 **吞吐量 (Throughput)**、**TPS**、**QPS**、**平均请求时间 (RTT)**、**P50/P90/P99 延迟分位数** 与 **网络传输带宽 (KB/s)**，支持一键导出自包含矢量 SVG 时序图表的离线 HTML 报告。
- **🎭 嵌入式轻量 Mock 服务中心** — 本地一键启停多线程 HTTP Mock 服务，支持通配符与正则路由，请求实时监控，窗口支持独立最小化后台静默运行。
- **🌐 全场景企业网络代理矩阵** — 直连、系统代理、自定义 HTTP/HTTPS/SOCKS5 代理以及 PAC 自动化动态分流脚本深度支持。
- **🌊 大模型流式输出 (SSE) 智能提取** — 针对 OpenAI、Claude、DeepSeek 等大模型增量对话流，自动剥离前缀并支持 JSONPath 实时结构化提取。
- **🌊 全链路耗时瀑布流 (Timing Waterfall)** — 毫秒级精准拆解 DNS 查询、TCP 握手、TLS 协商、首包 TTFB 与数据传输阶段。
- **🗕 窗口自由度革新** — 压测、嗅探、明细图表及 Mock 中心均赋予独立最小化/最大化控制，解耦模态阻塞，测试与调试同时进行。

---

## 快速开始

### 依赖环境
- Python 3.10+
- Go 1.20+ (仅二次开发编译引擎需要，直接使用发布包无需安装)

### 源码启动
```bash
# 1. 安装 Python 依赖
pip install -r requirements.txt

# 2. 编译 Go 原生引擎 (可选，发布包内已内置)
cd postmanage-go
go build -ldflags="-s -w" -o ../app/bin/postmanage-engine.exe ./cmd/engine
cd ..

# 3. 启动应用
python main.py
```

### 构建交付二进制包
```bash
# 目录免安装绿色版
pyinstaller postmanage.spec --noconfirm

# 单文件便携版
pyinstaller postmanage_onefile.spec --noconfirm

# 自动安装向导包
pyinstaller installer.spec --noconfirm
```

---

## 开源协议

本项目基于 [MIT License](LICENSE) 协议开源。
