"""Ledger reconciliation, compensating pairs and the three concurrency tokens."""

from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    bank_deposit,
    buy_extension,
    cancel_request,
    factories,
    file_exchange_request,
    list_exchange_requests,
    list_ledger_entries,
    list_quality_reviews,
    make_member_headers,
    read_deposit,
    read_exchange_request,
    read_member,
    read_resort,
    setup_confirmed_exchange,
    setup_market,
    validate_error,
    validate_success,
    withdraw_deposit,
)

THREE_WEEKS = (
    ("ONE_BR", "2027-06-15", 82),
    ("ONE_BR", "2027-06-25", 82),
    ("TWO_BR", "2027-05-10", 107),
)


def _three_banked_weeks():
    """One member holding three non-colliding weeks worth 271 points together."""
    market = setup_market(member_count=1)
    member = market["members"][0]
    weeks = []
    for unit_size, check_in_date, expected in THREE_WEEKS:
        week = bank_deposit(
            member["id"], market["resort"]["id"],
            unit_size=unit_size, check_in_date=check_in_date,
        )
        assert week["awarded_power"] == expected
        assert week["deposit_status"] == "BANKED"
        assert week["rental_status"] == "NOT_LISTED"
        weeks.append(week)
    market["member"] = member
    market["weeks"] = weeks
    return market


def _funded_request_awaiting_a_match():
    """A DEPOSIT_FIRST ONE_BR request funded by a TWO_BR week nobody can match."""
    market = setup_market(member_count=1)
    member = market["members"][0]
    funding = bank_deposit(
        member["id"], market["resort"]["id"],
        unit_size="TWO_BR", check_in_date="2027-05-10",
    )
    assert funding["awarded_power"] == 107
    request = file_exchange_request(
        member["id"], market["resort"]["id"], requested_unit_size="ONE_BR",
        window_start_date="2027-06-01", window_end_date="2027-06-30",
        deposit_id=funding["id"],
    )
    market.update({"member": member, "funding": funding, "request": request})
    return market


class TestDepositWithdrawalConservesPower:
    def test_three_credits_and_three_reversals_return_the_balance_to_zero(self, api):
        """271 points in, 271 points out, and every reversal names its own week.

        PRD §3.3: "On success the deposit's `remaining_power` is reversed out of
        the owner's balance through a `DEPOSIT_WITHDRAWAL_REVERSAL` ledger entry,
        and the resort's `deposits_committed_count` falls by 1 while its
        `committed_nights` falls by eight nights."

        Design: Difficulty/compensating_invariant/deposit_then_withdraw_conserves_trading_power
        """
        market = _three_banked_weeks()
        member_id = market["member"]["id"]

        assert read_member(member_id)["trading_power_balance"] == 271, "82 + 82 + 107"
        loaded = read_resort(market["resort"]["id"])
        assert loaded["deposits_committed_count"] == 3
        assert loaded["committed_nights"] == 24

        for week in market["weeks"]:
            withdrawn = withdraw_deposit(week["id"], member_id)
            assert withdrawn["deposit_status"] == "WITHDRAWN"

        assert read_member(member_id)["trading_power_balance"] == 0, (
            "exactly the pre-deposit value"
        )
        for week, (_, _, expected) in zip(market["weeks"], THREE_WEEKS):
            after = read_deposit(week["id"])
            assert after["deposit_status"] == "WITHDRAWN"
            assert after["awarded_power"] == expected, (
                "the frozen award is never rewritten by a withdrawal"
            )

        emptied = read_resort(market["resort"]["id"])
        assert emptied["deposits_committed_count"] == 0
        assert emptied["committed_nights"] == 0

    def test_the_reversals_are_new_rows_rather_than_edits_of_the_credits(self, api):
        """Seven rows survive, and their power deltas sum to the balance.

        PRD §2.6: "Power-side movements are `DEPOSIT_CREDIT`,
        `DEPOSIT_WITHDRAWAL_REVERSAL`, `DEPOSIT_EXPIRY_FORFEIT`,
        `SETTLEMENT_ADJUSTMENT`, `EXCHANGE_DEBIT`, `EXCHANGE_RESTORATION`,
        `RESTORATION_HAIRCUT`, `GETAWAY_LISTING_FORFEIT` and
        `DISPUTE_POWER_GRANT`."

        Design: Difficulty/compensating_invariant/deposit_then_withdraw_conserves_trading_power
        """
        market = _three_banked_weeks()
        member_id = market["member"]["id"]
        for week in market["weeks"]:
            withdraw_deposit(week["id"], member_id)

        rows, meta = list_ledger_entries(member_id=member_id)
        assert meta["total_count"] == 7
        assert [row["entry_type"] for row in rows] == [
            "DUES_PAYMENT",
            "DEPOSIT_CREDIT",
            "DEPOSIT_CREDIT",
            "DEPOSIT_CREDIT",
            "DEPOSIT_WITHDRAWAL_REVERSAL",
            "DEPOSIT_WITHDRAWAL_REVERSAL",
            "DEPOSIT_WITHDRAWAL_REVERSAL",
        ], "no row was deleted or edited"
        assert [row["power_delta"] for row in rows] == [0, 82, 82, 107, -82, -82, -107]

        member = read_member(member_id)
        assert sum(row["power_delta"] for row in rows) == 0
        assert member["trading_power_balance"] == 0
        assert member["wallet_credit_cents"] == 80100, (
            "withdrawing an unreserved week carries no fee"
        )


