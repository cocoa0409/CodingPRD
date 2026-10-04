"""TransitionTask routes and the closure-progress signal."""
from core import auth, calc, domain
from core.db import DB, new_common, parse_dt, serialize, touch
from core.errors import ApiError
from core.response import ok

from routes.registry import body, lookup, paginated_ok, req, route, validate

TM_ONLY = ["TransitionManager"]
TASK_ROLES = ["AccountExecutive", "TransitionManager", "GovernanceManager"]

TASK_TYPES = ("DATA_HANDOVER", "RECORDS_TRANSFER", "VENDOR_TERMINATION",
              "FINAL_RECONCILIATION")


@route("POST", "/api/transition-tasks", "create_transition_task", TM_ONLY, 201)
def create_transition_task():
    data = validate(body(), [req("account_id"), req("task_name"), req("task_type"),
                             req("sequence_no"), req("blocking"), req("due_at")])
    account = lookup("accounts", data.get("account_id"), "account")
    if data["task_type"] not in TASK_TYPES:
        raise ApiError("ERR_INVALID_REQUEST",
                       "task_type must be one of %s." % ", ".join(TASK_TYPES))
    if not isinstance(data["blocking"], bool):
        raise ApiError("ERR_INVALID_REQUEST", "blocking must be a boolean.")
    seq = data["sequence_no"]
    if isinstance(seq, bool) or not isinstance(seq, int):
        raise ApiError("ERR_INVALID_REQUEST", "sequence_no must be an integer.")
    due_at = parse_dt(data["due_at"])
    if due_at is None:
        raise ApiError("ERR_INVALID_REQUEST", "due_at must be an ISO 8601 instant.")
    obj = new_common()
    obj.update({
        "account_id": account["id"],
        "task_name": data["task_name"],
        "task_type": data["task_type"],
        "sequence_no": seq,
        "blocking": data["blocking"],
        "due_at": due_at,
        "task_state": "PENDING",
    })
    DB.insert("transition_tasks", obj)
    account["completion_pct_bps"] = calc.transition_completion_score(account["id"])
    touch(account)
    return ok(serialize(obj), 201)


@route("GET", "/api/transition-tasks", "list_transition_tasks", TASK_ROLES)
def list_transition_tasks():
    rows = DB.ordered("transition_tasks")
    args = __import__("flask").request.args
    if args.get("account_id"):
        rows = [r for r in rows if r.get("account_id") == args.get("account_id")]
    if args.get("task_type"):
        rows = [r for r in rows if r.get("task_type") == args.get("task_type")]
    return paginated_ok(rows)


@route("GET", "/api/transition-tasks/<task_id>", "get_transition_task", TASK_ROLES)
def get_transition_task(task_id):
    return ok(serialize(lookup("transition_tasks", task_id, "transition task")))


@route("POST", "/api/transition-tasks/<task_id>/start", "start_transition_task", TM_ONLY)
def start_transition_task(task_id):
    task = lookup("transition_tasks", task_id, "transition task")
    account = lookup("accounts", task.get("account_id"), "account")
    if task.get("task_state") != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Only a PENDING task may be started.")
    if account.get("lifecycle_state") != "OFFBOARDING":
        raise ApiError("ERR_INVALID_STATE", "Starting a task requires an OFFBOARDING account.")
    due_at = task.get("due_at")
    if due_at is None or not due_at > DB.clock:
        raise ApiError("ERR_INVALID_STATE",
                       "The task is overdue and cannot be started.")
    task["task_state"] = "IN_PROGRESS"
    touch(task)
    return ok(serialize(task))


@route("POST", "/api/transition-tasks/<task_id>/complete", "complete_transition_task",
       TM_ONLY)
def complete_transition_task(task_id):
    task = lookup("transition_tasks", task_id, "transition task")
    account = lookup("accounts", task.get("account_id"), "account")
    if task.get("task_state") != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Only an IN_PROGRESS task may be completed.")
    if account.get("lifecycle_state") != "OFFBOARDING":
        raise ApiError("ERR_INVALID_STATE", "Completion requires an OFFBOARDING account.")
    task["task_state"] = "DONE"
    touch(task)
    account["completion_pct_bps"] = calc.transition_completion_score(account["id"])
    domain.recompute_governance(account)
    touch(account)
    return ok(serialize(task))


@route("POST", "/api/transition-tasks/<task_id>/fail", "fail_transition_task", TM_ONLY)
def fail_transition_task(task_id):
    task = lookup("transition_tasks", task_id, "transition task")
    account = lookup("accounts", task.get("account_id"), "account")
    if task.get("task_state") != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Only an IN_PROGRESS task may be failed.")
    if account.get("lifecycle_state") != "OFFBOARDING":
        raise ApiError("ERR_INVALID_STATE", "Failure requires an OFFBOARDING account.")
    task["task_state"] = "FAILED"
    touch(task)
    account["completion_pct_bps"] = calc.transition_completion_score(account["id"])
    domain.recompute_governance(account)
    touch(account)
    return ok(serialize(task))


@route("POST", "/api/transition-tasks/<task_id>/expire", "expire_transition_task", TM_ONLY)
def expire_transition_task(task_id):
    task = lookup("transition_tasks", task_id, "transition task")
    account = lookup("accounts", task.get("account_id"), "account")
    if task.get("task_state") not in ("PENDING", "IN_PROGRESS"):
        raise ApiError("ERR_INVALID_STATE",
                       "Only a non-terminal task may be expired.")
    due_at = task.get("due_at")
    if due_at is None or due_at > DB.clock:
        raise ApiError("ERR_INVALID_STATE",
                       "The account clock has not yet passed the task's due_at.")
    task["task_state"] = "FAILED"
    touch(task)
    account["completion_pct_bps"] = calc.transition_completion_score(account["id"])
    domain.recompute_governance(account)
    touch(account)
    return ok(serialize(task))