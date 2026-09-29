"""Calculation rules (PRD sections 2.8, 3.2, 3.3, 3.4, 3.6, 3.8).

Every rounding operation here is round-half-up and every intermediate rounding
prescribed by the PRD is performed exactly where the PRD places it.
"""
from decimal import Decimal, ROUND_CEILING

from store import add_days, day_span, dec, q1, q2, store

# --- months_in_rank_ledger -------------------------------------------------
TOTAL_MONTHS_IN_RANK_CAP = 60
MIN_TERM_MONTHS = 12
MAX_TERM_MONTHS = 36

# --- salary_floor_computation ---------------------------------------------
NIH_SCALE_BY_BAND = [Decimal("61008"), Decimal("61428"), Decimal("62124"),
                     Decimal("64536"), Decimal("67284")]
INSTITUTIONAL_MIN_BY_BAND = [Decimal("58000"), Decimal("60000"), Decimal("62000"),
                             Decimal("62000"), Decimal("62000")]
TITLE_UPLIFT_USD = Decimal("3000")
ABSOLUTE_STIPEND_FLOOR_USD = Decimal("54000.00")

# --- funding_encumbrance --------------------------------------------------
PRORATION_DAYS_PER_YEAR = Decimal("365")
FRINGE_BAND_1_CEILING_USD = Decimal("40000.00")
FRINGE_BAND_2_CEILING_USD = Decimal("65000.00")
FELLOWSHIP_FRINGE_RATE = Decimal("0.075")
FRINGE_BAND_1_RATE = Decimal("0.28")
FRINGE_BAND_2_RATE = Decimal("0.31")
FRINGE_BAND_3_RATE = Decimal("0.335")

HELD_APPOINTMENT_STATUSES = ("OFFER_ISSUED", "OFFER_ACCEPTED", "ACTIVE", "NON_RENEWED")
RANK_CONTRIBUTING_PREDECESSOR = ("ACTIVE", "COMPLETED", "NON_RENEWED", "TERMINATED")
REALIZED_RANK_STATUSES = ("COMPLETED", "NON_RENEWED", "TERMINATED")

# --- benefits_eligibility -------------------------------------------------
BENEFITS_FULL_MIN_MONTHS = 12

# --- visa_category_selection ---------------------------------------------
CATEGORY_PRIORITY = {"TN": 1, "J1_RESEARCH_SCHOLAR": 2, "H1B": 3, "O1": 4}
PREMIUM_ELIGIBLE_CATEGORIES = ("H1B", "O1")

# --- visa_processing_timeline --------------------------------------------
STANDARD_PROCESSING_DAYS = {"TN": 10, "J1_RESEARCH_SCHOLAR": 21, "H1B": 120, "O1": 75}
PREMIUM_PROCESSING_DAYS = {"H1B": 15, "O1": 15}
RFE_EXTENSION_FACTOR = Decimal("1.5")
VISA_ACTIVATION_LEAD_DAYS = 10
RFE_ROUND_LIMIT = 2

# --- development documents ----------------------------------------------
DOC_REVISION_LIMIT = 3

# --- export_control_risk_score ------------------------------------------
COUNTRY_RISK = {"US": Decimal("0.0"), "CA": Decimal("0.5"), "MX": Decimal("0.5"),
                "IN": Decimal("1.5"), "CN": Decimal("2.5"), "IR": Decimal("4.0")}
COUNTRY_RISK_DEFAULT = Decimal("1.0")
FUNDING_RISK = {"FEDERAL_GRANT": Decimal("1.0"), "FOUNDATION_GRANT": Decimal("0.5"),
                "EXTERNAL_FELLOWSHIP": Decimal("1.6"), "INSTITUTIONAL_FELLOWSHIP": Decimal("0.0")}
TIER_1_COUNTRY_WEIGHT = Decimal("12.5")
TIER_2_COUNTRY_WEIGHT = Decimal("15.0")
TECH_COMPONENT = Decimal("18.75")
PARTY_COMPONENT = Decimal("40.00")
FUNDING_WEIGHT = Decimal("6.25")
DURATION_WEIGHT = Decimal("3.125")
CONDITIONS_THRESHOLD = Decimal("35.0")
DENIAL_THRESHOLD = Decimal("60.0")

