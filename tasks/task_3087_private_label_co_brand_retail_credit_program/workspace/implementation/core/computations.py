"""Domain constants and the pure calculation functions (PRD §3.4, §3.6, §3.7).

All money is integer cents; every computed monetary result is struck to two
decimal places with round-half-up, and where a per-item figure is rounded and
then summed the per-item rounding happens first (PRD §2.7).
"""
from decimal import Decimal, ROUND_HALF_UP

# --- promotional term rate table (PRD §3.4) --------------------------------
TERM_RATE = {6: Decimal("0.1299"), 12: Decimal("0.1599"),
             18: Decimal("0.1899"), 24: Decimal("0.2199")}
SUPPORTED_PROMO_TERMS = (6, 12, 18, 24)

# --- agreement defaults (PRD §3.1) ------------------------------------------
MINIMUM_CHARGE_CENTS_DEFAULT = 29900
SETTLEMENT_TERMS_DAYS_DEFAULT = 30
DISPUTE_GRACE_DAYS_DEFAULT = 0
RENEWAL_NOTICE_DAYS_DEFAULT = 90
PURCHASE_RIGHT_RATE_DEFAULT = 1.04

# --- acquisition bands (PRD §3.3) -------------------------------------------
CREDIT_APPROVAL_CEILING_CENTS = 1_500_000
CREDIT_APPLICANT_CEILING_CENTS = 5_000_000

# --- minimum payment / windows (PRD §3.5) -----------------------------------
MINIMUM_PAYMENT_FLOOR_CENTS = 3500
BALANCE_FRACTION = Decimal("0.02")
CHARGE_OFF_WINDOW_DAYS = 180
DISPUTE_WINDOW_DAYS = 60

# --- agreement exposure safeguard (PRD §3.1) --------------------------------
AGREEMENT_SUSPENSION_THRESHOLD_CENTS = 5_000_000_000
AGREEMENT_REINSTATEMENT_THRESHOLD_CENTS = 4_000_000_000

# --- delinquency risk scoring (PRD §3.6) ------------------------------------
DELINQUENT_POINTS = 400
OVER_LIMIT_POINTS = 300
UTILIZATION_UNIT_CENTS = 500_000
UTILIZATION_STEP_POINTS = 25
UTILIZATION_CAP_POINTS = 200
DAYS_PENALTY_PER_DAY = 2
DAYS_CAP_POINTS = 100
SCORE_CEILING = 1000

# --- profitability (PRD §3.6) -----------------------------------------------
ACQUISITION_COST_PER_ACCOUNT_CENTS = 4200
BALANCE_CAP_MULTIPLE = Decimal("2.5")
BALANCE_UNIT_CENTS = 1_000_000


def dec(value) -> Decimal:
    return Decimal(str(value))


def round_half_up(value, places: int = 0):
    """Round with ROUND_HALF_UP; places=0 yields int, places>0 yields float."""
    quant = Decimal(1).scaleb(-places)
    rounded = dec(value).quantize(quant, rounding=ROUND_HALF_UP)
    return int(rounded) if places == 0 else float(rounded)


def money(value) -> int:
    """Round a decimal amount to whole cents, half-up."""
    return round_half_up(value, 0)


def term_rate(months: int) -> Decimal:
    return TERM_RATE[months]


# ---------------------------------------------------------------------------
# Promotional subsidy (PRD §3.4, §3.7)
# ---------------------------------------------------------------------------

def projected_interest(principal_cents: int, months: int) -> int:
    """Full-term projected subsidy: principal * rate * months / 12, half-up."""
    raw = dec(principal_cents) * term_rate(months) * dec(months) / dec(12)
    return money(raw)


def accrued_interest(principal_cents: int, months: int, days_accrued: int) -> int:
    """As-charged accrued subsidy: principal * rate * days / 365, half-up."""
    raw = dec(principal_cents) * term_rate(months) * dec(days_accrued) / dec(365)
    return money(raw)


def subsidy_at_application(principal_cents: int, months: int) -> int:
    """Struck once from the transaction-specific term rate; never revised."""
    return projected_interest(principal_cents, months)


def minimum_payment_due(account: dict) -> int:
    """Computed serviced minimum (PRD §3.5)."""
    if account.get("account_status") == "CHARGED_OFF":
        return 0
    balance = account.get("outstanding_balance_cents", 0)
    if balance == 0:
        return 0
    if account.get("account_status") == "DELINQUENT":
        return balance
    pct = money(dec(balance) * BALANCE_FRACTION)
    return pct if pct >= MINIMUM_PAYMENT_FLOOR_CENTS else MINIMUM_PAYMENT_FLOOR_CENTS


def delinquency_risk_score(account: dict, days_since_last_payment: int) -> int:
    """Per-account risk score, ceiling 1000 (PRD §3.6)."""
    score = 0
    if account.get("account_status") == "DELINQUENT":
        score += DELINQUENT_POINTS
    if account.get("outstanding_balance_cents", 0) > account.get("credit_limit_cents", 0):
        score += OVER_LIMIT_POINTS
    units = account.get("outstanding_balance_cents", 0) // UTILIZATION_UNIT_CENTS
    score += min(UTILIZATION_CAP_POINTS, units * UTILIZATION_STEP_POINTS)
    score += min(DAYS_CAP_POINTS, days_since_last_payment * DAYS_PENALTY_PER_DAY)
    return min(SCORE_CEILING, score)