"""Corner tests: store creation defaults, uniqueness and range
constraints, append-only record shapes, listing pagination, and existence
checks."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, is_valid_uuid, is_iso8601_timestamp,
    NON_EXISTENT_UUID, ApiErrorId,
    make_store_manager_headers, make_inspector_headers,
    make_appraiser_headers, anonymous_headers,
    set_clock, create_store, create_customer, create_associate,
    create_vehicle, create_customer_payload, create_vehicle_payload,
    create_appraisal_for, open_inspection_for, add_line_item_for,
    admin_headers,
    assert_store, assert_customer, assert_vehicle, assert_line_item,
)


class TestStoreCreateDefaultsAndSystemFields:
    def test_store_created_with_defaults_and_common_fields(self):
        """PRD §2.11: "A `Store` is identified by a unique `store_code` (for example, `PHX-01`) and a human-readable `display_name`. Each store belongs to a `region` — `WEST`, `CENTRAL`, or `EAST` — which determines the transfer lane band for shipping-fee calculation. A store's `retail_threshold_pct` (default 0.20, expressed as a fraction of appraisal value) sets the reconditioning-cost ceiling beyond which a vehicle is forced to wholesale disposition, and its `transfer_hold_days` (default 7) sets how long a customer-paid transfer hold keeps a vehicle off the open market at the destination store. Stores are created with `status` `ACTIVE`; a `CLOSED` store rejects all new operations."
        PRD §2.4: "`version`: an integer incremented by exactly one on every mutation, serving as the basis for optimistic concurrency control."

        Design: Corner/entities/store_create_defaults_and_system_fields
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api_client.create_store(
            {"store_code": "PHX-01", "display_name": "Phoenix",
             "region": "WEST"},
            admin_headers())
        store = validate_success(resp, expected_status=201)
        assert_store(store)
        assert store["status"] == "ACTIVE"
        assert store["version"] == 1
        assert store["retail_threshold_pct"] == pytest.approx(0.20)
        assert store["transfer_hold_days"] == 7
        assert is_valid_uuid(store["id"])
        assert is_iso8601_timestamp(store["created_at"])
        assert store["created_at"] == store["updated_at"]
        body = resp.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"]
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])


class TestStoreDuplicateCodeRejected:
    def test_duplicate_store_code_rejected(self):
        """PRD §2.11: "A `Store` is identified by a unique `store_code` (for example, `PHX-01`) and a human-readable `display_name`."
        PRD §2.8: "7. Field shape and uniqueness (`ERR_VALIDATION`), including hammer-price positivity on auction close (`ERR_HAMMER_BELOW_RESERVE_INVALID`)."

        Design: Corner/entities/store_duplicate_code_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        create_store()
        resp = api_client.create_store(
            {"store_code": "PHX-01", "display_name": "Phoenix Dup",
             "region": "WEST"},
            admin_headers())
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

        stores, meta = validate_paginated(api_client.list_stores(
            admin_headers()))
        assert len(stores) == 1
        assert meta["total_count"] == 1


class TestCustomerInvalidEnumAndRangeInputsRejected:
    def test_credit_score_and_income_bounds_enforced(self):
        """PRD §3.1: "A `PlatformAdmin` registers a `CustomerAccount` with the customer's `full_name` (legal name), a unique `email`, a `credit_score` between 300 and 850 inclusive, and a `stated_annual_income_cents` (self-reported, zero or greater)."

        Design: Corner/entities/customer_invalid_enum_and_range_inputs_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        admin = admin_headers()

        resp = api_client.create_customer(
            create_customer_payload(email="low@x.com", credit_score=299,
                                    stated_annual_income_cents=1000000),
            admin)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

        resp = api_client.create_customer(
            create_customer_payload(email="neg@x.com", credit_score=500,
                                    stated_annual_income_cents=-1),
            admin)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

        c300 = validate_success(api_client.create_customer(
            create_customer_payload(email="e300@x.com", credit_score=300,
                                    stated_annual_income_cents=0),
            admin), expected_status=201)
        assert_customer(c300)
        assert c300["credit_score"] == 300

        c850 = validate_success(api_client.create_customer(
            create_customer_payload(email="e850@x.com", credit_score=850,
                                    stated_annual_income_cents=1000000),
            admin), expected_status=201)
        assert_customer(c850)
        assert c850["credit_score"] == 850


