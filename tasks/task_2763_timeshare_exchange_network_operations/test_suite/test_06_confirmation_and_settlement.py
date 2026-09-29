"""Confirming a match: the two valuations, the debit and the reconciliation."""

from test_helpers import (
    ApiErrorId,
    OPERATOR_HEADERS,
    api_client,
    bank_deposit,
    confirm_request,
    create_active_member,
    create_tier,
    factories,
    file_exchange_request,
    list_confirmations,
    list_ledger_entries,
    make_member_headers,
    read_deposit,
    read_deposit_valuation,
    read_exchange_request,
    read_member,
    run_matching,
    set_clock,
    setup_affiliated_resort,
    validate_error,
    validate_success,
    withdraw_deposit,
)


def _diverging_settlement_market():
    """A TWO_BR week banked at demand 4, then settled at demand 2 five months on."""
    tier = create_tier()
    resort = setup_affiliated_resort()
    owner = create_active_member(tier["id"])
    seeker = create_active_member(
        tier["id"], email="m2@example.com", full_name="Priya Ravindran"
    )
    week = bank_deposit(
        owner["id"], resort["id"], unit_size="TWO_BR", check_in_date="2027-06-15"
    )
    funding = bank_deposit(
        seeker["id"], resort["id"], unit_size="THREE_BR", check_in_date="2027-05-10"
    )
    assert funding["awarded_power"] == 139

    validate_success(
        api_client.update_resort(
            resort["id"],
            factories.resort_patch_payload(demand_index=2),
            OPERATOR_HEADERS,
        )
    )
    set_clock("2027-01-15T00:00:00Z")
    request = file_exchange_request(
        seeker["id"],
        resort["id"],
        requested_unit_size="TWO_BR",
        window_start_date="2027-06-01",
        window_end_date="2027-06-30",
        deposit_id=funding["id"],
    )
    assert request["power_budget"] == 152, "floor(139 * 110 / 100)"
    assert request["required_power_estimate"] == 74, (
        "60 times 1.25 and 0.90 rounds to 68, plus 6 is 74, lead 137 factor 1.00"
    )
    return {
        "resort": resort,
        "owner": owner,
        "seeker": seeker,
        "week": week,
        "funding": funding,
        "request": request,
    }


def _same_instant_market():
    """The canonical chain with the run at the very instant the week was banked."""
    tier = create_tier()
    resort = setup_affiliated_resort()
    owner = create_active_member(tier["id"])
    seeker = create_active_member(
        tier["id"], email="m2@example.com", full_name="Priya Ravindran"
    )
    week = bank_deposit(owner["id"], resort["id"], check_in_date="2027-06-15")
    funding = bank_deposit(
        seeker["id"], resort["id"], unit_size="TWO_BR", check_in_date="2027-05-10"
    )
    request = file_exchange_request(
        seeker["id"], resort["id"], deposit_id=funding["id"]
    )
    assert request["quoted_charge_cents"] == 23060
    run_matching("settle at the banking instant")
    return {
        "owner": owner,
        "seeker": seeker,
        "week": week,
        "funding": funding,
        "request": request,
    }


