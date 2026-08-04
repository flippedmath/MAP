-- Add ticket status: awaiting_response (waiting for the client).
-- ADD VALUE cannot always run inside an explicit transaction; keep this file standalone.
-- Safe to re-run (IF NOT EXISTS).

ALTER TYPE ticket_status_enum ADD VALUE IF NOT EXISTS 'awaiting_response';
