package models

import "time"

// KeyValueItem 通用键值对项（用于 Headers, Params 等）
type KeyValueItem struct {
	Key     string `json:"key"`
	Value   string `json:"value"`
	Enabled bool   `json:"enabled"`
}

// RequestData API 请求完整数据模型
type RequestData struct {
	ID           string            `json:"id"`
	CollectionID string            `json:"collection_id"`
	Name         string            `json:"name"`
	Method       string            `json:"method"`
	URL          string            `json:"url"`
	Headers      []KeyValueItem    `json:"headers"`
	Params       []KeyValueItem    `json:"params"`
	BodyType     string            `json:"body_type"` // none, json, form, urlencoded, raw, binary
	BodyContent  string            `json:"body_content"`
	AuthType     string            `json:"auth_type"` // none, basic, bearer, apikey
	AuthConfig   map[string]string `json:"auth_config"`
	Cookies      []KeyValueItem    `json:"cookies,omitempty"`
	Timeout      int64             `json:"timeout"` // 毫秒，0 表示无限制
	SortOrder    int               `json:"sort_order"`
	ProxyURL     string            `json:"proxy_url,omitempty"` // 单请求指定代理 (如 http://192.168.66.44:8443, direct)
	CreatedAt    time.Time         `json:"created_at"`
	UpdatedAt    time.Time         `json:"updated_at"`
}

// TimingDetail 网络全链路各阶段耗时明细（毫秒）
type TimingDetail struct {
	DNSLookupMS    float64 `json:"dns_lookup_ms"`    // DNS 解析耗时
	TCPConnectMS   float64 `json:"tcp_connect_ms"`   // TCP 建连耗时
	TLSHandshakeMS float64 `json:"tls_handshake_ms"` // TLS 握手耗时
	RequestSendMS  float64 `json:"request_send_ms"`  // 请求写入发送耗时
	TTFBMS         float64 `json:"ttfb_ms"`          // 等待服务器首包耗时 (Time To First Byte)
	DownloadMS     float64 `json:"download_ms"`      // 响应数据下载耗时
	TotalMS        float64 `json:"total_ms"`         // 总耗时
}

// HTTPResponseData HTTP 响应结果模型
type HTTPResponseData struct {
	StatusCode int               `json:"status_code"`
	Reason     string            `json:"reason"`
	Headers    map[string]string `json:"headers"`
	Cookies    map[string]string `json:"cookies"`
	Body       string            `json:"body"`
	SizeBytes  int64             `json:"size_bytes"`
	SizeText   string            `json:"size_text"`
	ElapsedMS  float64           `json:"elapsed_ms"`
	Timing     TimingDetail      `json:"timing"`
	Error      string            `json:"error,omitempty"`
}

// StressConfig 压测参数配置
type StressConfig struct {
	Concurrency   int   `json:"concurrency"`    // 并发用户数 (1~200)
	DurationSec   int   `json:"duration_sec"`   // 持续时间（秒）
	TotalRequests int   `json:"total_requests"` // 目标请求总数（与持续时间互斥或选一）
	RampUpSec     int   `json:"ramp_up_sec"`    // 爬坡升压时间（秒）
	DelayMS       int    `json:"delay_ms"`       // 单次请求后间隔（毫秒）
	TimeoutMS     int64  `json:"timeout_ms"`     // 单请求超时（毫秒）
	ProxyURL      string `json:"proxy_url,omitempty"` // 代理服务器地址 (如 http://192.168.66.44:8443, 或 direct)
}

// StressSample 压测单次采样点
type StressSample struct {
	LatencyMS  float64 `json:"latency_ms"`
	StatusCode int     `json:"status_code"`
	Success    bool    `json:"success"`
	Error      string  `json:"error,omitempty"`
}

