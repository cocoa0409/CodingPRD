"""The ten calculation rules of SCAFFOLD.yaml section 1.3 / PRD section 3."""
import math
from decimal import Decimal

from core import D, rhu, rhu_int, now, days_between

# --- registration_price_resolution -----------------------------------------
LOYALTY_DISCOUNT_PCT = {
    "NEW": D("0.00"),
    "RETURNING": D("0.05"),
    "LOYAL": D("0.10"),
    "CHAMPION": D("0.15"),
}
FEE_TIER_BREAKPOINTS_CENTS = [0, 25000, 75000]
FEE_TIER_PCT = [D("0.06"), D("0.04"), D("0.025")]
FEE_MIN_CENTS = 500
FEE_MAX_CENTS = 4000

# --- offering_net_program_revenue ------------------------------------------
INSTITUTIONAL_OVERHEAD_RATE = D("0.185")
PLATFORM_FEE_PER_REG_CENTS = 250

# --- refund_amount ----------------------------------------------------------
POLICY_TIER_DAYS = [14, 7, 1]
POLICY_TIER_PCT = [D("1.00"), D("0.75"), D("0.50"), D("0.00")]
PRO_RATA_MAX_REFUND_PCT = D("0.90")

# --- instructor pay ---------------------------------------------------------
CREDENTIAL_MULTIPLIER = {
    "ADJUNCT": D("1.00"),
    "SENIOR": D("1.15"),
    "MASTER": D("1.30"),
}
KILL_FEE_PCT = D("0.25")

# --- ceu award --------------------------------------------------------------
MIN_ATTENDANCE_RATIO = D("0.80")

# --- learner loyalty --------------------------------------------------------
LOYALTY_THRESHOLDS = {"RETURNING": 1, "LOYAL": 4, "CHAMPION": 8}

# --- cpl credit conversion --------------------------------------------------
CEU_TO_CREDIT_DIVISOR = D("3.0")
CPL_MAX_PCT_OF_COURSE = D("0.75")
CPL_ROUND_STEP = D("0.5")
RECENCY_DECAY_YEARS = 5
RECENCY_DECAY_FACTOR = D("0.5")
MAX_CPL_REVISION_ROUNDS = 2

# --- misc constants ---------------------------------------------------------
TRANSFER_FEE_CENTS = 2500
WAITLIST_CAP = 5
MAX_CONCURRENT_CEU = D("4.0")


def registration_price_resolution(offering, learner):
    """Eight-step pinned pricing resolution. Returns a dict of the four
    computed money fields."""
    list_tuition_cents = int(offering["tuition_cents"])
    tier = learner["loyalty_tier"]
    pct = LOYALTY_DISCOUNT_PCT.get(tier, D("0.00"))
    loyalty_discount_cents = rhu_int(D(list_tuition_cents) * pct)
    subtotal_cents = list_tuition_cents - loyalty_discount_cents

    index = 0
    for j, breakpoint_cents in enumerate(FEE_TIER_BREAKPOINTS_CENTS):
        if subtotal_cents >= breakpoint_cents:
            index = j
    fee_pct = FEE_TIER_PCT[index]

    raw_fee_cents = rhu_int(D(subtotal_cents) * fee_pct)
    processing_fee_cents = min(FEE_MAX_CENTS, max(FEE_MIN_CENTS, raw_fee_cents))
    total_due_cents = subtotal_cents + processing_fee_cents
    return {
        "list_tuition_cents": list_tuition_cents,
        "loyalty_discount_cents": loyalty_discount_cents,
        "processing_fee_cents": processing_fee_cents,
        "total_due_cents": total_due_cents,
    }


REVENUE_PAYMENT_STATES = ("PAID", "PARTIALLY_REFUNDED")
REVENUE_ENROLLMENT_STATES = ("ENROLLED", "COMPLETED", "NO_SHOW")


def offering_net_program_revenue(offering, registrations):
    """Per-line rounding, then an integer sum. Never round the total."""
    lines = [r for r in registrations
             if r["offering_id"] == offering["id"]
             and r["payment_status"] in REVENUE_PAYMENT_STATES
             and r["enrollment_status"] in REVENUE_ENROLLMENT_STATES]
    lines = sorted(lines, key=lambda r: (r["created_at"], r["_seq"]))
    total = 0
    for line in lines:
        gross_cents = int(line["amount_paid_cents"]) - int(line["amount_refunded_cents"])
        overhead_cents = rhu_int(D(gross_cents) * INSTITUTIONAL_OVERHEAD_RATE)
        total += gross_cents - overhead_cents - PLATFORM_FEE_PER_REG_CENTS
    return total


