"""Component shortage and the substitution negotiation: the shortage cascade,
the PENDING-REJECTED-PENDING cycle, approval repricing, incompatibility, and
the state-over-fiscal priority pair."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_account,
    create_chassis,
    create_component,
    add_allowed_rule,
    create_validated_configuration,
    create_order_with_lines,
    get_order_build_jobs,
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


def test_shortage_allocate_cascades_job_to_request_to_order_hold(api):
    """PRD §3.6: "when any required component's `available_units` falls below
    the required quantity, the affected job does not simply fail — it moves
    from `QUEUED` to `SHORTAGE_BLOCKED`, its `shortage_component_id` is set to
    the component with the largest shortfall (ties broken by the component's
    `created_at` ascending), the system automatically creates a
    `SubstitutionRequest` in `PENDING` status against the job, and the order
    cascades from `SUBMITTED` to `ON_HOLD`."

    Design: Difficulty/transitive_cascade/shortage_allocate_cascades_job_to_request_to_order_hold
    """
    account = create_account(company_name="A8")
    chassis = create_chassis(model_code="L8", category="DESKTOP", base_price_cents=90_000)
    psu = create_component(sku="PSU8", kind="PSU", price_cents=6_000,
                           lead_time_days=4, stock_on_hand=1)
    add_allowed_rule(chassis["id"], psu["id"])
    config = create_validated_configuration(account, chassis["id"],
                                            [{"component_id": psu["id"], "qty": 1}])
    order, _ = create_order_with_lines(
        account, [{"configuration_id": config["id"], "qty": 2, "ship_to_mode": "SINGLE_ADDRESS"}],
        po_number="PO-8",
    )
    submit_order(account, order, config["version"])
    job = get_order_build_jobs(order["id"])[0]
    resp = api.allocate_build_job(job["id"], OPS)
    job_after = validate_success(resp, 200)
    assert job_after["status"] == "SHORTAGE_BLOCKED"
    assert job_after["shortage_component_id"] == psu["id"]
    srs = get_success_data(api.list_job_substitution_requests(job["id"], OPS))
    assert len(srs) == 1
    assert srs[0]["status"] == "PENDING"
    assert srs[0]["original_component_id"] == psu["id"]
    order_after = get_success_data(api.get_order(order["id"], MANAGER))
    assert order_after["build_status"] == "ON_HOLD"
    psu_after = get_success_data(api.get_component(psu["id"], OPS))
    assert psu_after["reserved_units"] == 0


def test_shortage_leaves_component_pool_untouched(api):
    """PRD §3.5: "On success, each required component's `reserved_units`
    increases by the required quantity, which recomputes `available_units`
    downward per the invariant in §2.8."
    PRD §3.6: "when any required component's `available_units` falls below the
    required quantity, the affected job does not simply fail — it moves from
    `QUEUED` to `SHORTAGE_BLOCKED`, its `shortage_component_id` is set to the
    component with the largest shortfall (ties broken by the component's
    `created_at` ascending), the system automatically creates a
    `SubstitutionRequest` in `PENDING` status against the job, and the order
    cascades from `SUBMITTED` to `ON_HOLD`."

    Design: Difficulty/transitive_cascade/shortage_allocate_cascades_job_to_request_to_order_hold
    """
    env = setup_shortage_blocked_order()
    shorted_after = get_success_data(api.get_component(env["shorted"]["id"], OPS))
    assert shorted_after["reserved_units"] == 0
    assert shorted_after["available_units"] == shorted_after["stock_on_hand"]
    order_after = get_success_data(api.get_order(env["order"]["id"], MANAGER))
    assert order_after["build_status"] == "ON_HOLD"


def test_substitution_negotiation_cycle_pending_rejected_pending(api):
    """PRD §3.6: "The factory answers with a reproposal: a `FactoryOps`
    operator proposes a different `proposed_component_id` — it must differ from
    the rejected one, or the same `ERR_SUBSTITUTION_INCOMPATIBLE` applies —
    which moves the request from `REJECTED` back to `PENDING`, increments
    `round` by 1, and recomputes `price_delta_cents` for the new proposal."
    PRD §3.6: "Rejection leaves the request in `REJECTED`, the job
    `SHORTAGE_BLOCKED`, and the order `ON_HOLD` — rejection is a negotiating
    position, not an escape hatch."

    Design: Difficulty/non_linear_state_machine/substitution_negotiation_cycle_pending_rejected_pending
    """
    env = setup_shortage_blocked_order(line_qty=2, spare_price=7_000)
    account = env["account"]
    third = create_component(sku="SSD3", kind="STORAGE", price_cents=6_500, stock_on_hand=50)
    add_allowed_rule(env["chassis"]["id"], third["id"])
    resp = api.reject_substitution(env["sr"]["id"], make_customer_user_headers(account["id"]))
    validate_success(resp, 200)
    resp = api.repropose_substitution(env["sr"]["id"],
                                      {"proposed_component_id": third["id"]}, OPS)
    sr_after = validate_success(resp, 200)
    assert sr_after["status"] == "PENDING"
    assert sr_after["round"] == 2
    assert sr_after["price_delta_cents"] == 1_500
    job_after = get_success_data(api.get_build_job(env["job"]["id"], OPS))
    assert job_after["status"] == "SHORTAGE_BLOCKED"
    order_after = get_success_data(api.get_order(env["order"]["id"], MANAGER))
    assert order_after["build_status"] == "ON_HOLD"


def test_substitution_cycle_second_round_keeps_hold(api):
    """PRD §3.6: "This `PENDING` to `REJECTED` to `PENDING` loop is cyclic by
    design and continues until an approval or a supersede closes it."

    Design: Difficulty/non_linear_state_machine/substitution_negotiation_cycle_pending_rejected_pending
    """
    env = setup_shortage_blocked_order()
    account = env["account"]
    spare2 = create_component(sku="SPARE2", kind="STORAGE", price_cents=4_000, stock_on_hand=50)
    add_allowed_rule(env["chassis"]["id"], spare2["id"])
    api.reject_substitution(env["sr"]["id"], make_customer_user_headers(account["id"]))
    api.repropose_substitution(env["sr"]["id"], {"proposed_component_id": spare2["id"]}, OPS)
    api.reject_substitution(env["sr"]["id"], make_customer_user_headers(account["id"]))
    spare3 = create_component(sku="SPARE3", kind="STORAGE", price_cents=8_000, stock_on_hand=50)
    add_allowed_rule(env["chassis"]["id"], spare3["id"])
    resp = api.repropose_substitution(env["sr"]["id"],
                                      {"proposed_component_id": spare3["id"]}, OPS)
    sr_after = validate_success(resp, 200)
    assert sr_after["round"] == 3
    assert sr_after["price_delta_cents"] == 3_000
    order_after = get_success_data(api.get_order(env["order"]["id"], MANAGER))
    assert order_after["build_status"] == "ON_HOLD"


def test_repropose_from_pending_rejected(api):
    """PRD §3.6: "The factory answers with a reproposal: a `FactoryOps`
    operator proposes a different `proposed_component_id` — it must differ from
    the rejected one, or the same `ERR_SUBSTITUTION_INCOMPATIBLE` applies —
    which moves the request from `REJECTED` back to `PENDING`, increments
    `round` by 1, and recomputes `price_delta_cents` for the new proposal."
    PRD §2.9: "then state-machine legality (the target resource is not in a
    state from which the requested transition is defined, `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/repropose_from_pending_rejected
    """
    env = setup_shortage_blocked_order()
    resp = api.repropose_substitution(
        env["sr"]["id"], {"proposed_component_id": env["spare"]["id"]}, OPS,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    sr_after = get_success_data(api.get_substitution_request(env["sr"]["id"], OPS))
    assert sr_after["round"] == 1


def test_substitution_approve_compatible_passes(api):
    """PRD §3.6: "Approval moves the request from `PENDING` to `APPROVED`,
    cascades the job from `SHORTAGE_BLOCKED` back to `QUEUED` with the proposed
    component swapped into the job's effective component list, reprices the
    order by adding the price delta multiplied by the job's `qty` to
    `total_cents`, and adjusts `outstanding_cents` by the same amount."
    PRD §3.6: "When the last `SHORTAGE_BLOCKED` job of an order leaves that
    state through an approval, the order cascades back from `ON_HOLD` to
    `SUBMITTED` automatically."

    Design: Corner/validations/substitution_by_factory_ops_forbidden_and_compatible_passes
    """
    env = setup_shortage_blocked_order(line_qty=2, spare_price=7_000)
    account = env["account"]
    api.reject_substitution(env["sr"]["id"], make_customer_user_headers(account["id"]))
    api.repropose_substitution(env["sr"]["id"],
                               {"proposed_component_id": env["spare"]["id"]}, OPS)
    resp = api.approve_substitution(env["sr"]["id"], make_customer_user_headers(account["id"]))
    sr_after = validate_success(resp, 200)
    assert sr_after["status"] == "APPROVED"
    job_after = get_success_data(api.get_build_job(env["job"]["id"], OPS))
    assert job_after["status"] == "QUEUED"
    order_after = get_success_data(api.get_order(env["order"]["id"], MANAGER))
    assert order_after["build_status"] == "SUBMITTED"
    # unit 100000 + 5000 = 105000 per unit x 2 = 210000 before approval;
    # delta 2000 x qty 2 = 4000 -> 214000
    assert order_after["total_cents"] == 214_000
    account_after = get_success_data(api.get_account(account["id"], ADMIN))
    assert account_after["outstanding_cents"] == 214_000


def test_substitution_approve_state_outranks_fiscal(api):
    """PRD §3.6: "Between these two, the state rule outranks the fiscal rule:
    state legality (priority 4) is evaluated before the credit check (priority
    10), so a stale approval always surfaces as `ERR_INVALID_STATE` even when
    the credit limit would also have failed."
    PRD §3.6: "When the order is no longer `ON_HOLD` — a stale approval
    arriving after the hold has lifted — the approval is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/substitution_approve_state_outranks_fiscal
    """
    # credit limit 110001c; order total 105000c; approval delta +4999c fits
    # (109999 <= 110001), so the first approval succeeds. A second approval of
    # the now-APPROVED request fails the state gate; re-applying the delta
    # would also have overflowed the limit (114998 > 110001).
    account = create_account(company_name="A10", credit_limit_cents=110_001)
    chassis = create_chassis(model_code="L10", base_price_cents=100_000)
    ssd10 = create_component(sku="SSD10", kind="STORAGE", price_cents=5_000, stock_on_hand=0)
    ssd11 = create_component(sku="SSD11", kind="STORAGE", price_cents=9_999, stock_on_hand=5)
    add_allowed_rule(chassis["id"], ssd10["id"])
    add_allowed_rule(chassis["id"], ssd11["id"])
    config = create_validated_configuration(account, chassis["id"],
                                            [{"component_id": ssd10["id"], "qty": 1}])
    order, _ = create_order_with_lines(
        account, [{"configuration_id": config["id"], "qty": 1, "ship_to_mode": "SINGLE_ADDRESS"}],
        po_number="PO-10",
    )
    submit_order(account, order, config["version"])
    job = get_order_build_jobs(order["id"])[0]
    resp = api.allocate_build_job(job["id"], OPS)
    assert resp.status_code == 200
    srs = get_success_data(api.list_job_substitution_requests(job["id"], OPS))
    sr = srs[0]
    # The auto-created request names no proposal; the factory puts the
    # replacement on the table through the reject/repropose negotiation
    # (PRD §3.6) before the customer can approve it.
    resp = api.reject_substitution(sr["id"], make_customer_user_headers(account["id"]))
    validate_success(resp, 200)
    resp = api.repropose_substitution(sr["id"], {"proposed_component_id": ssd11["id"]}, OPS)
    validate_success(resp, 200)
    resp = api.approve_substitution(sr["id"], make_customer_user_headers(account["id"]))
    validate_success(resp, 200)
    resp = api.approve_substitution(sr["id"], make_customer_user_headers(account["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    order_after = get_success_data(api.get_order(order["id"], MANAGER))
    assert order_after["total_cents"] == 109_999


def test_stale_approval_never_reports_credit_limit_error(api):
    """PRD §3.6: "When the order is no longer `ON_HOLD` — a stale approval
    arriving after the hold has lifted — the approval is rejected with
    `ERR_INVALID_STATE` (HTTP 409). When the order is still `ON_HOLD` but a
    positive price delta would push the account's `outstanding_cents` beyond
    `credit_limit_cents`, the approval is rejected with
    `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402). Between these two, the state rule
    outranks the fiscal rule: state legality (priority 4) is evaluated before
    the credit check (priority 10), so a stale approval always surfaces as
    `ERR_INVALID_STATE` even when the credit limit would also have failed."

    Design: Difficulty/priority_pair_validation_conflict/substitution_approve_state_outranks_fiscal
    """
    account = create_account(credit_limit_cents=110_001)
    chassis = create_chassis(base_price_cents=100_000)
    ssd_a = create_component(sku="SSDA", kind="STORAGE", price_cents=5_000, stock_on_hand=0)
    ssd_b = create_component(sku="SSDB", kind="STORAGE", price_cents=9_999, stock_on_hand=5)
    add_allowed_rule(chassis["id"], ssd_a["id"])
    add_allowed_rule(chassis["id"], ssd_b["id"])
    config = create_validated_configuration(account, chassis["id"],
                                            [{"component_id": ssd_a["id"], "qty": 1}])
    order, _ = create_order_with_lines(
        account, [{"configuration_id": config["id"], "qty": 1, "ship_to_mode": "SINGLE_ADDRESS"}],
    )
    submit_order(account, order, config["version"])
    job = get_order_build_jobs(order["id"])[0]
    api.allocate_build_job(job["id"], OPS)
    sr = get_success_data(api.list_job_substitution_requests(job["id"], OPS))[0]
    # Negotiate the proposal onto the table (PRD §3.6 reject/repropose cycle)
    # so the first approval is valid; the second is the stale one under test.
    api.reject_substitution(sr["id"], make_customer_user_headers(account["id"]))
    api.repropose_substitution(sr["id"], {"proposed_component_id": ssd_b["id"]}, OPS)
    api.approve_substitution(sr["id"], make_customer_user_headers(account["id"]))
    resp = api.approve_substitution(sr["id"], make_customer_user_headers(account["id"]))
    err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert err["error_id"] != ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value


def test_substitution_incompatible_component_rejected(api):
    """PRD §3.6: "the acting `X-User-ID` must resolve to the `CustomerAccount`
    that owns the order, and the proposed component must be `ACTIVE` and must
    pass every compatibility rule of the chassis in place of the original — a
    proposed component that is end-of-life, that duplicates the original, or
    that breaks the chassis rule set is rejected with
    `ERR_SUBSTITUTION_INCOMPATIBLE` (HTTP 422)."

    Design: Corner/validations/substitution_incompatible_component_rejected
    """
    env = setup_shortage_blocked_order()
    account = env["account"]
    xnic = create_component(sku="VV4X", kind="NIC", price_cents=3_000, stock_on_hand=50)
    # NB: deliberately NO ALLOWED rule for xnic on this chassis.
    api.reject_substitution(env["sr"]["id"], make_customer_user_headers(account["id"]))
    resp = api.repropose_substitution(env["sr"]["id"],
                                      {"proposed_component_id": xnic["id"]}, OPS)
    validate_error(resp, ApiErrorId.ERR_SUBSTITUTION_INCOMPATIBLE.value, 422)
    sr_after = get_success_data(api.get_substitution_request(env["sr"]["id"], OPS))
    assert sr_after["status"] == "REJECTED"
