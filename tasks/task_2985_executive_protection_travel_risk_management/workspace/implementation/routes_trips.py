"""Trips, legs, the approval ladder, check-ins, incidents and settlement.

PRD 3.4, 3.6, 3.7, 3.8 (reporting) and 3.9 (close).
"""

from datetime import timedelta

from flask import Blueprint

import payload
import serializers
from auth import (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_EXECUTIVE,
    ROLE_PROTECTION_MANAGER,
    ROLE_SECURITY_ANALYST,
    ROLE_SECURITY_DIRECTOR,
    acting_id,
    acting_role,
    compares_to_staff_rows,
    endpoint,
    require_executive_owns,
)
from calc import (
    ALLOCATION_METHODS,
    CHECK_IN_KINDS,
    DURESS_CHECK_IN_HOURS,
    INCIDENT_TYPES,
    MISSED_CHECK_IN_THRESHOLD,
    TRIP_DECISIONS,
    TRIP_PURPOSES,
    check_in_interval_hours,
    level_rank,
    perquisite_rate,
    perquisite_split,
)
from derive import (
    cascade_trip_denial,
    degrade_trip,
    duress_affected_sequence_no,
    final_cost_cents,
    get_executive,
    get_policy,
    get_rating,
    get_trip,
    leg_of_trip_by_sequence,
    max_required_coverage_cents,
    provisional_cost_cents,
    recompute_advance_complete,
    recompute_leg_band,
    recompute_trip_band_and_level,
    recount_missed_check_ins,
)
from envelope import list_response, object_response
from errors import ApiError
from store import (
    assignments_of_trip,
    audit_row,
    checkins_of_trip,
    event_row,
    executive_of_trip,
    incidents_of_trip,
    legs_of_trip,
    rating_for_country,
    store,
    touch,
)
from util import ZERO_SCORE

bp = Blueprint("trips", __name__)

_TRIP_READ_ROLES = (ROLE_SECURITY_ANALYST, ROLE_PROTECTION_MANAGER,
                    ROLE_SECURITY_DIRECTOR, ROLE_COMPLIANCE_OFFICER,
                    ROLE_EXECUTIVE)


# ---------------------------------------------------------------------------
# Trip creation and reads -- PRD 3.4
# ---------------------------------------------------------------------------


@bp.post("/exec-protection/trips")
@endpoint(ROLE_PROTECTION_MANAGER)
def create_trip():
    data = payload.body()
    executive_id = payload.id_field(data, "executive_id")
    created_by_staff_id = payload.id_field(data, "created_by_staff_id")
    risk_assessment_id = payload.id_field(data, "risk_assessment_id")
    trip_purpose = payload.enum_field(data, "trip_purpose", TRIP_PURPOSES)
    primary_destination_country_code = payload.country_field(
        data, "primary_destination_country_code")
    depart_at = payload.instant_field(data, "depart_at")
    return_at = payload.instant_field(data, "return_at")
    insurance_policy_id = payload.id_field(data, "insurance_policy_id",
                                           required=False, nullable=True,
                                           default=None)
    cost_allocation_method = payload.enum_field(data, "cost_allocation_method",
                                                ALLOCATION_METHODS,
                                                required=False,
                                                default="PRORATA")
    payload.require_interval(depart_at, return_at)

    # PRD 2.6 / 2.11 item 6: existence resolved left to right.
    get_executive(executive_id)
    from derive import get_assessment, get_staff
    # PRD 2.6: created_by_staff_id is checked in the same existence pass.
    get_staff(created_by_staff_id)
    get_assessment(risk_assessment_id)
    get_rating(primary_destination_country_code)
    if insurance_policy_id is not None:
        get_policy(insurance_policy_id)

    # PRD 3.4: created_by_staff_id must equal the creating request's X-User-ID.
    if created_by_staff_id != acting_id():
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    # PRD 3.4 / 2.11 band (c): BUSINESS_ONLY is permitted only for business travel.
    if cost_allocation_method == "BUSINESS_ONLY" and trip_purpose != "BUSINESS_TRAVEL":
        raise ApiError("ERR_ALLOCATION_METHOD_NOT_PERMITTED")

    row = audit_row({
        "executive_id": executive_id,
        "created_by_staff_id": created_by_staff_id,
        "risk_assessment_id": risk_assessment_id,
        "insurance_policy_id": insurance_policy_id,
        "trip_purpose": trip_purpose,
        "primary_destination_country_code": primary_destination_country_code,
        "depart_at": depart_at,
        "return_at": return_at,
        "cost_allocation_method": cost_allocation_method,
        "approval_state": "DRAFT",
        "readiness_state": "NOT_READY",
        "required_approval_level": "MANAGER",
        "max_leg_risk_band": None,
        "provisional_security_cost_cents": 0,
        "total_security_cost_cents": 0,
        "perquisite_taxable_cents": 0,
        "business_borne_cents": 0,
        "perquisite_rate_applied": ZERO_SCORE,
        # PRD 3.4: seeded at 24 hours, the cadence for the lowest risk band.
        "check_in_interval_hours": 24,
        "next_check_in_due_at": None,
        "missed_check_in_count": 0,
        "duress_active": False,
        "briefing_ack_at": None,
        "denied_reason": None,
        "closed_at": None,
    })
    store.trips[row["id"]] = row
    return object_response(serializers.trip(row), 201)


