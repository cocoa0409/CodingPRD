"""Breadth: domain constraint refusals, paginated reads, and computed reads."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    ANONYMOUS,
    SALES_OPS,
    SETUP_TECH,
    SUPPORT_AGENT,
    activate_warranty_plan,
    add_quote_line,
    close_claim,
    create_backorder,
    create_customer,
    create_quote,
    create_service_center,
    create_warranty_claim,
    create_warranty_plan,
    quote_summary,
    route_claim,
    set_clock,
    setup_book_world,
    setup_reserved_quote,
    setup_shipped_instrument,
    setup_submitted_quote,
    submit_quote,
)


def test_claim_against_an_unknown_service_center_is_a_referenced_resource_error():
    """PRD 2.10: "a `service_center_id` that names no center ... is rejected
    with `ERR_REFERENCED_RESOURCE_NOT_FOUND` at HTTP 404 before any state check
    runs."

    Design: Corner/validations/unknown_service_center_on_claim_create_returns_referenced_resource_not_found
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    shipped = setup_shipped_instrument(world)
    plan = activate_warranty_plan(
        create_warranty_plan(world["customer"], shipped), "2026-09-01T00:00:00.000Z")

    resp = api_client.create_warranty_claim(
        {"warranty_plan_id": plan["id"], "reported_fault": "Output jack crackle",
         "service_center_id": NON_EXISTENT_UUID},
        SUPPORT_AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCED_RESOURCE_NOT_FOUND)


def test_a_refused_claim_does_not_move_the_plan_or_create_a_row():
    """PRD 3.6: "Either way the plan moves to `CLAIM_OPEN` and the new
    `WarrantyClaim` begins in `PENDING_ROUTING`".

    Design: Corner/validations/unknown_service_center_on_claim_create_returns_referenced_resource_not_found
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    shipped = setup_shipped_instrument(world)
    plan = activate_warranty_plan(
        create_warranty_plan(world["customer"], shipped), "2026-09-01T00:00:00.000Z")
    api_client.create_warranty_claim(
        {"warranty_plan_id": plan["id"], "reported_fault": "Output jack crackle",
         "service_center_id": NON_EXISTENT_UUID},
        SUPPORT_AGENT,
    )

    after = validate_success(api_client.get_warranty_plan(plan["id"], SUPPORT_AGENT))
    assert after["status"] == "ACTIVE"
    rows, meta = validate_paginated(
        api_client.list_warranty_claims(SUPPORT_AGENT, {"warranty_plan_id": plan["id"]})
    )
    assert meta["total_count"] == 0


def test_temporary_coverage_without_an_end_instant_is_refused():
    """PRD 2.4: "An assignment whose `reason_code` is `TEMPORARY_COVERAGE` must
    carry `effective_until`, the instant at which the coverage lapses; an
    assignment with any of the other three reasons must not carry one."

    Design: Corner/validations/temporary_coverage_requires_effective_until_pairing
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z", with_catalog=False,
                             accept=False)
    resp = api_client.create_assignment(
        {"customer_id": world["customer_id"], "engineer_id": world["engineer_id"],
         "reason_code": "TEMPORARY_COVERAGE",
         "expected_customer_version": world["customer"]["version"]},
        SALES_OPS,
    )
    validate_error(resp, ApiErrorId.ERR_TEMPORARY_COVERAGE_UNTIL_REQUIRED)


