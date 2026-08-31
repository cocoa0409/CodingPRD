"""Calculation rules (scaffold 1.3 / PRD 2.7-2.9, 3.5, 3.7, 3.8, 3.9)."""
import datetime
import math
from decimal import Decimal, ROUND_HALF_UP

import store

# --- constants -------------------------------------------------------------
BASIC_ELECTIVE_DEFERRAL_LIMIT_CENTS = 2450000
AGE_50_CATCHUP_LIMIT_CENTS = 800000
SERVICE_15YR_MIN_YEARS = 15
SERVICE_15YR_ANNUAL_CAP_CENTS = 300000
SERVICE_15YR_LIFETIME_CAP_CENTS = 1500000
SERVICE_15YR_PER_YEAR_FACTOR_CENTS = 500000
NORMAL_RETIREMENT_AGE = 65
FINAL_3YR_MULTIPLIER = 2
ANNUAL_ADDITIONS_LIMIT_415C_CENTS = 7200000

LOAN_ABSOLUTE_CAP_CENTS = 5000000
LOAN_MINIMUM_FLOOR_CENTS = 1000000
LOAN_VESTED_PERCENT_BPS = 5000
LOAN_LOOKBACK_DAYS = 365

SMALL_PLAN_PARTICIPANT_THRESHOLD = 100
SMALL_PLAN_SAFE_HARBOR_BUSINESS_DAYS = 7
LARGE_PLAN_DEADLINE_BUSINESS_DAY = 15

LOST_EARNINGS_ANNUAL_RATE_BPS = 600
DAYS_PER_YEAR = 365
EXCISE_TAX_RATE_BPS = 1500

ISA_DATA_STALENESS_DAYS = 45
ISA_MINIMUM_GAP_DAYS = 1

PART_TIME_HOURS_PER_WEEK_THRESHOLD = 20
PART_TIME_PRIOR_YEAR_HOURS_THRESHOLD = 1000

FEDERAL_HOLIDAYS = {
    datetime.date(2026, 1, 1), datetime.date(2026, 1, 19), datetime.date(2026, 2, 16),
    datetime.date(2026, 5, 25), datetime.date(2026, 6, 19), datetime.date(2026, 7, 3),
    datetime.date(2026, 9, 7), datetime.date(2026, 10, 12), datetime.date(2026, 11, 11),
    datetime.date(2026, 11, 26), datetime.date(2026, 12, 25),
}

ENTITY_TYPES = {"PUBLIC_SCHOOL", "TAX_EXEMPT_501C3", "GOVERNMENTAL_NON_SCHOOL", "CHURCH"}
ORG_SUBTYPES = {"SCHOOL", "HOSPITAL", "HOME_HEALTH_AGENCY", "HEALTH_AND_WELFARE_AGENCY",
                "CHURCH_ORG", "OTHER"}
PLAN_TYPES = {"PLAN_403B", "PLAN_457B"}
PLAN_STATUSES = {"DRAFT", "ACTIVE", "FROZEN", "TERMINATED"}
ISA_STATUSES = {"PENDING", "ACTIVE", "SUSPENDED", "TERMINATED"}
EMPLOYMENT_STATUSES = {"ACTIVE", "TERMINATED"}
DELIVERY_METHODS = {"EMAIL", "PAPER_MAIL", "INTRANET_POSTING", "HAND_DELIVERY"}
ASSERTED_EXCLUSIONS = {"NONE", "STUDENT", "LESS_THAN_20_HOURS", "NONRESIDENT_ALIEN",
                       "NOT_TOP_HAT_GROUP"}
DETERMINATION_STATUSES = {"ELIGIBLE", "EXCLUDED_STUDENT", "EXCLUDED_LESS_THAN_20_HOURS",
                          "EXCLUDED_NONRESIDENT_ALIEN", "EXCLUDED_NOT_TOP_HAT_GROUP",
                          "INELIGIBLE_PLAN_NOT_ACTIVE"}
CATCHUP_ELECTIONS = {"NONE", "AGE_50", "SERVICE_15_YEAR", "FINAL_3_YEAR",
                     "AGE_50_AND_SERVICE_15_YEAR"}