@bp.get("/exec-protection/trips")
@endpoint(ROLE_SECURITY_ANALYST, ROLE_PROTECTION_MANAGER, ROLE_SECURITY_DIRECTOR,
          ROLE_COMPLIANCE_OFFICER)
def list_trips():
    limit, offset = payload.pagination()
    rows = list(store.trips.values())
    for name in ("executive_id", "created_by_staff_id", "risk_assessment_id",
                 "insurance_policy_id", "approval_state", "readiness_state"):
        wanted = payload.request.args.get(name)
        if wanted is not None:
            rows = [r for r in rows if r[name] == wanted]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]), reverse=True)
    page, total, has_more = payload.paginate(rows, limit, offset)
    return list_response([serializers.trip(r) for r in page],
                         limit, offset, total, has_more)


@bp.get("/exec-protection/trips/<trip_id>")
@endpoint(*_TRIP_READ_ROLES)
def read_trip(trip_id):
    trip = get_trip(trip_id)
    require_executive_owns(trip["executive_id"])
    return object_response(serializers.trip(trip))


# ---------------------------------------------------------------------------
# Legs -- PRD 3.4
# ---------------------------------------------------------------------------


@bp.post("/exec-protection/trips/<trip_id>/legs")
@endpoint(ROLE_PROTECTION_MANAGER)
def add_leg(trip_id):
    data = payload.body()
    sequence_no = payload.int_field(data, "sequence_no", minimum=1)
    destination_country_code = payload.country_field(data, "destination_country_code")
    arrive_at = payload.instant_field(data, "arrive_at")
    leg_depart_at = payload.instant_field(data, "depart_at")
    payload.require_interval(arrive_at, leg_depart_at)

    trip = get_trip(trip_id)
    get_rating(destination_country_code)

    # PRD 3.4: legs may only be added while approval_state is DRAFT.
    if trip["approval_state"] != "DRAFT":
        raise ApiError("ERR_TRIP_INVALID_APPROVAL_STATE")

    # PRD 2.11 band (b): window containment then sequence uniqueness.
    if arrive_at < trip["depart_at"] or leg_depart_at > trip["return_at"]:
        raise ApiError("ERR_LEG_OUTSIDE_TRIP_WINDOW")
    if leg_of_trip_by_sequence(trip_id, sequence_no) is not None:
        raise ApiError("ERR_DUPLICATE_LEG_SEQUENCE")

    row = audit_row({
        "trip_id": trip_id,
        "sequence_no": sequence_no,
        "destination_country_code": destination_country_code,
        "arrive_at": arrive_at,
        "depart_at": leg_depart_at,
        "leg_risk_band": None,
        "required_advance_items": [],
        "completed_advance_items": [],
        "waived_advance_items": [],
        "advance_complete": False,
        "lead_agent_covered": False,
    })
    store.legs[row["id"]] = row
    executive = executive_of_trip(trip)
    recompute_leg_band(row, trip, executive)
    # PRD 3.4: every leg creation re-derives the owning trip's maximum band and
    # its required approval level.
    recompute_trip_band_and_level(trip)
    touch(trip)
    return object_response(serializers.trip_leg(row), 201)


@bp.get("/exec-protection/trips/<trip_id>/legs")
@endpoint(*_TRIP_READ_ROLES)
def list_legs(trip_id):
    limit, offset = payload.pagination()
    trip = get_trip(trip_id)
    require_executive_owns(trip["executive_id"])
    rows = legs_of_trip(trip_id)
    page, total, has_more = payload.paginate(rows, limit, offset)
    return list_response([serializers.trip_leg(r) for r in page],
                         limit, offset, total, has_more)


