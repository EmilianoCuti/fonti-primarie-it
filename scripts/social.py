#!/usr/bin/env python
"""Ricerca su fonti social, solo con canali gratuiti e verificati.

Che cosa funziona davvero (provato il 5 novembre 2026):
  telegram   canali pubblici via t.me/s/<canale> — nessuna chiave, nessun account
  bluesky    API pubblica api.bsky.app — nessuna chiave
  youtube    ricerca e canali via yt-dlp — nessuna chiave API

Che cosa NON funziona senza pagare o senza violare i termini:
  Facebook, Instagram, X/Twitter, TikTok, Reddit, Mastodon (rate limit severi).
  Per quelli l'unico metodo corretto resta la consultazione manuale con browser,
  documentando URL, data e screenshot.

Esempi:
    python social.py telegram ultimora -n 10
    python social.py bluesky "consiglio comunale lodi" -n 10
    python social.py youtube "consiglio comunale lodi" -n 5
    python social.py youtube-canale @ComunediLodi -n 5
    python social.py sottotitoli "https://www.youtube.com/watch?v=XXXX" --lingua it
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
SEP = "\x1f"


# ------------------------------------------------------------------ utilita

def trova_ytdlp() -> str | None:
    exe = shutil.which("yt-dlp")
    if exe:
        return exe
    for c in (
        r"D:\Progetti\fonti-it\.venv\Scripts\yt-dlp.exe",
        r"C:\Users\emili\AppData\Local\hermes\hermes-agent\venv\Scripts\yt-dlp.exe",
        r"C:\Users\emili\.local\bin\yt-dlp.exe",
    ):
        if Path(c).exists():
            return c
    return None


def pulisci(t: str, n: int = 400) -> str:
    t = re.sub(r"<br\s*/?>", " ", t or "")
    t = re.sub(r"<[^>]+>", "", t)
    t = t.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'").replace("&quot;", '"')
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= n else t[: n - 1] + "…"


# ------------------------------------------------------------------ telegram

def telegram(canale: str, n: int) -> int:
    import requests

    url = f"https://t.me/s/{canale}"
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    except Exception as e:
        print(f"ERRORE rete: {e}")
        return 1
    if r.status_code != 200:
        print(f"ERRORE: HTTP {r.status_code} su {url}")
        return 1

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("serve beautifulsoup4 (bs4) per leggere il feed Telegram.")
        return 1

    soup = BeautifulSoup(r.text, "lxml")
    post = []
    for blocco in soup.select("div.tgme_widget_message"):
        testo = blocco.select_one(".tgme_widget_message_text")
        if testo is None:
            continue
        orario = blocco.select_one("time[datetime]")
        link_el = blocco.select_one("a.tgme_widget_message_date")
        viste_el = blocco.select_one(".tgme_widget_message_views")
        post.append({
            "data": (orario["datetime"][:19].replace("T", " ") if orario else ""),
            "testo": pulisci(testo.get_text(" ", strip=True)),
            "url": (link_el["href"] if link_el is not None and link_el.has_attr("href") else url),
            "viste": (viste_el.get_text(strip=True) if viste_el is not None else ""),
        })

    if not post:
        print(f"nessun post pubblico su t.me/s/{canale}.")
        print("Molti canali non espongono il feed web: in quel caso l'archivio non è accessibile senza account.")
        return 2

    print(f"canale: {canale} | post pubblici nel feed: {len(post)}\n")
    for p in post[-n:]:
        print(f"[{p['data']}] {p['testo']}")
        extra = f"  ({p['viste']} visualizzazioni)" if p["viste"] else ""
        print(f"   {p['url']}{extra}\n")
    print("--- citazione ---")
    print(f"Telegram, canale pubblico @{canale} ({url}), consultato il {dt.date.today().isoformat()}")
    return 0


# ------------------------------------------------------------------ bluesky

def bluesky(query: str, n: int) -> int:
    import requests

    url = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts"
    try:
        r = requests.get(url, params={"q": query, "limit": min(max(n, 1), 100)},
                         headers={"User-Agent": "curl/8.5.0", "Accept": "application/json"}, timeout=45)
    except Exception as e:
        print(f"ERRORE rete: {e}")
        return 1
    if r.status_code != 200:
        print(f"ERRORE: HTTP {r.status_code} — {r.text[:200]}")
        return 1

    dati = r.json()
    post = dati.get("posts", [])
    if not post:
        print(f"nessun post per «{query}».")
        print("(l'assenza di risultati non significa che non se ne parli: l'indice Bluesky è parziale)")
        return 2

    print(f"Bluesky | query: «{query}» | post: {len(post)}\n")
    for p in post:
        rec = p.get("record", {}) or {}
        autore = (p.get("author", {}) or {}).get("handle", "?")
        testo = pulisci(rec.get("text", ""), 320) or "(post senza testo: immagine, video o repost)"
        creato = (rec.get("createdAt") or "")[:19].replace("T", " ")
        uri = p.get("uri", "")
        rkey = uri.rsplit("/", 1)[-1] if uri else ""
        print(f"[{creato}] @{autore}")
        print(f"   {testo}")
        if rkey:
            print(f"   https://bsky.app/profile/{autore}/post/{rkey}")
        print()
    print("--- citazione ---")
    print(f"Bluesky (API pubblica), ricerca \"{query}\", consultato il {dt.date.today().isoformat()}")
    return 0


# ------------------------------------------------------------------ youtube

def _esegui_ytdlp(yt: str, argomenti: list[str]) -> list[list[str]]:
    campi = ["id", "title", "channel", "duration", "upload_date", "webpage_url"]
    fmt = SEP.join(f"%({c})s" for c in campi)
    cmd = [yt, "--flat-playlist", "--no-warnings", "--ignore-errors", "--print", fmt] + argomenti
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=180, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        print("yt-dlp: tempo scaduto (180 s)")
        return []
    righe = []
    for riga in (out.stdout or "").splitlines():
        if SEP in riga:
            righe.append(riga.split(SEP))
    if not righe and out.stderr:
        print("yt-dlp:", out.stderr.strip().splitlines()[-1][:200])
    return righe


def _stampa_video(righe: list[list[str]], n: int, contesto: str) -> int:
    if not righe:
        print("nessun video trovato.")
        return 2
    righe = righe[:n]
    print(f"{contesto} | video: {len(righe)}\n")
    for c in righe:
        while len(c) < 6:
            c.append("")
        vid, titolo, canale, durata, data, link = c[:6]
        mm = ""
        try:
            sec = int(float(durata))
            mm = f"{sec // 60}:{sec % 60:02d}"
        except Exception:
            pass
        quando = data if data and data != "NA" else ""
        print(f"• {titolo}")
        print(f"   canale: {canale} | durata: {mm or '?'} {('| ' + quando) if quando else ''}")
        print(f"   https://www.youtube.com/watch?v={vid}")
        if "consiglio" in (titolo or "").lower():
            print("   (seduta: si può scaricare l'audio e trascriverlo)")
        print()
    print("--- citazione ---")
    print(f"YouTube, {contesto}, consultato il {dt.date.today().isoformat()}")
    return 0


def youtube(query: str, n: int) -> int:
    yt = trova_ytdlp()
    if not yt:
        print("yt-dlp non trovato: è in Hermes o in fonti-it, serve per la ricerca YouTube.")
        return 1
    righe = _esegui_ytdlp(yt, [f"ytsearch{max(n, 1)}:{query}"])
    return _stampa_video(righe, n, f"ricerca «{query}»")


def youtube_canale(canale: str, n: int) -> int:
    yt = trova_ytdlp()
    if not yt:
        print("yt-dlp non trovato.")
        return 1
    if canale.startswith("http"):
        url = canale
    elif canale.startswith("@"):
        url = f"https://www.youtube.com/{canale}/videos"
    else:
        url = f"https://www.youtube.com/@{canale}/videos"
    righe = _esegui_ytdlp(yt, ["--playlist-end", str(max(n, 1)), url])
    return _stampa_video(righe, n, f"canale {canale}")


def sottotitoli(url: str, lingua: str, out_dir: str | None) -> int:
    yt = trova_ytdlp()
    if not yt:
        print("yt-dlp non trovato.")
        return 1
    dest = Path(out_dir or ".")
    dest.mkdir(parents=True, exist_ok=True)
    cmd = [yt, "--skip-download", "--write-auto-subs", "--write-subs",
           "--sub-langs", lingua, "--sub-format", "vtt",
           "-o", str(dest / "%(upload_date)s_%(title).60s.%(ext)s"), url]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=300, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        print("yt-dlp: tempo scaduto")
        return 1
    if r.returncode != 0:
        print("errore:", (r.stderr or "").strip().splitlines()[-1][:200] if r.stderr else "sconosciuto")
        return 1
    file_vtt = list(dest.glob("*.vtt"))
    if not file_vtt:
        print("nessun sottotitolo disponibile per questa lingua.")
        print("In alternativa: scaricare l'audio e usare la skill trascrizione-audio.")
        return 2
    for f in file_vtt:
        testo = f.read_text(encoding="utf-8", errors="replace")
        righe = [r for r in testo.splitlines() if r.strip() and "-->" not in r and not r.startswith(("WEBVTT", "Kind:", "Language:"))]
        pulito = re.sub(r"<[^>]+>", "", " ".join(righe))
        pulito = re.sub(r"\s+", " ", pulito).strip()
        md = f.with_suffix(".md")
        md.write_text(
            f"# Sottotitoli: {f.stem}\n\n- Fonte: {url}\n- Scaricati il: {dt.date.today().isoformat()}\n"
            f"- Lingua: {lingua}\n- Avvertenza: sottotitoli automatici, possono contenere errori di riconoscimento.\n\n{pulito}\n",
            encoding="utf-8",
        )
        print(f"[scritto] {md}  ({len(pulito)} caratteri)")
    print("\n--- citazione ---")
    print(f"{url} | sottotitoli YouTube ({lingua}), scaricati il {dt.date.today().isoformat()}")
    return 0


# ------------------------------------------------------------------ main

def principale() -> int:
    ap = argparse.ArgumentParser(description="Ricerca su Telegram, Bluesky e YouTube (fonti gratuite).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("telegram", help="post di un canale pubblico")
    t.add_argument("canale")
    t.add_argument("-n", type=int, default=15)

    b = sub.add_parser("bluesky", help="ricerca post")
    b.add_argument("query")
    b.add_argument("-n", type=int, default=15)

    y = sub.add_parser("youtube", help="ricerca video")
    y.add_argument("query")
    y.add_argument("-n", type=int, default=10)

    c = sub.add_parser("youtube-canale", help="ultimi video di un canale")
    c.add_argument("canale")
    c.add_argument("-n", type=int, default=10)

    s = sub.add_parser("sottotitoli", help="scarica i sottotitoli di un video")
    s.add_argument("url")
    s.add_argument("--lingua", default="it")
    s.add_argument("--out-dir")

    a = ap.parse_args()
    if a.cmd == "telegram":
        return telegram(a.canale, a.n)
    if a.cmd == "bluesky":
        return bluesky(a.query, a.n)
    if a.cmd == "youtube":
        return youtube(a.query, a.n)
    if a.cmd == "youtube-canale":
        return youtube_canale(a.canale, a.n)
    return sottotitoli(a.url, a.lingua, a.out_dir)


if __name__ == "__main__":
    try:
        raise SystemExit(principale())
    except BrokenPipeError:
        import os
        os._exit(0)
