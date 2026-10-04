"""Tests for the booking validation chain: slot-state gate, lead time, plan
acceptance, type mapping, and the new-patient gate (PRD §3.4 and §3.5).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    book_slot,
    create_attestation,
    create_patient,
    create_plan,
    create_slot,
    get_slot,
    make_patient_headers,
    make_provider_headers,
    set_clock,
    setup_bookable_practice,
    setup_completed_booking,
    slot_time,
    validate_error,
    validate_success,
    verify_attestation,
)


class TestBookingRequiresSlotOpen:
    def test_booking_on_closed_slot_rejected(self, api):
        """PRD §3.4: "The slot must be `OPEN`, otherwise `ERR_SLOT_NOT_OPEN`."

        Design: Difficulty/cross_entity_state_dependency/booking_requires_slot_open
        """
        ctx = setup_bookable_practice(slot_windows=[slot_time(48)])
        slot = ctx["slots"][0]
        patient = create_patient()
        api_client.close_slot(slot["id"], make_provider_headers(ctx["provider"]["id"]))
        resp = api_client.create_booking(
            slot["id"],
            {"patient_id": patient["id"], "appointment_type_id": ctx["type"]["id"]},
            make_patient_headers(patient["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_NOT_OPEN)
        slot_after = get_slot(slot["id"])
        assert slot_after["status"] == "CLOSED"
        assert slot_after["close_reason"] == "PROVIDER_CLOSED"

    def test_closed_slot_creates_no_booking(self, api):
        """PRD §3.4: "The slot must be `OPEN`, otherwise `ERR_SLOT_NOT_OPEN`."
        PRD §3.4: "A successful booking is created in `CONFIRMED` status, pins `booked_copay_cents` from the appointment type, flips the slot from `OPEN` to `BOOKED`, and sets the slot's `current_booking_id`."

        Design: Difficulty/cross_entity_state_dependency/booking_requires_slot_open
        """
        ctx = setup_bookable_practice(slot_windows=[slot_time(48)])
        slot = ctx["slots"][0]
        patient = create_patient()
        api_client.close_slot(slot["id"], make_provider_headers(ctx["provider"]["id"]))
        api_client.create_booking(
            slot["id"],
            {"patient_id": patient["id"], "appointment_type_id": ctx["type"]["id"]},
            make_patient_headers(patient["id"]),
        )
        resp = api_client.list_bookings(
            TEST_USERS["ops_admin_headers"], params={"slot_id": slot["id"]}
        )
        data = validate_success(resp)
        items = data if isinstance(data, list) else data.get("data", [])
        assert len(items) == 0, f"no booking row may exist for a rejected booking, got {len(items)}"


class TestLeadTime:
    def test_new_patient_booking_12h_ahead_rejected(self, api):
        """PRD §3.4: "The gap between the slot's `start_at` and now must be at least the applicable number of hours; exactly the lead time passes, one second less fails with `ERR_LEAD_TIME_VIOLATION`."
        PRD §3.1: "`new_patient_lead_time_hours` defaults to 24 hours and `existing_patient_lead_time_hours` defaults to 4 hours."

        Design: Corner/calculations/lead_time_new_patient_violation_rejected
        """
        ctx = setup_bookable_practice(slot_windows=[slot_time(34)])
        patient = create_patient()
        # Clock at default+22h; slot is 12h ahead of the clock, under the 24h lead.
        set_clock("2026-09-01T22:00:00Z")
        resp = api_client.create_booking(
            ctx["slots"][0]["id"],
            {"patient_id": patient["id"], "appointment_type_id": ctx["type"]["id"]},
            make_patient_headers(patient["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LEAD_TIME_VIOLATION)
        slot_after = get_slot(ctx["slots"][0]["id"])
        assert slot_after["status"] == "OPEN", "rejected booking must not write back to the slot"

    def test_existing_patient_books_12h_ahead_under_4h_lead(self, api):
        """PRD §3.4: "A patient is new — the booking's computed `is_new_patient` flag is true — exactly when they have no `COMPLETED` booking with this practice at booking time."
        PRD §3.1: "`existing_patient_lead_time_hours` defaults to 4 hours."

        Design: Corner/calculations/lead_time_new_vs_existing_patient
        """
        ctx = setup_completed_booking()
        practice = ctx["practice"]
        provider = ctx["provider"]
        patient = ctx["patient"]
        # After the completed booking the patient is existing at this practice.
        # Create a new slot 12h ahead of the current clock and book it.
        set_clock("2026-09-03T22:00:00Z")
        slot = create_slot(provider["id"], "2026-09-04T10:00:00Z", "2026-09-04T10:30:00Z")
        resp = api_client.create_booking(
            slot["id"],
            {"patient_id": patient["id"], "appointment_type_id": ctx["type"]["id"]},
            make_patient_headers(patient["id"]),
        )
        data = validate_success(resp, 201)
        assert data["is_new_patient"] is False, (
            "one prior COMPLETED booking at this practice makes the patient existing"
        )


class TestPlanAcceptance:
    def test_attested_not_verified_attestation_rejected(self, api):
        """PRD §3.4: "When `insurance_plan_id` is provided, the slot's provider must hold a `VERIFIED` attestation for that plan whose window contains now; otherwise the booking is rejected with `ERR_PLAN_NOT_ACCEPTED`."

        Design: Corner/calculations/booking_without_verified_attestation_rejected
        """
        ctx = setup_bookable_practice(slot_windows=[slot_time(48), slot_time(49)])
        plan = create_plan()
        create_attestation(ctx["provider"]["id"], plan["id"])
        patient = create_patient(plan_id=plan["id"])
        resp = api_client.create_booking(
            ctx["slots"][0]["id"],
            {
                "patient_id": patient["id"],
                "appointment_type_id": ctx["type"]["id"],
                "insurance_plan_id": plan["id"],
            },
            make_patient_headers(patient["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACCEPTED)

    def test_self_pay_booking_on_same_provider_succeeds(self, api):
        """PRD §3.4: "A `Patient` books an `OPEN` slot by posting the patient's own `patient_id` (which must equal `X-User-ID`), an `appointment_type_id`, and optionally an `insurance_plan_id` (null means self-pay)."

        Design: Corner/calculations/booking_without_verified_attestation_rejected
        """
        ctx = setup_bookable_practice(slot_windows=[slot_time(48), slot_time(49)])
        plan = create_plan()
        create_attestation(ctx["provider"]["id"], plan["id"])
        patient = create_patient(plan_id=plan["id"])
        resp = api_client.create_booking(
            ctx["slots"][1]["id"],
            {"patient_id": patient["id"], "appointment_type_id": ctx["type"]["id"]},
            make_patient_headers(patient["id"]),
        )
        validate_success(resp, 201)

    def test_expired_attestation_window_rejected(self, api):
        """PRD §3.3: "Only a `VERIFIED` attestation whose window contains the current logical time — `effective_from` at or before now, and now strictly before `effective_to` — counts as actual acceptance, and that single fact drives both directory filtering and booking validation."

        Design: Corner/calculations/booking_with_expired_attestation_window_rejected
        """
        ctx = setup_bookable_practice(slot_windows=[slot_time(48)])
        plan = create_plan()
        att = create_attestation(
            ctx["provider"]["id"],
            plan["id"],
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-08-01T00:00:00Z",
        )
        verify_attestation(att["id"], "VERIFY")
        patient = create_patient(plan_id=plan["id"])
        resp = api_client.create_booking(
            ctx["slots"][0]["id"],
            {
                "patient_id": patient["id"],
                "appointment_type_id": ctx["type"]["id"],
                "insurance_plan_id": plan["id"],
            },
            make_patient_headers(patient["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACCEPTED)


class TestTypeMapping:
    def test_retired_type_booking_rejected(self, api):
        """PRD §3.4: "The appointment type must belong to the slot's provider and be `ACTIVE`; a type of another provider or a `RETIRED` type is rejected with `ERR_TYPE_MAPPING_MISSING`."

        Design: Corner/validations/retired_appointment_type_booking_rejected
        """
        ctx = setup_bookable_practice(slot_windows=[slot_time(48)])
        api_client.retire_appointment_type(
            ctx["type"]["id"], make_provider_headers(ctx["provider"]["id"])
        )
        patient = create_patient()
        resp = api_client.create_booking(
            ctx["slots"][0]["id"],
            {"patient_id": patient["id"], "appointment_type_id": ctx["type"]["id"]},
            make_patient_headers(patient["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TYPE_MAPPING_MISSING)
        slot_after = get_slot(ctx["slots"][0]["id"])
        assert slot_after["status"] == "OPEN"

    def test_type_of_another_provider_rejected(self, api):
        """PRD §3.4: "The appointment type must belong to the slot's provider and be `ACTIVE`; a type of another provider or a `RETIRED` type is rejected with `ERR_TYPE_MAPPING_MISSING`."

        Design: Corner/validations/retired_appointment_type_booking_rejected
        """
        ctx_a = setup_bookable_practice(slot_windows=[slot_time(48)])
        ctx_b = setup_bookable_practice(slot_windows=[slot_time(48)])
        patient = create_patient()
        resp = api_client.create_booking(
            ctx_a["slots"][0]["id"],
            {"patient_id": patient["id"], "appointment_type_id": ctx_b["type"]["id"]},
            make_patient_headers(patient["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TYPE_MAPPING_MISSING)


class TestNewPatientTypeGate:
    def test_new_patient_blocked_from_existing_only_type(self, api):
        """PRD §3.4: "If the type's `accepts_new_patients` is false and the patient has no `COMPLETED` booking at this practice, the booking is rejected with `ERR_NEW_PATIENT_TYPE_BLOCKED`."

        Design: Corner/validations/new_patient_blocked_from_existing_only_type
        """
        ctx = setup_bookable_practice(
            slot_windows=[slot_time(48), slot_time(49)],
            type_overrides={
                "code": "FU15",
                "display_name": "Follow up 15",
                "duration_minutes": 15,
                "booked_copay_cents": 5000,
                "accepts_new_patients": False,
            },
        )
        patient = create_patient()
        resp = api_client.create_booking(
            ctx["slots"][0]["id"],
            {"patient_id": patient["id"], "appointment_type_id": ctx["type"]["id"]},
            make_patient_headers(patient["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NEW_PATIENT_TYPE_BLOCKED)

    def test_existing_patient_books_existing_only_type_after_completion(self, api):
        """PRD §3.4: "If the type's `accepts_new_patients` is false and the patient has no `COMPLETED` booking at this practice, the booking is rejected with `ERR_NEW_PATIENT_TYPE_BLOCKED`."

        Design: Corner/validations/new_patient_blocked_from_existing_only_type
        """
        # Complete one booking first so the patient has a COMPLETED booking.
        ctx = setup_completed_booking()
        provider = ctx["provider"]
        patient = ctx["patient"]
        from test_helpers import create_appointment_type
        fu_type = create_appointment_type(
            provider["id"],
            code="FU15",
            display_name="Follow up 15",
            duration_minutes=15,
            booked_copay_cents=5000,
            accepts_new_patients=False,
        )
        set_clock("2026-09-03T12:00:00Z")
        slot = create_slot(provider["id"], "2026-09-04T10:00:00Z", "2026-09-04T10:30:00Z")
        resp = api_client.create_booking(
            slot["id"],
            {"patient_id": patient["id"], "appointment_type_id": fu_type["id"]},
            make_patient_headers(patient["id"]),
        )
        data = validate_success(resp, 201)
        assert data["is_new_patient"] is False
