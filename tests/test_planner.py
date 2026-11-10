import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from energieplanner import bronnen
from energieplanner.batterij import plan_batterij
from energieplanner.config import Airco, Batterij, Tarieven, laad_config
from energieplanner.homeassistant import stuur
from energieplanner.planner import maak_plan
from energieplanner.warmte import cop, gaskosten_per_kwh_warmte, plan_warmte

VOORBEELD = Path(__file__).resolve().parent.parent / "config.voorbeeld.toml"
START = datetime(2026, 11, 10, 0, tzinfo=timezone.utc)


class TestTarieven(unittest.TestCase):
    def test_allin(self):
        t = Tarieven(inkoop_opslag=0.02, energiebelasting=0.10, btw=0.21)
        self.assertAlmostEqual(t.stroom_allin(0.10), 0.22 * 1.21)

    def test_saldering_stopt_in_2027(self):
        t = Tarieven()
        self.assertAlmostEqual(t.stroom_teruglever(0.10, date(2027, 1, 1)), 0.10)

    def test_teruglevering_zonneplan(self):
        # Koop- en verkoopprijs uit de Anker-app, 10-11-2026 10:15
        t = Tarieven(inkoop_opslag=0.01653, energiebelasting=0.09161, btw=0.21, teruglever_kosten=0.02)
        kaal = 0.51947 / 1.21 - 0.01653 - 0.09161
        self.assertAlmostEqual(t.stroom_allin(kaal), 0.51947, places=4)
        self.assertAlmostEqual(t.stroom_teruglever(kaal, date(2026, 11, 10)), 0.47609, delta=0.002)
        self.assertAlmostEqual(t.stroom_teruglever(kaal, date(2027, 1, 1)), kaal - 0.02)


class TestWarmte(unittest.TestCase):
    def test_cop_daalt_bij_kou(self):
        a = Airco("x", "climate.x", cop_7c=4.0)
        self.assertGreater(cop(a, 10), cop(a, 0))
        self.assertGreater(cop(a, 0), cop(a, -10))
        self.assertGreaterEqual(cop(a, -30), 1.5)

    def test_gas_warmteprijs(self):
        self.assertAlmostEqual(gaskosten_per_kwh_warmte(1.35, 0.9), 0.1535, places=3)

    def test_keuze_airco_of_cv(self):
        cfg = laad_config(VOORBEELD)
        goedkoop = plan_warmte(cfg, [12], [5.0], [0.25], 1.35)[0]
        self.assertEqual(goedkoop.bron, "airco")
        self.assertLess(goedkoop.cv_setpoint, cfg.huis.dagtemperatuur)
        duur = plan_warmte(cfg, [12], [5.0], [0.90], 1.35)[0]
        self.assertEqual(duur.bron, "cv")
        self.assertEqual(duur.stroom_kw, 0.0)

    def test_koelen_in_zomer(self):
        cfg = laad_config(VOORBEELD)
        w = plan_warmte(cfg, [15], [30.0], [0.25], 1.35)[0]
        self.assertEqual(w.bron, "koelen")
        self.assertTrue(all(a.modus == "cool" for a in w.aircos))


class TestBatterij(unittest.TestCase):
    def test_laadt_goedkoop_ontlaadt_duur(self):
        bat = Batterij(capaciteit_kwh=5, max_laadvermogen_kw=2.5, max_ontlaadvermogen_kw=2.5,
                       rendement_rondgang=0.9, min_soc=0.1, max_soc=0.9, slijtage_eur_per_kwh=0.02)
        inkoop = [0.15, 0.15, 0.45, 0.45]
        plan = plan_batterij(bat, 0.5, [1.0] * 4, [0.0] * 4, inkoop, inkoop)
        self.assertEqual(plan[0].modus, "laden_net")
        self.assertLess(plan[2].batterij_kw, 0)
        for u in plan:
            self.assertGreaterEqual(u.soc_eind, 0.5 - 1e-9)
            self.assertLessEqual(u.soc_eind, 4.5 + 1e-9)

    def test_geen_cycli_bij_vlakke_prijs(self):
        bat = Batterij()
        inkoop = [0.25] * 6
        plan = plan_batterij(bat, 2.5, [0.5] * 6, [0.0] * 6, inkoop, inkoop)
        self.assertTrue(all(u.modus != "laden_net" for u in plan))

    def test_zonne_overschot_opslaan_zonder_saldering(self):
        bat = Batterij(slijtage_eur_per_kwh=0.0)
        inkoop = [0.30] * 4
        terug = [0.02] * 4
        plan = plan_batterij(bat, 1.0, [0.3, 0.3, 1.0, 1.0], [1.5, 1.5, 0.0, 0.0], inkoop, terug)
        self.assertGreater(plan[1].soc_eind, plan[0].soc_begin)
        self.assertAlmostEqual(plan[0].net_kw, 0.0, delta=0.1)


class TestGeheel(unittest.TestCase):
    def test_plan_bespaart(self):
        cfg = laad_config(VOORBEELD)
        plan = maak_plan(cfg, bronnen.demo_uren(START), 0.5, 1.35)
        self.assertEqual(len(plan.uren), 36)
        self.assertGreater(plan.besparing, 0)

    def test_kwartierprijzen_naar_uren(self):
        t = START
        kwartier = [(t.replace(minute=m), p) for m, p in [(0, 0.1), (15, 0.2), (30, 0.3), (45, 0.4)]]
        self.assertAlmostEqual(bronnen.middel_per_uur(kwartier)[t], 0.25)

    def test_stuur_droog(self):
        cfg = laad_config(VOORBEELD)
        plan = maak_plan(cfg, bronnen.demo_uren(START), 0.5, 1.35)
        client = stuur(cfg, plan, droog=True, nu=START)
        paden = [p for p, _ in client.log]
        self.assertIn("/api/services/input_select/select_option", paden)
        self.assertIn("/api/states/sensor.energieplan", paden)
        self.assertEqual(sum(p == "/api/services/climate/set_temperature" or
                             p == "/api/services/climate/set_hvac_mode" for p in paden), 3)


if __name__ == "__main__":
    unittest.main()
