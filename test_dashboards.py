import os
import requests

# Create session
s = requests.Session()

# Login
print("Logging in...")
_login_pwd = os.getenv("TEST_ADMIN_PASSWORD", "admin123")
login_response = s.post('http://localhost:8080/login', data={
    'username': 'admin',
    'password': _login_pwd
})
print(f"Login status: {login_response.status_code}")

# Test dashboards
dashboards = {
    'Executive': '/dashboard/executive',
    'Sales': '/dashboard/sales',
    'Warehouse': '/dashboard/warehouse',
    'Delivery': '/dashboard/delivery'
}

print("\nTesting dashboards:")
for name, url in dashboards.items():
    r = s.get(f'http://localhost:8080{url}')
    print(f"{name}: {r.status_code}")
