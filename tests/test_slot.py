import json
import os
import tempfile
import unittest
from unittest import mock

from energieplanner import slot


class TestSlot(unittest.TestCase):
    def test_heen_en_terug(self):
        p = slot.versleutel(b'{"a": 1}', "geheime code", iteraties=1000)
        self.assertNotIn("a", base64_tekst(p))
        self.assertEqual(slot.ontsleutel(p, "geheime code"), b'{"a": 1}')

    def test_verkeerde_code(self):
        p = slot.versleutel(b"x", "goed", iteraties=1000)
        with self.assertRaises(Exception):
            slot.ontsleutel(p, "fout")

    def test_zonder_code_geen_bestand(self):
        with tempfile.TemporaryDirectory() as d:
            pad = os.path.join(d, "plan.json")
            with open(pad, "w") as f:
                f.write('{"geheim": true}')
            with mock.patch.dict(os.environ, {}, clear=True):
                slot.main([pad])
            self.assertFalse(os.path.exists(pad))

    def test_met_code_versleuteld(self):
        with tempfile.TemporaryDirectory() as d:
            pad = os.path.join(d, "plan.json")
            with open(pad, "w") as f:
                f.write('{"growatt": 123}')
            with mock.patch.dict(os.environ, {"SITE_CODE": "abc"}, clear=True), \
                 mock.patch.object(slot, "ITERATIES", 1000):
                slot.main([pad])
            with open(pad) as f:
                p = json.load(f)
            self.assertEqual(p["versleuteld"], 1)
            self.assertNotIn("growatt", json.dumps(p))


def base64_tekst(p):
    return p["data"]


if __name__ == "__main__":
    unittest.main()
