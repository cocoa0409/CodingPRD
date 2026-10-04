"""Orders: submit gates (state, credit), cancellation paths, outstanding
reconciliation, and the submit-to-build-job cascade."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    allocate_job,
    complete_job,
    create_account,
    create_chassis,
    create_component,
    add_allowed_rule,
    create_configuration,
    create_validated_configuration,
    create_order_with_lines,
    get_order_build_jobs,
    start_job,
    submit_order,
    setup_submitted_order,
    setup_built_order,
    make_customer_user_headers,
    get_success_data,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["account_manager_headers"]
OPS = TEST_USERS["factory_ops_headers"]


def test_order_submit_requires_configuration_validated(api):
    """PRD §3.4: "then the state rule that every line's configuration is in
    `VALIDATED` or `LOCKED` status, and then the fiscal rule that the account's
    current `outstanding_cents` plus the computed order total stays within the
    account's `credit_limit_cents`, with an overflow rejected as
    `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."
    PRD §2.9: "then state-machine legality (the target resource is not in a
    state from which the requested transition is defined, `ERR_INVALID_STATE`)."

    Design: Difficulty/cross_entity_state_dependency/order_submit_requires_configuration_validated
    """
    account = create_account(company_name="A14")
    chassis = create_chassis(model_code="L14")
    cpu = create_component(sku="CPU14")
    add_allowed_rule(chassis["id"], cpu["id"])
    config = create_configuration(account, chassis["id"],
                                  [{"component_id": cpu["id"], "qty": 1}])
    order, _ = create_order_with_lines(
        account, [{"configuration_id": config["id"], "qty": 1, "ship_to_mode": "SINGLE_ADDRESS"}],
        po_number="PO-14",
    )
    resp = api.submit_order(
        order["id"], {"expected_configuration_version": config["version"]},
        make_customer_user_headers(account["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    order_after = get_success_data(api.get_order(order["id"], MANAGER))
    assert order_after["build_status"] == "DRAFT"
    account_after = get_success_data(api.get_account(account["id"], ADMIN))
    assert account_after["outstanding_cents"] == 0


def test_order_submit_locked_configuration_accepted(api):
    """PRD §3.4: "then the state rule that every line's configuration is in
    `VALIDATED` or `LOCKED` status, and then the fiscal rule that the account's
    current `outstanding_cents` plus the computed order total stays within the
    account's `credit_limit_cents`, with an overflow rejected as
    `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

    Design: Difficulty/cross_entity_state_dependency/order_submit_requires_configuration_validated
    """
    from test_helpers import create_program, create_template
    account = create_account()
    program = create_program(account["id"])
    chassis = create_chassis()
    cpu = create_component()
    add_allowed_rule(chassis["id"], cpu["id"])
    template = create_template(program["id"], chassis["id"],
                               [{"component_id": cpu["id"], "revision": "A01", "qty": 1}])
    api.publish_template(template["id"], MANAGER)
    api.lock_program(program["id"], MANAGER)
    config = create_validated_configuration(
        account, chassis["id"], [{"component_id": cpu["id"], "qty": 1}],
        template_id=template["id"],
    )
    resp = api.lock_configuration(config["id"], MANAGER)
    locked = validate_success(resp, 200)
    assert locked["status"] == "LOCKED"
    order, _ = create_order_with_lines(
        account, [{"configuration_id": config["id"], "qty": 1, "ship_to_mode": "SINGLE_ADDRESS"}],
    )
    submit_order(account, order, locked["version"])
    order_after = get_success_data(api.get_order(order["id"], MANAGER))
    assert order_after["build_status"] == "SUBMITTED"


def test_credit_limit_exceeded_on_submit(api):
    """PRD §3.4: "then the fiscal rule that the account's current
    `outstanding_cents` plus the computed order total stays within the
    account's `credit_limit_cents`, with an overflow rejected as
    `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

    Design: Corner/validations/credit_limit_exceeded_on_submit
    """
    account = create_account(company_name="VV1", credit_limit_cents=110_000)
    chassis = create_chassis(model_code="VVL1", base_price_cents=100_000)
    cpu = create_component(sku="VVC1", price_cents=20_000)
    add_allowed_rule(chassis["id"], cpu["id"])
    config = create_validated_configuration(account, chassis["id"],
                                            [{"component_id": cpu["id"], "qty": 1}])
    order, _ = create_order_with_lines(
        account, [{"configuration_id": config["id"], "qty": 1, "ship_to_mode": "SINGLE_ADDRESS"}],
        po_number="PO-VV1",
    )
    resp = api.submit_order(
        order["id"], {"expected_configuration_version": config["version"]},
        make_customer_user_headers(account["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value, 402)
    account_after = get_success_data(api.get_account(account["id"], ADMIN))
    assert account_after["outstanding_cents"] == 0
    order_after = get_success_data(api.get_order(order["id"], MANAGER))
    assert order_after["build_status"] == "DRAFT"


def test_submit_not_found_outranks_state(api):
    """PRD §2.9: "When an endpoint path contains multiple resource identifiers
    — for example a resource nested under an account, an order, an order line,
    a program, or a build job — the server validates path parameters strictly
    left to right. The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at
    the first path identifier that does not correspond to an existing resource,
    before any deeper identifier or any business rule is evaluated."
    PRD §2.9: "then path existence left to right (`ERR_NOT_FOUND`), then
    state-machine legality (the target resource is not in a state from which
    the requested transition is defined, `ERR_INVALID_STATE`)."

    Design: Corner/validations/submit_not_found_outranks_state
    """
    account = create_account(company_name="VV2")
    chassis = create_chassis(model_code="VVL2")
    cpu = create_component(sku="VVC2")
    config = create_configuration(account, chassis["id"],
                                  [{"component_id": cpu["id"], "qty": 1}])
    resp = api.submit_order(
        NON_EXISTENT_UUID, {"expected_configuration_version": config["version"]},
        make_customer_user_headers(account["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_cancel_draft_order_is_valid(api):
    """PRD §3.4: "From `DRAFT` it cancels unconditionally."

    Design: Corner/state_machines/cancel_draft_order_is_valid
    """
    account = create_account(company_name="SM-4")
    resp = api.create_order({"account_id": account["id"], "po_number": "PO-SM4"},
                            make_customer_user_headers(account["id"]))
    order = get_success_data(resp)
    resp = api.cancel_order(order["id"], make_customer_user_headers(account["id"]))
    validate_success(resp, 200)
    order_after = get_success_data(api.get_order(order["id"], MANAGER))
    assert order_after["build_status"] == "CANCELLED"
    account_after = get_success_data(api.get_account(account["id"], ADMIN))
    assert account_after["outstanding_cents"] == 0


def test_cancel_built_order_rejected(api):
    """PRD §3.4: "From `SUBMITTED` it is permitted only while no build job of
    the order has reached `ALLOCATED`, `BUILDING`, or `COMPLETE`; on success
    every `QUEUED` job of the order moves to `CANCELLED` and the account's
    `outstanding_cents` is credited back by `total_cents`, exactly compensating
    the submission debit."
    PRD §2.9: "then state-machine legality (the target resource is not in a
    state from which the requested transition is defined, `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/cancel_built_order_rejected
    """
    env = setup_built_order()
    resp = api.cancel_order(env["order"]["id"], make_customer_user_headers(env["account"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    order_after = get_success_data(api.get_order(env["order"]["id"], MANAGER))
    assert order_after["build_status"] == "BUILT"


def test_outstanding_cents_submit_cancel_invariant(api):
    """PRD §3.4: "From `SUBMITTED` it is permitted only while no build job of
    the order has reached `ALLOCATED`, `BUILDING`, or `COMPLETE`; on success
    every `QUEUED` job of the order moves to `CANCELLED` and the account's
    `outstanding_cents` is credited back by `total_cents`, exactly compensating
    the submission debit."

    Design: Difficulty/compensating_invariant/outstanding_cents_submit_cancel_invariant
    """
    env = setup_submitted_order()
    account_id = env["account"]["id"]
    order_id = env["order"]["id"]
    account_after = get_success_data(api.get_account(account_id, ADMIN))
    assert account_after["outstanding_cents"] == 120_000
    resp = api.cancel_order(order_id, make_customer_user_headers(account_id))
    validate_success(resp, 200)
    account_after = get_success_data(api.get_account(account_id, ADMIN))
    assert account_after["outstanding_cents"] == 0
    order_after = get_success_data(api.get_order(order_id, MANAGER))
    assert order_after["build_status"] == "CANCELLED"
    jobs = get_order_build_jobs(order_id)
    assert len(jobs) == 1
    assert jobs[0]["status"] == "CANCELLED"


def test_outstanding_cents_submit_debit_is_exact_total(api):
    """PRD §3.1: "The outstanding balance is a live, computed figure: it is
    the sum of order totals for the account's orders whose build status sits
    anywhere from `SUBMITTED` through `SHIPPED`, and it is debited at order
    submission, adjusted by approved substitution price deltas, and settled
    when the order is delivered or cancelled."

    Design: Difficulty/compensating_invariant/outstanding_cents_submit_cancel_invariant
    """
    env = setup_submitted_order(qty=2)
    account_after = get_success_data(api.get_account(env["account"]["id"], ADMIN))
    # unit 120000 x 2 = 240000 debited at submission
    assert account_after["outstanding_cents"] == 240_000
    order_after = get_success_data(api.get_order(env["order"]["id"], MANAGER))
    assert order_after["total_cents"] == 240_000


def test_submit_creates_build_job_cascade(api):
    """PRD §3.4: "On success, the submission stamps `submitted_at`, computes
    and stores the committed lead time per configuration and the order's
    `promised_ship_date`, computes `total_cents` and `discount_cents` per the
    pinned pricing rule, creates one build job per order line in `QUEUED`
    status with its `sequence_rank` assigned by the queue-scoring rule, debits
    `outstanding_cents` by `total_cents`, and increments each referenced
    configuration's `version` by 1."
    PRD §3.5: "Each order line spawns exactly one `BuildJob` at submission. The
    job copies the line's `qty` at creation, records its `order_id` and
    `order_line_id`, enters `QUEUED` status, and receives a `sequence_rank`."

    Design: Corner/cross_cutting_layers/submit_creates_build_job_cascade
    """
    env_account = create_account(company_name="XL3")
    chassis = create_chassis(model_code="XLL3")
    cpu = create_component(sku="XLC3")
    add_allowed_rule(chassis["id"], cpu["id"])
    config = create_validated_configuration(env_account, chassis["id"],
                                            [{"component_id": cpu["id"], "qty": 1}])
    order, lines = create_order_with_lines(
        env_account,
        [
            {"configuration_id": config["id"], "qty": 1, "ship_to_mode": "SINGLE_ADDRESS"},
            {"configuration_id": config["id"], "qty": 3, "ship_to_mode": "SINGLE_ADDRESS"},
        ],
        po_number="PO-XL3",
    )
    submit_order(env_account, order, config["version"])
    jobs = get_order_build_jobs(order["id"])
    assert len(jobs) == 2
    qtys = sorted(j["qty"] for j in jobs)
    assert qtys == [1, 3]
    for job in jobs:
        assert job["status"] == "QUEUED"
        assert isinstance(job["sequence_rank"], int)
