-- Course invitation extensions for user_course_activation
-- Applied manually (unmanaged Django tables). Safe to re-run with IF NOT EXISTS / DROP IF EXISTS.

BEGIN;

ALTER TABLE user_course_activation
  ALTER COLUMN temp_email DROP NOT NULL;

ALTER TABLE user_course_activation
  DROP CONSTRAINT IF EXISTS user_course_activation_temp_email_key;

ALTER TABLE user_course_activation
  ADD COLUMN IF NOT EXISTS status character varying(32) NOT NULL DEFAULT 'pending',
  ADD COLUMN IF NOT EXISTS invited_username character varying(255) NULL,
  ADD COLUMN IF NOT EXISTS target_user_id integer NULL,
  ADD COLUMN IF NOT EXISTS created_by_id integer NULL,
  ADD COLUMN IF NOT EXISTS creation_date timestamp without time zone DEFAULT now();

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'user_course_activation_target_user_id_fkey'
  ) THEN
    ALTER TABLE user_course_activation
      ADD CONSTRAINT user_course_activation_target_user_id_fkey
      FOREIGN KEY (target_user_id) REFERENCES user_profile(user_id)
      ON DELETE SET NULL DEFERRABLE;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'user_course_activation_created_by_id_fkey'
  ) THEN
    ALTER TABLE user_course_activation
      ADD CONSTRAINT user_course_activation_created_by_id_fkey
      FOREIGN KEY (created_by_id) REFERENCES user_profile(user_id)
      ON DELETE SET NULL DEFERRABLE;
  END IF;
END $$;

ALTER TABLE user_course_activation
  DROP CONSTRAINT IF EXISTS user_course_activation_status_check;
ALTER TABLE user_course_activation
  ADD CONSTRAINT user_course_activation_status_check
  CHECK (status IN ('pending', 'accepted', 'voided'));

CREATE UNIQUE INDEX IF NOT EXISTS uq_uca_code
  ON user_course_activation (code);

CREATE UNIQUE INDEX IF NOT EXISTS uq_uca_pending_course_email
  ON user_course_activation (course_id, lower(temp_email))
  WHERE status = 'pending' AND temp_email IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_uca_pending_course_target
  ON user_course_activation (course_id, target_user_id)
  WHERE status = 'pending' AND target_user_id IS NOT NULL;

COMMIT;
