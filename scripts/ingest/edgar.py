#!/usr/bin/env python3
"""SEC EDGAR ingestion: filings (10-K, 10-Q, 8-K) + Form 4 insider transactions.

EDGAR is free, has a public REST API, and is the ground truth source for
US-listed companies. The only requirement is a User-Agent header.

Usage:
    python3 -m scripts.ingest.edgar --filings           # 10-K/Q/8-K + Form 4
    python3 -m scripts.ingest.edgar --form4-only        # insider only (faster)
    python3 -m scripts.ingest.edgar --ticker NVDA       # one ticker
    python3 -m scripts.ingest.edgar --since 2025-01-01  # backfill
"""
from __future__ import annotations
import argparse, hashlib, json, sys, time
from datetime import datetime, date, timedelta
from pathlib import Path
import requests, yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db import kb  # noqa: E402

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
RAW_DIR = ROOT / "data" / "raw" / "edgar"
SOURCES = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text())
UNIVERSE = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text())

UA = SOURCES["defaults"]["user_agent"]
HEADERS = {"User-Agent": UA, "Accept": "application/json"}
TICKER_CIK_MAP_URL = "https://www.sec.gov/files/company_tickers.json"


def all_tickers() -> list[str]:
    out = []
    for cat, tickers in UNIVERSE["universe"].items():
        out.extend(tickers)
    return out


def get_cik_map() -> dict[str, str]:
    """Map TICKER -> zero-padded 10-digit CIK."""
    cache = RAW_DIR / "_cik_map.json"
    if cache.exists() and (time.time() - cache.stat().st_mtime) < 7 * 86400:
        return json.loads(cache.read_text())
    r = requests.get(TICKER_CIK_MAP_URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    raw = r.json()
    out = {}
    for _, entry in raw.items():
        ticker = entry["ticker"].upper()
        cik = str(entry["cik_str"]).zfill(10)
        out[ticker] = cik
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out))
    return out


def get_submissions(cik: str) -> dict:
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.json()


def fingerprint(*parts: str) -> str:
    return hashlib.sha256("||".join(parts).encode()).hexdigest()[:32]


def ingest_filings_for_ticker(ticker: str, cik: str, since: date, forms: list[str]) -> tuple[int, int]:
    """Returns (filings_recorded, form4_recorded)."""
    try:
        subs = get_submissions(cik)
    except Exception as e:
        print(f"  [{ticker}] submissions error: {e}")
        return (0, 0)

    recent = subs.get("filings", {}).get("recent", {})
    forms_arr = recent.get("form", [])
    dates_arr = recent.get("filingDate", [])
    accs_arr = recent.get("accessionNumber", [])
    docs_arr = recent.get("primaryDocument", [])
    descs_arr = recent.get("primaryDocDescription", [])

    filings_recorded = 0
    form4_recorded = 0
    con = kb()
    raw_dir = RAW_DIR / ticker
    raw_dir.mkdir(parents=True, exist_ok=True)

    for i in range(len(forms_arr)):
        form = forms_arr[i]
        try:
            fdate = date.fromisoformat(dates_arr[i])
        except Exception:
            continue
        if fdate < since:
            continue

        accession = accs_arr[i]
        primary_doc = docs_arr[i]
        desc = descs_arr[i] if i < len(descs_arr) else ""
        accession_clean = accession.replace("-", "")
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_clean}/{primary_doc}"
        doc_id = fingerprint(ticker, accession, form)

        # Track 10-K, 10-Q, 8-K as filings
        if form in forms:
            existing = con.execute("SELECT 1 FROM documents WHERE doc_id = ?", [doc_id]).fetchone()
            if not existing:
                con.execute(
                    """INSERT INTO documents
                       (doc_id, source, source_id, ticker, title, url, published_at, raw_path, metadata)
                       VALUES (?, 'edgar', ?, ?, ?, ?, ?, NULL, ?)""",
                    [doc_id, accession, ticker, f"{form} — {desc}", url,
                     datetime.combine(fdate, datetime.min.time()),
                     json.dumps({"form": form, "cik": cik})]
                )
                filings_recorded += 1

        # Form 4 — fetch and parse insider transactions
        if form in ("4", "4/A"):
            n = ingest_form4_doc(con, ticker, cik, accession, fdate, raw_dir)
            form4_recorded += n

        time.sleep(0.12)  # SEC rate limit ~10 req/s; stay polite

    con.close()
    return (filings_recorded, form4_recorded)


