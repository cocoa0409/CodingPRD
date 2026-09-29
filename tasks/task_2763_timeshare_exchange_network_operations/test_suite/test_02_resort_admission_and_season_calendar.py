"""Resort registration, the season calendar and the affiliation lifecycle."""

from test_helpers import (
    ApiErrorId,
    OPERATOR_HEADERS,
    assert_decimal_equals,
    assert_instant_equals,
    assert_resort,
    assert_season_band,
    bank_deposit,
    change_resort_status,
    create_active_member,
    create_resort,
    create_season_band,
    create_tier,
    factories,
    grant_affiliation,
    read_deposit,
    read_deposit_valuation,
    read_member,
    read_resort,
    setup_affiliated_resort,
    validate_error,
    validate_success,
)

RESORT_B = dict(factories.RESORT_B)


class TestResortRegistrationDefaults:
    def test_units_per_size_and_demand_index_take_their_defaults(self, api):
        """A resort registered without the two optional figures takes 2 and 3.

        PRD §3.1: "Two further profile figures may be supplied and otherwise
        take defaults: `units_per_size`, the aggregate nightly capacity per unit
        size — how many banked weeks of one unit size may cover the same night —
        defaults to 2 and must be at least 1; and `demand_index`, the
        operator-assigned demand rating that feeds the demand factor of every
        trading-power valuation, defaults to 3 and must be between 1 and 5
        inclusive."

        Design: Corner/entities/resort_defaults_applied_when_units_and_demand_omitted
        """
        response = api.create_resort(
            {
                "name": "Cedar Point Retreat",
                "region_code": "US-OH",
                "required_annual_deposit_units": 1,
                "initial_quality_rating": "STANDARD",
            },
            OPERATOR_HEADERS,
        )
        data = validate_success(response, 201)
        assert data["units_per_size"] == 2
        assert data["demand_index"] == 3
        assert_resort(data)

        fresh = read_resort(data["id"])
        assert fresh["affiliation_status"] == "PENDING_AFFILIATION"
        assert fresh["affiliated_on"] is None
        assert fresh["quality_score"] is None
        assert fresh["review_count"] == 0
        assert fresh["downgrade_notches"] == 0
        assert fresh["complaint_strikes"] == 0
        assert fresh["deposits_committed_count"] == 0
        assert fresh["committed_nights"] == 0

    def test_default_demand_index_prices_a_week_at_the_pivot(self, api):
        """The default demand index of 3 gives a demand factor of exactly 1.00.

        PRD §3.3: "The demand factor is one plus one tenth for each step the
        resort's `demand_index` stands above 3, and one minus one tenth for each
        step it stands below 3, so an index of 5 gives 1.20 and an index of 1
        gives 0.80."

        Design: Corner/entities/resort_defaults_applied_when_units_and_demand_omitted
        """
        tier = create_tier()
        resort = validate_success(
            api.create_resort(
                {
                    "name": "Cedar Point Retreat",
                    "region_code": "US-OH",
                    "required_annual_deposit_units": 1,
                    "initial_quality_rating": "STANDARD",
                },
                OPERATOR_HEADERS,
            ),
            201,
        )
        create_season_band(
            resort["id"],
            band_code="SILVER",
            start_month_day="01-01",
            end_month_day="12-31",
        )
        affiliated = grant_affiliation(resort["id"])
        assert affiliated["affiliation_status"] == "ACTIVE"
        assert_instant_equals(
            affiliated["affiliated_on"], "2026-08-01T00:00:00Z", "affiliated_on"
        )
        assert affiliated["quality_rating"] == "STANDARD"

        member = create_active_member(tier["id"])
        deposit = bank_deposit(
            member["id"], resort["id"], unit_size="STUDIO", check_in_date="2027-01-15"
        )
        assert deposit["awarded_power"] == 30, (
            "30 base times 1.00 season and 1.00 demand, no bonus, lead factor 1.00"
        )

        valuation = read_deposit_valuation(deposit["id"])
        assert valuation["unit_size_base"] == 30
        assert_decimal_equals(valuation["season_multiplier"], "1.00", "season_multiplier")
        assert_decimal_equals(valuation["demand_multiplier"], "1.00", "demand_multiplier")
        assert valuation["quality_bonus"] == 0