def test_a_permanent_reason_carrying_an_end_instant_is_refused():
    """PRD 2.4: "Either violation — a temporary coverage with no end instant, or
    a permanent reason carrying a stray one — is rejected with
    `ERR_TEMPORARY_COVERAGE_UNTIL_REQUIRED` at HTTP 422."

    Design: Corner/validations/temporary_coverage_requires_effective_until_pairing
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z", with_catalog=False,
                             accept=False)
    resp = api_client.create_assignment(
        {"customer_id": world["customer_id"], "engineer_id": world["engineer_id"],
         "reason_code": "NEW_ACCOUNT", "effective_until": "2026-10-09T00:00:00.000Z",
         "expected_customer_version": world["customer"]["version"]},
        SALES_OPS,
    )
    validate_error(resp, ApiErrorId.ERR_TEMPORARY_COVERAGE_UNTIL_REQUIRED)


def test_the_paired_temporary_coverage_shape_is_admitted():
    """PRD 2.4: "Temporary coverage is a different animal from the other three:
    it is the only reason that must be bounded in time."

    Design: Corner/validations/temporary_coverage_requires_effective_until_pairing
    """
    from test_helpers.fixtures import create_engineer, set_clock

    world = setup_book_world(clock="2026-09-09T00:00:00.000Z", with_catalog=False,
                             accept=False)
    # The second book is built on the same clock day as the first: its assignment
    # window must not overlap the first book's, so no assignment is accepted yet.
    set_clock("2026-09-09T00:00:00.000Z")
    cover = create_engineer("Ada Chen", "ada.chen@sweetwater.example", "WEST")
    second_customer = create_customer("Sasha Poe", "sasha.poe@example.com", "TN")
    created = validate_success(
        api_client.create_assignment(
            {"customer_id": second_customer["id"], "engineer_id": cover["id"],
             "reason_code": "TEMPORARY_COVERAGE",
             "effective_until": "2026-10-09T00:00:00.000Z",
             "expected_customer_version": second_customer["version"]},
            SALES_OPS,
        ),
        expected_status=201,
    )
    assert created["status"] == "PENDING_ACCEPT"
    assert created["effective_until"] == "2026-10-09T00:00:00.000Z"
    assert world["engineer_id"] is not None


def test_zero_unit_backorder_request_is_refused():
    """PRD 3.5: "A claim asking for zero units is refused rather than being
    quietly satisfied with nothing: `units_requested` of exactly 0 defines an
    empty candidate set and raises `ERR_ZERO_ALLOCATION_REQUEST` at HTTP 422."

    Design: Corner/validations/zero_unit_backorder_is_rejected_before_any_sweep
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    resp = api_client.create_backorder(
        {"quote_line_id": world["guitar_line"]["id"], "engineer_id": world["engineer_id"],
         "units_requested": 0, "preorder_open_at": "2026-09-09T00:00:00.000Z"},
        SALES_OPS,
    )
    validate_error(resp, ApiErrorId.ERR_ZERO_ALLOCATION_REQUEST)


def test_a_refused_zero_unit_claim_creates_no_row_and_spares_the_reservation():
    """PRD 3.5: "This is the single-line guard that keeps an empty request from
    turning into an empty allocation further down the pipeline."

    Design: Corner/validations/zero_unit_backorder_is_rejected_before_any_sweep
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    api_client.create_backorder(
        {"quote_line_id": world["guitar_line"]["id"], "engineer_id": world["engineer_id"],
         "units_requested": 0, "preorder_open_at": "2026-09-09T00:00:00.000Z"},
        SALES_OPS,
    )
    rows, meta = validate_paginated(
        api_client.list_backorders(SALES_OPS, {"quote_line_id": world["guitar_line"]["id"]})
    )
    # The only claim on this line is the one the reservation itself created;
    # the refused zero-unit request added nothing (PRD 3.5).
    assert meta["total_count"] == 1
    quote = validate_success(api_client.get_quote(world["quote_id"], SALES_OPS))
    assert quote["status"] == "RESERVED"


def test_exhausted_repair_allowance_blocks_the_fourth_claim():
    """PRD 3.6: "Opening a claim consumes nothing yet, but it requires a
    strictly positive remaining allowance: a plan whose
    `remaining_repair_rounds` is exactly zero admits no further claim, and the
    attempt fails with `ERR_REPAIR_ROUNDS_EXHAUSTED` at HTTP 422."

    Design: Corner/validations/exhausted_repair_rounds_blocks_the_fourth_claim
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    shipped = setup_shipped_instrument(world)
    plan = activate_warranty_plan(
        create_warranty_plan(world["customer"], shipped), "2026-09-01T00:00:00.000Z")
    center = create_service_center(capacity_slots=2, accepted_families=["GUITAR"])

    for index in range(3):
        claim = create_warranty_claim(plan, center, f"Round {index + 1} fault")
        route_claim(claim)
        close_claim(claim)

    refreshed = validate_success(api_client.get_warranty_plan(plan["id"], SUPPORT_AGENT))
    assert refreshed["repair_rounds_used"] == 3
    assert refreshed["remaining_repair_rounds"] == 0
    assert refreshed["status"] == "EXPIRED"

    resp = api_client.create_warranty_claim(
        {"warranty_plan_id": plan["id"], "reported_fault": "Fourth round no-signal",
         "service_center_id": center["id"]},
        SUPPORT_AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_REPAIR_ROUNDS_EXHAUSTED)

    claims, meta = validate_paginated(
        api_client.list_warranty_claims(SUPPORT_AGENT, {"warranty_plan_id": plan["id"]})
    )
    assert meta["total_count"] == 3


