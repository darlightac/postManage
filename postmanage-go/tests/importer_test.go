package tests

import (
	"os"
	"path/filepath"
	"testing"

	"postmanage/internal/core/db"
	"postmanage/internal/core/importer"
	"postmanage/internal/core/models"
)

func TestCollection_ExportAndImport(t *testing.T) {
	tempDir := filepath.Join(os.TempDir(), "postmanage_test_export")
	_ = os.RemoveAll(tempDir)
	storage, err := db.NewStorage(tempDir)
	if err != nil {
		t.Fatalf("初始化存储失败: %v", err)
	}

	// 1. 创建测试集合和请求
	col := models.Collection{
		ID:   "col_test_1",
		Name: "用户认证接口",
	}
	_ = storage.SaveCollection(col)

	req := models.RequestData{
		ID:           "req_test_1",
		CollectionID: "col_test_1",
		Name:         "登录请求",
		Method:       "POST",
		URL:          "https://api.example.com/login",
		Headers: []models.KeyValueItem{
			{Key: "Content-Type", Value: "application/json", Enabled: true},
		},
		BodyType:    "json",
		BodyContent: `{"username":"admin"}`,
	}
	_ = storage.SaveRequest(req)

	// 2. 导出集合
	exportBytes, err := importer.ExportCollections(storage)
	if err != nil {
		t.Fatalf("导出集合失败: %v", err)
	}

	if len(exportBytes) == 0 {
		t.Fatal("导出的 JSON 为空")
	}
	t.Logf("导出的集合 JSON: %s", string(exportBytes))

	// 3. 在全新的 Storage 中导入
	tempDir2 := filepath.Join(os.TempDir(), "postmanage_test_import")
	_ = os.RemoveAll(tempDir2)
	storage2, _ := db.NewStorage(tempDir2)

	cCount, rCount, err := importer.ImportCollections(exportBytes, storage2)
	if err != nil {
		t.Fatalf("导入失败: %v", err)
	}

	if cCount != 1 || rCount != 1 {
		t.Errorf("期望导入 1 集合 1 请求，实际导入 %d 集合 %d 请求", cCount, rCount)
	}

	allCols := storage2.GetAllCollections()
	if len(allCols) != 1 || allCols[0].Name != "用户认证接口" {
		t.Errorf("导入后集合数据不一致: %+v", allCols)
	}

	allReqs := storage2.GetRequestsByCollection(allCols[0].ID)
	if len(allReqs) != 1 || allReqs[0].Name != "登录请求" {
		t.Errorf("导入后请求数据不一致: %+v", allReqs)
	}
}

func TestCollection_ImportPostmanV21(t *testing.T) {
	postmanJSON := `
	{
		"info": {
			"name": "Postman 演示集合",
			"schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
		},
		"item": [
			{
				"name": "用户模块",
				"item": [
					{
						"name": "获取用户信息",
						"request": {
							"method": "GET",
							"url": {
								"raw": "https://api.example.com/user?id=100",
								"query": [{"key": "id", "value": "100"}]
							},
							"header": [{"key": "Accept", "value": "application/json"}]
						}
					}
				]
			}
		]
	}
	`

	tempDir := filepath.Join(os.TempDir(), "postmanage_test_pm_import")
	_ = os.RemoveAll(tempDir)
	storage, _ := db.NewStorage(tempDir)

	cCount, rCount, err := importer.ImportCollections([]byte(postmanJSON), storage)
	if err != nil {
		t.Fatalf("导入 Postman v2.1 失败: %v", err)
	}

	if cCount < 2 || rCount != 1 {
		t.Errorf("期望导入至少 2 个集合层级和 1 个请求，实际得到 cCount=%d, rCount=%d", cCount, rCount)
	}

	cols := storage.GetAllCollections()
	t.Logf("Postman 导入成功，共 %d 个集合项，%d 个请求", len(cols), rCount)
}
