"""Level-of-care changes, continuing care, recovery housing placement, alumni
contacts and the episode lifecycle actions (admit / complete / discharge)."""

from datetime import timedelta

from flask import Blueprint, request

from common import (
    ASAM_LEVELS,
    HOUSING_BASES,
    SHELTER_CLASSES,
    base_fields,
    check_allowed,
    filter_param,
    iso,
    level_rank,
    opt_bool,
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
    tier_rank,
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
    resolve_payer,
)
from response import array_response, object_response
from services import calc, duties, engine, facility as facility_svc
from services.engine import clearance_view

bp = Blueprint("changes", __name__)

CONTACT_OUTCOMES = ["REACHED", "UNREACHABLE", "DECLINED"]

ALLOWED_ROUTES = {
    ("ASAM_3_7", "ASAM_3_5"), ("ASAM_3_7", "ASAM_3_1"),
    ("ASAM_3_5", "ASAM_3_1"), ("ASAM_3_5", "ASAM_2_1"),
    ("ASAM_3_1", "ASAM_2_1"), ("ASAM_3_1", "ASAM_1_0"),
    ("ASAM_2_1", "ASAM_1_0"),
}
ALLOWED_ROUTES |= {(to_lvl, from_lvl) for (from_lvl, to_lvl) in list(ALLOWED_ROUTES)}


def _ordered(rows):
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_created_seq") or 0))


# ---------------------------------------------------------------------------
# Admission / completion / discharge
# ---------------------------------------------------------------------------

@bp.route("/facilities/<facility_id>/treatment-episodes/<episode_id>/admit", methods=["POST"])
def admit(facility_id, episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["AdmissionsIntakeNurse"])
    facility = facility_in_path(facility_id)
    episode = episode_in_path(facility, episode_id)
    duties.assert_segregation(episode, user_id)

    if facility.get("facility_posture") == "FROZEN":
        raise ApiError("ERR_FACILITY_POSTURE_FROZEN")
    engine.admit_episode(facility, episode, STORE.now(), user_id)
    duties.record_so_step(episode, "admit", user_id)
    return object_response(public(episode))


@bp.route("/facilities/<facility_id>/treatment-episodes/<episode_id>/complete-treatment", methods=["POST"])
def complete_treatment(facility_id, episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["ClinicalDirector"])
    facility = facility_in_path(facility_id)
    episode = episode_in_path(facility, episode_id)
    duties.assert_segregation(episode, user_id)

    status = episode.get("clinical_status")
    if status == "DISCHARGED":
        raise ApiError("ERR_ALREADY_DISCHARGED")
    if status != "IN_TREATMENT":
        raise ApiError("ERR_EPISODE_NOT_IN_TREATMENT")

    plan = engine.withdrawal_plan(episode)
    if plan is None or plan.get("status") != "MEDICALLY_STABLE":
        raise ApiError("ERR_WITHDRAWAL_MANAGEMENT_NOT_STABLE")

    treatment_plan = engine.active_treatment_plan(episode)
    if treatment_plan is None or not treatment_plan.get("cosign_granted"):
        raise ApiError("ERR_TREATMENT_PLAN_NOT_ACTIVE")

    _, _, compliant, _ = calc.curriculum_status(episode, engine.session_rows(episode), STORE.now())
    if not compliant:
        raise ApiError("ERR_CURRICULUM_NOT_COMPLETE")

    now = STORE.now()
    episode["clinical_status"] = "COMPLETED"
    episode["version"] = episode.get("version", 1) + 1
    episode["updated_at"] = iso(now)
    engine.recompute_episode_revenue(episode)
    duties.record_so_step(episode, "complete_treatment", user_id)
    return object_response(public(episode))


@bp.route("/facilities/<facility_id>/treatment-episodes/<episode_id>/discharge", methods=["POST"])
def discharge(facility_id, episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["ClinicalDirector"])
    facility = facility_in_path(facility_id)
    episode = episode_in_path(facility, episode_id)
    duties.assert_segregation(episode, user_id)

    engine.discharge_episode(facility, episode, STORE.now())
    duties.record_so_step(episode, "discharge", user_id)
    return object_response(public(episode))


