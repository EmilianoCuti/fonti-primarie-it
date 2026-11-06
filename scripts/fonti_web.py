#!/usr/bin/env python
"""Pagina di un ente -> testo pulito, data di pubblicazione, link ai documenti.

Conserva sempre l'HTML originale: se la pagina cambia, la copia resta come prova.

Esempi:
    python fonti_web.py "https://www.comune.lodi.it/albo-pretorio" --out-dir D:\\ricerche\\xyz\\fonti
    python fonti_web.py URL --no-html        (solo testo, niente archivio)
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def scarica(url: str) -> tuple[str, str]:
    import requests

    r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9"}, timeout=45)
    r.raise_for_status()
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding
    return r.text, r.url


def estrai(html: str) -> tuple[str, dict]:
    import trafilatura

    md = trafilatura.extract(
        html,
        output_format="markdown",
        include_tables=True,
        include_links=True,
        include_comments=False,
        favor_recall=True,
    ) or ""
    meta = trafilatura.extract_metadata(html)
    dati = {}
    if meta is not None:
        dati = {
            "titolo": getattr(meta, "title", None) or "",
            "data": getattr(meta, "date", None) or "",
            "sito": getattr(meta, "sitename", None) or "",
        }
    return md, dati


def documenti(html: str, base: str) -> list[str]:
    """Link a PDF e atti, che sono quasi sempre il vero documento."""
    link = re.findall(r'href=["\']([^"\']+)["\']', html, flags=re.I)
    tenuti = []
    for l in link:
        if re.search(r"\.(pdf|p7m|docx?|xlsx?)(\?|$)", l, flags=re.I):
            tenuti.append(l if l.startswith("http") else base.rstrip("/") + "/" + l.lstrip("/"))
    visti, unici = set(), []
    for x in tenuti:
        if x not in visti:
            visti.add(x)
            unici.append(x)
    return unici


def utile(testo: str) -> tuple[int, float]:
    """Parole reali e quota di righe che sono solo link.

    La lunghezza da sola inganna: la home di un ente puo produrre 5.000 caratteri di menu
    e nessuna informazione. Conta il testo, non il markup.
    """
    righe = [r for r in testo.splitlines() if r.strip()]
    if not righe:
        return 0, 0.0
    link = sum(1 for r in righe if "](" in r)
    senza_url = re.sub(r"\]\([^)]*\)", " ", testo)
    parole = len(re.findall(r"[A-Za-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u00ff]{3,}", senza_url))
    return parole, link / len(righe)


def via_jina(url: str, timeout: int = 120) -> tuple[str, dict]:
    """Fallback per pagine che trafilatura riduce a nulla (JS, portali a cornice, PDF).

    ATTENZIONE: l'URL viene inviato a un terzo (r.jina.ai). Mai usarci link riservati,
    documenti non pubblici o indirizzi con token di sessione.
    """
    import requests

    r = requests.get(
        "https://r.jina.ai/" + url,
        headers={"X-Return-Format": "markdown", "User-Agent": UA},
        timeout=timeout,
    )
    r.raise_for_status()
    testo = r.text
    meta: dict = {}
    if testo.lstrip().startswith("Title:"):
        testa, _, corpo = testo.partition("Markdown Content:")
        for riga in testa.splitlines():
            if ":" in riga:
                k, v = riga.split(":", 1)
                meta[k.strip().lower()] = v.strip()
        testo = corpo
    return testo.strip(), meta


def principale() -> int:
    ap = argparse.ArgumentParser(description="Testo pulito e citazione da una pagina web.")
    ap.add_argument("url")
    ap.add_argument("--out-dir", help="cartella dove salvare testo e HTML")
    ap.add_argument("--no-html", action="store_true", help="non salvare l'HTML originale")
    ap.add_argument("--motore", choices=["auto", "trafilatura", "jina"], default="auto",
                    help="auto = trafilatura, con Jina Reader se il testo estratto e scarso")
    ap.add_argument("--soglia-parole", type=int, default=250,
                    help="sotto queste parole utili si riprova con Jina (default 250)")
    ap.add_argument("--max-link", type=float, default=0.5,
                    help="oltre questa quota di righe-link il testo e considerato menu (default 0.5)")
    args = ap.parse_args()

    try:
        html, finale = scarica(args.url)
    except Exception as e:
        print(f"ERRORE download: {e}")
        return 1

    testo, meta = estrai(html)
    motore = "trafilatura"
    meta_jina: dict = {}

    parole, quota_link = utile(testo)
    scarso = parole < args.soglia_parole or quota_link > args.max_link

    if args.motore == "jina" or (args.motore == "auto" and scarso):
        print(f"(testo trafilatura: {parole} parole utili, {quota_link:.0%} righe-link -> provo Jina)")
        try:
            alternativo, meta_jina = via_jina(finale)
            p2, q2 = utile(alternativo)
            if p2 > parole:
                testo, motore = alternativo, "jina"
        except Exception as e:
            print(f"(Jina non disponibile: {e})")

    if not testo.strip():
        print("ATTENZIONE: nessun testo principale estratto (pagina a cornice, PDF o blocco anti-bot).")
        testo = ""

    base = f"{urlparse(finale).scheme}://{urlparse(finale).netloc}"
    docs = documenti(html, base)

    data_rif = meta.get("data") or meta_jina.get("published time", "")
    sha = hashlib.sha256(html.encode("utf-8", "ignore")).hexdigest()[:12]

    if args.out_dir:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        nome = re.sub(r"[^a-zA-Z0-9]+", "-", urlparse(finale).path.strip("/"))[:60] or \
            re.sub(r"[^a-zA-Z0-9]+", "-", urlparse(finale).netloc)[:60] or "pagina"
        (out / f"{nome}.md").write_text(
            f"# {meta.get('titolo') or args.url}\n\n"
            f"- URL: {finale}\n- Consultato: {dt.date.today().isoformat()}\n"
            f"- Data dichiarata: {data_rif or 'non dichiarata'}\n- SHA256 HTML: {sha}\n"
            f"- Motore di estrazione: {motore}\n\n{testo}\n",
            encoding="utf-8",
        )
        if not args.no_html:
            (out / f"{nome}.html").write_text(html, encoding="utf-8")
        print(f"[salvato] {out / (nome + '.md')}" + ("" if args.no_html else f" + {nome}.html"))

    print(testo)
    if docs:
        print("\n--- documenti linkati (il vero atto è spesso qui) ---")
        for d in docs[:40]:
            print(" ", d)

    print("\n--- citazione ---")
    print(
        f"{finale} | titolo: {meta.get('titolo') or 'n/d'} | data dichiarata: {data_rif or 'n/d'} "
        f"| consultato il {dt.date.today().isoformat()} | sha256(html) {sha} | estratto con {motore}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(principale())
    except BrokenPipeError:
        import os
        os._exit(0)
