"""全模块导入测试"""
import sys
sys.path.insert(0, ".")

try:
    from app.config.constants import APP_NAME
    print(f"[OK] constants")

    from app.config.settings import Settings
    s = Settings()
    print(f"[OK] settings: theme={s.theme}")

    from app.config.themes import ThemeManager, LightTheme, DarkTheme
    ThemeManager.set_theme("light")
    print(f"[OK] themes")

    from app.core.models import Collection, SavedRequest, HistoryRecord, HTTPResponse
    print(f"[OK] models")

    from app.core.db import Database
    db = Database()
    print(f"[OK] db")

    from app.core.http_client import HTTPClient
    client = HTTPClient()
    print(f"[OK] http_client")

    from app.core.exporter import export_collection, import_collection
    print(f"[OK] exporter (PostManage + Postman)")

    from app.core.importer import parse_curl
    # 测试 cURL 解析
    req = parse_curl('curl -X POST https://api.example.com/users -H "Content-Type: application/json" -d \'{"name":"test"}\'')
    assert req.method == "POST"
    assert req.url == "https://api.example.com/users"
    assert req.body_type == "json"
    print(f"[OK] importer (cURL parser): method={req.method}, url={req.url}")

    # 测试主题切换
    ThemeManager.toggle()
    assert ThemeManager.current().name == "dark"
    ThemeManager.toggle()
    assert ThemeManager.current().name == "light"
    print(f"[OK] theme toggle")

    print("\n=== All modules imported and tested successfully! ===")
except Exception as e:
    print(f"[ERROR] {e}")
    import traceback
    traceback.print_exc()
