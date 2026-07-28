-- Nested permission groups (subgroups). Unmanaged Django table — apply outside migrate.
-- Safe to re-run.

BEGIN;

CREATE TABLE IF NOT EXISTS permission_group_subgroup (
  parent_pg_id integer NOT NULL REFERENCES permission_group(id) ON DELETE CASCADE,
  child_pg_id integer NOT NULL REFERENCES permission_group(id) ON DELETE CASCADE,
  permissions users_group_permission NOT NULL,
  PRIMARY KEY (parent_pg_id, child_pg_id),
  CONSTRAINT permission_group_subgroup_not_self CHECK (parent_pg_id <> child_pg_id)
);

COMMENT ON TABLE permission_group_subgroup IS
  'Nesting: child permission_group is a subgroup of parent. Edge permissions are edit|read_only caps for inherited branch ACL.';

COMMENT ON COLUMN permission_group_subgroup.permissions IS
  'Access level the child group inherits from the parent when the parent is granted on a branch: edit | read_only.';

CREATE INDEX IF NOT EXISTS idx_permission_group_subgroup_child
  ON permission_group_subgroup (child_pg_id);

COMMIT;
