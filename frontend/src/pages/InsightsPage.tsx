import { useQuery } from "@tanstack/react-query";
import { BarChart3 } from "lucide-react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { EmptyState, ErrorNotice, Loading, PageHeader, Section, TONE_FILL } from "../components/ui";
import { api } from "../lib/api";
import { humanize, mandateName, num } from "../lib/format";
import { useConfig } from "../lib/hooks";

const AXIS = { fontSize: 12, fill: "#586174" };
const GRID = "#E7EAEF";
const tooltipStyle = {
  contentStyle: { border: "1px solid #DFE3E9", borderRadius: 6, fontSize: 13, boxShadow: "none" },
  cursor: { fill: "#F4F5F7" },
};

export default function InsightsPage() {
  const config = useConfig();
  const insights = useQuery({ queryKey: ["insights"], queryFn: api.insights });

  if (insights.isLoading) return <Loading label="Loading insights" />;

  const d = insights.data;

  return (
    <>
      <PageHeader title="Insights" description="Patterns across every completed review." />
      {insights.isError && <ErrorNotice error={insights.error} title="Insights could not be loaded" />}

      {d && d.total_reviews === 0 ? (
        <div className="panel">
          <EmptyState icon={<BarChart3 className="h-8 w-8" />} title="Nothing to analyse yet"
            action={<Link to="/new" className="btn-primary">Start a review</Link>}>
            Insights appear once at least one review has finished.
          </EmptyState>
        </div>
      ) : d && (
        <div className="space-y-6">
          <dl className="panel grid grid-cols-2 sm:grid-cols-5 sm:divide-x divide-rule">
            {[
              ["Completed reviews", d.total_reviews],
              ["Average trust", num(d.average_trust)],
              ["Sent to a person", d.human_review_rate == null ? "—" : `${num(d.human_review_rate)}%`],
              ["Firewall failures", d.firewall_failures],
              ["Average debate rounds", num(d.average_debate_rounds, 2)],
            ].map(([label, value]) => (
              <div key={label} className="px-5 py-4">
                <dt className="text-xs text-slate">{label}</dt>
                <dd className="mt-1 font-serif text-2xl font-semibold tabular-nums">{value}</dd>
              </div>
            ))}
          </dl>

          <div className="grid gap-6 lg:grid-cols-2">
            <Section title="Outcomes">
              <div className="h-60 px-3 py-4">
                <ResponsiveContainer>
                  <BarChart data={d.outcomes} layout="vertical" margin={{ left: 24, right: 24 }}>
                    <CartesianGrid horizontal={false} stroke={GRID} />
                    <XAxis type="number" allowDecimals={false} tick={AXIS} axisLine={false} tickLine={false} />
                    <YAxis type="category" dataKey="label" width={130} tick={AXIS} axisLine={false} tickLine={false} />
                    <Tooltip {...tooltipStyle} />
                    <Bar dataKey="count" name="Reviews" radius={[0, 3, 3, 0]} barSize={18}>
                      {d.outcomes.map((o) => <Cell key={o.key} fill={TONE_FILL[o.tone]} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Section>

            <Section title="Trust score distribution">
              <div className="h-60 px-3 py-4">
                <ResponsiveContainer>
                  <BarChart data={d.trust_distribution} margin={{ right: 16 }}>
                    <CartesianGrid vertical={false} stroke={GRID} />
                    <XAxis dataKey="range" tick={AXIS} axisLine={false} tickLine={false} />
                    <YAxis allowDecimals={false} tick={AXIS} axisLine={false} tickLine={false} width={32} />
                    <Tooltip {...tooltipStyle} />
                    <Bar dataKey="count" name="Reviews" fill="#1C3D6E" radius={[3, 3, 0, 0]} barSize={36} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Section>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <Section title="Average trust components" description="Where trust is usually lost.">
              <div className="h-64 px-3 py-4">
                <ResponsiveContainer>
                  <BarChart data={d.components.map((c) => ({ ...c, label: humanize(c.key) }))} layout="vertical" margin={{ left: 24, right: 24 }}>
                    <CartesianGrid horizontal={false} stroke={GRID} />
                    <XAxis type="number" domain={[0, 100]} tick={AXIS} axisLine={false} tickLine={false} />
                    <YAxis type="category" dataKey="label" width={130} tick={AXIS} axisLine={false} tickLine={false} />
                    <Tooltip {...tooltipStyle} />
                    <Bar dataKey="average" name="Average score" fill="#4C78B0" radius={[0, 3, 3, 0]} barSize={14} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Section>

            <Section title="Most frequent risk flags">
              {d.risk_flags.length === 0 ? (
                <p className="px-5 py-4 text-sm text-slate">No risk flags have been raised.</p>
              ) : (
                <ul className="divide-y divide-rule">
                  {d.risk_flags.map((f) => (
                    <li key={f.code} className="flex gap-4 px-5 py-3 text-sm">
                      <span className="w-8 shrink-0 text-right font-serif text-lg font-semibold tabular-nums">{f.count}</span>
                      <span className="min-w-0 text-ink/85">{f.example}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Section>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <Section title="Average trust by mandate">
              <ul className="divide-y divide-rule">
                {d.trust_by_mandate.map((m) => (
                  <li key={m.mandate} className="flex items-center justify-between gap-4 px-5 py-3 text-sm">
                    <span>{mandateName(m.mandate, config.data?.mandates)}</span>
                    <span className="text-slate">
                      <span className="font-medium tabular-nums text-ink">{num(m.average)}</span> across {m.count} review{m.count === 1 ? "" : "s"}
                    </span>
                  </li>
                ))}
              </ul>
            </Section>

            <Section title="Agent response time" description="Average per review, in milliseconds.">
              <ul className="divide-y divide-rule">
                {d.agent_latency_ms.map((a) => (
                  <li key={a.agent} className="flex items-center justify-between px-5 py-3 text-sm">
                    <span>{humanize(a.agent)}</span>
                    <span className="font-medium tabular-nums">{num(a.average)} ms</span>
                  </li>
                ))}
              </ul>
            </Section>
          </div>
        </div>
      )}
    </>
  );
}
