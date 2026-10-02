// Display helpers shared across pages.

export function humanize(value: string | null | undefined): string {
  if (!value) return "—";
  const text = String(value).replace(/_/g, " ").toLowerCase();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function pct(value: number | null | undefined, digits = 0): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function num(value: unknown, digits = 1): string {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  return Number.isInteger(n) ? n.toLocaleString() : n.toFixed(digits);
}

export function display(value: unknown): string {
  if (value == null || value === "") return "—";
  if (typeof value === "number") return num(value, 2);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 45) return "Just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days} d ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
}

export function duration(startIso: string | null | undefined, endIso: string | null | undefined): string {
  if (!startIso || !endIso) return "—";
  const ms = new Date(endIso).getTime() - new Date(startIso).getTime();
  if (ms < 1000) return "under 1 s";
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.floor(ms / 60_000)} min ${Math.round((ms % 60_000) / 1000)} s`;
}

export const STAGES: { id: string; label: string; description: string }[] = [
  { id: "data_steward", label: "Data Steward", description: "Profiles the fund data and builds the evidence ledger." },
  { id: "committee", label: "Committee debate", description: "Proponent builds the case, Challenger attacks it, rebuttals follow." },
  { id: "policy", label: "Policy and suitability", description: "Deterministic cost, policy and mandate rules." },
  { id: "governance", label: "Governance", description: "Hallucination firewall, conflict detection and Trust Score." },
  { id: "supervisor", label: "Supervisor routing", description: "Chooses to finalize, rework or escalate to a person." },
];

export const PROVIDER_LABEL: Record<string, string> = {
  bedrock: "Bedrock",
  groq: "Groq",
  mock: "Mock",
};

export function mandateName(id: string, mandates: { id: string; name: string }[] | undefined): string {
  return mandates?.find((m) => m.id === id)?.name ?? humanize(id);
}
