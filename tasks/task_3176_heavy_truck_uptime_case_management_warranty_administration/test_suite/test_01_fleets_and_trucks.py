"""Fleet and truck registration: creation fields, defaults, retrieval,
uniqueness and odometer constraints."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_fleet,
    assert_fleet_invariants,
    assert_truck,
    create_fleet_payload,
    create_truck_payload,
    make_fleet_manager_headers,
    setup_clock,
    setup_fleet,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestFleetCreateReturnsEveryDeclaredField:
    def test_fleet_create_returns_every_declared_field_and_starts_active(self, api):
        """PRD §3.1: "New fleets are born `ACTIVE` with `reliability_score`
        initialized to 1000, `total_downtime_hours` at 0, and `open_case_count`
        at 0."

        Design: Corner/entities/fleet_create_returns_every_declared_field_and_starts_active
        """
        setup_clock()
        resp = api.create_fleet(
            create_fleet_payload(fleet_name="Acme Haulage", home_region="SE"),
            make_fleet_manager_headers("fm-a"),
        )
        body = resp.json()
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
        assert body["response_type"] == "object"
        fleet = body["data"]
        assert_fleet(fleet)
        assert fleet["fleet_name"] == "Acme Haulage"
        assert fleet["home_region"] == "SE"
        assert fleet["fleet_status"] == "ACTIVE"
        assert fleet["reliability_score"] == 1000
        assert fleet["open_case_count"] == 0
        assert fleet["total_downtime_hours"] == 0
        assert fleet["version"] == 1
        assert body["meta"]["api_request_id"].startswith("req_")
        assert body["meta"]["api_request_timestamp"]

    def test_fleet_create_computed_fields_start_at_zero_and_score_at_1000(self, api):
        """PRD §3.1: "New fleets are born `ACTIVE` with `reliability_score`
        initialized to 1000, `total_downtime_hours` at 0, and `open_case_count`
        at 0."

        Design: Corner/entities/fleet_create_returns_every_declared_field_and_starts_active
        """
        setup_clock()
        fleet = validate_success(
            api.create_fleet(
                create_fleet_payload(fleet_name="Second Fleet", home_region="PNW"),
                make_fleet_manager_headers("fm-b"),
            ),
            expected_status=201,
        )
        assert_fleet_invariants(fleet)
        assert fleet["reliability_score"] == 1000
        assert fleet["total_downtime_hours"] == 0
        assert fleet["open_case_count"] == 0


class TestFleetCrud:
    def test_fleet_standard_crud_round_trip(self, api):
        """PRD §3.1: "Fleet metadata — `fleet_name` and `home_region` — can be
        updated, and each update increments the fleet's `version`."

        Design: Corner/endpoints/create_fleet_standard_crud
        """
        setup_clock()
        fm_boot = make_fleet_manager_headers("fm-crud")
        create_resp = api.create_fleet(
            create_fleet_payload(fleet_name="CRUD Fleet", home_region="SE"), fm_boot
        )
        assert create_resp.status_code == 201, f"create must return 201: {create_resp.text}"
        fleet = validate_success(create_resp, expected_status=201)
        fm = make_fleet_manager_headers(fleet["id"])

        got = validate_success(api.get_fleet(fleet["id"], fm))
        assert got["id"] == fleet["id"]

        validate_success(api.update_fleet(fleet["id"], {"fleet_name": "CRUD Renamed"}, fm))
        after = validate_success(api.get_fleet(fleet["id"], fm))
        assert after["fleet_name"] == "CRUD Renamed"
        assert after["version"] == 2, (
            f"Expected version 2 after create(1) + put(2), got {after['version']}"
        )

    def test_fleet_update_increments_version_by_one_each_time(self, api):
        """PRD §3.1: "Fleet metadata — `fleet_name` and `home_region` — can be
        updated, and each update increments the fleet's `version`."

        Design: Corner/endpoints/create_fleet_standard_crud
        """
        setup_clock()
        fleet, fm = setup_fleet(fleet_name="Version Fleet", home_region="SE")
        v0 = fleet["version"]
        validate_success(api.update_fleet(fleet["id"], {"home_region": "PNW"}, fm))
        after = validate_success(api.get_fleet(fleet["id"], fm))
        assert after["home_region"] == "PNW"
        assert after["version"] == v0 + 1


class TestTruckRegistration:
    def test_truck_get_returns_stored_data_unchanged(self, api):
        """PRD §3.1: "Under a fleet, a `FleetManager` registers trucks with a
        17-character `vin` (unique across all trucks — a duplicate is rejected
        with `ERR_DUPLICATE_IDENTIFIER`), a `model_code`, the `in_service_on`
        date the truck entered revenue service, an initial `odometer_miles`
        reading, and the base factory warranty boundaries
        `base_warranty_until_miles` and `base_warranty_until_on`."

        Design: Corner/entities/truck_get_returns_stored_data_unchanged
        """
        setup_clock()
        fleet, fm = setup_fleet(fleet_name="Retrieval Fleet", home_region="SE")
        created = validate_success(
            api.create_truck(
                fleet["id"],
                create_truck_payload(
                    vin="1FUJGBDV8CLBP0200",
                    model_code="CASCADIA_126",
                    in_service_on="2025-06-01T00:00:00Z",
                    odometer_miles=123456,
                    base_warranty_until_miles=250000,
                    base_warranty_until_on="2027-12-31T00:00:00Z",
                ),
                fm,
            ),
            expected_status=201,
        )
        truck = validate_success(api.get_truck(fleet["id"], created["id"], fm))
        assert_truck(truck)
        assert truck["vin"] == "1FUJGBDV8CLBP0200"
        assert truck["model_code"] == "CASCADIA_126"
        assert truck["odometer_miles"] == 123456
        assert truck["truck_status"] == "IN_SERVICE"
        assert truck["repeat_repair_flag"] is False

    def test_truck_create_defaults_repeat_repair_flag_to_false(self, api):
        """PRD §3.1: "New trucks start with `truck_status` of `IN_SERVICE`, an
        `open_case_count` of 0, and a `repeat_repair_flag` of `false`."

        Design: Corner/entities/truck_create_defaults_repeat_repair_flag_to_false
        """
        setup_clock()
        fleet, fm = setup_fleet(fleet_name="Default Fleet", home_region="SE")
        resp = api.create_truck(fleet["id"], create_truck_payload(odometer_miles=0), fm)
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
        truck = validate_success(resp, expected_status=201)
        assert_truck(truck)
        assert truck["repeat_repair_flag"] is False
        assert truck["open_case_count"] == 0

    def test_truck_get_with_unknown_id_returns_truck_not_found(self, api):
        """PRD §2.6: "For a path under a fleet, the fleet identifier is
        resolved first (`ERR_FLEET_NOT_FOUND` on miss), then the truck within
        that fleet (`ERR_TRUCK_NOT_FOUND`)"

        Design: Corner/entities/truck_get_with_unknown_id_returns_truck_not_found
        """
        setup_clock()
        fleet, fm = setup_fleet(fleet_name="NF Fleet", home_region="SE")
        resp = api.get_truck(fleet["id"], NON_EXISTENT_UUID, fm)
        body = resp.json()
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == ApiErrorId.ERR_TRUCK_NOT_FOUND.value
        assert "message" in body["data"] and body["data"]["message"]

    def test_truck_create_missing_vin_returns_invalid_request(self, api):
        """PRD §5: "`ERR_INVALID_REQUEST` | 400 Bad Request" (the generic
        request validation failure for a missing required field such as the
        required `vin` of a truck registration)."

        Design: Corner/entities/truck_create_missing_vin_returns_invalid_request
        """
        setup_clock()
        fleet, fm = setup_fleet(fleet_name="RQ Fleet", home_region="SE")
        payload = create_truck_payload()
        payload.pop("vin")
        resp = api.create_truck(fleet["id"], payload, fm)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)
        trucks, meta = validate_paginated(api.list_trucks(fleet["id"], fm))
        assert len(trucks) == 0, "no truck may be created when vin is omitted"
        assert meta["total_count"] == 0

    def test_truck_create_with_short_vin_returns_invalid_request(self, api):
        """PRD §3.1: "Under a fleet, a `FleetManager` registers trucks with a
        17-character `vin` (unique across all trucks — a duplicate is rejected
        with `ERR_DUPLICATE_IDENTIFIER`)"

        Design: Corner/entities/truck_create_with_out_of_range_priority_returns_invalid_request
        """
        setup_clock()
        fleet, fm = setup_fleet(fleet_name="TC Fleet", home_region="SE")
        payload = create_truck_payload(vin="SHORT", odometer_miles=0)
        resp = api.create_truck(fleet["id"], payload, fm)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


class TestUniquenessAndOdometer:
    def test_vin_uniqueness_enforced_across_fleets(self, api):
        """PRD §3.1: "Under a fleet, a `FleetManager` registers trucks with a
        17-character `vin` (unique across all trucks — a duplicate is rejected
        with `ERR_DUPLICATE_IDENTIFIER`)"

        Design: Corner/validations/vin_uniqueness_enforced
        """
        setup_clock()
        fleet_a, fm_a = setup_fleet(fleet_name="VIN1 Fleet", home_region="SE")
        fleet_b, fm_b = setup_fleet(fleet_name="VIN2 Fleet", home_region="PNW")
        shared_vin = "1FUJGBDV8CLBP0300"
        first = api.create_truck(fleet_a["id"], create_truck_payload(vin=shared_vin, odometer_miles=0), fm_a)
        assert first.status_code == 201, f"first registration must succeed: {first.text}"
        resp = api.create_truck(fleet_b["id"], create_truck_payload(vin=shared_vin, odometer_miles=0), fm_b)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value, expected_status=409)

    def test_odometer_regression_rejected_and_stored_value_unchanged(self, api):
        """PRD §3.1: "A truck's odometer may be updated over its life, but
        `odometer_miles` must be monotonically non-decreasing: an update
        carrying a value lower than the current one is rejected with
        `ERR_ODOMETER_REGRESSION` (HTTP 422)."

        Design: Corner/validations/odometer_regression_rejected
        """
        setup_clock()
        fleet, fm = setup_fleet(fleet_name="Odo Fleet", home_region="SE")
        truck = validate_success(
            api.create_truck(
                fleet["id"], create_truck_payload(odometer_miles=50000), fm
            ),
            expected_status=201,
        )
        resp = api.update_truck(fleet["id"], truck["id"], {"odometer_miles": 49999}, fm)
        validate_error(resp, ApiErrorId.ERR_ODOMETER_REGRESSION.value, expected_status=422)
        after = validate_success(api.get_truck(fleet["id"], truck["id"], fm))
        assert after["odometer_miles"] == 50000, "odometer must be unchanged after rejection"

    def test_odometer_equal_update_accepted_monotonic_non_decreasing(self, api):
        """PRD §3.1: "A truck's odometer may be updated over its life, but
        `odometer_miles` must be monotonically non-decreasing: an update
        carrying a value lower than the current one is rejected with
        `ERR_ODOMETER_REGRESSION` (HTTP 422)."

        Design: Corner/validations/odometer_regression_rejected
        """
        setup_clock()
        fleet, fm = setup_fleet(fleet_name="Odo2 Fleet", home_region="SE")
        truck = validate_success(
            api.create_truck(
                fleet["id"], create_truck_payload(odometer_miles=50000), fm
            ),
            expected_status=201,
        )
        resp = api.update_truck(fleet["id"], truck["id"], {"odometer_miles": 50000}, fm)
        updated = validate_success(resp)
        assert updated["odometer_miles"] == 50000
