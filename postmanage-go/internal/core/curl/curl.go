package curl

import (
	"fmt"
	"net/url"
	"regexp"
	"strings"

	"postmanage/internal/core/models"
)

// ExportCurl 将请求模型转换为格式化的 cURL 命令行
func ExportCurl(req models.RequestData, globalHeaders []models.KeyValueItem) string {
	parts := []string{"curl"}

	// 1. HTTP 方法
	method := strings.ToUpper(req.Method)
	if method == "" {
		method = "GET"
	}
	if method != "GET" {
		parts = append(parts, fmt.Sprintf("-X %s", method))
	}

	// 2. 目标 URL（拼接 Query 参数）
	targetURL := req.URL
	if len(req.Params) > 0 {
		parsed, err := url.Parse(targetURL)
		if err == nil {
			q := parsed.Query()
			for _, p := range req.Params {
				if p.Enabled && strings.TrimSpace(p.Key) != "" {
					q.Add(p.Key, p.Value)
				}
			}
			parsed.RawQuery = q.Encode()
			targetURL = parsed.String()
		}
	}
	parts = append(parts, fmt.Sprintf("'%s'", escapeSingleQuote(targetURL)))

	// 3. 合并全局请求头与单请求头（单请求配置同名 key 优先覆盖，大小写不敏感）
	mergedHeaders := make(map[string]string)
	lowerToKey := make(map[string]string)

	for _, gh := range globalHeaders {
		if gh.Enabled && strings.TrimSpace(gh.Key) != "" {
			k := strings.TrimSpace(gh.Key)
			kLower := strings.ToLower(k)
			mergedHeaders[k] = gh.Value
			lowerToKey[kLower] = k
		}
	}

	for _, h := range req.Headers {
		if h.Enabled && strings.TrimSpace(h.Key) != "" {
			k := strings.TrimSpace(h.Key)
			kLower := strings.ToLower(k)
			if oldKey, exists := lowerToKey[kLower]; exists && oldKey != k {
				delete(mergedHeaders, oldKey)
			}
			mergedHeaders[k] = h.Value
			lowerToKey[kLower] = k
		}
	}

	for k, v := range mergedHeaders {
		parts = append(parts, fmt.Sprintf("-H '%s: %s'", k, escapeSingleQuote(v)))
	}

	// 4. Cookies
	if len(req.Cookies) > 0 {
		cookiePairs := make([]string, 0)
		for _, c := range req.Cookies {
			if c.Enabled && c.Key != "" {
				cookiePairs = append(cookiePairs, fmt.Sprintf("%s=%s", c.Key, c.Value))
			}
		}
		if len(cookiePairs) > 0 {
			parts = append(parts, fmt.Sprintf("--cookie '%s'", escapeSingleQuote(strings.Join(cookiePairs, "; "))))
		}
	}

	// 5. Auth
	switch strings.ToLower(req.AuthType) {
	case "basic":
		username := req.AuthConfig["username"]
		password := req.AuthConfig["password"]
		parts = append(parts, fmt.Sprintf("-u '%s:%s'", escapeSingleQuote(username), escapeSingleQuote(password)))
	case "bearer":
		token := req.AuthConfig["token"]
		if token != "" {
			parts = append(parts, fmt.Sprintf("-H 'Authorization: Bearer %s'", escapeSingleQuote(token)))
		}
	case "apikey":
		key := req.AuthConfig["key"]
		val := req.AuthConfig["value"]
		if key != "" {
			parts = append(parts, fmt.Sprintf("-H '%s: %s'", key, escapeSingleQuote(val)))
		}
	}

	// 6. Body
	switch strings.ToLower(req.BodyType) {
	case "json":
		if strings.TrimSpace(req.BodyContent) != "" {
			hasContentType := false
			for k := range mergedHeaders {
				if strings.EqualFold(k, "Content-Type") {
					hasContentType = true
					break
				}
			}
			if !hasContentType {
				parts = append(parts, "-H 'Content-Type: application/json'")
			}
			parts = append(parts, fmt.Sprintf("--data-raw '%s'", escapeSingleQuote(req.BodyContent)))
		}
	case "urlencoded":
		if strings.TrimSpace(req.BodyContent) != "" {
			parts = append(parts, fmt.Sprintf("--data '%s'", escapeSingleQuote(req.BodyContent)))
		}
	case "raw":
		if strings.TrimSpace(req.BodyContent) != "" {
			parts = append(parts, fmt.Sprintf("--data '%s'", escapeSingleQuote(req.BodyContent)))
		}
	case "binary":
		if req.BodyContent != "" {
			parts = append(parts, fmt.Sprintf("--data-binary '@%s'", escapeSingleQuote(req.BodyContent)))
		}
	}

	return strings.Join(parts, " \\\n  ")
}

