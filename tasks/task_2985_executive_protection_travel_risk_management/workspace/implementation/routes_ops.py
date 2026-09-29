"""Advance work, protective details, vendors, engagements and incident response.

PRD 3.4 (advance progress), 3.5 (details and vendors), 3.8 (triage and join).
"""

from datetime import timedelta

from flask import Blueprint

import payload
import serializers
from auth import (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_PROTECTION_MANAGER,
    ROLE_SECURITY_ANALYST,
    ROLE_SECURITY_DIRECTOR,
    acting_role,
    endpoint,
)
from calc import (
    ADVANCE_ITEMS,
    ADVANCE_OUTCOMES,
    DETAIL_ROLES,
    NON_WAIVABLE_ITEMS,
    REST_BUFFER_HOURS,
    VENDOR_TYPES,
    check_in_interval_hours,
    detail_cost_cents,
    final_billable_hours,
    planned_billable_hours,
)
from derive import (
    active_overlapping_engagements,
    cancel_assignment,
    cascade_vendor_suspension,
    create_engagement_row,
    degrade_trip,
    get_assignment,
    get_engagement,
    get_leg,
    get_staff,
    get_vendor,
    recompute_advance_complete,
    recompute_advance_readiness,
    recompute_lead_agent_covered,
    try_recover_trip,
)
from envelope import list_response, object_response
from errors import ApiError
from store import (
    assignments_of_leg,
    assignments_of_trip,
    audit_row,
    legs_of_trip,
    store,
    touch,
    trip_of_leg,
)

bp = Blueprint("ops", __name__)

_READ_ROLES = (ROLE_SECURITY_ANALYST, ROLE_PROTECTION_MANAGER,
               ROLE_SECURITY_DIRECTOR, ROLE_COMPLIANCE_OFFICER)


def _require_live_trip(trip):
    """PRD 3.4 / 3.5: work may be recorded while the trip is neither denied nor
    closed."""
    if trip["approval_state"] == "DENIED" or trip["readiness_state"] == "CLOSED":
        raise ApiError("ERR_TRIP_INVALID_APPROVAL_STATE")


# ---------------------------------------------------------------------------
# Trip legs and advance work -- PRD 3.4
# ---------------------------------------------------------------------------


@bp.get("/exec-protection/trip-legs/<leg_id>")
@endpoint(*_READ_ROLES)
def read_trip_leg(leg_id):
    return object_response(serializers.trip_leg(get_leg(leg_id)))


@bp.post("/exec-protection/trip-legs/<leg_id>/advance-progress")
@endpoint(ROLE_SECURITY_ANALYST, ROLE_PROTECTION_MANAGER, ROLE_SECURITY_DIRECTOR)
def record_advance_progress(leg_id):
    data = payload.body()
    item_type = payload.enum_field(data, "item_type", ADVANCE_ITEMS)
    outcome = payload.enum_field(data, "outcome", ADVANCE_OUTCOMES)
    payload.string_field(data, "note", required=False, max_len=500, default=None,
                         nullable=True)

    leg = get_leg(leg_id)
    trip = trip_of_leg(leg)
    _require_live_trip(trip)

    # PRD 3.4 / 2.11 band (a): waiving is tightly held.
    if outcome == "WAIVED":
        if (acting_role() != ROLE_SECURITY_DIRECTOR
                or item_type in NON_WAIVABLE_ITEMS):
            raise ApiError("ERR_WAIVER_NOT_PERMITTED")

    target = ("completed_advance_items" if outcome == "COMPLETE"
              else "waived_advance_items")
    # Recording the same item twice is idempotent in the array.
    if item_type not in leg[target]:
        leg[target].append(item_type)
    recompute_advance_complete(leg)
    touch(leg)

    if recompute_advance_readiness(trip):
        touch(trip)
    try_recover_trip(trip)
    return object_response(serializers.trip_leg(leg))


# ---------------------------------------------------------------------------
# Protective-detail assignments -- PRD 3.5
# ---------------------------------------------------------------------------


