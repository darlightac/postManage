package sniffer

import (
	"context"
	"crypto/tls"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"postmanage/internal/core/models"
)

// PageSniffer 页面级接口智能嗅探与健康巡检引擎
type PageSniffer struct {
	httpClient *http.Client
}

// NewPageSniffer 创建嗅探器
func NewPageSniffer() *PageSniffer {
	return &PageSniffer{
		httpClient: &http.Client{
			Transport: &http.Transport{
				TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
			},
			Timeout: 10 * time.Second,
		},
	}
}

func applyHeadersAndCookies(req *http.Request, headers map[string]string, cookies map[string]string) {
	if req.Header.Get("User-Agent") == "" {
		req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PostManage/2.0")
	}
	for k, v := range headers {
		if strings.TrimSpace(k) != "" {
			req.Header.Set(k, v)
		}
	}
	if len(cookies) > 0 {
		var cookiePairs []string
		for k, v := range cookies {
			if strings.TrimSpace(k) != "" {
				cookiePairs = append(cookiePairs, fmt.Sprintf("%s=%s", k, v))
			}
		}
		if len(cookiePairs) > 0 {
			req.Header.Set("Cookie", strings.Join(cookiePairs, "; "))
		}
	}
}

// 常见 API 路由匹配正则表达式（支持深入识别 GET/POST/PUT/DELETE/PATCH 方法）
var (
	scriptSrcRegex = regexp.MustCompile(`(?i)<script[^>]+src=["']([^"']+)["']`)

	// 1. axios.get(url), axios.post(url), axios.put(url), axios.delete(url), axios.patch(url)
	axiosMethodRegex = regexp.MustCompile(`(?i)axios\.(get|post|put|delete|patch)\s*\(\s*["']([^"']+)["']`)

	// 2. axios({ method: 'post', url: '...' }) 或 axios({ url: '...', method: 'post' })
	axiosConfigRegex1 = regexp.MustCompile(`(?i)axios\s*\(\s*\{[^}]*method\s*:\s*["'](get|post|put|delete|patch)["'][^}]*url\s*:\s*["']([^"']+)["']`)
	axiosConfigRegex2 = regexp.MustCompile(`(?i)axios\s*\(\s*\{[^}]*url\s*:\s*["']([^"']+)["'][^}]*method\s*:\s*["'](get|post|put|delete|patch)["']`)

	// 3. 通用 axios(url)
	axiosDefaultRegex = regexp.MustCompile(`(?i)axios(?:\.(?:get|post|put|delete|patch))?\s*\(\s*["']([^"']+)["']`)

	// 4. fetch(url, { method: 'POST' })
	fetchMethodRegex = regexp.MustCompile(`(?i)fetch\s*\(\s*["']([^"']+)["']\s*,\s*\{[^}]*method\s*:\s*["'](get|post|put|delete|patch)["']`)

	// 5. fetch(url)
	fetchDefaultRegex = regexp.MustCompile(`(?i)fetch\s*\(\s*["']([^"']+)["']`)

	// 6. $.get(url) / $.post(url)
	jqueryShortRegex = regexp.MustCompile(`(?i)\$\.(get|post)\s*\(\s*["']([^"']+)["']`)

	// 7. $.ajax({ type/method: 'POST', url: '...' }) 或 $.ajax({ url: '...', type/method: 'POST' })
	jqueryAjaxRegex1       = regexp.MustCompile(`(?i)\$\.ajax\s*\(\s*\{[^}]*(?:type|method)\s*:\s*["'](get|post|put|delete|patch)["'][^}]*url\s*:\s*["']([^"']+)["']`)
	jqueryAjaxRegex2       = regexp.MustCompile(`(?i)\$\.ajax\s*\(\s*\{[^}]*url\s*:\s*["']([^"']+)["'][^}]*(?:type|method)\s*:\s*["'](get|post|put|delete|patch)["']`)
	jqueryAjaxDefaultRegex = regexp.MustCompile(`(?i)\$\.(?:ajax|get|post)\s*\(\s*(?:["']([^"']+)["']|\{[^}]*url:\s*["']([^"']+)["'])`)

	// 8. RESTful 路径匹配
	restPathRegex = regexp.MustCompile(`["'](/(?:api|v[0-9]+|system|auth|user|service)[a-zA-Z0-9_\-\/\.\?\=\&]*)["']`)
)

// ScanPageURL 兼容直接传入目标 URL 字符串的嗅探接口
func (s *PageSniffer) ScanPageURL(ctx context.Context, targetURL string) (*models.PageScanResult, error) {
	return s.ScanPage(ctx, models.PageScanConfig{TargetURL: targetURL})
}

