"""Facility, bed, service-offering, recovery-housing, accreditation, clock, ops."""

from flask import Blueprint, request

from common import (
    ASAM_LEVELS,
    base_fields,
    bump_version,
    filter_param,
    iso,
    level_rank,
    page_params,
    paginate,
    parse_iso,
    public,
    require_fields,
    check_allowed,
    as_string,
    as_enum,
    as_int,
    opt_int,
    touch,
    touch_only,
)
from db import STORE
from errors import ApiError
from middleware import caller, facility_in_path, json_body, require_roles
from response import array_response, object_response
from services import calc, facility as facility_svc
from services import engine

bp = Blueprint("facilities", __name__)

ACCREDITATION_CLASSES = ["ACCREDITATION_BODY", "STATE_LICENSE", "RECOVERY_HOUSE"]
ACCREDITATION_STATUSES = ["GRANTED", "SUSPENDED", "REVOKED", "EXPIRED"]


def _facility_view(facility):
    return public(facility)


# ---------------------------------------------------------------------------
# Facilities + clock + ops
# ---------------------------------------------------------------------------

@bp.route("/facilities", methods=["POST"])
def create_facility():
    user_id, role = caller()
    require_roles(user_id, role, ["PlatformAdmin"])
    body = json_body()
    check_allowed(body, {"name", "state_code"})
    require_fields(body, ["name", "state_code"])
    name = as_string(body, "name")
    state_code = as_string(body, "state_code")
    if len(state_code) != 2 or state_code != state_code.upper():
        raise ApiError("ERR_INVALID_REQUEST", "state_code must be a two-letter uppercase code.")

    facility = base_fields("Facility")
    facility.update({
        "name": name,
        "state_code": state_code,
        "licensed": False,
        "as_level_max": "ASAM_1_0",
        "state_min_credential_tier": "TIER_1_SUPPORT",
        "is_accepting_admissions": False,
        "facility_posture": "OPEN",
        "compliance_risk_points": 0,
        "ops_epoch": 0,
        "last_ops_run_at": None,
    })
    STORE.put("Facility", facility)
    return object_response(_facility_view(facility), 201)


@bp.route("/facilities", methods=["GET"])
def list_facilities():
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    limit, offset = page_params(request.args)
    rows = sorted(STORE.all("Facility"), key=lambda r: (r.get("created_at") or "", r.get("_created_seq") or 0))

    state_code = filter_param(request.args, "state_code")
    licensed = filter_param(request.args, "licensed")
    posture = filter_param(request.args, "facility_posture")
    if state_code:
        rows = [r for r in rows if r.get("state_code") == state_code]
    if licensed is not None:
        want = licensed.lower() in ("true", "1", "yes")
        rows = [r for r in rows if bool(r.get("licensed")) == want]
    if posture:
        rows = [r for r in rows if r.get("facility_posture") == posture]

    page = paginate(rows, limit, offset)
    return array_response([_facility_view(r) for r in page["rows"]], page)


