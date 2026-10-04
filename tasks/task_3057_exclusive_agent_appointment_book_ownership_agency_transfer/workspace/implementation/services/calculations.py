"""Pure calculation rules (SCAFFOLD §1.3).

Each function is a direct transcription of one calculation rule.  Money is
Decimal end to end and every rounding site is round-half-up, as pinned by
PRD §2.7.
"""

from decimal import Decimal

import clock
import db
import money
from money import dec, round_cents, round_int

# --- pinned constants (SCAFFOLD §1.3) ---------------------------------------
W_ODDS = Decimal("0.40")
W_ASSESSMENT = Decimal("0.30")
W_MARKET_NEED = Decimal("0.30")

FLOOR_SCORE = 40
HIGH_STRICT = 70
MID_INCLUSIVE = 60
PREMIUM_THRESHOLD = 80

MARKET_NEED_FLAG = 40
AGENCY_UNIT_CAP = 12

EXPOSURE_RATE = Decimal("0.04")
EXPOSURE_CAP_CENTS = Decimal("250000")
POOL_CAP_CENTS = Decimal("400000")

UNIT_ALLOWANCE_CENTS = Decimal("1.00")
STAFFING_CAP_CENTS = Decimal("500.00")

PER_STAFF_CENTS = Decimal("10.00")
MIN_MONTHS = 12
CONTRACT_VALUE_MULTIPLE = Decimal("1.5")
ASEASONED_MULTIPLE = Decimal("2.0")
SEASONING_YEARS = 5

PREMIUM_BASE_RATE = Decimal("0.12")
LOSS_FLAG_THRESHOLD = Decimal("70")

VALUATION_BASE_CENTS = Decimal("1000000")
VALUATION_MULTIPLE = Decimal("1.5")
VALUATION_FLOOR_CENTS = Decimal("2000000")

BASE_RATE = Decimal("0.10")
TRANSFER_COMMISSION_RATE = Decimal("0.10")
PAYOUT_RATE = Decimal("0.90")
EARLY_WRITE_MONTHS = 24

SPLIT_BASE_CENTS = Decimal("120000.00")
HOUSE_SHARE = Decimal("0.50")
SUBPRODUCER_SHARE = Decimal("0.20")

PAID_CLAIM_CAP_CENTS = Decimal("10000000.00")
PAID_PREMIUM_RATE = Decimal("0.80")

RETENTION_TARGET_PCT = Decimal("85")


# --- application scoring ----------------------------------------------------

def appointment_priority(app):
    """0.4*odds + 0.3*assessment + 0.3*market_need, rounded half up to an int."""
    raw = (W_ODDS * dec(app["market_odds_score"])
           + W_ASSESSMENT * dec(app["candidate_assessment_score"])
           + W_MARKET_NEED * dec(app["market_need_score"]))
    return round_int(raw)


def required_action(app):
    """Ordered chain; first match wins (PRD §3.1)."""
    odds = app["market_odds_score"]
    assessment = app["candidate_assessment_score"]
    if odds < FLOOR_SCORE or assessment < FLOOR_SCORE:
        return "REJECT"
    if odds > HIGH_STRICT and assessment > HIGH_STRICT:
        return "PROCEED"
    if (MID_INCLUSIVE <= odds <= HIGH_STRICT) or (MID_INCLUSIVE <= assessment <= HIGH_STRICT):
        return "MARKET_ANALYSIS_REQUIRED"
    return "REJECT"


def application_value_tier(priority):
    return "PREMIUM" if priority >= PREMIUM_THRESHOLD else "STANDARD"


# --- book aggregates --------------------------------------------------------

def agency_policies(agency_id, status=None):
    rows = [p for p in db.policy_rows().values() if p["owner_agency_id"] == agency_id]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    rows.sort(key=lambda p: (p["first_written_at"], p["policy_number"]))
    return rows


def open_policies(agency_id):
    return agency_policies(agency_id, "OPEN")


def book_open_count(agency_id):
    return len(open_policies(agency_id))


def exposure_inforce_cents(agency_id):
    total = Decimal(0)
    for p in open_policies(agency_id):
        total += dec(p["annual_premium_cents"])
    return round_cents(total)


def agency_level_units(agency_id):
    return len([a for a in db.agreement_rows().values()
                if a["agency_id"] == agency_id and a["status"] == "ACTIVE"])


def agency_paid_claims_cents(agency_id):
    """Sum of policy_paid_cents over claims on the agency's policies (gross-paid)."""
    policy_ids = {p["id"] for p in agency_policies(agency_id)}
    total = Decimal(0)
    for c in db.claim_rows().values():
        if c["policy_id"] in policy_ids:
            total += dec(c["policy_paid_cents"])
    total = round_cents(total)
    if total > PAID_CLAIM_CAP_CENTS:
        total = PAID_CLAIM_CAP_CENTS
    return total


