"""The sixteen named calculations of the PRD, plus the derived-field refreshers
that PRD 2.9 requires to run inside the triggering request."""

import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from store import bump, d, db, dt, fmt_date, now_date, ordered

# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------

WARTIME_PERIODS = (
    (datetime.date(1961, 2, 28), datetime.date(1975, 5, 7)),
    (datetime.date(1990, 8, 2), datetime.date(1991, 4, 11)),
    (datetime.date(2001, 9, 11), datetime.date(2021, 8, 30)),
)
WARTIME_MIN_DAYS = 90

INCOME_LIMIT_BASE_CENTS = 1884000
INCOME_LIMIT_PER_DEPENDENT_CENTS = 483000
PENSION_NET_WORTH_LIMIT_CENTS = 15506000

TYPE_WEIGHT = {
    "SERVICE_TREATMENT_RECORD": Decimal("20.0"),
    "PRIVATE_MEDICAL": Decimal("12.5"),
    "VA_MEDICAL": Decimal("12.5"),
    "LAY_STATEMENT": Decimal("6.0"),
    "NEXUS_LETTER": Decimal("22.5"),
    "DBQ": Decimal("17.5"),
}
NEXUS_MULTIPLIER = {
    "NONE": Decimal("1.00"),
    "POSSIBLE": Decimal("1.00"),
    "AT_LEAST_AS_LIKELY_AS_NOT": Decimal("1.15"),
    "HIGHLY_PROBABLE": Decimal("1.30"),
}
WAIVE_FACTOR = Decimal("0.5")
LATE_MULTIPLIER = Decimal("0.85")
ON_TIME_MULTIPLIER = Decimal("1.00")
TIMELINESS_WINDOW_DAYS = 30
REQUIRED_BASE_POINTS = Decimal("40")
REQUIRED_POINTS_PER_CONDITION = Decimal("15")
EVIDENCE_READY_THRESHOLD_PCT = Decimal("80.00")

ITF_WINDOW_DAYS = 365
DEPENDENT_ADD_ON_CENTS = 8200
DEPENDENT_CAP = 3
DEPENDENT_ADD_ON_MIN_RATING = 30
MONTHLY_RATE_CENTS = {
    0: 0, 10: 17500, 20: 34600, 30: 53700, 40: 77400, 50: 110200,
    60: 139500, 70: 175900, 80: 204400, 90: 229800, 100: 383100,
}

EXEMPTION_BANDS = (
    (100, Decimal("1.00")),
    (70, Decimal("0.60")),
    (50, Decimal("0.40")),
    (30, Decimal("0.25")),
)
TUITION_CREDIT_COST_CENTS = 45000
BURIAL_FLAT_ALLOWANCE_CENTS = 90000
ADMIN_FEE_BANDS = (
    (5000000, Decimal("0.02")),
    (2000000, Decimal("0.01")),
)

MAX_POA_PER_REPRESENTATIVE = 40
POA_WEIGHT = 1
CLAIM_STAGE_WEIGHT = {
    "EVIDENCE_DEVELOPMENT": 3,
    "PEER_REVIEW": 5,
    "READY_TO_FILE": 2,
    "FILED": 4,
}
OPEN_CLAIM_STAGES = ("EVIDENCE_DEVELOPMENT", "PEER_REVIEW", "READY_TO_FILE", "FILED")
PLANNED_OUTREACH_WEIGHT = 2
ASSIGNABLE_TYPES = ("COUNTY_CVSO", "VSO_ORG")

APPEAL_WINDOW_DAYS = 365

DEFAULT_BUFFER_MINUTES = 15
DEFAULT_CONCURRENT_CAPACITY = 2
TRAVEL_BUFFER_MINUTES = 30

EMPTY_SET_SCORE = Decimal("0.0")
QUARTER_SPANS = {
    "1": ((1, 1), (3, 31)),
    "2": ((4, 1), (6, 30)),
    "3": ((7, 1), (9, 30)),
    "4": ((10, 1), (12, 31)),
}

FAVORABLE_OUTCOMES = ("GRANTED", "PARTIAL_GRANT")


