"""Filing an exchange request: budgets, quoted charges and the funding link."""

import pytest

from test_helpers import (
    ApiErrorId,
    bank_deposit,
    cancel_request,
    create_active_member,
    create_member,
    create_tier,
    factories,
    file_exchange_request,
    list_exchange_requests,
    list_ledger_entries,
    make_member_headers,
    pay_dues,
    read_deposit,
    read_exchange_request,
    read_member,
    setup_affiliated_resort,
    validate_error,
    validate_success,
    withdraw_deposit,
)

UNKNOWN_REQUEST_ID = "33333333-3333-4333-8333-333333333333"
UNKNOWN_DEPOSIT_ID = "44444444-4444-4444-8444-444444444444"

# A tier whose only interesting figure is a single-request cap.
CAPPED_TIER = {
    "tier_code": "BASIC",
    "annual_dues_cents": 9900,
    "base_exchange_fee_cents": 21900,
    "priority_surcharge_cents": 0,
    "priority_window_days": 365,
    "deposit_first_bonus_pct": 0,
    "max_active_requests": 1,
    "cancellation_fee_cents": 8900,
    "reinstatement_fee_cents": 10900,
    "extension_fee_cents_per_month": 3400,
}


def _fee_only_tier(tier_code, base_exchange_fee_cents):
    """A tier that withholds no dues and adds no surcharge, so subtotal == base fee."""
    return {
        "tier_code": tier_code,
        "annual_dues_cents": 0,
        "base_exchange_fee_cents": base_exchange_fee_cents,
        "priority_surcharge_cents": 0,
        "priority_window_days": 365,
        "deposit_first_bonus_pct": 10,
        "max_active_requests": 3,
        "cancellation_fee_cents": 0,
        "reinstatement_fee_cents": 0,
        "extension_fee_cents_per_month": 0,
    }


def _cheap_resort_market():
    """Resort C on a year-long SILVER band with demand 2, plus one PLUS member."""
    tier = create_tier()
    resort = setup_affiliated_resort(
        band_code="SILVER",
        band_start_month_day="01-01",
        band_end_month_day="12-31",
        **dict(factories.RESORT_C, required_annual_deposit_units=2),
    )
    member = create_active_member(
        tier["id"], email="m2@example.com", full_name="Priya Ravindran"
    )
    return tier, resort, member


