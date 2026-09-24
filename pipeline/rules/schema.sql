-- The rule store schema. SQLite for the demo; written so it moves to
-- Postgres unchanged (no SQLite-specific types beyond the trivial ones).
--
-- Rulesets are immutable once written: a quarterly update is a new row
-- with a new effective_from, never an edit to an existing row. Every
-- lookup takes a date and resolves to the ruleset effective on that date
-- -- there is no "current" query path.

CREATE TABLE IF NOT EXISTS ruleset (
  ruleset_id    TEXT PRIMARY KEY,   -- "2026q3"
  effective_from DATE NOT NULL,
  effective_to   DATE,              -- null = current
  source_note    TEXT NOT NULL,     -- where it came from, when pulled
  content_hash   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mue (
  ruleset_id TEXT NOT NULL REFERENCES ruleset(ruleset_id),
  code TEXT NOT NULL,
  max_units INTEGER NOT NULL,
  adjudication_type TEXT NOT NULL,
  PRIMARY KEY (ruleset_id, code)
);

CREATE TABLE IF NOT EXISTS ptp_edit (
  ruleset_id TEXT NOT NULL REFERENCES ruleset(ruleset_id),
  column1 TEXT NOT NULL,
  column2 TEXT NOT NULL,
  modifier_allowed INTEGER NOT NULL,  -- 0 | 1 | 9
  PRIMARY KEY (ruleset_id, column1, column2)
);

CREATE TABLE IF NOT EXISTS coverage_policy (
  ruleset_id TEXT NOT NULL REFERENCES ruleset(ruleset_id),
  policy_id TEXT NOT NULL,   -- e.g. an LCD identifier
  mac_jurisdiction TEXT NOT NULL,
  code TEXT NOT NULL,
  PRIMARY KEY (ruleset_id, policy_id, code)
);

CREATE TABLE IF NOT EXISTS coverage_diagnosis (
  ruleset_id TEXT NOT NULL REFERENCES ruleset(ruleset_id),
  policy_id TEXT NOT NULL,
  icd10 TEXT NOT NULL,
  PRIMARY KEY (ruleset_id, policy_id, icd10)
);

CREATE TABLE IF NOT EXISTS substitution (
  ruleset_id TEXT NOT NULL REFERENCES ruleset(ruleset_id),
  payer_class TEXT NOT NULL,
  from_code TEXT NOT NULL,
  to_code TEXT NOT NULL,
  condition TEXT NOT NULL,
  PRIMARY KEY (ruleset_id, payer_class, from_code)
);
