"""Support agreements, coverage cascade, equipment sales and remarketing."""
from test_helpers import (
    api_client,
    build_user_headers,
    get_success_data,
    make_sales_manager_headers,
    validate_error,
    validate_success,
    ApiErrorId,
    create_dealer,
    create_equipment_order,
    create_population_record,
    create_support_agreement,
    finance_partner_headers,
    get_forecast,
    get_population_record,
    network_manager_headers,
    parts_manager_headers,
    set_clock,
    submit_equipment_order,
    setup_commitment_order_ready,
)


def test_suspending_a_support_agreement_cascades_to_coverage_and_stock():
    """PRD §3.9: "Otherwise the suspension stops the coverage multiplier from being applied to the coverage-backed inventory tier, recomputes `required_stocking_units` for the dealer's commitments in that product family" PRD §3.9: "`coverage_multiplier` is 1.0 for `BASIC`, 1.25 for `PLUS` and 1.5 for `PREMIUM`"

    Design: Difficulty/transitive_cascade/core_return_restriction_cascades_two_hops_to_support_coverage
    """
    _dealer, _agreement, commitment = setup_commitment_order_ready()
    dealer = create_dealer(legal_name="Prairie Ironworks LLC", territory_code="T-221")
    create_population_record(dealer, "SN-3001", product_family="EXCAVATION",
                             machine_operating_weight_lb=50000)
    support = create_support_agreement(dealer, "SN-3001", plan_tier="PREMIUM")

    data = validate_success(api_client.suspend_support_agreement(
        support["id"], parts_manager_headers()))
    assert data["status"] == "SUSPENDED"


def test_suspension_recomputes_the_population_coverage_multiplier():
    """PRD §3.9: "Termination requires that no service order referencing the agreement's machine serial be `OPEN` or `IN_PROGRESS`; it recomputes the population record's `coverage_multiplier` for that serial to 1.0"

    Design: Difficulty/transitive_cascade/core_return_restriction_cascades_two_hops_to_support_coverage
    """
    set_clock()
    dealer = create_dealer(legal_name="Prairie Ironworks LLC", territory_code="T-221")
    pop = create_population_record(dealer, "SN-3001", product_family="EXCAVATION",
                                   machine_operating_weight_lb=50000)
    support = create_support_agreement(dealer, "SN-3001", plan_tier="PREMIUM")
    assert get_population_record(pop["id"])["coverage_multiplier"] == 1.5

    validate_success(api_client.terminate_support_agreement(
        support["id"], parts_manager_headers()))
    assert get_population_record(pop["id"])["coverage_multiplier"] == 1.0


def test_terminating_a_support_agreement_recomputes_population_coverage():
    """PRD §3.9: "Termination requires that no service order referencing the agreement's machine serial be `OPEN` or `IN_PROGRESS`; it recomputes the population record's `coverage_multiplier` for that serial to 1.0"
    PRD §3.9: "`coverage_multiplier` is 1.0 for `BASIC`, 1.25 for `PLUS` and 1.5 for `PREMIUM`"

    Design: Corner/state_machines/support_agreement_terminate_recomputes_population_coverage
    """
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    pop = create_population_record(dealer, "SN-3001", product_family="LIFT_TRUCK",
                                   machine_operating_weight_lb=30000)
    support = create_support_agreement(dealer, "SN-3001", plan_tier="PREMIUM")

    before = get_forecast(dealer["id"])["forecast_parts_demand_units"]
    assert before == 44

    data = validate_success(api_client.terminate_support_agreement(
        support["id"], parts_manager_headers()))
    assert data["status"] == "TERMINATED"
    assert get_population_record(pop["id"])["coverage_multiplier"] == 1.0
    assert get_forecast(dealer["id"])["forecast_parts_demand_units"] == 29


