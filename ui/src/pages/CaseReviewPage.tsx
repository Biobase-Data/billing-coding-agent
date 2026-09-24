import { useCallback, useEffect, useMemo, useState } from "react"
import { useParams } from "react-router-dom"
import { api } from "../lib/api"
import EvidencePanel from "../components/EvidencePanel"
import type { CodeLine, DecisionLogEntry, Evidence, Finding, ReasonCode, Recommendation } from "../lib/types"

const REASON_CODES: ReasonCode[] = ["duplicate", "clinical_judgment", "payer_rule_exception", "other"]
const SEVERITY_ORDER: Record<string, number> = { blocker: 0, review: 1, informational: 2 }

type LineStatus = "pending" | "accepted" | "removed" | "edited"

function computeLineStatuses(lines: CodeLine[], decisions: DecisionLogEntry[]): Record<string, LineStatus> {
  const acceptedAll = decisions.some((d) => d.action === "accept_all")
  const statuses: Record<string, LineStatus> = {}
  for (const line of lines) {
    statuses[line.line_id] = acceptedAll ? "accepted" : "pending"
  }
  // Later decisions override earlier ones, including the accept_all default.
  for (const d of decisions) {
    if (!d.line_id) continue
    if (d.action === "remove") statuses[d.line_id] = "removed"
    else if (d.action === "edit") statuses[d.line_id] = "edited"
    else if (d.action === "accept_selected") statuses[d.line_id] = "accepted"
  }
  return statuses
}

