-- IT Tickets + Contact Us extensions (unmanaged). Safe to re-run.

BEGIN;

-- contact_us: creation timestamp for admin inbox sorting
ALTER TABLE contact_us
  ADD COLUMN IF NOT EXISTS creation_date timestamp without time zone NOT NULL DEFAULT now();

COMMENT ON COLUMN contact_us.creation_date IS
  'When the Contact Us submission was created.';

-- ticket priority enum
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'ticket_priority_enum') THEN
    CREATE TYPE ticket_priority_enum AS ENUM ('low', 'normal', 'high', 'urgent');
  END IF;
END$$;

ALTER TABLE ticket
  ADD COLUMN IF NOT EXISTS access_token character varying(64),
  ADD COLUMN IF NOT EXISTS priority ticket_priority_enum NOT NULL DEFAULT 'normal'::ticket_priority_enum,
  ADD COLUMN IF NOT EXISTS modification_date timestamp without time zone NOT NULL DEFAULT now(),
  ADD COLUMN IF NOT EXISTS last_comment_at timestamp without time zone,
  ADD COLUMN IF NOT EXISTS admin_unread boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS client_notified_at timestamp without time zone;

-- Backfill tokens for any pre-existing rows, then enforce NOT NULL + unique.
UPDATE ticket
SET access_token = replace(gen_random_uuid()::text || gen_random_uuid()::text, '-', '')
WHERE access_token IS NULL OR btrim(access_token) = '';

ALTER TABLE ticket
  ALTER COLUMN access_token SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_ticket_access_token
  ON ticket (access_token);

COMMENT ON COLUMN ticket.access_token IS
  'Unguessable public client access token (URL /tickets/t/<token>/).';
COMMENT ON COLUMN ticket.priority IS
  'IT triage priority: low, normal, high, urgent.';
COMMENT ON COLUMN ticket.modification_date IS
  'Bumped on any admin or client ticket action.';
COMMENT ON COLUMN ticket.last_comment_at IS
  'Bumped when a discussion row is inserted.';
COMMENT ON COLUMN ticket.admin_unread IS
  'True when the client has commented since IT last viewed/replied.';
COMMENT ON COLUMN ticket.client_notified_at IS
  'When the client was last sent a ticket access/update notification stub.';

ALTER TABLE ticket_discussion
  ADD COLUMN IF NOT EXISTS is_system boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS author_user_id integer;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ticket_discussion_author_user_id_fkey'
  ) THEN
    ALTER TABLE ticket_discussion
      ADD CONSTRAINT ticket_discussion_author_user_id_fkey
      FOREIGN KEY (author_user_id) REFERENCES user_profile(user_id) DEFERRABLE;
  END IF;
END$$;

COMMENT ON COLUMN ticket_discussion.is_system IS
  'True for auto-generated action lines (assign, status, reopen, etc.).';
COMMENT ON COLUMN ticket_discussion.author_user_id IS
  'Known platform user who authored the comment, when available.';

COMMIT;