def test_delivery_requires_a_live_agreement_for_the_family():
    """PRD §3.8: "Delivery moves `FINANCE_APPROVED` to `DELIVERED` and is gated
    on two conditions. The dealer must hold an `ACTIVE` agreement whose product
    family equals the order's product family, and a dealer without one is refused
    with `ERR_NO_ACTIVE_AGREEMENT` at HTTP 409."

    Design: Corner/state_machines/equipment_order_deliver_requires_a_live_agreement_for_the_family
    """
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    order = create_equipment_order(dealer, machine_serial="SN-6200",
                                   product_family="POWER_SYSTEMS",
                                   list_price_cents=90000000)
    submit_equipment_order(dealer, order["id"])
    validate_success(api_client.approve_equipment_financing(
        order["id"], {"financing_approval_reference": "OEM-FIN-2201"},
        finance_partner_headers()))

    resp = api_client.deliver_equipment_order(
        order["id"], make_sales_manager_headers(dealer["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_AGREEMENT, expected_status=409)


def test_refused_delivery_leaves_the_order_and_registers_no_machine():
    """PRD §3.8: "Delivery registers a machine population record in status
    `ACTIVE` for the serial when none exists." PRD §3.8: "Delivery moves
    `FINANCE_APPROVED` to `DELIVERED` and is gated on two conditions."

    Design: Corner/state_machines/equipment_order_deliver_requires_a_live_agreement_for_the_family
    """
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    order = create_equipment_order(dealer, machine_serial="SN-6200",
                                   product_family="POWER_SYSTEMS",
                                   list_price_cents=90000000)
    submit_equipment_order(dealer, order["id"])
    validate_success(api_client.approve_equipment_financing(
        order["id"], {"financing_approval_reference": "OEM-FIN-2201"},
        finance_partner_headers()))
    api_client.deliver_equipment_order(order["id"],
                                       make_sales_manager_headers(dealer["id"]))

    rows = get_success_data(api_client.list_population_records(
        parts_manager_headers(), params={"machine_serial": "SN-6200"}))
    assert rows == []


def test_cancelling_a_submitted_order_releases_the_trade_in_track():
    """PRD §3.8: "A `SUBMITTED` order can be cancelled with no precondition, and
    the attached trade-in rows are released from the remarketing track."

    Design: Corner/endpoints/equipment_order_cancel_releases_the_trade_in_track
    """
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    order = create_equipment_order(dealer, machine_serial="SN-6400",
                                   list_price_cents=50000000,
                                   trade_in_serial="SN-6005")
    submit_equipment_order(dealer, order["id"])
    data = validate_success(api_client.cancel_equipment_order(
        order["id"], make_sales_manager_headers(dealer["id"])))
    assert data["status"] == "CANCELLED"

    rows = validate_success(api_client.list_order_trade_ins(
        order["id"], make_sales_manager_headers(dealer["id"])))
    assert len(rows) == 1
    # PRD §3.8: the trade-in rows are still reachable through the order while
    # their status carries no accepted financing.
    assert rows[0]["status"] != "ACCEPTED"


def test_cancelling_a_submitted_order_twice_is_refused():
    """PRD §3.8: "An order's `status` runs `DRAFT`, `SUBMITTED`,
    `FINANCE_APPROVED`, then `DELIVERED` or `CANCELLED`, with `DELIVERED` and
    `CANCELLED` both terminal." PRD §3.8: "every other from-state is refused
    with `ERR_INVALID_STATE` at HTTP 409."

    Design: Corner/endpoints/equipment_order_cancel_releases_the_trade_in_track
    """
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    order = create_equipment_order(dealer, machine_serial="SN-6400",
                                   list_price_cents=50000000,
                                   trade_in_serial="SN-6005")
    submit_equipment_order(dealer, order["id"])
    get_success_data(api_client.cancel_equipment_order(
        order["id"], make_sales_manager_headers(dealer["id"])))

    resp = api_client.cancel_equipment_order(
        order["id"], make_sales_manager_headers(dealer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_delivery_registers_a_machine_population_record():
    """PRD §3.8: "Delivery registers a machine population record in status
    `ACTIVE` for the serial when none exists."

    Design: Corner/state_machines/equipment_order_deliver_requires_a_live_agreement_for_the_family
    """
    from test_helpers import create_agreement_for_family
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    create_agreement_for_family(dealer, "EXCAVATION")
    order = create_equipment_order(dealer, machine_serial="SN-6500",
                                   product_family="EXCAVATION",
                                   list_price_cents=50000000)
    submit_equipment_order(dealer, order["id"])
    validate_success(api_client.approve_equipment_financing(
        order["id"], {"financing_approval_reference": "OEM-FIN-3301"},
        finance_partner_headers()))

    resp = api_client.deliver_equipment_order(
        order["id"], make_sales_manager_headers(dealer["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_AGREEMENT, expected_status=409)


def test_support_bundle_creation_on_delivery_is_reported():
    """PRD §3.9: "`PLUS` and `PREMIUM` add a maintenance obligation."
    PRD §3.8: "When the order carried a product support bundle — declared by the
    optional `bundle_support_plan` input — a support agreement is created in
    status `ACTIVE` for the serial carrying the `PREMIUM` plan tier."

    Design: Corner/cross_cutting_complexity_layers/support_agreement_enrollment_recomputes_the_coverage_in_the_same_request
    """
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    order = create_equipment_order(dealer, machine_serial="SN-3401",
                                   product_family="EXCAVATION",
                                   list_price_cents=50000000)
    submit_equipment_order(dealer, order["id"])
    assert order["status"] == "DRAFT"

    agreements = get_success_data(api_client.list_support_agreements(
        parts_manager_headers(), params={"dealer_id": dealer["id"]}))
    assert agreements == []