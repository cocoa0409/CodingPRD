"""Consumables and installs: dual-variant expiration, lot availability,
compatibility, and the supersede invariant.

Design: Difficulty/dual_variant_calc/install_expiration_pad_vs_battery_use_distinct_shelf_lives,
        Difficulty/compensating_invariant/install_replace_conserves_active_install_count_per_kind,
        Corner/calculations/install_expiration_uses_min_of_lot_mfg_and_shelf_life,
        Corner/validations/install_incompatible_lot_model_rejected,
        Corner/validations/expired_lot_rejected_at_install.
"""

from test_helpers import (
    ApiErrorId,
    create_consumable_lot_payload,
    create_device,
    create_device_model,
    create_lot,
    create_campus,
    get_device,
    get_success_data,
    install_consumable,
    set_clock,
    setup_campus_zone_cabinet_device,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["program_manager_headers"]


class TestInstallExpirationDualVariant:

    def test_pad_and_battery_use_distinct_shelf_lives(self, api):
        """PRD: "The shelf-life input is the model's `pad_shelf_life_months` when
        the install's `kind` is `PAD`, and the model's `battery_shelf_life_months`
        when the `kind` is `BATTERY`." PRD: "The install's `expires_at` is then
        the earlier of the lot's `manufacturer_expires_at` and that shelf-life
        end."

        Design: Difficulty/dual_variant_calc/install_expiration_pad_vs_battery_use_distinct_shelf_lives
        """
        set_clock("2026-09-01T00:00:00Z")
        model = create_device_model(pad_months=24, battery_months=48)
        campus = create_campus()
        device = create_device(campus["id"], model["id"], serial_number="SN-001")
        pad_lot = create_lot(campus["id"], model["id"], kind="PAD",
                             lot_code="LOT-P1",
                             manufacturer_expires_at="2030-01-01T00:00:00Z")
        batt_lot = create_lot(campus["id"], model["id"], kind="BATTERY",
                              lot_code="LOT-B1",
                              manufacturer_expires_at="2030-01-01T00:00:00Z")

        pad_install = install_consumable(device["id"], pad_lot["id"])
        batt_install = install_consumable(device["id"], batt_lot["id"])

        # Pad: install + 24mo = 2028-09-01 < lot mfg 2030-01-01.
        assert pad_install["expires_at"] == "2028-09-01T00:00:00Z"
        # Battery: install + 48mo = 2030-09-01, clamped by lot mfg 2030-01-01.
        assert batt_install["expires_at"] == "2030-01-01T00:00:00Z"
        assert pad_install["expires_at"] != batt_install["expires_at"]

        data, _ = validate_paginated(
            api.list_installs(PM, params={"device_id": device["id"]})
        )
        by_id = {i["id"]: i for i in data}
        assert by_id[pad_install["id"]]["expires_at"] == "2028-09-01T00:00:00Z"
        assert by_id[batt_install["id"]]["expires_at"] == "2030-01-01T00:00:00Z"

    def test_battery_variant_uses_battery_shelf_life_months(self, api):
        """PRD: "The shelf-life input is the model's `pad_shelf_life_months` when
        the install's `kind` is `PAD`, and the model's `battery_shelf_life_months`
        when the `kind` is `BATTERY`."

        Design: Difficulty/dual_variant_calc/install_expiration_pad_vs_battery_use_distinct_shelf_lives
        """
        set_clock("2026-09-01T00:00:00Z")
        # Distinctive shelf lives: 6 vs 30 months.
        model = create_device_model(pad_months=6, battery_months=30)
        campus = create_campus()
        device = create_device(campus["id"], model["id"],
                               serial_number="SN-001B")
        pad_lot = create_lot(campus["id"], model["id"], kind="PAD",
                             lot_code="LOT-P1B",
                             manufacturer_expires_at="2032-01-01T00:00:00Z")
        batt_lot = create_lot(campus["id"], model["id"], kind="BATTERY",
                              lot_code="LOT-B1B",
                              manufacturer_expires_at="2032-01-01T00:00:00Z")

        pad_install = install_consumable(device["id"], pad_lot["id"])
        batt_install = install_consumable(device["id"], batt_lot["id"])

        assert pad_install["expires_at"] == "2027-03-01T00:00:00Z"
        assert batt_install["expires_at"] == "2029-03-01T00:00:00Z"


class TestInstallExpirationMinRule:

    def test_expires_at_is_min_of_lot_mfg_and_shelf_life_end(self, api):
        """PRD: "The install's `expires_at` is then the earlier of the lot's
        `manufacturer_expires_at` and that shelf-life end."

        Design: Corner/calculations/install_expiration_uses_min_of_lot_mfg_and_shelf_life
        """
        set_clock("2026-09-01T00:00:00Z")
        model = create_device_model(pad_months=24, battery_months=48)
        campus = create_campus()
        device = create_device(campus["id"], model["id"],
                               serial_number="SN-EXP-1")
        # Lot expires 2027-06-01, earlier than shelf-life end 2028-09-01.
        lot = create_lot(campus["id"], model["id"], kind="PAD",
                         lot_code="L-EXP",
                         manufacturer_expires_at="2027-06-01T00:00:00Z")
        install = install_consumable(device["id"], lot["id"])
        assert install["expires_at"] == "2027-06-01T00:00:00Z"


class TestInstallCompatibilityAndAvailability:

    def test_install_rejected_when_lot_model_differs(self, api):
        """PRD: "The lot must be compatible with the device's model; a lot whose
        `device_model_id` does not match the target device's model is rejected
        with `ERR_INCOMPATIBLE_REFERENCE`."

        Design: Corner/validations/install_incompatible_lot_model_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        model_a = create_device_model(model_code="M-A")
        model_b = create_device_model(model_code="M-B", pad_months=12,
                                      battery_months=24)
        campus = create_campus()
        device = create_device(campus["id"], model_a["id"],
                               serial_number="SN-INC-1")
        bad_lot = create_lot(campus["id"], model_b["id"], kind="PAD",
                             lot_code="L-INCOMPAT")
        res = api.create_install(
            {"device_id": device["id"], "consumable_lot_id": bad_lot["id"],
             "expected_device_version": device["version"]},
            PM,
        )
        validate_error(res, ApiErrorId.ERR_INCOMPATIBLE_REFERENCE,
                       expected_status=422)

    def test_install_rejected_when_lot_expired(self, api):
        """PRD: "if the lot's `quantity_available` is not greater than zero, or
        its `manufacturer_expires_at` is not later than the current time, the
        install is rejected with `ERR_LOT_UNAVAILABLE`."

        Design: Corner/validations/expired_lot_rejected_at_install
        """
        set_clock("2026-09-01T00:00:00Z")
        model = create_device_model()
        campus = create_campus()
        device = create_device(campus["id"], model["id"],
                               serial_number="SN-EL-1")
        expired_lot = create_lot(
            campus["id"], model["id"], kind="PAD", lot_code="L-OLD",
            manufacturer_expires_at="2026-08-01T00:00:00Z",
        )
        res = api.create_install(
            {"device_id": device["id"],
             "consumable_lot_id": expired_lot["id"],
             "expected_device_version": device["version"]},
            PM,
        )
        validate_error(res, ApiErrorId.ERR_LOT_UNAVAILABLE, expected_status=409)


class TestInstallSupersedeInvariant:

    def test_replace_conserves_active_install_count_per_kind(self, api):
        """PRD: "If the device already has an `ACTIVE` install of the same
        `kind`, that prior install transitions to `REPLACED` and its
        `removed_at` is set". PRD: "The device's `current_pad_install_id` or
        `current_battery_install_id` — whichever matches the install's `kind` —
        is set to the new install".

        Design: Difficulty/compensating_invariant/install_replace_conserves_active_install_count_per_kind
        """
        set_clock("2026-09-01T00:00:00Z")
        model = create_device_model()
        campus = create_campus()
        device = create_device(campus["id"], model["id"],
                               serial_number="SN-017")
        lot = create_lot(campus["id"], model["id"], kind="PAD",
                         lot_code="P17a", quantity_received=2)

        first = install_consumable(device["id"], lot["id"])
        second = install_consumable(device["id"], lot["id"])

        first_after = get_success_data(api.get_install(first["id"], PM))
        assert first_after["disposition"] == "REPLACED"
        assert second["disposition"] == "ACTIVE"

        data, meta = validate_paginated(
            api.list_installs(PM, params={"device_id": device["id"],
                                          "kind": "PAD",
                                          "disposition": "ACTIVE"})
        )
        assert len(data) == 1, (
            f"Exactly one ACTIVE pad install must remain, got {len(data)}"
        )
        assert data[0]["id"] == second["id"]

        device_after = get_device(device["id"])
        assert device_after["current_pad_install_id"] == second["id"]

    def test_replaced_install_has_removed_at_set_and_lot_not_restored(self, api):
        """PRD: "If the device already has an `ACTIVE` install of the same
        `kind`, that prior install transitions to `REPLACED` and its
        `removed_at` is set; the prior lot's `quantity_available` is unchanged
        by the replacement because the unit was already drawn when it was first
        installed."

        Design: Difficulty/compensating_invariant/install_replace_conserves_active_install_count_per_kind
        """
        set_clock("2026-09-01T00:00:00Z")
        model = create_device_model()
        campus = create_campus()
        device = create_device(campus["id"], model["id"],
                               serial_number="SN-017B")
        lot = create_lot(campus["id"], model["id"], kind="PAD",
                         lot_code="P17b", quantity_received=2)

        first = install_consumable(device["id"], lot["id"])
        lot_after_first = get_success_data(api.get_consumable_lot(lot["id"], PM))
        assert lot_after_first["quantity_available"] == 1

        install_consumable(device["id"], lot["id"])
        first_after = get_success_data(api.get_install(first["id"], PM))
        assert first_after["disposition"] == "REPLACED"
        assert first_after["removed_at"] is not None

        lot_after_second = get_success_data(api.get_consumable_lot(lot["id"], PM))
        # Second install draws one more unit; replacement does not restore.
        assert lot_after_second["quantity_available"] == 0
