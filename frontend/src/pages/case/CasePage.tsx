import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowLeft, Trash2 } from "lucide-react";
import { useMemo } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ErrorNotice, Loading, OutcomePill, TrustScale } from "../../components/ui";
import { api } from "../../lib/api";
import { PROVIDER_LABEL, dateTime, duration, mandateName } from "../../lib/format";
import { useConfig } from "../../lib/hooks";
import type { OutcomeKey } from "../../lib/types";
import CommitteeTab from "./CommitteeTab";
import EvidenceTab from "./EvidenceTab";
import OverviewTab from "./OverviewTab";
import Progress from "./Progress";
import TraceTab from "./TraceTab";
import TrustTab from "./TrustTab";
import WhatIfTab from "./WhatIfTab";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "committee", label: "Committee" },
  { id: "evidence", label: "Evidence" },
  { id: "trust", label: "Trust and governance" },
  { id: "trace", label: "Trace" },
  { id: "whatif", label: "What-if" },
] as const;

const VERDICT: Record<OutcomeKey, string> = {
  finalize: "Eligible to finalize",
  human_review: "A person needs to review this fund",
  blocked: "Blocked by a hard policy control",
  rework: "Sent back for rework",
  failed: "The review did not finish",
  pending: "Review in progress",
};

export default function CasePage() {
  const { id = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const config = useConfig();
  const queryKey = useMemo(() => ["review", id], [id]);

  const review = useQuery({ queryKey, queryFn: () => api.review(id) });

  const remove = useMutation({
    mutationFn: () => api.deleteReview(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["reviews"] });
      navigate("/cases");
    },
  });

  const tab = (params.get("tab") as (typeof TABS)[number]["id"]) || "overview";
  const focusEvidence = params.get("ev");
  const goTo = (next: string, ev?: string) => {
    const p = new URLSearchParams();
    p.set("tab", next);
    if (ev) p.set("ev", ev);
    setParams(p, { replace: false });
  };

  if (review.isLoading) return <Loading label="Loading case" />;
  if (review.isError) {
    return (
      <div className="space-y-4">
        <Link to="/cases" className="btn-quiet -ml-3"><ArrowLeft className="h-4 w-4" aria-hidden />Cases</Link>
        <ErrorNotice error={review.error} title="This case could not be loaded" />
      </div>
    );
  }

  const r = review.data!;
  const s = r.state;
  const finalizeMin = config.data?.trust.finalize_min ?? 80;
  const reanalysisMin = config.data?.trust.reanalysis_min ?? 50;
  const running = r.status === "queued" || r.status === "running";
  const reasons = r.overview?.reasons ?? [];
  const verdictNote = reasons.length
    ? `${reasons[0]}${reasons.length > 1 ? ` Plus ${reasons.length - 1} more reason${reasons.length > 2 ? "s" : ""} below.` : ""}`
    : r.overview?.route_reason ?? null;

  return (
    <>
      <Link to="/cases" className="btn-quiet -ml-3 mb-4"><ArrowLeft className="h-4 w-4" aria-hidden />Cases</Link>

      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="font-serif text-[2rem] font-semibold leading-tight tracking-[-0.01em]">{r.fund_name ?? r.fund_id}</h1>
          <dl className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-sm">
            {[
              ["Ticker", r.ticker ?? "—"],
              ["Fund", r.fund_id],
              ["Mandate", mandateName(r.mandate, config.data?.mandates)],
              ["Model", `${PROVIDER_LABEL[r.provider] ?? r.provider}${r.model ? ` (${r.model})` : ""}`],
              ["Case", r.id],
            ].map(([k, v]) => (
              <div key={k} className="flex gap-1.5">
                <dt className="text-slate">{k}</dt>
                <dd className="font-medium text-ink">{v}</dd>
              </div>
            ))}
          </dl>
        </div>
        {!running && (
          <button
            type="button"
            className="btn-quiet"
            disabled={remove.isPending}
            onClick={() => {
              if (window.confirm("Delete this case and its what-if scenarios? This cannot be undone.")) remove.mutate();
            }}
          >
            <Trash2 className="h-4 w-4" aria-hidden />Delete case
          </button>
        )}
      </header>

      {remove.isError && <div className="mb-4"><ErrorNotice error={remove.error} title="The case was not deleted" /></div>}

      {r.status !== "completed" || !s ? (
        <Progress review={r} queryKey={queryKey} />
      ) : (
        <>
          <section className="panel mb-6 grid gap-6 px-6 py-6 md:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] md:gap-10">
            <div>
              <OutcomePill outcome={r.outcome} />
              <p className="mt-3 font-serif text-[1.5rem] font-semibold leading-snug">{VERDICT[r.outcome.key]}</p>
              {verdictNote && <p className="mt-2 text-sm text-slate">{verdictNote}</p>}
              <p className="mt-4 text-xs text-mute">
                Reviewed {dateTime(r.completed_at)}, took {duration(r.started_at, r.completed_at)}
                {r.options?.seed_unsupported_claims ? ". Two unsupported claims were seeded for demonstration." : "."}
              </p>
            </div>
            <div className="flex flex-col justify-center">
              <p className="mb-1 text-sm font-medium text-slate">Trust score</p>
              <TrustScale score={s.trust_score} finalizeMin={finalizeMin} reanalysisMin={reanalysisMin} />
              {r.outcome.key !== "finalize" && (s.trust_score ?? 0) >= finalizeMin && (
                <p className="mt-3 text-xs text-slate">
                  Trust is high, but a high score never overrides a policy, suitability or committee control.
                </p>
              )}
            </div>
          </section>

          <div className="mb-6 overflow-x-auto border-b border-rule" role="tablist" aria-label="Case sections">
            <div className="flex min-w-max gap-6">
              {TABS.map((t) => (
                <button
                  key={t.id}
                  role="tab"
                  aria-selected={tab === t.id}
                  onClick={() => goTo(t.id)}
                  className={clsx(
                    "-mb-px border-b-2 pb-2.5 pt-1 text-sm transition-colors",
                    tab === t.id ? "border-navy font-medium text-ink" : "border-transparent text-slate hover:text-ink",
                  )}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>

          <div role="tabpanel">
            {tab === "overview" && <OverviewTab review={r} onNavigate={goTo} />}
            {tab === "committee" && <CommitteeTab state={s} onEvidence={(ev) => goTo("evidence", ev)} />}
            {tab === "evidence" && <EvidenceTab state={s} focus={focusEvidence} />}
            {tab === "trust" && <TrustTab state={s} config={config.data} />}
            {tab === "trace" && <TraceTab review={r} />}
            {tab === "whatif" && <WhatIfTab review={r} config={config.data} />}
          </div>
        </>
      )}
    </>
  );
}