ELECTION_STATES = {"SUBMITTED", "EFFECTIVE", "REJECTED", "SUPERSEDED", "REVOKED"}
DEPOSIT_STATES = {"WITHHELD", "DEPOSITED", "REVERSED"}
COMPLIANCE_STATES = {"UNDETERMINED", "TIMELY", "LATE", "CORRECTION_PENDING", "CORRECTED"}
CORRECTION_STATES = {"OPEN", "SETTLED", "VOIDED"}
REQUEST_TYPES = {"LOAN", "HARDSHIP", "UNFORESEEABLE_EMERGENCY"}
REQUEST_STATES = {"SUBMITTED", "UNDER_REVIEW", "RETURNED_FOR_INFO", "APPROVED", "DENIED",
                  "DISBURSED", "PAID"}
SAFE_HARBOR_REASONS = {"NONE", "MEDICAL_EXPENSES", "PURCHASE_PRINCIPAL_RESIDENCE", "TUITION",
                       "PREVENT_EVICTION", "FUNERAL", "CASUALTY_REPAIR", "DISASTER"}
EMERGENCY_REASONS = {"NONE", "ILLNESS_OF_PARTICIPANT_OR_DEPENDENT", "LOSS_OF_PROPERTY_CASUALTY",
                     "IMMINENT_FORECLOSURE_OR_EVICTION", "FUNERAL_EXPENSES",
                     "EXTRAORDINARY_MEDICAL", "COLLEGE_TUITION", "PURCHASE_OF_HOME"}
REQUEST_KINDS = {"CONTRACT_EXCHANGE", "PLAN_TO_PLAN_TRANSFER"}
MOVEMENT_STATES = {"SUBMITTED", "ACCEPTED_BY_VENDOR", "REJECTED_BY_VENDOR", "APPROVED",
                   "DENIED", "EXECUTED", "REVERSED"}
REGIMES = {"UA_ONLY", "UA_PLUS_410B_401A4", "GOVERNMENTAL_457_ALL_EMPLOYEES", "TOP_HAT_457",
           "CHURCH_EXEMPT"}
UA_REGIMES = {"UA_ONLY", "UA_PLUS_410B_401A4"}


# --- generic numeric helpers ----------------------------------------------
def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_iso_date(value):
    if value is None:
        return None
    return datetime.date.fromisoformat(value)


# --- Employer derivations (PRD 2.8) ---------------------------------------
def is_governmental(entity_type):
    return entity_type in ("PUBLIC_SCHOOL", "GOVERNMENTAL_NON_SCHOOL")


def is_qualified_organization(entity_type, organization_subtype):
    if entity_type in ("PUBLIC_SCHOOL", "CHURCH"):
        return True
    if entity_type == "TAX_EXEMPT_501C3" and organization_subtype in (
            "HOSPITAL", "HOME_HEALTH_AGENCY", "HEALTH_AND_WELFARE_AGENCY"):
        return True
    return False


def nondiscrimination_regime(employer, plan_type):
    if employer["entity_type"] == "CHURCH":
        return "CHURCH_EXEMPT"
    if plan_type == "PLAN_403B":
        return "UA_ONLY" if employer["is_governmental"] else "UA_PLUS_410B_401A4"
    return "GOVERNMENTAL_457_ALL_EMPLOYEES" if employer["is_governmental"] else "TOP_HAT_457"


# --- Notice validity -------------------------------------------------------
def notice_is_valid(notice, plan):
    return bool(notice["describes_effective_opportunity"]
                and notice["recipient_count"] >= plan["reported_participant_count"]
                and notice["delivery_method"] != "INTRANET_POSTING")


# --- ISA staleness (PRD 2.9) ----------------------------------------------
def isa_data_stale(isa):
    d = isa.get("data_current_through_date")
    if not d:
        return True
    return (store.today() - parse_iso_date(d)).days > ISA_DATA_STALENESS_DAYS


def isa_covers(plan_id, vendor_id, data_class=None, require_fresh=False):
    """Return the first ACTIVE agreement for the pair meeting the requirements."""
    for a in store.isas_for(plan_id, vendor_id):
        if a["status"] != "ACTIVE":
            continue
        if data_class and not a.get(data_class, False):
            continue
        if require_fresh and isa_data_stale(a):
            continue
        return a
    return None


