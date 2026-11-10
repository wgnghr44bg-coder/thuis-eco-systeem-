"""Het plan voor het huidige uur doorzetten naar Home Assistant (REST API)."""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone

from .config import Config
from .planner import Plan, PlanUur


class HomeAssistantClient:
    def __init__(self, url: str, token: str, droog: bool = False):
        self.url = url.rstrip("/")
        self.token = token
        self.droog = droog
        self.log: list[tuple[str, dict]] = []

    def _post(self, pad: str, data: dict) -> None:
        self.log.append((pad, data))
        if self.droog:
            return
        req = urllib.request.Request(
            f"{self.url}{pad}", data=json.dumps(data).encode(), method="POST",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15):
            pass

    def dienst(self, domein: str, dienst: str, **data) -> None:
        self._post(f"/api/services/{domein}/{dienst}", data)

    def zet_status(self, entity_id: str, status: str, attributen: dict) -> None:
        self._post(f"/api/states/{entity_id}", {"state": status, "attributes": attributen})


def huidig_uur(plan: Plan, nu: datetime | None = None) -> PlanUur | None:
    nu = (nu or datetime.now(timezone.utc)).replace(minute=0, second=0, microsecond=0)
    for u in plan.uren:
        if u.tijd == nu:
            return u
    return plan.uren[0] if plan.uren else None


def stuur(cfg: Config, plan: Plan, droog: bool = False, nu: datetime | None = None) -> HomeAssistantClient:
    ha = cfg.homeassistant
    token = os.environ.get(ha.token_env, "")
    if not token and not droog:
        raise SystemExit(f"Geen Home Assistant token gevonden in ${ha.token_env}")
    client = HomeAssistantClient(ha.url, token, droog)
    u = huidig_uur(plan, nu)
    if u is None:
        return client

    # 1. Batterijstand (een HA-automatisering vertaalt dit naar jullie omvormer)
    client.dienst("input_select", "select_option",
                  entity_id=ha.batterij_modus_entity, option=u.batterij.modus)

    # 2. Airco's
    for a in u.warmte.aircos:
        if a.modus == "off":
            client.dienst("climate", "set_hvac_mode", entity_id=a.entity, hvac_mode="off")
        else:
            client.dienst("climate", "set_temperature", entity_id=a.entity,
                          hvac_mode=a.modus, temperature=round(a.setpoint * 2) / 2)

    # 3. CV-thermostaat
    client.dienst("climate", "set_temperature", entity_id=cfg.cv.thermostaat_entity,
                  temperature=round(u.warmte.cv_setpoint * 2) / 2)

    # 4. Het volledige plan als sensor (voor dashboards en grafieken)
    client.zet_status(ha.plan_sensor, f"{u.inkoop:.3f}", {
        "unit_of_measurement": "€/kWh",
        "friendly_name": "Energieplan",
        "warmtebron": u.warmte.bron,
        "batterij_modus": u.batterij.modus,
        "verwachte_besparing_eur": round(plan.besparing, 2),
        "gasprijs_m3": round(plan.gasprijs_m3, 3),
        "plan": [{
            "tijd": p.lokale_tijd.isoformat(),
            "prijs": round(p.inkoop, 3),
            "bron": p.warmte.bron,
            "batterij": p.batterij.modus,
            "soc_kwh": round(p.batterij.soc_eind, 2),
        } for p in plan.uren],
    })
    return client