def ingest_form4_doc(con, ticker: str, cik: str, accession: str, filed: date, raw_dir: Path) -> int:
    """Fetch the Form 4 XML and extract transactions."""
    accession_clean = accession.replace("-", "")
    xml_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_clean}/"
    # Get the filing index to find the .xml file
    try:
        r = requests.get(f"{xml_url}index.json", headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return 0
        idx = r.json()
        xml_file = None
        for item in idx.get("directory", {}).get("item", []):
            name = item.get("name", "")
            if name.endswith(".xml") and not name.startswith("primary_doc"):
                xml_file = name
                break
            if name == "primary_doc.xml":
                xml_file = name
        if not xml_file:
            return 0
        xml = requests.get(f"{xml_url}{xml_file}", headers=HEADERS, timeout=15).text
    except Exception:
        return 0

    # Lightweight XML parsing without lxml dep
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml)
    except Exception:
        return 0

    # Extract reporting owner info
    owner_name = ""
    owner_role = ""
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag == "rptOwnerName" and el.text:
            owner_name = el.text.strip()
        if tag == "officerTitle" and el.text:
            owner_role = el.text.strip()
        if tag == "isDirector" and el.text == "1" and not owner_role:
            owner_role = "Director"
        if tag == "isTenPercentOwner" and el.text == "1" and not owner_role:
            owner_role = "10%+ Owner"

    count = 0
    # Iterate over nonDerivativeTransaction blocks
    for txn in root.iter():
        tag = txn.tag.split("}")[-1]
        if tag != "nonDerivativeTransaction":
            continue
        try:
            t_date = None
            t_code = None
            shares = price = total = None
            shares_after = None
            for sub in txn.iter():
                stag = sub.tag.split("}")[-1]
                # value lives in a child <value> element
                if stag == "transactionDate":
                    for v in sub.iter():
                        if v.tag.split("}")[-1] == "value" and v.text:
                            try:
                                t_date = date.fromisoformat(v.text.strip()[:10])
                            except Exception:
                                pass
                elif stag == "transactionCode" and sub.text:
                    t_code = sub.text.strip()
                elif stag == "transactionShares":
                    for v in sub.iter():
                        if v.tag.split("}")[-1] == "value" and v.text:
                            try:
                                shares = float(v.text.strip())
                            except Exception:
                                pass
                elif stag == "transactionPricePerShare":
                    for v in sub.iter():
                        if v.tag.split("}")[-1] == "value" and v.text:
                            try:
                                price = float(v.text.strip())
                            except Exception:
                                pass
                elif stag == "sharesOwnedFollowingTransaction":
                    for v in sub.iter():
                        if v.tag.split("}")[-1] == "value" and v.text:
                            try:
                                shares_after = float(v.text.strip())
                            except Exception:
                                pass
            if shares and price:
                total = shares * price
            txn_id = fingerprint(ticker, accession, str(t_date), t_code or "", str(shares or 0))
            existing = con.execute(
                "SELECT 1 FROM insider_transactions WHERE txn_id = ?", [txn_id]
            ).fetchone()
            if existing:
                continue
            con.execute(
                """INSERT INTO insider_transactions
                   (txn_id, ticker, insider_name, insider_role, transaction_date, filed_date,
                    transaction_code, shares, price_per_share, total_value, shares_after,
                    accession, raw_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [txn_id, ticker, owner_name, owner_role, t_date, filed,
                 t_code, shares, price, total, shares_after, accession, xml_url]
            )
            count += 1
        except Exception:
            continue
    return count


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", help="Limit to one ticker")
    ap.add_argument("--since", default=None, help="ISO date; default = 90 days ago")
    ap.add_argument("--filings", action="store_true", help="Include 10-K/Q/8-K")
    ap.add_argument("--form4-only", action="store_true")
    args = ap.parse_args()

    since = date.fromisoformat(args.since) if args.since else (date.today() - timedelta(days=90))
    tickers = [args.ticker.upper()] if args.ticker else all_tickers()
    forms = SOURCES["tier_1_fundamentals"]["edgar_filings"]["forms"] if (args.filings or not args.form4_only) else []

    print(f"EDGAR ingest: {len(tickers)} tickers since {since}, forms={forms or 'Form 4 only'}")
    cik_map = get_cik_map()
    total_f = total_4 = 0
    for t in tickers:
        cik = cik_map.get(t.upper())
        if not cik:
            print(f"  [{t}] no CIK found; skipping")
            continue
        f, ff = ingest_filings_for_ticker(t, cik, since, forms)
        if f or ff:
            print(f"  [{t}] filings={f}  form4_txns={ff}")
        total_f += f
        total_4 += ff
    print(f"\nDone. New filings recorded: {total_f}, insider transactions: {total_4}")


if __name__ == "__main__":
    main()