# ---------------------------------------------------------------------------
# Level-of-care changes
# ---------------------------------------------------------------------------

@bp.route("/facilities/<facility_id>/treatment-episodes/<episode_id>/level-of-care-changes", methods=["POST"])
def appoint_change(facility_id, episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["ClinicalDirector", "UtilizationReviewer"])
    facility = facility_in_path(facility_id)
    episode = episode_in_path(facility, episode_id)
    body = json_body()
    allowed = {"authorization_id", "to_level", "effective_at", "expected_treatment_episode_version", "bed_id"}
    check_allowed(body, allowed)
    require_fields(body, ["authorization_id", "to_level", "effective_at", "expected_treatment_episode_version"])

    expected = body.get("expected_treatment_episode_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError("ERR_INVALID_REQUEST", "expected_treatment_episode_version must be an integer.")
    if expected != episode.get("version"):
        raise ApiError("ERR_STALE_VERSION")

    authorization_id = as_string(body, "authorization_id")
    authorization = STORE.get("LevelOfCareAuthorization", authorization_id)
    if authorization is None or authorization.get("facility_id") != facility["id"]:
        raise ApiError("ERR_AUTHORIZATION_NOT_FOUND")
    bed_id = opt_string(body, "bed_id")

    if bed_id:
        bed = STORE.get("Bed", bed_id)
        if bed is None:
            raise ApiError("ERR_BED_NOT_FOUND")
        # PRD §2.7: a body reference that exists but belongs to a different facility
        # from the one in the path is ERR_INVALID_REFERENCE, not a not-found code.
        if bed.get("facility_id") != facility["id"]:
            raise ApiError("ERR_INVALID_REFERENCE")

    # PRD §2.7 places request-shape validation at the resolution layer, ahead of the
    # state rules: the target level and the effective instant are body-shape concerns.
    to_level = as_enum(body, "to_level", ASAM_LEVELS)
    effective_at = parse_iso(body.get("effective_at"), "effective_at")

    if not facility.get("licensed"):
        raise ApiError("ERR_FACILITY_NOT_LICENSED")
    if facility.get("facility_posture") == "FROZEN":
        raise ApiError("ERR_FACILITY_POSTURE_FROZEN")
    if episode.get("clinical_status") != "IN_TREATMENT":
        raise ApiError("ERR_EPISODE_NOT_IN_TREATMENT")

    if int(episode.get("step_down_count") or 0) >= 2:
        raise ApiError("ERR_MAX_STEP_DOWNS_REACHED")

    payer = STORE.get("Payer", authorization.get("payer_id"))
    payer_id = authorization.get("payer_id")
    changes_under_payer = [
        r for r in STORE.where("LevelOfCareChange", lambda r: r.get("_episode_id") == episode["id"])
    ]
    same_payer = 0
    for row in changes_under_payer:
        auth = STORE.get("LevelOfCareAuthorization", row.get("authorization_id"))
        if auth is not None and auth.get("payer_id") == payer_id:
            same_payer += 1
    if same_payer >= 5:
        raise ApiError("ERR_MAX_CHANGE_PER_PAYER")

    if level_rank(to_level) > level_rank(facility.get("as_level_max")):
        raise ApiError("ERR_LEVEL_EXCEEDS_FACILITY_LICENSE")

    from_level = episode.get("assigned_level")
    # PRD §2.7a pins the sequence: "the level-route and coverage-map rules ... and
    # finally the fiscal rules", so the route test answers before the unused-days
    # test when both could fire.
    if from_level and (from_level, to_level) not in ALLOWED_ROUTES:
        raise ApiError("ERR_LEVEL_ROUTE_NOT_ALLOWED")

    if level_rank(to_level) < level_rank(from_level) and int(authorization.get("days_used") or 0) <= 0:
        raise ApiError("ERR_AUTHORIZATION_UNUSED")

    _check_bed_window(facility, bed_id, effective_at, authorization, episode)

    now = STORE.now()
    change_type = "STEP_UP" if level_rank(to_level) > level_rank(from_level) else "STEP_DOWN"
    row = base_fields("LevelOfCareChange")
    row.update({
        "episode_id": episode["id"],
        "_episode_id": episode["id"],
        "facility_id": facility["id"],
        "_facility_id": facility["id"],
        "authorization_id": authorization_id,
        "bed_id": bed_id,
        "from_level": from_level,
        "to_level": to_level,
        "change_type": change_type,
        "effective_at": iso(effective_at),
        "retry_available_at": None,
        "status": "PLANNED",
        "_step_up": False,
        "_created_seq": STORE.next_episode_seq(episode["id"]),
    })
    STORE.put("LevelOfCareChange", row)

    if change_type == "STEP_DOWN":
        episode["care_level_status"] = "STEP_DOWN_PENDING"
    episode["version"] = episode.get("version", 1) + 1
    episode["updated_at"] = iso(now)
    return object_response(public(row), 201)


def _check_bed_window(facility, bed_id, effective_at, authorization, episode):
    if not bed_id:
        return
    window_days = int(authorization.get("days_remaining") or 0)
    start = effective_at
    end = effective_at + timedelta(days=window_days)
    for other in STORE.where("LevelOfCareChange", lambda r: r.get("bed_id") == bed_id):
        other_start = parse_iso(other.get("effective_at"), "effective_at")
        other_auth = STORE.get("LevelOfCareAuthorization", other.get("authorization_id"))
        other_days = int((other_auth or {}).get("days_remaining") or 0)
        other_end = other_start + timedelta(days=other_days)
        if start < other_end and other_start < end:
            raise ApiError("ERR_BED_OCCUPANCY_OVERLAP")


def _change_in_path(facility, change_id):
    row = STORE.get("LevelOfCareChange", change_id)
    if row is None or row.get("facility_id") != facility["id"]:
        raise ApiError("ERR_CHANGE_NOT_FOUND")
    return row


@bp.route("/facilities/<facility_id>/treatment-episodes/<episode_id>/level-of-care-changes", methods=["GET"])
def list_episode_changes(facility_id, episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    facility = facility_in_path(facility_id)
    episode = episode_in_path(facility, episode_id)
    limit, offset = page_params(request.args)
    rows = _ordered(STORE.where("LevelOfCareChange", lambda r: r.get("_episode_id") == episode["id"]))
    status = filter_param(request.args, "status")
    change_type = filter_param(request.args, "change_type")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    if change_type:
        rows = [r for r in rows if r.get("change_type") == change_type]
    page = paginate(rows, limit, offset)
    return array_response([public(r) for r in page["rows"]], page)


@bp.route("/facilities/<facility_id>/level-of-care-changes/<change_id>/complete", methods=["POST"])
def complete_change(facility_id, change_id):
    user_id, role = caller()
    require_roles(user_id, role, ["ClinicalDirector"])
    facility = facility_in_path(facility_id)
    change = _change_in_path(facility, change_id)
    engine.complete_change(facility, change, STORE.now())
    return object_response(public(change))


@bp.route("/facilities/<facility_id>/level-of-care-changes/<change_id>/cancel", methods=["POST"])
def cancel_change(facility_id, change_id):
    user_id, role = caller()
    require_roles(user_id, role, ["ClinicalDirector"])
    facility = facility_in_path(facility_id)
    change = _change_in_path(facility, change_id)
    episode = STORE.get("TreatmentEpisode", change["_episode_id"])
    status = change.get("status")
    now = STORE.now()

    if status == "PLANNED":
        change["status"] = "CANCELLED"
        if episode is not None:
            episode["care_level_status"] = "ACTIVE"
            episode["version"] = episode.get("version", 1) + 1
            episode["updated_at"] = iso(now)
    elif status == "AWAITING_DISCHARGE":
        change["status"] = "CANCELLED"
        if episode is not None:
            episode["care_level_status"] = "ACTIVE"
            episode["version"] = episode.get("version", 1) + 1
            episode["updated_at"] = iso(now)
    elif status == "COMPLETED":
        completed_epoch = change.get("_completed_epoch")
        if completed_epoch is not None and completed_epoch != facility.get("ops_epoch"):
            raise ApiError("ERR_EPOCH_STALE")
        change["status"] = "CANCELLED"
        if episode is not None:
            episode["step_down_count"] = max(0, int(episode.get("step_down_count") or 0) - 1)
            episode["assigned_level"] = change.get("from_level")
            episode["care_level_status"] = "ACTIVE"
            episode["version"] = episode.get("version", 1) + 1
            episode["updated_at"] = iso(now)
        target = STORE.get("Bed", change.get("bed_id")) if change.get("bed_id") else None
        if target is not None and target.get("status") == "OCCUPIED":
            target["status"] = "AVAILABLE"
            target["next_available_at"] = None
            target["version"] = target.get("version", 1) + 1
            target["updated_at"] = iso(now)
        source_id = change.get("_source_bed_id")
        source = STORE.get("Bed", source_id) if source_id else None
        if source is None:
            for candidate in STORE.where("Bed", lambda r: r.get("_facility_id") == facility["id"] and r.get("status") == "CLEANING"):
                source = candidate
                break
        if source is not None and source.get("status") == "CLEANING" and source is not target:
            engine.schedule_bed_occupancy(source, now)
    elif status == "PENDING_DISCHARGE_ORDER":
        change["status"] = "CANCELLED"
        if episode is not None:
            episode["care_level_status"] = "ACTIVE"
            episode["version"] = episode.get("version", 1) + 1
            episode["updated_at"] = iso(now)
    else:
        raise ApiError("ERR_CHANGE_NOT_PLANNED")

    change["version"] = change.get("version", 1) + 1
    change["updated_at"] = iso(now)
    return object_response(public(change))


@bp.route("/facilities/<facility_id>/level-of-care-changes/<change_id>/step-up", methods=["POST"])
def step_up(facility_id, change_id):
    user_id, role = caller()
    require_roles(user_id, role, ["ClinicalDirector"])
    facility = facility_in_path(facility_id)
    change = _change_in_path(facility, change_id)
    body = json_body()
    check_allowed(body, {"bed_id"})
    require_fields(body, ["bed_id"])
    bed_id = as_string(body, "bed_id")
    bed = STORE.get("Bed", bed_id)
    if bed is None or bed.get("facility_id") != facility["id"]:
        raise ApiError("ERR_BED_NOT_FOUND")

    episode = STORE.get("TreatmentEpisode", change["_episode_id"])
    plan = engine.withdrawal_plan(episode) if episode else None
    if plan is None or plan.get("status") != "COMPLICATED":
        raise ApiError("ERR_WITHDRAWAL_MANAGEMENT_NOT_COMPLICATED")
    if bed.get("status") != "AVAILABLE":
        raise ApiError("ERR_BED_NOT_AVAILABLE")

    now = STORE.now()
    from_level = episode.get("assigned_level") if episode else change.get("to_level")
    to_level = bed.get("level_of_care")
    if from_level and (from_level, to_level) not in ALLOWED_ROUTES:
        raise ApiError("ERR_LEVEL_ROUTE_NOT_ALLOWED")

    row = base_fields("LevelOfCareChange")
    row.update({
        "episode_id": episode["id"],
        "_episode_id": episode["id"],
        "facility_id": facility["id"],
        "_facility_id": facility["id"],
        "authorization_id": change.get("authorization_id"),
        "bed_id": bed_id,
        "from_level": from_level,
        "to_level": to_level,
        "change_type": "STEP_UP",
        "effective_at": iso(now),
        "retry_available_at": None,
        "status": "COMPLETED",
        "_step_up": True,
        "_completed_epoch": facility.get("ops_epoch"),
        "_created_seq": STORE.next_episode_seq(episode["id"]),
    })
    STORE.put("LevelOfCareChange", row)

    source = engine.episode_bed(episode) if episode else None
    if source is not None and source["id"] != bed["id"]:
        engine.schedule_bed_release(source, now)
    engine.schedule_bed_occupancy(bed, now)

    if episode is not None:
        episode["assigned_level"] = to_level
        episode["step_down_count"] = max(0, int(episode.get("step_down_count") or 0) - 1)
        episode["care_level_status"] = "STEPPED_DOWN"
        episode["version"] = episode.get("version", 1) + 1
        episode["updated_at"] = iso(now)
    return object_response(public(row))


# ---------------------------------------------------------------------------
# Continuing care plans
# ---------------------------------------------------------------------------

def _cc_plan_in_path(facility, plan_id):
    row = STORE.get("ContinuingCarePlan", plan_id)
    if row is None or row.get("facility_id") != facility["id"]:
        raise ApiError("ERR_PLAN_NOT_FOUND")
    return row


@bp.route("/facilities/<facility_id>/treatment-episodes/<episode_id>/continuing-care-plans", methods=["POST"])
def create_cc_plan(facility_id, episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["ClinicalDirector", "Clinician"])
    facility = facility_in_path(facility_id)
    episode = episode_in_path(facility, episode_id)
    body = json_body()
    allowed = {
        "housing_selection_basis", "housing_window_start", "housing_window_end",
        "alumni_contact_interval_days", "alumni_contacts_required", "authorizing_clinician_id",
        "shelter_class", "wants_recovery_only_house", "expected_treatment_episode_version", "housing_id",
    }
    check_allowed(body, allowed)
    require_fields(body, [
        "housing_selection_basis", "housing_window_start", "housing_window_end",
        "alumni_contact_interval_days", "alumni_contacts_required", "authorizing_clinician_id",
        "shelter_class", "expected_treatment_episode_version",
    ])

    expected = body.get("expected_treatment_episode_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError("ERR_INVALID_REQUEST", "expected_treatment_episode_version must be an integer.")
    if expected != episode.get("version"):
        raise ApiError("ERR_STALE_VERSION")

    basis = as_enum(body, "housing_selection_basis", HOUSING_BASES)
    window_start = parse_iso(body.get("housing_window_start"), "housing_window_start")
    window_end = parse_iso(body.get("housing_window_end"), "housing_window_end")
    interval = as_int(body, "alumni_contact_interval_days")
    required = as_int(body, "alumni_contacts_required")
    author_id = as_string(body, "authorizing_clinician_id")
    resolve_clinician(author_id)
    shelter_class = as_enum(body, "shelter_class", SHELTER_CLASSES)
    wants_only = opt_bool(body, "wants_recovery_only_house")
    if wants_only is None:
        wants_only = True
    housing_id = opt_string(body, "housing_id")

    if interval < 1 or interval > 90 or required < 1 or required > 24:
        raise ApiError("ERR_ALUMNI_INTERVAL_INVALID")
    if window_end <= window_start:
        raise ApiError("ERR_HOUSING_WINDOW_INVALID")

    if housing_id:
        house = STORE.get("RecoveryHousing", housing_id)
        if house is None or house.get("facility_id") != facility["id"]:
            raise ApiError("ERR_HOUSING_NOT_FOUND")
        for other in STORE.where("ContinuingCarePlan", lambda r: r.get("housing_id") == housing_id and r.get("status") == "ACTIVE"):
            ostart = parse_iso(other.get("housing_window_start"), "housing_window_start")
            oend = parse_iso(other.get("housing_window_end"), "housing_window_end")
            # PRD §2.9: a `grab_barrier_hours` of 0 means "no barrier and open-ended
            # occupancy windows", so a zero-barrier house's placement runs from its
            # start for ever and any later window on the same row sits inside it.
            if int(house.get("grab_barrier_hours") or 0) == 0:
                oend = None
            if window_start < oend if oend is not None else True:
                if oend is None or ostart < window_end:
                    raise ApiError("ERR_HOUSING_WINDOW_OVERLAP")

    now = STORE.now()
    for prior in STORE.where(
        "ContinuingCarePlan",
        lambda r: r.get("_episode_id") == episode["id"] and r.get("status") == "ACTIVE",
    ):
        prior["status"] = "SUPERSEDED"
        prior["version"] = prior.get("version", 1) + 1
        prior["updated_at"] = iso(now)

    row = base_fields("ContinuingCarePlan")
    row.update({
        "episode_id": episode["id"],
        "_episode_id": episode["id"],
        "facility_id": facility["id"],
        "_facility_id": facility["id"],
        "housing_selection_basis": basis,
        "housing_id": housing_id if basis == "EXPLICIT" else None,
        "housing_window_start": iso(window_start),
        "housing_window_end": iso(window_end),
        "shelter_class": shelter_class,
        "wants_recovery_only_house": wants_only,
        "alumni_contact_interval_days": interval,
        "alumni_contacts_required": required,
        "authorizing_clinician_id": author_id,
        "status": "DRAFT",
        "_created_seq": STORE.next_episode_seq(episode["id"]),
    })
    if basis == "EXPLICIT" and not housing_id:
        raise ApiError("ERR_INVALID_REFERENCE", "EXPLICIT housing selection requires housing_id.")
    STORE.put("ContinuingCarePlan", row)

    episode["version"] = episode.get("version", 1) + 1
    episode["updated_at"] = iso(now)
    return object_response(public(row), 201)


@bp.route("/facilities/<facility_id>/continuing-care-plans", methods=["GET"])
def list_facility_cc_plans(facility_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    facility = facility_in_path(facility_id)
    limit, offset = page_params(request.args)
    rows = _ordered(STORE.where("ContinuingCarePlan", lambda r: r.get("_facility_id") == facility["id"]))
    status = filter_param(request.args, "status")
    episode_id = filter_param(request.args, "episode_id")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    if episode_id:
        rows = [r for r in rows if r.get("episode_id") == episode_id]
    page = paginate(rows, limit, offset)
    return array_response([public(r) for r in page["rows"]], page)


@bp.route("/facilities/<facility_id>/treatment-episodes/<episode_id>/continuing-care-plans", methods=["GET"])
def list_episode_cc_plans(facility_id, episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    facility = facility_in_path(facility_id)
    episode = episode_in_path(facility, episode_id)
    limit, offset = page_params(request.args)
    rows = _ordered(STORE.where("ContinuingCarePlan", lambda r: r.get("_episode_id") == episode["id"]))
    status = filter_param(request.args, "status")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    page = paginate(rows, limit, offset)
    return array_response([public(r) for r in page["rows"]], page)


@bp.route("/facilities/<facility_id>/continuing-care-plans/<cc_plan_id>/activate", methods=["POST"])
def activate_cc_plan(facility_id, cc_plan_id):
    user_id, role = caller()
    require_roles(user_id, role, ["ClinicalDirector", "Clinician"])
    facility = facility_in_path(facility_id)
    row = _cc_plan_in_path(facility, cc_plan_id)
    episode = STORE.get("TreatmentEpisode", row["_episode_id"])
    now = STORE.now()

    if row.get("housing_selection_basis") == "RANKED_AUTO":
        active_by_house = {}
        for other in STORE.where("ContinuingCarePlan", lambda r: r.get("status") == "ACTIVE"):
            active_by_house[other.get("housing_id")] = active_by_house.get(other.get("housing_id"), 0) + 1
        pool = calc.ranked_housing_pool(facility, row, active_by_house)
        if not pool:
            raise ApiError("ERR_HOUSING_POOL_EXHAUSTED")
        row["housing_id"] = pool[0]["id"]

    if row.get("housing_id"):
        window_start = parse_iso(row["housing_window_start"], "housing_window_start")
        window_end = parse_iso(row["housing_window_end"], "housing_window_end")
        for other in STORE.where(
            "ContinuingCarePlan",
            lambda r: r.get("housing_id") == row["housing_id"] and r.get("status") == "ACTIVE" and r["id"] != row["id"],
        ):
            ostart = parse_iso(other.get("housing_window_start"), "housing_window_start")
            oend = parse_iso(other.get("housing_window_end"), "housing_window_end")
            if window_start < oend and ostart < window_end:
                raise ApiError("ERR_HOUSING_WINDOW_OVERLAP")

    capacity = calc.open_housing_capacity(facility)
    active_count = len([r for r in STORE.where("ContinuingCarePlan", lambda r: r.get("_facility_id") == facility["id"] and r.get("status") == "ACTIVE")])
    if active_count + 1 > capacity:
        raise ApiError("ERR_CONTINUING_CARE_HOUSING_FULL")

    for other in STORE.where(
        "ContinuingCarePlan",
        lambda r: r.get("_episode_id") == row["_episode_id"] and r.get("status") == "ACTIVE" and r["id"] != row["id"],
    ):
        other["status"] = "SUPERSEDED"
        other["version"] = other.get("version", 1) + 1
        other["updated_at"] = iso(now)

    row["status"] = "ACTIVE"
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = iso(now)
    return object_response(public(row))


# ---------------------------------------------------------------------------
# Alumni contacts
# ---------------------------------------------------------------------------

@bp.route("/facilities/<facility_id>/treatment-episodes/<episode_id>/alumni-contacts", methods=["POST"])
def create_contact(facility_id, episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["AlumniCoordinator"])
    facility = facility_in_path(facility_id)
    episode = episode_in_path(facility, episode_id)
    body = json_body()
    check_allowed(body, {"scheduled_for", "attempt_number"})
    require_fields(body, ["scheduled_for", "attempt_number"])

    now = STORE.now()
    row = base_fields("AlumniContact")
    row.update({
        "episode_id": episode["id"],
        "_episode_id": episode["id"],
        "facility_id": facility["id"],
        "_facility_id": facility["id"],
        "scheduled_for": iso(parse_iso(body.get("scheduled_for"), "scheduled_for")),
        "attempt_number": as_int(body, "attempt_number"),
        "outcome": "PENDING",
        "abstinent_at_contact": None,
        "record_filed_at": None,
        "recorded_by_user_id": None,
    })
    STORE.put("AlumniContact", row)
    return object_response(public(row), 201)


@bp.route("/facilities/<facility_id>/treatment-episodes/<episode_id>/alumni-contacts", methods=["GET"])
def list_episode_contacts(facility_id, episode_id):
    user_id, role = caller()
    require_roles(user_id, role, ["Any"])
    facility = facility_in_path(facility_id)
    episode = episode_in_path(facility, episode_id)
    limit, offset = page_params(request.args)
    rows = _ordered(STORE.where("AlumniContact", lambda r: r.get("_episode_id") == episode["id"]))
    outcome = filter_param(request.args, "outcome")
    if outcome:
        rows = [r for r in rows if r.get("outcome") == outcome]
    page = paginate(rows, limit, offset)
    return array_response([public(r) for r in page["rows"]], page)


@bp.route("/facilities/<facility_id>/alumni-contacts/<contact_id>/record", methods=["POST"])
def record_contact(facility_id, contact_id):
    user_id, role = caller()
    require_roles(user_id, role, ["AlumniCoordinator"])
    facility = facility_in_path(facility_id)
    row = STORE.get("AlumniContact", contact_id)
    if row is None or row.get("facility_id") != facility["id"]:
        raise ApiError("ERR_CONTACT_NOT_FOUND")
    body = json_body()
    check_allowed(body, {"outcome", "abstinent_at_contact"})
    require_fields(body, ["outcome"])
    outcome = as_enum(body, "outcome", CONTACT_OUTCOMES)

    if row.get("outcome") != "PENDING":
        raise ApiError("ERR_CONTACT_NOT_PENDING")

    now = STORE.now()
    row["outcome"] = outcome
    if outcome == "REACHED" and "abstinent_at_contact" in body:
        row["abstinent_at_contact"] = as_bool(body, "abstinent_at_contact")
    row["record_filed_at"] = iso(now)
    row["recorded_by_user_id"] = user_id
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = iso(now)
    return object_response(public(row))