class TestVehicleDuplicateVinAndBadYearRejected:
    def test_duplicate_vin_and_model_year_bounds(self):
        """PRD §3.1: "A `StoreManager` intakes a vehicle by supplying its `vin` (a 17-character identifier unique across all vehicles), `make`, `model`, `model_year` (between 1990 and 2027 inclusive), `odometer_miles` (zero or greater), `book_value_cents` (the wholesale book value at intake, strictly positive), and `current_store_id`. The vehicle begins life with `lifecycle_status` `INTAKE`, `hold_status` `NONE`, `condition_grade` `UNGRADED`, `recon_cost_total_cents` zero, and `inventory_acquired_at` stamped to the current logical time."

        Design: Corner/entities/vehicle_duplicate_vin_and_bad_year_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        store = create_store()
        mgr = create_associate(store["id"], "MANAGER", "Manager One")
        mgr_headers = make_store_manager_headers(mgr["id"])
        create_vehicle(store["id"], mgr["id"], vin="VAAAAAAAAAAAAAAAA")

        resp = api_client.create_vehicle(
            create_vehicle_payload(store["id"], vin="VAAAAAAAAAAAAAAAA",
                                   odometer_miles=100,
                                   book_value_cents=1000000),
            mgr_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

        resp = api_client.create_vehicle(
            create_vehicle_payload(store["id"], vin="VOLD0000000000001",
                                   make="Old", model="Car", model_year=1989,
                                   odometer_miles=100,
                                   book_value_cents=100000),
            mgr_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

        veh_new = validate_success(api_client.create_vehicle(
            create_vehicle_payload(store["id"], vin="VNEW0000000000001",
                                   make="New", model="Car", model_year=2027,
                                   odometer_miles=10,
                                   book_value_cents=3000000),
            mgr_headers), expected_status=201)
        assert_vehicle(veh_new)
        assert veh_new["lifecycle_status"] == "INTAKE"
        assert veh_new["hold_status"] == "NONE"
        assert veh_new["condition_grade"] == "UNGRADED"
        assert veh_new["recon_cost_total_cents"] == 0


class TestRepairLineItemImmutabilityNoUpdateEndpoint:
    def test_line_item_is_append_only_and_recomputes_inspection_total(self):
        """PRD §2.4: "Three resources are lighter-weight and carry **only** `id` and `created_at` — both `updated_at` and `version` are absent: `RepairLineItem`, `PricingEvent`, and `LedgerEntry`."
        PRD §3.2: "Each line begins `PROPOSED` and is individually approved or rejected; both actions recompute the inspection's `estimated_repair_total_cents`, which is always the sum of `cost_cents` over line items whose `line_status` is not `REJECTED`."

        Design: Corner/entities/repair_line_item_immutability_no_update_endpoint
        """
        set_clock("2026-09-01T00:00:00Z")
        store = create_store()
        mgr = create_associate(store["id"], "MANAGER", "Manager One")
        ap = create_associate(store["id"], "APPRAISER", "Appraiser One")
        ins = create_associate(store["id"], "INSPECTOR", "Inspector One")
        cust = create_customer(email="c1@x.com")
        veh = create_vehicle(store["id"], mgr["id"],
                             vin="VAAAAAAAAAAAAAAAA")
        create_appraisal_for(veh["id"], cust["id"], ap["id"])
        insp = open_inspection_for(veh["id"], ins["id"])

        li = add_line_item_for(insp["id"], ins["id"], category="COSMETIC",
                               cost_cents=12000)
        assert_line_item(li)
        assert li["line_status"] == "PROPOSED"
        assert "updated_at" not in li
        assert "version" not in li

        insp = get_success_data(api_client.get_inspection(
            insp["id"], make_inspector_headers(ins["id"])))
        assert insp["estimated_repair_total_cents"] == 12000


class TestListEndpointsPaginateWithEnvelopeDefaults:
    def test_vehicles_paginate_with_limit_offset_and_filters(self):
        """PRD §2.3: "List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100. `offset` defaults to 0. Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_endpoints_paginate_with_envelope_defaults
        """
        set_clock("2026-09-01T00:00:00Z")
        store = create_store()
        mgr = create_associate(store["id"], "MANAGER", "Manager One")
        mgr_headers = make_store_manager_headers(mgr["id"])
        create_vehicle(store["id"], mgr["id"], vin="VAAAAAAAAAAAAAAAA")
        create_vehicle(store["id"], mgr["id"], vin="VBBBBBBBBBBBBBBBB",
                       make="Toyota", model="Corolla", model_year=2020,
                       odometer_miles=95000, book_value_cents=800000)
        create_vehicle(store["id"], mgr["id"], vin="VCCCCCCCCCCCCCCCC",
                       make="Ford", model="F-150", model_year=2018,
                       odometer_miles=140000, book_value_cents=1000000)

        page1, meta1 = validate_paginated(api_client.list_vehicles(
            mgr_headers,
            params={"current_store_id": store["id"], "limit": 2,
                    "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(api_client.list_vehicles(
            mgr_headers,
            params={"current_store_id": store["id"], "limit": 2,
                    "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        all_rows, meta_all = validate_paginated(api_client.list_vehicles(
            mgr_headers))
        assert len(all_rows) == 3
        assert meta_all["limit"] == 10
        assert meta_all["offset"] == 0

        intake, meta_i = validate_paginated(api_client.list_vehicles(
            mgr_headers, params={"lifecycle_status": "INTAKE"}))
        assert len(intake) == 3
        sold, meta_s = validate_paginated(api_client.list_vehicles(
            mgr_headers, params={"lifecycle_status": "SOLD"}))
        assert sold == []
        assert meta_s["total_count"] == 0


class TestEntityGetUnknownIdReturnsNotFound:
    def test_unknown_ids_return_not_found_without_mutating_state(self):
        """PRD §2.8: "4. Existence of path- and body-referenced resources, validated left-to-right — store, then vehicle, then appraisal, inspection, lot, sale, application, return, and transfer as applicable (`ERR_NOT_FOUND`)."

        Design: Corner/entities/entity_get_unknown_id_returns_not_found
        """
        set_clock("2026-09-01T00:00:00Z")
        store = create_store()
        mgr = create_associate(store["id"], "MANAGER", "Manager One")
        ap = create_associate(store["id"], "APPRAISER", "Appraiser One")
        ins = create_associate(store["id"], "INSPECTOR", "Inspector One")
        cust = create_customer(email="c1@x.com")
        veh = create_vehicle(store["id"], mgr["id"],
                             vin="VAAAAAAAAAAAAAAAA")
        create_appraisal_for(veh["id"], cust["id"], ap["id"])
        insp = open_inspection_for(veh["id"], ins["id"])
        li = add_line_item_for(insp["id"], ins["id"], category="BODY",
                               cost_cents=9000)

        resp = api_client.get_vehicle(
            NON_EXISTENT_UUID, make_store_manager_headers(mgr["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

        resp = api_client.approve_line_item(
            insp["id"], NON_EXISTENT_UUID, make_inspector_headers(ins["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

        line_items, _meta = validate_paginated(api_client.list_line_items(
            insp["id"], make_inspector_headers(ins["id"])))
        assert len(line_items) == 1
        assert line_items[0]["line_status"] == "PROPOSED"
