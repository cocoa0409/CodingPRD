"""Appointment booking: slot conflict buffer, check-in window, lifecycle."""
from test_helpers import (
    ApiErrorId,
    assert_appointment,
    book_appointment,
    create_appointment_payload,
    get_device,
    make_customer_headers,
    make_customer_service_headers,
    make_technician_headers,
    set_clock,
    setup_appointment,
    setup_customer_device_and_network,
    validate_error,
    validate_success,
)


class TestSlotConflictBuffer:
    def test_appointment_slot_overlap_with_buffer(self, api):
        """PRD §3.3: "For another appointment sharing the same `technician_id`,
        the candidate slot's effective window begins 10 minutes before its
        `slot_start` and ends 10 minutes after its `slot_end`; a conflict exists
        whenever that effective window starts before the existing appointment's
        `slot_end` and ends after the existing appointment's `slot_start`."
        PRD §3.3: "Two slots that merely touch — the new `slot_start` exactly
        equal to the existing `slot_end` — do not by themselves conflict, but the
        10-minute buffer means genuinely back-to-back bookings for one technician
        are still rejected."
        PRD §3.3: "A detected conflict is rejected with `ERR_SLOT_CONFLICT`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/appointment_slot_overlap_with_buffer
        """
        set_clock()
        customer, device, location, technician = setup_customer_device_and_network()
        first = book_appointment(
            customer, device, location, technician,
            slot_start="2026-09-02T10:00:00Z", slot_end="2026-09-02T10:30:00Z",
        )
        assert first["appointment_status"] == "SCHEDULED"

        def attempt(slot_start, slot_end):
            fresh_device = get_device(device["id"])
            payload = create_appointment_payload(
                customer["id"], device["id"], location["id"], technician["id"],
                fresh_device["version"], slot_start=slot_start, slot_end=slot_end,
            )
            return api.create_appointment(payload, make_customer_service_headers())

        # Genuinely back-to-back (touching) slots fall inside the 10-minute
        # buffer and conflict.
        resp = attempt("2026-09-02T10:30:00Z", "2026-09-02T11:00:00Z")
        validate_error(resp, ApiErrorId.ERR_SLOT_CONFLICT.value, expected_status=409)

        # Overlapping slot conflicts.
        resp = attempt("2026-09-02T10:25:00Z", "2026-09-02T10:55:00Z")
        validate_error(resp, ApiErrorId.ERR_SLOT_CONFLICT.value, expected_status=409)

        # 10:40 start: effective window [10:30, 11:20) starts at the existing
        # slot_end, so it is outside the buffered conflict and is allowed.
        resp = attempt("2026-09-02T10:40:00Z", "2026-09-02T11:10:00Z")
        data = validate_success(resp, expected_status=201)
        assert data["appointment_status"] == "SCHEDULED"

    def test_appointment_slot_buffer_lower_edge_conflicts(self, api):
        """PRD §3.3: "For another appointment sharing the same `technician_id`,
        the candidate slot's effective window begins 10 minutes before its
        `slot_start` and ends 10 minutes after its `slot_end`; a conflict exists
        whenever that effective window starts before the existing appointment's
        `slot_end` and ends after the existing appointment's `slot_start`."

        Design: Difficulty/resource_temporal_overlap/appointment_slot_overlap_with_buffer
        """
        set_clock()
        customer, device, location, technician = setup_customer_device_and_network()
        book_appointment(
            customer, device, location, technician,
            slot_start="2026-09-02T10:00:00Z", slot_end="2026-09-02T10:30:00Z",
        )
        fresh_device = get_device(device["id"])
        # Ends exactly at the existing slot_start: effective window
        # [09:10, 10:10) ends after the existing slot_start, so it conflicts.
        payload = create_appointment_payload(
            customer["id"], device["id"], location["id"], technician["id"],
            fresh_device["version"],
            slot_start="2026-09-02T09:20:00Z", slot_end="2026-09-02T10:00:00Z",
        )
        resp = api.create_appointment(payload, make_customer_service_headers())
        validate_error(resp, ApiErrorId.ERR_SLOT_CONFLICT.value, expected_status=409)


