"""Entity surface: declared fields, defaults, derivations and the 404 codes."""

import pytest

from test_helpers import (
    FINANCE_CONTROLLER,
    PRACTICE_PARTNER,
    RESOURCE_MANAGER,
    SALES_LEAD,
    ApiErrorId,
    AvailabilityStatus,
    ForecastBasis,
    PipelineStatus,
    Posture,
    ProgramStatus,
    StaffingStatus,
    assert_hiring_forecast,
    assert_meta_envelope,
    assert_practice_group,
    assert_skill,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import (
    DEFAULT_EXTERNAL_SOURCING_CAP_PCT,
    INSTANT_AUG_03,
    UNKNOWN_UUID,
)


class TestPracticeGroupSurface:
    def test_a_minimal_create_returns_every_declared_field(self, api):
        """PRD §3.1: "A freshly registered group starts empty in every derived
        respect: `total_headcount`, `bench_headcount` and `escalated_l2_count` are all
        0, `own_bench_ratio` and `rollup_bench_ratio` are both 0.0000, and `posture` is
        `OPEN`."

        Design: Corner/entities/practice_group_create_returns_201_with_every_declared_field
        """
        response = api.create_practice_group(
            factories.practice_group_payload(name="Cloud NA", geography_code="NA"),
            PRACTICE_PARTNER,
        )
        group = validate_success(response, 201)

        body = response.json()
        assert body["response_type"] == "object"
        assert_meta_envelope(body)

        assert_practice_group(group)
        assert group["name"] == "Cloud NA"
        assert group["geography_code"] == "NA"
        assert group["parent_group_id"] is None
        assert group["level_targets"] == {}
        assert group["external_sourcing_cap_pct"] == pytest.approx(
            DEFAULT_EXTERNAL_SOURCING_CAP_PCT, abs=0.005
        )

        assert group["total_headcount"] == 0
        assert group["bench_headcount"] == 0
        assert group["escalated_l2_count"] == 0
        # The zero-denominator case reports 0.0000 rather than failing.
        assert group["own_bench_ratio"] == pytest.approx(0.0000, abs=0.00005)
        assert group["rollup_bench_ratio"] == pytest.approx(0.0000, abs=0.00005)
        assert group["posture"] == Posture.OPEN
        assert group["version"] == 1

    def test_a_read_returns_the_stored_row_without_bumping_the_version(self, api):
        """PRD §2.4: "The `version` property is an integer that starts at 1 on
        creation and increments by one on every mutation of the row; it is the value
        optimistic concurrency control is quoted against (§2.8)."

        Design: Corner/entities/practice_group_get_by_id_returns_the_stored_row
        """
        created = fixtures.create_group(
            api,
            name="Cloud EMEA",
            geography_code="EMEA",
            external_sourcing_cap_pct=45.00,
        )

        # A different authorised role reads it; a GET is not a mutation.
        stored = fixtures.read_group(api, created["id"], RESOURCE_MANAGER)

        assert stored["id"] == created["id"]
        assert stored["name"] == "Cloud EMEA"
        assert stored["geography_code"] == "EMEA"
        assert stored["external_sourcing_cap_pct"] == pytest.approx(45.00, abs=0.005)
        assert stored["version"] == 1
        assert stored["posture"] == Posture.OPEN
        assert stored["total_headcount"] == 0
        assert stored["created_at"] == created["created_at"]
        assert stored["updated_at"] == created["updated_at"]

    def test_the_parent_link_reads_back_from_both_directions(self, api):
        """PRD §3.1: "Groups can be listed filtered by `geography_code`, by
        `parent_group_id` — which doubles as the reverse-reachability filter for the
        self-referential parent link — and by `posture`, and a group's direct children
        can be listed as a nested read under that group."

        Design: Corner/entities/self_referential_parent_link_is_readable_from_both_directions
        """
        parent = fixtures.create_group(api, name="Cloud NA", geography_code="NA")
        child = fixtures.create_group(
            api,
            name="Cloud NA East",
            geography_code="NA",
            parent_group_id=parent["id"],
        )

        nested, nested_meta = validate_paginated(
            api.list_child_groups(parent["id"], RESOURCE_MANAGER)
        )
        assert nested_meta["total_count"] == 1
        assert nested[0]["id"] == child["id"]
        assert nested[0]["parent_group_id"] == parent["id"]

        filtered, filtered_meta = validate_paginated(
            api.list_practice_groups(RESOURCE_MANAGER, {"parent_group_id": parent["id"]})
        )
        assert filtered_meta["total_count"] == 1
        assert filtered[0]["id"] == child["id"]

        # Adding a child rewrites only the parent's derived rollup terms.
        stored_parent = fixtures.read_group(api, parent["id"])
        assert stored_parent["parent_group_id"] is None
        assert stored_parent["rollup_bench_ratio"] == pytest.approx(0.0000, abs=0.00005)
        assert stored_parent["own_bench_ratio"] == pytest.approx(0.0000, abs=0.00005)
        assert stored_parent["total_headcount"] == 0

        _, leaf_meta = validate_paginated(
            api.list_child_groups(child["id"], RESOURCE_MANAGER)
        )
        assert leaf_meta["total_count"] == 0


class TestSkillSurface:
    def test_a_two_row_page_reports_the_whole_filtered_set(self, api):
        """PRD §2.3: "List responses populate `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope, where `total_count` is the
        number of rows matching the filters before pagination is applied and `has_more`
        indicates whether any matching row remains beyond the current window."

        Design: Corner/entities/skills_list_reports_total_count_and_has_more_across_pages
        """
        fixtures.create_skill(api, code="CLOUD_ARCH", name="Cloud Architecture", family="CLOUD")
        fixtures.create_skill(api, code="DATA_ENG", name="Data Engineering", family="DATA")
        fixtures.create_skill(
            api, code="MAINFRAME", name="Mainframe Ops", family="CLOUD", retired=True
        )

        first_response = api.list_skills(RESOURCE_MANAGER, {"limit": 2, "offset": 0})
        assert first_response.json()["response_type"] == "array"
        page_one, meta_one = validate_paginated(first_response)
        assert len(page_one) == 2
        assert meta_one["limit"] == 2
        assert meta_one["offset"] == 0
        assert meta_one["total_count"] == 3
        assert meta_one["has_more"] is True

        page_two, meta_two = validate_paginated(
            api.list_skills(RESOURCE_MANAGER, {"limit": 2, "offset": 2})
        )
        assert len(page_two) == 1
        assert meta_two["offset"] == 2
        assert meta_two["total_count"] == 3
        assert meta_two["has_more"] is False

        # The window moved; the rows did not repeat.
        assert {row["id"] for row in page_one}.isdisjoint({row["id"] for row in page_two})

        retired, retired_meta = validate_paginated(
            api.list_skills(RESOURCE_MANAGER, {"retired": "true"})
        )
        assert retired_meta["total_count"] == 1
        assert len(retired) == 1
        assert retired[0]["code"] == "MAINFRAME"
        assert retired[0]["retired"] is True

    def test_the_server_mints_the_system_fields_and_bumps_version_per_mutation(self, api):
        """PRD §2.4: "The `id` is a server-minted UUID string with no type prefix of
        any kind."

        Design: Corner/entities/system_fields_are_server_minted_and_version_bumps_per_mutation
        """
        created = fixtures.create_skill(
            api, code="CLOUD_ARCH", name="Cloud Architecture", family="CLOUD"
        )
        assert_skill(created)
        assert created["version"] == 1
        assert created["updated_at"] == created["created_at"]

        # Move the clock forward so the refreshed stamp is observably later under
        # either clock reading.
        fixtures.set_clock(api, INSTANT_AUG_03)

        patched = validate_success(
            api.patch_skill(created["id"], {"scarcity_index": 0.8000}, PRACTICE_PARTNER)
        )

        assert patched["version"] == 2
        assert patched["id"] == created["id"]
        assert patched["created_at"] == created["created_at"]
        assert patched["updated_at"] > created["created_at"]
        assert patched["scarcity_index"] == pytest.approx(0.8000, abs=0.00005)
        # The untouched optional field keeps its stored value.
        assert patched["retired"] is False
        assert patched["code"] == "CLOUD_ARCH"
        assert patched["family"] == "CLOUD"

    def test_omitting_the_optional_tokens_lands_on_the_declared_defaults(self, api):
        """PRD §3.2: "Four further inputs are optional: `travel_max_nights_per_week`, an
        integer from 0 to 5 defaulting to 3; `travel_willing_international`, a boolean
        defaulting to false; `development_goal_skill_id`, the `id` of the skill this
        person is deliberately developing, defaulting to absent; and
        `industry_experience`, an array of objects each carrying an `industry_code`
        string and a `years` number between 0.0 and 40.0, defaulting to an empty array."

        Design: Corner/entities/omitted_optional_inputs_apply_the_declared_defaults
        """
        group = fixtures.create_group(api, name="Cloud NA", geography_code="NA")

        skill = fixtures.create_skill(
            api, code="CLOUD_ARCH", name="Cloud Architecture", family="CLOUD"
        )
        consultant = fixtures.create_consultant(
            api,
            group["id"],
            full_name="Ada Byron",
            email="ada.byron@firm.test",
            level="CONSULTANT",
            home_city="Boston",
            home_geo_code="NA",
            cost_rate_usd_per_hour=120.00,
            standard_bill_rate_usd_per_hour=300.00,
        )
        firm = fixtures.create_firm(
            api,
            name="NorthStar Partners",
            geo_code="NA",
            max_concurrent_placements=2,
            pass_through_rate_usd_per_hour=150.00,
        )
        program = fixtures.create_program(
            api,
            skill["id"],
            target_proficiency_level=4,
            cohort_start_on="2026-09-01",
            cohort_end_on="2026-09-30",
            seat_capacity=2,
        )

        assert skill["scarcity_index"] == pytest.approx(0.5000, abs=0.00005)
        assert skill["retired"] is False

        assert consultant["travel_max_nights_per_week"] == 3
        assert consultant["travel_willing_international"] is False
        assert consultant["development_goal_skill_id"] is None
        assert consultant["industry_experience"] == []
        assert consultant["availability_status"] == AvailabilityStatus.BENCH
        assert consultant["allocated_pct"] == pytest.approx(0.00, abs=0.005)
        assert consultant["separated_on"] is None

        assert firm["markup_pct"] == pytest.approx(15.00, abs=0.005)
        assert firm["approval_status"] == "APPROVED"
        assert firm["active_placements_count"] == 0

        assert program["cooldown_days"] == 3
        assert program["seats_taken"] == 0
        assert program["status"] == ProgramStatus.PLANNED

        after = fixtures.read_group(api, group["id"])
        assert after["external_sourcing_cap_pct"] == pytest.approx(20.00, abs=0.005)
        assert after["total_headcount"] == 1

    def test_a_create_derives_every_computed_field_from_its_inputs(self, api):
        """PRD §3.7: "The rate that governs a demand is its
        `effective_rate_usd_per_hour`: the `approved_rate_usd_per_hour` when a discount
        has been approved, and the `requested_rate_usd_per_hour` otherwise."

        Design: Corner/entities/demand_create_derives_every_computed_field_from_the_inputs
        """
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)

        demand = fixtures.create_demand(
            api,
            world["group"]["id"],
            world["skill"]["id"],
            client_name="Acme Retail",
            min_proficiency_level=3,
            required_fte=2.00,
            win_probability_pct=65,
            start_date="2026-08-03",
            end_date="2026-08-28",
            industry_code="RETAIL",
            onsite_nights_per_week=2,
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=240.00,
        )

        # 2.00 * 65 / 100 = 1.30, and 100 * 240.00 / 250.00 = 96.00.
        assert demand["weighted_fte"] == pytest.approx(1.30, abs=0.005)
        assert demand["approved_rate_usd_per_hour"] is None
        assert demand["effective_rate_usd_per_hour"] == pytest.approx(240.00, abs=0.005)
        assert demand["booked_realization_pct"] == pytest.approx(96.00, abs=0.005)

        # Nothing has been staffed and nothing delivered.
        assert demand["earned_realization_pct"] is None
        assert demand["blended_margin_pct"] is None
        assert demand["blended_cost_rate_usd_per_hour"] == pytest.approx(0.00, abs=0.005)
        assert demand["margin_breach"] is False

        assert demand["covered_internal_fte"] == pytest.approx(0.00, abs=0.005)
        assert demand["covered_external_fte"] == pytest.approx(0.00, abs=0.005)
        assert demand["open_fte"] == pytest.approx(2.00, abs=0.005)

        assert demand["pipeline_status"] == PipelineStatus.QUALIFYING
        assert demand["staffing_status"] == StaffingStatus.UNSTAFFED
        assert demand["staffing_mode"] is None
        assert demand["closed_outcome"] is None
        assert demand["is_international"] is False


