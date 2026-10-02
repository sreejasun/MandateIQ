"""Live demo of the agentic review committee: tool use + multi-round debate + governance.

    LLM_PROVIDER=mock python3 scripts/demo_committee.py              # instant, deterministic
    LLM_PROVIDER=bedrock BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-5 \\
        python3 scripts/demo_committee.py B F                        # real agents, chosen cases
    LLM_PROVIDER=groq GROQ_API_KEY=... python3 scripts/demo_committee.py B   # same agents on Groq

Cases: A clean, B hallucination, C policy failure, E missing evidence, FEE high fee,
F persistent disagreement. Pass case letters to run a subset (default: all).
"""
import os
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("LLM_PROVIDER", "mock")

from src.agents.committee_pipeline import run_full_review  # noqa: E402
from tests.fixtures import review_cases as rc  # noqa: E402

CASES = {
    "A": ("Clean agreement", rc.case_a_clean),
    "B": ("Proponent hallucinates -> debate self-correction", rc.case_b_unsupported_claim),
    "C": ("Hard policy failure", rc.case_c_policy_failure),
    "E": ("Missing evidence / low confidence", rc.case_e_low_evidence),
    "FEE": ("High fee", rc.case_high_fee_review),
    "F": ("Imputed fee: debate + hard control (POL-005) -> human", rc.case_f_persistent_disagreement),
}
W = 100


def wrap(text, indent):
    return textwrap.fill(str(text), W, initial_indent=indent, subsequent_indent=indent + "  ")


def show_trace(trace, who):
    for t in trace:
        arg = ", ".join(f"{k}={v}" for k, v in t["input"].items() if k != "cited_values")
        mark = "ok " if t["ok"] else "ERR"
        print(wrap(f"[{mark}] {who}.{t['tool']}({arg[:70]}) -> {t['result_summary'][:90]}", "      "))


def run(key):
    title, fn = CASES[key]
    s = run_full_review(fn())
    p, c, d, g = s["proponent_result"], s["challenger_result"], s["debate"], s["governance_gate"]
    print("\n" + "=" * W)
    print(f"CASE {key}: {title}   [{p['generation_mode']}]")
    print("=" * W)

    print("\nROUND 1 - opening statements")
    print("  Proponent investigated:")
    show_trace(p["trace"], "proponent")
    allclaims = p["claims"] + p.get("withdrawn_claims", [])
    for cl in sorted(allclaims, key=lambda x: x["claim_id"]):
        print(wrap(f"{cl['claim_id']}: {cl['claim']}  {cl['evidence_ids']}", "    "))
    print("  Challenger investigated:")
    show_trace(c["trace"], "challenger")
    for ch in c["challenges"]:
        tgt = ch["target_claim"] or "independent"
        print(wrap(f"{ch['challenge_id']} [{ch['severity']}] vs {tgt}: {ch['reason']}", "    "))

    for r in d["rounds"]:
        print(f"\nROUND {r['round']} - rebuttal (firewall before round: {r['firewall_status_before']}, "
              f"blocked {r['blocked_claim_ids_before']})")
        show_trace(r["proponent_trace"], "proponent")
        for rb in r["rebuttals"]:
            print(wrap(f"Proponent {rb['action']} on {rb['challenge_id']} ({rb['target_claim']}): "
                       f"{rb['response']} {rb['evidence_ids'] or ''}", "    "))
        show_trace(r["challenger_trace"], "challenger")
        for v in r["verdicts"]:
            print(wrap(f"Challenger {v['verdict']} {v['challenge_id']}: {v['reason']}", "    "))

    print(f"\nDEBATE: {d['total_rounds']} round(s), converged={d['converged']} - {d['stop_reason']}")
    if d["withdrawn_claims"]:
        print(f"  withdrawn: {[w['claim_id'] for w in d['withdrawn_claims']]}")
    pol = s["policy_result"]
    print(f"POLICY   : policy={pol['policy_status']} cost={pol['cost_status']} "
          f"suitability={pol['suitability_status']} critical={pol['has_critical_failure']}")
    print(f"FIREWALL : {s['firewall_status']}   TRUST: {s['trust_score']} ({g['band']})")
    print(wrap(f"GATE     : {g['gate']}  <- {' | '.join(g['reasons'])}", ""))


if __name__ == "__main__":
    keys = [k.upper() for k in sys.argv[1:]] or list(CASES)
    for k in keys:
        run(k)
