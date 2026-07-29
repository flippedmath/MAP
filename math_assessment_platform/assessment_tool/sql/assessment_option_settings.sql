-- Assessment / course columns supporting revised assessment options.

ALTER TABLE assessment
  ADD COLUMN IF NOT EXISTS grade_weight double precision NOT NULL DEFAULT 1;

ALTER TABLE assessment
  ADD COLUMN IF NOT EXISTS curve_max_points double precision NOT NULL DEFAULT 0;

-- One-time semantic conversion: old values were denominators, so they cannot be
-- carried forward as bonus points. The column comment makes this idempotent.
DO $$
BEGIN
  IF COALESCE(
    col_description('assessment'::regclass, (
      SELECT attnum
      FROM pg_attribute
      WHERE attrelid = 'assessment'::regclass
        AND attname = 'curve_max_points'
        AND NOT attisdropped
    )),
    ''
  ) <> 'Bonus points added to every recorded student grade for this assessment.' THEN
    UPDATE assessment SET curve_max_points = 0;
  ELSE
    UPDATE assessment SET curve_max_points = 0 WHERE curve_max_points IS NULL;
  END IF;
END
$$;

ALTER TABLE assessment
  ALTER COLUMN curve_max_points SET DEFAULT 0,
  ALTER COLUMN curve_max_points SET NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'assessment_curve_bonus_nonnegative'
      AND conrelid = 'assessment'::regclass
  ) THEN
    ALTER TABLE assessment
      ADD CONSTRAINT assessment_curve_bonus_nonnegative
      CHECK (
        curve_max_points >= 0
        AND curve_max_points <> 'NaN'::double precision
        AND curve_max_points <> 'Infinity'::double precision
      );
  END IF;
END
$$;

ALTER TABLE assessment
  ADD COLUMN IF NOT EXISTS time_limit_minutes integer NULL;

ALTER TABLE course
  ADD COLUMN IF NOT EXISTS default_time_limit_minutes integer NULL;

COMMENT ON COLUMN assessment.grade_weight IS
  'Relative weight for course totals when aggregation is percent-of-final-grade. 0 excludes the assessment.';

COMMENT ON COLUMN assessment.curve_max_points IS
  'Bonus points added to every recorded student grade for this assessment.';

COMMENT ON COLUMN assessment.time_limit_minutes IS
  'Allotted minutes when countdown forcibly-end option is active. NULL inherits course default.';

COMMENT ON COLUMN course.default_time_limit_minutes IS
  'Default allotted minutes for assessments using forcibly-end countdown without an override.';
