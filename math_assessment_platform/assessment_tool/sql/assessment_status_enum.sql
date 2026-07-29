-- Narrow assessment.status to the current lifecycle set + soft-delete.
-- Apply manually (assessment is unmanaged).
--
-- Teacher-selectable: closed | open | upcoming | hidden
-- Soft-delete (trash): deleted
-- Legacy remaps: inactive -> hidden; locked|retake_available|submitted|active -> closed
-- NULL status -> hidden (matches app default / student visibility)

BEGIN;

-- Widen to text so remaps are not constrained by the old enum labels.
ALTER TABLE assessment
    ALTER COLUMN status TYPE text
    USING status::text;

UPDATE assessment
SET status = 'hidden'
WHERE status IS NULL
   OR status = 'inactive';

UPDATE assessment
SET status = 'closed'
WHERE status IN (
    'locked',
    'retake_available',
    'submitted',
    'active'
);

CREATE TYPE assessment_status_enum_new AS ENUM (
    'closed',
    'open',
    'upcoming',
    'hidden',
    'deleted'
);

ALTER TABLE assessment
    ALTER COLUMN status TYPE assessment_status_enum_new
    USING status::assessment_status_enum_new;

DROP TYPE assessment_status_enum;

ALTER TYPE assessment_status_enum_new RENAME TO assessment_status_enum;

COMMENT ON COLUMN assessment.status IS
  'closed | open | upcoming | hidden (teacher lifecycle); deleted (trash).';

COMMIT;
