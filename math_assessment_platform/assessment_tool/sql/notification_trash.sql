-- Soft-delete / trash for notifications.
-- Applied manually (unmanaged Django tables). Safe to re-run with IF NOT EXISTS.

BEGIN;

ALTER TABLE notification
  ADD COLUMN IF NOT EXISTS deleted_at timestamp without time zone NULL;

COMMENT ON COLUMN notification.deleted_at IS
  'When set, the notification is in the user trash. Permanently purged ~30 days after this timestamp.';

CREATE INDEX IF NOT EXISTS idx_notification_receiver_deleted_at
  ON notification (receiver, deleted_at);

CREATE INDEX IF NOT EXISTS idx_notification_deleted_at_purge
  ON notification (deleted_at)
  WHERE deleted_at IS NOT NULL;

COMMIT;
