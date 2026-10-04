"""Customization order intake and the two-variant quote (PRD section 3.5)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    approve_proof,
    boot_clock,
    create_colorway_drop,
    create_order,
    create_print_slot,
    create_product_line,
    get_order,
    make_buyer_headers,
    reserve_slot,
    set_clock,
    setup_catalog,
    submit_order,
    submit_proof,
    validate_error,
    validate_paginated,
    validate_success,
    assert_customization_order,
    TEST_USERS,
)

_ADMIN = TEST_USERS["platform_admin_headers"]
_PRODUCTION = TEST_USERS["production_lead_headers"]


def _line_and_drop(sku, **line_overrides):
    line = create_product_line(base_sku=sku, **line_overrides)
    drop = create_colorway_drop(line["id"])
    return line, drop


def test_order_created_with_all_axes_at_initial_states(api):
    """A new order reports every parallel axis at rest, on create and on the
    immediate read-back.

    PRD section 3.5: "A new order starts with every axis at rest:
    `order_state` `ACTIVE`, `artwork_status` `NO_ART`, `proof_round` 0,
    `schedule_status` `UNSCHEDULED`, `payment_status` `UNPAID`, `return_status`
    `NONE` with no `return_reason` or `return_resolution` yet,
    `reservation_status` `NONE` with no `slot_id`, and `quote_variant` `NONE`."

    Design: Corner/state_machines/order_created_with_all_axes_at_initial_states
    """
    boot_clock()
    catalog = setup_catalog()
    resp = api.create_customization_order(
        {
            "buyer_type": "INDIVIDUAL", "buyer_ref": "buyer-std",
            "product_line_id": catalog["line"]["id"],
            "colorway_drop_id": catalog["drop"]["id"],
            "quantity": 10, "declared_color_count": 1,
            "declared_placement_count": 1, "print_technology": "LASER",
            "requested_ship_date": "2026-09-16T00:00:00Z",
        },
        make_buyer_headers("buyer-std"),
    )
    order = validate_success(resp, 201)
    assert_customization_order(order)
    expected = {
        "order_state": "ACTIVE", "artwork_status": "NO_ART",
        "schedule_status": "UNSCHEDULED", "payment_status": "UNPAID",
        "return_status": "NONE", "reservation_status": "NONE",
        "proof_round": 0, "quote_variant": "NONE",
    }
    for field, value in expected.items():
        assert order[field] == value, f"{field}: expected {value}, got {order[field]}"
    assert order.get("return_reason") is None
    assert order.get("return_resolution") is None
    assert order.get("slot_id") is None

    read_back = get_order(order["id"])
    for field, value in expected.items():
        assert read_back[field] == value, "immediate read-after-write must agree"


def test_order_create_missing_required_quantity_returns_400(api):
    """quantity is required input; omitting it fails the request-shape check.

    PRD section 2.7: "(3) request-body shape — required fields present, types
    correct, enum values in range, and conditionally required fields satisfied
    ... with any failure reported as `ERR_INVALID_REQUEST`"
    PRD section 3.5: "a `quantity` of at least 1"

    Design: Corner/entities/order_create_missing_required_quantity_returns_400
    """
    boot_clock()
    catalog = setup_catalog()
    resp = api.create_customization_order(
        {
            "buyer_type": "INDIVIDUAL", "buyer_ref": "buyer-std",
            "product_line_id": catalog["line"]["id"],
            "colorway_drop_id": catalog["drop"]["id"],
            "declared_color_count": 1, "declared_placement_count": 1,
            "print_technology": "LASER",
            "requested_ship_date": "2026-09-16T00:00:00Z",
        },
        make_buyer_headers("buyer-std"),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    rows, meta = validate_paginated(api.list_customization_orders(
        TEST_USERS["production_lead_headers"], params={"buyer_ref": "buyer-std"}))
    assert len(rows) == 0 and meta["total_count"] == 0


def test_order_create_body_fk_checked_in_input_order(api):
    """Body foreign keys resolve in declared input order: product_line_id
    before colorway_drop_id.

    PRD section 2.7: "(4) existence of referenced resources, where path
    identifiers resolve left-to-right and then body foreign keys resolve in
    the endpoint's declared input order, each surfacing its entity-specific
    404"
    PRD section 3.5: "Creation checks that the referenced product line and drop
    exist; the line's status and the colorway's coherence are deliberately
    deferred to submit."

    Design: Corner/entities/order_create_body_fk_checked_in_input_order
    """
    boot_clock()
    line = create_product_line()
    unknown_line = "00000000-0000-4000-8000-000000000001"
    unknown_drop = "00000000-0000-4000-8000-000000000002"

    def create_with(line_id, drop_id):
        return api.create_customization_order(
            {
                "buyer_type": "INDIVIDUAL", "buyer_ref": "buyer-std",
                "product_line_id": line_id, "colorway_drop_id": drop_id,
                "quantity": 10, "declared_color_count": 1,
                "declared_placement_count": 1, "print_technology": "LASER",
                "requested_ship_date": "2026-09-16T00:00:00Z",
            },
            make_buyer_headers("buyer-std"),
        )

    resp_both = create_with(unknown_line, unknown_drop)
    validate_error(resp_both, ApiErrorId.ERR_PRODUCT_LINE_NOT_FOUND)

    resp_drop_only = create_with(line["id"], unknown_drop)
    validate_error(resp_drop_only, ApiErrorId.ERR_DROP_NOT_FOUND)

    rows, meta = validate_paginated(api.list_customization_orders(
        TEST_USERS["production_lead_headers"], params={"buyer_ref": "buyer-std"}))
    assert len(rows) == 0 and meta["total_count"] == 0


def test_quote_surcharges_and_setup_constants_applied(api):
    """Every pinned constant lands in the total: 150 per extra color, 200 per
    extra placement, the 8000 setup fee below 144 units, no INDIVIDUAL rate,
    no peak.

    PRD section 3.5: "The unit price is the line's `base_custom_price_cents`
    plus 150 cents for each declared or actual color beyond the first, plus
    200 cents for each placement beyond the first — colors and placements
    below one never reduce the base."
    PRD section 3.5: "A setup fee of 8000 cents is then added unless the
    quantity is at least 144, in which case the fee is waived for both buyer
    types."

    Design: Corner/calculations/quote_surcharges_and_setup_constants_applied
    """
    boot_clock()
    line, drop = _line_and_drop("SURCH", name="Surcharge Line",
                                base_custom_price_cents=2000,
                                map_price_cents=2499, min_custom_quantity=1)
    order = create_order(line["id"], drop["id"], buyer_ref="buyer-surch",
                         quantity=10, declared_color_count=4,
                         declared_placement_count=3, print_technology="PAD",
                         requested_ship_date="2026-09-12T00:00:00Z")
    submitted = submit_order(order["id"], "buyer-surch")
    # 10 x (2000 + 3*150 + 2*200) + 8000 = 28500 + 8000 = 36500, off-peak.
    assert submitted["provisional_quote_cents"] == 36500
    assert submitted["peak_applied"] is False, \
        "ship date 2026-09-12 is outside the peak window"


def test_tiered_quote_combines_rate_waiver_and_buyer_type_branches(api):
    """The quantity-tier discount is CORPORATE-gated while the setup waiver is
    quantity-gated for both buyer types.

    PRD section 3.5: "A quantity-tier discount applies to `CORPORATE` buyers
    only: 22 percent off at 500 units or more, 15 percent at 144 up to 499,
    and 8 percent at 48 up to 143; `INDIVIDUAL` orders never receive a
    quantity rate."
    PRD section 3.5: "A setup fee of 8000 cents is then added unless the
    quantity is at least 144, in which case the fee is waived for both buyer
    types."

    Design: Difficulty/combinatorial_formula/tiered_quote_combines_rate_waiver_and_buyer_type_branches
    """
    boot_clock()
    line, drop = _line_and_drop("CAMP20", name="Camp Mug 20 oz",
                                base_custom_price_cents=3000,
                                map_price_cents=3499, min_custom_quantity=1)

    def submit_qty(buyer_type, buyer_ref, qty, ship):
        order = create_order(line["id"], drop["id"], buyer_ref=buyer_ref,
                             buyer_type=buyer_type, quantity=qty,
                             declared_color_count=1, declared_placement_count=1,
                             print_technology="PAD", requested_ship_date=ship)
        return submit_order(order["id"], buyer_ref)

    corp47 = submit_qty("CORPORATE", "buyer-corp47", 47, "2026-09-10T00:00:00Z")
    # 47 x 3000 = 141000; 47 < 48 skips tier 1; 47 < 144 keeps the 8000 fee.
    assert corp47["provisional_quote_cents"] == 149000
    assert corp47["quote_variant"] == "PROVISIONAL"
    assert corp47["payment_status"] == "AUTHORIZED"

    ind500 = submit_qty("INDIVIDUAL", "buyer-ind500", 500, "2026-09-12T00:00:00Z")
    # 500 x 3000; INDIVIDUAL never tiers; fee waived at >= 144.
    assert ind500["provisional_quote_cents"] == 1500000
    assert ind500["quote_variant"] == "PROVISIONAL"
    assert ind500["payment_status"] == "AUTHORIZED"

    corp500 = submit_qty("CORPORATE", "buyer-corp500", 500, "2026-09-12T00:00:00Z")
    # round_half_up(1500000 x 0.78) = 1170000 — the buyer-type gate, not
    # quantity alone, decides the 0.22 branch.
    assert corp500["provisional_quote_cents"] == 1170000


def test_moq_exactly_at_threshold_passes_one_below_fails(api):
    """min_custom_quantity is an inclusive floor: qty == 24 submits, qty == 23
    on an identical order is rejected.

    PRD section 3.5: "And the `quantity` must meet the line's
    `min_custom_quantity`, failing with `ERR_BELOW_MINIMUM_QUANTITY`."

    Design: Difficulty/boundary_precision_check/moq_exactly_at_threshold_passes_one_below_fails
    """
    boot_clock()
    line, drop = _line_and_drop("RAM24", name="Rambler 24 oz",
                                base_custom_price_cents=3100,
                                map_price_cents=3699, min_custom_quantity=24)

    def make_order(qty):
        return create_order(line["id"], drop["id"], buyer_ref="buyer-moq",
                            buyer_type="CORPORATE", quantity=qty,
                            requested_ship_date="2026-09-15T00:00:00Z")

    ok_order = make_order(24)
    submitted = submit_order(ok_order["id"], "buyer-moq")
    assert submitted["payment_status"] == "AUTHORIZED"
    assert submitted["quote_variant"] == "PROVISIONAL"

    low_order = make_order(23)
    resp = api.submit_order(low_order["id"], make_buyer_headers("buyer-moq"))
    validate_error(resp, ApiErrorId.ERR_BELOW_MINIMUM_QUANTITY)
    low_after = get_order(low_order["id"])
    assert low_after["payment_status"] == "UNPAID"
    assert low_after["quote_variant"] == "NONE"


def test_submit_with_mismatched_colorway_returns_not_available(api):
    """An order on line A naming a drop of line B fails submit even though
    both parents exist and are ACTIVE.

    PRD section 3.5: "The chosen drop must belong to the same product line as
    the order and must not be `CLOSED`, failing with
    `ERR_COLORWAY_NOT_AVAILABLE`."

    Design: Corner/validations/submit_with_mismatched_colorway_returns_not_available
    """
    boot_clock()
    line = create_product_line()
    other = create_product_line(name="Other Line", category="SOFT_GOOD",
                                base_sku="OTHER1", base_custom_price_cents=4000,
                                map_price_cents=4499)
    drop_other = create_colorway_drop(other["id"], color_name="Other Olive",
                                      pantone_code="PMS 575", total_units=1000,
                                      dtc_reserved_units=100,
                                      dealer_unit_price_cents=2500)
    order = create_order(line["id"], drop_other["id"], buyer_ref="buyer-mix")

    resp = api.submit_order(order["id"], make_buyer_headers("buyer-mix"))
    validate_error(resp, ApiErrorId.ERR_COLORWAY_NOT_AVAILABLE)
    after = get_order(order["id"])
    assert after["payment_status"] == "UNPAID"
    assert after["quote_variant"] == "NONE"


def test_state_beats_constraint_on_resubmitted_cancelled_order(api):
    """One request violating both the order-state guard (priority 5) and the
    MOQ constraint (priority 11) reports the state error.

    PRD section 2.7: "When several checks could reject the same request, they
    are evaluated in a fixed priority order and the first failure wins."
    PRD section 3.5: "Submitting guards that the order is still `ACTIVE` — a
    second submit on the same order is a replay of a consumed transition and
    is rejected with `ERR_INVALID_STATE_TRANSITION`"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_constraint_on_resubmitted_cancelled_order
    """
    boot_clock()
    line, drop = _line_and_drop("RAM24X", name="Rambler 24 oz",
                                base_custom_price_cents=3100,
                                map_price_cents=3699, min_custom_quantity=24)
    order = create_order(line["id"], drop["id"], buyer_ref="buyer-lowmoq",
                         buyer_type="CORPORATE", quantity=23,
                         requested_ship_date="2026-09-15T00:00:00Z")

    # Constraint leg verified live: 23 < 24 fails submit while ACTIVE.
    resp_moq = api.submit_order(order["id"], make_buyer_headers("buyer-lowmoq"))
    validate_error(resp_moq, ApiErrorId.ERR_BELOW_MINIMUM_QUANTITY)

    cancelled = validate_success(
        api.cancel_order(order["id"], make_buyer_headers("buyer-lowmoq")))
    assert cancelled["order_state"] == "CANCELLED"
    assert cancelled["payment_status"] == "UNPAID", \
        "the failed submit never authorized, and an UNPAID order stays UNPAID"

    # The MOQ violation is still present, but the state guard speaks first.
    resp_state = api.submit_order(order["id"], make_buyer_headers("buyer-lowmoq"))
    validate_error(resp_state, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


def test_provisional_vs_final_quote_diverges_on_approved_artwork(api):
    """Same order, two evidence sets: the PROVISIONAL quote prices declared
    counts with the ship-date peak probe; the FINAL quote prices the approved
    proof's actual counts with the reserved slot's off-peak probe and replaces
    it — and approval confirms the HELD reservation atomically.

    PRD section 3.5: "The quote runs twice over the same tiered structure with
    different evidence, and the second run replaces rather than adjusts the
    first."
    PRD section 3.5: "The provisional probe treats the peak window as
    applicable when the `requested_ship_date` falls inside it."
    PRD section 3.6: "for this variant the peak probe reads the reserved slot's
    `peak_overlap` when the order's `reservation_status` is `HELD`,
    `WAITLISTED`, or `CONFIRMED`, and falls back to the `requested_ship_date`
    probe otherwise."
    PRD section 3.6: "When the order's reservation was sitting `HELD`,
    approval confirms it atomically: `reservation_status` moves to `CONFIRMED`
    and `schedule_status` moves from `RESERVED` to `CONFIRMED` in the same
    step."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_quote_diverges_on_approved_artwork
    """
    boot_clock()
    line = create_product_line(name="Rambler 20 oz", base_sku="RAM20",
                               base_custom_price_cents=3000, map_price_cents=3499,
                               min_custom_quantity=24)
    drop = create_colorway_drop(line["id"], color_name="Rescue Red",
                                pantone_code="PMS 186")
    slot = create_print_slot(station_code="L-1", technology="LASER",
                             window_start="2026-10-05T00:00:00Z",
                             window_end="2026-10-05T12:00:00Z",
                             capacity_minutes=600)
    order = create_order(line["id"], drop["id"], buyer_ref="buyer-acme",
                         buyer_type="CORPORATE", quantity=144,
                         declared_color_count=2, declared_placement_count=1,
                         print_technology="LASER",
                         requested_ship_date="2026-11-20T00:00:00Z")

    submitted = submit_order(order["id"], "buyer-acme")
    # unit 3000 + 1*150 = 3150; 144 x 3150 = 453600; 15% tier -> 385560;
    # setup waived at 144; ship 2026-11-20 is in-peak -> x1.25 = 481950.
    assert submitted["provisional_quote_cents"] == 481950
    assert submitted["peak_applied"] is True
    assert submitted["quote_variant"] == "PROVISIONAL"

    reserved = reserve_slot(order["id"], slot["id"], "buyer-acme")
    assert reserved["reservation_status"] == "HELD"  # 576 of 600 minutes

    proof = submit_proof(order["id"], "buyer-acme",
                         artwork_file_ref="s3://art/acme-v1.ai",
                         color_count=3, placement_count=2,
                         pantone_codes=["PMS 186", "PMS Black"])
    approved = approve_proof(proof["id"])
    assert approved["status"] == "APPROVED"

    final = get_order(order["id"])
    # unit 3000 + 2*150 + 1*200 = 3500; 144 x 3500 = 504000; x0.85 = 428400;
    # setup waived; slot L-1 is off-peak -> x1.0.
    assert final["final_quote_cents"] == 428400
    assert final["provisional_quote_cents"] == 481950, "the provisional is kept, not adjusted"
    assert final["quote_variant"] == "FINAL"
    assert final["peak_applied"] is False, "flipped from the ship-date probe to the slot probe"
    assert final["reservation_status"] == "CONFIRMED"
    assert final["schedule_status"] == "CONFIRMED"
