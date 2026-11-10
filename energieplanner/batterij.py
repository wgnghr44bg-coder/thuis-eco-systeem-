"""Optimale batterijplanning met dynamisch programmeren.

Voor elk uur kiest de planner hoeveel de batterij laadt of ontlaadt zodat de
totale stroomrekening (inclusief slijtagekosten) over de hele horizon minimaal
is. De laadtoestand (SoC) wordt opgedeeld in kleine stapjes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .config import Batterij


@dataclass
class BatterijUur:
    soc_begin: float            # kWh
    soc_eind: float             # kWh
    batterij_kw: float          # + = laden (vanaf netzijde), - = ontladen (naar huis/net)
    net_kw: float               # + = afname van net, - = teruglevering
    kosten: float               # € in dit uur (excl. slijtage)
    modus: str                  # laden_net / zelfconsumptie / vasthouden / ontladen_net


def plan_batterij(bat: Batterij, start_soc_kwh: float, verbruik_kw: list[float],
                  zon_kw: list[float], inkoop: list[float], teruglever: list[float],
                  stappen: int = 50) -> list[BatterijUur]:
    n = len(verbruik_kw)
    if n == 0:
        return []
    stap = bat.capaciteit_kwh / stappen
    lo = math.ceil(bat.min_soc * stappen - 1e-9)
    hi = math.floor(bat.max_soc * stappen + 1e-9)
    s0 = min(max(round(start_soc_kwh / stap), lo), hi)
    lo = min(lo, s0)
    hi = max(hi, s0)
    eta = math.sqrt(bat.rendement_rondgang)  # rendement per richting
    max_op = int(bat.max_laadvermogen_kw / stap + 1e-9)
    max_af = int(bat.max_ontlaadvermogen_kw / stap + 1e-9)

    # Restwaarde van energie in de batterij aan het eind van de horizon: wat je
    # er later redelijkerwijs mee bespaart (mediane inkoopprijs × rendement).
    mediaan = sorted(inkoop)[len(inkoop) // 2]
    restwaarde = mediaan * eta * 0.9

    def uurkosten(t: int, delta_stappen: int) -> tuple[float, float, float]:
        energie = delta_stappen * stap  # verandering in batterij (kWh)
        if energie >= 0:
            bat_kw = energie / eta
            slijt = 0.0
        else:
            bat_kw = energie * eta
            slijt = -energie * bat.slijtage_eur_per_kwh
        net = verbruik_kw[t] - zon_kw[t] + bat_kw
        kosten = net * inkoop[t] if net >= 0 else net * teruglever[t]
        return kosten, slijt, net

    INF = float("inf")
    waarde = [-(s * stap) * restwaarde if lo <= s <= hi else INF for s in range(stappen + 1)]
    keuze = [[0] * (stappen + 1) for _ in range(n)]
    for t in range(n - 1, -1, -1):
        nieuw = [INF] * (stappen + 1)
        for s in range(lo, hi + 1):
            beste, beste_d = INF, 0
            for d in range(-min(max_af, s - lo), min(max_op, hi - s) + 1):
                k, slijt, _ = uurkosten(t, d)
                totaal = k + slijt + waarde[s + d]
                if totaal < beste - 1e-12 or (abs(totaal - beste) <= 1e-12 and abs(d) < abs(beste_d)):
                    beste, beste_d = totaal, d
            nieuw[s] = beste
            keuze[t][s] = beste_d
        waarde = nieuw

    plan = []
    s = s0
    for t in range(n):
        d = keuze[t][s]
        kosten, _, net = uurkosten(t, d)
        bat_kw = net - (verbruik_kw[t] - zon_kw[t])
        plan.append(BatterijUur(s * stap, (s + d) * stap, bat_kw, net, kosten,
                                _modus(bat_kw, verbruik_kw[t] - zon_kw[t], s, lo, hi)))
        s += d
    return plan


def _modus(bat_kw: float, rest_kw: float, s: int, lo: int, hi: int) -> str:
    """Vertaal het plan naar een eenvoudige stand voor de batterijomvormer.

    - laden_net:      actief laden uit het net (goedkoop uur)
    - ontladen_net:   meer ontladen dan het huis verbruikt (duur uur, terugleveren)
    - vasthouden:     niet ontladen, energie bewaren voor een duurder uur
    - zelfconsumptie: normale stand: zonne-overschot opslaan, tekort aanvullen
    """
    marge = 0.05
    overschot = max(0.0, -rest_kw)
    tekort = max(0.0, rest_kw)
    if bat_kw > overschot + marge:
        return "laden_net"
    if -bat_kw > tekort + marge:
        return "ontladen_net"
    if tekort > marge and -bat_kw < marge and s > lo:
        return "vasthouden"
    return "zelfconsumptie"
