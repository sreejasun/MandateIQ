import clsx from "clsx";
import type { ReactNode } from "react";

import { EvidenceRef, Section, StatusTag } from "../../components/ui";
import { humanize, pct } from "../../lib/format";
import type { Challenge, Claim, WorkflowState } from "../../lib/types";

type Speaker = "proponent" | "challenger";

function Avatar({ who }: { who: Speaker }) {
  return (
    <span
      className={clsx(
        "flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold",
        who === "proponent" ? "bg-navy text-white" : "border border-ink bg-paper text-ink",
      )}
      aria-hidden
    >
      {who === "proponent" ? "P" : "C"}
    </span>
  );
}

function Turn({ who, title, children }: { who: Speaker; title: ReactNode; children: ReactNode }) {
  return (
    <li className="relative flex gap-4 pb-7 last:pb-0">
      <span className="absolute bottom-0 left-[13px] top-8 w-px bg-rule" aria-hidden />
      <Avatar who={who} />
      <div className="min-w-0 flex-1">
        <p className="text-sm">
          <span className="font-semibold">{who === "proponent" ? "Proponent" : "Challenger"}</span>
          <span className="text-slate"> {title}</span>
        </p>
        <div className="mt-2 space-y-2">{children}</div>
      </div>
    </li>
  );
}

function RoundHeading({ children }: { children: ReactNode }) {
  return (
    <li className="flex items-center gap-3 pb-6 pt-1">
      <span className="font-serif text-lg font-semibold">{children}</span>
      <span className="h-px flex-1 bg-rule" aria-hidden />
    </li>
  );
}

function Entry({ id, children, struck, aside }: { id: string; children: ReactNode; struck?: boolean; aside?: ReactNode }) {
  return (
    <div className={clsx("rounded border px-3.5 py-2.5", struck ? "border-negative/25 bg-negative-soft/50" : "border-rule bg-paper")}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="text-xs font-medium text-slate">{id}</p>
        {aside}
      </div>
      <div className={clsx("mt-1 text-[0.9375rem] leading-6", struck && "text-slate line-through decoration-negative/60")}>{children}</div>
    </div>
  );
}

function Refs({ ids, onEvidence }: { ids: string[]; onEvidence: (id: string) => void }) {
  if (!ids?.length) return null;
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-slate">
      Evidence {ids.map((id) => <EvidenceRef key={id} id={id} onSelect={onEvidence} />)}
    </div>
  );
}

const SEVERITY_TONE: Record<string, string> = {
  HIGH: "bg-negative-soft text-negative",
  MEDIUM: "bg-caution-soft text-caution",
  LOW: "bg-neutral-soft text-slate",
};

