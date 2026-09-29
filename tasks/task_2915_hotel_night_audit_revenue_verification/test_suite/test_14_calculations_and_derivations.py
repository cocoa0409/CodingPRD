"""Derived money and derived counts: no-show policy, sweeps, aging and aggregates.

Covers the arithmetic PRD section 3.3 raises for reservations that never
arrived, the input-set filtering and per-account rounding of the city-ledger
sweep in PRD section 3.8, the room-night ordinal of PRD section 3.3, the
authorization aging curve of PRD section 3.7, and the running guest-account
totals of PRD section 3.7.
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
    assert_null_fields,
    assert_row_count,
    find_by,
    single,
)
from test_helpers.test_users import AUDITOR, CONTROLLER, FRONT_DESK


def test_a_no_show_is_charged_one_night_plus_its_own_rounded_tax(api):
    """189.99 at 8.875% rounds half up to 16.86, and the room stays unoccupied.

    PRD section 3.3 moves a reservation that never arrived to NO_SHOW and, under the
    property's FIRST_NIGHT_PLUS_TAX policy, appends a NO_SHOW line for the contracted
    rate and an OCCUPANCY_TAX line for that same rate times `occupancy_tax_rate_pct`
    over one hundred, rounded half up to 2 decimals. Only the first night is charged
    however many nights were booked. PRD section 3.3 files no-show money under
    `other_room_revenue_amount`, which is not the average-daily-rate numerator, and
    PRD section 3.8 counts only accounts holding a ROOM line as occupied, so the
    revenue exists without an occupied room and the rate statistics stay at 0.00.

    Design: Corner/calculations/calc_correct_result_no_show_posts_first_night_plus_its_own_tax
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api, no_show_charge_policy="FIRST_NIGHT_PLUS_TAX")
    bd1 = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd1["id"],
        confirmation_code="CF-NS1",
        guest_name="Zoe Barros",
        room_number="2901",
        nights_count=2,
        contracted_rate_amount=189.99,
        rate_plan_code="ADV",
        settlement_method="CREDIT_CARD",
        scheduled_checkout_at="2026-08-03T11:00:00.000Z",
    )

    fx.post_room_and_tax(api, bd1["id"])

    assert_fields(fx.read_folio(api, folio["id"]), {"stay_status": "NO_SHOW"})

    rows = fx.list_postings(api, folio_id=folio["id"])
    assert_row_count(rows, 2, "journal lines on the no-show account")
    no_show = single(find_by(rows, charge_type="NO_SHOW"), "the NO_SHOW line")
    assert_money(no_show["amount"], 189.99, "the no-show charge")
    assert_fields(no_show, {"source_channel": "NIGHT_AUDIT"})
    assert_null_fields(no_show, ["night_index"])
    tax = single(find_by(rows, charge_type="OCCUPANCY_TAX"), "the OCCUPANCY_TAX line")
    # round(189.99 * 8.875 / 100, 2) == round(16.86161..., 2) == 16.86
    assert_money(tax["amount"], 16.86, "the no-show occupancy tax")
    assert_fields(tax, {"source_channel": "NIGHT_AUDIT"})
    assert_empty(find_by(rows, charge_type="ROOM"), "ROOM lines on a no-show account")

    account = fx.read_folio(api, folio["id"])
    assert_money_fields(
        account,
        {
            "charges_total_amount": 206.85,
            "credits_total_amount": 0.00,
            "balance_amount": 206.85,
        },
    )
    assert_fields(account, {"settlement_status": "UNSETTLED"})

    day = fx.read_business_date(api, bd1["id"])
    assert_money_fields(
        day,
        {
            "other_room_revenue_amount": 189.99,
            "tax_revenue_amount": 16.86,
            "room_night_revenue_amount": 0.00,
            "total_revenue_amount": 206.85,
        },
    )
    assert_int(day["rooms_occupied_count"], 0, "rooms_occupied_count")
    assert_money_fields(
        day, {"occupancy_pct": 0.00, "adr_amount": 0.00, "revpar_amount": 0.00}
    )

    bd2 = fx.create_business_date(api, prop["id"], "2026-08-02", out_of_order_room_count=4)
    fx.post_room_and_tax(api, bd2["id"])
    assert_empty(fx.list_postings(api, business_date_id=bd2["id"]), "lines on the next day")
    assert_fields(fx.read_folio(api, folio["id"]), {"stay_status": "NO_SHOW"})


