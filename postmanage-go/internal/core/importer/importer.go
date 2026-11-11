package importer

import (
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"postmanage/internal/core/db"
	"postmanage/internal/core/models"
)

// PostManageExportData 导出的 JSON 顶层结构
type PostManageExportData struct {
	Version     string           `json:"version"`
	Format      string           `json:"format"`
	Collections []CollectionExport `json:"collections"`
}

type CollectionExport struct {
	Name        string                `json:"name"`
	Description string                `json:"description"`
	Requests    []models.RequestData  `json:"requests"`
	Children    []CollectionExport    `json:"children,omitempty"`
}

// ExportCollections 导出集合为标准 JSON
func ExportCollections(storage *db.Storage) ([]byte, error) {
	allCols := storage.GetAllCollections()
	rootCols := make([]models.Collection, 0)
	for _, c := range allCols {
		if c.ParentID == "" {
			rootCols = append(rootCols, c)
		}
	}

	res := PostManageExportData{
		Version:     "2.0",
		Format:      "postmanage",
		Collections: make([]CollectionExport, 0),
	}

	for _, rc := range rootCols {
		ce := exportCollectionRecursive(rc, allCols, storage)
		res.Collections = append(res.Collections, ce)
	}

	return json.MarshalIndent(res, "", "  ")
}

func exportCollectionRecursive(col models.Collection, allCols []models.Collection, storage *db.Storage) CollectionExport {
	reqs := storage.GetRequestsByCollection(col.ID)
	ce := CollectionExport{
		Name:        col.Name,
		Description: col.Description,
		Requests:    reqs,
		Children:    make([]CollectionExport, 0),
	}

	for _, c := range allCols {
		if c.ParentID == col.ID {
			childCe := exportCollectionRecursive(c, allCols, storage)
			ce.Children = append(ce.Children, childCe)
		}
	}
	return ce
}

// ImportCollections 导入集合（支持 PostManage 原生格式与 Postman Collection v2.1 格式）
func ImportCollections(jsonData []byte, storage *db.Storage) (int, int, error) {
	var rawMap map[string]any
	if err := json.Unmarshal(jsonData, &rawMap); err != nil {
		return 0, 0, fmt.Errorf("JSON 解析失败: %w", err)
	}

	// 1. 检测是否为 PostManage / RequestManager 格式
	fmtVal, _ := rawMap["format"].(string)
	if fmtVal == "postmanage" || fmtVal == "requestmanager" {
		var pmData PostManageExportData
		if err := json.Unmarshal(jsonData, &pmData); err != nil {
			return 0, 0, err
		}
		cCount, rCount := 0, 0
		for _, ce := range pmData.Collections {
			c, r := importPmRecursive(ce, "", storage)
			cCount += c
			rCount += r
		}
		return cCount, rCount, nil
	}

	// 2. 检测是否为 Postman Collection v2.1 格式
	if infoMap, ok := rawMap["info"].(map[string]any); ok {
		schemaStr, _ := infoMap["schema"].(string)
		if strings.Contains(schemaStr, "schema.getpostman.com") || infoMap["name"] != nil {
			return importPostmanCollection(rawMap, storage)
		}
	}

	// 尝试作为通用格式解析
	if colsArray, ok := rawMap["collections"].([]any); ok && len(colsArray) > 0 {
		var pmData PostManageExportData
		if err := json.Unmarshal(jsonData, &pmData); err == nil {
			cCount, rCount := 0, 0
			for _, ce := range pmData.Collections {
				c, r := importPmRecursive(ce, "", storage)
				cCount += c
				rCount += r
			}
			return cCount, rCount, nil
		}
	}

	return 0, 0, fmt.Errorf("无法识别的集合格式，仅支持 PostManage JSON 或 Postman Collection v2.1")
}

func importPmRecursive(ce CollectionExport, parentID string, storage *db.Storage) (int, int) {
	colID := fmt.Sprintf("col_%d", time.Now().UnixNano())
	col := models.Collection{
		ID:          colID,
		Name:        ce.Name,
		Description: ce.Description,
		ParentID:    parentID,
		CreatedAt:   time.Now(),
		UpdatedAt:   time.Now(),
	}
	_ = storage.SaveCollection(col)
	cCount := 1
	rCount := 0

	for _, r := range ce.Requests {
		r.ID = fmt.Sprintf("req_%d", time.Now().UnixNano())
		r.CollectionID = colID
		_ = storage.SaveRequest(r)
		rCount++
	}

	for _, child := range ce.Children {
		c, r := importPmRecursive(child, colID, storage)
		cCount += c
		rCount += r
	}

	return cCount, rCount
}

