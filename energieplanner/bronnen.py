"""Ophalen van dynamische prijzen (EnergyZero) en weersverwachting (Open-Meteo).

Beide API's zijn gratis en hebben geen sleutel nodig. Er is ook een demo-bron
met realistische nep-data, zodat alles zonder internet te testen is.
"""

from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

ENERGYZERO_URL = "https://api.energyzero.nl/v1/energyprices"
OPENMETEO_URL = "https://api.open-meteo.com/v1/forecast"


@dataclass
class Uur:
    """Invoer voor één uur (tijd in UTC, begin van het uur)."""

    tijd: datetime
    kale_prijs: float          # €/kWh excl. btw (day-ahead)
    buitentemp: float          # °C
    straling: float            # W/m² (globale horizontale straling)


def _get_json(url: str, params: dict, timeout: float = 15) -> dict:
    volledige_url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(volledige_url, headers={"User-Agent": "energieplanner/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _parse_tijd(s: str) -> datetime:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def middel_per_uur(prijzen: list[tuple[datetime, float]]) -> dict[datetime, float]:
    """Kwartierprijzen (of uurprijzen) middelen naar hele uren."""
    groepen: dict[datetime, list[float]] = defaultdict(list)
    for tijd, prijs in prijzen:
        groepen[tijd.replace(minute=0, second=0, microsecond=0)].append(prijs)
    return {t: sum(v) / len(v) for t, v in sorted(groepen.items())}


def haal_stroomprijzen(van: datetime, tot: datetime) -> dict[datetime, float]:
    data = _get_json(ENERGYZERO_URL, {
        "fromDate": _iso(van), "tillDate": _iso(tot),
        "interval": 4, "usageType": 1, "inclBtw": "false",
    })
    return middel_per_uur([(_parse_tijd(p["readingDate"]), float(p["price"])) for p in data["Prices"]])


def haal_gasprijs(dag: datetime) -> float | None:
    """Kale gasprijs (€/m³ excl. btw) van vandaag, of None als niet beschikbaar."""
    try:
        data = _get_json(ENERGYZERO_URL, {
            "fromDate": _iso(dag), "tillDate": _iso(dag + timedelta(days=1)),
            "interval": 4, "usageType": 3, "inclBtw": "false",
        })
        prijzen = [float(p["price"]) for p in data.get("Prices", [])]
        return sum(prijzen) / len(prijzen) if prijzen else None
    except Exception:
        return None


def haal_weer(lat: float, lon: float) -> dict[datetime, tuple[float, float]]:
    data = _get_json(OPENMETEO_URL, {
        "latitude": lat, "longitude": lon,
        "hourly": "temperature_2m,shortwave_radiation",
        "forecast_days": 3, "timezone": "UTC",
    })
    h = data["hourly"]
    uit = {}
    for t, temp, straling in zip(h["time"], h["temperature_2m"], h["shortwave_radiation"]):
        uit[_parse_tijd(t)] = (float(temp), float(straling or 0.0))
    return uit


def combineer(prijzen: dict[datetime, float], weer: dict[datetime, tuple[float, float]],
              vanaf: datetime) -> list[Uur]:
    """Alleen uren waarvoor een prijs bekend is (meestal tot morgen 24:00)."""
    uren = []
    laatste_weer = (10.0, 0.0)
    for tijd in sorted(prijzen):
        if tijd < vanaf:
            continue
        temp, straling = weer.get(tijd, laatste_weer)
        laatste_weer = (temp, straling)
        uren.append(Uur(tijd, prijzen[tijd], temp, straling))
    return uren


def demo_uren(start: datetime, aantal: int = 36, basistemp: float = 6.0) -> list[Uur]:
    """Realistische nep-data voor een Nederlandse novemberdag."""
    uren = []
    for i in range(aantal):
        t = start + timedelta(hours=i)
        uur = (t.hour + 1) % 24  # ruwweg lokale tijd (CET)
        # Prijsprofiel: goedkoop 's nachts en rond het middaguur, duur in de avondpiek
        prijs = 0.09
        prijs += 0.06 * math.exp(-((uur - 8) ** 2) / 4)
        prijs += 0.12 * math.exp(-((uur - 18.5) ** 2) / 5)
        prijs -= 0.04 * math.exp(-((uur - 3.5) ** 2) / 6)
        prijs -= 0.02 * math.exp(-((uur - 13) ** 2) / 4)
        temp = basistemp + 3.5 * math.sin((uur - 9) / 24 * 2 * math.pi)
        straling = max(0.0, 300 * math.sin((uur - 8) / 9 * math.pi)) if 8 <= uur <= 17 else 0.0
        uren.append(Uur(t, round(prijs, 4), round(temp, 1), round(straling)))
    return uren
