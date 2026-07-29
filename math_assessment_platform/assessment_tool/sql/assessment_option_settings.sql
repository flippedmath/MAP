-- Assessment / course columns supporting revised assessment options.

ALTER TABLE assessment
  ADD COLUMN IF NOT EXISTS grade_weight double precision NOT NULL DEFAULT 1;

ALTER TABLE assessment
  ADD COLUMN IF NOT EXISTS curve_max_points double precision NULL;

ALTER TABLE assessment
  ADD COLUMN IF NOT EXISTS time_limit_minutes integer NULL;

ALTER TABLE course
  ADD COLUMN IF NOT EXISTS default_time_limit_minutes integer NULL;

COMMENT ON COLUMN assessment.grade_weight IS
  'Relative weight for course totals when aggregation is percent-of-final-grade. 0 excludes the assessment.';

COMMENT ON COLUMN assessment.curve_max_points IS
  'Teacher curve denominator for this assessment. NULL means follow live assessment total points when unlocked.';

COMMENT ON COLUMN assessment.time_limit_minutes IS
  'Allotted minutes when countdown forcibly-end option is active. NULL inherits course default.';

COMMENT ON COLUMN course.default_time_limit_minutes IS
  'Default allotted minutes for assessments using forcibly-end countdown without an override.';
