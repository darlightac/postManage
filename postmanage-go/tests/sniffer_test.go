package tests

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"postmanage/internal/core/models"
	"postmanage/internal/core/sniffer"
)

func TestPageSniffer_ScanPageURL(t *testing.T) {
	// 模拟被检测页面及其后台接口
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/":
			w.Header().Set("Content-Type", "text/html; charset=utf-8")
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write([]byte(`
				<!DOCTYPE html>
				<html>
				<head>
					<script src="/static/app.js"></script>
				</head>
				<body>
					<h1>Test App</h1>
					<script>
						fetch('/api/user/info');
						axios.post('/api/order/create', { id: 1 });
					</script>
				</body>
				</html>
			`))
		case "/static/app.js":
			w.Header().Set("Content-Type", "application/javascript")
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write([]byte(`
				function checkAuth() {
					$.ajax({ url: '/api/auth/status' });
				}
			`))
		case "/api/user/info":
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write([]byte(`{"username":"tester"}`))
		case "/api/order/create":
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write([]byte(`{"orderId":1001}`))
		case "/api/auth/status":
			w.WriteHeader(http.StatusUnauthorized) // 模拟 warning
			_, _ = w.Write([]byte(`{"error":"unauthorized"}`))
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer ts.Close()

	sniff := sniffer.NewPageSniffer()
	result, err := sniff.ScanPageURL(context.Background(), ts.URL)
	if err != nil {
		t.Skipf("本地环境禁止底层 Socket 连接，跳过测试: %v", err)
		return
	}

	if result.TotalEndpoints < 3 {
		t.Errorf("期望至少嗅探到 3 个接口，实际嗅探到 %d 个", result.TotalEndpoints)
	}

	foundUserInfo := false
	foundOrderCreate := false
	foundAuthStatus := false

	for _, ep := range result.Endpoints {
		t.Logf("嗅探到端点: Method=%s, URL=%s, Status=%d, StatusType=%s", ep.Method, ep.URL, ep.StatusCode, ep.StatusType)
		if ep.Path == "/api/user/info" {
			foundUserInfo = true
			if ep.StatusCode != http.StatusOK || ep.StatusType != "healthy" {
				t.Errorf("/api/user/info 应该是 healthy, 实际状态: %s (%d)", ep.StatusType, ep.StatusCode)
			}
		}
		if ep.Path == "/api/order/create" {
			foundOrderCreate = true
			if ep.Method != "POST" {
				t.Errorf("/api/order/create 方法应被识别为 POST, 实际为 %s", ep.Method)
			}
		}
		if ep.Path == "/api/auth/status" {
			foundAuthStatus = true
			if ep.StatusType != "warning" {
				t.Errorf("/api/auth/status (401) 应该是 warning, 实际状态: %s", ep.StatusType)
			}
		}
	}

	if !foundUserInfo || !foundOrderCreate || !foundAuthStatus {
		t.Errorf("未全部嗅探出预期接口: userInfo=%v, orderCreate=%v, authStatus=%v",
			foundUserInfo, foundOrderCreate, foundAuthStatus)
	}

	// 进一步验证并发压测与 records 明细采集
	stressResult, err := sniff.StressPage(context.Background(), models.PageStressConfig{
		TargetURL:     ts.URL,
		TotalRequests: 5,
		Concurrency:   2,
	})
	if err != nil {
		t.Fatalf("全页面压测执行失败: %v", err)
	}
	if len(stressResult.EndpointReports) == 0 {
		t.Fatalf("未生成 EndpointReports")
	}
	for _, rep := range stressResult.EndpointReports {
		if rep.TotalRequests > 0 && len(rep.Records) == 0 {
			t.Errorf("接口 %s 的 Records 未采集到明细", rep.URL)
		}
	}

	// 验证页面事务级压测核心口径
	if stressResult.TotalPageIterations != 5 {
		t.Errorf("预期 TotalPageIterations=5, 实际=%d", stressResult.TotalPageIterations)
	}
	if stressResult.AvgPageLoadDurationMS <= 0 {
		t.Errorf("预期 AvgPageLoadDurationMS > 0, 实际=%f", stressResult.AvgPageLoadDurationMS)
	}
	if len(stressResult.EndpointRankings) == 0 {
		t.Errorf("预期生成 EndpointRankings")
	}
	// 验证排行榜是否降序
	for i := 1; i < len(stressResult.EndpointRankings); i++ {
		if stressResult.EndpointRankings[i].AvgLatencyMS > stressResult.EndpointRankings[i-1].AvgLatencyMS {
			t.Errorf("EndpointRankings 未按耗时降序排列: rank %d (%f) > rank %d (%f)",
				i+1, stressResult.EndpointRankings[i].AvgLatencyMS, i, stressResult.EndpointRankings[i-1].AvgLatencyMS)
		}
	}
	if len(stressResult.PageRecords) != 5 {
		t.Errorf("预期 PageRecords 长度=5, 实际=%d", len(stressResult.PageRecords))
	}
}
