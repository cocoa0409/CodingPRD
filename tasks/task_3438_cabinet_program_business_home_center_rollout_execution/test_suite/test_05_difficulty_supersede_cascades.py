"""Supersede and cancel cascades through pricing, exposure and holds (PRD §2.8, §3.6, §3.7)."""

from test_helpers import WEEK_PLUS_2, family_spec, order_line
from test_helpers import fixtures


def test_supersede_reprices_submitted_and_recomputes_exposure(api):
    """A supersede sunsets the old line, reprices SUBMITTED orders, breaks
    locks, and re-runs the account's credit evaluation.

    PRD §3.7: "The previously `ACTIVE` line moves to `SUNSETTING`, and its `remaining_disposition_qty` is initialized from that same input."
    PRD §3.7: "The program moves `ACTIVE` → `TRANSITIONING`, stamping `transition_started_at` from the logical clock and computing two deadlines: `display_reset_deadline` at 45 days after the transition start, and `disposition_deadline` at 90 days after it."
    PRD §3.7: "Every `SUBMITTED` order of the program is repriced against the new line with the quoted variant of §3.3 and flagged `repricing_required`, and each such reprice in turn recomputes the account's credit exposure and re-evaluates the release of its held orders."
    PRD §3.7: "Every order standing in `ACKNOWLEDGED`, `SCHEDULED`, `IN_PRODUCTION`, or `MFG_COMPLETE` whose `payment_status` is still `UNINVOICED` or `CREDIT_HOLD` loses its `price_lock`, which is set back to false."
    Design: Difficulty/transitive_cascade/line_supersede_reprice_exposure_cascade
    """
    world = fixtures.setup_active_program(
        api, account_overrides={"credit_limit_cents": 100000}
    )
    o1 = fixtures.place_order(
        api, world["account"], world["program"], lines=[order_line(quantity=2)]
    )
    o2 = fixtures.place_order(
        api, world["account"], world["program"],
        jobsite_address="2 Job Ln", lines=[order_line(quantity=9)],
    )
    o3 = fixtures.place_order(
        api, world["account"], world["program"],
        jobsite_address="3 Job Ln", lines=[order_line(quantity=3)],
    )
    fixtures.acknowledge_order(api, o1["id"])           # 19000
    o2_ack = fixtures.acknowledge_order(api, o2["id"])  # 104500 > 100000
    assert o2_ack["payment_status"] == "CREDIT_HOLD"

    line2 = fixtures.supersede_program_line(
        api,
        world["program"]["id"],
        line_code="L2",
        effective_start_week=WEEK_PLUS_2,
        families=[family_spec(standard_price_cents=5000, base_lead_weeks=3, complexity_units_per_cabinet=1)],
        include_disposition_qty=True,
    )
    assert line2["status"] == "ACTIVE"
    assert line2["supersedes_line_id"] == world["line"]["id"]

    line1 = fixtures.get_line(api, world["line"]["id"])
    assert line1["status"] == "SUNSETTING"
    program = fixtures.get_program(api, world["program"]["id"])
    assert program["status"] == "TRANSITIONING"

    # Link 2: the still-SUBMITTED o3 repriced under L2 (3 x round(5000x0.95)).
    o3_after = fixtures.get_order(api, o3["id"])
    assert o3_after["quoted_total_cents"] == 14250
    assert o3_after["repricing_required"] is True

    # o2 stood ACKNOWLEDGED + CREDIT_HOLD at the supersede: its lock broke.
    o2_after = fixtures.get_order(api, o2["id"])
    assert o2_after["price_lock"] is False

    # Link 3: exposure recomputed as 19000 + 85500 + 14250 = 118750.
    account = fixtures.get_account(api, world["account"]["id"])
    assert account["open_exposure_cents"] == 118750

    # Link 4: the re-evaluation ran and did not release o2 (118750 > 100000).
    assert o2_after["payment_status"] == "CREDIT_HOLD"
    # o1 was never repriced (it was not SUBMITTED at the supersede).
    o1_after = fixtures.get_order(api, o1["id"])
    assert o1_after["quoted_total_cents"] == 19000


