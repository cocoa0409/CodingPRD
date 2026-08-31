"""Operating-room scheduling geometry and the reservation round trip."""

from test_helpers import (
    ApiErrorId,
    CC,
    IL,
    add_lot_to_stock,
    create_case,
    create_patient,
    get_case,
    get_catalog_item,
    get_lot,
    get_unit,
    reserve_unit,
    set_clock,
    setup_scheduled_case,
    setup_stock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestOperatingRoomGeometry:
    def test_room_booking_that_only_touches_an_existing_window_is_accepted(self, api):
        """PRD §3.3: "The room rule is half-open and unbuffered: the requested
        window is treated as including its start instant and excluding its end
        instant, and it is compared against the identically-treated window of every
        other case in the same `or_room_code` whose `status` is `SCHEDULED` or
        `IN_PROGRESS`."
        PRD §3.3: "Two windows that merely touch — one case's end instant equal to
        another's start instant — do **not** intersect and are accepted, which is
        what lets a room be turned over back to back."

        Design: Difficulty/resource_temporal_overlap/or_room_half_open_interval_rejects_only_true_intersection
        """
        set_clock("2026-09-01T00:00:00Z")
        patient_one = create_patient(mrn="MRN-1001", display_name="Pat One")
        patient_two = create_patient(mrn="MRN-1002", display_name="Pat Two")
        create_case(
            patient_one["id"],
            case_number="CASE-1",
            or_room_code="OR-3",
            scheduled_start_utc="2026-09-10T08:00:00Z",
            scheduled_end_utc="2026-09-10T10:00:00Z",
        )

        touching = validate_success(
            api.create_surgical_case(
                {
                    "patient_id": patient_two["id"],
                    "case_number": "CASE-2",
                    "or_room_code": "OR-3",
                    "scheduled_start_utc": "2026-09-10T10:00:00Z",
                    "scheduled_end_utc": "2026-09-10T12:00:00Z",
                    "surgeon_code": "SURG-9",
                },
                CC,
            ),
            201,
        )
        assert touching["status"] == "SCHEDULED"

        _, meta = validate_paginated(api.list_surgical_cases(CC, {"or_room_code": "OR-3"}))
        assert meta["total_count"] == 2

    def test_room_booking_that_genuinely_overlaps_is_rejected(self, api):
        """PRD §3.3: "Two windows that merely touch — one case's end instant equal
        to another's start instant — do **not** intersect and are accepted, which
        is what lets a room be turned over back to back. A genuine overlap is
        rejected with `ERR_OR_ROOM_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/or_room_half_open_interval_rejects_only_true_intersection
        """
        set_clock("2026-09-01T00:00:00Z")
        patient_one = create_patient(mrn="MRN-1001", display_name="Pat One")
        patient_three = create_patient(mrn="MRN-1003", display_name="Pat Three")
        create_case(
            patient_one["id"],
            case_number="CASE-1",
            or_room_code="OR-3",
            scheduled_start_utc="2026-09-10T08:00:00Z",
            scheduled_end_utc="2026-09-10T10:00:00Z",
        )

        validate_error(
            api.create_surgical_case(
                {
                    "patient_id": patient_three["id"],
                    "case_number": "CASE-3",
                    "or_room_code": "OR-3",
                    "scheduled_start_utc": "2026-09-10T09:59:00Z",
                    "scheduled_end_utc": "2026-09-10T11:00:00Z",
                    "surgeon_code": "SURG-9",
                },
                CC,
            ),
            ApiErrorId.ERR_OR_ROOM_CONFLICT,
            409,
        )

        _, meta = validate_paginated(api.list_surgical_cases(CC, {"or_room_code": "OR-3"}))
        assert meta["total_count"] == 1


class TestPatientRecoveryGeometry:
    def test_buffered_windows_that_touch_at_their_endpoints_are_rejected(self, api):
        """PRD §3.3: "Take the requested window and every existing window of the
        same `patient_id` whose case `status` is `SCHEDULED` or `IN_PROGRESS`, and
        expand each by a recovery buffer of 120 minutes — two hours — on *each*
        side — that is, from two hours before its start to two hours after its end
        — then compare the expanded windows as closed intervals in which both
        endpoints belong to the interval."
        PRD §3.3: "Under closed comparison, touching endpoints **do** intersect and
        the request is rejected with `ERR_PATIENT_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/patient_recovery_buffered_closed_interval_rejects_touching_windows
        """
        set_clock("2026-09-01T00:00:00Z")
        patient = create_patient(mrn="MRN-1001", display_name="Pat One")
        create_case(
            patient["id"],
            case_number="CASE-1",
            or_room_code="OR-3",
            scheduled_start_utc="2026-09-10T08:00:00Z",
            scheduled_end_utc="2026-09-10T10:00:00Z",
        )

        # Requested 14:00-15:00 buffers back to 12:00, exactly touching the
        # existing case's buffered end of 12:00.  OR-9 is empty, so the room rule
        # cannot fire.
        validate_error(
            api.create_surgical_case(
                {
                    "patient_id": patient["id"],
                    "case_number": "CASE-2",
                    "or_room_code": "OR-9",
                    "scheduled_start_utc": "2026-09-10T14:00:00Z",
                    "scheduled_end_utc": "2026-09-10T15:00:00Z",
                    "surgeon_code": "SURG-9",
                },
                CC,
            ),
            ApiErrorId.ERR_PATIENT_SCHEDULE_CONFLICT,
            409,
        )

        _, meta = validate_paginated(
            api.list_surgical_cases(CC, {"patient_id": patient["id"]})
        )
        assert meta["total_count"] == 1

    def test_one_second_clear_of_the_recovery_buffer_is_accepted(self, api):
        """PRD §3.3: "The patient rule is closed and buffered, because a human body
        needs recovery time that a room does not."
        PRD §3.3: "Under closed comparison, touching endpoints **do** intersect and
        the request is rejected with `ERR_PATIENT_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/patient_recovery_buffered_closed_interval_rejects_touching_windows
        """
        set_clock("2026-09-01T00:00:00Z")
        patient = create_patient(mrn="MRN-1001", display_name="Pat One")
        create_case(
            patient["id"],
            case_number="CASE-1",
            or_room_code="OR-3",
            scheduled_start_utc="2026-09-10T08:00:00Z",
            scheduled_end_utc="2026-09-10T10:00:00Z",
        )

        accepted = validate_success(
            api.create_surgical_case(
                {
                    "patient_id": patient["id"],
                    "case_number": "CASE-3",
                    "or_room_code": "OR-9",
                    "scheduled_start_utc": "2026-09-10T14:00:01Z",
                    "scheduled_end_utc": "2026-09-10T15:00:00Z",
                    "surgeon_code": "SURG-9",
                },
                CC,
            ),
            201,
        )
        assert accepted["status"] == "SCHEDULED"

        _, meta = validate_paginated(
            api.list_surgical_cases(CC, {"patient_id": patient["id"]})
        )
        assert meta["total_count"] == 2
        assert get_case(accepted["id"])["patient_id"] == patient["id"]

    def test_case_end_equal_to_its_start_is_malformed(self, api):
        """PRD §3.3: "The end must be strictly after the start, and a request that
        violates that is malformed rather than conflicting."

        Design: Corner/entities/surgical_case_end_not_after_start_returns_invalid_request
        """
        patient = create_patient()

        validate_error(
            api.create_surgical_case(
                {
                    "patient_id": patient["id"],
                    "case_number": "CASE-1",
                    "or_room_code": "OR-3",
                    "scheduled_start_utc": "2026-09-10T08:00:00Z",
                    "scheduled_end_utc": "2026-09-10T08:00:00Z",
                    "surgeon_code": "SURG-9",
                },
                CC,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )

        _, meta = validate_paginated(
            api.list_surgical_cases(CC, {"patient_id": patient["id"]})
        )
        assert meta["total_count"] == 0


class TestReservationSelector:
    def test_supplying_both_selector_fields_is_malformed(self, api):
        """PRD §3.4: "Supplying `catalog_item_id` asks the server to pick a serial;
        supplying `device_unit_id` pins a specific one. Supplying both, or neither,
        is malformed and is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/reservation_with_both_selector_fields_returns_invalid_request
        """
        world = setup_stock((400_000,))
        case = setup_scheduled_case()["case"]

        validate_error(
            api.create_reservation(
                case["id"],
                {
                    "catalog_item_id": world["catalog_item"]["id"],
                    "device_unit_id": world["units"][0]["id"],
                },
                CC,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )
        assert get_unit(world["units"][0]["id"])["custody_state"] == "AVAILABLE"

    def test_catalog_driven_pick_takes_the_earliest_expiring_lot_then_the_oldest_unit(
        self, api
    ):
        """PRD §3.4: "The pool is then ordered by the lot's `expiration_date`
        ascending, so that the stock closest to expiring leaves the shelf first;
        ties on that date are broken by the lot's `received_at_utc` ascending, and
        any remaining tie by the device unit's own `created_at` ascending."
        PRD §3.4: "No part of this selection ever reads a resource `id`. The first
        candidate in that order is the one reserved."

        Design: Corner/calculations/fefo_selector_picks_earliest_expiring_lot_then_oldest_unit
        """
        world = setup_stock(
            (400_000,),
            serials=["SN-L"],
            lot_overrides={"lot_number": "L-LATE", "expiration_date": "2027-06-30"},
        )
        early = add_lot_to_stock(
            world,
            (400_000, 400_000),
            lot_number="L-EARLY",
            expiration_date="2027-01-31",
            serials=["SN-E1", "SN-E2"],
        )

        patient_one = create_patient(mrn="MRN-1001", display_name="Pat One")
        patient_two = create_patient(mrn="MRN-1002", display_name="Pat Two")
        case_one = create_case(
            patient_one["id"],
            case_number="CASE-1",
            or_room_code="OR-3",
            scheduled_start_utc="2026-09-10T08:00:00Z",
            scheduled_end_utc="2026-09-10T10:00:00Z",
        )
        case_two = create_case(
            patient_two["id"],
            case_number="CASE-2",
            or_room_code="OR-4",
            scheduled_start_utc="2026-09-11T08:00:00Z",
            scheduled_end_utc="2026-09-11T10:00:00Z",
        )

        first_pick = validate_success(
            api.create_reservation(
                case_one["id"], {"catalog_item_id": world["catalog_item"]["id"]}, CC
            ),
            201,
        )
        second_pick = validate_success(
            api.create_reservation(
                case_two["id"], {"catalog_item_id": world["catalog_item"]["id"]}, CC
            ),
            201,
        )

        assert first_pick["udi_serial"] == "SN-E1"
        assert first_pick["id"] == early["units"][0]["id"]
        assert second_pick["udi_serial"] == "SN-E2"
        assert second_pick["id"] == early["units"][1]["id"]
        assert first_pick["reserved_case_id"] == case_one["id"]
        assert second_pick["reserved_case_id"] == case_two["id"]

        assert get_unit(world["units"][0]["id"])["custody_state"] == "AVAILABLE"
        assert get_catalog_item(world["catalog_item"]["id"])["on_hand_available_qty"] == 1

    def test_a_lot_expiring_before_the_case_ends_empties_the_candidate_pool(self, api):
        """PRD §3.4: "The eligible pool is every device unit whose `custody_state`
        is `AVAILABLE`, whose `reserved_case_id` is null, whose lot's `status` is
        `AVAILABLE`, whose lot's `catalog_item_id` equals the requested one, and
        whose lot expiry instant is strictly after the case's `scheduled_end_utc`."
        PRD §3.4: "If the pool is empty, the request is rejected with
        `ERR_NO_ELIGIBLE_UNIT`."

        Design: Corner/calculations/fefo_empty_candidate_pool_returns_no_eligible_unit
        """
        world = setup_stock(
            (400_000,),
            lot_overrides={"lot_number": "L-SHORT", "expiration_date": "2026-09-15"},
        )
        case = setup_scheduled_case(
            scheduled_start_utc="2026-09-20T08:00:00Z",
            scheduled_end_utc="2026-09-20T10:00:00Z",
        )["case"]

        validate_error(
            api.create_reservation(
                case["id"], {"catalog_item_id": world["catalog_item"]["id"]}, CC
            ),
            ApiErrorId.ERR_NO_ELIGIBLE_UNIT,
            409,
        )

        unit = get_unit(world["units"][0]["id"])
        assert unit["custody_state"] == "AVAILABLE"
        assert unit["reserved_case_id"] is None
        assert get_case(case["id"])["blocked_reservation_count"] == 0


class TestCaseLifecycleGuards:
    def test_starting_an_already_started_case_is_rejected(self, api):
        """PRD §3.3: "Starting a case moves it `SCHEDULED → IN_PROGRESS` and
        advances the case's `version` by one; a case not in `SCHEDULED` cannot be
        started and is rejected with `ERR_INVALID_CASE_STATE`."

        Design: Corner/state_machines/start_an_already_started_case_returns_invalid_case_state
        """
        case = setup_scheduled_case()["case"]
        started = validate_success(api.start_case(case["id"], CC), 200)
        assert started["status"] == "IN_PROGRESS"
        assert started["version"] == case["version"] + 1

        validate_error(
            api.start_case(case["id"], CC), ApiErrorId.ERR_INVALID_CASE_STATE, 409
        )

        after = get_case(case["id"])
        assert after["status"] == "IN_PROGRESS"
        assert after["version"] == started["version"], (
            "The rejected start must not advance the case version"
        )

    def test_close_frees_reserved_stock_and_the_terminal_case_refuses_a_cancel(self, api):
        """PRD §3.11: "A `READY` case moves `IN_PROGRESS → CLOSED`, and every
        device unit still `RESERVED` to it is released back to `AVAILABLE` with
        `reserved_case_id` cleared and the catalog item's `on_hand_available_qty`
        re-derived."
        PRD §3.3: "A case in any terminal state cannot be cancelled again."
        PRD §2.6: "Path-target state — the resource named by the path is in a state
        from which the requested transition is declared."

        Design: Corner/state_machines/close_releases_reservations_then_terminal_case_rejects_cancel
        """
        world = setup_stock((400_000,))
        case = setup_scheduled_case()["case"]
        reserve_unit(case["id"], world["units"][0]["id"])
        validate_success(api.start_case(case["id"], CC), 200)

        closed = validate_success(api.close_case(case["id"], CC), 200)
        assert closed["status"] == "CLOSED"

        unit = get_unit(world["units"][0]["id"])
        assert unit["custody_state"] == "AVAILABLE"
        assert unit["reserved_case_id"] is None
        assert get_catalog_item(world["catalog_item"]["id"])["on_hand_available_qty"] == 1

        validate_error(
            api.cancel_case(case["id"], CC), ApiErrorId.ERR_INVALID_CASE_STATE, 409
        )
        assert get_case(case["id"])["status"] == "CLOSED"

    def test_reservation_side_effects_are_visible_in_the_very_next_read(self, api):
        """PRD §2.12: "Cascades run to completion inside the request that triggered
        them, and the effects are visible in that same response."
        PRD §3.4: "Whichever form was used, reserving moves the chosen unit
        `AVAILABLE → RESERVED`, sets its `reserved_case_id` to the case, decrements
        the case's `blocked_reservation_count` by one but never below zero,
        re-derives the catalog item's `on_hand_available_qty`, and re-derives the
        case's `readiness_status`."
        PRD §2.12: "`on_hand_available_qty` on a catalog item counts that item's
        units whose `custody_state` is `AVAILABLE`."

        Design: Corner/consistency_model/immediate_consistency_of_derived_counters_within_one_request
        """
        world = setup_stock((400_000, 400_000))
        catalog_item_id = world["catalog_item"]["id"]
        case = setup_scheduled_case()["case"]

        assert get_catalog_item(catalog_item_id)["on_hand_available_qty"] == 2

        reserved = validate_success(
            api.create_reservation(
                case["id"], {"device_unit_id": world["units"][0]["id"]}, CC
            ),
            201,
        )
        assert reserved["custody_state"] == "RESERVED"
        assert reserved["reserved_case_id"] == case["id"]

        assert get_catalog_item(catalog_item_id)["on_hand_available_qty"] == 1

        lot = get_lot(world["lot"]["id"])
        assert lot["on_hand_qty"] == 2
        assert lot["consumed_qty"] == 0

        refreshed_case = get_case(case["id"])
        assert refreshed_case["readiness_status"] == "READY"
        assert refreshed_case["blocked_reservation_count"] == 0