def test_three_closed_rounds_expire_the_plan_and_release_every_slot():
    """PRD 3.6: "The plan then either returns to `ACTIVE` when the allowance is
    still positive or moves to `EXPIRED` when it has reached zero. The routed
    center's `open_ticket_count` is decremented, releasing the slot the claim
    was holding".

    Design: Corner/validations/exhausted_repair_rounds_blocks_the_fourth_claim
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    shipped = setup_shipped_instrument(world)
    plan = activate_warranty_plan(
        create_warranty_plan(world["customer"], shipped), "2026-09-01T00:00:00.000Z")
    center = create_service_center(capacity_slots=2, accepted_families=["GUITAR"])
    for _ in range(3):
        claim = create_warranty_claim(plan, center, "Repeated fault")
        route_claim(claim)
        close_claim(claim)

    rows = api_client.list_service_centers(SUPPORT_AGENT, {"region": "MIDWEST"}).json()["data"]
    assert [row for row in rows if row["id"] == center["id"]][0]["open_ticket_count"] == 0
    plan_after = validate_success(api_client.get_warranty_plan(plan["id"], SUPPORT_AGENT))
    assert plan_after["status"] == "EXPIRED"


def test_customers_list_paginates_across_three_rows():
    """PRD 2.3: "`limit` must be an integer of at least 1 and no greater than
    100"". PRD 2.3: "`offset` is a zero-based count of records to skip".

    Design: Corner/endpoints/customers_list_paginates_across_three_rows
    """
    set_clock("2026-09-01T00:00:00.000Z")
    create_customer("Riley Chance", "riley.chance@example.com", "IN")
    create_customer("Sasha Poe", "sasha.poe@example.com", "TN")
    create_customer("Ken Ives", "ken.ives@example.com", "OH")

    first_page, meta = validate_paginated(
        api_client.list_customers(SALES_OPS, {"limit": 2, "offset": 0}))
    assert len(first_page) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    second_page, meta2 = validate_paginated(
        api_client.list_customers(SALES_OPS, {"limit": 2, "offset": 2}))
    assert len(second_page) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_customers_list_defaults_to_ten_rows_from_the_first_offset():
    """PRD 2.3: "When `limit` is omitted it defaults to 10; when `offset` is
    omitted it defaults to 0."

    Design: Corner/endpoints/customers_list_paginates_across_three_rows
    """
    set_clock("2026-09-01T00:00:00.000Z")
    create_customer("Riley Chance", "riley.chance@example.com", "IN")
    create_customer("Sasha Poe", "sasha.poe@example.com", "TN")
    create_customer("Ken Ives", "ken.ives@example.com", "OH")

    rows, meta = validate_paginated(api_client.list_customers(SALES_OPS))
    assert len(rows) == 3
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert all("created_at" in row and "version" in row for row in rows)


def test_customers_list_orders_rows_by_created_at_ascending_and_is_stable():
    """PRD 2.3: "Lists are ordered by `created_at` ascending. This is the
    default and the only ordering a caller may rely on for list endpoints; the
    ordering is stable across pages so that a caller walking `offset` forward
    observes each record exactly once."

    Design: Corner/endpoints/customers_list_paginates_across_three_rows
    """
    set_clock("2026-09-01T00:00:00.000Z")
    create_customer("Riley Chance", "riley.chance@example.com", "IN")
    create_customer("Sasha Poe", "sasha.poe@example.com", "TN")
    create_customer("Ken Ives", "ken.ives@example.com", "OH")

    page_one, _ = validate_paginated(
        api_client.list_customers(SALES_OPS, {"limit": 2, "offset": 0}))
    page_two, _ = validate_paginated(
        api_client.list_customers(SALES_OPS, {"limit": 2, "offset": 2}))
    seen = [row["id"] for row in page_one] + [row["id"] for row in page_two]
    assert len(seen) == len(set(seen)) == 3
    assert [row["created_at"] for row in page_one] == sorted(
        row["created_at"] for row in page_one)


def test_customer_status_filter_partitions_the_table_by_explicit_enum():
    """PRD 3.10: "customer listings by `status`". PRD 3.1: "Activating a
    `PENDING` customer makes it `ACTIVE` and leaves its assignment mirror
    alone."

    Design: Corner/endpoints/customers_filter_by_status_uses_explicit_enum
    """
    set_clock("2026-09-01T00:00:00.000Z")
    activated = create_customer("Riley Chance", "riley.chance@example.com", "IN")
    pending = create_customer("Sasha Poe", "sasha.poe@example.com", "TN")
    validate_success(api_client.activate_customer(activated["id"], SALES_OPS))

    active_rows, active_meta = validate_paginated(
        api_client.list_customers(SALES_OPS, {"status": "ACTIVE"}))
    pending_rows, pending_meta = validate_paginated(
        api_client.list_customers(SALES_OPS, {"status": "PENDING"}))

    assert len(active_rows) == 1
    assert active_rows[0]["id"] == activated["id"]
    assert len(pending_rows) == 1
    assert pending_rows[0]["id"] == pending["id"]
    assert active_meta["total_count"] == 1
    assert pending_meta["total_count"] == 1


def test_quote_summary_matches_the_entity_read_and_the_formula():
    """PRD 3.10: "A dedicated computed read on a quote returns the derived
    figures together: `gross_subtotal_cents`, `package_bundle_price_cents`,
    `dependency_closure_size`, `bundle_ready`, `engineer_commission_cents`, and
    `commission_variant`".

    Design: Corner/endpoints/quote_summary_computed_read_matches_formula
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_submitted_quote(world)

    summary = quote_summary(world["quote_id"])
    assert summary["gross_subtotal_cents"] == 69993
    assert summary["package_bundle_price_cents"] == 69993
    assert summary["dependency_closure_size"] == 2
    assert summary["bundle_ready"] is True
    assert summary["engineer_commission_cents"] == 2800
    assert summary["commission_variant"] == "provisional"

    quote = validate_success(api_client.get_quote(world["quote_id"], SALES_OPS))
    assert quote["gross_subtotal_cents"] == summary["gross_subtotal_cents"]


