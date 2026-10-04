"""Breadth: initial states, terminal lockdown, invalid transitions, side effects."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    SALES_OPS,
    SETUP_TECH,
    SUPPORT_AGENT,
    accept_assignment,
    add_quote_line,
    create_quote,
    create_service_center,
    create_support_ticket,
    create_instrument_unit,
    decline_assignment,
    reject_quote,
    setup_book_world,
    setup_reserved_quote,
    setup_shipped_book_with_active_plan,
    setup_shipped_instrument,
    setup_instrument_unit,
    start_setup,
    submit_quote,
    triage_ticket,
    walk_unit_to_inspected,
    walk_unit_to_shipped,
    get_support_ticket,
    ledger_rows_for_ticket,
)


def test_assignment_starts_pending_with_no_assigned_at():
    """PRD 3.1: "Ownership arrives through an `Assignment`, created by an
    operations desk in `PENDING_ACCEPT` status". PRD 2.4: "`assigned_at` is
    never accepted from a client; it is stamped from the service's logical clock
    at the moment the row first transitions into `ACTIVE`."

    Design: Corner/state_machines/assignment_starts_pending_and_second_accept_is_rejected
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z", with_catalog=False,
                             accept=False)
    assignment = world["assignment"]
    assert assignment["status"] == "PENDING_ACCEPT"
    assert assignment.get("assigned_at") is None


