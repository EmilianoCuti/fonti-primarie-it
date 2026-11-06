#!/usr/bin/env python
"""Demografia e bilancio demografico per comune dai tracciati ufficiali ISTAT.

Scarica i file di demo.istat.it (nessuna chiave API), filtra il comune e mostra le colonne
così come sono nel tracciato ufficiale. Non indovina il significato delle colonne e non
restituisce zero quando l'anno manca.

Esempi:
    python istat_comune.py --comune Lodi --sigla LO --anni 2020-2025
    python istat_comune.py --comune Lodi --codice 098 --provincia Lodi --anni 2025 --tipo posas
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import sys
import zipfile

BASE = "https://demo.istat.it/data"

# sigla -> (codice provincia, nome nel nome file). Le province sono aggiungibili.
PROVINCE = {
    "LO": ("098", "Lodi"), "MI": ("015", "Milano"), "MB": ("108", "Monza e Brianza"),
    "PV": ("018", "Pavia"), "CR": ("019", "Cremona"), "MN": ("020", "Mantova"),
    "BS": ("017", "Brescia"), "BG": ("016", "Bergamo"), "CO": ("013", "Como"),
    "VA": ("012", "Varese"), "LC": ("097", "Lecco"), "SO": ("014", "Sondrio"),
    "TO": ("001", "Torino"), "GE": ("010", "Genova"), "BO": ("037", "Bologna"),
    "FI": ("048", "Firenze"), "RM": ("058", "Roma"), "NA": ("063", "Napoli"),
    "BA": ("072", "Bari"), "PA": ("082", "Palermo"), "VE": ("027", "Venezia"),
    "PD": ("028", "Padova"), "VR": ("023", "Verona"), "PR": ("034", "Parma"),
    "RE": ("035", "Reggio nell'Emilia"), "MO": ("036", "Modena"), "RA": ("039", "Ravenna"),
}


def candidati(tipo: str, anno: int, codice: str, provincia: str) -> list[str]:
    varianti = {
        provincia,
        provincia.replace(" ", "_"),
        provincia.replace(" ", ""),
        provincia.replace("'", "_"),
        provincia.replace("'", ""),
        provincia.replace(" ", "_").replace("'", "_"),
    }
    prefisso = {"p2": "P2", "p3": "P3", "posas": "POSAS"}.get(tipo)
    if not prefisso:
        sys.exit(f"tipo non gestito: {tipo} (usa p2, p3 o posas)")
    cartella = {"p2": "p2", "p3": "p3", "posas": "posas"}[tipo]
    return [f"{BASE}/{cartella}/{prefisso}_{anno}_it_{codice}_{v}.zip" for v in sorted(varianti)]


def scarica(url: str) -> bytes | None:
    import requests

    r = requests.get(url, timeout=120, headers={"User-Agent": "fonti-primarie-it/1.0"})
    if r.status_code != 200 or not r.content:
        return None
    return r.content


def trova_colonna_comune(intest: list[str]) -> int | None:
    """La colonna del nome del comune, non quella del codice."""
    for i, c in enumerate(intest):
        if (c or "").strip().lower() == "comune":
            return i
    for i, c in enumerate(intest):
        u = (c or "").upper()
        if "COMUNE" in u and "CODICE" not in u and "COD" not in u:
            return i
    return None


def leggi_zip(dati: bytes) -> tuple[list[str], list[list[str]]]:
    with zipfile.ZipFile(io.BytesIO(dati)) as z:
        nome = [n for n in z.namelist() if n.lower().endswith(".csv")][0]
        testo = z.read(nome).decode("utf-8-sig", "replace")
    righe = list(csv.reader(io.StringIO(testo), delimiter=";"))
    if not righe:
        return [], []
    # i tracciati ISTAT hanno una o piu righe di titolo prima dell'intestazione vera:
    # si prende la prima riga che contiene una colonna COMUNE.
    idx = next((i for i, r in enumerate(righe) if any("COMUNE" in (c or "").upper() for c in r)), None)
    if idx is None:
        return [], righe
    return righe[idx], righe[idx + 1:]


def principale() -> int:
    ap = argparse.ArgumentParser(description="Serie demografica comunale da ISTAT.")
    ap.add_argument("--comune", required=True)
    ap.add_argument("--sigla", help="sigla provincia (es. LO)")
    ap.add_argument("--codice", help="codice provincia a 3 cifre (es. 098)")
    ap.add_argument("--provincia", help="nome provincia come compare nel file (es. Lodi)")
    ap.add_argument("--anni", required=True, help="es. 2024 oppure 2019-2025")
    ap.add_argument("--tipo", default="p2", choices=["p2", "p3", "posas"])
    ap.add_argument("--tutte", action="store_true", help="stampa tutte le colonne, non solo popolazione e totali")
    ap.add_argument("--out", help="salva in CSV le righe del comune")
    args = ap.parse_args()

    if args.sigla:
        cod, nome = PROVINCE.get(args.sigla.upper(), (None, None))
        if not cod:
            sys.exit(f"sigla {args.sigla} non in tabella: passa --codice e --provincia")
        codice, provincia = args.codice or cod, args.provincia or nome
    else:
        if not (args.codice and args.provincia):
            sys.exit("servono --sigla, oppure --codice insieme a --provincia")
        codice, provincia = args.codice, args.provincia

    if "-" in args.anni:
        a, b = args.anni.split("-", 1)
        anni = list(range(int(a), int(b) + 1))
    else:
        anni = [int(args.anni)]

    trovati = 0
    for anno in anni:
        dati, usato = None, None
        for url in candidati(args.tipo, anno, codice, provincia):
            dati = scarica(url)
            if dati:
                usato = url
                break
        if not dati:
            print(f"\n### {anno}: NON DISPONIBILE (nessuna variante ha risposto). "
                  f"Provato: {candidati(args.tipo, anno, codice, provincia)[0]}")
            continue
        trovati += 1
        intest, righe = leggi_zip(dati)
        col_comune = trova_colonna_comune(intest)
        if col_comune is None:
            print(f"\n### {anno}: tracciato senza colonna del nome comune. Colonne: {intest[:8]}")
            continue
        mie = [r for r in righe if len(r) > col_comune and r[col_comune].strip().lower() == args.comune.strip().lower()]
        print(f"\n### {anno}  [{usato}]  ({len(righe)} comuni nel file)")
        if not mie:
            vicini = sorted({r[col_comune].strip() for r in righe
                             if args.comune.strip().lower()[:4] in r[col_comune].strip().lower()})[:10]
            print(f"  nessuna riga per {args.comune}")
            if vicini:
                print(f"  nomi simili nel file: {', '.join(vicini)}")
            continue
        chiave = [i for i, c in enumerate(intest) if "popolazione" in (c or "").lower() or "totale" in (c or "").lower()]
        for r in mie:
            indici = range(len(intest)) if args.tutte else chiave
            for i in indici:
                if i < len(r) and r[i].strip():
                    print(f"  {intest[i]} = {r[i].strip()}")
            if args.out:
                import pathlib
                p = pathlib.Path(args.out)
                p.parent.mkdir(parents=True, exist_ok=True)
                with p.open("w", newline="", encoding="utf-8") as f:
                    scrittore = csv.writer(f, delimiter=";")
                    scrittore.writerow(intest)
                    scrittore.writerows(mie)
                print(f"  [salvato] {p}")
        if not args.tutte:
            print("  (per tutte le colonne: --tutte)")

    print("\n--- citazione ---")
    print(
        f"ISTAT, demo.istat.it, tracciato {args.tipo.upper()} {codice} {provincia}, "
        f"anni {args.anni}, consultato il {dt.date.today().isoformat()}"
    )
    if not trovati:
        print("ATTENZIONE: nessun anno scaricato: nel rapporto va scritto 'non disponibile', non zero.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(principale())
