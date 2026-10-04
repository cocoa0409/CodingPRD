"""Education path and project completion endpoints."""

from flask import Blueprint, request

import auth
import calc
import db
import recompute
import serializers
from errors import ApiError
from response import array, ok

bp = Blueprint("education", __name__, url_prefix="/toastmasters")

PATH_CODES = (
    "DYNAMIC_LEADERSHIP",
    "ENGAGING_HUMOR",
    "PERSUASIVE_INFLUENCE",
    "PRESENTATION_MASTERY",
    "TEAM_COLLABORATION",
    "VISIONARY_COMMUNICATION",
)
PROJECT_KINDS = ("SPEECH", "EVALUATION", "LEADERSHIP")


def _get_path(path_id):
    return db.get(db.PATHS, path_id)


def _get_completion(completion_id):
    return db.get(db.COMPLETIONS, completion_id)


def _path_membership(path):
    return db.get(db.MEMBERSHIPS, path["membership_id"])


def _path_club(path):
    return db.get(db.CLUBS, _path_membership(path)["club_id"])


@bp.get("/education-paths")
def list_paths():
    principal = auth.authenticate(request.headers)
    auth.require_role(
        principal, ("WorldHeadquarters", "ClubOfficer", "Member", "DistrictDirector")
    )
    limit, offset = db.parse_pagination(request.args)

    paths = list(db.PATHS.values())
    for query_name in ("membership_id", "level", "status"):
        wanted = request.args.get(query_name)
        if wanted not in (None, ""):
            paths = [p for p in paths if p.get(query_name) == wanted]

    paths.sort(key=lambda p: p["created_at"])
    window, total, _ = db.paginate(paths, limit, offset)
    return array(serializers.render_all("education_path", window), limit=limit,
                 offset=offset, total_count=total)


@bp.get("/education-paths/<path_id>")
def get_path(path_id):
    principal = auth.authenticate(request.headers)
    auth.require_role(
        principal, ("WorldHeadquarters", "ClubOfficer", "Member", "DistrictDirector")
    )
    return ok(serializers.render("education_path", _get_path(path_id)))


@bp.post("/education-paths")
def create_path():
    body = request.get_json(silent=True)
    if body is None:
        body = {}

    membership_id = db.require_str(body, "membership_id")
    path_code = db.require_enum(body, "path_code", PATH_CODES)
    expected_version = db.require_int(body, "expected_membership_version")

    principal = auth.authenticate(request.headers)
    auth.require_role(principal, ("Member",))

    # Priority 4: the referenced membership exists.
    membership = db.get(db.MEMBERSHIPS, membership_id)
    # Priority 2: Member ownership runs through the path's membership.
    auth.require_member_identity(principal, membership["member_id"])

    # Priority 5: optimistic concurrency against the parent membership.
    if expected_version != membership["version"]:
        raise ApiError("ERR_STALE_VERSION")

    # Priority 7: one path per membership and path_code.
    for existing in recompute.paths_of_membership(membership_id):
        if existing["path_code"] == path_code and existing["status"] in ("ACTIVE", "SUSPENDED"):
            raise ApiError("ERR_DUPLICATE_PATH_ENROLLMENT")

    # Priority 18: the membership must be ACTIVE and paid through the cycle.
    club = db.get(db.CLUBS, membership["club_id"])
    recompute.require_membership_paid_active(membership, club)

    now = db.utcnow()
    path = db.create(
        db.PATHS,
        {
            "membership_id": membership_id,
            "path_code": path_code,
            "level": "LEVEL_1",
            "status": "ACTIVE",
            "approved_speeches_at_level": 0,
            "approved_projects_at_level": 0,
            "level_started_at": now,
            "last_advanced_at": None,
        },
    )
    db.touch(membership)
    return ok(serializers.render("education_path", path), status=201)


