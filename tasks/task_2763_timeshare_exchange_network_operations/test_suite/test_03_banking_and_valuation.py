"""Banking a week: the valuation formula, occupancy capacity and shelf life."""

import pytest

from test_helpers import (
    ANALYST_HEADERS,
    ApiErrorId,
    OPERATOR_HEADERS,
    assert_common_fields,
    assert_decimal_equals,
    assert_deposit,
    assert_instant_equals,
    bank_deposit,
    buy_extension,
    change_resort_status,
    create_active_member,
    create_resort,
    create_season_band,
    create_tier,
    entries_of_type,
    factories,
    grant_affiliation,
    list_deposits,
    list_ledger_entries,
    list_matching_runs,
    make_member_headers,
    make_resort_manager_headers,
    read_deposit,
    read_deposit_valuation,
    read_member,
    read_resort,
    setup_affiliated_resort,
    setup_banked_week,
    validate_error,
    validate_success,
)

UNKNOWN_DEPOSIT_ID = "11111111-1111-4111-8111-111111111111"
UNKNOWN_RESORT_ID = "22222222-2222-4222-8222-222222222222"


def _platinum_market(band_start="01-01", band_end="03-31", **resort_overrides):
    """A PLUS tier, one affiliated resort with a single PLATINUM band, one member."""
    tier = create_tier()
    resort = setup_affiliated_resort(
        band_code="PLATINUM",
        band_start_month_day=band_start,
        band_end_month_day=band_end,
        **resort_overrides,
    )
    member = create_active_member(tier["id"])
    return tier, resort, member


class TestNestedRoundingOrder:
    def test_two_roundings_produce_sixty_two_not_sixty_one(self, api):
        """The worked studio example must land on 62, never on 61.

        PRD §3.3: "Consider a `STUDIO` in a `PLATINUM` band at a resort with
        `demand_index` 4 and `quality_rating` `GOLD_CROWN`, evaluated 185 days
        ahead: the first step is 30 multiplied by 1.50 and by 1.10, giving 49.5,
        which rounds half up to 50; adding the gold-crown bonus of 6 gives 56;
        multiplying by the lead factor 1.10 gives 61.6, which rounds half up to
        62; and the floor leaves it at 62."

        Design: Difficulty/combinatorial_formula/deposit_power_nested_rounding_order
        """
        _, resort, member = _platinum_market()

        deposit = validate_success(
            api.create_deposit(
                factories.deposit_payload(
                    member["id"],
                    resort["id"],
                    unit_size="STUDIO",
                    check_in_date="2027-02-02",
                ),
                make_member_headers(member["id"]),
            ),
            201,
        )
        assert deposit["awarded_power"] == 62, (
            "the single-rounding shortcut would have produced 61"
        )
        assert deposit["season_band_code"] == "PLATINUM"
        assert deposit["remaining_power"] == 62
        assert_deposit(deposit)

        assert read_member(member["id"])["trading_power_balance"] == 62

    def test_valuation_publishes_the_terms_of_the_worked_example(self, api):
        """Each factor of the worked example is readable on the valuation view.

        PRD §3.3: "First, multiply the unit-size base by the season factor and by
        the demand factor, and round that product half up to a whole number.
        Second, add the quality bonus to that already-rounded whole number; the
        intermediate result may legitimately be negative for a low-quality,
        low-demand studio in a bronze week. Third, multiply that sum by the lead
        factor and round half up to a whole number again."

        Design: Difficulty/combinatorial_formula/deposit_power_nested_rounding_order
        """
        _, resort, member = _platinum_market()
        deposit = bank_deposit(
            member["id"], resort["id"], unit_size="STUDIO", check_in_date="2027-02-02"
        )

        valuation = read_deposit_valuation(deposit["id"])
        assert valuation["unit_size_base"] == 30
        assert_decimal_equals(valuation["season_multiplier"], "1.50", "season_multiplier")
        assert_decimal_equals(valuation["demand_multiplier"], "1.10", "demand_multiplier")
        assert valuation["quality_bonus"] == 6
        assert valuation["awarded_lead_time_days"] == 185
        assert valuation["awarded_power"] == 62

        rows, meta = list_ledger_entries(
            member_id=member["id"], entry_type="DEPOSIT_CREDIT"
        )
        assert meta["total_count"] == 1
        assert rows[0]["power_delta"] == 62


