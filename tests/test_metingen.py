import os
import sys
import types
import unittest
from unittest import mock

from energieplanner import metingen


class TestOmrekenen(unittest.TestCase):
    def test_eenheden(self):
        self.assertAlmostEqual(metingen._naar_kw("620 W"), 0.62)
        self.assertAlmostEqual(metingen._naar_kw("1.2 kW"), 1.2)
        self.assertAlmostEqual(metingen._naar_kw("350", "w"), 0.35)
        self.assertAlmostEqual(metingen._naar_kwh("3,4 kWh"), 3.4)
        self.assertIsNone(metingen._naar_kw(None))
        self.assertIsNone(metingen._naar_kw("onbekend"))

    def test_vermogen_zonder_eenheid(self):
        self.assertAlmostEqual(metingen._vermogen_kw(0.478), 0.478)
        self.assertAlmostEqual(metingen._vermogen_kw("0.478"), 0.478)
        self.assertAlmostEqual(metingen._vermogen_kw(478), 0.478)
        self.assertAlmostEqual(metingen._vermogen_kw("478 W"), 0.478)
        self.assertAlmostEqual(metingen._vermogen_kw("1.2 kW"), 1.2)


class TestZonderInlog(unittest.TestCase):
    def test_niet_gekoppeld(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(metingen.lees_growatt()["status"], "niet_gekoppeld")
            self.assertEqual(metingen.lees_anker()["status"], "niet_gekoppeld")


class TestGrowatt(unittest.TestCase):
    def test_klassieke_api(self):
        nep = types.ModuleType("growattServer")

        class Api:
            def __init__(self, **kw): pass
            def login(self, u, p): return {"success": True, "user": {"id": 7}}
            def plant_list(self, uid): return {"data": [{"currentPower": "1.25 kW", "todayEnergy": "4.3 kWh"}]}

        nep.GrowattApi = Api
        with mock.patch.dict(sys.modules, {"growattServer": nep}), \
             mock.patch.dict(os.environ, {"GROWATT_USERNAME": "a", "GROWATT_PASSWORD": "b"}, clear=True):
            r = metingen.lees_growatt()
        self.assertEqual(r, {"status": "ok", "zon_kw": 1.25, "zon_vandaag_kwh": 4.3})

    def test_api_token(self):
        nep = types.ModuleType("growattServer")

        class OpenApi:
            def __init__(self, token): assert token == "tok"
            def plant_list(self): return {"plants": [{"plant_id": 42}]}
            def plant_energy_overview(self, pid):
                assert pid == 42
                return {"current_power": 840, "today_energy": "2.3"}

        nep.OpenApiV1 = OpenApi
        with mock.patch.dict(sys.modules, {"growattServer": nep}), \
             mock.patch.dict(os.environ, {"GROWATT_TOKEN": "tok"}, clear=True):
            r = metingen.lees_growatt()
        self.assertEqual(r["status"], "ok")
        self.assertAlmostEqual(r["zon_kw"], 0.84)
        self.assertAlmostEqual(r["zon_vandaag_kwh"], 2.3)

    def test_fout_lekt_geen_wachtwoord(self):
        nep = types.ModuleType("growattServer")

        class Api:
            def __init__(self, **kw): pass
            def login(self, u, p): raise RuntimeError(f"login {p} geweigerd")

        nep.GrowattApi = Api
        with mock.patch.dict(sys.modules, {"growattServer": nep}), \
             mock.patch.dict(os.environ, {"GROWATT_USERNAME": "a", "GROWATT_PASSWORD": "geheim123"}, clear=True):
            r = metingen.lees_growatt()
        self.assertEqual(r["status"], "fout")
        self.assertNotIn("geheim123", r["fout"])


class TestAnker(unittest.TestCase):
    def test_batterij_uitlezen(self):
        apimod = types.ModuleType("api.api")

        class NepApi:
            def __init__(self, *a): self.devices, self.sites = {}, {}
            async def update_sites(self):
                self.devices = {"x": {"battery_soc": "63", "bat_charge_power": "800", "output_power": "250"}}
            async def update_device_details(self): pass

        apimod.AnkerSolixApi = NepApi
        pakket = types.ModuleType("api")
        pakket.api = apimod
        aio = types.ModuleType("aiohttp")

        class Sessie:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False

        aio.ClientSession = Sessie
        with mock.patch.dict(sys.modules, {"api": pakket, "api.api": apimod, "aiohttp": aio}), \
             mock.patch.dict(os.environ, {"ANKER_USERNAME": "a", "ANKER_PASSWORD": "b"}, clear=True):
            r = metingen.lees_anker()
        self.assertEqual(r["status"], "ok")
        self.assertAlmostEqual(r["soc"], 0.63)
        self.assertAlmostEqual(r["laden_kw"], 0.8)
        self.assertAlmostEqual(r["naar_huis_kw"], 0.25)


if __name__ == "__main__":
    unittest.main()
