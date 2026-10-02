import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowRight, FlaskConical, Loader2, RotateCcw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { EmptyState, ErrorNotice, OutcomePill, Section, StatusTag, TONE_TEXT, trustTone } from "../../components/ui";
import { api } from "../../lib/api";
import { display, humanize, num, relativeTime } from "../../lib/format";
import type { AppConfig, Comparison, ReviewDetail } from "../../lib/types";

type Values = Record<string, string>;

function initialValues(review: ReviewDetail, config: AppConfig): Values {
  const fund = review.fund ?? {};
  return Object.fromEntries(Object.keys(config.scenario_fields).map((k) => [k, fund[k] == null ? "" : String(fund[k])]));
}

function ComparisonView({ c, config }: { c: Comparison; config: AppConfig }) {
  const { finalize_min: f, reanalysis_min: r } = config.trust;
  const delta = c.trust_delta ?? 0;
  const components = Object.keys({ ...c.before.components, ...c.after.components });

  return (
    <div className="space-y-6">
      <div className="panel grid gap-6 px-6 py-5 sm:grid-cols-[1fr_auto_1fr] sm:items-center">
        {[{ label: "Original", s: c.before }, null, { label: "Scenario", s: c.after }].map((side, i) =>
          side === null ? (
            <ArrowRight key="arrow" className="mx-auto hidden h-5 w-5 text-mute sm:block" aria-hidden />
          ) : (
            <div key={side.label}>
              <p className="text-xs text-slate">{side.label}</p>
              <div className="mt-2 flex items-center gap-3">
                <span className={clsx("font-serif text-[1.75rem] font-semibold tabular-nums", TONE_TEXT[trustTone(side.s.trust_score, f, r)])}>
                  {num(side.s.trust_score)}
                </span>
                <OutcomePill outcome={side.s.outcome} size="sm" />
              </div>
              {i === 2 && (
                <p className={clsx("mt-1 text-sm", delta > 0 ? "text-positive" : delta < 0 ? "text-negative" : "text-slate")}>
                  {delta === 0 ? "No change in trust" : `${delta > 0 ? "+" : ""}${num(delta)} trust points`}
                  {c.outcome_changed ? ", outcome changed" : ", same outcome"}
                </p>
              )}
            </div>
          ),
        )}
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <Section title="What changed">
          <ul className="divide-y divide-rule">
            {c.changes.map((ch) => (
              <li key={ch.field} className="flex items-center justify-between gap-3 px-5 py-2.5 text-sm">
                <span>{ch.label}</span>
                <span className="tabular-nums">
                  <span className="text-slate line-through decoration-mute">{ch.field === "risk_level" ? humanize(String(ch.before)) : display(ch.before)}</span>
                  <span className="mx-2 text-mute">to</span>
                  <span className="font-medium">{ch.field === "risk_level" ? humanize(String(ch.after)) : display(ch.after)}</span>
                </span>
              </li>
            ))}
          </ul>
        </Section>

        <Section title="Rules affected">
          <div className="space-y-3 px-5 py-4 text-sm">
            {c.rules_now_passing.length === 0 && c.rules_now_failing.length === 0 && <p className="text-slate">No rule changed its result.</p>}
            {c.rules_now_passing.length > 0 && <p><span className="font-medium text-positive">Now passing:</span> {c.rules_now_passing.join(", ")}</p>}
            {c.rules_now_failing.length > 0 && <p><span className="font-medium text-negative">Now failing:</span> {c.rules_now_failing.join(", ")}</p>}
            <div className="flex flex-wrap gap-2 border-t border-rule pt-3">
              {(["policy_status", "cost_status", "suitability_status"] as const).map((k) => (
                <span key={k} className="text-xs text-slate">
                  {humanize(k.replace("_status", ""))}: <StatusTag value={c.before[k]} /> <ArrowRight className="inline h-3 w-3" aria-hidden /> <StatusTag value={c.after[k]} />
                </span>
              ))}
            </div>
          </div>
        </Section>
      </div>

      <Section title="Trust components">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[520px] border-collapse text-sm">
            <thead>
              <tr>
                <th className="th">Component</th>
                <th className="th text-right">Original</th>
                <th className="th text-right">Scenario</th>
                <th className="th text-right">Change</th>
              </tr>
            </thead>
            <tbody>
              {components.map((k) => {
                const b = c.before.components[k] ?? 0;
                const a = c.after.components[k] ?? 0;
                const d = a - b;
                return (
                  <tr key={k}>
                    <td className="td">{humanize(k)}</td>
                    <td className="td text-right tabular-nums text-slate">{num(b)}</td>
                    <td className="td text-right tabular-nums">{num(a)}</td>
                    <td className={clsx("td text-right tabular-nums", d > 0 ? "text-positive" : d < 0 ? "text-negative" : "text-mute")}>
                      {Math.abs(d) < 0.05 ? "—" : `${d > 0 ? "+" : ""}${num(d)}`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Section>
    </div>
  );
}

export default function WhatIfTab({ review, config }: { review: ReviewDetail; config?: AppConfig }) {
  const queryClient = useQueryClient();
  const [values, setValues] = useState<Values>({});
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (config) setValues(initialValues(review, config));
  }, [config, review]);

  const scenarios = useQuery({
    queryKey: ["scenarios", review.id],
    queryFn: () => api.scenarios(review.id),
    refetchInterval: (q) => (q.state.data?.some((s) => s.status === "queued" || s.status === "running") ? 1500 : false),
  });

  useEffect(() => {
    if (!selected && scenarios.data?.length) setSelected(scenarios.data[0].id);
  }, [scenarios.data, selected]);

  const scenario = useQuery({
    queryKey: ["scenario", selected],
    queryFn: () => api.scenario(selected!),
    enabled: !!selected,
    refetchInterval: (q) => (q.state.data && ["queued", "running"].includes(q.state.data.status) ? 1500 : false),
  });

  const original = useMemo(() => (config ? initialValues(review, config) : {}), [config, review]);
  const changes = useMemo(() => {
    const out: Record<string, string | number> = {};
    if (!config) return out;
    for (const [k, field] of Object.entries(config.scenario_fields)) {
      if (values[k] === undefined || values[k] === original[k] || values[k] === "") continue;
      if (field.type === "number") {
        const n = Number(values[k]);
        if (!Number.isNaN(n) && n !== Number(original[k])) out[k] = n;
      } else {
        out[k] = values[k];
      }
    }
    return out;
  }, [values, original, config]);

  const run = useMutation({
    mutationFn: () => api.startScenario(review.id, changes),
    onSuccess: ({ id }) => {
      setSelected(id);
      queryClient.invalidateQueries({ queryKey: ["scenarios", review.id] });
    },
  });

  if (!config) return null;

  return (
    <div className="grid gap-6 lg:grid-cols-[18rem_minmax(0,1fr)]">
      <div className="space-y-6">
        <Section title="Change the fund" description="Rerun this exact review with different values.">
          <form
            className="space-y-4 px-5 py-4"
            onSubmit={(e) => { e.preventDefault(); if (Object.keys(changes).length) run.mutate(); }}
          >
            {Object.entries(config.scenario_fields).map(([key, field]) => {
              const changed = key in changes;
              return (
                <label key={key} className="block">
                  <span className="field-label flex items-center justify-between">
                    {field.label}{field.unit ? <span className="font-normal text-slate">{field.unit}</span> : null}
                  </span>
                  {field.type === "select" ? (
                    <select
                      className={clsx("input mt-1", changed && "border-navy bg-navy-50")}
                      value={values[key] ?? ""}
                      onChange={(e) => setValues({ ...values, [key]: e.target.value })}
                    >
                      {config.risk_levels.map((lvl) => <option key={lvl} value={lvl}>{humanize(lvl)}</option>)}
                    </select>
                  ) : (
                    <input
                      type="number"
                      className={clsx("input mt-1 tabular-nums", changed && "border-navy bg-navy-50")}
                      min={field.min} max={field.max} step={field.step}
                      value={values[key] ?? ""}
                      onChange={(e) => setValues({ ...values, [key]: e.target.value })}
                    />
                  )}
                  {changed && <span className="field-hint mt-1 block">Originally {key === "risk_level" ? humanize(original[key]) : original[key] || "empty"}</span>}
                </label>
              );
            })}

            {run.isError && <ErrorNotice error={run.error} title="The scenario could not start" />}

            <div className="flex gap-2 pt-1">
              <button type="submit" className="btn-primary flex-1" disabled={!Object.keys(changes).length || run.isPending}>
                {run.isPending && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}Run scenario
              </button>
              <button type="button" className="btn-secondary" onClick={() => setValues(original)} aria-label="Reset values">
                <RotateCcw className="h-4 w-4" aria-hidden />
              </button>
            </div>
          </form>
        </Section>

        {(scenarios.data?.length ?? 0) > 0 && (
          <Section title="Scenarios run">
            <ul className="divide-y divide-rule">
              {scenarios.data!.map((sc) => (
                <li key={sc.id}>
                  <button
                    type="button"
                    onClick={() => setSelected(sc.id)}
                    className={clsx("w-full px-5 py-3 text-left text-sm hover:bg-canvas", selected === sc.id && "bg-navy-50 hover:bg-navy-50")}
                  >
                    <span className="block font-medium">
                      {Object.entries(sc.changes ?? {}).map(([k, v]) => `${config.scenario_fields[k]?.label ?? k} ${k === "risk_level" ? humanize(String(v)) : v}`).join(", ")}
                    </span>
                    <span className="mt-0.5 flex items-center justify-between text-xs text-slate">
                      {sc.status === "completed" ? <>Trust {num(sc.trust_score)}</> : humanize(sc.status)}
                      <span>{relativeTime(sc.created_at)}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </Section>
        )}
      </div>

      <div className="min-w-0">
        {!selected ? (
          <div className="panel">
            <EmptyState icon={<FlaskConical className="h-8 w-8" />} title="No scenarios yet">
              Change a value on the left, such as a lower expense ratio or a different risk level, and run it to see
              whether the outcome would change. The original case is never modified.
            </EmptyState>
          </div>
        ) : scenario.isLoading || !scenario.data || ["queued", "running"].includes(scenario.data.status) ? (
          <div className="panel flex items-center gap-2 px-6 py-10 text-sm text-slate" role="status">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />Running the scenario through the full pipeline…
          </div>
        ) : scenario.data.status === "failed" ? (
          <ErrorNotice error={scenario.data.error ?? "Unknown error"} title="The scenario failed" />
        ) : scenario.data.comparison ? (
          <ComparisonView c={scenario.data.comparison} config={config} />
        ) : null}
      </div>
    </div>
  );
}
