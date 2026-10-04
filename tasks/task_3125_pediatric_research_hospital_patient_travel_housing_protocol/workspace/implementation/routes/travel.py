"""Travel arrangement endpoints: confirmation, disbursement, reversal
(PRD §3.6)."""

from flask import Blueprint

from db import DB, parse_iso, touch
from datetime import timedelta
from errors import ApiError
from http_util import body_json, required, require_role
from response import success_object
from routes._common import arg, filtered, list_response, ordered
from services import (
    cents_ceil, current_pledge, fund_add_patient_support, fund_add_research,
    get_or_404, leg_billed_days,
    protocol_for_enrollment, protocol_is_frozen, referral_for_enrollment,
    recompute_protocol_committed, research_day_accrual, resolve_leg_cost,
    review_lock_active, serialize_travel,
)

bp = Blueprint("travel", __name__)

COVERAGE_VALIDITY_DAYS = 30


def _find_fund(leg):
    enrollment = DB["enrollments"].get(leg["enrollment_id"])
    protocol = protocol_for_enrollment(enrollment) if enrollment else None
    if protocol is None:
        return None, None
    return protocol, DB["funds"].get(protocol["fund_id"])


def _shared_instant(leg, candidate):
    """True when two travel windows touch on the arrival boundary.

    PRD §3.6: confirmation refuses a same-enrollment, same-mode leg that
    "collide[s] on the arrival boundary", so a window whose departure equals the
    other's return (or whose return equals the other's departure) still collides.
    """
    if candidate["id"] == leg["id"]:
        return False
    if candidate["enrollment_id"] != leg["enrollment_id"]:
        return False
    if candidate["mode"] != leg["mode"]:
        return False
    if candidate["status"] not in ("CONFIRMED", "DISBURSED"):
        return False
    start = parse_iso(leg["departure_at"])
    end = parse_iso(leg["return_at"]) if leg.get("return_at") else start
    other_start = parse_iso(candidate["departure_at"])
    other_end = parse_iso(candidate["return_at"]) if candidate.get("return_at") else other_start
    return start <= other_end and other_start <= end


def _overlaps_by_a_day(leg, candidate):
    """True when two windows overlap by a day or more.

    PRD §3.6: disbursement refuses a confirmed or disbursed leg for the same
    enrollment and mode whose window "overlap[s] this leg's window by a day or
    more" — touching on a boundary is not yet an overlap.
    """
    if candidate["id"] == leg["id"]:
        return False
    if candidate["enrollment_id"] != leg["enrollment_id"]:
        return False
    if candidate["mode"] != leg["mode"]:
        return False
    if candidate["status"] not in ("CONFIRMED", "DISBURSED"):
        return False
    start = parse_iso(leg["departure_at"])
    end = parse_iso(leg["return_at"]) if leg.get("return_at") else start
    other_start = parse_iso(candidate["departure_at"])
    other_end = parse_iso(candidate["return_at"]) if candidate.get("return_at") else other_start
    return start < other_end and other_start < end


@bp.get("/programs/travel-arrangements")
def list_travel():
    require_role("Any")
    enrollment_id = arg("enrollment_id")
    status = arg("status")
    mode = arg("mode")
    rows = ordered(DB["travel_arrangements"].values())
    rows = filtered(rows, enrollment_id=enrollment_id, status=status, mode=mode)
    return list_response(rows, serialize_travel)


@bp.get("/programs/travel-arrangements/<travel_id>")
def get_travel(travel_id):
    require_role("Any")
    leg = get_or_404("travel_arrangements", travel_id)
    return success_object(serialize_travel(leg), 200)


@bp.post("/programs/travel-arrangements/<travel_id>/confirm")
def confirm_travel(travel_id):
    require_role("PatientSupportOfficer")
    leg = get_or_404("travel_arrangements", travel_id)
    enrollment = get_or_404("enrollments", leg["enrollment_id"])
    protocol = protocol_for_enrollment(enrollment)
    body_json()

    if leg["status"] != "REQUESTED":
        raise ApiError("ERR_TRAVEL_NOT_REQUESTED")
    if not (2 <= int(leg["traveler_count"]) <= 6):
        raise ApiError("ERR_TRAVELER_COUNT_RANGE")
    if protocol is None or not (protocol["status"] == "OPEN"
                                and not protocol_is_frozen(protocol)):
        raise ApiError("ERR_TRAVEL_ELIGIBILITY_NOT_CONFIRMED")
    for candidate in DB["travel_arrangements"].values():
        if _shared_instant(leg, candidate):
            raise ApiError("ERR_TRAVEL_LEG_OVERLAP")

    leg["status"] = "CONFIRMED"
    from db import now_iso
    leg["eligibility_confirmed_at"] = now_iso()
    referral = referral_for_enrollment(enrollment)
    fund = DB["funds"].get(protocol["fund_id"]) if protocol else None
    if fund is not None:
        leg["fund_patient_support_balance_cents"] = fund["patient_support_balance_cents"]
        leg["fund_research_balance_cents"] = fund["research_balance_cents"]
    touch(leg)
    return success_object(serialize_travel(leg), 200)


