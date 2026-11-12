"""Versleutelt plan.json met een code, zodat de openbare website niets prijsgeeft.

De code staat als repository secret SITE_CODE. De website vraagt dezelfde code
en ontsleutelt in de browser (WebCrypto: PBKDF2-SHA256 + AES-GCM).
Zonder code is het bestand alleen onleesbare tekst.

Gebruik:  python -m energieplanner.slot _site/plan.json
Zonder SITE_CODE wordt plan.json verwijderd (liever geen data dan open data).
"""
from __future__ import annotations

import base64
import json
import os
import sys

ITERATIES = 600_000


def _sleutel(code: str, zout: bytes, iteraties: int) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=zout, iterations=iteraties)
    return kdf.derive(code.encode("utf-8"))


def versleutel(data: bytes, code: str, iteraties: int = ITERATIES) -> dict:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    zout, iv = os.urandom(16), os.urandom(12)
    geheim = AESGCM(_sleutel(code, zout, iteraties)).encrypt(iv, data, None)
    b64 = lambda b: base64.b64encode(b).decode("ascii")
    return {"versleuteld": 1, "iter": iteraties, "zout": b64(zout), "iv": b64(iv), "data": b64(geheim)}


def ontsleutel(pakket: dict, code: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    d = lambda k: base64.b64decode(pakket[k])
    sleutel = _sleutel(code, d("zout"), int(pakket["iter"]))
    return AESGCM(sleutel).decrypt(d("iv"), d("data"), None)


def main(argv: list[str] | None = None) -> int:
    pad = (argv or sys.argv[1:] or ["_site/plan.json"])[0]
    code = os.environ.get("SITE_CODE", "").strip()
    if not code:
        if os.path.exists(pad):
            os.remove(pad)
        print("SITE_CODE ontbreekt: plan.json NIET gepubliceerd.")
        return 0
    with open(pad, "rb") as f:
        pakket = versleutel(f.read(), code, ITERATIES)
    with open(pad, "w", encoding="utf-8") as f:
        json.dump(pakket, f)
    print("plan.json versleuteld.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