# --- Participant derivations ----------------------------------------------
def attained_age_at_year_end(participant):
    dob = parse_iso_date(participant["date_of_birth"])
    return store.today().year - dob.year


# --- Eligibility (PRD 3.3) -------------------------------------------------
EXCLUSION_BASIS = {
    "EXCLUDED_NONRESIDENT_ALIEN":
        "Nonresident alien with no US-source income from the employer "
        "(section 403(b)(12)(A)(ii) permissible exclusion).",
    "EXCLUDED_STUDENT":
        "Student performing services described in section 3121(b)(10).",
    "EXCLUDED_LESS_THAN_20_HOURS":
        "Employee normally scheduled for fewer than 20 hours per week who worked fewer "
        "than 1,000 hours in the prior plan year.",
    "EXCLUDED_NOT_TOP_HAT_GROUP":
        "Participant is outside the select group of management or highly compensated "
        "employees required by a non-governmental 457(b) top-hat plan.",
}


def eligibility_status(plan, participant):
    if plan["status"] not in ("ACTIVE", "FROZEN"):
        return "INELIGIBLE_PLAN_NOT_ACTIVE"
    regime = plan["nondiscrimination_regime"]
    if regime == "TOP_HAT_457":
        return "ELIGIBLE" if participant["is_select_management_or_hce"] else "EXCLUDED_NOT_TOP_HAT_GROUP"
    if regime == "GOVERNMENTAL_457_ALL_EMPLOYEES":
        return "ELIGIBLE"
    if regime == "CHURCH_EXEMPT":
        return "ELIGIBLE"
    # UA_ONLY / UA_PLUS_410B_401A4 -- exclusion ladder, first hit wins.
    if participant["is_nonresident_alien_no_us_income"]:
        return "EXCLUDED_NONRESIDENT_ALIEN"
    if participant["is_student_performing_services"]:
        return "EXCLUDED_STUDENT"
    if (participant["scheduled_hours_per_week"] < PART_TIME_HOURS_PER_WEEK_THRESHOLD
            and participant["prior_year_hours_worked"] < PART_TIME_PRIOR_YEAR_HOURS_THRESHOLD):
        return "EXCLUDED_LESS_THAN_20_HOURS"
    return "ELIGIBLE"


def notice_status_for(plan):
    applies = plan["nondiscrimination_regime"] in UA_REGIMES
    if not applies:
        return "CURRENT", applies
    notices = [n for n in store.notices_of(plan["id"]) if n["plan_year"] == plan["plan_year"]]
    if not notices:
        return "MISSING", applies
    if any(n["is_valid"] for n in notices):
        return "CURRENT", applies
    return "INVALID", applies


ASSERTION_TO_STATUS = {
    "NONE": "ELIGIBLE",
    "STUDENT": "EXCLUDED_STUDENT",
    "LESS_THAN_20_HOURS": "EXCLUDED_LESS_THAN_20_HOURS",
    "NONRESIDENT_ALIEN": "EXCLUDED_NONRESIDENT_ALIEN",
    "NOT_TOP_HAT_GROUP": "EXCLUDED_NOT_TOP_HAT_GROUP",
}


# --- Contribution capacity (PRD 3.5) --------------------------------------
def lifetime_elective_deferrals(participant):
    total = participant.get("prior_employer_elective_deferrals_cents", 0)
    for va in store.accounts_of(participant["id"], status="OPEN"):
        plan = store.plans.get(va["plan_id"])
        if plan and plan["plan_type"] == "PLAN_403B":
            total += va["prior_years_elective_deferrals_cents"] + va["ytd_elective_deferrals_cents"]
    return total