class TestExchangeChargeBandKeying:
    def test_both_bands_are_keyed_on_the_pre_credit_subtotal(self, api):
        """A subtotal of 30400 costs 30260, because the fee band reads the subtotal.

        PRD §3.4: "Neither band may be keyed on the final quoted charge or on the
        subtotal after the credit has been taken off: a subtotal of 30400 cents
        on a `DEPOSIT_FIRST` request earns a 10 percent credit of 3040 cents and
        a processing fee of 2900 cents because 30400 exceeds 29999, for a total
        of 30260 cents. Keying the processing fee on the post-credit 27360 would
        wrongly yield 2000 cents and a total of 29360. Implementations must
        produce 30260."

        Design: Difficulty/combinatorial_formula/exchange_charge_band_keyed_on_subtotal_not_total
        """
        _, resort, member = _cheap_resort_market()
        deposit = bank_deposit(
            member["id"], resort["id"], unit_size="STUDIO", check_in_date="2026-11-01"
        )
        assert deposit["awarded_power"] == 27, (
            "30 base times 1.00 season and 0.90 demand, no bonus, lead 92 factor 1.00"
        )

        request = file_exchange_request(
            member["id"],
            resort["id"],
            requested_unit_size="ONE_BR",
            window_start_date="2027-06-01",
            window_end_date="2027-06-30",
            deposit_id=deposit["id"],
        )
        assert request["funding_mode"] == "DEPOSIT_FIRST"
        assert request["power_budget"] == 29, "floor(27 * 110 / 100)"
        assert request["required_power_estimate"] == 49, (
            "45 times 0.90 rounds to 41, no bonus, lead 304 factor 1.20 gives 49"
        )
        assert request["quoted_charge_cents"] == 30260, (
            "subtotal 30400, credit 3040 at 10 percent, processing fee 2900"
        )
        assert request["quoted_charge_cents"] != 29360, (
            "29360 would mean the processing fee was keyed on the post-credit 27360"
        )

        assert read_member(member["id"])["wallet_credit_cents"] == 49840
        rows, meta = list_ledger_entries(
            member_id=member["id"], entry_type="EXCHANGE_CHARGE"
        )
        assert meta["total_count"] == 1
        assert rows[0]["cash_delta_cents"] == -30260

    def test_request_first_gets_the_fee_band_but_never_the_credit(self, api):
        """The same shortfall priced without a deposit takes 2900 and no credit.

        PRD §3.4: "the credit itself is the subtotal multiplied by that
        percentage and divided by one hundred with any fraction discarded, and it
        is granted only to a `DEPOSIT_FIRST` request — a `REQUEST_FIRST` request
        receives a credit of 0 regardless of its subtotal. The processing-fee
        band, also scanned from the top, adds 1200 cents for a subtotal of 14999
        cents or less, 2000 cents for a subtotal of 29999 cents or less, and 2900
        cents above that."

        Design: Difficulty/combinatorial_formula/exchange_charge_band_keyed_on_subtotal_not_total
        """
        _, resort, member = _cheap_resort_market()

        request = file_exchange_request(
            member["id"],
            resort["id"],
            requested_unit_size="ONE_BR",
            window_start_date="2027-06-01",
            window_end_date="2027-06-30",
        )
        assert request["funding_mode"] == "REQUEST_FIRST"
        assert request["power_budget"] == 0
        assert request["required_power_estimate"] == 49
        assert request["quoted_charge_cents"] == 43450, (
            "subtotal 20900 + 17150 + 2500 = 40550, no credit, processing fee 2900"
        )

        assert read_member(member["id"])["wallet_credit_cents"] == 36650
        rows, meta = list_ledger_entries(
            member_id=member["id"], entry_type="EXCHANGE_CHARGE"
        )
        assert meta["total_count"] == 1
        assert rows[0]["cash_delta_cents"] == -43450


class TestLateFundingKeepsTheRequestFirstBranch:
    def test_attaching_a_deposit_does_not_promote_the_request(self, api):
        """Late funding recomputes the budget through the surcharged branch.

        PRD §3.4: "Attaching a deposit recomputes `power_budget` from that
        deposit's `awarded_power` — but `funding_mode` stays `REQUEST_FIRST`, so
        the surcharged, shrunken budget applies."

        Design: Corner/calculations/request_first_funding_keeps_the_surcharged_power_budget
        """
        tier = create_tier()
        resort = setup_affiliated_resort()
        member = create_active_member(tier["id"])
        deposit = bank_deposit(
            member["id"], resort["id"], unit_size="TWO_BR", check_in_date="2027-05-10"
        )
        assert deposit["awarded_power"] == 107

        request = file_exchange_request(member["id"], resort["id"])
        assert request["funding_mode"] == "REQUEST_FIRST"
        assert request["power_budget"] == 0
        assert request["required_power_estimate"] == 82
        assert request["quoted_charge_cents"] == 55000, (
            "subtotal 20900 + 28700 + 2500 = 52100, no credit, processing fee 2900"
        )

        funded = validate_success(
            api.attach_request_funding(
                request["id"],
                {"deposit_id": deposit["id"]},
                make_member_headers(member["id"]),
            )
        )
        assert funded["deposit_id"] == deposit["id"]
        assert funded["funding_mode"] == "REQUEST_FIRST"
        assert funded["power_budget"] == 97, "floor(107 * 100 / 110)"
        assert funded["power_budget"] != 117, "the deposit-first uplift is not available"
        assert funded["status"] == "SUBMITTED"

    def test_funding_does_not_requote_the_charge_or_move_any_balance(self, api):
        """The charge is quoted once, at creation, and funding moves nothing.

        PRD §3.4: "`funding_mode` is decided once, at creation, and never changes
        afterwards."
        PRD §3.4: "The quoted charge is debited at creation as an
        `EXCHANGE_CHARGE` ledger entry whose `cash_delta_cents` is the negative
        of `quoted_charge_cents`, raised against the `EXCHANGE_REQUEST` family."

        Design: Corner/calculations/request_first_funding_keeps_the_surcharged_power_budget
        """
        tier = create_tier()
        resort = setup_affiliated_resort()
        member = create_active_member(tier["id"])
        deposit = bank_deposit(
            member["id"], resort["id"], unit_size="TWO_BR", check_in_date="2027-05-10"
        )
        request = file_exchange_request(member["id"], resort["id"])
        assert read_member(member["id"])["wallet_credit_cents"] == 25100

        funded = validate_success(
            api.attach_request_funding(
                request["id"],
                {"deposit_id": deposit["id"]},
                make_member_headers(member["id"]),
            )
        )
        assert funded["quoted_charge_cents"] == 55000, "funding does not requote"
        assert funded["charge_refunded_cents"] == 0

        after = read_member(member["id"])
        assert after["wallet_credit_cents"] == 25100, "funding moves no cash"
        assert after["trading_power_balance"] == 107, "funding moves no power"
        assert read_deposit(deposit["id"])["deposit_status"] == "BANKED", (
            "linking funding does not reserve the week"
        )


