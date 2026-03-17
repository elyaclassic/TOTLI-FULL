"""
Login funksiyasini to'g'ridan-to'g'ri test qilish
"""
import os
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)
_test_pwd = os.getenv("TEST_ADMIN_PASSWORD")
if not _test_pwd:
    raise SystemExit("[XATO] TEST_ADMIN_PASSWORD .env da o'rnatilmagan!")

print("=" * 60)
print("LOGIN ENDPOINT TEST")
print("=" * 60)

# GET /login
print("\n1. GET /login:")
response = client.get("/login")
print(f"   Status: {response.status_code}")
print(f"   OK: {response.status_code == 200}")

# POST /login (noto'g'ri parol)
print("\n2. POST /login (noto'g'ri parol):")
response = client.post("/login", data={"username": "admin", "password": "wrong"}, follow_redirects=False)
print(f"   Status: {response.status_code}")
print(f"   Contains error: {'noto' in response.text}")

# POST /login (to'g'ri parol)
print("\n3. POST /login (to'g'ri parol):")
response = client.post("/login", data={"username": "admin", "password": _test_pwd}, follow_redirects=False)
print(f"   Status: {response.status_code}")
print(f"   Redirect: {response.status_code == 303}")
if response.status_code == 303:
    print(f"   Location: {response.headers.get('location')}")
    print(f"   Has cookie: {'session_token' in response.cookies}")
    print(f"   ✅ LOGIN ISHLAYAPTI!")
else:
    print(f"   ❌ LOGIN ISHLAMAYAPTI!")
    print(f"   Response: {response.text[:200]}")