def _no_show_folio(api, policy: str, code: str, room: str, name: str):
    """One property on the given policy holding a three-night reservation that never arrives."""
    prop = fx.create_property(api, name=f"Policy {policy}", no_show_charge_policy=policy)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01")
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code=code,
        guest_name=name,
        room_number=room,
        nights_count=3,
        contracted_rate_amount=189.99,
        rate_plan_code="ADV",
        settlement_method="CASH",
        scheduled_checkout_at="2026-08-04T11:00:00.000Z",
        credit_limit_amount=2000.00,
    )
    return prop, bd, folio


def test_each_no_show_policy_branch_uses_its_own_arithmetic_on_the_same_reservation(api):
    """Three identical reservations under three policies produce three different answers.

    PRD section 2.3 puts `no_show_charge_policy` on the property, so PRD section 3.3
    reads a different branch for each one on an otherwise identical account. NONE
    appends nothing at all, FULL_STAY_NO_TAX multiplies the contracted rate by
    `nights_count` and deliberately appends no occupancy-tax line, and
    FIRST_NIGHT_PLUS_TAX charges one night plus its own tax. PRD section 3.3 moves the
    account to NO_SHOW in every branch, because only the money is policy-driven, and
    increments the day's `version` for the run either way.

    Design: Corner/calculations/calc_constants_applied_each_no_show_policy_branch_uses_its_own_arithmetic
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    _p_none, bd_none, folio_none = _no_show_folio(api, "NONE", "CF-PN1", "301", "Ada Kine")
    _p_full, bd_full, folio_full = _no_show_folio(
        api, "FULL_STAY_NO_TAX", "CF-PF1", "302", "Bo Larsen"
    )
    _p_first, bd_first, folio_first = _no_show_folio(
        api, "FIRST_NIGHT_PLUS_TAX", "CF-PT1", "303", "Cy Mena"
    )

    fx.post_room_and_tax(api, bd_none["id"])
    full_day = fx.post_room_and_tax(api, bd_full["id"])

    full_rows = fx.list_postings(api, folio_id=folio_full["id"])
    assert_row_count(full_rows, 1, "journal lines under FULL_STAY_NO_TAX")
    # round(189.99 * 3, 2) == 569.97
    assert_money(single(full_rows)["amount"], 569.97, "the full-stay no-show charge")
    assert_fields(single(full_rows), {"charge_type": "NO_SHOW"})
    assert_empty(
        find_by(full_rows, charge_type="OCCUPANCY_TAX"),
        "occupancy-tax lines under FULL_STAY_NO_TAX",
    )
    assert_money_fields(
        full_day,
        {
            "other_room_revenue_amount": 569.97,
            "tax_revenue_amount": 0.00,
            "total_revenue_amount": 569.97,
        },
    )
    assert_money(
        fx.read_folio(api, folio_full["id"])["balance_amount"], 569.97, "balance_amount"
    )

    assert_empty(fx.list_postings(api, folio_id=folio_none["id"]), "lines under NONE")
    assert_fields(fx.read_folio(api, folio_none["id"]), {"stay_status": "NO_SHOW"})
    none_day = fx.read_business_date(api, bd_none["id"])
    assert_money(none_day["total_revenue_amount"], 0.00, "total_revenue_amount under NONE")
    assert_int(none_day["version"], bd_none["version"] + 1, "the day's version after the run")
    assert_money(
        fx.read_folio(api, folio_none["id"])["balance_amount"], 0.00, "balance_amount"
    )

    fx.post_room_and_tax(api, bd_first["id"])
    first_rows = fx.list_postings(api, folio_id=folio_first["id"])
    assert_row_count(first_rows, 2, "journal lines under FIRST_NIGHT_PLUS_TAX")
    assert_money(
        single(find_by(first_rows, charge_type="NO_SHOW"), "the NO_SHOW line")["amount"],
        189.99,
        "the first-night no-show charge",
    )
    assert_money(
        single(find_by(first_rows, charge_type="OCCUPANCY_TAX"), "the tax line")["amount"],
        16.86,
        "the no-show occupancy tax",
    )
    assert_money(
        fx.read_folio(api, folio_first["id"])["balance_amount"], 206.85, "balance_amount"
    )


def _four_folios_astride_the_sweep_filter(api):
    """Four accounts differing on exactly one sweep-filter dimension each."""
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    city = fx.create_ledger_account(
        api,
        prop["id"],
        "CITY_LEDGER",
        account_code="CL-100",
        gl_account_code="1210",
        opening_balance_amount=0.00,
    )
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)

    def direct_bill(code, room, name):
        return fx.create_folio(
            api,
            prop["id"],
            bd["id"],
            confirmation_code=code,
            guest_name=name,
            room_number=room,
            contracted_rate_amount=200.00,
            rate_plan_code="CORP",
            market_segment="CORPORATE",
            settlement_method="DIRECT_BILL",
            credit_limit_amount=900.00,
        )

    owing = direct_bill("CF-DB1", "401", "Cy Rahman")
    fx.check_in(api, owing["id"])
    fx.post_journal_line(
        api, bd["id"], "MISC_CHARGE", 200.00, folio_id=owing["id"], memo="Conference package"
    )
    fx.check_out(api, owing["id"], bd["id"])

    settled = direct_bill("CF-DB2", "402", "Dov Sela")
    fx.check_in(api, settled["id"])
    fx.check_out(api, settled["id"], bd["id"])

    cash = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-CA1",
        guest_name="Eve Toma",
        room_number="403",
        contracted_rate_amount=200.00,
        settlement_method="CASH",
        credit_limit_amount=900.00,
    )
    fx.check_in(api, cash["id"])
    fx.post_journal_line(
        api, bd["id"], "MISC_CHARGE", 150.00, folio_id=cash["id"], memo="Laundry"
    )
    fx.check_out(api, cash["id"], bd["id"])

    in_house = direct_bill("CF-DB3", "404", "Fay Oduya")
    fx.check_in(api, in_house["id"])
    fx.post_journal_line(
        api, bd["id"], "MISC_CHARGE", 90.00, folio_id=in_house["id"], memo="Minibar"
    )
    fx.post_room_and_tax(api, bd["id"])
    return prop, city, bd, owing, settled, cash, in_house


def test_the_city_ledger_sweep_takes_only_departed_direct_bill_debtors(api):
    """One of four accounts qualifies, and a second run resets the three totals to zero.

    PRD section 3.8 narrows the sweep to accounts that are DEPARTED, settle by
    DIRECT_BILL, are not already TRANSFERRED_TO_CITY_LEDGER and carry a balance
    strictly above 0.00 — so a zero-balance direct-bill account, a cash account and an
    account still in house are all excluded. The qualifying account is charged a fee of
    its balance times `city_ledger_fee_pct` over one hundred rounded for that account
    alone, then transferred out in a balanced pair, which leaves it on exactly 0.00 with
    the terminal TRANSFERRED_TO_CITY_LEDGER status, raises the receivable account by the
    swept total and leaves the day's `ledger_control_amount` at exactly 0.00. PRD section
    3.7 then refuses any further posting or tender against it, and PRD section 3.8 makes
    the three day-level figures describe the run rather than a lifetime accumulation.

    Design: Corner/calculations/calc_input_set_filtering_city_ledger_sweep_only_takes_departed_direct_bill_debtors
    """
    _prop, city, bd, owing, settled, cash, in_house = _four_folios_astride_the_sweep_filter(api)

    validate_success(api.city_ledger_sweep(bd["id"], AUDITOR))

    day = fx.read_business_date(api, bd["id"])
    assert_int(day["city_ledger_swept_folio_count"], 1, "city_ledger_swept_folio_count")
    assert_money_fields(
        day,
        {
            # round(200.00 * 1.5 / 100, 2) == 3.00
            "city_ledger_transferred_balance_total_amount": 200.00,
            "city_ledger_fee_total_amount": 3.00,
            "ledger_control_amount": 0.00,
        },
    )

    swept_rows = fx.list_postings(api, folio_id=owing["id"])
    assert_row_count(swept_rows, 3, "journal lines on the swept account")
    fee = single(find_by(swept_rows, charge_type="CITY_LEDGER_FEE"), "the fee line")
    assert_money(fee["amount"], 3.00, "the city-ledger fee")
    out_leg = single(
        find_by(swept_rows, charge_type="LEDGER_TRANSFER"), "the account's transfer leg"
    )
    assert_money(out_leg["amount"], -203.00, "the transfer off the guest account")
    in_leg = single(
        fx.list_postings(api, ledger_account_id=city["id"]), "the receivable transfer leg"
    )
    assert_money(in_leg["amount"], 203.00, "the transfer onto the city ledger")
    assert_fields(in_leg, {"charge_type": "LEDGER_TRANSFER"})

    swept = fx.read_folio(api, owing["id"])
    assert_money(swept["balance_amount"], 0.00, "balance_amount")
    assert_fields(swept, {"settlement_status": "TRANSFERRED_TO_CITY_LEDGER"})
    assert_money(
        fx.read_ledger_account(api, city["id"])["current_balance_amount"],
        203.00,
        "current_balance_amount",
    )

    # `settled` carries no journal line at all: its late-checkout charge was 0.00, so
    # PRD section 3.7 wrote no line, and PRD section 3.3 skips a DEPARTED account. PRD
    # section 3.7 re-derives the settlement dimension "after every line that touches
    # it", and no line ever touched this account, so the PRD does not determine a
    # settlement_status for it beyond the UNSETTLED that PRD section 3.2 gives it at
    # creation. What the sweep filter is being tested on — a 0.00 balance and no fee
    # line — is asserted below without that ambiguity.
    for folio_id, balance, status, label in [
        (settled["id"], 0.00, None, "the zero-balance direct-bill account"),
        (cash["id"], 150.00, "UNSETTLED", "the cash account"),
        (in_house["id"], 307.75, "UNSETTLED", "the account still in house"),
    ]:
        row = fx.read_folio(api, folio_id)
        assert_money(row["balance_amount"], balance, f"balance_amount of {label}")
        if status is not None:
            assert_fields(row, {"settlement_status": status})
        assert_empty(
            fx.list_postings(api, folio_id=folio_id, charge_type="CITY_LEDGER_FEE"),
            f"fee lines on {label}",
        )

    validate_error(
        api.create_journal_posting(
            f.build_journal_posting_payload(
                bd["id"], "MISC_CHARGE", 10.00, folio_id=owing["id"]
            ),
            AUDITOR,
        ),
        E.ERR_FOLIO_ALREADY_TRANSFERRED,
    )
    validate_error(
        api.post_payment(
            owing["id"], f.build_payment_payload(bd["id"], 10.00), FRONT_DESK
        ),
        E.ERR_FOLIO_ALREADY_TRANSFERRED,
    )

    before = fx.list_postings(api, business_date_id=bd["id"])
    validate_success(api.city_ledger_sweep(bd["id"], AUDITOR))
    after_day = fx.read_business_date(api, bd["id"])
    assert_int(after_day["city_ledger_swept_folio_count"], 0, "city_ledger_swept_folio_count")
    assert_money_fields(
        after_day,
        {
            "city_ledger_transferred_balance_total_amount": 0.00,
            "city_ledger_fee_total_amount": 0.00,
        },
    )
    assert_row_count(
        fx.list_postings(api, business_date_id=bd["id"]),
        len(before),
        "journal lines after the second sweep",
    )


def test_room_nights_number_themselves_per_account_and_a_full_stay_is_skipped(api):
    """Each stay counts its own ROOM lines, so both start at 1 and both stop at 2.

    PRD section 3.3 derives `night_index` as the count of ROOM lines the account
    already holds plus one, not from the day being audited, so creation order and
    check-in order are irrelevant and two consecutive runs number the same stay 1 then
    2. An account whose ROOM count has reached `nights_count` is skipped entirely, so a
    third run writes nothing at all while still advancing the day to ROOM_POSTING and
    incrementing its `version`. PRD section 3.8 counts only accounts holding a ROOM line
    on the day as occupied, so each night's revenue stays on its own day.

    Design: Corner/calculations/calc_chronological_room_nights_number_themselves_per_folio_across_dates
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd1 = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    bd2 = fx.create_business_date(api, prop["id"], "2026-08-02", out_of_order_room_count=4)
    bd3 = fx.create_business_date(api, prop["id"], "2026-08-03", out_of_order_room_count=4)

    def two_night_stay(code, room, name):
        return fx.create_folio(
            api,
            prop["id"],
            bd1["id"],
            confirmation_code=code,
            guest_name=name,
            room_number=room,
            nights_count=2,
            contracted_rate_amount=200.00,
            scheduled_checkout_at="2026-08-03T11:00:00.000Z",
            credit_limit_amount=2000.00,
        )

    folio_a = two_night_stay("CF-CH1", "501", "Gus Merlo")
    folio_b = two_night_stay("CF-CH2", "502", "Hal Pike")
    fx.check_in(api, folio_b["id"])
    fx.check_in(api, folio_a["id"])

    fx.post_room_and_tax(api, bd1["id"])
    for folio in (folio_a, folio_b):
        first = fx.list_postings(api, folio_id=folio["id"], charge_type="ROOM")
        assert_row_count(first, 1, "ROOM lines after the first run")
        assert_money(single(first)["amount"], 200.00, "the first room night")
        assert_int(single(first)["night_index"], 1, "night_index of the first room night")

    fx.post_room_and_tax(api, bd2["id"])
    for folio in (folio_a, folio_b):
        rooms = fx.list_postings(api, folio_id=folio["id"], charge_type="ROOM")
        assert_row_count(rooms, 2, "ROOM lines after the second run")
        assert sorted(row["night_index"] for row in rooms) == [1, 2], (
            "expected night_index values 1 and 2, got "
            f"{sorted(row['night_index'] for row in rooms)}"
        )

    third = fx.post_room_and_tax(api, bd3["id"])
    assert_fields(third, {"status": "ROOM_POSTING"})
    assert_int(third["version"], bd3["version"] + 1, "the third day's version")
    assert_empty(fx.list_postings(api, business_date_id=bd3["id"]), "lines on the third day")
    assert_int(third["rooms_occupied_count"], 0, "rooms_occupied_count")
    assert_money_fields(
        third, {"room_night_revenue_amount": 0.00, "total_revenue_amount": 0.00}
    )

    account = fx.read_folio(api, folio_a["id"])
    # 2 x (200.00 + round(200.00 * 8.875 / 100, 2)) == 2 x 217.75
    assert_money_fields(
        account, {"charges_total_amount": 435.50, "balance_amount": 435.50}
    )

    for day in (bd1, bd2):
        row = fx.read_business_date(api, day["id"])
        assert_money(row["room_night_revenue_amount"], 400.00, "room_night_revenue_amount")
        assert_int(row["rooms_occupied_count"], 2, "rooms_occupied_count")


