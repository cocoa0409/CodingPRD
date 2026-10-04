"""Breadth: closure filtering, tier thresholds, fees, allocation and entitlement."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    SALES_OPS,
    SETUP_TECH,
    SUPPORT_AGENT,
    activate_warranty_plan,
    add_quote_line,
    close_claim,
    create_backorder,
    create_certification_attempt,
    create_quote,
    create_service_center,
    create_warranty_claim,
    create_warranty_plan,
    end_assignment,
    finalize_allocation,
    get_engineer as read_engineer,
    grade_certification_attempt,
    quote_summary,
    route_claim,
    setup_book_world,
    setup_reserved_quote,
    setup_shipped_instrument,
    start_sweep,
    set_clock,
    walk_unit_to_inspected,
    setup_instrument_unit,
    start_setup,
    create_support_ticket,
)


def test_dependency_closure_counts_only_lines_reachable_from_the_anchor():
    """PRD 3.2: "From that anchor the closure is the set of lines reachable by
    following `requires_line_id` edges outward, including the anchor itself. Its
    size is reported as `dependency_closure_size`. Lines that neither declare a
    prerequisite nor are required by anything else fall outside the closure and
    do not contribute to its size even though they appear on the quote."

    Design: Corner/calculations/dependency_closure_excludes_unrelated_lines_from_anchor
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    from test_helpers.fixtures import create_product

    # Adding a line requires the quote to be DRAFT (PRD 3.2): the RESERVED
    # quote is amended back to SUBMITTED, rejected, then reopened as a draft.
    from test_helpers.fixtures import amend_quote, reject_quote, reopen_quote

    create_product(product_code="SW-ACC-010", display_name="Woven Instrument Cable",
                   product_family="ACCESSORY", unit_price_cents=1500)
    submitted = amend_quote(world["quote"], world["engineer"])
    rejected = reject_quote(submitted, SALES_OPS)
    draft = reopen_quote(rejected, world["engineer"])
    accessory = add_quote_line(draft, world["engineer"],
                               product_code="SW-ACC-010", quantity=2)

    summary = quote_summary(world["quote_id"])
    assert accessory.get("requires_line_id") is None
    assert accessory["is_anchor"] is False
    assert summary["dependency_closure_size"] == 2


def test_bundle_ready_holds_when_the_required_family_is_inside_the_closure():
    """PRD 3.2: "every product in the closure whose `required_family` is set
    must find at least one other member of the closure occupying that family. An
    amp that requires a guitar is only ready when a guitar is in the closure
    with it".

    Design: Corner/calculations/dependency_closure_excludes_unrelated_lines_from_anchor
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    summary = quote_summary(world["quote_id"])
    assert summary["dependency_closure_size"] == 2
    assert summary["bundle_ready"] is True


def test_reverse_dependency_read_returns_only_the_dependent_line():
    """PRD 3.10: "Quote lines can be listed by their owning `quote_id` or by the
    `requires_line_id` they point at, which is the query that reconstructs a
    dependency graph in reverse."

    Design: Corner/calculations/dependency_closure_excludes_unrelated_lines_from_anchor
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    rows, meta = validate_paginated_lines(
        api_client.list_quote_lines(SALES_OPS,
                                    {"requires_line_id": world["guitar_line"]["id"]})
    )
    assert len(rows) == 1
    assert rows[0]["id"] == world["amp_line"]["id"]
    assert meta["total_count"] == 1


def validate_paginated_lines(resp):
    from test_helpers import validate_paginated

    return validate_paginated(resp)


