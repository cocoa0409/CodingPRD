"""The declared precedence order, tested where two rules fire on one call."""

from test_helpers import (
    ApiErrorId,
    OPERATOR_HEADERS,
    change_resort_status,
    create_active_member,
    create_tier,
    factories,
    list_deposits,
    list_exchange_requests,
    list_page,
    make_member_headers,
    read_member,
    read_resort,
    run_matching,
    set_clock,
    setup_affiliated_resort,
    validate_error,
    validate_success,
)

LATE_GOLD_WINDOW = {
    "window_start_date": "2027-06-30",
    "window_end_date": "2027-06-30",
}


def _lapsed_broke_member():
    """A member swept to LAPSED by a run whose wallet is also exactly empty."""
    tier = create_tier()
    resort = setup_affiliated_resort()
    member = create_active_member(
        tier["id"],
        email="m2@example.com",
        full_name="Ravi Bergqvist",
        amount_cents=19900,
        paid_through_date="2026-08-31",
    )
    assert member["enrollment_status"] == "ACTIVE"
    assert member["wallet_credit_cents"] == 0, "the payment exactly covered the dues"

    set_clock("2026-10-01T00:00:00Z")
    run = run_matching("dues sweep")
    return {"tier": tier, "resort": resort, "member": member, "run": run}


def _request_payload(market):
    """A REQUEST_FIRST filing with no funding deposit, so the whole estimate is charged."""
    return factories.exchange_request_payload(
        market["member"]["id"], market["resort"]["id"], **LATE_GOLD_WINDOW
    )


def _suspended_resort_without_a_january_band():
    """Resort A suspended, and its only band covers 04-01..06-30."""
    tier = create_tier()
    resort = setup_affiliated_resort()
    member = create_active_member(tier["id"])
    suspended = change_resort_status(resort["id"], "SUSPENDED", "audit in progress")
    assert suspended["affiliation_status"] == "SUSPENDED"
    return {"tier": tier, "resort": resort, "member": member}


def _january_deposit_payload(market):
    """A ONE_BR week checking in on a date no season band of the resort covers."""
    return factories.deposit_payload(
        market["member"]["id"],
        market["resort"]["id"],
        unit_size="ONE_BR",
        check_in_date="2027-01-20",
    )


class TestLapsedStateOutranksWallet:
    def test_the_lapsed_member_with_an_empty_wallet_is_refused_on_state(self, api):
        """Both rules fire; the state category answers and the fiscal one is silent.

        PRD §2.10: "A lapsed member who submits an exchange request with an empty
        wallet violates both the enrollment-state rule at position 12 and the
        wallet-sufficiency rule at position 32; the response is
        `ERR_MEMBER_NOT_ACTIVE` with HTTP 409, never
        `ERR_INSUFFICIENT_WALLET_CREDIT`."

        Design: Difficulty/priority_pair_validation_conflict/lapsed_member_state_beats_wallet_fiscal_on_exchange_request
        """
        market = _lapsed_broke_member()
        assert market["run"]["lapsed_member_count"] == 1

        lapsed = read_member(market["member"]["id"])
        assert lapsed["enrollment_status"] == "LAPSED"
        assert lapsed["wallet_credit_cents"] == 0, (
            "nothing to pay a 55000-cent charge with, so rule 32 is violated too"
        )
        assert lapsed["dues_paid_through"] == "2026-08-31"

        response = api.create_exchange_request(
            _request_payload(market), make_member_headers(market["member"]["id"])
        )
        validate_error(response, ApiErrorId.ERR_MEMBER_NOT_ACTIVE.value, 409)

        _, requests = list_exchange_requests(member_id=market["member"]["id"])
        assert requests["total_count"] == 0, "the rejected call wrote nothing"
        after = read_member(market["member"]["id"])
        assert after["active_request_count"] == 0
        assert after["wallet_credit_cents"] == 0, "no partial debit"

    def test_reinstating_the_member_exposes_the_wallet_rule_underneath(self, api):
        """The fiscal rule was live all along and merely outranked.

        PRD §2.10: "The paying member's `wallet_credit_cents` is at least the
        amount about to be debited — otherwise `ERR_INSUFFICIENT_WALLET_CREDIT`
        (402). This guards five operations, each with its own amount:
        `quoted_charge_cents` on exchange request creation"

        Design: Difficulty/priority_pair_validation_conflict/lapsed_member_state_beats_wallet_fiscal_on_exchange_request
        """
        market = _lapsed_broke_member()
        validate_error(
            api.create_exchange_request(
                _request_payload(market),
                make_member_headers(market["member"]["id"]),
            ),
            ApiErrorId.ERR_MEMBER_NOT_ACTIVE.value,
            409,
        )

        lapsed = read_member(market["member"]["id"])
        reinstated = validate_success(
            api.create_dues_payment(
                lapsed["id"],
                factories.dues_payment_payload(
                    lapsed["version"],
                    amount_cents=19900,
                    paid_through_date="2030-12-31",
                ),
                make_member_headers(lapsed["id"]),
            ),
            200,
        )
        assert reinstated["enrollment_status"] == "ACTIVE"
        assert reinstated["wallet_credit_cents"] == 0, (
            "the reinstating payment left no excess to spend"
        )

        response = api.create_exchange_request(
            _request_payload(market), make_member_headers(market["member"]["id"])
        )
        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_WALLET_CREDIT.value, 402)

        _, requests = list_exchange_requests(member_id=market["member"]["id"])
        assert requests["total_count"] == 0, (
            "the charge is refused before anything is written"
        )
        assert read_member(market["member"]["id"])["active_request_count"] == 0


