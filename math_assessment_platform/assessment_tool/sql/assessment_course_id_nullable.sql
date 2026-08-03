-- Allow standalone library assessments (Workspace / shared copies) with no course.
-- Student-facing takes still require a course-scoped assessment; course_id NULL
-- means the assessment is editorial-only until attached to a course later.
--
-- Safe to re-run.

ALTER TABLE assessment
  ALTER COLUMN course_id DROP NOT NULL;

COMMENT ON COLUMN assessment.course_id IS
  'Course this assessment belongs to. NULL for standalone library assessments that are not enrolled/student-facing until attached to a course.';
