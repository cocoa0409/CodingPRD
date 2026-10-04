"""Corner queue B: state machines — transitions, lockdown, scheduled activation."""
from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    admin_of,
    approver_as,
    dev_headers,
    op_headers,
    ApiErrorId,
    activate_definition,
    add_step,
    create_active_connector,
    create_active_unit,
    create_definition,
    create_group_with_member,
    create_prod_sandbox_pair,
    create_tenant,
    create_weekly_train,
    create_worker,
    get_tenant,
    get_train,
    initiate,
    list_notifications,
    plan_refresh,
    run_refresh_to,
    set_clock,
    setup_active_definition,
)


def test_weekly_train_skips_opt_in_and_acknowledge(api):
    """PRD §3.7: "A `WEEKLY_SERVICE` train skips opt-in entirely, moving
    straight from `ANNOUNCED` to `MANDATORY_LIVE`, applied at each tenant's
    maintenance slot: tenants with `weekly_update_auto_apply` true have their
    `code_version` advanced, while others retain their prior version until the
    acknowledgement flow of §3.1."
    PRD §3.1: "Acknowledgement advances `code_version` to the platform's
    current weekly version and increments the tenant's `version` by 1."

    Design: Corner/state_machines/release_train_weekly_skips_opt_in
    """
    auto = create_tenant("T-WA")
    manual = create_tenant("T-WM", weekly_update_auto_apply=False)
    cv_auto0, cv_manual0 = auto["code_version"], manual["code_version"]
    train = create_weekly_train("W37", "2026-09-05T00:00:00Z")

    set_clock("2026-09-06T03:00:00Z")  # past mandatory date and the 02:00 slot

    train = get_train(train["id"])
    assert train["status"] == "MANDATORY_LIVE", (
        "WEEKLY_SERVICE trains skip OPT_IN_OPEN/OPT_IN_CLOSED entirely"
    )

    auto = get_tenant(auto["id"])
    manual = get_tenant(manual["id"])
    assert auto["code_version"] != cv_auto0, "auto-apply tenant advances"
    assert manual["code_version"] == cv_manual0, "opt-out tenant queues the update"

    manual = get_success_data(
        api_client.acknowledge_weekly_update(manual["id"], admin_of(manual))
    )
    assert manual["code_version"] == auto["code_version"], (
        "acknowledgement advances to the platform's current weekly version"
    )


def test_completed_transaction_rejects_cancel(api):
    """PRD §3.6: "Cancellation moves an instance from `IN_PROGRESS` to
    `CANCELLED` and accepts no further step events."
    PRD §2.7: "6. Target state — the entity being acted on is in a state that
    permits the requested transition, else `ERR_INVALID_STATE`."

    Design: Corner/state_machines/terminal_state_lockdown_completed_transaction
    """
    ctx = setup_active_definition("T-SM2", steps=[{"order": 1}])
    tid, admin = ctx["tenant"]["id"], ctx["admin"]
    inst = initiate(ctx)
    result = get_success_data(
        api_client.approve_step(tid, inst["id"], 1, {},
                                approver_as(ctx["approver"]["id"]))
    )
    assert result["status"] == "COMPLETED"

    resp = api_client.cancel_transaction(tid, inst["id"], admin)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    inst = get_success_data(api_client.get_transaction(tid, inst["id"], admin))
    assert inst["status"] == "COMPLETED"


def test_org_unit_auto_activates_at_effective_date(api):
    """PRD §3.3: "A unit is born `PROPOSED` and activates automatically — with
    no API call — when the logical clock reaches its `effective_date`, provided
    its parent is null or already `ACTIVE`."
    PRD §3.3: "Workers are created with a `worker_ref` unique per tenant, a
    `full_name`, an `org_unit_id` that must reference an `ACTIVE` unit at
    assignment time".

    Design: Corner/state_machines/org_unit_auto_activation_at_effective_date
    """
    tenant = create_tenant("T-SM3")
    admin = admin_of(tenant)
    tid = tenant["id"]
    set_clock("2026-09-02T00:00:00Z")

    unit = get_success_data(api_client.create_org_unit(
        tid,
        {"unit_name": "U1", "unit_type": "TEAM",
         "effective_date": "2026-09-10T00:00:00Z"},
        admin,
    ), 201)
    assert unit["status"] == "PROPOSED"

    resp = api_client.create_worker(
        tid,
        {"worker_ref": "W1", "full_name": "Early", "org_unit_id": unit["id"],
         "hire_date": "2026-09-02T00:00:00Z"},
        admin,
    )
    assert resp.status_code >= 400, "a PROPOSED unit cannot accept workers"
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_INVALID_REQUEST]
    )

    set_clock("2026-09-10T00:00:00Z")  # reaches effective_date
    unit = get_success_data(api_client.get_org_unit(tid, unit["id"], admin))
    assert unit["status"] == "ACTIVE", "the unit activates with no API call"

    worker = get_success_data(api_client.create_worker(
        tid,
        {"worker_ref": "W1", "full_name": "Early", "org_unit_id": unit["id"],
         "hire_date": "2026-09-10T00:00:00Z"},
        admin,
    ), 201)
    assert worker["status"] == "ACTIVE"


