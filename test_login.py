"""
Login endpointini test qilish
"""
import os
import requests

_test_pwd = os.getenv("TEST_ADMIN_PASSWORD")
if not _test_pwd:
    raise SystemExit("[XATO] TEST_ADMIN_PASSWORD .env da o'rnatilmagan!")

url = "http://10.243.45.144:8080/login"
data = {
    "username": "admin",
    "password": _test_pwd,
}

print("=" * 60)
print("LOGIN TEST")
print("=" * 60)
print(f"URL: {url}")
print(f"Data: {data}")
print()

try:
    response = requests.post(url, data=data, allow_redirects=False)
    print(f"Status Code: {response.status_code}")
    print(f"Headers: {dict(response.headers)}")
    print()
    
    if response.status_code == 303:
        print("✅ Login muvaffaqiyatli! Redirect qilinmoqda...")
        print(f"Location: {response.headers.get('Location')}")
        print(f"Cookies: {response.cookies}")
    else:
        print("❌ Login muvaffaqiyatsiz!")
        print(f"Response: {response.text[:500]}")
        
except Exception as e:
    print(f"❌ Xato: {e}")
