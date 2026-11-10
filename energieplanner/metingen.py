"""Echte meetwaarden uit de clouds van Growatt (zonnepanelen) en Anker (batterij).

Gebruikt dezelfde inlog als de apps. De gegevens komen uit omgevingsvariabelen
(in GitHub: repository secrets), nooit uit bestanden in de repository.

    GROWATT_USERNAME / GROWATT_PASSWORD   inlog van de ShinePhone/Growatt-app
    GROWATT_TOKEN                         (optioneel) API-token i.p.v. wachtwoord
    ANKER_USERNAME / ANKER_PASSWORD       inlog van de Anker-app
    ANKER_COUNTRY                         landcode, standaard "NL"

Elke bron faalt los en netjes: een fout bij Growatt houdt Anker niet tegen,
en zonder inlog wordt een bron gewoon als "niet gekoppeld" gemeld.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone

log = logging.getLogger("energieplanner.metingen")


def _getal(waarde, standaard_eenheid: str = "") -> tuple[float | None, str]:
    """'1.2 kW' -> (1.2, 'kw'); '620' -> (620.0, standaard_eenheid)."""
    if waarde is None:
        return None, ""
    if isinstance(waarde, (int, float)):
        return float(waarde), standaard_eenheid
    m = re.search(r"(-?\d+(?:[.,]\d+)?)\s*([a-zA-Z%]*)", str(waarde))
    if not m:
        return None, ""
    return float(m.group(1).replace(",", ".")), (m.group(2) or standaard_eenheid).lower()


def _naar_kw(waarde, standaard_eenheid: str = "kw") -> float | None:
    getal, eenheid = _getal(waarde, standaard_eenheid)
    if getal is None:
        return None
    return getal / 1000 if eenheid == "w" else getal


def _vermogen_kw(waarde) -> float | None:
    """Zonnevermogen naar kW, ook als de eenheid ontbreekt.

    Growatt geeft het vermogen soms als kale waarde in kW (0.478), soms in W
    (478). Een huisinstallatie levert nooit meer dan ~20 kW, dus een kaal getal
    boven 20 is watt.
    """
    getal, eenheid = _getal(waarde)
    if getal is None:
        return None
    if eenheid == "w" or (eenheid == "" and getal > 20):
        return getal / 1000
    return getal


def _dagcurve(api, plant_id) -> list[dict]:
    """5-minutencurve van vandaag als [{"tijd": "HH:MM", "kw": 0.48}, ...]."""
    try:
        curve = api.plant_power_overview(plant_id)
    except Exception as e:
        log.info("Growatt dagcurve niet beschikbaar: %s", type(e).__name__)
        return []
    punten = curve.get("powers", curve.get("data", [])) if isinstance(curve, dict) else curve
    ruw = []
    for p in punten or []:
        v = p.get("power") if isinstance(p, dict) else p
        getal, _ = _getal(v)
        if getal is None:
            continue
        tijd = str(p.get("time", "")) if isinstance(p, dict) else ""
        m = re.search(r"(\d{1,2}):(\d{2})", tijd)
        ruw.append((f"{int(m.group(1)):02d}:{m.group(2)}" if m else "", getal))
    if not ruw:
        log.info("Growatt dagcurve: geen punten")
        return []
    # Eenheid bepalen aan de hand van de hele curve: boven 20 is het watt.
    deler = 1000 if max(v for _, v in ruw) > 20 else 1
    log.info("Growatt dagcurve: %d punten, laatste %r", len(ruw), ruw[-1][1])
    return [{"tijd": t, "kw": round(v / deler, 3)} for t, v in ruw]


def _laatste_vermogen(api, plant_id) -> float | None:
    """Laatste gemeten vermogen (kW) uit de 5-minutencurve van vandaag."""
    curve = _dagcurve(api, plant_id)
    return curve[-1]["kw"] if curve else None


def _naar_kwh(waarde, standaard_eenheid: str = "kwh") -> float | None:
    getal, eenheid = _getal(waarde, standaard_eenheid)
    if getal is None:
        return None
    return getal / 1000 if eenheid == "wh" else getal


def _zoek(d: dict, *sleutels):
    for s in sleutels:
        if s in d and d[s] not in (None, ""):
            return d[s]
    return None


def _fout(e: Exception) -> str:
    """Korte foutmelding zonder inloggegevens of serienummers."""
    tekst = f"{type(e).__name__}: {e}"
    for var in ("GROWATT_USERNAME", "GROWATT_PASSWORD", "GROWATT_TOKEN", "ANKER_USERNAME", "ANKER_PASSWORD"):
        if os.environ.get(var):
            tekst = tekst.replace(os.environ[var], "***")
    return tekst[:200]


# --------------------------------------------------------------------- Growatt

def lees_growatt() -> dict:
    gebruiker = os.environ.get("GROWATT_USERNAME")
    wachtwoord = os.environ.get("GROWATT_PASSWORD")
    token = os.environ.get("GROWATT_TOKEN")
    if not (token or (gebruiker and wachtwoord)):
        return {"status": "niet_gekoppeld"}
    try:
        import growattServer  # pip install growattServer
    except ImportError:
        return {"status": "fout", "fout": "pakket growattServer niet geïnstalleerd"}

    curve: list[dict] = []
    try:
        if token:
            api = growattServer.OpenApiV1(token=token)
            plants = api.plant_list()
            lijst = plants.get("plants", plants.get("data", [])) if isinstance(plants, dict) else plants
            plant_id = lijst[0].get("plant_id") or lijst[0].get("plantId")
            o = api.plant_energy_overview(plant_id)
            log.info("Growatt overview-velden: %s", sorted(o.keys()))
            ruw = _zoek(o, "current_power", "currentPower")
            log.info("Growatt current_power ruw: %r", ruw)
            nu = _vermogen_kw(ruw)
            # current_power wordt door Growatt vaak niet live bijgewerkt (0).
            # Neem dan het laatste punt uit de dagcurve (zoals de grafiek in de app).
            curve = _dagcurve(api, plant_id) if hasattr(api, "plant_power_overview") else []
            if not nu and curve:
                nu = curve[-1]["kw"]
            vandaag = _naar_kwh(_zoek(o, "today_energy", "todayEnergy"))
        else:
            api = growattServer.GrowattApi(add_random_user_id=True)
            login = api.login(gebruiker, wachtwoord)
            if not login.get("success", True) or "user" not in login:
                return {"status": "fout", "fout": "inloggen bij Growatt mislukt (controleer gebruikersnaam/wachtwoord)"}
            plants = api.plant_list(login["user"]["id"])
            p = plants["data"][0]
            log.info("Growatt plant-velden: %s", sorted(p.keys()))
            nu = _naar_kw(_zoek(p, "currentPower", "current_power"))
            vandaag = _naar_kwh(_zoek(p, "todayEnergy", "today_energy"))
    except Exception as e:  # netwerk, gewijzigde API, geen installatie gevonden
        return {"status": "fout", "fout": _fout(e)}

    uit = {"status": "ok", "zon_kw": nu, "zon_vandaag_kwh": vandaag}
    if curve:
        uit["curve"] = curve
    return uit


# ----------------------------------------------------------------------- Anker

def _anker_module():
    """De Anker Solix API (github.com/thomluther/anker-solix-api).

    De workflow kloont die repository naar `vendor/anker-solix-api`; we voegen
    die map toe aan het zoekpad.
    """
    import sys
    pad = os.environ.get("ANKER_API_PAD", os.path.join(os.path.dirname(__file__), "..", "vendor", "anker-solix-api"))
    if os.path.isdir(pad) and pad not in sys.path:
        sys.path.insert(0, os.path.abspath(pad))
    from api import api  # type: ignore
    return api


async def _anker_async(gebruiker: str, wachtwoord: str, land: str) -> dict:
    from aiohttp import ClientSession
    api = _anker_module()
    async with ClientSession() as sessie:
        a = api.AnkerSolixApi(gebruiker, wachtwoord, land, sessie, log)
        await a.update_sites()
        try:
            await a.update_device_details()
        except Exception as e:  # niet elk model ondersteunt alle details
            log.info("Anker device details niet beschikbaar: %s", type(e).__name__)
        apparaten = list(getattr(a, "devices", {}).values())
        sites = list(getattr(a, "sites", {}).values())

    # Kies het apparaat met een batterij-percentage
    batterij = None
    for d in apparaten:
        if _zoek(d, "battery_soc", "soc", "battery_percentage") is not None:
            batterij = d
            break
    if batterij is None:
        log.info("Anker: %d apparaten, %d sites; geen batterijpercentage gevonden", len(apparaten), len(sites))
        for d in apparaten:
            log.info("Anker apparaat-velden: %s", sorted(d.keys()))
        # Terugval: sommige systemen geven de lading op site-niveau (0-1)
        for s in sites:
            info = s.get("solarbank_info", {}) if isinstance(s, dict) else {}
            totaal = _zoek(info, "total_battery_power")
            if totaal is not None:
                soc, _ = _getal(totaal)
                return {"status": "ok", "soc": soc if soc <= 1 else soc / 100}
        return {"status": "fout", "fout": "geen batterij gevonden in het Anker-account"}

    log.info("Anker batterij-velden: %s", sorted(batterij.keys()))
    soc, _ = _getal(_zoek(batterij, "battery_soc", "soc", "battery_percentage"))
    laden = _naar_kw(_zoek(batterij, "bat_charge_power", "charging_power"), "w")
    ontladen = _naar_kw(_zoek(batterij, "bat_discharge_power", "discharging_power"), "w")
    naar_huis = _naar_kw(_zoek(batterij, "output_power", "home_load_power"), "w")
    return {
        "status": "ok",
        "soc": None if soc is None else (soc / 100 if soc > 1 else soc),
        "laden_kw": laden,
        "ontladen_kw": ontladen,
        "naar_huis_kw": naar_huis,
        "model": batterij.get("device_pn") or batterij.get("type"),
    }


def lees_anker() -> dict:
    gebruiker = os.environ.get("ANKER_USERNAME")
    wachtwoord = os.environ.get("ANKER_PASSWORD")
    if not (gebruiker and wachtwoord):
        return {"status": "niet_gekoppeld"}
    try:
        return asyncio.run(_anker_async(gebruiker, wachtwoord, os.environ.get("ANKER_COUNTRY", "NL")))
    except ImportError as e:
        return {"status": "fout", "fout": f"Anker-API niet geïnstalleerd ({e.name})"}
    except Exception as e:
        return {"status": "fout", "fout": _fout(e)}


def lees_alles() -> dict:
    return {
        "tijd": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "growatt": lees_growatt(),
        "anker": lees_anker(),
    }
