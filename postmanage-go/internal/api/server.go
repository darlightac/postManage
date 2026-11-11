package api

import (
	"embed"
	"encoding/json"
	"io"
	"io/fs"
	"net/http"

	"postmanage/internal/config"
	"postmanage/internal/core/client"
	"postmanage/internal/core/curl"
	"postmanage/internal/core/db"
	"postmanage/internal/core/importer"
	"postmanage/internal/core/models"
	"postmanage/internal/core/runner"
	"postmanage/internal/core/sniffer"
)

//go:embed web/*
var webFS embed.FS

// Server 统一 API 控制器与静态资源服务器
type Server struct {
	storage    *db.Storage
	httpClient *client.HTTPClient
	runner     *runner.LoadRunner
	sniffer    *sniffer.PageSniffer
	mux        *http.ServeMux
}

// NewServer 创建服务器实例
func NewServer(storage *db.Storage) *Server {
	s := &Server{
		storage:    storage,
		httpClient: client.NewHTTPClient(),
		runner:     runner.NewLoadRunner(),
		sniffer:    sniffer.NewPageSniffer(),
		mux:        http.NewServeMux(),
	}
	s.routes()
	return s
}

// Handler 返回标准 http.Handler
func (s *Server) Handler() http.Handler {
	return s.mux
}

func (s *Server) routes() {
	// API 请求发送
	s.mux.HandleFunc("/api/request/send", s.handleSendRequest)

	// 极简并发压测
	s.mux.HandleFunc("/api/stress/run", s.handleRunStress)

	// 页面接口智能嗅探巡检
	s.mux.HandleFunc("/api/sniffer/scan", s.handlePageScan)
	s.mux.HandleFunc("/api/sniffer/stress", s.handlePageStress)

	// cURL 双向转换
	s.mux.HandleFunc("/api/curl/export", s.handleCurlExport)
	s.mux.HandleFunc("/api/curl/parse", s.handleCurlParse)

	// 集合管理与导入导出
	s.mux.HandleFunc("/api/collections", s.handleCollections)
	s.mux.HandleFunc("/api/collections/export", s.handleCollectionsExport)
	s.mux.HandleFunc("/api/collections/import", s.handleCollectionsImport)

	// 接口项管理
	s.mux.HandleFunc("/api/requests", s.handleRequests)

	// 历史记录
	s.mux.HandleFunc("/api/history", s.handleHistory)

	// 系统设置
	s.mux.HandleFunc("/api/settings", s.handleSettings)

	// 静态 Web 控制面板
	subFS, err := fs.Sub(webFS, "web")
	if err == nil {
		s.mux.Handle("/", http.FileServer(http.FS(subFS)))
	}
}

func (s *Server) handleSendRequest(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var reqData models.RequestData
	if err := json.NewDecoder(r.Body).Decode(&reqData); err != nil {
		s.jsonError(w, "无效的请求格式", http.StatusBadRequest)
		return
	}

	resp, err := s.httpClient.Send(r.Context(), reqData)
	if err != nil && resp == nil {
		s.jsonError(w, err.Error(), http.StatusInternalServerError)
		return
	}

	// 记录历史
	if resp != nil {
		_ = s.storage.AddHistory(models.HistoryRecord{
			ID:          reqData.ID,
			Name:        reqData.Name,
			Method:      reqData.Method,
			URL:         reqData.URL,
			StatusCode:  resp.StatusCode,
			ElapsedMS:   resp.ElapsedMS,
			SizeBytes:   resp.SizeBytes,
			Timing:      resp.Timing,
			RequestData: reqData,
		})
	}

	s.jsonResponse(w, resp)
}

func (s *Server) handleRunStress(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var payload struct {
		Request models.RequestData  `json:"request"`
		Config  models.StressConfig `json:"config"`
	}

	if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
		s.jsonError(w, "无效的压测请求载荷", http.StatusBadRequest)
		return
	}

	result, err := s.runner.RunStressTest(r.Context(), payload.Request, payload.Config, nil)
	if err != nil {
		s.jsonError(w, err.Error(), http.StatusInternalServerError)
		return
	}

	s.jsonResponse(w, result)
}

func (s *Server) handlePageScan(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var payload models.PageScanConfig
	if err := json.NewDecoder(r.Body).Decode(&payload); err != nil || payload.TargetURL == "" {
		s.jsonError(w, "必须提供有效的 target_url", http.StatusBadRequest)
		return
	}

	result, err := s.sniffer.ScanPage(r.Context(), payload)
	if err != nil {
		s.jsonError(w, err.Error(), http.StatusInternalServerError)
		return
	}

	s.jsonResponse(w, result)
}

func (s *Server) handlePageStress(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var cfg models.PageStressConfig
	if err := json.NewDecoder(r.Body).Decode(&cfg); err != nil || cfg.TargetURL == "" {
		s.jsonError(w, "必须提供有效的压测参数及 target_url", http.StatusBadRequest)
		return
	}

	result, err := s.sniffer.StressPage(r.Context(), cfg)
	if err != nil {
		s.jsonError(w, err.Error(), http.StatusInternalServerError)
		return
	}

	s.jsonResponse(w, result)
}

