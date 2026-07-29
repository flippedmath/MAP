-- Teacher per-student actions on attempts (adjust / void) + allow retake attempts.
-- Apply outside Django migrations (unmanaged tables).

ALTER TABLE student_assessment_attempt
  ADD COLUMN IF NOT EXISTS original_earned_points double precision NULL,
  ADD COLUMN IF NOT EXISTS original_max_points double precision NULL,
  ADD COLUMN IF NOT EXISTS score_voided boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN student_assessment_attempt.original_earned_points IS
  'Earned points before any teacher attempt-level score adjustment. NULL means never adjusted.';
COMMENT ON COLUMN student_assessment_attempt.original_max_points IS
  'Max points before any teacher attempt-level score adjustment. NULL means never adjusted.';
COMMENT ON COLUMN student_assessment_attempt.score_voided IS
  'When true, this attempt does not count toward the student grade for the assessment.';

-- Retakes need multiple attempts per enrollment + assessment.
DROP INDEX IF EXISTS uq_saa_enrollment_assessment;

CREATE INDEX IF NOT EXISTS idx_saa_enrollment_assessment
  ON student_assessment_attempt (enrollment_id, assessment_id);
