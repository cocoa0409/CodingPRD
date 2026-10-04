"""Depth: cyclic state machines — assignment reopen and quote amend/re-reserve."""
from test_helpers import validate_success
from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    SALES_OPS,
    add_quote_line,
    amend_quote,
    backorders_for,
    create_quote,
    end_assignment,
    quote_version,
    reopen_assignment,
    reserve_quote,
    setup_book_world,
    setup_reserved_quote,
    submit_quote,
    get_customer as read_customer,
    get_engineer as read_engineer,
)


def test_ended_assignment_reopens_back_to_active_with_sequence_incremented():
    """PRD 3.1: "Reopening an ended assignment is available to an operations
    desk or an administrator, and it puts a customer's book back under an
    engineer after a gap. It requires the assignment to be `ENDED`, the engineer
    to be `ACTIVE`, the engineer to have room under `max_book_size`" PRD 3.1:
    "Reopening restamps `assigned_at` from the logical clock, increments the
    assignment's `sequence` index by one, sets `assigned_engineer_id` again, and
    re-increments the engineer's `active_book_size`."

    Design: Difficulty/non_linear_state_machine/assignment_cyclic_reopen_returns_ended_book_to_active
    """
    world = setup_book_world(clock="2026-09-13T00:00:00.000Z", with_catalog=False)
    ended = end_assignment(world["assignment"], SALES_OPS)
    assert ended["status"] == "ENDED"
    sequence_at_end = ended["sequence"]

    reopened = reopen_assignment(world["assignment"], SALES_OPS)
    assert reopened["status"] == "ACTIVE"
    assert reopened["sequence"] == sequence_at_end + 1


def test_reopen_restores_the_customer_slot_mirror_and_the_book_counter():
    """PRD 3.1: "Reopening restamps `assigned_at` from the logical clock,
    increments the assignment's `sequence` index by one, sets
    `assigned_engineer_id` again, and re-increments the engineer's
    `active_book_size`."

    Design: Difficulty/non_linear_state_machine/assignment_cyclic_reopen_returns_ended_book_to_active
    """
    world = setup_book_world(clock="2026-09-13T00:00:00.000Z", with_catalog=False)
    end_assignment(world["assignment"], SALES_OPS)
    assert read_customer(world["customer_id"])["assigned_engineer_id"] is None
    assert read_engineer(world["engineer_id"])["active_book_size"] == 0

    reopen_assignment(world["assignment"], SALES_OPS)

    assert read_customer(world["customer_id"])["assigned_engineer_id"] == world["engineer_id"]
    assert read_engineer(world["engineer_id"])["active_book_size"] == 1


def test_reopened_interval_stamps_assigned_at_from_the_logical_clock():
    """PRD 2.4: "`assigned_at` is never accepted from a client; it is stamped
    from the service's logical clock at the moment the row first transitions
    into `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/assignment_cyclic_reopen_returns_ended_book_to_active
    """
    world = setup_book_world(clock="2026-09-13T00:00:00.000Z", with_catalog=False)
    end_assignment(world["assignment"], SALES_OPS)
    assert read_customer(world["customer_id"])["assigned_engineer_id"] is None

    from test_helpers.fixtures import set_clock

    set_clock("2026-09-20T00:00:00.000Z")
    reopened = reopen_assignment(world["assignment"], SALES_OPS)
    assert reopened["assigned_at"] == "2026-09-20T00:00:00.000Z"


def test_amend_returns_a_reserved_quote_to_submitted_and_clears_reserved_at():
    """PRD 3.3: "Amendment unwinds a reservation that has not yet been
    fulfilled. It is available to the authoring engineer, requires the quote to
    be `RESERVED`, and requires that no backorder on any of its lines has
    reached `BOARD_FILLED`, `SHIPPED`, or `RECEIVING`". PRD 3.3: "Amendment
    clears `reserved_at` to null, advances `version` by one, returns the quote
    to `SUBMITTED`".

    Design: Difficulty/non_linear_state_machine/quote_branching_cycle_reserved_back_to_submitted_and_again
    """
    world = setup_book_world(clock="2026-09-14T00:00:00.000Z")
    setup_reserved_quote(world)
    quote = world["quote"]
    assert quote["status"] == "RESERVED"
    assert quote["reserved_at"] is not None

    amended = amend_quote(quote, world["engineer"])
    assert amended["status"] == "SUBMITTED"
    assert amended["reserved_at"] is None


