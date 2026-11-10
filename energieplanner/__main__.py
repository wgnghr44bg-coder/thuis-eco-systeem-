"""Opdrachtregel.

    python -m energieplanner plan  [--config config.toml] [--demo] [--soc 0.5]
    python -m energieplanner stuur [--config config.toml] [--soc 0.5] [--droog]
    python -m energieplanner json  [--config config.toml] [--uitvoer site/plan.json]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import bronnen
from .config import Config, laad_config
from .homeassistant import lees_soc, stuur
from .planner import Plan, maak_plan, plan_naar_dict

MODUS_SYMBOOL = {"laden_net": "⬆ laden", "ontladen_net": "⬇ ontladen",
                 "vasthouden": "⏸ vasthouden", "zelfconsumptie": "↔ zelfcons."}


def verzamel(cfg: Config, demo: bool) -> tuple[list[bronnen.Uur], float]:
    nu = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    if demo:
        return bronnen.demo_uren(nu), cfg.tarieven.gasprijs
    begin_dag = nu.replace(hour=0) - timedelta(hours=2)
    prijzen = bronnen.haal_stroomprijzen(begin_dag, begin_dag + timedelta(days=2, hours=4))
    weer = bronnen.haal_weer(cfg.breedtegraad, cfg.lengtegraad)
    gas = cfg.tarieven.gas_allin(bronnen.haal_gasprijs(begin_dag))
    return bronnen.combineer(prijzen, weer, nu), gas


def toon(plan: Plan) -> None:
    print(f"Gasprijs: €{plan.gasprijs_m3:.3f}/m³\n")
    print(f"{'tijd':<11}{'prijs':>7}{'buiten':>8}{'zon':>6}{'warmte':>8}  {'bron':<7}"
          f"{'CV':>6}  {'airco setpoints':<16}{'batterij':<14}{'SoC':>6}{'net':>7}")
    for u in plan.uren:
        sp = "/".join("uit" if a.setpoint is None else f"{a.setpoint:.1f}" for a in u.warmte.aircos) or "-"
        print(f"{u.lokale_tijd:%a %H:%M} {u.inkoop:>6.3f} {u.buitentemp:>6.1f}° {u.zon_kw:>5.2f}"
              f"{u.warmte.warmtevraag_kw:>7.2f}  {u.warmte.bron:<7}{u.warmte.cv_setpoint:>5.1f}°  {sp:<16}"
              f"{MODUS_SYMBOOL[u.batterij.modus]:<14}{u.batterij.soc_eind:>5.1f}{u.batterij.net_kw:>7.2f}")
    print(f"\nKosten met slimme sturing : €{plan.kosten_plan:7.2f}")
    print(f"Kosten zonder sturing     : €{plan.kosten_referentie:7.2f}  (alles op CV, batterij alleen zon opslaan)")
    print(f"Verwachte besparing       : €{plan.besparing:7.2f} over {len(plan.uren)} uur")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="energieplanner", description="Slimme sturing van airco's, CV en thuisbatterij")
    p.add_argument("opdracht", choices=["plan", "stuur", "json"])
    p.add_argument("--config", default="config.toml")
    p.add_argument("--demo", action="store_true", help="gebruik nep-data i.p.v. internet")
    p.add_argument("--soc", type=float, default=None,
                   help="huidige batterijlading als fractie (0-1); standaard uit Home Assistant of 0.5")
    p.add_argument("--uitvoer", default="site/plan.json", help="bestand voor de json-opdracht")
    p.add_argument("--droog", action="store_true", help="toon wat naar Home Assistant zou gaan, zonder te sturen")
    args = p.parse_args(argv)

    pad = Path(args.config)
    if not pad.exists():
        pad = Path(__file__).resolve().parent.parent / "config.voorbeeld.toml"
        print(f"(config.toml niet gevonden, gebruik {pad.name})", file=sys.stderr)
    cfg = laad_config(pad)

    bron = "demo" if args.demo else "live"
    try:
        uren, gas = verzamel(cfg, args.demo)
    except Exception as e:
        if args.opdracht != "json":
            raise
        # Voor de website liever een demo-plan dan een lege pagina.
        print(f"Live data niet beschikbaar ({e}), val terug op demo", file=sys.stderr)
        uren, gas, bron = *verzamel(cfg, True), "demo"
    if not uren:
        print("Geen prijzen beschikbaar.", file=sys.stderr)
        return 1

    soc, soc_bron = args.soc, "opgegeven"
    if soc is None:
        soc = lees_soc(cfg)
        soc_bron = "home_assistant" if soc is not None else "aanname"
        soc = 0.5 if soc is None else soc
    plan = maak_plan(cfg, uren, soc, gas)

    if args.opdracht == "plan":
        toon(plan)
    elif args.opdracht == "json":
        data = plan_naar_dict(cfg, plan, bron=bron, soc_bron=soc_bron)
        os.makedirs(os.path.dirname(args.uitvoer) or ".", exist_ok=True)
        with open(args.uitvoer, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        print(f"Plan geschreven naar {args.uitvoer} ({len(plan.uren)} uur, bron: {bron})")
    else:
        client = stuur(cfg, plan, droog=args.droog)
        for pad_, data in client.log:
            kort = {k: v for k, v in data.items() if k != "attributes"}
            print(("[droog] " if args.droog else "") + pad_, kort)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
