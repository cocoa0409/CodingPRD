"""JobProfile CRUD + FLSA determination + review lifecycle (§3.2)."""
from flask import Blueprint, request
from db import store, new_id
from middleware import require_roles, get_auth
from response import success_object, success_list
from errors import (
    not_found, invalid_request, invalid_enum, invalid_state_transition,
    already_terminal, flsa_tests_incomplete, profile_in_use, referenced_entity_state,
)
from services.common import (
    now_iso, require_fields, parse_int, parse_pagination, sort_by_created_at,
    paginate, bump, FLSA_WEEKLY_MINIMUM_CENTS,
)
from services import clock

bp = Blueprint("profiles", __name__)

PROFILE_STATES = ["DRAFT", "IN_REVIEW", "APPROVED", "RETIRED"]
FLSA_CLASSES = ["PENDING", "EXEMPT", "NON_EXEMPT"]


def profile_view(p):
    return {k: p[k] for k in ("id", "job_family_id", "job_level_id", "title", "summary",
                              "salary_basis_weekly_cents", "duties_test_passed",
                              "flsa_classification", "flsa_determined_at", "status",
                              "created_at", "updated_at", "version")}


def get_profile_or_404(pid):
    p = store.job_profiles.get(pid)
    if p is None:
        raise not_found("job profile not found")
    return p


@bp.route("/comp/job-profiles", methods=["POST"])
def create_profile():
    require_roles("CompAnalyst")
    body = request.get_json(silent=True) or {}
    require_fields(body, ["job_family_id", "job_level_id", "title", "summary",
                          "salary_basis_weekly_cents", "duties_test_passed"])
    fam_id = body["job_family_id"]
    lvl_id = body["job_level_id"]
    if fam_id not in store.job_families:
        raise not_found("job family not found")
    if lvl_id not in store.job_levels:
        raise not_found("job level not found")
    if store.job_families[fam_id]["status"] == "RETIRED":
        raise referenced_entity_state("job family is RETIRED")
    title = body["title"]
    if not isinstance(title, str) or not title:
        raise invalid_request("title must be a non-empty string")
    summary = body["summary"]
    if not isinstance(summary, str):
        raise invalid_request("summary must be a string")
    weekly = parse_int(body["salary_basis_weekly_cents"], "salary_basis_weekly_cents", minimum=0)
    duties = body["duties_test_passed"]
    if not isinstance(duties, bool):
        raise invalid_request("duties_test_passed must be a boolean")
    now = now_iso()
    p = {"id": new_id(), "job_family_id": fam_id, "job_level_id": lvl_id,
         "title": title, "summary": summary,
         "salary_basis_weekly_cents": weekly, "duties_test_passed": duties,
         "flsa_classification": "PENDING", "flsa_determined_at": None,
         "status": "DRAFT",
         "created_at": now, "updated_at": now, "version": 1}
    store.job_profiles[p["id"]] = p
    return success_object(profile_view(p), 201)


@bp.route("/comp/job-profiles", methods=["GET"])
def list_profiles():
    get_auth()
    limit, offset = parse_pagination(request.args)
    rows = list(store.job_profiles.values())
    for arg in ("job_family_id", "job_level_id"):
        v = request.args.get(arg)
        if v is not None:
            rows = [p for p in rows if p[arg] == v]
    status_filter = request.args.get("status")
    if status_filter is not None:
        if status_filter not in PROFILE_STATES:
            raise invalid_enum("status is not a declared member")
        rows = [p for p in rows if p["status"] == status_filter]
    rows = sort_by_created_at(rows)
    page, total = paginate(rows, limit, offset)
    return success_list([profile_view(p) for p in page], limit, offset, total)


@bp.route("/comp/job-profiles/<pid>", methods=["GET"])
def get_profile(pid):
    get_auth()
    return success_object(profile_view(get_profile_or_404(pid)))


@bp.route("/comp/job-profiles/<pid>/determine-flsa", methods=["POST"])
def determine_flsa(pid):
    require_roles("CompAnalyst")
    p = get_profile_or_404(pid)
    if p["status"] == "RETIRED":
        raise already_terminal("profile is RETIRED")
    if p["status"] not in ("DRAFT", "IN_REVIEW"):
        raise invalid_state_transition("determine-flsa declared only for DRAFT or IN_REVIEW")
    if (p["salary_basis_weekly_cents"] >= FLSA_WEEKLY_MINIMUM_CENTS
            and p["duties_test_passed"] is True):
        p["flsa_classification"] = "EXEMPT"
    else:
        p["flsa_classification"] = "NON_EXEMPT"
    p["flsa_determined_at"] = clock.now_iso()
    bump(p)
    return success_object(profile_view(p))


@bp.route("/comp/job-profiles/<pid>/submit", methods=["POST"])
def submit_profile(pid):
    require_roles("CompAnalyst")
    p = get_profile_or_404(pid)
    if p["status"] == "RETIRED":
        raise already_terminal("profile is RETIRED")
    if p["status"] != "DRAFT":
        raise invalid_state_transition("submit declared only from DRAFT")
    if p["flsa_classification"] == "PENDING":
        raise flsa_tests_incomplete()
    p["status"] = "IN_REVIEW"
    bump(p)
    return success_object(profile_view(p))


@bp.route("/comp/job-profiles/<pid>/approve", methods=["POST"])
def approve_profile(pid):
    require_roles("CompManager")
    p = get_profile_or_404(pid)
    if p["status"] == "RETIRED":
        raise already_terminal("profile is RETIRED")
    if p["status"] != "IN_REVIEW":
        raise invalid_state_transition("approve declared only from IN_REVIEW")
    if p["flsa_classification"] not in ("EXEMPT", "NON_EXEMPT"):
        raise flsa_tests_incomplete()
    p["status"] = "APPROVED"
    bump(p)
    return success_object(profile_view(p))


@bp.route("/comp/job-profiles/<pid>/return", methods=["POST"])
def return_profile(pid):
    require_roles("CompManager")
    p = get_profile_or_404(pid)
    if p["status"] == "RETIRED":
        raise already_terminal("profile is RETIRED")
    if p["status"] != "IN_REVIEW":
        raise invalid_state_transition("return declared only from IN_REVIEW")
    p["status"] = "DRAFT"
    bump(p)
    return success_object(profile_view(p))


@bp.route("/comp/job-profiles/<pid>/revise", methods=["POST"])
def revise_profile(pid):
    require_roles("CompAnalyst")
    p = get_profile_or_404(pid)
    if p["status"] == "RETIRED":
        raise already_terminal("profile is RETIRED")
    if p["status"] != "APPROVED":
        raise invalid_state_transition("revise declared only from APPROVED")
    p["status"] = "IN_REVIEW"
    p["flsa_classification"] = "PENDING"
    p["flsa_determined_at"] = None
    bump(p)
    return success_object(profile_view(p))


@bp.route("/comp/job-profiles/<pid>/retire", methods=["POST"])
def retire_profile(pid):
    require_roles("CompManager")
    p = get_profile_or_404(pid)
    if p["status"] == "RETIRED":
        raise already_terminal("profile is RETIRED")
    if p["status"] != "APPROVED":
        raise invalid_state_transition("retire declared only from APPROVED")
    for e in store.employees.values():
        if e["job_profile_id"] == pid and e["status"] == "ACTIVE":
            raise profile_in_use()
    p["status"] = "RETIRED"
    bump(p)
    return success_object(profile_view(p))
