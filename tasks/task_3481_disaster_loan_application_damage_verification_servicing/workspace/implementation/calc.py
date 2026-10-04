"""Calculations (PRD 3): payment formulas, affordability, approved amount, losses.

All money math is exact Decimal; rounding to integer cents is round-half-up and
happens only where the owning calculation pins it.
"""

from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP, getcontext

getcontext().prec = 60

RATE_PERSONAL = Decimal("0.03125")
RATE_BUSINESS = Decimal("0.04")
DEFERRAL_MONTHS = 12
MAX_DTI_PERCENT = 43
MIN_CREDIT_SCORE = 640
INITIAL_DISBURSEMENT_CAP_CENTS = 2500000
ESTIMATION_MAX_CENTS = 2500000
MAX_RECONSIDERATIONS = 2
DISPUTE_WINDOW_DAYS = 30
PHYSICAL_FILING_WINDOW_DAYS = 90
EIDL_FILING_WINDOW_DAYS = 270
EXCESS_FUNDS_DUE_DAYS = 30
ACCOMMODATION_MAX_DAYS = 360
LATE_FEE_GRACE_DAYS = 15
LATE_FEE_PCT = Decimal("0.05")
DELINQUENT_AFTER_DAYS = 30
DEFAULT_AFTER_DAYS = 120
CHARGE_OFF_AFTER_DAYS = 180
DAYS_IN_YEAR = 365
COLLATERAL_THRESHOLD = {"PHYSICAL_DAMAGE": 2500000, "ECONOMIC_INJURY": 5000000}


def rate_and_term(applicant_type, loan_purpose):
    """PRD 2.8: fixed rate/term per applicant type x loan purpose."""
    if loan_purpose == "ECONOMIC_INJURY":
        return RATE_BUSINESS, 360
    if applicant_type == "HOMEOWNER":
        return RATE_PERSONAL, 360
    if applicant_type == "RENTER":
        return RATE_PERSONAL, 84
    return RATE_BUSINESS, 360  # BUSINESS physical


def rate_and_term_for_loan(loan):
    """The loan's stored annual rate as an exact Decimal (term is loan['term_months'])."""
    return Decimal(str(loan["interest_rate"]))


def statutory_cap(applicant_type, loan_purpose):
    if loan_purpose == "ECONOMIC_INJURY":
        return 200000000
    return {"HOMEOWNER": 50000000, "RENTER": 10000000, "BUSINESS": 200000000}[applicant_type]


def monthly_payment_cents(principal_cents, rate, term_months, deferred_capitalized):
    """monthly_payment_calc. STANDARD: amortize L. DEFERRED_CAPITALIZED: capitalize
    simple interest over the deferral window first, then amortize. Rounds half-up
    to integer cents at the final step only."""
    r = rate / Decimal(12)
    L = Decimal(principal_cents)
    if deferred_capitalized:
        L = L * (Decimal(1) + r * DEFERRAL_MONTHS)
    q = (Decimal(1) + r) ** term_months
    payment = L * r * q / (q - Decimal(1))
    return int(payment.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def affordability_cap_cents(annual_income_cents, verified_monthly_debt_cents, rate, term_months):
    """Largest principal whose STANDARD-variant payment keeps
    (debt + P) * 100 <= 43 * floor(annual_income / 12); inverted amortization,
    floored to whole cents."""
    monthly_income = annual_income_cents // 12
    p_max = Decimal(MAX_DTI_PERCENT * monthly_income) / Decimal(100) - Decimal(verified_monthly_debt_cents)
    if p_max <= 0:
        return 0
    r = rate / Decimal(12)
    q = (Decimal(1) + r) ** term_months
    principal = p_max * (q - Decimal(1)) / (r * q)
    return int(principal.to_integral_value(rounding=ROUND_FLOOR))


def verified_loss_cents(assessed_loss_cents, valuation_basis, depreciation_pct):
    """verified_loss_calc. REPLACEMENT_COST: full assessed loss. ACTUAL_CASH_VALUE:
    round_half_up(assessed * (1 - depreciation_pct)) in exact decimal."""
    if valuation_basis == "REPLACEMENT_COST":
        return assessed_loss_cents
    value = Decimal(assessed_loss_cents) * (Decimal(1) - depreciation_pct)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def net_verified_loss_cents(verified_loss, insurance_proceeds_cents):
    return max(0, verified_loss - insurance_proceeds_cents)


def daily_interest_cents(outstanding_cents, rate, days):
    """round_half_up(outstanding * rate * days / 365) — the single accrual rounding
    step shared by payment posting and later-release folding."""
    if days <= 0 or outstanding_cents <= 0:
        return 0
    value = Decimal(outstanding_cents) * rate * Decimal(days) / Decimal(DAYS_IN_YEAR)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def late_fee_cents(monthly_payment):
    """round_half_up(0.05 * monthly_payment_cents)."""
    value = LATE_FEE_PCT * Decimal(monthly_payment)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def approved_amount_cents(app, applicant, latest_pass_review, latest_completed_verif, grants):
    """approved_amount_calc: pinned four-step order."""
    rate, term = rate_and_term(applicant["applicant_type"], app["loan_purpose"])
    cap = statutory_cap(applicant["applicant_type"], app["loan_purpose"])
    parts = [app["requested_amount_cents"], cap]
    if app["loan_purpose"] == "PHYSICAL_DAMAGE":
        net = latest_completed_verif["net_verified_loss_cents"] if latest_completed_verif else 0
        grant_sum = sum(g["award_amount_cents"] for g in grants if g["purpose_category"] == "PHYSICAL_DAMAGE")
        parts.append(max(0, net - grant_sum))
    verified_debt = (latest_pass_review["verified_monthly_debt_cents"]
                     if latest_pass_review else applicant["monthly_debt_cents"])
    parts.append(affordability_cap_cents(applicant["annual_income_cents"], verified_debt, rate, term))
    return min(parts)