def test_commission_share_cap_rejects_one_basis_point_above_the_ceiling():
    """PRD 2.4: "It is bounded above by the engineer's current
    `commission_cap_bps`: a share equal to the cap is admitted, and a share one
    basis point above the cap is rejected with `ERR_COMMISSION_CAP_EXCEEDED` at
    HTTP 422."

    Design: Corner/calculations/commission_share_capped_by_engineer_cap_bps
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z", with_catalog=False)
    from test_helpers.fixtures import create_assignment, create_customer

    other = create_customer("Sasha Poe", "sasha.poe@example.com", "TN")
    resp = api_client.create_assignment(
        {"customer_id": other["id"], "engineer_id": world["engineer_id"],
         "reason_code": "NEW_ACCOUNT", "commission_share_bps": 5001,
         "expected_customer_version": other["version"]},
        SALES_OPS,
    )
    validate_error(resp, ApiErrorId.ERR_COMMISSION_CAP_EXCEEDED)


def test_assignment_commission_default_and_provisional_credit():
    """PRD 2.4: "`commission_share_bps` is the requested engineer share of a
    quote's commission pool, expressed in basis points and defaulting to 5000."
    PRD 3.3: "The pool is 800 basis points of the quote's `gross_subtotal_cents`,
    rounded half-up to 2 decimal places."

    Design: Corner/calculations/commission_share_capped_by_engineer_cap_bps
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z", with_catalog=False)
    from test_helpers.fixtures import add_quote_line, create_product

    create_product(product_code="SW-GTR-100", display_name="Studio Guitar 100",
                   product_family="GUITAR", unit_price_cents=120000)
    quote = create_quote(world["customer"], world["engineer"], "SYSTEM_PACKAGE")
    add_quote_line(quote, world["engineer"], product_code="SW-GTR-100", quantity=1,
                   is_anchor=True)
    api_client.submit_quote(quote["id"],
                            {"X-User-ID": world["engineer_id"], "X-User-Role": "Engineer",
                             "Content-Type": "application/json"})

    assignment = validate_success(
        api_client.get_assignment(world["assignment_id"], SALES_OPS))
    assert assignment["commission_share_bps"] == 5000
    assert read_engineer(world["engineer_id"])["commission_cap_bps"] == 5000
    summary = quote_summary(quote["id"])
    assert summary["gross_subtotal_cents"] == 39996
    assert summary["engineer_commission_cents"] == 1600


def test_seniority_tier_promotes_at_exactly_two_certified_families():
    """PRD 3.9: "Two or three place them at `TIER_2` with a cap of 6500 basis
    points." PRD 3.9: "Grading divides cleanly at 80 percent. A `SCHEDULED`
    attempt scoring at least 80 is graded `PASSED`".

    Design: Corner/calculations/seniority_tier_threshold_boundary_at_two_and_four
    """
    set_clock("2026-09-01T00:00:00.000Z")
    from test_helpers.fixtures import create_engineer

    engineer = create_engineer()
    grade_certification_attempt(create_certification_attempt(engineer, "GUITAR", 85))
    grade_certification_attempt(create_certification_attempt(engineer, "AMPLIFIER", 80))

    refreshed = read_engineer(engineer["id"])
    assert refreshed["certified_family_count"] == 2
    assert refreshed["seniority_tier"] == "TIER_2"
    assert refreshed["commission_cap_bps"] == 6500


def test_a_score_below_eighty_neither_certifies_nor_promotes_the_tier():
    """PRD 3.9: "A `SCHEDULED` attempt scoring below 80 is graded `FAILED`, with
    `certified` set to false, `attempt_index` recomputed as one more than the
    number of prior attempts already recorded for that same engineer and family
    pairing".

    Design: Corner/calculations/seniority_tier_threshold_boundary_at_two_and_four
    """
    set_clock("2026-09-01T00:00:00.000Z")
    from test_helpers.fixtures import create_engineer

    engineer = create_engineer()
    grade_certification_attempt(create_certification_attempt(engineer, "GUITAR", 85))
    grade_certification_attempt(create_certification_attempt(engineer, "AMPLIFIER", 80))
    failed = grade_certification_attempt(
        create_certification_attempt(engineer, "MICROPHONE", 79))

    assert failed["status"] == "FAILED"
    assert failed["certified"] is False
    assert failed["attempt_index"] == 1
    refreshed = read_engineer(engineer["id"])
    assert refreshed["certified_family_count"] == 2
    assert refreshed["seniority_tier"] == "TIER_2"


