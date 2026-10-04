"""Assignment routes: create, list, get, respond, submit-critique."""
from datetime import timedelta

from flask import Blueprint, request

from constants import (
    ASSIGNMENT_ROLES,
    LIVE_ASSIGNMENT_STATUSES,
    MAX_ACTIVE_ASSIGNMENTS_PER_REVIEWER,
    MAX_LIVE_ASSIGNMENTS_PER_APPLICATION,
    MEETING_PROXIMITY_BUFFER_DAYS,
    MIN_LIVE_ASSIGNMENTS,
    RECRUIT_DECISIONS,
    ROLE_REVIEWER,
    ROLE_SRO,
)
from db import STORE, new_entity, touch
from errors import fail
from serializers import assignment_json
from services import (
    active_assignment_count,
    get,
    live_assignment_count,
)
from util import (
    auth_context,
    get_body,
    ok_list,
    ok_object,
    parse_pagination,
    req_enum,
    req_int,
    req_str,
    require_owner,
    require_role,
    sort_and_page,
)

bp = Blueprint("assignments", __name__)

SCORE_FIELDS = (
    "significance_score",
    "innovation_score",
    "approach_score",
    "investigator_score",
    "environment_score",
    "overall_impact_score",
)


def _get_assignment_or_404(assignment_id):
    assignment = get("assignments", assignment_id)
    if assignment is None:
        fail("ERR_ASSIGNMENT_NOT_FOUND", "assignment not found")
    return assignment


@bp.route("/grants/assignments", methods=["POST"])
def create_assignment():
    user_id, role = auth_context()
    require_role(role, (ROLE_SRO,))
    body = get_body()
    application_id = req_str(body, "application_id")
    reviewer_id = req_str(body, "reviewer_id")
    assign_role = req_enum(body, "role", ASSIGNMENT_ROLES)
    app = get("applications", application_id)
    if app is None:
        fail("ERR_APPLICATION_NOT_FOUND", "application not found")
    reviewer = get("reviewers", reviewer_id)
    if reviewer is None:
        fail("ERR_REVIEWER_NOT_FOUND", "reviewer not found")
    # lifecycle state gates (stage 6)
    if reviewer["status"] != "ACTIVE":
        fail("ERR_REVIEWER_NOT_ACTIVE", "assignment requires an ACTIVE reviewer")
    section = (
        get("study_sections", app["study_section_id"])
        if app["study_section_id"]
        else None
    )
    if section is None or section["status"] != "RECRUITING":
        fail(
            "ERR_SECTION_NOT_RECRUITING",
            "assignment requires the application's study section to be RECRUITING",
        )
    # conflict-of-interest screening (stage 9)
    if reviewer["institution_id"] == app["institution_id"]:
        fail(
            "ERR_COI_INSTITUTION_MATCH",
            "reviewer's institution matches the applicant institution",
        )
    if reviewer["id"] in app["excluded_reviewer_ids"]:
        fail("ERR_REVIEWER_EXCLUDED", "reviewer is on the application's exclusion list")
    if app["id"] in reviewer["declared_conflicts"]:
        fail(
            "ERR_REVIEWER_SELF_DECLARED_CONFLICT",
            "reviewer has self-declared a conflict with this application",
        )
    # uniqueness (stage 12)
    live = [
        a
        for a in STORE["assignments"].values()
        if a["application_id"] == app["id"] and a["status"] in LIVE_ASSIGNMENT_STATUSES
    ]
    if any(a["reviewer_id"] == reviewer["id"] for a in live):
        fail(
            "ERR_DUPLICATE_ASSIGNMENT",
            "a live assignment for this (application, reviewer) pair already exists",
        )
    if assign_role == "PRIMARY" and any(a["role"] == "PRIMARY" for a in live):
        fail(
            "ERR_PRIMARY_ALREADY_ASSIGNED",
            "a live PRIMARY assignment already exists for this application",
        )
    if len(live) >= MAX_LIVE_ASSIGNMENTS_PER_APPLICATION:
        fail(
            "ERR_ASSIGNMENT_LIMIT_REACHED",
            "the application already has %d live assignments"
            % MAX_LIVE_ASSIGNMENTS_PER_APPLICATION,
        )
    # reviewer capacity (stage 13; inclusive at the limit)
    if active_assignment_count(reviewer["id"]) >= MAX_ACTIVE_ASSIGNMENTS_PER_REVIEWER:
        fail(
            "ERR_REVIEWER_CAPACITY_EXCEEDED",
            "the reviewer already holds %d active assignments"
            % MAX_ACTIVE_ASSIGNMENTS_PER_REVIEWER,
        )
    # meeting proximity (stage 17): other-section live assignments only
    buffer = timedelta(days=MEETING_PROXIMITY_BUFFER_DAYS)
    for other in STORE["assignments"].values():
        if other["reviewer_id"] != reviewer["id"]:
            continue
        if other["status"] not in LIVE_ASSIGNMENT_STATUSES:
            continue
        other_app = get("applications", other["application_id"])
        if other_app is None or other_app["study_section_id"] is None:
            continue
        if other_app["study_section_id"] == section["id"]:
            continue  # same-section co-review is exempt
        other_section = get("study_sections", other_app["study_section_id"])
        if other_section is None:
            continue
        if abs(other_section["meeting_date"] - section["meeting_date"]) <= buffer:
            fail(
                "ERR_MEETING_PROXIMITY_CONFLICT",
                "reviewer holds a live assignment to a section meeting within "
                "%d days of the target section" % MEETING_PROXIMITY_BUFFER_DAYS,
            )
    assignment = new_entity()
    assignment.update(
        {
            "application_id": app["id"],
            "reviewer_id": reviewer["id"],
            "role": assign_role,
            "significance_score": None,
            "innovation_score": None,
            "approach_score": None,
            "investigator_score": None,
            "environment_score": None,
            "overall_impact_score": None,
            "status": "ASSIGNED",
        }
    )
    STORE["assignments"][assignment["id"]] = assignment
    if app["status"] == "REFERRED":
        app["status"] = "UNDER_REVIEW"
        touch(app)
    return ok_object(assignment_json(assignment), 201)


