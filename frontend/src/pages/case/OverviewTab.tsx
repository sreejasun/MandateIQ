import { ArrowRight, CircleAlert, UserRound } from "lucide-react";

import { KeyValue, Section, StatusTag } from "../../components/ui";
import { display, humanize, pct } from "../../lib/format";
import type { ReviewDetail } from "../../lib/types";

const FUND_FIELDS = [
  "asset_class", "category", "risk_level", "expense_ratio", "expense_ratio_percentile",
  "history_years", "manager_tenure_years", "return_5y", "volatility",
];

const FUND_LABELS: Record<string, string> = {
  expense_ratio_percentile: "Fee percentile in category",
  history_years: "Track record",
  manager_tenure_years: "Manager tenure",
  return_5y: "5-year return",
};

const FUND_UNITS: Record<string, string> = {
  expense_ratio: "%", return_5y: "%", volatility: "%", history_years: " years", manager_tenure_years: " years",
  expense_ratio_percentile: "th",
};

export default function OverviewTab({ review, onNavigate }: {
  review: ReviewDetail; onNavigate: (tab: string) => void;
}) {
  const o = review.overview!;
  const s = review.state!;
  const fund = s.fund_record ?? {};

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
      <div className="space-y-6">
        <Section title="Why this outcome">
          <ul className="divide-y divide-rule">
            {(o.reasons.length ? o.reasons : ["All controls passed and the committee converged."]).map((reason) => (
              <li key={reason} className="px-5 py-3 text-[0.9375rem] leading-6">{reason}</li>
            ))}
          </ul>
        </Section>

        {o.human_review_items.some((item) => !o.reasons.includes(item)) && (
          <Section title="For the human reviewer" description="Points the system could not settle on its own.">
            <ul className="divide-y divide-rule">
              {o.human_review_items.map((item) => (
                <li key={item} className="flex gap-3 px-5 py-3 text-sm">
                  <UserRound className="mt-0.5 h-4 w-4 shrink-0 text-caution" aria-hidden />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </Section>
        )}

        <Section title="Risk flags" description="Raised by the deterministic policy and suitability rules.">
          {o.risk_flags.length === 0 ? (
            <p className="px-5 py-4 text-sm text-slate">No risk flags were raised.</p>
          ) : (
            <ul className="divide-y divide-rule">
              {o.risk_flags.map((flag) => {
                const [code, ...rest] = flag.split(": ");
                return (
                  <li key={flag} className="flex gap-3 px-5 py-3 text-sm">
                    <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-caution" aria-hidden />
                    <span><span className="font-medium">{code}</span>{rest.length ? ` — ${rest.join(": ")}` : ""}</span>
                  </li>
                );
              })}
            </ul>
          )}
        </Section>
      </div>

      <div className="space-y-6">
        <Section
          title="Controls"
          actions={<button className="btn-quiet -my-1.5 h-8 px-2 text-xs" onClick={() => onNavigate("trust")}>Details<ArrowRight className="h-3.5 w-3.5" aria-hidden /></button>}
        >
          <dl className="divide-y divide-rule px-5">
            <KeyValue label="Hallucination firewall"><StatusTag value={o.firewall_status} /></KeyValue>
            <KeyValue label="Policy"><StatusTag value={o.policy.policy} /></KeyValue>
            <KeyValue label="Cost"><StatusTag value={o.policy.cost} /></KeyValue>
            <KeyValue label="Suitability"><StatusTag value={o.policy.suitability} /></KeyValue>
            <KeyValue label="Rules passed">{o.policy.passed} of {o.policy.total}</KeyValue>
            <KeyValue label="Data quality">{pct(o.quality_score)}</KeyValue>
          </dl>
        </Section>

        <Section
          title="Committee"
          actions={<button className="btn-quiet -my-1.5 h-8 px-2 text-xs" onClick={() => onNavigate("committee")}>Transcript<ArrowRight className="h-3.5 w-3.5" aria-hidden /></button>}
        >
          <dl className="divide-y divide-rule px-5">
            <KeyValue label="Proponent">
              <StatusTag value={o.committee.proponent_position} /> <span className="ml-1 text-slate">{pct(o.committee.proponent_confidence)}</span>
            </KeyValue>
            <KeyValue label="Challenger">
              <StatusTag value={o.committee.challenger_position} /> <span className="ml-1 text-slate">{pct(o.committee.challenger_confidence)}</span>
            </KeyValue>
            <KeyValue label="Claims made">{o.committee.claims}</KeyValue>
            <KeyValue label="Challenges raised">{o.committee.challenges}</KeyValue>
            <KeyValue label="Debate rounds">{s.debate?.total_rounds ?? 1}</KeyValue>
          </dl>
        </Section>

        <Section title="Fund facts">
          <dl className="divide-y divide-rule px-5">
            {FUND_FIELDS.filter((f) => fund[f] != null).map((f) => (
              <KeyValue key={f} label={FUND_LABELS[f] ?? humanize(f)}>
                {f === "risk_level" || f === "asset_class" ? humanize(String(fund[f])) : `${display(fund[f])}${FUND_UNITS[f] ?? ""}`}
              </KeyValue>
            ))}
          </dl>
        </Section>
      </div>
    </div>
  );
}
