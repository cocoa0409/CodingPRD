"""The two account-level counters that must equal the sum of their live contributions."""
import pytest

from test_helpers import (
    assert_instant_equals,
    decide_exception,
    file_exception,
    read_account,
    read_exception,
    read_order_form,
    read_pricing_preview,
    read_quote,
    revoke_exception,
    reverse_booking,
    setup_booked_order_form,
    setup_single_line_quote,
)


def test_booking_moves_the_account_recurring_ledger_and_the_quote_figures(api, base):
    """PRD §2.12: "`Account.booked_arr_cents` equals the sum of `booked_arr_cents` over
    that account's order forms whose status is `BOOKED`. Booking an order form increases it
    by that form's recorded amount; reversing a booking decreases it by the same amount. No
    other operation touches it."
    PRD §3.9: "Booking moves the form `SIGNED` to `BOOKED`, stamps `booked_at`, writes both
    figures onto the form, increases the account's conserved `booked_arr_cents` by the
    form's `booked_arr_cents`, and bubbles up: the quote moves `APPROVED` to `BOOKED`,
    stamps its own `booked_at`, and copies both booking figures onto itself."

    Design: Difficulty/compensating_invariant/account_booked_arr_ledger_conserved_across_booking_and_reversal
    """
    account = read_account(api, base["account"]["id"])
    assert account["booked_arr_cents"] == 0
    assert account["credit_status"] == "CLEAR"

    scenario = setup_booked_order_form(
        api, base, [("support", 10, 0.00)], term_months=12,
        title="Northwind Support Renewal FY27", payment_terms_days=30,
        billing_frequency="ANNUAL",
    )
    form = scenario["form"]
    assert form["status"] == "BOOKED"
    assert form["booked_arr_cents"] == 300000
    assert form["booked_tcv_cents"] == 300000
    assert_instant_equals(form["booked_at"], "2026-08-01T00:00:00.000Z", "booked_at")

    assert scenario["quote"]["final_net_total_cents"] == 300000
    assert read_account(api, base["account"]["id"])["booked_arr_cents"] == 300000


def test_reversing_a_booking_returns_the_ledger_while_the_form_retains_its_figures(api, base):
    """PRD §3.9: "It decreases the account's `booked_arr_cents` by exactly the amount that
    form had contributed, while the form retains its own `booked_arr_cents` and
    `booked_tcv_cents` for audit."
    PRD §3.9: "It moves the form `BOOKED` to `VOID`, stamping `booking_reversed_at` and
    `voided_at` with the logical clock, recording the supplied `reversal_reason`, setting
    `void_reason` to the fixed string `BOOKING_REVERSED`, and incrementing
    `booking_reversal_count` by one."
    PRD §3.9: "And it bubbles up: the quote moves `BOOKED` back to `APPROVED`, has its
    `booked_at` cleared, and has its own `booked_arr_cents` and `booked_tcv_cents` reset to
    zero."

    Design: Difficulty/compensating_invariant/account_booked_arr_ledger_conserved_across_booking_and_reversal
    """
    scenario = setup_booked_order_form(
        api, base, [("support", 10, 0.00)], term_months=12,
        title="Northwind Support Renewal FY27", payment_terms_days=30,
        billing_frequency="ANNUAL",
    )
    reverse_booking(
        api,
        scenario["form"]["id"],
        reversal_reason="Customer legal entity changed; rebooking under the correct entity",
    )

    form = read_order_form(api, scenario["form"]["id"])
    assert form["status"] == "VOID"
    assert form["booked_arr_cents"] == 300000
    assert form["booked_tcv_cents"] == 300000
    assert form["booking_reversal_count"] == 1
    assert form["void_reason"] == "BOOKING_REVERSED"
    assert_instant_equals(
        form["booking_reversed_at"], "2026-08-01T00:00:00.000Z", "booking_reversed_at"
    )
    assert_instant_equals(form["voided_at"], "2026-08-01T00:00:00.000Z", "voided_at")

    assert read_account(api, base["account"]["id"])["booked_arr_cents"] == 0

    quote = read_quote(api, scenario["quote"]["id"])
    assert quote["status"] == "APPROVED"
    assert quote["booked_arr_cents"] == 0
    assert quote["booked_tcv_cents"] == 0