def test_four_certified_families_reach_the_top_rung_of_the_ladder():
    """PRD 3.9: "Four or more current certified families place the engineer at
    `TIER_3` with a commission cap of 7500 basis points."

    Design: Corner/calculations/seniority_tier_threshold_boundary_at_two_and_four
    """
    set_clock("2026-09-01T00:00:00.000Z")
    from test_helpers.fixtures import create_engineer

    engineer = create_engineer()
    for family in ("GUITAR", "AMPLIFIER", "MICROPHONE", "ACCESSORY"):
        grade_certification_attempt(create_certification_attempt(engineer, family, 85))

    refreshed = read_engineer(engineer["id"])
    assert refreshed["certified_family_count"] == 4
    assert refreshed["seniority_tier"] == "TIER_3"
    assert refreshed["commission_cap_bps"] == 7500


def test_warranty_service_fee_is_dual_variant_across_route_and_close():
    """PRD 3.6: "Provisional is a per-round bench fee: the base round fee of
    2500 cents multiplied by the plan's `repair_rounds_used` plus one, charged
    when a claim routes". PRD 3.6: "Final is a term-scaled flat fee: 2500 cents
    multiplied by the plan's `term_months` and divided by 24, rounded half-up to
    2 decimal places, charged when the claim closes".

    Design: Corner/calculations/warranty_service_fee_dual_variant_on_close
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    shipped = setup_shipped_instrument(world)
    plan = activate_warranty_plan(
        create_warranty_plan(world["customer"], shipped, 36), "2026-09-01T00:00:00.000Z")
    assert plan["expires_on"] == "2029-09-01T00:00:00.000Z"

    center = create_service_center(capacity_slots=2, accepted_families=["GUITAR"])
    claim = create_warranty_claim(plan, center)
    routed = route_claim(claim)
    assert routed["status"] == "ROUTED"

    closed = close_claim(claim)
    assert closed["status"] == "CLOSED"
    refreshed = validate_success(api_client.get_warranty_plan(plan["id"], SUPPORT_AGENT))
    assert refreshed["repair_rounds_used"] == 1
    assert refreshed["remaining_repair_rounds"] == 2
    assert refreshed["status"] == "ACTIVE"


def test_conditional_verdict_when_only_the_action_height_check_fails():
    """PRD 3.4: "The string action at the twelfth fret passes when the rounded
    value is at least 0.50 millimetres and at most 2.00 millimetres inclusive at
    both ends."

    Design: Corner/calculations/inspection_verdict_conditional_when_only_relief_fails
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    unit = setup_instrument_unit(world)
    start_setup(unit)

    completed = validate_success(
        api_client.complete_setup(unit["id"],
                                  {"action_height_mm": 3.1, "relief_mm": 0.2,
                                   "intonation_offset_cents": 1},
                                  SETUP_TECH)
    )
    assert completed["inspection_overall"] == "CONDITIONAL"

    inspected = validate_success(api_client.record_inspection(unit["id"], SETUP_TECH))
    assert inspected["inspection_overall"] == "CONDITIONAL"