@bp.post("/exec-protection/detail-assignments")
@endpoint(ROLE_PROTECTION_MANAGER)
def create_detail_assignment():
    data = payload.body()
    trip_leg_id = payload.id_field(data, "trip_leg_id")
    staff_id = payload.id_field(data, "staff_id")
    role_on_detail = payload.enum_field(data, "role_on_detail", DETAIL_ROLES)
    starts_at = payload.instant_field(data, "starts_at")
    ends_at = payload.instant_field(data, "ends_at")
    expected_trip_leg_version = payload.int_field(data, "expected_trip_leg_version")
    payload.require_interval(starts_at, ends_at)

    leg = get_leg(trip_leg_id)
    staff = get_staff(staff_id)
    trip = trip_of_leg(leg)
    _require_live_trip(trip)

    # PRD 2.8 / 2.11 item 10.
    if expected_trip_leg_version != leg["version"]:
        raise ApiError("ERR_STALE_TRIP_LEG_VERSION")

    # PRD 3.5 / 2.11 band (a): certification cover, then the rest buffer.
    if not staff["certification_expires_at"] > ends_at:
        raise ApiError("ERR_STAFF_CERTIFICATION_EXPIRED")
    buffer_delta = timedelta(hours=REST_BUFFER_HOURS)
    for neighbour in store.assignments.values():
        if neighbour["staff_id"] != staff_id or neighbour["status"] != "CONFIRMED":
            continue
        if (starts_at < neighbour["ends_at"] + buffer_delta
                and neighbour["starts_at"] < ends_at + buffer_delta):
            raise ApiError("ERR_STAFF_REST_BUFFER_CONFLICT")

    # PRD 3.5 / 2.11 band (c): the intelligence the detail is planned against.
    from derive import get_assessment
    assessment = get_assessment(trip["risk_assessment_id"])
    if assessment["status"] != "APPROVED":
        raise ApiError("ERR_ASSESSMENT_NOT_APPROVED")

    hours = planned_billable_hours(starts_at, ends_at)
    row = audit_row({
        "trip_leg_id": trip_leg_id,
        "staff_id": staff_id,
        "role_on_detail": role_on_detail,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "status": "CONFIRMED",
        "planned_billable_hours": hours,
        "actual_ends_at": None,
        "final_billable_hours": None,
        "cost_cents": detail_cost_cents(hours, staff["hourly_rate_cents"],
                                        role_on_detail),
        "cost_basis": "PROVISIONAL",
        "cancelled_reason": None,
    })
    store.assignments[row["id"]] = row
    staff["committed_detail_hours"] += hours
    touch(staff)
    recompute_lead_agent_covered(leg)
    touch(leg)
    try_recover_trip(trip)
    return object_response(serializers.detail_assignment(row), 201)


@bp.get("/exec-protection/detail-assignments")
@endpoint(*_READ_ROLES)
def list_detail_assignments():
    limit, offset = payload.pagination()
    rows = list(store.assignments.values())
    for name in ("trip_leg_id", "staff_id", "status"):
        wanted = payload.request.args.get(name)
        if wanted is not None:
            rows = [r for r in rows if r[name] == wanted]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]), reverse=True)
    page, total, has_more = payload.paginate(rows, limit, offset)
    return list_response([serializers.detail_assignment(r) for r in page],
                         limit, offset, total, has_more)


@bp.get("/exec-protection/detail-assignments/<assignment_id>")
@endpoint(*_READ_ROLES)
def read_detail_assignment(assignment_id):
    return object_response(
        serializers.detail_assignment(get_assignment(assignment_id)))


