#!/usr/bin/env python
"""Client per l'Archivio Semantico (progetto newssearch, embeddinggemma-2 + Chroma).

Interroga il server locale che tiene il modello in memoria: una query costa 0,3-0,5 s.
La CLI del progetto, invece, ricarica il modello a ogni invocazione (~105 s): non usarla
per ricerche interattive.

Prima di cercare serve il server acceso:
    powershell -File "C:\\Users\\emili\\.openclaw-autoclaw\\agents\\il-mio-coding-agent\\workspace\\projects\\semantic-news-search\\run_server.ps1"

Esempi:
    python archivio.py stato
    python archivio.py cerca "spese per il personale comunale"
    python archivio.py cerca "appalti rifiuti" -k 8 --sotto-soglia
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

BASE = "http://127.0.0.1:8000"
AVVIO = (r'powershell -NoProfile -ExecutionPolicy Bypass -File '
         r'"C:\Users\emili\.openclaw-autoclaw\agents\il-mio-coding-agent'
         r'\workspace\projects\semantic-news-search\run_server.ps1"')


def chiama(percorso: str, parametri: dict | None = None, timeout: int = 60) -> dict:
    import requests

    try:
        r = requests.get(BASE + percorso, params=parametri or {}, timeout=timeout)
    except Exception as e:
        sys.exit(
            f"Archivio Semantico non raggiungibile su {BASE} ({type(e).__name__}).\n"
            f"Avvia il server con:\n  {AVVIO}\n"
            "Il primo avvio carica il modello in memoria (20-80 s); poi le query sono immediate."
        )
    if r.status_code >= 400:
        try:
            errore = r.json().get("error", {}).get("message", r.text[:200])
        except Exception:
            errore = r.text[:200]
        sys.exit(f"errore dal servizio (HTTP {r.status_code}): {errore}")
    return r.json()


def stato() -> int:
    salute = chiama("/healthz", {"_": ""})
    print(f"servizio   : {BASE}")
    print(f"indice     : {'presente' if salute.get('index') else 'ASSENTE'}")
    print(f"documenti  : {salute.get('articles')}")
    print(f"modello    : {'caricato' if salute.get('model_loaded') else 'in caricamento'}")
    if salute.get("error"):
        print(f"errore     : {salute['error']}")
    try:
        s = chiama("/api/stats")
        print(f"backend    : {s.get('backend')} (dim {s.get('dim')})")
        print(f"soglia     : {s.get('threshold')}")
        print(f"creato il  : {s.get('created_at')}")
        if s.get("languages"):
            print(f"lingue     : {', '.join(s['languages'])}")
        if s.get("dates"):
            print(f"date       : {s['dates'].get('min')} -> {s['dates'].get('max')}")
    except SystemExit:
        raise
    except Exception as e:
        print(f"(statistiche non disponibili: {e})")
    return 0


def cerca(query: str, k: int, sotto_soglia: bool, categoria: str | None) -> int:
    param = {"q": query, "k": k}
    if sotto_soglia:
        param["below"] = "true"
    if categoria:
        param["category"] = categoria

    dati = chiama("/api/search", param)
    risultati = dati.get("results", [])
    meta = dati.get("meta", {})

    scope = ("sull'intero corpus" if meta.get("counts_scope") == "corpus"
             else f"su {meta.get('pool_size', '?')} esaminati")
    print(f"«{query}»")
    print(f"documenti nell'indice: {meta.get('articles_indexed')} | soglia {meta.get('threshold')} "
          f"| sopra soglia {meta.get('count_above')} {scope} | tempo {meta.get('took_ms')} ms")
    if not risultati:
        print("\nnessun risultato sopra soglia: la domanda è fuori dal dominio dell'archivio, "
              "oppure i documenti non sono stati indicizzati.")
        print("(l'assenza di risultati NON significa che il fatto non esista)")
        return 2

    for r in risultati:
        print(f"\n{r['rank']}. score {r['score']:.4f}  {r['title']}")
        riga = f"   {r.get('id')}"
        if r.get("source"):
            riga += f" · {r['source']}"
        if r.get("date"):
            riga += f" · {r['date']}"
        if r.get("category"):
            riga += f" · {r['category']}"
        print(riga)
        if r.get("snippet"):
            print(f"   {r['snippet'][:300]}")

    print("\n--- citazione ---")
    print(
        f"Archivio Semantico locale (modello google/embeddinggemma-2), indice di "
        f"{meta.get('articles_indexed')} documenti, query \"{query}\", "
        f"consultato il {dt.date.today().isoformat()}"
    )
    return 0


def principale() -> int:
    ap = argparse.ArgumentParser(description="Ricerca semantica nell'Archivio.")
    sub = ap.add_subparsers(dest="comando", required=True)
    sub.add_parser("stato", help="salute dell'indice e del modello")
    c = sub.add_parser("cerca", help="ricerca per concetto")
    c.add_argument("query")
    c.add_argument("-k", type=int, default=5)
    c.add_argument("--sotto-soglia", action="store_true", help="mostra anche i risultati deboli")
    c.add_argument("--categoria", help="filtra per categoria (economia, politica, ...)")
    args = ap.parse_args()

    if args.comando == "stato":
        return stato()
    return cerca(args.query, args.k, args.sotto_soglia, args.categoria)


if __name__ == "__main__":
    try:
        raise SystemExit(principale())
    except BrokenPipeError:
        import os
        os._exit(0)
