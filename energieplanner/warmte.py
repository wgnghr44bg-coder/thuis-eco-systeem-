"""Warmte: wanneer verwarmt de airco (warmtepomp) goedkoper dan de CV-ketel?

Kern van de afweging per uur:

    kosten airco per kWh warmte = stroomprijs / COP(buitentemperatuur)
    kosten CV    per kWh warmte = gasprijs / (9,77 kWh/m³ × ketelrendement)

Met gas rond €1,35/m³ kost CV-warmte ~€0,15/kWh. Een airco met COP 4 is dus
goedkoper zolang stroom onder ~€0,60/kWh blijft – met een dynamisch contract
vrijwel altijd, behalve in extreme piekuren of bij strenge vorst.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import Airco, Config

GAS_KWH_PER_M3 = 9.769  # bovenwaarde Gronings-kwaliteit aardgas


def cop(airco: Airco, buitentemp: float) -> float:
    """Eenvoudig COP-model voor een lucht-lucht warmtepomp.

    Ongeveer 2,5% COP-verlies per graad kouder, plus een ontdooiverlies
    tussen -3 en 5 °C (rijp op de buitenunit bij hoge luchtvochtigheid).
    """
    waarde = airco.cop_7c * (1 + 0.025 * (buitentemp - 7))
    if -3 <= buitentemp <= 5:
        waarde *= 0.92
    return max(1.5, min(waarde, airco.cop_7c * 1.4))


def eer(airco: Airco, buitentemp: float) -> float:
    """Koelrendement: ongeveer gelijk aan de COP bij 7 °C rond 27 °C buiten, daarna lager."""
    return max(1.5, airco.cop_7c * (1 - 0.03 * (buitentemp - 27)))


def gaskosten_per_kwh_warmte(gasprijs_m3: float, ketelrendement: float) -> float:
    return gasprijs_m3 / (GAS_KWH_PER_M3 * ketelrendement)


@dataclass
class AircoActie:
    naam: str
    entity: str
    modus: str                  # "heat", "cool" of "off"
    setpoint: float | None
    warmte_kw: float            # geleverde warmte (of koude)
    stroom_kw: float            # opgenomen elektrisch vermogen
    cop: float


@dataclass
class WarmteUur:
    warmtevraag_kw: float
    bron: str                   # "airco", "cv", "koelen" of "geen"
    cv_setpoint: float
    stroom_kw: float            # totaal elektrisch vermogen van de airco's
    gas_m3: float
    aircos: list[AircoActie] = field(default_factory=list)
    reden: str = ""


def prijsrang(prijzen: list[float]) -> list[float]:
    """Percentiel (0 = goedkoopste, 1 = duurste) van elk uur binnen de horizon."""
    if len(prijzen) <= 1:
        return [0.5] * len(prijzen)
    gesorteerd = sorted(prijzen)
    n = len(prijzen) - 1
    return [gesorteerd.index(p) / n for p in prijzen]


def plan_warmte(cfg: Config, uren_lokaal: list[int], buitentemps: list[float],
                stroomprijzen: list[float], gasprijs_m3: float) -> list[WarmteUur]:
    """Plan per uur welke bron verwarmt en met welk setpoint.

    `stroomprijzen` zijn all-in inkoopprijzen. Voorverwarmen gebeurt binnen
    `comfort_marge`: in de goedkoopste uren een iets hoger setpoint (het huis
    slaat warmte op in muren en vloeren), in de duurste uren iets lager.
    """
    huis, cv = cfg.huis, cfg.cv
    gas_kwh = gaskosten_per_kwh_warmte(gasprijs_m3, cv.ketelrendement)
    rang = prijsrang(stroomprijzen)
    plan: list[WarmteUur] = []

    for uur, temp, prijs, r in zip(uren_lokaal, buitentemps, stroomprijzen, rang):
        basis = huis.setpoint(uur)

        # --- Koelen (zomer) ---
        if temp >= huis.koelen_vanaf:
            acties = []
            for a in cfg.aircos:
                sp = huis.koel_temperatuur
                if r <= 0.25:
                    sp -= huis.comfort_marge      # voorkoelen als stroom goedkoop is
                elif r >= 0.75:
                    sp += huis.comfort_marge
                koude = min(a.max_warmte_kw,
                            huis.warmteverlies_w_per_k * max(0.0, temp - sp) / 1000 * a.dekking)
                c = eer(a, temp)
                acties.append(AircoActie(a.naam, a.entity, "cool", sp, koude, koude / c, c))
            plan.append(WarmteUur(0.0, "koelen", basis - 2, sum(x.stroom_kw for x in acties), 0.0,
                                  acties, "warm buiten: koelen, voorkoelen in goedkope uren"))
            continue

        vraag = max(0.0, huis.warmteverlies_w_per_k * (basis - temp) / 1000)
        if vraag <= 0.05:
            acties = [AircoActie(a.naam, a.entity, "off", None, 0, 0, cop(a, temp)) for a in cfg.aircos]
            plan.append(WarmteUur(vraag, "geen", basis, 0.0, 0.0, acties, "geen warmtevraag"))
            continue

        acties = []
        airco_warmte = 0.0
        stroom = 0.0
        redenen = []
        for a in cfg.aircos:
            c = cop(a, temp)
            airco_kwh = prijs / c
            if airco_kwh < gas_kwh:
                sp = basis
                if r <= 0.25 and _mag_voorverwarmen(huis, uur):
                    sp += huis.comfort_marge
                elif r >= 0.85:
                    sp -= huis.comfort_marge / 2
                factor = 1 + (sp - basis) / max(basis - temp, 1.0)  # meer/minder vermogen bij boost/eco
                warmte = min(a.max_warmte_kw, vraag * a.dekking * max(factor, 0.0))
                acties.append(AircoActie(a.naam, a.entity, "heat", sp, warmte, warmte / c, c))
                airco_warmte += warmte
                stroom += warmte / c
            else:
                acties.append(AircoActie(a.naam, a.entity, "off", None, 0.0, 0.0, c))
                redenen.append(f"{a.naam}: gas goedkoper ({airco_kwh:.3f} > {gas_kwh:.3f} €/kWh)")

        rest = max(0.0, vraag - airco_warmte)
        if airco_warmte > 0:
            bron = "airco"
            cv_sp = basis - cv.verlaging_bij_airco
            beste_cop = max(x.cop for x in acties if x.modus == "heat")
            redenen.insert(0, f"airco {prijs / beste_cop:.3f} €/kWh warmte vs gas {gas_kwh:.3f}")
        else:
            bron = "cv"
            cv_sp = basis
        gas = rest / (GAS_KWH_PER_M3 * cv.ketelrendement)
        plan.append(WarmteUur(vraag, bron, cv_sp, stroom, gas, acties, "; ".join(redenen)))
    return plan


def _mag_voorverwarmen(huis, uur: int) -> bool:
    """Overdag altijd; 's nachts alleen in de laatste 2 uur voor het opstaan."""
    if huis.setpoint(uur) == huis.dagtemperatuur:
        return True
    return (huis.nacht_tot - uur) % 24 <= 2
