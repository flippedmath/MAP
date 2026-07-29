-- Permanently remove deprecated assessment_option_group rows and dependent settings.

-- Drop course / assessment selections that point at deprecated enum rows.
DELETE FROM course_default_assessment_options cdao
USING assessment_option_group g
WHERE g.group_num = cdao.option_type_id
  AND g.choice = cdao.choice
  AND g.deprecated = true;

DELETE FROM assessment_options ao
USING assessment_option_group g
WHERE g.group_num = ao.option_type_id
  AND g.choice = ao.choice
  AND g.deprecated = true;

-- Also remove any leftover selections for fully-retired group numbers
-- (in case rows were already unmarked but should not exist).
DELETE FROM course_default_assessment_options
WHERE option_type_id IN (1, 5, 8, 10, 11, 13);

DELETE FROM assessment_options
WHERE option_type_id IN (1, 5, 8, 10, 11, 13);

-- Old student-view choices replaced by (2,1) and (2,2)
DELETE FROM course_default_assessment_options
WHERE option_type_id = 2 AND choice IN (6, 8);

DELETE FROM assessment_options
WHERE option_type_id = 2 AND choice IN (6, 8);

DELETE FROM assessment_option_group
WHERE deprecated = true
   OR group_num IN (1, 5, 8, 10, 11, 13)
   OR (group_num = 2 AND choice IN (6, 8));
