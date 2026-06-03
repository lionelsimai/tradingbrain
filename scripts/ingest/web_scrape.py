#!/usr/bin/env python3
"""Hourly web scrape — breaking news + filings + retail sentiment.

Runs in <30 sec. No browser. RSS + JSON only. Adds new documents to
knowledge.duckdb, tagged so the hourly pulse can surface them.

Sources (curated for AI-trade relevance):
  - Reuters Markets RSS
  - CNBC Markets + Technology RSS
  - MarketWatch top stories
  - PR Newswire press releases
  - SEC EDGAR latest 8-K Atom feed (filtered to universe CIKs)
  - SEC EDGAR latest Form 4 Atom feed (filtered to universe CIKs)
  - Reddit JSON: r/investing /r/stocks /r/wallstreetbets new posts
  - Hacker News top stories (filtered for AI/data-center/semi keywords)
  - DataCenterDynamics + DataCenterKnowledge RSS
"""
from __future__ import annotations
import argparse, hashlib, json, re, sys
from datetime import datetime, timezone
from pathlib import Path
import requests, yaml
from xml.etree import ElementTree as ET
from email.utils import parsedate_to_datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db import kb  # noqa: E402

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
SOURCES = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text())
UNIVERSE = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text())
UA = SOURCES["defaults"]["user_agent"]
HEADERS = {"User-Agent": UA, "Accept": "*/*"}

KEYWORDS_AI = re.compile(
    r"\b(AI|GPU|datacenter|data center|hyperscaler|NVIDIA|HBM|inference|"
    r"training|chip|semiconduct|foundry|TSMC|cloud capex|nuclear|SMR|"
    r"GPU shortage|cooling|GW|gigawatt|substation|MW|megawatt|"
    r"transformer|LLM|model|frontier)\b",
    re.IGNORECASE,
)

# --- helpers --------------------------------------------------------------

def all_tickers() -> list[str]:
    out: list[str] = []
    for v in UNIVERSE.values():
        if isinstance(v, list):
            out += v
        elif isinstance(v, dict):
            for vv in v.values():
                if isinstance(vv, list):
                    out += vv
    return sorted(set(out))

TICKERS = set(all_tickers())
TICKER_PAT = re.compile(r"\b(" + "|".join(re.escape(t) for t in TICKERS if len(t) >= 2) + r")\b")
DOLLAR_PAT = re.compile(r"\$([A-Z]{1,5})\b")


def find_tickers(text: str) -> list[str]:
    hits = set(TICKER_PAT.findall(text or ""))
    hits |= {m for m in DOLLAR_PAT.findall(text or "") if m in TICKERS}
    return sorted(hits)


def fp(*parts: str) -> str:
    return hashlib.sha256("||".join(parts).encode()).hexdigest()[:32]


def normalize_ts(s: str | None) -> str:
    if not s:
        return datetime.now(timezone.utc).isoformat()
    try:
        return parsedate_to_datetime(s).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        pass
    try:
        # fallback: try ISO
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except ValueError:
        return datetime.now(timezone.utc).isoformat()


def http_get(url: str, timeout: int = 10) -> requests.Response | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code == 200:
            return r
    except Exception:
        return None
    return None


# Load EDGAR CIK map (built by scripts/ingest/edgar.py during backfill),
# then intersect with our 80-ticker universe.
_CIK_MAP_PATH = ROOT / "data" / "raw" / "edgar" / "_cik_map.json"
_TICKER_TO_CIK: dict[str, str] = {}
_CIK_TO_TICKER: dict[str, str] = {}
if _CIK_MAP_PATH.exists():
    try:
        raw = json.loads(_CIK_MAP_PATH.read_text())
        for ticker, cik in raw.items():
            tk = ticker.upper()
            if tk not in TICKERS:
                continue
            cik_str = str(cik).zfill(10) if isinstance(cik, (int, str)) else None
            if cik_str:
                _TICKER_TO_CIK[tk] = cik_str
                _CIK_TO_TICKER[cik_str] = tk
    except Exception:
        pass


# --- source-specific parsers ---------------------------------------------

RSS_FEEDS = {
    "reuters_business": "https://feeds.reuters.com/reuters/businessNews",
    "cnbc_markets": "https://www.cnbc.com/id/19854910/device/rss/rss.html",
    "cnbc_tech": "https://www.cnbc.com/id/19854910/device/rss/rss.html",
    "marketwatch_top": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "prnewswire": "https://www.prnewswire.com/rss/news-releases-list.rss",
    "datacenter_dynamics": "https://www.datacenterdynamics.com/en/rss/",
    "datacenter_knowledge": "https://www.datacenterknowledge.com/rss.xml",
    "investing_com_stocks": "https://www.investing.com/rss/news_25.rss",
}