class TestLeadTimeFactorBoundary:
    def test_exactly_one_hundred_eighty_days_takes_the_one_point_one_band(self, api):
        """A week exactly 180 days out wins the 1.10 lead band and scores 62.

        PRD §3.3: "The lead factor is chosen from the number of whole days
        between the evaluated date and the calendar date of the as-of instant, a
        signed figure that goes negative once the evaluated date is in the past:
        scanning four bands from the top, the first band whose threshold is at
        most that lead time wins — 1.20 at 270 days or more, 1.10 at 180 days or
        more, 1.00 at 90 days or more, and 0.85 as the catch-all for anything
        less, including negative lead times."

        Design: Difficulty/boundary_precision_check/lead_time_factor_boundary_at_exactly_180_days
        """
        _, resort, member = _platinum_market()

        deposit = bank_deposit(
            member["id"], resort["id"], unit_size="STUDIO", check_in_date="2027-01-28"
        )
        assert deposit["awarded_power"] == 62

        valuation = read_deposit_valuation(deposit["id"])
        assert valuation["awarded_lead_time_days"] == 180
        assert valuation["season_band_code"] == "PLATINUM"
        assert valuation["unit_size_base"] == 30
        assert_decimal_equals(valuation["season_multiplier"], "1.50", "season_multiplier")
        assert_decimal_equals(valuation["demand_multiplier"], "1.10", "demand_multiplier")
        assert valuation["quality_bonus"] == 6

    def test_one_hundred_seventy_nine_days_falls_to_the_one_point_zero_band(self, api):
        """One day nearer, the same week is worth 56 rather than 62.

        PRD §3.3: "The lead factor is chosen from the number of whole days
        between the evaluated date and the calendar date of the as-of instant, a
        signed figure that goes negative once the evaluated date is in the past:
        scanning four bands from the top, the first band whose threshold is at
        most that lead time wins — 1.20 at 270 days or more, 1.10 at 180 days or
        more, 1.00 at 90 days or more, and 0.85 as the catch-all for anything
        less, including negative lead times."

        Design: Difficulty/boundary_precision_check/lead_time_factor_boundary_at_exactly_180_days
        """
        _, resort, member = _platinum_market()

        at_180 = bank_deposit(
            member["id"], resort["id"], unit_size="STUDIO", check_in_date="2027-01-28"
        )
        at_179 = bank_deposit(
            member["id"], resort["id"], unit_size="STUDIO", check_in_date="2027-01-27"
        )
        assert at_180["awarded_power"] == 62
        assert at_179["awarded_power"] == 56, "the same 56 subtotal with a 1.00 factor"
        assert read_deposit_valuation(at_179["id"])["awarded_lead_time_days"] == 179

        assert read_member(member["id"])["trading_power_balance"] == 118
        resort_now = read_resort(resort["id"])
        assert resort_now["deposits_committed_count"] == 2
        assert resort_now["committed_nights"] == 16