@bp.post("/exec-protection/detail-assignments/<assignment_id>/release")
@endpoint(ROLE_PROTECTION_MANAGER)
def release_detail_assignment(assignment_id):
    data = payload.body()
    actual_ends_at = payload.instant_field(data, "actual_ends_at")

    assignment = get_assignment(assignment_id)
    # PRD 2.11 item 5: a release's actual_ends_at against the assignment's
    # starts_at.
    payload.require_interval(assignment["starts_at"], actual_ends_at)
    if assignment["status"] != "CONFIRMED":
        raise ApiError("ERR_ASSIGNMENT_INVALID_STATE")

    staff = store.staff.get(assignment["staff_id"])
    hours = final_billable_hours(assignment["starts_at"], actual_ends_at)
    assignment["status"] = "RELEASED"
    assignment["actual_ends_at"] = actual_ends_at
    assignment["final_billable_hours"] = hours
    assignment["cost_cents"] = detail_cost_cents(
        hours, staff["hourly_rate_cents"], assignment["role_on_detail"])
    assignment["cost_basis"] = "FINAL"
    staff["committed_detail_hours"] -= assignment["planned_billable_hours"]
    staff["released_detail_hours"] += hours
    touch(staff)
    touch(assignment)

    leg = store.legs.get(assignment["trip_leg_id"])
    if leg is not None:
        was_covered = leg["lead_agent_covered"]
        recompute_lead_agent_covered(leg)
        touch(leg)
        trip = trip_of_leg(leg)
        if trip is not None and was_covered and not leg["lead_agent_covered"]:
            degrade_trip(trip)
    return object_response(serializers.detail_assignment(assignment))


# ---------------------------------------------------------------------------
# Vendors -- PRD 3.5
# ---------------------------------------------------------------------------


@bp.post("/exec-protection/vendors")
@endpoint(ROLE_PROTECTION_MANAGER, ROLE_SECURITY_DIRECTOR)
def register_vendor():
    data = payload.body()
    vendor_name = payload.string_field(data, "vendor_name", min_len=1, max_len=120,
                                       non_blank=True)
    vendor_type = payload.enum_field(data, "vendor_type", VENDOR_TYPES)
    country_code = payload.country_field(data, "country_code")
    max_concurrent_engagements = payload.int_field(
        data, "max_concurrent_engagements", minimum=1)
    sla_response_minutes = payload.int_field(data, "sla_response_minutes", minimum=1)
    hourly_rate_cents = payload.int_field(data, "hourly_rate_cents", minimum=1)
    retainer_cents = payload.int_field(data, "retainer_cents", minimum=0)

    row = audit_row({
        "vendor_name": vendor_name,
        "vendor_type": vendor_type,
        "country_code": country_code,
        "max_concurrent_engagements": max_concurrent_engagements,
        "sla_response_minutes": sla_response_minutes,
        "hourly_rate_cents": hourly_rate_cents,
        "retainer_cents": retainer_cents,
        "activation_status": "AVAILABLE",
        "committed_engagement_hours": 0,
        "suspension_reason": None,
    })
    store.vendors[row["id"]] = row
    return object_response(serializers.vendor(row), 201)


@bp.get("/exec-protection/vendors/<vendor_id>")
@endpoint(*_READ_ROLES)
def read_vendor(vendor_id):
    return object_response(serializers.vendor(get_vendor(vendor_id)))


@bp.post("/exec-protection/vendors/<vendor_id>/suspend")
@endpoint(ROLE_SECURITY_DIRECTOR)
def suspend_vendor(vendor_id):
    data = payload.body()
    suspension_reason = payload.string_field(data, "suspension_reason", min_len=1,
                                             max_len=500, non_blank=True)

    vendor = get_vendor(vendor_id)
    # PRD 3.5: suspending an already-suspended vendor is rejected.
    if vendor["activation_status"] != "AVAILABLE":
        raise ApiError("ERR_VENDOR_SUSPENDED")
    cascade_vendor_suspension(vendor, suspension_reason)
    return object_response(serializers.vendor(vendor))


# ---------------------------------------------------------------------------
# Vendor engagements -- PRD 3.5
# ---------------------------------------------------------------------------