class TestRequestCancellationConservesCash:
    def test_the_refund_returns_the_net_quote_rather_than_any_component(self, api):
        """23060 out and 23060 back, not the 20900 base and not the 23400 subtotal.

        PRD §3.4: "The charge is refunded exactly once, as a single
        `EXCHANGE_CHARGE_REFUND` entry, whenever the request leaves the pipeline
        unfulfilled — that is, on reaching `CANCELLED`, `EXPIRED` or `DENIED` — in
        the amount `quoted_charge_cents` minus whatever `charge_refunded_cents`
        already records"

        Design: Difficulty/compensating_invariant/request_create_then_cancel_conserves_wallet_cash
        """
        market = _funded_request_awaiting_a_match()
        request = market["request"]
        assert request["funding_mode"] == "DEPOSIT_FIRST"
        assert request["power_budget"] == 117, "107 * 110 / 100 = 117.7, floored"
        assert request["required_power_estimate"] == 82
        assert request["quoted_charge_cents"] == 23060, (
            "subtotal 23400 with no shortfall, less the 2340 credit, plus 2000"
        )
        assert request["status"] == "SUBMITTED"

        before = read_member(market["member"]["id"])
        assert before["wallet_credit_cents"] == 57040, "80100 less the 23060 charge"
        assert before["active_request_count"] == 1
        assert before["trading_power_balance"] == 107

        cancelled = cancel_request(request["id"], market["member"]["id"])
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["charge_refunded_cents"] == 23060
        assert cancelled["quoted_charge_cents"] == 23060, "the quote itself is not rewritten"

        after = read_member(market["member"]["id"])
        assert after["wallet_credit_cents"] == 80100, "exactly the pre-request value"
        assert after["active_request_count"] == 0, (
            "the cap of three live requests is fully available again"
        )

    def test_the_ledger_gains_a_refund_row_and_the_week_comes_back(self, api):
        """Four rows summing to the wallet, and the funding week is BANKED again.

        PRD §2.6: "a member's `trading_power_balance` always equals the sum of
        `power_delta` across every ledger entry whose `member_id` is that member,
        and their `wallet_credit_cents` always equals the sum of
        `cash_delta_cents` across those same entries."

        Design: Difficulty/compensating_invariant/request_create_then_cancel_conserves_wallet_cash
        """
        market = _funded_request_awaiting_a_match()

        rows, meta = list_ledger_entries(member_id=market["member"]["id"])
        assert meta["total_count"] == 3
        assert [row["entry_type"] for row in rows] == [
            "DUES_PAYMENT",
            "DEPOSIT_CREDIT",
            "EXCHANGE_CHARGE",
        ]
        assert [row["cash_delta_cents"] for row in rows] == [80100, 0, -23060]

        cancel_request(market["request"]["id"], market["member"]["id"])

        rows, meta = list_ledger_entries(member_id=market["member"]["id"])
        assert meta["total_count"] == 4
        assert rows[3]["entry_type"] == "EXCHANGE_CHARGE_REFUND"
        assert rows[3]["cash_delta_cents"] == 23060
        assert rows[3]["power_delta"] == 0

        member = read_member(market["member"]["id"])
        assert sum(row["cash_delta_cents"] for row in rows) == 80100
        assert member["wallet_credit_cents"] == 80100

        funding = read_deposit(market["funding"]["id"])
        assert funding["deposit_status"] == "BANKED"
        assert funding["remaining_power"] == 107


