-- Class-wide retake status + attempt series for separate grade contributions.
-- Apply outside Django migrations (unmanaged tables). Safe to re-run.
--
-- Note: ADD VALUE IF NOT EXISTS must run outside an open transaction on older
-- Postgres; run this file as a whole (psql autocommit between statements).

ALTER TYPE assessment_status_enum ADD VALUE IF NOT EXISTS 'retake';

ALTER TABLE assessment
  ADD COLUMN IF NOT EXISTS active_retake_series integer NOT NULL DEFAULT 1;

COMMENT ON COLUMN assessment.active_retake_series IS
  'Series that open/upcoming/retake currently apply to. Advances when the first student starts a new series under class retake.';

COMMENT ON COLUMN assessment.status IS
  'closed | open | upcoming | hidden | retake (teacher lifecycle); deleted (trash).';

ALTER TABLE student_assessment_attempt
  ADD COLUMN IF NOT EXISTS retake_series integer NOT NULL DEFAULT 1;

COMMENT ON COLUMN student_assessment_attempt.retake_series IS
  'Attempt series for grade counting. Highest/latest retake scoring applies within a series; each series contributes separately to course totals.';

CREATE INDEX IF NOT EXISTS idx_saa_user_series
  ON student_assessment_attempt (user_id, retake_series);

ALTER TABLE open_student_assessment_overwrite
  ADD COLUMN IF NOT EXISTS retake_series integer NULL;

COMMENT ON COLUMN open_student_assessment_overwrite.retake_series IS
  'When status_open, new attempts attach to this series (from the teacher-selected attempt). NULL means use assessment.active_retake_series.';

ALTER TABLE final_grade_calculation
  ADD COLUMN IF NOT EXISTS retake_series integer NOT NULL DEFAULT 1;

COMMENT ON COLUMN final_grade_calculation.retake_series IS
  'Series this stored grade belongs to (matches student_assessment_attempt.retake_series).';

DROP INDEX IF EXISTS uq_fgc_enrollment_assessment;

CREATE UNIQUE INDEX IF NOT EXISTS uq_fgc_enrollment_assessment_series
  ON final_grade_calculation (enrollment_id, assessment_id, retake_series)
  WHERE assessment_id IS NOT NULL;