def test_tier_rate_stays_at_zero_below_the_mid_threshold():
    """PRD 3.3: "no tier applies below 200000 cents."

    Design: Corner/endpoints/quote_summary_computed_read_matches_formula
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_submitted_quote(world)
    summary = quote_summary(world["quote_id"])
    assert summary["gross_subtotal_cents"] == 69993
    assert summary["package_bundle_price_cents"] == 69993, (
        "69993 is below TIER_MID_CENTS 200000, so the tier rate is 0"
    )


def test_bench_setup_is_unreachable_while_the_quote_line_is_unreserved():
    """PRD 3.4: "The unit begins life in `PENDING_SETUP`, and it may only enter
    setup when the `QuoteLine` it was registered against belongs to a quote that
    is currently `RESERVED`". PRD 2.11: "A resource that is not in a state the
    requested transition admits fails with `ERR_INVALID_STATE` at HTTP 409".

    Design: Corner/endpoints/instrument_unit_create_on_unreserved_quote_line_is_not_reachable
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    quote = create_quote(world["customer"], world["engineer"], "SYSTEM_PACKAGE")
    line = add_quote_line(quote, world["engineer"], product_code="SW-GTR-100",
                          quantity=1, is_anchor=True)
    submit_quote(quote, world["engineer"])
    unit = validate_success(
        api_client.create_instrument_unit(
            {"quote_line_id": line["id"], "serial_number": "SN-GTR-5521",
             "model_code": "SW-GTR-100"},
            SETUP_TECH,
        ),
        expected_status=201,
    )

    resp = api_client.start_setup(unit["id"], SETUP_TECH)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = validate_success(api_client.get_instrument_unit(unit["id"], SETUP_TECH))
    assert after["setup_status"] == "PENDING_SETUP"
    assert after.get("setup_technician_id") is None


def test_bench_setup_becomes_reachable_once_the_quote_is_reserved():
    """PRD 3.4: "The unit begins life in `PENDING_SETUP`, and it may only enter
    setup when the `QuoteLine` it was registered against belongs to a quote that
    is currently `RESERVED` — an instrument attached to a draft or amended quote
    has nothing to be set up for."

    Design: Corner/endpoints/instrument_unit_create_on_unreserved_quote_line_is_not_reachable
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    quote = create_quote(world["customer"], world["engineer"], "SYSTEM_PACKAGE")
    line = add_quote_line(quote, world["engineer"], product_code="SW-GTR-100",
                          quantity=1, is_anchor=True)
    submit_quote(quote, world["engineer"])
    unit = validate_success(
        api_client.create_instrument_unit(
            {"quote_line_id": line["id"], "serial_number": "SN-GTR-5521",
             "model_code": "SW-GTR-100"},
            SETUP_TECH,
        ),
        expected_status=201,
    )

    from test_helpers.fixtures import reserve_quote

    current = validate_success(api_client.get_quote(quote["id"], SALES_OPS))
    reserve_quote(current, world["engineer"], expected_quote_version=current["version"])

    started = validate_success(api_client.start_setup(unit["id"], SETUP_TECH))
    assert started["setup_status"] == "IN_SETUP"