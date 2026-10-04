"""Advisor routes: registration, lifecycle, training enrollment, branch assignment,
retirement, termination (§3.1, §3.3, §3.7)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import auth_context, require_role
from helpers import (
    body_json, require_fields, require_string, parse_dt, get_or_404,
    stamp_new, touch, paginate, sort_by_created_at, recompute_staffing,
    branch_active_administrator, release_territory, active_transfer_for_branch,
)
from response import success_object, success_list

bp = Blueprint("advisors", __name__)

PREFIX = "/branch-office/advisors"


@bp.route(PREFIX, methods=["POST"])
def create_advisor():
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    body = body_json()
    require_fields(body, ["full_name", "email", "hire_date"])
    full_name = require_string(body, "full_name")
    email = require_string(body, "email")
    hire = parse_dt(body["hire_date"], "hire_date")
    for a in db.advisors.values():
        if a.get("email") == email:
            raise err("ERR_DUPLICATE", "An advisor with this email already exists.")
    advisor = stamp_new({
        "full_name": full_name,
        "email": email,
        "status": "CANDIDATE",
        "hire_date": db.iso_format(hire),
        "branch_id": None,
        "predecessor_advisor_id": None,
        "cumulative_commissions_cents": 0,
    })
    db.advisors[advisor["id"]] = advisor
    return success_object(advisor, 201)


@bp.route(PREFIX, methods=["GET"])
def list_advisors():
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin", "CompliancePrincipal"})
    items = list(db.advisors.values())
    status = request.args.get("status")
    if status:
        items = [a for a in items if a.get("status") == status]
    branch_id = request.args.get("branch_id")
    if branch_id:
        items = [a for a in items if a.get("branch_id") == branch_id]
    pred = request.args.get("predecessor_advisor_id")
    if pred:
        items = [a for a in items if a.get("predecessor_advisor_id") == pred]
    items = sort_by_created_at(items)
    page, limit, offset, total, has_more = paginate(items)
    return success_list(page, limit, offset, total, has_more)


@bp.route(f"{PREFIX}/<aid>", methods=["GET"])
def get_advisor(aid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin", "Advisor", "CompliancePrincipal"})
    advisor = get_or_404(db.advisors, aid, "Advisor")
    return success_object(advisor)


@bp.route(f"{PREFIX}/<aid>/goodwill-transfers", methods=["GET"])
def advisor_goodwill_transfers(aid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin", "Advisor"})
    get_or_404(db.advisors, aid, "Advisor")
    items = [t for t in db.goodwill_transfers.values() if t.get("retiring_advisor_id") == aid]
    items = sort_by_created_at(items)
    page, limit, offset, total, has_more = paginate(items)
    return success_list(page, limit, offset, total, has_more)


@bp.route(f"{PREFIX}/<aid>/solicitation-requests", methods=["GET"])
def advisor_solicitations(aid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin", "Advisor", "CompliancePrincipal"})
    get_or_404(db.advisors, aid, "Advisor")
    items = [s for s in db.solicitation_requests.values() if s.get("advisor_id") == aid]
    items = sort_by_created_at(items)
    page, limit, offset, total, has_more = paginate(items)
    return success_list(page, limit, offset, total, has_more)


@bp.route(f"{PREFIX}/<aid>/production-records", methods=["GET"])
def advisor_production(aid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin", "Advisor"})
    get_or_404(db.advisors, aid, "Advisor")
    items = [r for r in db.production_records.values() if r.get("advisor_id") == aid]
    items = sort_by_created_at(items)
    page, limit, offset, total, has_more = paginate(items)
    return success_list(page, limit, offset, total, has_more)


@bp.route(f"{PREFIX}/<aid>/enroll-training", methods=["POST"])
def enroll_training(aid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    advisor = get_or_404(db.advisors, aid, "Advisor")
    body = body_json()
    # existence before state? Path id resolved. Now state check.
    if advisor.get("status") != "CANDIDATE":
        raise err("ERR_INVALID_STATE", "Advisor is not a CANDIDATE.")
    require_fields(body, ["goal_cents", "start_date"])
    goal = body["goal_cents"]
    if isinstance(goal, bool) or not isinstance(goal, int) or goal <= 0:
        raise err("ERR_INVALID_REQUEST", "goal_cents must be a positive integer.")
    start = parse_dt(body["start_date"], "start_date")
    # one non-terminal program per advisor
    for p in db.training_programs.values():
        if p.get("advisor_id") == aid and p.get("status") in ("ACTIVE", "MILESTONE_PENDING", "REMEDIATION"):
            raise err("ERR_INVALID_STATE", "Advisor already has a non-terminal training program.")
    program = stamp_new({
        "advisor_id": aid,
        "goal_cents": goal,
        "start_date": db.iso_format(start),
        "status": "ACTIVE",
    })
    db.training_programs[program["id"]] = program
    advisor["status"] = "TRAINEE"
    touch(advisor)
    return success_object(program, 201)


@bp.route(f"{PREFIX}/<aid>/assign-branch", methods=["POST"])
def assign_branch(aid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    advisor = get_or_404(db.advisors, aid, "Advisor")
    body = body_json()
    require_fields(body, ["branch_id"])
    branch = get_or_404(db.branches, body["branch_id"], "Branch")
    # state checks (priority 4): transition defined only from VALIDATED
    if advisor.get("status") != "VALIDATED":
        raise err("ERR_ADVISOR_NOT_VALIDATED", "Advisor must be VALIDATED to be assigned to a branch.")
    if branch.get("operating_status") not in ("SITE_APPROVED", "OPEN"):
        raise err("ERR_INVALID_STATE", "Branch must be SITE_APPROVED or OPEN.")
    # business constraint: single-advisor invariant (priority 7)
    for a in db.advisors.values():
        if (a["id"] != aid and a.get("branch_id") == branch["id"]
                and a.get("status") not in ("RETIRED", "TERMINATED")):
            raise err("ERR_BRANCH_OCCUPIED", "Branch already has an assigned advisor.")
    # territory must be OPEN or assigned to this advisor
    territory = db.territories.get(branch.get("territory_id"))
    if territory is not None:
        if territory.get("status") == "RETIRED":
            raise err("ERR_INVALID_STATE", "Branch territory is RETIRED.")
        if territory.get("status") == "ASSIGNED" and territory.get("assigned_advisor_id") != aid:
            raise err("ERR_TERRITORY_OVERLAP", "Territory is assigned to another advisor.")
        # take territory under this advisor's rights
        territory["assigned_advisor_id"] = aid
        territory["assignment_start"] = db.now_iso()
        territory["assignment_end"] = None
        territory["status"] = "ASSIGNED"
        touch(territory)
    advisor["branch_id"] = branch["id"]
    advisor["status"] = "PRACTICING"
    touch(advisor)
    recompute_staffing(branch)
    touch(branch)
    return success_object(advisor)


@bp.route(f"{PREFIX}/<aid>/declare-retirement", methods=["POST"])
def declare_retirement(aid):
    user_id, role = auth_context()
    require_role(role, {"Advisor"})
    advisor = get_or_404(db.advisors, aid, "Advisor")
    if user_id != aid:
        raise err("ERR_UNAUTHORIZED", "Advisors may only declare their own retirement.")
    if advisor.get("status") != "PRACTICING":
        raise err("ERR_INVALID_STATE", "Advisor is not PRACTICING.")
    advisor["status"] = "RETIRING"
    touch(advisor)
    branch = db.branches.get(advisor.get("branch_id"))
    if branch is not None:
        branch["staffing_status"] = "SUCCESSION_PENDING"
        touch(branch)
    return success_object(advisor)


@bp.route(f"{PREFIX}/<aid>/rescind-retirement", methods=["POST"])
def rescind_retirement(aid):
    user_id, role = auth_context()
    require_role(role, {"Advisor"})
    advisor = get_or_404(db.advisors, aid, "Advisor")
    if user_id != aid:
        raise err("ERR_UNAUTHORIZED", "Advisors may only rescind their own retirement.")
    if advisor.get("status") != "RETIRING":
        raise err("ERR_INVALID_STATE", "Advisor is not RETIRING.")
    branch = db.branches.get(advisor.get("branch_id"))
    if branch is not None:
        for t in db.goodwill_transfers.values():
            if (t.get("branch_id") == branch["id"]
                    and t.get("status") in ("ACCEPTED", "COMPLETED")):
                raise err("ERR_TRANSFER_ACTIVE", "A goodwill transfer on the branch is ACCEPTED or COMPLETED.")
    advisor["status"] = "PRACTICING"
    touch(advisor)
    if branch is not None:
        recompute_staffing(branch)
        touch(branch)
    return success_object(advisor)


@bp.route(f"{PREFIX}/<aid>/terminate", methods=["POST"])
def terminate_advisor(aid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    advisor = get_or_404(db.advisors, aid, "Advisor")
    if advisor.get("status") not in ("PRACTICING", "RETIRING"):
        raise err("ERR_INVALID_STATE", "Advisor is not PRACTICING or RETIRING.")
    branch = db.branches.get(advisor.get("branch_id"))
    if branch is not None and advisor.get("status") == "RETIRING":
        # no transfer in ACCEPTED; OFFERED/NEGOTIATING auto-cancelled with escrow refunded
        for t in db.goodwill_transfers.values():
            if t.get("branch_id") == branch["id"]:
                if t.get("status") == "ACCEPTED":
                    raise err("ERR_TRANSFER_ACTIVE", "A goodwill transfer on the branch is ACCEPTED.")
        for t in db.goodwill_transfers.values():
            if t.get("branch_id") == branch["id"] and t.get("status") in ("OFFERED", "NEGOTIATING"):
                t["status"] = "CANCELLED"
                t["escrow_deposit_cents"] = 0
                touch(t)
    # cascade
    advisor["status"] = "TERMINATED"
    advisor["branch_id"] = None
    touch(advisor)
    if branch is not None:
        branch["staffing_status"] = "UNSTAFFED"
        branch["operating_status"] = "SUSPENDED"
        touch(branch)
        territory = db.territories.get(branch.get("territory_id"))
        if territory is not None and territory.get("assigned_advisor_id") == aid:
            release_territory(territory)
    # withdraw SUBMITTED solicitations
    for s in db.solicitation_requests.values():
        if s.get("advisor_id") == aid and s.get("status") == "SUBMITTED":
            s["status"] = "WITHDRAWN"
            touch(s)
    return success_object(advisor)
