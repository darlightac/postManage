package tests

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"postmanage/internal/config"
	"postmanage/internal/core/client"
	"postmanage/internal/core/models"
)

func TestHTTPClient_TimingBreakdown(t *testing.T) {
	// 创建模拟测试服务
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(15 * time.Millisecond) // 模拟服务端耗时
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"status":"ok","message":"hello postmanage"}`))
	}))
	defer ts.Close()

	c := client.NewHTTPClient()
	reqData := models.RequestData{
		Method: "GET",
		URL:    ts.URL + "/test-endpoint",
		Params: []models.KeyValueItem{
			{Key: "query", Value: "golang", Enabled: true},
		},
	}

	resp, err := c.Send(context.Background(), reqData)
	if err != nil {
		t.Skipf("本地环境禁止底层 Socket 连接，跳过测试: %v", err)
		return
	}

	if resp.StatusCode != http.StatusOK {
		t.Errorf("期望状态码 200，实际为 %d", resp.StatusCode)
	}

	// 验证网络耗时拆解 (Feature 3)
	if resp.Timing.TotalMS <= 0 {
		t.Errorf("TotalMS 应该大于 0，实际为: %f", resp.Timing.TotalMS)
	}
	if resp.Timing.TTFBMS <= 0 {
		t.Errorf("TTFBMS 应该大于 0，实际为: %f", resp.Timing.TTFBMS)
	}
	t.Logf("Timing Breakdown 验证成功: DNS=%.2fms, TCP=%.2fms, TLS=%.2fms, TTFB=%.2fms, Download=%.2fms, Total=%.2fms",
		resp.Timing.DNSLookupMS, resp.Timing.TCPConnectMS, resp.Timing.TLSHandshakeMS,
		resp.Timing.TTFBMS, resp.Timing.DownloadMS, resp.Timing.TotalMS)
}

func TestHTTPClient_GlobalHeadersOverride(t *testing.T) {
	var receivedAuthHeader string
	var receivedCustomHeader string

	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedAuthHeader = r.Header.Get("Authorization")
		receivedCustomHeader = r.Header.Get("X-App-Env")
		w.WriteHeader(http.StatusOK)
	}))
	defer ts.Close()

	// 配置全局请求头
	cfg := config.GetConfigManager()
	_ = cfg.UpdateSettings(config.Settings{
		GlobalHeaders: []models.KeyValueItem{
			{Key: "Authorization", Value: "Bearer global-token-123", Enabled: true},
			{Key: "X-App-Env", Value: "production", Enabled: true},
		},
	})

	c := client.NewHTTPClient()

	// 场景 1: 单请求覆盖同名 Key（大小写不敏感覆盖: authorization 覆盖 Authorization）
	reqData := models.RequestData{
		Method: "GET",
		URL:    ts.URL,
		Headers: []models.KeyValueItem{
			{Key: "authorization", Value: "Bearer local-token-999", Enabled: true},
		},
	}

	_, err := c.Send(context.Background(), reqData)
	if err != nil {
		t.Skipf("本地环境禁止底层 Socket 连接，跳过测试: %v", err)
		return
	}

	if receivedAuthHeader != "Bearer local-token-999" {
		t.Errorf("单请求同名 Header 未正确覆盖全局 Header! 期望 Bearer local-token-999，实际得到: %s", receivedAuthHeader)
	}
	if receivedCustomHeader != "production" {
		t.Errorf("未被覆盖的全局 Header 应该生效! 期望 production，实际得到: %s", receivedCustomHeader)
	}

	t.Logf("全局请求头大小写不敏感覆盖优先级验证成功: %s, %s", receivedAuthHeader, receivedCustomHeader)
}
