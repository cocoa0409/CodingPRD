"""Training modules, curriculum assignments, sweeps and escalation notices."""
from flask import Blueprint

import calc
import cascades
import derive
import guards
import lookups
from envelope import created, ok, ok_list, paginate
from errors import fail
from store import add_days, fmt, new_row, now, ordered, store, touch

bp = Blueprint("training", __name__)


# ------------------------------------------------------------ training modules
@bp.post("/awareness/training-modules")
def create_module():
    guards.authorize("ProgramAdmin")
    data = guards.body()
    code = guards.req_str(data, "code")
    title = guards.req_str(data, "title")
    module_type = guards.req_enum(data, "module_type", calc.MODULE_TYPES)
    applies_to = guards.opt_enum_array(data, "applies_to_role_codes", calc.ROLE_CODES, [])
    criticality = guards.opt_enum(data, "criticality", calc.CRITICALITIES, "STANDARD")
    passing = guards.opt_int(data, "passing_score_pct", 80, 0, 100)
    offsets = guards.opt_int_array(data, "reminder_offsets_days",
                                   calc.DEFAULT_REMINDER_OFFSETS_DAYS)
    escalate_after = guards.opt_int(data, "escalate_after_reminders", 3, 1, None)
    max_extension = guards.opt_int(data, "max_extension_days", 10, 0, None)

    for other in store.modules.values():
        if other["code"] == code:
            fail("ERR_DUPLICATE_MODULE_CODE", "module code %s already exists" % code)

    row = new_row()
    row.update({
        "code": code,
        "title": title,
        "module_type": module_type,
        "applies_to_role_codes": applies_to,
        "criticality": criticality,
        "passing_score_pct": passing,
        "reminder_offsets_days": offsets,
        "escalate_after_reminders": escalate_after,
        "max_extension_days": max_extension,
        "status": "DRAFT",
        "published_at": None,
        "retired_at": None,
    })
    store.modules[row["id"]] = row
    return created(derive.module_json(row))


@bp.get("/awareness/training-modules/<module_id>")
def read_module(module_id):
    guards.authorize("ProgramAdmin", "SecurityAnalyst", "Learner")
    return ok(derive.module_json(lookups.get_module(module_id)))


@bp.post("/awareness/training-modules/<module_id>/publish")
def publish_module(module_id):
    guards.authorize("ProgramAdmin")
    mod = lookups.get_module(module_id)
    if mod["status"] != "DRAFT":
        fail("ERR_MODULE_STATE_INVALID", "only a DRAFT module can be published")
    if mod["module_type"] == "ROLE_SPECIFIC" and not mod["applies_to_role_codes"]:
        fail("ERR_MODULE_STATE_INVALID",
             "a ROLE_SPECIFIC module needs at least one applies_to_role_codes entry")
    mod["status"] = "PUBLISHED"
    mod["published_at"] = now()
    touch(mod)
    return ok(derive.module_json(mod))


@bp.post("/awareness/training-modules/<module_id>/retire")
def retire_module(module_id):
    guards.authorize("ProgramAdmin")
    mod = lookups.get_module(module_id)
    if mod["status"] != "PUBLISHED":
        fail("ERR_MODULE_STATE_INVALID", "only a PUBLISHED module can be retired")
    mod["status"] = "RETIRED"
    mod["retired_at"] = now()
    touch(mod)
    return ok(derive.module_json(mod))


# ------------------------------------------------------- curriculum assignments
@bp.post("/awareness/curriculum-assignments")
def create_assignment():
    guards.authorize("ProgramAdmin")
    data = guards.body()
    employee_id = guards.req_str(data, "employee_id")
    module_id = guards.req_str(data, "module_id")
    reason = guards.req_enum(data, "assignment_reason", calc.ASSIGNMENT_REASONS)
    expected = guards.req_int(data, "expected_employee_version")

    emp = lookups.get_employee(employee_id)
    mod = lookups.get_module(module_id)

    if expected != emp["version"]:
        fail("ERR_STALE_EMPLOYEE_VERSION",
             "expected_employee_version %s does not match %s" % (expected, emp["version"]))
    if emp["employment_status"] != "ACTIVE":
        fail("ERR_EMPLOYEE_OFFBOARDED", "employee is offboarded")
    if mod["status"] != "PUBLISHED":
        fail("ERR_MODULE_NOT_PUBLISHED", "module is not PUBLISHED")
    if mod["applies_to_role_codes"] and emp["role_code"] not in mod["applies_to_role_codes"]:
        fail("ERR_ROLE_NOT_ELIGIBLE_FOR_MODULE",
             "role %s is not eligible for this module" % emp["role_code"])

    row = cascades.create_assignment(emp, mod, reason)
    touch(emp)
    return created(derive.assignment_json(row))


