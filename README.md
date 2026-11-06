# Fonti primarie

Nove strumenti a riga di comando per il giornalismo investigativo italiano: albi pretori,
delibere, bilanci, sedute consiliari, demografia ISTAT.

Ogni comando stampa, oltre al risultato, la **riga di citazione** da incollare nel dossier:
percorso o URL, data di consultazione, numero di pagina.

Nessuna chiave API, nessun servizio cloud, nessun costo. Tutto gira in locale.

## Strumenti

| Script | A cosa serve |
|---|---|
| `albo.py` | albo pretorio o elenco atti: pagina -> link PDF -> download parallelo -> indice tabellare |
| `atti_pdf.py` | testo per pagina da PDF, con cascata `pdftotext` -> PyMuPDF -> OCR 200/300 dpi |
| `tabelle.py` | tabelle e bilanci con Docling remoto (zero RAM locale), fallback `pdfplumber` |
| `dati_query.py` | SQL e controlli numerici su CSV/Parquet con DuckDB |
| `fonti_web.py` | pagina della PA -> testo pulito + data, fallback Jina Reader per i portali JS |
| `wayback_prova.py` | snapshot datati dell'Internet Archive: cosa diceva la pagina, e se oggi non lo dice piu |
| `istat_comune.py` | tracciati ufficiali ISTAT per comune, con verifica di continuita tra anni |
| `archivio.py` | client per un indice semantico locale (8.612 documenti, `embeddinggemma-2`) |
| `social.py` | Telegram, Bluesky, YouTube senza chiavi; sottotitoli delle sedute |

Documentazione completa: [SKILL.md](SKILL.md).

## Installazione

Python 3.11 e sei dipendenze:

```
uv venv --python 3.11 D:\fonti-primarie\.venv
uv pip install --python D:\fonti-primarie\.venv\Scripts\python.exe ^
   trafilatura duckdb pytesseract pdfplumber pymupdf beautifulsoup4 yt-dlp
```

Servono anche due binari gratuiti: **Tesseract** (OCR, con lingua italiana) e
**pdftotext** (incluso in Git for Windows o Poppler).

## Esempio

```
python atti_pdf.py delibera.pdf --out delibera.md
# --- citazione ---
# delibera.pdf | pagine 1-4 | pdftotext 4 | pymupdf 0 | OCR 0 | vuote 0 | consultato il 2026-11-05
```

```
python istat_comune.py --comune Lodi --sigla LO --anni 2023-2024
# 2023: 44.843 al 1/1 -> 45.158 al 31/12
# 2024: 45.158 al 1/1  (continuita verificata)
```

## Numeri misurati

| Operazione | Prima | Dopo |
|---|---|---|
| 1 PDF con testo nativo | 3.238 ms | 536 ms |
| 6 PDF in batch | 3.310 ms | 2.540 ms |
| `group by` su 200.000 righe | 158 ms (CSV) | 5 ms (Parquet) |
| Righe tabellari da PDF | 0 (Jina) | 51 (Docling) |

## Principi

1. L'assenza di un dato non e zero: si dichiara "non disponibile".
2. Se due fonti divergono si riportano entrambe, senza mediarle.
3. Nessun nome, importo o accusa senza il documento che lo prova.
4. I documenti riservati non vanno a servizi di terzi: esiste la modalita locale.
5. Un post social e una traccia, non una prova.

## Licenza

MIT. Vedi [LICENSE](LICENSE).
