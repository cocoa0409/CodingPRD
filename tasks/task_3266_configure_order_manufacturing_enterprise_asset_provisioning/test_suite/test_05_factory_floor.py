"""Factory floor: allocation, exact-fit boundary, sequencing, build
completion, parallel order status dimensions, and immediate pool visibility."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    allocate_job,
    complete_job,
    create_account,
    create_chassis,
    create_component,
    add_allowed_rule,
    create_validated_configuration,
    create_order_with_lines,
    create_wave_payload,
    get_order_build_jobs,
    start_job,
    submit_order,
    setup_submitted_order,
    make_customer_user_headers,
    get_success_data,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["account_manager_headers"]
OPS = TEST_USERS["factory_ops_headers"]


def test_allocation_exact_fit_available_equals_required(api):
    """PRD §3.5: "The order must be in `SUBMITTED` build status, and every
    component required by the job's configuration must satisfy the stock rule:
    the component's `available_units` is at least the required quantity — the
    boundary is inclusive, so an exact fit allocates cleanly, while any
    shortfall rejects with `ERR_INSUFFICIENT_COMPONENT_STOCK` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/allocation_exact_fit_available_equals_required
    """
    account = create_account(company_name="A12")
    chassis = create_chassis(model_code="L12", category="DESKTOP", base_price_cents=60_000)
    mem = create_component(sku="MEM12", kind="MEMORY", price_cents=3_000,
                           lead_time_days=2, stock_on_hand=2)
    add_allowed_rule(chassis["id"], mem["id"])
    config = create_validated_configuration(account, chassis["id"],
                                            [{"component_id": mem["id"], "qty": 1}])
    order, _ = create_order_with_lines(
        account, [{"configuration_id": config["id"], "qty": 2, "ship_to_mode": "SINGLE_ADDRESS"}],
        po_number="PO-12",
    )
    submit_order(account, order, config["version"])
    job = get_order_build_jobs(order["id"])[0]
    resp = api.allocate_build_job(job["id"], OPS)
    job_after = validate_success(resp, 200)
    assert job_after["status"] == "ALLOCATED"
    mem_after = get_success_data(api.get_component(mem["id"], OPS))
    assert mem_after["reserved_units"] == 2
    assert mem_after["available_units"] == 0
    resp = api.list_job_substitution_requests(job["id"], OPS)
    srs = get_success_data(resp)
    assert len(srs) == 0


def test_allocation_one_unit_short_blocks_job(api):
    """PRD §3.5: "The order must be in `SUBMITTED` build status, and every
    component required by the job's configuration must satisfy the stock rule:
    the component's `available_units` is at least the required quantity — the
    boundary is inclusive, so an exact fit allocates cleanly, while any
    shortfall rejects with `ERR_INSUFFICIENT_COMPONENT_STOCK` (HTTP 422)."
    PRD §3.6: "when any required component's `available_units` falls below the
    required quantity, the affected job does not simply fail — it moves from
    `QUEUED` to `SHORTAGE_BLOCKED`, its `shortage_component_id` is set to the
    component with the largest shortfall (ties broken by the component's
    `created_at` ascending), the system automatically creates a
    `SubstitutionRequest` in `PENDING` status against the job, and the order
    cascades from `SUBMITTED` to `ON_HOLD`."

    Design: Difficulty/boundary_precision_check/allocation_exact_fit_available_equals_required
    """
    # One unit short: stock 1, required 2.
    account = create_account()
    chassis = create_chassis()
    mem = create_component(kind="MEMORY", price_cents=3_000, stock_on_hand=1)
    add_allowed_rule(chassis["id"], mem["id"])
    config = create_validated_configuration(account, chassis["id"],
                                            [{"component_id": mem["id"], "qty": 1}])
    order, _ = create_order_with_lines(
        account, [{"configuration_id": config["id"], "qty": 2, "ship_to_mode": "SINGLE_ADDRESS"}],
    )
    submit_order(account, order, config["version"])
    job = get_order_build_jobs(order["id"])[0]
    resp = api.allocate_build_job(job["id"], OPS)
    job_after = validate_success(resp, 200)
    assert job_after["status"] == "SHORTAGE_BLOCKED"


def test_build_out_of_sequence_rejected(api):
    """PRD §3.5: "Starting a build moves a job from `ALLOCATED` to `BUILDING`,
    and sequencing is enforced: only the job whose `sequence_rank` is the
    minimum among the factory queue's `ALLOCATED` jobs may start — with rank
    ties broken by the job's `created_at` ascending — and an out-of-sequence
    start is rejected with `ERR_BUILD_OUT_OF_SEQUENCE` (HTTP 422)."

    Design: Corner/errors/build_out_of_sequence_rejected
    """
    account = create_account(company_name="ER1")
    chassis = create_chassis(model_code="ERL1")
    cpu = create_component(sku="ERC1", stock_on_hand=20)
    add_allowed_rule(chassis["id"], cpu["id"])
    config = create_validated_configuration(account, chassis["id"],
                                            [{"component_id": cpu["id"], "qty": 1}])
    order_a, _ = create_order_with_lines(
        account, [{"configuration_id": config["id"], "qty": 1, "ship_to_mode": "SINGLE_ADDRESS"}],
        po_number="PO-ER1A",
    )
    submit_order(account, order_a, config["version"])
    order_b, _ = create_order_with_lines(
        account, [{"configuration_id": config["id"], "qty": 1, "ship_to_mode": "SINGLE_ADDRESS"}],
        po_number="PO-ER1B",
    )
    config_after = get_success_data(api.get_configuration(config["id"], MANAGER))
    submit_order(account, order_b, config_after["version"])
    job_a = get_order_build_jobs(order_a["id"])[0]
    job_b = get_order_build_jobs(order_b["id"])[0]
    allocate_job(job_a["id"])
    allocate_job(job_b["id"])
    # The later-submitted order's job is not the minimum-rank ALLOCATED job.
    resp = api.start_build_job(job_b["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_BUILD_OUT_OF_SEQUENCE.value, 422)
    job_b_after = get_success_data(api.get_build_job(job_b["id"], OPS))
    assert job_b_after["status"] == "ALLOCATED"


def test_build_out_of_sequence_min_rank_starts_cleanly(api):
    """PRD §3.5: "Starting a build moves a job from `ALLOCATED` to `BUILDING`,
    and sequencing is enforced: only the job whose `sequence_rank` is the
    minimum among the factory queue's `ALLOCATED` jobs may start — with rank
    ties broken by the job's `created_at` ascending — and an out-of-sequence
    start is rejected with `ERR_BUILD_OUT_OF_SEQUENCE` (HTTP 422)."

    Design: Corner/errors/build_out_of_sequence_rejected
    """
    account = create_account()
    chassis = create_chassis()
    cpu = create_component(stock_on_hand=20)
    add_allowed_rule(chassis["id"], cpu["id"])
    config = create_validated_configuration(account, chassis["id"],
                                            [{"component_id": cpu["id"], "qty": 1}])
    order_a, _ = create_order_with_lines(
        account, [{"configuration_id": config["id"], "qty": 1, "ship_to_mode": "SINGLE_ADDRESS"}],
    )
    submit_order(account, order_a, config["version"])
    order_b, _ = create_order_with_lines(
        account, [{"configuration_id": config["id"], "qty": 1, "ship_to_mode": "SINGLE_ADDRESS"}],
    )
    config_after = get_success_data(api.get_configuration(config["id"], MANAGER))
    submit_order(account, order_b, config_after["version"])
    job_a = get_order_build_jobs(order_a["id"])[0]
    job_b = get_order_build_jobs(order_b["id"])[0]
    allocate_job(job_a["id"])
    allocate_job(job_b["id"])
    # The first order's job is the min-rank ALLOCATED job; it starts cleanly.
    resp = api.start_build_job(job_a["id"], OPS)
    job_after = validate_success(resp, 200)
    assert job_after["status"] == "BUILDING"


def test_allocation_to_consumption_to_asset_mint_cascade(api):
    """PRD §3.5: "Starting physically consumes stock: each consumed
    component's `reserved_units` decreases by the consumed quantity and its
    `stock_on_hand` decreases by the same amount. The first job start of an
    order bubbles the order's `build_status` from `ALLOCATED` to
    `IN_PRODUCTION`."
    PRD §3.5: "Completion moves a job from `BUILDING` to `COMPLETE` and mints
    the physical record of the work: for each unit of the line's `qty`, one
    `Asset` row is created under the order line with a unique factory-stamped
    `serial_number`, an `asset_tag` composed from the program's
    `asset_tag_prefix` plus a zero-padded sequence (for example `FE-000123`),
    and the `image_applied_ref` recording the custom image actually flashed in
    the factory. Each minted asset begins in `STAGED` status with
    `destination_employee_ref` null. When the last non-terminal job of an order
    completes, the order's `build_status` bubbles to `BUILT` while
    `ship_status` remains `PENDING`, awaiting wave planning."

    Design: Difficulty/transitive_cascade/allocation_to_consumption_to_asset_mint_cascade
    """
    account = create_account(company_name="A9")
    chassis = create_chassis(model_code="L9", category="SERVER", base_price_cents=70_000)
    nic = create_component(sku="NIC9", kind="NIC", price_cents=4_000,
                           lead_time_days=2, stock_on_hand=5)
    add_allowed_rule(chassis["id"], nic["id"])
    config = create_validated_configuration(account, chassis["id"],
                                            [{"component_id": nic["id"], "qty": 1}])
    order, lines = create_order_with_lines(
        account, [{"configuration_id": config["id"], "qty": 2, "ship_to_mode": "SINGLE_ADDRESS"}],
        po_number="PO-9",
    )
    submit_order(account, order, config["version"])
    job = get_order_build_jobs(order["id"])[0]
    allocate_job(job["id"])
    start_job(job["id"])
    nic_after = get_success_data(api.get_component(nic["id"], OPS))
    assert nic_after["reserved_units"] == 0
    assert nic_after["stock_on_hand"] == 3
    order_after = get_success_data(api.get_order(order["id"], MANAGER))
    assert order_after["build_status"] == "IN_PRODUCTION"
    complete_job(job["id"])
    assets = get_success_data(api.list_line_assets(
        lines[0]["id"], make_customer_user_headers(account["id"])))
    assert len(assets) == 2
    for asset in assets:
        assert asset["status"] == "STAGED"
        assert asset["serial_number"]
    order_after = get_success_data(api.get_order(order["id"], MANAGER))
    assert order_after["build_status"] == "BUILT"


def test_asset_minted_staged_with_null_destination(api):
    """PRD §3.5: "Each minted asset begins in `STAGED` status with
    `destination_employee_ref` null."

    Design: Difficulty/transitive_cascade/allocation_to_consumption_to_asset_mint_cascade
    """
    account = create_account()
    chassis = create_chassis()
    cpu = create_component()
    add_allowed_rule(chassis["id"], cpu["id"])
    config = create_validated_configuration(account, chassis["id"],
                                            [{"component_id": cpu["id"], "qty": 1}])
    order, lines = create_order_with_lines(
        account, [{"configuration_id": config["id"], "qty": 1, "ship_to_mode": "SINGLE_ADDRESS"}],
    )
    submit_order(account, order, config["version"])
    job = get_order_build_jobs(order["id"])[0]
    allocate_job(job["id"])
    start_job(job["id"])
    complete_job(job["id"])
    assets = get_success_data(api.list_line_assets(
        lines[0]["id"], make_customer_user_headers(account["id"])))
    assert len(assets) == 1
    assert assets[0]["status"] == "STAGED"
    assert assets[0]["destination_employee_ref"] is None


def test_order_parallel_build_and_ship_dimensions(api):
    """PRD §3.4: "The order is born with `build_status` of `DRAFT` and
    `ship_status` of `PENDING` — two parallel status dimensions that move
    independently until delivery — and with `submitted_at` null until
    submission stamps it."
    PRD §3.7: "The first release of an order also bubbles the order's
    `ship_status` from `PENDING` to `STAGED`."

    Design: Difficulty/non_linear_state_machine/order_parallel_build_and_ship_dimensions
    """
    account = create_account(company_name="A7")
    chassis = create_chassis(model_code="L7", category="DESKTOP", base_price_cents=80_000)
    ram = create_component(sku="RAM7", kind="MEMORY", price_cents=8_000, lead_time_days=2)
    add_allowed_rule(chassis["id"], ram["id"])
    config = create_validated_configuration(account, chassis["id"],
                                            [{"component_id": ram["id"], "qty": 1}])
    order, _ = create_order_with_lines(
        account, [{"configuration_id": config["id"], "qty": 1, "ship_to_mode": "SINGLE_ADDRESS"}],
        po_number="PO-7",
    )
    submit_order(account, order, config["version"])
    job = get_order_build_jobs(order["id"])[0]
    allocate_job(job["id"])
    after_alloc = get_success_data(api.get_order(order["id"], MANAGER))
    assert after_alloc["build_status"] == "ALLOCATED"
    assert after_alloc["ship_status"] == "PENDING"
    resp = api.create_deployment_wave(
        order["id"],
        create_wave_payload(
            ship_window_start="2026-09-01T00:00:00Z",
            ship_window_end="2026-09-20T00:00:00Z",
            destinations=[{"employee_ref": "HQ", "address": "1 Main St", "units": 1}],
        ),
        MANAGER,
    )
    wave = get_success_data(resp)
    start_job(job["id"])
    complete_job(job["id"])
    after_built = get_success_data(api.get_order(order["id"], MANAGER))
    assert after_built["build_status"] == "BUILT"
    assert after_built["ship_status"] == "PENDING"
    resp = api.release_wave(wave["id"], MANAGER)
    validate_success(resp, 200)
    after_release = get_success_data(api.get_order(order["id"], MANAGER))
    assert after_release["ship_status"] == "STAGED"
    assert after_release["build_status"] == "BUILT"


def test_order_parallel_dimensions_hold_through_production(api):
    """PRD §3.4: "The order is born with `build_status` of `DRAFT` and
    `ship_status` of `PENDING` — two parallel status dimensions that move
    independently until delivery — and with `submitted_at` null until
    submission stamps it."

    Design: Difficulty/non_linear_state_machine/order_parallel_build_and_ship_dimensions
    """
    env = setup_submitted_order()
    order_id = env["order"]["id"]
    mid = get_success_data(api.get_order(order_id, MANAGER))
    assert mid["build_status"] == "SUBMITTED"
    assert mid["ship_status"] == "PENDING"
    job = env["jobs"][0]
    allocate_job(job["id"])
    start_job(job["id"])
    mid = get_success_data(api.get_order(order_id, MANAGER))
    assert mid["build_status"] == "IN_PRODUCTION"
    assert mid["ship_status"] == "PENDING"


def test_allocation_effects_visible_in_same_response(api):
    """PRD §3.5: "On success, each required component's `reserved_units`
    increases by the required quantity, which recomputes `available_units`
    downward per the invariant in §2.8."
    PRD §2.8: "`available_units` is a derived quantity equal to `stock_on_hand`
    minus `reserved_units`; it is never stored as an independent input, and
    every mutation that touches the pool — allocation, build start, restock,
    entitlement parts stocking, entitlement release — must keep this identity
    true."

    Design: Corner/consistency_model/allocation_effects_visible_in_same_response
    """
    account = create_account(company_name="CM1")
    chassis = create_chassis(model_code="CML1")
    cpu = create_component(sku="CMC1", stock_on_hand=4)
    add_allowed_rule(chassis["id"], cpu["id"])
    config = create_validated_configuration(account, chassis["id"],
                                            [{"component_id": cpu["id"], "qty": 1}])
    order, _ = create_order_with_lines(
        account, [{"configuration_id": config["id"], "qty": 3, "ship_to_mode": "SINGLE_ADDRESS"}],
        po_number="PO-CM1",
    )
    submit_order(account, order, config["version"])
    job = get_order_build_jobs(order["id"])[0]
    resp = api.allocate_build_job(job["id"], OPS)
    job_after = validate_success(resp, 200)
    assert job_after["status"] == "ALLOCATED"
    cpu_after = get_success_data(api.get_component(cpu["id"], OPS))
    assert cpu_after["reserved_units"] == 3
    assert cpu_after["available_units"] == 1
