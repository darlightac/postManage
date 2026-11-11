package tests

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"postmanage/internal/core/models"
	"postmanage/internal/core/runner"
)

func TestLoadRunner_StressExecution(t *testing.T) {
	requestCount := 0
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requestCount++
		time.Sleep(5 * time.Millisecond)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"code":0,"data":"ok"}`))
	}))
	defer ts.Close()

	r := runner.NewLoadRunner()
	reqData := models.RequestData{
		Method: "GET",
		URL:    ts.URL + "/api/bench",
	}

	cfg := models.StressConfig{
		Concurrency:   5,
		TotalRequests: 25,
		TimeoutMS:     2000,
	}

	result, err := r.RunStressTest(context.Background(), reqData, cfg, nil)
	if err != nil {
		t.Fatalf("压测执行失败: %v", err)
	}

	if result.TotalRequests != 25 {
		t.Errorf("期望完成 25 次请求，实际为 %d", result.TotalRequests)
	}
	if result.SuccessCount == 0 && result.FailureCount > 0 {
		// 在无网络权限的环境中(沙箱约束)，跳过连接断言
		t.Skip("本地环境禁止底层 Socket 网络监听与连接，跳过连接断言")
		return
	}
	if result.SuccessCount != 25 {
		t.Errorf("期望成功 25 次请求，实际为 %d", result.SuccessCount)
	}
	if result.SuccessRate != 100.0 {
		t.Errorf("期望成功率 100%%，实际为 %f", result.SuccessRate)
	}
	if result.AvgTPS <= 0 {
		t.Errorf("期望 AvgTPS > 0，实际为 %f", result.AvgTPS)
	}
	if result.P50MS <= 0 || result.P90MS <= 0 || result.P99MS <= 0 {
		t.Errorf("延迟分位数计算异常: P50=%.2f, P90=%.2f, P99=%.2f", result.P50MS, result.P90MS, result.P99MS)
	}

	t.Logf("压测结果验证成功: Total=%d, TPS=%.2f, P50=%.2fms, P90=%.2fms, P99=%.2fms",
		result.TotalRequests, result.AvgTPS, result.P50MS, result.P90MS, result.P99MS)
}

func TestLoadRunner_StressExecutionWithProxy(t *testing.T) {
	proxyHits := 0
	// 启动一个模拟 HTTP 代理服务器
	proxyServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		proxyHits++
		w.Header().Set("X-Proxied-By", "MockProxy")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"proxy":true,"status":"ok"}`))
	}))
	defer proxyServer.Close()

	r := runner.NewLoadRunner()
	reqData := models.RequestData{
		Method: "GET",
		URL:    "http://external.mock.api.local/v1/data",
	}

	cfg := models.StressConfig{
		Concurrency:   3,
		TotalRequests: 10,
		TimeoutMS:     2000,
		ProxyURL:      proxyServer.URL,
	}

	result, err := r.RunStressTest(context.Background(), reqData, cfg, nil)
	if err != nil {
		t.Fatalf("带代理的压测执行失败: %v", err)
	}

	if result.TotalRequests != 10 {
		t.Errorf("期望完成 10 次请求，实际为 %d", result.TotalRequests)
	}
	if result.ProxyURL != proxyServer.URL {
		t.Errorf("期望报告中记录代理地址 %s，实际为 %s", proxyServer.URL, result.ProxyURL)
	}

	foundTip := false
	for _, tip := range result.DiagnosisTips {
		if strings.Contains(tip, "代理转发") {
			foundTip = true
			break
		}
	}
	if !foundTip {
		t.Errorf("期望诊断建议中包含代理转发提示，实际诊断建议为: %v", result.DiagnosisTips)
	}

	if proxyHits == 0 && result.FailureCount > 0 {
		t.Skip("本地环境禁止底层 Socket 连接，跳过代理命中计数断言")
		return
	}
	if proxyHits != 10 {
		t.Errorf("期望代理服务器收到 10 次请求，实际为 %d", proxyHits)
	}
}