class TestChargeBandBoundaries:
    def test_one_cent_more_base_fee_crosses_into_the_five_percent_credit(self, api):
        """At subtotal 9999 the credit is 0, so 10000 costs 499 cents less.

        PRD §3.4: "The deposit-first credit band, scanned from the top, gives 0
        percent for a subtotal of 9999 cents or less, 5 percent for a subtotal of
        19999 cents or less, and 10 percent for anything above that."

        Design: Corner/calculations/deposit_first_credit_band_boundary_at_subtotal_9999
        """
        low_tier = create_tier(**_fee_only_tier("BASIC", 9999))
        high_tier = create_tier(**_fee_only_tier("PLUS", 10000))
        resort = setup_affiliated_resort()

        quotes = {}
        for label, tier in (("low", low_tier), ("high", high_tier)):
            member = create_active_member(
                tier["id"], email=f"{label}@example.com", full_name=f"Member {label}"
            )
            assert member["wallet_credit_cents"] == 100000, "no dues are withheld"
            deposit = bank_deposit(
                member["id"], resort["id"], check_in_date="2027-06-15"
            )
            assert deposit["awarded_power"] == 82
            request = file_exchange_request(
                member["id"],
                resort["id"],
                window_start_date="2027-06-15",
                window_end_date="2027-06-15",
                deposit_id=deposit["id"],
            )
            assert request["funding_mode"] == "DEPOSIT_FIRST"
            assert request["power_budget"] == 90, "floor(82 * 110 / 100)"
            assert request["required_power_estimate"] == 82
            quotes[label] = (request["quoted_charge_cents"], member["id"])

        assert quotes["low"][0] == 11199, (
            "subtotal 9999 takes a 0 percent credit and a 1200 processing fee"
        )
        assert quotes["high"][0] == 10700, (
            "subtotal 10000 takes a 500 credit at 5 percent and a 1200 fee"
        )
        assert quotes["low"][0] - quotes["high"][0] == 499, (
            "one extra cent of base fee buys a 500 cent credit"
        )

        assert read_member(quotes["low"][1])["wallet_credit_cents"] == 88801
        assert read_member(quotes["high"][1])["wallet_credit_cents"] == 89300
        rows, meta = list_ledger_entries(entry_type="EXCHANGE_CHARGE")
        assert meta["total_count"] == 2
        assert sorted(row["cash_delta_cents"] for row in rows) == [-11199, -10700]

    def test_one_cent_more_base_fee_crosses_into_the_two_thousand_fee(self, api):
        """At subtotal 14999 the processing fee is 1200, at 15000 it is 2000.

        PRD §3.4: "The processing-fee band, also scanned from the top, adds 1200
        cents for a subtotal of 14999 cents or less, 2000 cents for a subtotal of
        29999 cents or less, and 2900 cents above that."

        Design: Corner/cross_cutting_complexity_layers/processing_fee_band_boundary_at_subtotal_fifteen_thousand
        """
        under_tier = create_tier(**_fee_only_tier("BASIC", 14999))
        over_tier = create_tier(**_fee_only_tier("PLUS", 15000))
        resort = setup_affiliated_resort()

        quotes = {}
        for label, tier in (("under", under_tier), ("over", over_tier)):
            member = create_active_member(
                tier["id"], email=f"{label}@example.com", full_name=f"Member {label}"
            )
            deposit = bank_deposit(
                member["id"], resort["id"], check_in_date="2027-06-15"
            )
            request = file_exchange_request(
                member["id"],
                resort["id"],
                window_start_date="2027-06-15",
                window_end_date="2027-06-15",
                deposit_id=deposit["id"],
            )
            assert request["funding_mode"] == "DEPOSIT_FIRST"
            assert request["power_budget"] == 90
            assert request["required_power_estimate"] == 82
            quotes[label] = (request["quoted_charge_cents"], member["id"])

        assert quotes["under"][0] == 15450, (
            "subtotal 14999, credit 749 at 5 percent, processing fee 1200"
        )
        assert quotes["over"][0] == 16250, (
            "subtotal 15000, credit 750 at 5 percent, processing fee 2000"
        )
        assert quotes["over"][0] - quotes["under"][0] == 800, (
            "the post-credit 14250 would have selected the 1200 fee and produced 15450"
        )

        assert read_member(quotes["under"][1])["wallet_credit_cents"] == 84550
        assert read_member(quotes["over"][1])["wallet_credit_cents"] == 83750
        rows, meta = list_ledger_entries(entry_type="EXCHANGE_CHARGE")
        assert meta["total_count"] == 2
        assert sorted(row["cash_delta_cents"] for row in rows) == [-16250, -15450]


