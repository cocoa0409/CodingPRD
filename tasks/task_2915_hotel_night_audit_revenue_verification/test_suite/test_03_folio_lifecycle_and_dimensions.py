"""The guest account's two independent dimensions.

Covers PRD section 3.7 (checking out, applying a tender and the re-derivation of
the settlement dimension from the account's own running totals) and PRD section
3.2 (the account's opening state).
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import fixtures as fx
from test_helpers.assertions import assert_fields, assert_instant_equals, assert_money_fields
from test_helpers.test_users import FRONT_DESK


def _departed_and_settled_account(api):
    """One cash account that departed with a zero balance inside the grace window."""
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-5001",
        guest_name="Ivo Tran",
        room_number="501",
        nights_count=1,
        contracted_rate_amount=200.00,
        settlement_method="CASH",
        scheduled_checkout_at="2026-08-02T11:00:00.000Z",
    )
    fx.check_in(api, folio["id"])
    fx.post_journal_line(
        api,
        bd["id"],
        "MISC_CHARGE",
        100.00,
        headers=FRONT_DESK,
        folio_id=folio["id"],
        memo="Spa treatment",
    )
    get_success_data(
        api.post_payment(
            folio["id"],
            {"business_date_id": bd["id"], "amount": 100.00, "memo": "Cash in full"},
            FRONT_DESK,
        )
    )
    fx.check_out(api, folio["id"], bd["id"])
    return prop, bd, folio


def test_a_charge_after_departure_drags_the_settlement_dimension_backwards(api):
    """SETTLED is not terminal: a late charge re-derives it to PARTIALLY_SETTLED.

    PRD section 3.7 re-derives the settlement dimension from the account's own
    totals after every line, so a charge appended to an account that had reached
    SETTLED moves it backwards — to PARTIALLY_SETTLED when the account holds credits.
    The stay dimension is a separate machine and does not move at all: the guest is
    still DEPARTED.

    Design: Difficulty/non_linear_state_machine/folio_settlement_dimension_reverses_while_stay_dimension_holds_departed
    """
    _prop, bd, folio = _departed_and_settled_account(api)
    before = fx.read_folio(api, folio["id"])
    assert_fields(before, {"stay_status": "DEPARTED", "settlement_status": "SETTLED"})

    fx.post_journal_line(
        api,
        bd["id"],
        "MISC_CHARGE",
        40.00,
        headers=FRONT_DESK,
        folio_id=folio["id"],
        memo="Minibar found after departure",
    )

    after = fx.read_folio(api, folio["id"])
    assert_fields(
        after, {"stay_status": "DEPARTED", "settlement_status": "PARTIALLY_SETTLED"}
    )


def test_the_backwards_move_comes_only_from_the_running_totals(api):
    """The re-derivation reads the two totals and touches nothing else on the account.

    PRD section 3.7 makes `charges_total_amount` the sum of the positive lines,
    `credits_total_amount` the sum of the negative ones and `balance_amount` their
    sum, so the late 40.00 charge takes the account to 140.00 / -100.00 / 40.00 and
    the non-zero credit total is exactly what selects PARTIALLY_SETTLED over
    UNSETTLED. Neither `settlement_hold` nor `actual_checkout_at` participates.

    Design: Difficulty/non_linear_state_machine/folio_settlement_dimension_reverses_while_stay_dimension_holds_departed
    """
    _prop, bd, folio = _departed_and_settled_account(api)
    before = fx.read_folio(api, folio["id"])

    fx.post_journal_line(
        api,
        bd["id"],
        "MISC_CHARGE",
        40.00,
        headers=FRONT_DESK,
        folio_id=folio["id"],
        memo="Minibar found after departure",
    )

    after = fx.read_folio(api, folio["id"])
    assert_money_fields(
        after,
        {
            "charges_total_amount": 140.00,
            "credits_total_amount": -100.00,
            "balance_amount": 40.00,
        },
    )
    assert_fields(after, {"settlement_hold": False})
    assert_instant_equals(
        after["actual_checkout_at"], before["actual_checkout_at"], "actual_checkout_at"
    )
