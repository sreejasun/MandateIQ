import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowLeft, Check, Database, FileUp, Loader2 } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState, type DragEvent, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { ErrorNotice, Loading, PageHeader } from "../components/ui";
import { api } from "../lib/api";
import { display, humanize, mandateName } from "../lib/format";
import { useConfig } from "../lib/hooks";
import type { Dataset, FundRow, ProviderId } from "../lib/types";

const STEPS = ["Dataset", "Fund and mandate", "Model", "Confirm"];
const VISIBLE_ROWS = 5;
const PREVIEW_COLUMNS =["fund_id", "fund_name", "ticker", "asset_class", "risk_level", "expense_ratio", "history_years"];

function Stepper({ step, onJump }: { step: number; onJump: (i: number) => void }) {
  return (
    <ol className="mb-8 flex flex-wrap items-center gap-x-2 gap-y-3" aria-label="Progress">
      {STEPS.map((label, i) => {
        const done = i < step;
        const current = i === step;
        return (
          <li key={label} className="flex items-center gap-2">
            <button
              type="button"
              disabled={!done}
              onClick={() => onJump(i)}
              aria-current={current ? "step" : undefined}
              className={clsx("flex items-center gap-2 rounded py-1 pr-1 text-sm", done && "hover:text-navy")}
            >
              <span
                className={clsx(
                  "flex h-6 w-6 items-center justify-center rounded-full border text-xs font-semibold tabular-nums",
                  done && "border-navy bg-navy text-white",
                  current && "border-navy text-navy",
                  !done && !current && "border-rule-strong text-mute",
                )}
              >
                {done ? <Check className="h-3.5 w-3.5" aria-hidden /> : i + 1}
              </span>
              <span className={clsx(current ? "font-medium text-ink" : done ? "text-ink" : "text-mute")}>{label}</span>
            </button>
            {i < STEPS.length - 1 && <span className="h-px w-8 bg-rule-strong" aria-hidden />}
          </li>
        );
      })}
    </ol>
  );
}

function Choice({ selected, disabled, onSelect, children, className }: {
  selected: boolean; disabled?: boolean; onSelect: () => void; children: ReactNode; className?: string;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      disabled={disabled}
      onClick={onSelect}
      className={clsx(
        "relative w-full rounded-panel border bg-paper p-4 text-left transition-colors",
        selected ? "border-navy ring-1 ring-navy" : "border-rule hover:border-rule-strong",
        disabled && "cursor-not-allowed bg-canvas opacity-70 hover:border-rule",
        className,
      )}
    >
      {selected && (
        <span className="absolute right-3 top-3 flex h-5 w-5 items-center justify-center rounded-full bg-navy text-white">
          <Check className="h-3 w-3" aria-hidden />
        </span>
      )}
      {children}
    </button>
  );
}

