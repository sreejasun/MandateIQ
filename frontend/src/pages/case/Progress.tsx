import { useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Check, Loader2, X } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../../lib/api";
import { STAGES, num } from "../../lib/format";
import type { ReviewDetail, StageEvent } from "../../lib/types";

function detailText(stage: string, d: Record<string, unknown>): string | null {
  switch (stage) {
    case "data_steward":
      return `${d.evidence_count ?? "?"} evidence records, data quality ${num(Number(d.quality_score) * 100, 0)}%`;
    case "committee":
      return `${d.rounds ?? 1} debate round${d.rounds === 1 ? "" : "s"}, ${d.converged ? "converged" : "not converged"}`;
    case "policy":
      return `${d.rules_passed}/${d.rules_total} rules passed`;
    case "governance":
      return `Trust ${num(d.trust_score)}, firewall ${String(d.firewall_status ?? "—").toLowerCase()}`;
    case "supervisor":
      return d.route ? `Route: ${String(d.route).replace(/_/g, " ")}` : null;
    default:
      return null;
  }
}

/** Live, stage-by-stage view of a running review. */
export default function Progress({ review, queryKey }: { review: ReviewDetail; queryKey: unknown[] }) {
  const queryClient = useQueryClient();
  const [events, setEvents] = useState<StageEvent[]>(review.events);
  const live = review.status === "queued" || review.status === "running";

  useEffect(() => {
    if (!live) {
      setEvents(review.events);
      return;
    }
    const source = new EventSource(api.eventsUrl(review.id));
    const seen: StageEvent[] = [];
    source.addEventListener("stage", (e) => {
      seen.push(JSON.parse((e as MessageEvent).data));
      setEvents([...seen]);
    });
    source.addEventListener("done", () => {
      source.close();
      queryClient.invalidateQueries({ queryKey });
      queryClient.invalidateQueries({ queryKey: ["reviews"] });
    });
    let timer: ReturnType<typeof setInterval> | undefined;
    source.onerror = () => {
      // Fall back to polling the case if the stream drops.
      source.close();
      timer = setInterval(() => queryClient.invalidateQueries({ queryKey }), 2000);
    };
    return () => {
      source.close();
      if (timer) clearInterval(timer);
    };
  }, [live, review.id, review.events, queryKey, queryClient]);

  const status = (id: string): "done" | "active" | "failed" | "pending" => {
    const forStage = events.filter((e) => e.stage === id);
    if (forStage.some((e) => e.status === "completed")) return "done";
    if (forStage.some((e) => e.status === "started")) {
      return review.status === "failed" ? "failed" : "active";
    }
    return "pending";
  };

  return (
    <section className="panel px-6 py-6" aria-live="polite">
      <h2 className="font-serif text-xl font-semibold">
        {review.status === "failed" ? "The review stopped" : review.status === "queued" ? "Waiting to start" : "Reviewing this fund"}
      </h2>
      <p className="mt-1 text-sm text-slate">
        {review.status === "failed"
          ? "The stage marked below raised an error. The message is shown underneath."
          : "Each stage appears here as it finishes. You can leave this page; the review keeps running."}
      </p>

      <ol className="mt-6">
        {STAGES.map((s, i) => {
          const st = status(s.id);
          const done = events.find((e) => e.stage === s.id && e.status === "completed");
          return (
            <li key={s.id} className="relative flex gap-4 pb-6 last:pb-0">
              {i < STAGES.length - 1 && (
                <span className={clsx("absolute left-[11px] top-7 h-[calc(100%-1.5rem)] w-px", st === "done" ? "bg-navy" : "bg-rule-strong")} aria-hidden />
              )}
              <span
                className={clsx(
                  "relative z-10 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border",
                  st === "done" && "border-navy bg-navy text-white",
                  st === "active" && "border-navy bg-paper text-navy",
                  st === "failed" && "border-negative bg-negative text-white",
                  st === "pending" && "border-rule-strong bg-paper",
                )}
              >
                {st === "done" && <Check className="h-3.5 w-3.5" aria-hidden />}
                {st === "active" && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
                {st === "failed" && <X className="h-3.5 w-3.5" aria-hidden />}
              </span>
              <div className="min-w-0 pt-0.5">
                <p className={clsx("font-medium", st === "pending" ? "text-mute" : "text-ink")}>{s.label}</p>
                <p className="text-sm text-slate">
                  {done ? detailText(s.id, done.details) : s.description}
                </p>
              </div>
            </li>
          );
        })}
      </ol>

      {review.status === "failed" && review.error && (
        <pre className="mt-6 whitespace-pre-wrap rounded border border-negative/30 bg-negative-soft p-3 text-xs text-negative">
          {review.error}
        </pre>
      )}
    </section>
  );
}
