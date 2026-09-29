"""
Declared defaults, server-minted system fields, retrieval and listing shape.

Every row in this file is created through the public endpoints with the optional
inputs omitted, so the server has to supply the defaults the specification
declares and derive the aggregates that hang off them.
"""

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import get_success_data, validate_error, validate_paginated, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_2dp,
    assert_3dp,
    assert_append_only_entity,
    assert_created_at_has_three_fractional_digits,
    assert_error_envelope_shape,
    assert_ids_equal,
    assert_instant_equals,
    assert_no_id_prefix,
    assert_null,
    assert_pagination_meta,
    assert_plant_posture,
    ids_of,
)
from test_helpers.test_users import (
    GRAIN_ACCOUNTANT,
    GRAIN_BUYER,
    LOGISTICS_COORDINATOR,
    PLANT_MANAGER,
    PROCESS_OPERATOR,
    SCALE_OPERATOR,
)

_COMMISSIONED_AT = "2026-08-15T00:00:00Z"


class TestPlantCommissioningDefaults:
    """A plant registered with only its two required inputs."""

    def test_the_four_optional_inputs_take_their_declared_defaults(self, api):
        """Name and nameplate alone are enough; the rest of the row is defaulted.

        PRD 3.1: "Four further inputs are optional and carry defaults chosen for
        a typical 120-million-gallon dry mill: `base_grind_cap_bushels`, the
        unrestricted daily corn grind ceiling before posture multipliers,
        defaults to 120,000 bushels and must be positive; `coverage_floor_bushels`,
        the minimum open contracted coverage below which procurement is
        considered short, defaults to 200,000 bushels and may be zero but not
        negative; `baseline_ci_g_per_mj`, the pathway baseline carbon intensity in
        grams of carbon dioxide equivalent per megajoule before any certified
        reduction, defaults to 60.0, is carried to one decimal and must be
        positive; and `rin_generation_enabled`, defaulting to true, which when
        false suppresses renewable credit creation on batch completion entirely."

        Design: Corner/entities/plant_creation_applies_declared_defaults
        """
        fx.advance_clock(api, _COMMISSIONED_AT)

        plant = validate_success(
            api.create_plant(
                {"name": "Prairie Gold Ethanol", "nameplate_capacity_gallons": 120000000},
                PLANT_MANAGER,
            ),
            201,
        )

        assert plant["base_grind_cap_bushels"] == 120000, plant["base_grind_cap_bushels"]
        assert plant["coverage_floor_bushels"] == 200000, plant["coverage_floor_bushels"]
        assert plant["baseline_ci_g_per_mj"] == 60.0, plant["baseline_ci_g_per_mj"]
        assert plant["rin_generation_enabled"] is True, plant["rin_generation_enabled"]

        assert_no_id_prefix(plant["id"])
        assert_created_at_has_three_fractional_digits(plant["created_at"])
        assert_instant_equals(plant["created_at"], _COMMISSIONED_AT, "created_at")
        assert plant["version"] == 1, plant["version"]

    def test_every_derived_aggregate_starts_at_its_zero_value(self, api):
        """The opening balance sheet is empty and the two carbon figures are seeded.

        PRD 3.1: "Registration initialises every derived aggregate to its zero
        value — no corn, no distillers grains, no corn oil, no contracted
        coverage, and all three credit counters at zero."

        PRD 3.1: "`rolling_yield_gal_per_bushel` starts at 2.850 gallons per
        bushel, the figure that also stands in whenever no batch has yet
        completed."

        Design: Corner/entities/plant_creation_applies_declared_defaults
        """
        plant = get_success_data(
            api.create_plant(
                {"name": "Prairie Gold Ethanol", "nameplate_capacity_gallons": 120000000},
                PLANT_MANAGER,
            )
        )

        assert_2dp(plant["corn_inventory_bushels"], 0.00, "corn_inventory_bushels")
        assert_3dp(plant["ddgs_inventory_tons"], 0.000, "ddgs_inventory_tons")
        assert_2dp(plant["corn_oil_inventory_lbs"], 0.00, "corn_oil_inventory_lbs")
        assert_2dp(
            plant["open_contract_coverage_bushels"], 0.00, "open_contract_coverage_bushels"
        )
        assert plant["rin_generated_count"] == 0, plant["rin_generated_count"]
        assert plant["rin_separated_count"] == 0, plant["rin_separated_count"]
        assert plant["rin_retired_count"] == 0, plant["rin_retired_count"]

        assert_3dp(plant["rolling_yield_gal_per_bushel"], 2.850, "rolling_yield_gal_per_bushel")
        assert_3dp(plant["ci_score_g_per_mj"], 60.000, "ci_score_g_per_mj")
        assert_3dp(
            plant["lcfs_credit_tonnes_per_million_gal"],
            0.000,
            "lcfs_credit_tonnes_per_million_gal",
        )

        for mark in (
            "mark_corn_cents_per_bushel",
            "mark_ethanol_cents_per_gallon",
            "mark_natgas_cents_per_mmbtu",
            "mark_soybean_meal_usd_per_ton",
            "mark_sbo_cents_per_lb",
        ):
            assert_null(plant[mark], mark)

    def test_the_empty_contract_book_makes_the_new_plant_short_and_caps_the_grind(self, api):
        """An unfunded contract book costs the plant a quarter of its grind on day one.

        PRD 3.1: "`procurement_posture`, however, does **not** start optimistic:
        the contract book is empty, so coverage is zero, and with any non-zero
        coverage floor the plant is born `SHORT`. Under the default floor that
        makes the opening `daily_grind_cap_bushels` three quarters of the base cap
        floored to whole bushels — 90,000 with the default base."

        Design: Corner/entities/plant_creation_applies_declared_defaults
        """
        plant = get_success_data(
            api.create_plant(
                {"name": "Prairie Gold Ethanol", "nameplate_capacity_gallons": 120000000},
                PLANT_MANAGER,
            )
        )

        assert_plant_posture(
            plant,
            compliance_posture="OPEN",
            procurement_posture="SHORT",
            daily_grind_cap_bushels=90000,
        )