def policy_tier_pct(days_before_start):
    if days_before_start >= POLICY_TIER_DAYS[0]:
        return POLICY_TIER_PCT[0]
    if days_before_start >= POLICY_TIER_DAYS[1]:
        return POLICY_TIER_PCT[1]
    if days_before_start >= POLICY_TIER_DAYS[2]:
        return POLICY_TIER_PCT[2]
    return POLICY_TIER_PCT[3]


def refund_amount(registration, offering, refund_basis, clock_now=None):
    clock_now = clock_now or now()
    subtotal_paid_cents = (int(registration["amount_paid_cents"])
                           - int(registration["processing_fee_cents"]))
    if refund_basis == "PRO_RATA_ATTENDANCE":
        total_sessions = int(registration["total_sessions"])
        attended = int(registration["sessions_attended"])
        if total_sessions <= 0:
            unused_ratio = D(0)
        else:
            unused_ratio = D(total_sessions - attended) / D(total_sessions)
        effective_pct = min(unused_ratio, PRO_RATA_MAX_REFUND_PCT)
    else:
        dbs = days_between(offering["start_date"], clock_now)
        effective_pct = policy_tier_pct(dbs)
    return rhu_int(D(subtotal_paid_cents) * effective_pct)


def instructor_contract_pay(contract, instructor):
    if contract["pay_basis"] == "FINAL_COMPLETION":
        headcount = contract.get("final_headcount")
    else:
        headcount = contract.get("census_headcount")
    headcount = 0 if headcount is None else int(headcount)
    capped = min(headcount, int(contract["enrollment_cap_for_pay"]))
    if capped < 0:
        capped = 0
    variable = capped * int(contract["per_enrollment_cents"])
    raw_cents = int(contract["base_stipend_cents"]) + variable
    multiplier = CREDENTIAL_MULTIPLIER[instructor["credential_level"]]
    return rhu_int(D(raw_cents) * multiplier)


def instructor_kill_fee(contract, instructor):
    multiplier = CREDENTIAL_MULTIPLIER[instructor["credential_level"]]
    return rhu_int(D(int(contract["base_stipend_cents"])) * KILL_FEE_PCT * multiplier)


def attendance_ratio(registration):
    total_sessions = int(registration["total_sessions"])
    attended = int(registration["sessions_attended"])
    if total_sessions <= 0:
        return D(0)
    return rhu(D(attended) / D(total_sessions), 4)


def ceu_award(course):
    return rhu(course["ceu_units"], 1)


def learner_loyalty_and_ceu(learner, completion_records):
    issued = [cr for cr in completion_records
              if cr["learner_id"] == learner["id"] and cr["status"] == "ISSUED"]
    count = len(issued)
    total = D(0)
    for record in issued:
        total += D(record["ceu_awarded"])
    lifetime_ceu_total = rhu(total, 1)
    if count >= LOYALTY_THRESHOLDS["CHAMPION"]:
        tier = "CHAMPION"
    elif count >= LOYALTY_THRESHOLDS["LOYAL"]:
        tier = "LOYAL"
    elif count >= LOYALTY_THRESHOLDS["RETURNING"]:
        tier = "RETURNING"
    else:
        tier = "NEW"
    return count, lifetime_ceu_total, tier


def cpl_credit_conversion(petition, citations, completion_records, target_course,
                          clock_now=None):
    """Returns (claimed_ceu_total, awarded_credit_units) as Decimals."""
    clock_now = clock_now or now()
    rows = sorted(citations, key=lambda c: (c["created_at"], c["_seq"]))
    accumulated = D(0)
    for citation in rows:
        record = completion_records.get(citation["completion_record_id"])
        if record is None:
            continue
        age_years = int(math.floor(
            (clock_now - record["issued_at"]).total_seconds() / (365 * 86400.0)))
        factor = RECENCY_DECAY_FACTOR if age_years >= RECENCY_DECAY_YEARS else D("1.0")
        contribution = rhu(D(record["ceu_awarded"]) * D(citation["weight"]) * factor, 2)
        accumulated += contribution
    claimed_ceu_total = rhu(accumulated, 2)
    raw_credits = claimed_ceu_total / CEU_TO_CREDIT_DIVISOR
    ceiling_credits = D(target_course["cpl_credit_units"]) * CPL_MAX_PCT_OF_COURSE
    capped_credits = min(raw_credits, ceiling_credits)
    steps = int(math.floor(capped_credits / CPL_ROUND_STEP))
    awarded_credit_units = D(steps) * CPL_ROUND_STEP
    if awarded_credit_units < 0:
        awarded_credit_units = D(0) * CPL_ROUND_STEP
    return claimed_ceu_total, awarded_credit_units
