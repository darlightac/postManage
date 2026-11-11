"""帮助文档查看器 - 内嵌 HTML 说明书 + 查找功能"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QLabel, QTextBrowser, QDialog,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from app.config.constants import APP_NAME, APP_VERSION, APP_AUTHOR, APP_LICENSE, APP_COPYRIGHT
from app.config.themes import ThemeManager
from b64_constants import _WECHAT_B64, _ALIPAY_B64


def _build_help_html() -> str:
    """构建帮助文档 HTML（图片数据已内嵌在源码中）"""
    wechat_qr = _WECHAT_B64
    alipay_qr = _ALIPAY_B64
    return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body {{
    font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 14px;
    line-height: 1.8;
    color: #333;
    max-width: 860px;
    margin: 0 auto;
    padding: 20px;
}}
h1 {{
    color: #1a1a1a;
    border-bottom: 2px solid #3b82f6;
    padding-bottom: 8px;
    font-size: 24px;
}}
h2 {{
    color: #1e3a8a;
    margin-top: 30px;
    font-size: 19px;
    border-left: 4px solid #3b82f6;
    padding-left: 10px;
}}
h3 {{
    color: #1f2937;
    font-size: 15px;
    margin-top: 18px;
}}
table {{
    border-collapse: separate;
    border-spacing: 0;
    border: 1px solid #ddd;
    width: 100%;
    margin: 12px 0;
}}
th, td {{
    border: 1px solid #ddd;
    padding: 8px 12px;
    text-align: left;
    word-wrap: break-word;
    font-size: 13px;
}}
th {{
    background-color: #f1f5f9;
    font-weight: bold;
    color: #1e293b;
}}
tr:nth-child(even) {{
    background-color: #f8fafc;
}}
code {{
    background-color: #f1f5f9;
    padding: 2px 6px;
    border-radius: 3px;
    font-family: Consolas, monospace;
    font-size: 13px;
    color: #b91c1c;
}}
pre {{
    background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 12px;
    overflow-x: auto;
    font-family: Consolas, monospace;
    font-size: 13px;
    line-height: 1.5;
}}
.note {{
    background-color: #eff6ff;
    border-left: 4px solid #3b82f6;
    padding: 10px 14px;
    margin: 12px 0;
    border-radius: 0 4px 4px 0;
}}
.tip {{
    background-color: #ecfdf5;
    border-left: 4px solid #10b981;
    padding: 10px 14px;
    margin: 12px 0;
    border-radius: 0 4px 4px 0;
}}
ul, ol {{
    padding-left: 24px;
}}
li {{
    margin: 4px 0;
}}
</style>
</head>
<body>

<h1>{APP_NAME} 官方使用说明书</h1>
<p>版本 <b>{APP_VERSION}</b> — 现代化离线 API 生产力与性能测试套件</p>
<p>作者：<b>{APP_AUTHOR}</b> | 许可协议：<b>{APP_LICENSE}</b></p>

<h2 id="sec-overview">1. 产品简介与定位</h2>
<p>{APP_NAME} 是一款现代化离线 API 生产力工具，深度融合了 <b>单接口精细化调试、Go 协程高并发性能压测、页面接口智能嗅探与全页面压测以及全链路网络耗时拆解</b> 四大核心能力。</p>
<div class="note">
<b>核心特性：</b>全部数据保存在本地 SQLite 数据库中，零依赖、无强制注册登录、完全离线可用，原生单文件交付，启动秒开。
</div>

<h2 id="sec-quickstart">2. 快速开始</h2>
<ol>
<li>在左侧「集合」面板中，右键点击空白区域，选择 <b>新建集合</b>；</li>
<li>在集合上右键，选择 <b>新建请求</b> 并双击打开；</li>
<li>在顶部 URL 栏输入目标地址（如 <code>https://httpbin.org/get</code>），选择请求方法；</li>
<li>点击 <b>发送</b> 按钮或按 <code>Ctrl+Enter</code> 发送请求；</li>
<li>在下方查看响应报文与「耗时拆解」瀑布流；</li>
<li>点击 URL 栏右侧的 <b>[压测]</b> 发起并发性能测试，或点击 <b>[嗅探]</b> 探测并压测网页所有后端接口。</li>
</ol>

<h2 id="sec-request">3. 发送请求与编辑器功能</h2>

<h3>3.1 HTTP 方法</h3>
<p>完整支持所有主流 HTTP 请求方法，不同方法采用独立标识色：</p>
<table>
<tr><th>方法</th><th>说明</th><th>方法</th><th>说明</th></tr>
<tr><td><code>GET</code></td><td>获取资源（绿色）</td><td><code>POST</code></td><td>创建资源（橙色）</td></tr>
<tr><td><code>PUT</code></td><td>全量更新（蓝色）</td><td><code>PATCH</code></td><td>局部更新（紫色）</td></tr>
<tr><td><code>DELETE</code></td><td>删除资源（红色）</td><td><code>HEAD</code></td><td>仅获取响应头（灰色）</td></tr>
<tr><td><code>OPTIONS</code></td><td>支持的选项（青蓝）</td><td>-</td><td>-</td></tr>
</table>

<h3>3.2 URL 与 Query Params 双向联动</h3>
<p>在 URL 框直接输入 <code>?page=1&size=20</code>，<b>Params</b> 表格会自动拆解并填充对应键值；反之，在表格中添加或勾选参数，URL 也会自动同步刷新。</p>
<div class="tip">
<b>批量编辑：</b>点击 Params/Headers 表格右上角的「批量编辑」按钮可切换到多行文本模式（格式为 <code>key: value</code>），支持从文档一次性批量粘贴多个参数。
</div>

<h3>3.3 请求体（Body）模式</h3>
<p>切换到 <b>Body</b> 标签页支持 5 种请求体格式：</p>
<ul>
<li><b>none</b> — 无请求体（默认用于 GET/DELETE 等）；</li>
<li><b>json</b> — JSON 格式，支持代码折叠、语法高亮与「格式化 JSON」一键排版，字符串内换行符自动转义；</li>
<li><b>form</b> — multipart/form-data 表单格式；</li>
<li><b>urlencoded</b> — application/x-www-form-urlencoded 格式；</li>
<li><b>raw</b> — 原始文本或 Binary 文件上传。</li>
</ul>

<h3>3.4 认证（Auth）与 RFC 6265 域名 Cookie 自动分配机制</h3>
<ul>
<li><b>Auth</b>：支持 Basic Auth（用户名/密码）、Bearer Token、API Key 自定义放置在 Header 或 Query 中；</li>
<li><b>Cookie 域名智能分配</b>：系统内置标准 RFC 6265 域名/路径匹配引擎。所有 Cookie 默认按 <code>domain</code> 维度自动归类与隔离。只要标签页请求的目标 URL 匹配该域名（包含主域名与子域名匹配规则），系统在发送前均会自动将该域名的有效 Cookie 注入请求头；</li>
<li><b>自动增量合并</b>：当响应报文包含 <code>Set-Cookie</code> 头部时，系统会自动增量解析并安全写回本地持久化 Cookie 仓库中。</li>
</ul>

<h3>3.5 全局请求头（Global Headers）实时广播同步与优先级覆盖</h3>
<p>为避免在每个请求中重复配置相同的 Token 或租户标识，系统提供无缝的全局请求头机制：</p>
<ul>
<li><b>全标签页实时广播同步</b>：全局请求头无论是在独立设置弹窗还是在标签页中进行新增、修改或删除，<b>所有已打开的标签页（Tabs）以及后续新建的标签页都会毫秒级自动刷新同步</b>，无需重启软件或重新打开请求；</li>
<li><b>发送前级联决策链</b>：发起 HTTP 请求前，系统优先加载全局请求头并合并匹配当前域名的 Cookies，随后加载当前标签页的专属 Headers；<b>若标签页中配置了与全局请求头同名（Key 大小写不敏感）的请求头，标签页配置严格覆盖全局配置</b>；</li>
<li><b>cURL 导出同步</b>：生成 cURL 命令时自动合并全局与单独配置的请求头，保证与底层实际请求行为完全一致。</li>
</ul>

<h3>3.6 表格无损编辑与标签页切换防丢机制</h3>
<p>针对日常接口调试中经常需要输入半成品参数的场景：在 Params、Headers 或全局请求头表格中输入的内容，<b>即使用户仅输入了 Key 或仅输入了 Value（另一侧为 null / 留空），在切换标签页、切换子面板或编辑其他请求时均会严格持久保留</b>，绝不会被自动剔除或清空，保障工作流连续无损。</p>

<h3>3.7 请求即时取消机制</h3>
<p>在网络请求发送过程中，发送按钮会自动切换为红色 <b>取消发送</b>。点击后 UI 界面<b>毫秒级即刻重置为「发送」待命状态</b>，底层网络连接和后台线程立即安全终止，响应查看区明确呈现「请求已取消」，彻底杜绝网络高延迟或弱网阻塞造成的界面挂起与按钮卡顿。</p>

<h2 id="sec-collection">4. 集合管理、多级文件夹、拖拽与剪贴板操作</h2>
<ul>
<li><b>多层级文件夹与展开收起</b>：支持无限层级的树形组织结构（<code>父集合 → 多级子文件夹 → 请求</code>）。文件夹支持独立展开/折叠，具有动态 <code>📁</code> / <code>📂</code> 图标提示，集合树顶部提供 <b>[📂 全部展开]</b> 与 <b>[📁 全部折叠]</b> 快捷操作，在树形刷新时 100% 保持用户的展开与折叠状态；</li>
<li><b>鼠标拖拽组织 (Drag & Drop)</b>：
  <ul>
    <li>支持直接拖拽接口到任意集合或子文件夹中，实现直观拖拽归类；</li>
    <li>支持拖拽调整子文件夹的所属层级，系统内置祖先链递归校验，严防循环嵌套；</li>
  </ul>
</li>
<li><b>右键剪贴板与快捷键</b>：
  <ul>
    <li><b>复制接口 (Ctrl+C)</b>：复制选中的接口到应用内部剪贴板；</li>
    <li><b>剪切接口 (Ctrl+X)</b>：剪切选中的接口，粘贴后完成跨目录转移；</li>
    <li><b>粘贴接口 (Ctrl+V)</b>：在目标集合或文件夹中粘贴已复制或剪切的接口；</li>
    <li><b>创建副本</b>：右键点击接口选择「创建副本」即可在当前目录下快速深拷贝一份独立副本；</li>
    <li><b>新建子文件夹 / 新建请求</b>：右键集合节点可快速新建多级子文件夹或直接创建新接口；</li>
    <li><b>删除 (Del)</b>：支持快捷键直接删除选中的接口或集合（带防误触确认弹窗）。</li>
  </ul>
</li>
<li><b>导入导出生态</b>：
  <ul>
    <li>支持导出/导入 PostManage 原生 JSON 集合树；</li>
    <li>无缝兼容导入 <b>Postman Collection v2.1</b> 导出文件；</li>
    <li>菜单 <b>文件 → 从 cURL 导入...</b>：支持一键解析粘贴的 cURL 命令行生成完整请求配置。</li>
  </ul>
</li>
<li><b>快捷 cURL 导出</b>：编辑器提供专属的 <b>cURL</b> 导出标签页，实时根据最新配置生成格式化的 cURL 执行命令，并支持一键复制。</li>
</ul>

<h2 id="sec-response">5. 查看响应与全链路网络耗时拆解</h2>
<p>发送请求后，响应面板提供四个子视图与流式内容整合功能：</p>
<ul>
<li><b>Pretty</b>：自动检测 JSON/XML/HTML 并进行语法高亮与美化折叠；</li>
<li><b>Raw</b>：原始报文输出；</li>
<li><b>Headers</b>：完整的 HTTP 响应头表格；</li>
<li><b>耗时拆解 (Timing Waterfall)</b>：微秒级全链路网络生命周期拆解；</li>
<li><b>流式响应自动提取整合 [整合]</b>：快速将分块流式响应（SSE / Chunked）拼接为连续文本。</li>
</ul>

<h3>5.1 全链路网络生命周期耗时拆解说明</h3>
<p>{APP_NAME} 依托底层 Go 协程引擎的 <code>net/http/httptrace</code> 技术，对网络传输各个阶段进行精准打点分析：</p>
<table>
<tr><th>网络阶段</th><th>指标名称</th><th>核心含义与排查建议</th></tr>
<tr><td>🌐 <b>DNS 解析</b></td><td>DNS Lookup</td><td>域名解析耗时。若耗时偏高，通常为本地 DNS 响应慢或未命中缓存。</td></tr>
<tr><td>🔌 <b>TCP 建连</b></td><td>TCP Connect</td><td>TCP 三次握手耗时。反映客户端与服务器之间的物理网络往返延时（RTT）。</td></tr>
<tr><td>🔒 <b>TLS 握手</b></td><td>TLS Handshake</td><td>SSL/TLS 密钥协商与证书验证耗时。若耗时较长可考虑开启 Keep-Alive 复用长连接。</td></tr>
<tr><td>📤 <b>发送请求</b></td><td>Request Send</td><td>向网络缓冲区写入请求报文的时间。通常在 1ms 内完成。</td></tr>
<tr><td>⏳ <b>等待首包 (TTFB)</b></td><td>Time to First Byte</td><td>从请求发送完毕到接收到第一个响应字节的延迟。<b>核心性能指标</b>，直接反映远程服务器后端处理与数据库查询开销。</td></tr>
<tr><td>📥 <b>内容下载</b></td><td>Content Download</td><td>从首包到达至读取完整个响应体的耗时。主要取决于报文体积大小与下行带宽。</td></tr>
</table>
<div class="tip">
<b>智能性能建议：</b>在「耗时拆解」页面中，系统会自动绘制彩色瀑布流复合占比图，并智能输出优化建议（例如 TTFB 耗时过长提示排查慢 SQL、DNS 耗时过长提示排查解析等）。
</div>

<h3>5.2 流式响应自动提取与内容整合 (SSE / Chunked Stream Consolidator)</h3>
<p>针对现代大模型（LLM / ChatGPT / Claude / DeepSeek）或流式通知接口返回的 SSE 分块碎片数据（如多条 <code>data: {{"choices":[{{"delta":{{"content":"你好"}}}}]}}</code>），系统提供一键整合提取能力：</p>
<ol>
<li><b>点击「整合」按钮</b>：请求得到响应后，在响应状态栏右侧点击 <b>[整合]</b> 按钮弹出工作台；</li>
<li><b>配置截取前缀</b>：输入流式数据每行的前缀（如 <code>data:</code> 或 <code>data: </code>，留空则默认解析整行）；</li>
<li><b>配置提取字段</b>：
  <ul>
    <li><b>完整路径提取</b>：支持如 <code>choices[0].delta.content</code>、<code>delta.text</code> 等点号及列表下标语法；</li>
    <li><b>单字段简写</b>：支持直接输入 <code>content</code> 等单个字段名称；</li>
  </ul>
</li>
<li><b>同名歧义安全拦截</b>：当用户输入单字段名（如 <code>content</code>）且单个数据块中存在多个同名字段时，系统会<b>主动弹出警告窗口</b>，要求指定完整路径，防止提取内容混乱错乱；</li>
<li><b>左右分栏双视图与一键复制</b>：左侧实时呈现截取配置与原始流数据，右侧完整拼接呈现合并后的文本内容，并显示字符计数，支持 <b>[一键复制]</b> 快速提取到剪贴板。</li>
</ol>

<h2 id="sec-stress">6. 极简高并发性能压测 (Go 协程引擎)</h2>
<p>传统测试工具启动沉重、配置繁杂；PostManage 将核心压测能力重构为<b>免脚本、零配置、开箱即用</b>的原生性能测试工作台，底层依托 Go 原生高并发协程池（Goroutines），轻松突破 Python GIL 瓶颈，实现万级并发与网络吞吐。</p>

<h3>6.1 如何开启压测</h3>
<ul>
<li><b>快捷按钮</b>：在任意请求编辑界面的 URL 输入栏右侧，点击纯文字 <b>[压测]</b> 按钮（会自动将当前请求的方法、URL、Headers、Body、Auth 与 Cookies 全部载入压测器）；</li>
<li><b>菜单入口</b>：点击顶部菜单栏 <b>工具(&T) → 高并发性能压测 (Ctrl+Alt+S)</b>。</li>
</ul>

<h3>6.2 参数配置指南</h3>
<table>
<tr><th>参数项</th><th>推荐取值</th><th>功能说明</th></tr>
<tr><td><b>并发用户数 (Concurrency)</b></td><td>1 ~ 200</td><td>并发协程池容量，模拟同时在线发起请求的虚拟用户并发数。</td></tr>
<tr><td><b>压测时长 (Duration)</b></td><td>5 ~ 300 秒</td><td>持续产生高并发负载的时间窗口。</td></tr>
<tr><td><b>爬坡升压时间 (Ramp-up)</b></td><td>0 ~ 30 秒</td><td>平滑线性递增启动并发协程的时间，避免突发尖峰直接冲垮服务端。</td></tr>
<tr><td><b>单请求间隔 (Delay)</b></td><td>0 ~ 1000 ms</td><td>每个协程完成一次请求后的休眠延迟，用于精细化控制总请求频率与压力梯度。</td></tr>
<tr><td><b>单请求超时 (Timeout)</b></td><td>1 ~ 30 秒</td><td>单个请求等待响应的最大时限，超时将自动打标为超时异常。</td></tr>
</table>

<h3>6.3 压测指标与诊断大盘</h3>
<p>点击「开始并发压测」后，系统实时计算并在测试结束后呈现完整评估大盘：</p>
<ul>
<li><b>总请求数 / 成功率</b>：执行的总请求笔数及 HTTP 2xx/3xx 成功百分比；</li>
<li><b>平均 TPS / 峰值 TPS</b>：每秒事务吞吐量（Transactions Per Second），反映系统最大处理能力；</li>
<li><b>平均耗时 / Min / Max</b>：接口响应时间的数学期望及极值；</li>
<li><b>P50 / P90 / P99 延迟分位数</b>：长尾延迟关键指标。例如 P99 = 80ms 代表 99% 的请求耗时都在 80ms 以内；</li>
<li><b>延迟阶梯柱状图</b>：将所有请求按 <code>&lt;50ms</code>、<code>50-200ms</code>、<code>200-500ms</code>、<code>&gt;500ms</code> 阶梯归类，直观洞察耗时分布；</li>
<li><b>HTTP 状态码明细</b>：精准统计 200/404/500 等各状态码的具体次数；</li>
<li><b>智能瓶颈诊断</b>：根据 TPS 波动、错误率及长尾耗时自动出具调优建议（如排查数据库索引、线程池排队等）；</li>
<li><b>📋 结果列表与多维可视化分析看板</b>：点击<b>「📋 结果列表」</b>按钮即可打开专属详情大盘：
  <ul>
    <li><b>请求明细清单</b>：逐笔查看每次请求的序号、时间偏移、Method、URL、状态码、响应耗时、数据包大小与错误详情，支持按 2xx/3xx/4xx/5xx 分类筛选与关键词检索，支持一键导出为 CSV 或 JSON；</li>
    <li><b>📈 响应耗时波动折线图</b>：直观呈现压测过程中每笔请求耗时变化与红色虚线均值基准线；</li>
    <li><b>🍩 HTTP 状态码分布环形饼图</b>：统计 2xx/3xx/4xx/5xx/网络故障所占比例及次数；</li>
    <li><b>📊 延迟区间阶梯柱状图</b>：直观对比极速、正常、慢响应各阶梯请求分布。</li>
  </ul>
</li>
<li><b>报告导出</b>：点击「导出报告 (JSON)」可一键保存完整性能指标数据，便于归档与分享。</li>
</ul>

<h2 id="sec-sniffer">7. 页面接口智能嗅探、真机交互与并发压测大盘</h2>
<p>传统抓包测试工具（如 Fiddler、Charles）需要手动安装与信任根证书，极易遭遇 HTTPS 证书阻碍与 CORS 跨域问题。PostManage 创新性集成了<b>「CDP 真机交互嗅探」</b>与<b>「Go 原生无头静默引擎」</b>双核体系，既支持在真实浏览器中可视化登录、交互操作与多轮压测，也支持全自动提取所有异步 API、执行自适应 Network Idle 零 pending 压测与生成多维深度分析大盘。</p>

<h3>7.1 无头模式 (Headless) 与非无头模式 (GUI 真实浏览器模式) 深度对比</h3>
<p><b>什么是无头模式（Headless Mode）？</b><br>
“无头模式”是指浏览器或网络引擎在<b>没有图形用户界面（GUI）</b>的后台静默运行。它不在屏幕上弹出任何可见的浏览器窗口，完全在后台进程中高效拉取页面、解析脚本并派发网络请求。</p>

<p><b>什么是真机交互模式（非无头模式 / GUI 模式）？</b><br>
真机交互模式通过 Chrome DevTools Protocol (CDP) 协议直接调起操作系统中真实安装的 Google Chrome 或 Microsoft Edge 浏览器。浏览器窗口正常呈现在屏幕上，用户可以像日常上网一样进行<b>鼠标点击、输入账号密码、拖动滑块验证码、手机扫码登录或通过企业 SSO 单点登录系统</b>。</p>

<table>
<tr><th style="width:16%;">对比维度</th><th style="width:42%;">真机交互模式 (非无头模式)</th><th style="width:42%;">后台静默模式 (无头模式)</th></tr>
<tr><td><b>窗口显示</b></td><td>弹出独立 Chrome / Edge 真实窗口，渲染动画与操作界面完整可见</td><td>完全无窗口弹出，在操作系统后台静默执行，不干扰当前桌面工作</td></tr>
<tr><td><b>用户交互能力</b></td><td><b>支持全人工交互</b>：表单输入、验证码识别、扫码、点击特定按钮触发业务</td><td><b>不支持人工干预</b>：依赖预置 URL、Cookie 与预先配置好的全局请求头</td></tr>
<tr><td><b>认证凭证捕获</b></td><td><b>动态自动捕获</b>：登录后自动通过 CDP 穿透提取动态 Session、HttpOnly Cookies 及鉴权 Token</td><td><b>静态自动携带</b>：依赖本地 Cookie 管理器与全局 Headers 中预先存储的凭据</td></tr>
<tr><td><b>资源占用</b></td><td>需要加载完整渲染树、CSS 布局与 GPU 显存，占用稍多系统资源</td><td>纯后台网络与 AST 语法树解析，极低 CPU/内存占用，轻量高效</td></tr>
<tr><td><b>执行速度</b></td><td>适合真实用户会话抓取与多轮交互式压测（约 100~500ms / 轮）</td><td>适合大规模并发巡检与高频接口并发探测，速度达到万级 TPS</td></tr>
<tr><td><b>推荐使用场景</b></td><td>
  <ul>
    <li>目标网站<b>必须登录</b>才能访问（如管理后台、OA系统、下单链路）；</li>
    <li>存在<b>图形验证码、短信验证码、滑块验证</b>等人机校验；</li>
    <li>接口需要<b>特定页面操作</b>才能触发（如点击“提交审批”按钮）；</li>
    <li>需要测试已登录状态下全页面的综合渲染与异步接口加载表现。</li>
  </ul>
</td><td>
  <ul>
    <li>目标页面为<b>免登录公开页面</b>（如官网首页、文档、新闻大屏）；</li>
    <li>已在 PostManage 中<b>提前配置好全局 Token / 域名 Cookie</b>；</li>
    <li>日常自动化批量健康体检、CI/CD 链路巡检；</li>
    <li>希望以极轻量资源执行高并发纯接口负载压测。</li>
  </ul>
</td></tr>
</table>

<h3>7.2 按钮功能详解与标准使用顺序 (操作全流程)</h3>
<p>为保障压测数据完整性并避免出现未授权（401/403）或接口中断挂起（pending），推荐按照以下标准顺序使用嗅探与压测按钮：</p>

<ol>
<li><b>第 1 步：输入待测 URL 并确认代理通道</b><br>
在顶部「目标 Web 页面 URL」输入框输入地址（例如 <code>http://10.111.212.130/dashboard</code>）。如果该地址需要经过内网网关或特定代理，点击右上角【🌐 代理】确认已选择系统代理、PAC 模式或自定义代理。</li>

<li><b>第 2 步：点击【🚀 启动真机交互嗅探】</b><br>
系统将自动识别系统中的 Chrome 或 Edge 浏览器，并以独立调试端口与专用临时隔离配置调起浏览器窗口（同时注入当前生效的代理配置参数）。此时该按钮将切换为红色【🛑 停止真机交互嗅探】状态。</li>

<li><b>第 3 步：在浏览器中完成登录与业务交互</b><br>
在弹出的浏览器中，正常输入用户名密码、接收验证码或扫码完成登录；在页面内可自由点击导航菜单或业务按钮。PostManage 窗口下方的接口表格将<b>实时毫秒级捕获</b>所有被触发的 XHR / Fetch 后端 API 接口，并自动解析请求方法、响应状态码、Headers、POST 数据包与会话 Cookies。</li>

<li><b>第 4 步：配置压测参数并点击【⚡ 开始嗅探压测】</b><br>
登录并定位到目标业务页面后，在 PostManage 控制栏设置：
<ul>
  <li><b>页面刷新轮次 (Rounds)</b>：拟自动刷新测试的轮数（如 20 轮）；</li>
  <li><b>并发协程数 (Concurrency)</b>：并发虚拟用户数（如 5 协程）；</li>
  <li><b>页面加载超时 (Timeout)</b>：单轮页面网络收敛的最长等待时限（如 10 秒）。</li>
</ul>
点击<b>【⚡ 开始嗅探压测】</b>！系统将启动<b>自适应 Network Idle 在途请求追踪引擎</b>，每轮严格等待所有异步请求完整返回后立即进入下一轮刷新，既保证接口不会处于 pending/canceled 状态，又以真实网络物理速度极速推进！</li>

<li><b>第 5 步：压测完成或点击【🛑 停止真机交互嗅探】</b><br>
压测完成后系统会自动收敛并生成大盘；若中途需要人工中止，点击【🛑 停止真机交互嗅探】即可安全切断 CDP 连接并关闭浏览器。</li>
</ol>

<h4>所有功能按钮速查一览表：</h4>
<table>
<tr><th style="width:22%;">按钮名称</th><th style="width:28%;">所属模式</th><th style="width:50%;">功能说明与触发动作</th></tr>
<tr><td><b>🚀 启动真机交互嗅探</b></td><td>非无头 (GUI 真实浏览器)</td><td>通过 CDP 协议唤起系统的真实 Chrome/Edge 浏览器，自动注入代理与网络监听管道，开始实时录制页面 API。</td></tr>
<tr><td><b>⚡ 开始嗅探压测</b></td><td>非无头 (GUI 真实浏览器)</td><td>在真机浏览器中启动自动化多轮压测。具备自适应在途网络追踪（Network Idle），等异步数据全部返回后触发下一轮，杜绝 pending。</td></tr>
<tr><td><b>🛑 停止真机交互嗅探</b></td><td>非无头 (GUI 真实浏览器)</td><td>安全断开 WebSocket 调试通道，关闭当前唤起的浏览器窗口，释放端口资源并固化采集到的数据。</td></tr>
<tr><td><b>🔍 一键嗅探并巡检</b></td><td>无头模式 (Go 静默引擎)</td><td>无需弹出浏览器，后台静默下载页面 HTML/JS 源码，利用 AST 语法树算法挖掘潜在 API，并发起探针巡检。</td></tr>
<tr><td><b>🚀 页面全接口压测</b></td><td>无头模式 (Go 协程引擎)</td><td>后台多协程并发直接压测嗅探提取的所有后端端点，自动保留原请求的 Headers、POST Body、Session 及 Cookie。</td></tr>
<tr><td><b>📋 全页面压测明细与图表</b></td><td>通用综合分析</td><td>调出全页面事务的多维综合大盘对话框，包含轮次耗时、接口排行、延迟直方图与状态码分布。</td></tr>
<tr><td><b>📋 结果列表与图表</b></td><td>单接口分析</td><td>针对表格中选中的特定接口，单独调出该接口的每次请求明细、响应耗时走势折线图与错误分类。</td></tr>
<tr><td><b>📥 导入到当前请求</b></td><td>工作流流转</td><td>将嗅探到的接口参数、请求头、Body 及 Cookie 一键导入主界面 Request Editor，方便进行单接口单独复现与调试。</td></tr>
<tr><td><b>⚡ 单独发起并发压测</b></td><td>工作流流转</td><td>以选中的单个接口为目标，直接唤起独立的万级高并发压测器进行单独升压测试。</td></tr>
<tr><td><b>🌐 导出离线 HTML 报告</b></td><td>报表导出</td><td>导出脱机独立的交互式 HTML 性能报告（内嵌 ECharts 图表），适合发给团队、领导汇报或存档。</td></tr>
<tr><td><b>💾 导出报告 (JSON)</b></td><td>报表导出</td><td>导出结构化压测原始 JSON 数据包，供第三方自动化平台或自研分析系统二次处理。</td></tr>
</table>

<h3>7.3 各个报表的查看方式与内容解读</h3>
<p>压测结束后，系统提供了由宏观到微观的全方位性能报表：</p>
<ol>
<li><b>大盘聚合核心指标卡片（8 大关键指标）</b>：
  <ul>
    <li><b>总请求数 / 页面轮次</b>：累计执行的页面加载轮次与接口调用总次数；</li>
    <li><b>成功率 (%)</b>：所有响应状态码在 200~399 之间的比例。建议生产环境健康阈值保持在 <code>99.9%</code> 以上；</li>
    <li><b>平均吞吐量 (TPS) 与峰值 TPS</b>：系统每秒能够支撑的事务请求数，反映系统承载上限；</li>
    <li><b>平均响应耗时 (RT)</b>：所有请求返回时长的算术平均值；</li>
    <li><b>P50 / P90 / P99 延迟分位数</b>：长尾分布衡量核心。P90 代表 90% 的请求在此时长内返回（推荐 &lt; 200ms），P99 反映最慢 1% 极端长尾用户的体验；</li>
    <li><b>网络带宽 (KB/s)</b>：每秒接收的数据字节吞吐量，评估网络带宽是否达到瓶颈。</li>
  </ul>
</li>

<li><b>全页面接口耗时排行榜 (Endpoint Ranking)</b>：
  <p>按平均响应时间由慢到快排序呈现页面中所有异步接口，包含：请求方法、相对路径、平均耗时、最大耗时、最小耗时、成功率、调用次数及<b>耗时占比 (%)</b>。通过耗时占比可一目了然定位“是哪一个慢接口拉垮了整页加载速度”。</p>
</li>

<li><b>响应耗时区间分布直方图 (Latency Bins)</b>：
  <p>将请求归类为四大阶梯：<code>&lt; 50 ms (优)</code>、<code>50 ~ 200 ms (良)</code>、<code>200 ~ 500 ms (中)</code>、<code>&gt; 500 ms (慢/长尾)</code>。健康的系统应当在极速和良性区间集中 95% 以上。</p>
</li>

<li><b>HTTP 状态码分布列表 (Status Code Distribution)</b>：
  <p>分门别类统计 HTTP 200、304、400、401、403、404、500、502、504 等状态码的发生次数，帮助快速甄别是鉴权未通过（401/403）还是网关超时（504）或后端死锁崩溃（500）。</p>
</li>

<li><b>单次全页面事务明细清单 (Page Iterations)</b>：
  <p>点击【📋 全页面压测明细与图表】打开。逐行展示每一轮页面刷新的时间偏移、整页收敛耗时、调用的接口总数、失败接口数与错误信息，便于回溯压测过程中某一次偶发的性能劣变。</p>
</li>

<li><b>单接口请求明细与耗时波动折线图</b>：
  <p>在任意接口行点击【结果列表】即可打开。呈现该接口每次发包的毫秒耗时折线图、红色均值基准线、HTTP 状态码分布饼图，支持一键导出为 CSV 电子表格。</p>
</li>

<li><b>HTTP Timing 全链路网络耗时拆解瀑布图</b>：
  <p>在单接口查看器中呈现 DNS 解析、TCP 握手、TLS 安全握手、发送请求、TTFB 首包等待、数据下载各阶段耗时，精准定界是 DNS 慢、网络建连慢、还是后端代码执行慢（TTFB 慢）。</p>
</li>

<li><b>离线 HTML 交互式压测报告导出</b>：
  <p>点击【导出离线 HTML 报告】，系统自动生成包含单页面自包含样式与交互图表的 HTML 文件。无需联网，直接用任意浏览器打开即可脱机交互式查阅与汇报演示。</p>
</li>
</ol>

<h2 id="sec-proxy">8. 全场景代理管理与智能调度指南 (Proxy Management)</h2>
<p>在企业级开发与接口测试中，往往面临复杂的网络隔离环境：企业内网堡垒机、开发环境反向代理网关、本地抓包分析工具（如 Fiddler、Charles、Mitmproxy）、智能分流脚本（PAC）以及特定服务网卡直连需求。PostManage 提供了完备的<b>全局与接口级两级代理策略</b>以及对常用代理模式的全面支持。</p>

<h3>8.1 代理层级架构与优先级规则</h3>
<ul>
<li><b>全局代理策略</b>：
  <ul>
    <li><b>设置入口</b>：点击顶部主菜单 <b>编辑(&E) → 全局代理配置...</b>；</li>
    <li><b>作用范围</b>：PostManage 发起的所有日常请求、自动化测试、压测以及嗅探的默认通道；</li>
    <li><b>默认配置</b>：默认为“跟随系统代理”，与 Windows 操作系统设置完全一致，开箱即用无需任何额外调整。</li>
  </ul>
</li>
<li><b>单接口专属代理</b>：
  <ul>
    <li><b>设置入口</b>：在请求编辑界面的保存按钮前点击【🌐 代理】按钮；</li>
    <li><b>作用范围</b>：仅对当前打开的特定接口生效，保存请求时代理配置与接口数据同步持久化保存；</li>
    <li><b>优先级</b>：<code>单接口专属代理 > 全局代理配置</code>。当某接口配置了专属代理时，即便全局处于系统代理或直连，该接口也会严格走其专属通道；设置为“跟随全局代理策略”时自动继承全局。</li>
  </ul>
</li>
<li><b>并发压测专属代理</b>：
  <ul>
    <li><b>设置入口</b>：在并发性能压测对话框的目标信息卡片中点击【🌐 代理】按钮；</li>
    <li><b>作用范围</b>：仅在本次并发压测运行时生效，方便临时切换测试代理或排查直连瓶颈，测试结束后不污染接口原始保存项。</li>
  </ul>
</li>
</ul>

<h3>8.2 四种主流代理模式配置与示例</h3>

<h4>模式 1：跟随系统代理 (System Proxy) — 默认推荐</h4>
<p><b>原理</b>：自动检测并读取 Windows 注册表（<code>Internet Settings</code>）与系统环境变量（<code>HTTP_PROXY</code> / <code>HTTPS_PROXY</code> / <code>NO_PROXY</code>）。系统代理开启时走系统代理，系统代理关闭时自动直连。</p>
<p><b>配置示例</b>：直接勾选 <code>[🌐 跟随系统代理]</code> 即可，无需填写任何服务器或端口。在企业开启了全局透明代理或使用了网络分流工具时，直接开箱即用。</p>

<h4>模式 2：网卡直连无代理 (Direct / None)</h4>
<p><b>原理</b>：强制屏蔽操作系统的任何代理设置及环境变量，直接通过物理网卡向目标 IP / 域名发起 Socket 握手。</p>
<p><b>配置示例</b>：勾选 <code>[🔌 网卡直连无代理]</code>。<br>
<b>适用场景</b>：本地 <code>127.0.0.1</code> 服务调试、内网直连（如 <code>192.168.x.x</code>）、或者本地开启了抓包软件但不希望干扰当前压测性能时。</p>

<h4>模式 3：自定义手动代理 (Custom / Manual Proxy)</h4>
<p><b>原理</b>：手动指定指定的代理协议、服务器主机、端口以及可选的身份验证凭据与主机绕过名单。</p>
<table>
<tr><th>配置项</th><th>格式与示例</th><th>说明</th></tr>
<tr><td><b>协议 (Protocol)</b></td><td><code>HTTP</code> / <code>HTTPS</code> / <code>SOCKS5</code></td><td>支持标准 HTTP 代理与 SOCKS5 代理。</td></tr>
<tr><td><b>服务器与端口</b></td><td>主机: <code>127.0.0.1</code> 端口: <code>7890</code></td><td>代理服务器的 IP 地址或局域网域名与端口。</td></tr>
<tr><td><b>不代理的主机 (Bypass)</b></td><td><code>localhost, 127.0.0.1, 192.168.*, *.internal.lan</code></td><td>逗号分隔。匹配的主机将直接连接，不通过代理。</td></tr>
<tr><td><b>代理身份认证</b></td><td>勾选并填写用户名 <code>admin</code>，密码 <code>******</code></td><td>用于企业正向鉴权网关（支持 Basic Auth）。</td></tr>
</table>

<div class="note">
<b>典型配置示例：</b>
<ul>
  <li><b>对接本地 Fiddler / Charles 抓包</b>：协议选择 <code>HTTP</code>，服务器填写 <code>127.0.0.1</code>，端口填写 <code>8888</code>；</li>
  <li><b>对接本地 SOCKS5 代理</b>：协议选择 <code>SOCKS5</code>，服务器填写 <code>127.0.0.1</code>，端口填写 <code>1080</code>；</li>
  <li><b>企业专用高防网关</b>：协议选择 <code>HTTP</code>，服务器填写 <code>proxy.corp.internal</code>，端口填写 <code>8080</code>，启用身份认证并输入工号密码。</li>
</ul>
</div>

<h4>模式 4：PAC 自动配置脚本模式 (Proxy Auto-Configuration)</h4>
<p><b>原理与规范说明</b>：PAC 是 Netscape 制定并被全球所有现代浏览器（Chrome、Edge、Firefox、Safari）统一支持的工业级代理自动调度规范。它的核心是通过一个名为 <code>FindProxyForURL(url, host)</code> 的 JavaScript 函数，在每次发送 HTTP/HTTPS 网络请求前根据目标 URL 和主机名动态裁决该请求的走向。</p>

<div class="note">
<b>📌 语法格式开放性说明：</b><br>
PAC 脚本<b>绝不仅限于某种固定模板或特定写法</b>！PostManage 内置了完整的通用 PAC 语法解析与执行引擎。只要脚本实现了 <code>FindProxyForURL(url, host)</code> 并返回标准代理指令，无论您使用 <code>if-else</code> 条件分支、<code>switch-case</code> 语句、数组循环、JavaScript 对象哈希白名单查表、正则表达式、还是调用官方 PAC 标准函数，<b>均受原生完整支持，可直接将公司现成 PAC 脚本无缝导入使用</b>。
</div>

<p><b>配置方式</b>：在「PAC 脚本 URL / 本地路径」中输入：
<ul>
  <li><b>远程 HTTP/HTTPS 地址</b>：例如 <code>http://127.0.0.1:18033/proxy.pac</code> 或 <code>http://pac.corp.internal/wpad.dat</code>（支持动态拉取与智能缓存）；</li>
  <li><b>本地磁盘文件路径</b>：例如 <code>file:///C:/Users/Administrator/proxy.pac</code> 或 <code>C:\\tools\\proxy.pac</code>（支持离线运行）。</li>
</ul>
</p>

<h5>4.1 标准 PAC 函数支持清单</h5>
<p>PostManage 内置 PAC 引擎完整原生支持以下所有官方标准函数：</p>
<table>
<tr><th>标准函数</th><th>参数与格式</th><th>功能说明与示例</th></tr>
<tr><td><code>shExpMatch(str, pat)</code></td><td><code>(host / url, 通配符模式)</code></td><td>通配符匹配（支持 <code>*</code> 和 <code>?</code>），如 <code>shExpMatch(host, "*.internal.lan")</code></td></tr>
<tr><td><code>dnsDomainIs(host, domain)</code></td><td><code>(host, 域名后缀)</code></td><td>域名后缀匹配，如 <code>dnsDomainIs(host, ".google.com")</code></td></tr>
<tr><td><code>isPlainHostName(host)</code></td><td><code>(host)</code></td><td>判断是否为无点单段内部主机名（如 <code>http://oa/</code> 或 <code>http://localhost/</code>）</td></tr>
<tr><td><code>isInNet(ip, net, mask)</code></td><td><code>(ip, 网络号, 子网掩码)</code></td><td>判断 IP 是否位于特定子网网段，如 <code>isInNet(ip, "10.0.0.0", "255.0.0.0")</code></td></tr>
<tr><td><code>localHostOrDomainIs(h, d)</code></td><td><code>(host, 主机全名)</code></td><td>精确匹配本机主机名或带域名的完整主机名</td></tr>
<tr><td><code>dnsResolve(host)</code></td><td><code>(host)</code></td><td>将域名动态解析为实际 IPv4 地址</td></tr>
<tr><td><code>myIpAddress()</code></td><td>无参数</td><td>获取当前客户端本机的 IPv4 IP 地址</td></tr>
<tr><td><code>JS 原生字符串方法</code></td><td><code>substring</code>, <code>indexOf</code>, <code>toLowerCase</code> 等</td><td>字符串截取、查找与大小写转换等标准 JavaScript 语法</td></tr>
</table>

<h5>4.2 支持的返回值指令 (Directives) 与主备容灾</h5>
<p>函数返回值为字符串，支持以下指令类型，且支持以分号 <code>;</code> 隔开配置<b>多代理主备回退容灾</b>：</p>
<ul>
  <li><code>DIRECT</code>：网卡直连，不走代理；</li>
  <li><code>PROXY host:port</code>：通过标准 HTTP 代理服务器转发；</li>
  <li><code>HTTPS host:port</code>：通过加密 HTTPS 代理服务器转发；</li>
  <li><code>SOCKS host:port</code> 或 <code>SOCKS5 host:port</code>：通过 SOCKS4 / SOCKS5 代理通道转发；</li>
  <li><b>主备容灾链路写法</b>：<code>return "PROXY 192.168.66.44:8443; PROXY 192.168.66.45:8080; DIRECT";</code>（若首选代理不可达，系统将自动尝试次选代理或最终直连）。</li>
</ul>

<h5>4.3 多场景真实 PAC 脚本编写范例</h5>

<p><b>范例 A：多分支与特定 IP 端口网关（典型企业混合环境）</b></p>
<pre>
function FindProxyForURL(url, host) {{
    // 1. 本地回环与无点主机直连
    if (isPlainHostName(host) || shExpMatch(host, "127.0.0.1") || shExpMatch(host, "localhost")) {{
        return "DIRECT";
    }}

    // 2. 指定内网主机或特定业务段走专用网关
    if (shExpMatch(host, "10.119.254.59")) {{
        return "PROXY 192.168.184.165:8443";
    }}
    if (shExpMatch(host, "10.111.212.130") || shExpMatch(host, "10.111.11.*")) {{
        return "PROXY 192.168.66.44:8443";
    }}

    // 3. 其它请求默认直连
    return "DIRECT";
}}
</pre>

<p><b>范例 B：海量域名白名单字典查表格式（推荐大量 API/微服务场景，执行极速）</b></p>
<pre>
var proxyMap = {{
    "api.dev.internal":     "PROXY 10.0.1.10:8080",
    "auth.sso.corp":        "PROXY 10.0.1.10:8080",
    "gateway.test.lan":     "PROXY 10.0.2.20:8443",
    "gitlab.internal":      "PROXY 10.0.3.30:3128"
}};

function FindProxyForURL(url, host) {{
    host = host.toLowerCase();
    if (proxyMap[host]) {{
        return proxyMap[host];
    }}
    return "DIRECT";
}}
</pre>

<p><b>范例 C：基于 IP 子网网段 (CIDR / Subnet) 分流格式</b></p>
<pre>
function FindProxyForURL(url, host) {{
    // 纯内网单主机名直连
    if (isPlainHostName(host)) {{
        return "DIRECT";
    }}

    // 解析域名的真实 IP
    var ip = dnsResolve(host);
    if (!ip) {{
        return "DIRECT";
    }}

    // 10.0.0.0/8 核心数据中心网段走专线代理
    if (isInNet(ip, "10.0.0.0", "255.0.0.0")) {{
        return "PROXY 10.200.0.1:8080";
    }}

    // 172.16.0.0/12 测试环境网段走测试代理
    if (isInNet(ip, "172.16.0.0", "255.240.0.0")) {{
        return "PROXY 172.16.1.1:8080";
    }}

    return "DIRECT";
}}
</pre>

<p><b>范例 D：按协议（HTTP/HTTPS/SOCKS）与特定端口分流格式</b></p>
<pre>
function FindProxyForURL(url, host) {{
    if (shExpMatch(host, "127.0.0.1") || shExpMatch(host, "localhost")) {{
        return "DIRECT";
    }}

    // HTTPS 安全接口走专用审计网关
    if (url.substring(0, 6) === "https:") {{
        return "PROXY 192.168.1.200:8443";
    }}

    // SSH 或特定后台端口走 SOCKS5 代理
    if (shExpMatch(url, "*:22") || shExpMatch(url, "*:8000")) {{
        return "SOCKS5 127.0.0.1:1080";
    }}

    return "DIRECT";
}}
</pre>

<h3>8.3 压测与嗅探中的代理联动</h3>
<ul>
  <li><b>真机交互嗅探</b>：调起 Chrome / Edge 浏览器时，自动注入当前代理参数（如 <code>--proxy-pac-url</code>、<code>--proxy-server</code>、<code>--proxy-bypass-list</code>），即使在无头模式或真实浏览器中，所有网络请求均精准走代理通道，同时自动忽略自签名证书阻断（<code>--ignore-certificate-errors</code>）；</li>
  <li><b>Go 协程高并发压测</b>：Go 原生高并发协程池底层 <code>http.Transport</code> 自动挂接对应代理（支持 PAC 动态结算结果、自定义 HTTP/SOCKS 代理与显式直连），万级并发压测流量全程按既定代理路线高速转发。</li>
</ul>

<h3>8.4 代理连通性实时测试工具</h3>
<p>在任意代理配置窗口中，底部均集成了<b>【⚡ 测试代理连接】</b>工具：</p>
<ul>
  <li>点击后立即通过当前配置的代理策略向测试探针发起真实 HTTP 请求；</li>
  <li>实时检测代理握手是否成功、统计建连与往返毫秒数（例如 <code>连接成功！耗时: 68ms</code>），或准确输出失败原因（如拒绝连接、认证失败、无法解析 PAC 脚本等），确保配置无误后再投入生产测试。</li>
</ul>


<h2 id="sec-mock">9. Mock 服务中心 (Mock Server Center)</h2>
<p>{APP_NAME} 内置全功能的独立本地 Mock 服务器，能够对外提供真实的 HTTP 端口监听与模拟服务，支持全方法路由匹配、延时模拟、自定义状态码与响应头、多级目录分类以及打入外部请求的全景实时监控。</p>

<h3>9.1 核心作用与使用场景</h3>
<ul>
  <li><b>前后端解耦并行开发</b>：在后端真实 API 尚未就绪前，前端或测试人员可一键启动 Mock 服务，提供高度契合业务结构的数据响应，无需等待后端排期；</li>
  <li><b>脱机与离线联调</b>：出差网络受限或内网无法直连测试环境时，可在本地完整模拟支付回调、第三方鉴权或全套业务链路；</li>
  <li><b>异常容灾与边界模拟</b>：轻松模拟服务端 404 资源缺失、500 服务崩溃、504 网关超时，以及网络高延迟（如 2000ms 慢网络），验证前端容错降级逻辑。</li>
</ul>

<h3>9.2 功能入口与端口启停授权</h3>
<ul>
  <li><b>功能入口</b>：点击顶部主菜单 <b>Mock中心(&M) → Mock 服务中心...</b> 或使用快捷键 <code>Ctrl+Alt+M</code>；</li>
  <li><b>端口配置与权限提示</b>：输入拟监听的本地端口（如 <code>9999</code> 或 <code>8000-65535</code>），点击 <b>开始 Mock</b> 按钮。系统会弹出明确授权提示窗口，征得用户同意后安全拉起后台 HTTP 线程并绑定端口；</li>
  <li><b>基准服务地址</b>：服务启动后，顶部工具栏会展示高亮绿色状态 <code>● 运行中: 端口 9999</code> 以及对外基准地址（如 <code>http://127.0.0.1:9999</code>），外部系统或代码可直接向该地址发起真实 HTTP 调用；随时点击「停止 Mock」即可瞬间安全释放端口。</li>
</ul>

<h3>8.3 接口多级树组织、复制与剪贴板操作</h3>
<ul>
  <li><b>左侧多级目录树</b>：支持新建项目文件夹与多级子目录（如 <code>用户中心 → 鉴权模块 → 查询用户详情</code>）；</li>
  <li><b>新建与重命名</b>：点击顶部 <b>+ 新建接口</b> 或 <b>+ 文件夹</b>，支持随时重命名与就地删除；</li>
  <li><b>搜索过滤</b>：输入路径或名称关键字，目录树毫秒级实时过滤；</li>
  <li><b>右键菜单与快捷复制</b>：右键支持「创建副本」、「复制接口」、「剪切接口」、「粘贴接口」，可在不同文件夹间自由迁移 Mock 接口。</li>
</ul>

<h3>8.4 Mock 规则配置与响应编辑器</h3>
<ul>
  <li><b>基本路由匹配</b>：配置接口名称、请求方式（GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS）、URL 路径（如 <code>/api/v1/users</code>）及是否启用；</li>
  <li><b>响应状态码与延迟注入</b>：可自由设置返回的 HTTP 状态码（如 <code>200</code>, <code>201</code>, <code>400</code>, <code>401</code>, <code>404</code>, <code>500</code> 等），支持毫秒级模拟网络延时（0 ~ 60000 ms）；</li>
  <li><b>响应内容与格式化</b>：支持 <code>json</code>, <code>text</code>, <code>html</code>, <code>xml</code> 四种返回类型。在编写 JSON 响应体时，点击 <b>格式化 JSON</b> 按钮即可一键美化排版与语法校验；</li>
  <li><b>自定义响应头 (Response Headers)</b>：支持添加任意自定义响应头（如 <code>X-Custom-Header</code>, <code>Set-Cookie</code>, <code>Cache-Control</code> 等），系统默认全自动处理 CORS 跨域请求；</li>
  <li><b>响应编辑区自适应与监控折叠</b>：响应内容编辑器具有全向弹性拉伸能力，窗口放大时享有最大化拉伸空间；顶部工具栏提供 <b>[▼ 折叠监控区]</b> 按钮，一键将全部垂直空间留给响应编辑区，极大提升编写大型 JSON 报文的沉浸感。</li>
</ul>

<h3>8.5 实时外部请求监控与全景排查</h3>
<ul>
  <li><b>打入外部请求实时捕获</b>：当外部程序或浏览器请求 Mock 服务时，右下角监控大盘实时捕获记录（请求时间、HTTP 方法、URL 路径、状态码、耗时、客户端 IP）；</li>
  <li><b>多维度入参审计</b>：鼠标选中任意一行请求记录，右侧选项卡清晰呈现：
    <ul>
      <li><b>入参 (Query)</b>：解析出的 URL Query 查询参数键值对表格；</li>
      <li><b>请求头 (Headers)</b>：外部请求携带的全部 HTTP Headers（含 User-Agent, Authorization 等）；</li>
      <li><b>Cookie</b>：外部请求携带的 Cookies；</li>
      <li><b>请求体 (Body)</b>：外部 POST/PUT 打入的请求体报文（JSON 格式自动格式化展开）；</li>
      <li><b>返回响应 (Response)</b>：查看当时 Mock 服务器回写给外部的真实状态码、响应头与响应体数据；</li>
    </ul>
  </li>
  <li><b>一键清空日志与监控最大化</b>：点击「清空请求日志」可重置监控大盘，点击「⛶ 最大化监控」可快速展开全屏监控视图。</li>
</ul>

<h2 id="sec-processors">10. 接口前置处理与后置处理 (Pre & Post Processors)</h2>
<p>在接口测试、链路编排或压测嗅探中，参数动态计算与跨接口上下文依赖至关重要。PostManage 创新提供了开箱即用的「前置处理」与「后置处理」双引擎，<b>无需编写任何晦涩的脚本语法，纯表格可视化配置，且前置/后置配置全自动同步至单接口调试、高并发压测与页面接口嗅探中！</b></p>

<h3>10.1 按钮位置与入口</h3>
<p>在请求编辑器的参数配置栏中，紧跟在 <b>Params、Headers、Body、Auth、Cookies</b> 标签之后，新增 <b>前置处理</b> 与 <b>后置处理</b> 专属配置选项卡。</p>

<h3>10.2 前置处理 (Pre-processor) — 发送前动态参数包装</h3>
<p>前置处理器在请求发送前自动执行，支持根据配置规则动态生成参数或从文件提取数据，并自动组装注入到请求报文中：</p>
<ul>
  <li><b>参数来源 (Source Type)</b>：
    <ul>
      <li><b>环境变量/表达式</b>：支持引用系统全局变量或上下文占位符（如 <code>{{{{token}}}}</code>、<code>{{{{account_id}}}}</code>）；</li>
      <li><b>本地文件读取 (File Reader)</b>：支持直接读取本地数据文件。支持 <b>JSON 文件</b>（支持点号深层提取如 <code>auth.token</code>）、<b>键值对配置文件</b>（<code>.env / .properties</code> 等号提取）以及<b>纯文本文件</b>（全文读取）；点击面板上的「💡 文件格式案例与说明」可随时查看规范样例；</li>
      <li><b>常用内置函数与计算 (Built-in Functions)</b>：点击「⚡ 常用内置函数」下拉菜单可一键生成常用动态计算规则：
        <ul>
          <li><code>UUID()</code> — 生成标准 UUID 唯一标识；</li>
          <li><code>Timestamp(ms)</code> / <code>Timestamp(s)</code> — 生成 13位毫秒级 或 10位秒级当前时间戳；</li>
          <li><code>RandomInt(min, max)</code> — 生成指定数值范围的随机整数（如 4位/6位验证码）；</li>
          <li><code>RandomString(len)</code> — 生成指定长度的随机英数字符串；</li>
          <li><code>MD5(text)</code> / <code>SHA256(text)</code> — 哈希算法摘要计算；</li>
          <li><code>Base64Encode(text)</code> / <code>Base64Decode(text)</code> — Base64 编解码。</li>
        </ul>
      </li>
    </ul>
  </li>
  <li><b>设置目标 (Target Type)</b>：
    <ul>
      <li><b>请求头 (Header)</b>：自动将计算值注入到发送的 HTTP 请求头中；若已存在同名 Header 则覆盖；</li>
      <li><b>查询参数 (Param)</b>：自动将参数注入到 URL Query 参数中；若已存在同名 Param 则覆盖；</li>
      <li><b>请求体 (Body)</b>：<b>智能组装覆盖！</b>如果设置目标为「请求体」，系统将在请求发送前将参数动态组装到原请求体中：
        <ul>
          <li>在 <b>JSON 请求体</b> 中：支持顶级字段或点号嵌套路径（如 <code>userId</code> 或 <code>data.profile.role</code>），若原请求体中已有该字段则<b>无损精准覆盖</b>，若原字段为数字或布尔类型则自动保持对应数据类型！</li>
          <li>在 <b>Form 表单 / Urlencoded</b> 中：自动查找对应行 <code>key=value</code> 进行就地覆盖替换，若不存在则追加；</li>
          <li>若原请求体为空（none），则自动初始化为标准 JSON 字典并组装注入！</li>
        </ul>
      </li>
      <li><b>环境变量 (Variable)</b>：存入运行时上下文，后续规则或 URL/Body 中可通过 <code>{{{{var}}}}</code> 占位符自由引用。</li>
    </ul>
  </li>
</ul>

<h3>10.3 后置处理 (Post-processor) — 响应数据提取与持久化回写</h3>
<p>后置处理器在收到服务端响应报文后自动触发，从响应中提取 Token 或关键业务标识并自动持久化写回：</p>
<ul>
  <li><b>提取来源 (Extract From)</b>：
    <ul>
      <li><b>响应头 (Header)</b>：提取指定响应头的值（如 <code>Set-Cookie</code>, <code>Authorization</code>）；</li>
      <li><b>响应 Cookie</b>：按 Cookie 名称提取对应值（如 <code>JSESSIONID</code>, <code>token</code>）；</li>
      <li><b>响应体 JSONPath</b>：轻量高性能 JSON 路径提取（支持 <code>data.token</code>, <code>user.id</code>, <code>items[0].id</code>）；</li>
      <li><b>响应体 正则 (Regex)</b>：支持正则表达式匹配提取（自动捕获第 1 组或整段匹配）；</li>
      <li><b>响应体 纯文本</b>：提取响应体原始全文内容。</li>
    </ul>
  </li>
  <li><b>保存目标 (Target Destination)</b>：
    <ul>
      <li><b>全局请求头 (Global Headers)</b>：<b>核心自动化利器！</b>提取到的 Token 自动写回系统全局请求头，<b>后续所有单接口调试、高并发压测以及页面接口嗅探将毫秒级全自动携带该 Header</b>，彻底告别手动复制 Token！</li>
      <li><b>Cookie 库 (Cookie Storage)</b>：自动写回本地标准 Cookie 存储库，并在目标域名下持久生效；</li>
      <li><b>环境变量 (Environment)</b>：持久化保存至环境变量，方便多接口之间参数级联传递。</li>
    </ul>
  </li>
</ul>

<h2 id="sec-save-dialog">11. 接口多级文件夹保存与另存为</h2>
<p>针对复杂企业级项目中庞大的接口目录树结构，PostManage 提供了全交互式的「保存请求」与「请求另存为」工作台：</p>
<ul>
  <li><b>多级子文件夹目录树</b>：完整呈现 1级项目、2级模块、3级子文件夹等无限层级的完整树形架构，支持在弹窗内直接选中任意深度的子文件夹节点；</li>
  <li><b>动态面包屑导航路径</b>：选中的文件夹会在顶部直观展示面包屑路径（如 <code>📁 电商系统 / 📁 用户中心 / 📁 登录模块</code>），杜绝误存；</li>
  <li><b>就地实时搜索过滤</b>：输入关键字瞬间过滤文件夹名称，快速定位目标分组；</li>
  <li><b>就地快速新建文件夹</b>：无需返回主窗口集合面板，在保存弹窗内即可直接点击 <b>[+ 新建文件夹]</b> 并指定所属父层级，实现即建即存。</li>
</ul>

<h2 id="sec-history">12. 历史记录</h2>
<p>每次发送请求都会自动保存到本地历史数据库。</p>
<ul>
<li>切换到左侧「历史」标签页查看最近发送的记录；</li>
<li>支持按 URL 或请求方法关键字进行快速检索过滤；</li>
<li>双击任意一条历史记录可快速恢复到当前编辑器继续调试；</li>
<li>点击顶部「清空」按钮可一键清理历史；历史记录默认保留最新 500 条。</li>
</ul>

<h2 id="sec-shortcuts">13. 常用快捷键一览</h2>
<table>
<tr><th>快捷键</th><th>对应功能</th><th>快捷键</th><th>对应功能</th></tr>
<tr><td><code>Ctrl+Enter</code></td><td>发送当前请求</td><td><code>Ctrl+S</code></td><td>保存请求到集合</td></tr>
<tr><td><code>Ctrl+N</code></td><td>新建空白请求标签页</td><td><code>Ctrl+Shift+N</code></td><td>新建集合</td></tr>
<tr><td><code>Ctrl+C</code></td><td>复制选中的接口 (集合树)</td><td><code>Ctrl+X</code></td><td>剪切选中的接口 (集合树)</td></tr>
<tr><td><code>Ctrl+V</code></td><td>粘贴接口 (集合树)</td><td><code>Del</code></td><td>删除选中接口/集合</td></tr>
<tr><td><code>Ctrl+Shift+I</code></td><td>导入集合 / Postman 文件</td><td><code>Ctrl+Shift+E</code></td><td>导出集合为 JSON</td></tr>
<tr><td><code>Ctrl+Alt+S</code></td><td><b>高并发性能压测</b></td><td><code>Ctrl+Alt+P</code></td><td><b>页面接口智能嗅探</b></td></tr>
<tr><td><code>Ctrl+Alt+M</code></td><td><b>Mock 服务中心</b></td><td><code>Ctrl+Shift+T</code></td><td>切换亮色 / 暗色护眼主题</td></tr>
<tr><td><code>Ctrl+F1</code></td><td>打开本使用说明书</td><td><code>Ctrl+Q</code></td><td>安全退出程序</td></tr>
</table>

<h2 id="sec-theme">14. 视觉主题与色彩哲学</h2>
<p>PostManage 专为工程师长时间编码打造：</p>
<ul>
<li><b>亮色模式 (Light)</b>：采用极低饱和度的奶白与雅灰底层（<code>#ffffff / #f8f9fa</code>），杜绝刺眼纯白反光，柔和护眼；</li>
<li><b>暗色模式 (Dark)</b>：沉稳黑曜石深灰色系（<code>#1f2937 / #111827</code>），弱化高频对比度，夜间调试更舒适；</li>
<li><b>热切换支持</b>：可通过菜单 <b>视图 → 切换主题</b> 或按 <code>Ctrl+Shift+T</code> 即时切换，偏好自动持久化。</li>
</ul>

<h2 id="sec-data">15. 本地数据存储、自定义目录与日志安全</h2>
<p>所有集合、请求、历史记录与环境配置均保存在本地 SQLite 数据库中。系统默认采用<b>绿色便携模式 (Portable Mode)</b>，开箱即用、随拷随走：</p>

<h3>15.1 默认便携存储路径</h3>
<ul>
<li><b>数据存储目录</b>：默认位于安装程序/可执行文件同级 <code>&lt;应用目录&gt;/data/</code>；</li>
<li><b>核心数据库</b>：<code>&lt;应用目录&gt;/data/requestmanager.db</code>；</li>
<li><b>持久化配置</b>：<code>&lt;应用目录&gt;/data/config.json</code> 及 <code>cookies.json</code>；</li>
<li><b>日志目录</b>：<code>&lt;应用目录&gt;/data/logs/postmanage.log</code>。</li>
</ul>
<div class="note">
<b>容错保障：</b>若软件运行在受限只读目录中（如无管理员写入权限的 Program Files），系统会自动安全回退至用户目录（如 <code>%APPDATA%/PostManage/data</code>），确保数据读写永不报错。
</div>

<h3>15.2 自定义存储与日志目录</h3>
<p>系统完整支持自由定义数据与日志的存储位置，方便集中管理或挂载到网络驱动器：</p>
<ol>
<li><b>进入设置</b>：点击顶部菜单栏 <b>编辑(&E) → 设置 (Ctrl+,)</b>；</li>
<li><b>配置数据存储目录</b>：在「数据存储目录」行点击 <b>[浏览...]</b> 选择自定义目录；</li>
<li><b>数据智能平滑迁移</b>：若选中的新目录下暂无数据库文件，系统会弹出确认框提示<b>「是否将当前现有的数据（集合、请求、历史、配置与Cookies）自动迁移复制到新目录？」</b>，确认后毫秒级全量复制，保障已有资产万无一失；</li>
<li><b>配置日志输出目录</b>：支持独立自定义日志文件的存放路径；</li>
<li><b>一键恢复默认</b>：点击输入框右侧的 <b>[恢复默认]</b> 按钮，即可瞬间恢复为程序同级便携目录；</li>
<li><b>热生效免重启</b>：点击「确定」后，底层数据库连接池与日志输出流实时切换，工作区界面即刻无感刷新，无需重启软件。</li>
</ol>

<h3>15.3 关键运行日志与快速排查</h3>
<p>系统内置工业级自动日志轮转体系，记录系统启动、请求发送与取消、报错排查等关键事件：</p>
<ul>
<li><b>自动轮转机制</b>：单文件达到 10MB 时自动切分，自动保留最新 5 个历史备份文件，防止无休止占用磁盘空间；</li>
<li><b>快捷打开入口</b>：随时点击顶部菜单栏 <b>帮助(&H) → 打开日志目录</b>，即可快速调出本地日志文件夹进行故障排查。</li>
</ul>

<div class="tip">
<b>绝对隐私保证：</b>本软件不向任何外部云端上传您的接口凭证、密码或业务报文数据。如需换机迁移，直接拷贝整个 <code>data/</code> 文件夹或使用集合导出功能即可。
</div>

<h2 id="sec-faq">16. 常见问题解答 (FAQ)</h2>
<h3>Q: 嗅探多轮压测为什么不会出现接口处于 pending 挂起的状态？</h3>
<p>A: PostManage 采用了类似于 Puppeteer 的自适应 Network Idle 状态机机制。系统在 CDP 监听通道中对每一个在途网络请求（In-flight Requests）进行毫秒级生命周期追踪。当且仅当本轮所有异步请求全部响应完毕并维持 150ms 静默窗口后，才会判定当前轮次完成并立即进入下一轮刷新，既杜绝了接口被客户端强制中断（pending/canceled），又以实际网络物理速度极速推进！</p>

<h3>Q: 什么是无头模式（Headless）？为什么有时配置的代理在无头模式会失效？</h3>
<p>A: 无头模式是指浏览器完全在没有图形界面的后台静默执行。Chromium 在无头模式下通常使用临时隔离用户数据目录（<code>--user-data-dir</code>），默认不会隐式继承系统的部分扩展与注册表。PostManage 在唤起无头浏览器时，会自动通过 CLI 显式注入 <code>--proxy-server</code>、<code>--proxy-pac-url</code>、<code>--proxy-bypass-list</code> 及 <code>--ignore-certificate-errors</code> 等参数，确保无头模式与静默 Go 协程压测同样 100% 严格走代理网络通道。</p>

<h3>Q: PAC 模式配置脚本只能使用某种固定模板吗？支持其他语法和格式吗？</h3>
<p>A: 绝不仅限于固定模板！PAC（Proxy Auto-Configuration）是全球所有主流浏览器通用的开放标准规范。PostManage 内置了完整的通用 PAC 语法解析与执行引擎。无论是使用对象字典查表、子网掩码网段（isInNet）、域名后缀（dnsDomainIs）、通配符（shExpMatch）、switch-case、还是多代理容灾返回，任何符合标准 JavaScript 规范的 PAC 脚本均可开箱即用，无需对脚本做任何特殊修改！</p>

<h3>Q: PAC 代理脚本在浏览器中可以访问，在 PostManage 中如何确保生效？</h3>
<p>A: 在【编辑 -> 全局代理配置】或接口详情中，选择「📜 PAC 自动脚本模式」，直接填入脚本 URL（如 <code>http://127.0.0.1:18033/proxy.pac</code>）或本地路径。点击下方的【⚡ 测试代理连接】按钮可立即验证当前 PAC 规则是否匹配成功。PostManage 具备专属 PAC JavaScript 规则解析引擎，完全兼容 <code>shExpMatch</code> 与 <code>isInNet</code> 等官方规范。</p>

<h3>Q: 压测能达到多高的并发和 TPS？</h3>
<p>A: 压测底层由经过极速裁剪的 Go 独立引擎驱动，采用 Goroutine 原生协程池与高效 HTTP 连接复用，在主流个人电脑上可轻松达到数万 TPS 吞吐，压测过程不占用 Python UI 线程，界面始终丝滑不卡顿。</p>

<h3>Q: 页面接口嗅探支持内网 Web 系统吗？</h3>
<p>A: 只要当前运行 PostManage 的电脑能够网络访问该内网 Web 页面，嗅探引擎即可正常下载 HTML 与外链 JS 并自动提取接口进行连通性与并发压测。</p>

<h3>Q: 如何将嗅探出来的接口持久化保存？</h3>
<p>A: 在嗅探大盘中点击对应接口的「导入调试」按钮，接口将立即被加载到主编辑器的新标签页中，点击保存或按 <code>Ctrl+S</code> 即可保存至指定的集合目录中。</p>

<h3>Q: Mock 服务启动失败，提示端口被占用怎么办？</h3>
<p>A: 可以在 Mock 监听端口输入框中修改为其他未被占用的端口（如 9998、8088、18080 等），再次点击「开始 Mock」即可。</p>

<h3>Q: 前置处理中设置的目标为「请求体」时，如何与原有的 JSON Body 配合？</h3>
<p>A: 前置处理会在发送请求前自动将目标字段注入或覆盖到请求体中。例如原请求体为 <code>{{"userId": 100, "token": "old"}}</code>，在前置处理中配置提取文件中的 token 并设置目标为请求体、目标名称为 <code>token</code>，请求发送时该字段的值将全自动被覆盖更新，若字段为数字或布尔值还会智能保留数据类型；若原请求体无内容（none），则会自动转为标准 JSON 格式并封装目标字段。</p>

<h3>Q: 后置处理提取的 Token 如何在其他接口或压测中自动生效？</h3>
<p>A: 在后置处理中将保存目标选择为「全局请求头 (Global Headers)」，提取后的 Token 会自动写入系统全局请求头。随后所有接口标签页以及高并发性能压测、页面接口嗅探均会自动携带该请求头。</p>

<h3>Q: 调试大模型 (LLM) 流式接口时，如何一键提取并复制拼接好的完整回复？</h3>
<p>A: 收到 SSE 或流式分块响应后，在响应栏右侧点击 <b>[整合]</b> 按钮。系统默认配置了 <code>data:</code> 前缀与 <code>choices[0].delta.content</code> 字段（也支持切换 Anthropic、Ollama 或单字段简写）。系统会自动过滤 <code>[DONE]</code> 标记并合并所有字词生成完整文章，点击右侧的 <b>[一键复制]</b> 即可将最终文本存入剪贴板。</p>

<h3>Q: 修改或新增全局请求头后，已打开的标签页会生效吗？</h3>
<p>A: 会立即生效。PostManage 具备响应式请求头广播机制，无论是打开设置弹窗修改，还是在某个标签页的「全局请求头」面板中编辑，所有已打开的 Tab 和新建 Tab 均实时无感同步最新配置。若单个标签页中配置了相同名称的 Header，则以该标签页的配置优先覆盖。</p>

<h3>Q: Cookie 是如何按照域名进行隔离与自动携带的？</h3>
<p>A: 系统内置了 RFC 6265 标准 Cookie 存储引擎。所有 Cookie 均以 <code>Domain</code> 与 <code>Path</code> 为键进行持久化存储。每次发送请求时，系统会自动分析目标 URL 的主机名，匹配并注入所有符合该域名的 Cookies，无需手动复制粘贴。</p>

<h2 id="sec-author">17. 版本与作者信息</h2>
<table>
<tr><td><b>软件名称</b></td><td>{APP_NAME}</td></tr>
<tr><td><b>发布版本</b></td><td>{APP_VERSION}</td></tr>
<tr><td><b>核心作者</b></td><td>{APP_AUTHOR}</td></tr>
<tr><td><b>开源许可</b></td><td>{APP_LICENSE} 开源协议</td></tr>
</table>

<h2 id="sec-copyright">18. 版权与开源声明</h2>
<p>{APP_COPYRIGHT}</p>
<p>根据 {APP_LICENSE} 许可证规定，任何人均可自由使用、分发、修改本软件代码。本软件按“现状”提供，不包含任何明示或暗示的商业担保。</p>

<h2 id="sec-donate">19. 请作者喝杯咖啡 ☕</h2>
<p>这款工具是作者在业余时间一点点打磨出来的，初衷是给大家提供一个简单、干净、离线且高性能的 API 与压测调试助手。如果你在日常工作中用到了它，觉得还算顺手，欢迎请作者喝杯咖啡支持后续迭代！</p>
<table style="width:100%; border:none; margin:16px 0;">
<tr style="background:none;">
<td style="text-align:center; border:none; padding:12px; width:50%;">
<img src="{wechat_qr}" alt="微信打赏" style="border:1px solid #ddd; border-radius:8px; padding:6px; background:#fff;">
<br><span style="font-size:13px; color:#999;">微信赞赏</span>
</td>
<td style="text-align:center; border:none; padding:12px; width:50%;">
<img src="{alipay_qr}" alt="支付宝打赏" style="border:1px solid #ddd; border-radius:8px; padding:6px; background:#fff;">
<br><span style="font-size:13px; color:#999;">支付宝打赏</span>
</td>
</tr>
</table>
<p style="text-align:center;"><span style="font-size:13px; color:#999;">扫码打赏，金额随意，感谢每一位同行的认可与支持！</span></p>

</body>
</html>
"""


