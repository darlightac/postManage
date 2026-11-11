package db

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
	"sync"
	"time"

	"postmanage/internal/core/models"
)

// Storage 本地纯 Go 嵌入式存储引擎（Zero CGO，全平台原生兼容）
type Storage struct {
	mu          sync.RWMutex
	dir         string
	collections map[string]models.Collection
	requests    map[string]models.RequestData
	history     []models.HistoryRecord
}

// NewStorage 创建存储实例
func NewStorage(dir string) (*Storage, error) {
	if err := os.MkdirAll(dir, 0755); err != nil {
		return nil, err
	}

	s := &Storage{
		dir:         dir,
		collections: make(map[string]models.Collection),
		requests:    make(map[string]models.RequestData),
		history:     make([]models.HistoryRecord, 0),
	}

	s.load()
	return s, nil
}

func (s *Storage) getCollectionsFile() string {
	return filepath.Join(s.dir, "collections.json")
}

func (s *Storage) getRequestsFile() string {
	return filepath.Join(s.dir, "requests.json")
}

func (s *Storage) getHistoryFile() string {
	return filepath.Join(s.dir, "history.json")
}

func (s *Storage) load() {
	s.mu.Lock()
	defer s.mu.Unlock()

	// 载入 Collections
	if data, err := os.ReadFile(s.getCollectionsFile()); err == nil {
		var list []models.Collection
		if err := json.Unmarshal(data, &list); err == nil {
			for _, c := range list {
				s.collections[c.ID] = c
			}
		}
	}

	// 载入 Requests
	if data, err := os.ReadFile(s.getRequestsFile()); err == nil {
		var list []models.RequestData
		if err := json.Unmarshal(data, &list); err == nil {
			for _, r := range list {
				s.requests[r.ID] = r
			}
		}
	}

	// 载入 History
	if data, err := os.ReadFile(s.getHistoryFile()); err == nil {
		var list []models.HistoryRecord
		if err := json.Unmarshal(data, &list); err == nil {
			s.history = list
		}
	}
}

func (s *Storage) saveCollections() error {
	list := make([]models.Collection, 0, len(s.collections))
	for _, c := range s.collections {
		list = append(list, c)
	}
	data, err := json.MarshalIndent(list, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(s.getCollectionsFile(), data, 0644)
}

func (s *Storage) saveRequests() error {
	list := make([]models.RequestData, 0, len(s.requests))
	for _, r := range s.requests {
		list = append(list, r)
	}
	data, err := json.MarshalIndent(list, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(s.getRequestsFile(), data, 0644)
}

func (s *Storage) saveHistory() error {
	data, err := json.MarshalIndent(s.history, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(s.getHistoryFile(), data, 0644)
}

// ─── Collection CRUD ─────────────────────────────────────────

func (s *Storage) SaveCollection(c models.Collection) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	if c.CreatedAt.IsZero() {
		c.CreatedAt = time.Now()
	}
	c.UpdatedAt = time.Now()

	s.collections[c.ID] = c
	return s.saveCollections()
}

func (s *Storage) RenameCollection(id, newName string) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	if c, exists := s.collections[id]; exists {
		c.Name = newName
		c.UpdatedAt = time.Now()
		s.collections[id] = c
		return s.saveCollections()
	}
	return nil
}

func (s *Storage) DeleteCollection(id string) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	delete(s.collections, id)
	// 级联删除子请求
	for reqID, req := range s.requests {
		if req.CollectionID == id {
			delete(s.requests, reqID)
		}
	}
	_ = s.saveRequests()
	return s.saveCollections()
}

func (s *Storage) GetAllCollections() []models.Collection {
	s.mu.RLock()
	defer s.mu.RUnlock()

	list := make([]models.Collection, 0, len(s.collections))
	for _, c := range s.collections {
		list = append(list, c)
	}
	sort.Slice(list, func(i, j int) bool {
		return list[i].SortOrder < list[j].SortOrder
	})
	return list
}

// ─── Request CRUD ────────────────────────────────────────────

func (s *Storage) SaveRequest(r models.RequestData) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	if r.CreatedAt.IsZero() {
		r.CreatedAt = time.Now()
	}
	r.UpdatedAt = time.Now()

	s.requests[r.ID] = r
	return s.saveRequests()
}

func (s *Storage) GetRequest(id string) (models.RequestData, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	r, ok := s.requests[id]
	return r, ok
}

func (s *Storage) DeleteRequest(id string) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	delete(s.requests, id)
	return s.saveRequests()
}

func (s *Storage) GetRequestsByCollection(collectionID string) []models.RequestData {
	s.mu.RLock()
	defer s.mu.RUnlock()

	list := make([]models.RequestData, 0)
	for _, r := range s.requests {
		if r.CollectionID == collectionID {
			list = append(list, r)
		}
	}
	sort.Slice(list, func(i, j int) bool {
		return list[i].SortOrder < list[j].SortOrder
	})
	return list
}

// ─── History ─────────────────────────────────────────────────

func (s *Storage) AddHistory(h models.HistoryRecord) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	if h.CreatedAt.IsZero() {
		h.CreatedAt = time.Now()
	}

	// 插入到最前面
	s.history = append([]models.HistoryRecord{h}, s.history...)

	// 最多保留 500 条
	if len(s.history) > 500 {
		s.history = s.history[:500]
	}

	return s.saveHistory()
}

func (s *Storage) GetHistory() []models.HistoryRecord {
	s.mu.RLock()
	defer s.mu.RUnlock()

	res := make([]models.HistoryRecord, len(s.history))
	copy(res, s.history)
	return res
}

func (s *Storage) ClearHistory() error {
	s.mu.Lock()
	defer s.mu.Unlock()

	s.history = make([]models.HistoryRecord, 0)
	return s.saveHistory()
}