class TestProductTankDefaults:
    """A tank commissioned without an opening balance or a settling buffer."""

    def test_an_omitted_opening_balance_and_buffer_default_and_the_headroom_derives(self, api):
        """The empty tank is in service, holds nothing and offers all of its capacity.

        PRD 3.5: "Two inputs are optional: `opening_gallons`, the volume already
        in the tank at commissioning, defaults to 0 and must be at least zero and
        no greater than the capacity; and `settling_buffer_minutes`, defaulting to
        120, a non-negative whole number of minutes appended to the end of every
        blend window on this tank before its occupancy interval is compared with
        other reservations."

        PRD 3.5: "A new tank is `IN_SERVICE`, its `current_gallons` equal to its
        opening gallons, its `hold_reason` and `held_at` null."

        Design: Corner/entities/product_tank_creation_defaults_opening_gallons_and_settling_buffer
        """
        fx.commission_plant(api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000)
        fx.advance_clock(api, _COMMISSIONED_AT)

        tank = validate_success(
            api.create_tank(
                {
                    "tank_code": "T-101",
                    "product_type": "ETHANOL_200_PROOF",
                    "capacity_gallons": 1000000.00,
                },
                PROCESS_OPERATOR,
            ),
            201,
        )

        assert_2dp(tank["opening_gallons"], 0.00, "opening_gallons")
        assert_2dp(tank["current_gallons"], 0.00, "current_gallons")
        assert tank["settling_buffer_minutes"] == 120, tank["settling_buffer_minutes"]
        assert_2dp(tank["available_gallons"], 1000000.00, "available_gallons")
        assert tank["service_status"] == "IN_SERVICE", tank["service_status"]
        assert_null(tank["hold_reason"], "hold_reason")
        assert_null(tank["held_at"], "held_at")
        assert tank["version"] == 1, tank["version"]


