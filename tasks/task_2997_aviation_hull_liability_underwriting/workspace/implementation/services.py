"""Lookups, rating, the premium ledger and every cascade of PRD 2.8."""

import auth
import calc
import constants as C
import derive
import util
from errors import ApiError
from store import db, new_record, ordered, touch


# --- lookups ------------------------------------------------------------------

def _find(collection, row_id, error_id):
    if not isinstance(row_id, str):
        raise ApiError(error_id)
    rec = collection.get(row_id)
    if rec is None:
        raise ApiError(error_id)
    return rec


def get_operator(row_id):
    return _find(db.operators, row_id, "ERR_OPERATOR_NOT_FOUND")


def get_aircraft(row_id):
    return _find(db.aircraft, row_id, "ERR_AIRCRAFT_NOT_FOUND")


def get_pilot(row_id):
    return _find(db.pilots, row_id, "ERR_PILOT_NOT_FOUND")


def get_policy(row_id):
    return _find(db.policies, row_id, "ERR_POLICY_NOT_FOUND")


def get_schedule(row_id, error_id="ERR_SCHEDULE_NOT_FOUND"):
    return _find(db.schedules, row_id, error_id)


def get_endorsement(row_id):
    return _find(db.endorsements, row_id, "ERR_ENDORSEMENT_NOT_FOUND")


def get_market(row_id):
    return _find(db.markets, row_id, "ERR_MARKET_NOT_FOUND")


def get_placement(row_id):
    return _find(db.placements, row_id, "ERR_PLACEMENT_NOT_FOUND")


def get_claim(row_id):
    return _find(db.claims, row_id, "ERR_CLAIM_NOT_FOUND")


def get_assessment(row_id):
    return _find(db.assessments, row_id, "ERR_ASSESSMENT_NOT_FOUND")


def get_transaction(row_id):
    return _find(db.transactions, row_id, "ERR_TRANSACTION_NOT_FOUND")


def get_declaration(row_id):
    return _find(db.declarations, row_id, "ERR_DECLARATION_NOT_FOUND")


# --- operator scope (rank 4) ---------------------------------------------------

def scope_policy(policy):
    auth.scope_operator_id(policy["operator_id"])


def scope_via_policy(policy_id):
    policy = db.policies.get(policy_id)
    if policy is not None:
        auth.scope_operator_id(policy["operator_id"])


def scope_schedule(schedule):
    scope_via_policy(schedule["policy_id"])


def scope_claim(claim):
    scope_via_policy(claim["policy_id"])


def scope_assessment(assessment):
    claim = db.claims.get(assessment["claim_id"])
    if claim is not None:
        scope_claim(claim)


def visible_policy_ids():
    """Policy ids an OperatorUser may see, or None when no narrowing applies."""
    operator_id = auth.visible_operator_id()
    if operator_id is None:
        return None
    return set(p["id"] for p in db.policies.values() if p["operator_id"] == operator_id)


# --- premium ledger -----------------------------------------------------------

def append_transaction(policy_id, txn_type, amount_cents, effective_date, basis, memo,
                       endorsement_id=None):
    """Append a ledger row. A zero amount is never written."""
    if amount_cents == 0:
        return None
    return new_record(db.transactions, {
        "policy_id": policy_id,
        "endorsement_id": endorsement_id,
        "txn_type": txn_type,
        "amount_cents": amount_cents,
        "effective_date": effective_date,
        "basis": basis,
        "memo": memo,
    }, versioned=False)


# --- warranty minima and rating ------------------------------------------------

def warranty_minima(use_class):
    return C.WARRANTY_MIN_TOTAL_HOURS[use_class], C.WARRANTY_MIN_HOURS_ON_TYPE[use_class]


def basis_for(pilot):
    return "VERIFIED_HOURS" if pilot.get("verified_at") is not None else "LOGGED_HOURS"


def price(policy, agreed_value_cents, use_class, band, live_count):
    rate = calc.hull_rate_ppm(policy["base_hull_rate_ppm"], use_class,
                              policy["territorial_limit_code"], band)
    premium = calc.annual_hull_premium(agreed_value_cents, rate,
                                       policy["policy_type"], live_count)
    return rate, premium


def live_count_including_new(policy_id):
    return derive.live_schedule_count(policy_id) + 1


def rerate_schedule(schedule, policy, refresh_basis=False, pilot=None):
    """Recompute rate_ppm and hull_premium_cents in place; returns the old premium."""
    old_premium = schedule["hull_premium_cents"]
    if refresh_basis:
        if pilot is None:
            pilot = db.pilots[schedule["named_pilot_id"]]
        schedule["warranty_basis"] = basis_for(pilot)
        schedule["rated_pilot_band"] = calc.pilot_band(pilot, schedule["warranty_basis"], db.clock)
    live_count = derive.live_schedule_count(policy["id"])
    if schedule["coverage_status"] not in C.LIVE_COVERAGE:
        live_count += 1
    rate, premium = price(policy, schedule["agreed_value_cents"], schedule["use_class"],
                          schedule["rated_pilot_band"], live_count)
    schedule["rate_ppm"] = rate
    schedule["hull_premium_cents"] = premium
    return old_premium


def post_rerate_adjustment(schedule, policy, old_premium, memo):
    """The full annual difference of two rounded premiums; never apportioned."""
    delta = schedule["hull_premium_cents"] - old_premium
    if delta != 0 and policy["status"] == "BOUND":
        append_transaction(policy["id"], "RERATE_ADJUSTMENT", delta, db.clock, "ANNUAL", memo)
    return delta


# --- coverage / warranty cascades ---------------------------------------------