# --- non_renewal_notice_policy ------------------------------------------
NOTICE_TIER_1_MONTHS = 12
NOTICE_TIER_2_MONTHS = 36
GRIEVANCE_WINDOW_DAYS = 21

# --- lab_bench_occupancy -------------------------------------------------
RESTRICTED_MAX_BENCH_SEATS = 1


# =========================================================================
# pinned month arithmetic (PRD 3.2)
# =========================================================================

def term_months_between(start, end):
    months = (end.year * 12 + end.month) - (start.year * 12 + start.month)
    if end.day >= start.day:
        months += 1
    return months


def predecessor_chain(appointment):
    chain = []
    cursor = appointment.get("predecessor_appointment_id")
    while cursor:
        predecessor = store.appointments.get(cursor)
        if predecessor is None:
            break
        chain.append(predecessor)
        cursor = predecessor.get("predecessor_appointment_id")
    return chain


def months_in_rank_at_start(appointment, postdoc):
    total = int(postdoc.get("prior_external_months_in_rank") or 0)
    for predecessor in predecessor_chain(appointment):
        if predecessor["appointment_status"] in RANK_CONTRIBUTING_PREDECESSOR:
            total += term_months_between(
                predecessor["term_start_date"], predecessor["term_end_date"])
    return total


# =========================================================================
# salary floor (PRD 3.3)
# =========================================================================