class TestDepositBlockedByAffiliationStatus:
    def test_pending_affiliation_resort_refuses_a_deposit(self, api):
        """A prospect that has not been affiliated yet accepts no inventory.

        PRD §2.10: "The resort involved has `affiliation_status` `ACTIVE` or
        `PROBATION` — otherwise `ERR_RESORT_NOT_AFFILIATED` (409).
        `PENDING_AFFILIATION`, `SUSPENDED` and `TERMINATED` all reject."

        Design: Difficulty/cross_entity_state_dependency/deposit_create_blocked_by_resort_affiliation_status
        """
        tier = create_tier()
        resort = create_resort()
        create_season_band(resort["id"])
        member = create_active_member(tier["id"])

        response = api.create_deposit(
            factories.deposit_payload(member["id"], resort["id"]),
            make_member_headers(member["id"]),
        )
        validate_error(response, ApiErrorId.ERR_RESORT_NOT_AFFILIATED.value, 409)

        _, meta = list_deposits(resort_id=resort["id"])
        assert meta["total_count"] == 0
        assert read_member(member["id"])["trading_power_balance"] == 0

    def test_active_then_probation_both_accept_the_same_week(self, api):
        """A probated resort keeps taking deposits so it can work off its shortfall.

        PRD §3.1: "Only `ACTIVE` and `PROBATION` resorts accept new inventory."

        Design: Difficulty/cross_entity_state_dependency/deposit_create_blocked_by_resort_affiliation_status
        """
        tier = create_tier()
        resort = create_resort()
        create_season_band(resort["id"])
        member = create_active_member(tier["id"])
        grant_affiliation(resort["id"])

        while_active = bank_deposit(
            member["id"], resort["id"], check_in_date="2027-06-15"
        )
        assert while_active["awarded_power"] == 82
        assert while_active["deposit_status"] == "BANKED"

        change_resort_status(resort["id"], "PROBATION", "obligation shortfall")
        while_on_probation = bank_deposit(
            member["id"], resort["id"], check_in_date="2027-06-25"
        )
        assert while_on_probation["awarded_power"] == 82

        assert read_member(member["id"])["trading_power_balance"] == 164
        _, meta = list_deposits(resort_id=resort["id"])
        assert meta["total_count"] == 2

    def test_suspended_resort_refuses_the_same_week_again(self, api):
        """Suspension closes the resort to new inventory once more.

        PRD §3.1: "Suspension has real inventory consequences: while a resort is
        `SUSPENDED` no week may be banked against it, and the attempt is refused
        with `ERR_RESORT_NOT_AFFILIATED` — as it is for a resort still
        `PENDING_AFFILIATION` or already `TERMINATED`."

        Design: Difficulty/cross_entity_state_dependency/deposit_create_blocked_by_resort_affiliation_status
        """
        tier = create_tier()
        resort = setup_affiliated_resort()
        member = create_active_member(tier["id"])
        bank_deposit(member["id"], resort["id"], check_in_date="2027-06-15")
        change_resort_status(resort["id"], "PROBATION", "obligation shortfall")
        bank_deposit(member["id"], resort["id"], check_in_date="2027-06-25")
        change_resort_status(resort["id"], "SUSPENDED", "escalated findings")

        response = api.create_deposit(
            factories.deposit_payload(
                member["id"], resort["id"], check_in_date="2027-06-05"
            ),
            make_member_headers(member["id"]),
        )
        validate_error(response, ApiErrorId.ERR_RESORT_NOT_AFFILIATED.value, 409)

        _, meta = list_deposits(resort_id=resort["id"])
        assert meta["total_count"] == 2
        after = read_resort(resort["id"])
        assert after["affiliation_status"] == "SUSPENDED"
        assert after["deposits_committed_count"] == 2
        assert after["committed_nights"] == 16


