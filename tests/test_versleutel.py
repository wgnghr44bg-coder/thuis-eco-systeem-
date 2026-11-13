import unittest

try:
    import cryptography  # noqa: F401
    HEEFT_CRYPTO = True
except ImportError:
    HEEFT_CRYPTO = False


@unittest.skipUnless(HEEFT_CRYPTO, "pakket cryptography niet geïnstalleerd")
class TestVersleutel(unittest.TestCase):
    def test_heen_en_terug(self):
        from energieplanner.versleutel import ontsleutel, versleutel
        pakket = versleutel(b'{"a": 1}', "lang genoeg wachtwoord", iteraties=1000)
        self.assertEqual(ontsleutel(pakket, "lang genoeg wachtwoord"), b'{"a": 1}')

    def test_fout_wachtwoord(self):
        from cryptography.exceptions import InvalidTag
        from energieplanner.versleutel import ontsleutel, versleutel
        pakket = versleutel(b"geheim", "goed wachtwoord 123", iteraties=1000)
        with self.assertRaises(InvalidTag):
            ontsleutel(pakket, "fout wachtwoord 123")

    def test_elke_keer_anders(self):
        from energieplanner.versleutel import versleutel
        a = versleutel(b"x", "goed wachtwoord 123", iteraties=1000)
        b = versleutel(b"x", "goed wachtwoord 123", iteraties=1000)
        self.assertNotEqual(a["data"], b["data"])


if __name__ == "__main__":
    unittest.main()