def test_supersede_reprice_releases_credit_hold(api):
    """When the reprice pulls exposure back to the limit, the held order flips
    back to UNINVOICED as part of the same cascade.

    PRD §3.7: "Every `SUBMITTED` order of the program is repriced against the new line with the quoted variant of §3.3 and flagged `repricing_required`, and each such reprice in turn recomputes the account's credit exposure and re-evaluates the release of its held orders."
    PRD §2.8: "Symmetrically, whenever a recompute finds the exposure at or below the limit, every order of that account currently sitting in `CREDIT_HOLD` flips back to `UNINVOICED`."
    Design: Difficulty/transitive_cascade/line_supersede_reprice_exposure_cascade
    """
    world = fixtures.setup_active_program(
        api, account_overrides={"credit_limit_cents": 100000}
    )
    o1 = fixtures.place_order(api, world["account"], world["program"])  # 9500
    o3 = fixtures.place_order(
        api, world["account"], world["program"],
        jobsite_address="3 Job Ln", lines=[order_line(quantity=9)],
    )  # 85500, stays SUBMITTED
    o2 = fixtures.place_order(
        api, world["account"], world["program"], jobsite_address="2 Job Ln"
    )  # 9500
    fixtures.acknowledge_order(api, o1["id"])           # 9500 + 85500 = 95000 <= limit
    o2_ack = fixtures.acknowledge_order(api, o2["id"])  # 104500 > 100000 -> hold
    assert o2_ack["payment_status"] == "CREDIT_HOLD"

    fixtures.supersede_program_line(
        api,
        world["program"]["id"],
        line_code="L2",
        effective_start_week=WEEK_PLUS_2,
        families=[family_spec(standard_price_cents=5000, base_lead_weeks=3, complexity_units_per_cabinet=1)],
        include_disposition_qty=True,
    )

    # o3 repriced to 9 x 4750 = 42750; exposure 9500 + 9500 + 42750 = 61750 <= limit.
    o3_after = fixtures.get_order(api, o3["id"])
    assert o3_after["quoted_total_cents"] == 42750
    assert o3_after["repricing_required"] is True
    account = fixtures.get_account(api, world["account"]["id"])
    assert account["open_exposure_cents"] == 61750

    o2_after = fixtures.get_order(api, o2["id"])
    assert o2_after["payment_status"] == "UNINVOICED"
    assert o2_after["status"] == "ACKNOWLEDGED"
    assert o2_after["price_lock"] is False


def test_cancel_releases_exposure_and_lifts_hold(api):
    """Cancelling an acknowledged order recomputes exposure and releases a
    sibling's hold.

    PRD §3.6: "Cancelling a `SCHEDULED` order returns its committed units to each picked slot — re-opening a full slot automatically — and every cancellation, from any of the three states, recomputes the account's credit exposure and re-evaluates its held orders per §2.8."
    PRD §2.8: "every order not in `CANCELLED` contributes its `quoted_total_cents` while its `payment_status` is `UNINVOICED` or `CREDIT_HOLD`, its `invoiced_total_cents` once `INVOICED`, and nothing once `PAID`."
    Design: Difficulty/transitive_cascade/cancel_releases_exposure_and_relieves_credit_hold
    """
    world = fixtures.setup_active_program(
        api, account_overrides={"credit_limit_cents": 100000}
    )
    o1 = fixtures.place_order(
        api, world["account"], world["program"], lines=[order_line(quantity=2)]
    )
    o2 = fixtures.place_order(
        api, world["account"], world["program"],
        jobsite_address="2 Job Ln", lines=[order_line(quantity=9)],
    )
    fixtures.acknowledge_order(api, o1["id"])           # 19000
    o2_ack = fixtures.acknowledge_order(api, o2["id"])  # 104500 > 100000
    assert o2_ack["payment_status"] == "CREDIT_HOLD"

    cancelled = fixtures.cancel_order(api, o1["id"])
    assert cancelled["status"] == "CANCELLED"

    account = fixtures.get_account(api, world["account"]["id"])
    assert account["open_exposure_cents"] == 85500

    o2_after = fixtures.get_order(api, o2["id"])
    assert o2_after["payment_status"] == "UNINVOICED"
    assert o2_after["status"] == "ACKNOWLEDGED"


def test_cancel_submitted_order_relieves_held_acknowledged(api):
    """Cancelling a merely-submitted order also recomputes exposure: the
    cancelled order's contribution leaves the sum and the held order clears.

    PRD §3.6: "Cancelling a `SCHEDULED` order returns its committed units to each picked slot — re-opening a full slot automatically — and every cancellation, from any of the three states, recomputes the account's credit exposure and re-evaluates its held orders per §2.8."
    PRD §2.8: "Symmetrically, whenever a recompute finds the exposure at or below the limit, every order of that account currently sitting in `CREDIT_HOLD` flips back to `UNINVOICED`."
    Design: Difficulty/transitive_cascade/cancel_releases_exposure_and_relieves_credit_hold
    """
    world = fixtures.setup_active_program(
        api, account_overrides={"credit_limit_cents": 100000}
    )
    o1 = fixtures.place_order(
        api, world["account"], world["program"], lines=[order_line(quantity=9)]
    )  # 85500
    o2 = fixtures.place_order(
        api, world["account"], world["program"],
        jobsite_address="2 Job Ln", lines=[order_line(quantity=2)],
    )  # 19000, stays SUBMITTED

    o1_ack = fixtures.acknowledge_order(api, o1["id"])  # 104500 > 100000
    assert o1_ack["payment_status"] == "CREDIT_HOLD"

    cancelled = fixtures.cancel_order(api, o2["id"])
    assert cancelled["status"] == "CANCELLED"

    account = fixtures.get_account(api, world["account"]["id"])
    assert account["open_exposure_cents"] == 85500

    o1_after = fixtures.get_order(api, o1["id"])
    assert o1_after["payment_status"] == "UNINVOICED"
    assert o1_after["status"] == "ACKNOWLEDGED"