class TestOccupancyCapacity:
    def test_week_starting_on_the_turnover_night_conflicts(self, api):
        """The eighth night is the turnover night, so night 7 is still occupied.

        PRD §2.8: "A banked week occupies seven stay nights plus one turnover
        night, and the resulting occupancy interval runs from `check_in_date`
        inclusive to `occupancy_end_date` exclusive, where `occupancy_end_date`
        is eight days after `check_in_date`."

        Design: Difficulty/resource_temporal_overlap/deposit_occupancy_halfopen_buffer_capacity_conflict
        """
        tier = create_tier()
        resort = setup_affiliated_resort(
            band_code="PLATINUM",
            band_start_month_day="01-01",
            band_end_month_day="06-30",
            **factories.RESORT_B,
        )
        member = create_active_member(tier["id"])

        first = bank_deposit(
            member["id"], resort["id"], check_in_date="2027-03-01"
        )
        assert first["awarded_power"] == 92
        assert first["occupancy_end_date"] == "2027-03-09"

        response = api.create_deposit(
            factories.deposit_payload(
                member["id"], resort["id"], check_in_date="2027-03-08"
            ),
            make_member_headers(member["id"]),
        )
        validate_error(response, ApiErrorId.ERR_UNIT_INVENTORY_CONFLICT.value, 409)

    def test_week_starting_on_the_first_free_night_is_accepted(self, api):
        """Because the interval is half-open, day eight is free.

        PRD §2.8: "Two deposits of the same resort and the same `unit_size`
        conflict when their intervals share at least one calendar day; because
        the interval is half-open, a week checking in exactly eight days after
        another does not conflict with it."

        Design: Difficulty/resource_temporal_overlap/deposit_occupancy_halfopen_buffer_capacity_conflict
        """
        tier = create_tier()
        resort = setup_affiliated_resort(
            band_code="PLATINUM",
            band_start_month_day="01-01",
            band_end_month_day="06-30",
            **factories.RESORT_B,
        )
        member = create_active_member(tier["id"])
        bank_deposit(member["id"], resort["id"], check_in_date="2027-03-01")

        second = bank_deposit(member["id"], resort["id"], check_in_date="2027-03-09")
        assert second["awarded_power"] == 92
        assert second["deposit_status"] == "BANKED"

    def test_capacity_is_scoped_per_unit_size(self, api):
        """A larger unit may start on the very date the smaller one was refused.

        PRD §2.8: "Capacity is aggregate rather than per-deposit: for any single
        day, the number of deposits of one `unit_size` whose interval covers
        that day, counting only deposits whose `deposit_status` is `BANKED`,
        `RESERVED` or `USED`, may not exceed that resort's `units_per_size`."

        Design: Difficulty/resource_temporal_overlap/deposit_occupancy_halfopen_buffer_capacity_conflict
        """
        tier = create_tier()
        resort = setup_affiliated_resort(
            band_code="PLATINUM",
            band_start_month_day="01-01",
            band_end_month_day="06-30",
            **factories.RESORT_B,
        )
        member = create_active_member(tier["id"])
        bank_deposit(member["id"], resort["id"], check_in_date="2027-03-01")
        refused = api.create_deposit(
            factories.deposit_payload(
                member["id"], resort["id"], check_in_date="2027-03-08"
            ),
            make_member_headers(member["id"]),
        )
        validate_error(refused, ApiErrorId.ERR_UNIT_INVENTORY_CONFLICT.value, 409)
        bank_deposit(member["id"], resort["id"], check_in_date="2027-03-09")

        two_br = bank_deposit(
            member["id"], resort["id"], unit_size="TWO_BR", check_in_date="2027-03-08"
        )
        assert two_br["awarded_power"] == 122

        _, meta = list_deposits(resort_id=resort["id"])
        assert meta["total_count"] == 3, "the refused attempt wrote nothing"
        assert read_member(member["id"])["trading_power_balance"] == 306
        resort_now = read_resort(resort["id"])
        assert resort_now["deposits_committed_count"] == 3
        assert resort_now["committed_nights"] == 24


