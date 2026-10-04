"""Domain services: computed counters, calculations, issuance, cascades."""
import calendar
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
import clock
import errors as E
from util import parse_iso, add_months

# ---------------------------------------------------------------------------
# Computed counters (read-time, per scaffold §1.1)
# ---------------------------------------------------------------------------

ENROLLED_STATUSES = {"APPLIED", "ISSUED", "ACTIVE", "LAPSED", "PORTED"}

# For the group's `enrolled_count` counter, ported policies drop out: a ported
# policy leaves the group and must never be billed by the group's payroll
# cycles. The participation gate at campaign close uses the same counter.
ENROLLED_COUNT_STATUSES = ENROLLED_STATUSES - {"PORTED"}


def eligible_employee_count(group_id):
    return sum(
        1 for e in db.STORES["employees"].values()
        if e["employer_group_id"] == group_id and e["status"] == "ACTIVE"
    )


def enrolled_count(group_id):
    campaign_ids = {
        c["id"] for c in db.STORES["enrollment_campaigns"].values()
        if c["employer_group_id"] == group_id
    }
    return sum(
        1 for p in db.STORES["policies"].values()
        if p["campaign_id"] in campaign_ids and p["status"] in ENROLLED_COUNT_STATUSES
    )


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def find_benefit_item(schedule, event_code):
    for item in schedule["benefit_items"]:
        if item["event_code"] == event_code:
            return item
    return None


def claim_payable(policy, schedule, event_code, claimed_occurrences, service_year):
    """claim_payable calculation. Returns (occurrences_credited, payable_cents).
    Integer arithmetic only; no rounding."""
    item = find_benefit_item(schedule, event_code)
    if item is None:
        return 0, 0
    paid_this_year = (
        policy.get("paid_occurrences_by_year", {})
        .get(str(service_year), {})
        .get(event_code, 0)
    )
    remaining_occurrences = max(0, item["max_occurrences_per_year"] - paid_this_year)
    remaining_lifetime = max(0, item["lifetime_max_cents"] - policy.get("lifetime_paid_cents", 0))
    occurrences_credited = min(claimed_occurrences, remaining_occurrences)
    uncapped = item["benefit_amount_cents"] * occurrences_credited
    payable = min(uncapped, remaining_lifetime)
    return occurrences_credited, payable


def required_enrollments(group):
    import math
    pct = Decimal(str(group.get("participation_minimum_pct", 0.10)))
    eligible = eligible_employee_count(group["id"])
    by_pct = int((pct * eligible).to_integral_value(rounding="ROUND_CEILING"))
    return max(group.get("participation_minimum_count", 3), by_pct)