@bp.route("/grants/assignments", methods=["GET"])
def list_assignments():
    auth_context()
    limit, offset = parse_pagination(request.args)
    items = list(STORE["assignments"].values())
    for field in ("application_id", "reviewer_id", "status"):
        if request.args.get(field) is not None:
            items = [a for a in items if a.get(field) == request.args[field]]
    page, total = sort_and_page(items, limit, offset)
    return ok_list([assignment_json(a) for a in page], total, limit, offset)


@bp.route("/grants/assignments/<assignment_id>", methods=["GET"])
def get_assignment(assignment_id):
    auth_context()
    return ok_object(assignment_json(_get_assignment_or_404(assignment_id)))


@bp.route("/grants/assignments/<assignment_id>/respond", methods=["POST"])
def assignment_respond(assignment_id):
    user_id, role = auth_context()
    require_role(role, (ROLE_REVIEWER,))
    assignment = _get_assignment_or_404(assignment_id)
    require_owner(assignment["reviewer_id"], user_id)
    body = get_body()
    decision = req_enum(body, "decision", RECRUIT_DECISIONS)
    valid = (
        decision == "ACCEPT"
        and assignment["status"] == "ASSIGNED"
        or decision == "DECLINE"
        and assignment["status"] in ("ASSIGNED", "ACCEPTED")
    )
    if not valid:
        fail(
            "ERR_ASSIGNMENT_INVALID_STATE",
            "ACCEPT requires ASSIGNED; DECLINE requires ASSIGNED or ACCEPTED",
        )
    if decision == "ACCEPT":
        assignment["status"] = "ACCEPTED"
        touch(assignment)
        return ok_object(assignment_json(assignment))
    # DECLINE: quorum cascade
    assignment["status"] = "DECLINED"
    touch(assignment)
    app = get("applications", assignment["application_id"])
    if (
        app is not None
        and app["status"] == "UNDER_REVIEW"
        and live_assignment_count(app["id"]) < MIN_LIVE_ASSIGNMENTS
    ):
        app["status"] = "REFERRED"
        touch(app)
    return ok_object(assignment_json(assignment))


@bp.route("/grants/assignments/<assignment_id>/submit-critique", methods=["POST"])
def submit_critique(assignment_id):
    user_id, role = auth_context()
    require_role(role, (ROLE_REVIEWER,))
    assignment = _get_assignment_or_404(assignment_id)
    require_owner(assignment["reviewer_id"], user_id)
    body = get_body()
    if assignment["status"] != "ACCEPTED":
        fail("ERR_ASSIGNMENT_INVALID_STATE", "submit-critique requires ACCEPTED status")
    app = get("applications", assignment["application_id"])
    section = (
        get("study_sections", app["study_section_id"])
        if app is not None and app["study_section_id"]
        else None
    )
    if section is None or section["status"] != "MEETING_HELD":
        fail(
            "ERR_SECTION_NOT_IN_MEETING",
            "critique submission requires the application's section to be MEETING_HELD",
        )
    scores = {}
    for field in SCORE_FIELDS:
        scores[field] = req_int(body, field, minimum=1, maximum=9)
    for field, value in scores.items():
        assignment[field] = value
    assignment["status"] = "CRITIQUE_SUBMITTED"
    touch(assignment)
    return ok_object(assignment_json(assignment))