func (s *Server) handleCurlExport(w http.ResponseWriter, r *http.Request) {
	var reqData models.RequestData
	if err := json.NewDecoder(r.Body).Decode(&reqData); err != nil {
		s.jsonError(w, "无效的请求格式", http.StatusBadRequest)
		return
	}

	cfg := config.GetConfigManager().GetSettings()
	cmd := curl.ExportCurl(reqData, cfg.GlobalHeaders)
	s.jsonResponse(w, map[string]string{"curl_command": cmd})
}

func (s *Server) handleCurlParse(w http.ResponseWriter, r *http.Request) {
	var payload struct {
		Command string `json:"command"`
	}
	if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
		s.jsonError(w, "缺少 command 字段", http.StatusBadRequest)
		return
	}

	reqData, err := curl.ParseCurl(payload.Command)
	if err != nil {
		s.jsonError(w, err.Error(), http.StatusBadRequest)
		return
	}

	s.jsonResponse(w, reqData)
}

func (s *Server) handleCollections(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodGet:
		cols := s.storage.GetAllCollections()
		s.jsonResponse(w, cols)
	case http.MethodPost:
		var c models.Collection
		if err := json.NewDecoder(r.Body).Decode(&c); err != nil {
			s.jsonError(w, "无效数据", http.StatusBadRequest)
			return
		}
		_ = s.storage.SaveCollection(c)
		s.jsonResponse(w, map[string]bool{"ok": true})
	case http.MethodDelete:
		id := r.URL.Query().Get("id")
		if id != "" {
			_ = s.storage.DeleteCollection(id)
		}
		s.jsonResponse(w, map[string]bool{"ok": true})
	default:
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
	}
}

func (s *Server) handleCollectionsExport(w http.ResponseWriter, r *http.Request) {
	data, err := importer.ExportCollections(s.storage)
	if err != nil {
		s.jsonError(w, err.Error(), http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Content-Disposition", "attachment; filename=\"postmanage_collections.json\"")
	_, _ = w.Write(data)
}

func (s *Server) handleCollectionsImport(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	body, err := io.ReadAll(r.Body)
	if err != nil {
		s.jsonError(w, "无法读取上传内容", http.StatusBadRequest)
		return
	}
	cCount, rCount, err := importer.ImportCollections(body, s.storage)
	if err != nil {
		s.jsonError(w, err.Error(), http.StatusBadRequest)
		return
	}
	s.jsonResponse(w, map[string]any{
		"ok":                   true,
		"imported_collections": cCount,
		"imported_requests":    rCount,
	})
}

func (s *Server) handleRequests(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodGet:
		if id := r.URL.Query().Get("id"); id != "" {
			req, ok := s.storage.GetRequest(id)
			if !ok {
				s.jsonError(w, "请求未找到", http.StatusNotFound)
				return
			}
			s.jsonResponse(w, req)
			return
		}
		cid := r.URL.Query().Get("collection_id")
		reqs := s.storage.GetRequestsByCollection(cid)
		s.jsonResponse(w, reqs)
	case http.MethodPost:
		var reqData models.RequestData
		if err := json.NewDecoder(r.Body).Decode(&reqData); err != nil {
			s.jsonError(w, "无效数据", http.StatusBadRequest)
			return
		}
		_ = s.storage.SaveRequest(reqData)
		s.jsonResponse(w, map[string]bool{"ok": true})
	case http.MethodDelete:
		id := r.URL.Query().Get("id")
		if id != "" {
			_ = s.storage.DeleteRequest(id)
		}
		s.jsonResponse(w, map[string]bool{"ok": true})
	default:
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
	}
}

func (s *Server) handleHistory(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodGet:
		s.jsonResponse(w, s.storage.GetHistory())
	case http.MethodDelete:
		_ = s.storage.ClearHistory()
		s.jsonResponse(w, map[string]bool{"ok": true})
	default:
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
	}
}

func (s *Server) handleSettings(w http.ResponseWriter, r *http.Request) {
	mgr := config.GetConfigManager()
	switch r.Method {
	case http.MethodGet:
		s.jsonResponse(w, mgr.GetSettings())
	case http.MethodPost:
		var sCfg config.Settings
		if err := json.NewDecoder(r.Body).Decode(&sCfg); err != nil {
			s.jsonError(w, "无效设置数据", http.StatusBadRequest)
			return
		}
		_ = mgr.UpdateSettings(sCfg)
		s.jsonResponse(w, map[string]bool{"ok": true})
	default:
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
	}
}

func (s *Server) jsonResponse(w http.ResponseWriter, data any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	_ = json.NewEncoder(w).Encode(data)
}

func (s *Server) jsonError(w http.ResponseWriter, msg string, code int) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": msg})
}
