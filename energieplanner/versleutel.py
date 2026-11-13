"""Versleutelt plan.json met een wachtwoord, zodat de openbare website alleen
leesbaar is voor wie het wachtwoord kent.

Gebruik (in de GitHub Action):
    SITE_WACHTWOORD=... python -m energieplanner.versleutel _site/plan.json _site/plan.enc.json

De browser ontsleutelt met de Web Crypto API: PBKDF2-SHA256 maakt van het
wachtwoord een AES-256-sleutel, AES-GCM versleutelt en controleert de inhoud.
"""
from __future__ import annotations

import base64
import json
import os
import sys

ITERATIES = 600_000  # maakt raden traag; OWASP-advies voor PBKDF2-SHA256


def _sleutel(wachtwoord: str, zout: bytes, iteraties: int) -> bytes:
    import hashlib
    return hashlib.pbkdf2_hmac("sha256", wachtwoord.encode("utf-8"), zout, iteraties, dklen=32)


def versleutel(data: bytes, wachtwoord: str, iteraties: int = ITERATIES) -> dict:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    zout, iv = os.urandom(16), os.urandom(12)
    geheim = AESGCM(_sleutel(wachtwoord, zout, iteraties)).encrypt(iv, data, None)
    b64 = lambda b: base64.b64encode(b).decode("ascii")
    return {"versie": 1, "kdf": "PBKDF2-SHA256", "iteraties": iteraties,
            "zout": b64(zout), "iv": b64(iv), "data": b64(geheim)}


def ontsleutel(pakket: dict, wachtwoord: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    d = lambda k: base64.b64decode(pakket[k])
    return AESGCM(_sleutel(wachtwoord, d("zout"), pakket["iteraties"])).decrypt(d("iv"), d("data"), None)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("gebruik: python -m energieplanner.versleutel <plan.json> <plan.enc.json>", file=sys.stderr)
        return 2
    wachtwoord = os.environ.get("SITE_WACHTWOORD", "")
    if len(wachtwoord) < 12:
        print("SITE_WACHTWOORD ontbreekt of is korter dan 12 tekens", file=sys.stderr)
        return 1
    with open(argv[0], "rb") as f:
        pakket = versleutel(f.read(), wachtwoord)
    with open(argv[1], "w", encoding="utf-8") as f:
        json.dump(pakket, f)
    print(f"Plan versleuteld naar {argv[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
