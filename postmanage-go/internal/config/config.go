package config

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sync"

	"postmanage/internal/core/models"
)

// Settings 全局配置
type Settings struct {
	DefaultTimeout int64                 `json:"default_timeout"` // 毫秒
	Theme          string                `json:"theme"`           // light, dark
	Language       string                `json:"language"`        // zh, en
	GlobalHeaders  []models.KeyValueItem `json:"global_headers"`
}

// ConfigManager 配置管理器单例
type ConfigManager struct {
	mu       sync.RWMutex
	settings Settings
	filePath string
}

var (
	instance *ConfigManager
	once     sync.Once
)

// DefaultSettings 获取默认配置
func DefaultSettings() Settings {
	return Settings{
		DefaultTimeout: 30000,
		Theme:          "light",
		Language:       "zh",
		GlobalHeaders:  []models.KeyValueItem{},
	}
}

// GetConfigManager 获取单例实例
func GetConfigManager(dataDir ...string) *ConfigManager {
	once.Do(func() {
		dir := "."
		if len(dataDir) > 0 && dataDir[0] != "" {
			dir = dataDir[0]
		}
		path := filepath.Join(dir, "settings.json")
		instance = &ConfigManager{
			settings: DefaultSettings(),
			filePath: path,
		}
		instance.Load()
	})
	return instance
}

// Load 从磁盘读取配置
func (m *ConfigManager) Load() error {
	m.mu.Lock()
	defer m.mu.Unlock()

	data, err := os.ReadFile(m.filePath)
	if err != nil {
		return err
	}
	var s Settings
	if err := json.Unmarshal(data, &s); err != nil {
		return err
	}
	m.settings = s
	return nil
}

// Save 保存配置到磁盘
func (m *ConfigManager) Save() error {
	m.mu.RLock()
	defer m.mu.RUnlock()

	data, err := json.MarshalIndent(m.settings, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(m.filePath, data, 0644)
}

// GetSettings 读取配置副本
func (m *ConfigManager) GetSettings() Settings {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.settings
}

// UpdateSettings 更新配置并持久化
func (m *ConfigManager) UpdateSettings(s Settings) error {
	m.mu.Lock()
	m.settings = s
	m.mu.Unlock()
	return m.Save()
}

// ─── 主题色板定义（优雅温润的低饱和护眼色调） ────────────────────────

// ThemeColors 主题颜色集合
type ThemeColors struct {
	Name             string            `json:"name"`
	BgPrimary        string            `json:"bg_primary"`
	BgSecondary      string            `json:"bg_secondary"`
	BgSidebar        string            `json:"bg_sidebar"`
	TextPrimary      string            `json:"text_primary"`
	TextSecondary    string            `json:"text_secondary"`
	Border           string            `json:"border"`
	Accent           string            `json:"accent"`
	AccentHover      string            `json:"accent_hover"`
	MethodColors     map[string]string `json:"method_colors"`
}

var LightTheme = ThemeColors{
	Name:          "light",
	BgPrimary:     "#ffffff",
	BgSecondary:   "#f8f9fa",
	BgSidebar:     "#f4f5f7",
	TextPrimary:   "#1f2937",
	TextSecondary: "#4b5563",
	Border:        "#d1d5db",
	Accent:        "#2563eb",
	AccentHover:   "#1d4ed8",
	MethodColors: map[string]string{
		"GET":     "#15803d", // 森林绿（杜绝刺眼荧光绿）
		"POST":    "#b45309", // 沉稳深琥珀
		"PUT":     "#1d4ed8", // 皇家蓝
		"DELETE":  "#b91c1c", // 沉稳酒红
		"PATCH":   "#6d28d9", // 雅致深紫
		"HEAD":    "#475569", // 铅灰
		"OPTIONS": "#0e7490", // 墨青
	},
}

var DarkTheme = ThemeColors{
	Name:          "dark",
	BgPrimary:     "#1e1e1e",
	BgSecondary:   "#252526",
	BgSidebar:     "#252526",
	TextPrimary:   "#cccccc",
	TextSecondary: "#858585",
	Border:        "#3c3c3c",
	Accent:        "#0e639c",
	AccentHover:   "#1177bb",
	MethodColors: map[string]string{
		"GET":     "#49cc90",
		"POST":    "#fca130",
		"PUT":     "#61affe",
		"DELETE":  "#f93e3e",
		"PATCH":   "#50e3c2",
		"HEAD":    "#9012fe",
		"OPTIONS": "#0d5aa7",
	},
}

// ─── 国际化词典 (i18n) ──────────────────────────────────────────

var Translations = map[string]map[string]string{
	"zh": {
		"app_name":            "PostManage API 工作台",
		"btn_send":            "发送",
		"btn_cancel":          "取消",
		"btn_stress_test":     "⚡ 压力测试",
		"btn_page_sniff":      "🔍 页面接口巡检",
		"tab_params":          "Params",
		"tab_headers":         "Headers",
		"tab_cookies":         "Cookies",
		"tab_body":            "Body",
		"tab_auth":            "Auth",
		"tab_curl":            "cURL Export",
		"tab_global_headers":  "全局请求头",
		"tab_timing":          "⏱ 耗时分析",
		"gh_tip":              "💡 全局请求头在所有请求中均自动生效。若某个请求配置了同名请求头（大小写不敏感），以该请求为准。",
	},
	"en": {
		"app_name":            "PostManage API Workbench",
		"btn_send":            "Send",
		"btn_cancel":          "Cancel",
		"btn_stress_test":     "⚡ Stress Test",
		"btn_page_sniff":      "🔍 Page API Inspector",
		"tab_params":          "Params",
		"tab_headers":         "Headers",
		"tab_cookies":         "Cookies",
		"tab_body":            "Body",
		"tab_auth":            "Auth",
		"tab_curl":            "cURL Export",
		"tab_global_headers":  "Global Headers",
		"tab_timing":          "⏱ Timing",
		"gh_tip":              "💡 Global headers apply to all requests automatically. Individual request headers override them case-insensitively.",
	},
}

// Tr 快速翻译
func Tr(lang, key string) string {
	if dict, ok := Translations[lang]; ok {
		if val, exists := dict[key]; exists {
			return val
		}
	}
	if zhDict, ok := Translations["zh"]; ok {
		if val, exists := zhDict[key]; exists {
			return val
		}
	}
	return key
}