// ParseCurl 将 cURL 命令行反解为 RequestData 请求对象
func ParseCurl(curlCmd string) (*models.RequestData, error) {
	req := &models.RequestData{
		Method:     "GET",
		Headers:    make([]models.KeyValueItem, 0),
		Params:     make([]models.KeyValueItem, 0),
		AuthConfig: make(map[string]string),
	}

	// 规范化多行命令
	cleaned := strings.ReplaceAll(curlCmd, "\\\n", " ")
	cleaned = strings.ReplaceAll(cleaned, "\\\r\n", " ")
	cleaned = strings.TrimSpace(cleaned)

	// 正则分词（支持单双引号内的字符串）
	tokens := tokenize(cleaned)
	if len(tokens) == 0 || tokens[0] != "curl" {
		return nil, fmt.Errorf("无效的 cURL 命令")
	}

	for i := 1; i < len(tokens); i++ {
		arg := tokens[i]

		switch arg {
		case "-X", "--request":
			if i+1 < len(tokens) {
				req.Method = strings.ToUpper(tokens[i+1])
				i++
			}
		case "-H", "--header":
			if i+1 < len(tokens) {
				headerStr := tokens[i+1]
				if idx := strings.Index(headerStr, ":"); idx > 0 {
					k := strings.TrimSpace(headerStr[:idx])
					v := strings.TrimSpace(headerStr[idx+1:])
					req.Headers = append(req.Headers, models.KeyValueItem{Key: k, Value: v, Enabled: true})
				}
				i++
			}
		case "-d", "--data", "--data-raw", "--data-ascii":
			if i+1 < len(tokens) {
				req.BodyContent = tokens[i+1]
				req.BodyType = "json"
				if req.Method == "GET" {
					req.Method = "POST"
				}
				i++
			}
		case "-u", "--user":
			if i+1 < len(tokens) {
				userPass := tokens[i+1]
				parts := strings.SplitN(userPass, ":", 2)
				req.AuthType = "basic"
				req.AuthConfig["username"] = parts[0]
				if len(parts) > 1 {
					req.AuthConfig["password"] = parts[1]
				}
				i++
			}
		case "-b", "--cookie":
			if i+1 < len(tokens) {
				cookieStr := tokens[i+1]
				pairs := strings.Split(cookieStr, ";")
				for _, pair := range pairs {
					if cparts := strings.SplitN(strings.TrimSpace(pair), "=", 2); len(cparts) == 2 {
						req.Cookies = append(req.Cookies, models.KeyValueItem{
							Key:     strings.TrimSpace(cparts[0]),
							Value:   strings.TrimSpace(cparts[1]),
							Enabled: true,
						})
					}
				}
				i++
			}
		default:
			if !strings.HasPrefix(arg, "-") && req.URL == "" {
				req.URL = arg
			}
		}
	}

	// 如果 URL 包含 query，反解到 Params
	if req.URL != "" {
		if parsed, err := url.Parse(req.URL); err == nil {
			q := parsed.Query()
			for k, vs := range q {
				for _, v := range vs {
					req.Params = append(req.Params, models.KeyValueItem{Key: k, Value: v, Enabled: true})
				}
			}
		}
	}

	return req, nil
}

func escapeSingleQuote(s string) string {
	return strings.ReplaceAll(s, "'", "'\\''")
}

// tokenize 正则拆分命令行参数
func tokenize(cmd string) []string {
	re := regexp.MustCompile(`[^\s"']+|"([^"]*)"|'([^']*)'`)
	matches := re.FindAllStringSubmatch(cmd, -1)
	tokens := make([]string, 0, len(matches))
	for _, m := range matches {
		if m[1] != "" {
			tokens = append(tokens, m[1])
		} else if m[2] != "" {
			tokens = append(tokens, m[2])
		} else {
			tokens = append(tokens, m[0])
		}
	}
	return tokens
}