class TestDepositComputedFields:
    def test_derived_fields_come_from_the_resort_and_the_clock(self, api):
        """Band, occupancy end, expiry and both power figures are all derived.

        PRD §3.3: "Its `season_band_code` is the `band_code` of the unique band
        that covers `check_in_date`. Its `occupancy_end_date` is eight days after
        `check_in_date` and is the exclusive end of the occupancy interval
        described in §2.8. Its `expires_at` is computed from `check_in_date`
        taken at midnight UTC and pushed out by the deposit lifetime of 730 days
        — two years of shelf life — plus 30 days for each extension month the
        deposit has bought, which is 0 at creation."

        Design: Corner/entities/deposit_computed_fields_derived_from_resort_and_clock
        """
        tier = create_tier()
        resort = setup_affiliated_resort()
        member = create_active_member(tier["id"])

        data = validate_success(
            api.create_deposit(
                factories.deposit_payload(member["id"], resort["id"]),
                make_member_headers(member["id"]),
            ),
            201,
        )
        assert data["season_band_code"] == "GOLD"
        assert data["occupancy_end_date"] == "2027-06-23", (
            "the exclusive end is eight days after check-in, not seven"
        )
        assert data["awarded_power"] == 82
        assert data["remaining_power"] == 82
        assert data["restoration_haircut_power"] == 0
        assert data["settlement_power"] is None, (
            "no run has reserved or listed this week yet"
        )
        assert_instant_equals(data["expires_at"], "2029-06-14T00:00:00Z", "expires_at")
        assert data["extension_months_purchased"] == 0
        assert data["deposit_status"] == "BANKED"
        assert data["rental_status"] == "NOT_LISTED"
        assert_common_fields(data, "deposit")

        resort_now = read_resort(resort["id"])
        assert resort_now["deposits_committed_count"] == 1
        assert resort_now["committed_nights"] == 8

    def test_creation_response_already_reflects_every_consequence(self, api):
        """The 201 carries its own valuation, credit and counters with no run needed.

        PRD §3.3: "The resort's `deposits_committed_count` rises by 1 and its
        `committed_nights` rises by eight nights. The owner is credited the
        deposit's `awarded_power` through a `DEPOSIT_CREDIT` ledger entry raised
        against the `DEPOSIT` family."

        Design: Corner/consistency_model/deposit_creation_response_already_reflects_the_power_credit
        """
        tier = create_tier()
        resort = setup_affiliated_resort()
        member = create_active_member(tier["id"])

        created = validate_success(
            api.create_deposit(
                factories.deposit_payload(member["id"], resort["id"]),
                make_member_headers(member["id"]),
            ),
            201,
        )
        assert created["awarded_power"] == 82
        assert created["remaining_power"] == 82
        assert created["season_band_code"] == "GOLD"
        assert created["deposit_status"] == "BANKED"
        assert created["rental_status"] == "NOT_LISTED"

        assert read_deposit(created["id"])["awarded_power"] == 82
        assert read_member(member["id"])["trading_power_balance"] == 82
        resort_now = read_resort(resort["id"])
        assert resort_now["deposits_committed_count"] == 1
        assert resort_now["committed_nights"] == 8

        rows, meta = list_ledger_entries(member_id=member["id"])
        credits = entries_of_type(rows, "DEPOSIT_CREDIT")
        assert len(credits) == 1
        assert credits[0]["power_delta"] == 82
        assert credits[0]["cash_delta_cents"] == 0
        assert credits[0]["related_entity_type"] == "DEPOSIT"
        assert credits[0]["related_entity_id"] == created["id"]

        valuation = read_deposit_valuation(created["id"])
        assert valuation["unit_size_base"] == 45
        assert valuation["quality_bonus"] == 6
        assert valuation["awarded_lead_time_days"] == 318

        _, runs_meta = list_matching_runs()
        assert runs_meta["total_count"] == 0, (
            "nothing about the deposit waited for an operations run"
        )


class TestDepositLeadWindow:
    def test_banking_fifty_nine_days_ahead_is_refused(self, api):
        """A week fewer than 60 days out is too late to bank.

        PRD §3.3: "Weeks cannot be banked at the last minute: a `check_in_date`
        fewer than 60 days after the calendar date of the current logical clock
        instant is too late to bank and is refused with
        `ERR_DEPOSIT_WINDOW_CLOSED`, while a `check_in_date` exactly 60 days out
        is accepted."

        Design: Corner/validations/deposit_within_the_sixty_day_lead_window_is_rejected
        """
        tier = create_tier()
        resort = setup_affiliated_resort(
            extra_bands=(
                {
                    "band_code": "SILVER",
                    "start_month_day": "07-01",
                    "end_month_day": "10-31",
                },
            )
        )
        member = create_active_member(tier["id"])

        response = api.create_deposit(
            factories.deposit_payload(
                member["id"],
                resort["id"],
                unit_size="STUDIO",
                check_in_date="2026-09-29",
            ),
            make_member_headers(member["id"]),
        )
        validate_error(response, ApiErrorId.ERR_DEPOSIT_WINDOW_CLOSED.value, 422)

        _, meta = list_deposits(resort_id=resort["id"])
        assert meta["total_count"] == 0
        assert read_member(member["id"])["trading_power_balance"] == 0

    def test_banking_exactly_sixty_days_ahead_is_accepted(self, api):
        """The 60-day bound is inclusive and lands in the 0.85 lead band.

        PRD §2.10: "A deposit's `check_in_date` is at least 60 days after the
        date of the current logical clock instant — otherwise
        `ERR_DEPOSIT_WINDOW_CLOSED` (422), on deposit creation."

        Design: Corner/validations/deposit_within_the_sixty_day_lead_window_is_rejected
        """
        tier = create_tier()
        resort = setup_affiliated_resort(
            extra_bands=(
                {
                    "band_code": "SILVER",
                    "start_month_day": "07-01",
                    "end_month_day": "10-31",
                },
            )
        )
        member = create_active_member(tier["id"])

        deposit = validate_success(
            api.create_deposit(
                factories.deposit_payload(
                    member["id"],
                    resort["id"],
                    unit_size="STUDIO",
                    check_in_date="2026-09-30",
                ),
                make_member_headers(member["id"]),
            ),
            201,
        )
        assert deposit["season_band_code"] == "SILVER"
        assert deposit["awarded_power"] == 33, (
            "30 times 1.00 and 1.10 is 33, plus 6 is 39, times the 0.85 catch-all"
        )
        assert_instant_equals(
            deposit["expires_at"], "2028-09-29T00:00:00Z", "expires_at"
        )
        assert read_member(member["id"])["trading_power_balance"] == 33


