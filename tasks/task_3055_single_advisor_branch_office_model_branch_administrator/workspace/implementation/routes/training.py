"""Training program and milestone evaluation routes (§3.1)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import auth_context, require_role
from helpers import (
    body_json, require_fields, parse_dt, get_or_404, stamp_new, touch,
    paginate, sort_by_created_at,
)
from response import success_object, success_list

bp = Blueprint("training", __name__)
PREFIX = "/branch-office/training-programs"


@bp.route(PREFIX, methods=["GET"])
def list_programs():
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    items = list(db.training_programs.values())
    advisor_id = request.args.get("advisor_id")
    if advisor_id:
        items = [p for p in items if p.get("advisor_id") == advisor_id]
    items = sort_by_created_at(items)
    page, limit, offset, total, has_more = paginate(items)
    return success_list(page, limit, offset, total, has_more)


@bp.route(f"{PREFIX}/<pid>", methods=["GET"])
def get_program(pid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin", "Advisor"})
    return success_object(get_or_404(db.training_programs, pid, "TrainingProgram"))


@bp.route(f"{PREFIX}/<pid>/evaluations", methods=["GET"])
def list_evaluations(pid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin", "Advisor"})
    get_or_404(db.training_programs, pid, "TrainingProgram")
    items = [e for e in db.milestone_evaluations.values() if e.get("training_program_id") == pid]
    items = sort_by_created_at(items)
    page, limit, offset, total, has_more = paginate(items)
    return success_list(page, limit, offset, total, has_more)


@bp.route(f"{PREFIX}/<pid>/submit-milestone", methods=["POST"])
def submit_milestone(pid):
    user_id, role = auth_context()
    require_role(role, {"Advisor"})
    program = get_or_404(db.training_programs, pid, "TrainingProgram")
    if program.get("status") not in ("ACTIVE", "REMEDIATION"):
        raise err("ERR_INVALID_STATE", "Program is not ACTIVE or REMEDIATION.")
    if program.get("advisor_id") != user_id:
        raise err("ERR_UNAUTHORIZED", "Only the program's advisor may submit a milestone.")
    program["status"] = "MILESTONE_PENDING"
    touch(program)
    return success_object(program)


@bp.route(f"{PREFIX}/<pid>/evaluate", methods=["POST"])
def evaluate_milestone(pid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    program = get_or_404(db.training_programs, pid, "TrainingProgram")
    body = body_json()
    require_fields(body, ["window_end"])
    window_end = parse_dt(body["window_end"], "window_end")
    force_outcome = body.get("force_outcome")
    if force_outcome is not None and force_outcome not in ("PASS", "FAIL"):
        raise err("ERR_INVALID_REQUEST", "force_outcome must be PASS or FAIL.")
    if program.get("status") != "MILESTONE_PENDING":
        raise err("ERR_INVALID_STATE", "Program is not MILESTONE_PENDING.")
    advisor = get_or_404(db.advisors, program.get("advisor_id"), "Advisor")
    # training_production_window: sum per-record rounded commissions in [start, end]
    start = parse_dt(program["start_date"], "start_date")
    production = 0
    for rec in db.production_records.values():
        if rec.get("advisor_id") != advisor["id"] or rec.get("status") != "POSTED":
            continue
        posted = parse_dt(rec["posted_at"], "posted_at")
        if start <= posted <= window_end:
            production += rec.get("commissions_cents", 0)
    outcome = "PASS" if production >= program.get("goal_cents", 0) else "FAIL"
    if force_outcome is not None:
        if force_outcome == "PASS" and outcome != "PASS":
            raise err("ERR_GOAL_NOT_MET", "Forced PASS but production_cents < goal_cents.")
        outcome = force_outcome
    evaluation = stamp_new({
        "training_program_id": pid,
        "window_end": db.iso_format(window_end),
        "production_cents": production,
        "outcome": outcome,
    }, with_version=False)
    db.milestone_evaluations[evaluation["id"]] = evaluation
    if outcome == "PASS":
        program["status"] = "COMPLETED"
        touch(program)
        advisor["status"] = "VALIDATED"
        touch(advisor)
    else:
        # second consecutive cycle FAIL?
        prior_fails = [e for e in db.milestone_evaluations.values()
                       if e.get("training_program_id") == pid
                       and e.get("outcome") == "FAIL"
                       and e.get("id") != evaluation["id"]]
        if prior_fails:
            program["status"] = "FAILED"
            touch(program)
            advisor["status"] = "TERMINATED"
            advisor["branch_id"] = None
            touch(advisor)
        else:
            program["status"] = "REMEDIATION"
            touch(program)
    return success_object(evaluation, 201)