// RequestRecord 压测中单次请求记录明细
type RequestRecord struct {
	Index           int64             `json:"index"`                     // 请求序号 (1, 2, 3...)
	OffsetMS        float64           `json:"offset_ms"`                 // 距离压测启动的时间偏移（毫秒）
	Method          string            `json:"method"`                    // 请求方法
	URL             string            `json:"url"`                       // 目标 URL
	StatusCode      int               `json:"status_code"`               // 响应状态码
	ElapsedMS       float64           `json:"elapsed_ms"`                // 响应时间（毫秒）
	SizeBytes       int64             `json:"size_bytes"`                // 数据包大小（字节）
	Error           string            `json:"error,omitempty"`           // 错误信息
	RequestHeaders  map[string]string `json:"request_headers,omitempty"`  // 请求头
	RequestBody     string            `json:"request_body,omitempty"`     // 请求体
	ResponseHeaders map[string]string `json:"response_headers,omitempty"` // 响应头
	ResponseBody    string            `json:"response_body,omitempty"`    // 响应体
}

// StressResult 压测聚合分析报告
type StressResult struct {
	TotalRequests  int64            `json:"total_requests"`
	SuccessCount   int64            `json:"success_count"`
	FailureCount   int64            `json:"failure_count"`
	SuccessRate    float64          `json:"success_rate"`
	ElapsedSec     float64          `json:"elapsed_sec"`
	AvgTPS         float64          `json:"avg_tps"`
	PeakTPS        float64          `json:"peak_tps"`
	QPS            float64          `json:"qps"`            // 每秒查询数 (单接口模式下与 AvgTPS 等同)
	ThroughputRPS  float64          `json:"throughput_rps"` // 吞吐量 (每秒请求数)
	AvgLatencyMS   float64          `json:"avg_latency_ms"`
	MinLatencyMS   float64          `json:"min_latency_ms"`
	MaxLatencyMS   float64          `json:"max_latency_ms"`
	P50MS          float64          `json:"p50_ms"`
	P90MS          float64          `json:"p90_ms"`
	P99MS          float64          `json:"p99_ms"`
	TotalBytes     int64            `json:"total_bytes"`
	BandwidthKBps  float64          `json:"bandwidth_kbps"`
	StatusCodeDist map[int]int64    `json:"status_code_dist"`
	LatencyBins    map[string]int64 `json:"latency_bins"` // <50ms, 50-200ms, 200-500ms, >500ms
	DiagnosisTips  []string         `json:"diagnosis_tips"`
	ProxyURL       string           `json:"proxy_url,omitempty"` // 本次压测实际使用的代理
	Records        []RequestRecord  `json:"records,omitempty"` // 请求结果清单明细
}

// PageEndpoint 页面嗅探到的后端 API 端点
type PageEndpoint struct {
	Method     string            `json:"method"`          // GET, POST 等
	URL        string            `json:"url"`             // 完整解析后的 URL
	Path       string            `json:"path"`            // 相对路径
	StatusCode int               `json:"status_code"`     // 探测状态码
	LatencyMS  float64           `json:"latency_ms"`      // 探测耗时
	StatusType string            `json:"status_type"`     // healthy (2xx), warning (401/403/slow), critical (404/500/timeout)
	Snippet    string            `json:"snippet"`         // 源码匹配片段或类型
	Body       string            `json:"body,omitempty"`  // 请求体 (POST/PUT 时携带)
	Headers    map[string]string `json:"headers,omitempty"` // 单接口特定头
}

// PageScanConfig 页面扫描配置
type PageScanConfig struct {
	TargetURL string            `json:"target_url"`
	Headers   map[string]string `json:"headers,omitempty"`   // 全局请求头
	Cookies   map[string]string `json:"cookies,omitempty"`   // 匹配的域名 Cookie
	ProxyURL  string            `json:"proxy_url,omitempty"`  // 代理服务器 (如 http://192.168.66.44:8443)
}

// PageScanResult 页面接口智能嗅探大盘
type PageScanResult struct {
	TargetURL      string         `json:"target_url"`
	TotalEndpoints int            `json:"total_endpoints"`
	HealthyCount   int            `json:"healthy_count"`
	WarningCount   int            `json:"warning_count"`
	CriticalCount  int            `json:"critical_count"`
	ElapsedMS      float64        `json:"elapsed_ms"`
	Endpoints      []PageEndpoint `json:"endpoints"`
}