class TestDepositExtensionCap:
    def test_further_month_beyond_twelve_is_refused(self, api):
        """The cap is on the cumulative months already bought, not on one call.

        PRD §3.3: "The purchase is refused with `ERR_EXTENSION_CAP_EXCEEDED`
        when the deposit's existing `extension_months_purchased` plus the
        submitted `months` would exceed 12 months."

        Design: Corner/validations/extension_beyond_the_twelve_month_cap_is_rejected
        """
        scenario = setup_banked_week()
        member, deposit = scenario["member"], scenario["deposit"]

        extended = buy_extension(
            deposit["id"], member["id"], 12, deposit["version"]
        )
        assert extended["extension_months_purchased"] == 12
        assert_instant_equals(
            extended["expires_at"], "2030-06-09T00:00:00Z", "expires_at"
        )
        assert read_member(member["id"])["wallet_credit_cents"] == 39300

        current = read_deposit(deposit["id"])
        response = api.create_deposit_extension(
            deposit["id"],
            factories.extension_payload(1, current["version"]),
            make_member_headers(member["id"]),
        )
        validate_error(response, ApiErrorId.ERR_EXTENSION_CAP_EXCEEDED.value, 409)

        unchanged = read_deposit(deposit["id"])
        assert unchanged["extension_months_purchased"] == 12
        assert_instant_equals(
            unchanged["expires_at"], "2030-06-09T00:00:00Z", "expires_at"
        )
        assert read_member(member["id"])["wallet_credit_cents"] == 39300
        rows, meta = list_ledger_entries(
            member_id=member["id"], entry_type="EXTENSION_FEE"
        )
        assert meta["total_count"] == 1
        assert rows[0]["cash_delta_cents"] == -40800