class TestLoadingTrackSystemFields:
    """Identity, timestamps and defaults on a freshly commissioned track."""

    def test_the_server_mints_the_identity_quartet_and_defaults_the_two_optional_inputs(
        self, api
    ):
        """The client supplies a code and a capacity; everything else is the server's.

        PRD 2.4: "Every resource carries a server-minted `id`: a UUID string with
        no type prefix of any kind."

        PRD 3.6: "Two optional inputs follow: `loading_rate_cars_per_hour`, a
        positive one-decimal figure defaulting to 4.0 that is purely informational
        and gates nothing, and `is_active`, defaulting to true, which when false
        makes the track refuse new shipments."

        Design: Corner/entities/system_fields_are_server_generated_on_loading_track_create
        """
        fx.commission_plant(api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000)
        fx.advance_clock(api, _COMMISSIONED_AT)

        track = validate_success(
            api.create_track({"track_code": "TRK-A", "spot_capacity": 110}, LOGISTICS_COORDINATOR),
            201,
        )

        assert_no_id_prefix(track["id"])
        assert track["loading_rate_cars_per_hour"] == 4.0, track["loading_rate_cars_per_hour"]
        assert track["is_active"] is True, track["is_active"]
        assert track["committed_railcars"] == 0, track["committed_railcars"]
        assert_instant_equals(track["created_at"], _COMMISSIONED_AT, "created_at")
        assert_instant_equals(track["updated_at"], _COMMISSIONED_AT, "updated_at")
        assert track["version"] == 1, track["version"]


def _three_open_contracts(api):
    """C-1 for October and C-2 then C-3 for November, created in that order."""
    fx.commission_plant(api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000)
    fx.advance_clock(api, "2026-09-01T00:00:00Z")
    first = fx.open_contract(
        api, supplier_name="Cedar Ridge Elevator", delivery_month="2026-10",
        bushels_contracted=200000.00, basis_cents_per_bushel=-18.0,
    )
    second = fx.open_contract(
        api, supplier_name="Mill Creek Farms", delivery_month="2026-11",
        bushels_contracted=150000.00, basis_cents_per_bushel=-12.0,
    )
    third = fx.open_contract(
        api, supplier_name="Two Rivers Grain", delivery_month="2026-11",
        bushels_contracted=90000.00, basis_cents_per_bushel=-9.0,
    )
    return {"first": first, "second": second, "third": third}


class TestCornContractRetrieval:
    """The stored row comes back exactly as it was opened."""

    def test_a_fresh_contract_reads_back_open_unpriced_and_undelivered(self, api):
        """Both state dimensions and every pricing field are at their opening values.

        PRD 3.2: "A new contract opens with `status` at `OPEN`, `pricing_status` at
        `UNPRICED`, `bushels_delivered` at 0 and both
        `futures_price_cents_per_bushel` and `priced_at` null."

        Design: Corner/entities/corn_contract_retrieval_returns_the_stored_row
        """
        fx.commission_plant(api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000)
        fx.advance_clock(api, "2026-09-01T00:00:00Z")
        created = fx.open_contract(
            api, supplier_name="Cedar Ridge Elevator", delivery_month="2026-10",
            bushels_contracted=200000.00, basis_cents_per_bushel=-18.0,
        )

        fetched = validate_success(api.get_contract(created["id"], GRAIN_ACCOUNTANT), 200)

        assert_ids_equal(fetched["id"], created["id"], "id")
        assert fetched["status"] == "OPEN", fetched["status"]
        assert fetched["pricing_status"] == "UNPRICED", fetched["pricing_status"]
        assert_2dp(fetched["bushels_contracted"], 200000.00, "bushels_contracted")
        assert_2dp(fetched["bushels_delivered"], 0.00, "bushels_delivered")
        assert fetched["basis_cents_per_bushel"] == -18.0, fetched["basis_cents_per_bushel"]
        assert_null(fetched["futures_price_cents_per_bushel"], "futures_price_cents_per_bushel")
        assert_null(fetched["priced_at"], "priced_at")
        assert_null(fetched["rolled_from_contract_id"], "rolled_from_contract_id")