class TestSlotTimeValidity:
    def test_appointment_create_with_past_slot_returns_invalid_slot_time(self, api):
        """PRD §3.3: "Booking succeeds only when a chain of checks passes: the
        slot must start in the future and no more than 30 days ahead, otherwise
        `ERR_INVALID_SLOT_TIME` (HTTP 422); ..."

        Design: Corner/validations/appointment_create_with_past_slot_returns_invalid_slot_time
        """
        set_clock()
        customer, device, location, technician = setup_customer_device_and_network()
        payload = create_appointment_payload(
            customer["id"], device["id"], location["id"], technician["id"],
            device["version"],
            slot_start="2026-08-01T10:00:00Z", slot_end="2026-08-01T10:30:00Z",
        )
        resp = api.create_appointment(payload, make_customer_service_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_SLOT_TIME.value, expected_status=422)

    def test_appointment_create_with_slot_beyond_30_days_returns_invalid_slot_time(self, api):
        """PRD §3.3: "Booking succeeds only when a chain of checks passes: the
        slot must start in the future and no more than 30 days ahead, otherwise
        `ERR_INVALID_SLOT_TIME` (HTTP 422); ..."

        Design: Corner/validations/appointment_create_with_slot_beyond_30_days_returns_invalid_slot_time
        """
        set_clock()
        customer, device, location, technician = setup_customer_device_and_network()
        payload = create_appointment_payload(
            customer["id"], device["id"], location["id"], technician["id"],
            device["version"],
            slot_start="2026-10-05T10:00:00Z", slot_end="2026-10-05T10:30:00Z",
        )
        resp = api.create_appointment(payload, make_customer_service_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_SLOT_TIME.value, expected_status=422)