// ScanPage 抓取指定页面，自动提取其调用的所有后端 API（识别 GET/POST 等方法），并支持携带全局请求头与 Cookie 并发探测
func (s *PageSniffer) ScanPage(ctx context.Context, cfg models.PageScanConfig) (*models.PageScanResult, error) {
	t0 := time.Now()

	parsedBase, err := url.Parse(cfg.TargetURL)
	if err != nil {
		return nil, err
	}

	scanClient := s.httpClient
	if cfg.ProxyURL != "" {
		if pURL, err := url.Parse(cfg.ProxyURL); err == nil {
			scanClient = &http.Client{
				Transport: &http.Transport{
					TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
					Proxy:           http.ProxyURL(pURL),
				},
				Timeout: 10 * time.Second,
			}
		}
	}

	// 1. 获取目标主页面 HTML（携带全局请求头与匹配的 Cookie）
	req, err := http.NewRequestWithContext(ctx, "GET", cfg.TargetURL, nil)
	if err != nil {
		return nil, err
	}
	applyHeadersAndCookies(req, cfg.Headers, cfg.Cookies)

	resp, err := scanClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	htmlBytes, _ := io.ReadAll(resp.Body)
	htmlContent := string(htmlBytes)

	// 2. 收集页面文本与关联的外链脚本内容
	contentsToScan := []string{htmlContent}

	scriptMatches := scriptSrcRegex.FindAllStringSubmatch(htmlContent, -1)
	var scriptWg sync.WaitGroup
	scriptMu := sync.Mutex{}

	// 并发获取前 10 个外链 JS 脚本（加速分析）
	limit := len(scriptMatches)
	if limit > 10 {
		limit = 10
	}

	for i := 0; i < limit; i++ {
		jsSrc := scriptMatches[i][1]
		fullJSURL := s.resolveURL(parsedBase, jsSrc)
		if strings.HasSuffix(fullJSURL, ".js") || strings.Contains(fullJSURL, ".js?") {
			scriptWg.Add(1)
			go func(urlStr string) {
				defer scriptWg.Done()
				jsReq, _ := http.NewRequestWithContext(ctx, "GET", urlStr, nil)
				applyHeadersAndCookies(jsReq, cfg.Headers, cfg.Cookies)
				jsResp, err := scanClient.Do(jsReq)
				if err == nil {
					defer jsResp.Body.Close()
					jsData, _ := io.ReadAll(io.LimitReader(jsResp.Body, 512*1024)) // 限制 512KB
					scriptMu.Lock()
					contentsToScan = append(contentsToScan, string(jsData))
					scriptMu.Unlock()
				}
			}(fullJSURL)
		}
	}
	scriptWg.Wait()

	// 3. 提取所有疑似 API 路径并去重，同时精准捕获 HTTP Method
	endpointMap := make(map[string]models.PageEndpoint)

	for _, code := range contentsToScan {
		// axios.get / axios.post / axios.put / axios.delete
		for _, m := range axiosMethodRegex.FindAllStringSubmatch(code, -1) {
			s.addEndpointCandidate(parsedBase, m[2], strings.ToUpper(m[1]), m[0], endpointMap)
		}
		// axios({ method: 'post', url: '...' })
		for _, m := range axiosConfigRegex1.FindAllStringSubmatch(code, -1) {
			s.addEndpointCandidate(parsedBase, m[2], strings.ToUpper(m[1]), m[0], endpointMap)
		}
		for _, m := range axiosConfigRegex2.FindAllStringSubmatch(code, -1) {
			s.addEndpointCandidate(parsedBase, m[1], strings.ToUpper(m[2]), m[0], endpointMap)
		}
		// fetch(url, { method: 'POST' })
		for _, m := range fetchMethodRegex.FindAllStringSubmatch(code, -1) {
			s.addEndpointCandidate(parsedBase, m[1], strings.ToUpper(m[2]), m[0], endpointMap)
		}
		// fetch(url)
		for _, m := range fetchDefaultRegex.FindAllStringSubmatch(code, -1) {
			s.addEndpointCandidate(parsedBase, m[1], "GET", m[0], endpointMap)
		}
		// $.get / $.post
		for _, m := range jqueryShortRegex.FindAllStringSubmatch(code, -1) {
			s.addEndpointCandidate(parsedBase, m[2], strings.ToUpper(m[1]), m[0], endpointMap)
		}
		// $.ajax({ type: 'POST', url: '...' })
		for _, m := range jqueryAjaxRegex1.FindAllStringSubmatch(code, -1) {
			s.addEndpointCandidate(parsedBase, m[2], strings.ToUpper(m[1]), m[0], endpointMap)
		}
		for _, m := range jqueryAjaxRegex2.FindAllStringSubmatch(code, -1) {
			s.addEndpointCandidate(parsedBase, m[1], strings.ToUpper(m[2]), m[0], endpointMap)
		}
		// axios 通用兜底
		for _, m := range axiosDefaultRegex.FindAllStringSubmatch(code, -1) {
			s.addEndpointCandidate(parsedBase, m[1], "GET", m[0], endpointMap)
		}
		// jquery 通用兜底
		for _, m := range jqueryAjaxDefaultRegex.FindAllStringSubmatch(code, -1) {
			path := m[1]
			if path == "" {
				path = m[2]
			}
			s.addEndpointCandidate(parsedBase, path, "GET", m[0], endpointMap)
		}
		// RESTful 路径匹配
		for _, m := range restPathRegex.FindAllStringSubmatch(code, -1) {
			s.addEndpointCandidate(parsedBase, m[1], "GET", m[0], endpointMap)
		}
	}

	// 4. 并发探测接口连通性健康状态（使用对应的 Method 并注入全局请求头与 Cookie）
	endpoints := make([]models.PageEndpoint, 0, len(endpointMap))
	for _, ep := range endpointMap {
		endpoints = append(endpoints, ep)
	}

	var probeWg sync.WaitGroup
	var probeMu sync.Mutex
	healthyCount := 0
	warningCount := 0
	criticalCount := 0

	// 限制并发探测数为 10
	semaphore := make(chan struct{}, 10)

	for i := range endpoints {
		probeWg.Add(1)
		go func(idx int) {
			defer probeWg.Done()
			semaphore <- struct{}{}
			defer func() { <-semaphore }()

			ep := &endpoints[idx]
			pingStart := time.Now()

			pingReq, _ := http.NewRequestWithContext(ctx, ep.Method, ep.URL, nil)
			applyHeadersAndCookies(pingReq, cfg.Headers, cfg.Cookies)

			pingResp, err := scanClient.Do(pingReq)
			latency := float64(time.Since(pingStart).Microseconds()) / 1000.0
			ep.LatencyMS = latency

			if err != nil {
				ep.StatusCode = 0
				ep.StatusType = "critical"
			} else {
				ep.StatusCode = pingResp.StatusCode
				pingResp.Body.Close()

				if ep.StatusCode >= 200 && ep.StatusCode < 300 {
					if latency > 1000 {
						ep.StatusType = "warning" // 慢接口告警
					} else {
						ep.StatusType = "healthy"
					}
				} else if ep.StatusCode == 401 || ep.StatusCode == 403 {
					ep.StatusType = "warning" // 需要鉴权
				} else {
					ep.StatusType = "critical" // 404 / 500 等
				}
			}

			probeMu.Lock()
			switch ep.StatusType {
			case "healthy":
				healthyCount++
			case "warning":
				warningCount++
			case "critical":
				criticalCount++
			}
			probeMu.Unlock()
		}(i)
	}

	probeWg.Wait()
	elapsed := float64(time.Since(t0).Microseconds()) / 1000.0

	return &models.PageScanResult{
		TargetURL:      cfg.TargetURL,
		TotalEndpoints: len(endpoints),
		HealthyCount:   healthyCount,
		WarningCount:   warningCount,
		CriticalCount:  criticalCount,
		ElapsedMS:      elapsed,
		Endpoints:      endpoints,
	}, nil
}

