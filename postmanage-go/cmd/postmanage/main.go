package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"runtime"
	"syscall"
	"time"

	"github.com/jchv/go-webview2"

	"postmanage/internal/api"
	"postmanage/internal/config"
	"postmanage/internal/core/db"
)

func init() {
	// Win32 GUI 消息循环与 COM 组件必须锁定在主操作系统线程
	runtime.LockOSThread()
}

func openDefaultBrowser(url string) {
	var err error
	switch runtime.GOOS {
	case "windows":
		err = exec.Command("rundll32", "url.dll,FileProtocolHandler", url).Start()
	case "darwin":
		err = exec.Command("open", url).Start()
	case "linux":
		err = exec.Command("xdg-open", url).Start()
	}
	if err != nil {
		log.Printf("自动打开浏览器失败: %v，请手动访问: %s", err, url)
	}
}

func main() {
	port := flag.Int("port", 8088, "HTTP 服务监听端口")
	dataDir := flag.String("data", "./data", "本地数据与配置文件持久化目录")
	headless := flag.Bool("headless", false, "是否以后台纯服务模式运行 (不弹出原生桌面窗口)")
	debug := flag.Bool("debug", false, "是否开启内置 WebView2 开发者工具 (F12 调试)")
	flag.Parse()

	absDataDir, err := filepath.Abs(*dataDir)
	if err != nil {
		absDataDir = *dataDir
	}

	if err := os.MkdirAll(absDataDir, 0755); err != nil {
		log.Fatalf("创建数据目录失败: %v", err)
	}

	// 初始化全局配置与存储引擎
	_ = config.GetConfigManager(absDataDir)
	storage, err := db.NewStorage(absDataDir)
	if err != nil {
		log.Fatalf("初始化存储引擎失败: %v", err)
	}

	// 构造 API 服务
	srvHandler := api.NewServer(storage)

	addr := fmt.Sprintf(":%d", *port)
	httpServer := &http.Server{
		Addr:         addr,
		Handler:      srvHandler.Handler(),
		ReadTimeout:  120 * time.Second,
		WriteTimeout: 120 * time.Second,
		IdleTimeout:  120 * time.Second,
	}

	appURL := fmt.Sprintf("http://127.0.0.1:%d", *port)

	fmt.Println("==================================================================")
	fmt.Println("       PostManage v2.0 (Go 高性能企业级 API 调试与压测平台)")
	fmt.Println("       【架构模式】：方案二 · 原生 Win32 窗口内嵌 WebView2 运行时")
	fmt.Println("==================================================================")
	fmt.Printf(" [√] 控制台服务地址 : %s\n", appURL)
	fmt.Printf(" [√] 数据存储目录   : %s\n", absDataDir)
	fmt.Println(" [√] 核心功能模块   : API 调试 | 全链路瀑布流耗时 | 极简高并发压测 | 页面接口智能嗅探")
	fmt.Println("==================================================================")

	// 异步启动 HTTP API 后台服务
	go func() {
		if err := httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("后台服务启动异常: %v", err)
		}
	}()

	// 纯后台模式 (Headless / Server Mode)
	if *headless {
		fmt.Println("提示: 当前处于后台服务模式，按 Ctrl + C 可平滑关闭服务")
		quit := make(chan os.Signal, 1)
		signal.Notify(quit, os.Interrupt, syscall.SIGTERM)
		<-quit
		shutdownServer(httpServer)
		return
	}

	// 方案二：创建宿主进程 Win32 原生桌面窗口并内嵌 WebView2 COM 控件
	wvDataDir := filepath.Join(absDataDir, ".webview2")
	opts := webview2.WebViewOptions{
		Debug:     *debug,
		DataPath:  wvDataDir,
		AutoFocus: true,
		WindowOptions: webview2.WindowOptions{
			Title:  "PostManage - 高性能 API 调试与压测平台",
			Width:  1400,
			Height: 900,
			Center: true,
		},
	}

	w := webview2.NewWithOptions(opts)
	if w == nil {
		// 环境缺失 WebView2 时的优雅降级
		fmt.Println("未检测到系统原生 WebView2 运行时，自动降级为外部浏览器唤起模式...")
		openDefaultBrowser(appURL)

		quit := make(chan os.Signal, 1)
		signal.Notify(quit, os.Interrupt, syscall.SIGTERM)
		<-quit
		shutdownServer(httpServer)
		return
	}

	defer w.Destroy()
	w.SetTitle("PostManage - 高性能 API 调试与压测平台")
	w.SetSize(1400, 900, webview2.HintNone)

	// 导航加载内嵌 Web 视图
	w.Navigate(appURL)

	fmt.Println(" [√] 原生桌面应用窗口已成功呈现，关闭软件窗口将自动退出程序。")

	// 阻塞运行 Win32 原生 UI 消息泵循环 (GetMessage / DispatchMessage)
	w.Run()

	// 窗口关闭后，联动安全停机并持久化保存数据
	shutdownServer(httpServer)
}

func shutdownServer(server *http.Server) {
	fmt.Println("\n正在关闭 PostManage 服务，保存数据中...")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := server.Shutdown(ctx); err != nil {
		log.Printf("服务关闭异常: %v", err)
	}
	fmt.Println("PostManage 已安全退出。")
}