class TestCornContractListing:
    """Page windows, ordering and the four pagination fields."""

    def test_the_first_page_is_two_rows_in_creation_order_with_more_to_come(self, api):
        """total_count counts the whole match set, not the page.

        PRD 2.3: "Four pagination fields appear in the `meta` object of every list
        response — `limit`, `offset`, `total_count` and `has_more` — where
        `total_count` is the number of records matching the filters before the page
        window is applied, and `has_more` is true when records remain beyond the
        current window."

        PRD 2.3: "Unless a list endpoint's own description in §4 names a different
        ordering, results are sorted by `created_at` ascending."

        Design: Corner/entities/corn_contract_listing_paginates_with_envelope_metadata
        """
        contracts = _three_open_contracts(api)

        rows, meta = validate_paginated(
            api.list_contracts(GRAIN_BUYER, {"limit": 2, "offset": 0})
        )

        assert len(rows) == 2, rows
        assert_pagination_meta(meta, limit=2, offset=0, total_count=3, has_more=True)
        assert ids_of(rows) == [contracts["first"]["id"], contracts["second"]["id"]], ids_of(rows)

    def test_the_last_page_holds_the_single_remaining_row_and_stops(self, api):
        """Offset two leaves one row, so has_more turns false.

        PRD 2.3: "`offset` controls the starting position within the result set,
        defaults to 0, and has a minimum of 0."

        Design: Corner/entities/corn_contract_listing_paginates_with_envelope_metadata
        """
        contracts = _three_open_contracts(api)

        rows, meta = validate_paginated(
            api.list_contracts(GRAIN_BUYER, {"limit": 2, "offset": 2})
        )

        assert len(rows) == 1, rows
        assert_pagination_meta(meta, limit=2, offset=2, total_count=3, has_more=False)
        assert ids_of(rows) == [contracts["third"]["id"]], ids_of(rows)

    def test_a_delivery_month_filter_narrows_the_count_before_the_window_applies(self, api):
        """Filtering to November drops C-1 out of total_count entirely.

        PRD 3.2: "Contracts are discoverable through a filtered list that accepts
        `status`, `delivery_month`, `pricing_status` and `rolled_from_contract_id`,
        the last of which is what makes the self-referential roll chain navigable
        in both directions."

        Design: Corner/entities/corn_contract_listing_paginates_with_envelope_metadata
        """
        contracts = _three_open_contracts(api)

        rows, meta = validate_paginated(
            api.list_contracts(
                GRAIN_BUYER, {"limit": 2, "offset": 0, "delivery_month": "2026-11"}
            )
        )

        assert_pagination_meta(meta, limit=2, offset=0, total_count=2, has_more=False)
        assert ids_of(rows) == [contracts["second"]["id"], contracts["third"]["id"]], ids_of(rows)


