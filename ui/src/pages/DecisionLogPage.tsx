import { useEffect, useState } from "react"
import { api } from "../lib/api"
import type { DecisionLogEntry } from "../lib/types"

export default function DecisionLogPage() {
  const [entries, setEntries] = useState<DecisionLogEntry[] | null>(null)
  const [actorFilter, setActorFilter] = useState("")
  const [error, setError] = useState<string | null>(null)

  const load = (actor?: string) => {
    api
      .listDecisions(actor ? { actor } : undefined)
      .then(setEntries)
      .catch((e) => setError(String(e)))
  }

  useEffect(() => load(), [])

  return (
    <div className="decision-log">
      <div className="decision-log-controls">
        <label>
          Filter by actor:{" "}
          <input
            value={actorFilter}
            onChange={(e) => setActorFilter(e.target.value)}
            placeholder="e.g. coder-1"
          />
        </label>
        <button onClick={() => load(actorFilter || undefined)}>Apply</button>
        <button
          onClick={() => {
            setActorFilter("")
            load()
          }}
        >
          Clear
        </button>
      </div>

      {error && <div className="error">Failed to load decision log: {error}</div>}
      {!entries && !error && <div className="loading">Loading…</div>}
      {entries && entries.length === 0 && <div className="empty-state">No decisions recorded yet.</div>}

      {entries && entries.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Timestamp</th>
              <th>Actor</th>
              <th>Action</th>
              <th>Case</th>
              <th>Line</th>
              <th>Reason</th>
              <th>Rule version</th>
              <th>Note</th>
            </tr>
          </thead>
          <tbody>
            {[...entries].reverse().map((e, i) => (
              <tr key={i}>
                <td>{new Date(e.timestamp).toLocaleString()}</td>
                <td>{e.actor}</td>
                <td>{e.action}</td>
                <td>{e.case_id}</td>
                <td>{e.line_id ?? "—"}</td>
                <td>{e.reason_code ?? "—"}</td>
                <td>{e.ruleset_id}</td>
                <td>{e.note ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
