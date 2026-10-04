"""Treatment episodes: intake, assessment, authorization, admission, discharge."""

from flask import Blueprint, request

from common import (
    ASAM_LEVELS,
    PLACEMENT_BASES,
    base_fields,
    check_allowed,
    filter_param,
    iso,
    level_rank,
    opt_string,
    page_params,
    paginate,
    parse_iso,
    public,
    require_fields,
    as_enum,
    as_string,
    as_int,
    opt_int,
    touch,
)
from db import STORE
from errors import ApiError
from middleware import (
    caller,
    check_idempotency,
    child_in_path,
    episode_in_path,
    facility_in_path,
    json_body,
    require_roles,
    resolve_clinician,
    resolve_payer,
    resolve_service,
)
from response import array_response, object_response
from services import calc, duties, engine, facility as facility_svc

bp = Blueprint("episodes", __name__)

CLINICAL_STATUSES = [
    "AWAITING_ASSESSMENT", "UNDER_ASSESSMENT", "AWAITING_AUTHORIZATION",
    "AWAITING_ADMISSION", "IN_TREATMENT", "COMPLETED", "DISCHARGED",
]
CARE_LEVEL_STATUSES = ["NOT_STARTED", "ACTIVE", "STEP_DOWN_PENDING", "STEPPED_DOWN"]
CLEARANCE_TYPES = ["MEDICAL", "PSYCHIATRIC", "TB_SCREEN"]
PROTOCOLS = ["NONE", "ALCOHOL_TAPER", "OPIOID_AGONIST", "BENZO_TAPER"]
WM_STATUSES = ["ACTIVE", "MEDICALLY_STABLE", "COMPLICATED"]


def _ordered(rows):
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_created_seq") or 0))


def _episode_view(episode):
    return public(episode)


# ---------------------------------------------------------------------------
# Episode CRUD
# ---------------------------------------------------------------------------

@bp.route("/facilities/<facility_id>/treatment-episodes", methods=["POST"])
def create_episode(facility_id):
    user_id, role = caller()
    require_roles(user_id, role, ["AdmissionsIntakeNurse", "Clinician"])
    facility = facility_in_path(facility_id)
    body = json_body()
    check_allowed(body, {"patient_ref", "assigned_level"})
    require_fields(body, ["patient_ref"])

    episode = base_fields("TreatmentEpisode")
    episode.update({
        "facility_id": facility["id"],
        "_facility_id": facility["id"],
        "patient_ref": as_string(body, "patient_ref"),
        "assigned_level": as_enum(body, "assigned_level", ASAM_LEVELS) if "assigned_level" in body and body.get("assigned_level") is not None else None,
        "admitted_at": None,
        "discharged_at": None,
        "clinical_status": "AWAITING_ASSESSMENT",
        "care_level_status": "NOT_STARTED",
        "step_down_count": 0,
        "therapy_revenue_cents": 0,
        "revcap_pre_step_down_cents": None,
        "revcap_post_step_down_cents": None,
        "_created_seq": STORE.next_seq(),
    })
    STORE.put("TreatmentEpisode", episode)
    return object_response(_episode_view(episode), 201)


