import clsx from "clsx";
import { Check, X } from "lucide-react";

import { Section, StatusTag } from "../../components/ui";
import { humanize, num } from "../../lib/format";
import type { AppConfig, WorkflowState } from "../../lib/types";

const SHADES = ["#1C3D6E", "#2F5A93", "#4C78B0", "#7398C6", "#9DB7DA", "#C3D3E8"];

export default function TrustTab({ state }: { state: WorkflowState; config?: AppConfig }) {
  const components = Object.values(state.trust_components ?? {});
  const gate = state.governance_gate;
  const raw = gate?.raw_score ?? components.reduce((s, c) => s + c.weighted, 0);
  const capped = state.trust_score != null && raw != null && state.trust_score < raw - 0.05;
  const rules = state.policy_result?.rule_results ?? [];
  const verifications = state.claim_verifications ?? [];
  const conflicts = state.disagreements ?? [];

  return (
    <div className="space-y-6">
      <Section
        title="How the score is built"
        description="Six weighted components add up to the raw score. Hard caps can lower it; nothing can raise it past a failed control."
      >
        <div className="px-5 py-5">
          <div className="flex h-3 w-full overflow-hidden rounded-full bg-[#ECEEF2]" role="img"
            aria-label={`Weighted contributions adding to ${num(raw)}`}>
            {components.map((c, i) => (
              <div key={c.name} style={{ width: `${c.weighted}%`, background: SHADES[i % SHADES.length] }} title={`${humanize(c.name)}: ${num(c.weighted)}`} />
            ))}
          </div>
          <div className="mt-2 flex flex-wrap justify-between gap-2 text-sm">
            <span className="text-slate">Raw score <span className="font-medium text-ink tabular-nums">{num(raw)}</span></span>
            <span className="text-slate">
              Final score <span className="font-medium text-ink tabular-nums">{num(state.trust_score)}</span>
              {capped && gate?.caps_applied?.length ? <span className="ml-1 text-negative">after cap: {gate.caps_applied.join(", ")}</span> : null}
            </span>
          </div>
        </div>

        <div className="overflow-x-auto border-t border-rule">
          <table className="w-full min-w-[680px] border-collapse text-sm">
            <thead>
              <tr>
                <th className="th">Component</th>
                <th className="th w-24 text-right">Weight</th>
                <th className="th w-48">Score</th>
                <th className="th w-24 text-right">Points</th>
                <th className="th">Why</th>
              </tr>
            </thead>
            <tbody>
              {components.map((c, i) => (
                <tr key={c.name}>
                  <td className="td">
                    <span className="mr-2 inline-block h-2.5 w-2.5 rounded-sm align-middle" style={{ background: SHADES[i % SHADES.length] }} aria-hidden />
                    <span className="font-medium">{humanize(c.name)}</span>
                  </td>
                  <td className="td text-right tabular-nums text-slate">{Math.round(c.weight * 100)}%</td>
                  <td className="td">
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 flex-1 rounded-full bg-rule">
                        <div className="h-full rounded-full bg-navy" style={{ width: `${c.score}%` }} />
                      </div>
                      <span className="w-10 text-right tabular-nums">{num(c.score, 0)}</span>
                    </div>
                  </td>
                  <td className="td text-right font-medium tabular-nums">{num(c.weighted)}</td>
                  <td className="td text-slate">{c.explanation}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <div className="grid gap-6 lg:grid-cols-2">
        <Section title="Governance gate">
          <div className="space-y-3 px-5 py-4 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <StatusTag value={gate?.gate} />
              <span className="text-slate">Band {humanize(gate?.band)}</span>
              <span className="text-slate">Material conflicts {gate?.material_conflicts ?? 0}</span>
            </div>
            {gate?.reasons?.length ? (
              <ul className="list-disc space-y-1 pl-4">{gate.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
            ) : <p className="text-slate">No gate reasons were recorded.</p>}
          </div>
        </Section>

        <Section title="Hallucination firewall" actions={<StatusTag value={state.firewall_status} />}>
          {verifications.length === 0 ? (
            <p className="px-5 py-4 text-sm text-slate">No claims were checked.</p>
          ) : (
            <ul className="divide-y divide-rule">
              {verifications.map((v) => (
                <li key={`${v.agent}-${v.claim_id}`} className="px-5 py-3 text-sm">
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-medium">{v.claim_id} <span className="font-normal text-slate">{humanize(v.agent)}</span></span>
                    <StatusTag value={v.status} />
                  </div>
                  {v.problems.length > 0 && (
                    <ul className="mt-1.5 list-disc space-y-0.5 pl-4 text-negative">{v.problems.map((p) => <li key={p}>{p}</li>)}</ul>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>

      <Section title="Policy, cost and suitability rules" description={state.policy_result?.rationale}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] border-collapse text-sm">
            <thead>
              <tr>
                <th className="th w-12"><span className="sr-only">Result</span></th>
                <th className="th">Rule</th>
                <th className="th">Area</th>
                <th className="th">Severity</th>
                <th className="th">Detail</th>
              </tr>
            </thead>
            <tbody>
              {rules.map((r) => (
                <tr key={r.rule_id}>
                  <td className="td">
                    <span className={clsx("flex h-5 w-5 items-center justify-center rounded-full", r.passed ? "bg-positive-soft text-positive" : "bg-negative-soft text-negative")}>
                      {r.passed ? <Check className="h-3 w-3" aria-label="Passed" /> : <X className="h-3 w-3" aria-label="Failed" />}
                    </span>
                  </td>
                  <td className="td">
                    <span className="font-medium">{r.rule_id}</span>
                    <span className="ml-2 text-ink/85">{r.description}</span>
                  </td>
                  <td className="td text-slate">{humanize(r.dimension)}</td>
                  <td className="td text-slate">{humanize(r.severity)}</td>
                  <td className="td text-slate">{r.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="Conflicts between agents">
        {conflicts.length === 0 ? (
          <p className="px-5 py-4 text-sm text-slate">The agents did not contradict each other on any material point.</p>
        ) : (
          <ul className="divide-y divide-rule">
            {conflicts.map((c) => (
              <li key={c.conflict_id} className="px-5 py-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{c.conflict_id}</span>
                  <span className="text-slate">{humanize(c.conflict_type)}</span>
                  {c.material && <span className="rounded bg-caution-soft px-1.5 py-0.5 text-xs text-caution">Material</span>}
                  {c.resolved && <span className="rounded bg-positive-soft px-1.5 py-0.5 text-xs text-positive">Resolved</span>}
                </div>
                <p className="mt-1 text-ink/85">{c.description}</p>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}