// PageStressConfig 页面全接口并发压测配置
type PageStressConfig struct {
	TargetURL     string            `json:"target_url"`
	Endpoints     []PageEndpoint    `json:"endpoints"`          // 若为空则自动嗅探获取
	Concurrency   int               `json:"concurrency"`        // 并发协程数 (默认 5)
	TotalRequests int               `json:"total_requests"`     // 计划执行的总页面加载轮次 (默认 20)
	DelayMS       int               `json:"delay_ms"`           // 请求间隔毫秒 (默认 50)
	TimeoutMS     int               `json:"timeout_ms"`         // 超时时间毫秒 (默认 5000)
	Headers       map[string]string `json:"headers,omitempty"`   // 全局请求头
	Cookies       map[string]string `json:"cookies,omitempty"`   // 匹配的域名 Cookie
	ProxyURL      string            `json:"proxy_url,omitempty"`// 代理服务器 (如 http://192.168.66.44:8443)
}

// PageIterationRecord 单次全页面压测轮次记录 (一次完整的全接口加载会话)
type PageIterationRecord struct {
	Index           int64   `json:"index"`
	OffsetMS        float64 `json:"offset_ms"`
	PageLoadMS      float64 `json:"page_load_ms"`      // 页面加载时长 (当次所有接口中的最长耗时)
	Success         bool    `json:"success"`           // 是否当次所有接口全部成功
	EndpointCount   int     `json:"endpoint_count"`
	FailedEndpoints int     `json:"failed_endpoints"`
	ErrorSummary    string  `json:"error_summary,omitempty"`
}

// EndpointRanking 页面接口平均耗时排行
type EndpointRanking struct {
	Rank         int     `json:"rank"`
	Method       string  `json:"method"`
	URL          string  `json:"url"`
	Path         string  `json:"path"`
	AvgLatencyMS float64 `json:"avg_latency_ms"`
	MaxLatencyMS float64 `json:"max_latency_ms"`
	MinLatencyMS float64 `json:"min_latency_ms"`
	SuccessRate  float64 `json:"success_rate"`
	ErrorCount   int64   `json:"error_count"`
	TotalCalls   int64   `json:"total_calls"`
	SharePercent float64 `json:"share_percent"` // 占页面总耗时比例 %
}

// EndpointErrorStat 页面接口错误与异常归因统计
type EndpointErrorStat struct {
	Method      string        `json:"method"`
	URL         string        `json:"url"`
	ErrorCount  int64         `json:"error_count"`
	ErrorRate   float64       `json:"error_rate"`
	StatusCodes map[int]int64 `json:"status_codes"`
	LastErrors  []string      `json:"last_errors,omitempty"`
}

// EndpointStressReport 单个接口的独立压测统计报告
type EndpointStressReport struct {
	Method         string           `json:"method"`
	URL            string           `json:"url"`
	Path           string           `json:"path"`
	TotalRequests  int64            `json:"total_requests"`
	SuccessCount   int64            `json:"success_count"`
	ErrorCount     int64            `json:"error_count"`
	TimeoutCount   int64            `json:"timeout_count"`
	AvgLatencyMS   float64          `json:"avg_latency_ms"`
	MinLatencyMS   float64          `json:"min_latency_ms"`
	MaxLatencyMS   float64          `json:"max_latency_ms"`
	P50MS          float64          `json:"p50_ms"`
	P90MS          float64          `json:"p90_ms"`
	P95MS          float64          `json:"p95_ms"`
	P99MS          float64          `json:"p99_ms"`
	TimeoutRate    float64          `json:"timeout_rate"` // 超时率 %
	ErrorRate      float64          `json:"error_rate"`   // 错误率 %
	SuccessRate    float64          `json:"success_rate"` // 成功率 %
	QPS            float64          `json:"qps"`
	StatusCodeDist map[int]int64    `json:"status_code_dist"`
	LatencyBins    map[string]int64 `json:"latency_bins"`
	DiagnosisTips  []string         `json:"diagnosis_tips"`
	ProxyURL       string           `json:"proxy_url,omitempty"` // 本次压测实际使用的代理
	Records        []RequestRecord  `json:"records,omitempty"` // 请求结果清单明细
}