function FundTable({ dataset, selected, onSelect }: {
  dataset: Dataset; selected?: string | null; onSelect?: (id: string) => void;
}) {
  const cols = PREVIEW_COLUMNS.filter((c) => dataset.columns.includes(c));
  const box = useRef<HTMLDivElement>(null);
  const [maxHeight, setMaxHeight] = useState<number>();

  // Size the box to the header plus the first VISIBLE_ROWS rows; the rest scroll inside it.
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const measure = () => {
      const head = el.querySelector("thead")?.getBoundingClientRect().height ?? 0;
      const rows = Array.from(el.querySelectorAll("tbody tr")).slice(0, VISIBLE_ROWS);
      const body = rows.reduce((sum, r) => sum + r.getBoundingClientRect().height, 0);
      setMaxHeight(rows.length < dataset.rows.length ? Math.ceil(head + body) + 2 : undefined);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [dataset, cols.length]);

  return (
    <div ref={box} style={{ maxHeight }} className="overflow-auto rounded-panel border border-rule">
      <table className="w-full min-w-[640px] border-collapse text-sm" role={onSelect ? "radiogroup" : undefined}>
        <thead className="sticky top-0 z-10">
          <tr>
            {onSelect && <th className="th w-10"><span className="sr-only">Select</span></th>}
            {cols.map((c) => <th key={c} className="th">{humanize(c)}</th>)}
          </tr>
        </thead>
        <tbody>
          {dataset.rows.map((row: FundRow) => {
            const id = String(row.fund_id);
            const isSel = selected === id;
            return (
              <tr
                key={id}
                onClick={onSelect ? () => onSelect(id) : undefined}
                className={clsx(onSelect && "cursor-pointer hover:bg-[#F8F9FB]", isSel && "bg-navy-50 hover:bg-navy-50")}
              >
                {onSelect && (
                  <td className="td">
                    <input
                      type="radio"
                      name="fund"
                      checked={isSel}
                      onChange={() => onSelect(id)}
                      className="h-4 w-4 accent-navy"
                      aria-label={`Select ${row.fund_name ?? id}`}
                    />
                  </td>
                )}
                {cols.map((c) => (
                  <td key={c} className={clsx("td", c === "fund_name" ? "font-medium" : "text-slate")}>
                    {c === "risk_level" ? humanize(String(row[c] ?? "")) : display(row[c])}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function NewReviewPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const config = useConfig();
  const fileInput = useRef<HTMLInputElement>(null);

  const [step, setStep] = useState(0);
  const [datasetId, setDatasetId] = useState<string>("demo");
  const [fundId, setFundId] = useState<string | null>(null);
  const [mandate, setMandate] = useState<string | null>(null);
  const [provider, setProvider] = useState<ProviderId | null>(null);
  const [seed, setSeed] = useState(false);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [step]);

  const datasets = useQuery({ queryKey: ["datasets"], queryFn: api.datasets });
  const dataset = useQuery({ queryKey: ["dataset", datasetId], queryFn: () => api.dataset(datasetId) });

  useEffect(() => {
    if (!config.data) return;
    setMandate((m) => m ?? config.data.default_mandate);
    setProvider((p) => {
      if (p) return p;
      const preferred = config.data.providers.find((x) => x.id === config.data.default_provider && x.available);
      return preferred?.id ?? config.data.providers.find((x) => x.available)?.id ?? "mock";
    });
  }, [config.data]);

  const upload = useMutation({
    mutationFn: api.uploadDataset,
    onSuccess: (ds) => {
      queryClient.setQueryData(["dataset", ds.id], ds);
      queryClient.invalidateQueries({ queryKey: ["datasets"] });
      setDatasetId(ds.id);
      setFundId(null);
    },
  });

  const start = useMutation({
    mutationFn: api.startReview,
    onSuccess: ({ id }) => {
      queryClient.invalidateQueries({ queryKey: ["reviews"] });
      navigate(`/cases/${id}`);
    },
  });

  const onFile = (file: File | undefined) => {
    if (file) upload.mutate(file);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    onFile(e.dataTransfer.files?.[0]);
  };

  if (config.isLoading) return <Loading label="Loading settings" />;
  if (config.isError) return <ErrorNotice error={config.error} title="Settings could not be loaded" />;
  const cfg = config.data!;

  const selectedFund = dataset.data?.rows.find((r) => String(r.fund_id) === fundId);
  const selectedProvider = cfg.providers.find((p) => p.id === provider);
  const canContinue = [
    !!dataset.data,
    !!fundId && !!mandate,
    !!selectedProvider?.available,
    true,
  ][step];

  return (
    <>
      <PageHeader title="New review" description="Choose a fund, the mandate to test it against, and the model the committee should use." />
      <Stepper step={step} onJump={setStep} />

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_17rem]">
        <div className="min-w-0 space-y-6">
          {step === 0 && (
            <>
              <div className="grid gap-3 sm:grid-cols-2" role="radiogroup" aria-label="Dataset">
                {(datasets.data ?? []).map((d) => (
                  <Choice key={d.id} selected={datasetId === d.id} onSelect={() => { setDatasetId(d.id); setFundId(null); }}>
                    <Database className="mb-2 h-5 w-5 text-navy" aria-hidden />
                    <p className="pr-6 font-medium">{d.is_demo ? "Demo funds" : d.name}</p>
                    <p className="mt-0.5 text-sm text-slate">
                      {d.row_count} {d.row_count === 1 ? "fund" : "funds"}
                      {d.is_demo ? ", synthetic data bundled with MandateIQ" : ", uploaded"}
                    </p>
                  </Choice>
                ))}
              </div>

              <div
                onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                onDragLeave={() => setDragging(false)}
                onDrop={onDrop}
                className={clsx(
                  "flex flex-col items-center rounded-panel border border-dashed px-6 py-8 text-center transition-colors",
                  dragging ? "border-navy bg-navy-50" : "border-rule-strong bg-paper",
                )}
              >
                <FileUp className="mb-2 h-6 w-6 text-slate" aria-hidden />
                <p className="font-medium">Upload a CSV of funds</p>
                <p className="mt-1 max-w-md text-sm text-slate">
                  Drop a file here or browse. Required columns: {cfg.required_columns.join(", ")}.
                </p>
                <button type="button" className="btn-secondary mt-4" onClick={() => fileInput.current?.click()} disabled={upload.isPending}>
                  {upload.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
                  {upload.isPending ? "Uploading" : "Browse files"}
                </button>
                <input ref={fileInput} type="file" accept=".csv,text/csv" className="hidden"
                  onChange={(e) => { onFile(e.target.files?.[0]); e.target.value = ""; }} />
              </div>
              {upload.isError && <ErrorNotice error={upload.error} title="The file was not accepted" />}

              {dataset.isLoading ? <Loading label="Loading dataset" /> : dataset.data && (
                <div>
                  <h2 className="mb-2 text-sm font-medium text-slate">Preview</h2>
                  <FundTable dataset={dataset.data} />
                </div>
              )}
            </>
          )}

          {step === 1 && dataset.data && (
            <>
              <div>
                <h2 className="mb-1 font-medium">Fund</h2>
                <p className="mb-3 text-sm text-slate">One review covers one fund.</p>
                <FundTable dataset={dataset.data} selected={fundId} onSelect={setFundId} />
              </div>
              <div>
                <h2 className="mb-1 font-medium">Mandate</h2>
                <p className="mb-3 text-sm text-slate">The investment policy the fund must satisfy.</p>
                <div className="grid gap-3 sm:grid-cols-2" role="radiogroup" aria-label="Mandate">
                  {cfg.mandates.map((m) => (
                    <Choice key={m.id} selected={mandate === m.id} onSelect={() => setMandate(m.id)}>
                      <p className="pr-6 font-medium">{m.name}</p>
                      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
                        <dt className="text-slate">Max risk</dt><dd>{humanize(m.max_risk_level)}</dd>
                        <dt className="text-slate">Max expense</dt><dd>{m.max_expense_ratio}%</dd>
                        <dt className="text-slate">Min history</dt><dd>{m.minimum_history_years} years</dd>
                        <dt className="text-slate">Asset classes</dt>
                        <dd>{m.allowed_asset_classes.map(humanize).join(", ")}</dd>
                      </dl>
                    </Choice>
                  ))}
                </div>
              </div>
            </>
          )}

          {step === 2 && (
            <>
              <div className="grid gap-3" role="radiogroup" aria-label="Model provider">
                {cfg.providers.map((p) => (
                  <Choice key={p.id} selected={provider === p.id} disabled={!p.available} onSelect={() => setProvider(p.id)}>
                    <div className="flex flex-wrap items-center gap-2 pr-6">
                      <p className="font-medium">{p.label}</p>
                      {p.primary && <span className="rounded bg-navy-50 px-1.5 py-0.5 text-xs font-medium text-navy">Main</span>}
                      {!p.available && <span className="rounded bg-neutral-soft px-1.5 py-0.5 text-xs text-slate">Not configured</span>}
                    </div>
                    <p className="mt-1 text-sm text-slate">{p.detail}</p>
                    {p.model && <p className="mt-1 text-xs text-mute">Model: {p.model}</p>}
                  </Choice>
                ))}
              </div>

              <label className="flex cursor-pointer gap-3 rounded-panel border border-rule bg-paper p-4">
                <input type="checkbox" checked={seed} onChange={(e) => setSeed(e.target.checked)} className="mt-1 h-4 w-4 accent-navy" />
                <span>
                  <span className="block font-medium">Seed two unsupported claims</span>
                  <span className="mt-0.5 block text-sm text-slate">
                    For demonstrations: the Proponent receives one claim that cites missing evidence and one that
                    misquotes a value, so you can watch the firewall and the debate catch them.
                  </span>
                </span>
              </label>
            </>
          )}

          {step === 3 && (
            <div className="panel divide-y divide-rule">
              {[
                ["Dataset", dataset.data?.is_demo ? "Demo funds" : dataset.data?.name],
                ["Fund", selectedFund ? `${selectedFund.fund_name} (${selectedFund.ticker})` : fundId],
                ["Mandate", mandate ? mandateName(mandate, cfg.mandates) : "—"],
                ["Model", selectedProvider ? `${selectedProvider.label}${selectedProvider.model ? ` · ${selectedProvider.model}` : ""}` : "—"],
                ["Seeded claims", seed ? "Yes, two unsupported claims" : "No"],
              ].map(([k, v]) => (
                <div key={k} className="flex justify-between gap-4 px-5 py-3 text-sm">
                  <span className="text-slate">{k}</span>
                  <span className="text-right font-medium">{v}</span>
                </div>
              ))}
              <p className="px-5 py-3 text-sm text-slate">
                The review runs in the background. You will see each stage complete on the case page.
                {provider !== "mock" && " Model-backed reviews usually take one to three minutes."}
              </p>
            </div>
          )}

          {start.isError && <ErrorNotice error={start.error} title="The review could not start" />}

          <div className="flex items-center justify-between border-t border-rule pt-5">
            <button type="button" className="btn-quiet" onClick={() => setStep((s) => s - 1)} disabled={step === 0}>
              <ArrowLeft className="h-4 w-4" aria-hidden />Back
            </button>
            {step < STEPS.length - 1 ? (
              <button type="button" className="btn-primary" disabled={!canContinue} onClick={() => setStep((s) => s + 1)}>
                Continue
              </button>
            ) : (
              <button
                type="button"
                className="btn-primary"
                disabled={start.isPending}
                onClick={() => start.mutate({
                  dataset_id: datasetId, fund_id: fundId!, mandate: mandate!, provider: provider!, seed_unsupported_claims: seed,
                })}
              >
                {start.isPending && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
                Start review
              </button>
            )}
          </div>
        </div>

        <aside className="hidden lg:block">
          <div className="sticky top-8 rounded-panel border border-rule bg-paper p-5 text-sm">
            <h2 className="font-medium">This review</h2>
            <dl className="mt-3 space-y-3">
              <div><dt className="text-xs text-slate">Fund</dt><dd>{selectedFund ? String(selectedFund.fund_name) : "Not chosen"}</dd></div>
              <div><dt className="text-xs text-slate">Mandate</dt><dd>{mandate ? mandateName(mandate, cfg.mandates) : "Not chosen"}</dd></div>
              <div><dt className="text-xs text-slate">Model</dt><dd>{selectedProvider?.label ?? "Not chosen"}</dd></div>
            </dl>
            <p className="mt-5 border-t border-rule pt-4 text-xs leading-5 text-slate">
              A Proponent argues for the fund, a Challenger argues against it, and deterministic rules and a
              hallucination firewall decide how far their claims can be trusted.
            </p>
          </div>
        </aside>
      </div>
    </>
  );
}
