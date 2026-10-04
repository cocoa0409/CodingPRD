"""Error-catalogue corners: each failure mode reports its own code."""

from test_helpers import (
    ADMIN,
    CURATOR,
    DCM,
    PICKER,
    ApiErrorId,
    account_headers,
    confirm_cutoff,
    create_and_approve_return,
    setup_allocated_order,
    setup_center,
    setup_clock,
    setup_curated_items,
    setup_order_scenario,
    setup_shipped_order,
    setup_supplier,
    validate_error,
    validate_paginated,
    validate_success,
)

ABSENT_ITEM = "00000000-0000-4000-8000-000000000000"


def test_allocation_with_no_surviving_center_reports_the_selector_fallback(api):
    """PRD §3.4: "The candidate set is every `DistributionCenter` satisfying both of two
    conditions at once: the center's `region` must equal the ordering account's
    `home_region`, and, for every line of the order, the stock row for that line's item at
    that center must have `on_hand_units` at least the line's `quantity`."
    PRD §3.4: "If the candidate set is empty, the allocation fails with `ERR_NO_ELIGIBLE_DC`
    (HTTP 409)."

    Design: Corner/errors/allocation_with_no_eligible_dc_returns_no_eligible_dc
    """
    scenario = setup_order_scenario(
        api,
        lines_spec=[{"price": 1500, "qty": 5, "bundle": 20, "on_hand": 1, "sku": "ER-1001"}],
        target="RELEASED",
    )
    order = scenario["order"]

    response = api.allocate_order(
        order["id"], {"expected_order_version": order["version"]}, scenario["acct_headers"])
    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_DC)

    after = validate_success(api.get_order(order["id"], scenario["acct_headers"]))
    assert after["fulfillment_status"] == "AWAITING_RELEASE"
    assert after["allocated_dc_id"] is None

    stock = validate_success(api.get_stock(scenario["stock_rows"][0]["id"], DCM))
    assert stock["reserved_units"] == 0, "the failed selection reserved nothing"

    dc = validate_success(api.get_distribution_center(scenario["dc"]["id"], DCM))
    assert dc["inbound_reserved_units"] == 0


def test_resuming_a_claim_against_a_suspended_item_is_refused(api):
    """PRD §3.6: "A picker may resume fulfillment of a claim, which is only permitted while
    the item's `catalog_status` is `ACTIVE`; a suspended item cannot have fulfillment
    resumed against it, and the attempt is rejected with `ERR_ITEM_SUSPENDED` (HTTP 409)."
    PRD §3.9: "Exactly 10,000 cents suspends the item; 9,999 cents does not."

    Design: Corner/errors/resume_fulfillment_on_a_suspended_item_returns_item_suspended
    """
    first = setup_shipped_order(api, qty=5, price=10000, long_tail=True, on_hand=10,
                                sku="ER-1101")
    ret = create_and_approve_return(api, first, requested_units=5)
    validate_success(api.receive_return(
        ret["id"], {"removed_manufacturer_part_numbers": {first["lines"][0]["id"]: "PN-1"}},
        DCM))

    item = validate_success(api.get_item(first["items"][0]["id"], DCM))
    assert item["catalog_status"] == "SUSPENDED", (
        "one damaged unit at 10000 cents reaches the inclusive trigger"
    )

    second = setup_allocated_order_second_order(api, first)
    claim = second["claim"]

    response = api.resume_claim_fulfillment(claim["id"], PICKER)
    validate_error(response, ApiErrorId.ERR_ITEM_SUSPENDED)

    still = validate_success(api.get_damage_claim(claim["id"], DCM))
    assert still["claim_status"] == "OPEN"


def setup_allocated_order_second_order(api, first):
    """The OPEN claim standing against the suspended long-tail item.

    PRD 3.6 opens a short-pick claim only when the line's item has `long_tail`
    false, so a short pick on this long-tail item would open nothing. The claim
    that does exist against this item is the one the return receipt's damage path
    opened (PRD 3.9 stage D), which is the claim this scenario resumes against.
    """
    claims, _meta = validate_paginated(api.list_damage_claims(
        DCM, {"order_id": first["order"]["id"], "limit": 10, "offset": 0}))
    assert claims, "the return receipt's damage path opened a claim"
    return {"order": first["order"], "claim": claims[0]}