def salary_floor(appointment, funding_source, months_at_start):
    band = min(int(months_at_start) // 12, 4)
    if funding_source["salary_floor_policy"] == "NIH_SCALE":
        policy_base = NIH_SCALE_BY_BAND[band]
    else:
        policy_base = INSTITUTIONAL_MIN_BY_BAND[band]
    multiplier = Decimal("1.00") if appointment["employment_class"] == "EMPLOYEE" else Decimal("0.95")
    uplift = TITLE_UPLIFT_USD if appointment["title_classification"] == "POSTDOC_SCHOLAR_EMPLOYEE" else Decimal("0")
    raw = q2(policy_base * multiplier + uplift)
    return raw if raw > ABSOLUTE_STIPEND_FLOOR_USD else ABSOLUTE_STIPEND_FLOOR_USD


def effective_floor(appointment):
    if appointment.get("salary_exception_floor_usd") is not None:
        return appointment["salary_exception_floor_usd"]
    return appointment["salary_floor_usd"]


# =========================================================================
# benefits (PRD 3.3)
# =========================================================================

def benefits_package(appointment, funding_source):
    employment_class = appointment["employment_class"]
    term_months = appointment.get("term_months") or 0
    if employment_class == "EMPLOYEE":
        if term_months >= BENEFITS_FULL_MIN_MONTHS:
            return "EMPLOYEE_FULL"
        return "EMPLOYEE_LIMITED"
    funding_type = funding_source["funding_type"]
    if employment_class == "FELLOWSHIP" and funding_type == "EXTERNAL_FELLOWSHIP":
        return "FELLOWSHIP_STIPEND_ONLY"
    if employment_class == "FELLOWSHIP" and funding_type == "INSTITUTIONAL_FELLOWSHIP":
        return "FELLOWSHIP_INSTITUTIONAL"
    return "NONE"


# =========================================================================
# encumbrance (PRD 3.3)
# =========================================================================

def overlap_days(appointment, funding_source):
    overlap_start = max(appointment["term_start_date"], funding_source["award_start_date"])
    overlap_end = min(appointment["term_end_date"], funding_source["award_end_date"])
    return day_span(overlap_start, overlap_end)


def encumbrance(appointment, funding_source):
    """Return (fringe_rate, encumbrance_usd) or (None, None) when there is no overlap."""
    days = overlap_days(appointment, funding_source)
    if days <= 0:
        return None, None
    base = q2(dec(appointment["annual_salary_usd"]) * Decimal(days) / PRORATION_DAYS_PER_YEAR)
    if appointment["employment_class"] == "FELLOWSHIP":
        rate = FELLOWSHIP_FRINGE_RATE
    elif base < FRINGE_BAND_1_CEILING_USD:
        rate = FRINGE_BAND_1_RATE
    elif base < FRINGE_BAND_2_CEILING_USD:
        rate = FRINGE_BAND_2_RATE
    else:
        rate = FRINGE_BAND_3_RATE
    fringe_amount = q2(base * rate)
    return rate, q2(base + fringe_amount)


def encumbered_total(funding_source_id):
    total = Decimal("0.00")
    for appointment in store.appointments.values():
        if appointment["funding_source_id"] != funding_source_id:
            continue
        if appointment["appointment_status"] not in HELD_APPOINTMENT_STATUSES:
            continue
        total += q2(appointment.get("encumbrance_usd") or 0)
    return q2(total)


# =========================================================================
# visa category selection and timeline (PRD 3.4)
# =========================================================================

def eligible_visa_categories(appointment, postdoc):
    eligible = []
    term_months = appointment.get("term_months") or 0
    if postdoc["citizenship_country"] in ("CA", "MX") and appointment["employment_class"] == "EMPLOYEE":
        eligible.append("TN")
    if not postdoc["j1_two_year_bar_flag"] and term_months <= 60:
        eligible.append("J1_RESEARCH_SCHOLAR")
    if appointment["employment_class"] == "EMPLOYEE" and term_months >= 12:
        eligible.append("H1B")
    if postdoc["o1_endorsement_on_file"]:
        eligible.append("O1")
    return eligible


def select_visa_category(appointment, postdoc):
    eligible = eligible_visa_categories(appointment, postdoc)
    if not eligible:
        return None
    return min(eligible, key=lambda category: CATEGORY_PRIORITY[category])


def base_processing_days(visa_category, processing_track):
    if processing_track == "PREMIUM":
        return PREMIUM_PROCESSING_DAYS.get(visa_category, STANDARD_PROCESSING_DAYS[visa_category])
    return STANDARD_PROCESSING_DAYS[visa_category]


def project_dates(visa_case, variant):
    base_days = base_processing_days(visa_case["visa_category"], visa_case["processing_track"])
    if variant == "POST_RFE_REFILING":
        extended = dec(base_days) * RFE_EXTENSION_FACTOR
        days = int(extended.to_integral_value(rounding=ROUND_CEILING))
    else:
        days = base_days
    filed_date = visa_case["filed_at"].date()
    projected = add_days(filed_date, days)
    return projected, add_days(projected, VISA_ACTIVATION_LEAD_DAYS)


# =========================================================================
# export control risk score (PRD 3.6)
# =========================================================================

def country_risk(citizenship_country):
    return COUNTRY_RISK.get(citizenship_country, COUNTRY_RISK_DEFAULT)


def screening_tier(review, postdoc):
    risk = country_risk(postdoc["citizenship_country"])
    if review["cycle_index"] >= 2:
        return "TIER_2_ENHANCED"
    if review["restricted_party_hit"]:
        return "TIER_2_ENHANCED"
    if review["controlled_technology_flag"] and risk >= Decimal("3.0"):
        return "TIER_2_ENHANCED"
    return "TIER_1_STANDARD"


def risk_score(review, appointment, postdoc, funding_source, tier):
    risk = country_risk(postdoc["citizenship_country"])
    funding_risk = FUNDING_RISK[funding_source["funding_type"]]
    weight = TIER_2_COUNTRY_WEIGHT if tier == "TIER_2_ENHANCED" else TIER_1_COUNTRY_WEIGHT
    w_country = q2(risk * weight)
    w_tech = q2(TECH_COMPONENT if review["controlled_technology_flag"] else Decimal("0.0"))
    w_party = q2(PARTY_COMPONENT if review["restricted_party_hit"] else Decimal("0.0"))
    w_funding = q2(funding_risk * FUNDING_WEIGHT)
    if tier == "TIER_2_ENHANCED":
        term_months = dec(appointment.get("term_months") or 0)
        w_duration = q2((term_months / Decimal(12)) * DURATION_WEIGHT)
    else:
        w_duration = Decimal("0.00")
    return q1(w_country + w_tech + w_party + w_funding + w_duration)


def screening_outcome(review, score):
    if review["restricted_party_hit"]:
        return "DENIED"
    if score >= DENIAL_THRESHOLD:
        return "DENIED"
    if score >= CONDITIONS_THRESHOLD:
        return "CLEARED_WITH_CONDITIONS"
    return "CLEARED"


# =========================================================================
# non-renewal notice policy (PRD 3.8)
# =========================================================================

def notice_days_for_service(service_months):
    if service_months <= NOTICE_TIER_1_MONTHS:
        return 30
    if service_months <= NOTICE_TIER_2_MONTHS:
        return 60
    return 90