@bp.post("/exec-protection/vendor-engagements")
@endpoint(ROLE_PROTECTION_MANAGER, ROLE_SECURITY_DIRECTOR)
def engage_vendor():
    data = payload.body()
    vendor_id = payload.id_field(data, "vendor_id")
    trip_leg_id = payload.id_field(data, "trip_leg_id")
    engagement_purpose = payload.enum_field(data, "engagement_purpose", VENDOR_TYPES)
    starts_at = payload.instant_field(data, "starts_at")
    ends_at = payload.instant_field(data, "ends_at")
    expected_vendor_version = payload.int_field(data, "expected_vendor_version")
    payload.require_interval(starts_at, ends_at)

    vendor = get_vendor(vendor_id)
    leg = get_leg(trip_leg_id)
    trip = trip_of_leg(leg)
    _require_live_trip(trip)
    # PRD 2.11 item 9: ERR_VENDOR_SUSPENDED sorts last among state preconditions.
    if vendor["activation_status"] != "AVAILABLE":
        raise ApiError("ERR_VENDOR_SUSPENDED")

    # PRD 2.8 / 2.11 item 10.
    if expected_vendor_version != vendor["version"]:
        raise ApiError("ERR_STALE_VENDOR_VERSION")

    # PRD 2.11 band (b): capacity before eligibility.
    if (active_overlapping_engagements(vendor_id, starts_at, ends_at)
            >= vendor["max_concurrent_engagements"]):
        raise ApiError("ERR_VENDOR_CAPACITY_EXCEEDED")
    if (engagement_purpose != vendor["vendor_type"]
            or vendor["country_code"] != leg["destination_country_code"]):
        raise ApiError("ERR_NO_ELIGIBLE_VENDOR")

    row = create_engagement_row(vendor, leg, engagement_purpose, starts_at, ends_at,
                                None)
    # PRD 3.5: engaging a local liaison vendor is how that advance item gets done.
    if engagement_purpose == "LOCAL_LIAISON":
        if "LOCAL_LIAISON" not in leg["completed_advance_items"]:
            leg["completed_advance_items"].append("LOCAL_LIAISON")
        recompute_advance_complete(leg)
        touch(leg)
        if recompute_advance_readiness(trip):
            touch(trip)
        try_recover_trip(trip)
    return object_response(serializers.vendor_engagement(row), 201)


@bp.get("/exec-protection/vendor-engagements")
@endpoint(*_READ_ROLES)
def list_vendor_engagements():
    limit, offset = payload.pagination()
    rows = list(store.engagements.values())
    for name in ("vendor_id", "trip_leg_id", "incident_id", "status"):
        wanted = payload.request.args.get(name)
        if wanted is not None:
            rows = [r for r in rows if r[name] == wanted]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]), reverse=True)
    page, total, has_more = payload.paginate(rows, limit, offset)
    return list_response([serializers.vendor_engagement(r) for r in page],
                         limit, offset, total, has_more)


@bp.get("/exec-protection/vendor-engagements/<engagement_id>")
@endpoint(*_READ_ROLES)
def read_vendor_engagement(engagement_id):
    return object_response(
        serializers.vendor_engagement(get_engagement(engagement_id)))


@bp.post("/exec-protection/vendor-engagements/<engagement_id>/complete")
@endpoint(ROLE_PROTECTION_MANAGER, ROLE_SECURITY_DIRECTOR)
def complete_vendor_engagement(engagement_id):
    engagement = get_engagement(engagement_id)
    if engagement["status"] != "ACTIVE":
        raise ApiError("ERR_ENGAGEMENT_INVALID_STATE")
    engagement["status"] = "COMPLETED"
    vendor = store.vendors.get(engagement["vendor_id"])
    if vendor is not None:
        vendor["committed_engagement_hours"] -= engagement["engagement_hours"]
        touch(vendor)
    touch(engagement)
    return object_response(serializers.vendor_engagement(engagement))


# ---------------------------------------------------------------------------
# Incident response: the triage fork and its join -- PRD 3.8
# ---------------------------------------------------------------------------

from calc import (  # noqa: E402  (grouped with the section it serves)
    INCIDENT_ACTIVE_STATUSES,
    RESPONSE_TRACKS,
    TRACK_ACTIVE_STATUS,
    TRACK_CAPABILITY,
    track_permitted,
)
from derive import (  # noqa: E402
    activation_window,
    get_incident,
    incident_response_cost_cents,
    leg_of_trip_by_sequence,
    select_vendor,
)
from store import engagements_of_incident, rating_for_country  # noqa: E402


