"""Depth: the inspection-verdict fold and the assignment-end escalation cascade."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    SALES_OPS,
    SETUP_TECH,
    SUPPORT_AGENT,
    complete_setup,
    create_service_center,
    create_support_ticket,
    end_assignment,
    get_ticket,
    ledger_rows_for_ticket,
    record_inspection,
    setup_book_world,
    setup_instrument_unit,
    setup_reserved_quote,
    setup_shipped_book_with_active_plan,
    start_setup,
    triage_ticket,
)


def _center_row(center_id):
    resp = api_client.list_service_centers(SUPPORT_AGENT, {"region": "MIDWEST"})
    rows = resp.json()["data"]
    return [row for row in rows if row["id"] == center_id][0]


def test_preliminary_verdict_grades_two_of_three_with_intonation_failing_as_conditional():
    """PRD 3.4: "the preliminary variant used at setup completion assigns `PASS`
    when all three pass, `CONDITIONAL` when exactly two pass, and `FAIL` when
    one or none pass." PRD 3.4: "Intonation passes when the absolute deviation
    is at most 5 cents."

    Design: Difficulty/combinatorial_formula/inspection_verdict_three_input_conditional_fold
    """
    world = setup_book_world(clock="2026-09-11T00:00:00.000Z")
    setup_reserved_quote(world)
    unit = setup_instrument_unit(world)
    start_setup(unit)

    completed = complete_setup(unit, action_height_mm=1.50, relief_mm=0.10,
                               intonation_offset_cents=12)
    assert completed["inspection_overall"] == "CONDITIONAL", (
        "action height 1.50 and relief 0.10 pass; intonation deviation 12 "
        "exceeds the 5-cent tolerance, so exactly two of three pass"
    )
    assert completed["setup_status"] == "SETUP_COMPLETE"


def test_final_verdict_grades_a_failed_intonation_as_fail():
    """PRD 3.4: "The final variant used at recorded inspection differs only in
    the two-check case: three passes still yield `PASS`, but of the three
    possible two-of-three combinations, only the ones in which intonation
    passed yield `CONDITIONAL` — a two-of-three unit whose failing check is
    intonation is graded `FAIL`."

    Design: Difficulty/combinatorial_formula/inspection_verdict_three_input_conditional_fold
    """
    world = setup_book_world(clock="2026-09-11T00:00:00.000Z")
    setup_reserved_quote(world)
    unit = setup_instrument_unit(world)
    start_setup(unit)
    complete_setup(unit, action_height_mm=1.50, relief_mm=0.10,
                   intonation_offset_cents=12)

    inspected = record_inspection(unit)
    assert inspected["inspection_overall"] == "FAIL"
    assert inspected["setup_status"] == "INSPECTED"


def test_fail_verdict_blocks_shipment_with_inspection_not_passed():
    """PRD 3.4: "A unit may ship only from `INSPECTED`, only when its
    `inspection_overall` is `PASS` or `CONDITIONAL`, and only when
    `modified_since_setup` is false — a `FAIL` verdict, or a measurement changed
    after inspection, blocks shipment with `ERR_INSPECTION_NOT_PASSED` at HTTP
    422."

    Design: Difficulty/combinatorial_formula/inspection_verdict_three_input_conditional_fold
    """
    world = setup_book_world(clock="2026-09-11T00:00:00.000Z")
    setup_reserved_quote(world)
    unit = setup_instrument_unit(world)
    start_setup(unit)
    complete_setup(unit, action_height_mm=1.50, relief_mm=0.10,
                   intonation_offset_cents=12)
    record_inspection(unit)

    resp = api_client.ship_instrument_unit(unit["id"], SETUP_TECH)
    validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_PASSED)


def test_conditional_verdict_still_ships_because_intonation_passed():
    """PRD 3.4: "only the ones in which intonation passed yield `CONDITIONAL`".
    PRD 3.4: "A unit may ship only from `INSPECTED`, only when its
    `inspection_overall` is `PASS` or `CONDITIONAL`, and only when
    `modified_since_setup` is false".

    Design: Difficulty/combinatorial_formula/inspection_verdict_three_input_conditional_fold
    """
    world = setup_book_world(clock="2026-09-11T00:00:00.000Z")
    setup_reserved_quote(world)
    unit = setup_instrument_unit(world)
    start_setup(unit)

    # Action height 3.10 fails its range, relief 0.20 passes, intonation 1 passes.
    completed = complete_setup(unit, action_height_mm=3.10, relief_mm=0.20,
                               intonation_offset_cents=1)
    assert completed["inspection_overall"] == "CONDITIONAL"

    inspected = record_inspection(unit)
    assert inspected["inspection_overall"] == "CONDITIONAL"
    assert inspected["modified_since_setup"] is False

    shipped = validate_success(api_client.ship_instrument_unit(unit["id"], SETUP_TECH))
    assert shipped["setup_status"] == "SHIPPED"
    assert shipped["shipped_at"] == "2026-09-11T00:00:00.000Z"


def test_ending_assignment_escalates_the_extended_entitlement_ticket():
    """PRD 3.1: "The third hop escalates every one of that customer's open
    support tickets that is in `OPEN` or `IN_TRIAGE` status and whose
    `required_entitlement` is `EXTENDED`, moving each to `ESCALATED` and
    stamping its `escalated_at` from the logical clock and its `escalated_by`
    from the acting operator's identifier."

    Design: Difficulty/transitive_cascade/assignment_end_escalates_tickets_to_service_desk
    """
    world = setup_shipped_book_with_active_plan(clock="2026-09-15T00:00:00.000Z")
    center = create_service_center(name="Indianapolis Bench", capacity_slots=2,
                                   accepted_families=["GUITAR", "AMPLIFIER"])
    ticket = create_support_ticket(world["customer"], center)
    triaged = triage_ticket(ticket)
    assert triaged["required_entitlement"] == "EXTENDED"

    end_assignment(world["assignment"], SALES_OPS)

    after = get_ticket(ticket["id"])
    assert after["status"] == "ESCALATED"
    assert after["escalated_at"] == "2026-09-15T00:00:00.000Z"
    assert after["escalated_by"] == "test-sales-engineer-ops-1"


def test_ending_assignment_appends_exactly_one_escalation_ledger_row():
    """PRD 3.7: "It assigns `escalation_seq` on the ticket as one more than the
    highest `escalation_seq` currently recorded in the escalation ledger for
    that same ticket, and appends exactly one `EscalationLedger` row with an
    `event_type` of `SERVICE_DEPARTMENT_ESCALATION`".

    Design: Difficulty/transitive_cascade/assignment_end_escalates_tickets_to_service_desk
    """
    world = setup_shipped_book_with_active_plan(clock="2026-09-15T00:00:00.000Z")
    center = create_service_center()
    ticket = create_support_ticket(world["customer"], center)
    triage_ticket(ticket)

    end_assignment(world["assignment"], SALES_OPS)

    rows = ledger_rows_for_ticket(ticket["id"])
    assert len(rows) == 1
    assert rows[0]["event_type"] == "SERVICE_DEPARTMENT_ESCALATION"
    assert rows[0]["escalation_seq"] == 1
    after = get_ticket(ticket["id"])
    assert after["escalation_seq"] == 1
    assert after["escalation_count"] == 1


def test_ending_assignment_consumes_a_service_center_slot():
    """PRD 3.1: "The fourth hop increments `open_ticket_count` on each such
    ticket's named service center, because an escalated ticket now occupies a
    desk slot."

    Design: Difficulty/transitive_cascade/assignment_end_escalates_tickets_to_service_desk
    """
    world = setup_shipped_book_with_active_plan(clock="2026-09-15T00:00:00.000Z")
    center = create_service_center(name="Indianapolis Bench", capacity_slots=2)
    ticket = create_support_ticket(world["customer"], center)
    triage_ticket(ticket)
    assert _center_row(center["id"])["open_ticket_count"] == 0

    end_assignment(world["assignment"], SALES_OPS)

    assert _center_row(center["id"])["open_ticket_count"] == 1


def test_ending_assignment_clears_the_book_mirror_and_occupancy_counter():
    """PRD 3.1: "When an `ACTIVE` assignment is ended, the customer's
    `assigned_engineer_id` is cleared to null, the holding engineer's
    `active_book_size` drops by one, and a four-hop cascade unwinds the
    customer's post-sale support."

    Design: Difficulty/transitive_cascade/assignment_end_escalates_tickets_to_service_desk
    """
    world = setup_shipped_book_with_active_plan(clock="2026-09-15T00:00:00.000Z")
    center = create_service_center()
    ticket = create_support_ticket(world["customer"], center)
    triage_ticket(ticket)

    ended = end_assignment(world["assignment"], SALES_OPS)
    assert ended["status"] == "ENDED"

    customer = validate_success(api_client.get_customer(world["customer_id"], SALES_OPS))
    assert customer["assigned_engineer_id"] is None

    engineer = validate_success(api_client.get_engineer(world["engineer_id"], SALES_OPS))
    assert engineer["active_book_size"] == 0