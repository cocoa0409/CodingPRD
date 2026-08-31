"""Master-data creation, envelope shape, listing, path resolution and role gates."""

import pytest

from test_helpers import (
    CLOCK_BASE,
    CLOCK_BASE_ISO,
    CLOCK_DEFAULT_ISO,
    QC_TECH_ID,
    STANDARD_PREDICTED_KV100,
    ApiErrorId,
    TEST_USERS,
    assert_bare_uuid,
    assert_component_lot,
    assert_customer,
    assert_recipe_component,
    create_active_config,
    create_active_spec,
    create_batch,
    create_component_lot,
    create_config,
    create_recipe,
    is_iso8601_timestamp,
    make_qc_technician_headers,
    set_clock,
    setup_active_formulation,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["product_manager_headers"]
OPERATOR = TEST_USERS["blend_operator_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
SALES = TEST_USERS["sales_rep_headers"]
QM = TEST_USERS["quality_manager_headers"]
QC = TEST_USERS["qc_technician_headers"]

MISSING_UUID = "00000000-0000-4000-8000-000000000000"


class TestAccountAndMaterialCreation:
    def test_customer_registration_initialises_ledger_and_agreement(self, api):
        """PRD 3.9: "On registration `takeback_credit_balance_cents` is initialised to 0
        and `last_credit_event_at` is null until the first credit event on the account."
        PRD 3.9: "An optional `takeback_agreement_status` may be supplied and defaults to
        `NONE`; the other permitted values are `ACTIVE` and `SUSPENDED`."
        PRD 2.4: "Every persisted resource carries an `id` that is a server-minted UUID
        with no type prefix of any kind."
        PRD 2.4: "The server maintains a **logical clock** which reads exactly
        `2026-08-01T00:00:00Z` before it is first set and never falls back to real time
        thereafter."

        Design: Corner/entities/customer_creation_returns_system_and_default_fields
        """
        response = api.create_customer(
            {
                "name": "Delta Lubricants",
                "customer_type": "DISTRIBUTOR",
                "contract_tier": "TIER_C",
                "credit_limit_cents": 250000,
            },
            ADMIN,
        )
        customer = validate_success(response, 201)
        assert_customer(customer)

        assert customer["version"] == 1, "a freshly created resource begins at version 1"
        assert customer["takeback_credit_balance_cents"] == 0
        assert customer["takeback_agreement_status"] == "NONE"
        assert customer["last_credit_event_at"] is None
        assert_bare_uuid(customer["id"])
        assert customer["created_at"] == CLOCK_DEFAULT_ISO, (
            "created_at must be stamped from the logical clock's fixed default instant"
        )

    def test_component_lot_defaults_when_optional_fields_are_omitted(self, api):
        """PRD 3.3: "The `additive_family` may be supplied and defaults to `NONE`."
        PRD 3.3: "A `coa_viscosity_verified` flag records whether the incoming certificate
        viscosity was independently re-tested; it defaults to true, and when it is false it
        will force any batch drawing from this lot to be ineligible for approval claims."
        PRD 3.3: "On receipt, `available_kg` is initialised to `received_kg`, `status` is
        initialised to `AVAILABLE`, and `quarantine_reason` is null."

        Design: Corner/entities/component_lot_defaults_applied_when_optional_fields_omitted
        """
        set_clock(CLOCK_BASE)

        response = api.create_component_lot(
            {
                "component_type": "BASE_OIL",
                "component_code": "GRP2-150N",
                "received_kg": 400.0,
                "unit_cost_cents_per_kg": 210,
                "kv100_cst": 5.200,
                "density_kg_per_l": 0.855,
            },
            ADMIN,
        )
        lot = validate_success(response, 201)
        assert_component_lot(lot)

        assert lot["additive_family"] == "NONE"
        assert lot["coa_viscosity_verified"] is True
        assert lot["status"] == "AVAILABLE"
        assert lot["available_kg"] == pytest.approx(400.000, abs=0.001)
        assert lot["quarantine_reason"] is None

    def test_product_spec_without_target_viscosity_is_an_invalid_request(self, api):
        """PRD 2.6: "Request shape — every required body field is present, every enumerated
        value is a declared member, every numeric field satisfies its declared range, and
        every datetime parses as ISO 8601 UTC; otherwise `ERR_INVALID_REQUEST` (400)."
        PRD 3.1: "Creating one supplies a `product_code`, which must be unique across every
        specification ever created, an `sae_grade` label such as 0W-20, a nominal
        `target_kv100_cst` giving the intended kinematic viscosity at 100 degrees Celsius in
        centistokes, a symmetric `kv100_tolerance_pct` expressing the half-width of the
        acceptance band as a percentage of that target, a `min_additive_treat_pct` naming the
        smallest total additive-package mass fraction any recipe for the product may carry, a
        `base_stock_group` drawn from `GROUP_I`, `GROUP_II`, `GROUP_III` and `GROUP_IV`, and an
        `additive_family` drawn from `ZDDP_PCMO`, `LOW_SAPS`, `HDEO_API_CK4`, `GEAR_EP` and
        `FOOD_GRADE_H1`."

        Design: Corner/entities/product_spec_missing_required_field_returns_invalid_request
        """
        response = api.create_product_spec(
            {
                "product_code": "LUBE-0W20-SP",
                "sae_grade": "0W-20",
                "kv100_tolerance_pct": 3.0,
                "min_additive_treat_pct": 8.00,
                "base_stock_group": "GROUP_II",
                "additive_family": "ZDDP_PCMO",
            },
            PM,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

        _, meta = validate_paginated(api.list_product_specs(PM))
        assert meta["total_count"] == 0, "a rejected create must leave no specification behind"

    def test_package_type_outside_the_declared_enumeration_is_rejected(self, api):
        """PRD 2.6: "Request shape — every required body field is present, every enumerated
        value is a declared member, every numeric field satisfies its declared range, and
        every datetime parses as ISO 8601 UTC; otherwise `ERR_INVALID_REQUEST` (400)."
        PRD 3.6: "A `ProductManager` creates one naming the `product_spec_id` being packaged,
        a `package_type` from `BULK`, `IBC_1000L`, `DRUM_205L`, `PAIL_20L` and `CASE_12X1L`, a
        `label_brand` printed on the label, and a `fill_volume_l` greater than zero giving the
        litres delivered per ordered unit."

        Design: Corner/entities/package_type_enum_rejects_unknown_member
        """
        set_clock(CLOCK_BASE)
        spec = create_active_spec()

        response = api.create_package_configuration(
            {
                "product_spec_id": spec["id"],
                "package_type": "TOTE_500L",
                "label_brand": "House Tote",
                "fill_volume_l": 500.0,
            },
            PM,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

        _, meta = validate_paginated(
            api.list_package_configurations(PM, {"product_spec_id": spec["id"]})
        )
        assert meta["total_count"] == 0, "a rejected create must leave no configuration behind"

    def test_recipe_creation_resolves_its_specification_reference_first(self, api):
        """PRD 2.5: "The same identifiers are used when a reference supplied inside a request
        body fails to resolve. Body-level reference resolution applies to recipe creation,
        batch creation, batch charging, package-configuration creation, packaging-run
        scheduling, order creation, order-line creation, take-back collection scheduling and
        approval-claim creation; in each case a `customer_id`, `product_spec_id`,
        `blend_recipe_id`, `blend_tank_id`, `blend_batch_id`, `package_configuration_id`,
        `packaging_line_id` or `order_id` that names no existing row produces the corresponding
        not-found identifier with HTTP 404."
        PRD 2.6: "5. Body reference existence — every reference supplied in the request body
        resolves; otherwise the matching not-found identifier (404)."

        Design: Corner/entities/blend_recipe_requires_existing_product_spec_parent
        """
        response = api.create_blend_recipe(
            {
                "product_spec_id": MISSING_UUID,
                "total_mass_basis_kg": 1000.0,
                "components": [
                    {
                        "component_code": "GRP2-150N",
                        "component_type": "BASE_OIL",
                        "mass_fraction_pct": 100.00,
                        "nominal_kv100_cst": 5.200,
                        "additive_family": "NONE",
                    }
                ],
            },
            PM,
        )
        error = validate_error(response, ApiErrorId.ERR_PRODUCT_SPEC_NOT_FOUND.value, 404)
        assert error["error_id"] != ApiErrorId.ERR_RECIPE_FRACTION_SUM.value


class TestReadsAndListings:
    def test_reading_an_unknown_vessel_reports_it_as_missing(self, api):
        """PRD 2.5: "Each resource kind has its own not-found identifier:
        `ERR_CUSTOMER_NOT_FOUND`, `ERR_COMPONENT_LOT_NOT_FOUND`, `ERR_PRODUCT_SPEC_NOT_FOUND`,
        `ERR_BLEND_RECIPE_NOT_FOUND`, `ERR_BLEND_TANK_NOT_FOUND`, `ERR_BLEND_BATCH_NOT_FOUND`,
        `ERR_RETAIN_SAMPLE_NOT_FOUND`, `ERR_APPROVAL_CLAIM_NOT_FOUND`,
        `ERR_PACKAGE_CONFIGURATION_NOT_FOUND`, `ERR_PACKAGING_LINE_NOT_FOUND`,
        `ERR_PACKAGING_RUN_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
        `ERR_TAKEBACK_COLLECTION_NOT_FOUND` and `ERR_SPEC_CHANGE_REQUEST_NOT_FOUND`. All of
        them carry HTTP 404."

        Design: Corner/entities/blend_tank_not_found_returns_404
        """
        response = api.get_blend_tank(MISSING_UUID, OPERATOR)
        validate_error(response, ApiErrorId.ERR_BLEND_TANK_NOT_FOUND.value, 404)

    def test_every_templated_segment_has_its_own_not_found_identifier(self, api):
        """PRD 2.5: "Each resource kind has its own not-found identifier:
        `ERR_CUSTOMER_NOT_FOUND`, `ERR_COMPONENT_LOT_NOT_FOUND`, `ERR_PRODUCT_SPEC_NOT_FOUND`,
        `ERR_BLEND_RECIPE_NOT_FOUND`, `ERR_BLEND_TANK_NOT_FOUND`, `ERR_BLEND_BATCH_NOT_FOUND`,
        `ERR_RETAIN_SAMPLE_NOT_FOUND`, `ERR_APPROVAL_CLAIM_NOT_FOUND`,
        `ERR_PACKAGE_CONFIGURATION_NOT_FOUND`, `ERR_PACKAGING_LINE_NOT_FOUND`,
        `ERR_PACKAGING_RUN_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
        `ERR_TAKEBACK_COLLECTION_NOT_FOUND` and `ERR_SPEC_CHANGE_REQUEST_NOT_FOUND`. All of
        them carry HTTP 404."
        PRD 2.6: "4. Path existence — every templated path segment resolves, checked left to
        right; otherwise the matching not-found identifier (404)."

        Design: Corner/errors/unknown_path_ids_return_the_matching_not_found_error
        """
        cases = [
            (api.get_customer("00000000-0000-4000-8000-000000000001", ADMIN),
             ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value),
            (api.get_component_lot("00000000-0000-4000-8000-000000000002", ADMIN),
             ApiErrorId.ERR_COMPONENT_LOT_NOT_FOUND.value),
            (api.get_product_spec("00000000-0000-4000-8000-000000000003", ADMIN),
             ApiErrorId.ERR_PRODUCT_SPEC_NOT_FOUND.value),
            (api.get_blend_recipe("00000000-0000-4000-8000-000000000004", ADMIN),
             ApiErrorId.ERR_BLEND_RECIPE_NOT_FOUND.value),
            (api.get_approval_claim("00000000-0000-4000-8000-000000000005", ADMIN),
             ApiErrorId.ERR_APPROVAL_CLAIM_NOT_FOUND.value),
            (api.get_package_configuration("00000000-0000-4000-8000-000000000006", ADMIN),
             ApiErrorId.ERR_PACKAGE_CONFIGURATION_NOT_FOUND.value),
            (api.get_packaging_line("00000000-0000-4000-8000-000000000007", ADMIN),
             ApiErrorId.ERR_PACKAGING_LINE_NOT_FOUND.value),
            (api.get_packaging_run("00000000-0000-4000-8000-000000000008", ADMIN),
             ApiErrorId.ERR_PACKAGING_RUN_NOT_FOUND.value),
            (api.get_order("00000000-0000-4000-8000-000000000009", ADMIN),
             ApiErrorId.ERR_ORDER_NOT_FOUND.value),
            (api.get_takeback_collection("00000000-0000-4000-8000-00000000000a", ADMIN),
             ApiErrorId.ERR_TAKEBACK_COLLECTION_NOT_FOUND.value),
            (api.get_spec_change_request("00000000-0000-4000-8000-00000000000b", ADMIN),
             ApiErrorId.ERR_SPEC_CHANGE_REQUEST_NOT_FOUND.value),
            (api.dispose_retain_sample(
                "00000000-0000-4000-8000-00000000000c", {"reason": "ROUTINE_CLEAROUT"}, QM),
             ApiErrorId.ERR_RETAIN_SAMPLE_NOT_FOUND.value),
        ]
        for response, expected_error in cases:
            assert response.status_code == 404, (
                f"Expected 404 for {expected_error}, got {response.status_code}"
            )
            assert response.json()["response_type"] == "error"
            validate_error(response, expected_error, 404)

    def test_component_lot_listing_pages_and_filters(self, api):
        """PRD 2.3: "`limit` controls page size: it defaults to 10, may not be smaller than 1,
        and may not be larger than 100."
        PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside
        `meta`, where `total_count` is the number of rows matching the filters before the page
        window is applied and `has_more` indicates whether any row remains beyond the current
        window."
        PRD 2.2: "The `response_type` is either "object" for a single resource or "array" for
        a list of resources."

        Design: Corner/entities/component_lot_listing_paginates_with_limit_and_offset
        """
        set_clock(CLOCK_BASE)
        lot1 = create_component_lot(
            component_type="BASE_OIL",
            component_code="GRP2-150N",
            received_kg=400.0,
            unit_cost_cents_per_kg=210,
            kv100_cst=5.200,
            density_kg_per_l=0.855,
        )
        create_component_lot(
            component_type="VI_IMPROVER",
            component_code="OCP-VII",
            received_kg=300.0,
            unit_cost_cents_per_kg=940,
            kv100_cst=850.000,
            density_kg_per_l=0.900,
        )
        create_component_lot(
            component_type="ADDITIVE_PACKAGE",
            component_code="ADD-SN-PLUS",
            received_kg=400.0,
            unit_cost_cents_per_kg=620,
            kv100_cst=105.000,
            density_kg_per_l=0.960,
            additive_family="ZDDP_PCMO",
        )

        first_response = api.list_component_lots(ADMIN, {"limit": 2, "offset": 0})
        page_one, meta_one = validate_paginated(first_response)
        assert len(page_one) == 2
        assert meta_one["total_count"] == 3
        assert meta_one["has_more"] is True
        assert first_response.json()["response_type"] == "array"

        second_response = api.list_component_lots(ADMIN, {"limit": 2, "offset": 2})
        page_two, meta_two = validate_paginated(second_response)
        assert len(page_two) == 1
        assert meta_two["total_count"] == 3
        assert meta_two["has_more"] is False
        assert second_response.json()["response_type"] == "array"

        filtered_response = api.list_component_lots(ADMIN, {"component_type": "BASE_OIL"})
        filtered, _ = validate_paginated(filtered_response)
        assert len(filtered) == 1
        assert filtered[0]["id"] == lot1["id"]
        assert filtered_response.json()["response_type"] == "array"

    def test_recipe_component_rows_carry_no_version(self, api):
        """PRD 2.4: "Two resource kinds are deliberately immutable once written and therefore
        carry neither field: recipe components — the individual material lines of a blend
        recipe — and laboratory results. Both of those carry only `id` and `created_at`; they
        have no `updated_at` and no `version`, and nothing in the system ever mutates them."
        PRD 3.2: "Each stored component records the `blend_recipe_id` of the recipe that owns
        it."

        Design: Corner/entities/recipe_component_rows_are_immutable_children
        """
        set_clock(CLOCK_BASE)
        spec = create_active_spec()
        recipe = create_recipe(spec["id"])

        rows, _ = validate_paginated(api.list_recipe_components(recipe["id"], PM))
        assert len(rows) == 3, f"expected the three formulated material lines, got {len(rows)}"
        for row in rows:
            assert_recipe_component(row)
            assert row["blend_recipe_id"] == recipe["id"]
            assert "version" not in row, "an immutable material line must not expose version"

        fractions = sorted(row["mass_fraction_pct"] for row in rows)
        assert fractions == pytest.approx([6.00, 10.00, 84.00], abs=0.001)

    def test_logical_clock_reads_its_fixed_default_before_being_set(self, api):
        """PRD 2.4: "The server maintains a **logical clock** which reads exactly
        `2026-08-01T00:00:00Z` before it is first set and never falls back to real time
        thereafter."
        PRD 2.4: "A `PlatformAdmin`-only test-driving capability sets the clock to a supplied
        instant, taking a single field `to_iso8601` and returning the resulting `current_utc`;
        it advances or rewinds the clock and mutates no entity."
        PRD 3.1: "Activation stamps `effective_from` from the logical clock and advances the
        specification's `version`."

        Design: Corner/endpoints/logical_clock_starts_at_the_fixed_default_instant
        """
        created = validate_success(
            api.create_product_spec(
                {
                    "product_code": "LUBE-0W20-SP",
                    "sae_grade": "0W-20",
                    "target_kv100_cst": 7.600,
                    "kv100_tolerance_pct": 3.0,
                    "min_additive_treat_pct": 8.00,
                    "base_stock_group": "GROUP_II",
                    "additive_family": "ZDDP_PCMO",
                },
                PM,
            ),
            201,
        )
        assert created["created_at"] == CLOCK_DEFAULT_ISO

        activated = validate_success(api.activate_product_spec(created["id"], PM))
        assert activated["effective_from"] == CLOCK_DEFAULT_ISO

        clock = validate_success(api.set_clock("2026-09-15T09:30:00Z", ADMIN))
        assert clock["current_utc"] == "2026-09-15T09:30:00.000Z"


class TestConfigurationIdentityAndSnapshots:
    def test_activating_a_replacement_configuration_supersedes_the_current_one(self, api):
        """PRD 3.6: "Activation also supersedes: any other configuration that is currently
        `ACTIVE` and shares the same combination of `product_spec_id`, `package_type` and
        `customer_id` moves `ACTIVE → SUPERSEDED`, has its `superseded_by_id` set to the newly
        activated configuration's `id`, and has every order line quoting it that is still
        `OPEN` moved `OPEN → HOLD`."
        PRD 3.6: "The configuration opens in `DRAFT` with `superseded_by_id` null."
        PRD 4: "Lists configurations with filtering and pagination (reverse reachability for
        product_spec_id, customer_id and superseded_by_id)."

        Design: Corner/entities/package_configuration_self_reference_records_supersession
        """
        set_clock(CLOCK_BASE)
        spec = create_active_spec()
        cfg_a = create_active_config(spec["id"], label_brand="House Pail v1")
        cfg_b = create_config(spec["id"], label_brand="House Pail v2")

        activated = validate_success(api.activate_package_configuration(cfg_b["id"], PM))
        assert activated["status"] == "ACTIVE"
        assert activated["superseded_by_id"] is None

        superseded = validate_success(api.get_package_configuration(cfg_a["id"], PM))
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["superseded_by_id"] == cfg_b["id"]

        rows, _ = validate_paginated(
            api.list_package_configurations(PM, {"superseded_by_id": cfg_b["id"]})
        )
        assert len(rows) == 1 and rows[0]["id"] == cfg_a["id"]

    def test_new_batch_snapshots_the_recipe_prediction_and_zeroes_its_computed_fields(self, api):
        """PRD 3.4: "The batch is born with `production_status` `PLANNED` and `qc_status`
        `PENDING` — two dimensions that evolve entirely independently of one another for the
        rest of the batch's life."
        PRD 3.4: "At creation the recipe's `predicted_kv100_cst` is snapshotted onto the batch,
        `claim_eligible` is initialised to false, both `estimated_component_cost_cents` and
        `component_cost_cents` are initialised to 0, `retain_count` is initialised to 0, and
        `blend_tank_id`, `charge_volume_l`, `charge_mass_kg`, `heel_ratio_actual`,
        `measured_kv100_cst`, `window_start` and `window_end` are all null."

        Design: Corner/entities/blend_batch_computed_fields_snapshot_recipe_prediction
        """
        world = setup_active_formulation(with_lots=False)
        batch = create_batch(world["recipe"]["id"])

        assert batch["predicted_kv100_cst"] == pytest.approx(STANDARD_PREDICTED_KV100, abs=0.0005)
        assert batch["production_status"] == "PLANNED"
        assert batch["qc_status"] == "PENDING"
        assert batch["claim_eligible"] is False
        assert batch["retain_count"] == 0
        assert batch["estimated_component_cost_cents"] == 0
        assert batch["component_cost_cents"] == 0
        for field in (
            "blend_tank_id",
            "charge_volume_l",
            "window_start",
            "window_end",
            "heel_ratio_actual",
        ):
            assert batch[field] is None, f"{field} must be null on a freshly planned batch"


class TestAuthenticationAndRoleGates:
    def test_request_without_identity_headers_is_unauthenticated(self, api):
        """PRD 2.1: "If either header is absent, or if `X-User-Role` is not one of the eight
        declared role names, the request is rejected with `ERR_UNAUTHENTICATED` and HTTP 401."
        PRD 2.6: "1. Authentication — both headers present and `X-User-Role` one of the eight
        declared roles; otherwise `ERR_UNAUTHENTICATED` (401). Applies to every endpoint."

        Design: Corner/validations/missing_headers_returns_unauthenticated
        """
        response = api._request("POST", "/customers", {}, {})
        error = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
        assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value

    def test_role_gate_is_consulted_before_path_resolution(self, api):
        """PRD 2.6: "Every check in the system occupies a fixed rung, and the rungs are
        evaluated in strictly ascending order; the **first** check that fails decides the
        response and no later check is consulted."
        PRD 2.6: "2. Authorisation — the caller's role appears in the endpoint's authorised
        list; otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint."
        PRD 2.6: "4. Path existence — every templated path segment resolves, checked left to
        right; otherwise the matching not-found identifier (404)."

        Design: Corner/validations/unauthorized_role_outranks_not_found_on_missing_path_resource
        """
        response = api.release_blend_batch(MISSING_UUID, SALES)
        error = validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
        assert error["error_id"] != ApiErrorId.ERR_BLEND_BATCH_NOT_FOUND.value

    def test_blend_operator_may_not_record_a_laboratory_result(self, api):
        """PRD 2.1: "If both headers are well formed but the named role is not one of the roles
        authorised for the endpoint being called, the request is rejected with
        `ERR_UNAUTHORIZED` and HTTP 403."
        PRD 2.1: "A `BlendOperator` runs the blend floor — creating batches, charging tanks,
        completing blends, reworking quarantined material, flushing vessels and scheduling and
        running packaging — and is deliberately barred from recording any laboratory result or
        releasing any batch."

        Design: Corner/rbac/blend_operator_cannot_record_qc_results
        """
        world = setup_active_formulation(with_lots=False)
        batch = create_batch(world["recipe"]["id"])

        response = api.create_qc_result(
            batch["id"], {"test_type": "KV100", "measured_value": 7.610}, OPERATOR
        )
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

        refreshed = validate_success(api.get_blend_batch(batch["id"], OPERATOR))
        assert refreshed["qc_status"] == "PENDING"

        rows, meta = validate_paginated(api.list_qc_results(batch["id"], QC))
        assert meta["total_count"] == 0 and rows == []

    def test_laboratory_analyst_may_not_release_a_batch(self, api):
        """PRD 2.1: "If both headers are well formed but the named role is not one of the roles
        authorised for the endpoint being called, the request is rejected with
        `ERR_UNAUTHORIZED` and HTTP 403."
        PRD 3.5: "**Release** is the `QualityManager`'s statement that the batch may be sold."
        PRD 2.1: "A `QCTechnician` is the laboratory analyst: it records test results, books
        retain jars and assays incoming used-oil loads."

        Design: Corner/rbac/qc_technician_cannot_release_a_batch
        """
        world = setup_active_formulation(with_lots=False)
        batch = create_batch(world["recipe"]["id"])

        response = api.release_blend_batch(batch["id"], make_qc_technician_headers(QC_TECH_ID))
        error = validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
        assert error["error_id"] != ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value
        assert error["error_id"] != ApiErrorId.ERR_INVALID_STATE.value

        refreshed = validate_success(api.get_blend_batch(batch["id"], OPERATOR))
        assert refreshed["production_status"] == "PLANNED"

    def test_commercial_desk_may_not_write_a_specification(self, api):
        """PRD 2.1: "If both headers are well formed but the named role is not one of the roles
        authorised for the endpoint being called, the request is rejected with
        `ERR_UNAUTHORIZED` and HTTP 403."
        PRD 3.1: "Everything the plant makes begins as a **product specification** — the
        finished-product definition a `ProductManager` writes before any material is ordered."

        Design: Corner/rbac/sales_rep_cannot_create_a_product_spec
        """
        response = api.create_product_spec(
            {
                "product_code": "LUBE-0W20-SP",
                "sae_grade": "0W-20",
                "target_kv100_cst": 7.600,
                "kv100_tolerance_pct": 3.0,
                "min_additive_treat_pct": 8.00,
                "base_stock_group": "GROUP_II",
                "additive_family": "ZDDP_PCMO",
            },
            SALES,
        )
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

        _, meta = validate_paginated(api.list_product_specs(PM))
        assert meta["total_count"] == 0

    def test_product_manager_may_not_record_the_certifying_bodys_verdict(self, api):
        """PRD 2.1: "If both headers are well formed but the named role is not one of the roles
        authorised for the endpoint being called, the request is rejected with
        `ERR_UNAUTHORIZED` and HTTP 403."
        PRD 2.1: "A `ComplianceOfficer` owns approval claims end to end and rules on the
        certification branch of a specification change."
        PRD 3.6: "The claim opens in `DRAFT` with `pinned_spec_revision` null, `licence_number`
        null, `valid_until` null, `requires_recertification` false and `suspension_reason`
        null."

        Design: Corner/rbac/product_manager_cannot_decide_an_approval_claim
        """
        world = setup_active_formulation(with_lots=False)
        claim = validate_success(
            api.create_approval_claim(
                {"product_spec_id": world["spec"]["id"], "claim_body": "API", "claim_code": "API SP"},
                COMPLIANCE,
            ),
            201,
        )
        validate_success(api.submit_approval_claim(claim["id"], COMPLIANCE))

        response = api.decide_approval_claim(
            claim["id"], {"decision": "APPROVE", "licence_number": "API-1234"}, PM
        )
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

        refreshed = validate_success(api.get_approval_claim(claim["id"], COMPLIANCE))
        assert refreshed["status"] == "SUBMITTED"
        assert refreshed["licence_number"] is None
        assert refreshed["valid_until"] is None