// PageStressResult 整个页面的聚合压测大盘结果 (全页面事务模型)
type PageStressResult struct {
	TargetURL                string                 `json:"target_url"`
	TotalEndpoints           int                    `json:"total_endpoints"`
	TotalRequests            int64                  `json:"total_requests"`
	SuccessCount             int64                  `json:"success_count"`
	ErrorCount               int64                  `json:"error_count"`
	TimeoutCount             int64                  `json:"timeout_count"`
	AvgLatencyMS             float64                `json:"avg_latency_ms"`
	ElapsedSec               float64                `json:"elapsed_sec"`
	OverallTPS               float64                `json:"overall_tps"`
	QPS                      float64                `json:"qps"`                        // 全页面底层 API 接口每秒总请求数 (QPS)
	ThroughputRPS            float64                `json:"throughput_rps"`             // 接口总吞吐量 (req/s)
	// 新增：全页面事务级压测核心口径
	TotalPageIterations      int64                  `json:"total_page_iterations"`      // 总页面加载轮次
	SuccessfulPageIterations int64                  `json:"successful_page_iterations"` // 所有接口皆成功的轮次
	FailedPageIterations     int64                  `json:"failed_page_iterations"`     // 失败轮次
	PageSuccessRate          float64                `json:"page_success_rate"`          // 页面整体成功率 %
	AvgPageLoadDurationMS    float64                `json:"avg_page_load_duration_ms"`  // 页面平均加载时长 (单轮所有接口最大耗时的均值)
	MinPageLoadDurationMS    float64                `json:"min_page_load_duration_ms"`
	MaxPageLoadDurationMS    float64                `json:"max_page_load_duration_ms"`
	P90PageLoadDurationMS    float64                `json:"p90_page_load_duration_ms"`
	P95PageLoadDurationMS    float64                `json:"p95_page_load_duration_ms"`
	PageRPS                  float64                `json:"page_rps"`                   // 页面每秒完成轮次 (页面吞吐量 RPS)
	PageTPS                  float64                `json:"page_tps"`                   // 页面事务吞吐量 (Page TPS)
	EndpointRankings         []EndpointRanking      `json:"endpoint_rankings,omitempty"`
	EndpointErrorStats       []EndpointErrorStat    `json:"endpoint_error_stats,omitempty"`
	PageRecords              []PageIterationRecord  `json:"page_records,omitempty"`     // 页面轮次时序记录
	Records                  []RequestRecord        `json:"records,omitempty"`          // 全量请求明细
	EndpointReports          []EndpointStressReport `json:"endpoint_reports"`
}

// Collection 集合模型（支持多层级嵌套）
type Collection struct {
	ID          string    `json:"id"`
	Name        string    `json:"name"`
	ParentID    string    `json:"parent_id,omitempty"` // 父集合 ID，为空表示根集合
	Description string    `json:"description"`
	SortOrder   int       `json:"sort_order"`
	CreatedAt   time.Time `json:"created_at"`
	UpdatedAt   time.Time `json:"updated_at"`
}

// HistoryRecord 历史记录模型
type HistoryRecord struct {
	ID           string       `json:"id"`
	Name         string       `json:"name"`
	Method       string       `json:"method"`
	URL          string       `json:"url"`
	StatusCode   int          `json:"status_code"`
	ElapsedMS    float64      `json:"elapsed_ms"`
	SizeBytes    int64        `json:"size_bytes"`
	Timing       TimingDetail `json:"timing"`
	RequestData  RequestData  `json:"request_data"`
	CreatedAt    time.Time    `json:"created_at"`
}
