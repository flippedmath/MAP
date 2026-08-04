-- Allow rejected allotment requests on credit_purchase.
-- Safe to re-run.

BEGIN;

ALTER TABLE credit_purchase
  DROP CONSTRAINT IF EXISTS chk_credit_purchase_status;

ALTER TABLE credit_purchase
  ADD CONSTRAINT chk_credit_purchase_status
  CHECK (status IN ('pending', 'completed', 'canceled', 'rejected'));

COMMENT ON CONSTRAINT chk_credit_purchase_status ON credit_purchase IS
  'pending | completed | canceled | rejected (allotment denied by IT)';

COMMIT;
