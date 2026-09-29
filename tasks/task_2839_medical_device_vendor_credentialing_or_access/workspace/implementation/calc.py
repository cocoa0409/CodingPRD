"""Calculation rules (PRD 3.2, 3.4, 3.7, 3.8, 3.9) and collection lookups."""
from decimal import Decimal, ROUND_HALF_UP

import db
from db import store
from timeutil import add_days, add_hours, add_minutes, fmt_instant, parse_instant


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------
def credentials_of_rep(rep_id):
    return [c for c in store.credentials.values() if c["vendor_rep_id"] == rep_id]


def reps_of_vendor(vendor_id):
    return [r for r in store.vendor_reps.values() if r["vendor_id"] == vendor_id]


def authorizations_of_case(case_id):
    return [a for a in store.authorizations.values() if a["surgical_case_id"] == case_id]


def authorizations_of_rep(rep_id):
    return [a for a in store.authorizations.values() if a["vendor_rep_id"] == rep_id]


def check_ins_of_authorization(auth_id):
    return [k for k in store.check_ins.values() if k["case_rep_authorization_id"] == auth_id]


def loaner_sets_of_case(case_id):
    return [s for s in store.loaner_sets.values() if s["surgical_case_id"] == case_id]


def loaner_sets_of_product(product_id):
    return [s for s in store.loaner_sets.values() if s["approved_product_id"] == product_id]


def appeals_of_rep(rep_id):
    return [a for a in store.appeals.values() if a["vendor_rep_id"] == rep_id]


def product_vendor_id(product):
    """A product's vendor is the vendor of the request that minted it."""
    pir = store.pirs.get(product["product_introduction_request_id"])
    return pir["vendor_id"] if pir else None


def product_facility_id(product):
    pir = store.pirs.get(product["product_introduction_request_id"])
    return pir["facility_id"] if pir else None


def loaner_set_vendor_id(loaner_set):
    product = store.approved_products.get(loaner_set["approved_product_id"])
    return product_vendor_id(product) if product else None


def loaner_sets_of_vendor(vendor_id):
    return [s for s in store.loaner_sets.values() if loaner_set_vendor_id(s) == vendor_id]


def incidents_of_vendor(vendor_id):
    rep_ids = {r["id"] for r in reps_of_vendor(vendor_id)}
    return [i for i in store.incidents.values() if i["vendor_rep_id"] in rep_ids]


def rep_of_authorization(auth):
    return store.vendor_reps.get(auth["vendor_rep_id"])


def vendor_of_rep(rep):
    return store.vendors.get(rep["vendor_id"])


def case_facility(case):
    return store.facilities.get(case["facility_id"])


def loaner_set_facility(loaner_set):
    case = store.surgical_cases.get(loaner_set["surgical_case_id"])
    return case_facility(case) if case else None


# --------------------------------------------------------------------------
# Rounding helpers (PRD 2.6: round half up)
# --------------------------------------------------------------------------
def round_half_up(value, places=0):
    quantum = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def clamp_score(value):
    return max(db.SCORE_FLOOR, min(db.SCORE_CEILING, value))


# --------------------------------------------------------------------------
# calculations.rep_credential_posture (PRD 3.2)
# --------------------------------------------------------------------------
def compute_credential_posture(rep):
    creds = credentials_of_rep(rep["id"])
    covered = {c["credential_type"] for c in creds if c["status"] in ("VERIFIED", "EXPIRING_SOON")}
    missing = [t for t in db.GATING_CREDENTIAL_TYPES if t not in covered]
    if missing:
        return "LAPSED" if rep["ever_credentialed"] else "INCOMPLETE"
    for c in creds:
        if c["status"] == "EXPIRING_SOON" and c["credential_type"] in db.GATING_CREDENTIAL_TYPES:
            return "EXPIRING_SOON"
    return "COMPLIANT"


# --------------------------------------------------------------------------
# calculations.badge_validity_window (PRD 3.4)
# --------------------------------------------------------------------------
def compute_badge_window(case, facility):
    start = parse_instant(case["scheduled_start_utc"])
    end = parse_instant(case["scheduled_end_utc"])
    window_start = add_minutes(start, -facility["badge_lead_minutes"])
    window_end = add_minutes(end, facility["badge_grace_minutes"])
    return fmt_instant(window_start), fmt_instant(window_end)


def windows_conflict(a_start, a_end, b_start, b_end):
    """Half-open comparison, so adjacency is legal (PRD 3.4)."""
    return a_start < b_end and b_start < a_end