class TestSeasonBandIntervals:
    def test_adjacent_bands_on_the_closed_boundary_are_both_accepted(self, api):
        """A band starting the day after an inclusive end does not overlap it.

        PRD §3.1: "A band that shares even one calendar day with an existing
        band of the same resort is rejected with `ERR_SEASON_BAND_OVERLAP`,
        while bands that merely touch are accepted: one ending 06-30 and the
        next starting 07-01 do not conflict."

        Design: Difficulty/resource_temporal_overlap/season_band_closed_interval_overlap_rejected_adjacent_accepted
        """
        resort = create_resort(**RESORT_B)

        platinum = validate_success(
            api.create_season_band(
                factories.season_band_payload(
                    resort["id"],
                    band_code="PLATINUM",
                    start_month_day="01-01",
                    end_month_day="06-30",
                ),
                OPERATOR_HEADERS,
            ),
            201,
        )
        gold = validate_success(
            api.create_season_band(
                factories.season_band_payload(
                    resort["id"],
                    band_code="GOLD",
                    start_month_day="07-01",
                    end_month_day="12-31",
                ),
                OPERATOR_HEADERS,
            ),
            201,
        )
        assert_season_band(platinum)
        assert_season_band(gold)
        assert_decimal_equals(platinum["season_multiplier"], "1.50", "season_multiplier")
        assert_decimal_equals(gold["season_multiplier"], "1.25", "season_multiplier")

        rows, meta = validate_paginated_bands(api, resort["id"])
        assert meta["total_count"] == 2
        assert sorted(row["band_code"] for row in rows) == ["GOLD", "PLATINUM"]

    def test_band_colliding_on_a_single_day_is_rejected(self, api):
        """A band overlapping one calendar day of an existing band is refused.

        PRD §2.10: "A new season band shares no calendar day with an existing
        band of the same resort — otherwise `ERR_SEASON_BAND_OVERLAP` (409), on
        season band creation. Adjacent bands are accepted."

        Design: Difficulty/resource_temporal_overlap/season_band_closed_interval_overlap_rejected_adjacent_accepted
        """
        resort = create_resort(**RESORT_B)
        create_season_band(
            resort["id"],
            band_code="PLATINUM",
            start_month_day="01-01",
            end_month_day="06-30",
        )
        create_season_band(
            resort["id"],
            band_code="GOLD",
            start_month_day="07-01",
            end_month_day="12-31",
        )

        response = api.create_season_band(
            factories.season_band_payload(
                resort["id"],
                band_code="SILVER",
                start_month_day="06-30",
                end_month_day="08-15",
            ),
            OPERATOR_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_SEASON_BAND_OVERLAP.value, 409)

        rows, meta = validate_paginated_bands(api, resort["id"])
        assert meta["total_count"] == 2, "the rejected band was not persisted"
        assert sorted(row["band_code"] for row in rows) == ["GOLD", "PLATINUM"]

    def test_malformed_range_is_rejected_before_the_overlap_check(self, api):
        """A start sorting after the end fails the earlier date-range rule.

        PRD §2.10: "A season band's `end_month_day` does not sort before its
        `start_month_day`, comparing the two day strings as text — otherwise
        `ERR_INVALID_DATE_RANGE` (422), on season band creation."

        Design: Difficulty/resource_temporal_overlap/season_band_closed_interval_overlap_rejected_adjacent_accepted
        """
        resort = create_resort(**RESORT_B)
        create_season_band(
            resort["id"],
            band_code="PLATINUM",
            start_month_day="01-01",
            end_month_day="06-30",
        )
        create_season_band(
            resort["id"],
            band_code="GOLD",
            start_month_day="07-01",
            end_month_day="12-31",
        )

        response = api.create_season_band(
            factories.season_band_payload(
                resort["id"],
                band_code="BRONZE",
                start_month_day="09-01",
                end_month_day="08-15",
            ),
            OPERATOR_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_DATE_RANGE.value, 422)

    def test_inclusive_end_day_belongs_to_the_earlier_band(self, api):
        """A week checking in on the inclusive end resolves to the earlier band.

        PRD §3.1: "The band covers a closed interval, both endpoints included,
        interpreted without reference to any particular year, so a band running
        from 12-20 to 12-31 covers both of those days and every day between."

        Design: Difficulty/resource_temporal_overlap/season_band_closed_interval_overlap_rejected_adjacent_accepted
        """
        tier = create_tier()
        resort = create_resort(**RESORT_B)
        create_season_band(
            resort["id"],
            band_code="PLATINUM",
            start_month_day="01-01",
            end_month_day="06-30",
        )
        create_season_band(
            resort["id"],
            band_code="GOLD",
            start_month_day="07-01",
            end_month_day="12-31",
        )
        grant_affiliation(resort["id"])
        member = create_active_member(tier["id"])

        on_the_end = bank_deposit(
            member["id"], resort["id"], unit_size="ONE_BR", check_in_date="2027-06-30"
        )
        assert on_the_end["season_band_code"] == "PLATINUM"

        day_after = bank_deposit(
            member["id"], resort["id"], unit_size="TWO_BR", check_in_date="2027-07-01"
        )
        assert day_after["season_band_code"] == "GOLD"


