import requests
from typing import Tuple

COUNTRIES_API = "https://restcountries.com/v2/all?fields=name,capital,region,population,flag,currencies"
EXCHANGE_RATE_API = "https://open.er-api.com/v6/latest/USD"


def fetch_countries(timeout: int = 10) -> Tuple[bool, dict]:
    """Fetches countries from the external API.

    Returns (success, json) where success is False when request failed.
    """
    try:
        r = requests.get(COUNTRIES_API, timeout=timeout)
        r.raise_for_status()
        return True, r.json()
    except Exception as e:
        return False, {"error": str(e)}


def fetch_exchange_rates(timeout: int = 10) -> Tuple[bool, dict]:
    try:
        r = requests.get(EXCHANGE_RATE_API, timeout=timeout)
        r.raise_for_status()
        return True, r.json()
    except Exception as e:
        return False, {"error": str(e)}