class TestStaleDepositVersionOnExtension:
    def test_replaying_the_pre_purchase_version_buys_no_second_extension(self, api):
        """Buying three months twice is legitimate, so only the token stops a replay.

        PRD §2.9: "On mismatch the rejection is `ERR_STALE_VERSION` with HTTP 412
        and `extension_months_purchased`, `expires_at`, the member's
        `wallet_credit_cents` and the ledger are all left untouched."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_deposit_version_on_extension_returns_412
        """
        market = setup_market(member_count=1)
        member = market["members"][0]
        week = bank_deposit(member["id"], market["resort"]["id"])
        assert week["awarded_power"] == 82
        assert_instant_equals(week["expires_at"], "2029-06-14T00:00:00Z", "expires_at")
        stale_version = week["version"]

        extended = buy_extension(week["id"], member["id"], 3, stale_version)
        assert extended["extension_months_purchased"] == 3
        assert_instant_equals(
            extended["expires_at"], "2029-09-12T00:00:00Z", "expires_at"
        )
        assert extended["version"] > stale_version
        assert read_member(member["id"])["wallet_credit_cents"] == 69900, (
            "80100 less three months at 3400"
        )

        response = api.create_deposit_extension(
            week["id"],
            factories.extension_payload(3, stale_version),
            make_member_headers(member["id"]),
        )
        validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)

        untouched = read_deposit(week["id"])
        assert untouched["extension_months_purchased"] == 3
        assert_instant_equals(
            untouched["expires_at"], "2029-09-12T00:00:00Z", "expires_at"
        )
        assert read_member(member["id"])["wallet_credit_cents"] == 69900
        rows, fees = list_ledger_entries(
            member_id=member["id"], entry_type="EXTENSION_FEE"
        )
        assert fees["total_count"] == 1
        assert rows[0]["cash_delta_cents"] == -10200

    def test_the_refreshed_version_buys_the_second_three_months(self, api):
        """The identical body succeeds once the caller re-reads the version.

        PRD §3.3: "On success `extension_months_purchased` accumulates the
        purchased months and `expires_at` moves out by 30 days for each month now
        held, measured from the same `check_in_date` midnight baseline."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_deposit_version_on_extension_returns_412
        """
        market = setup_market(member_count=1)
        member = market["members"][0]
        week = bank_deposit(member["id"], market["resort"]["id"])
        stale_version = week["version"]
        buy_extension(week["id"], member["id"], 3, stale_version)
        validate_error(
            api.create_deposit_extension(
                week["id"],
                factories.extension_payload(3, stale_version),
                make_member_headers(member["id"]),
            ),
            ApiErrorId.ERR_STALE_VERSION.value,
            412,
        )

        refreshed = read_deposit(week["id"])
        again = buy_extension(week["id"], member["id"], 3, refreshed["version"])
        assert again["extension_months_purchased"] == 6
        assert_instant_equals(
            again["expires_at"], "2029-12-11T00:00:00Z", "expires_at"
        )
        assert read_member(member["id"])["wallet_credit_cents"] == 59700

        _, fees = list_ledger_entries(
            member_id=member["id"], entry_type="EXTENSION_FEE"
        )
        assert fees["total_count"] == 2, "the rejected replay left no row behind"