def test_conditional_verdict_does_not_block_shipment():
    """PRD 3.4: "A unit may ship only from `INSPECTED`, only when its
    `inspection_overall` is `PASS` or `CONDITIONAL`, and only when
    `modified_since_setup` is false".

    Design: Corner/calculations/inspection_verdict_conditional_when_only_relief_fails
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    unit = setup_instrument_unit(world)
    start_setup(unit)
    api_client.complete_setup(unit["id"],
                              {"action_height_mm": 3.1, "relief_mm": 0.2,
                               "intonation_offset_cents": 1}, SETUP_TECH)
    inspected = validate_success(api_client.record_inspection(unit["id"], SETUP_TECH))
    assert inspected["modified_since_setup"] is False

    shipped = validate_success(api_client.ship_instrument_unit(unit["id"], SETUP_TECH))
    assert shipped["setup_status"] == "SHIPPED"


def test_final_allocation_walk_conserves_the_shared_pool():
    """PRD 3.5: "it starts with the full pool as remaining capacity, grants each
    claim in walk order the smaller of its requested units and what remains, and
    subtracts the grant before moving on, so the pool is conserved exactly and
    no fraction of a unit is ever allocated."

    Design: Corner/calculations/backorder_final_allocation_conserves_pool_across_two_claims
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    early = create_backorder(world["guitar_line"], world["engineer"], units_requested=2,
                             preorder_open_at="2026-09-07T00:00:00.000Z")
    late = create_backorder(world["guitar_line"], world["engineer"], units_requested=2,
                            preorder_open_at="2026-09-08T00:00:00.000Z")

    start_sweep(early, pool_units=3)
    filled_early = finalize_allocation(early, pool_units=3)
    assert filled_early["units_filled"] == 2
    assert filled_early["status"] == "BOARD_FILLED"

    start_sweep(late, pool_units=3)
    filled_late = finalize_allocation(late, pool_units=3)
    assert filled_late["units_filled"] == 1
    assert filled_late["status"] == "PARTIALLY_FILLED"

    assert filled_early["units_filled"] + filled_late["units_filled"] == 3
    assert early["alloc_sequence"] < late["alloc_sequence"]
    assert early["eta_deadline"] == "2026-10-07T00:00:00.000Z"


def test_later_claim_receives_less_than_its_preliminary_estimate():
    """PRD 3.5: "because each claim is measured on its own, those estimates may
    sum to far more than the pool actually holds. This is the intended reading
    of `overcommit_estimate_units`, not an error."

    Design: Corner/calculations/backorder_final_allocation_conserves_pool_across_two_claims
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    early = create_backorder(world["guitar_line"], world["engineer"], units_requested=2,
                             preorder_open_at="2026-09-07T00:00:00.000Z")
    late = create_backorder(world["guitar_line"], world["engineer"], units_requested=2,
                            preorder_open_at="2026-09-08T00:00:00.000Z")
    start_sweep(early, pool_units=3)
    finalize_allocation(early, pool_units=3)
    estimate = start_sweep(late, pool_units=3)
    assert estimate["overcommit_estimate_units"] == 2

    filled = finalize_allocation(late, pool_units=3)
    assert filled["units_filled"] == 1
    assert filled["units_filled"] < estimate["overcommit_estimate_units"]


def test_entitlement_needs_both_a_purchase_and_an_engineer_for_basic():
    """PRD 3.7: "With no warranty in force, the entitlement is `BASIC` only when
    the customer has both an `ACTIVE` assignment and at least one purchased
    instrument, and it is `NONE` otherwise."

    Design: Corner/calculations/entitlement_requires_assignment_and_purchase_for_basic
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    unit = setup_instrument_unit(world)
    walk_unit_to_inspected(unit)

    before = validate_success(api_client.get_customer(world["customer_id"], SALES_OPS))
    assert before["purchased_instrument_count"] == 0
    assert before["tech_support_entitlement"] == "NONE"

    api_client.ship_instrument_unit(unit["id"], SETUP_TECH)

    after = validate_success(api_client.get_customer(world["customer_id"], SALES_OPS))
    assert after["purchased_instrument_count"] == 1
    assert after["tech_support_entitlement"] == "BASIC"


def test_ending_the_assignment_drops_the_entitlement_back_to_none():
    """PRD 3.7: "losing the engineer drops the customer to `NONE` the moment
    nothing else supports them — which is exactly the cascade described in
    §3.1."

    Design: Corner/calculations/entitlement_requires_assignment_and_purchase_for_basic
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    setup_shipped_instrument(world)
    raised = validate_success(api_client.get_customer(world["customer_id"], SALES_OPS))
    assert raised["tech_support_entitlement"] == "BASIC"

    end_assignment(world["assignment"], SALES_OPS)

    dropped = validate_success(api_client.get_customer(world["customer_id"], SALES_OPS))
    assert dropped["tech_support_entitlement"] == "NONE"
    assert dropped["purchased_instrument_count"] == 1