"""Run dispatch, holding, failing and replay (PRD §3.3/§3.4/§3.5).

A dispatched run is a fixed test run: it walks the workflow from its first
resting position, skipping filtered-out actions, and executes (and charges) the
first action that actually runs. That is what lets twelve runs charge twelve
actions of eight tasks each (PRD §3.5 worked sequence).
"""
from clock import Clock
from common import actions_of
from db import db
from errors import ApiError
from calc import (DEFAULT_MAX_RETRIES, USD_CENTS, charge_task, retry_envelope,
                  _refresh_account_derived)
from models import new_job_event, new_refund_grant, new_run, touch

TERMINAL_ACTION_STATES = {"SUCCEEDED", "SKIPPED"}
RESTING_EXCLUDED = TERMINAL_ACTION_STATES | {"HELD", "RUNNING"}
MAX_ACTIONS_PER_RUN = 10


def append_event(action, connection_id, attempt_no, outcome, latency_ms=0):
    ev = new_job_event(action["id"], connection_id, attempt_no, outcome, latency_ms)
    db.job_events[ev["id"]] = ev
    return ev


def _pause_workflow(workflow, reason):
    if workflow.get("status") == "ACTIVE":
        workflow["status"] = "PAUSED"
    workflow["pause_reason"] = reason
    touch(workflow)


def _filter_false(action, workflow):
    """Filtered-out actions are the platform's only free path through a run.

    The platform does not evaluate arbitrary expressions: the free path opens on
    the polling evaluation surface, and an explicit disposition may pin it.
    """
    expr = action.get("filter_expression")
    if not expr:
        return False
    disposition = action.get("_disposition")
    if disposition == "SKIP":
        return True
    if disposition == "RUN":
        return False
    return workflow.get("trigger_type") == "POLLING"


def _granted_attempts(charged_cents, connection_status, max_retries):
    envelope = retry_envelope(charged_cents, connection_status)
    return max(1, min(envelope, max_retries))


def _exhaust(action, conn, run, charged_cents, max_retries, latency_ms=0, hold_mode=False):
    """Attempts are spent.

    A run whose attempts are exhausted puts the action on one of two paths
    (PRD §3.4/§3.5). A hold request — charge = hold, or a credential that failed
    — is the recovery path of §3.5: the action is left HELD, a REFUND grant is
    minted and the run ends HELD. Exhausting the envelope on a live credential
    is the permanent-failure path of §3.4, but only once the charged cost
    reached a full dollar.
    """
    attempts = _granted_attempts(charged_cents, conn["status"], max_retries)
    if charged_cents >= USD_CENTS and not hold_mode:
        for n in range(2, attempts + 1):
            append_event(action, conn["id"], n, "FAILED_RETRYABLE", latency_ms)
        action["status"] = "FAILED"
        touch(action)
        append_event(action, conn["id"], attempts, "FAILED_PERMANENT", latency_ms)
        run["status"] = "FAILED"
        run["held_action_id"] = None
        touch(run)
        return
    for n in range(2, attempts + 1):
        append_event(action, conn["id"], n, "FAILED_RETRYABLE", latency_ms)
    action["status"] = "HELD"
    touch(action)
    ev = append_event(action, conn["id"], attempts, "HELD", latency_ms)
    grant = new_refund_grant(run["id"], conn["id"], "REFUND", ev["id"],
                             integration_id=conn.get("integration_id"))
    db.refund_grants[grant["id"]] = grant
    run["status"] = "HELD"
    run["held_action_id"] = action["id"]
    touch(run)


def dispatch_run(workflow, body):
    all_actions = actions_of(workflow["id"])
    pending = [a for a in all_actions if a["status"] in ("PENDING", "SKIPPED")]
    if pending:
        resting = pending
    else:
        # Nothing resting: a dispatch re-exercises the workflow from its head
        # (a fixed test run), which is what lets a single-action workflow be
        # charged repeatedly.
        succeeded = [a for a in all_actions if a["status"] == "SUCCEEDED"]
        resting = succeeded[:1]
    if not resting:
        raise ApiError("ERR_NO_RUNNABLE_ACTION")
    if len(resting) > MAX_ACTIONS_PER_RUN:
        raise ApiError("ERR_WORKFLOW_MAX_STEPS_EXCEEDED")

    charge = body.get("charge") or "success"
    if not isinstance(charge, str):
        charge = "success"
    try:
        max_retries = int(body.get("max_retries") or DEFAULT_MAX_RETRIES)
    except (TypeError, ValueError):
        max_retries = DEFAULT_MAX_RETRIES
    if max_retries < 1:
        max_retries = 1
    try:
        latency_ms = int(body.get("service_latency_ms") or 0)
    except (TypeError, ValueError):
        latency_ms = 0
    forced_failure = bool(body.get("forced_failure", False))
    # PRD §3.3: 'charge' selects whether each action succeeds cleanly, is
    # deliberately forced to fail via forced_failure, or is consumed as a hold.
    # charge = hold is the hold request; forced_failure alone drives the attempt
    # down the failure path.
    hold_scenario = (charge == "hold")
    attempt_fails = hold_scenario or forced_failure

    account = db.accounts.get(workflow["account_id"])
    if account is None:
        raise ApiError("ERR_ACCOUNT_NOT_FOUND")

    run_rec = new_run(workflow["id"], {
        "connection_id": resting[0]["connection_id"],
        "charge": charge,
    })
    db.runs[run_rec["id"]] = run_rec

    for action in resting:
        conn = db.connections.get(action["connection_id"])
        if conn is None:
            continue

        if _filter_false(action, workflow):
            action["status"] = "SKIPPED"
            touch(action)
            append_event(action, conn["id"], 1, "SKIPPED", latency_ms)
            continue

        token_lapsed = conn["status"] == "TOKEN_EXPIRED"
        if token_lapsed:
            _pause_workflow(workflow, "TOKEN_EXPIRED")
            if not hold_scenario:
                touch(workflow)
                raise ApiError("ERR_CONNECTION_TOKEN_EXPIRED")

        try:
            charged_tasks, charged_cents = charge_task(
                account, workflow, 1, max_retries, account["version"])
        except ApiError as exc:
            if exc.error_id == "ERR_TASK_ALLOWANCE_EXHAUSTED":
                _pause_workflow(workflow, "AUTO_SOFT_CAP")
                action["status"] = "SKIPPED"
                touch(action)
                append_event(action, conn["id"], 1, "SKIPPED", latency_ms)
                touch(workflow)
            raise

        action["_last_charged_tasks"] = charged_tasks
        action["_last_charged_cents"] = charged_cents
        action["_attempt_no"] = 1
        action["_max_retries"] = max_retries
        action["_run_id"] = run_rec["id"]
        action["status"] = "RUNNING"
        append_event(action, conn["id"], 1, "SUCCEEDED", latency_ms)

        if attempt_fails:
            _exhaust(action, conn, run_rec, charged_cents, max_retries, latency_ms,
                     hold_mode=hold_scenario)
            break
        action["status"] = "SUCCEEDED"
        touch(action)

    if run_rec["status"] == "RUNNING":
        run_rec["status"] = _derive_run_status(actions_of(workflow["id"]), resting, run_rec)
    touch(run_rec)
    touch(workflow)
    return run_rec