def policy_paid_claims_cents(policy_id):
    total = Decimal(0)
    for c in db.claim_rows().values():
        if c["policy_id"] == policy_id:
            total += dec(c["policy_paid_cents"])
    return round_cents(total)


def loss_ratio(agency_id):
    exposure = exposure_inforce_cents(agency_id)
    paid = agency_paid_claims_cents(agency_id)
    if exposure <= 0:
        return 0
    return money.pct(paid / (exposure * PREMIUM_BASE_RATE) * 100)


def performance_status(loss_ratio_value, growth_pct):
    """Strictly ordered IF/ELIF: loss first, then growth (PRD §3.6)."""
    if dec(loss_ratio_value) > LOSS_FLAG_THRESHOLD:
        return "AT_RISK"
    if dec(growth_pct) < 0:
        return "BEHIND"
    return "ON_TRACK"


def growth_new_pct(annualized_commission_cents, rolling_base_cents):
    base = dec(rolling_base_cents)
    if base == 0:
        return 0
    return money.pct((dec(annualized_commission_cents) - base) / base * 100)


def agency_valuation_cents(annualized_commission_cents, paid_claims_cents,
                           flagged=False):
    multiple = Decimal("1.0") if flagged else VALUATION_MULTIPLE
    value = (VALUATION_BASE_CENTS
             + dec(annualized_commission_cents) * multiple
             - dec(paid_claims_cents))
    if value < VALUATION_FLOOR_CENTS:
        value = VALUATION_FLOOR_CENTS
    return round_cents(value)


# --- commission lines -------------------------------------------------------

def _schedule_rate(schedule, product_line, business_key):
    line = (schedule or {}).get(product_line)
    if isinstance(line, dict):
        return line.get(business_key)
    return None


def schedule_complete(schedule):
    """A schedule covers all three lines with a non-null {new, renewal} pair."""
    if not isinstance(schedule, dict):
        return False
    for line in ("AUTO", "HOME", "LIFE"):
        entry = schedule.get(line)
        if not isinstance(entry, dict):
            return False
        if entry.get("new") is None or entry.get("renewal") is None:
            return False
    return True


def direct_additions_commission_cents(agency_id, schedule):
    """Per-policy rounded line commission, then summed (PRD §3.3)."""
    total = Decimal(0)
    for p in agency_policies(agency_id, "OPEN"):
        if not p["is_new_business"]:
            continue
        rate = _schedule_rate(schedule, p["product_line"], "new")
        if rate is None:
            continue
        total += round_cents(dec(p["annual_premium_cents"]) * dec(rate))
    return round_cents(total)


def renewal_commission_cents(agency_id, schedule):
    total = Decimal(0)
    for p in agency_policies(agency_id, "OPEN"):
        if p["is_new_business"]:
            continue
        rate = _schedule_rate(schedule, p["product_line"], "renewal")
        if rate is None:
            continue
        total += round_cents(dec(p["annual_premium_cents"]) * dec(rate))
    return round_cents(total)


def direct_additions_revenue_cents(agency_id, schedule):
    total = Decimal(0)
    for p in agency_policies(agency_id, "OPEN"):
        if not p["is_new_business"]:
            continue
        rate = _schedule_rate(schedule, p["product_line"], "new")
        if rate is None:
            continue
        total += round_cents(dec(p["annual_premium_cents"]) * dec(rate))
    return round_cents(total)


# --- allowance ledger -------------------------------------------------------

def marketing_allowance_pool_cents(agency_id, carryover_cents):
    """pool = min(min(exposure*0.04, 250000) + carryover, 400000)."""
    base = round_cents(exposure_inforce_cents(agency_id) * EXPOSURE_RATE)
    if base > EXPOSURE_CAP_CENTS:
        base = EXPOSURE_CAP_CENTS
    pool = base + dec(carryover_cents)
    if pool > POOL_CAP_CENTS:
        pool = POOL_CAP_CENTS
    return round_cents(pool)


def marketing_allowance_spent_cents(agency_id):
    total = Decimal(0)
    for c in db.campaign_rows().values():
        if c["agency_id"] == agency_id and c["status"] == "PARTICIPATED":
            total += dec(c["marketing_allowance_cents"])
    return round_cents(total)


def allowance_carryover_cents(agency_id, carryover_cents):
    pool = marketing_allowance_pool_cents(agency_id, carryover_cents)
    spent = marketing_allowance_spent_cents(agency_id)
    return round_cents(pool - spent)


# --- staffing ---------------------------------------------------------------