# ---------------------------------------------------------------------------
# Submission -- PRD 3.6
# ---------------------------------------------------------------------------


@bp.post("/exec-protection/trips/<trip_id>/submit-for-approval")
@endpoint(ROLE_PROTECTION_MANAGER)
def submit_trip_for_approval(trip_id):
    trip = get_trip(trip_id)
    if trip["approval_state"] != "DRAFT":
        raise ApiError("ERR_TRIP_INVALID_APPROVAL_STATE")

    legs = legs_of_trip(trip_id)
    # PRD 3.6 / 2.11: safety first, then structure.
    for leg in legs:
        if not leg["advance_complete"]:
            raise ApiError("ERR_ADVANCE_WORK_INCOMPLETE")
    if not legs:
        raise ApiError("ERR_TRIP_HAS_NO_LEGS")

    from derive import get_assessment
    assessment = get_assessment(trip["risk_assessment_id"])
    if assessment["status"] != "APPROVED":
        raise ApiError("ERR_ASSESSMENT_NOT_APPROVED")

    policy_id = trip["insurance_policy_id"]
    policy = store.policies.get(policy_id) if policy_id is not None else None
    if policy is None or policy["status"] != "VERIFIED":
        raise ApiError("ERR_INSURANCE_NOT_VERIFIED")

    # PRD 3.6: insurance scope -- country exclusion and policy window.
    for leg in legs:
        if leg["destination_country_code"] in policy["excluded_country_codes"]:
            raise ApiError("ERR_INSURANCE_COUNTRY_EXCLUDED")
    if (policy["effective_from"] > trip["depart_at"]
            or policy["effective_to"] < trip["return_at"]):
        raise ApiError("ERR_INSURANCE_COUNTRY_EXCLUDED")

    if policy["coverage_cents"] < max_required_coverage_cents(trip):
        raise ApiError("ERR_INSURANCE_COVERAGE_INSUFFICIENT")

    # PRD 3.6: the fiscal gate, always last.
    executive = executive_of_trip(trip)
    provisional = provisional_cost_cents(trip)
    from derive import remaining_budget
    if provisional > remaining_budget(executive):
        raise ApiError("ERR_SECURITY_BUDGET_EXCEEDED")

    trip["provisional_security_cost_cents"] = provisional
    executive["committed_budget_cents"] += provisional
    touch(executive)

    trip["approval_state"] = "PENDING_REVIEW"
    interval = check_in_interval_hours(trip["duress_active"],
                                       trip["readiness_state"],
                                       trip["max_leg_risk_band"])
    trip["check_in_interval_hours"] = interval
    anchor = max(trip["depart_at"], store.now())
    trip["next_check_in_due_at"] = anchor + timedelta(hours=interval)
    touch(trip)
    return object_response(serializers.trip(trip))


# ---------------------------------------------------------------------------
# The decision fork -- PRD 3.6
# ---------------------------------------------------------------------------


def _reconcile_readiness_on_approval(trip):
    """PRD 3.6: a trip that arrives at APPROVED with full coverage becomes READY."""
    legs = legs_of_trip(trip["id"])
    covered = legs and all(leg["advance_complete"] and leg["lead_agent_covered"]
                           for leg in legs)
    if covered and trip["readiness_state"] == "ADVANCE_IN_PROGRESS":
        trip["readiness_state"] = "READY"
        anchor = max(trip["depart_at"], store.now())
        trip["next_check_in_due_at"] = anchor + timedelta(
            hours=trip["check_in_interval_hours"])


