"""Printer setup, material batch, site suspend cascades, and trade tasks
(PRD §3.2, §3.4, §3.5, §3.10)."""
from test_helpers import (
    ApiErrorId,
    PRINT_OP,
    SITE_MGR,
    TRADE_CON,
    assert_material_batch,
    assert_printer_setup,
    assert_trade_task,
    complete_print_job,
    create_and_qualify_printer,
    create_jurisdiction,
    create_material_batch_payload,
    create_printing_job,
    create_printer_setup_payload,
    create_qualified_batch,
    create_site,
    create_trade_task_payload,
    current_site_version,
    get_success_data,
    pour_and_cure_foundation,
    schedule_print_job,
    set_clock,
    setup_site_ready_for_print,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_printer_qualify_blocked_when_leveling_out_of_tolerance(api):
    """PRD §3.4: "Advancing further from `LEVELED` to `QUALIFIED` requires
    `is_within_tolerance` to be true (otherwise the request is rejected with
    `ERR_LEVELING_OUT_OF_TOLERANCE`)".

    Design: Corner/endpoints/printer_qualify_blocked_when_leveling_out_of_tolerance
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(code="JQ2")
    site = create_site(jurisdiction["id"], address="17 K")
    pour_and_cure_foundation(site["id"], "2026-09-01T00:00:00Z", "2026-09-04T00:00:00Z")
    version = current_site_version(site["id"])
    setup = get_success_data(
        api.create_printer_setup(
            site["id"],
            create_printer_setup_payload(
                version, leveling_tolerance_mm=5.0, measured_level_deviation_mm=7.0
            ),
            PRINT_OP,
        )
    )
    assert setup["is_within_tolerance"] is False
    get_success_data(
        api.advance_printer_setup(site["id"], setup["id"], {"to_state": "LEVELED"}, PRINT_OP)
    )
    resp = api.advance_printer_setup(site["id"], setup["id"], {"to_state": "QUALIFIED"}, PRINT_OP)
    validate_error(resp, ApiErrorId.ERR_LEVELING_OUT_OF_TOLERANCE)
    setups, _m = validate_paginated(api.list_printer_setups(site["id"], PRINT_OP))
    current = next(s for s in setups if s["id"] == setup["id"])
    assert current["status"] == "LEVELED", "rejected qualify must leave the setup LEVELED"


def test_printer_qualify_blocked_before_foundation_cured(api):
    """PRD §3.4: the LEVELED → QUALIFIED advance requires "the site's `status`
    to be `FOUNDATION_CURED` or `SITE_READY` (otherwise
    `ERR_FOUNDATION_NOT_CURED`)."

    Design: Corner/endpoints/printer_qualify_blocked_when_leveling_out_of_tolerance
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(code="JQ3")
    site = create_site(jurisdiction["id"], address="17 KB")
    get_success_data(api.site_action(site["id"], {"action": "POUR_FOUNDATION"}, SITE_MGR))
    # Clock only +1h: foundation not yet cured (72h window).
    set_clock("2026-09-01T01:00:00Z")
    version = current_site_version(site["id"])
    setup = get_success_data(
        api.create_printer_setup(site["id"], create_printer_setup_payload(version), PRINT_OP)
    )
    get_success_data(
        api.advance_printer_setup(site["id"], setup["id"], {"to_state": "LEVELED"}, PRINT_OP)
    )
    resp = api.advance_printer_setup(site["id"], setup["id"], {"to_state": "QUALIFIED"}, PRINT_OP)
    validate_error(resp, ApiErrorId.ERR_FOUNDATION_NOT_CURED)


def test_printer_qualify_cascades_site_to_ready(api):
    """PRD §3.2: "the first `PrinterSetup` on the site to reach `QUALIFIED`
    cascades the site from `FOUNDATION_CURED` to `SITE_READY`."

    Design: Corner/endpoints/printer_qualify_blocked_when_leveling_out_of_tolerance
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(code="JQ4")
    site = create_site(jurisdiction["id"], address="17 KC")
    pour_and_cure_foundation(site["id"], "2026-09-01T00:00:00Z", "2026-09-04T00:00:00Z")
    setup = create_and_qualify_printer(site["id"])
    assert setup["status"] == "QUALIFIED"
    site_now = get_success_data(api.get_site(site["id"], PRINT_OP))
    assert site_now["status"] == "SITE_READY"


def test_batch_qualify_requires_pumpable(api):
    """PRD §3.5: "Qualifying a batch (`PROPORTIONED` → `QUALIFIED`) requires
    `is_pumpable` to be true — a non-pumpable batch is rejected with
    `ERR_BATCH_NOT_PUMPABLE`."

    Design: Corner/endpoints/printer_qualify_blocked_when_leveling_out_of_tolerance
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(code="JQ5")
    site = create_site(jurisdiction["id"], address="17 KD")
    pour_and_cure_foundation(site["id"], "2026-09-01T00:00:00Z", "2026-09-04T00:00:00Z")
    # LAVACRETE_A pump window is [40, 60]; 70 is above the window.
    batch = get_success_data(
        api.create_material_batch(
            site["id"],
            create_material_batch_payload(mix_code="LAVACRETE_A",
                                          pump_consistency_kg_per_min=70),
            PRINT_OP,
        )
    )
    assert_material_batch(batch)
    assert batch["is_pumpable"] is False
    resp = api.qualify_material_batch(site["id"], batch["id"], PRINT_OP)
    validate_error(resp, ApiErrorId.ERR_BATCH_NOT_PUMPABLE)


def test_batch_pump_window_boundary_inclusive(api):
    """PRD §3.5: "for `LAVACRETE_A` the window is 40 to 60 kg/min" and "both
    endpoints are inclusive".

    Design: Corner/endpoints/printer_qualify_blocked_when_leveling_out_of_tolerance
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(code="JQ6")
    site = create_site(jurisdiction["id"], address="17 KE")
    pour_and_cure_foundation(site["id"], "2026-09-01T00:00:00Z", "2026-09-04T00:00:00Z")
    batch = get_success_data(
        api.create_material_batch(
            site["id"],
            create_material_batch_payload(mix_code="LAVACRETE_A",
                                          pump_consistency_kg_per_min=40),
            PRINT_OP,
        )
    )
    assert batch["pump_window_kg_per_min"][0] == 40
    assert batch["pump_window_kg_per_min"][1] == 60
    assert batch["is_pumpable"] is True, "pump consistency at the window minimum is pumpable"


def test_confirm_cure_before_window_rejected(api):
    """PRD §3.2: "Attempting to confirm before the cure window has elapsed is
    rejected with `ERR_FOUNDATION_NOT_CURED`."

    Design: Corner/endpoints/printer_qualify_blocked_when_leveling_out_of_tolerance
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(code="JQ7")
    site = create_site(jurisdiction["id"], address="17 KF")
    get_success_data(api.site_action(site["id"], {"action": "POUR_FOUNDATION"}, SITE_MGR))
    set_clock("2026-09-03T00:00:00Z")  # 48h < 72h cure window
    resp = api.site_action(site["id"], {"action": "CONFIRM_CURE"}, SITE_MGR)
    validate_error(resp, ApiErrorId.ERR_FOUNDATION_NOT_CURED)


def test_site_suspend_cascades_prints_trades_permits(api, platform_admin_headers):
    """PRD §3.2: "Suspension cascades: any print job still in `SCHEDULED` or
    `READY_TO_PRINT` moves to `CANCELLED`; any conventional trade task in
    `PLANNED` or `READY` moves to `CANCELLED`; and any permit application in
    `DRAFT`, `SUBMITTED`, or `AM_REVIEW` moves to `WITHDRAWN`."

    Design: Difficulty/transitive_cascade/site_suspend_cascades_prints_trades_permits
    """
    from test_helpers import PERMIT_COORD, create_permit_application_payload

    ctx = setup_site_ready_for_print(jurisdiction_code="JS")
    site_id = ctx["site"]["id"]
    job = schedule_print_job(
        ctx, scheduled_start_at="2026-09-05T08:00:00Z", scheduled_end_at="2026-09-05T16:00:00Z"
    )
    version = current_site_version(site_id)
    task = get_success_data(
        api.create_trade_task(site_id, create_trade_task_payload(job["id"], version), SITE_MGR)
    )
    # A second permit application left in DRAFT (the first is APPROVED and
    # terminal, hence not cascaded).
    app2 = get_success_data(
        api.create_permit_application(
            site_id, create_permit_application_payload(ctx["revision"]["id"]), PERMIT_COORD
        )
    )
    site = validate_success(
        api.site_action(site_id, {"action": "SUSPEND"}, platform_admin_headers)
    )
    assert site["status"] == "SUSPENDED"
    jobs, _m = validate_paginated(api.list_print_jobs(site_id, PRINT_OP))
    assert next(j for j in jobs if j["id"] == job["id"])["status"] == "CANCELLED"
    tasks, _m = validate_paginated(api.list_trade_tasks(site_id, SITE_MGR))
    assert next(t for t in tasks if t["id"] == task["id"])["status"] == "CANCELLED"
    app2_now = get_success_data(api.get_permit_application(site_id, app2["id"], PERMIT_COORD))
    assert app2_now["status"] == "WITHDRAWN"


def test_site_suspend_blocked_while_printing(api, platform_admin_headers):
    """PRD §3.2: "A `PlatformAdmin` may suspend a site from `REGISTERED`,
    `FOUNDATION_POURED`, `FOUNDATION_CURED`, or `SITE_READY`, provided no print
    job on the site is currently `PRINTING` or `PAUSED`." A suspend attempted
    while a job is `PRINTING` has no legal from-state (`ERR_INVALID_STATE`,
    PRD §2.11 item 8).

    Design: Difficulty/transitive_cascade/site_suspend_cascades_prints_trades_permits
    """
    ctx = setup_site_ready_for_print(jurisdiction_code="JS2")
    job = create_printing_job(ctx)
    assert job["status"] == "PRINTING"
    resp = api.site_action(ctx["site"]["id"], {"action": "SUSPEND"}, platform_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_trade_task_start_gated_on_print_completed(api):
    """PRD §3.10: "A task transitions from `PLANNED` to `READY` automatically
    the moment its dependencies are satisfied, re-evaluated on every dependency
    change." Starting requires the task to be READY first; a start on a
    `PLANNED` task violates state-machine legality (PRD §2.11 item 8,
    `ERR_INVALID_STATE`).

    Design: Difficulty/cross_entity_state_dependency/trade_task_start_gated_on_print_completed
    """
    ctx = setup_site_ready_for_print(jurisdiction_code="JT")
    site_id = ctx["site"]["id"]
    job = create_printing_job(ctx)  # PRINTING, not COMPLETED
    version = current_site_version(site_id)
    task = get_success_data(
        api.create_trade_task(
            site_id,
            create_trade_task_payload(
                job["id"], version, earliest_start_at="2026-09-04T08:00:00Z"
            ),
            SITE_MGR,
        )
    )
    assert task["status"] == "PLANNED"
    resp = api.transition_trade_task(site_id, task["id"], {"to_state": "IN_PROGRESS"}, TRADE_CON)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    jobs, _m = validate_paginated(api.list_print_jobs(site_id, PRINT_OP))
    assert next(j for j in jobs if j["id"] == job["id"])["status"] == "PRINTING"


def test_trade_task_auto_ready_when_dependencies_satisfied(api):
    """PRD §3.10: "A task transitions from `PLANNED` to `READY` automatically
    the moment its dependencies are satisfied, re-evaluated on every dependency
    change." — after the depended-upon print job completes, the task is READY.

    Design: Difficulty/cross_entity_state_dependency/trade_task_start_gated_on_print_completed
    """
    ctx = setup_site_ready_for_print(jurisdiction_code="JT3")
    site_id = ctx["site"]["id"]
    job = create_printing_job(ctx)
    version = current_site_version(site_id)
    task = get_success_data(
        api.create_trade_task(
            site_id,
            create_trade_task_payload(
                job["id"], version,
                earliest_start_at="2026-09-04T08:00:00Z",
                latest_end_at="2026-09-10T16:00:00Z",
            ),
            SITE_MGR,
        )
    )
    assert task["status"] == "PLANNED"
    complete_print_job(ctx, job["id"], clock_at="2026-09-04T09:00:00Z")
    tasks, _m = validate_paginated(api.list_trade_tasks(site_id, SITE_MGR))
    current = next(t for t in tasks if t["id"] == task["id"])
    assert current["status"] == "READY", (
        "completing the depended-upon print job must auto-transition the task to READY"
    )


def test_trade_task_start_too_early_returns_trade_too_early(api):
    """PRD §3.10: "Starting work (`READY` → `IN_PROGRESS`) is a
    `TradeContractor` action requiring the logical clock to be at or past
    `earliest_start_at` (a too-early start is rejected with
    `ERR_TRADE_TOO_EARLY`)".

    Design: Corner/endpoints/trade_task_start_too_early_returns_trade_too_early
    """
    ctx = setup_site_ready_for_print(jurisdiction_code="JE")
    site_id = ctx["site"]["id"]
    job = create_printing_job(ctx)
    complete_print_job(ctx, job["id"], clock_at="2026-09-04T09:00:00Z")
    version = current_site_version(site_id)
    task = get_success_data(
        api.create_trade_task(
            site_id,
            create_trade_task_payload(
                job["id"],
                version,
                earliest_start_at="2026-09-04T10:00:00Z",
                latest_end_at="2026-09-10T16:00:00Z",
            ),
            SITE_MGR,
        )
    )
    # The task's non-clock dependencies are satisfied at create time; only the
    # earliest_start_at clock gate keeps it PLANNED (TOO_EARLY blocker).
    assert task["status"] == "PLANNED"
    set_clock("2026-09-04T09:30:00Z")
    resp = api.transition_trade_task(site_id, task["id"], {"to_state": "IN_PROGRESS"}, TRADE_CON)
    validate_error(resp, ApiErrorId.ERR_TRADE_TOO_EARLY)
    tasks, _m = validate_paginated(api.list_trade_tasks(site_id, SITE_MGR))
    assert next(t for t in tasks if t["id"] == task["id"])["status"] == "READY"


def test_trade_task_full_chain_start_and_complete(api):
    """PRD §3.10: "Starting work (`READY` → `IN_PROGRESS`)" and "Completing
    (`IN_PROGRESS` → `COMPLETED`) requires the logical clock to be at or before
    `latest_end_at`" and "stamps `actual_end_at`". PRD §2.7: "Whenever this
    document describes a comparison as inclusive (at least, at most, no later
    than, no earlier than), the boundary value satisfies the check."

    Design: Corner/endpoints/trade_task_start_too_early_returns_trade_too_early
    """
    ctx = setup_site_ready_for_print(jurisdiction_code="JE2")
    site_id = ctx["site"]["id"]
    job = create_printing_job(ctx)
    complete_print_job(ctx, job["id"], clock_at="2026-09-04T09:00:00Z")
    version = current_site_version(site_id)
    task = get_success_data(
        api.create_trade_task(
            site_id,
            create_trade_task_payload(
                job["id"],
                version,
                earliest_start_at="2026-09-04T10:00:00Z",
                latest_end_at="2026-09-10T16:00:00Z",
            ),
            SITE_MGR,
        )
    )
    assert_trade_task(task)
    set_clock("2026-09-04T10:00:00Z")  # boundary: at earliest_start_at, inclusive
    started = validate_success(
        api.transition_trade_task(site_id, task["id"], {"to_state": "IN_PROGRESS"}, TRADE_CON)
    )
    assert started["status"] == "IN_PROGRESS"
    assert started["actual_start_at"] is not None
    set_clock("2026-09-10T16:00:00Z")  # boundary: at latest_end_at, inclusive
    completed = validate_success(
        api.transition_trade_task(site_id, task["id"], {"to_state": "COMPLETED"}, TRADE_CON)
    )
    assert completed["status"] == "COMPLETED"
    assert completed["actual_end_at"] is not None