def staffing_reimbursement_cents(agency_id):
    """Sum of active members' units at 1.00 cent each, then capped once (PRD §3.5)."""
    total = Decimal(0)
    for m in db.staff_rows().values():
        if m["agency_id"] == agency_id and m["status"] == "ACTIVE":
            total += round_cents(dec(m["allocation_units"]) * UNIT_ALLOWANCE_CENTS)
    if total > STAFFING_CAP_CENTS:
        total = STAFFING_CAP_CENTS
    return round_cents(total)


# --- cessation --------------------------------------------------------------

def cessation_bonus_cents(agency_id, agreement_created_at, current_utc):
    """Ten cents per active staff member once the agreement is a year old."""
    age_limit = clock.add_months(clock.parse_iso(agreement_created_at), MIN_MONTHS)
    if current_utc < age_limit:
        return round_cents(0)
    active = len([m for m in db.staff_rows().values()
                  if m["agency_id"] == agency_id and m["status"] == "ACTIVE"])
    return round_cents(PER_STAFF_CENTS * active)


def contract_value_cents(agency, appointment_iso, bonus_cents, current_utc):
    """max((annualized * multiple) + bonus - paid_claims, 0).

    The multiple is 1.5 for a seasoned book and 2.0 below five years; age is
    counted from appointment_date to the current logical instant (PRD §3.7).
    A book with no appointment date has not aged, so it takes the 2.0 multiple.
    """
    multiple = CONTRACT_VALUE_MULTIPLE
    if appointment_iso:
        appointment = clock.parse_iso(appointment_iso)
        if clock.add_months(appointment, SEASONING_YEARS * 12) > current_utc:
            multiple = ASEASONED_MULTIPLE
    else:
        multiple = ASEASONED_MULTIPLE
    payable = round_cents(dec(agency["annualized_commission_cents"]) * multiple)
    value = payable + dec(bonus_cents) - agency_paid_claims_cents(agency["id"])
    if value < 0:
        value = 0
    return round_cents(value)


# --- book transfer ----------------------------------------------------------

def retention_pct(retained, transferred):
    if transferred <= 0:
        return 0
    return money.pct(dec(retained) / dec(transferred) * 100)


def retention_met(pct_value):
    return dec(pct_value) >= RETENTION_TARGET_PCT


def transfer_base_cents(policies, current_utc, for_cause=False):
    """Sum of annual_premium * 0.10 over the transferred policies.

    When the prior agent terminated for cause, a policy written less than 24
    months before the current instant contributes nothing (PRD §3.7).
    """
    total = Decimal(0)
    for p in policies:
        if for_cause:
            written = clock.parse_iso(p["first_written_at"])
            if clock.add_months(written, EARLY_WRITE_MONTHS) > current_utc:
                continue
        total += dec(p["annual_premium_cents"]) * BASE_RATE
    return total


def book_transfer_settlement_cents(policies, current_utc, for_cause=False):
    base = transfer_base_cents(policies, current_utc, for_cause)
    commission = base * TRANSFER_COMMISSION_RATE
    return round_cents(commission * PAYOUT_RATE)


# --- successor selection ----------------------------------------------------

def successor_candidates(ceasing_agent, agency_rows):
    """ACTIVE agents in the ceasing agency's region, excluding the ceasing agent."""
    ceasing_agency = agency_rows.get(ceasing_agent.get("agency_id"))
    region = ceasing_agency["region_code"] if ceasing_agency else None
    candidates = []
    for agent in db.agent_rows().values():
        if agent["status"] != "ACTIVE":
            continue
        if agent["id"] == ceasing_agent["id"]:
            continue
        agency = agency_rows.get(agent.get("agency_id"))
        if agency is None:
            continue
        if agency["region_code"] != region:
            continue
        candidates.append(agent)
    # rank: agency_level_units DESC, created_at ASC; id is never a tie-break.
    def rank(agent):
        units = agency_level_units(agent["agency_id"])
        return (-units, agent["created_at"])
    candidates.sort(key=rank)
    return candidates


# --- commission split invariant --------------------------------------------

def commission_split():
    house_half = round_cents(SPLIT_BASE_CENTS * HOUSE_SHARE)
    released = round_cents(house_half * SUBPRODUCER_SHARE)
    remaining = round_cents(house_half - released)
    return released, remaining, house_half


def released_commission_cents():
    """The policy's pinned released ledger, standing at 20% of the house half."""
    released, _remaining, _half = commission_split()
    return released


def claim_paid_cents(claim_amount_cents, policy_annual_premium_cents):
    """min(reserve, 80% of annual premium), rounded half up (PRD §3.8)."""
    reserve = dec(claim_amount_cents)
    ceiling = round_cents(dec(policy_annual_premium_cents) * PAID_PREMIUM_RATE)
    return round_cents(reserve if reserve < ceiling else ceiling)