class TestActiveRequestCap:
    def test_a_second_live_request_on_a_one_request_tier_is_refused(self, api):
        """The cap is strict, and the refusal charges nothing.

        PRD §2.10: "A member's `active_request_count` is strictly less than that
        member's tier `max_active_requests` — otherwise
        `ERR_ACTIVE_REQUEST_LIMIT` (409), on exchange request creation."

        Design: Corner/validations/third_active_request_beyond_the_tier_cap_is_rejected
        """
        tier = create_tier(**CAPPED_TIER)
        resort = setup_affiliated_resort()
        member = create_member(tier["id"])
        member = pay_dues(member)
        assert member["wallet_credit_cents"] == 90100
        first_deposit = bank_deposit(
            member["id"], resort["id"], check_in_date="2027-06-15"
        )
        second_deposit = bank_deposit(
            member["id"], resort["id"], check_in_date="2027-06-25"
        )

        first = file_exchange_request(
            member["id"],
            resort["id"],
            window_start_date="2027-06-15",
            window_end_date="2027-06-15",
            deposit_id=first_deposit["id"],
        )
        assert first["power_budget"] == 82, "a zero bonus leaves floor(82 * 100 / 100)"
        assert first["required_power_estimate"] == 82
        assert first["quoted_charge_cents"] == 21710, (
            "subtotal 21900, credit 2190 at 10 percent, processing fee 2000"
        )
        assert read_member(member["id"])["wallet_credit_cents"] == 68390

        response = api.create_exchange_request(
            factories.exchange_request_payload(
                member["id"],
                resort["id"],
                window_start_date="2027-06-25",
                window_end_date="2027-06-25",
                deposit_id=second_deposit["id"],
            ),
            make_member_headers(member["id"]),
        )
        validate_error(response, ApiErrorId.ERR_ACTIVE_REQUEST_LIMIT.value, 409)

        after = read_member(member["id"])
        assert after["active_request_count"] == 1
        assert after["wallet_credit_cents"] == 68390, "the rejected request charged nothing"
        _, meta = list_exchange_requests(member_id=member["id"])
        assert meta["total_count"] == 1

    def test_cancelling_the_live_request_frees_the_only_slot(self, api):
        """The cap counts non-terminal requests only, so a cancellation reopens it.

        PRD §3.4: "the member's `active_request_count` rises by 1."
        PRD §3.4: "Cancellation from any of those three states refunds the
        unrefunded portion of the exchange charge as described above and lowers
        the member's `active_request_count` by 1."

        Design: Corner/validations/third_active_request_beyond_the_tier_cap_is_rejected
        """
        tier = create_tier(**CAPPED_TIER)
        resort = setup_affiliated_resort()
        member = pay_dues(create_member(tier["id"]))
        first_deposit = bank_deposit(
            member["id"], resort["id"], check_in_date="2027-06-15"
        )
        second_deposit = bank_deposit(
            member["id"], resort["id"], check_in_date="2027-06-25"
        )
        first = file_exchange_request(
            member["id"],
            resort["id"],
            window_start_date="2027-06-15",
            window_end_date="2027-06-15",
            deposit_id=first_deposit["id"],
        )

        cancelled = cancel_request(first["id"], member["id"])
        assert cancelled["status"] == "CANCELLED"
        freed = read_member(member["id"])
        assert freed["active_request_count"] == 0
        assert freed["wallet_credit_cents"] == 90100

        second = file_exchange_request(
            member["id"],
            resort["id"],
            window_start_date="2027-06-25",
            window_end_date="2027-06-25",
            deposit_id=second_deposit["id"],
        )
        assert second["status"] == "SUBMITTED"
        assert second["quoted_charge_cents"] == 21710
        assert read_member(member["id"])["active_request_count"] == 1
        _, meta = list_exchange_requests(member_id=member["id"])
        assert meta["total_count"] == 2