def test_suspend_blocked_while_refresh_planned(api):
    """PRD §3.2: "When a `PlatformOperator` suspends a tenant, the request is
    refused with `ERR_REFRESH_IN_FLIGHT` (HTTP 409) if any refresh job
    involving this tenant — whether as source or as target — is currently
    `PLANNED` or `RUNNING`."

    Design: Corner/state_machines/tenant_suspend_blocked_by_refresh_in_flight
    """
    src, tgt = create_prod_sandbox_pair("T-S4S", "T-S4T")
    set_clock("2026-09-02T00:00:00Z")
    plan_refresh(tgt, src["id"], "2026-09-05T02:00:00Z")

    resp = api_client.suspend_tenant(tgt["id"], op_headers())
    validate_error(resp, ApiErrorId.ERR_REFRESH_IN_FLIGHT)
    assert get_tenant(tgt["id"])["status"] == "ACTIVE"


def test_failed_refresh_leaves_target_untouched(api):
    """PRD §3.9: "Failing a `RUNNING` job leaves the target's configuration
    untouched — refresh is all-or-nothing".

    Design: Corner/state_machines/refresh_failure_leaves_target_config_atomic
    """
    src, tgt = create_prod_sandbox_pair("T-S5S", "T-S5T")
    src_admin = admin_of(src)
    group = create_group_with_member(
        src["id"], "G", src["bootstrap_admin_worker_id"], src_admin,
    )
    definition = create_definition(src["id"], src_admin,
                                   transaction_type="EXPENSE", name="SrcFlow")
    add_step(src["id"], definition["id"], 1, src_admin, group_id=group["id"])
    activate_definition(src["id"], definition["id"], src_admin)

    job = plan_refresh(tgt, src["id"], "2026-09-02T02:00:00Z")
    failed = run_refresh_to(tgt, job["id"], "fail",
                            advance_clock_to="2026-09-02T02:30:00Z")
    assert failed["status"] == "FAILED"

    defs, meta = validate_paginated(
        api_client.list_definitions(tgt["id"], admin_of(tgt))
    )
    assert meta["total_count"] == 0, (
        "a failed refresh applies zero configuration to the target"
    )


def test_completed_refresh_enqueues_event_run_and_notification(api):
    """PRD §3.9: "Completion then enqueues a run with trigger source `EVENT`
    on every `ACTIVE` `EVENT_DRIVEN` connector of the target tenant subscribed
    to `REFRESH_COMPLETED`, and sends a `REFRESH_COMPLETED` notification to the
    target tenant's administrators."

    Design: Corner/state_machines/refresh_completed_fires_event_driven_connector
    """
    src, tgt = create_prod_sandbox_pair("T-S6S", "T-S6T")
    connector = create_active_connector(
        tgt["id"], "CEV", trigger_mode="EVENT_DRIVEN",
        subscribed_event="REFRESH_COMPLETED",
    )
    job = plan_refresh(tgt, src["id"], "2026-09-02T02:00:00Z")
    completed = run_refresh_to(tgt, job["id"], "complete",
                               advance_clock_to="2026-09-02T02:30:00Z")
    assert completed["status"] == "COMPLETED"

    runs, meta = validate_paginated(
        api_client.list_runs(tgt["id"], connector["id"], dev_headers())
    )
    assert meta["total_count"] >= 1
    assert any(r["trigger_source"] == "EVENT" for r in runs)

    notifications = list_notifications(
        tgt["id"], admin_of(tgt), notification_kind="REFRESH_COMPLETED",
    )
    assert len(notifications) >= 1


def test_completed_transaction_enqueues_event_run(api):
    """PRD §3.6: "When no further step pends, the instance completes —
    `IN_PROGRESS` to `COMPLETED` — and every `EVENT_DRIVEN` connector of the
    tenant that is `ACTIVE` and subscribed to `TRANSACTION_COMPLETED` enqueues
    a run with trigger source `EVENT`."

    Design: Corner/state_machines/transaction_completion_fires_event_driven_connector
    """
    ctx = setup_active_definition("T-S7", steps=[{"order": 1}])
    tid = ctx["tenant"]["id"]
    connector = create_active_connector(
        tid, "CTX", trigger_mode="EVENT_DRIVEN",
        subscribed_event="TRANSACTION_COMPLETED",
    )
    inst = initiate(ctx)
    result = get_success_data(
        api_client.approve_step(tid, inst["id"], 1, {},
                                approver_as(ctx["approver"]["id"]))
    )
    assert result["status"] == "COMPLETED"

    runs, meta = validate_paginated(
        api_client.list_runs(tid, connector["id"], dev_headers())
    )
    assert meta["total_count"] >= 1
    assert any(r["trigger_source"] == "EVENT" for r in runs)