def _setup_below_floor_quote(api, base):
    quote, line = setup_single_line_quote(
        api, base, "service", 10, 0.00, term_months=12,
        title="Northwind Implementation Program", payment_terms_days=30,
        billing_frequency="ANNUAL",
    )
    return quote, line


def test_accepting_an_exception_charges_the_allowance_pool_and_lifts_the_level(
    api, base, cfo_headers
):
    """PRD §2.12: "`Account.exception_allowance_used_cents` equals the sum of
    `allowance_consumed_cents` over that account's competitive exceptions whose status is
    `ACCEPTED`. Exceptions in `SUBMITTED`, `REJECTED`, `REVOKED` and `RELEASED` contribute
    nothing."
    PRD §3.5: "It records the margin give-up figure into `allowance_consumed_cents`, and it
    moves the account's conserved pool upwards by exactly that amount."
    PRD §3.5: "It then reaches back into the quote: `required_approval_level` is recomputed
    as the greater of the matrix level and 3, and `Quote.version` is incremented by one."

    Design: Difficulty/compensating_invariant/exception_allowance_pool_conserved_across_acceptance_and_revocation
    """
    assert read_account(api, base["account"]["id"])["exception_allowance_used_cents"] == 0
    quote, line = _setup_below_floor_quote(api, base)
    assert line["final_net_cents"] == 2000000

    preview = read_pricing_preview(api, quote["id"])
    assert preview["final_net_total_cents"] == 2000000
    assert preview["cost_total_cents"] == 1500000
    assert preview["final_margin_pct"] == pytest.approx(0.250000, abs=1e-9)
    assert preview["margin_give_up_cents"] == 200000
    assert preview["required_approval_level"] == 0

    exception = file_exception(
        api, quote["id"], competitor_name="Meridian Systems",
        competitor_quoted_total_cents=1850000,
        evidence_reference="RFP-2026-114-competitor-quote.pdf",
        justification="Incumbent integrator undercut the implementation scope by 7.5 percent",
    )
    assert exception["status"] == "SUBMITTED"
    assert exception["documented_by_user_id"] == "u-rep-1"

    accepted = decide_exception(
        api, exception["id"], "ACCEPT", headers=cfo_headers,
        decision_note="Margin give-up approved against the FY26 allowance",
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["allowance_consumed_cents"] == 200000
    assert read_account(api, base["account"]["id"])["exception_allowance_used_cents"] == 200000
    assert read_quote(api, quote["id"])["required_approval_level"] == 3


def test_revoking_an_exception_returns_the_pool_and_the_matrix_level(api, base, cfo_headers):
    """PRD §3.5: "Revocation moves `ACCEPTED` to `REVOKED`, stamps `released_at` with the
    logical clock and records the note, returns exactly `allowance_consumed_cents` to the
    account's pool while retaining that recorded figure on the exception for audit,
    recomputes the quote's `required_approval_level` from the matrix without the
    accepted-exception floor, and increments `Quote.version` by one."
    PRD §2.12: "Accepting an exception increases the counter by the amount that exception
    consumed; revoking it, or releasing it automatically when the quote it defends is
    rejected or expires, decreases the counter by exactly that same recorded amount."

    Design: Difficulty/compensating_invariant/exception_allowance_pool_conserved_across_acceptance_and_revocation
    """
    quote, _ = _setup_below_floor_quote(api, base)
    exception = file_exception(
        api, quote["id"], competitor_name="Meridian Systems",
        competitor_quoted_total_cents=1850000,
        evidence_reference="RFP-2026-114-competitor-quote.pdf",
        justification="Incumbent integrator undercut the implementation scope by 7.5 percent",
    )
    decide_exception(
        api, exception["id"], "ACCEPT", headers=cfo_headers,
        decision_note="Margin give-up approved against the FY26 allowance",
    )

    revoked = revoke_exception(
        api, exception["id"], headers=cfo_headers,
        decision_note="Competitive threat withdrew; exception no longer justified",
    )
    assert revoked["status"] == "REVOKED"
    assert revoked["allowance_consumed_cents"] == 200000
    assert_instant_equals(revoked["released_at"], "2026-08-01T00:00:00.000Z", "released_at")

    account = read_account(api, base["account"]["id"])
    assert account["exception_allowance_used_cents"] == 0

    quote = read_quote(api, quote["id"])
    assert quote["required_approval_level"] == 0
    assert quote["status"] == "DRAFT"
    assert read_exception(api, quote["id"], exception["id"])["allowance_consumed_cents"] == 200000