class TestAwardedAndSettlementValuationsDiverge:
    def test_the_two_valuations_use_the_profile_of_their_own_instant(self, api):
        """One week carries 107 awarded and 74 at settlement.

        PRD §3.3: "The **at-settlement** variant produces `settlement_power`: its
        as-of instant is the `as_of_utc` of the matching run that reserved or
        getaway-listed the deposit, its evaluated date is again `check_in_date`,
        and it reads the resort's `demand_index` and `quality_rating` as they
        stand at that run. ... The two figures diverge whenever the resort's
        demand or quality moved between banking and settlement, or whenever the
        shrinking lead time crossed one of the four lead-factor thresholds."

        Design: Difficulty/dual_variant_calc/deposit_power_awarded_vs_settlement_divergence
        """
        market = _diverging_settlement_market()
        assert market["week"]["awarded_power"] == 107, (
            "60 times 1.25 and 1.10 rounds to 83, plus 6 is 89, lead 318 factor 1.20"
        )
        assert market["week"]["settlement_power"] is None

        run_matching("settle after the demand downgrade")

        settled = read_deposit(market["week"]["id"])
        assert settled["awarded_power"] == 107, "the awarded figure is never revalued"
        assert settled["settlement_power"] == 74, (
            "60 times 1.25 and 0.90 rounds to 68, plus 6 is 74, lead 151 factor 1.00"
        )
        assert settled["deposit_status"] == "RESERVED"

        valuation = read_deposit_valuation(market["week"]["id"])
        assert valuation["awarded_lead_time_days"] == 318
        assert valuation["settlement_lead_time_days"] == 151
        assert valuation["awarded_power"] == 107
        assert valuation["settlement_power"] == 74

    def test_the_reconciliation_lands_on_the_depositing_owner(self, api):
        """The confirmation debits 74 and posts the minus 33 delta to the owner.

        PRD §3.6: "The settlement delta is the week's `settlement_power` minus its
        `awarded_power`. When that delta is not zero, a `SETTLEMENT_ADJUSTMENT`
        ledger entry is written against the **depositing owner** — the week's
        `member_id`, never the confirming member — with a `power_delta` equal to
        the delta."

        Design: Difficulty/dual_variant_calc/deposit_power_awarded_vs_settlement_divergence
        """
        market = _diverging_settlement_market()
        run_matching("settle after the demand downgrade")

        confirmation = confirm_request(
            market["seeker"]["id"], market["request"]["id"]
        )
        assert confirmation["status"] == "CONFIRMED"
        assert confirmation["power_debited"] == 74, "the settlement figure, not 107"
        assert confirmation["awarded_deposit_id"] == market["week"]["id"]

        assert read_member(market["seeker"]["id"])["trading_power_balance"] == 65, (
            "139 credited for the THREE_BR week, 74 debited at settlement"
        )
        assert read_member(market["owner"]["id"])["trading_power_balance"] == 74, (
            "107 credited at deposit, 33 taken back by the adjustment"
        )

        owner_rows, owner_meta = list_ledger_entries(
            member_id=market["owner"]["id"], entry_type="SETTLEMENT_ADJUSTMENT"
        )
        assert owner_meta["total_count"] == 1
        assert owner_rows[0]["power_delta"] == -33
        assert owner_rows[0]["related_entity_type"] == "DEPOSIT"
        assert owner_rows[0]["related_entity_id"] == market["week"]["id"]

        _, seeker_meta = list_ledger_entries(
            member_id=market["seeker"]["id"], entry_type="SETTLEMENT_ADJUSTMENT"
        )
        assert seeker_meta["total_count"] == 0, (
            "the delta is never posted to the exchanging member"
        )