class TestStaleMemberVersionOnDuesPayment:
    def test_replaying_the_creation_version_does_not_double_credit_the_wallet(
        self, api
    ):
        """A replayed dues payment would be a second credit of real money.

        PRD §2.9: "On mismatch the rejection is `ERR_STALE_VERSION` with HTTP 412
        and `enrollment_status`, `dues_paid_through` and `wallet_credit_cents`
        keep their previous values with no `DUES_PAYMENT` ledger entry written."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_member_version_on_dues_payment_returns_412
        """
        market = setup_market(member_count=1)
        member = market["members"][0]
        assert member["enrollment_status"] == "ACTIVE"
        assert member["dues_paid_through"] == "2030-12-31"
        assert member["wallet_credit_cents"] == 80100, "100000 less 19900 of dues"

        stale_version = member["version"] - 1
        response = api.create_dues_payment(
            member["id"],
            factories.dues_payment_payload(
                stale_version, amount_cents=100000, paid_through_date="2031-12-31"
            ),
            make_member_headers(member["id"]),
        )
        validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)

        untouched = read_member(member["id"])
        assert untouched["enrollment_status"] == "ACTIVE"
        assert untouched["wallet_credit_cents"] == 80100
        assert untouched["dues_paid_through"] == "2030-12-31", (
            "the 2031 date was never written"
        )
        _, dues = list_ledger_entries(
            member_id=member["id"], entry_type="DUES_PAYMENT"
        )
        assert dues["total_count"] == 1

    def test_the_refreshed_version_records_the_next_years_dues(self, api):
        """Only the excess over the annual dues becomes spendable credit.

        PRD §2.5: "a `DUES_PAYMENT` ledger entry is written whose
        `cash_delta_cents` is the submitted `amount_cents` minus the tier's
        `annual_dues_cents`, so the excess over dues — and only the excess —
        becomes spendable wallet credit."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_member_version_on_dues_payment_returns_412
        """
        market = setup_market(member_count=1)
        member = market["members"][0]
        validate_error(
            api.create_dues_payment(
                member["id"],
                factories.dues_payment_payload(
                    member["version"] - 1,
                    amount_cents=100000,
                    paid_through_date="2031-12-31",
                ),
                make_member_headers(member["id"]),
            ),
            ApiErrorId.ERR_STALE_VERSION.value,
            412,
        )

        current = read_member(member["id"])
        renewed = validate_success(
            api.create_dues_payment(
                current["id"],
                factories.dues_payment_payload(
                    current["version"],
                    amount_cents=100000,
                    paid_through_date="2031-12-31",
                ),
                make_member_headers(current["id"]),
            ),
            200,
        )
        assert renewed["dues_paid_through"] == "2031-12-31"
        assert renewed["wallet_credit_cents"] == 160200, "80100 credited twice"

        rows, dues = list_ledger_entries(
            member_id=member["id"], entry_type="DUES_PAYMENT"
        )
        assert dues["total_count"] == 2
        assert [row["cash_delta_cents"] for row in rows] == [80100, 80100]
        assert sum(row["cash_delta_cents"] for row in rows) == 160200


