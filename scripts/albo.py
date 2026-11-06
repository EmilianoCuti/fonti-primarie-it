#!/usr/bin/env python
"""Raccoglie un albo pretorio o un elenco atti in una tabella verificabile.

Una sola chiamata invece di quaranta: scarica la pagina, trova i PDF, li scarica in
parallelo, estrae testo e campi (data, oggetto, importo, CIG) e produce un indice
markdown con la citazione di ogni atto.

Esempi:
    python albo.py "https://www.comune.xxx.it/albo-pretorio" --out-dir D:\\ricerche\\xyz
    python albo.py URL --filtro "determin" --max-atti 30
    python albo.py URL --solo-elenco          (non scarica i PDF, elenca soltanto)
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

RE_CIG = re.compile(r"(?i)\bcig\b[:\s]*([A-Z0-9]{10,12})\b")
RE_IMPORTO = re.compile(r"(?i)(?:euro|€)\s*([\d.]{1,12},\d{2})")
RE_DATA_NUM = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b")
RE_DATA_TEST = re.compile(r"\b(\d{1,2})\s+(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\s+(\d{4})\b", re.I)
RE_OGGETTO = re.compile(r"(?im)^\s*oggetto\s*[:\-]?\s*(.{5,200})$")
MESI = {m: i for i, m in enumerate(
    ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
     "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"], 1)}


def scarica(url: str, timeout: int = 60) -> bytes:
    import requests

    r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9"}, timeout=timeout)
    r.raise_for_status()
    return r.content


def link_pdf(html: str, base: str) -> list[str]:
    href = re.findall(r'href=["\']([^"\']+)["\']', html, flags=re.I)
    visti, out = set(), []
    for h in href:
        if not re.search(r"\.pdf(\?|$)", h, flags=re.I):
            continue
        u = urljoin(base, h)
        if u not in visti:
            visti.add(u)
            out.append(u)
    return out


def testo_rapido(pdf: Path) -> str:
    exe = shutil.which("pdftotext") or r"C:\Program Files\Git\mingw64\bin\pdftotext.exe"
    if Path(exe).exists():
        try:
            r = subprocess.run([exe, "-layout", "-enc", "UTF-8", str(pdf), "-"], capture_output=True, timeout=120)
            if r.returncode == 0 and r.stdout:
                return r.stdout.decode("utf-8", "replace")
        except Exception:
            pass
    try:
        import pymupdf as fitz
    except ImportError:
        try:
            import fitz  # type: ignore
        except ImportError:
            return ""
    try:
        doc = fitz.open(str(pdf))
        t = "\n".join(p.get_text("text") for p in doc)
        doc.close()
        return t
    except Exception:
        return ""


def campi(testo: str) -> dict:
    testa = testo[:4000]
    d = ""
    m = RE_DATA_TEST.search(testa)
    if m:
        d = f"{int(m.group(1)):02d}/{MESI[m.group(2).lower()]:02d}/{m.group(3)}"
    else:
        m = RE_DATA_NUM.search(testa)
        if m:
            d = m.group(0)
    imp = RE_IMPORTO.search(testa)
    cig = RE_CIG.search(testo)
    ogg = RE_OGGETTO.search(testa)
    return {
        "data": d,
        "oggetto": re.sub(r"\s+", " ", ogg.group(1)).strip()[:140] if ogg else "",
        "importo": imp.group(1) if imp else "",
        "cig": cig.group(1) if cig else "",
    }


def scarica_uno(url: str, cartella: Path) -> tuple[str, Path | None, str]:
    nome = re.sub(r"[^a-zA-Z0-9._-]+", "-", Path(urlparse(url).path).name)[-90:] or "atto.pdf"
    if not nome.lower().endswith(".pdf"):
        nome += ".pdf"
    dest = cartella / nome
    if dest.exists() and dest.stat().st_size > 1024:
        return url, dest, ""
    try:
        dati = scarica(url, timeout=90)
    except Exception as e:
        return url, None, str(e)
    if not dati.startswith(b"%PDF"):
        return url, None, "risposta non PDF (probabile pagina di errore o login)"
    dest.write_bytes(dati)
    return url, dest, ""


def principale() -> int:
    ap = argparse.ArgumentParser(description="Albo/elenco atti -> indice verificabile.")
    ap.add_argument("url")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--filtro", help="espressione regolare sul nome del PDF o sull'URL")
    ap.add_argument("--max-atti", type=int, default=40)
    ap.add_argument("--solo-elenco", action="store_true")
    ap.add_argument("--lavori", type=int, default=8)
    args = ap.parse_args()

    radice = Path(args.out_dir)
    atti = radice / "fonti" / "atti"
    atti.mkdir(parents=True, exist_ok=True)

    try:
        html = scarica(args.url).decode("utf-8", "replace")
    except Exception as e:
        print(f"ERRORE download pagina: {e}")
        return 1

    pdfs = link_pdf(html, args.url)
    if args.filtro:
        rx = re.compile(args.filtro, re.I)
        pdfs = [u for u in pdfs if rx.search(u)]
    totali = len(pdfs)
    pdfs = pdfs[: args.max_atti]
    print(f"PDF trovati nella pagina: {totali} | da scaricare: {len(pdfs)}")
    if not pdfs:
        print("nessun PDF: la pagina potrebbe caricare l'elenco via javascript. Usa browser_tool per l'elenco.")
        return 2
    if args.solo_elenco:
        for u in pdfs:
            print(" ", u)
        return 0

    with ThreadPoolExecutor(max_workers=max(1, args.lavori)) as pool:
        risultati = list(pool.map(lambda u: scarica_uno(u, atti), pdfs))

    righe = ["# Atti raccolti", "",
             f"- Pagina di partenza: {args.url}",
             f"- Raccolti il: {dt.date.today().isoformat()}",
             f"- PDF in elenco: {totali} | scaricati: {sum(1 for _, p, _ in risultati if p)}",
             "", "| data | oggetto | importo | CIG | file | URL |", "|---|---|---|---|---|---|"]
    errori = []
    for url, path, err in risultati:
        if not path:
            errori.append(f"{url} -> {err}")
            continue
        c = campi(testo_rapido(path))
        righe.append(
            f"| {c['data'] or '—'} | {c['oggetto'] or '—'} | {c['importo'] or '—'} | {c['cig'] or '—'} "
            f"| `{path.name}` | {url} |"
        )

    indice = radice / "dati" / "indice-atti.md"
    indice.parent.mkdir(parents=True, exist_ok=True)
    indice.write_text("\n".join(righe) + "\n", encoding="utf-8")

    print(f"\nindice: {indice}")
    print(f"atti salvati in: {atti}")
    if errori:
        print(f"\nNON scaricati ({len(errori)}):")
        for e in errori[:15]:
            print(" ", e)
        if len(errori) > 15:
            print(f"  ... e altri {len(errori) - 15}")
    print("\n--- citazione ---")
    print(f"{args.url} | consultato il {dt.date.today().isoformat()} | {sum(1 for _, p, _ in risultati if p)} atti archiviati")
    return 0


if __name__ == "__main__":
    raise SystemExit(principale())