def suspend_for_breach(schedule):
    """Hops two and three of the four-hop cascade of PRD 2.8."""
    if schedule["coverage_status"] != "ACTIVE":
        return
    schedule["coverage_status"] = "SUSPENDED_WARRANTY"
    touch(schedule)
    for claim in derive.claims_of_schedule(schedule["id"]):
        if claim["adjustment_status"] in ("NOTIFIED", "INVESTIGATING", "RESERVED"):
            claim["adjustment_status"] = "COVERAGE_REFERRED"
            touch(claim)


def reinstate_cover(schedule):
    if schedule["coverage_status"] == "SUSPENDED_WARRANTY":
        schedule["coverage_status"] = "ACTIVE"
        touch(schedule)


def activate_schedule(schedule):
    """PENDING -> ACTIVE, immediately suspended again when the warranty is breached."""
    if schedule["coverage_status"] != "PENDING":
        return
    schedule["coverage_status"] = "ACTIVE"
    touch(schedule)
    if schedule["warranty_status"] == "BREACHED":
        suspend_for_breach(schedule)


# --- clock and expiry ---------------------------------------------------------

def expiry_sweep():
    for policy in ordered(db.policies):
        if policy["status"] != "BOUND":
            continue
        if policy["effective_to"] <= db.clock:
            policy["status"] = "EXPIRED"
            for schedule in derive.schedules_of_policy(policy["id"]):
                if schedule["coverage_status"] in C.LIVE_COVERAGE:
                    schedule["coverage_status"] = "REMOVED"
                    touch(schedule)
            touch(policy)


# --- gates shared by attachment and endorsement binding -----------------------

def overlaps_half_open(a_from, a_to, b_from, b_to):
    return a_from < b_to and b_from < a_to


def check_aircraft_overlap(aircraft_id, window_from, window_to, exclude_schedule_id=None):
    for other in derive.schedules_of_aircraft(aircraft_id):
        if exclude_schedule_id is not None and other["id"] == exclude_schedule_id:
            continue
        if other["coverage_status"] in ("REMOVED", "TOTAL_LOSS_SETTLED"):
            continue
        if overlaps_half_open(window_from, window_to,
                              other["effective_from"], other["effective_to"]):
            raise ApiError("ERR_AIRCRAFT_COVERAGE_OVERLAP")


def check_use_class(policy, operator, use_class):
    if use_class not in policy["permitted_use_classes"]:
        raise ApiError("ERR_USE_CLASS_NOT_PERMITTED")
    if use_class == "INSTRUCTIONAL":
        if operator["operator_type"] not in ("FLIGHT_SCHOOL", "FLYING_CLUB"):
            raise ApiError("ERR_USE_CLASS_NOT_PERMITTED")
    if use_class == "COMMERCIAL":
        if operator["operator_type"] != "AIR_CARRIER" or not operator["aoc_number"]:
            raise ApiError("ERR_USE_CLASS_NOT_PERMITTED")


def check_over_insurance(aircraft, reference_year, agreed_value_cents):
    ceiling = calc.over_insurance_ceiling(aircraft, reference_year)
    if agreed_value_cents > ceiling:
        raise ApiError("ERR_OVER_INSURED_VALUE")


def check_hull_aggregate(policy, prospective_total):
    if prospective_total > policy["hull_aggregate_limit_cents"]:
        raise ApiError("ERR_HULL_AGGREGATE_EXCEEDED")


def check_medical(pilot, start_of_cover):
    if pilot["medical_expires_at"] < start_of_cover:
        raise ApiError("ERR_PILOT_MEDICAL_EXPIRED")


def bound_placement_covering(policy_id, instant):
    for placement in derive.placements_of_policy(policy_id):
        if placement["status"] != "BOUND":
            continue
        if placement["coverage_from"] <= instant <= placement["coverage_to"]:
            return placement
    return None


def require_placement_covering(policy_id, instant):
    if bound_placement_covering(policy_id, instant) is None:
        raise ApiError("ERR_WAR_RISK_NOT_PLACED")


def schedule_is_live(schedule):
    return schedule["coverage_status"] in C.LIVE_COVERAGE


def require_live_schedule(schedule):
    if not schedule_is_live(schedule):
        raise ApiError("ERR_SCHEDULE_NOT_LIVE")


# --- claim helpers ------------------------------------------------------------

def select_assessment(claim_id):
    """Greatest assessed_at, then greatest repair estimate, then earliest created_at."""
    best = None
    for row in derive.assessments_of_claim(claim_id):
        if best is None:
            best = row
            continue
        candidate = (row["assessed_at"], row["repair_cost_estimate_cents"])
        current = (best["assessed_at"], best["repair_cost_estimate_cents"])
        if candidate > current:
            best = row
    return best


def recompute_claim_ctl(claim):
    rows = derive.assessments_of_claim(claim["id"])
    claim["assessment_count"] = len(rows)
    selected = select_assessment(claim["id"])
    if selected is None:
        return
    claim["ctl_ratio_ppm"] = selected["ctl_ratio_ppm"]
    claim["ctl_flag"] = selected["ctl_ratio_ppm"] >= C.CTL_THRESHOLD_PPM
    if claim["ctl_flag"] and claim["loss_type"] == "HULL_DAMAGE":
        claim["loss_type"] = "TOTAL_LOSS"


def unexpired_days(effective_date, policy):
    return util.day_diff(effective_date, policy["effective_to"])


def resolve_fk(body, name, getter):
    """Rank 6 sits above rank 7, so a present-but-unresolvable FK is a 404.

    An absent foreign key cannot be resolved at all and falls through to the
    rank-7 presence failure instead.
    """
    value = body.get(name, None)
    if value is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    return getter(value)


def optional_fk(body, name, getter):
    value = body.get(name, None)
    if value is None:
        return None
    return getter(value)