func (s *PageSniffer) resolveURL(base *url.URL, ref string) string {
	refURL, err := url.Parse(ref)
	if err != nil {
		return ref
	}
	return base.ResolveReference(refURL).String()
}

func (s *PageSniffer) addEndpointCandidate(base *url.URL, rawPath, method, snippet string, endpointMap map[string]models.PageEndpoint) {
	cleanPath := strings.TrimSpace(rawPath)
	if cleanPath == "" || strings.HasPrefix(cleanPath, "javascript:") || strings.HasPrefix(cleanPath, "#") {
		return
	}

	// 排除静态资源文件后缀
	lowerPath := strings.ToLower(cleanPath)
	staticExtensions := []string{".png", ".jpg", ".jpeg", ".gif", ".svg", ".css", ".woff", ".woff2", ".ttf", ".ico", ".html"}
	for _, ext := range staticExtensions {
		if strings.HasSuffix(lowerPath, ext) || strings.Contains(lowerPath, ext+"?") {
			return
		}
	}

	fullURL := s.resolveURL(base, cleanPath)
	upperMethod := strings.ToUpper(strings.TrimSpace(method))
	if upperMethod == "" {
		upperMethod = "GET"
	}

	// 启发式识别：如果未明确给出方法或为 GET，根据 RESTful 路径动词特征进行推断
	if upperMethod == "GET" {
		if strings.Contains(lowerPath, "/create") || strings.Contains(lowerPath, "/add") ||
			strings.Contains(lowerPath, "/save") || strings.Contains(lowerPath, "/login") ||
			strings.Contains(lowerPath, "/register") || strings.Contains(lowerPath, "/submit") ||
			strings.Contains(lowerPath, "/upload") {
			upperMethod = "POST"
		} else if strings.Contains(lowerPath, "/delete") || strings.Contains(lowerPath, "/remove") {
			upperMethod = "DELETE"
		} else if strings.Contains(lowerPath, "/update") || strings.Contains(lowerPath, "/modify") {
			upperMethod = "PUT"
		}
	}

	if existing, exists := endpointMap[fullURL]; !exists {
		endpointMap[fullURL] = models.PageEndpoint{
			Method:     upperMethod,
			URL:        fullURL,
			Path:       cleanPath,
			StatusCode: 0,
			StatusType: "healthy",
			Snippet:    snippet,
		}
	} else if existing.Method == "GET" && upperMethod != "GET" {
		// 升级为更明确的非 GET 方法
		existing.Method = upperMethod
		endpointMap[fullURL] = existing
	}
}

