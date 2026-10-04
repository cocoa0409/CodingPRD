"""Breadth tests: creation defaults, reads, listing and derived lot fields."""

import pytest

from test_helpers import (
    api_client,
    get_success_data,
    setup_clinic,
    setup_active_patient,
    register_patient,
    set_clock,
    create_patient_payload,
    create_lot_payload,
    create_arrangement_payload,
    create_dose_dispense_payload,
    schedule_dose,
    check_in_dose,
    verify_dose,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
    validate_error,
    validate_paginated,
    NON_EXISTENT_UUID,
    ApiErrorId,
)


class TestPatientRegistration:
    """Registration produces the documented defaults and system fields."""

    def test_registration_lands_the_patient_in_pending_admission_with_defaults(self):
        """PRD 3.1: "The registration lands the patient in `PENDING_ADMISSION`
        with `diagnosis_confirmed` false, `time_in_treatment_days` at 0, and a
        freshly computed published stability reading copied into
        `stability_posting`."
        PRD 3.2: "The `counseling_standing` dimension takes `CURRENT`,
        `COUNSELING_DEFICIENT` or `REVIEW_OVERDUE`, defaults to `CURRENT`."
        PRD 3.2: "The `diversion_standing` dimension takes `CLEAR`,
        `UNDER_INVESTIGATION` or `CONFIRMED_DIVERSION`, defaults to `CLEAR`."
        PRD 2.4: "`id` (string) — a unique, server-minted identifier formatted as
        a UUID."

        Design: Corner/entities/patient_create_defaults_and_system_fields
        """
        clinic = setup_clinic(create_quota=False, create_lot=False)
        set_clock("2026-09-01T00:00:00Z")
        patient = register_patient(clinic, transportation_type="NO_RELIABLE_TRANSPORT",
                                   one_way_travel_minutes=95)

        assert is_valid_uuid(patient["id"])
        assert is_iso8601_timestamp(patient["created_at"])
        assert is_iso8601_timestamp(patient["updated_at"])
        assert isinstance(patient["version"], int)
        assert patient["status"] == "PENDING_ADMISSION"
        assert patient["diagnosis_confirmed"] is False
        assert patient["treatment_phase"] == "INDUCTION"
        assert patient["counseling_standing"] == "CURRENT"
        assert patient["diversion_standing"] == "CLEAR"
        assert patient["time_in_treatment_days"] == 0
        assert patient["admission_datetime"] is None
        assert patient["denial_count_12mo"] == 0
        assert patient["carries_used"] == 0
        assert patient["missed_dose_streak"] == 0


class TestPatientListing:
    """The list endpoint honours limit and offset against a known row set."""

    def test_limit_and_offset_partition_the_result_set(self):
        """PRD 2.3: "The `limit` parameter caps how many items a single page
        returns; it defaults to 10, must be no smaller than 1, and must be no
        larger than 100. The `offset` parameter states how many items to skip
        before the page begins and defaults to 0."
        PRD 2.3: "List-based responses (in both their paginated and
        non-paginated forms) place four fields in the `meta` object of the
        envelope: `limit`, `offset`, `total_count` and `has_more`."

        Design: Corner/entities/patient_read_and_list_pagination_envelope
        """
        clinic = setup_clinic(create_quota=False, create_lot=False)
        set_clock("2026-09-01T00:00:00Z")
        for i, name in enumerate(("Ada Patient", "Bea Patient", "Cara Patient")):
            register_patient(clinic, full_name=name, government_id_hash=f"sha256:aaaa000{i + 1}")

        first, meta_first = validate_paginated(api_client.list_patients(
            clinic["nurse_headers"], {"program_id": clinic["program"]["id"],
                                      "limit": 2, "offset": 0}))
        assert len(first) == 2
        assert meta_first["total_count"] == 3
        assert meta_first["has_more"] is True

        second, meta_second = validate_paginated(api_client.list_patients(
            clinic["nurse_headers"], {"program_id": clinic["program"]["id"],
                                      "limit": 2, "offset": 2}))
        assert len(second) == 1
        assert meta_second["total_count"] == 3
        assert meta_second["has_more"] is False

        ids = [p["id"] for p in first] + [p["id"] for p in second]
        assert len(set(ids)) == 3, "the two pages must cover three distinct patients"