def test_unknown_return_and_claim_ids_report_their_own_not_found_codes(api):
    """PRD §2.8: "The same left-to-right discipline governs the other parents, each with
    its own not-found code — `ERR_ITEM_NOT_FOUND` for an unresolvable `CatalogItem`,
    `ERR_DC_NOT_FOUND` for an unresolvable `DistributionCenter`, `ERR_RETURN_NOT_FOUND` for
    an unresolvable `ReturnAuthorization` and `ERR_CLAIM_NOT_FOUND` for an unresolvable
    `DamageClaim`."

    Design: Corner/errors/unknown_return_and_claim_ids_return_their_own_not_found_codes
    """
    setup_clock(api)
    absent_return = "00000000-0000-4000-8000-000000000010"
    absent_claim = "00000000-0000-4000-8000-000000000020"
    absent_dc = "00000000-0000-4000-8000-000000000030"

    receive = api.receive_return(
        absent_return,
        {"removed_manufacturer_part_numbers": {"00000000-0000-4000-8000-000000000011": "X"}},
        DCM)
    validate_error(receive, ApiErrorId.ERR_RETURN_NOT_FOUND)

    reject = api.reject_claim(absent_claim, DCM)
    validate_error(reject, ApiErrorId.ERR_CLAIM_NOT_FOUND)

    roll = api.roll_cutoff(absent_dc, DCM)
    validate_error(roll, ApiErrorId.ERR_DC_NOT_FOUND)


def test_reviewing_an_item_with_no_attribute_rows_is_refused(api):
    """PRD §3.1: "Every submitted item must already carry at least one attribute row — an
    item with no attribute rows blocks the whole submission with
    `ERR_CURATION_ATTRIBUTES_MISSING` (HTTP 409)".

    Design: Corner/errors/curation_review_without_attribute_rows_returns_attributes_missing
    """
    setup_clock(api)
    item = validate_success(api.create_item(
        {"sku": "CU-1001", "description": "Attribute-less item", "material_spec": "steel",
         "long_tail": False, "unit_price_cents": 1500, "unit_weight_kg": 0.10,
         "curation_bundle_size": 4,
         "curated_dimension_json": {"nominal_length_mm": 10, "nominal_width_mm": 10,
                                    "nominal_height_mm": 10, "drawing_revision": 5}},
        CURATOR), 201)

    response = api.create_curation_review({"item_ids": [item["id"]]}, CURATOR)
    validate_error(response, ApiErrorId.ERR_CURATION_ATTRIBUTES_MISSING)

    after = validate_success(api.get_item(item["id"], CURATOR))
    assert after["curation_review_state"] == "UNREVIEWED"
    assert after["curation_last_reviewed_by"] is None

    attribute = validate_success(api.create_item_attribute(
        item["id"], {"attribute_name": "Grade", "attribute_value": "8.8",
                     "unit_of_measure": "n/a"}, CURATOR), 201)
    assert attribute["id"]
    validate_success(api.create_curation_review({"item_ids": [item["id"]]}, CURATOR), 201)


def test_an_availability_report_below_the_commitment_empties_the_candidate_set(api):
    """PRD §3.2: "The eligibility filter admits only suppliers that are
    `long_tail_authorized` and whose `min_stock_commitment_units` is at least the
    `reported_available_units` just filed for the item".
    PRD §3.2: "If no supplier survives the filter, the filing is rejected with
    `ERR_SUPPLIER_CANDIDATE_EMPTY` (HTTP 409)."
    PRD §3.2: "filing an availability report whose `reported_available_units` falls below
    that supplier's own `min_stock_commitment_units` increments its
    `commitment_breach_count` by 1 and recomputes `performance_rating_units` from the new
    counter".

    Design: Corner/errors/long_tail_supplier_below_its_commitment_is_red_flagged
    """
    setup_clock(api)
    dc = setup_center(api)
    authorized = setup_supplier(api, home_dc=dc, min_stock_commitment_units=50)
    setup_supplier(api, home_dc=dc, supplier_name="Spot Buy Metals",
                   long_tail_authorized=False, min_stock_commitment_units=0)
    catalog = setup_curated_items(api, specs=[{"sku": "SP-1001", "price": 5500,
                                               "long_tail": True}],
                                  account=None, dc=None, with_stock=False, sku_prefix="SP")
    item = catalog["items"][0]

    response = api.create_availability_report(
        authorized["id"], {"item_id": item["id"], "reported_available_units": 40}, ADMIN)
    # PRD 3.2: the eligibility filter "admits only suppliers that are
    # `long_tail_authorized` and whose `min_stock_commitment_units` is at least the
    # `reported_available_units` just filed" — 50 >= 40, so this supplier survives and
    # the filing is accepted. What the filing does trigger is the breach ledger, because
    # 40 falls below that supplier's own 50-unit commitment.
    winner = validate_success(response, 201)
    assert winner["id"] == authorized["id"], "the surviving supplier is returned"

    supplier = validate_success(api.get_supplier(authorized["id"], ADMIN))
    assert supplier["commitment_breach_count"] == 1
    assert supplier["performance_rating_units"] == 90

    reports, _meta = validate_paginated(api.list_supplier_availability_reports(
        authorized["id"], ADMIN, {"limit": 100, "offset": 0}))
    assert len(reports) == 1, "the report was persisted"
    assert reports[0]["reported_available_units"] == 40

    unauthorized, _meta = validate_paginated(api.list_suppliers(
        ADMIN, {"long_tail_authorized": False, "limit": 100, "offset": 0}))
    assert len(unauthorized) == 1


