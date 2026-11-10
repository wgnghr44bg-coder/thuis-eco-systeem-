"""Combineert prijzen, weer, warmte en batterij tot één uurplan voor het huis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .batterij import BatterijUur, plan_batterij
from .bronnen import Uur
from .config import Config
from .warmte import GAS_KWH_PER_M3, WarmteUur, plan_warmte


@dataclass
class PlanUur:
    tijd: datetime              # UTC
    lokale_tijd: datetime
    kale_prijs: float
    inkoop: float               # all-in €/kWh
    teruglever: float           # €/kWh
    buitentemp: float
    zon_kw: float
    verbruik_kw: float          # basis + airco's
    warmte: WarmteUur
    batterij: BatterijUur


@dataclass
class Plan:
    uren: list[PlanUur]
    gasprijs_m3: float
    kosten_plan: float          # stroom + gas met slimme sturing
    kosten_referentie: float    # alles op CV, batterij alleen zelfconsumptie

    @property
    def besparing(self) -> float:
        return self.kosten_referentie - self.kosten_plan


def zon_vermogen(cfg: Config, straling: float) -> float:
    return cfg.zonnepanelen.vermogen_kwp * straling / 1000 * cfg.zonnepanelen.prestatieratio


def maak_plan(cfg: Config, uren: list[Uur], start_soc: float, gasprijs_m3: float) -> Plan:
    """`start_soc` als fractie (0–1) van de batterijcapaciteit."""
    tz = ZoneInfo(cfg.tijdzone)
    lokaal = [u.tijd.astimezone(tz) for u in uren]
    inkoop = [cfg.tarieven.stroom_allin(u.kale_prijs) for u in uren]
    terug = [cfg.tarieven.stroom_teruglever(u.kale_prijs, lt.date()) for u, lt in zip(uren, lokaal)]
    zon = [zon_vermogen(cfg, u.straling) for u in uren]

    warmte = plan_warmte(cfg, [lt.hour for lt in lokaal], [u.buitentemp for u in uren], inkoop, gasprijs_m3)
    verbruik = [cfg.huis.basisverbruik_kw + w.stroom_kw for w in warmte]
    bat = plan_batterij(cfg.batterij, start_soc * cfg.batterij.capaciteit_kwh, verbruik, zon, inkoop, terug)

    kosten = sum(b.kosten for b in bat) + sum(w.gas_m3 for w in warmte) * gasprijs_m3
    referentie = _referentiekosten(cfg, uren, warmte, zon, inkoop, terug, start_soc, gasprijs_m3)

    plan_uren = [PlanUur(u.tijd, lt, u.kale_prijs, i, t, u.buitentemp, z, v, w, b)
                 for u, lt, i, t, z, v, w, b in zip(uren, lokaal, inkoop, terug, zon, verbruik, warmte, bat)]
    return Plan(plan_uren, gasprijs_m3, kosten, referentie)


def _referentiekosten(cfg, uren, warmte, zon, inkoop, terug, start_soc, gasprijs) -> float:
    """Wat het zou kosten zonder slimme sturing: CV levert alle warmte en de
    batterij doet alleen 'dom' zelfconsumptie (zonne-overschot opslaan)."""
    bat = cfg.batterij
    soc = start_soc * bat.capaciteit_kwh
    eta = bat.rendement_rondgang ** 0.5
    kosten = 0.0
    for w, z, i, t in zip(warmte, zon, inkoop, terug):
        rest = cfg.huis.basisverbruik_kw - z
        if rest < 0:
            laad = min(-rest, bat.max_laadvermogen_kw, (bat.max_soc * bat.capaciteit_kwh - soc) / eta)
            soc += laad * eta
            rest += laad
        else:
            ontlaad = min(rest, bat.max_ontlaadvermogen_kw, (soc - bat.min_soc * bat.capaciteit_kwh) * eta)
            ontlaad = max(0.0, ontlaad)
            soc -= ontlaad / eta
            rest -= ontlaad
        kosten += rest * i if rest >= 0 else rest * t
        kosten += w.warmtevraag_kw / (GAS_KWH_PER_M3 * cfg.cv.ketelrendement) * gasprijs
    return kosten


def plan_naar_dict(cfg: Config, plan: Plan, bron: str = "live", soc_bron: str = "aanname") -> dict:
    """Plan als eenvoudige data voor de website (bevat geen locatie of tokens)."""
    return {
        "gemaakt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bron": bron,
        "soc_bron": soc_bron,
        "gasprijs_m3": round(plan.gasprijs_m3, 3),
        "kosten_plan": round(plan.kosten_plan, 2),
        "kosten_referentie": round(plan.kosten_referentie, 2),
        "besparing": round(plan.besparing, 2),
        "batterij_capaciteit_kwh": cfg.batterij.capaciteit_kwh,
        "uren": [{
            "tijd": u.tijd.isoformat(),
            "prijs": round(u.inkoop, 4),
            "teruglever": round(u.teruglever, 4),
            "buitentemp": round(u.buitentemp, 1),
            "zon_kw": round(u.zon_kw, 2),
            "verbruik_kw": round(u.verbruik_kw, 2),
            "warmtevraag_kw": round(u.warmte.warmtevraag_kw, 2),
            "warmtebron": u.warmte.bron,
            "cv_setpoint": round(u.warmte.cv_setpoint, 1),
            "gas_m3": round(u.warmte.gas_m3, 3),
            "aircos": [{"naam": a.naam, "modus": a.modus,
                        "setpoint": None if a.setpoint is None else round(a.setpoint, 1),
                        "cop": round(a.cop, 2)} for a in u.warmte.aircos],
            "batterij_modus": u.batterij.modus,
            "batterij_kw": round(u.batterij.batterij_kw, 2),
            "soc_kwh": round(u.batterij.soc_eind, 2),
            "net_kw": round(u.batterij.net_kw, 2),
            "kosten": round(u.batterij.kosten + u.warmte.gas_m3 * plan.gasprijs_m3, 4),
            "reden": u.warmte.reden,
        } for u in plan.uren],
    }