class TestValuationView:
    def test_valuation_exposes_every_multiplier_and_both_lead_times(self, api):
        """The valuation view publishes each intermediate term of the formula.

        PRD §3.3: "It reports the `deposit_id`, the `season_band_code` that was
        resolved, the `unit_size_base` that was used, the `season_multiplier` and
        the `demand_multiplier` that were applied, the `quality_bonus` that was
        added, the `awarded_lead_time_days` behind the at-deposit valuation
        together with the resulting `awarded_power`, the
        `settlement_lead_time_days` behind the at-settlement valuation together
        with the resulting `settlement_power`, and the deposit's current
        `remaining_power`."

        Design: Corner/endpoints/deposit_valuation_read_exposes_every_multiplier
        """
        scenario = setup_banked_week()
        deposit = scenario["deposit"]

        response = api.get_deposit_valuation(
            deposit["id"], make_resort_manager_headers(scenario["resort"]["id"])
        )
        data = validate_success(response)
        assert response.json()["response_type"] == "object"
        assert data["deposit_id"] == deposit["id"]
        assert data["season_band_code"] == "GOLD"
        assert data["unit_size_base"] == 45
        assert_decimal_equals(data["season_multiplier"], "1.25", "season_multiplier")
        assert_decimal_equals(data["demand_multiplier"], "1.10", "demand_multiplier")
        assert data["quality_bonus"] == 6
        assert data["awarded_lead_time_days"] == 318
        assert data["awarded_power"] == 82
        assert data["settlement_lead_time_days"] is None
        assert data["settlement_power"] is None
        assert data["remaining_power"] == 82

    def test_valuation_projection_is_not_role_dependent(self, api):
        """Every role authorised to read the view sees the same projection.

        PRD §3.3: "A read-only valuation view explains a deposit's arithmetic to
        whoever asks."

        Design: Corner/endpoints/deposit_valuation_read_exposes_every_multiplier
        """
        scenario = setup_banked_week()
        deposit = scenario["deposit"]

        as_member = validate_success(
            api.get_deposit_valuation(
                deposit["id"], make_member_headers(scenario["member"]["id"])
            )
        )
        as_operator = validate_success(
            api.get_deposit_valuation(deposit["id"], OPERATOR_HEADERS)
        )
        as_analyst = validate_success(
            api.get_deposit_valuation(deposit["id"], ANALYST_HEADERS)
        )
        as_manager = validate_success(
            api.get_deposit_valuation(
                deposit["id"], make_resort_manager_headers(scenario["resort"]["id"])
            )
        )
        assert as_member == as_operator == as_analyst == as_manager


class TestDepositNotFound:
    @pytest.mark.parametrize("sub_resource", [False, True])
    def test_unknown_deposit_id_is_a_deposit_not_found(self, api, sub_resource):
        """An unknown deposit id is a 404 on the row and on its sub-resource alike.

        PRD §2.4: "Path parameters are resolved left to right, in the order the
        identifiers appear in the URL, and the first identifier that matches no
        row ends the request with that family's 404: ... `deposit_id` yields
        `ERR_DEPOSIT_NOT_FOUND`."

        Design: Corner/entities/deposit_get_by_unknown_id_returns_not_found
        """
        create_tier()

        if sub_resource:
            response = api.get_deposit_valuation(UNKNOWN_DEPOSIT_ID, OPERATOR_HEADERS)
        else:
            response = api.get_deposit(UNKNOWN_DEPOSIT_ID, OPERATOR_HEADERS)
        validate_error(response, ApiErrorId.ERR_DEPOSIT_NOT_FOUND.value, 404)

        body = response.json()
        assert body["response_type"] == "error"
        assert sorted(body["data"].keys()) == ["error_id", "message"]

        rows, meta = list_deposits()
        assert meta["total_count"] == 0
        assert meta["has_more"] is False
        assert rows == []


