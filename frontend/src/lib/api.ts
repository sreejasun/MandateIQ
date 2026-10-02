import type {
  AppConfig, Dataset, DatasetSummary, Insights, ProviderId, ReviewDetail, ReviewSummary, ScenarioDetail,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError(0, "The MandateIQ API is not reachable. Start it from backend/ with: uvicorn api.main:app --port 8000");
  }
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = body?.detail;
    const message = typeof detail === "string"
      ? detail
      : Array.isArray(detail)
        ? detail.map((d: { msg: string }) => d.msg).join("; ")
        : res.status >= 500 && !body
          ? "The MandateIQ API is not reachable. Start it from backend/ with: uvicorn api.main:app --port 8000"
          : `Request failed (${res.status}).`;
    throw new ApiError(res.status, message);
  }
  return body as T;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export interface StartReviewBody {
  dataset_id: string;
  fund_id: string;
  mandate: string;
  provider: ProviderId;
  seed_unsupported_claims: boolean;
}

export const api = {
  config: () => request<AppConfig>("/api/config"),
  datasets: () => request<DatasetSummary[]>("/api/datasets"),
  dataset: (id: string) => request<Dataset>(`/api/datasets/${id}`),
  uploadDataset: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Dataset>("/api/datasets", { method: "POST", body: form });
  },
  reviews: () => request<ReviewSummary[]>("/api/reviews"),
  review: (id: string) => request<ReviewDetail>(`/api/reviews/${id}`),
  startReview: (body: StartReviewBody) => request<{ id: string }>("/api/reviews", json("POST", body)),
  deleteReview: (id: string) => request<void>(`/api/reviews/${id}`, { method: "DELETE" }),
  scenarios: (id: string) => request<ReviewSummary[]>(`/api/reviews/${id}/scenarios`),
  scenario: (id: string) => request<ScenarioDetail>(`/api/scenarios/${id}`),
  startScenario: (id: string, changes: Record<string, string | number>) =>
    request<{ id: string }>(`/api/reviews/${id}/scenarios`, json("POST", { changes })),
  insights: () => request<Insights>("/api/insights"),
  eventsUrl: (id: string) => `/api/reviews/${id}/events`,
};