def test_second_reservation_returns_the_quote_to_reserved_and_bumps_version():
    """PRD 3.2: "Cancellation is available to both the authoring engineer and
    the operations desk, but only from `DRAFT` or `REJECTED` — a quote that has
    been reserved has to be unwound through the amendment path described in
    §3.3 instead." PRD 2.5: "A reservation request against a `Quote` must carry
    `expected_quote_version` in its body."

    Design: Difficulty/non_linear_state_machine/quote_branching_cycle_reserved_back_to_submitted_and_again
    """
    world = setup_book_world(clock="2026-09-14T00:00:00.000Z")
    setup_reserved_quote(world)
    quote = world["quote"]

    amended = amend_quote(quote, world["engineer"])
    version_after_amend = amended["version"]

    reservable = validate_success(api_client.get_quote(quote["id"], SALES_OPS))
    re_reserved = reserve_quote(reservable, world["engineer"],
                                expected_quote_version=version_after_amend)
    assert re_reserved["status"] == "RESERVED"
    assert re_reserved["reserved_at"] is not None
    assert re_reserved["version"] == version_after_amend + 1


def test_each_reservation_advances_the_quote_version_exactly_once():
    """PRD 2.5: "Reserving a quote is the first. A reservation request against
    a `Quote` must carry `expected_quote_version` in its body."

    Design: Difficulty/non_linear_state_machine/quote_branching_cycle_reserved_back_to_submitted_and_again
    """
    world = setup_book_world(clock="2026-09-14T00:00:00.000Z")
    setup_reserved_quote(world)
    initial_version = world["quote"]["version"]

    amended = amend_quote(world["quote"], world["engineer"])
    assert amended["version"] == initial_version + 1

    re_reserved = reserve_quote(amended, world["engineer"],
                                expected_quote_version=amended["version"])
    assert re_reserved["version"] == amended["version"] + 1


def test_amend_cancels_the_swept_backorders_and_a_fresh_set_is_created():
    """PRD 3.3: "Amendment clears `reserved_at` to null, advances `version` by
    one, returns the quote to `SUBMITTED`, and cancels the backorders that the
    prior reservation created to the extent they are still sitting in
    `ALLOCATION_SWEEP`." PRD 3.3: "creates exactly one `Backorder` per
    `QuoteLine` on that quote, each in `PREORDER_PENDING` status".

    Design: Difficulty/non_linear_state_machine/quote_branching_cycle_reserved_back_to_submitted_and_again
    """
    world = setup_book_world(clock="2026-09-14T00:00:00.000Z")
    setup_reserved_quote(world)
    quote = world["quote"]

    first_set = backorders_for({"quote_line_id": world["guitar_line"]["id"]})
    assert len(first_set) == 1
    assert first_set[0]["status"] in ("PREORDER_PENDING", "ALLOCATION_SWEEP")

    for backorder in first_set:
        api_client.start_sweep(backorder["id"], {"pool_units": 1}, SALES_OPS)

    amend_quote(quote, world["engineer"])
    after_amend = backorders_for({"quote_line_id": world["guitar_line"]["id"]})
    assert [row["status"] for row in after_amend if row["id"] in
            [b["id"] for b in first_set]] == ["CANCELLED"]

    re_reserved = reserve_quote(
        validate_success(api_client.get_quote(quote["id"], SALES_OPS)),
        world["engineer"],
        expected_quote_version=quote_version(quote["id"], SALES_OPS),
    )
    assert re_reserved["status"] == "RESERVED"
    fresh = backorders_for({"quote_line_id": world["guitar_line"]["id"]})
    pending = [row for row in fresh if row["status"] == "PREORDER_PENDING"]
    assert len(pending) == 1


def test_submitted_quote_without_an_active_assignment_cannot_be_reserved():
    """PRD 3.2: "An unassigned account, or one that has been reassigned to a
    different engineer, cannot have a quote submitted or reserved against it,
    whether the acting role is the engineer or the operations desk: both are
    refused with `ERR_CUSTOMER_ASSIGNMENT_REQUIRED` at HTTP 422."

    Design: Difficulty/non_linear_state_machine/quote_branching_cycle_reserved_back_to_submitted_and_again
    """
    from test_helpers import ApiErrorId, validate_error

    world = setup_book_world(clock="2026-09-14T00:00:00.000Z")
    setup_reserved_quote(world)
    quote = world["quote"]

    amended = amend_quote(quote, world["engineer"])
    assert amended["status"] == "SUBMITTED"

    end_assignment(world["assignment"], SALES_OPS)

    resp = api_client.reserve_quote(quote["id"],
                                    {"expected_quote_version": quote_version(quote["id"], SALES_OPS)},
                                    {"X-User-ID": world["engineer_id"], "X-User-Role": "Engineer",
                                     "Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_ASSIGNMENT_REQUIRED)