@bp.post("/education-paths/<path_id>/advance-level")
def advance_level(path_id):
    body = request.get_json(silent=True)
    if body is None:
        body = {}

    expected_version = db.require_int(body, "expected_education_path_version")

    principal = auth.authenticate(request.headers)
    auth.require_role(principal, ("Member",))

    path = _get_path(path_id)
    auth.require_path_owner(principal, path)

    # Priority 5: optimistic concurrency against the path.
    if expected_version != path["version"]:
        raise ApiError("ERR_STALE_VERSION")

    # Priority 11: the path is ACTIVE and the published table is satisfied.
    # PRD section 2.10 does not list level advancement among the operations
    # carrying the priority-6 state check, so a terminal COMPLETED path falls
    # through to this check and fails it (it holds no completions at its level).
    required_speeches, required_projects = calc.level_requirement(path["level"])
    if path["status"] != "ACTIVE":
        raise ApiError("ERR_LEVEL_REQUIREMENTS_NOT_MET")
    if path["approved_speeches_at_level"] < required_speeches:
        raise ApiError("ERR_LEVEL_REQUIREMENTS_NOT_MET")
    if path["approved_projects_at_level"] < required_projects:
        raise ApiError("ERR_LEVEL_REQUIREMENTS_NOT_MET")

    membership = _path_membership(path)
    club = _path_club(path)

    # Priority 17: the club posture must be GOOD.
    recompute.require_club_good_standing(club)
    # Priority 18: the membership must be ACTIVE and paid through the cycle.
    recompute.require_membership_paid_active(membership, club)

    now = db.utcnow()
    target = calc.next_level(path["level"])
    path["level"] = target
    if target == "COMPLETED":
        path["last_advanced_at"] = now
    else:
        path["level_started_at"] = now
        path["last_advanced_at"] = now

    recompute.recompute_path(path)
    recompute.recompute_member(db.get(db.MEMBERS, membership["member_id"]))
    recompute.touch_club(club)
    db.touch(path)
    return ok(serializers.render("education_path", path))


@bp.get("/project-completions")
def list_completions():
    principal = auth.authenticate(request.headers)
    auth.require_role(
        principal, ("WorldHeadquarters", "ClubOfficer", "Member", "DistrictDirector")
    )
    limit, offset = db.parse_pagination(request.args)

    completions = list(db.COMPLETIONS.values())
    for query_name in ("path_id", "member_id", "club_id", "evaluator_member_id", "status"):
        wanted = request.args.get(query_name)
        if wanted not in (None, ""):
            completions = [c for c in completions if c.get(query_name) == wanted]

    completions.sort(key=lambda c: c["created_at"])
    window, total, _ = db.paginate(completions, limit, offset)
    return array(serializers.render_all("project_completion", window), limit=limit,
                 offset=offset, total_count=total)


@bp.get("/project-completions/<completion_id>")
def get_completion(completion_id):
    principal = auth.authenticate(request.headers)
    auth.require_role(
        principal, ("WorldHeadquarters", "ClubOfficer", "Member", "DistrictDirector")
    )
    return ok(serializers.render("project_completion", _get_completion(completion_id)))


@bp.post("/project-completions")
def create_completion():
    body = request.get_json(silent=True)
    if body is None:
        body = {}

    path_id = db.require_str(body, "path_id")
    project_code = db.require_str(body, "project_code")
    project_kind = db.require_enum(body, "project_kind", PROJECT_KINDS)
    level = db.require_int(body, "level")
    if level < 1 or level > 5:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'level' must lie between 1 and 5.")
    speech_minutes = db.require_int(body, "speech_minutes")
    delivered_at = db.parse_dt(db.require(body, "delivered_at"), "delivered_at")
    evaluator_member_id = db.optional(body, "evaluator_member_id")
    expected_version = db.require_int(body, "expected_education_path_version")

    principal = auth.authenticate(request.headers)
    auth.require_role(principal, ("Member",))

    # Priority 4: references resolved left to right, then in body field order.
    path = db.get(db.PATHS, path_id)
    if evaluator_member_id is not None:
        db.get(db.MEMBERS, evaluator_member_id)

    membership = _path_membership(path)
    auth.require_member_identity(principal, membership["member_id"])

    # Priority 5: optimistic concurrency against the parent path.
    if expected_version != path["version"]:
        raise ApiError("ERR_STALE_VERSION")

    # Priority 12: evaluator independence.
    if evaluator_member_id is not None and evaluator_member_id == membership["member_id"]:
        raise ApiError("ERR_EVALUATOR_CONFLICT")

    # Priority 18: the membership must be ACTIVE and paid through the cycle.
    club = db.get(db.CLUBS, membership["club_id"])
    recompute.require_membership_paid_active(membership, club)

    completion = db.create(
        db.COMPLETIONS,
        {
            "path_id": path_id,
            "member_id": membership["member_id"],
            "club_id": membership["club_id"],
            "project_code": project_code,
            "project_kind": project_kind,
            "level": level,
            "speech_minutes": speech_minutes,
            "delivered_at": delivered_at,
            "evaluator_member_id": evaluator_member_id,
            "evaluation_summary": None,
            "status": "LOGGED",
            "return_reason": None,
            "counts_for_level_advancement": False,
        },
    )
    db.touch(path)
    return ok(serializers.render("project_completion", completion), status=201)


