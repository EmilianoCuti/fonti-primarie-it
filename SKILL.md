---
name: fonti-primarie-it
description: "Raccolta e verifica di fonti primarie italiane per giornalismo investigativo: atti e delibere in PDF (testo e tabelle, con numero di pagina), albi pretori e siti della PA (testo pulito + data di pubblicazione), prova delle modifiche di una pagina via Internet Archive, serie demografiche ISTAT per comune, e conteggi automatici su CSV di appalti e bilanci. Usa quando devi documentare un fatto con un atto, contare righe di un elenco, o provare cosa diceva un portale in una data."
---

# Fonti primarie italiane

Strumenti locali che trasformano un atto o un portale in una citazione verificabile.
Regola unica: nessuno script produce solo testo, ognuno stampa anche la **riga di citazione**
(URL o percorso, data, pagina) da incollare nel dossier.

## Ambiente

Interprete dedicato (non il Python del runtime, che un aggiornamento dell'app può sovrascrivere):

```
D:\Progetti\fonti-it\.venv\Scripts\python.exe
```

Installato e verificato il 4 novembre 2026 (Python 3.11.9):

trafilatura 2.3.1 · duckdb 2.0.0 · pytesseract 0.3.13 · pdfplumber 0.11.10 · pymupdf 2.1 ·
arelle 2.2 · python-documentcloud 3.0.0 · datasette 0.65.5 · requests · lxml · pillow ·
beautifulsoup4 4.15 · **yt-dlp 2026.10.26** (ne esiste anche una copia in Hermes, 2026.08.19:
lo script usa la prima che trova, PATH compreso)

Fuori dal venv, già presenti sulla macchina: **Tesseract** (`C:\Program Files\Tesseract-OCR`,
con lingua `ita`), **markitdown 0.1.6** in `D:\Progetti\Markitdown\.venv` (invocabile come
`markitdown.cmd`, che è nel PATH via `D:\npm-global`), **pdftotext** (Git mingw64).

Tutti gli script stanno in `scripts\` di questa skill. Esegui sempre con quel percorso assoluto:
gli altri Python della macchina non hanno queste librerie.

## Verificato il 4 novembre 2026 (test reali)

- `atti_pdf.py` su PDF con testo nativo: 1 pagina, testo nativo 1, OCR 0.
- `atti_pdf.py` su PDF di sola immagine: riconosce `OCR necessario`, estrae correttamente il testo
  (“ATTO SCANSIONATO - PROT. 2026/4471”).
- `istat_comune.py --comune Lodi --sigla LO --anni 2023-2024`: 60 comuni nel file, popolazione
  al 1/1/2023 44.843 → 31/12/2023 45.158 → 31/12/2024 45.357. La continuità tra gli anni
  (45.158 = chiusura 2023 = apertura 2024) conferma che il tracciato è letto correttamente.
- `wayback_prova.py` su `istat.it`: snapshot del 18/12/2024, stringa trovata con contesto.
- `dati_query.py` su CSV di prova: 5 righe, 1 nullo segnalato, 1 duplicato su CIG, somma 608.000,50.
- `albo.py` su albo di prova: 3 PDF trovati, 3 scaricati, indice con data `14/03/2026`, oggetto e
  importo `248.500,00` estratti correttamente; 1,4 s in tutto.

## Prestazioni misurate (4 novembre 2026)

| Operazione | Prima | Dopo |
|---|---|---|
| 1 PDF con testo nativo | 3.238 ms | **536 ms** |
| 6 PDF (4 con testo, 2 scansioni) in batch | 3.310 ms | **2.540 ms** (e con OCR funzionante) |
| 1 pagina scansionata (nuovo processo) | 2.750 ms senza esito | **4.903 ms con testo estratto** |
| `group by` su 200.000 righe | 158 ms (CSV) | **5 ms** (Parquet) |
| PDF con 3 tabelle: righe tabellari | 0 (Jina) | **51** (Docling remoto) |

Il caso "scansione" sembra peggiorato solo perché prima falliva: il costo è l'avvio di PyMuPDF
(3,1 s) più Tesseract, che restano pagati una volta per processo. In batch si ammortizzano.

## Script

### `atti_pdf.py` — atto o delibera in PDF
Estrae testo per pagina, riconosce le pagine scansionate e fa OCR, prova a leggere le tabelle.
Stampa la citazione con il numero di pagina esatto.

```
python atti_pdf.py "D:\ricerche\xyz\fonti\delibera.pdf" --out "D:\ricerche\xyz\dati\delibera.md"
python atti_pdf.py atto.pdf --pages 3-7
```

Da usare prima di qualsiasi altra cosa su un PDF. La cascata è automatica e va dalla via più
veloce alla più costosa: `pdftotext -layout` (~60 ms, binario già installato), poi PyMuPDF solo
sulle pagine rimaste vuote, poi OCR Tesseract a 200 dpi e a 300 dpi solo se il testo resta
scarno. Non serve decidere a mano: la citazione dice per ogni pagina quale strada ha usato
(`pdftotext n | pymupdf n | OCR n | vuote n`).

Batch su una cartella, con l'indice di tutti i documenti e le citazioni:

```
python atti_pdf.py --dir "D:\ricerche\xyz\fonti" --out-dir "D:\ricerche\xyz\dati" --lavori 3
```

### `tabelle.py` — tabelle e bilanci, senza installare nulla
Docling ricostruisce righe e colonne dove `pdfplumber` si arrende (celle unite, griglie senza
bordi, PDF a due colonne). Gira **su un server pubblico**, quindi non occupa RAM né disco:
lo Space esegue l'immagine Docker ufficiale `docling-serve`.

```
python tabelle.py bilancio.pdf --out "D:\ricerche\xyz\dati\bilancio.md"
python tabelle.py https://www.comune.xxx.it/atti/rendiconto.pdf --pages 4-12
python tabelle.py atto.pdf --solo-locale        (nessun invio a terzi, usa pdfplumber)
```

Misurato il 4 novembre 2026 sullo stesso PDF con tre tabelle: **51 righe tabellari** con Docling
contro **0** con Jina Reader, che le appiattisce in paragrafi. Tempo: 13 s per un atto di una
pagina, 72-90 s per 15 pagine. Limiti del servizio: 2 richieste al minuto, massimo 3 elaborazioni
contemporanee, avvio a freddo 2-5 minuti dopo 48 ore di inattività (lo script aspetta e riprova).

**Riservatezza**: il documento viene inviato a un servizio comunitario di terzi. Mai usarlo su
atti riservati o non pubblicati: in quel caso `--solo-locale`, accettando tabelle meno precise.
Il markdown prodotto dichiara sempre il metodo usato e l'avvertenza.

### `archivio.py` — ricerca per concetto nei documenti già indicizzati
Interroga l'**Archivio Semantico** già presente sulla macchina (progetto `newssearch`,
modello `google/embeddinggemma-2`, indice Chroma a 768 dimensioni), che tiene il modello
in memoria e risponde in 0,2-0,6 s.

```
# prima il server (una volta sola, 80 s di avvio, ~620 MB di RAM)
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\emili\.openclaw-autoclaw\agents\il-mio-coding-agent\workspace\projects\semantic-news-search\run_server.ps1"

python archivio.py stato
python archivio.py cerca "spese per il personale nei comuni" -k 5
python archivio.py cerca "appalti rifiuti" --categoria economia
```

**Non usare la CLI del progetto per cercare**: `python -m newssearch.cli search` ricarica il
modello a ogni invocazione e impiega ~105 secondi. Il server lo carica una volta sola.

**Regola di metodo**: la ricerca semantica trova documenti *pertinenti*, non fatti *provati*.
Un risultato è una pista da risalire all'atto, non una fonte. E l'assenza di risultati non
dimostra che il fatto non esista: dimostra solo che l'indice non lo contiene.

**Stato al 5 novembre 2026** — indice reale, costruito sui documenti dell'utente:
**8.612 blocchi** da 534 file (3.685 da `D:\ricerche`, 3.307 da `D:\Archivio_Finanziario`,
1.302 da `D:\archivio_giornalistico`, 318 articoli dimostrativi), 2,7 ore di encoding,
indice da 108 MB. La soglia 0,693 — calibrata sugli articoli — **funziona anche sugli atti**:
le quattro query di collaudo hanno restituito tutte risultati pertinenti in testa
(«morti bianche nei cantieri» → l'inchiesta di Lodi a 0,8015; «infiltrazione mafiosa negli
appalti» → il monitoraggio Lombardia a 0,7606). Tempi: 107-193 ms per query su 8.612 documenti.

Due avvertenze pratiche:
- il campo `count_above` **era** inaffidabile (diceva 32 in ogni query) ed è stato corretto
  il 5 novembre 2026: prima contava i documenti dentro il pool di ricerca, che sopra i 5.000
  documenti restava fermo a 32. Ora conta sull'intero corpus e dichiara lo scope in
  `counts_scope` (`corpus` oppure `pool`). Costo: la query passa da ~110-190 ms a
  ~180-490 ms, perché serve una seconda passata sulle sole distanze, senza testi.
  Numeri verificati dopo la correzione: «morti bianche nei cantieri» 50 documenti sopra
  soglia, «spese per il personale comunale» 234, «infiltrazione mafiosa negli appalti» 241,
  «ricetta della carbonara» 0;
- le riviste finanziarie in PDF producono blocchi di testo disordinato (colonne, tabelle):
  compaiono nei risultati ma vanno lette con prudenza.

Per aggiungere altri documenti: `newssearch.cli sync` aggiorna solo ciò che è cambiato,
senza rifare tutto (il primo build completo ha richiesto 2,7 ore su CPU).

### `social.py` — fonti social, solo i canali gratuiti che funzionano
Provato il 5 novembre 2026. Tre backend, nessuna chiave, nessun account:

```
python social.py telegram ultimora -n 20
python social.py bluesky "consiglio comunale lodi" -n 20
python social.py youtube "consiglio comunale lodi" -n 5
python social.py youtube-canale @ComunediLodi -n 5
python social.py sottotitoli "https://www.youtube.com/watch?v=..." --lingua it --out-dir dati
```

Cosa restituisce, misurato:
- **Telegram**: post pubblici con data, testo, link diretto (`t.me/canale/123`) e visualizzazioni.
  Funziona sui canali che espongono il feed web (`ultimora`, `repubblica`, `ilsole24ore`):
  20 post ciascuno. Su altri (`ansa`, `ilpost`, `corriere`) il feed non è pubblico e non si
  può leggere senza account: lo script lo dice invece di restituire zero in silenzio.
- **Bluesky**: ricerca testuale sull'API pubblica (`api.bsky.app`), con autore, data e link.
  Attenzione: `public.api.bsky.app` risponde 403 dai client senza sessione; usare `api.bsky.app`.
- **YouTube**: ricerca e canali via `yt-dlp`, senza chiave API. È il pezzo più utile per la PA:
  le sedute dei consigli comunali sono online (`Consiglio Comunale - 22 ottobre 2026`, 334
  minuti). Con `sottotitoli` si scarica il testo; se non ci sono sottotitoli, si scarica
  l'audio e si usa la skill `trascrizione-audio`.

**Cosa NON è possibile, e non per pigrizia**: Facebook e Instagram (Graph API con permessi
speciale o scraping vietato), X/Twitter (API a pagamento), TikTok (ricerca non pubblica),
Reddit (403), Mastodon (rate limit 429 sulle istanze pubbliche). Per queste fonti l'unico
metodo corretto resta la consultazione manuale con `browser_tool`, documentando URL, data
e ora dello screenshot. Niente automazione di massa: i contenuti social contengono dati
personali e la raccolta indiscriminata è un problema GDPR prima che tecnico.

**Regola di metodo**: un post social è una traccia, non una prova. Va risalito alla fonte
(verbale, delibera, atto) o verificato con due indipendenti, e citato con URL e data.

### `fonti_web.py` — pagina di un ente, albo pretorio, amministrazione trasparente
Estrae il testo principale (senza menu e cookie banner), la data di pubblicazione e i link ai
documenti. Salva l'HTML originale: se la pagina cambia, la copia resta.

```
python fonti_web.py "https://www.comune.xxx.it/albo" --out-dir "D:\ricerche\xyz\fonti"
python fonti_web.py URL --motore jina        (forza Jina, utile per i PDF)
```

**Fallback Jina Reader** (gratuito, senza chiave, 20 richieste al minuto). Quando trafilatura
restituisce meno di 250 parole utili o oltre metà delle righe sono link — cioè quando la pagina
è tutta menu, o è caricata via javascript — lo script riprova con `r.jina.ai`, che rende la
pagina lato server e la converte in markdown. Nei test: home ISTAT da 442 parole di menu a
89 KB di contenuto reale; PDF remoto convertito in markdown con data di pubblicazione.

Due regole d'uso:
- **Privacy**: l'URL viene inviato a un terzo. Mai passarci link riservati, documenti non
  pubblici o indirizzi con token di sessione.
- **Citazione**: si cita sempre l'URL originale, mai `r.jina.ai`. Il proxy è un mezzo,
  non una fonte.

L'HTML originale viene comunque salvato in locale: è quello la prova, non il markdown.

### `albo.py` — albo pretorio o elenco atti in una sola chiamata
Scarica la pagina, trova i link ai PDF, li scarica in parallelo, estrae testo e campi
(data, oggetto, importo, CIG) e scrive un indice tabellare con la citazione di ogni atto.
È il sostituto di quaranta chiamate separate: usalo quando la pagina contiene un elenco di atti.

```
python albo.py "https://www.comune.xxx.it/albo-pretorio" --out-dir "D:\ricerche\xyz"
python albo.py URL --filtro "determin" --max-atti 30
python albo.py URL --solo-elenco
```

Produce `fonti\atti\` con i PDF e `dati\indice-atti.md` con la tabella. Il CIG va sempre
riverificato a mano sull'atto: lo script lo segnala come candidato, non come prova.

### `wayback_prova.py` — cosa diceva la pagina in una certa data
Interroga la CDX API dell'Internet Archive, trova lo snapshot più vicino alla data richiesta e
verifica se una stringa era presente. È la prova che una pagina è stata modificata.

```
python wayback_prova.py "https://www.comune.xxx.it/bandi" --data 2026-03-14 --cerca "importo 250.000"
```

### `istat_comune.py` — demografia per comune
Scarica i tracciati ufficiali (`demo.istat.it/data/...`), filtra il comune e produce la serie.
Nessuna chiave API. Se l'anno non esiste, lo dice invece di restituire zero.

```
python istat_comune.py --comune "Lodi" --provincia LO --anni 2019-2026
```

### `dati_query.py` — conteggi su CSV, Excel, Parquet
SQL su file locali con DuckDB, più il controllo numerico richiesto prima di consegnare:
righe, somma delle colonne indicate, valori nulli, duplicati, buchi nelle sequenze.

```
python dati_query.py appalti.csv --sql "select * from t where importo > 1000000"
python dati_query.py appalti.csv --controlla importo --chiave cig
python dati_query.py appalti.csv --converti --sql "select comune, count(*), sum(importo) from t group by 1"
```

`--converti` crea il Parquet accanto al CSV e da quel momento interroga quello: su 200.000 righe
un `group by` passa da 158 ms a 5 ms. Il Parquet viene riusato automaticamente se esiste.

## Limiti noti (dichiararli, non aggirarli)

- `fonti_web.py` su una **home page** a riquadri restituisce poco testo: trafilatura scarta i menu
  e tiene il contenuto. Per un albo pretorio o una pagina di delibere funziona; per una home
  inutile insistere, si va direttamente alla pagina dell'elenco atti.
- `istat_comune.py` copre le province in tabella (le 12 lombarde più le principali). Per le altre
  passare `--codice` (3 cifre) e `--provincia` (nome come nel file). Se un anno non esiste,
  lo script lo dice: nel rapporto va scritto “non disponibile”, mai zero.
- `dati_query.py` su Excel richiede l'estensione `excel` di DuckDB, che si installa alla prima
  esecuzione e richiede rete.
- `wayback_prova.py`: se un sito non è mai stato archiviato non c'è prova. Assenza di snapshot
  **non** significa che la pagina non sia cambiata.

## Ordine di lavoro consigliato

0. Se il documento ha **tabelle o bilanci**, parti da `tabelle.py`.
0b. Se devi capire **di che cosa parlano** i documenti che hai già, `archivio.py cerca`.
1. `atti_pdf.py` sull'atto: se il testo è nativo non serve OCR.
2. `fonti_web.py` sul portale, conservando l'HTML.
3. `wayback_prova.py` se il documento è sparito o è stato cambiato.
4. `dati_query.py` quando ci sono elenchi: mai scrivere "circa" se si può contare.
5. `istat_comune.py` per il contesto demografico del comune.

## Regole di rigore

- Il numero di pagina va citato sempre per i PDF: senza pagina la citazione non è verificabile.
- Se un dataset è vuoto o un anno manca, si scrive "non disponibile" con la data della richiesta.
  L'assenza non è zero.
- Gli HTML salvati in `fonti\` sono la prova: non cancellarli dopo aver scritto l'articolo.
- Se uno script fallisce, l'errore va riportato così com'è nel rapporto; non si aggira a mano
  senza dirlo.
