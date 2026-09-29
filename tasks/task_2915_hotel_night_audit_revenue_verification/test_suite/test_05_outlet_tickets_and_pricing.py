"""Outlet check pricing, the large-party discount and the void invariant.

Covers PRD section 3.4 (outlet capture: the five-step check computation, the
inclusive large-ticket threshold and the void that undoes every figure) together
with the money rules of PRD section 2.6.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_fields,
    assert_instant_equals,
    assert_int,
    assert_money,
    assert_money_fields,
    assert_row_count,
)
from test_helpers.test_users import AUDITOR, make_outlet_manager_headers


def _three_checks_scenario(api):
    """One F&B outlet holding checks of 400.00, 399.99 and 500.00 gross."""
    fx.set_clock(api, "2026-08-01T20:00:00.000Z")
    prop = fx.create_property(api)
    outlet = fx.create_outlet(
        api,
        prop["id"],
        outlet_code="GRILL",
        outlet_name="Harbor Grill",
        outlet_type="FB_OUTLET",
        requires_shift_settlement=False,
    )
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    tickets = {}
    for number, gross in [("T-0400", 400.00), ("T-0399", 399.99), ("T-0500", 500.00)]:
        tickets[number] = fx.create_outlet_ticket(
            api,
            outlet["id"],
            bd["id"],
            gross_amount=gross,
            ticket_number=number,
            settlement_type="CASH",
            opened_at="2026-08-01T19:00:00.000Z",
        )
    for number in ["T-0399", "T-0500", "T-0400"]:
        fx.close_outlet_ticket(
            api,
            tickets[number]["id"],
            outlet["id"],
            transmitted_at="2026-08-01T20:00:00.000Z",
        )
    return prop, outlet, bd, tickets


def test_the_discount_threshold_tests_the_base_but_the_discount_comes_off_the_gross(api):
    """A base landing exactly on the threshold earns 5% of gross, one cent below earns nothing.

    PRD section 3.4 gates `large_party_discount_amount` on `taxable_base_amount` being
    at or above `large_ticket_threshold_amount` — inclusive — yet computes the amount
    from `gross_amount`. A 400.00 check grosses a 72.00 service charge for a base of
    exactly 472.00, so it earns 20.00 off and totals 481.50; discounting the gross
    first and recomputing the service charge and tax on 380.00 would total 476.43,
    which the PRD forbids. A 399.99 check bases at 471.99, one cent short, so it earns
    nothing and — despite being the smaller check — totals the larger 501.49.

    Design: Difficulty/combinatorial_formula/outlet_ticket_threshold_pinned_to_pre_discount_taxable_base
    """
    _prop, _outlet, _bd, tickets = _three_checks_scenario(api)

    at_threshold = validate_success(api.get_outlet_ticket(tickets["T-0400"]["id"], AUDITOR))
    assert_money_fields(
        at_threshold,
        {
            "service_charge_amount": 72.00,
            "taxable_base_amount": 472.00,
            "tax_amount": 29.50,
            "large_party_discount_amount": 20.00,
            "total_amount": 481.50,
        },
    )

    one_cent_short = validate_success(api.get_outlet_ticket(tickets["T-0399"]["id"], AUDITOR))
    assert_money_fields(
        one_cent_short,
        {
            "taxable_base_amount": 471.99,
            "large_party_discount_amount": 0.00,
            "total_amount": 501.49,
        },
    )


def test_closed_check_totals_roll_up_into_the_operating_day(api):
    """The day's outlet revenue is the sum of the closed checks' own totals.

    PRD section 3.4 makes `outlet_revenue_amount` the sum of `total_amount` over the
    day's `CLOSED` checks and `closed_outlet_ticket_count` their count, so the three
    checks contribute 481.50, 501.49 and 601.88 for 1584.87 across three rows.

    Design: Difficulty/combinatorial_formula/outlet_ticket_threshold_pinned_to_pre_discount_taxable_base
    """
    _prop, _outlet, bd, tickets = _three_checks_scenario(api)

    largest = validate_success(api.get_outlet_ticket(tickets["T-0500"]["id"], AUDITOR))
    assert_money_fields(
        largest,
        {
            "service_charge_amount": 90.00,
            "taxable_base_amount": 590.00,
            "tax_amount": 36.88,
            "large_party_discount_amount": 25.00,
            "total_amount": 601.88,
        },
    )

    day = fx.read_business_date(api, bd["id"])
    assert_int(day["closed_outlet_ticket_count"], 3, "closed_outlet_ticket_count")
    assert_money(day["outlet_revenue_amount"], 1584.87, "outlet_revenue_amount")


def _room_charged_check_ready_to_void(api):
    """A CLOSED 128.00 room-charge check whose 160.48 total sits on an in-house account."""
    fx.set_clock(api, "2026-08-01T20:00:00.000Z")
    prop = fx.create_property(api)
    outlet = fx.create_outlet(
        api,
        prop["id"],
        outlet_code="STEAK",
        outlet_name="Harbor Steakhouse",
        outlet_type="FB_OUTLET",
        requires_shift_settlement=False,
    )
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-VOID1",
        guest_name="Ann Mora",
        room_number="1501",
        nights_count=1,
        contracted_rate_amount=200.00,
        scheduled_checkout_at="2026-08-02T11:00:00.000Z",
    )
    fx.check_in(api, folio["id"])
    ticket = fx.create_outlet_ticket(
        api,
        outlet["id"],
        bd["id"],
        128.00,
        ticket_number="S-001",
        settlement_type="ROOM_CHARGE",
        room_charge_folio_id=folio["id"],
        opened_at="2026-08-01T19:00:00.000Z",
    )
    closed = fx.close_outlet_ticket(
        api, ticket["id"], outlet["id"], "2026-08-01T20:00:00.000Z"
    )
    return prop, outlet, bd, folio, closed


def test_voiding_a_check_returns_the_days_count_and_revenue_to_zero(api):
    """The count is decremented, not merely flagged, and every figure it fed goes back.

    PRD section 3.4 zeroes a voided check's `total_amount`, stamps `voided_at` from the
    logical clock of PRD section 2.5, and reverses the check out of the day's
    `closed_outlet_ticket_count` and `outlet_revenue_amount`. With no room-and-tax pass
    yet, PRD section 3.3 leaves `total_revenue_amount` at exactly 0.00.

    Design: Difficulty/compensating_invariant/outlet_ticket_void_restores_a_count_quantity_exactly
    """
    _prop, outlet, bd, _folio, closed = _room_charged_check_ready_to_void(api)
    assert_money(closed["total_amount"], 160.48, "total_amount before the void")

    voided = validate_success(
        api.void_outlet_ticket(closed["id"], make_outlet_manager_headers(outlet["id"]))
    )
    assert_fields(voided, {"status": "VOID"})
    assert_money(voided["total_amount"], 0.00, "total_amount")
    assert_instant_equals(voided["voided_at"], "2026-08-01T20:00:00.000Z", "voided_at")

    day = fx.read_business_date(api, bd["id"])
    assert_int(day["closed_outlet_ticket_count"], 0, "closed_outlet_ticket_count")
    assert_money_fields(
        day, {"outlet_revenue_amount": 0.00, "total_revenue_amount": 0.00}
    )


def test_the_void_compensates_by_appending_and_never_drives_the_count_negative(api):
    """Two OUTLET_TRANSFER lines net to zero, and a second void is refused.

    PRD section 2.8 forbids deleting a journal line, so the void appends a mirror line
    naming the original through `reverses_posting_id` — the account's charges and credits
    both stand at 160.48 while its balance returns to exactly 0.00 and PRD section 3.7
    re-derives SETTLED. PRD section 3.4 then refuses a second void with
    ERR_TICKET_NOT_CLOSED (HTTP 409), so the day's count cannot fall below zero.

    Design: Difficulty/compensating_invariant/outlet_ticket_void_restores_a_count_quantity_exactly
    """
    _prop, outlet, bd, folio, closed = _room_charged_check_ready_to_void(api)
    manager = make_outlet_manager_headers(outlet["id"])
    validate_success(api.void_outlet_ticket(closed["id"], manager))

    rows = validate_success(
        api.list_journal_postings(AUDITOR, outlet_ticket_id=closed["id"])
    )
    assert_row_count(rows, 2, "OUTLET_TRANSFER lines")
    originals = [row for row in rows if row["reverses_posting_id"] is None]
    mirrors = [row for row in rows if row["reverses_posting_id"] is not None]
    assert_row_count(originals, 1, "original OUTLET_TRANSFER lines")
    assert_row_count(mirrors, 1, "reversing OUTLET_TRANSFER lines")
    original = originals[0]
    mirror = mirrors[0]
    assert_money(original["amount"], 160.48, "the original transfer")
    assert_money(mirror["amount"], -160.48, "the reversing transfer")
    assert_fields(
        original, {"charge_type": "OUTLET_TRANSFER", "source_channel": "OUTLET_POS"}
    )
    assert_fields(
        mirror,
        {
            "charge_type": "OUTLET_TRANSFER",
            "source_channel": "OUTLET_POS",
            "reverses_posting_id": original["id"],
        },
    )

    account = fx.read_folio(api, folio["id"])
    assert_money_fields(
        account,
        {
            "charges_total_amount": 160.48,
            "credits_total_amount": -160.48,
            "balance_amount": 0.00,
        },
    )
    assert_fields(account, {"settlement_status": "SETTLED"})

    validate_error(api.void_outlet_ticket(closed["id"], manager), E.ERR_TICKET_NOT_CLOSED)
    assert_int(
        fx.read_business_date(api, bd["id"])["closed_outlet_ticket_count"],
        0,
        "closed_outlet_ticket_count",
    )
