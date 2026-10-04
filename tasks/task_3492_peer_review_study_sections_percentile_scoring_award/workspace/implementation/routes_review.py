"""StudySection and Reviewer routes."""
from flask import Blueprint, request

from constants import RECRUIT_DECISIONS, ROLE_REVIEWER, ROLE_SRO
from db import STORE, new_entity, touch
from errors import fail
from serializers import reviewer_json, section_json
from services import get, release_section_scores
from util import (
    auth_context,
    get_body,
    ok_list,
    ok_object,
    parse_pagination,
    req_dt,
    req_enum,
    req_int,
    req_list,
    req_str,
    require_owner,
    require_role,
    sort_and_page,
)

bp = Blueprint("review", __name__)


def _get_section_or_404(section_id):
    section = get("study_sections", section_id)
    if section is None:
        fail("ERR_STUDY_SECTION_NOT_FOUND", "study section not found")
    return section


def _get_reviewer_or_404(reviewer_id):
    reviewer = get("reviewers", reviewer_id)
    if reviewer is None:
        fail("ERR_REVIEWER_NOT_FOUND", "reviewer not found")
    return reviewer


# ---------------------------------------------------------------------------
# StudySection
# ---------------------------------------------------------------------------
@bp.route("/grants/study-sections", methods=["POST"])
def create_section():
    user_id, role = auth_context()
    require_role(role, (ROLE_SRO,))
    body = get_body()
    name = req_str(body, "name")
    meeting_date = req_dt(body, "meeting_date")
    quota = req_int(body, "application_quota", minimum=1)
    section = new_entity()
    section.update(
        {
            "name": name,
            "meeting_date": meeting_date,
            "application_quota": quota,
            "status": "RECRUITING",
        }
    )
    STORE["study_sections"][section["id"]] = section
    return ok_object(section_json(section), 201)


@bp.route("/grants/study-sections/<section_id>", methods=["GET"])
def get_section(section_id):
    auth_context()
    return ok_object(section_json(_get_section_or_404(section_id)))


@bp.route("/grants/study-sections/<section_id>/convene", methods=["POST"])
def convene_section(section_id):
    user_id, role = auth_context()
    require_role(role, (ROLE_SRO,))
    section = _get_section_or_404(section_id)
    if section["status"] != "RECRUITING":
        fail("ERR_SECTION_NOT_CONVENABLE", "convene requires RECRUITING status")
    has_under_review = any(
        a["study_section_id"] == section["id"] and a["status"] == "UNDER_REVIEW"
        for a in STORE["applications"].values()
    )
    if not has_under_review:
        fail(
            "ERR_SECTION_NOT_CONVENABLE",
            "convene requires at least one UNDER_REVIEW application assigned",
        )
    section["status"] = "MEETING_HELD"
    touch(section)
    return ok_object(section_json(section))


@bp.route("/grants/study-sections/<section_id>/release-scores", methods=["POST"])
def release_scores(section_id):
    user_id, role = auth_context()
    require_role(role, (ROLE_SRO,))
    section = _get_section_or_404(section_id)
    if section["status"] != "MEETING_HELD":
        fail("ERR_SECTION_NOT_RELEASABLE", "release-scores requires MEETING_HELD")
    release_section_scores(section)
    return ok_object(section_json(section))


# ---------------------------------------------------------------------------
# Reviewer
# ---------------------------------------------------------------------------
@bp.route("/grants/reviewers", methods=["POST"])
def create_reviewer():
    user_id, role = auth_context()
    require_role(role, (ROLE_SRO,))
    body = get_body()
    full_name = req_str(body, "full_name")
    institution_id = req_str(body, "institution_id")
    keywords = req_list(body, "expertise_keywords", elem=str)
    if get("institutions", institution_id) is None:
        fail("ERR_INSTITUTION_NOT_FOUND", "institution not found")
    reviewer = new_entity()
    reviewer.update(
        {
            "full_name": full_name,
            "institution_id": institution_id,
            "expertise_keywords": list(keywords),
            "declared_conflicts": [],
            "status": "INVITED",
        }
    )
    STORE["reviewers"][reviewer["id"]] = reviewer
    return ok_object(reviewer_json(reviewer), 201)


@bp.route("/grants/reviewers", methods=["GET"])
def list_reviewers():
    auth_context()
    limit, offset = parse_pagination(request.args)
    items = list(STORE["reviewers"].values())
    if request.args.get("institution_id") is not None:
        items = [r for r in items if r["institution_id"] == request.args["institution_id"]]
    if request.args.get("status") is not None:
        items = [r for r in items if r["status"] == request.args["status"]]
    page, total = sort_and_page(items, limit, offset)
    return ok_list([reviewer_json(r) for r in page], total, limit, offset)


@bp.route("/grants/reviewers/<reviewer_id>", methods=["GET"])
def get_reviewer(reviewer_id):
    auth_context()
    return ok_object(reviewer_json(_get_reviewer_or_404(reviewer_id)))


@bp.route("/grants/reviewers/<reviewer_id>/respond", methods=["POST"])
def reviewer_respond(reviewer_id):
    user_id, role = auth_context()
    require_role(role, (ROLE_REVIEWER,))
    reviewer = _get_reviewer_or_404(reviewer_id)
    require_owner(reviewer["id"], user_id)
    body = get_body()
    decision = req_enum(body, "decision", RECRUIT_DECISIONS)
    if reviewer["status"] != "INVITED":
        fail("ERR_REVIEWER_INVALID_STATE", "respond requires INVITED status")
    reviewer["status"] = "ACTIVE" if decision == "ACCEPT" else "DECLINED"
    touch(reviewer)
    return ok_object(reviewer_json(reviewer))


@bp.route("/grants/reviewers/<reviewer_id>/declare-conflict", methods=["POST"])
def reviewer_declare_conflict(reviewer_id):
    user_id, role = auth_context()
    require_role(role, (ROLE_REVIEWER,))
    reviewer = _get_reviewer_or_404(reviewer_id)
    require_owner(reviewer["id"], user_id)
    body = get_body()
    application_id = req_str(body, "application_id")
    if get("applications", application_id) is None:
        fail("ERR_APPLICATION_NOT_FOUND", "application not found")
    if application_id not in reviewer["declared_conflicts"]:
        reviewer["declared_conflicts"].append(application_id)
        touch(reviewer)
    return ok_object(reviewer_json(reviewer))
