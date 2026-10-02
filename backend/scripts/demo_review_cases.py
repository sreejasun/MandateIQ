"""Print what the review committee + governance layer does on each seeded case.

    LLM_PROVIDER=mock python scripts/demo_review_cases.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("LLM_PROVIDER", "mock")

from tests.fixtures import review_cases as rc  # noqa: E402
from tests.review_pipeline import run_review  # noqa: E402

CASES = [
    ("A  Clean agreement", rc.case_a_clean),
    ("B  Unsupported Proponent claim", rc.case_b_unsupported_claim),
    ("C  Hard policy failure", rc.case_c_policy_failure),
    ("E  Low evidence / confidence", rc.case_e_low_evidence),
    ("+  High fee (cost REVIEW)", rc.case_high_fee_review),
]

for title, fn in CASES:
    s = run_review(fn())
    p, c, pol, g = s["proponent_result"], s["challenger_result"], s["policy_result"], s["governance_gate"]
    print(f"\n=== {title} ({s['case_id']}) ===")
    print(f"Proponent : {p['position']:<20} -> {p['recommended_status']}  conf {p['confidence']}")
    print(f"Challenger: {c['position']:<20} -> {c['recommended_status']}  conf {c['confidence']}")
    for ch in c["challenges"][:4]:
        tgt = ch["target_claim"] or "independent"
        print(f"   {ch['challenge_id']} [{ch['severity']}] vs {tgt}: {ch['reason'][:90]}")
    print(f"Policy    : policy={pol['policy_status']} cost={pol['cost_status']} "
          f"suitability={pol['suitability_status']} critical={pol['has_critical_failure']}")
    print(f"Firewall  : {s['firewall_status']}  blocked={g['blocked_claim_ids']}")
    print(f"Conflicts : {sum(d['material'] for d in s['disagreements'])} material / {len(s['disagreements'])} total")
    print(f"Trust     : {s['trust_score']} ({g['band']}, raw {g['raw_score']}) caps={g['caps_applied']}")
    print(f"GATE      : {g['gate']}  <- {' | '.join(g['reasons'])}")

s = run_review(rc.case_b_unsupported_claim())
s["retry_count"] = 1
s = run_review(s)
print("\n=== B after one re-analysis ===")
print(f"Proponent : {s['proponent_result']['rationale']}")
print(f"Firewall  : {s['firewall_status']}  Trust {s['trust_score']}  GATE {s['governance_gate']['gate']}")