class TestForeignAndMissingReferences:
    """An id of the wrong type is a miss, not a lucky hit."""

    def test_reading_a_contract_by_the_plants_id_is_a_contract_miss(self, api):
        """Each entity owns its own not-found code, so the contract code is reported.

        PRD 2.5: "Each entity has its own not-found code, and they are checked in a
        fixed order: plant (`ERR_PLANT_NOT_FOUND`), corn purchase contract
        (`ERR_CONTRACT_NOT_FOUND`), corn delivery (`ERR_DELIVERY_NOT_FOUND`),
        fermentation batch (`ERR_BATCH_NOT_FOUND`), product tank
        (`ERR_TANK_NOT_FOUND`), denaturant blend (`ERR_BLEND_NOT_FOUND`), loading
        track (`ERR_TRACK_NOT_FOUND`), unit train shipment
        (`ERR_SHIPMENT_NOT_FOUND`), co-product sale (`ERR_SALE_NOT_FOUND`), RIN
        batch (`ERR_RIN_BATCH_NOT_FOUND`), carbon project
        (`ERR_CARBON_PROJECT_NOT_FOUND`), hedge position
        (`ERR_HEDGE_POSITION_NOT_FOUND`) and permit condition
        (`ERR_PERMIT_CONDITION_NOT_FOUND`)."

        Design: Corner/entities/corn_contract_not_found_on_foreign_id
        """
        plant = fx.commission_plant(
            api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000
        )

        response = api.get_contract(plant["id"], GRAIN_BUYER)
        validate_error(response, ApiErrorId.CONTRACT_NOT_FOUND, 404)
        assert_error_envelope_shape(response.json())

    def test_booking_a_ticket_under_a_non_contract_id_reports_the_missing_contract(self, api):
        """The path resolves before the body is looked at, so no orphan load appears.

        PRD 2.5: "Path segments are resolved strictly left to right, so the outer
        resource must exist before the inner one is looked at, and the outermost
        missing reference is the one reported."

        Design: Corner/entities/delivery_create_requires_existing_parent_contract
        """
        plant = fx.commission_plant(
            api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000
        )

        validate_error(
            api.create_delivery(
                plant["id"],
                {"ticket_number": "TK-0001", "gross_weight_lbs": 78640, "tare_weight_lbs": 26000.00},
                SCALE_OPERATOR,
            ),
            ApiErrorId.CONTRACT_NOT_FOUND,
            404,
        )

        rows, meta = validate_paginated(api.list_contracts(GRAIN_BUYER))
        assert rows == [], rows
        assert meta["total_count"] == 0, meta["total_count"]


class TestRequestShapeOnDeliveryCreation:
    """Shape failures leave the contract and its sub-collection untouched."""

    def test_a_ticket_without_its_gross_weight_is_refused_and_books_nothing(self, api):
        """The required weight is missing, so the request never reaches the domain.

        PRD 2.9: "**Request shape** — `ERR_VALIDATION`. The body must conform to the
        endpoint's input contract: every required field present, types correct, enum
        members recognised, numeric ranges and decimal precision respected, month
        strings well formed as four digits, a hyphen and a month between 01 and 12,
        instants well formed as ISO 8601 UTC, `window_end` strictly after
        `window_start`, quantities and gallon and contract counts strictly positive,
        `index_pct` present exactly when `pricing_basis` is `INDEX` and absent when
        it is `FLAT`, and unknown fields rejected outright."

        Design: Corner/entities/delivery_create_missing_required_gross_weight_rejected
        """
        fx.commission_plant(api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000)
        contract = fx.open_contract(
            api, supplier_name="Cedar Ridge Elevator", delivery_month="2026-10",
            bushels_contracted=200000.00, basis_cents_per_bushel=-18.0,
        )

        validate_error(
            api.create_delivery(
                contract["id"],
                {"ticket_number": "TK-0001", "tare_weight_lbs": 26000.00},
                SCALE_OPERATOR,
            ),
            ApiErrorId.VALIDATION,
            400,
        )

        rows, _ = validate_paginated(api.list_contract_deliveries(contract["id"], SCALE_OPERATOR))
        assert rows == [], rows

        after = get_success_data(api.get_contract(contract["id"], GRAIN_BUYER))
        assert after["version"] == 1, after["version"]

    def test_supplying_the_computed_net_dry_bushels_is_an_unknown_field(self, api):
        """A computed figure is not an input, so the client's value is rejected outright.

        PRD 3.3: "A booked load lands at `grading_status` `PENDING_GRADE` with every
        quality reading, bushel figure, discount component and money field null."

        Design: Corner/entities/delivery_create_extra_field_net_dry_bushels_rejected
        """
        fx.commission_plant(api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000)
        contract = fx.open_contract(
            api, supplier_name="Cedar Ridge Elevator", delivery_month="2026-10",
            bushels_contracted=200000.00, basis_cents_per_bushel=-18.0,
        )

        validate_error(
            api.create_delivery(
                contract["id"],
                {
                    "ticket_number": "TK-0001",
                    "gross_weight_lbs": 78640,
                    "tare_weight_lbs": 26000.00,
                    "net_dry_bushels": 9999.00,
                },
                SCALE_OPERATOR,
            ),
            ApiErrorId.VALIDATION,
            400,
        )

        rows, _ = validate_paginated(api.list_contract_deliveries(contract["id"], SCALE_OPERATOR))
        assert rows == [], rows


