"""POST /readiness-tasks and its status action (PRD section 3.10)."""

import calc
import clock
import enums
import machines
import services
import store
import validate
from errors import ApiError
from store import set_field

TERMINAL_BATCH_STATES = ("RECONCILED", "ABORTED")


def create_task():
    validate.gate(enums.ROLES_TASK_CREATE)
    body = validate.json_body()
    acquisition_id = validate.req_id(body, "acquisition_id")
    task_code = validate.req_enum(body, "task_code", enums.TASK_CODES)
    is_blocking = validate.opt_bool(body, "is_blocking", True)
    due_on = validate.req_date(body, "due_on")

    # Rank 5, then rank 8.  This endpoint is exempt from the clearance freeze.
    acquisition = store.require("acquisitions", acquisition_id)
    for peer in store.where("readiness_tasks", acquisition_id=acquisition_id,
                            task_code=task_code):
        raise ApiError("ERR_DUPLICATE_TASK_CODE",
                       "Checklist line '%s' already exists on this acquisition."
                       % task_code)

    row = {
        "acquisition_id": acquisition_id,
        "task_code": task_code,
        "domain": calc.TASK_DOMAIN[task_code],
        "is_blocking": is_blocking,
        "due_on": clock.format_date(due_on),
        "waiver_justification": None,
        "failure_reason": None,
        "verified_by_user_id": None,
        "status": "OPEN",
    }
    store.insert("readiness_tasks", row)
    services.recompute_posture(acquisition)
    return services.respond_created(row)


def task_status(entity_id):
    user_id, role = validate.gate(enums.ROLES_TASK_ACTION)
    body = validate.json_body()
    target = validate.req_enum(body, "target_status",
                               machines.TASK_STATUS_VALUES)
    waiver_justification = validate.opt_str(body, "waiver_justification")
    failure_reason = validate.opt_str(body, "failure_reason")

    task = store.require("readiness_tasks", entity_id)
    acquisition = store.require("acquisitions", task["acquisition_id"])
    from_state = task["status"]

    # Rank 14: transition legality, then the conditional completion gate that
    # carries no dedicated code of its own.
    machines.resolve(machines.TASK_STATUS, from_state, target, role)
    if target == "COMPLETE" and task["task_code"] == "HR_STAFFING_PLAN":
        if acquisition["hr_staffing_coverage_pct"] < calc.HR_COVERAGE_MIN_PCT:
            raise machines.invalid(from_state, target)

    # This endpoint is exempt from the compliance-clearance freeze.

    # Rank 26: a waiver needs a substantive justification.
    if target == "WAIVED":
        if waiver_justification is None or waiver_justification.strip() == "":
            raise ApiError("ERR_WAIVER_JUSTIFICATION_REQUIRED",
                           "A non-empty waiver_justification is required.")

    # Rank 43: the migration workstream must be finished.
    if target == "COMPLETE" and task["task_code"] == "IT_DATA_MIGRATION":
        for batch in store.where("ehr_migration_batches",
                                 acquisition_id=acquisition["id"]):
            if batch["status"] not in TERMINAL_BATCH_STATES:
                raise ApiError("ERR_MIGRATION_INCOMPLETE",
                               "Migration batch %s is in %s."
                               % (batch["id"], batch["status"]))

    set_field(task, "status", target)
    if target == "COMPLETE":
        set_field(task, "verified_by_user_id", user_id)
    elif target == "WAIVED":
        set_field(task, "waiver_justification", waiver_justification)
        set_field(task, "verified_by_user_id", user_id)
    elif target == "FAILED":
        set_field(task, "failure_reason", failure_reason)
    elif target == "IN_PROGRESS" and from_state == "FAILED":
        set_field(task, "failure_reason", None)

    services.recompute_posture(acquisition)
    return services.respond(task)


def register(app):
    app.add_url_rule("/readiness-tasks", "create_task", create_task,
                     methods=["POST"])
    app.add_url_rule("/readiness-tasks/<entity_id>/status", "task_status",
                     task_status, methods=["POST"])