class TestRequestWindowSpan:
    @pytest.mark.parametrize(
        "window_end_date",
        [
            pytest.param("2027-08-01", id="span_of_61_days"),
            pytest.param("2027-05-20", id="end_before_start"),
        ],
    )
    def test_incoherent_window_is_an_invalid_date_range(self, api, window_end_date):
        """Both halves of the window rule report one error id.

        PRD §3.4: "The window must be coherent and compact: `window_end_date` may
        not be earlier than `window_start_date`, and the span between them in
        whole days may not exceed 60 days, either breach being refused with
        `ERR_INVALID_DATE_RANGE`."

        Design: Corner/validations/exchange_request_window_span_beyond_sixty_days_is_rejected
        """
        tier = create_tier()
        resort = setup_affiliated_resort()
        member = create_active_member(tier["id"])
        bank_deposit(member["id"], resort["id"], check_in_date="2027-06-15")

        response = api.create_exchange_request(
            factories.exchange_request_payload(
                member["id"],
                resort["id"],
                window_start_date="2027-06-01",
                window_end_date=window_end_date,
            ),
            make_member_headers(member["id"]),
        )
        validate_error(response, ApiErrorId.ERR_INVALID_DATE_RANGE.value, 422)

        _, meta = list_exchange_requests()
        assert meta["total_count"] == 0
        after = read_member(member["id"])
        assert after["wallet_credit_cents"] == 80100
        assert after["active_request_count"] == 0

    def test_the_span_rule_outranks_the_season_band_lookup(self, api):
        """A 61-day window ending outside every band still reports the date range.

        PRD §2.10: "18. An exchange request's `window_end_date` is not earlier
        than its `window_start_date`, and the span between them in whole days is
        at most 60 — otherwise `ERR_INVALID_DATE_RANGE` (422), on exchange
        request creation." ... "21. The evaluated date falls inside exactly one
        season band of the relevant resort, matched on month and day — otherwise
        `ERR_NO_SEASON_BAND_FOR_DATE` (422)."

        Design: Corner/validations/exchange_request_window_span_beyond_sixty_days_is_rejected
        """
        tier = create_tier()
        resort = setup_affiliated_resort()
        member = create_active_member(tier["id"])

        response = api.create_exchange_request(
            factories.exchange_request_payload(
                member["id"],
                resort["id"],
                window_start_date="2027-06-01",
                window_end_date="2027-08-01",
            ),
            make_member_headers(member["id"]),
        )
        validate_error(response, ApiErrorId.ERR_INVALID_DATE_RANGE.value, 422)
        assert (
            response.json()["data"]["error_id"]
            != ApiErrorId.ERR_NO_SEASON_BAND_FOR_DATE.value
        ), "2027-08-01 lies outside the only band, but rule 18 fires first"

        accepted = file_exchange_request(
            member["id"],
            resort["id"],
            window_start_date="2027-06-01",
            window_end_date="2027-07-31",
        )
        assert accepted["status"] == "SUBMITTED", "a span of exactly 60 days is allowed"