func makeEndpointRequest(ctx context.Context, ep models.PageEndpoint, globalHeaders map[string]string, cookies map[string]string) (*http.Request, error) {
	var bodyReader io.Reader
	if (ep.Method == "POST" || ep.Method == "PUT" || ep.Method == "PATCH") && len(ep.Body) > 0 {
		bodyReader = strings.NewReader(ep.Body)
	}
	req, err := http.NewRequestWithContext(ctx, ep.Method, ep.URL, bodyReader)
	if err != nil {
		return nil, err
	}

	// 1. 先应用全局头与域名级 Cookie 基础
	applyHeadersAndCookies(req, globalHeaders, cookies)

	// 2. 深度合并/保留单接口嗅探捕获到的所有真实参数、请求头、Session 及 Cookie
	for k, v := range ep.Headers {
		if strings.TrimSpace(k) != "" {
			lowerK := strings.ToLower(k)
			// 跳过由 Go 标准库自动精确计算的底层头
			if lowerK == "host" || lowerK == "content-length" {
				continue
			}
			req.Header.Set(k, v)
		}
	}

	// 3. 若捕获头中已包含特定 Cookie，且全局/会话 Cookie 中有补充项，则合并补充保证会话完整
	epCookie := ""
	for k, v := range ep.Headers {
		if strings.ToLower(k) == "cookie" {
			epCookie = v
			break
		}
	}
	if epCookie != "" && len(cookies) > 0 {
		mergedParts := []string{epCookie}
		existingKeys := make(map[string]bool)
		for _, part := range strings.Split(epCookie, ";") {
			kv := strings.SplitN(strings.TrimSpace(part), "=", 2)
			if len(kv) > 0 && kv[0] != "" {
				existingKeys[strings.ToLower(kv[0])] = true
			}
		}
		for ck, cv := range cookies {
			if strings.TrimSpace(ck) != "" && !existingKeys[strings.ToLower(ck)] {
				mergedParts = append(mergedParts, fmt.Sprintf("%s=%s", ck, cv))
			}
		}
		req.Header.Set("Cookie", strings.Join(mergedParts, "; "))
	}

	// 4. 自动保留与补齐 Content-Type
	if bodyReader != nil && req.Header.Get("Content-Type") == "" {
		trimmed := strings.TrimSpace(ep.Body)
		if strings.HasPrefix(trimmed, "{") || strings.HasPrefix(trimmed, "[") {
			req.Header.Set("Content-Type", "application/json; charset=utf-8")
		} else if strings.Contains(trimmed, "=") {
			req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
		}
	}
	return req, nil
}

