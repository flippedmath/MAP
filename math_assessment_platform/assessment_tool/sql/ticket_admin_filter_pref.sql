-- Per-IT-user saved default filters for the Tickets admin list (unmanaged).
-- Safe to re-run.

BEGIN;

CREATE TABLE IF NOT EXISTS ticket_admin_filter_pref (
  user_id integer PRIMARY KEY REFERENCES user_profile(user_id) ON DELETE CASCADE DEFERRABLE,
  filters json NOT NULL DEFAULT '{}'::json,
  updated_at timestamp without time zone NOT NULL DEFAULT now()
);

COMMENT ON TABLE ticket_admin_filter_pref IS
  'Saved default Tickets-list filter/sort settings for an IT Support user.';

COMMENT ON COLUMN ticket_admin_filter_pref.filters IS
  'JSON object of list query params: status, priority, assigned_to, requester, unread, sort, dir.';

COMMIT;
