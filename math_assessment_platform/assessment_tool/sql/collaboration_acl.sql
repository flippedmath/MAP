-- Collaboration ACL schema upgrades (unmanaged Django tables).
-- Safe to re-run with IF NOT EXISTS / guarded renames.

BEGIN;

-- 1. Rename permission enum label admin → owner (no row backfill; tables empty).
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM pg_enum e
    JOIN pg_type t ON e.enumtypid = t.oid
    WHERE t.typname = 'users_group_permission'
      AND e.enumlabel = 'admin'
  ) AND NOT EXISTS (
    SELECT 1
    FROM pg_enum e
    JOIN pg_type t ON e.enumtypid = t.oid
    WHERE t.typname = 'users_group_permission'
      AND e.enumlabel = 'owner'
  ) THEN
    ALTER TYPE users_group_permission RENAME VALUE 'admin' TO 'owner';
  END IF;
END $$;

-- 2. permission_group.owner_id
ALTER TABLE permission_group
  ADD COLUMN IF NOT EXISTS owner_id integer NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'permission_group_owner_id_fkey'
  ) THEN
    ALTER TABLE permission_group
      ADD CONSTRAINT permission_group_owner_id_fkey
      FOREIGN KEY (owner_id) REFERENCES user_profile(user_id)
      ON DELETE SET NULL DEFERRABLE;
  END IF;
END $$;

COMMENT ON COLUMN permission_group.owner_id IS
  'Optional user owner of a named permission group. System public is owned via owner_pg_id (admins), not a user.';

-- 3. Fix user_permission_group FKs + add permissions role column
ALTER TABLE user_permission_group
  ADD COLUMN IF NOT EXISTS permissions users_group_permission NULL;

-- Drop the incorrect FK that pointed user_id at permission_group (inspectdb artifact).
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'user_permission_group'::regclass
      AND conname = 'user_permission_group_user_id_fkey1'
  ) THEN
    ALTER TABLE user_permission_group DROP CONSTRAINT user_permission_group_user_id_fkey1;
  END IF;
END $$;

-- Ensure user_id → user_profile
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'user_permission_group'::regclass
      AND conname = 'user_permission_group_user_id_fkey'
  ) THEN
    ALTER TABLE user_permission_group
      ADD CONSTRAINT user_permission_group_user_id_fkey
      FOREIGN KEY (user_id) REFERENCES user_profile(user_id)
      ON DELETE CASCADE DEFERRABLE;
  END IF;
END $$;

-- Ensure pg_id → permission_group
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'user_permission_group'::regclass
      AND conname = 'user_permission_group_pg_id_fkey'
  ) THEN
    ALTER TABLE user_permission_group
      ADD CONSTRAINT user_permission_group_pg_id_fkey
      FOREIGN KEY (pg_id) REFERENCES permission_group(id)
      ON DELETE CASCADE DEFERRABLE;
  END IF;
END $$;

-- Default any null permissions then enforce NOT NULL (empty table today).
UPDATE user_permission_group SET permissions = 'read_only' WHERE permissions IS NULL;
ALTER TABLE user_permission_group
  ALTER COLUMN permissions SET NOT NULL;

COMMENT ON COLUMN user_permission_group.permissions IS
  'Membership role within the permission_group: owner | edit | read_only.';

-- 4. branch_group.trashed_at + share_group_id
ALTER TABLE branch_group
  ADD COLUMN IF NOT EXISTS trashed_at timestamp with time zone NULL;

ALTER TABLE branch_group
  ADD COLUMN IF NOT EXISTS share_group_id integer NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'branch_group_share_group_id_fkey'
  ) THEN
    ALTER TABLE branch_group
      ADD CONSTRAINT branch_group_share_group_id_fkey
      FOREIGN KEY (share_group_id) REFERENCES permission_group(id)
      ON DELETE SET NULL DEFERRABLE;
  END IF;
END $$;

COMMENT ON COLUMN branch_group.trashed_at IS
  'Set when this node is moved to Trash; cleared on restore. Used for 30-day purge.';

COMMENT ON COLUMN branch_group.share_group_id IS
  'When set, this branch is a share root linked to a permission_group.';

CREATE INDEX IF NOT EXISTS idx_branch_group_trashed_at_purge
  ON branch_group (trashed_at)
  WHERE trashed_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_branch_group_share_group_id
  ON branch_group (share_group_id)
  WHERE share_group_id IS NOT NULL;

-- 5. Group-owned permission groups (public owned by admins) + system protection
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
