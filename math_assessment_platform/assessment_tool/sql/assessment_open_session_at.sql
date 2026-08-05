-- Class open/retake session date for the Course Assessments table.
-- open_session_pending_at: set when status becomes open/retake/upcoming.
-- open_session_at: committed on close only when at least one student started
-- during that session (otherwise pending is cleared and open_session_at is unchanged).

ALTER TABLE assessment
  ADD COLUMN IF NOT EXISTS open_session_at timestamptz NULL;

ALTER TABLE assessment
  ADD COLUMN IF NOT EXISTS open_session_pending_at timestamptz NULL;

COMMENT ON COLUMN assessment.open_session_at IS
  'Date of the last open/retake session that had at least one student start before close.';

COMMENT ON COLUMN assessment.open_session_pending_at IS
  'When the current open/retake/upcoming session began; cleared on close.';