class TestResortSafetyOutranksSeasonBand:
    def test_the_suspended_resort_answers_before_the_missing_band(self, api):
        """Resolving the band is the natural first step, but rule 15 comes first.

        PRD §2.10: "A deposit filed against a suspended resort for a date no
        season band covers violates both the affiliation rule at position 15 and
        the season-band rule at position 21; the response is
        `ERR_RESORT_NOT_AFFILIATED` with HTTP 409, never
        `ERR_NO_SEASON_BAND_FOR_DATE`."

        Design: Difficulty/priority_pair_validation_conflict/suspended_resort_safety_beats_missing_season_band_referential_on_deposit
        """
        market = _suspended_resort_without_a_january_band()

        response = api.create_deposit(
            _january_deposit_payload(market),
            make_member_headers(market["member"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_RESORT_NOT_AFFILIATED.value, 409)

        _, deposits = list_deposits(resort_id=market["resort"]["id"])
        assert deposits["total_count"] == 0
        assert read_member(market["member"]["id"])["trading_power_balance"] == 0, (
            "no week was valued, so no power was credited"
        )

    def test_reactivating_the_resort_exposes_the_season_band_rule(self, api):
        """With the safety rule satisfied the identical call falls through to 422.

        PRD §2.10: "The evaluated date falls inside exactly one season band of the
        relevant resort, matched on month and day — otherwise
        `ERR_NO_SEASON_BAND_FOR_DATE` (422)."

        Design: Difficulty/priority_pair_validation_conflict/suspended_resort_safety_beats_missing_season_band_referential_on_deposit
        """
        market = _suspended_resort_without_a_january_band()
        validate_error(
            api.create_deposit(
                _january_deposit_payload(market),
                make_member_headers(market["member"]["id"]),
            ),
            ApiErrorId.ERR_RESORT_NOT_AFFILIATED.value,
            409,
        )

        revived = change_resort_status(market["resort"]["id"], "ACTIVE", "audit cleared")
        assert revived["affiliation_status"] == "ACTIVE"

        response = api.create_deposit(
            _january_deposit_payload(market),
            make_member_headers(market["member"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_NO_SEASON_BAND_FOR_DATE.value, 422)

        _, deposits = list_deposits(resort_id=market["resort"]["id"])
        assert deposits["total_count"] == 0, "the second refusal wrote nothing either"

        resort = read_resort(market["resort"]["id"])
        assert resort["affiliation_status"] == "ACTIVE"
        assert resort["deposits_committed_count"] == 0
        assert resort["committed_nights"] == 0


class TestMalformedCreateBodies:
    def test_three_different_shape_failures_share_one_error_id(self, api):
        """A missing field, an out-of-range integer and a bad enum are all 400.

        PRD §2.10: "Body and query shapes are satisfied, on every endpoint:
        required fields present, enum fields inside their declared value sets,
        integers inside their declared ranges ... otherwise `ERR_INVALID_REQUEST`
        (400)."

        Design: Corner/entities/create_calls_with_malformed_bodies_return_invalid_request
        """
        tier = create_tier()

        without_tier = factories.member_payload(tier["id"])
        without_tier.pop("tier_id")
        validate_error(
            api.create_member(without_tier, OPERATOR_HEADERS),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

        validate_error(
            api.create_resort(
                factories.resort_payload(demand_index=7), OPERATOR_HEADERS
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

        validate_error(
            api.create_resort(
                factories.resort_payload(initial_quality_rating="DIAMOND_CROWN"),
                OPERATOR_HEADERS,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

        _, members = list_page(api.list_members(OPERATOR_HEADERS))
        assert members["total_count"] == 0
        _, resorts = list_page(api.list_resorts(OPERATOR_HEADERS))
        assert resorts["total_count"] == 0
