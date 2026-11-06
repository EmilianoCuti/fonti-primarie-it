#!/usr/bin/env python
"""Tabelle da PDF con Docling, eseguito su un server pubblico: zero RAM locale.

Perche serve: pdftotext e pdfplumber leggono il testo e spesso sfaldano le tabelle;
Jina Reader appiattisce le tabelle in paragrafi (misurato: 0 righe tabellari su un PDF
con tre tabelle). Docling ricostruisce righe e colonne, ma in locale richiede PyTorch
e 2-4 GB di RAM. Qui il lavoro lo fa uno Space pubblico che esegue l'immagine Docker
ufficiale docling-serve.

    ATTENZIONE ALLA RISERVATEZZA: il documento viene inviato a un servizio comunitario
    di terzi. Non usarlo su atti riservati, documenti non pubblicati o dati personali.
    Per quelli: --solo-locale (pdfplumber) oppure self-host di docling-serve.

Esempi:
    python tabelle.py delibera.pdf
    python tabelle.py https://www.comune.xxx.it/atti/bilancio.pdf --out dati/bilancio.md
    python tabelle.py atto.pdf --solo-locale
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

SERVIZIO = "https://Bibyutatsu-HF-docling-serve.hf.space"
AVVISO = ("estrazione eseguita su servizio esterno (docling-serve su Hugging Face Space): "
          "il documento e stato inviato a un terzo")


# ------------------------------------------------------------ docling remoto

def _attendi(tentativo: int, motivo: str = "") -> None:
    attesa = min(30 * (2 ** (tentativo - 1)), 120)
    dettaglio = f" ({motivo})" if motivo else ""
    print(f"  servizio non disponibile{dettaglio}, attendo {attesa}s ...")
    time.sleep(attesa)


def docling_remoto(origine: str, tentativi: int = 4, timeout: int = 600,
                   pages: list[int] | None = None) -> tuple[str, dict]:
    """origine: percorso locale oppure URL http(s). Restituisce (markdown, info)."""
    import requests

    dati: dict = {}
    if pages:
        dati["page_range"] = pages

    ultimo = None
    for n in range(1, tentativi + 1):
        try:
            if origine.lower().startswith("http"):
                r = requests.post(
                    SERVIZIO + "/v1/convert/source",
                    json={"sources": [{"kind": "http", "url": origine}], **dati},
                    timeout=timeout,
                )
            else:
                with open(origine, "rb") as f:
                    r = requests.post(
                        SERVIZIO + "/v1/convert/file",
                        files={"files": (Path(origine).name, f, "application/pdf")},
                        data={k: str(v) for k, v in dati.items()},
                        timeout=timeout,
                    )
            if r.status_code == 200:
                corpo = r.json()
                md = corpo.get("document", {}).get("md_content", "")
                return md, {"metodo": "docling remoto", "status": 200,
                            "pagine": corpo.get("document", {}).get("page_count") or corpo.get("page_count")}
            if r.status_code in (429, 502, 503, 504):
                ultimo = f"HTTP {r.status_code}: {r.text[:150]}"
                if n < tentativi:
                    motivo = "limite di 2 richieste al minuto" if r.status_code == 429 else "servizio non pronto o in avvio"
                    _attendi(n, motivo)
                    continue
            return "", {"metodo": "docling remoto", "errore": f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as e:
            ultimo = f"{type(e).__name__}: {str(e)[:150]}"
            if n < tentativi:
                _attendi(n)
                continue
    return "", {"metodo": "docling remoto", "errore": ultimo or "errore sconosciuto"}


# ------------------------------------------------------------ fallback locale

def pdfplumber_locale(pdf: str, pages: list[int] | None = None) -> tuple[str, dict]:
    try:
        import pdfplumber
    except ImportError:
        return "", {"metodo": "pdfplumber", "errore": "pdfplumber non installato"}

    righe = []
    n_tab = 0
    with pdfplumber.open(pdf) as doc:
        indici = [p - 1 for p in pages] if pages else range(len(doc.pages))
        for i in indici:
            if i >= len(doc.pages):
                continue
            page = doc.pages[i]
            righe.append(f"\n## p. {i + 1}\n")
            testo = (page.extract_text() or "").strip()
            if testo:
                righe.append(testo)
            for t in page.extract_tables() or []:
                n_tab += 1
                righe.append(f"\n**Tabella {n_tab} (p. {i + 1})**\n")
                for n_r, r in enumerate(t):
                    celle = [(c or "").replace("\n", " ").strip() for c in r]
                    righe.append("| " + " | ".join(celle) + " |")
                    if n_r == 0:
                        righe.append("|" + "---|" * len(celle))
    return "\n".join(righe), {"metodo": "pdfplumber locale", "tabelle": n_tab}


def conta_tabelle(md: str) -> int:
    """Righe di dati dentro una tabella: almeno 3 pipe e non riga di separazione."""
    n = 0
    for r in md.splitlines():
        s = r.strip()
        if s.count("|") < 3:
            continue
        if set(s) <= set("|-: "):
            continue
        n += 1
    return n


# ------------------------------------------------------------ main

def principale() -> int:
    ap = argparse.ArgumentParser(description="Tabelle da PDF: Docling remoto, fallback locale.")
    ap.add_argument("origine", help="percorso del PDF oppure URL http(s)")
    ap.add_argument("--out", help="file markdown di destinazione")
    ap.add_argument("--pages", help="es. 3-7 (1-based)")
    ap.add_argument("--solo-locale", action="store_true", help="usa solo pdfplumber, nessun invio a terzi")
    ap.add_argument("--tentativi", type=int, default=4)
    args = ap.parse_args()

    pagine = None
    if args.pages:
        pagine = []
        for pezzo in args.pages.split(","):
            if "-" in pezzo:
                a, b = pezzo.split("-", 1)
                pagine.extend(range(int(a), int(b) + 1))
            else:
                pagine.append(int(pezzo))

    locale = not args.origine.lower().startswith("http")
    if locale and not Path(args.origine).exists():
        sys.exit(f"file non trovato: {args.origine}")

    md, info = "", {}
    if not args.solo_locale:
        print("invio a Docling remoto ...")
        md, info = docling_remoto(args.origine, args.tentativi, pages=pagine)
        if info.get("errore"):
            print(f"  non riuscito: {info['errore']}")

    if not md.strip():
        if not locale:
            sys.exit("servizio non disponibile e nessun fallback possibile su un URL: riprova piu tardi")
        print("ricado su pdfplumber in locale")
        md, info = pdfplumber_locale(args.origine, pagine)
        info["nota"] = "fallback locale: tabelle meno precise, nessun dato inviato a terzi"

    n_tab = conta_tabelle(md)
    intestazione = [
        f"# {Path(args.origine).name if locale else args.origine}",
        "",
        f"- Fonte: {args.origine}",
        f"- Estratto il: {dt.date.today().isoformat()}",
        f"- Metodo: {info.get('metodo', '?')}",
        f"- Righe tabellari riconosciute: {n_tab}",
    ]
    if info.get("metodo") == "docling remoto":
        intestazione.append(f"- Avvertenza: {AVVISO}")
    if info.get("nota"):
        intestazione.append(f"- Nota: {info['nota']}")
    if pagine:
        intestazione.append(f"- Pagine richieste: {args.pages}")

    contenuto = "\n".join(intestazione) + "\n\n" + md

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(contenuto, encoding="utf-8")
        print(f"[scritto] {out}  ({len(contenuto)} caratteri, {n_tab} righe tabellari)")
    else:
        try:
            print(contenuto)
        except BrokenPipeError:
            pass

    print("\n--- citazione ---")
    data = info.get("pagine")
    print(
        f"{args.origine} | metodo {info.get('metodo')} | "
        + (f"{data} pagine | " if data else "")
        + f"{n_tab} righe tabellari | estratto il {dt.date.today().isoformat()}"
    )
    if n_tab == 0:
        print("ATTENZIONE: nessuna tabella riconosciuta. Se l'atto ne contiene, verifica a mano.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(principale())
    except BrokenPipeError:
        import os
        os._exit(0)