class TestProgramReadExistence:
    """A well-formed but absent identifier is a 404, not a 400."""

    def test_an_absent_program_id_returns_not_found(self):
        """PRD 2.11: "The request fails with the 404 code corresponding to the
        first identifier that does not resolve — for example,
        `ERR_PROGRAM_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`,
        `ERR_DOSE_ORDER_NOT_FOUND`."
        PRD 5: "| `ERR_PROGRAM_NOT_FOUND` | 404 Not Found |"

        Design: Corner/entities/program_get_with_unknown_id_returns_not_found
        """
        set_clock("2026-09-01T00:00:00Z")
        res = api_client.get_program(NON_EXISTENT_UUID,
                                     {"X-User-ID": "op-1",
                                      "X-User-Role": "ProgramAdministrator"})
        err = validate_error(res, ApiErrorId.ERR_PROGRAM_NOT_FOUND.value)
        assert err["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value


class TestInventoryLotDerivedFields:
    """On-hand and expiry are derived from the logical clock, never supplied."""

    def test_on_hand_tracks_receipt_and_expiry_follows_the_clock(self):
        """PRD 2.9: "`is_expired` is true when the logical clock's date is on or
        after the lot's `expiration_date`."
        PRD 2.9: "Each lot maintains `running_on_hand_mg` as its received
        quantity plus the sum of `quantity_mg` over its `InventoryTransaction`
        rows with status `RECORDED` or `RECONCILED`."
        PRD 2.9: "an `expiration_date` that is exclusive — the lot is unusable
        on and after that date."

        Design: Corner/entities/inventory_lot_on_hand_and_expiry_are_computed_from_the_logical_clock
        """
        clinic = setup_clinic(create_quota=False, create_lot=False)
        set_clock("2026-09-01T00:00:00Z")
        lot = validate_success(api_client.create_lot(
            create_lot_payload(clinic["program"]["id"], lot_number="LOT-EXP",
                               expiration_date="2026-11-01", quantity_received_mg=1000.0),
            clinic["admin_headers"]), 201)
        assert lot["status"] == "RECEIVED"
        assert lot["running_on_hand_mg"] == pytest.approx(1000.0, abs=0.01)
        assert lot["is_expired"] is False

        set_clock("2026-10-31T00:00:00Z")
        before = validate_success(api_client.get_lot(lot["id"], clinic["admin_headers"]))
        assert before["is_expired"] is False
        assert before["running_on_hand_mg"] == pytest.approx(1000.0, abs=0.01)

        set_clock("2026-11-01T00:00:00Z")
        at_expiry = validate_success(api_client.get_lot(lot["id"], clinic["admin_headers"]))
        assert at_expiry["is_expired"] is True, "the expiration date is exclusive"
        assert at_expiry["running_on_hand_mg"] == pytest.approx(1000.0, abs=0.01)


class TestDoseDispenseSystemFields:
    """Status and lifecycle stamps are server-owned on a freshly scheduled dose."""

    def test_a_new_dose_carries_only_server_owned_lifecycle_values(self):
        """PRD 3.4: "The new row begins in `SCHEDULED`."
        PRD 3.4: "The `dispensed_mg`, `wasted_mg` and `returned_mg` figures all
        begin at 0, as do `carry_count`, `carries_before` and `carries_after`;
        `verification_result`, `arrived_at` and `completed_at` are null until
        their respective steps occur."
        PRD 3.4: "The `ordered_mg` is snapshotted from the active order's
        `ordered_daily_mg`."

        Design: Corner/entities/dose_dispense_status_is_never_client_supplied
        """
        clinic = setup_clinic(lot_overrides={"lot_number": "LOT-A1"})
        set_clock("2026-09-01T00:00:00Z")
        patient, order = setup_active_patient(clinic, ordered_daily_mg=90.0)
        set_clock("2026-12-15T00:00:00Z")
        dose = schedule_dose(clinic, order["id"], "2026-12-21", "2026-12-21T07:00:00Z",
                             inventory_lot_id=clinic["lot"]["id"])

        assert dose["status"] == "SCHEDULED"
        assert dose["source_type"] == "OBSERVED_CLINIC"
        assert dose["verification_result"] is None
        assert dose["arrived_at"] is None
        assert dose["completed_at"] is None
        assert dose["carry_count"] == 0
        assert dose["carries_before"] == 0
        assert dose["carries_after"] == 0
        assert dose["ordered_mg"] == pytest.approx(90.0, abs=0.01)
        assert isinstance(dose["version"], int)


class TestDoseSourceTypeEnum:
    """source_type is a closed enumeration."""

    def test_an_out_of_enum_source_type_is_rejected(self):
        """PRD 3.4: "The `source_type` defaults to `OBSERVED_CLINIC` and may
        otherwise be `TAKE_HOME_ISSUANCE` or `GUEST_OBSERVED`."
        PRD 2.11: "Constraint checks then run: titration (priority 14), mass
        balance (priority 15), partial-dispense accumulation (priority 16),
        witness requirements (priority 17), carry determination (priority 18),
        the stability floor (priority 19), carry quota (priority 20), the
        inventory ceiling (priority 21), lot usability (priority 22), guest
        token validity (priority 23), exception carry caps (priority 24), text
        minimum lengths (priority 25) and finally closed-enum and numeric-range
        checks (priority 26, `ERR_INVALID_REQUEST`)."

        Design: Corner/entities/dose_dispense_rejects_unknown_source_type_enum_value
        """
        clinic = setup_clinic(lot_overrides={"lot_number": "LOT-A1"})
        set_clock("2026-09-01T00:00:00Z")
        patient, order = setup_active_patient(clinic, ordered_daily_mg=90.0)
        set_clock("2026-12-15T00:00:00Z")

        res = api_client.create_dose_dispense(create_dose_dispense_payload(
            order["id"], "2026-12-21", "2026-12-21T07:00:00Z", "CLINIC_DISPENSE",
            clinic["lot"]["id"]), clinic["nurse_headers"])
        err = validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)
        assert err["error_id"] != ApiErrorId.ERR_OUTSIDE_CLINIC_HOURS.value

        rows, _meta = validate_paginated(api_client.list_dose_dispenses(
            clinic["nurse_headers"], {"dose_order_id": order["id"]}))
        assert rows == [], "a rejected request must not create a row"