def parse_rss(name: str, url: str) -> list[dict]:
    r = http_get(url)
    if r is None:
        return []
    try:
        root = ET.fromstring(r.text)
    except ET.ParseError:
        return []
    items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    out: list[dict] = []
    for it in items[:40]:
        get = lambda tag: (it.findtext(tag) or it.findtext("{http://www.w3.org/2005/Atom}" + tag) or "").strip()
        title = get("title")
        body = get("description") or get("summary") or get("content")
        link = get("link")
        if not link:
            l = it.find("{http://www.w3.org/2005/Atom}link")
            if l is not None:
                link = l.attrib.get("href", "")
        pub = get("pubDate") or get("published") or get("updated")
        text = f"{title} {body}"
        tickers_hit = find_tickers(text)
        if not tickers_hit and not KEYWORDS_AI.search(text):
            continue
        out.append({
            "source": f"web:{name}",
            "title": title[:300],
            "body": body[:5000],
            "url": link[:500],
            "published_at": pub,
            "tickers": tickers_hit,
        })
    return out


def parse_edgar_atom(form: str, limit: int = 100) -> list[dict]:
    # https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&output=atom
    url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type={form}&output=atom&count={limit}"
    r = http_get(url, timeout=15)
    if r is None:
        return []
    try:
        root = ET.fromstring(r.text)
    except ET.ParseError:
        return []
    ns = "{http://www.w3.org/2005/Atom}"
    out: list[dict] = []
    cik_pat = re.compile(r"\((\d{4,10})\)")
    for e in root.findall(f"{ns}entry")[:limit]:
        title = (e.findtext(f"{ns}title") or "").strip()
        summary = (e.findtext(f"{ns}summary") or "").strip()
        link_el = e.find(f"{ns}link")
        link = link_el.attrib.get("href", "") if link_el is not None else ""
        updated = (e.findtext(f"{ns}updated") or "").strip()
        # Match by CIK extracted from the title
        m = cik_pat.search(title)
        if not m:
            continue
        cik_str = m.group(1).zfill(10)
        if cik_str not in _CIK_TO_TICKER:
            continue
        ticker = _CIK_TO_TICKER[cik_str]
        out.append({
            "source": f"edgar_live:{form}",
            "title": title[:300],
            "body": summary[:5000],
            "url": link[:500],
            "published_at": updated,
            "tickers": [ticker],
        })
    return out


# Reddit ingest needs OAuth (PRAW + Reddit app credentials).
# Reddit's `new.json` returns 403 for unauthenticated cloud IPs.
# Defer to a separate skill once REDDIT_CLIENT_ID/SECRET are set.


def parse_hn() -> list[dict]:
    r = http_get("https://hacker-news.firebaseio.com/v0/topstories.json")
    if r is None:
        return []
    ids = r.json()[:60]
    out: list[dict] = []
    for hid in ids:
        rr = http_get(f"https://hacker-news.firebaseio.com/v0/item/{hid}.json", timeout=5)
        if rr is None:
            continue
        d = rr.json() or {}
        title = d.get("title", "")
        if not KEYWORDS_AI.search(title):
            continue
        out.append({
            "source": "hn",
            "title": title[:300],
            "body": (d.get("text") or "")[:3000],
            "url": d.get("url") or f"https://news.ycombinator.com/item?id={hid}",
            "published_at": datetime.fromtimestamp(d.get("time", 0), tz=timezone.utc).isoformat(),
            "tickers": find_tickers(title),
            "metadata": {"score": d.get("score", 0), "descendants": d.get("descendants", 0)},
        })
    return out


# --- write ---------------------------------------------------------------

def store(docs: list[dict]) -> int:
    if not docs:
        return 0
    con = kb()
    n_new = 0
    now = datetime.now(timezone.utc).isoformat()
    for d in docs:
        doc_id = fp(d["source"], d.get("url", ""), d["title"])
        exists = con.execute("SELECT 1 FROM documents WHERE doc_id = ?", [doc_id]).fetchone()
        if exists:
            continue
        ticker_first = d["tickers"][0] if d["tickers"] else None
        meta = {"tickers": d["tickers"], **d.get("metadata", {})}
        con.execute(
            """INSERT INTO documents
                 (doc_id, source, url, title, body, published_at, ingested_at, metadata, ticker)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [doc_id, d["source"], d.get("url", ""), d["title"], d.get("body", ""),
             normalize_ts(d.get("published_at")), now, json.dumps(meta), ticker_first],
        )
        n_new += 1
    con.close()
    return n_new


# --- main ----------------------------------------------------------------

def main() -> int:
    a = argparse.ArgumentParser()
    a.add_argument("--sources", default="all",
                   help="comma list: rss,edgar,hn or 'all'")
    args = a.parse_args()
    want = set(args.sources.split(",")) if args.sources != "all" else {"rss", "edgar", "hn"}

    print(f"Web scrape · {datetime.now(timezone.utc).isoformat()}")
    total = 0

    if "rss" in want:
        for name, url in RSS_FEEDS.items():
            docs = parse_rss(name, url)
            n = store(docs)
            print(f"  [rss:{name:<24}] hits={len(docs):>3}  new={n:>3}")
            total += n
    if "edgar" in want:
        for form in ("8-K", "4"):
            docs = parse_edgar_atom(form, limit=80)
            n = store(docs)
            print(f"  [edgar:{form:<22}] hits={len(docs):>3}  new={n:>3}")
            total += n
    if "hn" in want:
        docs = parse_hn()
        n = store(docs)
        print(f"  [hn{'':<25}] hits={len(docs):>3}  new={n:>3}")
        total += n

    print(f"\nDone. Total new documents: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
