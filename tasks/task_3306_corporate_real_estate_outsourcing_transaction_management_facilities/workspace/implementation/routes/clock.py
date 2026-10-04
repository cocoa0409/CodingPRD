"""The governed logical clock."""
from core import auth, calc, domain
from core.db import DB, iso, parse_dt, serialize, touch
from core.errors import ApiError
from core.response import ok

from routes.registry import body, route

CLOCK_ROLES = ["GovernanceManager", "AccountExecutive"]


@route("POST", "/api/_clock/set_current_utc", "set_current_utc", CLOCK_ROLES)
def set_current_utc():
    data = body()
    if "to_iso8601" not in data or data.get("to_iso8601") is None:
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 is required.")
    target = parse_dt(data["to_iso8601"])
    if target is None:
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 instant.")
    previous = DB.clock
    if not target > previous:
        raise ApiError("ERR_CLOCK_ALREADY_ADVANCED",
                       "The logical clock only moves forward.")
    DB.clock = target
    return ok(_apply_clock_effects(previous, target))


def _apply_clock_effects(previous, target):
    touched_accounts = set()
    for task in DB.rows("transition_tasks"):
        if task.get("task_state") in ("PENDING", "IN_PROGRESS"):
            due_at = task.get("due_at")
            if due_at is not None and due_at <= target:
                task["task_state"] = "FAILED"
                touch(task)
                touched_accounts.add(task.get("account_id"))
    for account_id in list(touched_accounts):
        account = DB.get("accounts", account_id)
        if account is not None:
            account["completion_pct_bps"] = calc.transition_completion_score(account_id)
            domain.recompute_governance(account)
            touch(account)
    for lease in DB.rows("leases"):
        lease["expiration_bucket"] = calc.expiration_bucket(lease, target)
        touch(lease)
    for kpi in DB.rows("service_level_kpis"):
        if kpi.get("evaluation_state") in ("EVALUATED", "ESCALATED"):
            domain.settle_kpi(kpi)
            touch(kpi)
            touched_accounts.add(kpi.get("account_id"))
    for account_id in list(touched_accounts):
        account = DB.get("accounts", account_id)
        if account is not None:
            domain.recompute_governance(account)
            touch(account)
    delta_hours = (target - previous).total_seconds() / 3600.0
    if delta_hours == int(delta_hours):
        delta_hours = int(delta_hours)
    return {
        "current_utc": iso(target),
        "advanced_by_hours": delta_hours,
    }