# --------------------------------------------------------------------------
# calculations.loaner_delivery_deadline (PRD 3.7)
# --------------------------------------------------------------------------
def tray_surcharge_hours(tray_count):
    if tray_count <= 4:
        return 0
    if tray_count <= 12:
        return 1
    return 2


def lead_hours(case, facility, complexity, tray_count):
    turnaround = (
        facility["spd_turnaround_hours"]
        + db.COMPLEXITY_HOURS[complexity]
        + tray_surcharge_hours(tray_count)
    )
    floor_hours = db.IMPLANT_MIN_LEAD_HOURS if case["implant_required"] else 0
    return max(turnaround, floor_hours)


def compute_deadline(basis_instant_str, case, facility, complexity, tray_count):
    basis = parse_instant(basis_instant_str)
    hours = lead_hours(case, facility, complexity, tray_count)
    return fmt_instant(add_hours(basis, -hours))


# --------------------------------------------------------------------------
# calculations.loaner_late_minutes (PRD 3.7)
# --------------------------------------------------------------------------
def compute_late_minutes(deadline_str, delivered_str):
    """Whole minutes, truncated toward zero, never below zero."""
    if not deadline_str or not delivered_str:
        return 0
    seconds = (parse_instant(delivered_str) - parse_instant(deadline_str)).total_seconds()
    if seconds <= 0:
        return 0
    return int(seconds // 60)


def delivery_branch(late_minutes_current):
    if late_minutes_current == 0:
        return "DELIVERED_ON_TIME"
    if late_minutes_current <= db.HARD_REJECT_GRACE_MINUTES:
        return "DELIVERED_LATE"
    return "REJECTED_LATE"


# --------------------------------------------------------------------------
# calculations.loaner_late_fee (PRD 3.7)
# --------------------------------------------------------------------------
def compute_late_fee(loaner_set):
    """Round the per-tray charge FIRST, then multiply by tray_count, then cap."""
    late_minutes = loaner_set["late_minutes_current_basis"]
    multiplier = Decimal(db.COMPLEXITY_FEE_MULTIPLIER[loaner_set["reprocessing_complexity"]])
    per_tray = round_half_up(
        Decimal(late_minutes) * Decimal(db.PER_TRAY_BASE_RATE_CENTS_PER_MINUTE) * multiplier, 0
    )
    raw_fee = int(per_tray) * loaner_set["tray_count"]
    return min(raw_fee, db.LATE_FEE_CAP_CENTS)


def compute_fee_status(loaner_set):
    if loaner_set["late_minutes_current_basis"] == 0:
        return "NONE"
    if loaner_set["tray_count"] == 0:
        return "WAIVED"
    return "ASSESSED"


# --------------------------------------------------------------------------
# calculations.spd_bay_occupation (PRD 3.7)
# --------------------------------------------------------------------------
def bay_collision_count(candidate_start_str, candidate_end_str, facility_id, exclude_id=None):
    candidate_start = parse_instant(candidate_start_str)
    candidate_end = parse_instant(candidate_end_str)
    count = 0
    for existing in db.in_creation_order(list(store.loaner_sets.values())):
        if exclude_id is not None and existing["id"] == exclude_id:
            continue
        if existing["status"] not in db.LOANER_BAY_OCCUPYING_STATUSES:
            continue
        facility = loaner_set_facility(existing)
        if facility is None or facility["id"] != facility_id:
            continue
        buffered_start = add_minutes(
            parse_instant(existing["spd_occupation_start_utc"]), -db.SPD_BAY_BUFFER_MINUTES
        )
        buffered_end = add_minutes(
            parse_instant(existing["spd_occupation_end_utc"]), db.SPD_BAY_BUFFER_MINUTES
        )
        if buffered_start <= candidate_end and candidate_start <= buffered_end:
            count += 1
    return count


# --------------------------------------------------------------------------
# calculations.case_vendor_coverage_status (PRD 3.4)
# --------------------------------------------------------------------------
def compute_coverage_status(case):
    approved = [a for a in authorizations_of_case(case["id"]) if a["status"] == "APPROVED"]
    if not case["implant_required"] and not approved:
        return "NOT_REQUIRED"
    if case["implant_required"] and not approved:
        return "UNCOVERED"
    for a in approved:
        rep = rep_of_authorization(a)
        if rep is not None and rep["credential_posture"] == "EXPIRING_SOON":
            return "AT_RISK"
    if case["revoked_authorization_count"] >= 1:
        return "AT_RISK"
    return "COVERED"


# --------------------------------------------------------------------------
# calculations.case_implant_readiness_status (PRD 3.7)
# --------------------------------------------------------------------------
def compute_readiness_status(case):
    if not case["implant_required"]:
        return "NOT_APPLICABLE"
    sets = loaner_sets_of_case(case["id"])
    for s in sets:
        if s["status"] in ("HELD", "REJECTED_LATE"):
            return "BLOCKED"
    if sets and all(s["status"] == "RELEASED_TO_OR" for s in sets):
        return "READY"
    return "PENDING"


# --------------------------------------------------------------------------
# calculations.vendor_compliance_score (PRD 3.8)
# --------------------------------------------------------------------------
def compute_late_delivery_count(vendor_id):
    return len(
        [
            s
            for s in loaner_sets_of_vendor(vendor_id)
            if s["status"] in ("DELIVERED_LATE", "REJECTED_LATE") and s["fee_status"] != "REVERSED"
        ]
    )


def compute_fee_balance(vendor_id):
    return sum(
        s["assessed_late_fee_cents"]
        for s in loaner_sets_of_vendor(vendor_id)
        if s["fee_status"] == "ASSESSED"
    )


def _incident_penalty(incidents):
    return sum(db.SEVERITY_WEIGHT[i["severity"]] for i in incidents)


def provisional_counted_incidents(vendor_id):
    return [
        i
        for i in incidents_of_vendor(vendor_id)
        if i["status"] in db.INCIDENT_OPEN_STATUSES or i["adjudicated_outcome"] == "SUBSTANTIATED"
    ]


def adjudicated_counted_incidents(vendor_id):
    return [
        i for i in incidents_of_vendor(vendor_id) if i["adjudicated_outcome"] == "SUBSTANTIATED"
    ]


def compute_scores(vendor, lapsed_rep_count=None, overage_penalty=None):
    """Both variants, differing only in which incidents they count."""
    vendor_id = vendor["id"]
    if lapsed_rep_count is None:
        lapsed_rep_count = vendor["_lapsed_rep_count_at_last_sweep"]
    if overage_penalty is None:
        overage_penalty = vendor["_overage_penalty_at_last_sweep"]
    late_penalty = db.W_LATE_DELIVERY * compute_late_delivery_count(vendor_id)
    lapsed_penalty = db.W_LAPSED_REP * lapsed_rep_count
    base = db.BASE_SCORE - late_penalty - lapsed_penalty - overage_penalty
    provisional = clamp_score(base - _incident_penalty(provisional_counted_incidents(vendor_id)))
    adjudicated = clamp_score(base - _incident_penalty(adjudicated_counted_incidents(vendor_id)))
    return provisional, adjudicated


def compute_utilization_ratio(used, quota):
    """Round half up to four decimal places (PRD 2.6 / 3.9)."""
    if quota == 0:
        return Decimal("0.0000")
    return round_half_up(Decimal(used) / Decimal(quota), 4)


def compute_lapsed_rep_count(vendor_id):
    return len([r for r in reps_of_vendor(vendor_id) if r["credential_posture"] == "LAPSED"])


def derive_tier(score):
    if score >= db.TIER_PLATINUM_MIN_SCORE:
        return "TIER_PLATINUM"
    if score >= db.TIER_STANDARD_MIN_SCORE:
        return "TIER_STANDARD"
    return "TIER_PROBATION"


def derive_compliance_status(score):
    if score < 40:
        return "BARRED"
    if score < 70:
        return "PROBATION"
    if score < 85:
        return "WATCH"
    return "IN_GOOD_STANDING"


def quota_hard_cap(quota_in_effect):
    """floor(access_quota_in_effect * 1.5) (PRD 3.4)."""
    return int((Decimal(quota_in_effect) * Decimal(db.QUOTA_HARD_MULTIPLIER)).to_integral_value(rounding="ROUND_FLOOR"))


def next_quota(quota_in_effect, tier):
    stepped = Decimal(quota_in_effect) * Decimal(db.TIER_STEP[tier])
    return max(1, int(stepped.to_integral_value(rounding="ROUND_FLOOR")))


def approval_expiry(approved_at_str):
    return fmt_instant(add_days(parse_instant(approved_at_str), db.APPROVAL_VALIDITY_DAYS))
