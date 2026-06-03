#!/usr/bin/env python3
"""Dry-run a single order proposal through the full gate and print the decision
with rejection reasons. No order is placed (NullBroker). Section 35."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from execution.order_manager import dry_run

if __name__ == "__main__":
    r = dry_run()
    print(json.dumps({"approved": r.approved, "submitted": r.submitted,
                      "reason": r.rejected_reason, "events": r.events}, indent=2))