class TestGuestArrangementReverseLookup:
    """The arrangement carries two keys to the same parent type."""

    def test_both_program_filters_resolve_the_same_row(self):
        """PRD 3.11: "The `originating_program_id` is not supplied by the client
        at all — it is taken from the patient's own admitting `program_id`."
        PRD 4: "| GET | `/otp/guest-dosing-arrangements` | List guest
        arrangements |"
        PRD 3.11: "The arrangement begins in `DRAFT` status with `token_consumed`
        false, `receiving_acknowledged_at` null and `dose_authorization_token`
        unset; the token is minted at transmission, not at creation."

        Design: Corner/entities/guest_arrangement_reverse_lookup_from_both_programs
        """
        clinic = setup_clinic(create_quota=False, lot_overrides={"lot_number": "LOT-ORIG"})
        set_clock("2026-09-01T00:00:00Z")
        patient, order = setup_active_patient(clinic, ordered_daily_mg=16.0,
                                              medication="BUPRENORPHINE")
        set_clock("2026-12-15T00:00:00Z")
        receiving = get_success_data(api_client.create_program({
            "name": "BayMark Coast", "state_code": "CA",
            "clinic_hours_start": "08:00", "clinic_hours_end": "10:00",
            "open_days": ["SA"], "max_daily_dose_slots": 10,
            "max_daily_mg_methadone": 120.0, "max_daily_mg_buprenorphine": 24.0,
            "guest_dosing_enabled": True, "dose_checkin_grace_minutes": 30},
            clinic["admin_headers"]))

        current = get_success_data(api_client.get_patient(patient["id"],
                                                          clinic["physician_headers"]))
        arr = validate_success(api_client.create_arrangement(
            create_arrangement_payload(patient["id"], receiving["id"], current["version"]),
            clinic["admin_headers"]), 201)
        assert arr["originating_program_id"] == clinic["program"]["id"]
        assert arr["receiving_program_id"] == receiving["id"]
        assert arr["status"] == "DRAFT"
        assert arr["authorized_mg"] is None
        assert arr["token_consumed"] is False

        by_origin, _m1 = validate_paginated(api_client.list_arrangements(
            clinic["admin_headers"], {"originating_program_id": clinic["program"]["id"]}))
        by_receiving, _m2 = validate_paginated(api_client.list_arrangements(
            clinic["admin_headers"], {"receiving_program_id": receiving["id"]}))
        assert len(by_origin) == 1 and by_origin[0]["id"] == arr["id"]
        assert len(by_receiving) == 1 and by_receiving[0]["id"] == arr["id"]