@bp.get("/awareness/curriculum-assignments/<assignment_id>")
def read_assignment(assignment_id):
    guards.authorize("ProgramAdmin", "SecurityAnalyst", "Learner", "Manager")
    return ok(derive.assignment_json(lookups.get_assignment(assignment_id)))


@bp.get("/awareness/curriculum-assignments")
def list_assignments():
    guards.authorize("ProgramAdmin", "SecurityAnalyst", "Manager")
    limit, offset = guards.pagination()
    employee_id = guards.query_str("employee_id")
    module_id = guards.query_str("module_id")
    state = guards.query_enum("state", calc.ASSIGNMENT_STATES)
    reason = guards.query_enum("assignment_reason", calc.ASSIGNMENT_REASONS)
    superseded_by = guards.query_str("superseded_by_assignment_id")

    rows = []
    for row in ordered(list(store.assignments.values())):
        if employee_id is not None and row["employee_id"] != employee_id:
            continue
        if module_id is not None and row["module_id"] != module_id:
            continue
        if state is not None and row["state"] != state:
            continue
        if reason is not None and row["assignment_reason"] != reason:
            continue
        if superseded_by is not None and row["superseded_by_assignment_id"] != superseded_by:
            continue
        rows.append(row)
    page, total = paginate(rows, limit, offset)
    return ok_list([derive.assignment_json(r) for r in page], limit, offset, total)


def _learner_owned(actor, assignment):
    if assignment["employee_id"] != actor.user_id:
        fail("ERR_NOT_ASSIGNMENT_OWNER", "the acting learner does not own this assignment")


def _module_still_published(assignment):
    mod = store.modules.get(assignment["module_id"])
    if mod is None or mod["status"] != "PUBLISHED":
        fail("ERR_MODULE_RETIRED", "the referenced module is no longer PUBLISHED")
    return mod


@bp.post("/awareness/curriculum-assignments/<assignment_id>/start")
def start_assignment(assignment_id):
    actor = guards.authorize("Learner")
    asg = lookups.get_assignment(assignment_id)
    _learner_owned(actor, asg)
    if asg["state"] not in ("ASSIGNED", "OVERDUE", "ESCALATED"):
        fail("ERR_ASSIGNMENT_STATE_INVALID", "cannot start from state %s" % asg["state"])
    emp = store.employees.get(asg["employee_id"])
    if emp is not None and emp["employment_status"] != "ACTIVE":
        fail("ERR_EMPLOYEE_OFFBOARDED", "employee is offboarded")
    _module_still_published(asg)
    asg["state"] = "IN_PROGRESS"
    touch(asg)
    return ok(derive.assignment_json(asg))


@bp.post("/awareness/curriculum-assignments/<assignment_id>/submit")
def submit_assignment(assignment_id):
    actor = guards.authorize("Learner")
    data = guards.body()
    score = guards.req_int(data, "score_pct", 0, 100)
    asg = lookups.get_assignment(assignment_id)
    _learner_owned(actor, asg)
    if asg["state"] != "IN_PROGRESS":
        fail("ERR_ASSIGNMENT_STATE_INVALID", "cannot submit from state %s" % asg["state"])
    mod = _module_still_published(asg)

    asg["attempt_count"] += 1
    asg["last_score_pct"] = score
    if score >= mod["passing_score_pct"]:
        cascades.complete_assignment(asg)
        cascades.bump_employee(store.employees.get(asg["employee_id"]))
    else:
        asg["state"] = "FAILED_ATTEMPT"
        touch(asg)
    return ok(derive.assignment_json(asg))


@bp.post("/awareness/curriculum-assignments/<assignment_id>/retake")
def retake_assignment(assignment_id):
    actor = guards.authorize("Learner")
    asg = lookups.get_assignment(assignment_id)
    _learner_owned(actor, asg)
    if asg["state"] != "FAILED_ATTEMPT":
        fail("ERR_ASSIGNMENT_STATE_INVALID", "cannot retake from state %s" % asg["state"])
    _module_still_published(asg)
    asg["state"] = "IN_PROGRESS"
    touch(asg)
    return ok(derive.assignment_json(asg))


