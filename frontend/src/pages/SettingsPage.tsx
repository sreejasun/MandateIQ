import clsx from "clsx";

import { ErrorNotice, Loading, PageHeader, Section } from "../components/ui";
import { humanize } from "../lib/format";
import { useConfig } from "../lib/hooks";

const ENV_HELP: Record<string, string[]> = {
  bedrock: ["BEDROCK_MODEL_ID", "AWS_REGION", "AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY or AWS_PROFILE"],
  groq: ["GROQ_API_KEY", "GROQ_MODEL (optional)"],
  mock: [],
};

export default function SettingsPage() {
  const config = useConfig();
  if (config.isLoading) return <Loading label="Loading settings" />;
  if (config.isError) return <ErrorNotice error={config.error} title="Settings could not be loaded" />;
  const cfg = config.data!;

  return (
    <>
      <PageHeader
        title="Settings"
        description="Read-only view of how this MandateIQ server is configured. Change values in the .env file and restart the API."
      />

      <div className="space-y-6">
        <Section title="Model providers" description={`New reviews default to ${humanize(cfg.default_provider)} (LLM_PROVIDER).`}>
          <ul className="divide-y divide-rule">
            {cfg.providers.map((p) => (
              <li key={p.id} className="grid gap-2 px-5 py-4 text-sm sm:grid-cols-[12rem_minmax(0,1fr)_auto] sm:items-start">
                <div>
                  <p className="font-medium">{p.label}</p>
                  {p.primary && <p className="text-xs text-navy">Main provider</p>}
                </div>
                <div className="text-slate">
                  <p>{p.detail}</p>
                  {p.model && <p className="mt-0.5 text-xs">Model: <span className="text-ink">{p.model}</span></p>}
                  {ENV_HELP[p.id].length > 0 && (
                    <p className="mt-1 text-xs">Variables: {ENV_HELP[p.id].join(", ")}</p>
                  )}
                </div>
                <span className={clsx(
                  "h-fit w-fit rounded-full px-2 py-0.5 text-xs font-medium",
                  p.available ? "bg-positive-soft text-positive" : "bg-neutral-soft text-slate",
                )}>
                  {p.available ? "Ready" : "Not configured"}
                </span>
              </li>
            ))}
          </ul>
        </Section>

        <div className="grid gap-6 lg:grid-cols-2">
          <Section title="Trust Score routing" description={cfg.trust.version ? `Configuration ${cfg.trust.version}` : undefined}>
            <dl className="divide-y divide-rule px-5 text-sm">
              <div className="flex justify-between py-2.5"><dt className="text-slate">Eligible to finalize from</dt><dd className="font-medium">{cfg.trust.finalize_min}</dd></div>
              <div className="flex justify-between py-2.5"><dt className="text-slate">Rework below</dt><dd className="font-medium">{cfg.trust.reanalysis_min}</dd></div>
              {Object.entries(cfg.trust.weights).map(([k, w]) => (
                <div key={k} className="flex justify-between py-2.5">
                  <dt className="text-slate">{humanize(k)} weight</dt>
                  <dd className="font-medium tabular-nums">{Math.round(w * 100)}%</dd>
                </div>
              ))}
            </dl>
          </Section>

          <Section title="Mandates" description="Defined in backend/config/mandates.yaml.">
            <ul className="divide-y divide-rule">
              {cfg.mandates.map((m) => (
                <li key={m.id} className="px-5 py-3 text-sm">
                  <p className="font-medium">{m.name}</p>
                  <p className="mt-0.5 text-slate">
                    Risk up to {humanize(m.max_risk_level).toLowerCase()}, expense ratio up to {m.max_expense_ratio}%,
                    at least {m.minimum_history_years} years of history, asset classes {m.allowed_asset_classes.map((a) => humanize(a).toLowerCase()).join(", ")}.
                  </p>
                </li>
              ))}
            </ul>
          </Section>
        </div>
      </div>
    </>
  );
}
