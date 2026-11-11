package client

import (
	"bytes"
	"context"
	"crypto/tls"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/httptrace"
	"net/url"
	"os"
	"strings"
	"time"

	"postmanage/internal/config"
	"postmanage/internal/core/models"
)

// HTTPClient 具备全链路网络耗时追踪与全局请求头优先级合并的高性能客户端
type HTTPClient struct {
	client *http.Client
}

// NewHTTPClient 创建客户端实例
func NewHTTPClient() *HTTPClient {
	transport := &http.Transport{
		Proxy: http.ProxyFromEnvironment,
		TLSClientConfig: &tls.Config{
			InsecureSkipVerify: true, // 允许自签名证书测试
		},
		MaxIdleConns:        1000,
		MaxIdleConnsPerHost: 200,
		IdleConnTimeout:     90 * time.Second,
		DisableCompression: false,
	}

	return &HTTPClient{
		client: &http.Client{
			Transport: transport,
			CheckRedirect: func(req *http.Request, via []*http.Request) error {
				if len(via) >= 10 {
					return fmt.Errorf("stopped after 10 redirects")
				}
				return nil
			},
		},
	}
}

// NewHTTPClientWithProxy 创建具备指定代理配置的高性能客户端
func NewHTTPClientWithProxy(proxyURL string) *HTTPClient {
	var proxyFunc func(*http.Request) (*url.URL, error)
	trimmed := strings.TrimSpace(proxyURL)
	if trimmed != "" {
		if strings.EqualFold(trimmed, "direct") || strings.EqualFold(trimmed, "none") {
			proxyFunc = nil
		} else if pURL, err := url.Parse(trimmed); err == nil {
			proxyFunc = http.ProxyURL(pURL)
		} else {
			proxyFunc = http.ProxyFromEnvironment
		}
	} else {
		proxyFunc = http.ProxyFromEnvironment
	}

	transport := &http.Transport{
		Proxy: proxyFunc,
		TLSClientConfig: &tls.Config{
			InsecureSkipVerify: true, // 允许自签名证书测试
		},
		MaxIdleConns:        1000,
		MaxIdleConnsPerHost: 200,
		IdleConnTimeout:     90 * time.Second,
		DisableCompression: false,
	}

	return &HTTPClient{
		client: &http.Client{
			Transport: transport,
			CheckRedirect: func(req *http.Request, via []*http.Request) error {
				if len(via) >= 10 {
					return fmt.Errorf("stopped after 10 redirects")
				}
				return nil
			},
		},
	}
}

