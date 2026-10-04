"""Access control, catalog defaults, and validation-pipeline tests (PRD §2.1, §2.5, §3.1, §3.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_region,
    create_allocation_run_payload,
    create_carrier_payload,
    create_commodity,
    create_dealer,
    create_model_line,
    create_order_payload,
    create_region_payload,
    create_run,
    create_restriction,
    config_with,
    get_dealer_allocation,
    get_success_data,
    is_valid_uuid,
    make_dealer_headers,
    setup_dealer_run,
    setup_restricted_line,
    submit_order,
    validate_error,
    validate_success,
)


class TestRegionCreation:
    def test_region_creation_applies_defaults(self, api, allocator_headers):
        """PRD §3.1: "a new region starts in `ACTIVE` status".
        PRD §2.4: "an integer `version` that starts at 1 and increments by exactly 1 on every mutation of that entity".

        Design: Corner/entities/region_creation_applies_defaults_and_system_fields
        """
        resp = api.create_region(create_region_payload(code="CR1", name="Corner Region"), allocator_headers)
        region = validate_success(resp, 201)
        assert_region(region)
        assert region["status"] == "ACTIVE"
        assert region["version"] == 1
        assert is_valid_uuid(region["id"])

    def test_region_code_must_be_present(self, api, allocator_headers):
        """PRD §3.1: "Regions are created with a short uppercase alphanumeric `code` (2 to 20 characters, dashes permitted, immutable after creation) and a human-readable `name`".
        PRD §2.5: "Request shape: required fields present, enums valid, integer ranges respected — otherwise `ERR_VALIDATION` (400)."

        Design: Corner/entities/region_missing_required_code_returns_validation
        """
        resp = api.create_region({"name": "No Code Region"}, allocator_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)

    def test_region_codes_are_unique(self, api, allocator_headers):
        """PRD §2.5: "Uniqueness: codes on region, dealer, model line, commodity, and carrier are unique; the `(dealer_id, model_line_id)` `DealerModelLine` pair is unique; at most one non-`CANCELLED` `Shipment` exists per order — otherwise `ERR_DUPLICATE` (409)."

        Design: Corner/errors/duplicate_region_code_rejected
        """
        resp = api.create_region(create_region_payload(code="DUP1", name="First"), allocator_headers)
        validate_success(resp, 201)
        dup = api.create_region(create_region_payload(code="DUP1", name="Second"), allocator_headers)
        validate_error(dup, ApiErrorId.ERR_DUPLICATE, 409)


class TestAccessControl:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying an `X-User-Role` value that is not one of the declared role names below, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_request_returns_401
        """
        resp = api.list_regions(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    def test_dealer_cannot_publish_run(self, api):
        """PRD §2.1: "A request whose role is recognized but is not permitted on the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.3: "A `RegionalAllocator` opens an allocation cycle by creating an `AllocationRun`".

        Design: Corner/roles/dealer_cannot_publish_run
        """
        fx = setup_dealer_run(num_dealers=1, base_units=3)
        dealer = fx["dealers"][0]
        run = get_success_data(api.create_allocation_run(
            create_allocation_run_payload(fx["model_line"]["id"], period="2026-11", base_units=3),
            TEST_USERS["allocator_headers"],
        ))
        assert run["status"] == "DRAFT"
        resp = api.publish_allocation_run(run["id"], make_dealer_headers(dealer["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    def test_scheduler_cannot_create_carrier(self, api, scheduler_headers):
        """PRD §2.1: "A request whose role is recognized but is not permitted on the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.8: "A `LogisticsCoordinator` owns carriers and the shipment lifecycle."

        Design: Corner/roles/scheduler_cannot_create_carrier
        """
        resp = api.create_carrier(
            create_carrier_payload(code="XCAR", weekly_capacity=5), scheduler_headers
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    def test_dealer_identity_mismatch_denied(self, api):
        """PRD §2.1: "a mismatch is rejected with `ERR_FORBIDDEN` (HTTP 403)" (Dealer X-User-ID versus the resource's dealer_id).

        Design: Corner/roles/dealer_identity_mismatch_denied
        """
        fx = setup_dealer_run(num_dealers=2, base_units=6)
        dealer_a, dealer_b = fx["dealers"]
        da_b = get_dealer_allocation(fx["run"]["id"], dealer_b["id"])
        payload = create_order_payload(
            dealer_b["id"], fx["model_line"]["id"], fx["run"]["id"], da_b["version"]
        )
        # Acting dealer is A; order claims dealer B.
        resp = api.create_order(payload, make_dealer_headers(dealer_a["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


class TestExistenceAndShape:
    def test_unknown_order_id_not_found(self, api, allocator_headers):
        """PRD §2.5: "Referenced resources exist, validated left-to-right along the path, then body foreign keys in declared field order — otherwise `ERR_NOT_FOUND` (404)."

        Design: Corner/validations/not_found_on_unknown_order_id
        """
        resp = api.get_order("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", allocator_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_order_kind_enum_validated(self, api):
        """PRD §2.5: "Request shape: required fields present, enums valid, integer ranges respected — otherwise `ERR_VALIDATION` (400)."
        PRD §3.6: "the `order_kind` (`RETAIL` for a customer-named unit, `STOCK` for inventory)".

        Design: Corner/entities/order_enum_invalid_value_returns_validation
        """
        fx = setup_dealer_run(num_dealers=1, base_units=3)
        dealer = fx["dealers"][0]
        da = get_dealer_allocation(fx["run"]["id"], dealer["id"])
        payload = create_order_payload(
            dealer["id"], fx["model_line"]["id"], fx["run"]["id"], da["version"],
            order_kind="FLEET",
        )
        resp = api.create_order(payload, make_dealer_headers(dealer["id"]))
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)

    def test_retail_order_requires_customer_ref(self, api):
        """PRD §3.6: "A `RETAIL` order must also carry `customer_ref`; a `STOCK` order must not."
        PRD §2.5: "`customer_ref` is present if and only if `order_kind` is `RETAIL` — otherwise `ERR_INVALID_CONFIGURATION` (422)."

        Design: Corner/validations/retail_order_without_customer_ref_rejected
        """
        fx = setup_dealer_run(num_dealers=1, base_units=3, retail_priority_pct=50)
        dealer = fx["dealers"][0]
        da = get_dealer_allocation(fx["run"]["id"], dealer["id"])
        payload = create_order_payload(
            dealer["id"], fx["model_line"]["id"], fx["run"]["id"], da["version"],
            order_kind="RETAIL",
        )
        assert "customer_ref" not in payload
        resp = api.create_order(payload, make_dealer_headers(dealer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_CONFIGURATION, 422)


class TestDealerAllocationComputedDefaults:
    def test_computed_fields_start_at_defaults(self, api):
        """PRD §3.10: "the target `DealerAllocation`'s `adjustment_units` increments by `granted_units`" (it accumulates from zero).
        PRD §3.6: "On accept, the order transitions `SUBMITTED → ACCEPTED`, its `consumed_units` becomes 1, the parent `DealerAllocation`'s `consumed_units` increments by 1" (from zero on a fresh run).

        Design: Corner/entities/dealer_allocation_computed_fields_ignore_client_input
        """
        fx = setup_dealer_run(num_dealers=1, base_units=3)
        dealer = fx["dealers"][0]
        da = get_dealer_allocation(fx["run"]["id"], dealer["id"])
        assert da["adjustment_units"] == 0
        assert da["consumed_units"] == 0
        assert da["retail_consumed_units"] == 0


class TestValidationPipelineOrder:
    def test_state_gate_beats_commodity_cap(self, api):
        """PRD §2.5: "Requests are evaluated against a fixed pipeline of checks; the first failure determines the rejection."
        PRD §2.5: "Parent lifecycle gate: the run is `PUBLISHED` for order entry, appeal grant, and trade execution; the dealer is `ACTIVE` for order entry; the carrier is `ACTIVE` for shipment creation — otherwise `ERR_PARENT_NOT_ACTIVE` (409)." and "8. Commodity cap evaluation for the order — otherwise `ERR_COMMODITY_CAP_EXCEEDED` (422)."

        Design: Difficulty/priority_pair_validation_conflict/state_gate_beats_commodity_cap_on_order_entry
        """
        region = get_success_data(api.create_region(create_region_payload(), TEST_USERS["allocator_headers"]))
        dealer = create_dealer(region["id"])
        line = create_model_line()
        commodity = create_commodity()
        create_restriction(commodity["id"], line["id"], install_rate_pct=0, allow_partial_build=False)
        run = create_run(line["id"], base_units=5, retail_priority_pct=0)
        assert run["status"] == "DRAFT"
        resp = api.create_order(
            create_order_payload(dealer["id"], line["id"], run["id"], 1,
                                 configuration=config_with([commodity["code"]])),
            make_dealer_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PARENT_NOT_ACTIVE, 409)

    def test_commodity_cap_beats_allocation_exhausted(self, api):
        """PRD §2.5: "Requests are evaluated against a fixed pipeline of checks; the first failure determines the rejection."
        PRD §2.5: "8. Commodity cap evaluation for the order — otherwise `ERR_COMMODITY_CAP_EXCEEDED` (422)." precedes "9. Allocation pool availability: remaining pool, and retail pool for a `RETAIL` order, must each be at least 1 — otherwise `ERR_ALLOCATION_EXHAUSTED` (422)."

        Design: Difficulty/priority_pair_validation_conflict/commodity_cap_beats_allocation_exhausted_on_order_entry
        """
        fx = setup_restricted_line(install_rate_pct=50, allow_partial_build=False, base_units=2)
        dealer = fx["dealer"]
        line = fx["model_line"]
        run = fx["run"]
        code = fx["commodity"]["code"]
        # Fill the dealer's pool (2 units): one plain, one carrying the feature.
        resp1 = submit_order(dealer["id"], line["id"], run["id"], configuration=config_with([]))
        assert get_success_data(resp1)["state"] == "ACCEPTED"
        resp2 = submit_order(dealer["id"], line["id"], run["id"], configuration=config_with([code]))
        assert get_success_data(resp2)["state"] == "ACCEPTED"
        da = get_dealer_allocation(run["id"], dealer["id"])
        assert da["consumed_units"] == 2 == da["final_units"]
        # Third order: violates the cap (A=2, F=1, rate 50 -> 1+1 <= floor(3*50/100)=1 false)
        # AND the pool is exhausted — cap (priority 8) must win over pool (priority 9).
        resp3 = submit_order(dealer["id"], line["id"], run["id"], configuration=config_with([code]))
        validate_error(resp3, ApiErrorId.ERR_COMMODITY_CAP_EXCEEDED, 422)


class TestValidationPipelineOrderExtra:
    def test_draft_run_rejects_even_cap_admissible_order(self, api):
        """PRD §2.5: "Requests are evaluated against a fixed pipeline of checks; the first failure determines the rejection."
        PRD §2.5: "Parent lifecycle gate: the run is `PUBLISHED` for order entry, appeal grant, and trade execution; the dealer is `ACTIVE` for order entry; the carrier is `ACTIVE` for shipment creation — otherwise `ERR_PARENT_NOT_ACTIVE` (409)."

        Design: Difficulty/priority_pair_validation_conflict/state_gate_beats_commodity_cap_on_order_entry
        """
        region = get_success_data(api.create_region(create_region_payload(), TEST_USERS["allocator_headers"]))
        dealer = create_dealer(region["id"])
        line = create_model_line()
        commodity = create_commodity()
        create_restriction(commodity["id"], line["id"], install_rate_pct=100,
                           allow_partial_build=False)
        run = create_run(line["id"], base_units=5, retail_priority_pct=0)
        assert run["status"] == "DRAFT"
        # Even a cap-admissible order (rate 100 never binds) hits the parent gate first.
        resp = api.create_order(
            create_order_payload(dealer["id"], line["id"], run["id"], 1,
                                 configuration=config_with([commodity["code"]])),
            make_dealer_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PARENT_NOT_ACTIVE, 409)

    def test_exhausted_pool_with_cap_admissible_order_reports_exhausted(self, api):
        """PRD §2.5: "9. Allocation pool availability: remaining pool, and retail pool for a `RETAIL` order, must each be at least 1 — otherwise `ERR_ALLOCATION_EXHAUSTED` (422)."
        PRD §3.6: "An `install_rate_pct` of 100 never binds".

        Design: Difficulty/priority_pair_validation_conflict/commodity_cap_beats_allocation_exhausted_on_order_entry
        """
        fx = setup_restricted_line(install_rate_pct=100, allow_partial_build=False, base_units=1)
        dealer = fx["dealer"]
        line = fx["model_line"]
        run = fx["run"]
        code = fx["commodity"]["code"]
        first = submit_order(dealer["id"], line["id"], run["id"], configuration=config_with([]))
        assert get_success_data(first)["state"] == "ACCEPTED"
        da = get_dealer_allocation(run["id"], dealer["id"])
        assert da["consumed_units"] == da["final_units"]
        # Rate 100 means the cap never binds, so the pool check is the one that fires.
        resp = submit_order(dealer["id"], line["id"], run["id"],
                            configuration=config_with([code]))
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_EXHAUSTED, 422)