@bp.route("/facilities/<facility_id>/treatment-episodes", methods=["GET"])
def list_episodes(facility_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    facility = facility_in_path(facility_id)
    limit, offset = page_params(request.args)
    rows = _ordered(STORE.where("TreatmentEpisode", lambda r: r.get("facility_id") == facility["id"]))
    for name in ("clinical_status", "care_level_status", "assigned_level"):
        value = filter_param(request.args, name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    page = paginate(rows, limit, offset)
    return array_response([_episode_view(r) for r in page["rows"]], page)


@bp.route("/facilities/<facility_id>/treatment-episodes/<episode_id>", methods=["GET"])
def get_episode_in_facility(facility_id, episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    facility = facility_in_path(facility_id)
    episode = episode_in_path(facility, episode_id)
    return object_response(_episode_view(episode))


# ---------------------------------------------------------------------------
# Assessments
# ---------------------------------------------------------------------------

@bp.route("/facilities/<facility_id>/treatment-episodes/<episode_id>/assessments", methods=["POST"])
def create_assessment(facility_id, episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["AdmissionsIntakeNurse", "Clinician"])
    facility = facility_in_path(facility_id)
    episode = episode_in_path(facility, episode_id)
    body = json_body()
    check_allowed(body, {"assessor_clinician_id", "dimension_scores", "placement_basis"})
    require_fields(body, ["assessor_clinician_id", "dimension_scores"])
    check_idempotency("assessments:%s" % episode["id"], body)

    assessor_id = as_string(body, "assessor_clinician_id")
    resolve_clinician(assessor_id)
    scores = _validate_dimensions(body.get("dimension_scores"))
    placement_basis = body.get("placement_basis")
    if placement_basis is not None:
        placement_basis = as_enum(body, "placement_basis", PLACEMENT_BASES)

    facility_svc_facility = facility
    if not facility.get("licensed"):
        raise ApiError("ERR_FACILITY_NOT_LICENSED")

    # PRD §3.1: "The assessor named by `assessor_clinician_id` must hold a
    # `credential_tier` at or above the facility's `state_min_credential_tier`, and
    # must hold a `ClinicianFacilityCredential` for that facility whose `is_usable`
    # flag is true." The named assessor is fixed at filing time, so the credential
    # standing is settled here as well as at completion.
    engine.authoring_credential_ok(assessor_id, facility, STORE.now())

    if episode.get("clinical_status") not in ("AWAITING_ASSESSMENT", "UNDER_ASSESSMENT"):
        raise ApiError("ERR_EPISODE_NOT_AWAITING_ASSESSMENT")

    now = STORE.now()
    for sibling in STORE.where(
        "ClinicalAssessment",
        lambda r: r.get("_episode_id") == episode["id"] and r.get("status") == "IN_PROGRESS",
    ):
        sibling["status"] = "SUPERSEDED"
        sibling["updated_at"] = iso(now)
        sibling["version"] = sibling.get("version", 1) + 1

    row = base_fields("ClinicalAssessment")
    row.update({
        "episode_id": episode["id"],
        "_episode_id": episode["id"],
        "facility_id": facility["id"],
        "_facility_id": facility["id"],
        "assessor_clinician_id": assessor_id,
        "assessed_at": None,
        "dimension_scores": scores,
        "placement_basis": placement_basis or "DIMENSION_SUM",
        "total_score": None,
        "recommended_level": None,
        "status": "IN_PROGRESS",
        "_created_seq": STORE.next_episode_seq(episode["id"]),
    })
    STORE.put("ClinicalAssessment", row)

    episode["clinical_status"] = "UNDER_ASSESSMENT"
    episode["version"] = episode.get("version", 1) + 1
    episode["updated_at"] = iso(now)
    return object_response(public(row), 201)


def _validate_dimensions(scores):
    from common import DIMENSION_NAMES

    if not isinstance(scores, dict):
        raise ApiError("ERR_INVALID_DIMENSION_SCORES")
    normalized = {}
    for name in DIMENSION_NAMES:
        if name not in scores:
            raise ApiError("ERR_INVALID_DIMENSION_SCORES")
        value = scores[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 4:
            raise ApiError("ERR_INVALID_DIMENSION_SCORES")
        normalized[name] = value
    for name in scores:
        if name not in DIMENSION_NAMES:
            raise ApiError("ERR_INVALID_DIMENSION_SCORES")
    return normalized


def _assessment_in_path(facility, assessment_id):
    row = STORE.get("ClinicalAssessment", assessment_id)
    if row is None or row.get("facility_id") != facility["id"]:
        raise ApiError("ERR_ASSESSMENT_NOT_FOUND")
    return row


@bp.route("/facilities/<facility_id>/treatment-episodes/<episode_id>/assessments", methods=["GET"])
def list_episode_assessments(facility_id, episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    facility = facility_in_path(facility_id)
    episode = episode_in_path(facility, episode_id)
    limit, offset = page_params(request.args)
    rows = _ordered(STORE.where("ClinicalAssessment", lambda r: r.get("_episode_id") == episode["id"]))
    status = filter_param(request.args, "status")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    page = paginate(rows, limit, offset)
    return array_response([public(r) for r in page["rows"]], page)


@bp.route("/facilities/<facility_id>/assessments/<assessment_id>/complete", methods=["POST"])
def complete_assessment(facility_id, assessment_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Clinician"])
    facility = facility_in_path(facility_id)
    assessment = _assessment_in_path(facility, assessment_id)
    episode = STORE.get("TreatmentEpisode", assessment["_episode_id"])

    if episode is None or episode.get("clinical_status") != "UNDER_ASSESSMENT":
        raise ApiError("ERR_EPISODE_NOT_UNDER_ASSESSMENT")
    if assessment.get("status") != "IN_PROGRESS":
        raise ApiError("ERR_ASSESSMENT_NOT_IN_PROGRESS")

    now = STORE.now()
    # The completing caller is itself an authoring clinician at this facility, so
    # PRD §2.5's credential ladder binds them too; the assessor named on the row is
    # checked alongside, per PRD §3.1.
    engine.authoring_credential_ok(user_id, facility, now)
    engine.authoring_credential_ok(assessment.get("assessor_clinician_id"), facility, now)

    total_score, recommended = calc.asam_placement(assessment["dimension_scores"], assessment.get("placement_basis"))
    assessment["total_score"] = total_score
    assessment["recommended_level"] = recommended
    assessment["status"] = "COMPLETED"
    assessment["assessed_at"] = iso(now)
    assessment["version"] = assessment.get("version", 1) + 1
    assessment["updated_at"] = iso(now)

    for sibling in STORE.where(
        "ClinicalAssessment",
        lambda r: r.get("_episode_id") == episode["id"] and r.get("status") == "IN_PROGRESS" and r["id"] != assessment["id"],
    ):
        sibling["status"] = "SUPERSEDED"
        sibling["updated_at"] = iso(now)
        sibling["version"] = sibling.get("version", 1) + 1

    engine.place_episode(episode, assessment, now)
    duties.record_utilization_step(episode, "assessment_cosign", user_id)
    return object_response(public(assessment))


@bp.route("/facilities/<facility_id>/assessments/<assessment_id>/cancel", methods=["POST"])
def cancel_assessment(facility_id, assessment_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Clinician", "ClinicalDirector"])
    facility = facility_in_path(facility_id)
    assessment = _assessment_in_path(facility, assessment_id)
    episode = STORE.get("TreatmentEpisode", assessment["_episode_id"])
    if episode is None:
        raise ApiError("ERR_EPISODE_NOT_FOUND")

    status = episode.get("clinical_status")
    if status not in ("AWAITING_ASSESSMENT", "UNDER_ASSESSMENT", "AWAITING_AUTHORIZATION"):
        raise ApiError("ERR_EPISODE_NOT_UNDER_ASSESSMENT")
    if assessment.get("status") not in ("IN_PROGRESS", "COMPLETED"):
        raise ApiError("ERR_ASSESSMENT_NOT_IN_PROGRESS")

    now = STORE.now()
    assessment["status"] = "CANCELLED"
    assessment["version"] = assessment.get("version", 1) + 1
    assessment["updated_at"] = iso(now)

    episode["assigned_level"] = None
    episode["clinical_status"] = "AWAITING_ASSESSMENT"
    episode["version"] = episode.get("version", 1) + 1
    episode["updated_at"] = iso(now)

    for authorization in STORE.where("LevelOfCareAuthorization", lambda r: r.get("_episode_id") == episode["id"]):
        if authorization.get("posture") in ("PENDING", "APPROVED"):
            authorization["posture"] = "EXPIRED"
            authorization["version"] = authorization.get("version", 1) + 1
            authorization["updated_at"] = iso(now)

    return object_response(public(assessment))


# ---------------------------------------------------------------------------
# Authorizations
# ---------------------------------------------------------------------------

@bp.route("/facilities/<facility_id>/treatment-episodes/<episode_id>/authorizations", methods=["POST"])
def create_authorization(facility_id, episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["UtilizationReviewer"])
    facility = facility_in_path(facility_id)
    episode = episode_in_path(facility, episode_id)
    body = json_body()
    check_allowed(body, {"payer_id", "requested_level", "bed_id"})
    require_fields(body, ["payer_id", "requested_level"])
    check_idempotency("authorizations:%s" % episode["id"], body)

    payer_id = as_string(body, "payer_id")
    resolve_payer(payer_id)
    requested_level = as_enum(body, "requested_level", ASAM_LEVELS)
    bed_id = opt_string(body, "bed_id")

    if not facility.get("licensed"):
        raise ApiError("ERR_FACILITY_NOT_LICENSED")

    bed = None
    if bed_id:
        bed = STORE.get("Bed", bed_id)
        if bed is None or bed.get("facility_id") != facility["id"]:
            raise ApiError("ERR_BED_NOT_FOUND")

    # PRD §3.2 gates the *initial* funding request on AWAITING_AUTHORIZATION. PRD §3.6
    # requires a level-of-care change on an IN_TREATMENT episode to be funded by "the
    # authorization_id funding the target level", so a request must also be possible
    # once treatment has begun — otherwise the whole step-down pathway is unreachable.
    if episode.get("clinical_status") not in ("AWAITING_AUTHORIZATION", "IN_TREATMENT"):
        raise ApiError("ERR_EPISODE_NOT_AWAITING_AUTHORIZATION")

    priors = STORE.where("LevelOfCareAuthorization", lambda r: r.get("_episode_id") == episode["id"])
    if priors:
        all_terminal = all(r.get("posture") in ("DENIED", "EXPIRED", "EXHAUSTED") for r in priors)
        level_differs = all(r.get("requested_level") != requested_level for r in priors)
        if not (all_terminal or level_differs):
            raise ApiError("ERR_AUTHORIZATION_NOT_REOPENABLE")

    if level_rank(requested_level) > level_rank(facility.get("as_level_max")):
        raise ApiError("ERR_LEVEL_EXCEEDS_FACILITY_LICENSE")

    now = STORE.now()
    row = base_fields("LevelOfCareAuthorization")
    row.update({
        "episode_id": episode["id"],
        "_episode_id": episode["id"],
        "facility_id": facility["id"],
        "_facility_id": facility["id"],
        "payer_id": payer_id,
        "requested_level": requested_level,
        "granted_level": None,
        "authorized_days": 0,
        "days_used": 0,
        "days_remaining": 0,
        "review_due_at": None,
        "concurrent_review_count": 0,
        "urgency_score": 0.0,
        "posture": "PENDING",
        "bed_id": bed_id,
        "_bed_held": False,
        "_created_seq": STORE.next_episode_seq(episode["id"]),
    })

    if level_rank(requested_level) >= 2 and bed is not None and bed.get("status") == "AVAILABLE":
        engine.schedule_bed_occupancy(bed, now)
        row["_bed_held"] = True

    STORE.put("LevelOfCareAuthorization", row)
    duties.record_utilization_step(episode, "authorization_request", user_id)
    return object_response(public(row), 201)


def _authorization_in_path(facility, authorization_id):
    row = STORE.get("LevelOfCareAuthorization", authorization_id)
    if row is None or row.get("facility_id") != facility["id"]:
        raise ApiError("ERR_AUTHORIZATION_NOT_FOUND")
    return row


@bp.route("/facilities/<facility_id>/treatment-episodes/<episode_id>/authorizations", methods=["GET"])
def list_episode_authorizations(facility_id, episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    facility = facility_in_path(facility_id)
    episode = episode_in_path(facility, episode_id)
    limit, offset = page_params(request.args)
    rows = _ordered(STORE.where("LevelOfCareAuthorization", lambda r: r.get("_episode_id") == episode["id"]))
    posture = filter_param(request.args, "posture")
    if posture:
        rows = [r for r in rows if r.get("posture") == posture]
    page = paginate(rows, limit, offset)
    return array_response([public(r) for r in page["rows"]], page)


@bp.route("/facilities/<facility_id>/authorizations/<authorization_id>/approve", methods=["POST"])
def approve_authorization(facility_id, authorization_id):
    user_id, role = caller()
    require_roles(user_id, role, ["UtilizationReviewer"])
    facility = facility_in_path(facility_id)
    authorization = _authorization_in_path(facility, authorization_id)
    episode = STORE.get("TreatmentEpisode", authorization["_episode_id"])

    if authorization.get("posture") != "PENDING":
        raise ApiError("ERR_AUTHORIZATION_NOT_PENDING")
    if level_rank(authorization.get("requested_level")) > level_rank(facility.get("as_level_max")):
        raise ApiError("ERR_LEVEL_EXCEEDS_FACILITY_LICENSE")

    payer = STORE.get("Payer", authorization.get("payer_id"))
    if payer is None:
        raise ApiError("ERR_PAYER_NOT_FOUND")

    floor_map = payer.get("credential_min_tier_by_loc") or {}
    floor_tier = floor_map.get(authorization.get("requested_level"))
    if floor_tier is not None and not engine.authoring_credential_ok_soft(
        {"credential_tier": facility.get("state_min_credential_tier")}, floor_tier
    ):
        raise ApiError("ERR_PAYER_CREDENTIAL_TIER_UNMET")
    if floor_tier is not None:
        plan = engine.any_treatment_plan(episode) if episode else None
        clinician = STORE.get("Clinician", plan.get("author_clinician_id")) if plan else None
        if clinician is not None and not engine.authoring_credential_ok_soft(clinician, floor_tier):
            raise ApiError("ERR_PAYER_CREDENTIAL_TIER_UNMET")

    now = STORE.now()
    granted_level = authorization.get("requested_level")
    authorization["granted_level"] = granted_level
    interval = int(payer.get("concurrent_review_interval_days") or 0)
    initial_map = payer.get("initial_authorized_days_by_loc") or {}
    authorized_days = int(initial_map.get(granted_level) or 0)
    authorization["authorized_days"] = authorized_days
    # PRD §3.2 measures the persisted variant "against the granted days alone", so the
    # grant made at approval is retained separately from the running authorized_days
    # that a concurrent review later extends.
    authorization["granted_days"] = authorized_days
    authorization["days_remaining"] = authorized_days
    authorization["review_due_at"] = iso(now + _days(authorized_days - interval))
    authorization["posture"] = "APPROVED"
    authorization["version"] = authorization.get("version", 1) + 1
    authorization["updated_at"] = iso(now)

    if episode is not None:
        engine.promote_to_awaiting_admission(authorization, now)

    if episode is not None:
        engine.recompute_authorization_urgency(episode)
    duties.record_utilization_step(episode, "authorization_approve", user_id)
    return object_response(public(authorization))


def _days(count):
    from datetime import timedelta

    return timedelta(days=count)


@bp.route("/facilities/<facility_id>/authorizations/<authorization_id>/deny", methods=["POST"])
def deny_authorization(facility_id, authorization_id):
    user_id, role = caller()
    require_roles(user_id, role, ["UtilizationReviewer"])
    facility = facility_in_path(facility_id)
    authorization = _authorization_in_path(facility, authorization_id)
    episode = STORE.get("TreatmentEpisode", authorization["_episode_id"])
    posture = authorization.get("posture")

    if posture == "DENIED":
        raise ApiError("ERR_AUTHORIZATION_ALREADY_DENIED")
    if posture not in ("PENDING", "APPROVED", "CONCURRENT_REVIEW_DUE"):
        raise ApiError("ERR_AUTHORIZATION_NOT_PENDING")
    if posture in ("APPROVED", "CONCURRENT_REVIEW_DUE") and int(authorization.get("days_used") or 0) <= 0:
        raise ApiError("ERR_AUTHORIZATION_UNUSED")

    now = STORE.now()
    if posture == "PENDING":
        authorization["posture"] = "DENIED"
    else:
        authorization["posture"] = "STEP_DOWN_REQUIRED"
        if episode is not None and episode.get("care_level_status") == "ACTIVE":
            episode["care_level_status"] = "STEP_DOWN_PENDING"
            episode["version"] = episode.get("version", 1) + 1
            episode["updated_at"] = iso(now)
    authorization["version"] = authorization.get("version", 1) + 1
    authorization["updated_at"] = iso(now)
    duties.record_utilization_step(episode, "authorization_deny", user_id)
    return object_response(public(authorization))


@bp.route("/facilities/<facility_id>/authorizations/<authorization_id>/submit-concurrent-review", methods=["POST"])
def submit_concurrent_review(facility_id, authorization_id):
    user_id, role = caller()
    require_roles(user_id, role, ["UtilizationReviewer"])
    facility = facility_in_path(facility_id)
    authorization = _authorization_in_path(facility, authorization_id)
    episode = STORE.get("TreatmentEpisode", authorization["_episode_id"])

    posture = authorization.get("posture")
    if posture in ("EXHAUSTED", "EXPIRED"):
        raise ApiError("ERR_AUTHORIZATION_DAYS_EXHAUSTED")
    if int(authorization.get("days_remaining") or 0) <= 0:
        raise ApiError("ERR_AUTHORIZATION_DAYS_EXHAUSTED")
    if posture not in ("APPROVED", "CONCURRENT_REVIEW_DUE", "EXTENDED", "STEP_DOWN_REQUIRED"):
        raise ApiError("ERR_AUTHORIZATION_NOT_PENDING")

    payer = STORE.get("Payer", authorization.get("payer_id"))
    interval = int((payer or {}).get("concurrent_review_interval_days") or 0)
    now = STORE.now()
    authorized_days = int(authorization.get("authorized_days") or 0) + interval
    authorization["authorized_days"] = authorized_days
    authorization["days_remaining"] = max(0, authorized_days - int(authorization.get("days_used") or 0))
    authorization["concurrent_review_count"] = int(authorization.get("concurrent_review_count") or 0) + 1
    authorization["review_due_at"] = iso(now + _days(authorized_days - interval))
    authorization["posture"] = "APPROVED"
    authorization["version"] = authorization.get("version", 1) + 1
    authorization["updated_at"] = iso(now)

    if episode is not None:
        engine.recompute_authorization_urgency(episode)
    duties.record_utilization_step(episode, "concurrent_review", user_id)
    return object_response(public(authorization))