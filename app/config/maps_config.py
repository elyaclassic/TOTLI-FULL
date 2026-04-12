"""
Xarita konfiguratsiyasi
Map configuration for switching between providers
"""
import os

# Xarita provayderi: 'yandex' yoki 'google'
# Map provider: 'yandex' or 'google'
MAP_PROVIDER = os.getenv('MAP_PROVIDER', 'yandex')

# Yandex Maps API Key (https://developer.tech.yandex.ru/ — bepul kalit olish mumkin)
YANDEX_MAPS_API_KEY = os.getenv('YANDEX_MAPS_API_KEY', '')

# Google Maps API Key (faqat MAP_PROVIDER='google' bo'lganda kerak)
# Google Maps API Key (only needed when MAP_PROVIDER='google')
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY', '')

# Default xarita markazi (Toshkent)
# Default map center (Tashkent)
DEFAULT_CENTER = {
    'latitude': 41.311081,
    'longitude': 69.240562,
    'zoom': 12
}

# Marker ranglari
# Marker colors
MARKER_COLORS = {
    'agent': '#0d6efd',      # Ko'k / Blue
    'driver': '#0dcaf0',     # Moviy / Cyan
    'partner': '#198754'     # Yashil / Green
}
