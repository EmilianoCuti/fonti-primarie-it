#!/usr/bin/env python
"""Prova documentale: cosa diceva una pagina in una certa data (Internet Archive).

Non usa librerie aggiuntive: interroga la CDX API e scarica lo snapshot con `id_`,
che restituisce il contenuto originale senza la barra di navigazione dell'archivio.

Esempi:
    python wayback_prova.py "https://www.comune.lodi.it/bandi" --data 2026-03-14
    python wayback_prova.py URL --data 2026-03-14 --cerca "importo 250.000"
    python wayback_prova.py URL --elenca 20        (ultimi 20 snapshot)
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time

CDX = "https://web.archive.org/cdx/search/cdx"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def snapshot(url: str, dal: str, al: str, limite: int = 60) -> list[dict]:
    import requests

    p = {
        "url": url,
        "output": "json",
        "from": dal,
        "to": al,
        "limit": str(limite),
        "filter": "statuscode:200",
        "collapse": "digest",
    }
    r = requests.get(CDX, params=p, headers={"User-Agent": UA}, timeout=60)
    r.raise_for_status()
    righe = r.json()
    if not righe or len(righe) < 2:
        return []
    intest = righe[0]
    return [dict(zip(intest, r_)) for r_ in righe[1:]]


def scarica_snapshot(ts: str, url: str) -> str:
    import requests

    r = requests.get(f"https://web.archive.org/web/{ts}id_/{url}", headers={"User-Agent": UA}, timeout=90)
    r.raise_for_status()
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding
    return r.text


def testo(html: str) -> str:
    try:
        import trafilatura

        return trafilatura.extract(html, include_tables=True, include_comments=False) or ""
    except Exception:
        import re

        return re.sub(r"<[^>]+>", " ", html)


def principale() -> int:
    ap = argparse.ArgumentParser(description="Snapshot datati e verifica di una stringa.")
    ap.add_argument("url")
    ap.add_argument("--data", help="data di interesse YYYY-MM-DD (default: oggi)")
    ap.add_argument("--finestra", type=int, default=180, help="giorni prima/dopo la data (default 180)")
    ap.add_argument("--cerca", help="stringa da cercare nel testo dello snapshot")
    ap.add_argument("--elenca", type=int, help="elenca solo gli ultimi N snapshot")
    args = ap.parse_args()
    if "://" not in args.url:
        args.url = "https://" + args.url

    riferimento = dt.date.fromisoformat(args.data) if args.data else dt.date.today()
    dal = (riferimento - dt.timedelta(days=args.finestra)).strftime("%Y%m%d")
    al = (riferimento + dt.timedelta(days=args.finestra)).strftime("%Y%m%d")

    try:
        snaps = snapshot(args.url, dal, al, limite=args.elenca or 60)
    except Exception as e:
        print(f"ERRORE CDX: {e}")
        return 1

    if not snaps:
        print(f"nessuno snapshot con status 200 per {args.url} tra {dal} e {al}")
        print("prova ad allargare --finestra, oppure il sito non è mai stato archiviato.")
        return 2

    snaps.sort(key=lambda s: s["timestamp"])
    if args.elenca:
        for s in snaps[-args.elenca:]:
            print(s["timestamp"], s.get("original") or args.url)
        return 0

    # snapshot più vicino alla data richiesta
    def distanza(s):
        t = dt.datetime.strptime(s["timestamp"][:8], "%Y%m%d").date()
        return abs((t - riferimento).days)

    scelto = min(snaps, key=distanza)
    ts = scelto["timestamp"]
    quando = dt.datetime.strptime(ts[:14], "%Y%m%d%H%M%S")

    print(f"snapshot scelto: {ts}  ({quando.isoformat(sep=' ')})  {len(snaps)} disponibili nella finestra")
    print(f"url archiviato: {scelto.get('original') or args.url}")
    print(f"url citabile : https://web.archive.org/web/{ts}/{scelto.get('original') or args.url}")

    if not args.cerca:
        return 0

    time.sleep(1)
    try:
        html = scarica_snapshot(ts, scelto.get("original") or args.url)
    except Exception as e:
        print(f"ERRORE download snapshot: {e}")
        return 1

    t = testo(html)
    trovata = args.cerca.lower() in t.lower()
    print(f"\ncerca \"{args.cerca}\": {'PRESENTE' if trovata else 'ASSENTE'} nello snapshot")
    if trovata:
        i = t.lower().find(args.cerca.lower())
        print("contesto:", " ".join(t[max(0, i - 160): i + len(args.cerca) + 160].split()))

    # confronto con la pagina di oggi
    try:
        import requests

        r = requests.get(args.url, headers={"User-Agent": UA}, timeout=45)
        oggi = testo(r.text)
        ora = args.cerca.lower() in oggi.lower()
        print(f"cerca \"{args.cerca}\": {'PRESENTE' if ora else 'ASSENTE'} nella pagina di oggi ({dt.date.today()})")
        if trovata and not ora:
            print("=> PROVA: la stringa c'era nello snapshot e non è più presente oggi.")
        elif not trovata and ora:
            print("=> la stringa è comparsa dopo: lo snapshot non la contiene.")
    except Exception as e:
        print(f"(confronto con la pagina attuale non riuscito: {e})")

    print("\n--- citazione ---")
    print(
        f"Internet Archive, snapshot {quando.date().isoformat()} di {args.url} "
        f"(https://web.archive.org/web/{ts}/{args.url}), consultato il {dt.date.today().isoformat()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(principale())
