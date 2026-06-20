"""Geografik hisob-kitoblar (koordinatalar orasidagi masofa)."""
import math


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Ikki koordinata orasidagi havo masofasi (km), haversine formulasi.

    To'g'ri chiziq (qush parvozi) masofasi — real yo'ldan ~20-40% kam.
    """
    R = 6371.0  # Yer radiusi (km)
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))
