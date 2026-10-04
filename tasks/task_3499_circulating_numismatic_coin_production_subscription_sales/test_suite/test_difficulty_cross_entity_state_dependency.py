"""Difficulty rule cross_entity_state_dependency (PRD §3.3, §3.6, §3.8): one
entity's permitted transition is gated on another entity's current state — a
run cannot start while its Federal Reserve order is CANCELLED, a product's
clock-driven release waits for its program to open, and an allocation offer
names an authorized purchaser that must stand APPROVED."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_success_data,
    make_collector_headers,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_order_payload
from test_helpers.fixtures import (
    create_authorized_purchaser,
    create_collector,
    create_product,
    create_run,
    get_bullion_issue,
    set_ap_status,
    set_clock,
    setup_approved_program,
    setup_bullion_issue,
    setup_circulating_base,
)
from test_helpers.factories import create_allocation_payload

LIAISON = TEST_USERS["fed_liaison_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
MANAGER = TEST_USERS["program_manager_headers"]


def test_run_start_blocked_when_fed_order_cancelled(api):
    """PRD §3.3: "The linked order must be in `SCHEDULED` or `FULFILLING`;
    starting a run that is not in `PLANNED` or `REWORK`, or whose order sits in
    any other state, is rejected with `ERR_RUN_NOT_STARTABLE` (422)."
    PRD §3.1: "A `FedLiaison` may cancel an order in `SUBMITTED` or
    `SCHEDULED`; cancelling a `SCHEDULED` order cascades, moving every linked
    run still in `PLANNED` or `REWORK` to `CANCELLED` and incrementing each such
    run's own `version`."

    Design: Difficulty/cross_entity_state_dependency/run_start_blocked_when_fed_order_cancelled
    """
    # Blanks fully stocked (1760000 >= 50000), so only the cross-entity
    # order-state gate can fail on start.
    denomination, lot, fed_order = setup_circulating_base(
        api, quantity_ordered_pieces=50000)
    resp = api.cancel_fed_order(fed_order["id"], LIAISON)
    validate_success(resp)
    run = create_run(
        api, fed_order["id"], facility="DENVER", press_line="P3",
        planned_start="2026-10-07T08:00:00Z", planned_end="2026-10-07T12:00:00Z",
        planned_quantity=50000)

    resp = api.start_production_run(run["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_RUN_NOT_STARTABLE)
    run = get_success_data(api.get_production_run(run["id"], PLANNER))
    assert run["status"] == "PLANNED"


def test_product_held_scheduled_until_program_on_sale(api):
    """PRD §3.6: "When a clock-set sweep finds the logical clock at or past a
    `SCHEDULED` product's `release_datetime`, the product moves to `ON_SALE` —
    unless it belongs to a program that is not yet `ON_SALE`, in which case it
    waits in `SCHEDULED` until the program opens."
    PRD §3.6: "The `product_id` must resolve to an existing product
    (`ERR_UNKNOWN_PRODUCT`, 422) that is in `ON_SALE` or `SOLD_OUT`; orders
    against `SCHEDULED` or `WITHDRAWN` products are rejected with
    `ERR_PRODUCT_NOT_ORDERABLE` (422)."

    Design: Difficulty/cross_entity_state_dependency/product_held_scheduled_until_program_on_sale
    """
    program = setup_approved_program(
        api, name="Gated Program", statute_reference="PL 119-11",
        max_mintage_legal=5000, surcharge_cents_per_unit=500,
        beneficiary_name="Gate Foundation", beneficiary_cap_cents=100000,
        direct_costs_cents=1000,
        sales_window_start="2026-09-15T00:00:00Z",
        sales_window_end="2026-12-31T00:00:00Z")
    product = create_product(
        api, product_code="CX-GATE", program_id=program["id"],
        product_family="PGATE", product_type="COMMEMORATIVE", price_cents=3000,
        mintage_limit=100, household_order_limit=10,
        release_datetime="2026-09-10T00:00:00Z")

    # Past the product's release_datetime but before the program's window
    # start: the sweep must NOT flip the product while its program is only
    # APPROVED_FOR_SALE.
    set_clock(api, "2026-09-12T00:00:00Z")
    product = get_success_data(api.get_product(product["id"], MANAGER))
    assert product["status"] == "SCHEDULED"

    c1 = create_collector(api, full_name="Gate Buyer", email="gate@example.com",
                          household_id="HH-G")
    resp = api.create_order(
        create_order_payload(product_id=product["id"], quantity=1),
        make_collector_headers(c1["id"]))
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_ORDERABLE)


def test_allocation_offer_blocked_when_ap_terminated(api):
    """PRD §3.8: "A `MintDirector` manages standing through set-status
    transitions carrying a `to_status`: `APPROVED ↔ SUSPENDED` in both
    directions, and `APPROVED` or `SUSPENDED` to `TERMINATED`, which is
    terminal."
    PRD §3.8: "The request names an `authorized_purchaser_id` — the firm must
    exist and be in `APPROVED`, otherwise `ERR_AP_NOT_APPROVED` (422) — a
    `quantity_units` of at least 1 (`ERR_QUANTITY_INVALID`, 400) that does not
    exceed the issue's `remaining_pool_units` (`ERR_POOL_INSUFFICIENT`, 422),
    and the OCC field `expected_bullion_issue_version` described in §2.6."

    Design: Difficulty/cross_entity_state_dependency/allocation_offer_blocked_when_ap_terminated
    """
    issue = setup_bullion_issue(api, name="AGE 2026", total_pool_units=1000)
    ap = create_authorized_purchaser(api, name="Doomed Dealer", tier="T3")
    set_ap_status(api, ap["id"], "TERMINATED")

    # The pool has ample units; only the cross-entity AP-status gate fails.
    resp = api.create_allocation(
        issue["id"],
        create_allocation_payload(
            authorized_purchaser_id=ap["id"], quantity_units=5,
            expected_bullion_issue_version=issue["version"]),
        MANAGER)
    validate_error(resp, ApiErrorId.ERR_AP_NOT_APPROVED)

    issue = get_bullion_issue(api, issue["id"])
    assert issue["remaining_pool_units"] == 1000