def catchup_capacity_403b(plan, participant, employer, snapshot_used=None, lifetime=None):
    if plan["plan_type"] != "PLAN_403B":
        return {"service_15yr": 0, "age_50": 0}
    if lifetime is None:
        lifetime = lifetime_elective_deferrals(participant)
    if snapshot_used is None:
        snapshot_used = participant["cumulative_special_catchup_used_cents"]
    if employer["is_qualified_organization"] and participant["years_of_service"] >= SERVICE_15YR_MIN_YEARS:
        term_annual = SERVICE_15YR_ANNUAL_CAP_CENTS
        term_lifetime = SERVICE_15YR_LIFETIME_CAP_CENTS - snapshot_used
        term_service = (SERVICE_15YR_PER_YEAR_FACTOR_CENTS
                        * int(math.floor(participant["years_of_service"])) - lifetime)
        service_15yr = max(0, min(term_annual, term_lifetime, term_service))
    else:
        service_15yr = 0
    age_50 = AGE_50_CATCHUP_LIMIT_CENTS if attained_age_at_year_end(participant) >= 50 else 0
    return {"service_15yr": service_15yr, "age_50": age_50}


def catchup_capacity_457b(plan, participant):
    if plan["plan_type"] != "PLAN_457B":
        return {"final_3yr": 0, "age_50": 0, "usable": 0}
    age = attained_age_at_year_end(participant)
    in_window = age in (NORMAL_RETIREMENT_AGE - 3, NORMAL_RETIREMENT_AGE - 2,
                        NORMAL_RETIREMENT_AGE - 1)
    if in_window:
        final_3yr = min(FINAL_3YR_MULTIPLIER * BASIC_ELECTIVE_DEFERRAL_LIMIT_CENTS,
                        BASIC_ELECTIVE_DEFERRAL_LIMIT_CENTS
                        + participant["underutilized_prior_limit_cents"]) \
                    - BASIC_ELECTIVE_DEFERRAL_LIMIT_CENTS
    else:
        final_3yr = 0
    age_50 = AGE_50_CATCHUP_LIMIT_CENTS if (age >= 50 and plan["is_governmental_457"]) else 0
    return {"final_3yr": final_3yr, "age_50": age_50, "usable": max(final_3yr, age_50)}


def bucket_accounts(participant_id, plan_type):
    """accounts_all for deferral_limit_aggregate_402g."""
    out = []
    for va in store.accounts_of(participant_id, status="OPEN"):
        plan = store.plans.get(va["plan_id"])
        if not plan or plan["plan_type"] != plan_type:
            continue
        if plan["status"] not in ("ACTIVE", "FROZEN"):
            continue
        out.append(va)
    return out


def verified_accounts(accounts):
    out = []
    for va in accounts:
        if isa_covers(va["plan_id"], va["vendor_id"], "shares_contribution_data",
                      require_fresh=True):
            out.append(va)
    return out


def deferral_limit_aggregate_402g(plan, participant, employer, snapshot_used=None):
    bucket = plan["plan_type"]
    accounts_all = bucket_accounts(participant["id"], bucket)
    accounts_ver = verified_accounts(accounts_all)
    ytd_gross = sum(va["ytd_elective_deferrals_cents"] for va in accounts_all)
    ytd_verified = sum(va["ytd_elective_deferrals_cents"] for va in accounts_ver)
    if bucket == "PLAN_403B":
        caps = catchup_capacity_403b(plan, participant, employer, snapshot_used=snapshot_used)
        service_15yr = caps["service_15yr"]
        age_50 = caps["age_50"]
        final_3yr = 0
        catchup_capacity = service_15yr + age_50
    else:
        caps = catchup_capacity_457b(plan, participant)
        service_15yr = 0
        age_50 = caps["age_50"]
        final_3yr = caps["final_3yr"]
        catchup_capacity = caps["usable"]
    total_limit = BASIC_ELECTIVE_DEFERRAL_LIMIT_CENTS + catchup_capacity
    return {
        "bucket": bucket,
        "accounts_all": accounts_all,
        "accounts_verified": accounts_ver,
        "ytd_gross": ytd_gross,
        "ytd_verified": ytd_verified,
        "service_15yr": service_15yr,
        "age_50": age_50,
        "final_3yr": final_3yr,
        "usable_catchup": catchup_capacity,
        "total_limit": total_limit,
        "room_gross": max(0, total_limit - ytd_gross),
        "room_verified": max(0, total_limit - ytd_verified),
    }


