"""The room-and-tax pass, occupancy tax and the tax true-up on sealing.

Covers PRD section 3.3 (the room-and-tax pass), section 2.6 (money, signs and
rounding), section 2.8 (the append-only journal) and the occupancy-tax true-up
that section 3.8 writes when charges are sealed.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_fields,
    assert_int,
    assert_money,
    assert_money_fields,
    assert_row_count,
    single,
)
from test_helpers.test_users import (
    AUDITOR,
    AUDITOR_2,
    CONTROLLER,
    FRONT_DESK,
    REVENUE_MANAGER,
)


def _sealed_true_up_scenario(api):
    """One 189.99 CASH folio, room and tax posted, then a 50.00 allowance posted."""
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(
        api,
        prop["id"],
        "2026-08-01",
        out_of_order_room_count=4,
        benchmark_calendar_room_revenue_amount=400.00,
        benchmark_weekday_room_revenue_amount=520.00,
    )
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-1001",
        guest_name="Ada Vance",
        room_number="101",
        contracted_rate_amount=189.99,
    )
    fx.check_in(api, folio["id"])
    fx.post_room_and_tax(api, bd["id"])
    allowance = fx.posted_allowance(
        api,
        folio["id"],
        bd["id"],
        requested_amount=50.00,
        requester=FRONT_DESK,
        approver=AUDITOR_2,
        reason_code="SERVICE_RECOVERY",
        narrative="Air conditioning failed on arrival night.",
    )
    return prop, bd, folio, allowance


def test_seal_charges_writes_a_true_up_line_and_leaves_the_provisional_line_alone(api):
    """The FINAL occupancy tax is reconciled by a TAX_TRUE_UP line, not by a rewrite.

    PRD section 3.3 taxes the gross room charge provisionally at posting time, and
    PRD section 3.8 recomputes the final occupancy tax over one allowance-reduced
    net base per folio when charges are sealed, writing the difference as a single
    TAX_TRUE_UP line. The original OCCUPANCY_TAX line is append-only and never
    rewritten (PRD section 2.8).

    Design: Difficulty/dual_variant_calc/occupancy_tax_provisional_vs_final_true_up_on_seal
    """
    prop, bd, folio, _allowance = _sealed_true_up_scenario(api)

    sealed = validate_success(api.seal_charges(bd["id"], AUDITOR))
    assert_fields(sealed, {"status": "CHARGES_SEALED"})

    provisional = validate_success(
        api.list_journal_postings(AUDITOR, folio_id=folio["id"], charge_type="OCCUPANCY_TAX")
    )
    assert_row_count(provisional, 1, "OCCUPANCY_TAX rows")
    # round(189.99 * 0.08875, 2) == 16.86
    assert_money(single(provisional)["amount"], 16.86, "provisional occupancy tax")

    true_ups = validate_success(
        api.list_journal_postings(AUDITOR, folio_id=folio["id"], charge_type="TAX_TRUE_UP")
    )
    assert_row_count(true_ups, 1, "TAX_TRUE_UP rows")
    # FINAL is round((189.99 - 50.00) * 0.08875, 2) == 12.42, and 12.42 - 16.86 == -4.44
    assert_money(single(true_ups)["amount"], -4.44, "tax true-up delta")


def test_the_true_up_moves_folio_balance_and_the_day_tax_figure_to_the_final_base(api):
    """Sealing leaves the day's tax figure at the FINAL number, not the gross one.

    PRD section 2.6 defines the folio balance as the signed sum of its journal
    lines, and PRD section 3.8 states the day's tax revenue is the sum of both the
    provisional occupancy tax and the true-up. A single-variant implementation that
    only ever taxes the gross room charge leaves 16.86 on the books.

    Design: Difficulty/dual_variant_calc/occupancy_tax_provisional_vs_final_true_up_on_seal
    """
    prop, bd, folio, _allowance = _sealed_true_up_scenario(api)

    fx.seal_charges(api, bd["id"])

    folio_row = validate_success(api.get_folio(folio["id"], FRONT_DESK))
    # 189.99 + 16.86 - 50.00 - 4.44
    assert_money(folio_row["balance_amount"], 152.41, "balance_amount")

    date_row = validate_success(api.get_business_date(bd["id"], AUDITOR))
    assert_money_fields(
        date_row,
        {
            "tax_revenue_amount": 12.42,
            "room_night_revenue_amount": 139.99,
            "allowance_credit_amount": -50.00,
            "total_revenue_amount": 152.41,
        },
    )
    assert_fields(date_row, {"status": "CHARGES_SEALED"})


def _one_empty_day_and_one_with_no_rooms_available(api):
    """2026-08-01 has 96 rooms and no guests; 2026-08-02 has one guest and no rooms."""
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    empty_day = fx.create_business_date(
        api,
        prop["id"],
        "2026-08-01",
        out_of_order_room_count=4,
        benchmark_calendar_room_revenue_amount=400.00,
        benchmark_weekday_room_revenue_amount=520.00,
    )
    fx.post_room_and_tax(api, empty_day["id"])
    no_rooms_day = fx.create_business_date(
        api, prop["id"], "2026-08-02", out_of_order_room_count=100
    )
    folio = fx.create_folio(
        api,
        prop["id"],
        no_rooms_day["id"],
        confirmation_code="CF-9501",
        guest_name="Tam Fox",
        room_number="907",
        nights_count=1,
        contracted_rate_amount=200.00,
        settlement_method="CASH",
        scheduled_checkout_at="2026-08-03T11:00:00.000Z",
    )
    fx.check_in(api, folio["id"])
    return prop, empty_day, no_rooms_day, folio


def test_a_zero_available_count_guards_occupancy_and_revpar_but_not_adr(api):
    """The three statistics carry independent guards, not one shared one.

    PRD section 3.8 makes `occupancy_pct` and `revpar_amount` divide by
    `rooms_available_count` and `adr_amount` divide by `rooms_occupied_count`, and
    gives each empty-set case a value of exactly 0.00 rather than an error or a null.
    With no rooms available but one occupied, the first two read 0.00 while the
    average daily rate is a real 200.00 division.

    Design: Difficulty/boundary_precision_check/empty_set_and_zero_denominator_statistics_return_exact_zero
    """
    _prop, _empty_day, no_rooms_day, _folio = _one_empty_day_and_one_with_no_rooms_available(api)

    day = fx.post_room_and_tax(api, no_rooms_day["id"])
    assert_int(day["rooms_available_count"], 0, "rooms_available_count")
    assert_int(day["rooms_occupied_count"], 1, "rooms_occupied_count")
    assert_money_fields(
        day,
        {
            "room_night_revenue_amount": 200.00,
            "occupancy_pct": 0.00,
            "revpar_amount": 0.00,
            "adr_amount": 200.00,
        },
    )


def test_a_day_with_no_guests_reports_exact_zeros_and_still_advances(api):
    """Every empty-set derivation is exactly 0.00 and none of them is null.

    PRD section 2.6 requires empty-set derivations to return exactly 0.00 rather than
    null or an error, and PRD section 3.8 divides a real 0.00 numerator by the 96
    available rooms for the revenue-per-available-room figure while guarding the
    average daily rate on the zero occupied count. PRD section 3.3 still carries the
    day from OPEN to ROOM_POSTING even though it wrote nothing.

    Design: Difficulty/boundary_precision_check/empty_set_and_zero_denominator_statistics_return_exact_zero
    """
    _prop, empty_day, _no_rooms_day, _folio = _one_empty_day_and_one_with_no_rooms_available(api)

    day = fx.read_business_date(api, empty_day["id"])
    assert_fields(day, {"status": "ROOM_POSTING"})
    assert_int(day["rooms_available_count"], 96, "rooms_available_count")
    assert_int(day["rooms_occupied_count"], 0, "rooms_occupied_count")
    assert_money_fields(
        day,
        {
            "occupancy_pct": 0.00,
            "adr_amount": 0.00,
            "revpar_amount": 0.00,
            "room_night_revenue_amount": 0.00,
            "other_room_revenue_amount": 0.00,
            "room_revenue_amount": 0.00,
            "tax_revenue_amount": 0.00,
            "outlet_revenue_amount": 0.00,
            "total_revenue_amount": 0.00,
        },
    )


def _comp_stay_whose_paperwork_is_revoked_after_the_first_night(api):
    """A two-night comp stay: night one posted under an ACTIVE waiver, then revoked."""
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd_d1 = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    bd_d2 = fx.create_business_date(api, prop["id"], "2026-08-02", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd_d1["id"],
        confirmation_code="CF-CMP1",
        guest_name="Ute Gil",
        room_number="1001",
        nights_count=2,
        contracted_rate_amount=200.00,
        rate_plan_code="COMP",
        market_segment="COMP",
        is_comp=True,
        scheduled_checkout_at="2026-08-03T11:00:00.000Z",
    )
    document = fx.create_authorization_document(
        api,
        prop["id"],
        doc_type="COMP_ROOM",
        folio_id=folio["id"],
        authorized_by_name="V. Holt, GM",
        document_reference="COMP-2026-0801",
        valid_from_date="2026-08-01",
        valid_to_date="2026-08-02",
    )
    fx.review_document(api, document["id"], "APPROVE", REVENUE_MANAGER)
    fx.check_in(api, folio["id"])
    fx.post_room_and_tax(api, bd_d1["id"])
    validate_success(api.revoke_authorization_document(document["id"], CONTROLLER))
    return prop, bd_d1, bd_d2, folio, document


def test_revoking_the_waiver_stops_tomorrows_pass_without_touching_yesterday(api):
    """The second night is refused outright while the first night's figures stand.

    PRD section 3.3 refuses the room-and-tax pass with ERR_COMP_AUTHORIZATION_MISSING
    (HTTP 409) when a comp account has no ACTIVE COMP_ROOM waiver covering the day, and
    PRD section 2.8 makes the journal append-only, so revoking the waiver cannot rewrite
    the 0.00 ROOM line already written for the first night. PRD section 3.3 also keeps
    the refused day untouched: it stays OPEN with nothing occupied.

    Design: Difficulty/cross_entity_state_dependency/revoking_comp_paperwork_breaks_tomorrows_audit_without_rewriting_yesterday
    """
    _prop, bd_d1, bd_d2, folio, _document = _comp_stay_whose_paperwork_is_revoked_after_the_first_night(api)

    validate_error(
        api.post_room_and_tax(bd_d2["id"], AUDITOR), E.ERR_COMP_AUTHORIZATION_MISSING
    )

    day2 = fx.read_business_date(api, bd_d2["id"])
    assert_fields(day2, {"status": "OPEN"})
    assert_int(day2["rooms_occupied_count"], 0, "rooms_occupied_count")
    assert_money(day2["room_night_revenue_amount"], 0.00, "room_night_revenue_amount")

    rows = validate_success(
        api.list_journal_postings(AUDITOR, folio_id=folio["id"], charge_type="ROOM")
    )
    assert_row_count(rows, 1, "ROOM lines")
    assert_money(single(rows)["amount"], 0.00, "the comp room night")

    day1 = fx.read_business_date(api, bd_d1["id"])
    assert_int(day1["rooms_occupied_count"], 1, "rooms_occupied_count")
    assert_money_fields(
        day1,
        {
            "occupancy_pct": 1.04,
            "room_night_revenue_amount": 0.00,
            "adr_amount": 0.00,
        },
    )


def test_a_fresh_waiver_for_the_second_night_unblocks_the_pass(api):
    """REVOKED records who revoked it, and only an ACTIVE replacement satisfies the gate.

    PRD section 3.6 moves a revoked waiver to REVOKED and stamps the revoking user on
    `reviewed_by_user_id`, and PRD section 3.6 makes a PENDING waiver satisfy no gate at
    all. Only after the replacement is approved does PRD section 3.3 let the second
    night post, at which point the day reaches ROOM_POSTING with the room occupied.

    Design: Difficulty/cross_entity_state_dependency/revoking_comp_paperwork_breaks_tomorrows_audit_without_rewriting_yesterday
    """
    prop, _bd_d1, bd_d2, folio, document = _comp_stay_whose_paperwork_is_revoked_after_the_first_night(api)

    revoked = fx.read_document(api, document["id"])
    assert_fields(revoked, {"status": "REVOKED"})
    assert revoked["reviewed_by_user_id"] == CONTROLLER["X-User-ID"], (
        "expected the revoking Controller on reviewed_by_user_id, got "
        f"{revoked['reviewed_by_user_id']!r}"
    )

    replacement = fx.create_authorization_document(
        api,
        prop["id"],
        doc_type="COMP_ROOM",
        folio_id=folio["id"],
        authorized_by_name="V. Holt, GM",
        document_reference="COMP-2026-0802",
        valid_from_date="2026-08-02",
        valid_to_date="2026-08-02",
    )
    assert_fields(replacement, {"status": "PENDING"})
    validate_error(
        api.post_room_and_tax(bd_d2["id"], AUDITOR), E.ERR_COMP_AUTHORIZATION_MISSING
    )

    fx.review_document(api, replacement["id"], "APPROVE", REVENUE_MANAGER)
    posted = fx.post_room_and_tax(api, bd_d2["id"])
    assert_fields(posted, {"status": "ROOM_POSTING"})
    assert_int(posted["rooms_occupied_count"], 1, "rooms_occupied_count")
