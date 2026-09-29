"""Departure, late-checkout pricing, tenders and card authorizations.

Covers PRD section 3.7 (departure, tenders, manual lines and card
authorizations) together with PRD section 2.5 (the logical clock as the only
time source) and PRD section 2.6 (money, signs and rounding).
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_empty,
    assert_fields,
    assert_int,
    assert_money,
    assert_money_fields,
    assert_row_count,
    single,
)
from test_helpers.test_users import AUDITOR, FRONT_DESK


def _three_overdue_folios(api):
    """Three in-house folios at rates 250.00, 20.00 and 80.00, overdue by 361/361/60."""
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    high = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-3001",
        guest_name="Cy Nolan",
        room_number="301",
        contracted_rate_amount=250.00,
        scheduled_checkout_at="2026-08-01T11:00:00.000Z",
    )
    low = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-3002",
        guest_name="Di Okafor",
        room_number="302",
        contracted_rate_amount=20.00,
        rate_plan_code="STAFF",
        market_segment="CORPORATE",
        scheduled_checkout_at="2026-08-01T11:00:00.000Z",
    )
    mid = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-3003",
        guest_name="Eli Pratt",
        room_number="303",
        contracted_rate_amount=80.00,
        rate_plan_code="STAFF",
        market_segment="CORPORATE",
        scheduled_checkout_at="2026-08-01T16:01:00.000Z",
    )
    for folio in (high, low, mid):
        fx.check_in(api, folio["id"])
    fx.set_clock(api, "2026-08-01T17:01:00.000Z", AUDITOR)
    return prop, bd, high, low, mid


def test_late_checkout_rate_ceiling_overrides_the_minimum_charge_floor(api):
    """On a 20.00 rate the contracted-rate ceiling beats the 25.00 floor.

    PRD section 3.7 prices a late checkout by rounding the tier percentage of the
    contracted rate, lifting the result to the 25.00 minimum and then clamping it
    down to the contracted rate. The clamp is applied last, so a 20.00 rate that is
    361 minutes overdue is charged 20.00 and not 25.00.

    Design: Difficulty/combinatorial_formula/late_checkout_charge_nested_floor_and_rate_ceiling_clamp
    """
    _prop, bd, _high, low, _mid = _three_overdue_folios(api)

    departed = validate_success(
        api.check_out(low["id"], f.build_check_out_payload(bd["id"]), FRONT_DESK)
    )
    assert_money(departed["balance_amount"], 20.00, "balance_amount")

    lines = validate_success(
        api.list_journal_postings(AUDITOR, folio_id=low["id"], charge_type="LATE_CHECKOUT")
    )
    assert_row_count(lines, 1, "LATE_CHECKOUT rows")
    line = single(lines)
    assert_money(line["amount"], 20.00, "late checkout amount")
    assert_fields(line, {"source_channel": "FRONT_DESK"})


def test_late_checkout_tiers_floor_and_ceiling_across_three_rates(api):
    """Each clamp is visible on a different folio, and the day's figure sums all three.

    PRD section 3.7 sets the tier percentage from the overdue minutes and then
    applies the 25.00 floor and the contracted-rate ceiling. At 361 overdue minutes
    a 250.00 rate is charged in full, at 60 overdue minutes an 80.00 rate is lifted
    from 20.00 to the 25.00 floor, and PRD section 3.3 counts late-checkout money as
    other room revenue.

    Design: Difficulty/combinatorial_formula/late_checkout_charge_nested_floor_and_rate_ceiling_clamp
    """
    _prop, bd, high, low, mid = _three_overdue_folios(api)

    fx.check_out(api, high["id"], bd["id"])
    fx.check_out(api, mid["id"], bd["id"])
    fx.check_out(api, low["id"], bd["id"])

    high_row = validate_success(api.get_folio(high["id"], FRONT_DESK))
    assert_money(high_row["balance_amount"], 250.00, "250.00 rate, tier 1.00")

    mid_row = validate_success(api.get_folio(mid["id"], FRONT_DESK))
    assert_money(mid_row["balance_amount"], 25.00, "80.00 rate lifted to the floor")

    low_row = validate_success(api.get_folio(low["id"], FRONT_DESK))
    assert_money(low_row["balance_amount"], 20.00, "20.00 rate clamped by the ceiling")

    date_row = validate_success(api.get_business_date(bd["id"], AUDITOR))
    assert_money_fields(
        date_row,
        {"other_room_revenue_amount": 295.00, "total_revenue_amount": 295.00},
    )


def _declined_authorization_over_a_reviewed_day(api):
    """A day in SETTLEMENT_REVIEW whose only card authorization was declined."""
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-8001",
        guest_name="Lu Wexler",
        room_number="801",
        nights_count=1,
        contracted_rate_amount=200.00,
        settlement_method="CREDIT_CARD",
        scheduled_checkout_at="2026-08-02T11:00:00.000Z",
    )
    fx.check_in(api, folio["id"])
    auth = fx.create_card_authorization(
        api, folio["id"], 500.00, "2026-08-01T08:00:00.000Z"
    )
    get_success_data(
        api.post_payment(
            folio["id"],
            {"business_date_id": bd["id"], "amount": 50.00, "memo": "Cash on account"},
            FRONT_DESK,
        )
    )
    fx.drive_to_settlement_review(api, bd["id"])
    validate_success(
        api.decline_card_authorization(
            auth["id"], f.build_decline_payload("DO_NOT_HONOR"), FRONT_DESK
        )
    )
    return prop, bd, folio, auth


def test_a_decline_holds_the_account_and_counts_against_the_operating_day(api):
    """Hops 1 to 3: the parallel dimension wakes, the account is held, the day counts it.

    PRD section 3.7 makes a decline force `follow_up_status` from NOT_REQUIRED to
    PENDING on the parallel dimension, set the owning account's `settlement_hold`
    true, and raise the day's `declined_authorization_count`. The account's money is
    untouched — the 200.00 room night plus 17.75 tax less the 50.00 tender still
    reads 167.75.

    Design: Difficulty/transitive_cascade/card_decline_cascades_three_hops_to_block_the_daily_balance
    """
    _prop, bd, folio, auth = _declined_authorization_over_a_reviewed_day(api)

    row = fx.read_card_authorization(api, auth["id"])
    assert_fields(
        row,
        {
            "status": "DECLINED",
            "decline_code": "DO_NOT_HONOR",
            "follow_up_status": "PENDING",
        },
    )

    account = fx.read_folio(api, folio["id"])
    assert_fields(account, {"settlement_hold": True})
    assert_money(account["balance_amount"], 167.75, "balance_amount")

    day = fx.read_business_date(api, bd["id"])
    assert_int(day["declined_authorization_count"], 1, "declined_authorization_count")


def test_the_declined_count_alone_blocks_the_day_from_balancing(api):
    """Balancing is refused by the third assertion while the other two are clean.

    PRD section 3.8 checks three assertions when balancing and refuses a non-zero
    `declined_authorization_count` with ERR_DECLINED_AUTH_UNRESOLVED (HTTP 409). Here
    `unresolved_settlement_batch_count` is zero and `ledger_control_amount` is exactly
    0.00, so the declined card is the only thing standing in the way and the day is
    still SETTLEMENT_REVIEW afterwards.

    Design: Difficulty/transitive_cascade/card_decline_cascades_three_hops_to_block_the_daily_balance
    """
    _prop, bd, _folio, _auth = _declined_authorization_over_a_reviewed_day(api)

    validate_error(
        api.balance_business_date(bd["id"], AUDITOR), E.ERR_DECLINED_AUTH_UNRESOLVED
    )

    day = fx.read_business_date(api, bd["id"])
    assert_fields(day, {"status": "SETTLEMENT_REVIEW"})
    assert_int(day["unresolved_settlement_batch_count"], 0, "unresolved_settlement_batch_count")
    assert_money(day["ledger_control_amount"], 0.00, "ledger_control_amount")


def test_only_resolving_the_follow_up_unwinds_the_cascade(api):
    """CONTACT leaves the hold in place; RESOLVE releases it and lets the day balance.

    PRD section 3.7 has CONTACT store the note and leave the account held, while
    RESOLVE — permitted only because the account already carries a PAYMENT line —
    recomputes `settlement_hold` to false and the day's
    `declined_authorization_count` downwards. The authorization's own `status` stays
    DECLINED throughout, since the two dimensions never constrain each other.

    Design: Difficulty/transitive_cascade/card_decline_cascades_three_hops_to_block_the_daily_balance
    """
    _prop, bd, folio, auth = _declined_authorization_over_a_reviewed_day(api)

    contacted = validate_success(
        api.follow_up_card_authorization(
            auth["id"], f.build_follow_up_payload("CONTACT"), FRONT_DESK
        )
    )
    assert_fields(contacted, {"follow_up_status": "CONTACTED", "status": "DECLINED"})
    assert_fields(fx.read_folio(api, folio["id"]), {"settlement_hold": True})
    assert_int(
        fx.read_business_date(api, bd["id"])["declined_authorization_count"],
        1,
        "declined_authorization_count",
    )

    resolved = validate_success(
        api.follow_up_card_authorization(
            auth["id"], f.build_follow_up_payload("RESOLVE"), AUDITOR
        )
    )
    assert_fields(resolved, {"follow_up_status": "RESOLVED", "status": "DECLINED"})
    assert_fields(fx.read_folio(api, folio["id"]), {"settlement_hold": False})
    assert_int(
        fx.read_business_date(api, bd["id"])["declined_authorization_count"],
        0,
        "declined_authorization_count",
    )

    balanced = validate_success(api.balance_business_date(bd["id"], AUDITOR))
    assert_fields(balanced, {"status": "BALANCED"})


def _two_folios_astride_the_grace_window(api):
    """Two accounts departing at 17:01, overdue by exactly 30 and by 31 minutes."""
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    at_grace = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-9401",
        guest_name="Rin Diaz",
        room_number="905",
        nights_count=1,
        contracted_rate_amount=189.99,
        settlement_method="CASH",
        scheduled_checkout_at="2026-08-01T16:31:00.000Z",
    )
    past_grace = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-9402",
        guest_name="Sol Eze",
        room_number="906",
        nights_count=1,
        contracted_rate_amount=189.99,
        settlement_method="CASH",
        scheduled_checkout_at="2026-08-01T16:30:00.000Z",
    )
    fx.check_in(api, at_grace["id"])
    fx.check_in(api, past_grace["id"])
    fx.set_clock(api, "2026-08-01T17:01:00.000Z", AUDITOR)
    return prop, bd, at_grace, past_grace


def test_exactly_thirty_overdue_minutes_is_free_and_writes_no_line(api):
    """The grace comparison is inclusive, and a 0.00 charge posts nothing at all.

    PRD section 3.7 makes the charge exactly 0.00 when overdue minutes are at or below
    `late_checkout_grace_minutes`, and PRD section 2.9 stops the whole cascade when the
    charge is 0.00 — no journal line, so no re-derivation. The guest still departs.

    Design: Difficulty/boundary_precision_check/late_checkout_grace_window_exclusive_at_thirty_minutes
    """
    _prop, bd, at_grace, _past = _two_folios_astride_the_grace_window(api)

    departed = fx.check_out(api, at_grace["id"], bd["id"])
    assert_fields(departed, {"stay_status": "DEPARTED"})
    assert_money(departed["balance_amount"], 0.00, "balance_amount")
    assert_empty(
        validate_success(
            api.list_journal_postings(
                AUDITOR, folio_id=at_grace["id"], charge_type="LATE_CHECKOUT"
            )
        ),
        "LATE_CHECKOUT lines",
    )


def test_one_minute_past_the_grace_window_costs_a_quarter_of_the_rate(api):
    """31 overdue minutes lands in the first tier, clear of both clamps.

    PRD section 3.7 charges one quarter of `contracted_rate_amount` when overdue
    minutes exceed the grace window but stay at or below one hundred and eighty, so
    189.99 yields 47.50 after rounding — above the twenty-five floor and below the
    rate ceiling. The line rolls into the day's `other_room_revenue_amount` and
    `total_revenue_amount`.

    Design: Difficulty/boundary_precision_check/late_checkout_grace_window_exclusive_at_thirty_minutes
    """
    _prop, bd, at_grace, past_grace = _two_folios_astride_the_grace_window(api)
    fx.check_out(api, at_grace["id"], bd["id"])

    departed = fx.check_out(api, past_grace["id"], bd["id"])
    assert_money(departed["balance_amount"], 47.50, "balance_amount")

    rows = validate_success(
        api.list_journal_postings(
            AUDITOR, folio_id=past_grace["id"], charge_type="LATE_CHECKOUT"
        )
    )
    assert_row_count(rows, 1, "LATE_CHECKOUT lines")
    assert_money(single(rows)["amount"], 47.50, "LATE_CHECKOUT amount")

    day = fx.read_business_date(api, bd["id"])
    assert_money_fields(
        day,
        {"other_room_revenue_amount": 47.50, "total_revenue_amount": 47.50},
    )
