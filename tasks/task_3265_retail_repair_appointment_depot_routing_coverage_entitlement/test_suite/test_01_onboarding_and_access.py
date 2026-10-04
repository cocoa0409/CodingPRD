"""Onboarding, entity-shape, retrieval, and RBAC tests (corner-design queue B)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_customer,
    assert_device,
    assert_repair_order,
    create_coverage_plan_payload,
    create_customer,
    create_customer_payload,
    create_device,
    create_device_payload,
    create_location,
    create_repair_order_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_anonymous_headers,
    make_customer_headers,
    make_customer_service_headers,
    make_platform_admin_headers,
    make_technician_headers,
    set_clock,
    setup_appointment,
    setup_customer_and_device,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCustomerCreation:
    def test_customer_create_returns_all_declared_fields_and_starts_active(self, api):
        """PRD §3.1: "A new customer begins with `account_status` set to `ACTIVE`."
        PRD §2.4: "Every persisted entity carries an `id` that is a server-minted
        UUID with no type prefix, plus a `created_at` timestamp in ISO 8601 UTC
        with three fractional digits. Entities participating in mutation workflows
        additionally carry `updated_at` (same timestamp format, refreshed on every
        mutation) and `version`, an integer starting at its initial value that
        increments by one on every state transition or mutating side effect applied
        to that entity."

        Design: Corner/entities/customer_create_returns_all_declared_fields_and_starts_active
        """
        set_clock()
        resp = api.create_customer(
            {"email": "corner1@x.com", "full_name": "Corner One", "phone": "555-1000"},
            make_anonymous_headers(),
        )
        data = validate_success(resp, expected_status=201)
        assert resp.json()["response_type"] == "object"
        assert data["email"] == "corner1@x.com"
        assert data["full_name"] == "Corner One"
        assert data["account_status"] == "ACTIVE"
        assert data["version"] == 1
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])
        assert_customer(data)


class TestDeviceRetrieval:
    def test_device_get_returns_stored_data(self, api):
        """PRD §3.1: "Device registration records the owning `customer_id`, a
        `serial_number` that is unique per device model family, a `model_code`
        such as IPHONE_15_PRO, whether `activation_lock_enabled` is currently
        true, whether `proof_of_purchase_on_file` has been uploaded, and the
        original `purchase_date`. A device starts with `device_status` of
        `ACTIVE` (the lifecycle also defines `IN_SERVICE` and `RETIRED`)."

        Design: Corner/entities/device_get_returns_stored_data
        """
        set_clock()
        customer = create_customer()
        device = create_device(
            customer,
            serial_number="SN-C2",
            model_code="IPHONE_14",
            activation_lock_enabled=True,
            proof_of_purchase_on_file=False,
            purchase_date="2025-03-15T00:00:00Z",
        )
        resp = api.get_device(device["id"], make_customer_headers(customer["id"]))
        data = validate_success(resp, expected_status=200)
        assert data["serial_number"] == "SN-C2"
        assert data["model_code"] == "IPHONE_14"
        assert data["activation_lock_enabled"] is True
        assert data["proof_of_purchase_on_file"] is False
        assert data["device_status"] == "ACTIVE"
        assert_device(data)


class TestServiceLocationListing:
    def test_service_locations_list_paginates(self, api):
        """PRD §2.3: "`limit` defaults to 10, must be at least 1, and may not
        exceed 100. `offset` defaults to 0. Results are always sorted by
        `created_at` in ascending order. The `meta` block of a list response
        carries `limit`, `offset`, `total_count`, and `has_more`, where
        `has_more` indicates whether additional records exist beyond the current
        window."

        Design: Corner/entities/service_locations_list_paginates
        """
        set_clock()
        admin = make_platform_admin_headers()
        for code, loc_type, same_day, express in [
            ("C3-A", "RETAIL_STORE", True, False),
            ("C3-B", "RETAIL_STORE", False, True),
            ("C3-C", "MAIL_IN_DEPOT", False, False),
        ]:
            resp = api.create_service_location(
                {
                    "location_code": code,
                    "location_type": loc_type,
                    "address": f"{code} St",
                    "supports_same_day_repair": same_day,
                    "supports_express_replacement": express,
                    "diagnostic_slot_duration_minutes": 30,
                },
                admin,
            )
            validate_success(resp, expected_status=201)

        reader = make_customer_headers("cust-x")
        resp = api.list_service_locations(reader, params={"limit": 2, "offset": 0})
        rows, meta = validate_paginated(resp)
        assert resp.json()["response_type"] == "array"
        assert len(rows) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

        resp = api.list_service_locations(reader, params={"limit": 2, "offset": 2})
        rows, meta = validate_paginated(resp)
        assert len(rows) == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is False


class TestNotFoundAndValidation:
    def test_device_get_unknown_id_returns_not_found(self, api):
        """PRD §2.6: "Existence errors use entity-specific identifiers where they
        exist — `ERR_CUSTOMER_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`, ..."

        Design: Corner/entities/device_get_unknown_id_returns_not_found
        """
        set_clock()
        resp = api.get_device(NON_EXISTENT_UUID, make_customer_headers("cust-x"))
        validate_error(resp, ApiErrorId.ERR_DEVICE_NOT_FOUND.value, expected_status=404)
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["data"]["error_id"], str)
        assert isinstance(body["data"]["message"], str)

    def test_device_create_missing_serial_number_returns_invalid_request(self, api):
        """PRD §3.1: "Device registration records the owning `customer_id`, a
        `serial_number` that is unique per device model family, a `model_code`
        such as IPHONE_15_PRO, ..."
        PRD §2.6: "A malformed payload or one missing required fields is rejected
        with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/device_create_missing_serial_number_returns_invalid_request
        """
        set_clock()
        customer = create_customer()
        payload = create_device_payload(customer["id"])
        del payload["serial_number"]
        resp = api.create_device(payload, make_customer_service_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)

        resp = api.list_customer_devices(
            customer["id"], make_customer_headers(customer["id"]))
        rows, meta = validate_paginated(resp)
        assert len(rows) == 0
        assert meta["total_count"] == 0

class TestCoveragePlanDefaults:
    def test_coverage_plan_create_defaults_incidents_used_to_zero(self, api):
        """PRD §3.1: "The plan opens with `coverage_status` of `ACTIVE` and
        `accidental_damage_incidents_used` at zero."

        Design: Corner/entities/coverage_plan_create_defaults_incidents_used_to_zero
        """
        set_clock()
        customer, device = setup_customer_and_device()
        payload = create_coverage_plan_payload(
            device["id"],
            plan_type="LIMITED_WARRANTY",
            accidental_damage_incident_limit=0,
            service_fee_cents=0,
        )
        resp = api.create_coverage_plan(payload, make_customer_service_headers())
        data = validate_success(resp, expected_status=201)
        assert data["accidental_damage_incidents_used"] == 0
        assert data["coverage_status"] == "ACTIVE"


class TestRepairOrderCreation:
    def test_repair_order_status_is_system_managed(self, api):
        """PRD §3.4: "The new repair order opens in `TRIAGED` with
        `current_location_id` equal to its `origin_location_id`,
        `repeat_repair_count` at zero, and a provisional `quoted_price_cents`
        computed from the issue category's base price alone — the provisional
        quote deliberately omits the age surcharge and model multiplier until
        entitlement resolution (§3.6)."

        Design: Corner/entities/repair_order_status_is_system_managed
        """
        set_clock()
        customer, device, location, technician, appointment = setup_appointment()
        fresh_device = appointment["_device"]
        payload = create_repair_order_payload(
            appointment["id"], device["id"], customer["id"], location["id"],
            fresh_device["version"],
        )
        payload["repair_status"] = "COMPLETED"  # must be ignored by the server
        resp = api.create_repair_order(payload, make_technician_headers(technician["id"]))
        data = validate_success(resp, expected_status=201)
        assert data["repair_status"] == "TRIAGED"
        assert data["version"] == 1
        assert_repair_order(data)

    def test_repair_order_create_checks_appointment_belongs_to_device(self, api):
        """PRD §3.4: "The repair order must reference a valid appointment, and
        its device must belong to the named customer, or the create fails with
        `ERR_INVALID_REFERENCE`."

        Design: Corner/entities/repair_order_create_checks_appointment_belongs_to_device
        """
        set_clock()
        customer, device, location, technician, appointment = setup_appointment()
        other_device = create_device(customer)
        # device_b was never mutated, so its version is unchanged at creation value
        payload = create_repair_order_payload(
            appointment["id"], other_device["id"], customer["id"], location["id"],
            other_device["version"],
        )
        resp = api.create_repair_order(payload, make_technician_headers(technician["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REFERENCE.value, expected_status=422)


class TestAuthAndRbac:
    def test_err_unauthenticated_on_missing_headers(self, api):
        """PRD §2.1: "A request missing either header, or carrying an empty value
        for either, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/err_unauthenticated_on_missing_headers
        """
        set_clock()
        headers = {"X-User-ID": "", "X-User-Role": "Customer",
                   "Content-Type": "application/json"}
        resp = api.get_customer(NON_EXISTENT_UUID, headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)

    def test_err_unauthorized_on_wrong_role(self, api):
        """PRD §2.1: "A request whose role is not permitted to perform the
        requested operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.1: "`PlatformAdmin` performs configuration writes — service
        locations, technicians, part catalog entries — and controls the logical
        clock."

        Design: Corner/errors/err_unauthorized_on_wrong_role
        """
        set_clock()
        resp = api.create_service_location(
            {
                "location_code": "C24-LOC",
                "location_type": "RETAIL_STORE",
                "address": "24 C St",
                "supports_same_day_repair": True,
                "supports_express_replacement": False,
                "diagnostic_slot_duration_minutes": 30,
            },
            make_customer_headers("cust-x"),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)