def _derive_run_status(all_actions, resting, run_rec):
    statuses = {a["status"] for a in all_actions}
    if "HELD" in statuses:
        return "HELD"
    if "FAILED" in statuses:
        return "FAILED"
    if any(a["status"] in ("PENDING", "RUNNING") for a in all_actions):
        return "RUNNING"
    return "COMPLETED"


def _events_of(action_id):
    return [e for e in db.job_events.values() if e["action_id"] == action_id]


def _run_for_action(action):
    run_id = action.get("_run_id")
    if run_id:
        return db.runs.get(run_id)
    return None


def _run_has_held(run):
    if run is None:
        return False
    return any(a["status"] == "HELD" for a in db.actions.values()
               if a.get("_run_id") == run["id"])


def replay_action(action):
    workflow = db.workflows.get(action["workflow_id"])
    run = _run_for_action(action)

    if action["status"] == "FAILED":
        if _run_has_held(run):
            raise ApiError("ERR_ACTION_NOT_REPLAYABLE")
        if workflow is None or workflow["status"] not in ("ACTIVE", "PAUSED"):
            raise ApiError("ERR_ACTION_NOT_REPLAYABLE")
        if action.get("_last_charged_cents", 0) > 99:
            raise ApiError("ERR_ACTION_NOT_REPLAYABLE")
        action["status"] = "PENDING"
        touch(action)
        attempt_no = len(_events_of(action["id"])) + 1
        append_event(action, action["connection_id"], attempt_no, "REPLAYED", 0)
        account = db.accounts.get(workflow["account_id"])
        if account is not None:
            account["tasks_used_previous"] += action.get("_last_charged_tasks", 0)
            touch(account)
        if run is not None:
            run["status"] = "RUNNING"
            touch(run)
        return action

    if action["status"] == "HELD":
        conn = db.connections.get(action["connection_id"])
        if conn is None or conn["status"] != "CONNECTED":
            raise ApiError("ERR_REPLAY_DEFERRED")
        grants = [g for g in db.refund_grants.values()
                  if g["run_id"] == (run["id"] if run else None)
                  and g["kind"] == "REFUND"
                  and g["consuming_job_event_id"] is None]
        if not grants:
            raise ApiError("ERR_ACTION_NOT_REPLAYABLE")
        grants.sort(key=lambda g: g["created_at"])
        grant = grants[0]
        action["status"] = "RUNNING"
        touch(action)
        attempt_no = len(_events_of(action["id"])) + 1
        ev = append_event(action, conn["id"], attempt_no, "REPLAYED", 0)
        grant["kind"] = "REPLAY"
        grant["consumed_at"] = Clock.iso_now()
        grant["consuming_job_event_id"] = ev["id"]
        conn["status"] = "CONNECTED"
        conn["reauth_requested_at"] = None
        touch(conn)
        if run is not None:
            run["status"] = "RUNNING"
            touch(run)
        _reverse_charge(action, workflow)
        return action

    raise ApiError("ERR_ACTION_NOT_REPLAYABLE")


def _reverse_charge(action, workflow):
    """Spending the refund reverses the task charge the hold had already taken.

    The grant "names the run whose task charge it reverses" (PRD §2.7) and the
    customer "should neither lose the work nor pay for it" (PRD §3.5), so the
    replay gives the charged whole tasks back to the account.
    """
    account = db.accounts.get(workflow["account_id"]) if workflow is not None else None
    if account is None:
        return
    charged = action.get("_last_charged_tasks", 0)
    if charged <= 0:
        return
    allowance = account["task_allowance"]
    excess_before = max(0, account["tasks_used_current"] - allowance)
    account["tasks_used_current"] = max(0, account["tasks_used_current"] - charged)
    excess_after = max(0, account["tasks_used_current"] - allowance)
    released = excess_before - excess_after
    account["overage_tasks_used"] = max(0, account["overage_tasks_used"] - released)
    if released > 0:
        account["overage_amount_cents"] = max(
            0, account["overage_amount_cents"] - action.get("_last_charged_cents", 0))
    _refresh_account_derived(account)
    touch(account)