// Send 发送请求并精准记录各阶段耗时指标
func (c *HTTPClient) Send(ctx context.Context, reqData models.RequestData) (*models.HTTPResponseData, error) {
	// 1. 构建最终目标 URL 与 Query 参数
	targetURL := reqData.URL
	if len(reqData.Params) > 0 {
		parsedURL, err := url.Parse(targetURL)
		if err == nil {
			q := parsedURL.Query()
			for _, p := range reqData.Params {
				if p.Enabled && strings.TrimSpace(p.Key) != "" {
					q.Add(p.Key, p.Value)
				}
			}
			parsedURL.RawQuery = q.Encode()
			targetURL = parsedURL.String()
		}
	}

	// 2. 构建 Request Body
	var bodyReader io.Reader
	contentTypeHeader := ""

	switch strings.ToLower(reqData.BodyType) {
	case "json":
		bodyReader = bytes.NewBufferString(reqData.BodyContent)
		contentTypeHeader = "application/json; charset=utf-8"
	case "urlencoded":
		bodyReader = bytes.NewBufferString(reqData.BodyContent)
		contentTypeHeader = "application/x-www-form-urlencoded"
	case "form":
		// multipart/form-data
		var b bytes.Buffer
		w := multipart.NewWriter(&b)
		lines := strings.Split(reqData.BodyContent, "\n")
		for _, line := range lines {
			if strings.Contains(line, "=") {
				parts := strings.SplitN(line, "=", 2)
				_ = w.WriteField(strings.TrimSpace(parts[0]), strings.TrimSpace(parts[1]))
			}
		}
		_ = w.Close()
		bodyReader = &b
		contentTypeHeader = w.FormDataContentType()
	case "binary":
		if reqData.BodyContent != "" {
			file, err := os.Open(reqData.BodyContent)
			if err == nil {
				defer file.Close()
				data, _ := io.ReadAll(file)
				bodyReader = bytes.NewReader(data)
			}
		}
	case "raw":
		bodyReader = bytes.NewBufferString(reqData.BodyContent)
	default:
		bodyReader = nil
	}

	// 3. 超时上下文
	reqCtx := ctx
	if reqData.Timeout > 0 {
		var cancel context.CancelFunc
		reqCtx, cancel = context.WithTimeout(ctx, time.Duration(reqData.Timeout)*time.Millisecond)
		defer cancel()
	}

	// 4. 网络阶段耗时打点 (HTTP Trace)
	var (
		t0, tDNSStart, tTCPStart, tTLSStart time.Time
		dnsDone, tcpDone, tlsDone           time.Time
		reqWritten, firstByte               time.Time
		totalDone                           time.Time
	)

	trace := &httptrace.ClientTrace{
		DNSStart: func(info httptrace.DNSStartInfo) {
			tDNSStart = time.Now()
		},
		DNSDone: func(info httptrace.DNSDoneInfo) {
			dnsDone = time.Now()
		},
		ConnectStart: func(network, addr string) {
			tTCPStart = time.Now()
		},
		ConnectDone: func(network, addr string, err error) {
			tcpDone = time.Now()
		},
		TLSHandshakeStart: func() {
			tTLSStart = time.Now()
		},
		TLSHandshakeDone: func(state tls.ConnectionState, err error) {
			tlsDone = time.Now()
		},
		WroteHeaders: func() {
			reqWritten = time.Now()
		},
		GotFirstResponseByte: func() {
			firstByte = time.Now()
		},
	}

	reqCtx = httptrace.WithClientTrace(reqCtx, trace)

	method := strings.ToUpper(reqData.Method)
	if method == "" {
		method = "GET"
	}

	httpReq, err := http.NewRequestWithContext(reqCtx, method, targetURL, bodyReader)
	if err != nil {
		return nil, fmt.Errorf("创建请求失败: %w", err)
	}

	// 5. 合并全局请求头与单请求请求头（单请求配置同名 key 优先覆盖，大小写不敏感）
	mergedHeaders := make(map[string]string)
	lowerToActual := make(map[string]string)

	// 先载入全局请求头
	cfg := config.GetConfigManager().GetSettings()
	for _, gh := range cfg.GlobalHeaders {
		if gh.Enabled && strings.TrimSpace(gh.Key) != "" {
			k := strings.TrimSpace(gh.Key)
			kLower := strings.ToLower(k)
			mergedHeaders[k] = gh.Value
			lowerToActual[kLower] = k
		}
	}

	// 单请求请求头覆盖全局请求头
	for _, h := range reqData.Headers {
		if h.Enabled && strings.TrimSpace(h.Key) != "" {
			k := strings.TrimSpace(h.Key)
			kLower := strings.ToLower(k)
			if oldActual, exists := lowerToActual[kLower]; exists && oldActual != k {
				delete(mergedHeaders, oldActual)
			}
			mergedHeaders[k] = h.Value
			lowerToActual[kLower] = k
		}
	}

	// 设置最终请求头
	for k, v := range mergedHeaders {
		httpReq.Header.Set(k, v)
	}

	if contentTypeHeader != "" && httpReq.Header.Get("Content-Type") == "" {
		httpReq.Header.Set("Content-Type", contentTypeHeader)
	}

	// 认证处理
	switch strings.ToLower(reqData.AuthType) {
	case "basic":
		username := reqData.AuthConfig["username"]
		password := reqData.AuthConfig["password"]
		httpReq.SetBasicAuth(username, password)
	case "bearer":
		token := reqData.AuthConfig["token"]
		if token != "" {
			httpReq.Header.Set("Authorization", "Bearer "+token)
		}
	case "apikey":
		key := reqData.AuthConfig["key"]
		val := reqData.AuthConfig["value"]
		addTo := reqData.AuthConfig["add_to"]
		if addTo == "query" {
			q := httpReq.URL.Query()
			q.Set(key, val)
			httpReq.URL.RawQuery = q.Encode()
		} else {
			httpReq.Header.Set(key, val)
		}
	}

	// Cookies 处理
	for _, c := range reqData.Cookies {
		if c.Enabled && c.Key != "" {
			httpReq.AddCookie(&http.Cookie{Name: c.Key, Value: c.Value})
		}
	}

	// 6. 执行请求并计时
	t0 = time.Now()
	resp, err := c.client.Do(httpReq)
	if err != nil {
		return &models.HTTPResponseData{
			StatusCode: 0,
			Error:      err.Error(),
			ElapsedMS:  float64(time.Since(t0).Microseconds()) / 1000.0,
		}, err
	}
	defer resp.Body.Close()

	bodyBytes, _ := io.ReadAll(resp.Body)
	totalDone = time.Now()

	// 7. 计算全链路耗时细分 (Timing Breakdown)
	timing := models.TimingDetail{}

	if !tDNSStart.IsZero() && !dnsDone.IsZero() {
		timing.DNSLookupMS = float64(dnsDone.Sub(tDNSStart).Microseconds()) / 1000.0
	}
	if !tTCPStart.IsZero() && !tcpDone.IsZero() {
		timing.TCPConnectMS = float64(tcpDone.Sub(tTCPStart).Microseconds()) / 1000.0
	}
	if !tTLSStart.IsZero() && !tlsDone.IsZero() {
		timing.TLSHandshakeMS = float64(tlsDone.Sub(tTLSStart).Microseconds()) / 1000.0
	}
	if !reqWritten.IsZero() {
		sendStart := t0
		if !tlsDone.IsZero() {
			sendStart = tlsDone
		} else if !tcpDone.IsZero() {
			sendStart = tcpDone
		}
		timing.RequestSendMS = float64(reqWritten.Sub(sendStart).Microseconds()) / 1000.0
	}
	if !firstByte.IsZero() && !reqWritten.IsZero() {
		timing.TTFBMS = float64(firstByte.Sub(reqWritten).Microseconds()) / 1000.0
	}
	if !firstByte.IsZero() {
		timing.DownloadMS = float64(totalDone.Sub(firstByte).Microseconds()) / 1000.0
	}
	timing.TotalMS = float64(totalDone.Sub(t0).Microseconds()) / 1000.0

	// 提取响应头与 Cookies
	respHeaders := make(map[string]string)
	for k, v := range resp.Header {
		respHeaders[k] = strings.Join(v, ", ")
	}
	respCookies := make(map[string]string)
	for _, cookie := range resp.Cookies() {
		respCookies[cookie.Name] = cookie.Value
	}

	sizeBytes := int64(len(bodyBytes))
	sizeText := fmt.Sprintf("%d B", sizeBytes)
	if sizeBytes >= 1024*1024 {
		sizeText = fmt.Sprintf("%.2f MB", float64(sizeBytes)/(1024*1024))
	} else if sizeBytes >= 1024 {
		sizeText = fmt.Sprintf("%.2f KB", float64(sizeBytes)/1024)
	}

	reason := strings.TrimSpace(strings.TrimPrefix(resp.Status, fmt.Sprintf("%d", resp.StatusCode)))
	if reason == "" {
		reason = http.StatusText(resp.StatusCode)
	}

	return &models.HTTPResponseData{
		StatusCode: resp.StatusCode,
		Reason:     reason,
		Headers:    respHeaders,
		Cookies:    respCookies,
		Body:       string(bodyBytes),
		SizeBytes:  sizeBytes,
		SizeText:   sizeText,
		ElapsedMS:  timing.TotalMS,
		Timing:     timing,
	}, nil
}
