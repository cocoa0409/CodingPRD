"""Clearances, withdrawal management, treatment plans and sessions."""

from datetime import timedelta

from flask import Blueprint, request

from common import (
    CREDENTIAL_TIERS,
    base_fields,
    check_allowed,
    filter_param,
    iso,
    opt_int,
    opt_string,
    page_params,
    paginate,
    parse_iso,
    public,
    require_fields,
    as_bool,
    as_enum,
    as_int,
    as_string,
    touch,
)
from db import STORE
from errors import ApiError
from middleware import (
    caller,
    check_idempotency,
    episode_in_path,
    facility_in_path,
    json_body,
    require_roles,
    resolve_clinician,
    resolve_service,
    resolve_payer,
)
from response import array_response, object_response
from services import calc, duties, engine, facility as facility_svc
from services.engine import clearance_view

bp = Blueprint("clinical", __name__)

CLEARANCE_TYPES = ["MEDICAL", "PSYCHIATRIC", "TB_SCREEN"]
PROTOCOLS = ["NONE", "ALCOHOL_TAPER", "OPIOID_AGONIST", "BENZO_TAPER"]
WM_STATUSES = ["ACTIVE", "MEDICALLY_STABLE", "COMPLICATED"]
PLAN_STATUSES = ["DRAFT", "PENDING_COSIGN", "ACTIVE", "SUPERSEDED", "REJECTED"]
SESSION_STATUSES = ["SCHEDULED", "ATTENDED", "NO_SHOW", "CANCELLED"]


def _ordered(rows):
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_created_seq") or 0))


# ---------------------------------------------------------------------------
# Medical clearances
# ---------------------------------------------------------------------------

@bp.route("/facilities/<facility_id>/treatment-episodes/<episode_id>/medical-clearances", methods=["POST"])
def create_clearance(facility_id, episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["AdmissionsIntakeNurse", "Clinician"])
    facility = facility_in_path(facility_id)
    episode = episode_in_path(facility, episode_id)
    body = json_body()
    check_allowed(body, {"clearance_type"})
    require_fields(body, ["clearance_type"])
    ctype = as_enum(body, "clearance_type", CLEARANCE_TYPES)

    now = STORE.now()
    row = base_fields("MedicalClearance")
    row.update({
        "episode_id": episode["id"],
        "_episode_id": episode["id"],
        "facility_id": facility["id"],
        "_facility_id": facility["id"],
        "clearance_type": ctype,
        "status": "PENDING",
        "ordered_at": iso(now),
        "cleared_at": None,
        "expires_at": None,
        "_created_seq": STORE.next_episode_seq(episode["id"]),
    })
    STORE.put("MedicalClearance", row)
    return object_response(clearance_view(row, now), 201)


def _clearance_in_path(facility, clearance_id):
    row = STORE.get("MedicalClearance", clearance_id)
    if row is None or row.get("facility_id") != facility["id"]:
        raise ApiError("ERR_ASSESSMENT_NOT_FOUND")
    return row


