import { useEffect, useRef } from "react"
import type { Document, Evidence } from "../lib/types"

interface Props {
  documents: Document[]
  activeEvidence: Evidence | null
}

export default function EvidencePanel({ documents, activeEvidence }: Props) {
  const markRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    markRef.current?.scrollIntoView({ block: "center", behavior: "smooth" })
  }, [activeEvidence])

  if (!activeEvidence) {
    return (
      <div className="evidence-panel evidence-empty">
        Select a line to see the source text that supports it.
      </div>
    )
  }

  const doc = documents.find((d) => d.document_id === activeEvidence.document_id)
  if (!doc) {
    return <div className="evidence-panel evidence-empty">Document {activeEvidence.document_id} not found.</div>
  }

  const before = doc.text.slice(0, activeEvidence.start)
  const highlighted = doc.text.slice(activeEvidence.start, activeEvidence.end)
  const after = doc.text.slice(activeEvidence.end)

  return (
    <div className="evidence-panel">
      <div className="evidence-doc-header">
        {doc.kind} · {doc.document_id}
      </div>
      <pre className="evidence-doc-text">
        {before}
        <mark ref={markRef}>{highlighted}</mark>
        {after}
      </pre>
    </div>
  )
}