class TestCheckInWindow:
    def test_appointment_slot_boundary_15_minute_checkin(self, api):
        """PRD §3.3: "Check-in is accepted no earlier than 15 minutes before
        `slot_start` and no later than `slot_end`, by the customer or the
        technician; outside that window, or from any other state, the transition
        is rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/appointment_slot_boundary_15_minute_checkin
        """
        set_clock()
        customer, device, location, technician, appointment = setup_appointment()

        # 16 minutes before slot_start: too early.
        set_clock("2026-09-02T09:44:00Z")
        resp = api.check_in_appointment(
            appointment["id"], make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

        # Exactly 15 minutes before slot_start: accepted.
        set_clock("2026-09-02T09:45:00Z")
        resp = api.check_in_appointment(
            appointment["id"], make_customer_headers(customer["id"]))
        data = validate_success(resp, expected_status=200)
        assert data["appointment_status"] == "CHECKED_IN"
        assert_appointment(data)

    def test_check_in_at_slot_end_boundary_accepted(self, api):
        """PRD §3.3: "Check-in is accepted no earlier than 15 minutes before
        `slot_start` and no later than `slot_end`, by the customer or the
        technician; outside that window, or from any other state, the transition
        is rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/appointment_slot_boundary_15_minute_checkin
        """
        set_clock()
        customer, device, location, technician, appointment = setup_appointment()

        # Exactly at slot_end: still within the window (no later than slot_end).
        set_clock("2026-09-02T10:30:00Z")
        resp = api.check_in_appointment(
            appointment["id"], make_customer_headers(customer["id"]))
        data = validate_success(resp, expected_status=200)
        assert data["appointment_status"] == "CHECKED_IN"


class TestAppointmentLifecycle:
    def test_appointment_parallel_status_dimensions(self, api):
        """PRD §3.3: "Cancellation from `SCHEDULED` is available to the customer,
        the technician, or `CustomerService`; once `CHECKED_IN`, only
        `CustomerService` may cancel. `CANCELLED` and `NO_SHOW` are terminal
        alongside `COMPLETED`."
        PRD §3.3: "If the logical clock passes `slot_end` with no check-in, the
        system marks the appointment `NO_SHOW`."

        Design: Difficulty/non_linear_state_machine/appointment_parallel_status_dimensions
        """
        set_clock()
        customer, device, location, technician = setup_customer_device_and_network()
        appt_cancel = book_appointment(
            customer, device, location, technician,
            slot_start="2026-09-02T10:00:00Z", slot_end="2026-09-02T10:30:00Z",
        )
        appt_noshow = book_appointment(
            customer, device, location, technician,
            slot_start="2026-09-02T11:00:00Z", slot_end="2026-09-02T11:30:00Z",
        )

        resp = api.cancel_appointment(
            appt_cancel["id"], make_customer_service_headers())
        data = validate_success(resp, expected_status=200)
        assert data["appointment_status"] == "CANCELLED"

        set_clock("2026-09-02T12:00:00Z")
        resp = api.get_appointment(
            appt_noshow["id"], make_customer_headers(customer["id"]))
        data = validate_success(resp, expected_status=200)
        assert data["appointment_status"] == "NO_SHOW"

    def test_appointment_terminal_states_do_not_reopen(self, api):
        """PRD §3.3: "Cancellation from `SCHEDULED` is available to the customer,
        the technician, or `CustomerService`; once `CHECKED_IN`, only
        `CustomerService` may cancel. `CANCELLED` and `NO_SHOW` are terminal
        alongside `COMPLETED`."
        PRD §2.6: "fourth state validity for the requested transition
        (`ERR_INVALID_STATE`)"

        Design: Difficulty/non_linear_state_machine/appointment_parallel_status_dimensions
        """
        set_clock()
        customer, device, location, technician = setup_customer_device_and_network()
        appt_cancel = book_appointment(
            customer, device, location, technician,
            slot_start="2026-09-02T10:00:00Z", slot_end="2026-09-02T10:30:00Z",
        )
        appt_noshow = book_appointment(
            customer, device, location, technician,
            slot_start="2026-09-02T11:00:00Z", slot_end="2026-09-02T11:30:00Z",
        )
        validate_success(api.cancel_appointment(
            appt_cancel["id"], make_customer_service_headers()), 200)

        # CANCELLED is terminal: a second cancel is state-invalid.
        resp = api.cancel_appointment(
            appt_cancel["id"], make_customer_service_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value,
                       expected_status=409)

        # NO_SHOW is terminal: after the clock passes slot_end without check-in,
        # cancelling the no-show appointment is state-invalid.
        set_clock("2026-09-02T12:00:00Z")
        resp = api.get_appointment(
            appt_noshow["id"], make_customer_headers(customer["id"]))
        assert validate_success(resp, 200)["appointment_status"] == "NO_SHOW"
        resp = api.cancel_appointment(
            appt_noshow["id"], make_customer_service_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value,
                       expected_status=409)

    def test_appointment_cancel_from_completed_returns_invalid_state(self, api):
        """PRD §3.3: "Cancellation from `SCHEDULED` is available to the customer,
        the technician, or `CustomerService`; once `CHECKED_IN`, only
        `CustomerService` may cancel. `CANCELLED` and `NO_SHOW` are terminal
        alongside `COMPLETED`."
        PRD §2.6: "fourth state validity for the requested transition
        (`ERR_INVALID_STATE`)"

        Design: Corner/state_machines/appointment_cancel_from_completed_returns_invalid_state
        """
        set_clock()
        customer, device, location, technician, appointment = setup_appointment()
        set_clock("2026-09-02T10:00:00Z")
        validate_success(api.check_in_appointment(
            appointment["id"], make_customer_headers(customer["id"])), 200)
        validate_success(api.start_diagnosis(
            appointment["id"], make_technician_headers(technician["id"])), 200)
        validate_success(api.complete_diagnosis(
            appointment["id"], make_technician_headers(technician["id"])), 200)

        resp = api.cancel_appointment(
            appointment["id"], make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

    def test_appointment_no_show_auto_transition_on_clock_advance(self, api):
        """PRD §3.3: "If the logical clock passes `slot_end` with no check-in,
        the system marks the appointment `NO_SHOW`."

        Design: Corner/state_machines/appointment_no_show_auto_transition_on_clock_advance
        """
        set_clock()
        customer, device, location, technician, appointment = setup_appointment()
        set_clock("2026-09-02T11:00:00Z")
        resp = api.get_appointment(
            appointment["id"], make_customer_headers(customer["id"]))
        data = validate_success(resp, expected_status=200)
        assert data["appointment_status"] == "NO_SHOW"
