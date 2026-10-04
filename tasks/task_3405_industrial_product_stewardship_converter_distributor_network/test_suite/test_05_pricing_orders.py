"""Price agreements, channel floor, and order placement gates (PRD §3.5, §3.6)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    clearance_payload,
    create_agreement,
    create_authorized_converter,
    create_distributor,
    create_formulation,
    create_jurisdiction,
    decide_clearance,
    get_clearance,
    get_formulation,
    get_order,
    grant_authorization,
    make_converter_headers,
    make_distributor_headers,
    order_payload,
    place_order,
    price_agreement_payload,
    set_clock,
    setup_active_formulation,
    ship_order,
    submit_clearance,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["product_manager_headers"]
CM = TEST_USERS["channel_manager_headers"]
RM = TEST_USERS["regulatory_manager_headers"]


def test_order_get_unknown_id_returns_not_found(api):
    """PRD §2.9: "Existence — every identifier in the path and every foreign-key
    identifier in the body resolves to an existing entity, else `ERR_NOT_FOUND`
    (404)."

    Design: Corner/entities/order_get_unknown_id_returns_not_found
    """
    set_clock()
    resp = api.get_order(NON_EXISTENT_UUID, CM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["message"], "error envelope carries a human-readable message"


def test_shipped_order_advance_is_terminal_lockdown(api):
    """PRD §3.6: "Advances aimed at terminal orders (`SHIPPED` or `CANCELLED`)
    are rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/shipped_order_advance_is_terminal_lockdown
    """
    ctx = setup_active_formulation()
    dist = create_distributor()
    ag = create_agreement(ctx["formulation"]["id"], ctx["jurisdiction"]["id"],
                          distributor_id=dist["id"], tier="STANDARD", base_price_cents=10000)
    order = place_order(ag["id"], 2, distributor_id=dist["id"])
    shipped = ship_order(order["id"], distributor_id=dist["id"])
    assert shipped["fulfillment_status"] == "SHIPPED"
    shipped_at = shipped["shipped_at"]
    resp = api.advance_order(order["id"], make_distributor_headers(dist["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_order(order["id"])
    assert after["fulfillment_status"] == "SHIPPED"
    assert after["shipped_at"] == shipped_at


def test_channel_floor_rejects_below_and_admits_above(api):
    """PRD §3.5: "compute each reference's unit price at quantity one — its
    `base_price_cents` reduced by its own tier discount only, with no breakpoint
    extra, rounded half-up to whole cents — and take the smallest such reference
    unit price; the floor is that minimum raised by eight percent, itself
    rounded half-up to whole cents." "If that worst-case price is below the
    floor, creation is rejected with `ERR_CHANNEL_FLOOR_VIOLATION` (422)."

    Design: Corner/calculations/channel_floor_rejects_below_and_admits_above
    """
    ctx = setup_active_formulation()
    fid, jur_id = ctx["formulation"]["id"], ctx["jurisdiction"]["id"]
    conv = create_authorized_converter()
    create_agreement(fid, jur_id, converter_id=conv["id"], tier="CONVERTER_AUTHORIZED",
                     base_price_cents=10000, effective_from="2026-10-01T00:00:00Z",
                     effective_to="2027-06-01T00:00:00Z")
    dist = create_distributor()
    low = api.create_price_agreement(
        price_agreement_payload(fid, jur_id, distributor_id=dist["id"],
                                tier="DISTRIBUTOR_PREFERRED", base_price_cents=10000,
                                effective_from="2026-10-01T00:00:00Z",
                                effective_to="2027-06-01T00:00:00Z"),
        CM,
    )
    validate_error(low, ApiErrorId.ERR_CHANNEL_FLOOR_VIOLATION)
    # floor = round(10000 * 0.82) * 1.08 = 8856; 10000 * 0.88 = 8800 < 8856
    ok = api.create_price_agreement(
        price_agreement_payload(fid, jur_id, distributor_id=dist["id"],
                                tier="DISTRIBUTOR_PREFERRED", base_price_cents=10100,
                                effective_from="2026-10-01T00:00:00Z",
                                effective_to="2027-06-01T00:00:00Z"),
        CM,
    )
    validate_success(ok, 201)
    # 10100 * 0.88 = 8888 >= 8856


def test_price_agreement_with_both_buyers_rejected(api):
    """PRD §3.5: "Buyer identity must be internally consistent:
    `CONVERTER_AUTHORIZED` tier is available to converter buyers only,
    `DISTRIBUTOR_PREFERRED` to distributor buyers only, and `STANDARD` to
    either; both ids present, neither id present at the shape level, or a tier
    inconsistent with the buyer kind all fail — both-absent surfaces at intake
    as `ERR_INVALID_REQUEST` (400), while a both-present or tier-mismatched
    combination is rejected as `ERR_BUYER_AMBIGUOUS` (422)."

    Design: Corner/validations/price_agreement_with_both_buyers_rejected
    """
    ctx = setup_active_formulation()
    fid, jur_id = ctx["formulation"]["id"], ctx["jurisdiction"]["id"]
    conv = create_authorized_converter()
    dist = create_distributor()
    resp = api.create_price_agreement(
        price_agreement_payload(fid, jur_id, converter_id=conv["id"],
                                distributor_id=dist["id"], tier="STANDARD",
                                base_price_cents=10000),
        CM,
    )
    validate_error(resp, ApiErrorId.ERR_BUYER_AMBIGUOUS)
    rows, meta = validate_paginated(
        api.list_price_agreements(CM, params={"formulation_id": fid})
    )
    assert meta["total_count"] == 0


def test_agreement_window_overlap_adjacent_allowed_overlapping_rejected(api):
    """PRD §2.8: "Overlap checks respect the same half-open reading, which makes
    **adjacency legal**: an authorization running to noon and another beginning
    at noon do not overlap." "A new converter authorization whose window
    intersects an existing authorization for the same (`converter_id`,
    `capability`, `territory_code`) triple is rejected with
    `ERR_AUTHORIZATION_WINDOW_OVERLAP` (HTTP 409); a new price agreement whose
    window intersects an existing agreement for the same buyer and the same
    `formulation_id` is rejected with `ERR_AGREEMENT_WINDOW_OVERLAP` (HTTP
    409)."

    Design: Corner/validations/agreement_window_overlap_adjacent_allowed_overlapping_rejected
    """
    ctx = setup_active_formulation()
    fid, jur_id = ctx["formulation"]["id"], ctx["jurisdiction"]["id"]
    dist = create_distributor()
    ag1 = create_agreement(fid, jur_id, distributor_id=dist["id"], tier="STANDARD",
                           base_price_cents=10000, effective_from="2026-10-01T00:00:00Z",
                           effective_to="2027-04-01T00:00:00Z")
    ag2 = api.create_price_agreement(
        price_agreement_payload(fid, jur_id, distributor_id=dist["id"], tier="STANDARD",
                                base_price_cents=11000,
                                effective_from="2027-04-01T00:00:00Z",
                                effective_to="2027-10-01T00:00:00Z"),
        CM,
    )
    validate_success(ag2, 201)
    overlap = api.create_price_agreement(
        price_agreement_payload(fid, jur_id, distributor_id=dist["id"], tier="STANDARD",
                                base_price_cents=12000,
                                effective_from="2027-03-01T00:00:00Z",
                                effective_to="2027-09-01T00:00:00Z"),
        CM,
    )
    validate_error(overlap, ApiErrorId.ERR_AGREEMENT_WINDOW_OVERLAP)


def test_converter_order_without_capability_coverage_rejected(api):
    """PRD §3.6: "an authorization must exist for the buyer whose `capability`
    equals the order's `intended_capability`, whose `territory_code` matches the
    `code` of the agreement's jurisdiction, and whose half-open window contains
    the current clock, else `ERR_AUTHORIZATION_CAPABILITY_MISMATCH` (422)."

    Design: Corner/validations/converter_order_without_capability_coverage_rejected
    """
    ctx = setup_active_formulation()
    conv = create_authorized_converter()
    grant_authorization(conv["id"], capability="SLITTING", territory_code="DE",
                        valid_from="2026-10-01T00:00:00Z", valid_to="2027-04-01T00:00:00Z")
    ag = create_agreement(ctx["formulation"]["id"], ctx["jurisdiction"]["id"],
                          converter_id=conv["id"], tier="CONVERTER_AUTHORIZED",
                          base_price_cents=10000)
    headers = make_converter_headers(conv["id"])
    bad = api.create_order(
        order_payload(ag["id"], quantity=5, requested_ship_date="2026-11-01T00:00:00Z",
                      expected_price_agreement_version=ag["version"],
                      converter_id=conv["id"], intended_capability="LAMINATION"),
        headers,
    )
    validate_error(bad, ApiErrorId.ERR_AUTHORIZATION_CAPABILITY_MISMATCH)
    good = api.create_order(
        order_payload(ag["id"], quantity=5, requested_ship_date="2026-11-01T00:00:00Z",
                      expected_price_agreement_version=ag["version"],
                      converter_id=conv["id"], intended_capability="SLITTING"),
        headers,
    )
    validate_success(good, 201)


def test_distributor_order_carrying_capability_field_rejected(api):
    """PRD §3.6: "For a converter buyer, `intended_capability` — one of
    `SLITTING`, `DIE_CUTTING`, or `LAMINATION` — is required; for a distributor
    buyer the same field is forbidden." and "a missing or misformed capability
    field surfaces at intake as `ERR_INVALID_REQUEST`."

    Design: Corner/validations/distributor_order_carrying_capability_field_rejected
    """
    ctx = setup_active_formulation()
    dist = create_distributor()
    ag = create_agreement(ctx["formulation"]["id"], ctx["jurisdiction"]["id"],
                          distributor_id=dist["id"], tier="STANDARD", base_price_cents=10000)
    resp = api.create_order(
        order_payload(ag["id"], quantity=5, requested_ship_date="2026-11-01T00:00:00Z",
                      expected_price_agreement_version=ag["version"],
                      distributor_id=dist["id"], intended_capability="SLITTING"),
        make_distributor_headers(dist["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_order_create_before_agreement_effective_rejected(api):
    """PRD §3.6: "The logical clock must fall inside the agreement's
    effectiveness window — at or after `effective_from` and strictly before
    `effective_to` — else `ERR_AGREEMENT_NOT_EFFECTIVE` (409)."

    Design: Corner/validations/order_create_before_agreement_effective_rejected
    """
    ctx = setup_active_formulation()
    dist = create_distributor()
    ag = create_agreement(ctx["formulation"]["id"], ctx["jurisdiction"]["id"],
                          distributor_id=dist["id"], tier="STANDARD", base_price_cents=10000,
                          effective_from="2026-11-01T00:00:00Z",
                          effective_to="2027-06-01T00:00:00Z")
    headers = make_distributor_headers(dist["id"])
    early = api.create_order(
        order_payload(ag["id"], quantity=5, requested_ship_date="2026-12-01T00:00:00Z",
                      expected_price_agreement_version=ag["version"],
                      distributor_id=dist["id"]),
        headers,
    )
    validate_error(early, ApiErrorId.ERR_AGREEMENT_NOT_EFFECTIVE)
    set_clock("2026-11-01T00:00:00Z")
    ok = api.create_order(
        order_payload(ag["id"], quantity=5, requested_ship_date="2026-12-01T00:00:00Z",
                      expected_price_agreement_version=ag["version"],
                      distributor_id=dist["id"]),
        headers,
    )
    validate_success(ok, 201)


def test_order_pricing_best_breakpoint_discounts_whole_quantity(api):
    """PRD §3.6: "among breakpoints whose `min_qty` is at most the order's
    `quantity`, the single largest `extra_discount_pct` applies (zero if none
    qualifies), and that one rate discounts the **whole** quantity — this is
    average-rate application, not marginal per-bracket allocation. The order's
    `unit_price_cents` is the agreement's `base_price_cents` reduced by that
    combined discount and rounded half-up to whole cents; the `line_total_cents`
    is the rounded unit price multiplied by `quantity`."

    Design: Difficulty/combinatorial_formula/order_pricing_average_rate_tier_plus_best_breakpoint
    """
    ctx = setup_active_formulation()
    conv = create_authorized_converter()
    grant_authorization(conv["id"], capability="SLITTING", territory_code="DE")
    ag = create_agreement(
        ctx["formulation"]["id"], ctx["jurisdiction"]["id"], converter_id=conv["id"],
        tier="CONVERTER_AUTHORIZED", base_price_cents=20000,
        volume_breakpoints=[{"min_qty": 100, "extra_discount_pct": 0.02},
                            {"min_qty": 250, "extra_discount_pct": 0.05}])
    order = place_order(ag["id"], 300, converter_id=conv["id"],
                        requested_ship_date="2026-11-01T00:00:00Z",
                        intended_capability="SLITTING")
    assert order["unit_price_cents"] == 15400, "20000 x (1 - 0.18 - 0.05) rounded once"
    assert order["line_total_cents"] == 4620000
    assert order["fulfillment_status"] == "PENDING"
    assert order["compliance_status"] == "CLEAR"


def test_order_pricing_quantity_below_breakpoint_gets_lower_discount(api):
    """PRD §3.6: "among breakpoints whose `min_qty` is at most the order's
    `quantity`, the single largest `extra_discount_pct` applies (zero if none
    qualifies)". PRD §3.5: "The tier discount is fixed by tier: 18% for
    `CONVERTER_AUTHORIZED`, 12% for `DISTRIBUTOR_PREFERRED`, and 0% for
    `STANDARD`."

    Design: Difficulty/combinatorial_formula/order_pricing_average_rate_tier_plus_best_breakpoint
    """
    ctx = setup_active_formulation()
    conv = create_authorized_converter()
    grant_authorization(conv["id"], capability="SLITTING", territory_code="DE")
    ag = create_agreement(
        ctx["formulation"]["id"], ctx["jurisdiction"]["id"], converter_id=conv["id"],
        tier="CONVERTER_AUTHORIZED", base_price_cents=20000,
        volume_breakpoints=[{"min_qty": 100, "extra_discount_pct": 0.02},
                            {"min_qty": 250, "extra_discount_pct": 0.05}])
    order = place_order(ag["id"], 249, converter_id=conv["id"],
                        requested_ship_date="2026-11-01T00:00:00Z",
                        intended_capability="SLITTING")
    assert order["unit_price_cents"] == 16000, "249 misses the 250 breakpoint: 20000 x (1 - 0.18 - 0.02)"
    assert order["line_total_cents"] == 3984000


def _setup_changes_requested_agreement(api):
    """Formulation whose DE clearance sits CHANGES_REQUESTED (formulation still
    DRAFT), plus a distributor STANDARD agreement in DE."""
    set_clock()
    jur = create_jurisdiction()
    form = create_formulation()
    cl = submit_clearance(form["id"], jur["id"], "EXEMPT")
    decide_clearance(cl["id"], "CHANGES_REQUESTED", decider="rm-1")
    dist = create_distributor()
    ag = create_agreement(form["id"], jur["id"], distributor_id=dist["id"],
                          tier="STANDARD", base_price_cents=10000)
    return jur, form, cl, dist, ag


def test_order_create_blocked_while_clearance_changes_requested(api):
    """PRD §3.6: "A `CLEARED` clearance must exist for the pair of the
    agreement's formulation and the agreement's jurisdiction, else
    `ERR_CLEARANCE_NOT_CLEARED` (409)."

    Design: Difficulty/cross_entity_state_dependency/order_create_gated_by_clearance_state
    """
    jur, form, cl, dist, ag = _setup_changes_requested_agreement(api)
    assert get_clearance(cl["id"])["status"] == "CHANGES_REQUESTED"
    resp = api.create_order(
        order_payload(ag["id"], quantity=10, requested_ship_date="2026-11-01T00:00:00Z",
                      expected_price_agreement_version=ag["version"],
                      distributor_id=dist["id"]),
        make_distributor_headers(dist["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CLEARANCE_NOT_CLEARED)


def test_order_create_succeeds_after_clearance_cleared_without_version_drift(api):
    """PRD §3.6: "A `CLEARED` clearance must exist for the pair of the
    agreement's formulation and the agreement's jurisdiction, else
    `ERR_CLEARANCE_NOT_CLEARED` (409)." PRD §2.6: "`POST /stewardship/orders`
    requires `expected_price_agreement_version`, matching the agreement's
    current `version`." PRD §3.2: "when that count rises from 0 to 1 the
    formulation itself bubbles up from `DRAFT` to `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/order_create_gated_by_clearance_state
    """
    jur, form, cl, dist, ag = _setup_changes_requested_agreement(api)
    headers = make_distributor_headers(dist["id"])
    blocked = api.create_order(
        order_payload(ag["id"], quantity=10, requested_ship_date="2026-11-01T00:00:00Z",
                      expected_price_agreement_version=ag["version"],
                      distributor_id=dist["id"]),
        headers,
    )
    validate_error(blocked, ApiErrorId.ERR_CLEARANCE_NOT_CLEARED)
    resub = api.create_clearance(clearance_payload(form["id"], jur["id"], "EXEMPT"), PM)
    validate_success(resub, 200)
    decide_clearance(cl["id"], "CLEARED", decider="rm-1")
    retry = api.create_order(
        order_payload(ag["id"], quantity=10, requested_ship_date="2026-11-01T00:00:00Z",
                      expected_price_agreement_version=ag["version"],
                      distributor_id=dist["id"]),
        headers,
    )
    order = validate_success(retry, 201)
    assert order["fulfillment_status"] == "PENDING", (
        "the failed create did not bump the agreement version, so the original "
        "expected version still matches"
    )
    assert get_formulation(form["id"])["status"] == "ACTIVE"
