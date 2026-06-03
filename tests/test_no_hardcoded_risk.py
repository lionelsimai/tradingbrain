import re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

# active risk constants must come from the canonical policy, not literals in code
BANNED = [
    re.compile(r"START_EQUITY\s*=\s*\d"),
    re.compile(r"MAX_OPEN\s*=\s*\d"),
]
SCAN = ["scripts","loops","safety","execution","portfolio"]

def test_no_hardcoded_risk_constants():
    bad=[]
    for d in SCAN:
        for f in (ROOT/d).rglob("*.py"):
            if "__pycache__" in str(f): continue
            txt=f.read_text()
            for pat in BANNED:
                if pat.search(txt):
                    bad.append(f"{f.relative_to(ROOT)}: {pat.pattern}")
    assert not bad, bad
