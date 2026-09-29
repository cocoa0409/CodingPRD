"""Platform-wide contract: envelope, defaults, request shape, 404 vocabulary,
RBAC, optimistic concurrency and list windowing.

Every test in this module translates exactly one instance from
SCAFFOLD_CORNER_DESIGN.yaml (§1.9) - the `entities`, `errors`, `rbac`,
`complexity_layers` and `validations` sections that carry the platform claims.
"""

import pytest

from test_helpers import (
    ADMIN,
    LOGISTICS,
    NON_EXISTENT_UUID,
    PLANNER,
    QUALITY,
    add_analysis,
    assert_immutable_config_shape,
    assert_kit_lines_in_component_order,
    assert_no_such_field,
    assert_version_advanced_by,
    assign_crew_payload,
    create_bin_design_payload,
    create_coating_spec_payload,
    create_dealer_order_payload,
    create_dealer_payload,
    create_design,
    create_design_analysis_payload,
    create_design_under_review,
    create_field_failure_payload,
    create_freight_load_payload,
    credit_limit_payload,
    create_jurisdiction_payload,
    create_roll_forming_line_payload,
    create_roll_forming_run_payload,
    engineer_headers,
    headers_for_role,
    headers_without_role,
    headers_without_user_id,
    make_dealer_principal_headers,
    make_design_engineer_headers,
    make_sealing_engineer_headers,
    order_payment_payload,
    place_order,
    plan_freight_load,
    read_dealer,
    read_design,
    receive_coil_lot,
    register_coating_spec,
    register_crew,
    seal_design,
    set_clock_payload,
    setup_design_listing_set,
    setup_reference_data,
    submit_for_review,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestConfigurationEnvelopeAndReadBack:
    def test_a_jurisdiction_create_is_wrapped_stored_and_listed_in_created_at_order(
        self, api
    ):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request
        that starts with `req_`."
        PRD §2.5: "Every stored row carries a server-minted `id` that is a UUID string with no type
        prefix and no embedded semantics; clients never supply it."
        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and `has_more` in
        `meta`, where `total_count` is the number of rows matching the filter before the page window is
        applied, and `has_more` is true exactly when rows remain beyond the current window."
        PRD §2.3: "Unless a specific endpoint states otherwise, list results are ordered by
        `created_at` ascending."
        PRD §3.1: "A permitting authority is registered with a `code` that must be unique across all
        jurisdictions and between 3 and 16 characters long, a human-readable `name`, a `seal_required`
        flag, a `min_design_wind_speed_mph` between 80 and 200 inclusive, a `seismic_design_category`
        that is one of `A`, `B`, `C` or `D`, and a `permit_review_days` count between 0 and 90 inclusive
        expressed in whole days."

        Design: Corner/entities/jurisdiction_create_returns_the_success_envelope_and_is_readable_back
        """
        created = api.create_jurisdiction(create_jurisdiction_payload("NE-WEST"), ADMIN)
        body = created.json()
        assert created.status_code == 201
        assert body["meta"]["api_request_id"].startswith("req_")
        assert body["meta"]["api_request_timestamp"]
        assert body["response_type"] == "object"
        first = validate_success(created, expected_status=201)
        assert_immutable_config_shape(first, "Jurisdiction")
        assert "error_id" not in first

        second = validate_success(
            api.create_jurisdiction(create_jurisdiction_payload("IA-CENTRAL"), ADMIN),
            expected_status=201,
        )

        stored = validate_success(api.get_jurisdiction(first["id"], ADMIN))
        assert stored["code"] == "NE-WEST"
        assert stored["name"] == "Nebraska West"
        assert stored["seal_required"] is False
        assert stored["min_design_wind_speed_mph"] == 95
        assert stored["seismic_design_category"] == "A"
        assert stored["permit_review_days"] == 0
        assert stored == first

        listed = api.list_jurisdictions(ADMIN, params={"limit": 10, "offset": 0})
        assert listed.json()["response_type"] == "array"
        rows, meta = validate_paginated(listed)
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert [row["id"] for row in rows] == [first["id"], second["id"]]
        assert rows[0]["code"] == "NE-WEST"
        assert rows[1]["code"] == "IA-CENTRAL"


class TestDesignComputedFieldsAtCreate:
    def test_the_whole_derived_ladder_is_populated_server_side_in_one_response(
        self, api
    ):
        """PRD §3.2: "The acting engineer's identifier is captured onto the design as
        `author_engineer_id`; the design's `sealed_by_engineer_id`, `sealed_at` and `permit_ready_at` all
        begin null, its `revision_round` begins at 0, its `status` begins at `DRAFT`, and its own
        `seal_required` flag is copied from the referenced jurisdiction's `seal_required` at the moment
        of creation and thereafter never re-read from the jurisdiction."
        PRD §3.2: "The `sidewall_sheet_count` is `sheet_courses` multiplied by `sheets_per_course`."
        PRD §3.2: "The stored `capacity_m3` is the sum of the cylinder and cone volumes rounded half
        up to 2 decimal places."
        PRD §3.2: "The `governing_demand_kpa` is the largest of the three rounded demands."
        PRD §3.2: "the stored `sheet_gauge_mm` is the lowest ladder value that is at or above the
        `governing_demand_kpa` multiplied by 0.05; when no ladder value qualifies, the gauge is 3.0."
        PRD §3.2: "Finally, `roof_ring_required` is true exactly when the design is high-wind by the
        same 115 mile-per-hour test that grants the stiffener bonus — the two flags always agree."

        Design: Corner/entities/bin_design_computed_geometry_and_structural_fields_are_populated_at_create
        """
        ref = setup_reference_data()
        design = create_design(ref)

        assert design["sheet_courses"] == 12
        assert design["circumference_m"] == pytest.approx(37.699, abs=1e-9)
        assert design["sheets_per_course"] == 35
        assert design["sidewall_sheet_count"] == 420
        assert design["roof_panel_count"] == 42
        assert design["capacity_m3"] == pytest.approx(1216.25, abs=1e-9)

        assert design["grain_lateral_kpa"] == pytest.approx(28.518, abs=1e-9)
        assert design["moisture_factor"] == pytest.approx(1.0, abs=1e-9)
        assert design["grain_demand_kpa"] == pytest.approx(28.518, abs=1e-9)
        assert design["wind_demand_kpa"] == pytest.approx(7.938, abs=1e-9)
        assert design["seismic_demand_kpa"] == pytest.approx(3.395, abs=1e-9)
        assert design["governing_load_case"] == "GRAIN_LATERAL"
        assert design["governing_demand_kpa"] == pytest.approx(28.518, abs=1e-9)

        assert design["required_stiffener_count"] == 12
        assert design["utilization_ratio"] == pytest.approx(0.9955, abs=1e-9)
        assert design["sheet_gauge_mm"] == pytest.approx(1.6, abs=1e-9)
        assert design["roof_ring_required"] is False

        assert design["author_engineer_id"] == ref["author"]["id"]
        assert design["sealed_by_engineer_id"] is None
        assert design["sealed_at"] is None
        assert design["permit_ready_at"] is None
        assert design["revision_round"] == 0
        assert design["status"] == "DRAFT"
        assert design["version"] == 1
        # Copied from NE-WEST rather than supplied by the client.
        assert design["seal_required"] is False


class TestCoatingCorrosionBands:
    def test_all_four_zinc_bands_are_reachable_and_the_cut_points_land_high(self, api):
        """PRD §3.1: "On creation the plant derives the coating's `corrosion_class` from its zinc mass
        by a four-band threshold: below 300 grams per square metre the class is `C2`; from 300 up to but
        not including 400 it is `C3`; from 400 up to but not including 550 it is `C4`; and at 550 or
        above it is `C5`."
        PRD §3.1: "The comparison is on integers and nothing is rounded."
        PRD §2.5: "Five entities are immutable reference or derived data and therefore carry **only**
        `id` and `created_at` — no `updated_at` and no `version` at all: `Jurisdiction`, `GrainProfile`,
        `CoatingSpec`, `RollFormingLine` and `KitLine`."

        Design: Corner/entities/coating_spec_corrosion_class_is_computed_across_all_four_zinc_bands
        """
        bands = {}
        for preset, expected in (
            ("G90", "C2"),
            ("G115", "C3"),
            ("G165", "C4"),
            ("G210", "C5"),
        ):
            row = register_coating_spec(preset)
            bands[preset] = row
            assert row["corrosion_class"] == expected
            assert_immutable_config_shape(row, "CoatingSpec")

        # The echoed inputs are stored unchanged alongside the derived class.
        assert bands["G115"]["coating_cost_per_kg_cents"] == 42
        assert bands["G115"]["changeover_minutes"] == 120
        assert bands["G115"]["max_ambient_moisture_pct"] == pytest.approx(18.0, abs=1e-9)
        assert bands["G210"]["zinc_mass_g_per_m2"] == 620

        rows, meta = validate_paginated(
            api.list_coating_specs(PLANNER, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 4
        assert rows[0]["corrosion_class"] == "C2"
        assert all("version" not in row for row in rows)

        # Each cut point belongs to the HIGHER band.
        for code, zinc, expected in (
            ("G300CUT", 300, "C3"),
            ("G400CUT", 400, "C4"),
            ("G550CUT", 550, "C5"),
        ):
            edge = validate_success(
                api.create_coating_spec(
                    create_coating_spec_payload(
                        "G115", coating_code=code, zinc_mass_g_per_m2=zinc
                    ),
                    ADMIN,
                ),
                expected_status=201,
            )
            assert edge["corrosion_class"] == expected
        assert (
            validate_paginated(api.list_coating_specs(ADMIN))[1]["total_count"] == 7
        )


class TestOrderDefaultsAndDerivedLadder:
    def test_five_inputs_write_the_three_dimensions_the_links_and_the_whole_price_ladder(
        self, api
    ):
        """PRD §3.4: "A fresh order begins with `production_status` `DRAFT`, `financial_status`
        `AWAITING_DEPOSIT` and `installation_readiness` `UNASSIGNED`, with `freight_load_id` and
        `installation_crew_id` both null, `deposit_paid_cents` 0, `allocated_freight_cents` 0 and
        `freight_sequence` null."
        PRD §3.4: "Step eight computes `required_deposit_cents` as twenty percent of `total_cents`,
        rounded half up to whole cents, and sets `credit_hold_cents` to `total_cents` minus
        `required_deposit_cents`."
        PRD §3.5: "The stored mass comes first: `grain_mass_kg` is the design's `capacity_m3`
        multiplied by the grain profile's `bulk_density_kg_per_m3`, rounded half up to 2 decimal places."
        PRD §3.5: "With `NONE` the package multiplier is zero, so `required_fan_cfm` is 0."
        PRD §3.5: "With `GRAVITY`, the `unload_rate_bph` is the design's `capacity_m3` multiplied by 3
        bushels per hour per cubic metre and taken **down** to the next whole number."
        PRD §3.1: "At registration the dealership's `credit_committed_cents` is 0, its
        `credit_available_cents` equals its `credit_limit_cents`, its `staged_kit_count` is 0, and its
        `status` is `ACTIVE`."

        Design: Corner/entities/dealer_order_defaults_and_system_fields_are_server_assigned_at_create
        """
        ref = setup_reference_data()
        design = create_design(ref)
        assert ref["alpha"]["credit_committed_cents"] == 0
        order = place_order(ref, design)

        assert order["production_status"] == "DRAFT"
        assert order["financial_status"] == "AWAITING_DEPOSIT"
        assert order["installation_readiness"] == "UNASSIGNED"
        assert order["freight_load_id"] is None
        assert order["installation_crew_id"] is None
        assert order["allocated_freight_cents"] == 0
        assert order["freight_sequence"] is None
        assert order["deposit_paid_cents"] == 0
        assert order["version"] == 1

        assert order["kit_subtotal_cents"] == 2392026
        assert order["season_uplift_cents"] == 0
        assert order["program_discount_cents"] == 0
        assert order["net_subtotal_cents"] == 2392026
        assert order["freight_surcharge_pct"] == pytest.approx(0.045, abs=1e-9)
        assert order["freight_surcharge_cents"] == 107641
        assert order["total_cents"] == 2499667
        assert order["required_deposit_cents"] == 499933
        assert order["credit_hold_cents"] == 1999734

        assert order["kit_weight_kg"] == pytest.approx(6410.4, abs=0.005)
        assert order["kit_cube_m3"] == pytest.approx(18.45, abs=0.0005)
        assert order["grain_mass_kg"] == pytest.approx(876916.25, abs=0.005)
        assert order["required_fan_cfm"] == 0
        assert order["drying_hours_estimate"] == 0
        assert order["unload_rate_bph"] == 3648

        # Pricing populates credit_hold_cents but commits nothing.
        dealer = read_dealer(ref["alpha"]["id"])
        assert dealer["credit_committed_cents"] == 0
        assert dealer["credit_available_cents"] == dealer["credit_limit_cents"]
        assert dealer["staged_kit_count"] == 0
        assert dealer["status"] == "ACTIVE"
        # The design is read, never written.
        assert read_design(design["id"]) == design


class TestMissingRequiredFieldsBeatEveryLookup:
    def test_a_missing_field_is_a_400_even_when_the_ids_are_bogus(self, api):
        """PRD §2.11: "Request shape, on every endpoint: every required input field present, of the
        declared type, within its declared numeric range, and — for enumerated fields — one of the
        declared members. Unknown body fields are ignored rather than rejected. Failure is
        `ERR_INVALID_REQUEST`, 400."
        PRD §2.11: "Body foreign-key resolution, in the order the fields appear in the endpoint's
        input list, on dealership registration, design creation, coil lot receipt, run scheduling, order
        placement, freight load planning, order attachment to a load, crew registration, crew assignment
        and failure intake — again the entity-specific 404 codes."
        PRD §2.1: "If a `DesignEngineer` or `SealingEngineer` presents an `X-User-ID` that does not
        resolve to a stored `Engineer` row, the request fails with `ERR_ENGINEER_SCOPE_VIOLATION` and
        HTTP 403."

        Design: Corner/entities/missing_required_input_fields_are_rejected_before_any_lookup
        """
        ref = setup_reference_data(with_pinnacle=False)
        jurisdiction_id = ref["jurisdictions"]["NE-WEST"]["id"]

        incomplete_dealer = create_dealer_payload(jurisdiction_id, name="Gamma Grain")
        del incomplete_dealer["credit_limit_cents"]
        validate_error(
            api.create_dealer(incomplete_dealer, ADMIN), "ERR_INVALID_REQUEST", 400
        )

        # Two dangling ids, an unregistered actor, and two missing fields: 400 wins.
        incomplete_design = create_bin_design_payload(
            NON_EXISTENT_UUID,
            NON_EXISTENT_UUID,
            NON_EXISTENT_UUID,
            NON_EXISTENT_UUID,
        )
        del incomplete_design["grain_profile_id"]
        del incomplete_design["coating_spec_id"]
        validate_error(
            api.create_bin_design(
                incomplete_design,
                make_design_engineer_headers("00000000-0000-4000-8000-000000000009"),
            ),
            "ERR_INVALID_REQUEST",
            400,
        )

        # An unknown body key is ignored, never rejected.
        accepted = validate_success(
            api.create_dealer(
                create_dealer_payload(
                    jurisdiction_id,
                    name="Gamma Grain",
                    region_code="NE-03",
                    credit_limit_cents=500000,
                    unknown_field="ignore me",
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        assert accepted["credit_limit_cents"] == 500000
        assert_no_such_field(accepted, "unknown_field")

        assert validate_paginated(api.list_dealers(ADMIN))[1]["total_count"] == 2
        assert validate_paginated(api.list_bin_designs(ADMIN))[1]["total_count"] == 0


class TestEnumAndRangeConstraintsOnCreate:
    def test_a_closed_string_enum_a_closed_integer_enum_and_an_inclusive_range(
        self, api
    ):
        """PRD §3.2: "a `roof_pitch_deg` that is one of `25`, `30` or `35`, a `design_wind_speed_mph`
        between 80 and 200, a `moisture_pct` between 8.0 and 24.0 describing the design storage moisture
        on a wet basis, and a `design_method` of either `ASD` or `LRFD`."
        PRD §3.1: "A roll-forming line is registered with a `line_code` unique across all lines and a
        `max_gauge_mm` between 0.8 and 6.0 giving the heaviest sheet that line can form."
        PRD §2.11: "Request shape, on every endpoint: every required input field present, of the
        declared type, within its declared numeric range, and — for enumerated fields — one of the
        declared members."

        Design: Corner/entities/enum_and_numeric_range_constraints_are_enforced_on_create
        """
        ref = setup_reference_data()
        author = engineer_headers(ref)

        def design_payload(**overrides):
            return create_bin_design_payload(
                ref["alpha"]["id"],
                ref["jurisdictions"]["NE-WEST"]["id"],
                ref["grain_profiles"]["CORN"]["id"],
                ref["coating_specs"]["G115"]["id"],
                **overrides,
            )

        validate_error(
            api.create_bin_design(design_payload(design_method="WSD"), author),
            "ERR_INVALID_REQUEST",
            400,
        )
        # 28 degrees is physically plausible but is not a declared member.
        validate_error(
            api.create_bin_design(design_payload(roof_pitch_deg=28), author),
            "ERR_INVALID_REQUEST",
            400,
        )

        validate_error(
            api.create_roll_forming_line(
                create_roll_forming_line_payload("LINE_MAX", max_gauge_mm=6.5), ADMIN
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        ceiling = validate_success(
            api.create_roll_forming_line(
                create_roll_forming_line_payload("LINE_MAX"), ADMIN
            ),
            expected_status=201,
        )
        assert ceiling["max_gauge_mm"] == pytest.approx(6.0, abs=1e-9)

        assert validate_paginated(api.list_bin_designs(ADMIN))[1]["total_count"] == 0


class TestImmutableConfigurationSurface:
    def test_the_five_reference_entities_carry_no_version_and_no_update_endpoint(
        self, api
    ):
        """PRD §2.5: "Five entities are immutable reference or derived data and therefore carry **only**
        `id` and `created_at` — no `updated_at` and no `version` at all: `Jurisdiction`, `GrainProfile`,
        `CoatingSpec`, `RollFormingLine` and `KitLine`."
        PRD §2.5: "Implementations must not emit those two properties for those five entities."
        PRD §3.1: "On creation the plant derives the coating's `corrosion_class` from its zinc mass by a
        four-band threshold: below 300 grams per square metre the class is `C2`; from 300 up to but not
        including 400 it is `C3`; from 400 up to but not including 550 it is `C4`; and at 550 or above it
        is `C5`."
        PRD §3.4: "The bill-of-materials lines of an order may be read back in the fixed component
        order, and orders themselves may be listed and narrowed by `dealer_id`, `bin_design_id`,
        `freight_load_id` or `installation_crew_id`."

        Design: Corner/entities/configuration_entities_are_immutable_and_expose_no_version_or_update_surface
        """
        ref = setup_reference_data()

        jurisdiction = validate_success(
            api.get_jurisdiction(ref["jurisdictions"]["NE-WEST"]["id"], ADMIN)
        )
        assert_immutable_config_shape(jurisdiction, "Jurisdiction")
        assert set(jurisdiction) == {
            "id",
            "created_at",
            "code",
            "name",
            "seal_required",
            "min_design_wind_speed_mph",
            "seismic_design_category",
            "permit_review_days",
        }

        profile = validate_success(
            api.get_grain_profile(ref["grain_profiles"]["CORN"]["id"], ADMIN)
        )
        assert_immutable_config_shape(profile, "GrainProfile")

        coating = validate_success(
            api.get_coating_spec(ref["coating_specs"]["G115"]["id"], ADMIN)
        )
        assert_immutable_config_shape(coating, "CoatingSpec")
        assert coating["corrosion_class"] == "C3"

        line = validate_success(
            api.get_roll_forming_line(ref["lines"]["LINE_A"]["id"], ADMIN)
        )
        assert_immutable_config_shape(line, "RollFormingLine")

        # KitLine is reachable only as a child collection, and is equally immutable.
        order = place_order(ref, create_design(ref))
        kit_lines, _ = validate_paginated(api.list_kit_lines(order["id"], ADMIN))
        assert kit_lines
        for kit_line in kit_lines:
            assert_immutable_config_shape(kit_line, "KitLine")


class TestNotFoundVocabulary:
    def test_each_entity_owns_its_404_and_configuration_shares_one(self, api):
        """PRD §2.7: "The four reference-configuration entities share a single code: a missing
        `Jurisdiction`, `GrainProfile`, `CoatingSpec` or `RollFormingLine`, whether addressed in the path
        or referenced from a body, yields `ERR_CONFIG_NOT_FOUND`."
        PRD §2.7: "The remaining entities each have their own: `ERR_ENGINEER_NOT_FOUND`,
        `ERR_DEALER_NOT_FOUND`, `ERR_BIN_DESIGN_NOT_FOUND`, `ERR_COIL_LOT_NOT_FOUND`,
        `ERR_ROLL_FORMING_RUN_NOT_FOUND`, `ERR_DEALER_ORDER_NOT_FOUND`, `ERR_FREIGHT_LOAD_NOT_FOUND`,
        `ERR_INSTALLATION_CREW_NOT_FOUND` and `ERR_FIELD_FAILURE_NOT_FOUND`."
        PRD §2.7: "Every not-found rejection carries HTTP 404."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific
        error."

        Design: Corner/entities/unknown_ids_return_the_entity_specific_not_found_error
        """
        missing = "00000000-0000-4000-8000-0000000000{:02d}"
        cases = (
            (api.get_jurisdiction(missing.format(1), ADMIN), "ERR_CONFIG_NOT_FOUND"),
            (api.get_coating_spec(missing.format(2), ADMIN), "ERR_CONFIG_NOT_FOUND"),
            (api.get_grain_profile(missing.format(3), ADMIN), "ERR_CONFIG_NOT_FOUND"),
            (
                api.get_roll_forming_line(missing.format(4), ADMIN),
                "ERR_CONFIG_NOT_FOUND",
            ),
            (api.get_engineer(missing.format(5), ADMIN), "ERR_ENGINEER_NOT_FOUND"),
            (api.get_dealer(missing.format(6), ADMIN), "ERR_DEALER_NOT_FOUND"),
            (api.get_bin_design(missing.format(7), ADMIN), "ERR_BIN_DESIGN_NOT_FOUND"),
            (
                api.get_dealer_order(missing.format(8), ADMIN),
                "ERR_DEALER_ORDER_NOT_FOUND",
            ),
            (api.get_coil_lot(missing.format(9), PLANNER), "ERR_COIL_LOT_NOT_FOUND"),
            (
                api.get_roll_forming_run(missing.format(10), PLANNER),
                "ERR_ROLL_FORMING_RUN_NOT_FOUND",
            ),
            (
                api.get_freight_load(missing.format(11), LOGISTICS),
                "ERR_FREIGHT_LOAD_NOT_FOUND",
            ),
            (
                api.get_field_failure(missing.format(12), QUALITY),
                "ERR_FIELD_FAILURE_NOT_FOUND",
            ),
            (
                api.get_installation_crew(missing.format(13), ADMIN),
                "ERR_INSTALLATION_CREW_NOT_FOUND",
            ),
        )
        for response, error_id in cases:
            validate_error(response, error_id, 404)
            body = response.json()
            assert body["response_type"] == "error"
            assert body["data"]["message"]


class TestBodyForeignKeyResolutionOrder:
    def test_the_leftmost_dangling_reference_in_the_input_list_wins(self, api):
        """PRD §2.7: "Foreign keys supplied in a request body are resolved after the path, and among
        themselves they are resolved in the order the fields appear in that endpoint's input list."
        PRD §3.2: "A `DesignEngineer` draws a bin by naming the dealership it is for with `dealer_id`,
        the permitting authority it will be checked against with `jurisdiction_id`, the stored product
        with `grain_profile_id` and the corrosion protection with `coating_spec_id`"
        PRD §3.1: "Dealerships are registered with a `name`, a `region_code`, the identifier of the
        jurisdiction governing their yard supplied as `jurisdiction_id`"

        Design: Corner/entities/body_foreign_keys_are_validated_left_to_right_in_the_declared_input_order
        """
        ref = setup_reference_data()
        author = engineer_headers(ref)
        grain_profile_id = ref["grain_profiles"]["CORN"]["id"]
        coating_spec_id = ref["coating_specs"]["G115"]["id"]

        # dealer_id is declared first, so its 404 is the one the client sees.
        validate_error(
            api.create_bin_design(
                create_bin_design_payload(
                    NON_EXISTENT_UUID,
                    NON_EXISTENT_UUID,
                    grain_profile_id,
                    coating_spec_id,
                ),
                author,
            ),
            "ERR_DEALER_NOT_FOUND",
            404,
        )

        # Both remaining offenders are configuration entities sharing one code.
        validate_error(
            api.create_bin_design(
                create_bin_design_payload(
                    ref["alpha"]["id"],
                    NON_EXISTENT_UUID,
                    NON_EXISTENT_UUID,
                    coating_spec_id,
                ),
                author,
            ),
            "ERR_CONFIG_NOT_FOUND",
            404,
        )

        validate_error(
            api.create_dealer(
                create_dealer_payload(NON_EXISTENT_UUID, name="Gamma Grain"), ADMIN
            ),
            "ERR_CONFIG_NOT_FOUND",
            404,
        )

        assert validate_paginated(api.list_bin_designs(ADMIN))[1]["total_count"] == 0
        assert validate_paginated(api.list_dealers(ADMIN))[1]["total_count"] == 2


class TestDesignListingFilterBeforeWindow:
    def test_total_count_reports_the_filtered_population_not_the_table(self, api):
        """PRD §3.2: "Designs may be listed and narrowed by `dealer_id`, `jurisdiction_id`,
        `grain_profile_id`, `coating_spec_id`, `author_engineer_id` or `sealed_by_engineer_id`."
        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and `has_more` in
        `meta`, where `total_count` is the number of rows matching the filter before the page window is
        applied, and `has_more` is true exactly when rows remain beyond the current window."
        PRD §2.3: "A `limit` below 1 or above 100, or a negative `offset`, is a malformed request and
        is rejected with `ERR_INVALID_REQUEST` and HTTP 400."

        Design: Corner/entities/bin_design_listing_combines_a_foreign_key_filter_with_limit_and_offset
        """
        ref = setup_reference_data()
        alpha_one = create_design(ref, dealer="alpha")
        alpha_two = create_design(ref, dealer="alpha")
        pinnacle_one = create_design(ref, dealer="pinnacle")
        alpha_filter = {"dealer_id": ref["alpha"]["id"]}

        listed = api.list_bin_designs(
            ADMIN, params={**alpha_filter, "limit": 1, "offset": 0}
        )
        assert listed.json()["response_type"] == "array"
        rows, meta = validate_paginated(listed)
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        assert [row["id"] for row in rows] == [alpha_one["id"]]

        rows, meta = validate_paginated(
            api.list_bin_designs(ADMIN, params={**alpha_filter, "limit": 1, "offset": 1})
        )
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert [row["id"] for row in rows] == [alpha_two["id"]]

        rows, meta = validate_paginated(
            api.list_bin_designs(ADMIN, params={"limit": 2, "offset": 0})
        )
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert len(rows) == 2
        assert pinnacle_one["id"] not in [row["id"] for row in rows]

        validate_error(
            api.list_bin_designs(ADMIN, params={"limit": 101, "offset": 0}),
            "ERR_INVALID_REQUEST",
            400,
        )


class TestKitLineChildCollection:
    def test_the_five_steel_lines_reconcile_with_the_parent_order(self, api):
        """PRD §3.4: "A kit line is emitted only for components whose quantity is 1 or more, and the
        emitted lines appear in the fixed component order above; a gravity-discharge bin with no aeration
        therefore has five lines, not seven."
        PRD §3.4: "The `unit_price_cents` is therefore the base price plus that rounded per-unit adder
        for steel components, and the base price alone for the other two."
        PRD §3.4: "the adder is rounded per component code and only then multiplied by quantity through
        `extended_cents`, which is the `quantity` multiplied by the `unit_price_cents`."
        PRD §3.4: "At the order level, `kit_subtotal_cents` is the sum of `extended_cents` over the
        emitted lines, `kit_weight_kg` is the sum of the lines' `weight_kg` rounded half up to 2 decimal
        places, and `kit_cube_m3` is the sum of the lines' `cube_m3` rounded half up to 3 decimal places
        — the rounding is applied per line and then again on the order-level sum."

        Design: Corner/entities/kit_lines_are_readable_as_a_child_collection_in_declared_component_order
        """
        ref = setup_reference_data()
        design = create_design(ref)
        order = place_order(ref, design, aeration_package="NONE", unload_system="GRAVITY")

        rows, meta = validate_paginated(api.list_kit_lines(order["id"], ADMIN))
        assert meta["total_count"] == 5
        assert meta["has_more"] is False
        assert_kit_lines_in_component_order(rows)
        assert [row["component_code"] for row in rows] == [
            "SIDEWALL_SHEET",
            "STIFFENER",
            "ROOF_PANEL",
            "ANCHOR_BOLT",
            "BOLT_PACK",
        ]
        assert all(row["dealer_order_id"] == order["id"] for row in rows)

        expected = {
            "SIDEWALL_SHEET": (420, 4725, 1984500, 5250.0, 15.96),
            "STIFFENER": (12, 11522, 138264, 492.0, 0.66),
            "ROOF_PANEL": (42, 3995, 167790, 394.8, 1.302),
            "ANCHOR_BOLT": (48, 500, 24000, 57.6, 0.096),
            "BOLT_PACK": (36, 2152, 77472, 216.0, 0.432),
        }
        for row in rows:
            quantity, unit, extended, weight, cube = expected[row["component_code"]]
            assert row["quantity"] == quantity
            assert row["unit_price_cents"] == unit
            assert row["extended_cents"] == extended
            assert row["weight_kg"] == pytest.approx(weight, abs=0.005)
            assert row["cube_m3"] == pytest.approx(cube, abs=0.0005)

        assert sum(row["extended_cents"] for row in rows) == order["kit_subtotal_cents"]
        assert order["kit_subtotal_cents"] == 2392026
        assert sum(row["weight_kg"] for row in rows) == pytest.approx(6410.4, abs=0.005)
        assert sum(row["cube_m3"] for row in rows) == pytest.approx(18.45, abs=0.0005)
        assert order["kit_weight_kg"] == pytest.approx(6410.4, abs=0.005)
        assert order["kit_cube_m3"] == pytest.approx(18.45, abs=0.0005)


class TestNotFoundFamilyAndPathBeforeBody:
    def test_the_path_id_is_resolved_before_the_body_and_shape_outranks_both(self, api):
        """PRD §2.7: "Path identifiers are resolved strictly left to right, and the first identifier
        that fails to resolve determines the error."
        PRD §2.11: "Path identifier resolution, on every endpoint carrying a path identifier, left to
        right — the entity-specific 404 codes listed in §2.7."
        PRD §2.11: "Body foreign-key resolution, in the order the fields appear in the endpoint's input
        list, on dealership registration, design creation, coil lot receipt, run scheduling, order
        placement, freight load planning, order attachment to a load, crew registration, crew assignment
        and failure intake — again the entity-specific 404 codes."
        PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and
        `api_request_timestamp`."

        Design: Corner/errors/the_not_found_family_names_the_entity_and_the_path_is_resolved_before_the_body
        """
        ref = setup_reference_data()
        design = create_design(ref)
        order = place_order(ref, design)
        crew = register_crew(ref)
        unknown = "00000000-0000-4000-8000-0000000000aa"

        doubly_unknown = api.assign_crew_to_order(
            unknown, assign_crew_payload(unknown), ADMIN
        )
        validate_error(doubly_unknown, "ERR_DEALER_ORDER_NOT_FOUND", 404)
        body = doubly_unknown.json()
        assert body["response_type"] == "error"
        assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}
        assert body["data"]["error_id"] and body["data"]["message"]

        # Request shape outranks both id lookups.
        validate_error(
            api.assign_crew_to_order(unknown, {}, ADMIN), "ERR_INVALID_REQUEST", 400
        )

        validate_error(
            api.assign_crew_to_order(order["id"], assign_crew_payload(unknown), ADMIN),
            "ERR_INSTALLATION_CREW_NOT_FOUND",
            404,
        )

        validate_error(
            api.get_bin_design(unknown, ADMIN), "ERR_BIN_DESIGN_NOT_FOUND", 404
        )
        validate_error(
            api.get_freight_load(unknown, LOGISTICS), "ERR_FREIGHT_LOAD_NOT_FOUND", 404
        )
        # One id, two configuration entities, one shared code.
        validate_error(
            api.get_coating_spec(unknown, ADMIN), "ERR_CONFIG_NOT_FOUND", 404
        )
        validate_error(
            api.get_grain_profile(unknown, ADMIN), "ERR_CONFIG_NOT_FOUND", 404
        )

        assigned = validate_success(
            api.assign_crew_to_order(
                order["id"], assign_crew_payload(crew["id"]), ADMIN
            )
        )
        assert assigned["installation_readiness"] == "ASSIGNED"


class TestRequestShapeDefectsAreAllFourHundred:
    def test_enum_range_and_type_defects_never_surface_as_business_errors(self, api):
        """PRD §2.11: "Request shape, on every endpoint: every required input field present, of the
        declared type, within its declared numeric range, and — for enumerated fields — one of the
        declared members. Unknown body fields are ignored rather than rejected. Failure is
        `ERR_INVALID_REQUEST`, 400."
        PRD §3.2: "a `diameter_m` between 4.0 and 30.0, an `eave_height_m` between 3.2 and 24.0, a
        `roof_pitch_deg` that is one of `25`, `30` or `35`, a `design_wind_speed_mph` between 80 and 200"
        PRD §3.5: "The `aeration_package` is one of `NONE`, `AERATION` or `DRYING_FULL`, and the
        `unload_system` is one of `GRAVITY`, `SWEEP_AUGER` or `POWER_SWEEP`."

        Design: Corner/errors/enum_range_and_type_defects_are_request_shape_errors_while_unknown_fields_are_ignored
        """
        ref = setup_reference_data()
        author = engineer_headers(ref)
        design = create_design(ref)

        def design_payload(**overrides):
            return create_bin_design_payload(
                ref["alpha"]["id"],
                ref["jurisdictions"]["NE-WEST"]["id"],
                ref["grain_profiles"]["CORN"]["id"],
                ref["coating_specs"]["G115"]["id"],
                **overrides,
            )

        for overrides in (
            {"roof_pitch_deg": 28},
            {"design_method": "ULSD"},
            {"diameter_m": 3.9},
            {"eave_height_m": 24.1},
            # 210 mph is out of range, so the priority-10 jurisdiction gate never runs.
            {"design_wind_speed_mph": 210},
        ):
            validate_error(
                api.create_bin_design(design_payload(**overrides), author),
                "ERR_INVALID_REQUEST",
                400,
            )

        # Both range endpoints are inclusive.
        minimum = validate_success(
            api.create_bin_design(
                design_payload(
                    diameter_m=4.0,
                    eave_height_m=3.2,
                    roof_pitch_deg=25,
                    design_method="LRFD",
                ),
                author,
            ),
            expected_status=201,
        )
        assert minimum["status"] == "DRAFT"

        bad_enum_order = create_dealer_order_payload(
            ref["alpha"]["id"], design["id"], aeration_package="AERATION_PLUS"
        )
        validate_error(
            api.create_dealer_order(bad_enum_order, ref["alpha_headers"]),
            "ERR_INVALID_REQUEST",
            400,
        )
        missing_field_order = create_dealer_order_payload(
            ref["alpha"]["id"], design["id"]
        )
        del missing_field_order["unload_system"]
        validate_error(
            api.create_dealer_order(missing_field_order, ref["alpha_headers"]),
            "ERR_INVALID_REQUEST",
            400,
        )

        version = read_dealer(ref["alpha"]["id"])["version"]
        validate_error(
            api.create_freight_load(
                create_freight_load_payload(
                    ref["alpha"]["id"], version, trailer_type="BOXCAR"
                ),
                LOGISTICS,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        validate_error(
            api.create_freight_load(
                create_freight_load_payload(
                    ref["alpha"]["id"], version, allocation_basis="TONNAGE"
                ),
                LOGISTICS,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        assert validate_paginated(api.list_freight_loads(LOGISTICS))[1]["total_count"] == 0

        # An unknown body key is ignored rather than rejected.
        ignored = validate_success(
            api.create_bin_design(design_payload(notes="ignore me"), author),
            expected_status=201,
        )
        assert_no_such_field(ignored, "notes")

        # Three successful creates, nine rejected ones, three stored rows.
        assert validate_paginated(api.list_bin_designs(ADMIN))[1]["total_count"] == 3


class TestRoleExclusiveOperations:
    def test_one_exclusive_write_from_each_of_the_seven_seats_succeeds(self, api):
        """PRD §2.1: "The seven roles are `PlantAdmin`, `DesignEngineer`, `SealingEngineer`,
        `ProductionPlanner`, `DealerPrincipal`, `LogisticsCoordinator` and `QualityInspector`."
        PRD §2.1: "A `DesignEngineer` authors, analyses, submits and revises bin designs, and never
        seals its own work."
        PRD §2.1: "A `SealingEngineer` reviews a design that is under review and either returns it for
        revision or applies the engineering seal."
        PRD §2.1: "A `ProductionPlanner` receives coil, books roll-forming line time, and posts run
        completion or void."
        PRD §3.9: "Intake copies the order's `bin_design_id` onto the investigation and freezes it
        there, so a later revision of the design library cannot move the target of the investigation."

        Design: Corner/rbac/each_of_the_seven_roles_holds_exactly_its_own_exclusive_operations
        """
        ref = setup_reference_data()

        crew = register_crew(ref)
        assert crew["status"] == "CERTIFIED"

        design = create_design(ref)
        assert design["status"] == "DRAFT"
        analysis = add_analysis(ref, design)
        assert analysis["analysis_index"] == 1
        assert submit_for_review(ref, design)["status"] == "UNDER_REVIEW"
        sealed = seal_design(ref, design)
        assert sealed["status"] == "SEALED"
        assert sealed["sealed_by_engineer_id"] == ref["sealer"]["id"]

        lot = receive_coil_lot(ref)
        assert lot["status"] == "AVAILABLE"

        order = place_order(ref, design)
        assert order["production_status"] == "DRAFT"

        # Reads are open, so the coordinator may inspect the dealership it stages for.
        assert (
            validate_success(api.get_dealer(ref["alpha"]["id"], LOGISTICS))["id"]
            == ref["alpha"]["id"]
        )
        load = plan_freight_load(ref)
        assert load["status"] == "PLANNED"

        failure = validate_success(
            api.create_field_failure(create_field_failure_payload(order["id"]), QUALITY),
            expected_status=201,
        )
        assert failure["status"] == "INTAKE"
        # Never sent in the body; copied from the order.
        assert failure["bin_design_id"] == design["id"]

    def test_the_wrong_seat_is_a_403_and_a_bad_header_is_a_401(self, api):
        """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the seven role
        names declared below, the request is rejected with `ERR_MISSING_AUTH_HEADERS` and HTTP 401."
        PRD §2.1: "If both headers are well formed but the named role is not permitted to call the
        addressed endpoint, the rejection is `ERR_UNAUTHORIZED_ROLE` with HTTP 403."
        PRD §2.11: "Role authorization for the called endpoint, on every endpoint —
        `ERR_UNAUTHORIZED_ROLE`, 403."
        PRD §2.11: "Authoring-versus-sealing segregation, on sealing and on revision request —
        `ERR_SEAL_SEGREGATION_VIOLATION`, 403."

        Design: Corner/rbac/each_of_the_seven_roles_holds_exactly_its_own_exclusive_operations
        """
        ref = setup_reference_data()
        design = create_design(ref)
        order = place_order(ref, design)
        crew = register_crew(ref)
        payload = create_bin_design_payload(
            ref["alpha"]["id"],
            ref["jurisdictions"]["NE-WEST"]["id"],
            ref["grain_profiles"]["CORN"]["id"],
            ref["coating_specs"]["G115"]["id"],
        )

        validate_error(
            api.create_bin_design(payload, ADMIN), "ERR_UNAUTHORIZED_ROLE", 403
        )
        # Role authorization outranks request shape.
        broken = dict(payload)
        del broken["diameter_m"]
        validate_error(
            api.create_bin_design(broken, ADMIN), "ERR_UNAUTHORIZED_ROLE", 403
        )

        # The two engineer seats are disjoint in both directions.
        validate_error(
            api.seal_bin_design(
                design["id"], make_design_engineer_headers(ref["sealer"]["id"])
            ),
            "ERR_UNAUTHORIZED_ROLE",
            403,
        )
        validate_error(
            api.submit_design_for_review(
                design["id"], make_sealing_engineer_headers(ref["author"]["id"])
            ),
            "ERR_UNAUTHORIZED_ROLE",
            403,
        )

        validate_error(
            api.create_dealer_order(
                create_dealer_order_payload(ref["alpha"]["id"], design["id"]), LOGISTICS
            ),
            "ERR_UNAUTHORIZED_ROLE",
            403,
        )
        validate_error(
            api.dispatch_freight_load(NON_EXISTENT_UUID, ref["alpha_headers"]),
            "ERR_UNAUTHORIZED_ROLE",
            403,
        )
        validate_error(
            api.create_roll_forming_run(
                create_roll_forming_run_payload(
                    ref["lines"]["LINE_A"]["id"],
                    NON_EXISTENT_UUID,
                    order["id"],
                    "2026-08-03T08:00:00Z",
                    "2026-08-03T12:00:00Z",
                    6600.0,
                ),
                LOGISTICS,
            ),
            "ERR_UNAUTHORIZED_ROLE",
            403,
        )
        validate_error(
            api.create_field_failure(create_field_failure_payload(order["id"]), ADMIN),
            "ERR_UNAUTHORIZED_ROLE",
            403,
        )
        validate_error(
            api.set_credit_limit(
                ref["alpha"]["id"], credit_limit_payload(1), ref["alpha_headers"]
            ),
            "ERR_UNAUTHORIZED_ROLE",
            403,
        )
        validate_error(
            api.set_clock(set_clock_payload("2026-09-01T00:00:00Z"), PLANNER),
            "ERR_UNAUTHORIZED_ROLE",
            403,
        )
        # Crew assignment is a PlantAdmin seat even for the dealership that owns both rows.
        validate_error(
            api.assign_crew_to_order(
                order["id"], assign_crew_payload(crew["id"]), ref["alpha_headers"]
            ),
            "ERR_UNAUTHORIZED_ROLE",
            403,
        )

        # Header defects outrank even the role check.
        validate_error(
            api.create_bin_design(payload, headers_without_role()),
            "ERR_MISSING_AUTH_HEADERS",
            401,
        )
        validate_error(
            api.create_bin_design(payload, headers_for_role("YardForeman")),
            "ERR_MISSING_AUTH_HEADERS",
            401,
        )
        validate_error(
            api.create_bin_design(payload, headers_without_user_id("DesignEngineer")),
            "ERR_MISSING_AUTH_HEADERS",
            401,
        )


class TestDealerPrincipalScopeIsAsymmetric:
    def test_a_peer_dealership_is_refused_every_write_but_reads_freely(self, api):
        """PRD §2.1: "When `X-User-Role` is `DealerPrincipal`, `X-User-ID` is the `id` of the acting
        `Dealer`; ownership checks on an order compare that order's `dealer_id` to `X-User-ID`, and on
        order placement the `dealer_id` supplied in the request body must equal `X-User-ID` as well."
        PRD §2.1: "A mismatch, or an `X-User-ID` that names no stored dealership, yields
        `ERR_DEALER_SCOPE_VIOLATION` with HTTP 403."
        PRD §2.11: "Ownership scope for the entity-backed roles, on order placement, order
        confirmation, deposit posting, order cancellation, design creation, analysis creation, review
        submission, revision request, revision and sealing — `ERR_DEALER_SCOPE_VIOLATION` or
        `ERR_ENGINEER_SCOPE_VIOLATION`, 403."
        PRD §2.1: "Every read endpoint in this API is available to all seven roles; the write endpoints
        are exclusive as described, and §4 records the authorization for each path individually."

        Design: Corner/rbac/a_dealer_principal_may_write_only_their_own_orders_but_may_read_anyone_s
        """
        ref = setup_reference_data()
        design = create_design_under_review(ref)
        order = place_order(ref, design)
        assert order["required_deposit_cents"] == 499933
        peer = ref["pinnacle_headers"]

        validate_error(
            api.create_dealer_order(
                create_dealer_order_payload(ref["alpha"]["id"], design["id"]), peer
            ),
            "ERR_DEALER_SCOPE_VIOLATION",
            403,
        )
        validate_error(
            api.confirm_dealer_order(order["id"], peer),
            "ERR_DEALER_SCOPE_VIOLATION",
            403,
        )
        validate_error(
            api.post_order_payment(order["id"], order_payment_payload(499933), peer),
            "ERR_DEALER_SCOPE_VIOLATION",
            403,
        )
        validate_error(
            api.cancel_dealer_order(order["id"], peer),
            "ERR_DEALER_SCOPE_VIOLATION",
            403,
        )

        # Reads carry no ownership condition.
        seen = validate_success(api.get_dealer_order(order["id"], peer))
        assert seen["dealer_id"] == ref["alpha"]["id"]
        assert seen["production_status"] == "DRAFT"
        assert seen["financial_status"] == "AWAITING_DEPOSIT"
        assert seen["deposit_paid_cents"] == 0
        rows, meta = validate_paginated(
            api.list_dealer_orders(peer, params={"dealer_id": ref["alpha"]["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == order["id"]

        owner = validate_success(
            api.confirm_dealer_order(order["id"], ref["alpha_headers"])
        )
        assert owner["production_status"] == "QUEUED"


class TestSharedReadSurface:
    def test_all_seven_roles_read_identical_payloads_across_ownership_boundaries(
        self, api
    ):
        """PRD §2.1: "Every read endpoint in this API is available to all seven roles; the write
        endpoints are exclusive as described, and §4 records the authorization for each path
        individually."
        PRD §2.1: "Every request — without exception, including reads — must carry two headers:
        `X-User-ID`, identifying the actor, and `X-User-Role`, naming the capability set that actor is
        exercising."
        PRD §2.10: "Whenever a `SealingEngineer` acts on a design — whether to return it for revision or
        to apply the seal — the acting `X-User-ID` must differ from that design's `author_engineer_id`."

        Design: Corner/rbac/every_role_shares_the_entire_get_surface_with_identical_payloads
        """
        ref = setup_reference_data()
        design = create_design(ref)
        register_crew(ref)
        receive_coil_lot(ref)
        order = place_order(ref, design)

        readers = (
            ADMIN,
            make_design_engineer_headers(ref["author"]["id"]),
            # The author's own id under the sealing seat: reads carry no segregation rule.
            make_sealing_engineer_headers(ref["author"]["id"]),
            PLANNER,
            make_dealer_principal_headers(ref["alpha"]["id"]),
            LOGISTICS,
            QUALITY,
        )
        payloads = [
            validate_success(api.get_bin_design(design["id"], headers))
            for headers in readers
        ]
        for payload in payloads:
            assert payload == payloads[0]
            assert payload["required_stiffener_count"] == 12
            assert payload["sidewall_sheet_count"] == 420
            assert payload["roof_panel_count"] == 42
            assert payload["capacity_m3"] == pytest.approx(1216.25, abs=1e-9)
            assert payload["author_engineer_id"] == ref["author"]["id"]
            assert payload["utilization_ratio"] == pytest.approx(0.9955, abs=1e-9)
            assert payload["sheet_gauge_mm"] == pytest.approx(1.6, abs=1e-9)

        # Cross-function reads: a planner reads a dealer's pricing detail.
        assert (
            validate_paginated(api.list_kit_lines(order["id"], PLANNER))[1][
                "total_count"
            ]
            == 5
        )
        assert (
            validate_paginated(api.list_coil_lots(QUALITY))[1]["total_count"] == 1
        )
        assert (
            validate_paginated(
                api.list_dealer_installation_crews(
                    ref["alpha"]["id"],
                    make_sealing_engineer_headers(ref["sealer"]["id"]),
                )
            )[1]["total_count"]
            == 1
        )


class TestAnalysisCreateGuardsTheDesignVersion:
    def test_a_replayed_design_version_is_412_and_the_create_bumps_the_parent(self, api):
        """PRD §2.9: "If `expected_bin_design_version` does not equal the design's current `version`,
        the request is rejected with `ERR_STALE_DESIGN_VERSION` and HTTP 412."
        PRD §2.9: "A `POST /bin-designs/{id}/analyses` request — creating a structural analysis on a bin
        design — requires `expected_bin_design_version` in the request body as a mandatory, non-optional
        field carrying the client's last observed `BinDesign` `version`."
        PRD §3.2: "Under `ASD` the allowable capacity per stiffener is the nominal 180.0 divided by a
        safety factor of 2.00, which is exactly 90.0 kilopascal-metres."
        PRD §3.2: "Under `LRFD` it is the nominal 180.0 multiplied by a resistance factor of 0.90 and
        divided by a load factor of 1.60, which is exactly 101.25 kilopascal-metres — twelve and a half
        percent more than `ASD`, so the same geometry and loading can legitimately require strictly fewer
        stiffeners under `LRFD` than under `ASD`."

        Design: Corner/complexity_layers/both_occ_rules_demand_exact_version_equality_and_every_guarded_write_bumps_the_parent
        """
        ref = setup_reference_data()
        author = engineer_headers(ref)
        design = create_design(ref)
        assert design["version"] == 1

        first = validate_success(
            api.create_design_analysis(
                design["id"], create_design_analysis_payload("ASD", 1), author
            ),
            expected_status=201,
        )
        assert first["analysis_index"] == 1
        assert first["allowable_kpa_m"] == pytest.approx(90.0, abs=1e-9)
        assert first["required_stiffener_count"] == 12
        assert first["verdict"] == "PASS"

        # The create bumped the design without writing any field the client sent.
        bumped = read_design(design["id"])
        assert_version_advanced_by(bumped, design, 1, "design")
        assert bumped["status"] == "DRAFT"

        validate_error(
            api.create_design_analysis(
                design["id"], create_design_analysis_payload("LRFD", 1), author
            ),
            "ERR_STALE_DESIGN_VERSION",
            412,
        )

        second = validate_success(
            api.create_design_analysis(
                design["id"],
                create_design_analysis_payload("LRFD", bumped["version"]),
                author,
            ),
            expected_status=201,
        )
        assert second["analysis_index"] == 2
        assert second["allowable_kpa_m"] == pytest.approx(101.25, abs=1e-9)
        assert second["required_stiffener_count"] == 11
        assert second["utilization_ratio"] == pytest.approx(0.9653, abs=1e-9)

        assert (
            validate_paginated(api.list_design_analyses(design["id"], author))[1][
                "total_count"
            ]
            == 2
        )


class TestFreightLoadCreateGuardsTheDealerVersion:
    def test_exact_equality_is_demanded_in_both_directions(self, api):
        """PRD §2.9: "If `expected_dealer_version` does not equal the dealership's current `version`,
        the request is rejected with `ERR_STALE_DEALER_VERSION` and HTTP 412."
        PRD §2.9: "A `POST /freight-loads` request — planning a freight load onto a dealer yard —
        requires `expected_dealer_version` in the request body as a mandatory, non-optional field carrying
        the client's last observed `Dealer` `version`."
        PRD §2.11: "Stale-version rejection on the two guarded creates — `ERR_STALE_DESIGN_VERSION` or
        `ERR_STALE_DEALER_VERSION`, 412."

        Design: Corner/complexity_layers/both_occ_rules_demand_exact_version_equality_and_every_guarded_write_bumps_the_parent
        """
        ref = setup_reference_data()
        opening = read_dealer(ref["alpha"]["id"])
        assert opening["staged_kit_count"] == 0

        first = validate_success(
            api.create_freight_load(
                create_freight_load_payload(ref["alpha"]["id"], opening["version"]),
                LOGISTICS,
            ),
            expected_status=201,
        )
        assert first["status"] == "PLANNED"
        after_first = read_dealer(ref["alpha"]["id"])
        assert after_first["staged_kit_count"] == 1
        assert_version_advanced_by(after_first, opening, 1, "dealer")

        validate_error(
            api.create_freight_load(
                create_freight_load_payload(ref["alpha"]["id"], opening["version"]),
                LOGISTICS,
            ),
            "ERR_STALE_DEALER_VERSION",
            412,
        )
        assert read_dealer(ref["alpha"]["id"])["staged_kit_count"] == 1

        second = validate_success(
            api.create_freight_load(
                create_freight_load_payload(ref["alpha"]["id"], after_first["version"]),
                LOGISTICS,
            ),
            expected_status=201,
        )
        assert second["status"] == "PLANNED"
        after_second = read_dealer(ref["alpha"]["id"])
        assert after_second["staged_kit_count"] == 2

        rows, meta = validate_paginated(
            api.list_freight_loads(LOGISTICS, params={"dealer_id": ref["alpha"]["id"]})
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {first["id"], second["id"]}

        # A version one GREATER than the stored value is equally stale.
        validate_error(
            api.create_freight_load(
                create_freight_load_payload(
                    ref["alpha"]["id"], after_second["version"] + 1
                ),
                LOGISTICS,
            ),
            "ERR_STALE_DEALER_VERSION",
            412,
        )


class TestListFiltersAndOffsetWalk:
    def test_filters_are_anded_and_the_window_walks_a_stable_created_at_order(self, api):
        """PRD §2.3: "`limit` controls page size: its default is 10, its minimum accepted value is 1 and
        its maximum is 100."
        PRD §2.3: "`offset` controls the starting position: its default is 0 and its minimum is 0."
        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and `has_more` in `meta`,
        where `total_count` is the number of rows matching the filter before the page window is applied,
        and `has_more` is true exactly when rows remain beyond the current window."
        PRD §2.3: "A `limit` below 1 or above 100, or a negative `offset`, is a malformed request and is
        rejected with `ERR_INVALID_REQUEST` and HTTP 400."
        PRD §3.2: "Designs may be listed and narrowed by `dealer_id`, `jurisdiction_id`,
        `grain_profile_id`, `coating_spec_id`, `author_engineer_id` or `sealed_by_engineer_id`."

        Design: Corner/complexity_layers/list_filters_combine_conjunctively_and_offset_walks_a_stable_created_at_order
        """
        scenario = setup_design_listing_set()
        ref = scenario["ref"]
        alpha_one, alpha_two, alpha_three = scenario["alpha_designs"]
        alpha_filter = {"dealer_id": ref["alpha"]["id"]}

        rows, meta = validate_paginated(
            api.list_bin_designs(ADMIN, params={**alpha_filter, "limit": 2, "offset": 0})
        )
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert [row["id"] for row in rows] == [alpha_one["id"], alpha_two["id"]]

        rows, meta = validate_paginated(
            api.list_bin_designs(ADMIN, params={**alpha_filter, "limit": 2, "offset": 2})
        )
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert [row["id"] for row in rows] == [alpha_three["id"]]

        # Past the end of the filtered set: an empty page, not a 404.
        rows, meta = validate_paginated(
            api.list_bin_designs(ADMIN, params={**alpha_filter, "limit": 2, "offset": 3})
        )
        assert rows == []
        assert meta["total_count"] == 3
        assert meta["has_more"] is False

        rows, meta = validate_paginated(api.list_bin_designs(ADMIN))
        assert meta["total_count"] == 5
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert len(rows) == 5

        author_filter = {"author_engineer_id": ref["second"]["id"]}
        rows, meta = validate_paginated(
            api.list_bin_designs(ADMIN, params=author_filter)
        )
        assert meta["total_count"] == 2
        assert rows[0]["id"] == alpha_three["id"]

        # Two filters are an AND, not an OR.
        rows, meta = validate_paginated(
            api.list_bin_designs(ADMIN, params={**alpha_filter, **author_filter})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [alpha_three["id"]]

        # A filter on a column that is null everywhere matches nothing.
        rows, meta = validate_paginated(
            api.list_bin_designs(
                ADMIN, params={"sealed_by_engineer_id": ref["sealer"]["id"]}
            )
        )
        assert rows == []
        assert meta["total_count"] == 0
        assert meta["has_more"] is False

        rows, meta = validate_paginated(api.list_bin_designs(ADMIN, params=alpha_filter))
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert len(rows) == 3

        validate_error(
            api.list_bin_designs(ADMIN, params={"limit": 0}), "ERR_INVALID_REQUEST", 400
        )
        validate_error(
            api.list_bin_designs(ADMIN, params={"limit": 101}),
            "ERR_INVALID_REQUEST",
            400,
        )


class TestAuthAndRoleOutrankEverything:
    def test_body_lookup_outranks_actor_scope_and_headers_outrank_both(self, api):
        """PRD §2.11: "Header presence and role validity, on every endpoint —
        `ERR_MISSING_AUTH_HEADERS`, 401."
        PRD §2.11: "Body foreign-key resolution, in the order the fields appear in the endpoint's input
        list, on dealership registration, design creation, coil lot receipt, run scheduling, order
        placement, freight load planning, order attachment to a load, crew registration, crew assignment
        and failure intake — again the entity-specific 404 codes."
        PRD §2.1: "If a `DesignEngineer` or `SealingEngineer` presents an `X-User-ID` that does not
        resolve to a stored `Engineer` row, the request fails with `ERR_ENGINEER_SCOPE_VIOLATION` and HTTP
        403."
        PRD §2.11: "Ownership scope for the entity-backed roles, on order placement, order confirmation,
        deposit posting, order cancellation, design creation, analysis creation, review submission,
        revision request, revision and sealing — `ERR_DEALER_SCOPE_VIOLATION` or
        `ERR_ENGINEER_SCOPE_VIOLATION`, 403."

        Design: Corner/validations/auth_and_role_outrank_everything_and_body_lookup_outranks_actor_scope
        """
        ref = setup_reference_data()
        stranger = make_design_engineer_headers("00000000-0000-0000-0000-0000000000ee")
        unknown_coating = "00000000-0000-0000-0000-0000000000cc"

        def payload(coating_spec_id):
            return create_bin_design_payload(
                ref["alpha"]["id"],
                ref["jurisdictions"]["NE-WEST"]["id"],
                ref["grain_profiles"]["CORN"]["id"],
                coating_spec_id,
            )

        # Body FK resolution (step 5) outranks actor ownership (step 6).
        validate_error(
            api.create_bin_design(payload(unknown_coating), stranger),
            "ERR_CONFIG_NOT_FOUND",
            404,
        )
        validate_error(
            api.create_bin_design(
                payload(ref["coating_specs"]["G115"]["id"]), stranger
            ),
            "ERR_ENGINEER_SCOPE_VIOLATION",
            403,
        )
        accepted = validate_success(
            api.create_bin_design(
                payload(ref["coating_specs"]["G115"]["id"]), engineer_headers(ref)
            ),
            expected_status=201,
        )
        assert accepted["author_engineer_id"] == ref["author"]["id"]

        # Step 1 outranks steps 3, 5 and 6 at once.
        validate_error(
            api.create_bin_design(
                payload(unknown_coating), headers_without_user_id("DesignEngineer")
            ),
            "ERR_MISSING_AUTH_HEADERS",
            401,
        )
        validate_error(
            api.create_bin_design(
                payload(unknown_coating), headers_for_role("YardForeman")
            ),
            "ERR_MISSING_AUTH_HEADERS",
            401,
        )

        # Step 2 outranks step 3.
        malformed = payload(ref["coating_specs"]["G115"]["id"])
        del malformed["diameter_m"]
        validate_error(
            api.create_bin_design(malformed, ADMIN), "ERR_UNAUTHORIZED_ROLE", 403
        )

        rows, meta = validate_paginated(
            api.list_bin_designs(ADMIN, params={"dealer_id": ref["alpha"]["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == accepted["id"]
