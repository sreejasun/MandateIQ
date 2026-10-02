import clsx from "clsx";
import { Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { EmptyState, Section } from "../../components/ui";
import { display, humanize, pct } from "../../lib/format";
import type { WorkflowState } from "../../lib/types";

type Filter = "all" | "cited" | "imputed";

export default function EvidenceTab({ state, focus }: { state: WorkflowState; focus: string | null }) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const focusRow = useRef<HTMLTableRowElement>(null);

  const citedBy = useMemo(() => {
    const map: Record<string, string[]> = {};
    const add = (ev: string, by: string) => { (map[ev] ??= []).includes(by) || map[ev].push(by); };
    state.proponent_result?.claims.forEach((c) => c.evidence_ids.forEach((e) => add(e, c.claim_id)));
    state.challenger_result?.challenges.forEach((c) => c.evidence_ids.forEach((e) => add(e, c.challenge_id)));
    state.policy_result?.rule_results.forEach((r) => r.evidence_ids.forEach((e) => add(e, r.rule_id)));
    return map;
  }, [state]);

  const records = state.evidence_ledger ?? [];
  const missingRef = focus && !records.some((r) => r.evidence_id === focus) ? focus : null;

  const visible = records.filter((r) => {
    if (filter === "cited" && !citedBy[r.evidence_id]) return false;
    if (filter === "imputed" && !r.metadata?.imputed) return false;
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return [r.evidence_id, r.field, String(r.value), r.source, r.calculation].some((v) => v?.toLowerCase().includes(q));
  });

  useEffect(() => {
    focusRow.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [focus]);

  const quality = state.quality_report;

  return (
    <div className="space-y-6">
      {missingRef && (
        <div className="rounded-panel border border-negative/30 bg-negative-soft px-4 py-3 text-sm text-negative" role="status">
          {missingRef} is not in the evidence ledger. A claim that cites it is unsupported, which is what the
          hallucination firewall checks for.
        </div>
      )}

      <Section
        title="Evidence ledger"
        description="Every value the agents may cite, recorded by the Data Steward with its source and calculation."
      >
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-rule px-4 py-3">
          <div className="flex gap-1" role="tablist" aria-label="Filter evidence">
            {([["all", "All"], ["cited", "Cited"], ["imputed", "Imputed"]] as const).map(([key, label]) => (
              <button
                key={key}
                role="tab"
                aria-selected={filter === key}
                onClick={() => setFilter(key)}
                className={clsx("rounded px-2.5 py-1 text-sm", filter === key ? "bg-ink text-white" : "text-slate hover:bg-canvas hover:text-ink")}
              >
                {label}
              </button>
            ))}
          </div>
          <label className="relative w-full sm:w-64">
            <span className="sr-only">Search evidence</span>
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-mute" aria-hidden />
            <input className="input pl-8" placeholder="Search field, value or ID" value={query} onChange={(e) => setQuery(e.target.value)} />
          </label>
        </div>

        {visible.length === 0 ? (
          <EmptyState title="No evidence matches">Clear the search or choose another filter.</EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] border-collapse text-sm">
              <thead>
                <tr>
                  {["ID", "Field", "Value", "Calculation", "Source", "Cited by"].map((h) => <th key={h} className="th">{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {visible.map((r) => {
                  const isFocus = r.evidence_id === focus;
                  return (
                    <tr key={r.evidence_id} ref={isFocus ? focusRow : undefined} className={clsx(isFocus && "bg-navy-50")}>
                      <td className="td font-medium tabular-nums text-navy">{r.evidence_id}</td>
                      <td className="td">
                        {humanize(r.field)}
                        {Boolean(r.metadata?.imputed) && <span className="ml-2 rounded bg-caution-soft px-1.5 py-0.5 text-xs text-caution">Imputed</span>}
                      </td>
                      <td className="td font-medium tabular-nums">{display(r.value)}</td>
                      <td className="td text-slate">{humanize(r.calculation)}</td>
                      <td className="td text-slate">{r.source}</td>
                      <td className="td text-xs text-slate">{(citedBy[r.evidence_id] ?? []).join(", ") || "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <div className="grid gap-6 md:grid-cols-2">
        <Section title="Data quality">
          <div className="px-5 py-4 text-sm">
            <p>
              <span className="font-serif text-2xl font-semibold tabular-nums">{pct(state.quality_score)}</span>
              <span className="ml-2 text-slate">{quality?.passed ? "Passed the quality threshold" : "Below the quality threshold"}</span>
            </p>
            {quality?.issues?.length ? (
              <ul className="mt-3 list-disc space-y-1 pl-4 text-slate">
                {quality.issues.map((i, n) => <li key={n}>{display(i)}</li>)}
              </ul>
            ) : <p className="mt-2 text-slate">No quality issues found.</p>}
          </div>
        </Section>
        <Section title="Transformations">
          <div className="px-5 py-4 text-sm">
            {state.transformation_log?.length ? (
              <ul className="list-disc space-y-1 pl-4 text-slate">
                {state.transformation_log.map((t, n) => <li key={n}>{display(t)}</li>)}
              </ul>
            ) : <p className="text-slate">The data needed no cleaning or derived fields beyond direct observation.</p>}
          </div>
        </Section>
      </div>
    </div>
  );
}
