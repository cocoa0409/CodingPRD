"""EscalationCase routes: the two manual levers plus the discretionary hold."""
from flask import Blueprint

import calc
import db
import guards
import middleware
import recompute
from errors import fail
from middleware import ALL_ROLES, EMPLOYEE, HR_BUSINESS_PARTNER, PEOPLE_MANAGER

bp = Blueprint("escalation", __name__)

READ_ROLES = tuple(r for r in ALL_ROLES if r != EMPLOYEE)
TERMINAL_STAGES = ("CURED", "CLOSED_SEPARATION")


def _interactive_pending(employee):
    for request in db.find("exception_request", employee_id=employee["id"]):
        if (request["status"] in ("SUBMITTED", "INFO_REQUESTED")
                and request["interactive_process_required"]):
            return True
    return False


@bp.route("/escalation-cases/<case_id>/escalate", methods=["POST"])
def escalate(case_id):
    actor = middleware.authorize((HR_BUSINESS_PARTNER,))
    case = middleware.must_exist("escalation_case", case_id)
    employee = db.get("employee", case["employee_id"])

    if actor.user_id == employee["manager_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "a manager may not sign their own report's formal action")

    payload = middleware.body()
    note = middleware.req_string(payload, "action_note", 1, None)

    if case["stage"] in TERMINAL_STAGES:
        fail("ERR_ESCALATION_TERMINAL", "the escalation case is terminal")
    if case["stage"] == "REFERRED":
        fail("ERR_ESCALATION_AT_CEILING", "the escalation case is already at REFERRED")
    if _interactive_pending(employee):
        fail("ERR_INTERACTIVE_PROCESS_PENDING",
             "an interactive accommodation process is in flight for this employee")

    next_stage = calc.LADDER[calc.LADDER.index(case["stage"]) + 1]
    db.apply_changes(case, {
        "stage": next_stage,
        "discretionary_hold": True,
        "last_action_by_user_id": actor.user_id,
        "action_note": note,
    })
    _after_manual_lever(employee, case)
    return guards.single("escalation_case", case)


@bp.route("/escalation-cases/<case_id>/de-escalate", methods=["POST"])
def de_escalate(case_id):
    actor = middleware.authorize((PEOPLE_MANAGER,))
    case = middleware.must_exist("escalation_case", case_id)
    employee = db.get("employee", case["employee_id"])

    if actor.user_id != employee["manager_user_id"]:
        fail("ERR_UNAUTHORIZED", "only the employee's own PeopleManager may de-escalate")

    payload = middleware.body()
    note = middleware.req_string(payload, "action_note", 1, None)

    if case["stage"] in TERMINAL_STAGES:
        fail("ERR_ESCALATION_TERMINAL", "the escalation case is terminal")
    if case["stage"] == "COACHING":
        fail("ERR_ESCALATION_AT_FLOOR", "the escalation case is already at COACHING")

    next_stage = calc.LADDER[calc.LADDER.index(case["stage"]) - 1]
    db.apply_changes(case, {
        "stage": next_stage,
        "discretionary_hold": False,
        "last_action_by_user_id": actor.user_id,
        "action_note": note,
    })
    _after_manual_lever(employee, case)
    return guards.single("escalation_case", case)


def _after_manual_lever(employee, case):
    recompute.mirror_stage(employee, case)
    team = recompute.team_of_employee(employee)
    recompute.recompute_team_counters(team)
    recompute.recompute_cycle_rollups(recompute.cycle_of_team(team) if team else None)


@bp.route("/escalation-cases/<case_id>/hold", methods=["POST"])
def hold(case_id):
    actor = middleware.authorize((HR_BUSINESS_PARTNER,))
    case = middleware.must_exist("escalation_case", case_id)
    payload = middleware.body()
    flag = middleware.req_bool(payload, "discretionary_hold")
    middleware.req_string(payload, "action_note", 1, None)

    db.apply_changes(case, {
        "discretionary_hold": flag,
        "last_action_by_user_id": actor.user_id,
    })
    return guards.single("escalation_case", case)


@bp.route("/escalation-cases/<case_id>", methods=["GET"])
def get_case(case_id):
    middleware.authorize(READ_ROLES)
    row = middleware.must_exist("escalation_case", case_id)
    return guards.single("escalation_case", row)


@bp.route("/escalation-cases", methods=["GET"])
def list_cases():
    middleware.authorize(READ_ROLES)
    rows = db.all_rows("escalation_case")
    for arg in ("employee_id", "prior_case_id", "stage"):
        value = middleware.filter_arg(arg)
        if value is not None:
            rows = [r for r in rows if r[arg] == value]
    return guards.paged("escalation_case", rows)