@bp.route("/facilities/<facility_id>/treatment-episodes/<episode_id>/medical-clearances", methods=["GET"])
def list_episode_clearances(facility_id, episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    facility = facility_in_path(facility_id)
    episode = episode_in_path(facility, episode_id)
    limit, offset = page_params(request.args)
    rows = _ordered(STORE.where("MedicalClearance", lambda r: r.get("_episode_id") == episode["id"]))
    ctype = filter_param(request.args, "clearance_type")
    status = filter_param(request.args, "status")
    if ctype:
        rows = [r for r in rows if r.get("clearance_type") == ctype]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    page = paginate(rows, limit, offset)
    now = STORE.now()
    return array_response([clearance_view(r, now) for r in page["rows"]], page)


@bp.route("/facilities/<facility_id>/medical-clearances/<clearance_id>/clear", methods=["POST"])
def clear_clearance(facility_id, clearance_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Clinician", "ClinicalDirector"])
    facility = facility_in_path(facility_id)
    row = _clearance_in_path(facility, clearance_id)
    now = STORE.now()
    row["status"] = "CLEARED"
    row["cleared_at"] = iso(now)
    row["expires_at"] = iso(now + timedelta(days=calc.CLEARANCE_VALIDITY_DAYS))
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = iso(now)
    engine.promote_to_awaiting_admission(row, now)
    return object_response(clearance_view(row, now))


@bp.route("/facilities/<facility_id>/medical-clearances/<clearance_id>/fail", methods=["POST"])
def fail_clearance(facility_id, clearance_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Clinician", "ClinicalDirector"])
    facility = facility_in_path(facility_id)
    row = _clearance_in_path(facility, clearance_id)
    now = STORE.now()
    row["status"] = "FAILED"
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = iso(now)
    return object_response(clearance_view(row, now))


# ---------------------------------------------------------------------------
# Withdrawal management
# ---------------------------------------------------------------------------

def _validate_dose_records(records):
    if not isinstance(records, list):
        raise ApiError("ERR_INVALID_REQUEST", "dose_records must be an array.")
    out = []
    for item in records:
        if not isinstance(item, dict):
            raise ApiError("ERR_INVALID_REQUEST", "Each dose record must be an object.")
        for field in ("medication_code", "dose_mg", "given_at", "given_by_clinician_id"):
            if field not in item:
                raise ApiError("ERR_INVALID_REQUEST", "Dose record is missing '%s'." % field)
        resolve_clinician(item.get("given_by_clinician_id"))
        out.append({
            "medication_code": item.get("medication_code"),
            "dose_mg": item.get("dose_mg"),
            "given_at": iso(parse_iso(item.get("given_at"), "given_at")),
            "given_by_clinician_id": item.get("given_by_clinician_id"),
        })
    return out


@bp.route("/facilities/<facility_id>/treatment-episodes/<episode_id>/withdrawal-management", methods=["POST"])
def create_wm(facility_id, episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Clinician"])
    facility = facility_in_path(facility_id)
    episode = episode_in_path(facility, episode_id)
    body = json_body()
    check_allowed(body, {"protocol", "ciwa_score", "dose_records"})
    require_fields(body, ["protocol", "ciwa_score", "dose_records"])

    # PRD §3.3 names the withdrawal-management record as an admission
    # precondition that must read ACTIVE at the admission gate, so it is authored
    # during the AWAITING_ADMISSION staging window as well as once treatment has
    # begun. PRD §3.4 gates session scheduling on IN_TREATMENT alone, and that gate
    # is enforced separately below.
    if episode.get("clinical_status") not in ("AWAITING_ADMISSION", "IN_TREATMENT"):
        raise ApiError("ERR_EPISODE_NOT_IN_TREATMENT")

    protocol = as_enum(body, "protocol", PROTOCOLS)
    ciwa = as_int(body, "ciwa_score")
    if ciwa < 0 or ciwa > 30:
        raise ApiError("ERR_INVALID_REQUEST", "ciwa_score must be between 0 and 30.")
    doses = _validate_dose_records(body.get("dose_records"))

    now = STORE.now()
    row = base_fields("WithdrawalManagementPlan")
    row.update({
        "episode_id": episode["id"],
        "_episode_id": episode["id"],
        "facility_id": facility["id"],
        "_facility_id": facility["id"],
        "protocol": protocol,
        "ciwa_score": ciwa,
        "ciwa_recorded_at": iso(now),
        "dose_records": doses,
        "status": "ACTIVE",
        "_created_seq": STORE.next_episode_seq(episode["id"]),
    })
    STORE.put("WithdrawalManagementPlan", row)
    engine.recompute_authorization_urgency(episode)
    return object_response(public(row), 201)


@bp.route("/facilities/<facility_id>/treatment-episodes/<episode_id>/withdrawal-management", methods=["GET"])
def list_episode_wm(facility_id, episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    facility = facility_in_path(facility_id)
    episode = episode_in_path(facility, episode_id)
    limit, offset = page_params(request.args)
    rows = _ordered(STORE.where("WithdrawalManagementPlan", lambda r: r.get("_episode_id") == episode["id"]))
    status = filter_param(request.args, "status")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    page = paginate(rows, limit, offset)
    return array_response([public(r) for r in page["rows"]], page)


@bp.route("/facilities/<facility_id>/withdrawal-management", methods=["GET"])
def list_facility_wm(facility_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    facility = facility_in_path(facility_id)
    limit, offset = page_params(request.args)
    rows = _ordered(STORE.where("WithdrawalManagementPlan", lambda r: r.get("_facility_id") == facility["id"]))
    status = filter_param(request.args, "status")
    episode_id = filter_param(request.args, "episode_id")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    if episode_id:
        rows = [r for r in rows if r.get("episode_id") == episode_id]
    page = paginate(rows, limit, offset)
    return array_response([public(r) for r in page["rows"]], page)


@bp.route("/facilities/<facility_id>/withdrawal-management/<wm_id>", methods=["PUT"])
def update_wm(facility_id, wm_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Clinician"])
    facility = facility_in_path(facility_id)
    row = STORE.get("WithdrawalManagementPlan", wm_id)
    if row is None or row.get("facility_id") != facility["id"]:
        raise ApiError("ERR_PLAN_NOT_FOUND")
    body = json_body()
    check_allowed(body, {"ciwa_score", "dose_records", "status"})

    now = STORE.now()
    if "ciwa_score" in body and body.get("ciwa_score") is not None:
        ciwa = as_int(body, "ciwa_score")
        if ciwa < 0 or ciwa > 30:
            raise ApiError("ERR_INVALID_REQUEST", "ciwa_score must be between 0 and 30.")
        row["ciwa_score"] = ciwa
        row["ciwa_recorded_at"] = iso(now)
    if "dose_records" in body and body.get("dose_records") is not None:
        row["dose_records"] = _validate_dose_records(body.get("dose_records"))
    if "status" in body and body.get("status") is not None:
        row["status"] = as_enum(body, "status", WM_STATUSES)

    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = iso(now)

    episode = STORE.get("TreatmentEpisode", row["_episode_id"])
    if episode is not None:
        engine.recompute_authorization_urgency(episode)
    return object_response(public(row))


# ---------------------------------------------------------------------------
# Treatment plans
# ---------------------------------------------------------------------------

def _plan_in_path(facility, plan_id):
    row = STORE.get("TreatmentPlan", plan_id)
    if row is None or row.get("facility_id") != facility["id"]:
        raise ApiError("ERR_PLAN_NOT_FOUND")
    return row


@bp.route("/facilities/<facility_id>/treatment-episodes/<episode_id>/treatment-plans", methods=["POST"])
def create_treatment_plan(facility_id, episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Clinician"])
    facility = facility_in_path(facility_id)
    episode = episode_in_path(facility, episode_id)
    body = json_body()
    allowed = {"author_clinician_id", "cosign_rationale_code", "expected_treatment_episode_version", "supersedes_plan_id"}
    check_allowed(body, allowed)
    require_fields(body, ["author_clinician_id", "cosign_rationale_code", "expected_treatment_episode_version"])
    check_idempotency("treatment-plans:%s" % episode["id"], body)

    expected = body.get("expected_treatment_episode_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError("ERR_INVALID_REQUEST", "expected_treatment_episode_version must be an integer.")
    if expected != episode.get("version"):
        raise ApiError("ERR_STALE_VERSION")

    author_id = as_string(body, "author_clinician_id")
    resolve_clinician(author_id)
    rationale = as_string(body, "cosign_rationale_code")
    supersedes_id = opt_string(body, "supersedes_plan_id")

    # PRD §3.4 + §2.7a priority 18: plan drafting requires IN_TREATMENT. PRD §3.3
    # nevertheless names the ACTIVE treatment plan as an admission precondition, so
    # a plan authored during the AWAITING_ADMISSION staging window is also accepted —
    # the admission gate's own check remains the authority on what may be admitted.
    if episode.get("clinical_status") not in ("AWAITING_ADMISSION", "IN_TREATMENT"):
        raise ApiError("ERR_EPISODE_NOT_IN_TREATMENT")
    if facility_svc.has_revoked_accreditation_body(facility):
        raise ApiError("ERR_FACILITY_ACCREDITATION_REVOKED")

    now = STORE.now()
    engine.authoring_credential_ok(author_id, facility, now)

    for prior in STORE.where(
        "TreatmentPlan",
        lambda r: r.get("_episode_id") == episode["id"] and r.get("status") == "ACTIVE",
    ):
        prior["status"] = "SUPERSEDED"
        prior["version"] = prior.get("version", 1) + 1
        prior["updated_at"] = iso(now)

    row = base_fields("TreatmentPlan")
    row.update({
        "episode_id": episode["id"],
        "_episode_id": episode["id"],
        "facility_id": facility["id"],
        "_facility_id": facility["id"],
        "author_clinician_id": author_id,
        "required_sessions_per_week": calc.required_sessions(episode.get("assigned_level")),
        "status": "DRAFT",
        "cosign_rationale_code": rationale,
        "supersedes_plan_id": supersedes_id,
        "cosign_granted": False,
        "_created_seq": STORE.next_episode_seq(episode["id"]),
    })
    STORE.put("TreatmentPlan", row)

    episode["version"] = episode.get("version", 1) + 1
    episode["updated_at"] = iso(now)
    return object_response(public(row), 201)


@bp.route("/facilities/<facility_id>/treatment-episodes/<episode_id>/treatment-plans", methods=["GET"])
def list_episode_plans(facility_id, episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    facility = facility_in_path(facility_id)
    episode = episode_in_path(facility, episode_id)
    limit, offset = page_params(request.args)
    rows = _ordered(STORE.where("TreatmentPlan", lambda r: r.get("_episode_id") == episode["id"]))
    status = filter_param(request.args, "status")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    page = paginate(rows, limit, offset)
    return array_response([public(r) for r in page["rows"]], page)


@bp.route("/facilities/<facility_id>/treatment-plans", methods=["GET"])
def list_facility_plans(facility_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    facility = facility_in_path(facility_id)
    limit, offset = page_params(request.args)
    rows = _ordered(STORE.where("TreatmentPlan", lambda r: r.get("_facility_id") == facility["id"]))
    status = filter_param(request.args, "status")
    episode_id = filter_param(request.args, "episode_id")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    if episode_id:
        rows = [r for r in rows if r.get("episode_id") == episode_id]
    page = paginate(rows, limit, offset)
    return array_response([public(r) for r in page["rows"]], page)


@bp.route("/treatment-plans/<plan_id>", methods=["PUT"])
def update_plan(plan_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Clinician", "ClinicalDirector"])
    row = STORE.get("TreatmentPlan", plan_id)
    if row is None:
        raise ApiError("ERR_PLAN_NOT_FOUND")
    body = json_body()
    check_allowed(body, {"author_clinician_id", "cosign_rationale_code", "expected_treatment_plan_version"})
    require_fields(body, ["expected_treatment_plan_version"])

    expected = body.get("expected_treatment_plan_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError("ERR_INVALID_REQUEST", "expected_treatment_plan_version must be an integer.")
    if expected != row.get("version"):
        raise ApiError("ERR_STALE_VERSION")

    if "author_clinician_id" in body and body.get("author_clinician_id") is not None:
        author_id = as_string(body, "author_clinician_id")
        resolve_clinician(author_id)
        row["author_clinician_id"] = author_id
    if "cosign_rationale_code" in body and body.get("cosign_rationale_code") is not None:
        row["cosign_rationale_code"] = as_string(body, "cosign_rationale_code")

    now = STORE.now()
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = iso(now)
    return object_response(public(row))


@bp.route("/facilities/<facility_id>/treatment-plans/<plan_id>/submit-for-cosign", methods=["POST"])
def submit_for_cosign(facility_id, plan_id):
    user_id, role = caller()
    require_roles(user_id, role, ["ClinicalDirector"])
    facility = facility_in_path(facility_id)
    row = _plan_in_path(facility, plan_id)
    episode = STORE.get("TreatmentEpisode", row["_episode_id"])
    duties.assert_segregation(episode, user_id)

    now = STORE.now()
    row["status"] = "ACTIVE"
    row["cosign_granted"] = True
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = iso(now)
    if episode is not None:
        duties.record_so_step(episode, "submit_for_cosign", user_id)
    return object_response(public(row))


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

@bp.route("/facilities/<facility_id>/treatment-episodes/<episode_id>/sessions", methods=["POST"])
def create_session(facility_id, episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["AdmissionsIntakeNurse", "Clinician"])
    facility = facility_in_path(facility_id)
    episode = episode_in_path(facility, episode_id)
    body = json_body()
    # PRD §3.4 owns `status`, `attended` and `billing_amount_cents` on this row:
    # "The row starts at `SCHEDULED` with `attended` false and
    # `billing_amount_cents` 0." Client input for them is ignored, not refused.
    check_allowed(body, {"service_id", "clinician_id", "scheduled_at", "duration_minutes",
                         "status", "attended", "billing_amount_cents"})
    require_fields(body, ["service_id", "clinician_id", "scheduled_at", "duration_minutes"])
    check_idempotency("sessions:%s" % episode["id"], body)

    service_id = as_string(body, "service_id")
    service = resolve_service(service_id, facility)
    clinician_id = as_string(body, "clinician_id")
    resolve_clinician(clinician_id)
    scheduled_at = parse_iso(body.get("scheduled_at"), "scheduled_at")
    duration = as_int(body, "duration_minutes")
    # PRD §2.7 validates request shape at the resolution layer, ahead of any state
    # rule; a non-positive duration is a shape failure, not a state failure.
    if duration <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "duration_minutes must be a positive integer.")

    if episode.get("clinical_status") != "IN_TREATMENT":
        raise ApiError("ERR_EPISODE_NOT_IN_TREATMENT")
    if facility.get("facility_posture") == "FROZEN":
        raise ApiError("ERR_FACILITY_POSTURE_FROZEN")
    if facility_svc.has_revoked_accreditation_body(facility):
        raise ApiError("ERR_FACILITY_ACCREDITATION_REVOKED")

    now = STORE.now()
    row = base_fields("SessionAttendance")
    row.update({
        "episode_id": episode["id"],
        "_episode_id": episode["id"],
        "facility_id": facility["id"],
        "_facility_id": facility["id"],
        "service_id": service_id,
        "clinician_id": clinician_id,
        "scheduled_at": iso(scheduled_at),
        "duration_minutes": duration,
        "attended": False,
        "status": "SCHEDULED",
        "billing_amount_cents": 0,
        "_created_seq": STORE.next_episode_seq(episode["id"]),
    })
    STORE.put("SessionAttendance", row)
    return object_response(public(row), 201)


def _session_in_path(facility, session_id):
    row = STORE.get("SessionAttendance", session_id)
    if row is None or row.get("facility_id") != facility["id"]:
        raise ApiError("ERR_SESSION_NOT_FOUND")
    return row


@bp.route("/facilities/<facility_id>/treatment-episodes/<episode_id>/sessions", methods=["GET"])
def list_episode_sessions(facility_id, episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    facility = facility_in_path(facility_id)
    episode = episode_in_path(facility, episode_id)
    limit, offset = page_params(request.args)
    rows = _ordered(STORE.where("SessionAttendance", lambda r: r.get("_episode_id") == episode["id"]))
    status = filter_param(request.args, "status")
    service_id = filter_param(request.args, "service_id")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    if service_id:
        rows = [r for r in rows if r.get("service_id") == service_id]
    page = paginate(rows, limit, offset)
    return array_response([public(r) for r in page["rows"]], page)


@bp.route("/facilities/<facility_id>/sessions/<session_id>/record-attendance", methods=["POST"])
def record_attendance(facility_id, session_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Clinician"])
    facility = facility_in_path(facility_id)
    row = _session_in_path(facility, session_id)
    body = json_body()
    check_allowed(body, {"attended"})
    require_fields(body, ["attended"])
    attended = as_bool(body, "attended")

    service = STORE.get("ServiceOffering", row.get("service_id"))
    level = service.get("level_of_care") if service else "ASAM_1_0"
    now = STORE.now()
    row["attended"] = attended
    row["status"] = "ATTENDED" if attended else "NO_SHOW"
    if attended:
        row["billing_amount_cents"] = calc.session_billing_amount(level, row.get("duration_minutes"))
    else:
        row["billing_amount_cents"] = 0
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = iso(now)

    episode = STORE.get("TreatmentEpisode", row["_episode_id"])
    if episode is not None:
        engine.recompute_episode_revenue(episode)
    return object_response(public(row))


@bp.route("/facilities/<facility_id>/sessions/<session_id>/cancel", methods=["POST"])
def cancel_session(facility_id, session_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Clinician"])
    facility = facility_in_path(facility_id)
    row = _session_in_path(facility, session_id)
    now = STORE.now()
    row["status"] = "CANCELLED"
    row["billing_amount_cents"] = 0
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = iso(now)

    episode = STORE.get("TreatmentEpisode", row["_episode_id"])
    if episode is not None:
        engine.recompute_episode_revenue(episode)
    return object_response(public(row))