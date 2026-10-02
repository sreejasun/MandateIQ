import clsx from "clsx";
import { AlertTriangle, Loader2 } from "lucide-react";
import type { ReactNode } from "react";
import type { Outcome, Tone } from "../lib/types";
import { humanize } from "../lib/format";

// ------------------------------------------------------------------ tones

export const TONE_TEXT: Record<Tone, string> = {
  positive: "text-positive",
  caution: "text-caution",
  negative: "text-negative",
  rework: "text-rework",
  neutral: "text-slate",
};

export const TONE_BG: Record<Tone, string> = {
  positive: "bg-positive-soft text-positive",
  caution: "bg-caution-soft text-caution",
  negative: "bg-negative-soft text-negative",
  rework: "bg-rework-soft text-rework",
  neutral: "bg-neutral-soft text-slate",
};

const TONE_DOT: Record<Tone, string> = {
  positive: "bg-positive",
  caution: "bg-caution",
  negative: "bg-negative",
  rework: "bg-rework",
  neutral: "bg-mute",
};

export const TONE_FILL: Record<Tone, string> = {
  positive: "#1B6E4A",
  caution: "#B9771A",
  negative: "#AE3A2D",
  rework: "#5A3E9B",
  neutral: "#8A93A3",
};

export function OutcomePill({ outcome, size = "md" }: { outcome: Outcome; size?: "sm" | "md" }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full font-medium",
        TONE_BG[outcome.tone],
        size === "sm" ? "px-2 py-0.5 text-xs" : "px-2.5 py-1 text-[0.8125rem]",
      )}
    >
      <span className={clsx("h-1.5 w-1.5 rounded-full", TONE_DOT[outcome.tone])} aria-hidden />
      {outcome.label}
    </span>
  );
}

/** PASS / FAIL / REVIEW style status words used by policy and firewall results. */
export function statusTone(value: string | null | undefined): Tone {
  const v = String(value ?? "").toUpperCase();
  if (["PASS", "VERIFIED", "ACCEPT", "FINALIZE_ELIGIBLE", "SUPPORT", "HIGH_BAND"].includes(v)) return "positive";
  if (["FAIL", "CONTRADICTED", "INVALID_REFERENCE", "REJECT", "OPPOSE", "BLOCKED"].includes(v)) return "negative";
  if (["REVIEW", "WARN", "UNSUPPORTED", "HUMAN_REVIEW_REQUIRED", "CHALLENGE", "CONDITIONAL_SUPPORT", "MAINTAIN",
    "REANALYSIS_SUGGESTED"].includes(v)) return "caution";
  return "neutral";
}

export function StatusTag({ value, label }: { value: string | null | undefined; label?: string }) {
  const tone = statusTone(value);
  return (
    <span className={clsx("inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium", TONE_BG[tone])}>
      {label ?? humanize(value)}
    </span>
  );
}

// ------------------------------------------------------------------ trust scale

export function trustTone(score: number | null | undefined, finalizeMin: number, reanalysisMin: number): Tone {
  if (score == null) return "neutral";
  if (score >= finalizeMin) return "positive";
  if (score >= reanalysisMin) return "caution";
  return "negative";
}

/**
 * The Trust Score drawn as a measured scale rather than a gauge: the reader
 * sees where the score sits relative to the two routing thresholds.
 */
