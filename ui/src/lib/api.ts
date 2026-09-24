import type { Document, DecisionAction, DecisionLogEntry, QueueRow, ReasonCode, Recommendation } from "./types"

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`${init?.method ?? "GET"} ${path} -> ${res.status}: ${body}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  listCases: () => request<QueueRow[]>("/api/cases"),

  getRecommendation: (caseId: string, runId: string) =>
    request<Recommendation>(`/api/cases/${caseId}/runs/${runId}`),

  getDocument: (caseId: string, runId: string, documentId: string) =>
    request<Document>(`/api/cases/${caseId}/runs/${runId}/documents/${documentId}`),

  listRunDecisions: (caseId: string, runId: string) =>
    request<DecisionLogEntry[]>(`/api/cases/${caseId}/runs/${runId}/decisions`),

  listDecisions: (params?: { actor?: string; case_id?: string }) => {
    const qs = new URLSearchParams()
    if (params?.actor) qs.set("actor", params.actor)
    if (params?.case_id) qs.set("case_id", params.case_id)
    const suffix = qs.toString() ? `?${qs}` : ""
    return request<DecisionLogEntry[]>(`/api/decisions${suffix}`)
  },

  recordDecision: (
    caseId: string,
    runId: string,
    decision: {
      actor: string
      action: DecisionAction
      line_id?: string | null
      reason_code?: ReasonCode | null
      edit?: Record<string, unknown> | null
      note?: string | null
    },
  ) =>
    request<DecisionLogEntry>(`/api/cases/${caseId}/runs/${runId}/decisions`, {
      method: "POST",
      body: JSON.stringify(decision),
    }),
}