class TestAffiliationGuards:
    def test_affiliation_without_a_season_band_is_rejected(self, api):
        """A prospect with no published calendar cannot be affiliated.

        PRD §3.1: "The grant is available only to an operator and is refused
        with `ERR_AFFILIATION_REQUIRES_SEASON_BANDS` if no season band exists
        for that resort yet."

        Design: Corner/validations/affiliation_before_any_season_band_is_rejected
        """
        resort = create_resort()

        response = api.grant_resort_affiliation(resort["id"], OPERATOR_HEADERS)
        validate_error(
            response, ApiErrorId.ERR_AFFILIATION_REQUIRES_SEASON_BANDS.value, 409
        )

        after = read_resort(resort["id"])
        assert after["affiliation_status"] == "PENDING_AFFILIATION"
        assert after["affiliated_on"] is None

        _, meta = validate_paginated_bands(api, resort["id"])
        assert meta["total_count"] == 0

    def test_affiliation_succeeds_once_a_band_exists(self, api):
        """With one band published the identical grant stamps the affiliation.

        PRD §3.1: "On success two things are stamped: `affiliated_on` is set to
        the current logical clock instant, anchoring the resort's affiliation
        year, and `quality_rating` is set to `initial_quality_rating`."

        Design: Corner/validations/affiliation_before_any_season_band_is_rejected
        """
        resort = create_resort()
        create_season_band(resort["id"])

        data = validate_success(
            api.grant_resort_affiliation(resort["id"], OPERATOR_HEADERS)
        )
        assert data["affiliation_status"] == "ACTIVE"
        assert_instant_equals(
            data["affiliated_on"], "2026-08-01T00:00:00Z", "affiliated_on"
        )
        assert data["quality_rating"] == "GOLD_CROWN"