export function TrustScale({
  score, finalizeMin = 80, reanalysisMin = 50, variant = "full",
}: { score: number | null | undefined; finalizeMin?: number; reanalysisMin?: number; variant?: "full" | "compact" }) {
  const tone = trustTone(score, finalizeMin, reanalysisMin);
  const value = score == null ? 0 : Math.max(0, Math.min(100, score));

  if (variant === "compact") {
    return (
      <div className="flex items-center gap-2.5" aria-label={score == null ? "No trust score" : `Trust score ${score}`}>
        <span className={clsx("w-9 text-right font-serif text-[0.9375rem] font-semibold tabular-nums", TONE_TEXT[tone])}>
          {score == null ? "—" : Math.round(score)}
        </span>
        <div className="relative h-1.5 w-24 rounded-full bg-rule">
          <div className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${value}%`, background: TONE_FILL[tone] }} />
          <div className="absolute -top-0.5 h-2.5 w-px bg-ink/40" style={{ left: `${finalizeMin}%` }} />
        </div>
      </div>
    );
  }

  return (
    <figure className="w-full" aria-label={score == null ? "No trust score" : `Trust score ${score} out of 100`}>
      <div className="relative h-14">
        {/* needle label */}
        {score != null && (
          <div
            className="absolute top-0 -translate-x-1/2 text-center"
            style={{ left: `${Math.min(Math.max(value, 4), 96)}%` }}
          >
            <span className={clsx("font-serif text-[1.75rem] font-semibold leading-none tabular-nums", TONE_TEXT[tone])}>
              {score.toFixed(1)}
            </span>
          </div>
        )}
        {/* track */}
        <div className="absolute inset-x-0 bottom-3 h-2 overflow-hidden rounded-full bg-[#ECEEF2]">
          <div
            className="h-full rounded-full transition-[width] duration-700 ease-out"
            style={{ width: `${value}%`, background: TONE_FILL[tone] }}
          />
        </div>
        {/* thresholds */}
        {[reanalysisMin, finalizeMin].map((t) => (
          <div key={t} className="absolute bottom-1.5 h-5 w-px bg-ink/50" style={{ left: `${t}%` }} aria-hidden />
        ))}
        {/* ticks */}
        {Array.from({ length: 11 }, (_, i) => i * 10).map((t) => (
          <div key={t} className="absolute bottom-0 h-1 w-px bg-rule-strong" style={{ left: `${t}%` }} aria-hidden />
        ))}
      </div>
      <figcaption className="relative mt-1 h-4 text-2xs text-slate">
        <span className="absolute left-0">0</span>
        <span className="absolute -translate-x-1/2 whitespace-nowrap" style={{ left: `${reanalysisMin}%` }}>
          <span className="hidden sm:inline">Rework below </span>{reanalysisMin}
        </span>
        <span className="absolute -translate-x-1/2 whitespace-nowrap" style={{ left: `${finalizeMin}%` }}>
          <span className="hidden sm:inline">Finalize from </span>{finalizeMin}
        </span>
        <span className="absolute right-0">100</span>
      </figcaption>
    </figure>
  );
}

// ------------------------------------------------------------------ layout

export function PageHeader({ title, description, actions, children }: {
  title: ReactNode; description?: ReactNode; actions?: ReactNode; children?: ReactNode;
}) {
  return (
    <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="font-serif text-[2rem] font-semibold leading-tight tracking-[-0.01em] text-ink">{title}</h1>
        {description && <p className="mt-1.5 max-w-2xl text-slate">{description}</p>}
        {children}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </header>
  );
}

export function Section({ title, description, actions, children, className }: {
  title?: ReactNode; description?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={clsx("panel", className)}>
      {(title || actions) && (
        <div className="flex items-start justify-between gap-4 border-b border-rule px-5 py-3.5">
          <div>
            <h2 className="text-[0.9375rem] font-semibold text-ink">{title}</h2>
            {description && <p className="mt-0.5 text-sm text-slate">{description}</p>}
          </div>
          {actions}
        </div>
      )}
      <div>{children}</div>
    </section>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-16 text-sm text-slate" role="status">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> {label}…
    </div>
  );
}

export function ErrorNotice({ error, title = "Something went wrong" }: { error: unknown; title?: string }) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="flex gap-3 rounded-panel border border-negative/30 bg-negative-soft px-4 py-3 text-sm" role="alert">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-negative" aria-hidden />
      <div>
        <p className="font-medium text-negative">{title}</p>
        <p className="mt-0.5 text-ink/80">{message}</p>
      </div>
    </div>
  );
}

export function EmptyState({ icon, title, children, action }: {
  icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center px-6 py-14 text-center">
      {icon && <div className="mb-3 text-mute">{icon}</div>}
      <p className="font-medium text-ink">{title}</p>
      {children && <p className="mt-1 max-w-md text-sm text-slate">{children}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function EvidenceRef({ id, onSelect }: { id: string; onSelect?: (id: string) => void }) {
  const missing = !/^EV-\d+$/.test(id);
  const cls = clsx(
    "inline-flex items-center rounded border px-1.5 text-xs font-medium tabular-nums",
    missing ? "border-negative/30 bg-negative-soft text-negative" : "border-navy-100 bg-navy-50 text-navy",
  );
  if (!onSelect) return <span className={cls}>{id}</span>;
  return (
    <button type="button" className={clsx(cls, "hover:border-navy")} onClick={() => onSelect(id)}>
      {id}
    </button>
  );
}

export function KeyValue({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-2 text-sm">
      <dt className="text-slate">{label}</dt>
      <dd className="text-right font-medium text-ink">{children}</dd>
    </div>
  );
}
