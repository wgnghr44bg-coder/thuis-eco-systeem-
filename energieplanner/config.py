"""Inlezen van de configuratie (TOML, alleen standaardbibliotheek)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass
class Tarieven:
    inkoop_opslag: float = 0.02
    energiebelasting: float = 0.0916
    btw: float = 0.21
    saldering_tot: date = date(2027, 1, 1)
    teruglever_kosten: float = 0.0
    gasprijs: float = 1.35
    gas_opslag: float = 0.05
    gas_energiebelasting: float = 0.58

    def stroom_allin(self, kale_prijs: float) -> float:
        """All-in inkoopprijs per kWh uit de kale (day-ahead) prijs excl. btw."""
        return (kale_prijs + self.inkoop_opslag + self.energiebelasting) * (1 + self.btw)

    def stroom_teruglever(self, kale_prijs: float, dag: date) -> float:
        """Waarde van 1 kWh teruglevering.

        Met saldering is dat de all-in prijs (zolang je per jaar meer verbruikt
        dan opwekt, wat met weinig panelen vrijwel zeker zo is). Daarna krijg je
        alleen de kale prijs minus eventuele terugleverkosten.
        """
        if dag < self.saldering_tot:
            return self.stroom_allin(kale_prijs)
        return kale_prijs - self.teruglever_kosten

    def gas_allin(self, kale_gasprijs: float | None) -> float:
        if kale_gasprijs is None:
            return self.gasprijs
        return (kale_gasprijs + self.gas_opslag + self.gas_energiebelasting) * (1 + self.btw)


@dataclass
class Batterij:
    capaciteit_kwh: float = 5.0
    max_laadvermogen_kw: float = 2.5
    max_ontlaadvermogen_kw: float = 2.5
    rendement_rondgang: float = 0.90
    min_soc: float = 0.10
    max_soc: float = 0.95
    slijtage_eur_per_kwh: float = 0.03


@dataclass
class Zonnepanelen:
    vermogen_kwp: float = 1.5
    prestatieratio: float = 0.80


@dataclass
class Huis:
    basisverbruik_kw: float = 0.35
    warmteverlies_w_per_k: float = 180.0
    dagtemperatuur: float = 20.0
    nachttemperatuur: float = 17.0
    nacht_van: int = 23
    nacht_tot: int = 7
    comfort_marge: float = 1.0
    koelen_vanaf: float = 25.0
    koel_temperatuur: float = 24.0

    def setpoint(self, uur: int) -> float:
        if self.nacht_van > self.nacht_tot:
            nacht = uur >= self.nacht_van or uur < self.nacht_tot
        else:
            nacht = self.nacht_van <= uur < self.nacht_tot
        return self.nachttemperatuur if nacht else self.dagtemperatuur


@dataclass
class CV:
    ketelrendement: float = 0.90
    thermostaat_entity: str = "climate.cv_thermostaat"
    verlaging_bij_airco: float = 1.5


@dataclass
class Airco:
    naam: str
    entity: str
    max_warmte_kw: float = 3.5
    cop_7c: float = 4.0
    dekking: float = 0.3


@dataclass
class HomeAssistant:
    url: str = "http://homeassistant.local:8123"
    token_env: str = "HA_TOKEN"
    batterij_modus_entity: str = "input_select.batterij_modus"
    plan_sensor: str = "sensor.energieplan"


@dataclass
class Config:
    breedtegraad: float = 52.1
    lengtegraad: float = 5.1
    tijdzone: str = "Europe/Amsterdam"
    tarieven: Tarieven = field(default_factory=Tarieven)
    batterij: Batterij = field(default_factory=Batterij)
    zonnepanelen: Zonnepanelen = field(default_factory=Zonnepanelen)
    huis: Huis = field(default_factory=Huis)
    cv: CV = field(default_factory=CV)
    aircos: list[Airco] = field(default_factory=list)
    homeassistant: HomeAssistant = field(default_factory=HomeAssistant)


def _maak(cls, data: dict | None):
    data = dict(data or {})
    if cls is Tarieven and isinstance(data.get("saldering_tot"), str):
        data["saldering_tot"] = date.fromisoformat(data["saldering_tot"])
    return cls(**data)


def laad_config(pad: str | Path) -> Config:
    with open(pad, "rb") as f:
        ruw = tomllib.load(f)
    loc = ruw.get("locatie", {})
    return Config(
        breedtegraad=loc.get("breedtegraad", 52.1),
        lengtegraad=loc.get("lengtegraad", 5.1),
        tijdzone=loc.get("tijdzone", "Europe/Amsterdam"),
        tarieven=_maak(Tarieven, ruw.get("tarieven")),
        batterij=_maak(Batterij, ruw.get("batterij")),
        zonnepanelen=_maak(Zonnepanelen, ruw.get("zonnepanelen")),
        huis=_maak(Huis, ruw.get("huis")),
        cv=_maak(CV, ruw.get("cv")),
        aircos=[Airco(**a) for a in ruw.get("airco", [])],
        homeassistant=_maak(HomeAssistant, ruw.get("homeassistant")),
    )