class TestZeroDeltaWritesNoAdjustment:
    def test_a_zero_delta_writes_no_settlement_row_at_all(self, api):
        """Settling at the banking instant leaves the reconciliation silent.

        PRD §3.6: "When the delta is exactly zero, no ledger row is written at
        all. The adjustment is posted exactly once, inside the confirmation,
        alongside the exchange debit; a getaway listing never posts a settlement
        adjustment."

        Design: Corner/calculations/settlement_reconciliation_writes_no_ledger_row_when_delta_is_zero
        """
        market = _same_instant_market()
        reserved = read_deposit(market["week"]["id"])
        assert reserved["awarded_power"] == 82
        assert reserved["settlement_power"] == 82, "the delta is exactly 0"

        confirmation = confirm_request(
            market["seeker"]["id"], market["request"]["id"]
        )
        assert confirmation["power_debited"] == 82
        assert confirmation["status"] == "CONFIRMED"
        assert confirmation["awarded_deposit_id"] == market["week"]["id"]
        assert confirmation["awarded_check_in_date"] == "2027-06-15"

        _, adjustments = list_ledger_entries(entry_type="SETTLEMENT_ADJUSTMENT")
        assert adjustments["total_count"] == 0, (
            "a zero delta must write nothing, not a row with power_delta 0"
        )

    def test_the_exchange_debit_is_posted_against_the_requester(self, api):
        """Only the confirming member pays; the owner's credit is untouched.

        PRD §3.6: "Two ledger entries may be written. The first is unconditional:
        an `EXCHANGE_DEBIT` taking `settlement_power` from the confirming member."

        Design: Corner/calculations/settlement_reconciliation_writes_no_ledger_row_when_delta_is_zero
        """
        market = _same_instant_market()
        confirm_request(market["seeker"]["id"], market["request"]["id"])

        rows, meta = list_ledger_entries(
            member_id=market["seeker"]["id"], entry_type="EXCHANGE_DEBIT"
        )
        assert meta["total_count"] == 1
        assert rows[0]["power_delta"] == -82

        _, owner_debits = list_ledger_entries(
            member_id=market["owner"]["id"], entry_type="EXCHANGE_DEBIT"
        )
        assert owner_debits["total_count"] == 0

        assert read_member(market["seeker"]["id"])["trading_power_balance"] == 25, (
            "107 credited for the funding week, 82 debited at settlement"
        )
        assert read_member(market["owner"]["id"])["trading_power_balance"] == 82

        used = read_deposit(market["week"]["id"])
        assert used["deposit_status"] == "USED"
        assert used["remaining_power"] == 82, (
            "the depositor's credit is untouched by the exchange"
        )


class TestConfirmationPowerGate:
    def test_a_live_balance_below_the_settlement_power_is_refused(self, api):
        """The frozen power budget does not substitute for a live balance.

        PRD §2.10: "The confirming member's `trading_power_balance` is at least
        the awarded deposit's `settlement_power` — otherwise
        `ERR_INSUFFICIENT_TRADING_POWER` (402)."

        Design: Corner/validations/confirmation_without_enough_trading_power_is_rejected
        """
        market = _same_instant_market()
        withdraw_deposit(market["funding"]["id"], market["seeker"]["id"])

        before = read_member(market["seeker"]["id"])
        assert before["trading_power_balance"] == 0
        still_matched = read_exchange_request(market["request"]["id"])
        assert still_matched["status"] == "MATCHED"
        assert still_matched["power_budget"] == 117

        response = api.create_confirmation(
            factories.confirmation_payload(market["request"]["id"]),
            make_member_headers(market["seeker"]["id"]),
        )
        validate_error(
            response, ApiErrorId.ERR_INSUFFICIENT_TRADING_POWER.value, 402
        )

    def test_the_refused_confirmation_moves_nothing(self, api):
        """No confirmation row, no advance to USED and no debit.

        PRD §3.6: "The confirming member's `trading_power_balance` must be at
        least the awarded week's `settlement_power`, or the attempt is refused
        with `ERR_INSUFFICIENT_TRADING_POWER`."

        Design: Corner/validations/confirmation_without_enough_trading_power_is_rejected
        """
        market = _same_instant_market()
        withdraw_deposit(market["funding"]["id"], market["seeker"]["id"])
        validate_error(
            api.create_confirmation(
                factories.confirmation_payload(market["request"]["id"]),
                make_member_headers(market["seeker"]["id"]),
            ),
            ApiErrorId.ERR_INSUFFICIENT_TRADING_POWER.value,
            402,
        )

        _, confirmations = list_confirmations()
        assert confirmations["total_count"] == 0
        assert read_deposit(market["week"]["id"])["deposit_status"] == "RESERVED", (
            "the held week is not advanced to USED"
        )
        after = read_member(market["seeker"]["id"])
        assert after["trading_power_balance"] == 0
        assert after["wallet_credit_cents"] == 57040
        _, debits = list_ledger_entries(
            member_id=market["seeker"]["id"], entry_type="EXCHANGE_DEBIT"
        )
        assert debits["total_count"] == 0
