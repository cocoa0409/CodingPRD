"""Persisted shapes: creation defaults, computed fields and code uniqueness.

Every resource in this service is either versioned or immutable, every derived
figure is server-owned, and codes are unique only inside the scope the contract
gives them.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_DUPLICATE_CODE,
    ERR_INVALID_REQUEST,
    ERR_PLANT_NOT_FOUND,
    ERR_TRAIN_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_gas_price,
    assert_hours,
    assert_identity_fields,
    assert_immutable_entity,
    assert_integer,
    assert_money,
    assert_pct,
    assert_position,
    assert_request_meta,
    assert_response_type,
    assert_status,
    assert_tons,
    assert_versioned_entity,
)
from test_helpers.constants import UNKNOWN_UUID
from test_helpers.test_users import ADMIN, COMMERCIAL, ENGINEER, LOGISTICS_HEADERS


class TestPlantCreation:
    def test_a_new_plant_echoes_its_inputs_and_seeds_every_default(self, api):
        """A plant opens active, current, unrestricted and unhedged at version 1.

        Design: Corner/entities/plant_created_with_required_fields_returns_201_and_defaults
        """
        payload = f.plant_payload(
            name="Yazoo City Complex",
            permit_limit_tons_30d=12.00,
            spot_gas_index_usd_per_mmbtu=4.2000,
        )

        response = api.create_plant(payload, ADMIN)
        plant = validate_success(response, 201)

        assert_request_meta(response)
        assert_response_type(response, "object")
        assert plant["name"] == "Yazoo City Complex"
        assert plant["site_code"] == payload["site_code"]
        assert_money(plant["permit_limit_tons_30d"], 12.00, "plant.permit_limit_tons_30d")
        assert_gas_price(
            plant["spot_gas_index_usd_per_mmbtu"],
            4.2000,
            "plant.spot_gas_index_usd_per_mmbtu",
        )
        assert_status(plant, "ACTIVE", field="permit_status", label="plant")
        assert_status(plant, "CURRENT", field="psm_program_status", label="plant")
        assert_status(plant, "NORMAL", field="operating_posture", label="plant")
        assert plant["exceeded_pollutants"] == []
        assert plant["hedged_blend_usd_per_mmbtu"] is None
        assert_versioned_entity(plant, expected_version=1, label="plant")

    def test_client_supplied_identity_and_version_are_discarded(self, api):
        """A caller cannot choose its own id or pre-set its own version.

        Design: Corner/entities/plant_id_and_created_at_client_input_ignored
        """
        forged_id = "11111111-1111-4111-8111-111111111111"

        plant = validate_success(
            api.create_plant(
                f.plant_payload(id=forged_id, version=77),
                ADMIN,
            ),
            201,
        )

        assert plant["id"] != forged_id
        assert_versioned_entity(plant, expected_version=1, label="plant")
        assert_identity_fields(plant, "plant")
        assert plant["updated_at"] == plant["created_at"]

    def test_the_forged_identity_names_no_plant_at_all(self, api):
        """Nothing was ever written under the id the caller tried to claim.

        Design: Corner/entities/plant_id_and_created_at_client_input_ignored
        """
        forged_id = "11111111-1111-4111-8111-111111111111"
        validate_success(
            api.create_plant(f.plant_payload(id=forged_id, version=77), ADMIN), 201
        )

        validate_error(api.get_plant(forged_id, ADMIN), ERR_PLANT_NOT_FOUND, 404)


class TestReformerTrainRepresentation:
    def test_reading_a_train_back_returns_what_was_stored(self, api):
        """A fresh train is idle, carries no charge and sits at version 1.

        Design: Corner/entities/reformer_train_get_by_id_returns_stored_fields
        """
        plant = fx.register_plant(api)
        created = fx.commission_train(api, plant["id"], rated_ammonia_tpd=1200.0)

        response = api.get_reformer_train(created["id"], ENGINEER)
        train = validate_success(response, 200)

        assert train["plant_id"] == plant["id"]
        assert train["train_code"] == created["train_code"]
        assert_tons(train["rated_ammonia_tpd"], 1200.000, "train.rated_ammonia_tpd")
        assert_status(train, "IDLE", label="train")
        assert train["active_charge_id"] is None
        assert_versioned_entity(train, expected_version=1, label="train")

    def test_a_train_needs_its_rated_capacity(self, api):
        """Omitting the rated tonnage is a malformed request, not a default.

        Design: Corner/entities/create_reformer_train_missing_required_rated_ammonia_tpd
        """
        plant = fx.register_plant(api)

        response = api.create_reformer_train(
            {"plant_id": plant["id"], "train_code": "RT1"}, ENGINEER
        )
        validate_error(response, ERR_INVALID_REQUEST, 422)

        _, meta = validate_paginated(
            api.list_reformer_trains(ENGINEER, plant_id=plant["id"])
        )
        assert meta["total_count"] == 0, (
            f"expected no trains on the plant, got {meta['total_count']}"
        )

    def test_a_train_code_is_unique_only_within_its_own_plant(self, api):
        """The same code on a second plant is accepted.

        Design: Corner/entities/train_code_unique_per_plant_but_repeatable_across_plants
        """
        first = fx.register_plant(api, name="Yazoo City Complex")
        second = fx.register_plant(api, name="Donaldsonville Complex")
        fx.commission_train(
            api, first["id"], train_code="RT1", rated_ammonia_tpd=1200.0
        )

        response = api.create_reformer_train(
            f.reformer_train_payload(
                second["id"], train_code="RT1", rated_ammonia_tpd=900.0
            ),
            ENGINEER,
        )
        twin = validate_success(response, 201)
        assert twin["plant_id"] == second["id"]
        assert twin["train_code"] == "RT1"

    def test_a_train_code_may_not_repeat_inside_one_plant(self, api):
        """The second attempt on the same plant is a duplicate code.

        Design: Corner/entities/train_code_unique_per_plant_but_repeatable_across_plants
        """
        first = fx.register_plant(api, name="Yazoo City Complex")
        second = fx.register_plant(api, name="Donaldsonville Complex")
        fx.commission_train(
            api, first["id"], train_code="RT1", rated_ammonia_tpd=1200.0
        )
        validate_success(
            api.create_reformer_train(
                f.reformer_train_payload(
                    second["id"], train_code="RT1", rated_ammonia_tpd=900.0
                ),
                ENGINEER,
            ),
            201,
        )

        response = api.create_reformer_train(
            f.reformer_train_payload(
                first["id"], train_code="RT1", rated_ammonia_tpd=1500.0
            ),
            ENGINEER,
        )
        validate_error(response, ERR_DUPLICATE_CODE, 409)

        for plant in (first, second):
            _, meta = validate_paginated(
                api.list_reformer_trains(ENGINEER, plant_id=plant["id"])
            )
            assert meta["total_count"] == 1, (
                f"expected one train per plant, got {meta['total_count']}"
            )


class TestProductionRunListing:
    def _three_campaigns(self, api):
        site = fx.commissioned_site(
            api,
            rated_ammonia_tpd=1200.0,
            design_life_hours=40000.0,
            baseline_operating_hours=0.0,
            poisoning_index=0.00,
        )
        windows = (
            ("2026-09-01T00:00:00.000Z", "2026-09-06T00:00:00.000Z"),
            ("2026-09-06T00:00:00.000Z", "2026-09-11T00:00:00.000Z"),
            ("2026-09-11T00:00:00.000Z", "2026-09-16T00:00:00.000Z"),
        )
        for start, end in windows:
            fx.schedule_run(
                api,
                site["train"]["id"],
                window_start=start,
                window_end=end,
                target_ammonia_tons=1000.000,
            )
        return site

    def test_the_first_page_reports_the_whole_count_and_promises_more(self, api):
        """Two of three campaigns come back with has_more still set.

        Design: Corner/entities/production_runs_list_paginates_with_total_count_and_has_more
        """
        site = self._three_campaigns(api)

        response = api.list_production_runs(
            ENGINEER, train_id=site["train"]["id"], limit=2, offset=0
        )
        runs, meta = validate_paginated(response)

        assert_response_type(response, "array")
        assert meta["total_count"] == 3, (
            f"expected three campaigns, got {meta['total_count']}"
        )
        assert meta["has_more"] is True
        assert len(runs) == 2, f"expected a page of two, got {len(runs)}"

    def test_the_last_page_holds_the_remainder_and_promises_nothing(self, api):
        """The tail page carries one campaign and closes the walk.

        Design: Corner/entities/production_runs_list_paginates_with_total_count_and_has_more
        """
        site = self._three_campaigns(api)

        runs, meta = validate_paginated(
            api.list_production_runs(
                ENGINEER, train_id=site["train"]["id"], limit=2, offset=2
            )
        )

        assert meta["total_count"] == 3, (
            f"expected three campaigns, got {meta['total_count']}"
        )
        assert meta["has_more"] is False
        assert len(runs) == 1, f"expected a page of one, got {len(runs)}"


class TestUnknownIdentifiers:
    def test_an_unknown_plant_id_is_a_not_found_error_envelope(self, api):
        """A well-formed but unused UUID names no plant.

        Design: Corner/entities/get_plant_with_unknown_uuid_returns_plant_not_found
        """
        response = api.get_plant(UNKNOWN_UUID, ADMIN)

        validate_error(response, ERR_PLANT_NOT_FOUND, 404)
        assert_response_type(response, "error")

    def test_a_charge_cannot_be_installed_on_a_train_that_does_not_exist(self, api):
        """The parent train is resolved before anything is written.

        Design: Corner/entities/create_catalyst_charge_with_unknown_train_id_not_found
        """
        fx.register_plant(api)

        response = api.create_catalyst_charge(
            {
                "train_id": "22222222-2222-4222-8222-222222222222",
                "charge_code": "CC1",
                "design_life_hours": 40000.0,
            },
            ENGINEER,
        )
        validate_error(response, ERR_TRAIN_NOT_FOUND, 404)

        _, meta = validate_paginated(api.list_catalyst_charges(ENGINEER))
        assert meta["total_count"] == 0, (
            f"expected no charges to exist, got {meta['total_count']}"
        )


class TestCatalystChargeDefaults:
    def test_omitting_the_optional_seeds_starts_the_charge_brand_new(self, api):
        """An unseeded charge is fully active with both readings at 100.00.

        Design: Corner/entities/catalyst_charge_omitted_optional_inputs_apply_zero_defaults
        """
        plant = fx.register_plant(api)
        train = fx.commission_train(api, plant["id"], rated_ammonia_tpd=1200.0)

        response = api.create_catalyst_charge(
            {
                "train_id": train["id"],
                "charge_code": "CC1",
                "design_life_hours": 40000.0,
            },
            ENGINEER,
        )
        charge = validate_success(response, 201)

        assert_hours(
            charge["baseline_operating_hours"], 0, "charge.baseline_operating_hours"
        )
        assert_pct(charge["poisoning_index"], 0.00, "charge.poisoning_index")
        assert_integer(charge["regeneration_count"], 0, "charge.regeneration_count")
        assert_hours(
            charge["cumulative_operating_hours"],
            0,
            "charge.cumulative_operating_hours",
        )
        assert_pct(
            charge["calendar_activity_pct"], 100.00, "charge.calendar_activity_pct"
        )
        assert_pct(charge["activity_pct"], 100.00, "charge.activity_pct")
        assert_status(charge, "ACTIVE", label="charge")

    def test_installing_a_charge_mounts_it_on_its_train(self, api):
        """The train names the charge it is carrying.

        Design: Corner/entities/catalyst_charge_omitted_optional_inputs_apply_zero_defaults
        """
        plant = fx.register_plant(api)
        train = fx.commission_train(api, plant["id"], rated_ammonia_tpd=1200.0)

        charge = validate_success(
            api.create_catalyst_charge(
                {
                    "train_id": train["id"],
                    "charge_code": "CC1",
                    "design_life_hours": 40000.0,
                },
                ENGINEER,
            ),
            201,
        )

        mounted = validate_success(api.get_reformer_train(train["id"], ENGINEER))
        assert mounted["active_charge_id"] == charge["id"]


class TestStorageAssetRepresentation:
    def test_a_client_supplied_counted_position_is_ignored(self, api):
        """The four position figures are server-owned and start at zero.

        Design: Corner/entities/storage_asset_on_hand_tons_input_ignored
        """
        plant = fx.register_plant(api)

        response = api.create_storage_asset(
            {
                "plant_id": plant["id"],
                "asset_code": "UT1",
                "asset_kind": "TANK",
                "product_code": "UREA",
                "capacity_tons": 20000.000,
                "security_class": "BASIC",
                "on_hand_tons": 9999,
            },
            LOGISTICS_HEADERS,
        )
        asset = validate_success(response, 201)

        assert_tons(asset["opening_balance_tons"], 0.000, "asset.opening_balance_tons")
        assert_position(
            asset,
            on_hand=0.000,
            reserved=0.000,
            seasonal_reserve=0.000,
            available=0.000,
            label="asset",
        )
        assert_pct(asset["seasonal_reserve_pct"], 0.00, "asset.seasonal_reserve_pct")

    def test_an_asset_kind_outside_the_declared_set_is_refused(self, api):
        """A silo is not one of the kinds this service knows.

        Design: Corner/entities/create_storage_asset_with_unknown_asset_kind_invalid_enum
        """
        plant = fx.register_plant(api)

        response = api.create_storage_asset(
            {
                "plant_id": plant["id"],
                "asset_code": "UT1",
                "asset_kind": "SILO",
                "product_code": "UREA",
                "capacity_tons": 20000.000,
                "security_class": "BASIC",
            },
            LOGISTICS_HEADERS,
        )
        validate_error(response, ERR_INVALID_REQUEST, 422)

        _, meta = validate_paginated(
            api.list_storage_assets(LOGISTICS_HEADERS, plant_id=plant["id"])
        )
        assert meta["total_count"] == 0, (
            f"expected no assets on the plant, got {meta['total_count']}"
        )


class TestImmutableRecords:
    def test_a_product_line_carries_no_version_and_no_update_stamp(self, api):
        """A slate definition is written once and never revised.

        Design: Corner/entities/product_line_is_immutable_with_no_version_and_no_updated_at
        """
        plant = fx.register_plant(api)
        line = fx.define_product_line(
            api,
            plant["id"],
            product_code="UREA",
            ammonia_tons_per_product_ton=0.580,
            conversion_cost_usd_per_ton=38.000,
            regulated=False,
            priority_rank=1,
        )

        stored = validate_success(api.get_product_line(line["id"], COMMERCIAL), 200)
        assert_immutable_entity(stored, "product line")

    def test_an_emissions_reading_carries_no_version_and_no_update_stamp(self, api):
        """A monitoring reading is an event record, not an editable row.

        Design: Corner/entities/product_line_is_immutable_with_no_version_and_no_updated_at
        """
        plant = fx.register_plant(api)
        reading = fx.ingest_reading(
            api,
            plant["id"],
            pollutant="NOX",
            rate_lb_per_hour=5.0,
            interval_hours=24.0,
            reading_at="2026-07-15T00:00:00.000Z",
        )

        stored = validate_success(api.get_emissions_reading(reading["id"], ADMIN), 200)
        assert_immutable_entity(stored, "emissions reading")