export default function CaseReviewPage() {
  const { caseId, runId } = useParams<{ caseId: string; runId: string }>()
  const [rec, setRec] = useState<Recommendation | null>(null)
  const [decisions, setDecisions] = useState<DecisionLogEntry[]>([])
  const [error, setError] = useState<string | null>(null)
  const [activeEvidence, setActiveEvidence] = useState<Evidence | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [removingLineId, setRemovingLineId] = useState<string | null>(null)
  const [reasonCode, setReasonCode] = useState<ReasonCode>("clinical_judgment")
  const [actor] = useState("coder-1") // demo: no auth/multi-tenancy posture yet, see ASSUMPTIONS.md

  const reload = useCallback(() => {
    if (!caseId || !runId) return
    api.getRecommendation(caseId, runId).then(setRec).catch((e) => setError(String(e)))
    api.listRunDecisions(caseId, runId).then(setDecisions).catch((e) => setError(String(e)))
  }, [caseId, runId])

  useEffect(reload, [reload])

  const statuses = useMemo(() => (rec ? computeLineStatuses(rec.codes.lines, decisions) : {}), [rec, decisions])

  if (error) return <div className="error">Failed to load case: {error}</div>
  if (!rec || !caseId || !runId) return <div className="loading">Loading…</div>

  const factById = new Map(rec.facts.map((f) => [f.fact_id, f]))
  const findingsByLine = new Map<string, Finding[]>()
  const caseLevelFindings: Finding[] = []
  for (const f of rec.findings) {
    if (f.line_id) {
      findingsByLine.set(f.line_id, [...(findingsByLine.get(f.line_id) ?? []), f])
    } else {
      caseLevelFindings.push(f)
    }
  }
  caseLevelFindings.sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity])

  const specimenIds = Array.from(new Set(rec.codes.lines.map((l) => l.specimen_id ?? "__case_level__")))
  const linesBySpecimen = new Map<string, CodeLine[]>()
  for (const line of rec.codes.lines) {
    const key = line.specimen_id ?? "__case_level__"
    linesBySpecimen.set(key, [...(linesBySpecimen.get(key) ?? []), line])
  }
  for (const lines of linesBySpecimen.values()) {
    lines.sort((a, b) => {
      const aSeverity = Math.min(...(findingsByLine.get(a.line_id) ?? [{ severity: "informational" }]).map((f) => SEVERITY_ORDER[f.severity]))
      const bSeverity = Math.min(...(findingsByLine.get(b.line_id) ?? [{ severity: "informational" }]).map((f) => SEVERITY_ORDER[f.severity]))
      return aSeverity - bSeverity
    })
  }

  const showEvidence = (line: CodeLine) => {
    const fact = factById.get(line.fact_ids[0])
    if (fact) setActiveEvidence(fact.evidence)
  }

  const toggleSelected = (lineId: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(lineId)) next.delete(lineId)
      else next.add(lineId)
      return next
    })
  }

  const acceptAll = async () => {
    await api.recordDecision(caseId, runId, { actor, action: "accept_all" })
    reload()
  }

  const acceptSelected = async () => {
    for (const lineId of selected) {
      await api.recordDecision(caseId, runId, { actor, action: "accept_selected", line_id: lineId })
    }
    setSelected(new Set())
    reload()
  }

  const confirmRemove = async (lineId: string) => {
    await api.recordDecision(caseId, runId, { actor, action: "remove", line_id: lineId, reason_code: reasonCode })
    setRemovingLineId(null)
    reload()
  }

  const requestPhysicianQuery = async () => {
    const note = window.prompt("What should the physician query ask?")
    if (note === null) return
    await api.recordDecision(caseId, runId, { actor, action: "physician_query", note })
    reload()
  }

  const activeLines = rec.codes.lines.filter((l) => statuses[l.line_id] !== "removed")
  const removedLines = rec.codes.lines.filter((l) => statuses[l.line_id] === "removed")
  const unsupported = rec.findings.filter((f) => f.severity === "blocker")

  return (
    <div className="case-review">
      <div className="case-review-header">
        <h2>{rec.case.case_id}</h2>
        <div className="case-meta">
          {rec.case.subspecialty} · DOS {rec.case.date_of_service} · {rec.case.billing_arrangement} ·{" "}
          {rec.case.requisition.payer.plan}
        </div>
        <div className="case-actions">
          <button onClick={acceptAll}>Accept all</button>
          <button onClick={acceptSelected} disabled={selected.size === 0}>
            Accept selected ({selected.size})
          </button>
          <button onClick={requestPhysicianQuery}>Request physician query</button>
        </div>
      </div>

      {caseLevelFindings.length > 0 && (
        <div className="case-level-findings">
          {caseLevelFindings.map((f, i) => (
            <div key={i} className={`finding finding-${f.severity}`}>
              <strong>{f.severity}</strong> · {f.rule_id}: {f.message}
            </div>
          ))}
        </div>
      )}

      <div className="review-columns">
        <div className="recommendation-panel">
          {specimenIds.map((specimenKey) => (
            <div className="specimen-group" key={specimenKey}>
              <h3>{specimenKey === "__case_level__" ? "Case-level lines" : `Specimen ${specimenKey}`}</h3>
              {(linesBySpecimen.get(specimenKey) ?? []).map((line) => {
                const status = statuses[line.line_id]
                const lineFindings = (findingsByLine.get(line.line_id) ?? []).sort(
                  (a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity],
                )
                const hasBlocker = lineFindings.some((f) => f.severity === "blocker")
                return (
                  <div
                    key={line.line_id}
                    className={`code-line ${status === "removed" ? "code-line-removed" : ""} ${hasBlocker ? "code-line-blocker" : ""}`}
                  >
                    <div className="code-line-main">
                      <input
                        type="checkbox"
                        checked={selected.has(line.line_id)}
                        onChange={() => toggleSelected(line.line_id)}
                        disabled={status === "removed"}
                      />
                      <button className="line-link" onClick={() => showEvidence(line)}>
                        {line.code}
                        <span className="code-system">{line.code_system}</span>
                      </button>
                      <span>units: {line.units}</span>
                      {line.modifiers.length > 0 && <span>mod: {line.modifiers.join(", ")}</span>}
                      <span className={`confidence confidence-${line.confidence}`}>{line.confidence}</span>
                      <span className="status-tag">{status}</span>
                      {status !== "removed" && (
                        <button className="remove-button" onClick={() => setRemovingLineId(line.line_id)}>
                          Remove
                        </button>
                      )}
                    </div>
                    {lineFindings.map((f, i) => (
                      <div key={i} className={`finding finding-${f.severity}`}>
                        <strong>{f.severity}</strong> · {f.rule_id}: {f.message}
                      </div>
                    ))}
                    {removingLineId === line.line_id && (
                      <div className="remove-form">
                        <select value={reasonCode} onChange={(e) => setReasonCode(e.target.value as ReasonCode)}>
                          {REASON_CODES.map((rc) => (
                            <option key={rc} value={rc}>
                              {rc}
                            </option>
                          ))}
                        </select>
                        <button onClick={() => confirmRemove(line.line_id)}>Confirm removal</button>
                        <button onClick={() => setRemovingLineId(null)}>Cancel</button>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          ))}
        </div>

        <EvidencePanel documents={rec.case.documents} activeEvidence={activeEvidence} />
      </div>

      <div className="charge-summary">
        <h3>Charge summary</h3>
        <div className="charge-summary-columns">
          <div>
            <h4>Lines the system added ({activeLines.length})</h4>
            <ul>
              {activeLines.map((l) => (
                <li key={l.line_id}>
                  {l.code} × {l.units} ({l.specimen_id ?? "case"})
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h4>Lines flagged as unsupported ({unsupported.length})</h4>
            <ul>
              {unsupported.map((f, i) => (
                <li key={i}>
                  {f.line_id ?? "case"}: {f.message}
                </li>
              ))}
            </ul>
          </div>
        </div>
        {removedLines.length > 0 && (
          <div>
            <h4>Removed by coder ({removedLines.length})</h4>
            <ul>
              {removedLines.map((l) => (
                <li key={l.line_id}>
                  {l.code} ({l.specimen_id ?? "case"})
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}
