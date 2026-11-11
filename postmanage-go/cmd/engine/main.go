package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"postmanage/internal/core/client"
	"postmanage/internal/core/models"
	"postmanage/internal/core/runner"
	"postmanage/internal/core/sniffer"
)

type EngineServer struct {
	httpClient *client.HTTPClient
	runner     *runner.LoadRunner
	sniffer    *sniffer.PageSniffer
	mux        *http.ServeMux
}

func NewEngineServer() *EngineServer {
	s := &EngineServer{
		httpClient: client.NewHTTPClient(),
		runner:     runner.NewLoadRunner(),
		sniffer:    sniffer.NewPageSniffer(),
		mux:        http.NewServeMux(),
	}
	s.routes()
	return s
}

func (s *EngineServer) routes() {
	// 心跳检查
	s.mux.HandleFunc("/api/health", func(w http.ResponseWriter, r *http.Request) {
		s.jsonResponse(w, map[string]string{"status": "ok", "version": "2.0"})
	})

	// 极简并发压测引擎
	s.mux.HandleFunc("/api/stress/run", s.handleStressRun)

	// 页面接口智能嗅探与健康巡检
	s.mux.HandleFunc("/api/sniffer/scan", s.handleSnifferScan)
	s.mux.HandleFunc("/api/sniffer/stress", s.handleSnifferStress)

	// 全链路网络耗时追踪
	s.mux.HandleFunc("/api/timing/send", s.handleTimingSend)
}

func (s *EngineServer) handleSnifferStress(w http.ResponseWriter, r *http.Request) {
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

func (s *EngineServer) handleStressRun(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var payload struct {
		Request models.RequestData  `json:"request"`
		Config  models.StressConfig `json:"config"`
	}

	if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
		s.jsonError(w, "无效的压测请求数据: "+err.Error(), http.StatusBadRequest)
		return
	}

	result, err := s.runner.RunStressTest(r.Context(), payload.Request, payload.Config, nil)
	if err != nil {
		s.jsonError(w, err.Error(), http.StatusInternalServerError)
		return
	}

	s.jsonResponse(w, result)
}

func (s *EngineServer) handleSnifferScan(w http.ResponseWriter, r *http.Request) {
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

func (s *EngineServer) handleTimingSend(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var reqData models.RequestData
	if err := json.NewDecoder(r.Body).Decode(&reqData); err != nil {
		s.jsonError(w, "无效请求格式", http.StatusBadRequest)
		return
	}

	resp, err := s.httpClient.Send(r.Context(), reqData)
	if err != nil && resp == nil {
		s.jsonError(w, err.Error(), http.StatusInternalServerError)
		return
	}

	s.jsonResponse(w, resp)
}

func (s *EngineServer) jsonResponse(w http.ResponseWriter, data any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	_ = json.NewEncoder(w).Encode(data)
}

func (s *EngineServer) jsonError(w http.ResponseWriter, msg string, code int) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": msg})
}

func main() {
	port := flag.Int("port", 0, "监听端口 (默认 0 表示由系统随机分配空闲端口)")
	flag.Parse()

	server := NewEngineServer()

	listener, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", *port))
	if err != nil {
		log.Fatalf("无法监听端口: %v", err)
	}

	actualPort := listener.Addr().(*net.TCPAddr).Port

	// 打印给父进程（Python）捕获的就绪信号
	fmt.Printf("POSTMANAGE_ENGINE_READY:%d\n", actualPort)
	_ = os.Stdout.Sync()

	httpServer := &http.Server{
		Handler:      server.mux,
		ReadTimeout:  300 * time.Second,
		WriteTimeout: 300 * time.Second,
		IdleTimeout:  120 * time.Second,
	}

	go func() {
		if err := httpServer.Serve(listener); err != nil && err != http.ErrServerClosed {
			log.Fatalf("引擎服务异常退出: %v", err)
		}
	}()

	// 守护协程：如果 stdin 关闭（例如父进程 Python 崩溃或退出），Go 引擎自动退出
	go func() {
		buf := make([]byte, 1)
		for {
			_, err := os.Stdin.Read(buf)
			if err != nil {
				// 父进程 pipe 关闭
				_ = httpServer.Close()
				os.Exit(0)
			}
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, os.Interrupt, syscall.SIGTERM)
	<-quit

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	_ = httpServer.Shutdown(ctx)
}
