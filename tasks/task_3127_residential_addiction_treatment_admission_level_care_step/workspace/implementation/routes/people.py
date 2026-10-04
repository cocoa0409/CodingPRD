"""Top-level clinicians and payers plus the network-wide read surface."""

from flask import Blueprint, request

from common import (
    CREDENTIAL_TIERS,
    base_fields,
    as_bool,
    as_enum,
    as_int,
    as_string,
    check_allowed,
    filter_param,
    iso,
    page_params,
    paginate,
    parse_iso,
    public,
    require_fields,
)
from db import STORE
from errors import ApiError
from middleware import caller, json_body, require_roles
from response import array_response, object_response
from services import engine

bp = Blueprint("people", __name__)


def _credential_view(row, now):
    out = public(row)
    effective = parse_iso(row["effective_at"], "effective_at")
    expires = parse_iso(row["expires_at"], "expires_at")
    out["is_usable"] = bool(row.get("status") == "ACTIVE" and effective <= now < expires)
    return out


def _ordered(rows):
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_created_seq") or 0))


# ---------------------------------------------------------------------------
# Clinicians
# ---------------------------------------------------------------------------

@bp.route("/clinicians", methods=["POST"])
def create_clinician():
    user_id, role = caller()
    require_roles(user_id, role, ["PlatformAdmin"])
    body = json_body()
    check_allowed(body, {"full_name", "credential_tier", "is_medical_provider"})
    require_fields(body, ["full_name", "credential_tier", "is_medical_provider"])

    clinician = base_fields("Clinician")
    clinician.update({
        "full_name": as_string(body, "full_name"),
        "credential_tier": as_enum(body, "credential_tier", CREDENTIAL_TIERS),
        "is_medical_provider": as_bool(body, "is_medical_provider"),
    })
    STORE.put("Clinician", clinician)
    return object_response(public(clinician), 201)


