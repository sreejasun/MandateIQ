import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { FolderOpen, Loader2, Plus, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { EmptyState, ErrorNotice, Loading, OutcomePill, PageHeader, TrustScale } from "../components/ui";
import { api } from "../lib/api";
import { PROVIDER_LABEL, mandateName, relativeTime } from "../lib/format";
import { useConfig } from "../lib/hooks";
import type { OutcomeKey, ReviewSummary } from "../lib/types";

const FILTERS: { key: "all" | OutcomeKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "finalize", label: "Eligible" },
  { key: "human_review", label: "Human review" },
  { key: "blocked", label: "Blocked" },
  { key: "rework", label: "Needs rework" },
  { key: "failed", label: "Failed" },
];

function isActive(r: ReviewSummary) {
  return r.status === "queued" || r.status === "running";
}

export default function CasesPage() {
  const navigate = useNavigate();
  const config = useConfig();
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["key"]>("all");
  const [query, setQuery] = useState("");

  const reviews = useQuery({
    queryKey: ["reviews"],
    queryFn: api.reviews,
    refetchInterval: (q) => (q.state.data?.some(isActive) ? 2000 : false),
  });

  const rows = reviews.data ?? [];
  const completed = rows.filter((r) => r.status === "completed");
  const scored = completed.filter((r) => r.trust_score != null);
  const count = (k: OutcomeKey) => rows.filter((r) => r.outcome.key === k).length;

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows.filter((r) => {
      if (filter !== "all" && r.outcome.key !== filter) return false;
      if (!q) return true;
      return [r.fund_name, r.ticker, r.fund_id, r.id, r.mandate].some((v) => v?.toLowerCase().includes(q));
    });
  }, [rows, filter, query]);

  const finalizeMin = config.data?.trust.finalize_min ?? 80;
  const reanalysisMin = config.data?.trust.reanalysis_min ?? 50;

  return (
    <>
      <PageHeader
        title="Cases"
        description="Every fund review, with the committee's outcome and how much the evidence can be trusted."
        actions={<Link to="/new" className="btn-primary"><Plus className="h-4 w-4" aria-hidden />New review</Link>}
      />

      {reviews.isError && <div className="mb-6"><ErrorNotice error={reviews.error} title="Cases could not be loaded" /></div>}

      <dl className="panel mb-6 grid grid-cols-2 divide-rule sm:grid-cols-5 sm:divide-x">
        {[
          { label: "Reviews", value: rows.length },
          { label: "Eligible to finalize", value: count("finalize") },
          { label: "Human review", value: count("human_review") },
          { label: "Blocked by policy", value: count("blocked") },
          {
            label: "Average trust",
            value: scored.length
              ? (scored.reduce((s, r) => s + (r.trust_score ?? 0), 0) / scored.length).toFixed(1)
              : "—",
          },
        ].map((s) => (
          <div key={s.label} className="px-5 py-4">
            <dt className="text-xs text-slate">{s.label}</dt>
            <dd className="mt-1 font-serif text-2xl font-semibold tabular-nums text-ink">{s.value}</dd>
          </div>
        ))}
      </dl>

      <div className="panel">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-rule px-4 py-3">
          <div className="flex flex-wrap gap-1" role="tablist" aria-label="Filter by outcome">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                role="tab"
                aria-selected={filter === f.key}
                onClick={() => setFilter(f.key)}
                className={clsx(
                  "rounded px-2.5 py-1 text-sm transition-colors",
                  filter === f.key ? "bg-ink text-white" : "text-slate hover:bg-canvas hover:text-ink",
                )}
              >
                {f.label}
              </button>
            ))}
          </div>
          <label className="relative w-full sm:w-64">
            <span className="sr-only">Search cases</span>
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-mute" aria-hidden />
            <input
              className="input pl-8"
              placeholder="Search fund, ticker or case"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
        </div>

        {reviews.isLoading ? (
          <div className="px-5"><Loading label="Loading cases" /></div>
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<FolderOpen className="h-8 w-8" />}
            title="No reviews yet"
            action={<Link to="/new" className="btn-primary"><Plus className="h-4 w-4" aria-hidden />Start the first review</Link>}
          >
            Pick a fund from the demo dataset or upload your own CSV, and the committee will review it.
          </EmptyState>
        ) : visible.length === 0 ? (
          <EmptyState title="No cases match">Try another filter or search term.</EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] border-collapse text-sm">
              <thead>
                <tr>
                  <th className="th">Fund</th>
                  <th className="th">Mandate</th>
                  <th className="th">Outcome</th>
                  <th className="th">Trust score</th>
                  <th className="th">Model</th>
                  <th className="th text-right">Reviewed</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((r) => (
                  <tr
                    key={r.id}
                    tabIndex={0}
                    onClick={() => navigate(`/cases/${r.id}`)}
                    onKeyDown={(e) => e.key === "Enter" && navigate(`/cases/${r.id}`)}
                    className="cursor-pointer transition-colors hover:bg-[#F8F9FB] focus:bg-navy-50"
                  >
                    <td className="td">
                      <div className="font-medium text-ink">{r.fund_name ?? r.fund_id}</div>
                      <div className="mt-0.5 text-xs text-slate">
                        {r.ticker ?? "—"} <span className="text-mute">/</span> {r.fund_id}
                        <span className="ml-2 text-mute">{r.id}</span>
                      </div>
                    </td>
                    <td className="td text-slate">{mandateName(r.mandate, config.data?.mandates)}</td>
                    <td className="td">
                      {isActive(r) ? (
                        <span className="inline-flex items-center gap-1.5 text-[0.8125rem] text-navy">
                          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                          {r.status === "queued" ? "Queued" : "Reviewing"}
                        </span>
                      ) : (
                        <OutcomePill outcome={r.outcome} size="sm" />
                      )}
                    </td>
                    <td className="td">
                      <TrustScale score={r.trust_score} variant="compact" finalizeMin={finalizeMin} reanalysisMin={reanalysisMin} />
                    </td>
                    <td className="td text-slate">{PROVIDER_LABEL[r.provider] ?? r.provider}</td>
                    <td className="td whitespace-nowrap text-right text-slate">{relativeTime(r.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