class TestNotFoundAndShapeGates:
    def test_a_well_formed_but_unused_uuid_is_a_consultant_not_found(self, api):
        """PRD §2.7: "Path identifiers are resolved **left to right**, and the first
        segment that names no existing row decides the error."

        Design: Corner/entities/consultant_get_with_unknown_uuid_returns_consultant_not_found
        """
        response = api.get_consultant(UNKNOWN_UUID, RESOURCE_MANAGER)

        error = validate_error(response, ApiErrorId.ERR_CONSULTANT_NOT_FOUND, 404)
        body = response.json()
        assert body["response_type"] == "error"
        assert isinstance(error["message"], str)
        assert error["message"] != ""
        # An error envelope carries only error_id and message.
        assert "id" not in error

    def test_an_omitted_required_field_is_a_malformed_request(self, api):
        """PRD §2.9: "3. **Request shape** — unknown body keys rejected; required
        fields present; types, enum members, numeric ranges and decimal widths exactly
        as this document declares them; ISO 8601 dates and instants well formed;
        intra-payload ordering satisfied (an assignment's `end_date` strictly after its
        `start_date`; a demand's `end_date` on or after its `start_date`;
        `cohort_end_on` on or after `cohort_start_on`; `period_end_on` on or after
        `period_start_on`; `horizon_end_on` on or after `horizon_start_on`); and
        pagination `limit` within 1 through 100 with `offset` at least 0. Applies to
        every endpoint. Failure: `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/skill_create_missing_required_family_returns_invalid_request
        """
        # `family` has no declared default, so its absence is a shape failure.
        response = api.create_skill(
            {"code": "CLOUD_ARCH", "name": "Cloud Architecture"}, PRACTICE_PARTNER
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

        _, meta = validate_paginated(api.list_skills(RESOURCE_MANAGER))
        assert meta["total_count"] == 0, "the rejected create persisted nothing"

    def test_four_shape_violations_all_answer_from_the_same_rung(self, api):
        """PRD §2.9: "When a single request violates several rules, exactly one error is
        returned and **no mutation of any kind occurs**."

        Design: Corner/entities/type_and_range_violations_are_rejected_before_any_business_rule
        """
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        group_id = world["group"]["id"]
        skill_id = world["skill"]["id"]

        # QUANTUM is not a member of the declared family enum.
        validate_error(
            api.create_skill(
                {"code": "QUANTUM_ML", "name": "Quantum ML", "family": "QUANTUM"},
                PRACTICE_PARTNER,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )

        # Unknown body keys are rejected, not ignored.
        validate_error(
            api.create_skill(
                {
                    "code": "GRAPH_DB",
                    "name": "Graph Databases",
                    "family": "DATA",
                    "unexpected_key": 1,
                },
                PRACTICE_PARTNER,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )

        # required_fte 0.10 sits below the declared 0.25 minimum.
        validate_error(
            api.create_demand(
                factories.demand_payload(
                    group_id,
                    skill_id,
                    required_fte=0.10,
                    win_probability_pct=60,
                    start_date="2026-08-03",
                    end_date="2026-08-28",
                ),
                SALES_LEAD,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )

        # A demand's end_date must be on or after its start_date.
        validate_error(
            api.create_demand(
                factories.demand_payload(
                    group_id,
                    skill_id,
                    required_fte=1.00,
                    win_probability_pct=60,
                    start_date="2026-08-28",
                    end_date="2026-08-03",
                ),
                SALES_LEAD,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )

        _, skill_meta = validate_paginated(api.list_skills(RESOURCE_MANAGER))
        assert skill_meta["total_count"] == 1, "only the setup skill survives"
        _, demand_meta = validate_paginated(api.list_demands(SALES_LEAD))
        assert demand_meta["total_count"] == 0

    def test_a_body_foreign_key_that_resolves_to_nothing_wins_over_the_geography_rule(
        self, api
    ):
        """PRD §2.9: "5. **Body foreign-key existence** — every foreign key supplied in
        the body resolves, checked in field-declaration order as described in §2.7.
        Applies to consultant creation, skill-assertion creation, demand creation,
        assignment proposal, reskilling-programme creation, cohort enrolment,
        external-placement request, discount-approval creation, consultant update and
        practice-group update. Failure: the relevant 404 code."

        Design: Corner/entities/consultant_create_with_unknown_practice_group_returns_group_not_found
        """
        response = api.create_consultant(
            factories.consultant_payload(
                UNKNOWN_UUID,
                full_name="Ada Byron",
                email="ada.byron@firm.test",
                level="CONSULTANT",
                home_city="Boston",
                # EMEA would also have broken rung 35 once a group existed.
                home_geo_code="EMEA",
                cost_rate_usd_per_hour=120.00,
                standard_bill_rate_usd_per_hour=300.00,
            ),
            RESOURCE_MANAGER,
        )

        error = validate_error(response, ApiErrorId.ERR_PRACTICE_GROUP_NOT_FOUND, 404)
        assert error["error_id"] != ApiErrorId.ERR_GEOGRAPHY_MISMATCH

        _, meta = validate_paginated(api.list_consultants(RESOURCE_MANAGER))
        assert meta["total_count"] == 0


class TestHiringForecastSnapshot:
    def test_the_snapshot_carries_no_version_and_never_moves_again(self, api):
        """PRD §2.4: "The hiring forecast is the sole exception: it is an immutable
        snapshot, so a forecast row carries only `id` and `created_at` — it has no
        `updated_at` property and no `version` property at all, and there is no
        operation anywhere in the API that modifies one after creation."

        Design: Corner/entities/hiring_forecast_is_an_immutable_snapshot_with_no_version_field
        """
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)

        forecast = fixtures.create_forecast(
            api,
            skill_code="CLOUD_ARCH",
            geography_code="NA",
            horizon_start_on="2026-08-01",
            horizon_end_on="2026-09-30",
        )
        assert_hiring_forecast(forecast)
        assert forecast["basis"] == ForecastBasis.WEIGHTED
        # Nothing exists to count yet.
        assert forecast["weighted_demand_fte"] == pytest.approx(0.00, abs=0.005)
        assert forecast["internal_supply_fte"] == pytest.approx(0.00, abs=0.005)
        assert forecast["external_supply_fte"] == pytest.approx(0.00, abs=0.005)
        assert forecast["gap_fte"] == pytest.approx(0.00, abs=0.005)
        assert forecast["recommended_hires"] == 0

        demand = fixtures.create_demand(
            api,
            world["group"]["id"],
            world["skill"]["id"],
            client_name="Acme Retail",
            required_fte=2.00,
            win_probability_pct=80,
            start_date="2026-08-03",
            end_date="2026-08-28",
        )
        qualified = fixtures.qualify(api, demand["id"])
        # In scope for CLOUD_ARCH / NA over 2026-08-01..2026-09-30, had the
        # forecast been generated afterwards.
        assert qualified["pipeline_status"] == PipelineStatus.QUALIFIED
        assert qualified["weighted_fte"] == pytest.approx(1.60, abs=0.005)

        again = fixtures.read_forecast(api, forecast["id"], FINANCE_CONTROLLER)
        assert again["id"] == forecast["id"]
        assert again["weighted_demand_fte"] == pytest.approx(0.00, abs=0.005)
        assert again["gap_fte"] == pytest.approx(0.00, abs=0.005)
        assert again["recommended_hires"] == 0
        assert again["generated_at"] == forecast["generated_at"]
        assert "version" not in again
        assert "updated_at" not in again
