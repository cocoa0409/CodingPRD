"""Depth: validation-priority pairs, serial boundaries, and the preorder deadline."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    NON_EXISTENT_UUID,
    SALES_OPS,
    SETUP_TECH,
    SUPPORT_AGENT,
    amend_quote,
    complete_setup,
    create_assignment,
    create_backorder,
    create_customer,
    create_engineer,
    create_instrument_unit,
    create_service_center,
    create_warranty_claim,
    create_warranty_plan,
    activate_warranty_plan,
    quote_version,
    record_inspection,
    reset_sweep,
    route_claim,
    setup_book_world,
    setup_inspected_instrument,
    setup_reserved_quote,
    setup_shipped_instrument,
    setup_instrument_unit,
    start_setup,
    start_sweep,
    set_clock,
    accept_assignment,
    get_backorder,
)


def test_fail_verdict_outranks_the_quote_not_reserved_check_on_ship():
    """PRD 3.4: "A unit may ship only from `INSPECTED`, only when its
    `inspection_overall` is `PASS` or `CONDITIONAL`, and only when
    `modified_since_setup` is false — a `FAIL` verdict, or a measurement changed
    after inspection, blocks shipment with `ERR_INSPECTION_NOT_PASSED` at HTTP
    422. Shipping additionally requires the unit's quote to still be `RESERVED`
    ... an instrument whose quote has been amended back to `SUBMITTED` is held
    at the bench and refused with `ERR_QUOTE_NOT_RESERVED` at HTTP 409."

    Design: Difficulty/priority_pair_validation_conflict/ship_instrument_fail_verdict_beats_quote_not_reserved
    """
    world = setup_book_world(clock="2026-09-17T00:00:00.000Z")
    setup_reserved_quote(world)
    unit = setup_instrument_unit(world)
    start_setup(unit)
    complete_setup(unit, action_height_mm=1.50, relief_mm=0.10,
                   intonation_offset_cents=40)
    inspected = record_inspection(unit)
    assert inspected["inspection_overall"] == "FAIL"

    amended = amend_quote(world["quote"], world["engineer"])
    assert amended["status"] == "SUBMITTED"

    resp = api_client.ship_instrument_unit(unit["id"], SETUP_TECH)
    validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_PASSED)
    assert resp.json()["data"]["error_id"] != "ERR_QUOTE_NOT_RESERVED"


def test_rejected_ship_leaves_the_unit_and_quote_untouched():
    """PRD 2.11: "Once identity, existence, and request shape have passed, the
    state checks run." PRD 3.4: "A `FAIL` verdict, or a measurement changed
    after inspection, blocks shipment with `ERR_INSPECTION_NOT_PASSED` at HTTP
    422."

    Design: Difficulty/priority_pair_validation_conflict/ship_instrument_fail_verdict_beats_quote_not_reserved
    """
    world = setup_book_world(clock="2026-09-17T00:00:00.000Z")
    setup_reserved_quote(world)
    unit = setup_instrument_unit(world)
    start_setup(unit)
    complete_setup(unit, action_height_mm=1.50, relief_mm=0.10,
                   intonation_offset_cents=40)
    record_inspection(unit)
    amend_quote(world["quote"], world["engineer"])

    api_client.ship_instrument_unit(unit["id"], SETUP_TECH)

    after_unit = validate_success(api_client.get_instrument_unit(unit["id"], SETUP_TECH))
    assert after_unit["setup_status"] == "INSPECTED"
    assert after_unit["inspection_overall"] == "FAIL"
    after_quote = validate_success(api_client.get_quote(world["quote_id"], SALES_OPS))
    assert after_quote["status"] == "SUBMITTED"


def test_unauthorized_role_outranks_the_book_capacity_check_on_accept():
    """PRD 2.11: "Authentication comes first: missing or malformed identity
    headers produce `ERR_UNAUTHENTICATED` (401) before anything else is
    examined, and a well-formed caller whose role the endpoint does not admit
    produces `ERR_UNAUTHORIZED` (403) next." PRD 2.4: "a transition that would
    reach the ceiling or pass it is rejected with `ERR_BOOK_CAPACITY_EXCEEDED`
    at HTTP 422."

    Design: Difficulty/priority_pair_validation_conflict/accept_assignment_authorization_beats_book_and_overlap
    """
    set_clock("2026-09-18T00:00:00.000Z")
    full_engineer = create_engineer("Toni Vance", "toni.vance@sweetwater.example",
                                    "SOUTH", max_book_size=1)
    first_customer = create_customer()
    first = create_assignment(first_customer, full_engineer)
    accepted = accept_assignment(first)
    assert accepted["status"] == "ACTIVE"

    second_customer = create_customer("Sasha Poe", "sasha.poe@example.com", "TN")
    second = create_assignment(second_customer, full_engineer)
    assert second["status"] == "PENDING_ACCEPT"

    resp = api_client.accept_assignment(second["id"],
                                        {"X-User-ID": "test-setup-technician-1",
                                         "X-User-Role": "SetupTechnician",
                                         "Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    assert resp.json()["data"]["error_id"] != "ERR_BOOK_CAPACITY_EXCEEDED"


def test_rejected_accept_leaves_the_book_row_and_the_counter_unchanged():
    """PRD 2.4: "Accepting a pending assignment or reopening an ended one is
    admitted only while `active_book_size` is still strictly below
    `max_book_size`". PRD 3.1: "A `PENDING_ACCEPT` assignment is a proposal,
    and the engineer decides."

    Design: Difficulty/priority_pair_validation_conflict/accept_assignment_authorization_beats_book_and_overlap
    """
    set_clock("2026-09-18T00:00:00.000Z")
    full_engineer = create_engineer("Toni Vance", "toni.vance@sweetwater.example",
                                    "SOUTH", max_book_size=1)
    first_customer = create_customer()
    accept_assignment(create_assignment(first_customer, full_engineer))

    second_customer = create_customer("Sasha Poe", "sasha.poe@example.com", "TN")
    second = create_assignment(second_customer, full_engineer)

    api_client.accept_assignment(second["id"],
                                 {"X-User-ID": "test-setup-technician-1",
                                  "X-User-Role": "SetupTechnician",
                                  "Content-Type": "application/json"})

    after = validate_success(api_client.get_assignment(second["id"], SALES_OPS))
    assert after["status"] == "PENDING_ACCEPT"
    refreshed = validate_success(api_client.get_engineer(full_engineer["id"], SALES_OPS))
    assert refreshed["active_book_size"] == 1
    assert refreshed["active_book_size"] == refreshed["max_book_size"]


def test_second_registration_on_a_used_serial_number_is_refused():
    """PRD 3.4: "A serial number may back at most one instrument; registering a
    second unit against a serial already in use is refused with
    `ERR_SERIAL_ALREADY_REGISTERED` at HTTP 409."

    Design: Difficulty/boundary_precision_check/serial_registration_second_unit_conflicts_and_third_takes_next_block
    """
    world = setup_book_world(clock="2026-09-19T00:00:00.000Z")
    setup_reserved_quote(world)
    create_instrument_unit(world["guitar_line"], "SN-GTR-5521", "SW-GTR-100")

    resp = api_client.create_instrument_unit(
        {"quote_line_id": world["amp_line"]["id"], "serial_number": "SN-GTR-5521",
         "model_code": "SW-GTR-100"},
        SETUP_TECH,
    )
    validate_error(resp, ApiErrorId.ERR_SERIAL_ALREADY_REGISTERED)


def test_an_unseen_serial_number_registers_as_the_next_unit():
    """PRD 3.4: "A serialized instrument — a guitar, most often — is registered
    as an `InstrumentUnit` against the `quote_line_id` that sold it, carrying a
    `serial_number` and a `model_code`."

    Design: Difficulty/boundary_precision_check/serial_registration_second_unit_conflicts_and_third_takes_next_block
    """
    world = setup_book_world(clock="2026-09-19T00:00:00.000Z")
    setup_reserved_quote(world)
    create_instrument_unit(world["guitar_line"], "SN-GTR-5521", "SW-GTR-100")

    api_client.create_instrument_unit(
        {"quote_line_id": world["amp_line"]["id"], "serial_number": "SN-GTR-5521",
         "model_code": "SW-GTR-100"},
        SETUP_TECH,
    )
    fresh = create_instrument_unit(world["amp_line"], "SN-AMP-9903", "SW-AMP-050")
    assert fresh["serial_number"] == "SN-AMP-9903"


def test_a_rejected_serial_registration_creates_no_row():
    """PRD 3.4: "A serial number may back at most one instrument; registering a
    second unit against a serial already in use is refused with
    `ERR_SERIAL_ALREADY_REGISTERED` at HTTP 409."

    Design: Difficulty/boundary_precision_check/serial_registration_second_unit_conflicts_and_third_takes_next_block
    """
    world = setup_book_world(clock="2026-09-19T00:00:00.000Z")
    setup_reserved_quote(world)
    create_instrument_unit(world["guitar_line"], "SN-GTR-5521", "SW-GTR-100")

    api_client.create_instrument_unit(
        {"quote_line_id": world["amp_line"]["id"], "serial_number": "SN-GTR-5521",
         "model_code": "SW-GTR-100"},
        SETUP_TECH,
    )
    created = create_instrument_unit(world["amp_line"], "SN-AMP-9903", "SW-AMP-050")
    resp = api_client.list_instrument_units(SETUP_TECH,
                                            {"quote_line_id": world["amp_line"]["id"]})
    rows = resp.json()["data"]
    assert len(rows) == 1
    assert rows[0]["id"] == created["id"]

    all_units = api_client.list_instrument_units(SETUP_TECH).json()["data"]
    assert len([row for row in all_units if row["serial_number"] == "SN-GTR-5521"]) == 1


def test_preorder_sweep_is_admitted_at_the_exact_deadline():
    """PRD 3.5: "A claim enters the sweep from `PREORDER_PENDING` only while it
    is unfilled and still inside its preorder window — the logical clock must
    not be past `preorder_open_at` plus thirty days, and landing exactly on that
    deadline is still in time per §2.6."

    Design: Difficulty/boundary_precision_check/preorder_sweep_admitted_at_deadline_and_rejected_one_day_later
    """
    world = setup_book_world(clock="2026-09-20T00:00:00.000Z")
    setup_reserved_quote(world)
    backorder = create_backorder(world["guitar_line"], world["engineer"],
                                 units_requested=2,
                                 preorder_open_at="2026-09-20T00:00:00.000Z")
    assert backorder["eta_deadline"] == "2026-10-20T00:00:00.000Z"

    set_clock("2026-10-20T00:00:00.000Z")
    swept = start_sweep(backorder, pool_units=2)
    assert swept["status"] == "ALLOCATION_SWEEP"


def test_preorder_sweep_is_rejected_one_day_past_the_deadline():
    """PRD 3.5: "A sweep attempt past the window fails with
    `ERR_PREORDER_WINDOW_EXPIRED` at HTTP 409."

    Design: Difficulty/boundary_precision_check/preorder_sweep_admitted_at_deadline_and_rejected_one_day_later
    """
    world = setup_book_world(clock="2026-09-20T00:00:00.000Z")
    setup_reserved_quote(world)
    backorder = create_backorder(world["guitar_line"], world["engineer"],
                                 units_requested=2,
                                 preorder_open_at="2026-09-20T00:00:00.000Z")

    set_clock("2026-10-20T00:00:00.000Z")
    start_sweep(backorder, pool_units=2)
    set_clock("2026-10-21T00:00:00.000Z")
    reset_sweep(backorder)

    resp = api_client.start_sweep(backorder["id"], {"pool_units": 2}, SALES_OPS)
    validate_error(resp, ApiErrorId.ERR_PREORDER_WINDOW_EXPIRED)


def test_preorder_deadline_is_preorder_open_at_plus_thirty_days():
    """PRD 2.6: "A backorder's `eta_deadline` is its `preorder_open_at` plus
    thirty days, the last instant at which a preorder may still be honoured."

    Design: Difficulty/boundary_precision_check/preorder_sweep_admitted_at_deadline_and_rejected_one_day_later
    """
    world = setup_book_world(clock="2026-09-20T00:00:00.000Z")
    setup_reserved_quote(world)
    backorder = create_backorder(world["guitar_line"], world["engineer"],
                                 units_requested=2,
                                 preorder_open_at="2026-09-20T00:00:00.000Z")

    set_clock("2026-10-20T00:00:00.000Z")
    start_sweep(backorder, pool_units=2)
    set_clock("2026-10-21T00:00:00.000Z")
    reset_sweep(backorder)

    after = get_backorder(backorder["id"])
    assert after["status"] == "PREORDER_PENDING"
    assert after["eta_deadline"] == "2026-10-20T00:00:00.000Z"


def test_routing_a_claim_requires_an_open_center_with_spare_capacity():
    """PRD 3.6: "A claim in `PENDING_ROUTING` may be routed to its named center
    only if that center is `OPEN` — a suspended center refuses the route with
    `ERR_SERVICE_CENTER_SUSPENDED` at HTTP 409 — and only if the center's
    `open_ticket_count` has not yet reached its `capacity_slots`".

    Design: Difficulty/cross_entity_state_dependency/warranty_claim_route_requires_open_center_under_capacity
    """
    world = setup_book_world(clock="2026-09-22T00:00:00.000Z")
    setup_reserved_quote(world)
    shipped = setup_shipped_instrument(world)
    plan = create_warranty_plan(world["customer"], shipped, 24)
    plan = activate_warranty_plan(plan, "2026-09-22T00:00:00.000Z")
    center = create_service_center(name="Fort Wayne Bench", capacity_slots=1,
                                   accepted_families=["GUITAR"])
    claim = create_warranty_claim(plan, center)

    routed = route_claim(claim)
    assert routed["status"] == "ROUTED"
    assert routed["routed_at"] == "2026-09-22T00:00:00.000Z"


def test_a_full_open_center_refuses_a_second_route():
    """PRD 3.6: "only if the center's `open_ticket_count` has not yet reached
    its `capacity_slots`, because the center's capacity is a count of
    concurrently open tickets rather than a pairwise time check; a full desk
    refuses with `ERR_SERVICE_CENTER_CAPACITY_FULL` at HTTP 422."

    Design: Difficulty/cross_entity_state_dependency/warranty_claim_route_requires_open_center_under_capacity
    """
    world = setup_book_world(clock="2026-09-22T00:00:00.000Z")
    setup_reserved_quote(world)
    shipped = setup_shipped_instrument(world)
    plan = activate_warranty_plan(
        create_warranty_plan(world["customer"], shipped, 24), "2026-09-22T00:00:00.000Z")
    center = create_service_center(name="Fort Wayne Bench", capacity_slots=1,
                                   accepted_families=["GUITAR"])
    # Routing a claim moves its plan to REPAIR_IN_PROGRESS (PRD 3.6), so the
    # center's single slot is filled from a second plan on the same instrument,
    # leaving the plan under test ACTIVE and still claimable.
    filler_plan = activate_warranty_plan(
        create_warranty_plan(world["customer"], shipped, 24), "2026-09-22T00:00:00.000Z")
    route_claim(create_warranty_claim(filler_plan, center))

    second = create_warranty_claim(plan, center, "Dead pickup selector")
    resp = api_client.route_warranty_claim(second["id"], SUPPORT_AGENT)
    validate_error(resp, ApiErrorId.ERR_SERVICE_CENTER_CAPACITY_FULL)


def test_a_refused_route_leaves_the_claim_and_plan_untouched():
    """PRD 3.6: "Routing stamps `routed_at`, increments the center's
    `open_ticket_count`, moves the claim to `ROUTED`, moves the plan to
    `REPAIR_IN_PROGRESS`, and stores the service fee in its provisional form."

    Design: Difficulty/cross_entity_state_dependency/warranty_claim_route_requires_open_center_under_capacity
    """
    world = setup_book_world(clock="2026-09-22T00:00:00.000Z")
    setup_reserved_quote(world)
    shipped = setup_shipped_instrument(world)
    plan = activate_warranty_plan(
        create_warranty_plan(world["customer"], shipped, 24), "2026-09-22T00:00:00.000Z")
    center = create_service_center(name="Fort Wayne Bench", capacity_slots=1,
                                   accepted_families=["GUITAR"])
    filler_plan = activate_warranty_plan(
        create_warranty_plan(world["customer"], shipped, 24), "2026-09-22T00:00:00.000Z")
    route_claim(create_warranty_claim(filler_plan, center))
    second = create_warranty_claim(plan, center, "Dead pickup selector")

    api_client.route_warranty_claim(second["id"], SUPPORT_AGENT)

    after_claim = validate_success(
        api_client.get_warranty_claim(second["id"], SUPPORT_AGENT))
    assert after_claim["status"] == "PENDING_ROUTING"
    after_plan = validate_success(api_client.get_warranty_plan(plan["id"], SUPPORT_AGENT))
    assert after_plan["status"] == "CLAIM_OPEN"


def test_ship_requires_the_owning_quote_to_be_reserved():
    """PRD 3.4: "Shipping additionally requires the unit's quote to still be
    `RESERVED`, which is the instrument-side consequence of §3.3's amendment
    path: an instrument whose quote has been amended back to `SUBMITTED` is
    held at the bench and refused with `ERR_QUOTE_NOT_RESERVED` at HTTP 409."

    Design: Difficulty/cross_entity_state_dependency/instrument_ship_requires_owning_quote_reserved
    """
    world = setup_book_world(clock="2026-09-21T00:00:00.000Z")
    setup_reserved_quote(world)
    unit = setup_inspected_instrument(world)
    amended = amend_quote(world["quote"], world["engineer"])
    assert amended["status"] == "SUBMITTED"

    resp = api_client.ship_instrument_unit(unit["id"], SETUP_TECH)
    validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_RESERVED)
    after = validate_success(api_client.get_instrument_unit(unit["id"], SETUP_TECH))
    assert after["setup_status"] == "INSPECTED"


def test_ship_succeeds_once_the_quote_is_reserved_again():
    """PRD 3.4: "Shipping additionally requires the unit's quote to still be
    `RESERVED`". PRD 3.4: "A successful shipment stamps `shipped_at` from the
    logical clock, marks the unit `SHIPPED`".

    Design: Difficulty/cross_entity_state_dependency/instrument_ship_requires_owning_quote_reserved
    """
    world = setup_book_world(clock="2026-09-21T00:00:00.000Z")
    setup_reserved_quote(world)
    unit = setup_inspected_instrument(world)
    amend_quote(world["quote"], world["engineer"])

    from test_helpers.fixtures import reserve_quote

    current = validate_success(api_client.get_quote(world["quote_id"], SALES_OPS))
    re_reserved = reserve_quote(current, world["engineer"],
                                expected_quote_version=current["version"])
    assert re_reserved["status"] == "RESERVED"

    shipped = validate_success(api_client.ship_instrument_unit(unit["id"], SETUP_TECH))
    assert shipped["setup_status"] == "SHIPPED"
    assert shipped["shipped_at"] == "2026-09-21T00:00:00.000Z"


def test_ship_succeeds_when_the_quote_still_holds_its_reservation():
    """PRD 3.4: "A unit may ship only from `INSPECTED`, only when its
    `inspection_overall` is `PASS` or `CONDITIONAL`, and only when
    `modified_since_setup` is false".

    Design: Difficulty/cross_entity_state_dependency/instrument_ship_requires_owning_quote_reserved
    """
    world = setup_book_world(clock="2026-09-21T00:00:00.000Z")
    setup_reserved_quote(world)
    unit = setup_inspected_instrument(world)
    shipped = validate_success(api_client.ship_instrument_unit(unit["id"], SETUP_TECH))
    assert shipped["setup_status"] == "SHIPPED"
    assert NON_EXISTENT_UUID is not None