class TestWithdrawnDepositAsFunding:
    def test_a_withdrawn_week_may_not_fund_a_request(self, api):
        """A terminal deposit is still readable but no longer usable as collateral.

        PRD §2.10: "A deposit named as funding for a request, or as the deposit
        behind a reinstatement, has `deposit_status` `BANKED` and `rental_status`
        `NOT_LISTED` — otherwise `ERR_DEPOSIT_NOT_AVAILABLE` (409)."

        Design: Corner/validations/withdrawn_deposit_named_as_funding_is_rejected
        """
        tier = create_tier()
        resort = setup_affiliated_resort()
        member = create_active_member(tier["id"])
        deposit = bank_deposit(member["id"], resort["id"], check_in_date="2027-06-15")
        assert deposit["awarded_power"] == 82
        withdrawn = withdraw_deposit(deposit["id"], member["id"])
        assert withdrawn["deposit_status"] == "WITHDRAWN"

        before = read_member(member["id"])
        assert before["trading_power_balance"] == 0
        assert before["wallet_credit_cents"] == 80100

        response = api.create_exchange_request(
            factories.exchange_request_payload(
                member["id"], resort["id"], deposit_id=deposit["id"]
            ),
            make_member_headers(member["id"]),
        )
        validate_error(response, ApiErrorId.ERR_DEPOSIT_NOT_AVAILABLE.value, 409)

        assert read_deposit(deposit["id"])["deposit_status"] == "WITHDRAWN", (
            "the row is still readable after the refusal"
        )
        _, meta = list_exchange_requests()
        assert meta["total_count"] == 0
        after = read_member(member["id"])
        assert after["wallet_credit_cents"] == 80100, "no charge was quoted"
        assert after["active_request_count"] == 0

    def test_the_same_body_without_the_deposit_is_accepted(self, api):
        """The deposit reference is the sole cause of the refusal.

        PRD §3.4: "A request created with a `deposit_id` in its body is
        `DEPOSIT_FIRST`; a request created without one is `REQUEST_FIRST`."

        Design: Corner/validations/withdrawn_deposit_named_as_funding_is_rejected
        """
        tier = create_tier()
        resort = setup_affiliated_resort()
        member = create_active_member(tier["id"])
        deposit = bank_deposit(member["id"], resort["id"], check_in_date="2027-06-15")
        withdraw_deposit(deposit["id"], member["id"])

        accepted = file_exchange_request(member["id"], resort["id"])
        assert accepted["funding_mode"] == "REQUEST_FIRST"
        assert accepted["status"] == "SUBMITTED"
        assert accepted["power_budget"] == 0
        assert accepted["quoted_charge_cents"] == 55000
        assert read_member(member["id"])["wallet_credit_cents"] == 25100


