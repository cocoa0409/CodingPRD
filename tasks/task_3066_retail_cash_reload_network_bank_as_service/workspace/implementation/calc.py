"""Calculation rules, implemented from the scaffold's calculations table.

Money is always integer cents or Decimal - never float.
"""

from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

# --- fixed constants ---------------------------------------------------------
FEE_TIER_1_FLAT_CENTS = 199
FEE_TIER_2_MARGINAL_CENTS = 249
FEE_TIER_3_MARGINAL_CENTS = 399

VELOCITY_TXN_LIMIT = 5
VELOCITY_AMOUNT_LIMIT_CENTS = 1000000

STRUCTURING_LOWER_CENTS = 9000
STRUCTURING_UPPER_CENTS = 9999
STRUCTURING_TXN_COUNT = 3
STRUCTURING_MIN_TOTAL_CENTS = 27000

POSTURE_LAMBDA_BASE = Decimal("0.10")
POSTURE_LAMBDA_OVERDUE = Decimal("0.20")
FREEZE_THRESHOLD = Decimal("60.00")
UNFREEZE_THRESHOLD = Decimal("3.99")

PROVISIONAL_CAP_REG_E = 2500
PROVISIONAL_CAP_VOLUNTARY = 1500
PROVISIONAL_CAP_CORPORATE = 500
REG_E_ERROR_RESOLUTION_FLOOR_CENTS = 250

BANK_BEAR_PCT_BAAS = Decimal("0.15")
BANK_BEAR_PCT_OWN = Decimal("0.00")

FLOAT_CAP_CENTS = 3000000
OVERSIGHT_INTERVAL_DAYS = 90

MIN_LOAD_PRINCIPAL_CENTS = 100

RESPONSE_WINDOW_HOURS = {"REG_E": 24, "VOLUNTARY": 48, "CORPORATE": 72}

TRAILING_WINDOW_SECONDS = 24 * 3600
DAY_SECONDS = 86400

_TWO = Decimal("0.01")


def round_half_up(value, places=2):
    """Round half-up exactly, never banker's rounding."""
    quantum = _TWO if places == 2 else Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def round_floor_int(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_FLOOR))


def num(value):
    """Render a computed Decimal value as a JSON number with 2 dp."""
    return float(round_half_up(value, 2))


# --- convenience fee ---------------------------------------------------------
def convenience_fee_cents(principal_cents):
    """Marginal tier walk; bands 2 and 3 proportional, band 1 flat.

    Rounding is applied exactly once, at the end of the walk.
    """
    if principal_cents <= 0:
        return 0.0
    total = Decimal(FEE_TIER_1_FLAT_CENTS)
    p = Decimal(principal_cents)
    if p > Decimal(2000):
        span = Decimal(10000) - Decimal(2000)
        covered = min(p, Decimal(10000)) - Decimal(2000)
        total += Decimal(FEE_TIER_2_MARGINAL_CENTS) * covered / span
    if p > Decimal(10000):
        total += Decimal(FEE_TIER_3_MARGINAL_CENTS)
    return num(total)


def large_load_surcharge_cents(principal_cents):
    """No large-load surcharge table is declared; the surcharge is always zero."""
    return 0


def posted_total_cents(principal_cents, fee_cents):
    """principal + convenience fee + any large-load surcharge.

    The convenience fee is a 2-decimal-place half-up value (PRD 3.4/ 2.6), so the
    posted total carries the same scale — it is not re-truncated to whole cents.
    """
    total = (
        Decimal(str(principal_cents))
        + Decimal(str(fee_cents))
        + Decimal(large_load_surcharge_cents(principal_cents))
    )
    return num(total)


def retailer_fee_share_cents(fee_cents, fee_split_retailer_pct):
    """Per-transaction rounded retailer share (round-then-sum schedule)."""
    return num(Decimal(fee_cents) * Decimal(str(fee_split_retailer_pct)))


# --- velocity -----------------------------------------------------------------
def velocity_qualifiers(loads, now):
    """TRAILING_24H variant: funded_at strictly after T-24h and at most T."""
    lower = now - _seconds(TRAILING_WINDOW_SECONDS)
    return [
        l
        for l in loads
        if l["load_status"] in ("FUNDED", "SETTLED")
        and l.get("funded_at") is not None
        and l["funded_at"] > lower
        and l["funded_at"] <= now
    ]


def _seconds(count):
    from datetime import timedelta

    return timedelta(seconds=count)


def velocity_trip(loads, now):
    qualifying = velocity_qualifiers(loads, now)
    count = len(qualifying)
    cents = sum(int(l["principal_cents"]) for l in qualifying)
    breached = count >= VELOCITY_TXN_LIMIT or cents >= VELOCITY_AMOUNT_LIMIT_CENTS
    return count, cents, breached


def velocity_alert_predicate(window_load_count, window_load_cents):
    return (
        window_load_count >= VELOCITY_TXN_LIMIT
        or window_load_cents >= VELOCITY_AMOUNT_LIMIT_CENTS
    )


# --- structuring --------------------------------------------------------------
def structuring_qualifiers(loads, now):
    return [
        l
        for l in velocity_qualifiers(loads, now)
        if STRUCTURING_LOWER_CENTS <= int(l["principal_cents"]) <= STRUCTURING_UPPER_CENTS
    ]


def structuring_trip(loads, now):
    below = structuring_qualifiers(loads, now)
    count = len(below)
    total = sum(int(l["principal_cents"]) for l in below)
    is_structuring = count >= STRUCTURING_TXN_COUNT and total >= STRUCTURING_MIN_TOTAL_CENTS
    return count, total, is_structuring


