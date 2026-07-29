-- Persistent canonical assessment forms used when "Synchronize tests" is on.
-- One attempt ordinal may have multiple preserved cohorts; exactly one is current.

CREATE TABLE IF NOT EXISTS assessment_synchronized_form (
  id serial PRIMARY KEY,
  assessment_id integer NOT NULL
    REFERENCES assessment(id) ON DELETE CASCADE,
  attempt_number integer NOT NULL CHECK (attempt_number >= 1),
  cohort_number integer NOT NULL CHECK (cohort_number >= 1),
  blueprint_hash varchar(64) NOT NULL,
  content_hash varchar(64) NOT NULL,
  is_current boolean NOT NULL DEFAULT true,
  unsynchronized_history_acknowledged_at timestamptz NOT NULL DEFAULT now(),
  created_by_id integer NULL
    REFERENCES user_profile(user_id) ON DELETE SET NULL,
  creation_date timestamptz NOT NULL DEFAULT now(),
  UNIQUE (assessment_id, attempt_number, cohort_number)
);

ALTER TABLE assessment_synchronized_form
  ADD COLUMN IF NOT EXISTS content_hash varchar(64);
UPDATE assessment_synchronized_form
SET content_hash = repeat(md5(id::text), 2)
WHERE content_hash IS NULL;
ALTER TABLE assessment_synchronized_form
  ALTER COLUMN content_hash SET NOT NULL;
ALTER TABLE assessment_synchronized_form
  ADD COLUMN IF NOT EXISTS unsynchronized_history_acknowledged_at timestamptz;
UPDATE assessment_synchronized_form
SET unsynchronized_history_acknowledged_at = creation_date
WHERE unsynchronized_history_acknowledged_at IS NULL;
ALTER TABLE assessment_synchronized_form
  ALTER COLUMN unsynchronized_history_acknowledged_at SET DEFAULT now(),
  ALTER COLUMN unsynchronized_history_acknowledged_at SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_assessment_sync_form_current
  ON assessment_synchronized_form (assessment_id, attempt_number)
  WHERE is_current;

CREATE INDEX IF NOT EXISTS idx_assessment_sync_form_lookup
  ON assessment_synchronized_form (assessment_id, attempt_number, cohort_number);

CREATE TABLE IF NOT EXISTS assessment_synchronized_problem (
  id serial PRIMARY KEY,
  synchronized_form_id integer NOT NULL
    REFERENCES assessment_synchronized_form(id) ON DELETE CASCADE,
  slot_index integer NOT NULL,
  section_name varchar(255) NULL,
  title varchar(255) NULL,
  source_problem_id integer NULL,
  body_html text NOT NULL,
  render_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  answer_key jsonb NOT NULL DEFAULT '{}'::jsonb,
  answer_fields jsonb NOT NULL DEFAULT '[]'::jsonb,
  max_points double precision NOT NULL DEFAULT 0,
  UNIQUE (synchronized_form_id, slot_index)
);

CREATE INDEX IF NOT EXISTS idx_assessment_sync_problem_form
  ON assessment_synchronized_problem (synchronized_form_id, slot_index);

ALTER TABLE student_assessment_attempt
  ADD COLUMN IF NOT EXISTS synchronized_form_id integer NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'student_assessment_attempt_synchronized_form_fk'
      AND conrelid = 'student_assessment_attempt'::regclass
  ) THEN
    ALTER TABLE student_assessment_attempt
      ADD CONSTRAINT student_assessment_attempt_synchronized_form_fk
      FOREIGN KEY (synchronized_form_id)
      REFERENCES assessment_synchronized_form(id)
      ON DELETE SET NULL;
  END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_student_assessment_attempt_sync_form
  ON student_assessment_attempt (synchronized_form_id)
  WHERE synchronized_form_id IS NOT NULL;

COMMENT ON TABLE assessment_synchronized_form IS
  'Preserved canonical generated tests by assessment, attempt ordinal, and synchronization cohort.';

COMMENT ON TABLE assessment_synchronized_problem IS
  'Frozen problem instances cloned into student attempts that use a synchronized form.';

COMMENT ON COLUMN student_assessment_attempt.synchronized_form_id IS
  'Canonical synchronized form used to create this attempt; NULL identifies legacy or unsynchronized generation.';
