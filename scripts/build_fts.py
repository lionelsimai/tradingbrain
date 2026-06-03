#!/usr/bin/env python3
"""Rebuild the FTS index over documents. Idempotent."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import kb


def main():
    con = kb()
    con.execute("INSTALL fts")
    con.execute("LOAD fts")
    con.execute("""
        PRAGMA create_fts_index(
            'documents', 'doc_id', 'title', 'body',
            stemmer='porter', stopwords='english',
            ignore='(\\.|[^a-z])+', strip_accents=1, lower=1,
            overwrite=1
        )
    """)
    n = con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    print(f"FTS index built over {n} documents.")


if __name__ == "__main__":
    main()
