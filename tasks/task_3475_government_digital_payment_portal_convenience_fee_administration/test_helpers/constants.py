"""Domain thresholds and shared literals, each pinned to a PRD sentence.

Every value below comes from PRD prose, never from an unpinned reading:

- DEFAULT_CLOCK_UTC: "the clock's startup default is exactly
  2026-09-01T00:00:00Z" (PRD section on the logical clock).
- Fee rate pairs: "at 150 basis points plus 25 fixed cents for CONSUMER_DEBIT,
  220 basis points plus 30 fixed cents for CONSUMER_CREDIT, and 290 basis
  points plus 35 fixed cents for COMMERCIAL; a WALLET payment is rated at 180
  basis points plus 25 fixed cents; and an ECHECK payment carries no rate at
  all, just a flat 150 cents" (PRD checkout section, fee step one).
- MIN_FEE_CENTS: "the fee is the greater of 100 cents and the raw fee"
  (fee step three).
- QUOTE_TTL_MINUTES: "expires thirty minutes after creation" (PRD checkout).
- METHOD_LAG_DAYS: "one day for CARD, one day for WALLET, and two days for
  ECHECK" (PRD checkout, capture paragraph).
- REPRESENTMENT_WINDOW_DAYS / MAX_REPRESENTMENT_COUNT: "re-present a RETURNED
  transaction exactly once ... a logical clock no later than thirty days after
  returned_at" (PRD ACH section).
- ACH_VERIFY_FAILURE_LIMIT: "the failure that brings ach_verify_failures to 3"
  (PRD instruments section).
- CHARGEBACK_EVIDENCE_DAYS: "its evidence_due_at computed as opened_at plus
  ten days" (PRD chargebacks section).
- DEPOSIT_GRACE_DAYS: "a grace of one day" (PRD reconciliation section).
- TOTAL_PORTAL_COST_CENTS / AMORTIZATION_MONTHS / MONTHLY_AMORTIZATION_CENTS:
  "a fixed total of 12000000 cents, amortized straight-line over 60 months at
  200000 cents per month" (PRD self-funding section).
- Pagination: "limit, defaulting to 10 with a minimum of 1 and a maximum of
  100, and offset, defaulting to 0" (PRD pagination section).
"""

# --- logical clock ---------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"

# --- convenience fee ---------------------------------------------------------
# (rate_bp, fixed_cents) per card cost bucket; ECHECK is flat, no rate.
CARD_FEE_RATES = {
    "CONSUMER_DEBIT": (150, 25),
    "CONSUMER_CREDIT": (220, 30),
    "COMMERCIAL": (290, 35),
}
WALLET_FEE_RATE_BP = 180
WALLET_FEE_FIXED_CENTS = 25
ECHECK_FLAT_FEE_CENTS = 150
MIN_FEE_CENTS = 100
QUOTE_TTL_MINUTES = 30

# --- funds-flow calendar -----------------------------------------------------
METHOD_LAG_DAYS = {"CARD": 1, "WALLET": 1, "ECHECK": 2}
REPRESENTMENT_WINDOW_DAYS = 30
MAX_REPRESENTMENT_COUNT = 1
ACH_VERIFY_FAILURE_LIMIT = 3
CHARGEBACK_EVIDENCE_DAYS = 10
DEPOSIT_GRACE_DAYS = 1

# --- self-funding ledger -----------------------------------------------------
TOTAL_PORTAL_COST_CENTS = 12_000_000
AMORTIZATION_MONTHS = 60
MONTHLY_AMORTIZATION_CENTS = 200_000

# --- pagination ---------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