class TestTerminatedResortLockdown:
    def test_terminated_resort_cannot_be_reactivated(self, api):
        """TERMINATED is absorbing even though SUSPENDED can return to ACTIVE.

        PRD §3.1: "From `SUSPENDED` the resort may return to `ACTIVE` or be
        moved to `TERMINATED`, which is terminal and has no outgoing
        transitions."

        Design: Corner/state_machines/terminated_resort_rejects_reactivation
        """
        resort = setup_affiliated_resort()
        suspended = change_resort_status(resort["id"], "SUSPENDED", "licence lapsed")
        assert suspended["affiliation_status"] == "SUSPENDED"
        terminated = change_resort_status(
            resort["id"], "TERMINATED", "affiliation ended"
        )
        assert terminated["affiliation_status"] == "TERMINATED"

        response = api.change_resort_status(
            resort["id"],
            factories.resort_status_change_payload(
                "ACTIVE", "operator changed their mind"
            ),
            OPERATOR_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

        after = read_resort(resort["id"])
        assert after["affiliation_status"] == "TERMINATED"
        assert_instant_equals(
            after["affiliated_on"], "2026-08-01T00:00:00Z", "affiliated_on"
        )

    def test_terminated_resort_cannot_be_put_on_probation_either(self, api):
        """No `to_status` at all is reachable out of TERMINATED.

        PRD §2.10: "The target row's current state has an outgoing transition to
        the requested state under the operation being invoked — otherwise
        `ERR_INVALID_STATE_TRANSITION` (409)."

        Design: Corner/state_machines/terminated_resort_rejects_reactivation
        """
        resort = setup_affiliated_resort()
        change_resort_status(resort["id"], "SUSPENDED", "licence lapsed")
        change_resort_status(resort["id"], "TERMINATED", "affiliation ended")

        response = api.change_resort_status(
            resort["id"],
            factories.resort_status_change_payload("PROBATION"),
            OPERATOR_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)
        assert read_resort(resort["id"])["affiliation_status"] == "TERMINATED"


class TestResortProfileEdit:
    def test_patch_touches_only_the_named_field(self, api):
        """A patch naming one figure leaves the other profile figures alone.

        PRD §3.1: "`demand_index`, `units_per_size` and
        `required_annual_deposit_units` may each be updated independently by an
        operator, and any field omitted from the update keeps its current
        value."

        Design: Corner/endpoints/resort_patch_does_not_rewrite_frozen_awarded_power
        """
        tier = create_tier()
        resort = setup_affiliated_resort()
        member = create_active_member(tier["id"])
        bank_deposit(member["id"], resort["id"], check_in_date="2027-06-15")
        before = read_resort(resort["id"])

        patched = validate_success(
            api.update_resort(
                resort["id"], factories.resort_patch_payload(demand_index=1),
                OPERATOR_HEADERS,
            )
        )
        assert patched["demand_index"] == 1
        assert patched["units_per_size"] == 2
        assert patched["required_annual_deposit_units"] == 2
        assert patched["version"] > before["version"]
        assert patched["affiliation_status"] == "ACTIVE"
        assert patched["quality_rating"] == "GOLD_CROWN"
        assert patched["deposits_committed_count"] == 1
        assert_instant_equals(
            patched["affiliated_on"], "2026-08-01T00:00:00Z", "affiliated_on"
        )

    def test_patch_does_not_rewrite_a_frozen_awarded_power(self, api):
        """A demand change reprices future weeks only, never a banked one.

        PRD §3.1: "Raising or lowering `demand_index` changes what future weeks
        are worth, but it never rewrites a week that has already been banked: an
        existing deposit's `awarded_power` was frozen at its own creation and is
        not recomputed by a profile edit."

        Design: Corner/endpoints/resort_patch_does_not_rewrite_frozen_awarded_power
        """
        tier = create_tier()
        resort = setup_affiliated_resort()
        member = create_active_member(tier["id"])
        old = bank_deposit(member["id"], resort["id"], check_in_date="2027-06-15")
        assert old["awarded_power"] == 82

        validate_success(
            api.update_resort(
                resort["id"], factories.resort_patch_payload(demand_index=1),
                OPERATOR_HEADERS,
            )
        )

        assert read_deposit(old["id"])["awarded_power"] == 82
        valuation = read_deposit_valuation(old["id"])
        assert_decimal_equals(
            valuation["demand_multiplier"], "1.10", "demand_multiplier"
        )

        new = bank_deposit(
            member["id"], resort["id"], unit_size="STUDIO", check_in_date="2027-06-20"
        )
        assert new["awarded_power"] == 43, (
            "30 times 1.25 and 0.80 rounds to 30, plus 6 is 36, times 1.20 rounds to 43"
        )
        assert read_member(member["id"])["trading_power_balance"] == 125


def validate_paginated_bands(api, resort_id):
    """Read a resort's season bands as a (rows, meta) pair."""
    response = api.list_season_bands(
        OPERATOR_HEADERS, params={"resort_id": resort_id, "limit": 100}
    )
    body = response.json()
    assert response.status_code == 200, response.text
    return body["data"], body["meta"]
