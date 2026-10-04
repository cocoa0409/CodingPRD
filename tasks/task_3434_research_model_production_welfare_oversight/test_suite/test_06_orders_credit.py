"""Order intake and credit: quantity floor, delivery lead time, quote locking,
GROSS vs NET_BILLED credit positions, cancel compensation, the
SOURCING<->BACKORDERED supply loop, and DELIVERED lockdown.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    allocate_order_to_cohort,
    api_client,
    assert_order,
    backorder_order,
    compute_expected_quote,
    create_active_customer,
    create_catalog_strain,
    create_order_payload,
    create_order_submitted,
    make_customer_headers,
    read_cohort,
    read_customer,
    read_order,
    setup_colony_with_cohorts,
    setup_delivered_order,
    setup_production_site,
    setup_sourcing_order,
    source_order,
    transition_order,
    validate_error,
    validate_success,
)

_ADMIN = TEST_USERS["admin_headers"]
_FM = TEST_USERS["facility_manager_headers"]


def test_zero_total_quantity_order_rejected():
    """PRD Section 3.6: "the requested `quantity_male` and `quantity_female`
    (each at least 0, and their sum must be at least 1 — a zero-quantity order
    is `ERR_INVALID_QUANTITY`, HTTP 422)".

    Design: Difficulty/boundary_precision_check/zero_total_quantity_order_rejected
    """
    strain = create_catalog_strain()
    customer = create_active_customer()
    payload = create_order_payload(
        strain["id"], quantity_male=0, quantity_female=0
    )
    resp = api_client.create_order(payload, make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_QUANTITY)


def test_one_animal_quantity_order_accepted():
    """PRD Section 3.6: "the requested `quantity_male` and `quantity_female`
    (each at least 0, and their sum must be at least 1 — a zero-quantity order
    is `ERR_INVALID_QUANTITY`, HTTP 422)" and "A valid order is born in
    `SUBMITTED` with `quoted_total_cents` still null and both `allocated_male`
    and `allocated_female` at 0."

    Design: Difficulty/boundary_precision_check/zero_total_quantity_order_rejected
    """
    strain = create_catalog_strain()
    customer = create_active_customer()
    order = create_order_submitted(
        customer, strain["id"], quantity_male=1, quantity_female=0
    )
    assert order["status"] == "SUBMITTED"
    assert order["quantity_male"] + order["quantity_female"] == 1
    assert order["quoted_total_cents"] is None
    assert order["allocated_male"] == 0
    assert order["allocated_female"] == 0
    assert_order(order)


def test_source_cancel_conserves_gross_exposure():
    """PRD Section 3.7: "Cancelling from `SOURCING`, `BACKORDERED`, or
    `ALLOCATED` releases all `RESERVED` allocations — decrementing cohort
    reserved counts and recomputing cohort statuses — and decreases the
    customer's `credit_exposure_cents` by the order's `quoted_total_cents`,
    the GROSS compensation."

    Design: Difficulty/compensating_invariant/source_cancel_conserves_gross_exposure
    """
    bundle = setup_sourcing_order(
        quantity_male=5, quantity_female=5,
        cohorts=[{"count_male": 5, "count_female": 5}],
    )
    customer = bundle["customer"]
    order = bundle["order"]

    owner = read_customer(customer["id"])
    assert owner["credit_exposure_cents"] == 10000

    cancelled = transition_order(
        order["id"], "CANCELLED", make_customer_headers(customer["id"])
    )
    assert cancelled["status"] == "CANCELLED"

    owner = read_customer(customer["id"])
    assert owner["credit_exposure_cents"] == 0
    assert owner["outstanding_balance_cents"] == 0


def test_source_cancel_locks_then_preserves_quote():
    """PRD Section 3.6: "A successful sourcing transition computes and stores
    `quoted_total_cents`, raises the customer's GROSS exposure by that amount".

    Design: Difficulty/compensating_invariant/source_cancel_conserves_gross_exposure
    """
    bundle = setup_sourcing_order(
        quantity_male=5, quantity_female=5,
        cohorts=[{"count_male": 5, "count_female": 5}],
    )
    customer = bundle["customer"]
    order = bundle["order"]

    # 10 animals * 1000 cents, no tier, no surcharges: quote locked at 10000.
    assert order["quoted_total_cents"] == compute_expected_quote(
        10, 1000, "IMMUNOCOMPETENT", "MPF"
    )
    assert order["quoted_total_cents"] == 10000

    transition_order(order["id"], "CANCELLED", make_customer_headers(customer["id"]))
    order = read_order(order["id"])
    assert order["status"] == "CANCELLED"
    assert order["quoted_total_cents"] == 10000


def test_customer_exposure_gross_vs_net():
    """PRD Section 3.6: "The `outstanding_balance_cents` figure — the
    NET_BILLED variant — sums `quoted_total_cents` over the customer's orders
    in `DELIVERED` only" and "The `credit_exposure_cents` figure — the GROSS
    variant — sums `quoted_total_cents` over orders in `SOURCING`,
    `BACKORDERED`, `ALLOCATED`, `SCHEDULED`, `SHIPPED`, and `DELIVERED`".

    Design: Difficulty/dual_variant_calc/customer_exposure_gross_vs_net
    """
    bundle = setup_delivered_order(
        quantity_male=10, quantity_female=10,
        cohorts=[{"count_male": 20, "count_female": 20, "hold": True}],
    )
    customer = bundle["customer"]
    order1 = bundle["order"]
    assert order1["status"] == "DELIVERED"

    order2 = create_order_submitted(
        customer, bundle["site"]["strain"]["id"],
        quantity_male=15, quantity_female=15,
    )
    order2 = source_order(order2)
    assert order2["status"] == "SOURCING"

    owner = read_customer(customer["id"])
    # NET_BILLED: only the DELIVERED order1 (20 animals * 1000 = 20000).
    assert owner["outstanding_balance_cents"] == 20000
    # GROSS: DELIVERED 20000 + SOURCING 30000.
    assert owner["credit_exposure_cents"] == 50000


def test_customer_exposure_variants_track_locked_quotes():
    """PRD Section 3.6: "Identical order data therefore always yields a
    NET_BILLED figure less than or equal to the GROSS figure."
    PRD Section 3.8: "the order then advances from `SHIPPED` to `DELIVERED`,
    and billing posts there — the customer's `outstanding_balance_cents` rises
    by the order's `quoted_total_cents`, the NET_BILLED event."

    Design: Difficulty/dual_variant_calc/customer_exposure_gross_vs_net
    """
    bundle = setup_delivered_order(
        quantity_male=10, quantity_female=10,
        cohorts=[{"count_male": 20, "count_female": 20, "hold": True}],
    )
    customer = bundle["customer"]
    order1 = read_order(bundle["order"]["id"])
    assert order1["quoted_total_cents"] == compute_expected_quote(
        20, 1000, "IMMUNOCOMPETENT", "MPF"
    )
    assert order1["quoted_total_cents"] == 20000

    order2 = create_order_submitted(
        customer, bundle["site"]["strain"]["id"],
        quantity_male=15, quantity_female=15,
    )
    order2 = source_order(order2)
    assert order2["quoted_total_cents"] == compute_expected_quote(
        30, 1000, "IMMUNOCOMPETENT", "MPF"
    )
    assert order2["quoted_total_cents"] == 30000

    owner = read_customer(customer["id"])
    assert owner["outstanding_balance_cents"] <= owner["credit_exposure_cents"]
    assert owner["outstanding_balance_cents"] == order1["quoted_total_cents"]
    assert (
        owner["credit_exposure_cents"]
        == order1["quoted_total_cents"] + order2["quoted_total_cents"]
    )


def test_order_sourcing_backorder_supply_cycle_reaches_allocated():
    """PRD Section 3.7: "A `FacilityManager` may park a `SOURCING` order into
    `BACKORDERED` and later retry sourcing from `BACKORDERED` back to
    `SOURCING`; the back-edge keeps every `RESERVED` allocation in place."
    PRD Section 3.7: "when the allocated totals first equal the requested
    `quantity_male` and `quantity_female`, the order auto-transitions to
    `ALLOCATED` — from `SOURCING` or from `BACKORDERED` alike."

    Design: Difficulty/non_linear_state_machine/order_sourcing_backorder_supply_cycle
    """
    bundle = setup_sourcing_order(quantity_male=5, quantity_female=5)
    order = bundle["order"]
    cohort = bundle["cohorts"][0]
    assert order["status"] == "SOURCING"

    order = backorder_order(order)
    assert order["status"] == "BACKORDERED"
    order = source_order(order)
    assert order["status"] == "SOURCING"

    allocation, order = allocate_order_to_cohort(order, cohort, 5, 5)
    assert order["status"] == "ALLOCATED"
    assert order["allocated_male"] == 5
    assert order["allocated_female"] == 5
    assert allocation["status"] == "RESERVED"


def test_order_sourcing_backorder_supply_cycle_cohort_side():
    """PRD Section 3.7: "On the cohort, `reserved_male` and `reserved_female`
    rise by the allocated quantities, and the status machine advances: a
    `HOLD` cohort becomes `PARTIALLY_ALLOCATED`".

    Design: Difficulty/non_linear_state_machine/order_sourcing_backorder_supply_cycle
    """
    bundle = setup_sourcing_order(quantity_male=5, quantity_female=5)
    order = bundle["order"]
    cohort = bundle["cohorts"][0]

    order = backorder_order(order)
    order = source_order(order)
    _allocation, order = allocate_order_to_cohort(order, cohort, 5, 5)
    assert order["status"] == "ALLOCATED"

    cohort = read_cohort(cohort["id"])
    assert cohort["status"] == "PARTIALLY_ALLOCATED"
    assert cohort["reserved_male"] == 5
    assert cohort["reserved_female"] == 5


def test_credit_limit_equality_then_exceed():
    """PRD Section 3.6: "the credit check compares figures — the customer's
    current `credit_exposure_cents` plus this order's freshly computed quote
    must not strictly exceed `credit_limit_cents`; equality passes, and a
    strictly greater result is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`
    (HTTP 422)."

    Design: Corner/calculations/credit_limit_equality_then_exceed
    """
    site = setup_production_site()
    setup_colony_with_cohorts(
        site, breeding_pair_count=25, cohorts=[{"count_male": 5, "count_female": 5}]
    )
    customer = create_active_customer(credit_limit_cents=90000)
    strain_id = site["strain"]["id"]

    # 100 animals * 1000 cents with the 10% tier -> exactly 90000 == limit.
    order1 = create_order_submitted(
        customer, strain_id, quantity_male=50, quantity_female=50
    )
    order1 = source_order(order1)
    assert order1["status"] == "SOURCING"
    assert order1["quoted_total_cents"] == compute_expected_quote(
        100, 1000, "IMMUNOCOMPETENT", "MPF"
    )
    assert read_customer(customer["id"])["credit_exposure_cents"] == 90000

    # 90000 + 1000 > 90000: strictly greater, so the second sourcing fails.
    order2 = create_order_submitted(
        customer, strain_id, quantity_male=1, quantity_female=0
    )
    resp = api_client.transition_order(order2["id"], {"target_state": "SOURCING"}, _FM)
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)


def test_delivery_lead_below_minimum_rejected():
    """PRD Section 3.6: "Submission requires the delivery date to be at least
    14 days after the current logical clock — the platform's minimum order
    lead time — and an earlier date is rejected with
    `ERR_DELIVERY_WINDOW_INFEASIBLE` (HTTP 422)."

    Design: Corner/validations/delivery_lead_below_minimum_rejected
    """
    strain = create_catalog_strain()
    customer = create_active_customer()
    # 2026-09-05 is 4 days after the 2026-09-01 logical clock: below the
    # 14-day minimum lead time.
    payload = create_order_payload(
        strain["id"], required_delivery_date="2026-09-05T00:00:00Z"
    )
    resp = api_client.create_order(payload, make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_DELIVERY_WINDOW_INFEASIBLE)


def test_order_delivered_cannot_return_to_sourcing():
    """PRD Section 2.7: "And any transition or action requested against a
    resource whose current state does not declare that transition — including
    any further transition out of a terminal state — is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."
    PRD Section 3.8: "the order then advances from `SHIPPED` to `DELIVERED`".

    Design: Corner/state_machines/order_delivered_cannot_return_to_sourcing
    """
    bundle = setup_delivered_order(quantity_male=2, quantity_female=2)
    order = bundle["order"]
    assert order["status"] == "DELIVERED"

    resp = api_client.transition_order(order["id"], {"target_state": "SOURCING"}, _FM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert read_order(order["id"])["status"] == "DELIVERED"