class TestDepositListing:
    def test_listing_carries_the_four_pagination_fields(self, api):
        """The list envelope reports limit, offset, total_count and has_more.

        PRD §2.3: "The `meta` block of every list response carries `limit` and
        `offset` as they were applied, `total_count` as the number of rows
        matching the filters before pagination, and `has_more` as a boolean that
        is true when rows remain beyond the current page."

        Design: Corner/entities/deposits_listing_returns_pagination_envelope_fields
        """
        tier = create_tier()
        resort = setup_affiliated_resort()
        member = create_active_member(tier["id"])
        for check_in in ("2027-05-10", "2027-06-15", "2027-06-25"):
            bank_deposit(member["id"], resort["id"], check_in_date=check_in)

        response = api.list_deposits(OPERATOR_HEADERS)
        rows = validate_success(response)
        meta = response.json()["meta"]
        assert response.json()["response_type"] == "array"
        assert meta["limit"] == 10, "limit defaults to 10 when omitted"
        assert meta["offset"] == 0, "offset defaults to 0 when omitted"
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert len(rows) == 3
        assert all(row["awarded_power"] == 82 for row in rows)

        assert read_member(member["id"])["trading_power_balance"] == 246
        resort_now = read_resort(resort["id"])
        assert resort_now["deposits_committed_count"] == 3
        assert resort_now["committed_nights"] == 24

    def test_total_count_describes_the_filtered_population(self, api):
        """A unit-size filter narrows total_count, and has_more follows the filtered total.

        PRD §2.3: "The `meta` block of every list response carries `limit` and
        `offset` as they were applied, `total_count` as the number of rows
        matching the filters before pagination, and `has_more` as a boolean that
        is true when rows remain beyond the current page."

        Design: Corner/cross_cutting_complexity_layers/deposits_list_filter_and_offset_interact_correctly
        """
        tier = create_tier()
        resort = setup_affiliated_resort()
        member = create_active_member(tier["id"])
        one_br_ids = [
            bank_deposit(member["id"], resort["id"], check_in_date=check_in)["id"]
            for check_in in ("2027-05-10", "2027-06-15", "2027-06-25")
        ]
        two_br = bank_deposit(
            member["id"], resort["id"], unit_size="TWO_BR", check_in_date="2027-05-10"
        )
        assert two_br["awarded_power"] == 107

        first_page, first_meta = list_deposits(unit_size="ONE_BR", limit=2, offset=0)
        assert first_meta["total_count"] == 3, "the TWO_BR week is filtered out"
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert first_meta["has_more"] is True
        assert len(first_page) == 2

        second_page, second_meta = list_deposits(unit_size="ONE_BR", limit=2, offset=1)
        assert second_meta["total_count"] == 3
        assert second_meta["offset"] == 1
        assert second_meta["has_more"] is False, (
            "offset 1 plus two rows already covers the filtered total"
        )
        assert len(second_page) == 2

        seen = {row["id"] for row in first_page} | {row["id"] for row in second_page}
        assert seen == set(one_br_ids)
        assert two_br["id"] not in seen

    def test_two_filters_narrow_the_population_together(self, api):
        """Filtering on unit size and status at once yields an empty page.

        PRD §2.3: "The `meta` block of every list response carries `limit` and
        `offset` as they were applied, `total_count` as the number of rows
        matching the filters before pagination, and `has_more` as a boolean that
        is true when rows remain beyond the current page."

        Design: Corner/cross_cutting_complexity_layers/deposits_list_filter_and_offset_interact_correctly
        """
        tier = create_tier()
        resort = setup_affiliated_resort()
        member = create_active_member(tier["id"])
        for check_in in ("2027-05-10", "2027-06-15", "2027-06-25"):
            bank_deposit(member["id"], resort["id"], check_in_date=check_in)
        bank_deposit(
            member["id"], resort["id"], unit_size="TWO_BR", check_in_date="2027-05-10"
        )

        rows, meta = list_deposits(unit_size="ONE_BR", deposit_status="RESERVED")
        assert meta["total_count"] == 0, "no deposit has been reserved"
        assert rows == []
        assert meta["has_more"] is False

        _, unfiltered = list_deposits()
        assert unfiltered["total_count"] == 4, "the filter is what narrowed the total"


class TestDepositBodyForeignKeys:
    def test_unknown_resort_in_the_body_is_a_resort_not_found(self, api):
        """A body foreign key that resolves to nothing is that family's 404.

        PRD §2.4: "Foreign keys supplied inside a request body or a query string
        are resolved the same way, in the field order declared for that
        operation's input, and raise the same family-specific 404 — a body naming
        an unknown `tier_id`, `resort_id`, `member_id`, `deposit_id`,
        `exchange_request_id` or `confirmation_id` fails with
        `ERR_TIER_NOT_FOUND`, `ERR_RESORT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`,
        `ERR_DEPOSIT_NOT_FOUND`, `ERR_EXCHANGE_REQUEST_NOT_FOUND` or
        `ERR_CONFIRMATION_NOT_FOUND` respectively."

        Design: Corner/entities/deposit_body_fk_to_unknown_resort_returns_resort_not_found
        """
        tier = create_tier()
        member = create_active_member(tier["id"])

        response = api.create_deposit(
            factories.deposit_payload(member["id"], UNKNOWN_RESORT_ID),
            make_member_headers(member["id"]),
        )
        validate_error(response, ApiErrorId.ERR_RESORT_NOT_FOUND.value, 404)

        _, meta = list_deposits()
        assert meta["total_count"] == 0
        after = read_member(member["id"])
        assert after["trading_power_balance"] == 0
        assert after["wallet_credit_cents"] == 80100
