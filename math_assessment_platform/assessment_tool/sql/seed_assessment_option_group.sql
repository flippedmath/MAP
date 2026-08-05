-- Fresh-DB seed for assessment_option_group (revised option set).
-- Prefer sync_assessment_option_group.sql on existing databases.

INSERT INTO assessment_option_group (id, group_num, choice, description, deprecated)
VALUES
  -- Group 2: Student view of graded assessments
  (nextval('assessment_option_group_id_seq'), 2, 1,
   'Do NOT allow students to view graded assessments answers (Students view score only)', false),
  (nextval('assessment_option_group_id_seq'), 2, 2,
   'When scores are released, Students can also pull up the graded submissions they took including the expected answers paired with the answers they provided', false),

  -- Group 3: Course total calculation
  (nextval('assessment_option_group_id_seq'), 3, 2,
   'Each assessment represents a % of the final grade and can be distributed by an assigned weight.', false),
  (nextval('assessment_option_group_id_seq'), 3, 3,
   'Calculate final score by accumulated points', false),

  -- Group 4: Retake assessment scoring
  (nextval('assessment_option_group_id_seq'), 4, 1,
   'Use highest score a Student receives for all retake attempts for a given assessment', false),
  (nextval('assessment_option_group_id_seq'), 4, 2,
   'Use the latest score a Student receives for all a given assessment attempts', false),

  -- Group 6: Count-up timer
  (nextval('assessment_option_group_id_seq'), 6, 1, 'Do not show count-up timer', false),
  (nextval('assessment_option_group_id_seq'), 6, 2, 'Show count-up timer while students take the assessment', false),

  -- Group 7: Count-down timer
  (nextval('assessment_option_group_id_seq'), 7, 1, 'Do not show count-down timer', false),
  (nextval('assessment_option_group_id_seq'), 7, 2, 'Show count-down timer based on assessment end time', false),
  (nextval('assessment_option_group_id_seq'), 7, 3,
   'Show count-down timer and forcibly end test after time_limit minutes', false),

  -- Group 9: Lock on focus leave
  (nextval('assessment_option_group_id_seq'), 9, 1,
   'Lock test progress when student focus leaves the browser tab', false),
  (nextval('assessment_option_group_id_seq'), 9, 2,
   'Do not lock test when student focus leaves the browser tab', false),

  -- Group 12: Synchronize tests
  (nextval('assessment_option_group_id_seq'), 12, 1,
   'Do not synchronize tests between students (All Students take a different test)', false),
  (nextval('assessment_option_group_id_seq'), 12, 2,
   'Synchronize tests between students taking the same assessment', false),

  -- Group 14: Curve
  (nextval('assessment_option_group_id_seq'), 14, 1, 'No adjusting the scores', false),
  (nextval('assessment_option_group_id_seq'), 14, 2,
   'Adjusting the scores on the class as a whole allowed', false),

  -- Group 15: Score release
  (nextval('assessment_option_group_id_seq'), 15, 1,
   'Release grades to students automatically when scores are ready', false),
  (nextval('assessment_option_group_id_seq'), 15, 2,
   'Teacher must release grades to students for each assessment', false),

  -- Group 16: Open session date column (Course Assessments table)
  (nextval('assessment_option_group_id_seq'), 16, 1,
   'Do not show the open session date column on the Course Assessments page', false),
  (nextval('assessment_option_group_id_seq'), 16, 2,
   'Show a column with the date of the open/retake session (only when at least one student started before close)', false)
ON CONFLICT (group_num, choice) DO NOTHING;