class TestRequestCancellationIsTerminal:
    def test_the_second_cancellation_is_an_invalid_transition(self, api):
        """CANCELLED has no outgoing edge, so replaying the call is a 409.

        PRD §3.4: "A member may cancel its own request outright while the request
        is `SUBMITTED`, `WAITLISTED` or `MATCHED`, and the destination is
        `CANCELLED`, which is terminal; cancelling a request already in a
        terminal state is refused with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/second_cancellation_of_the_same_request_is_rejected
        """
        tier = create_tier()
        resort = setup_affiliated_resort()
        member = create_active_member(tier["id"])
        deposit = bank_deposit(member["id"], resort["id"], check_in_date="2027-06-15")
        request = file_exchange_request(
            member["id"], resort["id"], deposit_id=deposit["id"]
        )
        assert request["quoted_charge_cents"] == 23060
        assert read_member(member["id"])["wallet_credit_cents"] == 57040

        cancelled = cancel_request(request["id"], member["id"])
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["charge_refunded_cents"] == 23060

        response = api.cancel_exchange_request(
            request["id"], make_member_headers(member["id"])
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

        after = read_exchange_request(request["id"])
        assert after["status"] == "CANCELLED"
        assert after["charge_refunded_cents"] == 23060, "not 46120"

    def test_the_refund_is_applied_exactly_once(self, api):
        """A refused replay leaves the single refund entry untouched.

        PRD §3.4: "The charge is refunded exactly once, as a single
        `EXCHANGE_CHARGE_REFUND` entry, whenever the request leaves the pipeline
        unfulfilled ... in the amount `quoted_charge_cents` minus whatever
        `charge_refunded_cents` already records."

        Design: Corner/state_machines/second_cancellation_of_the_same_request_is_rejected
        """
        tier = create_tier()
        resort = setup_affiliated_resort()
        member = create_active_member(tier["id"])
        deposit = bank_deposit(member["id"], resort["id"], check_in_date="2027-06-15")
        request = file_exchange_request(
            member["id"], resort["id"], deposit_id=deposit["id"]
        )
        cancel_request(request["id"], member["id"])
        validate_error(
            api.cancel_exchange_request(request["id"], make_member_headers(member["id"])),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            409,
        )

        after = read_member(member["id"])
        assert after["wallet_credit_cents"] == 80100, "exactly the pre-request wallet"
        assert after["active_request_count"] == 0
        rows, meta = list_ledger_entries(
            member_id=member["id"], entry_type="EXCHANGE_CHARGE_REFUND"
        )
        assert meta["total_count"] == 1
        assert rows[0]["cash_delta_cents"] == 23060


class TestFundingLinkExistenceOrder:
    def test_the_path_request_is_resolved_before_the_body_deposit(self, api):
        """Both references are checked, path first, each with its own 404.

        PRD §2.10: "6. Every path parameter identifies an existing row, on every
        endpoint carrying one, checked left to right — otherwise the
        family-specific 404 listed in §2.4. 7. Every foreign key in a body or
        query string identifies an existing row, on every endpoint accepting one,
        checked in the declared input field order — otherwise the family-specific
        404 listed in §2.4."

        Design: Corner/endpoints/request_funding_link_requires_both_rows_to_exist
        """
        tier = create_tier()
        resort = setup_affiliated_resort()
        member = create_active_member(tier["id"])
        deposit = bank_deposit(member["id"], resort["id"], check_in_date="2027-06-15")
        request = file_exchange_request(member["id"], resort["id"])
        assert request["quoted_charge_cents"] == 55000

        unknown_path = api.attach_request_funding(
            UNKNOWN_REQUEST_ID,
            {"deposit_id": deposit["id"]},
            make_member_headers(member["id"]),
        )
        validate_error(
            unknown_path, ApiErrorId.ERR_EXCHANGE_REQUEST_NOT_FOUND.value, 404
        )

        unknown_body = api.attach_request_funding(
            request["id"],
            {"deposit_id": UNKNOWN_DEPOSIT_ID},
            make_member_headers(member["id"]),
        )
        validate_error(unknown_body, ApiErrorId.ERR_DEPOSIT_NOT_FOUND.value, 404)

        linked = validate_success(
            api.attach_request_funding(
                request["id"],
                {"deposit_id": deposit["id"]},
                make_member_headers(member["id"]),
            )
        )
        assert linked["deposit_id"] == deposit["id"]
        assert linked["power_budget"] == 74, "floor(82 * 100 / 110)"

    def test_neither_rejection_nor_the_link_moves_any_money(self, api):
        """The wallet is untouched across both refusals and the successful link.

        PRD §3.4: "Attaching a deposit recomputes `power_budget` from that
        deposit's `awarded_power` — but `funding_mode` stays `REQUEST_FIRST`."

        Design: Corner/endpoints/request_funding_link_requires_both_rows_to_exist
        """
        tier = create_tier()
        resort = setup_affiliated_resort()
        member = create_active_member(tier["id"])
        deposit = bank_deposit(member["id"], resort["id"], check_in_date="2027-06-15")
        request = file_exchange_request(member["id"], resort["id"])
        assert read_member(member["id"])["wallet_credit_cents"] == 25100

        validate_error(
            api.attach_request_funding(
                UNKNOWN_REQUEST_ID,
                {"deposit_id": deposit["id"]},
                make_member_headers(member["id"]),
            ),
            ApiErrorId.ERR_EXCHANGE_REQUEST_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.attach_request_funding(
                request["id"],
                {"deposit_id": UNKNOWN_DEPOSIT_ID},
                make_member_headers(member["id"]),
            ),
            ApiErrorId.ERR_DEPOSIT_NOT_FOUND.value,
            404,
        )
        validate_success(
            api.attach_request_funding(
                request["id"],
                {"deposit_id": deposit["id"]},
                make_member_headers(member["id"]),
            )
        )

        assert read_member(member["id"])["wallet_credit_cents"] == 25100
        final = read_exchange_request(request["id"])
        assert final["funding_mode"] == "REQUEST_FIRST"
        assert final["quoted_charge_cents"] == 55000
        assert read_deposit(deposit["id"])["deposit_status"] == "BANKED"


class TestWalletGate:
    def test_an_unaffordable_charge_is_refused_with_402(self, api):
        """The last rule in the order fires on an otherwise flawless request.

        PRD §2.10: "The paying member's `wallet_credit_cents` is at least the
        amount about to be debited — otherwise `ERR_INSUFFICIENT_WALLET_CREDIT`
        (402). This guards five operations, each with its own amount:
        `quoted_charge_cents` on exchange request creation."

        Design: Corner/errors/insufficient_wallet_credit_rejects_the_exchange_request
        """
        tier = create_tier()
        resort = setup_affiliated_resort()
        member = create_active_member(tier["id"], amount_cents=19900)
        deposit = bank_deposit(member["id"], resort["id"], check_in_date="2027-06-15")

        before = read_member(member["id"])
        assert before["enrollment_status"] == "ACTIVE"
        assert before["wallet_credit_cents"] == 0, "the dues were withheld in full"
        assert before["trading_power_balance"] == 82

        response = api.create_exchange_request(
            factories.exchange_request_payload(
                member["id"], resort["id"], deposit_id=deposit["id"]
            ),
            make_member_headers(member["id"]),
        )
        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_WALLET_CREDIT.value, 402)

    def test_the_refused_charge_writes_nothing_at_all(self, api):
        """The charge is checked before anything is written.

        PRD §3.4: "a member whose `wallet_credit_cents` cannot cover it is
        refused with `ERR_INSUFFICIENT_WALLET_CREDIT` before anything is
        written."

        Design: Corner/errors/insufficient_wallet_credit_rejects_the_exchange_request
        """
        tier = create_tier()
        resort = setup_affiliated_resort()
        member = create_active_member(tier["id"], amount_cents=19900)
        deposit = bank_deposit(member["id"], resort["id"], check_in_date="2027-06-15")

        validate_error(
            api.create_exchange_request(
                factories.exchange_request_payload(
                    member["id"], resort["id"], deposit_id=deposit["id"]
                ),
                make_member_headers(member["id"]),
            ),
            ApiErrorId.ERR_INSUFFICIENT_WALLET_CREDIT.value,
            402,
        )

        _, requests_meta = list_exchange_requests()
        assert requests_meta["total_count"] == 0
        after = read_member(member["id"])
        assert after["active_request_count"] == 0
        assert after["wallet_credit_cents"] == 0, "never driven negative"
        _, charges = list_ledger_entries(
            member_id=member["id"], entry_type="EXCHANGE_CHARGE"
        )
        assert charges["total_count"] == 0
