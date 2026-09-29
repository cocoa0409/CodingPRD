"""Shift settlement: declared cash against priced checks, and the variance tolerance.

Covers PRD section 3.5 (declaring a batch, reconciliation and the tolerance verdict)
and the settlement-verification step of PRD section 3.8.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_fields,
    assert_int,
    assert_money,
    assert_money_fields,
    assert_row_count,
)
from test_helpers.test_users import (
    AUDITOR,
    REVENUE_MANAGER,
    make_outlet_manager_headers,
)


def _two_batches_astride_the_tolerance(api):
    """Two outlets, each with a 150.45 system amount, declaring 155.45 and 155.46."""
    fx.set_clock(api, "2026-08-01T20:00:00.000Z")
    prop = fx.create_property(api)
    cafe = fx.create_outlet(
        api,
        prop["id"],
        outlet_code="CAFE",
        outlet_name="Harbor Cafe",
        outlet_type="FB_OUTLET",
        requires_shift_settlement=True,
    )
    bar = fx.create_outlet(
        api,
        prop["id"],
        outlet_code="BAR",
        outlet_name="Harbor Bar",
        outlet_type="REMOTE_POS",
        requires_shift_settlement=True,
    )
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    for outlet, number in [(cafe, "C-001"), (bar, "B-001")]:
        ticket = fx.create_outlet_ticket(
            api,
            outlet["id"],
            bd["id"],
            gross_amount=120.00,
            ticket_number=number,
            settlement_type="CASH",
            opened_at="2026-08-01T17:30:00.000Z",
        )
        fx.close_outlet_ticket(
            api, ticket["id"], outlet["id"], transmitted_at="2026-08-01T18:00:00.000Z"
        )
    at_tolerance = fx.create_settlement_batch(api, bd["id"], cafe["id"], 155.45)
    over_tolerance = fx.create_settlement_batch(api, bd["id"], bar["id"], 155.46)
    fx.post_room_and_tax(api, bd["id"])
    fx.seal_charges(api, bd["id"])
    return prop, bd, at_tolerance, over_tolerance


def test_a_variance_landing_exactly_on_the_tolerance_matches(api):
    """5.00 against a 5.00 tolerance matches; 5.01 flags.

    PRD section 3.5 computes `system_amount` as the sum of `total_amount` over the
    checks matching the batch's outlet, day, tender type and half-open window, sets
    `variance_amount` to `declared_amount` minus that figure, and compares its absolute
    value inclusively against `settlement_variance_tolerance_amount`: a variance landing
    exactly on the tolerance matches and one cent beyond it flags.

    Design: Difficulty/boundary_precision_check/settlement_variance_tolerance_inclusive_at_five_dollars
    """
    _prop, bd, at_tolerance, over_tolerance = _two_batches_astride_the_tolerance(api)

    fx.verify_settlements(api, bd["id"])

    matched = fx.read_batch(api, at_tolerance["id"])
    assert_money_fields(matched, {"system_amount": 150.45, "variance_amount": 5.00})
    assert_fields(matched, {"status": "MATCHED"})

    flagged = fx.read_batch(api, over_tolerance["id"])
    assert_money_fields(flagged, {"system_amount": 150.45, "variance_amount": 5.01})
    assert_fields(flagged, {"status": "VARIANCE_FLAGGED"})


def test_only_the_flagged_batch_counts_as_unresolved_and_blocks_balancing(api):
    """The matched batch drops out of the unresolved count and the variance total.

    PRD section 3.5 stops a MATCHED batch counting towards
    `unresolved_settlement_batch_count`, and only a VARIANCE_FLAGGED batch contributes
    the absolute value of its variance to `settlement_variance_total_amount`. PRD
    section 3.8 then refuses to balance a day whose unresolved count is non-zero with
    ERR_SETTLEMENTS_UNRESOLVED.

    Design: Difficulty/boundary_precision_check/settlement_variance_tolerance_inclusive_at_five_dollars
    """
    _prop, bd, _at_tolerance, _over_tolerance = _two_batches_astride_the_tolerance(api)

    reviewed = fx.verify_settlements(api, bd["id"])
    assert_fields(reviewed, {"status": "SETTLEMENT_REVIEW"})
    assert_int(
        reviewed["unresolved_settlement_batch_count"],
        1,
        "unresolved_settlement_batch_count",
    )
    assert_money(
        reviewed["settlement_variance_total_amount"],
        5.01,
        "settlement_variance_total_amount",
    )

    validate_error(
        api.balance_business_date(bd["id"], AUDITOR), E.ERR_SETTLEMENTS_UNRESOLVED
    )


def _flagged_batch_blocking_the_daily_balance(api):
    """A day in SETTLEMENT_REVIEW whose only batch is 75.23 over its priced checks."""
    fx.set_clock(api, "2026-08-01T20:00:00.000Z")
    prop = fx.create_property(api)
    outlet = fx.create_outlet(
        api,
        prop["id"],
        outlet_code="LOBBY",
        outlet_name="Lobby Lounge",
        outlet_type="FB_OUTLET",
        requires_shift_settlement=True,
    )
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    ticket = fx.create_outlet_ticket(
        api,
        outlet["id"],
        bd["id"],
        120.00,
        ticket_number="L-001",
        settlement_type="CASH",
        opened_at="2026-08-01T17:30:00.000Z",
    )
    fx.close_outlet_ticket(api, ticket["id"], outlet["id"], "2026-08-01T18:00:00.000Z")
    batch = fx.create_settlement_batch(
        api,
        bd["id"],
        outlet["id"],
        225.68,
        tender_type="CASH",
        shift_start_at="2026-08-01T14:00:00.000Z",
        shift_end_at="2026-08-01T22:00:00.000Z",
    )
    fx.drive_to_settlement_review(api, bd["id"])
    return prop, outlet, bd, batch


def test_one_flagged_batch_alone_refuses_the_daily_balance(api):
    """Reconciliation flags the drawer, and the flag keeps the day out of BALANCED.

    PRD section 3.5 sets `system_amount` from the day's matching CLOSED checks — one
    120.00 check prices to 150.45 — so a declared 225.68 leaves a 75.23 variance that
    strictly exceeds the 5.00 tolerance and becomes VARIANCE_FLAGGED, still counting as
    unresolved. PRD section 3.8 then refuses the balance step with
    ERR_SETTLEMENTS_UNRESOLVED (HTTP 409) and leaves the day in SETTLEMENT_REVIEW.

    Design: Difficulty/cross_entity_state_dependency/daily_balance_gated_on_every_settlement_batch_being_resolved
    """
    _prop, _outlet, bd, batch = _flagged_batch_blocking_the_daily_balance(api)

    reconciled = fx.read_batch(api, batch["id"])
    assert_fields(reconciled, {"status": "VARIANCE_FLAGGED"})
    assert_money_fields(
        reconciled, {"system_amount": 150.45, "variance_amount": 75.23}
    )

    validate_error(
        api.balance_business_date(bd["id"], AUDITOR), E.ERR_SETTLEMENTS_UNRESOLVED
    )
    day = fx.read_business_date(api, bd["id"])
    assert_fields(day, {"status": "SETTLEMENT_REVIEW"})
    assert_int(day["unresolved_settlement_batch_count"], 1, "unresolved_settlement_batch_count")


def test_accepting_the_variance_unblocks_the_day_without_hiding_the_loss(api):
    """Management signs off: the count falls to zero while the variance total stands.

    PRD section 3.5 has acceptance stop the batch counting towards
    `unresolved_settlement_batch_count` while it *continues* contributing the absolute
    value of its variance to `settlement_variance_total_amount`, so the accepted loss
    stays visible. Only a RevenueManager or Controller may accept, so the OutletManager
    who counted the drawer is refused with ERR_UNAUTHORIZED under the authorization step
    of PRD section 2.12, and once accepted PRD section 3.8 lets the day reach BALANCED.

    Design: Difficulty/cross_entity_state_dependency/daily_balance_gated_on_every_settlement_batch_being_resolved
    """
    _prop, outlet, bd, batch = _flagged_batch_blocking_the_daily_balance(api)

    validate_error(
        api.accept_variance(batch["id"], make_outlet_manager_headers(outlet["id"])),
        E.ERR_UNAUTHORIZED,
    )

    accepted = validate_success(api.accept_variance(batch["id"], REVENUE_MANAGER))
    assert_fields(accepted, {"status": "ACCEPTED_WITH_VARIANCE"})
    assert accepted["accepted_by_user_id"] == REVENUE_MANAGER["X-User-ID"], (
        "expected the accepting RevenueManager on accepted_by_user_id, got "
        f"{accepted['accepted_by_user_id']!r}"
    )

    day = fx.read_business_date(api, bd["id"])
    assert_int(day["unresolved_settlement_batch_count"], 0, "unresolved_settlement_batch_count")
    assert_money(day["settlement_variance_total_amount"], 75.23, "settlement_variance_total_amount")

    balanced = validate_success(api.balance_business_date(bd["id"], AUDITOR))
    assert_fields(balanced, {"status": "BALANCED"})


def _one_declared_afternoon_shift(api):
    """A remote outlet with a single CASH batch covering [14:00, 22:00)."""
    fx.set_clock(api, "2026-08-01T22:30:00.000Z")
    prop = fx.create_property(api)
    outlet = fx.create_outlet(
        api,
        prop["id"],
        outlet_code="ROOM-SVC",
        outlet_name="Room Service",
        outlet_type="REMOTE_POS",
        requires_shift_settlement=False,
    )
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    batch = fx.create_settlement_batch(
        api,
        bd["id"],
        outlet["id"],
        100.00,
        tender_type="CASH",
        shift_start_at="2026-08-01T14:00:00.000Z",
        shift_end_at="2026-08-01T22:00:00.000Z",
    )
    return prop, outlet, bd, batch


def test_a_shift_starting_where_the_last_one_ended_is_accepted(api):
    """The window is half-open, so the shared instant belongs to the later shift alone.

    PRD section 3.5 judges overlap on the half-open interval from `shift_start_at` up to
    but excluding `shift_end_at`, so two adjacent shifts where one ends at exactly the
    instant the next begins do not overlap and both are accepted. A window reaching one
    millisecond back into the first shift does collide, and is refused with
    ERR_SHIFT_WINDOW_OVERLAP (HTTP 409).

    Design: Difficulty/resource_temporal_overlap/settlement_shift_half_open_window_allows_adjacent_shifts
    """
    _prop, outlet, bd, _batch = _one_declared_afternoon_shift(api)
    manager = make_outlet_manager_headers(outlet["id"])

    adjacent = validate_success(
        api.create_settlement_batch(
            f.build_settlement_batch_payload(
                bd["id"],
                outlet["id"],
                50.00,
                tender_type="CASH",
                shift_start_at="2026-08-01T22:00:00.000Z",
                shift_end_at="2026-08-02T06:00:00.000Z",
            ),
            manager,
        ),
        201,
    )
    assert_fields(adjacent, {"status": "DECLARED"})

    listed = validate_success(
        api.list_settlement_batches(AUDITOR, business_date_id=bd["id"], outlet_id=outlet["id"])
    )
    assert_row_count(listed, 2, "settlement batches")

    validate_error(
        api.create_settlement_batch(
            f.build_settlement_batch_payload(
                bd["id"],
                outlet["id"],
                50.00,
                tender_type="CASH",
                shift_start_at="2026-08-01T21:59:59.999Z",
                shift_end_at="2026-08-01T23:00:00.000Z",
            ),
            manager,
        ),
        E.ERR_SHIFT_WINDOW_OVERLAP,
    )


def test_overlap_is_scoped_to_the_tender_and_an_empty_window_is_malformed(api):
    """A different tender may reuse the very same window; a zero-length one may not exist.

    PRD section 3.5 scopes the overlap test to batches of the same outlet, operating day
    and `tender_type`, so a CREDIT_CARD batch occupying exactly the CASH batch's window is
    accepted. And because `shift_start_at` must be strictly before `shift_end_at`, a window
    whose endpoints coincide is rejected with ERR_SHIFT_WINDOW_INVALID (HTTP 422).

    Design: Difficulty/resource_temporal_overlap/settlement_shift_half_open_window_allows_adjacent_shifts
    """
    _prop, outlet, bd, _batch = _one_declared_afternoon_shift(api)
    manager = make_outlet_manager_headers(outlet["id"])

    same_window_other_tender = validate_success(
        api.create_settlement_batch(
            f.build_settlement_batch_payload(
                bd["id"],
                outlet["id"],
                75.00,
                tender_type="CREDIT_CARD",
                shift_start_at="2026-08-01T14:00:00.000Z",
                shift_end_at="2026-08-01T22:00:00.000Z",
            ),
            manager,
        ),
        201,
    )
    assert_fields(same_window_other_tender, {"status": "DECLARED", "tender_type": "CREDIT_CARD"})

    validate_error(
        api.create_settlement_batch(
            f.build_settlement_batch_payload(
                bd["id"],
                outlet["id"],
                0.00,
                tender_type="CASH",
                shift_start_at="2026-08-02T06:00:00.000Z",
                shift_end_at="2026-08-02T06:00:00.000Z",
            ),
            manager,
        ),
        E.ERR_SHIFT_WINDOW_INVALID,
    )