// StressPage 对网页及其嗅探出的所有接口发起全页面事务并发性能压测
func (s *PageSniffer) StressPage(ctx context.Context, cfg models.PageStressConfig) (*models.PageStressResult, error) {
	if cfg.Concurrency <= 0 {
		cfg.Concurrency = 5
	}
	if cfg.Concurrency > 50 {
		cfg.Concurrency = 50
	}
	if cfg.TotalRequests <= 0 {
		cfg.TotalRequests = 20
	}
	if cfg.TotalRequests > 500 {
		cfg.TotalRequests = 500
	}
	if cfg.TimeoutMS <= 0 {
		cfg.TimeoutMS = 5000
	}

	// 1. 如果传入的接口列表为空，先自动嗅探目标页面（携带认证请求头与 Cookie）
	endpoints := cfg.Endpoints
	if len(endpoints) == 0 {
		scanRes, err := s.ScanPage(ctx, models.PageScanConfig{
			TargetURL: cfg.TargetURL,
			Headers:   cfg.Headers,
			Cookies:   cfg.Cookies,
		})
		if err != nil {
			return nil, err
		}
		endpoints = scanRes.Endpoints
		// 将页面自身也作为 root 接口加入压测目标
		hasRoot := false
		for _, ep := range endpoints {
			if ep.URL == cfg.TargetURL {
				hasRoot = true
				break
			}
		}
		if !hasRoot && cfg.TargetURL != "" {
			rootEp := models.PageEndpoint{
				Method:     "GET",
				URL:        cfg.TargetURL,
				Path:       "/",
				StatusCode: 200,
				StatusType: "healthy",
				Snippet:    "页面主入口文档",
			}
			endpoints = append([]models.PageEndpoint{rootEp}, endpoints...)
		}
	}

	if len(endpoints) == 0 && cfg.TargetURL != "" {
		endpoints = append(endpoints, models.PageEndpoint{
			Method:     "GET",
			URL:        cfg.TargetURL,
			Path:       "/",
			StatusCode: 200,
			StatusType: "healthy",
			Snippet:    "页面主文档",
		})
	}

	totalEndpointsCount := len(endpoints)
	if totalEndpointsCount == 0 {
		return nil, fmt.Errorf("无有效压测接口")
	}

	startTime := time.Now()

	// 共享高并发 HTTP 连接池 (支持配置代理)
	tr := &http.Transport{
		TLSClientConfig:     &tls.Config{InsecureSkipVerify: true},
		MaxIdleConns:        200,
		MaxIdleConnsPerHost: 50,
		IdleConnTimeout:     30 * time.Second,
	}
	if cfg.ProxyURL != "" {
		if pURL, err := url.Parse(cfg.ProxyURL); err == nil {
			tr.Proxy = http.ProxyURL(pURL)
		}
	} else {
		tr.Proxy = http.ProxyFromEnvironment
	}
	client := &http.Client{
		Transport: tr,
		Timeout:   time.Duration(cfg.TimeoutMS) * time.Millisecond,
	}

	type epSample struct {
		latencyMS   float64
		statusCode  int
		sizeBytes   int64
		err         string
		reqHeaders  map[string]string
		reqBody     string
		respHeaders map[string]string
		respBody    string
	}

	type epStatCollector struct {
		endpoint models.PageEndpoint
		mu       sync.Mutex
		samples  []epSample
	}

	epCollectors := make([]*epStatCollector, totalEndpointsCount)
	for i := range endpoints {
		epCollectors[i] = &epStatCollector{
			endpoint: endpoints[i],
			samples:  make([]epSample, 0, cfg.TotalRequests),
		}
	}

	var (
		assignedIterations atomic.Int64
		totalPageIterCount atomic.Int64
		successPageIter    atomic.Int64
		failedPageIter     atomic.Int64

		pageRecordsMu sync.Mutex
		pageRecords   = make([]models.PageIterationRecord, 0, cfg.TotalRequests)

		pageDurationsMu sync.Mutex
		pageDurations   = make([]float64, 0, cfg.TotalRequests)

		allRecordsMu sync.Mutex
		allRecords   = make([]models.RequestRecord, 0, 5000)
		recordIdxGen atomic.Int64
	)

	var workerWg sync.WaitGroup
	for w := 0; w < cfg.Concurrency; w++ {
		workerWg.Add(1)
		go func() {
			defer workerWg.Done()
			for {
				select {
				case <-ctx.Done():
					return
				default:
				}

				iterIdx := assignedIterations.Add(1)
				if iterIdx > int64(cfg.TotalRequests) {
					return
				}

				iterStart := time.Now()
				iterOffsetMS := float64(time.Since(startTime).Microseconds()) / 1000.0

				// 当次轮次内部结果
				type roundResult struct {
					epIdx       int
					latencyMS   float64
					statusCode  int
					sizeBytes   int64
					err         error
					reqHeaders  map[string]string
					reqBody     string
					respHeaders map[string]string
					respBody    string
				}
				roundResults := make([]roundResult, totalEndpointsCount)

				// 并发触发当次页面的所有接口
				var iterWg sync.WaitGroup
				for epIdx := 0; epIdx < totalEndpointsCount; epIdx++ {
					iterWg.Add(1)
					go func(idx int) {
						defer iterWg.Done()
						targetEp := endpoints[idx]
						reqStart := time.Now()

						httpReq, reqErr := makeEndpointRequest(ctx, targetEp, cfg.Headers, cfg.Cookies)
						if reqErr != nil {
							roundResults[idx] = roundResult{
								epIdx:       idx,
								latencyMS:   0,
								statusCode:  0,
								sizeBytes:   0,
								err:         reqErr,
								reqHeaders:  nil,
								reqBody:     targetEp.Body,
								respHeaders: nil,
								respBody:    "",
							}
							return
						}

						reqHeadersMap := make(map[string]string)
						for hk, hv := range httpReq.Header {
							if len(hv) > 0 {
								reqHeadersMap[hk] = hv[0]
							}
						}

						resp, err := client.Do(httpReq)
						elapsed := float64(time.Since(reqStart).Microseconds()) / 1000.0

						var code int
						var size int64
						var respBodyStr string
						respHeadersMap := make(map[string]string)

						if err != nil {
							roundResults[idx] = roundResult{
								epIdx:       idx,
								latencyMS:   elapsed,
								statusCode:  0,
								sizeBytes:   0,
								err:         err,
								reqHeaders:  reqHeadersMap,
								reqBody:     targetEp.Body,
								respHeaders: respHeadersMap,
								respBody:    "",
							}
						} else {
							code = resp.StatusCode
							for rhk, rhv := range resp.Header {
								if len(rhv) > 0 {
									respHeadersMap[rhk] = rhv[0]
								}
							}
							bBytes, _ := io.ReadAll(io.LimitReader(resp.Body, 65536))
							respBodyStr = string(bBytes)
							size = int64(len(bBytes))
							if size == 0 && resp.ContentLength > 0 {
								size = resp.ContentLength
							}
							resp.Body.Close()
							roundResults[idx] = roundResult{
								epIdx:       idx,
								latencyMS:   elapsed,
								statusCode:  code,
								sizeBytes:   size,
								err:         nil,
								reqHeaders:  reqHeadersMap,
								reqBody:     targetEp.Body,
								respHeaders: respHeadersMap,
								respBody:    respBodyStr,
							}
						}
					}(epIdx)
				}

				// 等待当次页面的所有接口全部返回
				iterWg.Wait()

				totalPageIterCount.Add(1)

				// 计算页面加载时长 = 当次请求的最长时间 (即关键路径耗时 max(elapsed))
				var maxEndpointElapsed float64
				allSuccess := true
				failedCount := 0
				var firstErrMsg string

				for _, res := range roundResults {
					if res.latencyMS > maxEndpointElapsed {
						maxEndpointElapsed = res.latencyMS
					}

					errStr := ""
					if res.err != nil {
						errStr = res.err.Error()
					}
					col := epCollectors[res.epIdx]
					col.mu.Lock()
					col.samples = append(col.samples, epSample{
						latencyMS:   res.latencyMS,
						statusCode:  res.statusCode,
						sizeBytes:   res.sizeBytes,
						err:         errStr,
						reqHeaders:  res.reqHeaders,
						reqBody:     res.reqBody,
						respHeaders: res.respHeaders,
						respBody:    res.respBody,
					})
					col.mu.Unlock()

					recIndex := recordIdxGen.Add(1)
					allRecordsMu.Lock()
					if len(allRecords) < 5000 {
						allRecords = append(allRecords, models.RequestRecord{
							Index:           recIndex,
							OffsetMS:        iterOffsetMS,
							Method:          endpoints[res.epIdx].Method,
							URL:             endpoints[res.epIdx].URL,
							StatusCode:      res.statusCode,
							ElapsedMS:       res.latencyMS,
							SizeBytes:       res.sizeBytes,
							Error:           errStr,
							RequestHeaders:  res.reqHeaders,
							RequestBody:     res.reqBody,
							ResponseHeaders: res.respHeaders,
							ResponseBody:    res.respBody,
						})
					}
					allRecordsMu.Unlock()

					// 判定成功条件：只有响应状态码在 200~399 且无网络异常，才算该接口成功
					isEpSuccess := res.err == nil && res.statusCode >= 200 && res.statusCode < 400
					if !isEpSuccess {
						allSuccess = false
						failedCount++
						if firstErrMsg == "" {
							if res.err != nil {
								firstErrMsg = fmt.Sprintf("[%s %s] %s", endpoints[res.epIdx].Method, endpoints[res.epIdx].Path, res.err.Error())
							} else {
								firstErrMsg = fmt.Sprintf("[%s %s] HTTP %d", endpoints[res.epIdx].Method, endpoints[res.epIdx].Path, res.statusCode)
							}
						}
					}
				}

				if maxEndpointElapsed <= 0 {
					maxEndpointElapsed = float64(time.Since(iterStart).Microseconds()) / 1000.0
				}

				pageDurationsMu.Lock()
				pageDurations = append(pageDurations, maxEndpointElapsed)
				pageDurationsMu.Unlock()

				if allSuccess {
					successPageIter.Add(1)
				} else {
					failedPageIter.Add(1)
				}

				pageRecordsMu.Lock()
				if len(pageRecords) < 2000 {
					pageRecords = append(pageRecords, models.PageIterationRecord{
						Index:           iterIdx,
						OffsetMS:        iterOffsetMS,
						PageLoadMS:      maxEndpointElapsed,
						Success:         allSuccess,
						EndpointCount:   totalEndpointsCount,
						FailedEndpoints: failedCount,
						ErrorSummary:    firstErrMsg,
					})
				}
				pageRecordsMu.Unlock()

				// 只有当次页面压测全部接口响应完毕，此时才能继续触发下一次全页面压测
				if cfg.DelayMS > 0 {
					time.Sleep(time.Duration(cfg.DelayMS) * time.Millisecond)
				}
			}
		}()
	}

	workerWg.Wait()

	elapsedSec := time.Since(startTime).Seconds()
	if elapsedSec <= 0.001 {
		elapsedSec = 0.001
	}

	totalPage := totalPageIterCount.Load()
	successPage := successPageIter.Load()
	failedPage := failedPageIter.Load()
	pageSuccessRate := 0.0
	if totalPage > 0 {
		pageSuccessRate = (float64(successPage) / float64(totalPage)) * 100.0
	}
	pageRPS := float64(totalPage) / elapsedSec

	// 计算页面加载时长指标 (均值, min, max, p90, p95)
	sort.Float64s(pageDurations)
	var avgPageLoad, minPageLoad, maxPageLoad, p90PageLoad, p95PageLoad float64
	if len(pageDurations) > 0 {
		minPageLoad = pageDurations[0]
		maxPageLoad = pageDurations[len(pageDurations)-1]
		var sumPageLoad float64
		for _, d := range pageDurations {
			sumPageLoad += d
		}
		avgPageLoad = sumPageLoad / float64(len(pageDurations))
		p90PageLoad = percentile(pageDurations, 0.90)
		p95PageLoad = percentile(pageDurations, 0.95)
	}

	// 汇总各单接口的独立统计报告
	reports := make([]models.EndpointStressReport, totalEndpointsCount)
	rankings := make([]models.EndpointRanking, totalEndpointsCount)
	var totalAvgLatencySum float64

	var totalReqs, totalSuccess, totalError, totalTimeout int64
	var sumAllLatency float64

	for i, col := range epCollectors {
		ep := col.endpoint
		samples := col.samples
		count := int64(len(samples))

		var succCnt, errCnt, toCnt int64
		var latSum, minLat, maxLat float64
		codeDist := make(map[int]int64)
		latencies := make([]float64, 0, len(samples))
		bins := map[string]int64{
			"<50ms":     0,
			"50-200ms":  0,
			"200-500ms": 0,
			">500ms":    0,
		}

		for _, s := range samples {
			codeDist[s.statusCode]++
			latencies = append(latencies, s.latencyMS)
			latSum += s.latencyMS

			if s.err != "" {
				errCnt++
				lowerErr := strings.ToLower(s.err)
				if strings.Contains(lowerErr, "timeout") || strings.Contains(lowerErr, "deadline") {
					toCnt++
				}
			} else if s.statusCode >= 200 && s.statusCode < 400 {
				succCnt++
			} else {
				errCnt++
			}

			if s.latencyMS < 50 {
				bins["<50ms"]++
			} else if s.latencyMS <= 200 {
				bins["50-200ms"]++
			} else if s.latencyMS <= 500 {
				bins["200-500ms"]++
			} else {
				bins[">500ms"]++
			}
		}

		sort.Float64s(latencies)
		var p50, p90, p95, p99, avgLat float64
		if len(latencies) > 0 {
			minLat = latencies[0]
			maxLat = latencies[len(latencies)-1]
			avgLat = latSum / float64(len(latencies))
			p50 = percentile(latencies, 0.50)
			p90 = percentile(latencies, 0.90)
			p95 = percentile(latencies, 0.95)
			p99 = percentile(latencies, 0.99)
		}

		toRate := 0.0
		eRate := 0.0
		sRate := 0.0
		if count > 0 {
			toRate = (float64(toCnt) / float64(count)) * 100.0
			eRate = (float64(errCnt) / float64(count)) * 100.0
			sRate = (float64(succCnt) / float64(count)) * 100.0
		}
		qps := float64(count) / elapsedSec

		var tips []string
		if count == 0 {
			tips = append(tips, "未采集到有效请求")
		} else {
			if eRate == 0 && toRate == 0 && avgLat < 100 {
				tips = append(tips, "性能表现极佳：平均响应在 100ms 以内，成功率 100%。")
			} else if eRate == 0 && toRate == 0 && avgLat < 300 {
				tips = append(tips, "性能表现良好：无报错与超时，平均响应时间处于合理区间。")
			}
			if toRate > 5 {
				tips = append(tips, fmt.Sprintf("存在超时风险：超时率达到 %.1f%%，服务端线程池或下游依赖可能存在阻塞卡顿。", toRate))
			}
			if eRate > 5 {
				tips = append(tips, fmt.Sprintf("接口可用性告警：错误率达到 %.1f%%，请核查服务器业务逻辑、鉴权限制或异常日志。", eRate))
			}
			if p99 > 500 {
				tips = append(tips, fmt.Sprintf("长尾延迟明显：P99 耗时达到 %.1fms，建议排查慢 SQL、无索引全表扫描或冷启动开销。", p99))
			}
		}
		if len(tips) == 0 {
			tips = append(tips, "接口运行平稳，各项指标未见明显异常。")
		}

		epRecords := make([]models.RequestRecord, 0, len(samples))
		for sIdx, s := range samples {
			epRecords = append(epRecords, models.RequestRecord{
				Index:           int64(sIdx + 1),
				OffsetMS:        0,
				Method:          ep.Method,
				URL:             ep.URL,
				StatusCode:      s.statusCode,
				ElapsedMS:       s.latencyMS,
				SizeBytes:       s.sizeBytes,
				Error:           s.err,
				RequestHeaders:  s.reqHeaders,
				RequestBody:     s.reqBody,
				ResponseHeaders: s.respHeaders,
				ResponseBody:    s.respBody,
			})
		}

		reports[i] = models.EndpointStressReport{
			Method:         ep.Method,
			URL:            ep.URL,
			Path:           ep.Path,
			TotalRequests:  count,
			SuccessCount:   succCnt,
			ErrorCount:     errCnt,
			TimeoutCount:   toCnt,
			AvgLatencyMS:   avgLat,
			MinLatencyMS:   minLat,
			MaxLatencyMS:   maxLat,
			P50MS:          p50,
			P90MS:          p90,
			P95MS:          p95,
			P99MS:          p99,
			TimeoutRate:    toRate,
			ErrorRate:      eRate,
			SuccessRate:    sRate,
			QPS:            qps,
			StatusCodeDist: codeDist,
			LatencyBins:    bins,
			DiagnosisTips:  tips,
			Records:        epRecords,
		}

		rankings[i] = models.EndpointRanking{
			Method:       ep.Method,
			URL:          ep.URL,
			Path:         ep.Path,
			AvgLatencyMS: avgLat,
			MaxLatencyMS: maxLat,
			MinLatencyMS: minLat,
			SuccessRate:  sRate,
			ErrorCount:   errCnt,
			TotalCalls:   count,
		}
		totalAvgLatencySum += avgLat

		totalReqs += count
		totalSuccess += succCnt
		totalError += errCnt
		totalTimeout += toCnt
		sumAllLatency += latSum
	}

	// 页面接口平均耗时降序排行 (Slowest to Fastest)
	sort.Slice(rankings, func(i, j int) bool {
		return rankings[i].AvgLatencyMS > rankings[j].AvgLatencyMS
	})
	for i := range rankings {
		rankings[i].Rank = i + 1
		if totalAvgLatencySum > 0 {
			rankings[i].SharePercent = (rankings[i].AvgLatencyMS / totalAvgLatencySum) * 100.0
		}
	}

	// 页面接口错误与异常归因统计
	var errorStats []models.EndpointErrorStat
	for _, r := range reports {
		if r.ErrorCount > 0 || r.TimeoutCount > 0 {
			var lastErrs []string
			for _, sample := range epCollectors[0].samples {
				if sample.err != "" && len(lastErrs) < 3 {
					lastErrs = append(lastErrs, sample.err)
				}
			}
			errorStats = append(errorStats, models.EndpointErrorStat{
				Method:      r.Method,
				URL:         r.URL,
				ErrorCount:  r.ErrorCount,
				ErrorRate:   r.ErrorRate,
				StatusCodes: r.StatusCodeDist,
				LastErrors:  lastErrs,
			})
		}
	}

	// 全局平均耗时与 QPS
	overallAvgLatency := 0.0
	if totalReqs > 0 {
		overallAvgLatency = sumAllLatency / float64(totalReqs)
	}
	overallTPS := float64(totalReqs) / elapsedSec

	// 时序记录按序号排布
	sort.Slice(pageRecords, func(i, j int) bool {
		return pageRecords[i].Index < pageRecords[j].Index
	})
	sort.Slice(allRecords, func(i, j int) bool {
		return allRecords[i].Index < allRecords[j].Index
	})

	return &models.PageStressResult{
		TargetURL:                cfg.TargetURL,
		TotalEndpoints:           totalEndpointsCount,
		TotalRequests:            totalReqs,
		SuccessCount:             totalSuccess,
		ErrorCount:               totalError,
		TimeoutCount:             totalTimeout,
		AvgLatencyMS:             overallAvgLatency,
		ElapsedSec:               elapsedSec,
		OverallTPS:               overallTPS,
		QPS:                      overallTPS,
		ThroughputRPS:            overallTPS,
		TotalPageIterations:      totalPage,
		SuccessfulPageIterations: successPage,
		FailedPageIterations:     failedPage,
		PageSuccessRate:          pageSuccessRate,
		AvgPageLoadDurationMS:    avgPageLoad,
		MinPageLoadDurationMS:    minPageLoad,
		MaxPageLoadDurationMS:    maxPageLoad,
		P90PageLoadDurationMS:    p90PageLoad,
		P95PageLoadDurationMS:    p95PageLoad,
		PageRPS:                  pageRPS,
		PageTPS:                  pageRPS,
		EndpointRankings:         rankings,
		EndpointErrorStats:       errorStats,
		PageRecords:              pageRecords,
		Records:                  allRecords,
		EndpointReports:          reports,
	}, nil
}

func percentile(sorted []float64, p float64) float64 {
	if len(sorted) == 0 {
		return 0
	}
	idx := int(float64(len(sorted)-1) * p)
	if idx >= len(sorted) {
		idx = len(sorted) - 1
	}
	return sorted[idx]
}