def test_a_second_accept_on_an_active_assignment_is_an_invalid_state():
    """PRD 3.1: "Acceptance succeeds only when the engineer is in `ACTIVE`
    status, when their `active_book_size` is still strictly below their
    `max_book_size`, and when no other assignment for the same customer is
    already `ACTIVE`".

    Design: Corner/state_machines/assignment_starts_pending_and_second_accept_is_rejected
    """
    world = setup_book_world(clock="2026-09-02T00:00:00.000Z", with_catalog=False,
                             accept=False)
    accepted = accept_assignment(world["assignment"])
    assert accepted["status"] == "ACTIVE"
    assert accepted["assigned_at"] == "2026-09-02T00:00:00.000Z"

    resp = api_client.accept_assignment(
        world["assignment_id"],
        {"X-User-ID": world["engineer_id"], "X-User-Role": "Engineer",
         "Content-Type": "application/json"},
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_a_rejected_second_accept_does_not_double_count_the_book():
    """PRD 2.4: "Accepting a pending assignment or reopening an ended one is
    admitted only while `active_book_size` is still strictly below
    `max_book_size`". PRD 2.8: "`active_book_size` counts an engineer's `ACTIVE`
    assignments."

    Design: Corner/state_machines/assignment_starts_pending_and_second_accept_is_rejected
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z", with_catalog=False)
    api_client.accept_assignment(
        world["assignment_id"],
        {"X-User-ID": world["engineer_id"], "X-User-Role": "Engineer",
         "Content-Type": "application/json"},
    )
    engineer = validate_success(api_client.get_engineer(world["engineer_id"], SALES_OPS))
    assert engineer["active_book_size"] == 1


def test_shipped_instrument_is_terminal_and_refuses_a_second_ship():
    """PRD 3.4: "Shipment is terminal — an action attempted against a `SHIPPED`
    unit raises `ERR_ALREADY_TERMINAL` at HTTP 409."

    Design: Corner/state_machines/shipped_instrument_is_terminal_and_cannot_ship_again
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    shipped = setup_shipped_instrument(world)
    assert shipped["setup_status"] == "SHIPPED"

    resp = api_client.ship_instrument_unit(shipped["id"], SETUP_TECH)
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


def test_rejected_reship_leaves_shipped_at_and_purchase_count_untouched():
    """PRD 3.4: "A successful shipment stamps `shipped_at` from the logical
    clock, marks the unit `SHIPPED`, recomputes the customer's
    `purchased_instrument_count` for the quote's customer"."

    Design: Corner/state_machines/shipped_instrument_is_terminal_and_cannot_ship_again
    """
    world = setup_book_world(clock="2026-09-02T00:00:00.000Z")
    setup_reserved_quote(world)
    shipped = setup_shipped_instrument(world)
    assert shipped["shipped_at"] == "2026-09-02T00:00:00.000Z"

    api_client.ship_instrument_unit(shipped["id"], SETUP_TECH)

    after = validate_success(api_client.get_instrument_unit(shipped["id"], SETUP_TECH))
    assert after["setup_status"] == "SHIPPED"
    assert after["shipped_at"] == "2026-09-02T00:00:00.000Z"
    customer = validate_success(api_client.get_customer(world["customer_id"], SALES_OPS))
    assert customer["purchased_instrument_count"] == 1


def test_shipping_recomputes_the_customer_purchase_count():
    """PRD 2.8: "`purchased_instrument_count` on a customer counts the sold
    lines tied to that customer's quotes."

    Design: Corner/state_machines/shipped_instrument_is_terminal_and_cannot_ship_again
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    setup_shipped_instrument(world)
    customer = validate_success(api_client.get_customer(world["customer_id"], SALES_OPS))
    assert customer["purchased_instrument_count"] == 1


def test_record_inspection_from_pending_setup_is_an_invalid_transition():
    """PRD 3.4: "Recording the inspection is available only from
    `SETUP_COMPLETE` and is the step that re-evaluates the verdict in its final
    form". PRD 2.11: "A resource that is not in a state the requested transition
    admits fails with `ERR_INVALID_STATE` at HTTP 409".

    Design: Corner/state_machines/record_inspection_from_pending_setup_returns_invalid_state
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    unit = setup_instrument_unit(world)
    assert unit["setup_status"] == "PENDING_SETUP"

    resp = api_client.record_inspection(unit["id"], SETUP_TECH)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_rejected_inspection_leaves_the_unit_baseline_untouched():
    """PRD 3.4: "Starting setup is available only from `PENDING_SETUP`; it
    records the acting technician's identifier as `setup_technician_id`, seeds
    `inspection_overall` to `PASS` as a baseline, and clears
    `modified_since_setup` to false before any measurement exists."

    Design: Corner/state_machines/record_inspection_from_pending_setup_returns_invalid_state
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    unit = setup_instrument_unit(world)
    api_client.record_inspection(unit["id"], SETUP_TECH)

    after = validate_success(api_client.get_instrument_unit(unit["id"], SETUP_TECH))
    assert after["setup_status"] == "PENDING_SETUP"
    assert after["modified_since_setup"] is False
    assert after.get("setup_technician_id") is None


def test_quote_reject_clears_the_bundle_ready_flag():
    """PRD 3.2: "An operations desk may reject it, returning it to `REJECTED`
    and recomputing `bundle_ready` to false so that the engineer must
    re-establish readiness before resubmitting."

    Design: Corner/state_machines/quote_reject_clears_bundle_ready_side_effect
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    quote = create_quote(world["customer"], world["engineer"], "SYSTEM_PACKAGE")
    anchor = add_quote_line(quote, world["engineer"], product_code="SW-GTR-100",
                            quantity=1, is_anchor=True)
    add_quote_line(quote, world["engineer"], product_code="SW-AMP-050", quantity=1,
                   requires_line_id=anchor["id"])
    submitted = submit_quote(quote, world["engineer"])
    assert submitted["bundle_ready"] is True

    rejected = reject_quote(submitted, SALES_OPS)
    assert rejected["status"] == "REJECTED"
    assert rejected["bundle_ready"] is False


def test_reject_leaves_the_quotes_lines_intact():
    """PRD 3.2: "The service recomputes `dependency_closure_size`,
    `bundle_ready`, and the quote's `gross_subtotal_cents` every time a line is
    added and again at submission."

    Design: Corner/state_machines/quote_reject_clears_bundle_ready_side_effect
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    quote = create_quote(world["customer"], world["engineer"], "SYSTEM_PACKAGE")
    anchor = add_quote_line(quote, world["engineer"], product_code="SW-GTR-100",
                            quantity=1, is_anchor=True)
    add_quote_line(quote, world["engineer"], product_code="SW-AMP-050", quantity=1,
                   requires_line_id=anchor["id"])
    submit_quote(quote, world["engineer"])
    reject_quote(validate_success(api_client.get_quote(quote["id"], SALES_OPS)), SALES_OPS)

    lines = validate_success(
        api_client.list_quote_lines_for_quote(quote["id"], SALES_OPS))
    assert len(lines) == 2


def test_escalation_needs_the_extended_entitlement_precondition():
    """PRD 3.7: "First, the ticket's `required_entitlement` must be `EXTENDED`;
    a ticket computed as `BASIC` cannot be escalated and is refused with
    `ERR_ESCALATION_NOT_PERMITTED` at HTTP 422."

    Design: Corner/state_machines/escalation_requires_extended_entitlement_precondition
    """
    # An ACTIVE assignment plus one purchased instrument earns BASIC with no
    # warranty in force (PRD 3.7), so the ticket triages and computes as BASIC.
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    setup_shipped_instrument(world)
    center = create_service_center()
    ticket = create_support_ticket(world["customer"], center)
    triaged = triage_ticket(ticket)
    assert triaged["required_entitlement"] == "BASIC"

    resp = api_client.escalate_support_ticket(ticket["id"], SUPPORT_AGENT)
    validate_error(resp, ApiErrorId.ERR_ESCALATION_NOT_PERMITTED)


def test_a_refused_escalation_appends_no_ledger_row_and_books_no_slot():
    """PRD 3.7: "It increments the service center's `open_ticket_count`, and it
    increments the ticket's `escalation_count`, which counts the escalation
    ledger rows appended against that ticket."

    Design: Corner/state_machines/escalation_requires_extended_entitlement_precondition
    """
    # A BASIC ticket cannot be escalated (PRD 3.7): an ACTIVE assignment plus a
    # purchase earns triage, but with no warranty in force the requirement is
    # BASIC, so the escalation is refused and nothing is booked.
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    setup_shipped_instrument(world)
    center = create_service_center()
    ticket = create_support_ticket(world["customer"], center)
    triage_ticket(ticket)
    api_client.escalate_support_ticket(ticket["id"], SUPPORT_AGENT)

    after = get_support_ticket(ticket["id"])
    assert after["status"] == "IN_TRIAGE"
    assert after.get("escalated_at") is None
    assert ledger_rows_for_ticket(ticket["id"]) == []
    rows = api_client.list_service_centers(SUPPORT_AGENT, {"region": "MIDWEST"}).json()["data"]
    assert [row for row in rows if row["id"] == center["id"]][0]["open_ticket_count"] == 0


def test_declining_an_active_assignment_is_an_invalid_state():
    """PRD 3.1: "Declining is the other exit from `PENDING_ACCEPT`, and it is
    quieter. A declined assignment moves to `ENDED`".

    Design: Corner/state_machines/assignment_decline_after_active_returns_invalid_state
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z", with_catalog=False)
    assert world["assignment"]["status"] == "ACTIVE"

    resp = api_client.decline_assignment(
        world["assignment_id"],
        {"X-User-ID": world["engineer_id"], "X-User-Role": "Engineer",
         "Content-Type": "application/json"},
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_rejected_decline_leaves_the_mirror_and_counter_untouched():
    """PRD 3.1: "Acceptance stamps `assigned_at` from the logical clock, advances
    the customer's `sequence` bookkeeping by assigning the next index,
    increments the holding engineer's `active_book_size`, and mirrors the holder
    into the customer's `assigned_engineer_id`."

    Design: Corner/state_machines/assignment_decline_after_active_returns_invalid_state
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z", with_catalog=False)
    api_client.decline_assignment(
        world["assignment_id"],
        {"X-User-ID": world["engineer_id"], "X-User-Role": "Engineer",
         "Content-Type": "application/json"},
    )
    after = validate_success(api_client.get_assignment(world["assignment_id"], SALES_OPS))
    assert after["status"] == "ACTIVE"
    customer = validate_success(api_client.get_customer(world["customer_id"], SALES_OPS))
    assert customer["assigned_engineer_id"] == world["engineer_id"]
    engineer = validate_success(api_client.get_engineer(world["engineer_id"], SALES_OPS))
    assert engineer["active_book_size"] == 1