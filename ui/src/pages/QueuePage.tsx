import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { api } from "../lib/api"
import type { QueueRow } from "../lib/types"

export default function QueuePage() {
  const [rows, setRows] = useState<QueueRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.listCases().then(setRows).catch((e) => setError(String(e)))
  }, [])

  if (error) return <div className="error">Failed to load queue: {error}</div>
  if (!rows) return <div className="loading">Loading…</div>
  if (rows.length === 0) {
    return (
      <div className="empty-state">
        No runs yet. Seed some with <code>python -m pipeline.cli.seed_runs</code>.
      </div>
    )
  }

  return (
    <div className="queue">
      <table>
        <thead>
          <tr>
            <th>Case</th>
            <th>Date of service</th>
            <th>Subspecialty</th>
            <th>Specimens</th>
            <th>Blocker</th>
            <th>Review</th>
            <th>Info</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.case_id}-${row.run_id}`}>
              <td>
                <Link to={`/cases/${row.case_id}/runs/${row.run_id}`}>{row.case_id}</Link>
              </td>
              <td>{row.date_of_service}</td>
              <td>{row.subspecialty}</td>
              <td>{row.specimen_count}</td>
              <td className={row.finding_counts.blocker > 0 ? "count-blocker" : "count-zero"}>
                {row.finding_counts.blocker}
              </td>
              <td className={row.finding_counts.review > 0 ? "count-review" : "count-zero"}>
                {row.finding_counts.review}
              </td>
              <td className="count-zero">{row.finding_counts.informational}</td>
              <td>
                <span className={`status-badge ${row.decided ? "status-decided" : "status-pending"}`}>
                  {row.decided ? "decided" : "pending"}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