def test_an_authorization_lapses_on_the_day_boundary_and_the_capture_names_the_lapse(api):
    """Six whole days is still good, the seventh is EXPIRED, and the curve restarts.

    PRD section 3.7 derives `aging_days` as the elapsed seconds between `obtained_at`
    and the logical clock divided by the eighty-six thousand four hundred seconds in a
    day, truncated downwards, re-derived on every read; an APPROVED authorization lapses
    to EXPIRED the instant that count reaches `card_authorization_valid_days`, and the
    test is inclusive. PRD section 3.7 runs the aging recompute before the status gate on
    a capture, so a lapse is reported as ERR_AUTHORIZATION_EXPIRED rather than as a state
    problem, and PRD section 3.7 refuses a decline of anything that is not APPROVED with
    ERR_AUTHORIZATION_NOT_APPROVED, which makes EXPIRED terminal. A capture that fails
    appends no PAYMENT line at all.

    Design: Corner/calculations/calc_decay_function_authorization_lapses_on_the_day_boundary_and_blocks_capture
    """
    fx.set_clock(api, "2026-07-25T00:00:00.000Z")
    prop = fx.create_property(api, card_authorization_valid_days=7)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-AG1",
        guest_name="Ivy Sandoval",
        room_number="601",
        contracted_rate_amount=200.00,
        settlement_method="CREDIT_CARD",
        credit_limit_amount=900.00,
    )
    fx.check_in(api, folio["id"])
    auth = fx.create_card_authorization(api, folio["id"], 400.00, "2026-07-25T00:00:00.000Z")

    fx.set_clock(api, "2026-07-31T23:59:59.999Z")
    still_good = fx.read_card_authorization(api, auth["id"])
    assert_int(still_good["aging_days"], 6, "aging_days one millisecond short of the limit")
    assert_fields(still_good, {"status": "APPROVED"})

    fx.set_clock(api, "2026-08-01T00:00:00.000Z")
    lapsed = fx.read_card_authorization(api, auth["id"])
    assert_int(lapsed["aging_days"], 7, "aging_days at the day boundary")
    assert_fields(lapsed, {"status": "EXPIRED"})

    validate_error(
        api.capture_card_authorization(
            auth["id"], f.build_capture_payload(100.00, bd["id"]), AUDITOR
        ),
        E.ERR_AUTHORIZATION_EXPIRED,
    )
    assert_empty(fx.list_postings(api, folio_id=folio["id"]), "journal lines after the refusal")
    assert_money(
        fx.read_folio(api, folio["id"])["credits_total_amount"],
        0.00,
        "credits_total_amount",
    )

    validate_error(
        api.decline_card_authorization(
            auth["id"], f.build_decline_payload("EXPIRED_CARD"), FRONT_DESK
        ),
        E.ERR_AUTHORIZATION_NOT_APPROVED,
    )

    fresh = fx.create_card_authorization(api, folio["id"], 400.00, "2026-08-01T00:00:00.000Z")
    assert_int(fresh["aging_days"], 0, "aging_days of a freshly obtained authorization")
    assert_fields(fresh, {"status": "APPROVED"})
    captured = validate_success(
        api.capture_card_authorization(
            fresh["id"], f.build_capture_payload(100.00, bd["id"]), AUDITOR
        )
    )
    assert_fields(captured, {"status": "CAPTURED"})
    assert_money(captured["captured_amount"], 100.00, "captured_amount")
    payments = fx.list_postings(api, folio_id=folio["id"], charge_type="PAYMENT")
    assert_row_count(payments, 1, "PAYMENT lines")
    assert_money(single(payments)["amount"], -100.00, "the captured tender")