def _q2(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _q1(value):
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def as_number(value):
    """A Decimal rendered as a JSON number preserving its scale value."""
    return float(value)


# --------------------------------------------------------------------------
# 1. wartime_service_days
# --------------------------------------------------------------------------

def governing_document(veteran_id):
    docs = [x for x in db.discharge_documents.values()
            if x["veteran_id"] == veteran_id
            and x["verification_status"] == "VERIFIED"]
    if not docs:
        return None
    return ordered(docs)[-1]


def wartime_service_days(veteran_id):
    doc = governing_document(veteran_id)
    if doc is None:
        return 0
    start = d(doc["claimed_service_start"])
    end = d(doc["claimed_service_end"])
    total = 0
    for window_start, window_end in WARTIME_PERIODS:
        low = start if start > window_start else window_start
        high = end if end < window_end else window_end
        if not low > high:
            total += (high - low).days + 1
    return total


# --------------------------------------------------------------------------
# 2. veteran_priority_group
# --------------------------------------------------------------------------

def income_limit_cents(dependent_count):
    return (INCOME_LIMIT_BASE_CENTS
            + INCOME_LIMIT_PER_DEPENDENT_CENTS * dependent_count)


def priority_group(veteran):
    limit = income_limit_cents(veteran["dependent_count"])
    if veteran["homeless_status"] in ("UNSHELTERED", "SHELTERED") \
            or veteran["combined_rating_pct"] >= 50:
        return "P1"
    if veteran["combined_rating_pct"] >= 30 \
            or veteran["homeless_status"] == "AT_RISK":
        return "P2"
    if veteran["household_income_cents"] <= limit:
        return "P3"
    return "P4"


# --------------------------------------------------------------------------
# 3. eligibility_category_results
# --------------------------------------------------------------------------

def category_results(veteran):
    basic = veteran["character_of_service"] in ("HONORABLE", "GENERAL")
    limit = income_limit_cents(veteran["dependent_count"])
    chains = {
        "DISABILITY_COMPENSATION": [
            ("basic_eligibility", basic),
        ],
        "PENSION": [
            ("basic_eligibility", basic),
            ("wartime_service_days",
             veteran["wartime_service_days"] >= WARTIME_MIN_DAYS),
            ("household_income_cents",
             veteran["household_income_cents"] <= limit),
            ("net_worth_cents",
             veteran["net_worth_cents"] <= PENSION_NET_WORTH_LIMIT_CENTS),
        ],
        "DEPENDENCY_INDEMNITY": [
            ("basic_eligibility", basic),
            ("intake_status", veteran["intake_status"] == "DECEASED"),
        ],
        "STATE_PROPERTY_TAX_EXEMPTION": [
            ("basic_eligibility", basic),
            ("combined_rating_pct", veteran["combined_rating_pct"] >= 30),
        ],
        "STATE_TUITION_WAIVER": [
            ("basic_eligibility", basic),
            ("dependent_count", veteran["dependent_count"] >= 1),
        ],
        "BURIAL_BENEFIT": [
            ("basic_eligibility", basic),
            ("intake_status", veteran["intake_status"] == "DECEASED"),
        ],
    }
    results = {}
    for name in ("DISABILITY_COMPENSATION", "PENSION", "DEPENDENCY_INDEMNITY",
                 "STATE_PROPERTY_TAX_EXEMPTION", "STATE_TUITION_WAIVER",
                 "BURIAL_BENEFIT"):
        reason = ""
        eligible = True
        for conjunct, holds in chains[name]:
            if not holds:
                eligible = False
                reason = conjunct
                break
        results[name] = {"eligible": eligible, "reason": reason}
    return basic, results


# --------------------------------------------------------------------------
# 4. veteran_combined_rating_pct
# --------------------------------------------------------------------------

def combined_rating_pct(veteran_id):
    rows = [c for c in db.claims.values()
            if c["veteran_id"] == veteran_id
            and c["status"] == "DECIDED"
            and c["decision_outcome"] in FAVORABLE_OUTCOMES
            and c["awarded_rating_pct"] > 0]
    rows.sort(key=lambda c: (-c["awarded_rating_pct"], c["_seq"]))
    residual = Decimal(100)
    combined = Decimal(0)
    for row in rows:
        combined += residual * Decimal(row["awarded_rating_pct"]) / Decimal(100)
        residual = Decimal(100) - combined
    rounded = (combined / Decimal(10)).quantize(Decimal("1"),
                                                rounding=ROUND_HALF_UP)
    value = int(rounded) * 10
    if value < 0:
        return 0
    if value > 100:
        return 100
    return value


# --------------------------------------------------------------------------
# 5. evidence_completeness_pct
# --------------------------------------------------------------------------

def evidence_weight_points(item):
    if item["status"] not in ("RECEIVED", "WAIVED"):
        return Decimal("0.00")
    base = TYPE_WEIGHT[item["evidence_type"]]
    if item["evidence_type"] == "NEXUS_LETTER":
        opinion = NEXUS_MULTIPLIER[item.get("nexus_opinion_strength") or "NONE"]
    else:
        opinion = Decimal("1.00")
    if item["status"] == "WAIVED":
        status_factor = WAIVE_FACTOR
        timeliness = ON_TIME_MULTIPLIER
    else:
        status_factor = Decimal("1")
        received = item.get("received_on")
        requested = item.get("requested_on")
        if received is None or requested is None:
            timeliness = ON_TIME_MULTIPLIER
        else:
            gap = (d(received) - d(requested)).days
            timeliness = (ON_TIME_MULTIPLIER if gap <= TIMELINESS_WINDOW_DAYS
                          else LATE_MULTIPLIER)
    return _q2(base * opinion * status_factor * timeliness)


def required_points(claim):
    return (REQUIRED_BASE_POINTS
            + REQUIRED_POINTS_PER_CONDITION * len(claim["claimed_conditions"]))


def evidence_completeness_pct(claim):
    earned = Decimal("0.00")
    for item in db.evidence_items.values():
        if item["claim_id"] != claim["id"]:
            continue
        earned += Decimal(str(item["weight_points"]))
    required = required_points(claim)
    if required <= 0:
        return Decimal("0.00")
    pct = _q2(earned / required * Decimal(100))
    if pct > Decimal("100.00"):
        pct = Decimal("100.00")
    return pct


# --------------------------------------------------------------------------
# 6. claim_retro_award_cents
# --------------------------------------------------------------------------

def choose_effective_date(claim, filed_on):
    itf = claim.get("intent_to_file_date")
    if itf is not None and (filed_on - d(itf)).days <= ITF_WINDOW_DAYS:
        return "INTENT_TO_FILE_ANCHORED", d(itf)
    return "FILED_DATE_ANCHORED", filed_on


def whole_months(effective, decided):
    months = (decided.year - effective.year) * 12 + (decided.month - effective.month)
    if decided.day < effective.day:
        months -= 1
    return months if months > 0 else 0


def retro_award_cents(claim, veteran, awarded_rating_pct, decided_on):
    if claim.get("effective_date") is None:
        return 0
    months = whole_months(d(claim["effective_date"]), decided_on)
    if awarded_rating_pct >= DEPENDENT_ADD_ON_MIN_RATING:
        dependents = min(veteran["dependent_count"], DEPENDENT_CAP)
        add_on = DEPENDENT_ADD_ON_CENTS * dependents
    else:
        add_on = 0
    rate = MONTHLY_RATE_CENTS.get(awarded_rating_pct, 0)
    return months * (rate + add_on)


# --------------------------------------------------------------------------
# 7. state_benefit_award_cents
# --------------------------------------------------------------------------

def exemption_rate(rating):
    for floor, rate in EXEMPTION_BANDS:
        if rating >= floor:
            return rate
    return Decimal("0.00")


def admin_fee_rate(gross):
    for floor, rate in ADMIN_FEE_BANDS:
        if gross >= floor:
            return rate
    return Decimal("0.00")


def award_breakdown(program, application, rating):
    rate = exemption_rate(rating)
    program_type = program["program_type"]
    if program_type == "PROPERTY_TAX_EXEMPTION":
        assessed = application.get("assessed_property_value_cents") or 0
        product = (Decimal(assessed) * rate).quantize(Decimal("1"),
                                                      rounding=ROUND_HALF_UP)
        gross = min(int(product), program["max_award_cents"])
    elif program_type == "TUITION_WAIVER":
        credits = application.get("tuition_credits_requested") or 0
        gross = min(credits * TUITION_CREDIT_COST_CENTS, program["max_award_cents"])
    else:
        gross = min(BURIAL_FLAT_ALLOWANCE_CENTS, program["max_award_cents"])
    fee = int((Decimal(gross) * admin_fee_rate(gross))
              .quantize(Decimal("1"), rounding=ROUND_CEILING))
    return gross, fee, gross - fee


# --------------------------------------------------------------------------
# 8..10. the three conserved ledgers
# --------------------------------------------------------------------------

def program_allocated_cents(program_id):
    return sum(a["benefit_amount_cents"]
               for a in db.state_benefit_applications.values()
               if a["program_id"] == program_id
               and a["disbursement_status"] in ("PENDING", "ISSUED"))


def site_booked_slot_count(site_id):
    return sum(1 for a in db.exam_appointments.values()
               if a["exam_site_id"] == site_id and a["status"] == "SCHEDULED")


def representative_active_poa_count(representative_id):
    return sum(1 for p in db.powers_of_attorney.values()
               if p["representative_id"] == representative_id
               and p["status"] == "ACTIVE")


# --------------------------------------------------------------------------
# 11. representative_caseload_weight
# --------------------------------------------------------------------------

def caseload_decomposition(representative_id):
    active_poas = [p for p in db.powers_of_attorney.values()
                   if p["representative_id"] == representative_id
                   and p["status"] == "ACTIVE"]
    poa_ids = set(p["id"] for p in active_poas)
    claim_points = 0
    open_claims = 0
    for claim in db.claims.values():
        if claim.get("poa_id") in poa_ids:
            weight = CLAIM_STAGE_WEIGHT.get(claim["status"])
            if weight:
                claim_points += weight
                open_claims += 1
    planned = [e for e in db.outreach_events.values()
               if e["assigned_representative_id"] == representative_id
               and e["status"] == "PLANNED"]
    weight = (POA_WEIGHT * len(active_poas) + claim_points
              + PLANNED_OUTREACH_WEIGHT * len(planned))
    return {
        "active_poa_count": len(active_poas),
        "open_claim_count": open_claims,
        "planned_outreach_count": len(planned),
        "caseload_weight": weight,
    }


# --------------------------------------------------------------------------
# 12. representative_assignment_selector
# --------------------------------------------------------------------------

def assignment_eligible(representative):
    return (representative["accreditation_status"] == "ACTIVE"
            and representative["accreditation_type"] in ASSIGNABLE_TYPES
            and representative["active_poa_count"] < MAX_POA_PER_REPRESENTATIVE)


def assignment_candidates():
    rows = [r for r in db.representatives.values() if assignment_eligible(r)]
    rows.sort(key=lambda r: (r["caseload_weight"], r["_seq"]))
    return rows


# --------------------------------------------------------------------------
# 13. decision_review_deadline
# --------------------------------------------------------------------------

def deadline_on(notice_date):
    return d(notice_date) + datetime.timedelta(days=APPEAL_WINDOW_DAYS)


def days_remaining(review):
    return (d(review["deadline_on"]) - now_date()).days


# --------------------------------------------------------------------------
# 14. outcome_report_performance_score
# --------------------------------------------------------------------------

def quarter_window(label):
    year = int(label[0:4])
    (start_month, start_day), (end_month, end_day) = QUARTER_SPANS[label[5]]
    return (datetime.date(year, start_month, start_day),
            datetime.date(year, end_month, end_day))


def compute_report_figures(label, basis):
    window_start, window_end = quarter_window(label)
    in_window = []
    for claim in db.claims.values():
        filed = claim.get("filed_on")
        if filed is None:
            continue
        filed_date = d(filed)
        if window_start <= filed_date <= window_end:
            in_window.append(claim)
    favorable = [c for c in in_window
                 if c["status"] == "DECIDED"
                 and c["decision_outcome"] in FAVORABLE_OUTCOMES]
    retro = sum(c["retro_award_cents"] for c in favorable)
    contacted = 0
    for event in db.outreach_events.values():
        if event["status"] != "HELD":
            continue
        starts = dt(event["starts_at"]).date()
        if window_start <= starts <= window_end:
            contacted += event["veterans_contacted"]
    filed_count = len(in_window)
    favorable_count = len(favorable)
    if filed_count == 0:
        score = EMPTY_SET_SCORE
    elif basis == "VETERAN_WEIGHTED":
        all_vets = set(c["veteran_id"] for c in in_window)
        fav_vets = set(c["veteran_id"] for c in favorable)
        score = _q1(Decimal(len(fav_vets)) / Decimal(len(all_vets)) * Decimal(100))
    else:
        score = _q1(Decimal(favorable_count) / Decimal(filed_count) * Decimal(100))
    return {
        "filed_claim_count": filed_count,
        "favorable_claim_count": favorable_count,
        "performance_score": as_number(score),
        "retro_dollars_cents": retro,
        "veterans_contacted_total": contacted,
    }


# --------------------------------------------------------------------------
# 15. exam_site_interval_conflict
# --------------------------------------------------------------------------

def _block(starts, ends, buffer_minutes):
    return starts, ends + datetime.timedelta(minutes=buffer_minutes)


def site_overlap_count(site, starts, ends, exclude_id=None):
    buffer_minutes = site["buffer_minutes"]
    new_start, new_end = _block(starts, ends, buffer_minutes)
    count = 0
    for appointment in db.exam_appointments.values():
        if appointment["exam_site_id"] != site["id"]:
            continue
        if appointment["status"] != "SCHEDULED":
            continue
        if exclude_id is not None and appointment["id"] == exclude_id:
            continue
        old_start, old_end = _block(dt(appointment["starts_at"]),
                                    dt(appointment["ends_at"]), buffer_minutes)
        if new_start < old_end and old_start < new_end:
            count += 1
    return count


# --------------------------------------------------------------------------
# 16. outreach_travel_conflict
# --------------------------------------------------------------------------

def _travel_block(starts, ends):
    delta = datetime.timedelta(minutes=TRAVEL_BUFFER_MINUTES)
    return starts - delta, ends + delta


def travel_conflict(representative_id, starts, ends, exclude_id=None):
    new_start, new_end = _travel_block(starts, ends)
    for event in db.outreach_events.values():
        if event["assigned_representative_id"] != representative_id:
            continue
        if event["status"] not in ("PLANNED", "HELD"):
            continue
        if exclude_id is not None and event["id"] == exclude_id:
            continue
        old_start, old_end = _travel_block(dt(event["starts_at"]),
                                           dt(event["ends_at"]))
        if new_start < old_end and old_start < new_end:
            return True
    return False


# --------------------------------------------------------------------------
# derived-field refreshers (PRD 2.9)
# --------------------------------------------------------------------------

def refresh_discharge_mirror(veteran):
    """`discharge_doc_status` mirrors the veteran's newest document."""
    docs = [x for x in db.discharge_documents.values()
            if x["veteran_id"] == veteran["id"]]
    if not docs:
        veteran["discharge_doc_status"] = "NOT_SUBMITTED"
    else:
        veteran["discharge_doc_status"] = ordered(docs)[-1]["verification_status"]


def refresh_caseload(representative):
    """Recompute the caseload terms; bump the row only when a value moved."""
    if representative is None:
        return
    parts = caseload_decomposition(representative["id"])
    changed = (representative.get("active_poa_count") != parts["active_poa_count"]
               or representative.get("caseload_weight") != parts["caseload_weight"])
    representative["active_poa_count"] = parts["active_poa_count"]
    representative["caseload_weight"] = parts["caseload_weight"]
    if changed:
        bump(representative)


def refresh_caseload_no_bump(representative):
    if representative is None:
        return
    parts = caseload_decomposition(representative["id"])
    representative["active_poa_count"] = parts["active_poa_count"]
    representative["caseload_weight"] = parts["caseload_weight"]


def refresh_claim_score(claim):
    claim["evidence_completeness_pct"] = as_number(evidence_completeness_pct(claim))


def refresh_item_points(item):
    item["weight_points"] = as_number(evidence_weight_points(item))


def refresh_veteran_rating(veteran):
    veteran["combined_rating_pct"] = combined_rating_pct(veteran["id"])
    veteran["priority_group"] = priority_group(veteran)


def claim_preparer(claim):
    return db.representatives.get(claim.get("prepared_by_representative_id"))


def poa_representative(claim):
    poa = db.powers_of_attorney.get(claim.get("poa_id"))
    if poa is None:
        return None
    return db.representatives.get(poa["representative_id"])


def clock_date_str():
    return fmt_date(now_date())
