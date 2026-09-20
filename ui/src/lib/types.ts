export type Severity = "blocker" | "review" | "informational"
export type ReasonCode = "duplicate" | "clinical_judgment" | "payer_rule_exception" | "other"
export type DecisionAction = "accept_all" | "accept_selected" | "remove" | "edit" | "physician_query"

export interface Document {
  document_id: string
  kind: string
  text: string
  received_at: string
}

export interface Specimen {
  specimen_id: string
  site: string | null
  sites: string[]
  procedure_type: string | null
  container_label: string | null
}

export interface Case {
  case_id: string
  lab_id: string
  date_of_service: string
  date_reported: string
  subspecialty: string
  specimens: Specimen[]
  documents: Document[]
  billing_arrangement: string
  requisition: {
    clinical_indication: string | null
    payer: { plan: string; mac_jurisdiction: string; payer_class: string }
  }
}

export interface CodeLine {
  line_id: string
  code: string
  code_system: string
  units: number
  modifiers: string[]
  specimen_id: string | null
  fact_ids: string[]
  confidence: string
  rule_id: string
}

export interface CodeSet {
  case_id: string
  ruleset_id: string
  lines: CodeLine[]
}

export interface Finding {
  severity: Severity
  line_id: string | null
  rule_id: string
  message: string
  suggested_action: string | null
}

export interface Evidence {
  document_id: string
  start: number
  end: number
  quoted: string
}

export interface Fact {
  fact_id: string
  fact_type: string
  value: Record<string, unknown>
  specimen_id: string | null
  evidence: Evidence
  confidence: string
}

export interface Recommendation {
  case: Case
  codes: CodeSet
  findings: Finding[]
  facts: Fact[]
  manifest: Record<string, unknown>
}

export interface QueueRow {
  case_id: string
  run_id: string
  date_of_service: string
  subspecialty: string
  specimen_count: number
  finding_counts: { blocker: number; review: number; informational: number }
  decided: boolean
}

export interface DecisionLogEntry {
  timestamp: string
  case_id: string
  run_id: string
  ruleset_id: string
  actor: string
  action: DecisionAction
  line_id: string | null
  reason_code: ReasonCode | null
  edit: Record<string, unknown> | null
  note: string | null
}
