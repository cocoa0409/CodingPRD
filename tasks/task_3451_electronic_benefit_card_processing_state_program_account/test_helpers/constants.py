"""Domain constants taken verbatim from the PRD.

Sources:
- PRD §2.4: the logical clock starts at exactly 2026-09-01T00:00:00Z.
- PRD §2.11: the eighteen contract configuration defaults and their constraints.
- PRD §2.3: pagination defaults (limit 10, min 1, max 100, offset 0).

The small pure helpers at the bottom restate PRD formulas (posting bucket,
first-month proration, per-transaction acquirer fee, net settlement position)
so tests compute expectations the same way the contract specifies them. They
take all inputs as parameters and encode no instance-specific answers.
"""

# --- The logical clock (PRD §2.4) -------------------------------------------
LOGICAL_CLOCK_DEFAULT_UTC = "2026-09-01T00:00:00Z"

# --- Contract configuration defaults (PRD §2.11) ----------------------------
DEFAULT_POSTING_MODULUS = 10                # must be 1..28
DEFAULT_AVAILABILITY_HOUR_UTC = 6           # 0..23
DEFAULT_EXPUNGEMENT_INACTIVITY_DAYS = 90    # >= 31
EXPUNGEMENT_NOTICE_LEAD_DAYS = 30           # >= 1
DEFAULT_DISASTER_EXPIRY_DAYS = 30           # >= 1
DEFAULT_REPLACEMENT_FEE_CENTS = 250         # >= 0
FREE_REPLACEMENTS_PER_365D = 1              # >= 0
PIN_MAX_FAILURES = 3                        # >= 1
CLAIM_WINDOW_DAYS = 60                      # >= 1
PROVISIONAL_CREDIT_DELAY_DAYS = 10          # >= 1
PROVISIONAL_CREDIT_CAP_CENTS = 50000        # >= 0
SKIMMING_SUSPEND_THRESHOLD = 3              # >= 1
DISPUTE_WINDOW_DAYS = 15                    # >= 1
ACQUIRER_FEE_BASIS_POINTS = 75              # >= 0
CASH_WITHDRAWAL_DAILY_LIMIT_CENTS = 50000   # >= 0
CASH_WITHDRAWAL_MULTIPLE_CENTS = 500        # >= 1
SETTLEMENT_CUTOFF_HOUR_UTC = 0              # 0..23
CARD_MAIL_DELAY_HOURS = 24                  # >= 0

# --- Pagination (PRD §2.3) ----------------------------------------------------
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# --- Claim input bounds (PRD §3.8: between one and twenty transactions) -----
CLAIM_MAX_REFERENCED_TXNS = 20


# --- PRD formula helpers (generic; no instance answers) ----------------------

def round_half_up_ratio(numerator: int, denominator: int) -> int:
    """round_half_up(numerator / denominator) on integers (PRD §2.6)."""
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    quotient, remainder = divmod(numerator, denominator)
    if remainder * 2 >= denominator:
        quotient += 1
    return quotient


def posting_bucket(case_identifier: str, modulus: int = DEFAULT_POSTING_MODULUS) -> int:
    """bucket = int(case_identifier) MOD modulus (PRD §3.4)."""
    return int(case_identifier) % modulus


def prorated_amount_cents(run_amount_cents: int, remaining_days: int, days_in_month: int) -> int:
    """First-month proration, rounded half up exactly once (PRD §3.4)."""
    return round_half_up_ratio(run_amount_cents * remaining_days, days_in_month)


def acquirer_fee_cents_for(total_cents: int, basis_points: int = ACQUIRER_FEE_BASIS_POINTS) -> int:
    """Per-transaction fee, round half up BEFORE any summation (PRD §3.9)."""
    return round_half_up_ratio(total_cents * basis_points, 10000)


def net_position_cents(gross_settled_cents: int, acquirer_fee_cents: int,
                       adjustment_total_cents: int = 0) -> int:
    """net = gross - fee + adjustments (PRD §3.9)."""
    return gross_settled_cents - acquirer_fee_cents + adjustment_total_cents


def provisional_credit_cents_for(claimed_amount_cents: int,
                                 cap_cents: int = PROVISIONAL_CREDIT_CAP_CENTS) -> int:
    """min(claimed, cap) auto-issued by the provisional-credit sweep (PRD §3.8)."""
    return min(claimed_amount_cents, cap_cents)
