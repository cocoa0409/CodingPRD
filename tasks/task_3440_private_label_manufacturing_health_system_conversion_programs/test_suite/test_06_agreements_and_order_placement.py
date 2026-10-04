"""Prime vendor agreements and distribution-order placement: exclusivity,
lazy expiry, temporal window, order multiples, pricing, fiscal cap."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_prime_vendor_agreement,
    create_agreement,
    create_agreement_payload,
    create_facility,
    create_order_payload,
    create_product,
    find_order,
    get_agreement,
    make_facility_director_headers,
    place_order,
    receive_order,
    setup_facility_with_agreement,
    setup_suspended_agreement_scenario,
    ship_order,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_second_active_agreement_409(api):
    """PRD §3.5: "at most one non-`EXPIRED` agreement may exist per facility, so
    creating a second live agreement for a facility that already has an `ACTIVE`
    or `SUSPENDED` one is rejected with `ERR_ACTIVE_AGREEMENT_EXISTS`
    (HTTP 409)."

    Design: Corner/validations/second_active_agreement_rejected
    """
    facility = create_facility()
    create_agreement(facility["id"], committed_fill_rate_pct=95.0)
    resp = api.create_prime_vendor_agreement(
        create_agreement_payload(
            facility["id"],
            committed_fill_rate_pct=90.0,
            deliveries_per_week=2,
            annual_commitment_cents=50000,
        ),
        headers=ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_ACTIVE_AGREEMENT_EXISTS.value, 409)


def test_pva_lazy_expiry_blocks_new_orders(api):
    """PRD §3.5: "its lazy expiry is evaluated first — if the current logical
    clock has passed `end_date` the agreement transitions to `EXPIRED` on the
    spot — and the order is rejected with `ERR_AGREEMENT_NOT_ACTIVE` (HTTP 409)
    unless the agreement is `ACTIVE` after that evaluation." PRD §3.6: "any read
    or write of the agreement while the logical clock is past `end_date` lazily
    transitions it from `ACTIVE` or `SUSPENDED` to the terminal `EXPIRED`".

    Design: Corner/state_machines/pva_lazy_expiry_blocks_new_orders
    """
    facility = create_facility()
    product = create_product(sku="AJ-1")
    agreement = create_agreement(
        facility["id"], start_date="2026-01-01", end_date="2026-08-31"
    )
    resp = api.create_distribution_order(
        create_order_payload(
            agreement["id"],
            [{"product_id": product["id"], "ordered_qty": 10}],
        ),
        headers=make_facility_director_headers(facility["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value, 409)
    assert get_agreement(agreement["id"])["status"] == "EXPIRED"


def test_order_date_out_of_window_422(api):
    """PRD §3.5: "`requested_delivery_date` must fall strictly after the current
    logical-clock date and within the agreement's `start_date`-to-`end_date`
    window inclusive of both endpoints, otherwise
    `ERR_ORDER_DATE_OUT_OF_WINDOW` (HTTP 422)." The default logical clock reads
    2026-09-01 (§2.4), so a same-day delivery date fails the strictly-after
    rule.

    Design: Corner/validations/order_date_out_of_window_rejected
    """
    ctx = setup_facility_with_agreement()
    resp = api.create_distribution_order(
        create_order_payload(
            ctx["agreement"]["id"],
            [{"product_id": ctx["product"]["id"], "ordered_qty": 10}],
            requested_delivery_date="2026-09-01",
        ),
        headers=make_facility_director_headers(ctx["facility"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_DATE_OUT_OF_WINDOW.value, 422)


def test_order_multiple_violation_422(api):
    """PRD §3.5: "each line's `ordered_qty` must be a multiple of its product's
    `order_multiple` unless low-unit-of-measure terms apply — that is, unless
    the product is `lum_eligible` and the agreement carries `lum_commitment` —
    otherwise `ERR_ORDER_MULTIPLE_VIOLATION` (HTTP 422)."

    Design: Corner/validations/order_multiple_violation_without_lum
    """
    facility = create_facility()
    product = create_product(sku="VM-1", order_multiple=6, lum_eligible=False,
                             each_price_cents=10)
    agreement = create_agreement(facility["id"], committed_fill_rate_pct=90.0)
    resp = api.create_distribution_order(
        create_order_payload(
            agreement["id"],
            [{"product_id": product["id"], "ordered_qty": 10}],
        ),
        headers=make_facility_director_headers(facility["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_MULTIPLE_VIOLATION.value, 422)


def test_order_discontinued_product_422(api):
    """PRD §3.5: "Then referential health: every referenced product's
    `availability` must be `ACTIVE`, otherwise `ERR_PRODUCT_NOT_ORDERABLE`."

    Design: Corner/validations/order_discontinued_product_rejected
    """
    facility = create_facility()
    product = create_product(sku="OD-1", availability="DISCONTINUED")
    agreement = create_agreement(facility["id"], committed_fill_rate_pct=90.0)
    resp = api.create_distribution_order(
        create_order_payload(
            agreement["id"],
            [{"product_id": product["id"], "ordered_qty": 10}],
        ),
        headers=make_facility_director_headers(facility["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_ORDERABLE.value, 422)


def test_duplicate_order_line_409(api):
    """PRD §3.5: "Structural rules follow: no `product_id` may repeat across
    `lines` (`ERR_DUPLICATE_ORDER_LINE`, HTTP 409)".

    Design: Corner/validations/duplicate_order_line_rejected
    """
    facility = create_facility()
    product = create_product(sku="DO-1")
    agreement = create_agreement(facility["id"], committed_fill_rate_pct=90.0)
    resp = api.create_distribution_order(
        create_order_payload(
            agreement["id"],
            [
                {"product_id": product["id"], "ordered_qty": 5},
                {"product_id": product["id"], "ordered_qty": 7},
            ],
        ),
        headers=make_facility_director_headers(facility["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ORDER_LINE.value, 409)


def test_order_commitment_exceeded_422(api):
    """PRD §3.5: "The fiscal cap then bites: the agreement's `spent_cents` plus
    this computed `total_price_cents` must not exceed
    `annual_commitment_cents`, otherwise the order is rejected with
    `ERR_COMMITMENT_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/order_create_commitment_exceeded_fires
    """
    facility = create_facility()
    product = create_product(sku="VC-1", each_price_cents=100)
    agreement = create_agreement(
        facility["id"],
        committed_fill_rate_pct=90.0,
        annual_commitment_cents=50000,
    )
    resp = api.create_distribution_order(
        create_order_payload(
            agreement["id"],
            [{"product_id": product["id"], "ordered_qty": 600}],
        ),
        headers=make_facility_director_headers(facility["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_COMMITMENT_EXCEEDED.value, 422)


def test_order_price_lum_disabled_falls_back_to_case_rounding(api):
    """PRD §3.5: "For each line, when the product is `lum_eligible` and the
    agreement carries `lum_commitment`, the billable quantity is exactly the
    `ordered_qty`; otherwise the billable quantity is the `ordered_qty` rounded
    up to the next whole multiple of the product's `units_per_case` — ceiling
    division applied per line, before any summation."

    Design: Corner/calculations/order_price_lum_disabled_falls_back_to_case_rounding
    """
    facility = create_facility()
    product = create_product(
        sku="LD-1", brand_type="PRIVATE_LABEL", units_per_case=12,
        each_price_cents=80, lum_eligible=True,
    )
    agreement = create_agreement(
        facility["id"], committed_fill_rate_pct=90.0, lum_commitment=False
    )
    order = place_order(
        agreement["id"],
        facility["id"],
        [{"product_id": product["id"], "ordered_qty": 7}],
    )
    # ceil(7/12) = 1 case x 12 x 80 cents = 960; LUM relief denied.
    assert order["total_price_cents"] == 960


def test_order_price_per_line_case_ceiling_total(api):
    """PRD §3.5: "Pricing is computed line by line and never rounded at the
    order level." — line 1: ceil(30/12) x 12 x 250 = 9000; line 2 (LUM applies):
    7 x 80 = 560; the order total is the plain sum, 9560, not the 8060 that
    raw each-extension would give.

    Design: Difficulty/combinatorial_formula/order_price_per_line_case_ceiling
    """
    facility = create_facility()
    case_product = create_product(
        sku="PC-1", name="Suture case", category="SURGICAL_INSTRUMENTS",
        sterile=True, device_class="CLASS_II", units_per_case=12,
        each_price_cents=250, lum_eligible=False,
    )
    lum_product = create_product(
        sku="PL-1", name="Bandage each", brand_type="PRIVATE_LABEL",
        sterile=True, units_per_case=10, each_price_cents=80, lum_eligible=True,
    )
    agreement = create_agreement(
        facility["id"], committed_fill_rate_pct=90.0, lum_commitment=True
    )
    resp = api.create_distribution_order(
        create_order_payload(
            agreement["id"],
            [
                {"product_id": case_product["id"], "ordered_qty": 30},
                {"product_id": lum_product["id"], "ordered_qty": 7},
            ],
        ),
        headers=make_facility_director_headers(facility["id"]),
    )
    order = validate_success(resp, 201)
    assert order["total_price_cents"] == 9560
    assert order["total_price_cents"] != 8060  # raw each-extension is forbidden


def test_order_price_case_ceiling_single_line(api):
    """PRD §3.5: "Each line total is its billable quantity times the product's
    `each_price_cents`, and the order's `total_price_cents` is the plain sum of
    those line totals in integer cents with no further rounding." A lone
    non-case-aligned line proves the per-line ceiling in isolation:
    ceil(30/12) x 12 x 250 = 9000.

    Design: Difficulty/combinatorial_formula/order_price_per_line_case_ceiling
    """
    facility = create_facility()
    case_product = create_product(
        sku="PC-9", category="SURGICAL_INSTRUMENTS", sterile=True,
        device_class="CLASS_II", units_per_case=12, each_price_cents=250,
    )
    agreement = create_agreement(
        facility["id"], committed_fill_rate_pct=90.0, lum_commitment=True
    )
    order = place_order(
        agreement["id"],
        facility["id"],
        [{"product_id": case_product["id"], "ordered_qty": 30}],
    )
    assert order["total_price_cents"] == 9000


def test_order_create_on_suspended_blocked_but_receive_allowed(api):
    """PRD §3.5: "the order is rejected with `ERR_AGREEMENT_NOT_ACTIVE`
    (HTTP 409) unless the agreement is `ACTIVE` after that evaluation." A
    `SUSPENDED` agreement blocks new placements, while in-flight fulfillment on
    pre-existing orders continues (PRD §3.6 makes `RECEIVED` valid from
    `SHIPPED` or `PARTIALLY_SHIPPED` with no agreement-state gate, and the
    recovery path requires receiving while `SUSPENDED`).

    Design: Corner/validations/order_create_on_suspended_blocked_but_receive_allowed
    """
    ctx = setup_facility_with_agreement(committed_fill_rate_pct=95.0)
    facility, product, agreement = (
        ctx["facility"],
        ctx["product"],
        ctx["agreement"],
    )
    # Two orders placed before the breach.
    o1 = place_order(
        agreement["id"], facility["id"],
        [{"product_id": product["id"], "ordered_qty": 200}],
        requested_delivery_date="2026-09-10",
    )
    o2 = place_order(
        agreement["id"], facility["id"],
        [{"product_id": product["id"], "ordered_qty": 50}],
        requested_delivery_date="2026-09-12",
    )
    ship_order(o1["id"], [{"product_id": product["id"], "shipped_qty": 170,
                           "backorder_cancelled": False}])
    receive_order(o1["id"])
    assert get_agreement(agreement["id"])["status"] == "SUSPENDED"
    ship_order(o2["id"], [{"product_id": product["id"], "shipped_qty": 50,
                           "backorder_cancelled": False}])
    # New placement is blocked...
    resp = api.create_distribution_order(
        create_order_payload(
            agreement["id"],
            [{"product_id": product["id"], "ordered_qty": 10}],
            requested_delivery_date="2026-09-20",
        ),
        headers=make_facility_director_headers(facility["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value, 409)
    # ...but the pre-existing order receives normally (rolling 220/250 = 88.00
    # still < 95.0, so the agreement stays SUSPENDED).
    received = receive_order(o2["id"])
    assert received["status"] == "RECEIVED"
    after = get_agreement(agreement["id"])
    assert after["status"] == "SUSPENDED"
    assert after["rolling_fill_rate_pct"] == 88.00


def test_state_gate_beats_fiscal_gate(api):
    """PRD §2.6: "The server evaluates validation rules in a fixed priority order
    and reports only the first failure: the rule with the lower priority number
    wins." — state-machine legality (band 5) precedes fiscal caps (band 10), so
    an order under a `SUSPENDED` agreement that would also breach the annual
    commitment surfaces `ERR_AGREEMENT_NOT_ACTIVE`.

    Design: Difficulty/priority_pair_validation_conflict/order_create_state_gate_beats_fiscal_gate
    """
    ctx = setup_suspended_agreement_scenario(annual_commitment_cents=50000)
    # spent_cents is now 20000 after the breach receipt; a 400-unit order at
    # 100 cents computes 40000, and 20000 + 40000 > 50000.
    resp = api.create_distribution_order(
        create_order_payload(
            ctx["agreement"]["id"],
            [{"product_id": ctx["product"]["id"], "ordered_qty": 400}],
            requested_delivery_date="2026-09-20",
        ),
        headers=make_facility_director_headers(ctx["facility"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value, 409)


def test_fiscal_gate_not_reported_when_state_fails(api):
    """PRD §2.6: "The server evaluates validation rules in a fixed priority order
    and reports only the first failure: the rule with the lower priority number
    wins." The fiscal error (`ERR_COMMITMENT_EXCEEDED`, band 10) must NOT be
    reported when the state gate (band 5) fails; the agreement's spend stays
    untouched by the rejected placement.

    Design: Difficulty/priority_pair_validation_conflict/order_create_state_gate_beats_fiscal_gate
    """
    ctx = setup_suspended_agreement_scenario(annual_commitment_cents=50000)
    resp = api.create_distribution_order(
        create_order_payload(
            ctx["agreement"]["id"],
            [{"product_id": ctx["product"]["id"], "ordered_qty": 400}],
            requested_delivery_date="2026-09-20",
        ),
        headers=make_facility_director_headers(ctx["facility"]["id"]),
    )
    err = validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value, 409)
    assert err["error_id"] != ApiErrorId.ERR_COMMITMENT_EXCEEDED.value
    agreement = get_agreement(ctx["agreement"]["id"])
    assert_prime_vendor_agreement(agreement)
    assert agreement["spent_cents"] == 20000
    assert agreement["status"] == "SUSPENDED"


def test_subresource_orders_under_agreement(api):
    """PRD §3.5: "the orders riding under an agreement can be listed as a
    sub-resource reverse lookup, filterable by `status`."

    Design: Corner/endpoints/subresource_orders_under_agreement
    """
    ctx = setup_facility_with_agreement(committed_fill_rate_pct=90.0)
    o1 = place_order(
        ctx["agreement"]["id"], ctx["facility"]["id"],
        [{"product_id": ctx["product"]["id"], "ordered_qty": 10}],
        requested_delivery_date="2026-09-10",
    )
    o2 = place_order(
        ctx["agreement"]["id"], ctx["facility"]["id"],
        [{"product_id": ctx["product"]["id"], "ordered_qty": 20}],
        requested_delivery_date="2026-09-12",
    )
    data, meta = validate_paginated(
        api.list_agreement_orders(ctx["agreement"]["id"], ADMIN)
    )
    assert meta["total_count"] == 2
    assert len(data) == 2
    assert all(o["agreement_id"] == ctx["agreement"]["id"] for o in data)
    assert all(o["status"] == "PLACED" for o in data)
    assert find_order(data, o1["id"])["id"] == o1["id"]
    assert find_order(data, o2["id"])["id"] == o2["id"]