def annual_additions_415c(plan, participant):
    """Returns (annual_additions_cents, limit_cents) or (None, None) for 457(b)."""
    if plan["plan_type"] != "PLAN_403B":
        return None, None
    total = 0
    for va in store.accounts_of(participant["id"], status="OPEN"):
        p = store.plans.get(va["plan_id"])
        if p and p["plan_type"] == "PLAN_403B":
            total += va["ytd_elective_deferrals_cents"] + va["ytd_employer_contributions_cents"]
    limit = min(ANNUAL_ADDITIONS_LIMIT_415C_CENTS, participant["includible_compensation_cents"])
    return total, limit


def deferral_attribution_order(election, plan, participant, employer):
    """Pinned waterfall. Returns (attribution dict, remainder)."""
    snapshot_used = participant["cumulative_special_catchup_used_cents"]
    if plan["plan_type"] == "PLAN_403B":
        cap = catchup_capacity_403b(plan, participant, employer, snapshot_used=snapshot_used)
        cap_service = cap["service_15yr"]
        cap_age50 = cap["age_50"]
        cap_final3 = 0
    else:
        cap = catchup_capacity_457b(plan, participant)
        cap_service = 0
        cap_age50 = cap["age_50"]
        cap_final3 = cap["final_3yr"]
    agg = deferral_limit_aggregate_402g(plan, participant, employer, snapshot_used=snapshot_used)
    ytd_gross = agg["ytd_gross"]
    amount = election["annual_deferral_amount_cents"]
    catchup = election["catchup_election"]

    basic = min(amount, max(0, BASIC_ELECTIVE_DEFERRAL_LIMIT_CENTS - ytd_gross))
    rem = amount - basic

    if plan["plan_type"] == "PLAN_403B" and catchup in ("SERVICE_15_YEAR",
                                                        "AGE_50_AND_SERVICE_15_YEAR"):
        service = min(rem, cap_service)
    else:
        service = 0
    rem -= service

    if plan["plan_type"] == "PLAN_457B" and catchup == "FINAL_3_YEAR":
        final3 = min(rem, cap_final3)
    else:
        final3 = 0
    rem -= final3

    if catchup in ("AGE_50", "AGE_50_AND_SERVICE_15_YEAR"):
        age50 = min(rem, cap_age50)
    else:
        age50 = 0
    rem -= age50

    return {
        "basic_deferral_attributed_cents": basic,
        "service_catchup_attributed_cents": service,
        "age50_catchup_attributed_cents": age50,
        "final3yr_catchup_attributed_cents": final3,
        "snapshot_used": snapshot_used,
    }, rem


# --- Loan capacity (PRD 3.8) ----------------------------------------------
def loan_accounts(participant_id, plan):
    out = []
    for va in store.accounts_of(participant_id, status="OPEN"):
        p = store.plans.get(va["plan_id"])
        if not p:
            continue
        if p["employer_id"] == plan["employer_id"] and p["plan_type"] == plan["plan_type"]:
            out.append(va)
    return out


def loan_maximum_available(participant, plan):
    accounts = loan_accounts(participant["id"], plan)
    vested_total = sum(va["vested_balance_cents"] for va in accounts)
    outstanding_total = sum(va["outstanding_loan_balance_cents"] for va in accounts)
    highest_12mo = sum(va["highest_outstanding_loan_12mo_cents"] for va in accounts)

    cap_statutory = LOAN_ABSOLUTE_CAP_CENTS - highest_12mo
    cap_vested = max(vested_total * LOAN_VESTED_PERCENT_BPS // 10000,
                     LOAN_MINIMUM_FLOOR_CENTS) - outstanding_total
    cap_vested = min(cap_vested, vested_total - outstanding_total)
    maximum = max(0, min(cap_statutory, cap_vested))
    unverified = [va["id"] for va in accounts
                  if not isa_covers(va["plan_id"], va["vendor_id"], "shares_loan_data",
                                    require_fresh=True)]
    return {
        "accounts": accounts,
        "vested_total_cents": vested_total,
        "outstanding_total_cents": outstanding_total,
        "highest_outstanding_12mo_cents": highest_12mo,
        "cap_statutory_cents": cap_statutory,
        "cap_vested_cents": cap_vested,
        "maximum_loan_cents": maximum,
        "included_vendor_account_ids": [va["id"] for va in accounts],
        "unverified_vendor_account_ids": unverified,
    }


