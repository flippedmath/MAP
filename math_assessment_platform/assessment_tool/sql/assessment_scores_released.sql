-- Score release flags on parent assessments (unmanaged; apply manually).
-- Safe to re-run.

BEGIN;

ALTER TABLE assessment
  ADD COLUMN IF NOT EXISTS scores_released boolean NOT NULL DEFAULT false;

ALTER TABLE assessment
  ADD COLUMN IF NOT EXISTS scores_released_at timestamp without time zone NULL;

COMMENT ON COLUMN assessment.scores_released IS
  'When true, students may see their scores even if auto-visibility conditions are not met.';
COMMENT ON COLUMN assessment.scores_released_at IS
  'Timestamp of the most recent teacher score release.';

COMMIT;
