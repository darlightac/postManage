package tests

import (
	"strings"
	"testing"

	"postmanage/internal/core/curl"
	"postmanage/internal/core/models"
)

func TestCurlExport_WithGlobalHeaders(t *testing.T) {
	reqData := models.RequestData{
		Method: "POST",
		URL:    "https://api.example.com/v1/users",
		Params: []models.KeyValueItem{
			{Key: "source", Value: "web", Enabled: true},
		},
		Headers: []models.KeyValueItem{
			{Key: "Content-Type", Value: "application/json", Enabled: true},
			{Key: "x-request-id", Value: "local-req-001", Enabled: true},
		},
		Cookies: []models.KeyValueItem{
			{Key: "session_id", Value: "sess_abc123", Enabled: true},
		},
		BodyType:    "json",
		BodyContent: `{"name":"alice"}`,
	}

	globalHeaders := []models.KeyValueItem{
		{Key: "X-Request-Id", Value: "global-override-me", Enabled: true},
		{Key: "X-App-Version", Value: "2.0.0", Enabled: true},
	}

	cmd := curl.ExportCurl(reqData, globalHeaders)

	t.Logf("生成的 cURL 命令行:\n%s", cmd)

	if !strings.Contains(cmd, "-X POST") || !strings.Contains(cmd, "'https://api.example.com/v1/users?source=web'") {
		t.Errorf("cURL URL 与 Method 导出异常: %s", cmd)
	}
	if !strings.Contains(cmd, "-H 'x-request-id: local-req-001'") {
		t.Errorf("单请求同名 Header 应该优先覆盖全局 Header: %s", cmd)
	}
	if strings.Contains(cmd, "global-override-me") {
		t.Errorf("被覆盖的全局 Header 不应出现在最终命令中: %s", cmd)
	}
	if !strings.Contains(cmd, "-H 'X-App-Version: 2.0.0'") {
		t.Errorf("未冲突的全局 Header 应正常包含: %s", cmd)
	}
	if !strings.Contains(cmd, "--cookie 'session_id=sess_abc123'") {
		t.Errorf("Cookie 应正确导出: %s", cmd)
	}
	if !strings.Contains(cmd, "--data-raw '{\"name\":\"alice\"}'") {
		t.Errorf("Body 应正确导出: %s", cmd)
	}
}

func TestCurlParse(t *testing.T) {
	cmd := `curl -X POST "https://api.example.com/v2/items" -H "Authorization: Bearer token123" -H "Content-Type: application/json" -d '{"item_id": 42}'`

	req, err := curl.ParseCurl(cmd)
	if err != nil {
		t.Fatalf("ParseCurl 失败: %v", err)
	}

	if req.Method != "POST" {
		t.Errorf("解析 Method 期望 POST，实际得到 %s", req.Method)
	}
	if req.URL != "https://api.example.com/v2/items" {
		t.Errorf("解析 URL 错误: %s", req.URL)
	}
	if req.BodyContent != `{"item_id": 42}` {
		t.Errorf("解析 Body 错误: %s", req.BodyContent)
	}

	foundAuth := false
	for _, h := range req.Headers {
		if strings.EqualFold(h.Key, "Authorization") && h.Value == "Bearer token123" {
			foundAuth = true
		}
	}
	if !foundAuth {
		t.Errorf("未能正确解析 Header: Authorization")
	}
}