@bp.post("/exec-protection/incidents/<incident_id>/triage")
@endpoint(ROLE_PROTECTION_MANAGER, ROLE_SECURITY_DIRECTOR)
def triage_incident(incident_id):
    data = payload.body()
    response_track = payload.enum_field(data, "response_track", RESPONSE_TRACKS)

    incident = get_incident(incident_id)
    if incident["status"] != "REPORTED":
        raise ApiError("ERR_INCIDENT_INVALID_STATE")

    # PRD 3.8: the fork's permission matrix.
    if not track_permitted(incident["incident_type"], incident["severity"],
                           response_track):
        raise ApiError("ERR_INCIDENT_TRACK_INCOMPATIBLE")

    trip = store.trips.get(incident["trip_id"])
    leg = leg_of_trip_by_sequence(incident["trip_id"],
                                  incident["affected_leg_sequence_no"])
    if leg is None:
        raise ApiError("ERR_TRIP_LEG_NOT_FOUND")

    # PRD 3.8: every track activates a vendor, chosen by the service.
    capability = TRACK_CAPABILITY[response_track]
    window_start, window_end = activation_window()
    vendor = select_vendor(capability, leg["destination_country_code"],
                           window_start, window_end)
    if vendor is None:
        raise ApiError("ERR_NO_ELIGIBLE_VENDOR")

    if response_track == "MEDEVAC":
        # PRD 3.8: the medical-evacuation branch carries an insurance gate the
        # other two do not.
        policy_id = trip["insurance_policy_id"]
        policy = store.policies.get(policy_id) if policy_id is not None else None
        if (policy is None or policy["status"] != "VERIFIED"
                or policy["policy_type"] != "MEDICAL_EVAC"):
            raise ApiError("ERR_INSURANCE_NOT_VERIFIED")
        rating = rating_for_country(leg["destination_country_code"])
        if (rating is not None
                and policy["coverage_cents"]
                < rating["insurance_required_coverage_cents"]):
            raise ApiError("ERR_INSURANCE_COVERAGE_INSUFFICIENT")

    incident["status"] = TRACK_ACTIVE_STATUS[response_track]
    incident["response_track"] = response_track
    incident["triaged_at"] = store.now()
    touch(incident)

    create_engagement_row(vendor, leg, capability, window_start, window_end,
                          incident["id"])

    if response_track == "EXTRACTION":
        # PRD 3.8: uniquely to this branch, the standing detail is stood down.
        now = store.now()
        for assignment in assignments_of_trip(trip["id"]):
            if assignment["status"] == "CONFIRMED" and assignment["starts_at"] > now:
                cancel_assignment(assignment, "EXTRACTION")

    degrade_trip(trip)
    trip["check_in_interval_hours"] = check_in_interval_hours(
        trip["duress_active"], "DEGRADED", trip["max_leg_risk_band"])
    if response_track == "SHELTER_IN_PLACE":
        trip["next_check_in_due_at"] = store.now() + timedelta(
            hours=trip["check_in_interval_hours"])
    touch(trip)
    return object_response(serializers.incident(incident))


@bp.post("/exec-protection/incidents/<incident_id>/resolve")
@endpoint(ROLE_PROTECTION_MANAGER, ROLE_SECURITY_DIRECTOR)
def resolve_incident(incident_id):
    data = payload.body()
    payload.string_field(data, "resolution_note", required=False, max_len=1000,
                         default=None, nullable=True)

    incident = get_incident(incident_id)
    if incident["status"] not in INCIDENT_ACTIVE_STATUSES:
        raise ApiError("ERR_INCIDENT_INVALID_STATE")
    # PRD 3.8: an engagement still ACTIVE blocks the join.
    for engagement in engagements_of_incident(incident["id"]):
        if engagement["status"] not in ("COMPLETED", "CANCELLED"):
            raise ApiError("ERR_INCIDENT_INVALID_STATE")

    incident["status"] = "RESOLVED"
    incident["resolved_at"] = store.now()
    touch(incident)
    return object_response(serializers.incident(incident))


@bp.post("/exec-protection/incidents/<incident_id>/close")
@endpoint(ROLE_SECURITY_DIRECTOR)
def close_incident(incident_id):
    incident = get_incident(incident_id)
    if incident["status"] != "RESOLVED":
        raise ApiError("ERR_INCIDENT_INVALID_STATE")
    incident["status"] = "CLOSED"
    incident["closed_at"] = store.now()
    # PRD 3.8: freeze the response cost.
    incident["response_cost_cents"] = incident_response_cost_cents(incident)
    touch(incident)
    return object_response(serializers.incident(incident))