func importPostmanCollection(raw map[string]any, storage *db.Storage) (int, int, error) {
	info, _ := raw["info"].(map[string]any)
	colName := "Postman 导入集合"
	if info != nil && info["name"] != nil {
		colName = fmt.Sprintf("%v", info["name"])
	}

	rootID := fmt.Sprintf("col_%d", time.Now().UnixNano())
	rootCol := models.Collection{
		ID:        rootID,
		Name:      colName,
		CreatedAt: time.Now(),
		UpdatedAt: time.Now(),
	}
	_ = storage.SaveCollection(rootCol)

	items, _ := raw["item"].([]any)
	cCount := 1
	rCount := 0

	for _, item := range items {
		itemMap, ok := item.(map[string]any)
		if !ok {
			continue
		}
		c, r := importPostmanItemRecursive(itemMap, rootID, storage)
		cCount += c
		rCount += r
	}

	return cCount, rCount, nil
}

func importPostmanItemRecursive(item map[string]any, parentColID string, storage *db.Storage) (int, int) {
	name, _ := item["name"].(string)
	if name == "" {
		name = "未命名项"
	}

	// 如果包含 item 数组，说明是文件夹/子集合
	if subItems, ok := item["item"].([]any); ok && subItems != nil {
		folderID := fmt.Sprintf("col_%d", time.Now().UnixNano())
		folder := models.Collection{
			ID:        folderID,
			Name:      name,
			ParentID:  parentColID,
			CreatedAt: time.Now(),
			UpdatedAt: time.Now(),
		}
		_ = storage.SaveCollection(folder)
		cCount := 1
		rCount := 0

		for _, sub := range subItems {
			if subMap, ok := sub.(map[string]any); ok {
				c, r := importPostmanItemRecursive(subMap, folderID, storage)
				cCount += c
				rCount += r
			}
		}
		return cCount, rCount
	}

	// 否则这是一个 Request
	reqMap, _ := item["request"].(map[string]any)
	if reqMap == nil {
		return 0, 0
	}

	method, _ := reqMap["method"].(string)
	if method == "" {
		method = "GET"
	}

	rawURL := ""
	switch u := reqMap["url"].(type) {
	case string:
		rawURL = u
	case map[string]any:
		rawURL, _ = u["raw"].(string)
	}

	// Headers
	headers := make([]models.KeyValueItem, 0)
	if hList, ok := reqMap["header"].([]any); ok {
		for _, h := range hList {
			if hm, ok := h.(map[string]any); ok {
				disabled, _ := hm["disabled"].(bool)
				headers = append(headers, models.KeyValueItem{
					Key:     fmt.Sprintf("%v", hm["key"]),
					Value:   fmt.Sprintf("%v", hm["value"]),
					Enabled: !disabled,
				})
			}
		}
	}

	// Body
	bodyType := "none"
	bodyContent := ""
	if bMap, ok := reqMap["body"].(map[string]any); ok {
		mode, _ := bMap["mode"].(string)
		switch mode {
		case "raw":
			bodyContent, _ = bMap["raw"].(string)
			if strings.HasPrefix(strings.TrimSpace(bodyContent), "{") {
				bodyType = "json"
			} else {
				bodyType = "raw"
			}
		case "urlencoded":
			bodyType = "urlencoded"
			lines := make([]string, 0)
			if urlList, ok := bMap["urlencoded"].([]any); ok {
				for _, entry := range urlList {
					if em, ok := entry.(map[string]any); ok {
						lines = append(lines, fmt.Sprintf("%v=%v", em["key"], em["value"]))
					}
				}
			}
			bodyContent = strings.Join(lines, "\n")
		case "formdata":
			bodyType = "form"
			lines := make([]string, 0)
			if fList, ok := bMap["formdata"].([]any); ok {
				for _, entry := range fList {
					if em, ok := entry.(map[string]any); ok {
						lines = append(lines, fmt.Sprintf("%v=%v", em["key"], em["value"]))
					}
				}
			}
			bodyContent = strings.Join(lines, "\n")
		}
	}

	reqID := fmt.Sprintf("req_%d", time.Now().UnixNano())
	reqData := models.RequestData{
		ID:           reqID,
		CollectionID: parentColID,
		Name:         name,
		Method:       strings.ToUpper(method),
		URL:          rawURL,
		Headers:      headers,
		BodyType:     bodyType,
		BodyContent:  bodyContent,
		CreatedAt:    time.Now(),
		UpdatedAt:    time.Now(),
	}

	_ = storage.SaveRequest(reqData)
	return 0, 1
}