class HelpViewer(QDialog):
    """帮助文档查看器对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} - 使用说明书")
        self.setMinimumSize(860, 680)
        self.resize(980, 740)
        self._init_ui()
        self._apply_theme()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # ─── 搜索栏 ─────────────────────────────────────────
        search_layout = QHBoxLayout()

        search_label = QLabel("查找:")
        search_label.setStyleSheet("font-weight: bold;")
        search_layout.addWidget(search_label)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入关键字搜索文档内容 (如: 压测, 嗅探, 代理, 无头模式, 快捷键)...")
        self.search_input.textChanged.connect(self._on_search)
        self.search_input.returnPressed.connect(self._on_return_pressed)
        self.search_input.setStyleSheet("""
            QLineEdit {
                padding: 6px 10px;
                border: 1px solid #ccc;
                border-radius: 4px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #3b82f6;
            }
        """)
        search_layout.addWidget(self.search_input)

        self.btn_search = QPushButton("查找")
        self.btn_search.setFixedWidth(60)
        self.btn_search.clicked.connect(self._on_search)
        search_layout.addWidget(self.btn_search)

        self.btn_prev = QPushButton("上一个")
        self.btn_prev.setFixedWidth(60)
        self.btn_prev.clicked.connect(self._on_search_prev)
        self.btn_prev.setEnabled(False)
        search_layout.addWidget(self.btn_prev)

        self.btn_next = QPushButton("下一个")
        self.btn_next.setFixedWidth(60)
        self.btn_next.clicked.connect(self._on_search_next)
        self.btn_next.setEnabled(False)
        search_layout.addWidget(self.btn_next)

        self.search_status = QLabel("")
        self.search_status.setStyleSheet("font-size: 12px; color: #888;")
        search_layout.addWidget(self.search_status)

        layout.addLayout(search_layout)

        # ─── 文档浏览器 ─────────────────────────────────────
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(False)
        help_html = _build_help_html()
        self.browser.setHtml(help_html)
        self.browser.setFont(QFont("Microsoft YaHei", 10))
        layout.addWidget(self.browser)

        # 搜索相关状态
        self._search_matches = []
        self._current_match_index = -1
        self._original_html = help_html

    def _apply_theme(self):
        t = ThemeManager.current()
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {t.bg_primary};
            }}
            QLabel {{
                color: {t.text_primary};
            }}
            QLineEdit {{
                background-color: {t.bg_input};
                color: {t.text_primary};
                border: 1px solid {t.border};
            }}
            QPushButton {{
                background-color: {t.bg_input};
                color: {t.text_primary};
                border: 1px solid {t.border};
                border-radius: 4px;
                padding: 4px 10px;
            }}
            QPushButton:hover {{
                background-color: {t.bg_hover};
            }}
        """)

    def _on_return_pressed(self):
        if self._search_matches:
            self._on_search_next()
        else:
            self._on_search()

    def _on_search(self):
        query = self.search_input.text().strip()
        if not query:
            self.search_status.setText("")
            self.btn_prev.setEnabled(False)
            self.btn_next.setEnabled(False)
            self.browser.setExtraSelections([])
            self._search_matches = []
            self._current_match_index = -1
            return

        from PyQt6.QtGui import QTextCursor

        # 查找文档中所有匹配项
        doc = self.browser.document()
        matches = []
        cursor = QTextCursor(doc)
        while not cursor.isNull() and not cursor.atEnd():
            cursor = doc.find(query, cursor)
            if not cursor.isNull():
                matches.append(QTextCursor(cursor))

        self._search_matches = matches

        if not matches:
            self.search_status.setText("未找到匹配内容")
            self.btn_prev.setEnabled(False)
            self.btn_next.setEnabled(False)
            self.browser.setExtraSelections([])
            self._current_match_index = -1
            return

        self._current_match_index = 0
        self.btn_prev.setEnabled(len(matches) > 1)
        self.btn_next.setEnabled(len(matches) > 1)
        self._highlight_and_scroll()

    def _highlight_and_scroll(self):
        """用荧光黄标出所有匹配的关键字，并将当前匹配项用亮橙黄突出并平滑滚动定位"""
        from PyQt6.QtWidgets import QTextEdit
        from PyQt6.QtGui import QTextCharFormat, QColor

        if not self._search_matches or self._current_match_index < 0:
            self.browser.setExtraSelections([])
            return

        idx = self._current_match_index % len(self._search_matches)
        self._current_match_index = idx

        # 所有找到的关键字使用荧光黄色标出 (Fluorescent Yellow)
        fmt_all = QTextCharFormat()
        fmt_all.setBackground(QColor("#ffff00"))
        fmt_all.setForeground(QColor("#000000"))

        # 当前选中的匹配项使用琥珀金黄突出
        fmt_current = QTextCharFormat()
        fmt_current.setBackground(QColor("#f59e0b"))
        fmt_current.setForeground(QColor("#ffffff"))
        fmt_current.setFontWeight(QFont.Weight.Bold)

        extra_selections = []
        for i, cursor in enumerate(self._search_matches):
            extra = QTextEdit.ExtraSelection()
            extra.cursor = cursor
            extra.format = fmt_current if i == idx else fmt_all
            extra_selections.append(extra)

        self.browser.setExtraSelections(extra_selections)

        # 滚动居中定位当前项
        curr_cursor = self._search_matches[idx]
        self.browser.setTextCursor(curr_cursor)
        self.browser.ensureCursorVisible()

        total = len(self._search_matches)
        self.search_status.setText(f"第 {idx + 1} / {total} 项")

    def _on_search_next(self):
        if not self._search_matches:
            self._on_search()
            return
        self._current_match_index = (self._current_match_index + 1) % len(self._search_matches)
        self._highlight_and_scroll()

    def _on_search_prev(self):
        if not self._search_matches:
            self._on_search()
            return
        self._current_match_index = (self._current_match_index - 1 + len(self._search_matches)) % len(self._search_matches)
        self._highlight_and_scroll()