export default function CommitteeTab({ state, onEvidence }: { state: WorkflowState; onEvidence: (id: string) => void }) {
  const prop = state.proponent_result;
  const chal = state.challenger_result;
  const debate = state.debate;
  if (!prop || !chal) return <p className="text-slate">The committee did not produce a result for this case.</p>;

  const verification = Object.fromEntries((state.claim_verifications ?? []).map((v) => [v.claim_id, v]));
  const withdrawn = Object.fromEntries((debate?.withdrawn_claims ?? []).map((w) => [w.claim_id, w]));
  const blocked = new Set(state.governance_gate?.blocked_claim_ids ?? []);

  // Show the opening case as argued: current claims plus any withdrawn later.
  const opening: Claim[] = [...prop.claims];
  for (const c of prop.withdrawn_claims ?? []) {
    if (!opening.some((x) => x.claim_id === c.claim_id)) opening.push(c);
  }
  opening.sort((a, b) => a.claim_id.localeCompare(b.claim_id));
  const challengeById: Record<string, Challenge> = Object.fromEntries(chal.challenges.map((c) => [c.challenge_id, c]));

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2">
        {[{ who: "proponent" as const, r: prop }, { who: "challenger" as const, r: chal }].map(({ who, r }) => (
          <div key={who} className="panel px-5 py-4">
            <div className="flex items-center gap-3">
              <Avatar who={who} />
              <div className="min-w-0">
                <p className="font-medium">{who === "proponent" ? "Proponent" : "Challenger"}</p>
                <p className="text-xs text-slate">{who === "proponent" ? "Argues for approval" : "Looks for reasons to stop"}</p>
              </div>
              <div className="ml-auto text-right">
                <StatusTag value={r.position} />
                <p className="mt-1 text-xs text-slate">Confidence {pct(r.confidence)}</p>
              </div>
            </div>
            <p className="mt-3 text-sm leading-6 text-ink/85">{r.rationale}</p>
            {r.llm_error && <p className="mt-2 text-sm text-negative">Model error: {r.llm_error}</p>}
          </div>
        ))}
      </div>

      <Section
        title="Transcript"
        description={debate ? `${debate.total_rounds} of up to ${debate.max_rounds} rounds. ${humanize(debate.stop_reason)}.` : undefined}
      >
        <ol className="px-5 py-6">
          <RoundHeading>Opening</RoundHeading>

          <Turn who="proponent" title={`presents ${opening.length} claim${opening.length === 1 ? "" : "s"}, each citing evidence`}>
            {opening.map((c) => {
              const w = withdrawn[c.claim_id];
              const v = verification[c.claim_id];
              const status = w?.verification_status ?? v?.status;
              return (
                <Entry
                  key={c.claim_id}
                  id={c.claim_id}
                  struck={!!w || blocked.has(c.claim_id)}
                  aside={
                    <span className="flex items-center gap-1.5">
                      {status && <StatusTag value={status} />}
                      {w && <span className="text-xs text-negative">Withdrawn in round {w.round}</span>}
                    </span>
                  }
                >
                  {c.claim}
                  <Refs ids={c.evidence_ids} onEvidence={onEvidence} />
                </Entry>
              );
            })}
            {prop.weaknesses_acknowledged?.length > 0 && (
              <div className="rounded border border-rule bg-[#FAFBFC] px-3.5 py-2.5 text-sm">
                <p className="text-xs font-medium text-slate">Weaknesses acknowledged</p>
                <ul className="mt-1 list-disc space-y-0.5 pl-4">
                  {prop.weaknesses_acknowledged.map((w) => <li key={w}>{w}</li>)}
                </ul>
              </div>
            )}
          </Turn>

          <Turn who="challenger" title={chal.challenges.length ? `raises ${chal.challenges.length} challenges` : "raises no challenges"}>
            {chal.challenges.map((c) => (
              <Entry
                key={c.challenge_id}
                id={`${c.challenge_id}${c.target_claim ? ` on ${c.target_claim}` : ""}`}
                aside={
                  <span className="flex items-center gap-1.5">
                    <span className={clsx("rounded px-1.5 py-0.5 text-xs font-medium", SEVERITY_TONE[c.severity] ?? SEVERITY_TONE.LOW)}>
                      {humanize(c.severity)}
                    </span>
                    <span className="text-xs text-slate">{humanize(c.challenge_type)}</span>
                  </span>
                }
              >
                {c.reason}
                <Refs ids={c.evidence_ids} onEvidence={onEvidence} />
                {c.resolved && c.resolution && <p className="mt-1.5 text-sm text-positive">Resolved: {c.resolution}</p>}
              </Entry>
            ))}
          </Turn>

          {(debate?.rounds ?? []).map((round) => (
            <li key={round.round} className="list-none">
              <ol>
                <RoundHeading>Round {round.round}</RoundHeading>
                {round.rebuttals.length > 0 && (
                  <Turn who="proponent" title={`answers ${round.rebuttals.length} open challenge${round.rebuttals.length === 1 ? "" : "s"}`}>
                    {round.rebuttals.map((rb) => (
                      <Entry
                        key={rb.challenge_id}
                        id={`Re ${rb.challenge_id}${rb.target_claim ? `, ${rb.target_claim}` : ""}`}
                        aside={<StatusTag value={rb.action === "CONCEDE" ? "REVIEW" : rb.action === "REVISE" ? "WARN" : "PASS"} label={humanize(rb.action)} />}
                      >
                        {rb.response}
                        {rb.revised_claim && <p className="mt-1.5 text-sm"><span className="text-slate">Revised claim:</span> {rb.revised_claim}</p>}
                        <Refs ids={rb.evidence_ids} onEvidence={onEvidence} />
                      </Entry>
                    ))}
                  </Turn>
                )}
                {round.verdicts.length > 0 && (
                  <Turn who="challenger" title="rules on each answer">
                    {round.verdicts.map((v) => (
                      <Entry
                        key={v.challenge_id}
                        id={`${v.challenge_id}${challengeById[v.challenge_id]?.target_claim ? ` on ${challengeById[v.challenge_id].target_claim}` : ""}`}
                        aside={<StatusTag value={v.verdict} label={v.verdict === "ACCEPT" ? "Accepted" : "Maintained"} />}
                      >
                        {v.reason}
                      </Entry>
                    ))}
                  </Turn>
                )}
                {round.rebuttals.length === 0 && round.verdicts.length === 0 && (
                  <li className="pb-6 text-sm text-negative">This round stopped before both agents answered.</li>
                )}
              </ol>
            </li>
          ))}

          {debate && (
            <li className="flex items-center gap-3 pt-2 text-sm text-slate">
              <span className="h-px flex-1 bg-rule" aria-hidden />
              {debate.converged ? "Debate converged" : `Debate ended with ${debate.open_challenge_ids.length} open challenge(s)`}
              <span className="h-px flex-1 bg-rule" aria-hidden />
            </li>
          )}
        </ol>
      </Section>
    </div>
  );
}
