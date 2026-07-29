-- Assessment student release modes + course grade aggregation (unmanaged; apply manually).
-- Safe to re-run.

BEGIN;

ALTER TABLE assessment
  ADD COLUMN IF NOT EXISTS student_release_mode character varying(32) NOT NULL DEFAULT 'hidden';

ALTER TABLE assessment
  ADD COLUMN IF NOT EXISTS counts_toward_grade boolean NOT NULL DEFAULT true;

-- Migrate legacy boolean release into mode.
UPDATE assessment
SET student_release_mode = 'scores_only'
WHERE scores_released IS TRUE
  AND (student_release_mode IS NULL OR student_release_mode = 'hidden');

COMMENT ON COLUMN assessment.student_release_mode IS
  'hidden | scores_only | full_review — what students may see for this assessment.';
COMMENT ON COLUMN assessment.counts_toward_grade IS
  'When false, students may still see the score but it is excluded from course totals.';

ALTER TABLE course
  ADD COLUMN IF NOT EXISTS grade_aggregation_mode character varying(32) NOT NULL DEFAULT 'equal_weight';

COMMENT ON COLUMN course.grade_aggregation_mode IS
  'equal_weight | sum_points — how student course totals are computed from assessment scores.';

COMMIT;
