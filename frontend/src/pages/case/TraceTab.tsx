import clsx from "clsx";

import { Section, StatusTag } from "../../components/ui";
import { STAGES, dateTime, humanize, num, pct } from "../../lib/format";
import type { ReviewDetail, ToolCall } from "../../lib/types";

function ToolList({ calls }: { calls: ToolCall[] }) {
  if (!calls.length) return <p className="px-5 py-4 text-sm text-slate">No tool calls were recorded.</p>;
  return (
    <ol className="divide-y divide-rule">
      {calls.map((c, i) => (
        <li key={`${c.agent}-${c.step}-${i}`} className="px-5 py-2.5 text-sm">
          <details className="group">
            <summary className="flex cursor-pointer list-none items-center gap-3">
              <span className="w-6 text-right text-xs tabular-nums text-mute">{c.step}</span>
              <span className={clsx("h-1.5 w-1.5 rounded-full", c.ok ? "bg-positive" : "bg-negative")} aria-label={c.ok ? "Succeeded" : "Failed"} />
              <span className="font-medium">{c.tool}</span>
              <span className="min-w-0 flex-1 truncate text-slate">{c.result_summary}</span>
              <span className="text-xs text-navy group-open:hidden">Show</span>
              <span className="hidden text-xs text-navy group-open:inline">Hide</span>
            </summary>
            <div className="ml-9 mt-2 grid gap-2 text-xs">
              <div>
                <p className="text-slate">Input</p>
                <pre className="mt-0.5 overflow-x-auto whitespace-pre-wrap rounded bg-canvas p-2">{JSON.stringify(c.input, null, 2)}</pre>
              </div>
              <div>
                <p className="text-slate">Result</p>
                <pre className="mt-0.5 overflow-x-auto whitespace-pre-wrap rounded bg-canvas p-2">{c.result_summary}</pre>
              </div>
            </div>
          </details>
        </li>
      ))}
    </ol>
  );
}

export default function TraceTab({ review }: { review: ReviewDetail }) {
  const s = review.state!;
  const runs = [s.proponent_result?.run_log, s.challenger_result?.run_log, s.policy_result?.run_log].filter(Boolean);
  const roundCalls = (s.debate?.rounds ?? []).flatMap((r) => [...r.proponent_trace, ...r.challenger_trace]);

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
        <Section title="Pipeline">
          <ol className="px-5 py-4">
            {STAGES.map((stage) => {
              const done = review.events.find((e) => e.stage === stage.id && e.status === "completed");
              return (
                <li key={stage.id} className="flex items-baseline justify-between gap-4 border-b border-rule py-2.5 text-sm last:border-0">
                  <span className="font-medium">{stage.label}</span>
                  <span className="text-slate tabular-nums">{done ? dateTime(done.at) : "—"}</span>
                </li>
              );
            })}
          </ol>
        </Section>

        <Section title="Routing decisions">
          <ol className="divide-y divide-rule">
            {s.route_history.map((step, i) => (
              <li key={i} className="px-5 py-3 text-sm">
                <p className="font-medium">
                  {humanize(step.from_stage)} <span className="text-slate">to</span> {humanize(step.to_stage)}
                </p>
                <p className="mt-0.5 text-slate">{step.reason}</p>
                <p className="mt-1 text-xs text-mute">{step.reason_code}</p>
              </li>
            ))}
          </ol>
        </Section>
      </div>

      <Section title="Agent runs" description="Model, timing and versions recorded for each agent.">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] border-collapse text-sm">
            <thead>
              <tr>{["Agent", "Model", "Latency", "Confidence", "Prompt", "Rules", "Error"].map((h) => <th key={h} className="th">{h}</th>)}</tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r!.agent}>
                  <td className="td font-medium">{humanize(r!.agent)}</td>
                  <td className="td text-slate">{r!.model_id}</td>
                  <td className="td tabular-nums">{num(r!.latency_ms)} ms</td>
                  <td className="td tabular-nums">{pct(r!.confidence)}</td>
                  <td className="td text-slate">{r!.prompt_version ?? "—"}</td>
                  <td className="td text-slate">{r!.rule_version ?? "—"}</td>
                  <td className="td">{r!.error ? <StatusTag value="FAIL" label={r!.error} /> : <span className="text-slate">None</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <div className="grid gap-6 lg:grid-cols-2">
        <Section title="Proponent tool calls" description="Opening turn">
          <ToolList calls={s.proponent_result?.trace ?? []} />
        </Section>
        <Section title="Challenger tool calls" description="Opening turn">
          <ToolList calls={s.challenger_result?.trace ?? []} />
        </Section>
      </div>

      {roundCalls.length > 0 && (
        <Section title="Debate tool calls" description="Rebuttal and verdict rounds">
          <ToolList calls={roundCalls} />
        </Section>
      )}
    </div>
  );
}
