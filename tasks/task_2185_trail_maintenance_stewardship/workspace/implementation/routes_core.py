"""Land managers, volunteers, trail segments, the logical clock and weather."""

from flask import Blueprint, request

import calc
import domain
import store
import validation as v
from auth import ALL_ROLES, require
from envelope import created, ok, paginate
from errors import fail
from store import new_entity, touch

bp = Blueprint("core", __name__)

SURFACE_CLASSES = ("NATIVE_SOIL", "GRAVEL", "BOARDWALK", "ROCK")
TRAFFIC_CLASSES = ("LIGHT", "MODERATE", "HEAVY")
POSTURES = ("OPEN", "HAZARD_RESTRICTED", "WET_RESTRICTED", "SEASONAL_CLOSED", "INCIDENT_CLOSED")
ADOPTION_STATUSES = ("UNADOPTED", "ADOPTED")


def enum_filter(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' is not a declared member." % name)
    return value


def plain_filter(name):
    return request.args.get(name)


# ---------------------------------------------------------------------------
# LandManager
# ---------------------------------------------------------------------------
@bp.post("/land-managers")
@require("StewardshipCoordinator")
def create_land_manager():
    data = v.body()
    agency_name = v.req_str(data, "agency_name")
    jurisdiction_code = v.req_str(data, "jurisdiction_code")
    if not 1 <= len(jurisdiction_code) <= 40:
        fail("ERR_INVALID_REQUEST", "jurisdiction_code must be 1..40 characters.")
    permit_required = v.opt_bool(data, "permit_required", True)
    permit_lead_days = v.opt_int(data, "permit_lead_days", 14, minimum=0)
    max_party_size = v.opt_int(data, "max_party_size", 20, minimum=1)
    wet_threshold_index = v.opt_num(data, "wet_threshold_index", 0.65, minimum=0.0, maximum=1.0)
    requires_engineering_review = v.opt_bool(data, "requires_engineering_review", False)
    requires_certified_sawyer = v.opt_bool(data, "requires_certified_sawyer", True)

    for row in store.land_managers.values():
        if row["jurisdiction_code"] == jurisdiction_code:
            fail("ERR_INVALID_REQUEST", "jurisdiction_code must be unique.")

    manager = new_entity({
        "agency_name": agency_name,
        "jurisdiction_code": jurisdiction_code,
        "permit_required": permit_required,
        "permit_lead_days": permit_lead_days,
        "max_party_size": max_party_size,
        "wet_threshold_index": float(wet_threshold_index),
        "requires_engineering_review": requires_engineering_review,
        "requires_certified_sawyer": requires_certified_sawyer,
        "policy_version": 1,
        "adopted_segment_count": 0,
    })
    store.land_managers[manager["id"]] = manager
    return created(domain.s_manager(manager))


@bp.get("/land-managers/<entity_id>")
@require(*ALL_ROLES)
def read_land_manager(entity_id):
    return ok(domain.s_manager(domain.get_land_manager(entity_id)))


# ---------------------------------------------------------------------------
# VolunteerProfile
# ---------------------------------------------------------------------------
@bp.post("/volunteers")
@require("StewardshipCoordinator")
def create_volunteer():
    data = v.body()
    full_name = v.req_str(data, "full_name")
    email = v.req_str(data, "email")
    waiver_signed_on = v.opt_date(data, "waiver_signed_on")
    certifications = v.opt_enum_array(data, "certifications", calc.CERTIFICATIONS, [])
    first_aid_expires_on = v.opt_date(data, "first_aid_expires_on")

    for row in store.volunteers.values():
        if row["email"] == email:
            fail("ERR_INVALID_REQUEST", "email must be unique.")

    waiver_expires_on = None
    if waiver_signed_on is not None:
        from datetime import timedelta
        waiver_expires_on = waiver_signed_on + timedelta(days=365)

    volunteer = new_entity({
        "full_name": full_name,
        "email": email,
        "waiver_signed_on": store.fmt_date(waiver_signed_on),
        "waiver_expires_on": store.fmt_date(waiver_expires_on),
        "certifications": list(certifications or []),
        "first_aid_expires_on": store.fmt_date(first_aid_expires_on),
        "skill_class": calc.skill_class(certifications),
        "lifetime_credited_hours": 0,
        "pending_hours": 0,
        "verified_hours": 0,
        "certified_hours": 0,
        "active_registration_count": 0,
    })
    store.volunteers[volunteer["id"]] = volunteer
    return created(domain.s_volunteer(volunteer))


@bp.get("/volunteers/<entity_id>")
@require(*ALL_ROLES)
def read_volunteer(entity_id):
    return ok(domain.s_volunteer(domain.get_volunteer(entity_id)))


# ---------------------------------------------------------------------------
# TrailSegment
# ---------------------------------------------------------------------------
@bp.post("/trail-segments")
@require("StewardshipCoordinator", "LandManagerOfficer")
def create_segment():
    data = v.body()
    land_manager_id = v.req_id(data, "land_manager_id")
    name = v.req_str(data, "name")
    length_miles = v.req_num(data, "length_miles", exclusive_min=0)
    surface_class = v.req_enum(data, "surface_class", SURFACE_CLASSES)
    traffic_class = v.opt_enum(data, "traffic_class", TRAFFIC_CLASSES, "MODERATE")
    start_mmdd = v.opt_mmdd(data, "seasonal_closure_start_mmdd")
    end_mmdd = v.opt_mmdd(data, "seasonal_closure_end_mmdd")

    domain.get_land_manager(land_manager_id)

    segment = new_entity({
        "land_manager_id": land_manager_id,
        "name": name,
        "length_miles": float(length_miles),
        "surface_class": surface_class,
        "traffic_class": traffic_class,
        "seasonal_closure_start_mmdd": start_mmdd,
        "seasonal_closure_end_mmdd": end_mmdd,
        "latest_soil_moisture_index": None,
        "latest_moisture_observed_at": None,
        "hazard_index": 0,
        "escalated_hazard_count": 0,
        "open_severe_incident_count": 0,
        "posture": "OPEN",
        "adoption_status": "UNADOPTED",
    })
    store.segments[segment["id"]] = segment
    segment["posture"] = domain.compute_posture(segment)
    return created(domain.s_segment(segment))


@bp.get("/trail-segments/<entity_id>")
@require(*ALL_ROLES)
def read_segment(entity_id):
    return ok(domain.s_segment(domain.get_segment(entity_id)))


@bp.get("/trail-segments")
@require(*ALL_ROLES)
def list_segments():
    land_manager_id = plain_filter("land_manager_id")
    posture = enum_filter("posture", POSTURES)
    adoption_status = enum_filter("adoption_status", ADOPTION_STATUSES)
    rows = store.ordered(list(store.segments.values()))
    if land_manager_id is not None:
        rows = [r for r in rows if r["land_manager_id"] == land_manager_id]
    if posture is not None:
        rows = [r for r in rows if r["posture"] == posture]
    if adoption_status is not None:
        rows = [r for r in rows if r["adoption_status"] == adoption_status]
    return paginate(rows, domain.s_segment)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
@require(*ALL_ROLES)
def set_clock():
    data = v.body()
    target = v.req_datetime(data, "to_iso8601")
    if target <= store.now():
        fail("ERR_CLOCK_REWIND", "The logical clock never runs backwards.")

    store.set_clock(target)
    blocked = set()

    permits_expired = 0
    for permit in store.ordered(list(store.permits.values())):
        if permit["status"] != "ISSUED":
            continue
        window_end = store.parse_date(permit["window_end_date"])
        if window_end is not None and store.clock_date() > window_end:
            permit["status"] = "EXPIRED"
            touch(permit)
            permits_expired += 1
            domain.block_parties_for_permit(permit, "PERMIT_EXPIRED", False, blocked)

    segments = store.ordered(list(store.segments.values()))
    for segment in segments:
        domain.settle_segment(segment, blocked=blocked)

    return ok({
        "current_utc": store.now_iso(),
        "segments_recomputed": len(segments),
        "permits_expired": permits_expired,
        "parties_blocked": len(blocked),
    })


# ---------------------------------------------------------------------------
# Weather observations
# ---------------------------------------------------------------------------
@bp.post("/_weather/observations")
@require("StewardshipCoordinator", "LandManagerOfficer")
def record_observation():
    data = v.body()
    trail_segment_id = v.req_id(data, "trail_segment_id")
    soil_moisture_index = v.req_num(data, "soil_moisture_index", minimum=0.0, maximum=1.0)
    observed_at = v.req_datetime(data, "observed_at")

    segment = domain.get_segment(trail_segment_id)
    segment["latest_soil_moisture_index"] = float(soil_moisture_index)
    segment["latest_moisture_observed_at"] = store.iso(observed_at)
    domain.settle_segment(segment, force_touch=True)
    return ok(domain.s_segment(segment))
