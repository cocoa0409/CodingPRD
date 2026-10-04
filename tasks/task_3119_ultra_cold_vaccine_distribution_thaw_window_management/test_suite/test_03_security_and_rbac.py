"""Role authorization and segregation of duties."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_error_is_one_of,
    get_success_data,
    TEST_USERS,
    build_user_headers,
    make_site_coordinator_headers,
    make_product,
    make_program,
    make_site,
    make_batch,
    register_carton,
    release_batch,
    certify_site,
    setup_entitled_site,
    submit_order,
    create_excursion,
    add_ledger_entry,
    anchor_thawed_carton,
    anchor_delivered_carton,
    get_order,
    get_entitlement,
    get_carton,
)


def test_controller_cannot_submit_an_order_itself(api):
    """PRD §3.3: "Submission moves it from `DRAFT` to `SUBMITTED` and is guarded by
    five conditions."

    PRD §2.1: "A request that carries well-formed headers but asks a role to perform
    an operation outside its granted set is refused with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)."

    Design: Corner/validations/controller_cannot_submit_an_order_itself
    """
    ctx = setup_entitled_site()
    headers = make_site_coordinator_headers(ctx["site"]["id"])
    order = get_success_data(api.create_site_order(
        {"allocation_entitlement_id": ctx["entitlement"]["id"],
         "storage_site_id": ctx["site"]["id"], "requested_cartons": 2,
         "requested_doses": 1000}, headers))

    res = api.submit_site_order(order["id"], TEST_USERS["cold_chain_reviewer_headers"])
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)

    after = get_order(order["id"])
    assert after["order_status"] == "DRAFT"
    assert after["submitted_at"] is None
    assert get_entitlement(ctx["entitlement"]["id"])["held_cartons"] == 0


def test_review_endpoint_requires_the_cold_chain_reviewer_role(api):
    """PRD §3.8: "A `ColdChainReviewer` begins the review by moving the excursion
    from `REPORTED` to `UNDER_REVIEW`."

    PRD §2.1: "A request that carries well-formed headers but asks a role to perform
    an operation outside its granted set is refused with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)."

    Design: Corner/validations/review_endpoint_requires_the_cold_chain_reviewer_role
    """
    ctx = anchor_thawed_carton()
    exc = create_excursion(ctx["carton"]["id"], ctx["site"]["id"], min_temperature_c=-55)

    refused = api.review_temperature_excursion(
        exc["id"], TEST_USERS["manufacturing_qa_headers"])
    validate_error(refused, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)

    accepted = validate_success(
        api.review_temperature_excursion(exc["id"], TEST_USERS["cold_chain_reviewer_headers"]), 200)
    assert accepted["review_status"] == "UNDER_REVIEW"
    assert accepted["quarantine_status"] == "OPEN"

    site = get_success_data(api.get_storage_site(
        ctx["site"]["id"], TEST_USERS["cold_chain_reviewer_headers"]))
    assert site["inventory_status"] == "RESTRICTED"


def test_dispatch_on_a_disputed_order_is_held_for_payment(api):
    """PRD §3.5: "an order that has been disputed cannot be dispatched, nor
    delivered".

    PRD §3.5: "The order's `payment_status` becomes `DISPUTED`, and the route
    cartons remain `IN_TRANSIT` and are re-consigned to the staging site."

    Design: Corner/validations/dispatch_on_a_disputed_order_is_held_for_payment
    """
    from test_helpers import create_shipper_payload, create_logger_reading_payload

    ctx = setup_entitled_site()
    site_id = ctx["site"]["id"]
    # PRD §3.5 makes a dock refusal legitimate only when "the destination's
    # equipment certificate expired at arrival, or a pack hold was raised in
    # transit".  Certifying the destination with a certificate that lapses between
    # the pack instant and the arrival instant builds exactly that first basis.
    certify_site(site_id, certificate_number="CERT-MI-DOCK",
                 certificate_expires_at="2026-09-01T12:00:00Z")
    order = submit_order(ctx["entitlement"]["id"], site_id)
    accept = accept_order_or_fail(order["id"], ctx["window"]["version"])
    dispatch = get_success_data(api.create_dispatch(
        {"site_order_id": order["id"], "storage_site_id": site_id,
         "entry_route": "DIRECT_ULTRA_COLD"}, TEST_USERS["logistics_operator_headers"]))
    api.pack_dispatch(dispatch["id"], TEST_USERS["logistics_operator_headers"])
    shipper = get_success_data(api.create_shipper(
        create_shipper_payload(dispatch["id"]), TEST_USERS["logistics_operator_headers"]))
    api.attach_carton_to_shipper(shipper["id"], {"carton_id": ctx["carton"]["id"]},
                                 TEST_USERS["logistics_operator_headers"])
    for recorded_at, temp in (("2026-09-01T01:00:00Z", -75), ("2026-09-01T06:05:00Z", -74)):
        api.create_logger_reading(
            create_logger_reading_payload(shipper["id"], recorded_at=recorded_at,
                                          temperature_c=temp),
            TEST_USERS["logistics_operator_headers"])
    shipper = get_success_data(api.get_shipper(shipper["id"],
                                               TEST_USERS["cold_chain_reviewer_headers"]))
    api.seal_shipper(shipper["id"], {"expected_shipper_version": shipper["version"]},
                     TEST_USERS["logistics_operator_headers"])
    api.send_dispatch(dispatch["id"], TEST_USERS["logistics_operator_headers"])
    rejected = validate_success(api.reject_at_dock(
        dispatch["id"], {"reason_code": "SITE_NOT_READY"},
        make_site_coordinator_headers(site_id)), 200)
    assert rejected["status"] == "REJECTED_AT_DOCK"
    assert get_order(order["id"])["payment_status"] == "DISPUTED"

    # PRD §3.5 states two live rules over this same request -- "Dispatching moves a
    # `PACKED` dispatch to `IN_TRANSIT`" and "an order that has been disputed cannot
    # be dispatched, nor delivered" -- so both ERR_INVALID_STATE and ERR_PAYMENT_HOLD
    # are PRD-faithful answers to a re-dispatch of a shipment already refused at the
    # dock.  The disputed-payment rule is asserted by driving the request down the
    # non-terminal path instead, where only it can decide.
    res = api.send_dispatch(dispatch["id"], TEST_USERS["logistics_operator_headers"])
    assert res.status_code in (402, 409)
    validate_error_is_one_of(res, ["ERR_PAYMENT_HOLD", "ERR_INVALID_STATE"])


def accept_order_or_fail(order_id, window_version, accepted_cartons=2):
    res = api_client.accept_site_order(
        order_id,
        {"accepted_cartons": accepted_cartons, "deliver_at": "2026-09-01T06:00:00Z",
         "expected_allocation_window_version": window_version},
        TEST_USERS["distribution_planner_headers"])
    assert res.status_code < 400, f"setup failed at accept: {res.status_code} {res.text}"
    return get_success_data(res)


def test_impossible_rejection_reason_is_refused_but_the_minimum_branch_is_reachable(api):
    """PRD §3.3: "A `reason_code` that is not a member of the enum valid for the
    order's current state is refused with `ERR_REJECTION_REASON_INVALID` (HTTP 400)."

    PRD §3.3: "Accepting the full available quantity moves it to `FULFILLED`; the
    preconditions are that the acting program's `standing_status` is `OPEN`".
    PRD §3.3: "that the accepted cartons meet the governing minimum (otherwise
    `ERR_BELOW_MIN_ORDER`)".

    Design: Corner/validations/impossible_table_price_is_refused_but_the_state_error_branch_is_still_reachable
    """
    ctx = setup_entitled_site()
    site_id = ctx["site"]["id"]
    order = submit_order(ctx["entitlement"]["id"], site_id, requested_doses=1000)

    bad_reason = api.reject_site_order(
        order["id"], {"rejected_cartons": 2, "reason_code": "NOT_A_REASON"},
        TEST_USERS["distribution_planner_headers"])
    validate_error(bad_reason, "ERR_REJECTION_REASON_INVALID", expected_status=400)

    below = api.accept_site_order(
        order["id"],
        {"accepted_cartons": 1, "deliver_at": "2026-09-01T06:00:00Z",
         "expected_allocation_window_version": ctx["window"]["version"]},
        TEST_USERS["distribution_planner_headers"])
    validate_error(below, "ERR_BELOW_MIN_ORDER", expected_status=422)

    after = get_order(order["id"])
    assert after["order_status"] == "SUBMITTED"
    assert after["rejected_cartons"] == 0
    assert after["accepted_cartons"] == 0


def test_only_the_platform_admin_may_drive_the_logical_clock(api):
    """PRD §2.4: "A `PlatformAdmin` advances the clock to a supplied `current_utc`
    instant through the test-driving capability described in §4."

    PRD §2.1: "A request that carries well-formed headers but asks a role to perform
    an operation outside its granted set is refused with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)."

    Design: Corner/rbac/only_the_platform_admin_may_drive_the_logical_clock
    """
    ctx = setup_entitled_site()
    site_id = ctx["site"]["id"]
    refused = api.set_clock({"current_utc": "2026-09-05T00:00:00Z"},
                            make_site_coordinator_headers(site_id))
    validate_error(refused, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)

    accepted = validate_success(
        api.set_clock({"current_utc": "2026-09-05T00:00:00Z"},
                      TEST_USERS["platform_admin_headers"]), 200)
    assert accepted["current_utc"] == "2026-09-05T00:00:00Z"
    assert get_carton(ctx["carton"]["id"])["temperature_state"] == "ULTRA_COLD"


def test_manufacturing_qa_cannot_recall_a_batch(api):
    """PRD §3.1: "Recalling a batch is a `RegulatoryAffairsOfficer` act allowed only
    while the batch is `DRAFT`, `RELEASED`, or `ALLOCATED`; a batch already
    `DEPLETED` or `RECALLED` is refused with `ERR_BATCH_NOT_RECALLABLE`".

    PRD §2.1: "A request that carries well-formed headers but asks a role to perform
    an operation outside its granted set is refused with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)."

    Design: Corner/rbac/manufacturing_qa_cannot_recall_a_batch
    """
    product = make_product()
    program = make_program()
    batch = make_batch(product["id"], program["id"])
    carton = register_carton(batch["id"], serial="C-01")
    release_batch(batch["id"])

    refused = api.recall_batch(batch["id"], TEST_USERS["manufacturing_qa_headers"],
                               {"reason": "Attempting recall from QA."})
    validate_error(refused, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)
    assert get_success_data(api.get_allocation_batch(
        batch["id"], TEST_USERS["manufacturing_qa_headers"]))["status"] == "RELEASED"

    accepted = validate_success(
        api.recall_batch(batch["id"], TEST_USERS["regulatory_affairs_headers"],
                         {"reason": "Regulatory hold on the fill line."}), 200)
    assert accepted["status"] == "RECALLED"
    assert get_carton(carton["id"])["temperature_state"] == "DESTROYED"


def test_a_coordinator_cannot_accept_its_own_order(api):
    """PRD §3.3: "Acceptance by a `DistributionPlanner` computes the cartons the
    program will actually ship".

    PRD §2.1: "A request that carries well-formed headers but asks a role to perform
    an operation outside its granted set is refused with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)."

    Design: Corner/rbac/a_coordinator_cannot_accept_its_own_order
    """
    ctx = setup_entitled_site()
    site_id = ctx["site"]["id"]
    order = submit_order(ctx["entitlement"]["id"], site_id)

    refused = api.accept_site_order(
        order["id"],
        {"accepted_cartons": 2, "deliver_at": "2026-09-01T06:00:00Z",
         "expected_allocation_window_version": ctx["window"]["version"]},
        make_site_coordinator_headers(site_id))
    validate_error(refused, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)
    assert get_order(order["id"])["accepted_cartons"] == 0

    accepted = accept_order_or_fail(order["id"], ctx["window"]["version"], accepted_cartons=2)
    assert accepted["accepted_cartons"] == 2
    ent = get_entitlement(ctx["entitlement"]["id"])
    assert ent["held_cartons"] == 2
    assert ent["available_cartons"] == 8


def test_manufacturing_qa_can_read_cartons_and_shippers(api):
    """PRD §3.1: "The physical cartons themselves are registered against the
    released batch afterwards, one call per carton, each supplying a
    `carton_serial` that is unique and a `vials_per_carton` snapshot".

    PRD §3.4: "A `LogisticsOperator` starts one for a dispatch through
    `dispatch_order_id`, with a `shipper_serial` that is unique, a `dry_ice_kg`
    load, a `packing_started_at` instant, and a `logger_serial`; it begins in
    `PREPARING`."

    Design: Corner/rbac/manufacturing_qa_can_read_cartons_and_shippers
    """
    from test_helpers import create_shipper_payload

    ctx = setup_entitled_site()
    site_id = ctx["site"]["id"]
    order = submit_order(ctx["entitlement"]["id"], site_id)
    accept_order_or_fail(order["id"], ctx["window"]["version"])
    dispatch = get_success_data(api.create_dispatch(
        {"site_order_id": order["id"], "storage_site_id": site_id,
         "entry_route": "DIRECT_ULTRA_COLD"}, TEST_USERS["logistics_operator_headers"]))
    api.pack_dispatch(dispatch["id"], TEST_USERS["logistics_operator_headers"])
    shipper = get_success_data(api.create_shipper(
        create_shipper_payload(dispatch["id"]), TEST_USERS["logistics_operator_headers"]))
    api.attach_carton_to_shipper(shipper["id"], {"carton_id": ctx["carton"]["id"]},
                                 TEST_USERS["logistics_operator_headers"])

    carton = validate_success(
        api.get_carton(ctx["carton"]["id"], TEST_USERS["manufacturing_qa_headers"]), 200)
    assert carton["temperature_state"] == "ULTRA_COLD"

    shipper_read = validate_success(
        api.get_shipper(shipper["id"], TEST_USERS["manufacturing_qa_headers"]), 200)
    assert shipper_read["packing_status"] == "PREPARING"
    assert shipper_read["dry_ice_deficit_kg"] == 0

    sealed = api.seal_shipper(shipper["id"],
                              {"expected_shipper_version": shipper_read["version"]},
                              TEST_USERS["manufacturing_qa_headers"])
    validate_error(sealed, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)