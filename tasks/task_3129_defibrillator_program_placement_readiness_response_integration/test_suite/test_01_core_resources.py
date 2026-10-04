"""Core resources: creation envelopes, required fields, defaults, retrieval,
pagination, and uniqueness constraints.

Design: Corner/entities/* instances.
"""

from test_helpers import (
    ApiErrorId,
    create_campus_payload,
    create_consumable_lot_payload,
    create_device_model_payload,
    create_device_payload,
    get_success_data,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_campus,
    assert_consumable_lot,
    assert_device,
    assert_device_model,
    create_campus,
    create_device,
    create_device_model,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["program_manager_headers"]


class TestCampusCreation:

    def test_campus_create_returns_full_envelope_and_initial_posture(self, api):
        """PRD: "A newly created campus starts with `readiness_posture` equal to
        `OPERATIONAL`." PRD: "The `version` field is an integer that starts at
        its initial value at creation and increments by one on every mutation of
        the resource".

        Design: Corner/entities/campus_create_returns_full_envelope_and_initial_posture
        """
        set_clock("2026-09-01T00:00:00Z")
        res = api.create_campus(
            create_campus_payload(
                name="North Campus",
                jurisdiction_code="WA",
                jurisdiction_registration_number="WA-PAD-100",
                response_time_target_seconds=300,
            ),
            ADMIN,
        )
        body = res.json()
        assert body.get("response_type") == "object"
        campus = validate_success(res, expected_status=201)
        assert_campus(campus)
        assert campus["name"] == "North Campus"
        assert campus["readiness_posture"] == "OPERATIONAL"
        assert campus["version"] == 1

    def test_campus_create_missing_response_time_target_rejected(self, api):
        """PRD: "A defibrillator program begins when a `PlatformAdmin` creates a
        **Campus**, supplying a display `name`, the regulatory `jurisdiction_code`,
        the program's `jurisdiction_registration_number` with that jurisdiction,
        the `response_time_target_seconds` that placement planning will treat as
        the maximum acceptable response time, and the `medical_director_id` of the
        physician who will oversee the program." Missing required input is a
        malformed payload per PRD: "`ERR_INVALID_REQUEST` | 400".

        Design: Corner/entities/campus_create_missing_required_field_returns_invalid_request
        """
        set_clock("2026-09-01T00:00:00Z")
        payload = create_campus_payload()
        del payload["response_time_target_seconds"]
        res = api.create_campus(payload, ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestDeviceCreationAndRetrieval:

    def test_device_get_returns_stored_fields_and_computed_posture(self, api):
        """PRD: "A freshly registered device starts with lifecycle `status` equal
        to `REGISTERED`, with `cabinet_id` null, with `current_pad_install_id` and
        `current_battery_install_id` both null, with `last_inspection_at` null,
        with `last_selftest_status` equal to `UNKNOWN`, and — because it has no
        consumables — with `readiness_posture` equal to `OUT_OF_SERVICE` per the
        posture ladder in §2.5."

        Design: Corner/entities/device_get_returns_stored_fields_and_computed_posture
        """
        set_clock("2026-09-01T00:00:00Z")
        model = create_device_model(
            model_code="AED-X", pad_months=18, battery_months=36,
            prescription_required=True,
        )
        campus = create_campus()
        device = create_device(campus["id"], model["id"],
                               serial_number="SN-X-001")
        res = api.get_device(device["id"], PM)
        fetched = validate_success(res)
        assert_device(fetched)
        assert fetched["serial_number"] == "SN-X-001"
        assert fetched["device_model_id"] == model["id"]
        assert fetched["status"] == "REGISTERED"
        assert fetched["readiness_posture"] == "OUT_OF_SERVICE"

    def test_devices_list_paginates_with_limit_offset_total_count(self, api):
        """PRD: "The `limit` parameter specifies the maximum number of items to
        return; when omitted it defaults to 10, and it is constrained to a
        minimum of 1 and a maximum of 100. The `offset` parameter specifies how
        many items to skip and defaults to 0." PRD: "List responses include
        `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of
        the response envelope."

        Design: Corner/entities/devices_list_paginates_with_limit_offset_total_count
        """
        set_clock("2026-09-01T00:00:00Z")
        model = create_device_model()
        campus = create_campus()
        for i in range(3):
            create_device(campus["id"], model["id"], serial_number=f"SN-Y-{i:03d}")

        data, meta = validate_paginated(
            api.list_devices(PM, params={"campus_id": campus["id"],
                                         "limit": 2, "offset": 0})
        )
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert len(data) == 2

        data2, meta2 = validate_paginated(
            api.list_devices(PM, params={"campus_id": campus["id"],
                                         "limit": 2, "offset": 2})
        )
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert len(data2) == 1

    def test_device_get_with_unknown_id_returns_not_found(self, api):
        """PRD: "the system validates the existence of each referenced resource in
        order and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first
        reference that does not resolve."

        Design: Corner/entities/device_get_with_unknown_id_returns_not_found
        """
        set_clock("2026-09-01T00:00:00Z")
        create_campus()
        res = api.get_device(NON_EXISTENT_UUID, PM)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestConsumableLotDefaults:

    def test_lot_quantity_available_defaults_to_quantity_received(self, api):
        """PRD: "On creation the lot's `quantity_available` equals
        `quantity_received`".

        Design: Corner/entities/consumable_lot_quantity_available_defaults_to_quantity_received
        """
        set_clock("2026-09-01T00:00:00Z")
        model = create_device_model()
        campus = create_campus()
        res = api.create_consumable_lot(
            create_consumable_lot_payload(
                campus["id"], model["id"], kind="PAD",
                lot_code="L1", quantity_received=7,
            ),
            PM,
        )
        lot = validate_success(res, expected_status=201)
        assert_consumable_lot(lot)
        assert lot["quantity_received"] == 7
        assert lot["quantity_available"] == 7


class TestDeviceSerialUniqueness:

    def test_duplicate_serial_number_on_same_campus_rejected(self, api):
        """PRD: "The serial number must be unique within its campus; registering
        a duplicate is rejected with `ERR_SERIAL_NUMBER_CONFLICT`."

        Design: Corner/entities/device_serial_number_uniqueness_per_campus_enforced
        """
        set_clock("2026-09-01T00:00:00Z")
        model = create_device_model()
        campus = create_campus()
        create_device(campus["id"], model["id"], serial_number="DUP-1")
        res = api.create_device(
            create_device_payload(campus["id"], model["id"],
                                  serial_number="DUP-1"),
            PM,
        )
        validate_error(res, ApiErrorId.ERR_SERIAL_NUMBER_CONFLICT,
                       expected_status=409)
