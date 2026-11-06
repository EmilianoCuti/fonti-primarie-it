#!/usr/bin/env python
"""Conteggi e controllo numerico su CSV/Excel/Parquet, con SQL (DuckDB).

Serve alla regola del progetto: prima di consegnare, contare. Righe, somme, nulli,
duplicati, buchi nelle sequenze. Stampa sempre la citazione del file con l'hash.

Esempi:
    python dati_query.py appalti.csv --sql "select * from t limit 20"
    python dati_query.py appalti.csv --controlla importo --chiave cig
    python dati_query.py *.csv --sql "select count(*) from t"
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import sys
from pathlib import Path


def hash_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for blocco in iter(lambda: f.read(1 << 20), b""):
            h.update(blocco)
    return h.hexdigest()[:12]


def apri(con, files: list[Path], converti: bool = False, no_parquet: bool = False) -> str:
    """Registra i file come viste t, t2, ... e restituisce il nome della prima.

    Se accanto a un CSV esiste il Parquet (o se --converti lo crea), interroga il Parquet:
    su 200.000 righe un group by passa da 158 ms a 5 ms.
    """
    nomi = []
    for i, f in enumerate(files, 1):
        nome = "t" if i == 1 else f"t{i}"
        ext = f.suffix.lower()
        if ext in (".csv", ".txt", ".tsv"):
            parq = f.with_suffix(f.suffix + ".parquet")
            if parq.exists() and not no_parquet:
                con.execute(f"create or replace view {nome} as select * from read_parquet('{parq.as_posix()}')")
                print(f"[uso parquet] {parq.name}")
            else:
                opts = f"delim='\\t', " if ext == ".tsv" else ""
                con.execute(
                    f"create or replace view {nome} as select * from read_csv_auto('{f.as_posix()}', {opts}header=true, sample_size=-1)"
                )
                if converti:
                    con.execute(
                        f"copy (select * from read_csv_auto('{f.as_posix()}', {opts}header=true, sample_size=-1)) "
                        f"to '{parq.as_posix()}' (format parquet)"
                    )
                    con.execute(f"create or replace view {nome} as select * from read_parquet('{parq.as_posix()}')")
                    print(f"[parquet creato] {parq.name} ({parq.stat().st_size / 1e6:.1f} MB)")
        elif ext in (".parquet",):
            con.execute(f"create or replace view {nome} as select * from read_parquet('{f.as_posix()}')")
        elif ext in (".xlsx", ".xls"):
            con.execute("install excel; load excel;")
            con.execute(f"create or replace view {nome} as select * from st_read('{f.as_posix()}')")
        else:
            sys.exit(f"estensione non gestita: {ext}")
        nomi.append(nome)
    return nomi[0]


def mostra(con, sql: str) -> None:
    rel = con.sql(sql)
    colonne = rel.columns
    righe = rel.fetchall()
    larghezze = [max(len(str(c)), *(len(str(r[i])) for r in righe)) if righe else len(str(c)) for i, c in enumerate(colonne)]
    print(" | ".join(str(c).ljust(larghezze[i]) for i, c in enumerate(colonne)))
    print("-+-".join("-" * w for w in larghezze))
    for r in righe:
        print(" | ".join(str(v).ljust(larghezze[i]) for i, v in enumerate(r)))
    print(f"\n({len(righe)} righe mostrate)")


def controlla(con, vista: str, colonne: list[str], chiave: str | None) -> None:
    tot = con.execute(f"select count(*) from {vista}").fetchone()[0]
    print(f"righe totali: {tot}")
    for c in colonne:
        q = (
            f"select count({c}) as non_nulli, count(*) - count({c}) as nulli, "
            f"sum(try_cast({c} as double)) as somma, min(try_cast({c} as double)) as minimo, "
            f"max(try_cast({c} as double)) as massimo, count(distinct {c}) as distinti from {vista}"
        )
        try:
            non_nulli, nulli, somma, minimo, massimo, distinti = con.execute(q).fetchone()
        except Exception as e:
            print(f"  {c}: non numerica o non leggibile ({e})")
            continue
        print(
            f"  {c}: non nulli {non_nulli} | nulli {nulli} | somma {somma} | "
            f"min {minimo} | max {massimo} | distinti {distinti}"
        )
        if nulli:
            print(f"    ATTENZIONE: {nulli} valori nulli in {c} - nel rapporto vanno dichiarati, non contati come zero.")
    if chiave:
        dup = con.execute(
            f"select count(*) from (select {chiave} from {vista} group by 1 having count(*) > 1)"
        ).fetchone()[0]
        print(f"  duplicati su {chiave}: {dup}")
        try:
            buchi = con.execute(
                f"select min(try_cast({chiave} as bigint)), max(try_cast({chiave} as bigint)) from {vista}"
            ).fetchone()
            if buchi[0] is not None and buchi[1] is not None:
                attesi = buchi[1] - buchi[0] + 1
                print(f"  sequenza {chiave}: da {buchi[0]} a {buchi[1]} -> attesi {attesi}, presenti {tot - dup}")
        except Exception:
            pass


def principale() -> int:
    ap = argparse.ArgumentParser(description="SQL e controlli numerici su file tabellari.")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--sql", help="query da eseguire (la prima vista si chiama t)")
    ap.add_argument("--controlla", nargs="*", default=[], help="colonne da conteggiare/sommare")
    ap.add_argument("--chiave", help="colonna chiave per duplicati e buchi (es. cig)")
    ap.add_argument("--converti", action="store_true", help="crea il Parquet accanto al CSV e interroga quello")
    ap.add_argument("--no-parquet", action="store_true", help="ignora un Parquet gia esistente")
    args = ap.parse_args()

    import duckdb

    files = [Path(f) for f in args.files]
    for f in files:
        if not f.exists():
            sys.exit(f"file non trovato: {f}")

    con = duckdb.connect()
    vista = apri(con, files, args.converti, args.no_parquet)

    if args.controlla or args.chiave:
        controlla(con, vista, args.controlla, args.chiave)

    if args.sql:
        print()
        try:
            mostra(con, args.sql)
        except Exception as e:
            print(f"ERRORE SQL: {e}")
            return 1

    print("\n--- citazione ---")
    for f in files:
        print(f"{f} | sha256[:12] {hash_file(f)} | consultato il {dt.date.today().isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(principale())
