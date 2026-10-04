"""Difficulty queue A: non-linear state machines (return cycle, retry cycle)."""
from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    validate_paginated,
    admin_of,
    approver_as,
    ApiErrorId,
    create_active_connector,
    create_run,
    create_tenant,
    initiate,
    list_notifications,
    set_clock,
    setup_active_definition,
)


def _returned_instance():
    """Two-step APPROVAL chain (step 2 returns to step 1); instance with
    step 1 approved and step 2 returned."""
    ctx = setup_active_definition(
        "T-NL1", steps=[{"order": 1}, {"order": 2, "return_target": 1}],
    )
    tid, admin = ctx["tenant"]["id"], ctx["admin"]
    approver = approver_as(ctx["approver"]["id"])
    inst = initiate(ctx)
    iid = inst["id"]
    get_success_data(api_client.approve_step(tid, iid, 1, {}, approver))
    get_success_data(
        api_client.return_step(tid, iid, 2, {"comment": "revise"}, approver)
    )
    return ctx, iid


def test_return_rewinds_and_preserves_history(api):
    """PRD §3.6: "A return requires a `comment`, appends a `RETURN` event,
    rewinds `current_step_order` to the return target — intermediate step
    events are never erased, so history survives the loop — and notifies the
    initiator with a `RETURNED` notification."

    Design: Difficulty/non_linear_state_machine/transaction_return_cycle_preserves_history
    """
    ctx, iid = _returned_instance()
    tid, admin = ctx["tenant"]["id"], ctx["admin"]

    inst = get_success_data(api_client.get_transaction(tid, iid, admin))
    assert inst["status"] == "IN_PROGRESS"
    assert inst["current_step_order"] == 1, (
        f"return must rewind to step 1, got {inst['current_step_order']}"
    )

    events, meta = validate_paginated(
        api_client.list_events(tid, iid, admin, params={"action": "RETURN"})
    )
    assert meta["total_count"] == 1
    assert events[0]["step_order"] == 2
    assert events[0]["comment"] == "revise", "RETURN requires a comment"

    approvals, meta = validate_paginated(
        api_client.list_events(tid, iid, admin, params={"action": "APPROVE"})
    )
    assert meta["total_count"] == 1 and approvals[0]["step_order"] == 1, (
        "the first traversal's APPROVE event must survive the loop"
    )

    returned = list_notifications(
        tid, admin, notification_kind="RETURNED",
        recipient_worker_id=ctx["initiator"]["id"],
    )
    assert len(returned) == 1, "the initiator must receive a RETURNED notification"


def test_return_cycle_retraversal_completes(api):
    """PRD §3.6: "The instance must then re-traverse forward."
    PRD §3.6: "When no further step pends, the instance completes —
    `IN_PROGRESS` to `COMPLETED`".
    PRD §3.6: "The instance's `current_step_order` tracks the currently pending
    step and reads 0 when no step is pending."

    Design: Difficulty/non_linear_state_machine/transaction_return_cycle_preserves_history
    """
    ctx, iid = _returned_instance()
    tid, admin = ctx["tenant"]["id"], ctx["admin"]
    approver = approver_as(ctx["approver"]["id"])

    get_success_data(api_client.approve_step(tid, iid, 1, {}, approver))
    result = get_success_data(api_client.approve_step(tid, iid, 2, {}, approver))
    assert result["status"] == "COMPLETED", (
        "the cycle is re-entrant: re-approving steps 1 and 2 must complete"
    )
    assert result["current_step_order"] == 0

    approvals, meta = validate_paginated(
        api_client.list_events(tid, iid, admin, params={"action": "APPROVE"})
    )
    assert meta["total_count"] == 3, (
        "three approvals happened (step 1 twice across the loop, step 2 once)"
    )


def _manual_running_run():
    """Tenant with an ACTIVE SCHEDULED connector and one MANUAL run
    (dispatched to RUNNING within the create request)."""
    tenant = create_tenant("T-NL2")
    set_clock("2026-09-02T00:00:00Z")
    connector = create_active_connector(tenant["id"], "C1")
    run = create_run(tenant["id"], connector["id"], "MANUAL")
    return tenant, connector, run


def test_run_retry_cycle_to_limit(api):
    """PRD §3.8: "A `MANUAL` run bypasses the blackout window and dispatches
    immediately, transitioning from `QUEUED` to `RUNNING` within the same
    request".
    PRD §3.8: "Failure moves the run to `FAILED`, from which a retry returns it
    to `RUNNING` and increments `attempt_count` by 1 — retries are capped at 3
    attempts total, so a retry when `attempt_count` has already reached 3 is
    rejected with `ERR_RETRY_LIMIT_EXCEEDED` (HTTP 409)."
    PRD §3.8: "Runs begin `QUEUED` with an `attempt_count` of 1 and
    `records_processed` of 0."

    Design: Difficulty/non_linear_state_machine/integration_run_failed_running_retry_cycle
    """
    from test_helpers import dev_headers

    tenant, connector, run = _manual_running_run()
    tid, cid, rid = tenant["id"], connector["id"], run["id"]
    headers = dev_headers()

    assert run["status"] == "RUNNING"
    assert run["attempt_count"] == 1
    assert run["records_processed"] == 0

    get_success_data(api_client.fail_run(tid, cid, rid, headers))
    run = get_success_data(api_client.retry_run(tid, cid, rid, headers))
    assert run["status"] == "RUNNING" and run["attempt_count"] == 2

    get_success_data(api_client.fail_run(tid, cid, rid, headers))
    run = get_success_data(api_client.retry_run(tid, cid, rid, headers))
    assert run["status"] == "RUNNING" and run["attempt_count"] == 3

    get_success_data(api_client.fail_run(tid, cid, rid, headers))
    resp = api_client.retry_run(tid, cid, rid, headers)
    validate_error(resp, ApiErrorId.ERR_RETRY_LIMIT_EXCEEDED)

    run = get_success_data(api_client.get_run_flat(rid, headers))
    assert run["attempt_count"] == 3, "the rejected retry must not increment"


def test_run_dead_letter_terminal(api):
    """PRD §3.8: "A `FAILED` run can also be dead-lettered explicitly, and the
    system dead-letters automatically when the third attempt is exhausted;
    `DEAD_LETTERED` is terminal alongside `SUCCEEDED`."

    Design: Difficulty/non_linear_state_machine/integration_run_failed_running_retry_cycle
    """
    from test_helpers import dev_headers

    tenant, connector, run = _manual_running_run()
    tid, cid, rid = tenant["id"], connector["id"], run["id"]
    headers = dev_headers()

    run = get_success_data(api_client.fail_run(tid, cid, rid, headers))
    assert run["status"] == "FAILED"

    run = get_success_data(api_client.dead_letter_run(tid, cid, rid, headers))
    assert run["status"] == "DEAD_LETTERED"

    # Terminal: no transition leaves DEAD_LETTERED.
    resp = api_client.retry_run(tid, cid, rid, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    run = get_success_data(api_client.get_run_flat(rid, headers))
    assert run["status"] == "DEAD_LETTERED"
    assert run["attempt_count"] == 1