@bp.post("/project-completions/<completion_id>/evaluation")
def record_evaluation(completion_id):
    body = request.get_json(silent=True)
    if body is None:
        body = {}

    evaluation_summary = db.require_str(body, "evaluation_summary")

    principal = auth.authenticate(request.headers)
    auth.require_role(principal, ("Member",))

    completion = _get_completion(completion_id)
    # Priority 2: Member ownership runs through the completion's evaluator.
    auth.require_evaluator_owner(principal, completion)

    # Priority 6: an evaluation requires LOGGED or RETURNED.
    if completion["status"] not in ("LOGGED", "RETURNED"):
        raise ApiError("ERR_INVALID_STATE")
    if completion.get("evaluator_member_id") != principal.user_id:
        raise ApiError("ERR_UNAUTHORIZED")

    completion["status"] = "EVALUATED"
    completion["evaluation_summary"] = evaluation_summary
    completion["return_reason"] = None

    path = db.get(db.PATHS, completion["path_id"])
    recompute.recompute_path(path)
    db.touch(completion)
    return ok(serializers.render("project_completion", completion))


@bp.post("/project-completions/<completion_id>/review")
def review_completion(completion_id):
    body = request.get_json(silent=True)
    if body is None:
        body = {}

    decision = db.require_enum(body, "decision", ("APPROVE", "RETURN"))
    return_reason = db.optional(body, "return_reason")
    if return_reason is not None and not isinstance(return_reason, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'return_reason' must be a string.")
    if decision == "RETURN" and (return_reason is None or return_reason.strip() == ""):
        raise ApiError("ERR_INVALID_REQUEST", "A return requires a non-empty return_reason.")

    principal = auth.authenticate(request.headers)
    auth.require_role(principal, ("ClubOfficer",))

    completion = _get_completion(completion_id)
    # Priority 2: the acting officer must belong to the completion's club.
    auth.require_officer_of_club(principal, completion["club_id"])

    # Priority 6: the target must admit the requested transition.
    if decision == "APPROVE":
        if completion["status"] != "EVALUATED":
            raise ApiError("ERR_INVALID_STATE")
    else:
        if completion["status"] not in ("EVALUATED", "APPROVED"):
            raise ApiError("ERR_INVALID_STATE")

    path = db.get(db.PATHS, completion["path_id"])
    membership = db.get(db.MEMBERSHIPS, path["membership_id"])
    club = db.get(db.CLUBS, completion["club_id"])

    if decision == "APPROVE":
        if completion["project_kind"] == "SPEECH" and not completion.get("evaluation_summary"):
            raise ApiError("ERR_LEVEL_REQUIREMENTS_NOT_MET")
        current_level = calc.path_level_number(path["level"])
        after_speeches = path["approved_speeches_at_level"]
        after_projects = path["approved_projects_at_level"]
        if completion["level"] == current_level:
            after_projects += 1
            if completion["project_kind"] == "SPEECH":
                after_speeches += 1
        if (
            after_speeches > calc.MAX_PROJECTS_PER_LEVEL
            or after_projects > calc.MAX_PROJECTS_PER_LEVEL
        ):
            raise ApiError("ERR_LEVEL_REQUIREMENTS_NOT_MET")

        completion["status"] = "APPROVED"
        completion["return_reason"] = None
        completion["counts_for_level_advancement"] = (
            completion["level"] == current_level
        )
        recompute.recompute_path(path)
        recompute.recompute_member(db.get(db.MEMBERS, completion["member_id"]))
        recompute.recompute_membership(membership)
        recompute.touch_club(club)
        db.touch(completion)
        return ok(serializers.render("project_completion", completion))

    # decision RETURN
    was_approved = completion["status"] == "APPROVED"
    completion["status"] = "RETURNED"
    completion["return_reason"] = return_reason
    completion["counts_for_level_advancement"] = False

    if was_approved and completion["level"] == calc.path_level_number(path["level"]):
        # Retroactive return: the supporting level walks back one step.
        previous = calc.previous_level(path["level"])
        if previous is not None:
            path["level"] = previous
            path["level_started_at"] = db.utcnow()
        recompute.disqualify_entries_for_member_club(
            completion["member_id"], completion["club_id"]
        )

    recompute.recompute_path(path)
    recompute.recompute_member(db.get(db.MEMBERS, completion["member_id"]))
    recompute.recompute_membership(membership)
    recompute.touch_club(club)
    db.touch(completion)
    return ok(serializers.render("project_completion", completion))