@bp.post("/exec-protection/trips/<trip_id>/decision")
@endpoint(ROLE_SECURITY_DIRECTOR, ROLE_COMPLIANCE_OFFICER)
def decide_trip(trip_id):
    data = payload.body()
    decision = payload.enum_field(data, "decision", TRIP_DECISIONS)
    denied_reason = payload.string_field(data, "denied_reason", required=False,
                                        max_len=500, default=None, nullable=True)
    # PRD 3.6: a DENY decision requires denied_reason of 1 to 500 characters.
    if decision == "DENY":
        if denied_reason is None or len(denied_reason) < 1:
            raise ApiError("ERR_INVALID_REQUEST")

    trip = get_trip(trip_id)

    # PRD 2.9 / 2.11 item 8: segregation of duties, then the approval stage.
    # A ComplianceOfficer's X-User-ID is opaque and is never compared to a
    # persisted staff identifier (PRD 2.1).
    if compares_to_staff_rows() and acting_id() == trip["created_by_staff_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    role = acting_role()
    state = trip["approval_state"]
    if role == ROLE_SECURITY_DIRECTOR and state == "PENDING_COMPLIANCE":
        raise ApiError("ERR_APPROVAL_LEVEL_MISMATCH")
    if role == ROLE_COMPLIANCE_OFFICER and state == "PENDING_REVIEW":
        raise ApiError("ERR_APPROVAL_LEVEL_MISMATCH")

    # PRD 2.11 item 9: state preconditions.
    if state not in ("PENDING_REVIEW", "PENDING_COMPLIANCE"):
        raise ApiError("ERR_TRIP_INVALID_APPROVAL_STATE")

    if decision == "DENY":
        cascade_trip_denial(trip, denied_reason)
        return object_response(serializers.trip(trip))

    # An APPROVE from PENDING_REVIEW either lands on APPROVED in one hop or
    # steps across to PENDING_COMPLIANCE (PRD 3.6).
    direct = (state == "PENDING_COMPLIANCE"
              or trip["required_approval_level"] != "DIRECTOR_AND_COMPLIANCE")
    if (state == "PENDING_REVIEW" and direct
            and trip["readiness_state"] not in ("READY", "ADVANCE_IN_PROGRESS")):
        raise ApiError("ERR_TRIP_INVALID_APPROVAL_STATE")

    # PRD 2.11 band (a): the briefing acknowledgement.
    if trip["briefing_ack_at"] is None:
        raise ApiError("ERR_BRIEFING_NOT_ACKNOWLEDGED")

    if state == "PENDING_COMPLIANCE":
        # PRD 3.6: compliance re-verifies the allocation against the purpose.
        if (trip["cost_allocation_method"] == "BUSINESS_ONLY"
                and trip["trip_purpose"] != "BUSINESS_TRAVEL"):
            raise ApiError("ERR_ALLOCATION_METHOD_NOT_PERMITTED")
        trip["approval_state"] = "APPROVED"
        _reconcile_readiness_on_approval(trip)
    elif direct:
        trip["approval_state"] = "APPROVED"
        _reconcile_readiness_on_approval(trip)
    else:
        trip["approval_state"] = "PENDING_COMPLIANCE"
    touch(trip)
    return object_response(serializers.trip(trip))


@bp.post("/exec-protection/trips/<trip_id>/briefing-ack")
@endpoint(ROLE_EXECUTIVE)
def acknowledge_briefing(trip_id):
    trip = get_trip(trip_id)
    require_executive_owns(trip["executive_id"])
    # PRD 3.6: permitted only while the trip awaits a decision.
    if trip["approval_state"] not in ("PENDING_REVIEW", "PENDING_COMPLIANCE"):
        raise ApiError("ERR_TRIP_INVALID_APPROVAL_STATE")
    trip["briefing_ack_at"] = store.now()
    touch(trip)
    return object_response(serializers.trip(trip))


# ---------------------------------------------------------------------------
# Check-ins, the consent boundary and the duress chain -- PRD 3.7
# ---------------------------------------------------------------------------


@bp.post("/exec-protection/trips/<trip_id>/check-ins")
@endpoint(ROLE_EXECUTIVE)
def file_check_in(trip_id):
    data = payload.body()
    kind = payload.enum_field(data, "kind", CHECK_IN_KINDS)
    location_country_code = payload.country_field(data, "location_country_code",
                                                  required=False, default=None)
    note = payload.string_field(data, "note", required=False, max_len=500,
                                default=None, nullable=True)

    trip = get_trip(trip_id)
    require_executive_owns(trip["executive_id"])
    # PRD 3.7: permitted only while APPROVED and READY or DEGRADED.
    if (trip["approval_state"] != "APPROVED"
            or trip["readiness_state"] not in ("READY", "DEGRADED")):
        raise ApiError("ERR_TRIP_INVALID_APPROVAL_STATE")

    executive = executive_of_trip(trip)
    reported_at = store.now()

    # PRD 3.7: the consent boundary, evaluated per check-in.
    expires_at = executive["consent_expires_at"]
    if expires_at is not None and expires_at <= reported_at:
        consent_scope_snapshot = "NONE"
    else:
        consent_scope_snapshot = executive["consent_scope"]
    if consent_scope_snapshot != "NONE":
        recorded_location = location_country_code
        location_withheld = False
    else:
        # The reported value is never persisted outside the consent boundary.
        recorded_location = None
        location_withheld = location_country_code is not None

    # PRD 3.7: lateness is judged against the due instant in force beforehand.
    prior_due = trip["next_check_in_due_at"]
    late = (kind == "SCHEDULED" and prior_due is not None
            and reported_at > prior_due)

    row = event_row({
        "trip_id": trip_id,
        "kind": kind,
        "reported_at": reported_at,
        "location_country_code": recorded_location,
        "recorded_location_country_code": recorded_location,
        "location_withheld": location_withheld,
        "consent_scope_snapshot": consent_scope_snapshot,
        "late": late,
        "note": note,
    })
    store.checkins[row["id"]] = row
    recount_missed_check_ins(trip)

    # PRD 3.7: the due instant is re-anchored according to the kind.
    if kind == "SCHEDULED":
        trip["next_check_in_due_at"] = reported_at + timedelta(
            hours=trip["check_in_interval_hours"])
    elif kind == "DURESS":
        trip["next_check_in_due_at"] = reported_at + timedelta(
            hours=DURESS_CHECK_IN_HOURS)

    # PRD 3.7: two missed contacts are the escalation threshold.
    if (trip["missed_check_in_count"] >= MISSED_CHECK_IN_THRESHOLD
            and trip["readiness_state"] == "READY"):
        degrade_trip(trip)

    if kind == "DURESS":
        # Cascade E (PRD 2.12, 3.7).
        trip["duress_active"] = True
        trip["check_in_interval_hours"] = DURESS_CHECK_IN_HOURS
        degrade_trip(trip)
        trip["check_in_interval_hours"] = DURESS_CHECK_IN_HOURS
        trip["next_check_in_due_at"] = reported_at + timedelta(
            hours=DURESS_CHECK_IN_HOURS)
        incident = audit_row({
            "trip_id": trip_id,
            "affected_leg_sequence_no": duress_affected_sequence_no(trip),
            "incident_type": "UNREST",
            "severity": 5,
            "status": "REPORTED",
            "response_track": None,
            "duress_flag": True,
            "narrative": "Duress check-in filed by the protectee.",
            "opened_at": reported_at,
            "triaged_at": None,
            "resolved_at": None,
            "closed_at": None,
            "response_cost_cents": 0,
        })
        store.incidents[incident["id"]] = incident
    touch(trip)
    return object_response(serializers.check_in(row), 201)


@bp.get("/exec-protection/trips/<trip_id>/check-ins")
@endpoint(ROLE_PROTECTION_MANAGER, ROLE_SECURITY_DIRECTOR, ROLE_COMPLIANCE_OFFICER,
          ROLE_EXECUTIVE)
def list_check_ins(trip_id):
    limit, offset = payload.pagination()
    trip = get_trip(trip_id)
    require_executive_owns(trip["executive_id"])
    rows = checkins_of_trip(trip_id)
    kind = payload.request.args.get("kind")
    if kind is not None:
        rows = [r for r in rows if r["kind"] == kind]
    # PRD 4: newest reported_at first.
    rows.sort(key=lambda r: (r["reported_at"], r["_seq"]), reverse=True)
    page, total, has_more = payload.paginate(rows, limit, offset)
    return list_response([serializers.check_in(r) for r in page],
                         limit, offset, total, has_more)


# ---------------------------------------------------------------------------
# Incident reporting -- PRD 3.8
# ---------------------------------------------------------------------------


@bp.post("/exec-protection/trips/<trip_id>/incidents")
@endpoint(ROLE_PROTECTION_MANAGER, ROLE_SECURITY_DIRECTOR)
def report_incident(trip_id):
    data = payload.body()
    affected_leg_sequence_no = payload.int_field(data, "affected_leg_sequence_no",
                                                minimum=1)
    incident_type = payload.enum_field(data, "incident_type", INCIDENT_TYPES)
    severity = payload.int_field(data, "severity", minimum=1, maximum=5)
    narrative = payload.string_field(data, "narrative", min_len=1, max_len=1000)

    trip = get_trip(trip_id)
    # PRD 2.6: an incident report whose affected_leg_sequence_no does not resolve
    # to a leg of the addressed trip is an ERR_INCIDENT_NOT_FOUND condition.
    if leg_of_trip_by_sequence(trip_id, affected_leg_sequence_no) is None:
        raise ApiError("ERR_INCIDENT_NOT_FOUND")
    if (trip["approval_state"] != "APPROVED"
            or trip["readiness_state"] not in ("READY", "DEGRADED")):
        raise ApiError("ERR_TRIP_INVALID_APPROVAL_STATE")

    row = audit_row({
        "trip_id": trip_id,
        "affected_leg_sequence_no": affected_leg_sequence_no,
        "incident_type": incident_type,
        "severity": severity,
        "status": "REPORTED",
        "response_track": None,
        "duress_flag": False,
        "narrative": narrative,
        "opened_at": store.now(),
        "triaged_at": None,
        "resolved_at": None,
        "closed_at": None,
        "response_cost_cents": 0,
    })
    store.incidents[row["id"]] = row
    # PRD 3.8: merely reporting an incident degrades the trip, and only when it
    # was not already DEGRADED.
    degrade_trip(trip)
    return object_response(serializers.incident(row), 201)


@bp.get("/exec-protection/trips/<trip_id>/incidents")
@endpoint(ROLE_PROTECTION_MANAGER, ROLE_SECURITY_DIRECTOR, ROLE_COMPLIANCE_OFFICER)
def list_incidents(trip_id):
    limit, offset = payload.pagination()
    get_trip(trip_id)
    rows = incidents_of_trip(trip_id)
    for name in ("status", "incident_type"):
        wanted = payload.request.args.get(name)
        if wanted is not None:
            rows = [r for r in rows if r[name] == wanted]
    # PRD 4: newest opened_at first.
    rows.sort(key=lambda r: (r["opened_at"], r["_seq"]), reverse=True)
    page, total, has_more = payload.paginate(rows, limit, offset)
    return list_response([serializers.incident(r) for r in page],
                         limit, offset, total, has_more)


# ---------------------------------------------------------------------------
# Settlement -- PRD 3.9
# ---------------------------------------------------------------------------


@bp.post("/exec-protection/trips/<trip_id>/close")
@endpoint(ROLE_PROTECTION_MANAGER)
def close_trip(trip_id):
    trip = get_trip(trip_id)
    if (trip["approval_state"] != "APPROVED"
            or trip["readiness_state"] not in ("READY", "DEGRADED")):
        raise ApiError("ERR_TRIP_INVALID_APPROVAL_STATE")
    # PRD 3.9: the trip window must have ended, an equal instant passing.
    if store.now() < trip["return_at"]:
        raise ApiError("ERR_TRIP_NOT_ENDED")
    for incident in incidents_of_trip(trip_id):
        if incident["status"] != "CLOSED":
            raise ApiError("ERR_OPEN_INCIDENTS_BLOCK_CLOSE")
    for assignment in assignments_of_trip(trip_id):
        if assignment["status"] == "CONFIRMED":
            raise ApiError("ERR_ASSIGNMENTS_NOT_SETTLED")

    executive = executive_of_trip(trip)
    total = final_cost_cents(trip)
    trip["total_security_cost_cents"] = total

    # PRD 3.9: step one reads the prior disclosure, pinned strictly before the
    # step-five roll-up.
    prior_disclosure = executive["annual_disclosed_perquisite_cents"]
    rate = perquisite_rate(prior_disclosure, trip["cost_allocation_method"])
    taxable, business = perquisite_split(total, rate)
    trip["perquisite_taxable_cents"] = taxable
    trip["business_borne_cents"] = business
    trip["perquisite_rate_applied"] = rate
    executive["annual_disclosed_perquisite_cents"] = prior_disclosure + taxable
    executive["business_borne_security_cents"] += business

    # PRD 3.9: the ledgers settle in one pass.
    executive["committed_budget_cents"] -= trip["provisional_security_cost_cents"]
    executive["spent_budget_cents"] += total
    was_degraded = trip["readiness_state"] == "DEGRADED"
    trip["readiness_state"] = "CLOSED"
    trip["closed_at"] = store.now()
    trip["next_check_in_due_at"] = None
    if was_degraded:
        executive["open_degraded_trip_count"] -= 1
    touch(executive)
    touch(trip)
    return object_response(serializers.trip(trip))