class TestStaleResortVersionOnQualityReview:
    def test_the_version_compare_outranks_the_stay_completion_rule(self, api):
        """Priority 10 answers before priority 14, so a stale token is 412 not 409.

        PRD §2.10: "On the three operations that require an optimistic-concurrency
        token — deposit extension purchase, quality-review filing and dues-payment
        recording — the submitted `expected_deposit_version`,
        `expected_resort_version` or `expected_member_version` equals the parent
        row's current `version` — otherwise `ERR_STALE_VERSION` (412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_resort_version_on_quality_review_returns_412
        """
        scenario = setup_confirmed_exchange()
        assert scenario["confirmation"]["status"] == "CONFIRMED", (
            "the stay-completion rule would also reject this review"
        )

        stale_version = scenario["resort"]["version"]
        current = read_resort(scenario["resort"]["id"])
        assert current["version"] != stale_version, (
            "two deposits moved the resort's committed counters"
        )

        response = api.create_quality_review(
            current["id"],
            factories.quality_review_payload(
                scenario["confirmation"]["id"], stale_version
            ),
            make_member_headers(scenario["m2"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)

        _, reviews = list_quality_reviews(resort_id=current["id"])
        assert reviews["total_count"] == 0

    def test_the_current_version_falls_through_to_the_business_rule(self, api):
        """With a fresh token the same body reaches the completion check and 409s.

        PRD §2.9: "On mismatch the rejection is `ERR_STALE_VERSION` with HTTP 412,
        no review row is created, and `review_count`, `quality_score` and
        `quality_rating` keep their previous values."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_resort_version_on_quality_review_returns_412
        """
        scenario = setup_confirmed_exchange()
        current = read_resort(scenario["resort"]["id"])
        validate_error(
            api.create_quality_review(
                current["id"],
                factories.quality_review_payload(
                    scenario["confirmation"]["id"], scenario["resort"]["version"]
                ),
                make_member_headers(scenario["m2"]["id"]),
            ),
            ApiErrorId.ERR_STALE_VERSION.value,
            412,
        )

        validate_error(
            api.create_quality_review(
                current["id"],
                factories.quality_review_payload(
                    scenario["confirmation"]["id"], current["version"]
                ),
                make_member_headers(scenario["m2"]["id"]),
            ),
            ApiErrorId.ERR_STAY_NOT_COMPLETED.value,
            409,
        )

        _, reviews = list_quality_reviews(resort_id=current["id"])
        assert reviews["total_count"] == 0, "neither rejection wrote a review"
        after = read_resort(current["id"])
        assert after["review_count"] == 0
        assert after["quality_rating"] == "GOLD_CROWN"
        assert after["version"] == current["version"], (
            "a rejected write never advances the parent row"
        )


class TestRollupsReconcileWithTheLedger:
    def test_the_two_balances_equal_their_ledger_sums_after_a_refund(self, api):
        """Six rows, and both denormalised balances are recomputable from them.

        PRD §2.6: "Members hold two balances and neither is authored directly ...
        both are defined as sums over the append-only ledger"

        Design: Corner/cross_cutting_complexity_layers/member_wallet_and_power_reconcile_with_the_ledger
        """
        market = setup_market(member_count=1)
        member = market["members"][0]
        resort_id = market["resort"]["id"]

        weeks = []
        for check_in_date in ("2027-05-10", "2027-05-20"):
            week = bank_deposit(
                member["id"], resort_id,
                unit_size="TWO_BR", check_in_date=check_in_date,
            )
            assert week["awarded_power"] == 107
            weeks.append(week)
        assert read_member(member["id"])["trading_power_balance"] == 214

        requests = []
        for week in weeks:
            request = file_exchange_request(
                member["id"], resort_id, requested_unit_size="ONE_BR",
                window_start_date="2027-06-01", window_end_date="2027-06-30",
                deposit_id=week["id"],
            )
            assert request["quoted_charge_cents"] == 23060
            assert request["power_budget"] == 117
            assert request["required_power_estimate"] == 82
            requests.append(request)

        loaded = read_member(member["id"])
        assert loaded["active_request_count"] == 2
        assert loaded["wallet_credit_cents"] == 33980, "80100 less two 23060 charges"

        cancelled = cancel_request(requests[0]["id"], member["id"])
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["charge_refunded_cents"] == 23060

        settled = read_member(member["id"])
        assert settled["active_request_count"] == 1
        assert settled["wallet_credit_cents"] == 57040

        rows, meta = list_ledger_entries(member_id=member["id"])
        assert meta["total_count"] == 6
        assert sum(row["cash_delta_cents"] for row in rows) == 57040
        assert sum(row["power_delta"] for row in rows) == 214
        assert settled["trading_power_balance"] == 214, (
            "the cash operations moved no power"
        )

    def test_the_refund_is_a_new_row_and_the_counts_follow_the_statuses(self, api):
        """active_request_count tracks the live statuses rather than the call count.

        PRD §2.5: "Since `active_request_count` is defined as the count of that
        member's `SUBMITTED`, `WAITLISTED` and `MATCHED` requests"

        Design: Corner/cross_cutting_complexity_layers/member_wallet_and_power_reconcile_with_the_ledger
        """
        market = setup_market(member_count=1)
        member = market["members"][0]
        resort_id = market["resort"]["id"]

        requests = []
        for check_in_date in ("2027-05-10", "2027-05-20"):
            week = bank_deposit(
                member["id"], resort_id,
                unit_size="TWO_BR", check_in_date=check_in_date,
            )
            requests.append(
                file_exchange_request(
                    member["id"], resort_id, requested_unit_size="ONE_BR",
                    window_start_date="2027-06-01", window_end_date="2027-06-30",
                    deposit_id=week["id"],
                )
            )
        cancel_request(requests[0]["id"], member["id"])

        _, submitted = list_exchange_requests(
            member_id=member["id"], status="SUBMITTED"
        )
        assert submitted["total_count"] == 1
        _, gone = list_exchange_requests(member_id=member["id"], status="CANCELLED")
        assert gone["total_count"] == 1
        assert read_member(member["id"])["active_request_count"] == 1

        rows, refunds = list_ledger_entries(
            member_id=member["id"], entry_type="EXCHANGE_CHARGE_REFUND"
        )
        assert refunds["total_count"] == 1, (
            "the refund is a new row, not an edit of the charge row"
        )
        assert rows[0]["cash_delta_cents"] == 23060

        _, charges = list_ledger_entries(
            member_id=member["id"], entry_type="EXCHANGE_CHARGE"
        )
        assert charges["total_count"] == 2, "both charges are still on the ledger"
        assert read_exchange_request(requests[1]["id"])["status"] == "SUBMITTED"