def test_the_account_balance_is_a_running_total_over_every_line_ever_posted(api):
    """Two days of lines feed one pair of totals, and a reversal is another line.

    PRD section 3.7 sums an account's positive lines into `charges_total_amount` and its
    negative lines into `credits_total_amount` with no date scoping, derives
    `balance_amount` from the pair and re-derives `settlement_status` in strict order —
    exactly 0.00 reads SETTLED, otherwise a non-zero credit total reads
    PARTIALLY_SETTLED, otherwise UNSETTLED. PRD section 2.8 makes a reversal an appended
    negation rather than a retraction, so the charge total keeps the original while the
    credit total grows, and refuses a second reversal of the same line with
    ERR_POSTING_ALREADY_REVERSED. PRD section 3.3 counts none of these classes as room,
    tax or outlet revenue, so the day's total stays at 0.00 over the very same rows.

    Design: Corner/calculations/calc_aggregation_folio_balance_is_a_running_total_over_every_line_ever_posted
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd1 = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    bd2 = fx.create_business_date(api, prop["id"], "2026-08-02", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd1["id"],
        confirmation_code="CF-AGG1",
        guest_name="Jon Whitlock",
        room_number="701",
        nights_count=2,
        contracted_rate_amount=200.00,
        scheduled_checkout_at="2026-08-03T11:00:00.000Z",
        credit_limit_amount=2000.00,
    )
    fx.check_in(api, folio["id"])

    first = fx.post_journal_line(
        api, bd1["id"], "MISC_CHARGE", 120.55, headers=CONTROLLER,
        folio_id=folio["id"], memo="Day one spa",
    )
    fx.post_journal_line(
        api, bd2["id"], "MISC_CHARGE", 79.45, headers=CONTROLLER,
        folio_id=folio["id"], memo="Day two spa",
    )
    charged = fx.read_folio(api, folio["id"])
    assert_money_fields(
        charged,
        {
            "charges_total_amount": 200.00,
            "credits_total_amount": 0.00,
            "balance_amount": 200.00,
        },
    )
    assert_fields(charged, {"settlement_status": "UNSETTLED"})

    get_success_data(
        api.post_payment(
            folio["id"],
            f.build_payment_payload(bd2["id"], 50.00, memo="Part payment"),
            FRONT_DESK,
        )
    )
    part_paid = fx.read_folio(api, folio["id"])
    assert_money_fields(
        part_paid,
        {
            "charges_total_amount": 200.00,
            "credits_total_amount": -50.00,
            "balance_amount": 150.00,
        },
    )
    assert_fields(part_paid, {"settlement_status": "PARTIALLY_SETTLED"})

    reversal = validate_success(
        api.reverse_journal_posting(
            first["id"], AUDITOR, {"memo": "Spa charge disputed"}
        ),
        201,
    )
    assert_money(reversal["amount"], -120.55, "the reversing line")
    assert_fields(reversal, {"reverses_posting_id": first["id"], "charge_type": "MISC_CHARGE"})
    reversed_row = fx.read_folio(api, folio["id"])
    assert_money_fields(
        reversed_row,
        {
            "charges_total_amount": 200.00,
            "credits_total_amount": -170.55,
            "balance_amount": 29.45,
        },
    )

    validate_error(
        api.reverse_journal_posting(first["id"], AUDITOR),
        E.ERR_POSTING_ALREADY_REVERSED,
    )
    assert_money(
        fx.read_folio(api, folio["id"])["balance_amount"], 29.45, "balance_amount"
    )

    get_success_data(
        api.post_payment(
            folio["id"], f.build_payment_payload(bd2["id"], 29.45), FRONT_DESK
        )
    )
    settled = fx.read_folio(api, folio["id"])
    assert_money(settled["balance_amount"], 0.00, "balance_amount")
    assert_fields(settled, {"settlement_status": "SETTLED"})
    assert_row_count(
        fx.list_postings(api, folio_id=folio["id"]), 5, "journal lines on the account"
    )

    assert_money(
        fx.read_business_date(api, bd1["id"])["total_revenue_amount"],
        0.00,
        "total_revenue_amount",
    )
