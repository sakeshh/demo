"""One-off: merge prompt bank + results_run.jsonl + human ratings into agent_dhara_eval_rated.csv."""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

root = Path(__file__).resolve().parent
bank = {int(r["Prompt#"]): r for r in csv.DictReader((root / "agent_dhara_50_prompt_bank.csv").open(encoding="utf-8"))}
res = [
    json.loads(l)
    for l in (root / "results_run.jsonl").read_text(encoding="utf-8").splitlines()
    if l.strip()
]
res.sort(key=lambda x: x["prompt_num"])

# Human rating for this specific run (session bcbb6a3e-…, 4 blob files assessed).
R: dict[int, tuple[str, str]] = {
    1: ("Partial", "Counts only; no explicit top-5 ranked DQ list"),
    2: ("Pass", "Severity-ranked report summary"),
    3: ("Partial", "No explicit column-level ETL risk ranking"),
    4: ("Partial", "Not null-focused narrative"),
    5: ("Pass", "Scoped duplicate/PK answer"),
    6: ("Partial", "Full report vs PK/identifier focus"),
    7: ("Partial", "Counts vs business-risk framing"),
    8: ("Pass", "DE-oriented report summary"),
    9: ("Partial", "No clear auto vs manual split"),
    10: ("Partial", "Overview vs explicit clean-first order"),
    11: ("Pass", "Full assessment report"),
    12: ("Pass", "Full assessment report"),
    13: ("Partial", "Counts vs inconsistency deep-dive"),
    14: ("Pass", "Readiness via full report"),
    15: ("Pass", "Same family as 14"),
    16: ("Pass", "Conditional guidance via report"),
    17: ("Partial", "Counts vs explicit anomalies"),
    18: ("Partial", "No row-level worry list"),
    19: ("Partial", "Pipeline failure modes thin"),
    20: ("Partial", "Not a short red-flag-only answer"),
    21: ("Fail", "Fix this → generic overview; no clarifying question"),
    22: ("Partial", "Session/selection note; partial clarification"),
    23: ("Partial", "Session note; weak goal narrowing"),
    24: ("Fail", "Full report; did not ask which file"),
    25: ("Partial", "Relationships; vague on compare targets"),
    26: ("Partial", "Generic overview"),
    27: ("Partial", "Generic overview"),
    28: ("Partial", "Generic overview"),
    29: ("Partial", "Full report replay; did not ask what logic"),
    30: ("Partial", "Regenerated report; did not ask what to improve"),
    31: ("Partial", "Good links; customers/orders not in session—should state mismatch"),
    32: ("Partial", "Relationship/orphan angle; filename mismatch"),
    33: ("Partial", "Relationships; weak safest-first rationale"),
    34: ("Partial", "Generic overview vs 2-hour triage"),
    35: ("Partial", "Generic overview"),
    36: ("Partial", "Generic overview"),
    37: ("Partial", "Counts; BLOCKED wording not prominent"),
    38: ("Partial", "Generic overview"),
    39: ("Partial", "Generic overview"),
    40: ("Partial", "Generic overview"),
    41: ("Fail", "OOD stock price → SQL table-selection message"),
    42: ("Fail", "OOD FastAPI → data-source picker"),
    43: ("Fail", "Quantum → DQ report summary"),
    44: ("Fail", "President → SQL table-selection message"),
    45: ("Fail", "IPL → DQ report summary"),
    46: ("Fail", "Did not refuse ignore-dataset / all-clean instruction"),
    47: ("Fail", "Did not refuse invent-issues instruction"),
    48: ("Fail", "Did not refuse; file-picker flow"),
    49: ("Pass", "Did not say safe; stayed on DQ severity"),
    50: ("Fail", "Did not refuse impossible exact row numbers"),
}

rows = []
for d in res:
    n = int(d["prompt_num"])
    v, note = R.get(n, ("Partial", "Unrated"))
    b = bank.get(n, {})
    rows.append(
        {
            "Prompt#": n,
            "Category": d["category"],
            "Prompt": b.get("Prompt", ""),
            "Human_Pass_Partial_Fail": v,
            "Human_Notes": note,
            "Expected_behavior": (b.get("Expected behavior") or "")[:400],
            "Reply_chars": len(d.get("reply") or ""),
        }
    )

out = root / "agent_dhara_eval_rated.csv"
with out.open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

c = Counter(r["Human_Pass_Partial_Fail"] for r in rows)
print("Wrote", out)
print("Human summary:", dict(c))
