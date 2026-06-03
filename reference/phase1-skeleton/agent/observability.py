"""Observability: record every decision with its reason."""
import csv
from dataclasses import asdict


class DecisionLog:
    def __init__(self):
        self.rows = []

    def record(self, d, equity: float) -> None:
        row = asdict(d)
        row["equity"] = round(equity, 2)
        self.rows.append(row)

    def save(self, path: str = "decision_log.csv") -> str:
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=self.rows[0].keys())
            w.writeheader()
            w.writerows(self.rows)
        return path
