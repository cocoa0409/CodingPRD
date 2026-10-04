"""Deployment waves: release gates, half-open window overlap, ship windows,
the shortage freeze, drop-ship quantity checks, and receipt settlement."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_account,
    create_chassis,
    create_component,
    add_allowed_rule,
    create_validated_configuration,
    create_order_with_lines,
    create_wave_payload,
    get_order_build_jobs,
    setup_submitted_order,
    setup_built_order,
    setup_shortage_blocked_order,
    submit_order,
    make_customer_user_headers,
    get_success_data,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["account_manager_headers"]
OPS = TEST_USERS["factory_ops_headers"]


def test_wave_window_adjacency_end_equals_start(api):
    """PRD §3.7: "Wave windows of one order must not collide: at both planning
    time and release time, a new or releasing wave whose half-open window
    intersects another live wave of the same order — live meaning `PLANNED`,
    `RELEASED`, or `SHIPPED` — is rejected with `ERR_WAVE_WINDOW_OVERLAP`
    (HTTP 422), while two waves that merely touch, one's end equalling the
    other's start, do not overlap and are permitted."

    Design: Difficulty/boundary_precision_check/wave_window_adjacency_end_equals_start
    """
    account = create_account(company_name="A13", credit_limit_cents=20_000_000)
    chassis = create_chassis(model_code="L13", base_price_cents=50_000)
    wif = create_component(sku="WIF13", kind="WIFI", price_cents=2_000, lead_time_days=2)
    add_allowed_rule(chassis["id"], wif["id"])
    config = create_validated_configuration(account, chassis["id"],
                                            [{"component_id": wif["id"], "qty": 1}])
    order, _ = create_order_with_lines(
        account,
        [{"configuration_id": config["id"], "qty": 2, "ship_to_mode": "DROP_SHIP_EMPLOYEES"}],
        po_number="PO-13",
    )
    submit_order(account, order, config["version"])
    w1 = get_success_data(api.create_deployment_wave(
        order["id"],
        create_wave_payload(
            wave_label="W1",
            ship_window_start="2026-09-05T00:00:00Z",
            ship_window_end="2026-09-10T00:00:00Z",
            destinations=[{"employee_ref": "E1", "address": "1 A St", "units": 1}],
        ),
        MANAGER,
    ))
    assert w1["status"] == "PLANNED"
    # Adjacent: W2 starts exactly at W1's end — permitted.
    resp = api.create_deployment_wave(
        order["id"],
        create_wave_payload(
            wave_label="W2",
            ship_window_start="2026-09-10T00:00:00Z",
            ship_window_end="2026-09-15T00:00:00Z",
            destinations=[{"employee_ref": "E2", "address": "2 B St", "units": 1}],
        ),
        MANAGER,
    )
    validate_success(resp, 201)
    # One second of overlap — rejected.
    resp = api.create_deployment_wave(
        order["id"],
        create_wave_payload(
            wave_label="W3",
            ship_window_start="2026-09-09T23:59:59Z",
            ship_window_end="2026-09-12T00:00:00Z",
            destinations=[{"employee_ref": "E3", "address": "3 C St", "units": 1}],
        ),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_WAVE_WINDOW_OVERLAP.value, 422)


def test_wave_window_one_second_inside_rejected(api):
    """PRD §3.7: "Wave windows of one order must not collide: at both planning
    time and release time, a new or releasing wave whose half-open window
    intersects another live wave of the same order — live meaning `PLANNED`,
    `RELEASED`, or `SHIPPED` — is rejected with `ERR_WAVE_WINDOW_OVERLAP`
    (HTTP 422), while two waves that merely touch, one's end equalling the
    other's start, do not overlap and are permitted."

    Design: Difficulty/boundary_precision_check/wave_window_adjacency_end_equals_start
    """
    account = create_account(credit_limit_cents=20_000_000)
    chassis = create_chassis()
    cpu = create_component()
    add_allowed_rule(chassis["id"], cpu["id"])
    config = create_validated_configuration(account, chassis["id"],
                                            [{"component_id": cpu["id"], "qty": 1}])
    order, _ = create_order_with_lines(
        account,
        [{"configuration_id": config["id"], "qty": 2, "ship_to_mode": "DROP_SHIP_EMPLOYEES"}],
    )
    submit_order(account, order, config["version"])
    api.create_deployment_wave(
        order["id"],
        create_wave_payload(
            ship_window_start="2026-09-05T00:00:00Z",
            ship_window_end="2026-09-10T00:00:00Z",
            destinations=[{"employee_ref": "E1", "address": "1 A St", "units": 1}],
        ),
        MANAGER,
    )
    resp = api.create_deployment_wave(
        order["id"],
        create_wave_payload(
            ship_window_start="2026-09-09T23:59:59Z",
            ship_window_end="2026-09-12T00:00:00Z",
            destinations=[{"employee_ref": "E2", "address": "2 B St", "units": 1}],
        ),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_WAVE_WINDOW_OVERLAP.value, 422)


def test_wave_half_open_window_overlap_rejected(api):
    """PRD §3.7: "Wave windows of one order must not collide: at both planning
    time and release time, a new or releasing wave whose half-open window
    intersects another live wave of the same order — live meaning `PLANNED`,
    `RELEASED`, or `SHIPPED` — is rejected with `ERR_WAVE_WINDOW_OVERLAP`
    (HTTP 422), while two waves that merely touch, one's end equalling the
    other's start, do not overlap and are permitted."

    Design: Difficulty/resource_temporal_overlap/wave_half_open_window_overlap_rejected
    """
    account = create_account(company_name="A17", credit_limit_cents=20_000_000)
    chassis = create_chassis(model_code="L17", base_price_cents=50_000)
    nic = create_component(sku="NIC17", kind="NIC", price_cents=2_000, lead_time_days=2)
    add_allowed_rule(chassis["id"], nic["id"])
    config = create_validated_configuration(account, chassis["id"],
                                            [{"component_id": nic["id"], "qty": 1}])
    order, _ = create_order_with_lines(
        account,
        [{"configuration_id": config["id"], "qty": 3, "ship_to_mode": "DROP_SHIP_EMPLOYEES"}],
        po_number="PO-17",
    )
    submit_order(account, order, config["version"])
    api.create_deployment_wave(
        order["id"],
        create_wave_payload(
            wave_label="WA",
            ship_window_start="2026-09-05T00:00:00Z",
            ship_window_end="2026-09-10T00:00:00Z",
            destinations=[{"employee_ref": "EA", "address": "1 A St", "units": 1}],
        ),
        MANAGER,
    )
    # WB's start falls strictly inside WA's window.
    resp = api.create_deployment_wave(
        order["id"],
        create_wave_payload(
            wave_label="WB",
            ship_window_start="2026-09-09T00:00:00Z",
            ship_window_end="2026-09-20T00:00:00Z",
            destinations=[{"employee_ref": "EB", "address": "2 B St", "units": 1}],
        ),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_WAVE_WINDOW_OVERLAP.value, 422)
    waves = get_success_data(api.list_order_waves(order["id"], MANAGER))
    assert len(waves) == 1
    assert waves[0]["status"] == "PLANNED"


def test_wave_enclosing_window_overlap_rejected(api):
    """PRD §3.7: "Wave windows of one order must not collide: at both planning
    time and release time, a new or releasing wave whose half-open window
    intersects another live wave of the same order — live meaning `PLANNED`,
    `RELEASED`, or `SHIPPED` — is rejected with `ERR_WAVE_WINDOW_OVERLAP`
    (HTTP 422), while two waves that merely touch, one's end equalling the
    other's start, do not overlap and are permitted."

    Design: Difficulty/resource_temporal_overlap/wave_half_open_window_overlap_rejected
    """
    account = create_account(credit_limit_cents=20_000_000)
    chassis = create_chassis()
    cpu = create_component()
    add_allowed_rule(chassis["id"], cpu["id"])
    config = create_validated_configuration(account, chassis["id"],
                                            [{"component_id": cpu["id"], "qty": 1}])
    order, _ = create_order_with_lines(
        account,
        [{"configuration_id": config["id"], "qty": 2, "ship_to_mode": "DROP_SHIP_EMPLOYEES"}],
    )
    submit_order(account, order, config["version"])
    api.create_deployment_wave(
        order["id"],
        create_wave_payload(
            ship_window_start="2026-09-05T00:00:00Z",
            ship_window_end="2026-09-10T00:00:00Z",
            destinations=[{"employee_ref": "E1", "address": "1 A St", "units": 1}],
        ),
        MANAGER,
    )
    # A wave fully enclosing the first also intersects it.
    resp = api.create_deployment_wave(
        order["id"],
        create_wave_payload(
            ship_window_start="2026-09-01T00:00:00Z",
            ship_window_end="2026-09-20T00:00:00Z",
            destinations=[{"employee_ref": "E2", "address": "2 B St", "units": 1}],
        ),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_WAVE_WINDOW_OVERLAP.value, 422)


def test_wave_release_requires_order_built(api):
    """PRD §3.7: "Two preconditions guard the release: the order's
    `build_status` must be `BUILT`, and the overlap rule above must hold
    against the order's other live waves."
    PRD §2.9: "then state-machine legality (the target resource is not in a
    state from which the requested transition is defined, `ERR_INVALID_STATE`)."

    Design: Difficulty/cross_entity_state_dependency/wave_release_requires_order_built
    """
    env = setup_submitted_order()
    job = env["jobs"][0]
    resp = api.allocate_build_job(job["id"], OPS)
    assert resp.status_code == 200
    resp = api.start_build_job(job["id"], OPS)
    assert resp.status_code == 200
    wave = get_success_data(api.create_deployment_wave(
        env["order"]["id"],
        create_wave_payload(
            wave_label="W15",
            ship_window_start="2026-09-03T00:00:00Z",
            ship_window_end="2026-09-08T00:00:00Z",
            destinations=[{"employee_ref": "HQ", "address": "9 Z St", "units": 1}],
        ),
        MANAGER,
    ))
    resp = api.release_wave(wave["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    order_after = get_success_data(api.get_order(env["order"]["id"], MANAGER))
    assert order_after["build_status"] == "IN_PRODUCTION"
    assert order_after["ship_status"] == "PENDING"
    waves = get_success_data(api.list_order_waves(env["order"]["id"], MANAGER))
    assert waves[0]["status"] == "PLANNED"


def test_wave_release_on_submitted_order_rejected(api):
    """PRD §3.7: "Two preconditions guard the release: the order's
    `build_status` must be `BUILT`, and the overlap rule above must hold
    against the order's other live waves."

    Design: Difficulty/cross_entity_state_dependency/wave_release_requires_order_built
    """
    env = setup_submitted_order()
    wave = get_success_data(api.create_deployment_wave(
        env["order"]["id"],
        create_wave_payload(
            ship_window_start="2026-09-03T00:00:00Z",
            ship_window_end="2026-09-08T00:00:00Z",
            destinations=[{"employee_ref": "HQ", "address": "9 Z St", "units": 1}],
        ),
        MANAGER,
    ))
    resp = api.release_wave(wave["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    order_after = get_success_data(api.get_order(env["order"]["id"], MANAGER))
    assert order_after["ship_status"] == "PENDING"


def test_ship_outside_window_rejected(api):
    """PRD §3.7: "The current logical clock must fall within the wave's
    half-open window — at or after `ship_window_start` and strictly before
    `ship_window_end`; a shipment attempted outside the window is rejected with
    `ERR_OUTSIDE_SHIP_WINDOW` (HTTP 422)."
    PRD §2.7: "At server startup the logical clock is initialized to exactly
    `2026-09-01T00:00:00Z` and the server must not fall back to wall-clock time
    under any circumstance."

    Design: Corner/state_machines/ship_outside_window_rejected
    """
    env = setup_built_order()
    wave = get_success_data(api.create_deployment_wave(
        env["order"]["id"],
        create_wave_payload(
            wave_label="W1",
            ship_window_start="2026-09-05T00:00:00Z",
            ship_window_end="2026-09-10T00:00:00Z",
            destinations=[{"employee_ref": "HQ", "address": "1 Main St", "units": 1}],
        ),
        MANAGER,
    ))
    resp = api.release_wave(wave["id"], MANAGER)
    validate_success(resp, 200)
    # Clock is still 2026-09-01, before the window opens.
    resp = api.ship_wave(wave["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_SHIP_WINDOW.value, 422)
    waves = get_success_data(api.list_order_waves(env["order"]["id"], MANAGER))
    assert waves[0]["status"] == "RELEASED"


def test_second_release_is_invalid_state(api):
    """PRD §2.9: "then state-machine legality (the target resource is not in a
    state from which the requested transition is defined, `ERR_INVALID_STATE`)."
    PRD §3.7: "Releasing a wave moves it from `PLANNED` to `RELEASED`."

    Design: Corner/state_machines/second_release_is_invalid_state
    """
    env = setup_built_order()
    wave = get_success_data(api.create_deployment_wave(
        env["order"]["id"],
        create_wave_payload(
            wave_label="W1",
            ship_window_start="2026-09-02T00:00:00Z",
            ship_window_end="2026-09-20T00:00:00Z",
            destinations=[{"employee_ref": "HQ", "address": "1 Main St", "units": 1}],
        ),
        MANAGER,
    ))
    resp = api.release_wave(wave["id"], MANAGER)
    validate_success(resp, 200)
    resp = api.release_wave(wave["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    waves = get_success_data(api.list_order_waves(env["order"]["id"], MANAGER))
    assert waves[0]["status"] == "RELEASED"


def test_wave_release_on_hold_order_rejected(api):
    """PRD §3.7: "Recall from §3.6 that while an order is `ON_HOLD` under a
    pending substitution, release — like shipment — is frozen with
    `ERR_SHORTAGE_PENDING`, and this state-priority freeze (priority 5) is
    evaluated before any wave-window business rule."

    Design: Corner/errors/wave_release_on_hold_order_rejected
    """
    env = setup_shortage_blocked_order()
    # Note: the wave is planned before the shortage is triggered in the design
    # recipe; planning is allowed pre-BUILT, release is frozen by the hold.
    wave = get_success_data(api.create_deployment_wave(
        env["order"]["id"],
        create_wave_payload(
            wave_label="W1",
            ship_window_start="2026-09-02T00:00:00Z",
            ship_window_end="2026-09-20T00:00:00Z",
            destinations=[{"employee_ref": "HQ", "address": "1 Main St", "units": 1}],
        ),
        MANAGER,
    ))
    resp = api.release_wave(wave["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_SHORTAGE_PENDING.value, 409)
    waves = get_success_data(api.list_order_waves(env["order"]["id"], MANAGER))
    assert waves[0]["status"] == "PLANNED"


def test_drop_ship_destination_sum_must_equal_qty(api):
    """PRD §3.4: "A line quantity below 1, or a drop-ship plan whose
    destination units do not sum exactly to the line quantity, is rejected
    with `ERR_INVALID_ORDER_QUANTITY` (HTTP 422) — the quantity check applies
    both when a line is added and when the order's deployment waves are
    planned."

    Design: Corner/endpoints/drop_ship_destination_sum_must_equal_qty
    """
    account = create_account(company_name="EE2")
    chassis = create_chassis(model_code="EEL2")
    cpu = create_component(sku="EEC2")
    add_allowed_rule(chassis["id"], cpu["id"])
    config = create_validated_configuration(account, chassis["id"],
                                            [{"component_id": cpu["id"], "qty": 1}])
    order, _ = create_order_with_lines(
        account,
        [{"configuration_id": config["id"], "qty": 1, "ship_to_mode": "DROP_SHIP_EMPLOYEES"}],
        po_number="PO-EE2",
    )
    submit_order(account, order, config["version"])
    resp = api.create_deployment_wave(
        order["id"],
        create_wave_payload(
            wave_label="WBAD",
            ship_window_start="2026-09-05T00:00:00Z",
            ship_window_end="2026-09-10T00:00:00Z",
            destinations=[{"employee_ref": "E1", "address": "1 A St", "units": 2}],
        ),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_ORDER_QUANTITY.value, 422)


def test_outstanding_cents_reconciles_after_delivery(api):
    """PRD §3.7: "When the final in-flight wave is received, the order's
    `ship_status` advances from `SHIPPED` to `DELIVERED` — its terminal state
    on the shipment dimension — and the account's `outstanding_cents` is
    reduced by the order's `total_cents`, settling the receivable."
    PRD §3.7: "Shipping moves every asset covered by the wave's destinations
    from `STAGED` to `IN_TRANSIT` and stamps each with its
    `destination_employee_ref`."

    Design: Corner/cross_cutting_layers/outstanding_cents_reconciles_after_delivery
    """
    env = setup_built_order()
    account = env["account"]
    order = env["order"]
    line = env["line"]
    account_mid = get_success_data(api.get_account(account["id"], ADMIN))
    assert account_mid["outstanding_cents"] == 120_000
    resp = api.set_clock("2026-09-02T00:00:00Z", ADMIN)
    assert resp.status_code == 200
    wave = get_success_data(api.create_deployment_wave(
        order["id"],
        create_wave_payload(
            wave_label="W1",
            ship_window_start="2026-09-02T00:00:00Z",
            ship_window_end="2026-09-20T00:00:00Z",
            destinations=[{"employee_ref": "HQ", "address": "1 Main St", "units": 1}],
        ),
        MANAGER,
    ))
    api.release_wave(wave["id"], MANAGER)
    api.ship_wave(wave["id"], OPS)
    resp = api.receive_wave(wave["id"], make_customer_user_headers(account["id"]))
    validate_success(resp, 200)
    account_after = get_success_data(api.get_account(account["id"], ADMIN))
    assert account_after["outstanding_cents"] == 0
    order_after = get_success_data(api.get_order(order["id"], MANAGER))
    assert order_after["ship_status"] == "DELIVERED"
    assets = get_success_data(api.list_line_assets(
        line["id"], make_customer_user_headers(account["id"])))
    assert assets[0]["status"] == "DELIVERED"
