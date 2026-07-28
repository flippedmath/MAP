-- Group-owned permission groups (e.g. public owned by admins).
-- Safe to re-run.

BEGIN;

ALTER TABLE permission_group
  ADD COLUMN IF NOT EXISTS owner_pg_id integer NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'permission_group_owner_pg_id_fkey'
  ) THEN
    ALTER TABLE permission_group
      ADD CONSTRAINT permission_group_owner_pg_id_fkey
      FOREIGN KEY (owner_pg_id) REFERENCES permission_group(id)
      ON DELETE SET NULL DEFERRABLE;
  END IF;
END $$;

COMMENT ON COLUMN permission_group.owner_pg_id IS
  'When set, this permission_group is owned by another group (e.g. public owned by admins) instead of a single user.';

ALTER TABLE permission_group
  ADD COLUMN IF NOT EXISTS system_protected boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN permission_group.system_protected IS
  'System groups (admins, public) cannot be deleted even when empty.';

COMMIT;
