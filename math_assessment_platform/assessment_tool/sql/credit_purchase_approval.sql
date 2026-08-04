-- Purchase / invoice approval details for allotment verification and purchase history.
-- Safe to re-run.

BEGIN;

ALTER TABLE credit_purchase
  ADD COLUMN IF NOT EXISTS money_spent numeric(12, 2);

ALTER TABLE credit_purchase
  ADD COLUMN IF NOT EXISTS credits_gained integer;

ALTER TABLE credit_purchase
  ADD COLUMN IF NOT EXISTS invoice_dated date;

ALTER TABLE credit_purchase
  ADD COLUMN IF NOT EXISTS paid_by character varying(255);

ALTER TABLE credit_purchase
  ADD COLUMN IF NOT EXISTS payer_organization character varying(255);

ALTER TABLE credit_purchase
  ADD COLUMN IF NOT EXISTS approval_notes text;

ALTER TABLE credit_purchase
  ADD COLUMN IF NOT EXISTS approved_by_id integer
    REFERENCES user_profile(user_id) ON DELETE SET NULL DEFERRABLE;

ALTER TABLE credit_purchase
  ADD COLUMN IF NOT EXISTS approved_at timestamp without time zone;

CREATE INDEX IF NOT EXISTS idx_credit_purchase_completed_at
  ON credit_purchase (completed_at DESC NULLS LAST)
  WHERE status = 'completed';

CREATE INDEX IF NOT EXISTS idx_credit_purchase_invoice_dated
  ON credit_purchase (invoice_dated DESC NULLS LAST)
  WHERE invoice_dated IS NOT NULL;

COMMENT ON COLUMN credit_purchase.money_spent IS
  'Amount paid (from invoice for allotments; checkout total for website orders).';
COMMENT ON COLUMN credit_purchase.credits_gained IS
  'Credits granted on completion (may match pack_size).';
COMMENT ON COLUMN credit_purchase.invoice_dated IS
  'Date stamped on the invoice (allotments) or purchase date (checkout).';
COMMENT ON COLUMN credit_purchase.paid_by IS
  'Who paid for the credits (from invoice / admin entry, or website checkout label).';
COMMENT ON COLUMN credit_purchase.payer_organization IS
  'Optional organization associated with the payment.';
COMMENT ON COLUMN credit_purchase.approval_notes IS
  'Optional admin notes captured when verifying an allotment.';
COMMENT ON COLUMN credit_purchase.approved_by_id IS
  'IT Support user who verified an allotment request (null for website checkout).';
COMMENT ON COLUMN credit_purchase.approved_at IS
  'When an allotment was verified by IT Support.';

COMMIT;