@bp.route("/facilities/<facility_id>", methods=["GET"])
def get_facility(facility_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    facility = facility_in_path(facility_id)
    return object_response(_facility_view(facility))


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = caller()
    require_roles(user_id, role, ["PlatformAdmin"])
    body = json_body()
    check_allowed(body, {"current_utc"})
    require_fields(body, ["current_utc"])
    moment = parse_iso(body.get("current_utc"), "current_utc")
    STORE.set_now(moment)
    return object_response({"current_utc": iso(STORE.now()), "facility_count": len(STORE.all("Facility"))})


@bp.route("/facilities/<facility_id>/facility-ops/run", methods=["POST"])
def facility_ops(facility_id):
    user_id, role = caller()
    require_roles(user_id, role, ["PlatformAdmin", "ClinicalDirector"])
    facility = facility_in_path(facility_id)
    engine.run_ops(facility, STORE.now())
    return object_response(_facility_view(facility))


# ---------------------------------------------------------------------------
# Beds
# ---------------------------------------------------------------------------

@bp.route("/facilities/<facility_id>/beds", methods=["POST"])
def create_bed(facility_id):
    user_id, role = caller()
    require_roles(user_id, role, ["PlatformAdmin"])
    facility = facility_in_path(facility_id)
    body = json_body()
    check_allowed(body, {"unit_name", "bed_label", "level_of_care", "cleaning_turnaround_hours"})
    require_fields(body, ["unit_name", "bed_label", "level_of_care", "cleaning_turnaround_hours"])
    unit_name = as_string(body, "unit_name")
    bed_label = as_string(body, "bed_label")
    level_of_care = as_enum(body, "level_of_care", ASAM_LEVELS)
    turnaround = as_int(body, "cleaning_turnaround_hours")
    for existing in STORE.where("Bed", lambda r: r.get("facility_id") == facility["id"]):
        if existing.get("bed_label") == bed_label:
            raise ApiError("ERR_INVALID_REQUEST", "bed_label must be unique within the facility.")

    bed = base_fields("Bed")
    bed.update({
        "facility_id": facility["id"],
        "_facility_id": facility["id"],
        "unit_name": unit_name,
        "bed_label": bed_label,
        "level_of_care": level_of_care,
        "cleaning_turnaround_hours": turnaround,
        "next_available_at": None,
        "status": "AVAILABLE",
    })
    STORE.put("Bed", bed)
    return object_response(public(bed), 201)


@bp.route("/facilities/<facility_id>/beds", methods=["GET"])
def list_beds(facility_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    facility = facility_in_path(facility_id)
    limit, offset = page_params(request.args)
    rows = sorted(
        STORE.where("Bed", lambda r: r.get("facility_id") == facility["id"]),
        key=lambda r: (r.get("created_at") or "", r.get("_created_seq") or 0),
    )
    level = filter_param(request.args, "level_of_care")
    status = filter_param(request.args, "status")
    if level:
        rows = [r for r in rows if r.get("level_of_care") == level]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    page = paginate(rows, limit, offset)
    return array_response([public(r) for r in page["rows"]], page)


# ---------------------------------------------------------------------------
# Service offerings
# ---------------------------------------------------------------------------

@bp.route("/facilities/<facility_id>/service-offerings", methods=["POST"])
def create_service(facility_id):
    user_id, role = caller()
    require_roles(user_id, role, ["PlatformAdmin"])
    facility = facility_in_path(facility_id)
    body = json_body()
    allowed = {"service_code", "level_of_care", "required_min_credential_tier", "requires_medical_provider"}
    check_allowed(body, allowed)
    require_fields(body, ["service_code", "level_of_care", "required_min_credential_tier", "requires_medical_provider"])
    from common import CREDENTIAL_TIERS, as_bool

    service = base_fields("ServiceOffering")
    service.update({
        "facility_id": facility["id"],
        "_facility_id": facility["id"],
        "service_code": as_string(body, "service_code"),
        "level_of_care": as_enum(body, "level_of_care", ASAM_LEVELS),
        "required_min_credential_tier": as_enum(body, "required_min_credential_tier", CREDENTIAL_TIERS),
        "requires_medical_provider": as_bool(body, "requires_medical_provider"),
    })
    STORE.put("ServiceOffering", service)
    return object_response(public(service), 201)


@bp.route("/facilities/<facility_id>/service-offerings", methods=["GET"])
def list_services(facility_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    facility = facility_in_path(facility_id)
    limit, offset = page_params(request.args)
    rows = sorted(
        STORE.where("ServiceOffering", lambda r: r.get("facility_id") == facility["id"]),
        key=lambda r: (r.get("created_at") or "", r.get("_created_seq") or 0),
    )
    level = filter_param(request.args, "level_of_care")
    if level:
        rows = [r for r in rows if r.get("level_of_care") == level]
    page = paginate(rows, limit, offset)
    return array_response([public(r) for r in page["rows"]], page)


@bp.route("/service-offerings/<service_id>", methods=["GET"])
def get_service(service_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    service = STORE.get("ServiceOffering", service_id)
    if service is None:
        raise ApiError("ERR_SERVICE_NOT_FOUND")
    return object_response(public(service))


@bp.route("/service-offerings/<service_id>/sessions", methods=["GET"])
def list_service_sessions(service_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    service = STORE.get("ServiceOffering", service_id)
    if service is None:
        raise ApiError("ERR_SERVICE_NOT_FOUND")
    limit, offset = page_params(request.args)
    rows = sorted(
        STORE.where("SessionAttendance", lambda r: r.get("service_id") == service["id"]),
        key=lambda r: (r.get("created_at") or "", r.get("_created_seq") or 0),
    )
    episode_id = filter_param(request.args, "episode_id")
    status = filter_param(request.args, "status")
    if episode_id:
        rows = [r for r in rows if r.get("episode_id") == episode_id]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    page = paginate(rows, limit, offset)
    return array_response([public(r) for r in page["rows"]], page)


# ---------------------------------------------------------------------------
# Recovery housing
# ---------------------------------------------------------------------------

@bp.route("/facilities/<facility_id>/recovery-housing", methods=["POST"])
def create_housing(facility_id):
    user_id, role = caller()
    require_roles(user_id, role, ["PlatformAdmin"])
    facility = facility_in_path(facility_id)
    body = json_body()
    allowed = {"house_name", "proximity_rank", "day_rate_cents", "capacity_beds", "grab_barrier_hours"}
    check_allowed(body, allowed)
    require_fields(body, ["house_name", "proximity_rank", "day_rate_cents", "capacity_beds"])

    house = base_fields("RecoveryHousing")
    house.update({
        "facility_id": facility["id"],
        "_facility_id": facility["id"],
        "house_name": as_string(body, "house_name"),
        "proximity_rank": as_int(body, "proximity_rank"),
        "day_rate_cents": as_int(body, "day_rate_cents"),
        "grab_barrier_hours": opt_int(body, "grab_barrier_hours") or 0,
        "capacity_beds": as_int(body, "capacity_beds"),
        "licensed": False,
        "status": "OPEN",
    })
    STORE.put("RecoveryHousing", house)
    facility_svc.recompute_housing_licensed(facility)
    return object_response(public(house), 201)


@bp.route("/facilities/<facility_id>/recovery-housing", methods=["GET"])
def list_housing(facility_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    facility = facility_in_path(facility_id)
    limit, offset = page_params(request.args)
    rows = sorted(
        STORE.where("RecoveryHousing", lambda r: r.get("facility_id") == facility["id"]),
        key=lambda r: (r.get("created_at") or "", r.get("_created_seq") or 0),
    )
    status = filter_param(request.args, "status")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    page = paginate(rows, limit, offset)
    return array_response([public(r) for r in page["rows"]], page)


@bp.route("/recovery-housing/<housing_id>", methods=["GET"])
def get_housing(housing_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    house = STORE.get("RecoveryHousing", housing_id)
    if house is None:
        raise ApiError("ERR_HOUSING_NOT_FOUND")
    return object_response(public(house))


@bp.route("/recovery-housing/<housing_id>/continuing-care-plans", methods=["GET"])
def list_housing_plans(housing_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    house = STORE.get("RecoveryHousing", housing_id)
    if house is None:
        raise ApiError("ERR_HOUSING_NOT_FOUND")
    limit, offset = page_params(request.args)
    rows = sorted(
        STORE.where("ContinuingCarePlan", lambda r: r.get("housing_id") == house["id"]),
        key=lambda r: (r.get("created_at") or "", r.get("_created_seq") or 0),
    )
    status = filter_param(request.args, "status")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    page = paginate(rows, limit, offset)
    return array_response([public(r) for r in page["rows"]], page)


# ---------------------------------------------------------------------------
# Clinician facility credentials (facility-scoped read)
# ---------------------------------------------------------------------------

@bp.route("/facilities/<facility_id>/clinician-credentials", methods=["GET"])
def list_facility_credentials(facility_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    facility = facility_in_path(facility_id)
    limit, offset = page_params(request.args)
    rows = sorted(
        STORE.where("ClinicianFacilityCredential", lambda r: r.get("facility_id") == facility["id"]),
        key=lambda r: (r.get("created_at") or "", r.get("_created_seq") or 0),
    )
    clinician_id = filter_param(request.args, "clinician_id")
    status = filter_param(request.args, "status")
    if clinician_id:
        rows = [r for r in rows if r.get("clinician_id") == clinician_id]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    page = paginate(rows, limit, offset)
    now = STORE.now()
    return array_response([_credential_view(r, now) for r in page["rows"]], page)


def _credential_view(row, now):
    out = public(row)
    effective = parse_iso(row["effective_at"], "effective_at")
    expires = parse_iso(row["expires_at"], "expires_at")
    out["is_usable"] = bool(row.get("status") == "ACTIVE" and effective <= now < expires)
    return out


# ---------------------------------------------------------------------------
# Accreditations
# ---------------------------------------------------------------------------

@bp.route("/facilities/<facility_id>/accreditations", methods=["POST"])
def create_accreditation(facility_id):
    user_id, role = caller()
    require_roles(user_id, role, ["PlatformAdmin"])
    facility = facility_in_path(facility_id)
    body = json_body()
    allowed = {
        "accreditation_class", "granting_body", "effective_at", "expires_at",
        "license_level_max", "credential_tier_min",
    }
    check_allowed(body, allowed)
    require_fields(body, ["accreditation_class", "granting_body", "effective_at", "expires_at"])
    from common import CREDENTIAL_TIERS

    accreditation_class = as_enum(body, "accreditation_class", ACCREDITATION_CLASSES)

    row = base_fields("Accreditation")
    row.update({
        "facility_id": facility["id"],
        "_facility_id": facility["id"],
        "accreditation_class": accreditation_class,
        "granting_body": as_string(body, "granting_body"),
        "status": "GRANTED",
        "effective_at": iso(parse_iso(body.get("effective_at"), "effective_at")),
        "expires_at": iso(parse_iso(body.get("expires_at"), "expires_at")),
        "license_level_max": None,
        "credential_tier_min": None,
    })
    if accreditation_class == "STATE_LICENSE":
        level_max = body.get("license_level_max")
        tier_min = body.get("credential_tier_min")
        if level_max is not None:
            row["license_level_max"] = as_enum(body, "license_level_max", ASAM_LEVELS)
        if tier_min is not None:
            row["credential_tier_min"] = as_enum(body, "credential_tier_min", CREDENTIAL_TIERS)

    STORE.put("Accreditation", row)
    facility_svc.recompute(facility, STORE.now())
    facility_svc.recompute_housing_licensed(facility)
    return object_response(public(row), 201)


@bp.route("/facilities/<facility_id>/accreditations", methods=["GET"])
def list_accreditations(facility_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    facility = facility_in_path(facility_id)
    limit, offset = page_params(request.args)
    rows = sorted(
        STORE.where("Accreditation", lambda r: r.get("facility_id") == facility["id"]),
        key=lambda r: (r.get("created_at") or "", r.get("_created_seq") or 0),
    )
    cls = filter_param(request.args, "accreditation_class")
    status = filter_param(request.args, "status")
    if cls:
        rows = [r for r in rows if r.get("accreditation_class") == cls]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    page = paginate(rows, limit, offset)
    return array_response([public(r) for r in page["rows"]], page)


@bp.route("/accreditations/<accreditation_id>", methods=["GET"])
def get_accreditation(accreditation_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    row = STORE.get("Accreditation", accreditation_id)
    if row is None:
        raise ApiError("ERR_ACCREDITATION_NOT_FOUND")
    return object_response(public(row))


def _accreditation_action(facility_id, accreditation_id, new_status, push_days=None):
    user_id, role = caller()
    require_roles(user_id, role, ["ClinicalDirector"])
    facility = facility_in_path(facility_id)
    row = STORE.get("Accreditation", accreditation_id)
    if row is None or row.get("facility_id") != facility["id"]:
        raise ApiError("ERR_ACCREDITATION_NOT_FOUND")

    now = STORE.now()
    row["status"] = new_status
    if push_days:
        row["expires_at"] = iso(parse_iso(row["expires_at"], "expires_at") + time_delta_days(push_days))
    touch(row)
    facility_svc.recompute(facility, now)
    facility_svc.recompute_housing_licensed(facility)
    demote_over_licensed_authorizations(facility, now)
    return object_response(public(row))


def demote_over_licensed_authorizations(facility, now):
    """Any live authorization whose granted_level exceeds the facility's
    remaining licence becomes STEP_DOWN_REQUIRED."""
    ceiling = level_rank(facility.get("as_level_max"))
    for authorization in STORE.where("LevelOfCareAuthorization", lambda r: r.get("_facility_id") == facility["id"]):
        if authorization.get("posture") not in ("APPROVED", "CONCURRENT_REVIEW_DUE", "EXTENDED", "STEP_DOWN_REQUIRED"):
            continue
        granted = authorization.get("granted_level") or authorization.get("requested_level")
        if level_rank(granted) > ceiling and authorization.get("posture") != "STEP_DOWN_REQUIRED":
            authorization["posture"] = "STEP_DOWN_REQUIRED"
            authorization["version"] = authorization.get("version", 1) + 1
            authorization["updated_at"] = iso(now)


def time_delta_days(days):
    from datetime import timedelta

    return timedelta(days=days)


@bp.route("/facilities/<facility_id>/accreditations/<accreditation_id>/renew", methods=["POST"])
def renew_accreditation(facility_id, accreditation_id):
    return _accreditation_action(facility_id, accreditation_id, "GRANTED", push_days=365)


@bp.route("/facilities/<facility_id>/accreditations/<accreditation_id>/suspend", methods=["POST"])
def suspend_accreditation(facility_id, accreditation_id):
    return _accreditation_action(facility_id, accreditation_id, "SUSPENDED")


@bp.route("/facilities/<facility_id>/accreditations/<accreditation_id>/revoke", methods=["POST"])
def revoke_accreditation(facility_id, accreditation_id):
    return _accreditation_action(facility_id, accreditation_id, "REVOKED")


@bp.route("/facilities/<facility_id>/accreditations/<accreditation_id>/reinstate", methods=["POST"])
def reinstate_accreditation(facility_id, accreditation_id):
    return _accreditation_action(facility_id, accreditation_id, "GRANTED")