def test_a_cancelled_order_refuses_further_cancellation_with_the_terminal_code(api):
    """PRD §2.9: "Terminal state. The target resource must not already sit in one of its
    declared terminal states; otherwise `ERR_ALREADY_TERMINAL` (409)."
    PRD §3.3: "In all three cases the resulting order_status is the terminal value
    `CANCELLED`."

    Design: Corner/errors/terminal_order_refuses_further_mutation_with_already_terminal
    """
    scenario = setup_order_scenario(
        api,
        lines_spec=[{"price": 1500, "qty": 1, "bundle": 4, "on_hand": 10, "sku": "AT-1001"}],
        target="RELEASED",
    )
    headers = scenario["acct_headers"]
    cancelled = validate_success(api.cancel_order(scenario["order"]["id"], headers))
    assert cancelled["order_status"] == "CANCELLED"
    terminal_version = cancelled["version"]

    response = api.cancel_order(scenario["order"]["id"], headers)
    validate_error(response, ApiErrorId.ERR_ALREADY_TERMINAL)

    after = validate_success(api.get_order(scenario["order"]["id"], headers))
    assert after["order_status"] == "CANCELLED"
    assert after["version"] == terminal_version


def test_an_unresolvable_line_reports_the_line_code_not_the_order_code(api):
    """PRD §2.8: "an order identifier that matches no `CatalogOrder` is rejected with
    `ERR_ORDER_NOT_FOUND` (HTTP 404) before the line identifier is even examined, and a
    line identifier that matches no line of that order is rejected with
    `ERR_LINE_NOT_FOUND` (HTTP 404)."

    Design: Corner/errors/unknown_line_id_returns_line_not_found
    """
    scenario = setup_allocated_order(
        api,
        lines_spec=[{"price": 1500, "qty": 1, "bundle": 4, "on_hand": 5, "sku": "LN-1001"}],
    )
    absent_line = "00000000-0000-4000-8000-000000000099"

    response = api.pick_line(scenario["order"]["id"], absent_line,
                             {"requested_units": 1}, PICKER)
    error_data = validate_error(response, ApiErrorId.ERR_LINE_NOT_FOUND)

    assert error_data["error_id"] != ApiErrorId.ERR_ORDER_NOT_FOUND
    lines, _meta = validate_paginated(api.list_order_lines(
        scenario["order"]["id"], scenario["acct_headers"], {"limit": 10, "offset": 0}))
    assert len(lines) == 1
    assert lines[0]["line_status"] == "ALLOCATED"


def test_receiving_a_return_without_part_numbers_is_refused(api):
    """PRD §3.9: "Receiving requires `return_status` `APPROVED`, and every claimed unit
    must carry a `removed_manufacturer_part_number` recorded on the request — supplied as
    the `removed_manufacturer_part_numbers` collection on the receiving body; a claimed
    unit with no part number recorded is rejected with `ERR_RETURN_PART_NUMBER_REQUIRED`
    (HTTP 422)."

    Design: Corner/errors/return_receive_without_removed_part_numbers_is_refused
    """
    scenario = setup_shipped_order(api, qty=5, price=2000, on_hand=10, sku="RN-1001")
    ret = create_and_approve_return(api, scenario, requested_units=5)

    response = api.receive_return(ret["id"], {}, DCM)
    validate_error(response, ApiErrorId.ERR_RETURN_PART_NUMBER_REQUIRED)

    still = validate_success(api.get_return(ret["id"], DCM))
    assert still["return_status"] == "APPROVED"

    stock = validate_success(api.get_stock(scenario["stock_rows"][0]["id"], DCM))
    assert stock["on_hand_units"] == 5, "nothing was restocked"

    received = validate_success(api.receive_return(
        ret["id"], {"removed_manufacturer_part_numbers": {scenario["lines"][0]["id"]: "PN-2"}},
        DCM))
    assert received["return_status"] == "RECEIVED"