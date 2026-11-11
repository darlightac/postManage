package runner

import (
	"context"
	"fmt"
	"math"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"postmanage/internal/core/client"
	"postmanage/internal/core/models"
)

// LoadRunner 极简高并发压测引擎（依托 Go 原生协程引擎）
type LoadRunner struct {
	client *client.HTTPClient
}

// NewLoadRunner 创建压测运行器
func NewLoadRunner() *LoadRunner {
	return &LoadRunner{
		client: client.NewHTTPClient(),
	}
}

// RunStressTest 执行高并发压测
func (r *LoadRunner) RunStressTest(ctx context.Context, req models.RequestData, cfg models.StressConfig, progressCb func(currentTPS float64, completed int64)) (*models.StressResult, error) {
	if cfg.Concurrency <= 0 {
		cfg.Concurrency = 10
	}
	if cfg.Concurrency > 200 {
		cfg.Concurrency = 200 // 单机保护阈值
	}

	runCtx, cancel := context.WithCancel(ctx)
	defer cancel()

	if cfg.DurationSec > 0 {
		time.AfterFunc(time.Duration(cfg.DurationSec)*time.Second, cancel)
	}

	var (
		assignedRequests atomic.Int64
		totalRequests    atomic.Int64
		successCount     atomic.Int64
		failureCount     atomic.Int64
		totalBytes       atomic.Int64
		peakTPS          atomic.Int64 // 乘以 100 存整型
	)

	statusCodeMap := &sync.Map{}
	sampleMu := sync.Mutex{}
	latencies := make([]float64, 0, 10000)

	recordsMu := sync.Mutex{}
	records := make([]models.RequestRecord, 0, 5000)

	startTime := time.Now()
	var wg sync.WaitGroup

	// 确定压测使用的 HTTP 客户端 (支持代理调度)
	activeClient := r.client
	proxyURLToUse := strings.TrimSpace(cfg.ProxyURL)
	if proxyURLToUse == "" && strings.TrimSpace(req.ProxyURL) != "" {
		proxyURLToUse = strings.TrimSpace(req.ProxyURL)
	}
	if proxyURLToUse != "" {
		activeClient = client.NewHTTPClientWithProxy(proxyURLToUse)
	}

	// 秒级 TPS 滑动窗口统计
	tpsTicker := time.NewTicker(1 * time.Second)
	defer tpsTicker.Stop()

	go func() {
		var lastReqCount int64
		for {
			select {
			case <-runCtx.Done():
				return
			case <-tpsTicker.C:
				currentReq := totalRequests.Load()
				delta := currentReq - lastReqCount
				lastReqCount = currentReq
				currentTPS := float64(delta)

				// 更新峰值 TPS
				currentVal := int64(currentTPS * 100)
				for {
					oldPeak := peakTPS.Load()
					if currentVal <= oldPeak || peakTPS.CompareAndSwap(oldPeak, currentVal) {
						break
					}
				}

				if progressCb != nil {
					progressCb(currentTPS, currentReq)
				}
			}
		}
	}()

	// 启动并发 Worker 协程
	for i := 0; i < cfg.Concurrency; i++ {
		wg.Add(1)

		// 步进平滑升压 (Ramp-up)
		workerDelay := time.Duration(0)
		if cfg.RampUpSec > 0 {
			workerDelay = time.Duration(float64(cfg.RampUpSec)/float64(cfg.Concurrency)*float64(i)) * time.Second
		}

		go func(workerID int, delay time.Duration) {
			defer wg.Done()

			if delay > 0 {
				select {
				case <-runCtx.Done():
					return
				case <-time.After(delay):
				}
			}

			for {
				select {
				case <-runCtx.Done():
					return
				default:
				}

				// 按总请求数模式检查，原子领牌
				if cfg.TotalRequests > 0 {
					if assignedRequests.Add(1) > int64(cfg.TotalRequests) {
						return
					}
				}

				// 发送请求
				reqStart := time.Now()
				resp, err := activeClient.Send(runCtx, req)
				currentIdx := totalRequests.Add(1)
				offsetMS := float64(time.Since(startTime).Microseconds()) / 1000.0

				var code int
				var elapsed float64
				var size int64
				var errStr string

				if err == nil && resp != nil && resp.StatusCode >= 200 && resp.StatusCode < 400 {
					successCount.Add(1)
				} else {
					failureCount.Add(1)
				}

				if err != nil {
					errStr = err.Error()
				}

				if resp != nil {
					code = resp.StatusCode
					elapsed = resp.ElapsedMS
					size = resp.SizeBytes
					totalBytes.Add(resp.SizeBytes)

					// 统计状态码
					actualVal, _ := statusCodeMap.LoadOrStore(code, new(atomic.Int64))
					actualVal.(*atomic.Int64).Add(1)

					// 采样延迟 (最多保留 20,000 个采样用于精确分位数计算)
					sampleMu.Lock()
					if len(latencies) < 20000 {
						latencies = append(latencies, resp.ElapsedMS)
					}
					sampleMu.Unlock()
				} else if elapsed == 0 {
					elapsed = float64(time.Since(reqStart).Microseconds()) / 1000.0
				}

				// 收集单次请求明细（最多保留 5000 条供前端列表与可视化图表展示，包含请求体与响应体）
				recordsMu.Lock()
				if len(records) < 5000 {
					reqHeaders := make(map[string]string)
					for _, h := range req.Headers {
						if h.Enabled && strings.TrimSpace(h.Key) != "" {
							reqHeaders[h.Key] = h.Value
						}
					}
					var respHeaders map[string]string
					var respBody string
					if resp != nil {
						respHeaders = resp.Headers
						respBody = resp.Body
						if len(respBody) > 65536 {
							respBody = respBody[:65536] + "... [截断显示]"
						}
					}
					records = append(records, models.RequestRecord{
						Index:           currentIdx,
						OffsetMS:        offsetMS,
						Method:          req.Method,
						URL:             req.URL,
						StatusCode:      code,
						ElapsedMS:       elapsed,
						SizeBytes:       size,
						Error:           errStr,
						RequestHeaders:  reqHeaders,
						RequestBody:     req.BodyContent,
						ResponseHeaders: respHeaders,
						ResponseBody:    respBody,
					})
				}
				recordsMu.Unlock()

				if cfg.DelayMS > 0 {
					time.Sleep(time.Duration(cfg.DelayMS) * time.Millisecond)
				}
			}
		}(i, workerDelay)
	}

	wg.Wait()
	elapsedSec := time.Since(startTime).Seconds()
	if elapsedSec <= 0.001 {
		elapsedSec = 0.001
	}

	total := totalRequests.Load()
	success := successCount.Load()
	failed := failureCount.Load()

	successRate := 0.0
	if total > 0 {
		successRate = (float64(success) / float64(total)) * 100.0
	}

	// 整理状态码分布
	statusDist := make(map[int]int64)
	statusCodeMap.Range(func(k, v any) bool {
		statusDist[k.(int)] = v.(*atomic.Int64).Load()
		return true
	})

	// 计算延迟分位数与耗时区间
	sampleMu.Lock()
	sort.Float64s(latencies)
	sampleCount := len(latencies)

	var avgLatency, minLatency, maxLatency, p50, p90, p99 float64
	latencyBins := map[string]int64{
		"< 50ms":    0,
		"50-200ms":  0,
		"200-500ms": 0,
		"> 500ms":   0,
	}

	if sampleCount > 0 {
		minLatency = latencies[0]
		maxLatency = latencies[sampleCount-1]
		var sum float64
		for _, l := range latencies {
			sum += l
			if l < 50 {
				latencyBins["< 50ms"]++
			} else if l <= 200 {
				latencyBins["50-200ms"]++
			} else if l <= 500 {
				latencyBins["200-500ms"]++
			} else {
				latencyBins["> 500ms"]++
			}
		}
		avgLatency = sum / float64(sampleCount)

		p50Index := int(math.Min(float64(sampleCount-1), float64(sampleCount)*0.50))
		p90Index := int(math.Min(float64(sampleCount-1), float64(sampleCount)*0.90))
		p99Index := int(math.Min(float64(sampleCount-1), float64(sampleCount)*0.99))

		p50 = latencies[p50Index]
		p90 = latencies[p90Index]
		p99 = latencies[p99Index]
	}
	sampleMu.Unlock()

	avgTPS := float64(total) / elapsedSec
	peak := float64(peakTPS.Load()) / 100.0
	if peak < avgTPS {
		peak = avgTPS
	}

	bandwidthKBps := (float64(totalBytes.Load()) / 1024.0) / elapsedSec

	// 智能诊断提示
	tips := make([]string, 0)
	if successRate >= 99.5 && p90 < 100 {
		tips = append(tips, "✓ 接口性能优秀：成功率 > 99.5%，P90 响应时间低于 100ms。")
	}
	if p99 > 500 {
		tips = append(tips, "⚠ 存在较明显长尾延迟：P99 超过 500ms，部分用户可能感受到卡顿，建议排查数据库慢查询或锁争用。")
	}
	if rateLimited, ok := statusDist[429]; ok && rateLimited > 0 {
		tips = append(tips, "⚠ 触发服务端限流：出现 HTTP 429 Too Many Requests，请检查网关或应用层限流规则。")
	}
	if serverErr, ok := statusDist[500]; ok && serverErr > 0 {
		tips = append(tips, "⚠ 服务端内部异常：出现 HTTP 500 错误，表明高并发下后端可能存在未捕获异常或连接池枯竭。")
	}
	if proxyURLToUse != "" {
		if strings.EqualFold(proxyURLToUse, "direct") || strings.EqualFold(proxyURLToUse, "none") {
			tips = append(tips, "🌐 本次并发压测采用网卡直连模式（已显式绕过任何代理）")
		} else {
			tips = append(tips, fmt.Sprintf("🌐 本次并发压测流量已通过代理转发: %s", proxyURLToUse))
		}
	}
	if len(records) > 1 {
		sort.Slice(records, func(i, j int) bool {
			return records[i].Index < records[j].Index
		})
	}

	return &models.StressResult{
		TotalRequests:  total,
		SuccessCount:   success,
		FailureCount:   failed,
		SuccessRate:    successRate,
		ElapsedSec:     elapsedSec,
		AvgTPS:         avgTPS,
		PeakTPS:        peak,
		QPS:            avgTPS,
		ThroughputRPS:  avgTPS,
		AvgLatencyMS:   avgLatency,
		MinLatencyMS:   minLatency,
		MaxLatencyMS:   maxLatency,
		P50MS:          p50,
		P90MS:          p90,
		P99MS:          p99,
		TotalBytes:     totalBytes.Load(),
		BandwidthKBps:  bandwidthKBps,
		StatusCodeDist: statusDist,
		LatencyBins:    latencyBins,
		DiagnosisTips:  tips,
		ProxyURL:       proxyURLToUse,
		Records:        records,
	}, nil
}