class TestProductTypeEnum:
    """Only the three declared product types are admissible."""

    def test_an_unrecognised_product_type_is_refused_and_leaves_the_code_free(self, api):
        """GASOLINE is not a member of the enum, and nothing is written under that code.

        PRD 3.5: "A `ProcessOperator` commissions a tank with a globally unique
        `tank_code` such as T-101, a `product_type` that is one of
        `ETHANOL_200_PROOF`, `DENATURANT` or `DENATURED_E100`, and a positive
        working `capacity_gallons` carried to two decimals."

        Design: Corner/entities/product_tank_unknown_product_type_enum_rejected
        """
        fx.commission_plant(api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000)

        validate_error(
            api.create_tank(
                {"tank_code": "T-999", "product_type": "GASOLINE", "capacity_gallons": 1000000.00},
                PROCESS_OPERATOR,
            ),
            ApiErrorId.VALIDATION,
            400,
        )

        # The code is still free: a duplicate would be refused with ERR_DUPLICATE_CODE.
        reused = validate_success(
            api.create_tank(
                {
                    "tank_code": "T-999",
                    "product_type": "ETHANOL_200_PROOF",
                    "capacity_gallons": 1000000.00,
                },
                PROCESS_OPERATOR,
            ),
            201,
        )
        assert reused["tank_code"] == "T-999", reused["tank_code"]


class TestHealthReadingIsAppendOnly:
    """A fermentation health reading is written once and never touched again."""

    def test_the_reading_carries_only_an_id_and_a_created_at_and_stays_listable(self, api):
        """No version, no updated_at, and the batch keeps it in its reading list.

        PRD 2.4: "Two entities are exceptions because they are strictly
        append-only: a **fermentation health reading** and a **permit reading** are
        immutable once written, are never updated and are never deleted, so both
        carry only `id` and `created_at` — they have no `updated_at` and no
        `version` at all, and there is no endpoint that modifies either."

        Design: Corner/entities/fermentation_health_reading_is_immutable_and_versionless
        """
        fx.commission_plant(api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000)
        fx.advance_clock(api, "2026-09-01T00:00:00Z")
        tank = fx.commission_tank(
            api, "T-101", "ETHANOL_200_PROOF", 1000000.00, opening_gallons=0.00
        )
        contract = fx.priced_contract(api, 458.0, supplier_name="Cedar Ridge Elevator")
        fx.settled_load(api, contract["id"])
        batch = fx.charge_batch(
            api, tank["id"], batch_code="FB-1", corn_bushels_charged=900.00,
            charge_test_weight_lb_per_bu=54.0,
        )

        reading = validate_success(
            api.create_health_reading(batch["id"], f.health_reading_payload(), PROCESS_OPERATOR),
            201,
        )

        assert_append_only_entity(reading)
        assert_ids_equal(reading["batch_id"], batch["id"], "batch_id")
        assert_2dp(reading["reading_score"], 100.00, "reading_score")

        rows, meta = validate_paginated(
            api.list_health_readings(batch["id"], PLANT_MANAGER)
        )
        assert ids_of(rows) == [reading["id"]], ids_of(rows)
        assert meta["total_count"] == 1, meta["total_count"]