@bp.post("/programs/travel-arrangements/<travel_id>/disburse")
def disburse_travel(travel_id):
    require_role("PatientSupportOfficer")
    leg = get_or_404("travel_arrangements", travel_id)
    enrollment = get_or_404("enrollments", leg["enrollment_id"])
    protocol = protocol_for_enrollment(enrollment)
    referral = referral_for_enrollment(enrollment)
    body_json()

    if leg["status"] != "CONFIRMED":
        raise ApiError("ERR_TRAVEL_NOT_CONFIRMED")

    from db import clock, now_iso
    stamped = parse_iso(leg["eligibility_confirmed_at"])
    if clock() >= stamped + timedelta(days=COVERAGE_VALIDITY_DAYS):
        raise ApiError("ERR_TRAVEL_COVERAGE_EXPIRED")
    if int(leg["family_day_units"]) < 1:
        raise ApiError("ERR_INVALID_REQUEST")
    for candidate in DB["travel_arrangements"].values():
        if _overlaps_by_a_day(leg, candidate):
            raise ApiError("ERR_TRAVEL_LEG_OVERLAP")

    cost = resolve_leg_cost(leg, referral)
    leg["transport_cost_cents"] = cost
    leg["status"] = "DISBURSED"

    if protocol is not None:
        fund = DB["funds"].get(protocol["fund_id"])
        if fund is not None:
            fund_add_patient_support(fund, -cost)
            # PRD §3.6: a disbursed travel leg on a protocol that currently carries
            # a non-operational review lock also credits research by seven and a
            # half percent of the leg's transport cost, rounded up. Every leg here
            # is a travel arrangement, so the leg-mode qualifier is satisfied.
            if review_lock_active(protocol):
                fund_add_research(fund, cents_ceil(0.075, cost))
            leg["fund_patient_support_balance_cents"] = fund["patient_support_balance_cents"]
            leg["fund_research_balance_cents"] = fund["research_balance_cents"]
        recompute_protocol_committed(protocol)
        touch(protocol)

    days = leg_billed_days(leg)
    pledge = current_pledge(enrollment)
    if pledge is not None:
        pledge["covered_days"] = int(pledge["covered_days"]) + days
        from services import recompute_pledge_derived
        recompute_pledge_derived(pledge, enrollment, referral, protocol)
        touch(pledge)

    touch(leg)
    return success_object(serialize_travel(leg), 200)


@bp.post("/programs/travel-arrangements/<travel_id>/reverse-disbursement")
def reverse_disbursement(travel_id):
    require_role("PatientSupportOfficer")
    leg = get_or_404("travel_arrangements", travel_id)
    enrollment = get_or_404("enrollments", leg["enrollment_id"])
    protocol = protocol_for_enrollment(enrollment)
    referral = referral_for_enrollment(enrollment)
    data = body_json()
    required(data, "reversal_reason", "str")

    if leg["status"] != "DISBURSED":
        raise ApiError("ERR_INVALID_STATE")

    cost = int(leg["transport_cost_cents"])

    # PRD §3.6: the reversal "reduces the protocol's `committed_cents` by the
    # leg's research-day accrual, ... resets `transport_cost_cents` to zero, and
    # ends the leg at `CANCELLED`". The leg must already be out of `DISBURSED`
    # status before the accrual is recomputed, or the reversal would leave its
    # own charge behind in the counter.
    leg["transport_cost_cents"] = 0
    leg["status"] = "CANCELLED"

    if protocol is not None:
        fund = DB["funds"].get(protocol["fund_id"])
        if fund is not None:
            fund_add_patient_support(fund, cost)
            leg["fund_patient_support_balance_cents"] = fund["patient_support_balance_cents"]
            leg["fund_research_balance_cents"] = fund["research_balance_cents"]
        recompute_protocol_committed(protocol)
        touch(protocol)

    pledge = current_pledge(enrollment)
    if pledge is not None:
        pledge["covered_days"] = max(
            0, int(pledge["covered_days"]) - leg_billed_days(leg))
        from services import recompute_pledge_derived
        recompute_pledge_derived(pledge, enrollment, referral, protocol)
        touch(pledge)

    touch(leg)
    return success_object(serialize_travel(leg), 200)


@bp.post("/programs/travel-arrangements/<travel_id>/cancel")
def cancel_travel(travel_id):
    require_role("PatientSupportOfficer")
    leg = get_or_404("travel_arrangements", travel_id)
    body_json()
    if leg["status"] not in ("REQUESTED", "CONFIRMED"):
        raise ApiError("ERR_TRAVEL_NOT_CANCELLABLE")
    # PRD §3.6: a plain cancellation "reverses no fee" — the leg carries no
    # disbursed transport cost, so it is retired with the cost at zero.
    leg["transport_cost_cents"] = 0
    leg["status"] = "CANCELLED"
    touch(leg)
    return success_object(serialize_travel(leg), 200)