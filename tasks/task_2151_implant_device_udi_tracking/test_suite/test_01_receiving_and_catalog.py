"""Vendors, the device catalog, lots and serialized receipt."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_catalog_item,
    assert_created_at_ascending,
    assert_device_unit,
    assert_lot,
    assert_lot_conservation,
    assert_object_envelope,
    assert_patient,
    assert_vendor,
    create_catalog_item,
    create_lot,
    create_patient,
    create_vendor,
    get_catalog_item,
    get_lot,
    get_unit,
    lot_version,
    add_unit,
    is_valid_uuid,
    release_lot,
    reserve_unit,
    set_clock,
    setup_scheduled_case,
    setup_stock,
    validate_error,
    validate_paginated,
    validate_success,
    CC,
    IL,
    RT,
)


class TestVendorAndCatalogRegistration:
    def test_new_vendor_opens_active_with_zeroed_counters(self, api):
        """PRD §3.1: "A freshly registered vendor opens with `standing` set to
        `ACTIVE`, `open_consignment_liability_cents` at 0 and `recall_open_count`
        at 0."
        PRD §2.4: "`id` is a server-minted UUID with no type prefix of any kind;
        clients never supply it."
        PRD §2.4: "`version` is an integer that begins at 1 when the resource is
        created and increases by exactly 1 on every mutation of that resource,
        whether the mutation was requested directly or arrived as a cascade from
        another resource's transition."

        Design: Corner/entities/vendor_creation_returns_declared_fields_and_defaults
        """
        set_clock("2026-09-01T00:00:00Z")

        response = api.create_vendor(
            {"name": "Ortholux Medical", "vendor_code": "ORTHO-1"}, IL
        )
        vendor = validate_success(response, 201)

        assert_vendor(vendor)
        assert vendor["standing"] == "ACTIVE"
        assert vendor["open_consignment_liability_cents"] == 0
        assert vendor["recall_open_count"] == 0
        assert vendor["version"] == 1
        assert is_valid_uuid(vendor["id"]), (
            f"id must be a bare UUID with no type prefix, got {vendor['id']!r}"
        )
        assert_object_envelope(response.json())

    def test_catalog_item_without_list_charge_is_a_malformed_request(self, api):
        """PRD §3.1: "Registering one requires the manufacturing `vendor_id`, the
        `device_identifier` — the GS1 GTIN-14 that forms the UDI-DI half of the
        identifier and which must be globally unique and non-empty — a
        human-readable `description`, a `category` of `HIGH_COST_IMPLANT`,
        `STANDARD_IMPLANT` or `ACCESSORY`, a `list_charge_cents` chargemaster
        price that must be strictly greater than zero, the `charge_code` that will
        be stamped onto every charge line for this model, and `shelf_life_days`, a
        nominal shelf life recorded for information and read by no rule."
        PRD §2.6: "Request shape — every required input field present and
        non-null, every enum field carrying a declared member, every integer field
        an integer inside its declared range, `scheduled_end_utc` strictly after
        `scheduled_start_utc`, exactly one of `catalog_item_id` and
        `device_unit_id` on a reservation request, `lot_numbers` present only when
        `scope_type` is `LOT`, `serial_low` and `serial_high` present only when
        `scope_type` is `SERIAL_RANGE`, and pagination inside its declared bounds.
        Failure: `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/catalog_item_missing_required_field_returns_invalid_request
        """
        vendor = create_vendor()

        response = api.create_catalog_item(
            {
                "vendor_id": vendor["id"],
                "device_identifier": "00812345678905",
                "description": "Ti Femoral Stem",
                "category": "STANDARD_IMPLANT",
                "charge_code": "CDM-77140",
                "shelf_life_days": 1095,
            },
            IL,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

        rows, meta = validate_paginated(
            api.list_catalog_items(IL, {"vendor_id": vendor["id"]})
        )
        assert meta["total_count"] == 0, "The rejected request must create no catalog item"
        assert rows == []

    def test_optional_registry_and_consent_flags_take_their_declared_defaults(self, api):
        """PRD §3.1: "One optional flag, `registry_required`, defaults to false;
        when it is true, verifying an implant of this model creates a
        national-registry obligation."
        PRD §3.1: "A new catalog item opens with `on_hand_available_qty` at 0."
        PRD §3.3: "A `CircClinician` registers a patient with an `mrn` that must be
        globally unique and non-empty and a `display_name`, plus an optional
        `registry_consent` that defaults to `UNKNOWN` and otherwise takes `GRANTED`
        or `DECLINED`. A new patient's `implant_count` starts at 0."

        Design: Corner/entities/catalog_item_registry_required_and_patient_consent_defaults_applied
        """
        vendor = create_vendor()

        catalog_item = validate_success(
            api.create_catalog_item(
                {
                    "vendor_id": vendor["id"],
                    "device_identifier": "00812345678905",
                    "description": "Ti Femoral Stem",
                    "category": "STANDARD_IMPLANT",
                    "list_charge_cents": 600_000,
                    "charge_code": "CDM-77140",
                    "shelf_life_days": 1095,
                },
                IL,
            ),
            201,
        )
        patient = validate_success(
            api.create_patient({"mrn": "MRN-1001", "display_name": "Pat One"}, CC), 201
        )

        assert_catalog_item(catalog_item)
        assert_patient(patient)
        assert catalog_item["registry_required"] is False
        assert catalog_item["on_hand_available_qty"] == 0
        assert patient["registry_consent"] == "UNKNOWN"
        assert patient["implant_count"] == 0

    def test_undeclared_registry_consent_member_is_rejected(self, api):
        """PRD §3.3: "A `CircClinician` registers a patient with an `mrn` that must
        be globally unique and non-empty and a `display_name`, plus an optional
        `registry_consent` that defaults to `UNKNOWN` and otherwise takes `GRANTED`
        or `DECLINED`."
        PRD §2.6: "Request shape — every required input field present and
        non-null, every enum field carrying a declared member, every integer field
        an integer inside its declared range, `scheduled_end_utc` strictly after
        `scheduled_start_utc`, exactly one of `catalog_item_id` and
        `device_unit_id` on a reservation request, `lot_numbers` present only when
        `scope_type` is `LOT`, `serial_low` and `serial_high` present only when
        `scope_type` is `SERIAL_RANGE`, and pagination inside its declared bounds.
        Failure: `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/patient_invalid_enum_registry_consent_returns_invalid_request
        """
        set_clock("2026-09-01T00:00:00Z", CC)

        response = api.create_patient(
            {"mrn": "MRN-1001", "display_name": "Pat One", "registry_consent": "MAYBE"},
            CC,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestSerializedReceipt:
    def test_new_serial_opens_quarantined_owned_with_a_frozen_udi_snapshot(self, api):
        """PRD §3.2: "Each accepted serial opens with `custody_state` at
        `QUARANTINED`, `billing_state` at `NOT_BILLABLE`, `ownership` at
        `CONSIGNED` when an agreement was named and `OWNED` otherwise, and a
        `udi_di_snapshot` copied verbatim from the catalog item's
        `device_identifier` at this moment — a frozen copy, so that later catalog
        edits can never retroactively invalidate a transcription check."
        PRD §3.2: "Its `vendor_invoice_id`, `reserved_case_id`,
        `contract_price_cents`, `price_list_version_at_billing`,
        `implanted_at_utc` and `expired_at_utc` all start null."
        PRD §3.2: "Adding the unit re-derives the lot's `received_qty` and
        `on_hand_qty` and advances the lot's `version` by one, which is precisely
        why the next serial in the same carton needs a refreshed
        `expected_lot_version`."

        Design: Corner/entities/device_unit_computed_and_system_fields_are_not_client_settable
        """
        vendor = create_vendor()
        catalog_item = create_catalog_item(
            vendor["id"], device_identifier="00812345678905"
        )
        lot = create_lot(catalog_item["id"])

        unit = validate_success(
            api.add_device_unit(
                lot["id"],
                {
                    "udi_serial": "SN-0001",
                    "acquisition_cost_cents": 400_000,
                    "expected_lot_version": lot["version"],
                },
                RT,
            ),
            201,
        )

        assert_device_unit(unit)
        assert unit["custody_state"] == "QUARANTINED"
        assert unit["billing_state"] == "NOT_BILLABLE"
        assert unit["ownership"] == "OWNED"
        assert unit["udi_di_snapshot"] == "00812345678905"
        assert unit["contract_price_cents"] is None
        assert unit["price_list_version_at_billing"] is None
        assert unit["vendor_invoice_id"] is None
        assert unit["reserved_case_id"] is None
        assert unit["implanted_at_utc"] is None
        assert unit["expired_at_utc"] is None

        refreshed_lot = get_lot(lot["id"])
        assert refreshed_lot["received_qty"] == 1
        assert refreshed_lot["on_hand_qty"] == 1
        assert refreshed_lot["version"] == lot["version"] + 1

    def test_replacement_serial_is_reachable_through_the_self_reference_filter(self, api):
        """PRD §3.2: "Two optional fields ride along: `consignment_agreement_id`,
        which when supplied puts the unit on consignment terms and when omitted
        leaves it hospital-owned outright, and `replaced_unit_id`, the
        self-reference used when this serial is going in to replace a previously
        explanted one."
        PRD §2.3: "Serialized units expose every one of their foreign keys as a
        filter — `lot_id`, `consignment_agreement_id`, `vendor_invoice_id`,
        `reserved_case_id` and the self-reference `replaced_unit_id` — plus
        `custody_state` and `billing_state`."

        Design: Corner/entities/device_unit_self_reference_replaced_unit_id_is_reverse_reachable
        """
        vendor = create_vendor()
        catalog_item = create_catalog_item(vendor["id"])
        lot = create_lot(catalog_item["id"])
        first = add_unit(lot["id"], "SN-0001", 400_000)

        replacement = validate_success(
            api.add_device_unit(
                lot["id"],
                {
                    "udi_serial": "SN-0002",
                    "acquisition_cost_cents": 400_000,
                    "expected_lot_version": lot_version(lot["id"]),
                    "replaced_unit_id": first["id"],
                },
                RT,
            ),
            201,
        )

        assert replacement["replaced_unit_id"] == first["id"]

        rows, meta = validate_paginated(
            api.list_device_units(IL, {"replaced_unit_id": first["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == replacement["id"]

        all_rows, all_meta = validate_paginated(
            api.list_device_units(IL, {"lot_id": lot["id"]})
        )
        assert all_meta["total_count"] == 2
        assert_created_at_ascending(all_rows)

    def test_three_uniqueness_scopes_each_raise_their_own_collision_error(self, api):
        """PRD §3.1: "An `InventoryLead` registers a vendor with a legal `name` and
        a short `vendor_code`, which must be non-empty and unique across all
        vendors; a collision is rejected with `ERR_DUPLICATE_IDENTIFIER`."
        PRD §3.2: "A `ReceivingTech` books it in with the `catalog_item_id` of the
        model it contains, the manufacturer's `lot_number` — the UDI-PI lot, which
        must be unique among that catalog item's lots, with a collision rejected as
        `ERR_DUPLICATE_LOT_NUMBER` — and an `expiration_date` written as a plain
        calendar date in `YYYY-MM-DD` form."
        PRD §3.2: "A serial must be unique among the units of the same catalog
        item, resolved through the unit's lot; a collision is rejected with
        `ERR_DUPLICATE_UDI_SERIAL`."

        Design: Corner/validations/uniqueness_guards_for_vendor_code_lot_number_and_udi_serial
        """
        vendor = create_vendor(vendor_code="ORTHO-1")
        catalog_item = create_catalog_item(vendor["id"])
        lot = create_lot(catalog_item["id"], lot_number="L-4401")
        add_unit(lot["id"], "SN-0001", 400_000)

        validate_error(
            api.create_vendor({"name": "Ortholux Clone", "vendor_code": "ORTHO-1"}, IL),
            ApiErrorId.ERR_DUPLICATE_IDENTIFIER,
            409,
        )
        validate_error(
            api.create_lot(
                {
                    "catalog_item_id": catalog_item["id"],
                    "lot_number": "L-4401",
                    "expiration_date": "2028-06-30",
                },
                RT,
            ),
            ApiErrorId.ERR_DUPLICATE_LOT_NUMBER,
            409,
        )
        validate_error(
            api.add_device_unit(
                lot["id"],
                {
                    "udi_serial": "SN-0001",
                    "acquisition_cost_cents": 400_000,
                    "expected_lot_version": lot_version(lot["id"]),
                },
                RT,
            ),
            ApiErrorId.ERR_DUPLICATE_UDI_SERIAL,
            409,
        )

        _, lots_meta = validate_paginated(
            api.list_lots(RT, {"catalog_item_id": catalog_item["id"]})
        )
        assert lots_meta["total_count"] == 1
        assert get_lot(lot["id"])["received_qty"] == 1


class TestPatientListingWindow:
    def test_patient_list_reports_total_count_has_more_and_rejects_bad_limits(self, api):
        """PRD §2.3: "`limit` defaults to 10 when absent, has a minimum of 1 and a
        maximum of 100. `offset` defaults to 0 when absent and has a minimum of 0;
        there is no upper bound on it. A `limit` below 1 or above 100, or a
        negative `offset`, is a malformed request and is rejected with
        `ERR_INVALID_REQUEST` (HTTP 400) rather than being silently clamped."
        PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`,
        `total_count` and `has_more`, where `total_count` is the number of rows
        matching the filters before pagination is applied and `has_more` is true
        when rows remain beyond the current window."
        PRD §2.3: "Patients accept `registry_consent`."

        Design: Corner/entities/patient_list_pagination_limit_offset_total_count_and_has_more
        """
        create_patient(mrn="MRN-1001", display_name="Pat One", registry_consent="GRANTED")
        declined = create_patient(
            mrn="MRN-1002", display_name="Pat Two", registry_consent="DECLINED"
        )
        create_patient(mrn="MRN-1003", display_name="Pat Three", registry_consent="UNKNOWN")

        first_page = api.list_patients(CC, {"limit": 2, "offset": 0})
        rows, meta = validate_paginated(first_page)
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert len(rows) == 2
        assert first_page.json()["response_type"] == "array"
        assert_created_at_ascending(rows)

        rows, meta = validate_paginated(api.list_patients(CC, {"limit": 2, "offset": 2}))
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert len(rows) == 1

        rows, meta = validate_paginated(
            api.list_patients(CC, {"registry_consent": "DECLINED"})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == declined["id"]

        validate_error(
            api.list_patients(CC, {"limit": 101}),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )


class TestLotConservation:
    def test_lot_auto_depletes_when_its_last_on_hand_unit_is_wasted(self, api):
        """PRD §3.2: "Both source states share one side-effect set: the lot's
        `on_hand_qty` and `consumed_qty` and the catalog item's
        `on_hand_available_qty` are re-derived, and when the lot is `AVAILABLE` and
        its recomputed `on_hand_qty` reaches 0 while `received_qty` is at least 1,
        the lot auto-transitions `AVAILABLE → DEPLETED`."
        PRD §2.11: "`consumed_qty` is the count of those whose `custody_state` is
        `IMPLANTED`, `EXPLANTED`, `WASTED`, `EXPIRED`, `RETURNED_TO_VENDOR` or
        `DISPOSED`."

        Design: Corner/state_machines/lot_auto_depletes_when_its_last_on_hand_unit_is_wasted
        """
        world = setup_stock((400_000,), clock=None)
        unit = world["units"][0]

        wasted = validate_success(api.waste_device_unit(unit["id"], CC), 200)
        assert wasted["custody_state"] == "WASTED"

        lot = get_lot(world["lot"]["id"])
        assert lot["status"] == "DEPLETED"
        assert lot["received_qty"] == 1
        assert lot["on_hand_qty"] == 0
        assert lot["consumed_qty"] == 1
        assert_lot_conservation(lot)
        assert get_catalog_item(world["catalog_item"]["id"])["on_hand_available_qty"] == 0

    def test_reserve_then_release_leaves_every_lot_counter_numerically_identical(self, api):
        """PRD §2.11: "The ten custody states partition into exactly those two
        buckets with none omitted and none double-counted, so `on_hand_qty` plus
        `consumed_qty` always equals `received_qty`."
        PRD §2.11: "The canonical compensating pair is the reserve-then-unreserve
        round trip: both `AVAILABLE` and `RESERVED` sit in the on-hand bucket, so
        reserving a unit and then releasing that reservation leaves all three
        counters numerically identical to where they started."

        Design: Difficulty/compensating_invariant/lot_unit_count_conserved_across_reserve_release_roundtrip
        """
        world = setup_stock((400_000, 400_000, 400_000))
        lot_id = world["lot"]["id"]
        unit = world["units"][0]
        case = setup_scheduled_case()["case"]

        before = get_lot(lot_id)
        assert (before["received_qty"], before["on_hand_qty"], before["consumed_qty"]) == (
            3,
            3,
            0,
        )
        assert_lot_conservation(before)

        reserve_unit(case["id"], unit["id"])
        during = get_lot(lot_id)
        assert (during["received_qty"], during["on_hand_qty"], during["consumed_qty"]) == (
            3,
            3,
            0,
        )
        assert_lot_conservation(during)

        validate_success(api.release_reservation(unit["id"], IL), 200)
        after = get_lot(lot_id)
        assert (after["received_qty"], after["on_hand_qty"], after["consumed_qty"]) == (
            3,
            3,
            0,
        )
        assert_lot_conservation(after)
        assert after["status"] == "AVAILABLE", "The lot must never reach DEPLETED here"

    def test_reservation_round_trip_restores_availability_and_clears_the_case_link(
        self, api
    ):
        """PRD §3.4: "It moves the unit `RESERVED → AVAILABLE`, clears
        `reserved_case_id`, re-derives the catalog item's `on_hand_available_qty`
        and the case's `readiness_status`, and — as §2.11 promised — leaves the
        lot's `on_hand_qty` and `consumed_qty` numerically unchanged, because both
        `AVAILABLE` and `RESERVED` sit in the same conservation bucket."
        PRD §2.12: "`on_hand_available_qty` on a catalog item counts that item's
        units whose `custody_state` is `AVAILABLE`."

        Design: Difficulty/compensating_invariant/lot_unit_count_conserved_across_reserve_release_roundtrip
        """
        world = setup_stock((400_000, 400_000, 400_000))
        catalog_item_id = world["catalog_item"]["id"]
        unit = world["units"][0]
        case = setup_scheduled_case()["case"]

        assert get_catalog_item(catalog_item_id)["on_hand_available_qty"] == 3

        reserve_unit(case["id"], unit["id"])
        assert get_catalog_item(catalog_item_id)["on_hand_available_qty"] == 2
        assert get_unit(unit["id"])["custody_state"] == "RESERVED"

        released = validate_success(api.release_reservation(unit["id"], IL), 200)
        assert released["custody_state"] == "AVAILABLE"
        assert released["reserved_case_id"] is None
        assert get_catalog_item(catalog_item_id)["on_hand_available_qty"] == 3
        assert_lot_conservation(get_lot(world["lot"]["id"]))