@bp.post("/awareness/curriculum-assignments/<assignment_id>/extension")
def grant_extension(assignment_id):
    actor = guards.authorize("Manager")
    data = guards.body()
    extension_days = guards.req_int(data, "extension_days", 1, None)
    asg = lookups.get_assignment(assignment_id)
    emp = store.employees.get(asg["employee_id"])
    if emp is None or emp["manager_id"] != actor.user_id:
        fail("ERR_NOT_DIRECT_REPORT_MANAGER", "the acting manager does not manage this learner")
    if asg["state"] not in ("ASSIGNED", "OVERDUE", "ESCALATED"):
        fail("ERR_ASSIGNMENT_STATE_INVALID", "cannot extend from state %s" % asg["state"])

    mod = store.modules.get(asg["module_id"])
    total = asg["granted_extension_days"] + extension_days
    if mod is not None and total > mod["max_extension_days"]:
        fail("ERR_EXTENSION_LIMIT_EXCEEDED",
             "granted_extension_days would exceed max_extension_days")
    if asg["escalation_level"] >= 3:
        fail("ERR_EXTENSION_WINDOW_CLOSED",
             "an assignment at the suspension rung can no longer be extended")
    if now() > add_days(asg["due_at"], total):
        fail("ERR_EXTENSION_WINDOW_CLOSED", "the grant would not move the deadline into the future")

    asg["granted_extension_days"] = total
    asg["escalation_level"] = 0
    asg["state"] = "ASSIGNED" if asg["attempt_count"] == 0 else "IN_PROGRESS"
    touch(asg)
    cascades.expire_sent_notices(asg["id"])
    cascades.close_assignment_consequences(asg["id"], "VOIDED", "DEADLINE_EXTENDED")
    cascades.bump_employee(emp)
    return ok(derive.assignment_json(asg))


@bp.post("/awareness/curriculum-assignments/<assignment_id>/void")
def void_assignment(assignment_id):
    guards.authorize("ProgramAdmin")
    data = guards.body()
    void_reason_code = guards.req_str(data, "void_reason_code")
    asg = lookups.get_assignment(assignment_id)
    if asg["state"] not in calc.ASSIGNMENT_NON_TERMINAL:
        fail("ERR_ASSIGNMENT_STATE_INVALID", "cannot void from state %s" % asg["state"])
    cascades.void_assignment(asg, void_reason_code)
    cascades.bump_employee(store.employees.get(asg["employee_id"]))
    return ok(derive.assignment_json(asg))


# ------------------------------------------------------------ compliance sweep
@bp.post("/awareness/compliance-sweeps")
def run_sweep():
    guards.authorize("ProgramAdmin")
    result = cascades.run_compliance_sweep()
    result["swept_at"] = fmt(result["swept_at"])
    return ok(result)


# --------------------------------------------------------- escalation notices
@bp.get("/awareness/escalation-notices/<notice_id>")
def read_notice(notice_id):
    guards.authorize("ProgramAdmin", "SecurityAnalyst", "Manager")
    return ok(derive.notice_json(lookups.get_notice(notice_id)))


@bp.get("/awareness/escalation-notices")
def list_notices():
    guards.authorize("ProgramAdmin", "SecurityAnalyst", "Manager")
    limit, offset = guards.pagination()
    assignment_id = guards.query_str("assignment_id")
    manager_id = guards.query_str("manager_id")
    state = guards.query_enum("state", calc.NOTICE_STATES)
    level = guards.query_int("level")

    rows = []
    for row in ordered(list(store.notices.values())):
        if assignment_id is not None and row["assignment_id"] != assignment_id:
            continue
        if manager_id is not None and row["manager_id"] != manager_id:
            continue
        if state is not None and row["state"] != state:
            continue
        if level is not None and row["level"] != level:
            continue
        rows.append(row)
    page, total = paginate(rows, limit, offset)
    return ok_list([derive.notice_json(r) for r in page], limit, offset, total)


@bp.post("/awareness/escalation-notices/<notice_id>/acknowledge")
def acknowledge_notice(notice_id):
    actor = guards.authorize("Manager")
    data = guards.body()
    note = guards.req_str(data, "action_plan_note")
    row = lookups.get_notice(notice_id)
    if row["manager_id"] != actor.user_id:
        fail("ERR_NOT_DIRECT_REPORT_MANAGER", "this notice is addressed to another manager")
    if row["state"] != "SENT":
        fail("ERR_NOTICE_STATE_INVALID", "notice is not in SENT")
    row["state"] = "ACKNOWLEDGED"
    row["acknowledged_at"] = now()
    row["action_plan_note"] = note
    touch(row)
    return ok(derive.notice_json(row))
