"""测试 cURL 解析功能"""

import sys
sys.path.insert(0, 'C:/Users/18335/PycharmProjects/postManage')

from app.core.importer import parse_curl


def test_bearer_token():
    """测试 Bearer Token 认证"""
    curl_cmd = """curl --location 'http://127.0.0.1:8080/system/nl-query/select-plan' \\
--header 'authorization: Bearer eyJhbGciOiJIUzUxMiJ9.eyJzdWIiOiJhZG1pbiIsImxvZ2luX3VzZXJfa2V5IjoiMTkwY2FiMjYtODdkYi00OGFiLWFhYzEtMjJmY2E4YzlhMDAwIn0.eIXfnsM4Wrv6oQKysgWUv0OqZ4frm-2DRmd60-7CW7Hlcw6YmClVvxAwQNUyu5-H4Ulzh1A4ERLSzP8otrR9sA' \\
--header 'Content-Type: application/json' \\
--data '{
  "queryId": 24,
  "selectedPlans": [1, 2]
}'"""
    
    req = parse_curl(curl_cmd)
    
    print("=" * 60)
    print("cURL 解析结果")
    print("=" * 60)
    print(f"Method: {req.method}")
    print(f"URL: {req.url}")
    print(f"\nHeaders ({len(req.headers)}):")
    for h in req.headers:
        print(f"  {h.key}: {h.value[:50]}{'...' if len(h.value) > 50 else ''}")
    
    print(f"\nParams ({len(req.params)}):")
    for p in req.params:
        print(f"  {p.key}={p.value}")
    
    print(f"\nBody Type: {req.body_type}")
    print(f"Body Content:")
    print(f"  {req.body_content[:200]}{'...' if len(req.body_content) > 200 else ''}")
    
    print(f"\nAuth Type: {req.auth_type}")
    print(f"Auth Config: {req.auth_config}")
    print(f"Timeout: {req.timeout}ms")
    print("=" * 60)
    
    # 验证
    assert req.method == "POST", f"Expected POST, got {req.method}"
    assert req.url == "http://127.0.0.1:8080/system/nl-query/select-plan", f"URL mismatch: {req.url}"
    
    # 检查 headers
    auth_header = next((h for h in req.headers if h.key.lower() == "authorization"), None)
    assert auth_header is not None, "Authorization header not found"
    assert "Bearer" in auth_header.value, f"Bearer token not in header: {auth_header.value}"
    
    content_type_header = next((h for h in req.headers if h.key.lower() == "content-type"), None)
    assert content_type_header is not None, "Content-Type header not found"
    assert content_type_header.value == "application/json", f"Wrong Content-Type: {content_type_header.value}"
    
    # 检查 body
    assert req.body_type == "json", f"Expected json body type, got {req.body_type}"
    assert '"queryId"' in req.body_content, "queryId not in body"
    assert '"selectedPlans"' in req.body_content, "selectedPlans not in body"
    
    print("\n✅ All assertions passed!")


if __name__ == "__main__":
    test_bearer_token()