@bp.route("/clinicians/<clinician_id>", methods=["GET"])
def get_clinician(clinician_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    clinician = STORE.get("Clinician", clinician_id)
    if clinician is None:
        raise ApiError("ERR_CLINICIAN_NOT_FOUND")
    return object_response(public(clinician))


@bp.route("/clinicians/<clinician_id>/facility-credentials", methods=["POST"])
def create_credential(clinician_id):
    user_id, role = caller()
    require_roles(user_id, role, ["PlatformAdmin"])
    clinician = STORE.get("Clinician", clinician_id)
    if clinician is None:
        raise ApiError("ERR_CLINICIAN_NOT_FOUND")
    body = json_body()
    check_allowed(body, {"facility_id", "effective_at", "expires_at"})
    require_fields(body, ["facility_id", "effective_at", "expires_at"])
    facility_id = as_string(body, "facility_id")
    facility = STORE.get("Facility", facility_id)
    if facility is None:
        raise ApiError("ERR_FACILITY_NOT_FOUND")

    row = base_fields("ClinicianFacilityCredential")
    row.update({
        "clinician_id": clinician["id"],
        "facility_id": facility["id"],
        "_facility_id": facility["id"],
        "effective_at": iso(parse_iso(body.get("effective_at"), "effective_at")),
        "expires_at": iso(parse_iso(body.get("expires_at"), "expires_at")),
        "status": "ACTIVE",
    })
    STORE.put("ClinicianFacilityCredential", row)
    return object_response(_credential_view(row, STORE.now()), 201)


@bp.route("/clinicians/<clinician_id>/facility-credentials", methods=["GET"])
def list_credentials(clinician_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    clinician = STORE.get("Clinician", clinician_id)
    if clinician is None:
        raise ApiError("ERR_CLINICIAN_NOT_FOUND")
    limit, offset = page_params(request.args)
    rows = _ordered(STORE.where("ClinicianFacilityCredential", lambda r: r.get("clinician_id") == clinician["id"]))
    facility_id = filter_param(request.args, "facility_id")
    status = filter_param(request.args, "status")
    if facility_id:
        rows = [r for r in rows if r.get("facility_id") == facility_id]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    page = paginate(rows, limit, offset)
    now = STORE.now()
    return array_response([_credential_view(r, now) for r in page["rows"]], page)


def _clinician_child_list(clinician_id, entity, field, view=None):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    clinician = STORE.get("Clinician", clinician_id)
    if clinician is None:
        raise ApiError("ERR_CLINICIAN_NOT_FOUND")
    limit, offset = page_params(request.args)
    rows = _ordered(STORE.where(entity, lambda r: r.get(field) == clinician["id"]))
    episode_id = filter_param(request.args, "episode_id")
    status = filter_param(request.args, "status")
    if episode_id:
        rows = [r for r in rows if r.get("episode_id") == episode_id]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    page = paginate(rows, limit, offset)
    render = view or public
    return array_response([render(r) for r in page["rows"]], page)


@bp.route("/clinicians/<clinician_id>/assessments", methods=["GET"])
def clinician_assessments(clinician_id):
    return _clinician_child_list(clinician_id, "ClinicalAssessment", "assessor_clinician_id")


@bp.route("/clinicians/<clinician_id>/treatment-plans", methods=["GET"])
def clinician_treatment_plans(clinician_id):
    return _clinician_child_list(clinician_id, "TreatmentPlan", "author_clinician_id")


@bp.route("/clinicians/<clinician_id>/sessions", methods=["GET"])
def clinician_sessions(clinician_id):
    return _clinician_child_list(clinician_id, "SessionAttendance", "clinician_id")


@bp.route("/clinicians/<clinician_id>/continuing-care-plans", methods=["GET"])
def clinician_continuing_care_plans(clinician_id):
    return _clinician_child_list(clinician_id, "ContinuingCarePlan", "authorizing_clinician_id")


# ---------------------------------------------------------------------------
# Payers
# ---------------------------------------------------------------------------

@bp.route("/payers", methods=["POST"])
def create_payer():
    user_id, role = caller()
    require_roles(user_id, role, ["PlatformAdmin"])
    body = json_body()
    allowed = {
        "name",
        "initial_authorized_days_by_loc",
        "step_down_coverage_map",
        "concurrent_review_interval_days",
        "credential_min_tier_by_loc",
    }
    check_allowed(body, allowed)
    require_fields(body, ["name", "initial_authorized_days_by_loc", "step_down_coverage_map",
                          "concurrent_review_interval_days", "credential_min_tier_by_loc"])
    from common import ASAM_LEVELS

    initial = body.get("initial_authorized_days_by_loc")
    coverage = body.get("step_down_coverage_map")
    tiers = body.get("credential_min_tier_by_loc")
    for mapping, name in ((initial, "initial_authorized_days_by_loc"),
                          (coverage, "step_down_coverage_map"),
                          (tiers, "credential_min_tier_by_loc")):
        if not isinstance(mapping, dict):
            raise ApiError("ERR_INVALID_REQUEST", "%s must be an object." % name)

    payer = base_fields("Payer")
    payer.update({
        "name": as_string(body, "name"),
        "initial_authorized_days_by_loc": {k: int(v) for k, v in initial.items()},
        "step_down_coverage_map": {k: list(v) for k, v in coverage.items()},
        "concurrent_review_interval_days": as_int(body, "concurrent_review_interval_days"),
        "credential_min_tier_by_loc": dict(tiers),
    })
    STORE.put("Payer", payer)
    return object_response(public(payer), 201)


@bp.route("/payers/<payer_id>", methods=["GET"])
def get_payer(payer_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    payer = STORE.get("Payer", payer_id)
    if payer is None:
        raise ApiError("ERR_PAYER_NOT_FOUND")
    return object_response(public(payer))


@bp.route("/payers/<payer_id>/authorizations", methods=["GET"])
def payer_authorizations(payer_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    payer = STORE.get("Payer", payer_id)
    if payer is None:
        raise ApiError("ERR_PAYER_NOT_FOUND")
    limit, offset = page_params(request.args)
    rows = _ordered(STORE.where("LevelOfCareAuthorization", lambda r: r.get("payer_id") == payer["id"]))
    episode_id = filter_param(request.args, "episode_id")
    posture = filter_param(request.args, "posture")
    if episode_id:
        rows = [r for r in rows if r.get("episode_id") == episode_id]
    if posture:
        rows = [r for r in rows if r.get("posture") == posture]
    page = paginate(rows, limit, offset)
    return array_response([public(r) for r in page["rows"]], page)


# ---------------------------------------------------------------------------
# Network-wide reads
# ---------------------------------------------------------------------------

@bp.route("/treatment-episodes/<episode_id>", methods=["GET"])
def get_episode_network(episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    episode = STORE.get("TreatmentEpisode", episode_id)
    if episode is None:
        raise ApiError("ERR_EPISODE_NOT_FOUND")
    return object_response(public(episode))


@bp.route("/treatment-episodes/<episode_id>/utilization-summary", methods=["GET"])
def utilization_summary(episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    episode = STORE.get("TreatmentEpisode", episode_id)
    if episode is None:
        raise ApiError("ERR_EPISODE_NOT_FOUND")

    authorization_id = request.args.get("authorization_id")
    if authorization_id:
        authorization = STORE.get("LevelOfCareAuthorization", authorization_id)
        if authorization is None or authorization.get("episode_id") != episode["id"]:
            raise ApiError("ERR_AUTHORIZATION_NOT_FOUND")
    else:
        authorization = engine.active_authorization(episode)

    facility = STORE.get("Facility", episode.get("_facility_id"))
    plan = engine.withdrawal_plan(episode)
    wm_status = plan.get("status") if plan else None

    if authorization is not None:
        from services import calc

        urgency_score = calc.urgency_variant_a(authorization, wm_status)
        payer = STORE.get("Payer", authorization.get("payer_id"))
        interval = int((payer or {}).get("concurrent_review_interval_days") or 0)
        projected = calc.urgency_variant_b(authorization, wm_status, interval)
        days_used = int(authorization.get("days_used") or 0)
        days_remaining = int(authorization.get("days_remaining") or 0)
        auth_id = authorization["id"]
    else:
        from services import calc

        urgency_score = 0.0
        projected = 0.0
        days_used = 0
        days_remaining = 0
        auth_id = None

    from services import calc as calc_mod

    _, _, _, percent = calc_mod.curriculum_status(episode, engine.session_rows(episode), STORE.now())
    committed = calc_mod.committed_bed_nights(facility) if facility else 0

    data = {
        "authorization_id": auth_id,
        "urgency_score": urgency_score,
        "projected_step_down_urgency": projected,
        "days_used": days_used,
        "days_remaining": days_remaining,
        "curriculum_compliance_percent": percent,
        "committed_bed_nights": committed,
        "outstanding_formula": "authorization_days_bank",
        "formula_version": 1,
        "discharged_at": episode.get("discharged_at"),
    }
    return object_response(data)


def _network_child_list(entity, view=None):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    limit, offset = page_params(request.args)
    rows = _ordered(STORE.all(entity))
    page = paginate(rows, limit, offset)
    render = view or public
    return array_response([render(r) for r in page["rows"]], page)


@bp.route("/treatment-episodes/<episode_id>/assessments", methods=["GET"])
def episode_assessments_network(episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    if STORE.get("TreatmentEpisode", episode_id) is None:
        raise ApiError("ERR_EPISODE_NOT_FOUND")
    limit, offset = page_params(request.args)
    rows = _ordered(STORE.where("ClinicalAssessment", lambda r: r.get("episode_id") == episode_id))
    status = filter_param(request.args, "status")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    page = paginate(rows, limit, offset)
    return array_response([public(r) for r in page["rows"]], page)


@bp.route("/treatment-episodes/<episode_id>/authorizations", methods=["GET"])
def episode_authorizations_network(episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    if STORE.get("TreatmentEpisode", episode_id) is None:
        raise ApiError("ERR_EPISODE_NOT_FOUND")
    limit, offset = page_params(request.args)
    rows = _ordered(STORE.where("LevelOfCareAuthorization", lambda r: r.get("episode_id") == episode_id))
    posture = filter_param(request.args, "posture")
    if posture:
        rows = [r for r in rows if r.get("posture") == posture]
    page = paginate(rows, limit, offset)
    return array_response([public(r) for r in page["rows"]], page)


@bp.route("/authorizations/<authorization_id>", methods=["GET"])
def get_authorization(authorization_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    row = STORE.get("LevelOfCareAuthorization", authorization_id)
    if row is None:
        raise ApiError("ERR_AUTHORIZATION_NOT_FOUND")
    return object_response(public(row))


@bp.route("/authorizations/<authorization_id>/level-of-care-changes", methods=["GET"])
def authorization_changes(authorization_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    row = STORE.get("LevelOfCareAuthorization", authorization_id)
    if row is None:
        raise ApiError("ERR_AUTHORIZATION_NOT_FOUND")
    limit, offset = page_params(request.args)
    rows = _ordered(STORE.where("LevelOfCareChange", lambda r: r.get("authorization_id") == row["id"]))
    status = filter_param(request.args, "status")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    page = paginate(rows, limit, offset)
    return array_response([public(r) for r in page["rows"]], page)


@bp.route("/level-of-care-changes/<change_id>", methods=["GET"])
def get_change_network(change_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    row = STORE.get("LevelOfCareChange", change_id)
    if row is None:
        raise ApiError("ERR_CHANGE_NOT_FOUND")
    return object_response(public(row))


@bp.route("/beds/<bed_id>/level-of-care-changes", methods=["GET"])
def bed_changes(bed_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    bed = STORE.get("Bed", bed_id)
    if bed is None:
        raise ApiError("ERR_BED_NOT_FOUND")
    limit, offset = page_params(request.args)
    rows = _ordered(STORE.where("LevelOfCareChange", lambda r: r.get("bed_id") == bed["id"]))
    page = paginate(rows, limit, offset)
    return array_response([public(r) for r in page["rows"]], page)


@bp.route("/level-of-care-changes", methods=["GET"])
def list_changes_network():
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    limit, offset = page_params(request.args)
    rows = _ordered(STORE.all("LevelOfCareChange"))
    for name in ("bed_id", "authorization_id", "episode_id", "change_type", "status"):
        value = filter_param(request.args, name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    page = paginate(rows, limit, offset)
    return array_response([public(r) for r in page["rows"]], page)


@bp.route("/treatment-episodes/<episode_id>/medical-clearances", methods=["GET"])
def episode_clearances_network(episode_id):
    from services.engine import clearance_view

    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    if STORE.get("TreatmentEpisode", episode_id) is None:
        raise ApiError("ERR_EPISODE_NOT_FOUND")
    limit, offset = page_params(request.args)
    rows = _ordered(STORE.where("MedicalClearance", lambda r: r.get("episode_id") == episode_id))
    ctype = filter_param(request.args, "clearance_type")
    status = filter_param(request.args, "status")
    if ctype:
        rows = [r for r in rows if r.get("clearance_type") == ctype]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    page = paginate(rows, limit, offset)
    now = STORE.now()
    return array_response([clearance_view(r, now) for r in page["rows"]], page)


@bp.route("/treatment-episodes/<episode_id>/withdrawal-management", methods=["GET"])
def episode_wm_network(episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    if STORE.get("TreatmentEpisode", episode_id) is None:
        raise ApiError("ERR_EPISODE_NOT_FOUND")
    limit, offset = page_params(request.args)
    rows = _ordered(STORE.where("WithdrawalManagementPlan", lambda r: r.get("episode_id") == episode_id))
    status = filter_param(request.args, "status")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    page = paginate(rows, limit, offset)
    return array_response([public(r) for r in page["rows"]], page)


@bp.route("/withdrawal-management/<wm_id>", methods=["GET"])
def get_wm_network(wm_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    row = STORE.get("WithdrawalManagementPlan", wm_id)
    if row is None:
        raise ApiError("ERR_PLAN_NOT_FOUND")
    return object_response(public(row))


@bp.route("/treatment-episodes/<episode_id>/treatment-plans", methods=["GET"])
def episode_plans_network(episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    if STORE.get("TreatmentEpisode", episode_id) is None:
        raise ApiError("ERR_EPISODE_NOT_FOUND")
    limit, offset = page_params(request.args)
    rows = _ordered(STORE.where("TreatmentPlan", lambda r: r.get("episode_id") == episode_id))
    status = filter_param(request.args, "status")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    page = paginate(rows, limit, offset)
    return array_response([public(r) for r in page["rows"]], page)


@bp.route("/treatment-plans/<plan_id>", methods=["GET"])
def get_plan_network(plan_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    row = STORE.get("TreatmentPlan", plan_id)
    if row is None:
        raise ApiError("ERR_PLAN_NOT_FOUND")
    return object_response(public(row))


@bp.route("/treatment-episodes/<episode_id>/sessions", methods=["GET"])
def episode_sessions_network(episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    if STORE.get("TreatmentEpisode", episode_id) is None:
        raise ApiError("ERR_EPISODE_NOT_FOUND")
    limit, offset = page_params(request.args)
    rows = _ordered(STORE.where("SessionAttendance", lambda r: r.get("episode_id") == episode_id))
    status = filter_param(request.args, "status")
    service_id = filter_param(request.args, "service_id")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    if service_id:
        rows = [r for r in rows if r.get("service_id") == service_id]
    page = paginate(rows, limit, offset)
    return array_response([public(r) for r in page["rows"]], page)


@bp.route("/sessions/<session_id>", methods=["GET"])
def get_session_network(session_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    row = STORE.get("SessionAttendance", session_id)
    if row is None:
        raise ApiError("ERR_SESSION_NOT_FOUND")
    return object_response(public(row))


@bp.route("/treatment-episodes/<episode_id>/level-of-care-changes", methods=["GET"])
def episode_changes_network(episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    if STORE.get("TreatmentEpisode", episode_id) is None:
        raise ApiError("ERR_EPISODE_NOT_FOUND")
    limit, offset = page_params(request.args)
    rows = _ordered(STORE.where("LevelOfCareChange", lambda r: r.get("episode_id") == episode_id))
    status = filter_param(request.args, "status")
    change_type = filter_param(request.args, "change_type")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    if change_type:
        rows = [r for r in rows if r.get("change_type") == change_type]
    page = paginate(rows, limit, offset)
    return array_response([public(r) for r in page["rows"]], page)


@bp.route("/treatment-episodes/<episode_id>/continuing-care-plans", methods=["GET"])
def episode_cc_plans_network(episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    if STORE.get("TreatmentEpisode", episode_id) is None:
        raise ApiError("ERR_EPISODE_NOT_FOUND")
    limit, offset = page_params(request.args)
    rows = _ordered(STORE.where("ContinuingCarePlan", lambda r: r.get("episode_id") == episode_id))
    status = filter_param(request.args, "status")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    page = paginate(rows, limit, offset)
    return array_response([public(r) for r in page["rows"]], page)


@bp.route("/treatment-episodes/<episode_id>/alumni-contacts", methods=["GET"])
def episode_contacts_network(episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    if STORE.get("TreatmentEpisode", episode_id) is None:
        raise ApiError("ERR_EPISODE_NOT_FOUND")
    limit, offset = page_params(request.args)
    rows = _ordered(STORE.where("AlumniContact", lambda r: r.get("episode_id") == episode_id))
    outcome = filter_param(request.args, "outcome")
    if outcome:
        rows = [r for r in rows if r.get("outcome") == outcome]
    page = paginate(rows, limit, offset)
    return array_response([public(r) for r in page["rows"]], page)