def loan_eligibility_flag(participant):
    accounts = store.accounts_of(participant["id"], status="OPEN")
    outstanding_total = sum(va["outstanding_loan_balance_cents"] for va in accounts)
    if outstanding_total <= 0:
        return "AVAILABLE"
    buckets = set()
    for va in accounts:
        p = store.plans.get(va["plan_id"])
        if p:
            buckets.add((p["employer_id"], p["plan_type"]))
    if not buckets:
        return "AVAILABLE"
    for employer_id, plan_type in buckets:
        probe = {"employer_id": employer_id, "plan_type": plan_type}
        if loan_maximum_available(participant, probe)["maximum_loan_cents"] > 0:
            return "AVAILABLE"
    return "SUSPENDED"


def distribution_max_approvable(request, vendor_account):
    """Returns (max_approvable_cents, relief_defeats_need)."""
    if request["request_type"] == "HARDSHIP":
        base = request["stated_need_cents"] + request["estimated_taxes_cents"]
        relief_defeats = False
    else:
        relief = (request["insurance_reimbursement_available_cents"]
                  + request["liquidatable_assets_cents"]
                  + request["deferral_cessation_relief_cents"])
        relief_defeats = relief >= request["stated_need_cents"]
        base = max(0, request["stated_need_cents"] - relief) + request["estimated_taxes_cents"]
    return min(base, vendor_account["vested_balance_cents"]), relief_defeats


# --- Remittance timing (PRD 3.7) ------------------------------------------
def is_business_day(d):
    return d.weekday() < 5 and d not in FEDERAL_HOLIDAYS


def business_day_offset(d, n):
    """The nth business day strictly after d."""
    count = 0
    cur = d
    while count < n:
        cur = cur + datetime.timedelta(days=1)
        if is_business_day(cur):
            count += 1
    return cur


def nth_business_day_of_month(year, month, n):
    d = datetime.date(year, month, 1)
    count = 0
    while True:
        if is_business_day(d):
            count += 1
            if count == n:
                return d
        d = d + datetime.timedelta(days=1)


def remittance_deadline(batch, plan):
    withholding = parse_iso_date(batch["withholding_date"])
    if plan["is_small_plan"]:
        return business_day_offset(withholding, SMALL_PLAN_SAFE_HARBOR_BUSINESS_DAYS)
    year = withholding.year + (1 if withholding.month == 12 else 0)
    month = 1 if withholding.month == 12 else withholding.month + 1
    statutory = nth_business_day_of_month(year, month, LARGE_PLAN_DEADLINE_BUSINESS_DAY)
    seg = parse_iso_date(batch.get("segregation_feasible_date"))
    if seg is not None:
        return min(statutory, seg)
    return statutory


def count_business_days(after_date, through_date):
    """Business days strictly after `after_date` up to and including `through_date`."""
    if through_date <= after_date:
        return 0
    count = 0
    cur = after_date + datetime.timedelta(days=1)
    while cur <= through_date:
        if is_business_day(cur):
            count += 1
        cur = cur + datetime.timedelta(days=1)
    return count


def lost_earnings_correction(batch):
    days = batch["calendar_days_late"]
    breakdown = []
    for item in batch["line_items"]:
        raw = (Decimal(item["elective_deferral_cents"])
               * Decimal(LOST_EARNINGS_ANNUAL_RATE_BPS) / Decimal(10000)
               * Decimal(days) / Decimal(DAYS_PER_YEAR))
        breakdown.append({"vendor_account_id": item["vendor_account_id"],
                          "lost_earnings_cents": round_half_up(raw)})
    total = sum(line["lost_earnings_cents"] for line in breakdown)
    return breakdown, total


def excise_tax_on_late_deposit(lost_earnings_total_cents):
    return round_half_up(Decimal(lost_earnings_total_cents) * Decimal(EXCISE_TAX_RATE_BPS)
                         / Decimal(10000))


def vested_balance(accumulated_benefit_cents, vested_percentage_bps):
    return accumulated_benefit_cents * vested_percentage_bps // 10000