class TestLotSelectorResolvesWithoutAnExplicitLot:
    """A dispense that names no lot lets the deterministic selector choose one."""

    def test_the_selector_draws_from_the_earliest_expiring_usable_lot(self):
        """PRD 2.9: "Candidates are ranked by `expiration_date` ascending so
        that the earliest usable expiration is drawn first, with ties broken by
        `created_at` ascending."
        PRD 2.9: "The candidate set is every lot satisfying all of the
        following: it belongs to the dose's program; its medication matches the
        order's medication; its status is `IN_USE`; it is not expired; its
        `running_on_hand_mg` is at least the dose's `ordered_mg`."
        PRD 3.4: "A `DISPENSE` movement is appended with a negative `quantity_mg`
        equal to the dispensed milligrams and the selected lot recorded as
        `lot_id`."

        Design: Corner/entities/exclusion_from_the_ordering_queue_after_the_cutoff
        """
        clinic = setup_clinic(create_quota=False, create_lot=False)
        set_clock("2026-09-01T00:00:00Z")
        near = validate_success(api_client.create_lot(
            create_lot_payload(clinic["program"]["id"], lot_number="LOT-NEAR",
                               expiration_date="2026-12-01", quantity_received_mg=50000.0,
                               reusable_for_take_home=True), clinic["admin_headers"]), 201)
        far = validate_success(api_client.create_lot(
            create_lot_payload(clinic["program"]["id"], lot_number="LOT-FAR",
                               expiration_date="2027-06-30", quantity_received_mg=50000.0,
                               reusable_for_take_home=True), clinic["admin_headers"]), 201)

        patient, order = setup_active_patient(clinic, ordered_daily_mg=90.0)
        set_clock("2026-12-15T00:00:00Z")
        dose = schedule_dose(clinic, order["id"], "2026-12-21", "2026-12-21T07:00:00Z")
        check_in_dose(clinic, dose["id"])
        verify_dose(clinic, dose["id"], True)

        # No inventory_lot_id: the selector must resolve an eligible lot itself.
        drawn = validate_success(api_client.dispense_dose(dose["id"], {
            "dispensed_mg": 90.0, "wasted_mg": 0.0, "returned_mg": 0.0},
            clinic["nurse_headers"]))
        assert drawn["status"] == "DISPENSED"

        near_after = validate_success(api_client.get_lot(near["id"], clinic["admin_headers"]))
        far_after = validate_success(api_client.get_lot(far["id"], clinic["admin_headers"]))
        # The nearer lot is unusable at the 2026-12-15 clock, so nothing is
        # drawn from it and the later lot carries the whole draw.
        assert near_after["is_expired"] is True
        assert near_after["running_on_hand_mg"] == pytest.approx(50000.0, abs=0.01)
        assert far_after["running_on_hand_mg"] == pytest.approx(49910.0, abs=0.01)

        near_txs, _m1 = validate_paginated(api_client.list_transactions(
            clinic["admin_headers"], {"lot_id": near["id"]}))
        assert near_txs == []
        far_txs, _m2 = validate_paginated(api_client.list_transactions(
            clinic["admin_headers"], {"lot_id": far["id"]}))
        dispenses = [t for t in far_txs if t["transaction_type"] == "DISPENSE"]
        assert len(dispenses) == 1
        assert dispenses[0]["quantity_mg"] == pytest.approx(-90.0)