# --- posture ------------------------------------------------------------------
def lambda_for(is_oversight_overdue, has_overdue_prior_review):
    if is_oversight_overdue or has_overdue_prior_review:
        return POSTURE_LAMBDA_OVERDUE
    return POSTURE_LAMBDA_BASE


def posture_score(breach_count, lam):
    """100 * (1 - (1 - lambda) ** n), clamped then rounded half-up to 2 dp."""
    n = max(0, int(breach_count))
    base = Decimal(1) - Decimal(lam)
    raw = Decimal(100) * (Decimal(1) - (base ** n))
    if raw < Decimal(0):
        raw = Decimal(0)
    if raw > Decimal(100):
        raw = Decimal(100)
    return num(raw)


# --- provisional credit -------------------------------------------------------
def _capped(claimed, cap):
    return int(min(int(claimed), int(cap)))


def provisional_at_creation(agreement_type, claimed_amount_cents, error_resolution_eligible):
    """Value of provisional_credit_cents when the case opens."""
    if agreement_type == "REG_E":
        amount = _capped(claimed_amount_cents, PROVISIONAL_CAP_REG_E)
        if error_resolution_eligible:
            amount = max(amount, REG_E_ERROR_RESOLUTION_FLOOR_CENTS)
        return amount
    # VOLUNTARY and CORPORATE grant nothing at OPEN.
    return 0


def provisional_at_program_review(agreement_type, claimed_amount_cents, error_resolution_eligible):
    if agreement_type == "REG_E":
        amount = _capped(claimed_amount_cents, PROVISIONAL_CAP_REG_E)
        if error_resolution_eligible:
            amount = max(amount, REG_E_ERROR_RESOLUTION_FLOOR_CENTS)
        return amount
    if agreement_type == "VOLUNTARY":
        return _capped(claimed_amount_cents, PROVISIONAL_CAP_VOLUNTARY)
    # CORPORATE: no credit until RESOLVED_CARDHOLDER.
    return 0


def provisional_at_resolution(agreement_type, claimed_amount_cents, error_resolution_eligible,
                              favour_cardholder):
    if not favour_cardholder:
        return 0
    if agreement_type == "REG_E":
        amount = _capped(claimed_amount_cents, PROVISIONAL_CAP_REG_E)
        if error_resolution_eligible:
            amount = max(amount, REG_E_ERROR_RESOLUTION_FLOOR_CENTS)
        return amount
    if agreement_type == "VOLUNTARY":
        return _capped(claimed_amount_cents, PROVISIONAL_CAP_VOLUNTARY)
    return _capped(claimed_amount_cents, PROVISIONAL_CAP_CORPORATE)


# --- loss allocation ----------------------------------------------------------
def loss_split(total_loss_cents, per_transaction_limit_cents, program_type):
    """Retailer cap first, then the bank percentage of the remainder, then the
    program absorbs the floor remainder."""
    retailer_cap = min(int(total_loss_cents), int(per_transaction_limit_cents))
    retailer_share = min(int(total_loss_cents), retailer_cap)
    remaining = int(total_loss_cents) - retailer_share
    bank_pct = BANK_BEAR_PCT_BAAS if program_type == "BAAS_PROGRAM_MANAGER" else BANK_BEAR_PCT_OWN
    bank_share = round_floor_int(Decimal(remaining) * bank_pct)
    program_share = remaining - bank_share
    return retailer_share, program_share, bank_share


# --- settlement ---------------------------------------------------------------
def batch_amounts(fee_cents_list, principal_cents_list, fee_split_retailer_pct):
    """Pinned rounding order: per-load round-then-sum accrual against a
    sum-then-round payable."""
    per_load = [
        Decimal(str(retailer_fee_share_cents(fee, fee_split_retailer_pct)))
        for fee in fee_cents_list
    ]
    accrued = sum(per_load, Decimal(0))
    aggregate = sum(Decimal(str(f)) for f in fee_cents_list)
    payable = round_half_up(aggregate * Decimal(str(fee_split_retailer_pct)), 2)
    gross = sum(int(p) for p in principal_cents_list)
    return {
        "gross_principal_cents": gross,
        "accrued_retailer_share_cents": num(accrued),
        "net_fee_payable_cents": num(payable),
        "settlement_rounding_delta_cents": num(accrued - payable),
    }


def float_retained_cents(batch_loads, float_position_cents):
    """Float retained by the program through this batch: the posted totals the
    batch's loads contributed to the agreement's float position, capped at the
    position actually held so a clawback can never drive it negative."""
    contributed = sum(
        (Decimal(str(l["posted_total_cents"])) for l in batch_loads), Decimal(0)
    )
    position = Decimal(str(float_position_cents))
    return num(min(contributed, position))


# --- funding credit -----------------------------------------------------------
def funding_status_of(ledger_posted_cents, balance_cents):
    if ledger_posted_cents == 0:
        return "UNFUNDED"
    if balance_cents == 0:
        return "DRAINED"
    return "FUNDED"


def balance_of(ledger_posted_cents, ledger_reversed_cents):
    return max(0, int(ledger_posted_cents) - int(ledger_reversed_cents))


# --- dispute windows ----------------------------------------------------------
def response_window_hours(agreement_type):
    return RESPONSE_WINDOW_HOURS.get(agreement_type, 24)


# --- oversight ----------------------------------------------------------------
def overdue_days(clock, oversight_review_due_at):
    if oversight_review_due_at is None:
        return 0
    delta = (clock - oversight_review_due_at).total_seconds()
    if delta <= 0:
        return 0
    return int(delta // DAY_SECONDS)