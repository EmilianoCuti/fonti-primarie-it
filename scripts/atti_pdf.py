#!/usr/bin/env python
"""Testo, tabelle e citazione da PDF italiani (atti, delibere, bilanci, sentenze).

Strategia a cascata, dalla piu veloce alla piu costosa:
  1. pdftotext -layout  (~60 ms, binario gia installato)
  2. PyMuPDF            (solo per le pagine rimaste vuote)
  3. OCR Tesseract      (200 dpi, poi 300 dpi solo se il testo resta scarso)

Esempi:
    python atti_pdf.py delibera.pdf
    python atti_pdf.py atto.pdf --pages 3-7 --out atto.md
    python atti_pdf.py --dir D:\\ricerche\\xyz\\fonti --out-dir D:\\ricerche\\xyz\\dati
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SOGLIA_TESTO = 40       # caratteri minimi per considerare una pagina "letta" dalla cascata rapida
SOGLIA_OCR_OK = 30      # se a 200 dpi escono almeno questi caratteri, non si sale a 300
DPI_BASE = 200          # primo tentativo OCR
DPI_RIPRESA = 300       # solo se a 200 dpi il testo resta scarso


# ---------------------------------------------------------------- pdftotext

def eseguibile_pdftotext() -> str | None:
    exe = shutil.which("pdftotext")
    if exe:
        return exe
    for candidato in (
        r"C:\Program Files\Git\mingw64\bin\pdftotext.exe",
        r"C:\Program Files\Git\usr\bin\pdftotext.exe",
    ):
        if Path(candidato).exists():
            return candidato
    return None


def testo_pdftotext(pdf: Path) -> list[str] | None:
    exe = eseguibile_pdftotext()
    if not exe:
        return None
    try:
        r = subprocess.run(
            [exe, "-layout", "-enc", "UTF-8", str(pdf), "-"],
            capture_output=True, timeout=180,
        )
    except Exception:
        return None
    if r.returncode != 0 or not r.stdout:
        return None
    pagine = r.stdout.decode("utf-8", "replace").split("\f")
    if pagine and not pagine[-1].strip():
        pagine.pop()
    return pagine


# ---------------------------------------------------------------- PyMuPDF / OCR

def apri_pdf(pdf: Path):
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz  # type: ignore
    return fitz.open(str(pdf))


def ocr_pagina(page, dpi: int, lang: str | None) -> str:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""
    pix = page.get_pixmap(dpi=dpi)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    try:
        return pytesseract.image_to_string(img, lang=lang) if lang else pytesseract.image_to_string(img)
    except Exception:
        return pytesseract.image_to_string(img)


def parse_pages(spec: str | None, totale: int) -> list[int]:
    if not spec:
        return list(range(totale))
    pagine: list[int] = []
    for pezzo in spec.split(","):
        pezzo = pezzo.strip()
        if not pezzo:
            continue
        if "-" in pezzo:
            a, b = pezzo.split("-", 1)
            pagine.extend(range(int(a) - 1, int(b)))
        else:
            pagine.append(int(pezzo) - 1)
    return [p for p in pagine if 0 <= p < totale]


def tabelle_pagina(pdf_path: Path, numero: int) -> list[list[list[str]]]:
    try:
        import pdfplumber
    except ImportError:
        return []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            if numero - 1 >= len(pdf.pages):
                return []
            return pdf.pages[numero - 1].extract_tables() or []
    except Exception:
        return []


# ---------------------------------------------------------------- elaborazione

def elabora(pdf: Path, pagine_spec: str | None = None, ocr: bool = True,
            lang: str = "ita", tabelle: bool = False) -> dict:
    """Restituisce dettagli + markdown di un PDF. Nessuna stampa: usabile in batch."""
    if not pdf.exists():
        return {"file": pdf, "errore": "file non trovato", "md": "", "stats": {}}

    rapido = testo_pdftotext(pdf) or []
    totale = len(rapido)
    stato = {"doc": None}

    def documento():
        """PyMuPDF si apre solo se una pagina ne ha davvero bisogno."""
        if stato["doc"] is None:
            stato["doc"] = apri_pdf(pdf)
        return stato["doc"]

    if totale == 0:
        try:
            totale = documento().page_count
        except Exception as e:
            return {"file": pdf, "errore": f"PDF illeggibile: {e}", "md": "", "stats": {}}

    da_leggere = parse_pages(pagine_spec, totale)
    if not da_leggere:
        if stato["doc"]:
            stato["doc"].close()
        return {"file": pdf, "errore": f"intervallo pagine non valido su {totale}", "md": "", "stats": {}}

    righe = [f"# {pdf.name}", ""]
    nativi, da_pymupdf, ocrizzate, vuote = [], [], [], []

    for i in da_leggere:
        testo = (rapido[i] if i < len(rapido) else "").strip()
        modo = "pdftotext" if testo else "senza testo"

        if len(testo) < SOGLIA_TESTO:
            page = None
            try:
                page = documento().load_page(i)
                candidato = (page.get_text("text") or "").strip()
            except Exception:
                candidato = ""
            if len(candidato) > len(testo):
                testo, modo = candidato, "pymupdf"
                da_pymupdf.append(i + 1)

            if len(testo) < SOGLIA_TESTO and ocr and page is not None:
                letto, dpi_usato = "", DPI_BASE
                for dpi in (DPI_BASE, DPI_RIPRESA):
                    try:
                        l = (ocr_pagina(page, dpi, lang) or "").strip()
                    except Exception:
                        l = ""
                    if len(l) > len(letto):
                        letto, dpi_usato = l, dpi
                    if len(l) >= SOGLIA_OCR_OK:
                        break
                if len(letto) > len(testo):
                    testo, modo = letto, f"OCR {dpi_usato}dpi"
                    ocrizzate.append(i + 1)

        if not testo:
            vuote.append(i + 1)
            modo = "vuota"
        elif modo == "pdftotext":
            nativi.append(i + 1)

        righe.append(f"\n## p. {i + 1}  ({modo})\n")
        righe.append(testo if testo else "_[pagina senza testo estratto]_")

        if tabelle:
            for t_i, tab in enumerate(tabelle_pagina(pdf, i + 1), 1):
                righe.append(f"\n**Tabella {t_i} a p. {i + 1}**\n")
                for n_r, r in enumerate(tab):
                    celle = [re.sub(r"\s+", " ", (c or "")).strip() for c in r]
                    righe.append("| " + " | ".join(celle) + " |")
                    if n_r == 0:
                        righe.append("|" + "---|" * len(celle))

    if stato["doc"]:
        stato["doc"].close()

    stats = {
        "pagine": len(da_leggere),
        "pdftotext": len(nativi),
        "pymupdf": len(da_pymupdf),
        "ocr": len(ocrizzate),
        "vuote": len(vuote),
        "motore": "pdftotext" if nativi else ("pymupdf" if da_pymupdf else "ocr"),
    }
    citazione = (
        f"{pdf} | pagine {da_leggere[0] + 1}"
        + (f"-{da_leggere[-1] + 1}" if len(da_leggere) > 1 else "")
        + f" | pdftotext {len(nativi)} | pymupdf {len(da_pymupdf)} | OCR {len(ocrizzate)}"
        + f" | vuote {len(vuote)} | consultato il {dt.date.today().isoformat()}"
    )
    return {"file": pdf, "md": "\n".join(righe), "stats": stats, "citazione": citazione, "errore": None}


def principale() -> int:
    ap = argparse.ArgumentParser(description="Testo, tabelle e citazione da PDF.")
    ap.add_argument("pdf", nargs="?", help="file singolo")
    ap.add_argument("--dir", help="cartella con piu PDF (batch)")
    ap.add_argument("--pages", help="es. 3-7 oppure 1,4,9 (default: tutte)")
    ap.add_argument("--out", help="file markdown di destinazione (singolo)")
    ap.add_argument("--out-dir", help="cartella di destinazione (batch)")
    ap.add_argument("--no-ocr", action="store_true")
    ap.add_argument("--lang", default="ita")
    ap.add_argument("--tabelle", action="store_true")
    ap.add_argument("--lavori", type=int, default=3, help="PDF in parallelo nel batch (default 3)")
    args = ap.parse_args()

    if not args.pdf and not args.dir:
        ap.error("serve un PDF oppure --dir")

    if args.dir:
        cartella = Path(args.dir)
        if not cartella.is_dir():
            sys.exit(f"cartella non trovata: {cartella}")
        files = sorted(p for p in cartella.rglob("*.pdf") if p.is_file())
        if not files:
            sys.exit(f"nessun PDF in {cartella}")
        uscita = Path(args.out_dir or cartella / "testo")
        uscita.mkdir(parents=True, exist_ok=True)

        with ThreadPoolExecutor(max_workers=max(1, args.lavori)) as pool:
            risultati = list(pool.map(
                lambda f: elabora(f, args.pages, not args.no_ocr, args.lang, args.tabelle), files
            ))

        indice = ["# Indice dei documenti elaborati", "",
                  f"Cartella: `{cartella}`  ", f"Data: {dt.date.today().isoformat()}", "",
                  "| file | pagine | pdftotext | pymupdf | OCR | vuote | uscita |",
                  "|---|---|---|---|---|---|---|"]
        errori = []
        for r in risultati:
            nome = r["file"].stem + ".md"
            if r["errore"]:
                errori.append(f"{r['file'].name}: {r['errore']}")
                continue
            (uscita / nome).write_text(r["md"], encoding="utf-8")
            s = r["stats"]
            indice.append(
                f"| {r['file'].name} | {s['pagine']} | {s['pdftotext']} | {s['pymupdf']} | {s['ocr']} | {s['vuote']} | {nome} |"
            )
        (uscita / "_indice.md").write_text("\n".join(indice) + "\n", encoding="utf-8")

        print(f"elaborati {len(risultati) - len(errori)} PDF su {len(files)}")
        print(f"indice: {uscita / '_indice.md'}")
        for r in risultati:
            if not r["errore"]:
                print(" ", r["citazione"])
        if errori:
            print("\nERRORI:")
            for e in errori:
                print(" ", e)
            return 1
        return 0

    pdf = Path(args.pdf)
    if not pdf.exists():
        sys.exit(f"file non trovato: {pdf}")
    r = elabora(pdf, args.pages, not args.no_ocr, args.lang, args.tabelle)
    if r["errore"]:
        sys.exit(r["errore"])
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(r["md"], encoding="utf-8")
        print(f"[scritto] {out}  ({len(r['md'])} caratteri)")
    else:
        print(r["md"])
    print("\n--- citazione ---")
    print(r["citazione"])
    if r["stats"]["vuote"]:
        print(f"ATTENZIONE: pagine senza testo estratto -> vedi il markdown")
    return 0


if __name__ == "__main__":
    raise SystemExit(principale())
