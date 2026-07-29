-- Refresh assessment_option_group to the revised product option set.
-- Safe to re-run. Removed groups/choices are deleted (after dependent rows).

-- ---------------------------------------------------------------------------
-- Permanently remove retired groups / replaced choices
-- ---------------------------------------------------------------------------
DELETE FROM course_default_assessment_options
WHERE option_type_id IN (1, 5, 8, 10, 11, 13)
   OR (option_type_id = 2 AND choice IN (6, 8));

DELETE FROM assessment_options
WHERE option_type_id IN (1, 5, 8, 10, 11, 13)
   OR (option_type_id = 2 AND choice IN (6, 8));

DELETE FROM assessment_option_group
WHERE group_num IN (1, 5, 8, 10, 11, 13)
   OR (group_num = 2 AND choice IN (6, 8))
   OR deprecated = true;

-- ---------------------------------------------------------------------------
-- Group 2: Student view of graded assessments (replace old 1/6/8 set)
-- ---------------------------------------------------------------------------
UPDATE assessment_option_group
SET description = 'Do NOT allow students to view graded assessments answers (Students view score only)',
    deprecated = false
WHERE group_num = 2 AND choice = 1;

INSERT INTO assessment_option_group (id, group_num, choice, description, deprecated)
VALUES (
  nextval('assessment_option_group_id_seq'),
  2,
  2,
  'When scores are released, Students can also pull up the graded submissions they took including the expected answers paired with the answers they provided',
  false
)
ON CONFLICT (group_num, choice) DO UPDATE
SET description = EXCLUDED.description,
    deprecated = false;

-- ---------------------------------------------------------------------------
-- Group 3: Course total calculation
-- ---------------------------------------------------------------------------
UPDATE assessment_option_group
SET description = 'Each assessment represents a % of the final grade',
    deprecated = false
WHERE group_num = 3 AND choice = 2;

UPDATE assessment_option_group
SET description = 'Calculate final score by accumulated points',
    deprecated = false
WHERE group_num = 3 AND choice = 3;

-- ---------------------------------------------------------------------------
-- Group 4: Retake assessment scoring
-- ---------------------------------------------------------------------------
UPDATE assessment_option_group
SET description = 'Use highest score a Student receives for all retake attempts for a given assessment',
    deprecated = false
WHERE group_num = 4 AND choice = 1;

UPDATE assessment_option_group
SET description = 'Use the latest score a Student receives for all a given assessment attempts',
    deprecated = false
WHERE group_num = 4 AND choice = 2;

-- ---------------------------------------------------------------------------
-- Group 6: Count-up timer
-- ---------------------------------------------------------------------------
UPDATE assessment_option_group
SET description = 'Do not show count-up timer',
    deprecated = false
WHERE group_num = 6 AND choice = 1;

UPDATE assessment_option_group
SET description = 'Show count-up timer while students take the assessment',
    deprecated = false
WHERE group_num = 6 AND choice = 2;

-- ---------------------------------------------------------------------------
-- Group 7: Count-down timer (+ forced time limit)
-- ---------------------------------------------------------------------------
UPDATE assessment_option_group
SET description = 'Do not show count-down timer',
    deprecated = false
WHERE group_num = 7 AND choice = 1;

UPDATE assessment_option_group
SET description = 'Show count-down timer based on assessment end time',
    deprecated = false
WHERE group_num = 7 AND choice = 2;

INSERT INTO assessment_option_group (id, group_num, choice, description, deprecated)
VALUES (
  nextval('assessment_option_group_id_seq'),
  7,
  3,
  'Show count-down timer and forcibly end test after time_limit minutes',
  false
)
ON CONFLICT (group_num, choice) DO UPDATE
SET description = EXCLUDED.description,
    deprecated = false;

-- ---------------------------------------------------------------------------
-- Group 9: Lock on focus leave
-- ---------------------------------------------------------------------------
UPDATE assessment_option_group
SET description = 'Lock test progress when student focus leaves the browser tab',
    deprecated = false
WHERE group_num = 9 AND choice = 1;

UPDATE assessment_option_group
SET description = 'Do not lock test when student focus leaves the browser tab',
    deprecated = false
WHERE group_num = 9 AND choice = 2;

-- ---------------------------------------------------------------------------
-- Group 12: Synchronize tests
-- ---------------------------------------------------------------------------
UPDATE assessment_option_group
SET description = 'Do not synchronize tests between students (All Students take a different test)',
    deprecated = false
WHERE group_num = 12 AND choice = 1;

UPDATE assessment_option_group
SET description = 'Synchronize tests between students taking the same assessment',
    deprecated = false
WHERE group_num = 12 AND choice = 2;

-- ---------------------------------------------------------------------------
-- Group 14: Curve
-- ---------------------------------------------------------------------------
INSERT INTO assessment_option_group (id, group_num, choice, description, deprecated)
VALUES
  (
    nextval('assessment_option_group_id_seq'),
    14,
    1,
    'No adjusting the scores',
    false
  ),
  (
    nextval('assessment_option_group_id_seq'),
    14,
    2,
    'Adjusting the scores on the class as a whole allowed',
    false
  )
ON CONFLICT (group_num, choice) DO UPDATE
SET description = EXCLUDED.description,
    deprecated = false;