def proration_amount(convention, monthly_premium_cents, coverage_days, days_in_period):
    """deduction_proration calculation; line-level round_half_up to whole cents."""
    if coverage_days <= 0 or days_in_period <= 0:
        return 0
    premium = Decimal(int(monthly_premium_cents))
    if convention == "HALF_MONTH":
        half = (premium / Decimal(2)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        if coverage_days == days_in_period:
            return int(half * 2)
        return int(half)
    # DAILY: product-then-divide, rounded half-up as one step
    value = premium * Decimal(int(coverage_days)) / Decimal(int(days_in_period))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Policy issuance
# ---------------------------------------------------------------------------

def mint_certificate_number(series):
    seq = db.CERT_SEQ.get(series["id"], 0) + 1
    db.CERT_SEQ[series["id"]] = seq
    return f"{series['series_code']}-{seq:08d}"


def issue_policy(policy):
    """APPLIED -> ISSUED with full pinning. Caller has validated state.
    Returns None on success, or ('DECLINED', reason) if the policy must be
    declined instead (pre-existing screen), or raises ApiError for hard fails."""
    series = db.STORES["policy_series"][policy["policy_series_id"]]
    employee = db.STORES["employees"][policy["employee_id"]]
    campaign = db.STORES["enrollment_campaigns"][policy["campaign_id"]]

    if series["status"] == "RETIRED":
        raise E.err(E.ERR_SERIES_RETIRED, "Policy series is RETIRED")
    current_id = series.get("current_schedule_id")
    if not current_id or db.STORES["benefit_schedules"].get(current_id, {}).get("status") != "PUBLISHED":
        raise E.err(E.ERR_SERIES_WITHOUT_SCHEDULE, "Series has no PUBLISHED schedule")

    # pre-existing screen on non-guaranteed-issue business
    if not campaign.get("guaranteed_issue", False) and employee.get("preexisting_diagnosis_codes"):
        return ("DECLINED", "PRE_EXISTING")

    # duplicate coverage
    for other in db.STORES["policies"].values():
        if (
            other["id"] != policy["id"]
            and other["employee_id"] == policy["employee_id"]
            and other["policy_series_id"] == policy["policy_series_id"]
            and other["status"] in ENROLLED_STATUSES
        ):
            raise E.err(E.ERR_DUPLICATE_COVERAGE, "Duplicate coverage for employee+series")

    schedule = db.STORES["benefit_schedules"][current_id]
    now = clock.now()
    policy["benefit_schedule_id"] = current_id
    policy["monthly_premium_cents"] = schedule["monthly_premium_cents"]
    policy["issue_date"] = db.format_ts(now)
    first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    policy["coverage_start_date"] = db.format_ts(first)
    policy["certificate_number"] = mint_certificate_number(series)
    policy["status"] = "ISSUED"
    db.touch(policy)
    return None


def decline_policy(policy):
    policy["status"] = "DECLINED"
    db.touch(policy)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def lapse_policy(policy):
    policy["status"] = "LAPSED"
    # record lapse instant for the 60-day reinstatement window
    policy["_lapsed_at"] = db.format_ts(clock.now())
    db.touch(policy)


def force_close_campaign(campaign):
    """Forced closure used by group termination. LOCKED campaigns decline their
    APPLIED policies (3-hop chain). Other statuses just close."""
    if campaign["status"] == "LOCKED":
        for p in db.STORES["policies"].values():
            if p["campaign_id"] == campaign["id"] and p["status"] == "APPLIED":
                decline_policy(p)
    campaign["status"] = "CLOSED"
    db.touch(campaign)


def group_terminate_cascade(group):
    """Terminate side effects: lapse ISSUED/ACTIVE policies of group employees,
    close DRAFT/LOCKED/MET/FAILED campaigns (LOCKED closure declines APPLIED)."""
    employee_ids = {
        e["id"] for e in db.STORES["employees"].values()
        if e["employer_group_id"] == group["id"]
    }
    for p in db.STORES["policies"].values():
        if p["employee_id"] in employee_ids and p["status"] in ("ISSUED", "ACTIVE"):
            lapse_policy(p)
    for c in db.STORES["enrollment_campaigns"].values():
        if c["employer_group_id"] == group["id"] and c["status"] in ("DRAFT", "LOCKED", "MET", "FAILED"):
            force_close_campaign(c)


def group_suspend_cascade(group):
    for c in db.STORES["enrollment_campaigns"].values():
        if c["employer_group_id"] == group["id"] and c["status"] == "OPEN":
            c["status"] = "LOCKED"
            db.touch(c)


# ---------------------------------------------------------------------------
# Ledger sync (claims)
# ---------------------------------------------------------------------------

def ledger_pay(policy, claim):
    year = str(claim["service_date"][0:4])
    policy["lifetime_paid_cents"] = policy.get("lifetime_paid_cents", 0) + claim["payable_amount_cents"]
    pob = policy.setdefault("paid_occurrences_by_year", {})
    year_map = pob.setdefault(year, {})
    year_map[claim["event_code"]] = year_map.get(claim["event_code"], 0) + claim["adjudicated_occurrences"]
    db.touch(policy)


def ledger_void_paid(policy, claim):
    year = str(claim["service_date"][0:4])
    policy["lifetime_paid_cents"] = policy.get("lifetime_paid_cents", 0) - claim["payable_amount_cents"]
    pob = policy.setdefault("paid_occurrences_by_year", {})
    year_map = pob.setdefault(year, {})
    year_map[claim["event_code"]] = year_map.get(claim["event_code"], 0) - claim["adjudicated_occurrences"]
    db.touch(policy)
