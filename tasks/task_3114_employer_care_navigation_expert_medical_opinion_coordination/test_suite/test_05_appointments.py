"""Appointments: consent gating, half-open overlap, daily capacity, reschedule
checks, temporal gating, and the default logical clock."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_appointment_payload, create_member_payload,
    set_clock, setup_employer, setup_employer_with_member, setup_provider,
    grant_consent, setup_booked_appointment, fill_provider_day,
)
from test_helpers.test_users import (
    make_member_headers,
    make_care_advocate_headers,
    make_nurse_navigator_headers,
)


class TestAppointmentConsentGate:
    def test_appointment_booking_requires_active_booking_consent(
            self, api, platform_admin_headers):
        """PRD §2.8: "Four operations are consent-gated: booking or
        rescheduling an appointment requires an `ACTIVE` `APPOINTMENT_BOOKING`
        grant; creating or retrying a record request requires an `ACTIVE`
        `RECORD_RETRIEVAL` grant; opening or compiling an expert opinion case
        requires an `ACTIVE` `EMO_REVIEW` grant; and opening a billing case
        requires an `ACTIVE` `BILLING_ADVOCACY` grant. Each gate fails with
        `ERR_CONSENT_REQUIRED` (409)."

        Design: Difficulty/cross_entity_state_dependency/appointment_booking_requires_active_booking_consent
        """
        set_clock()
        _, member = setup_employer_with_member()
        consent = grant_consent(member, "APPOINTMENT_BOOKING")
        validate_success(api.revoke_consent(
            consent["id"], make_member_headers(member["id"])))
        provider = setup_provider(name="Westside ENT", specialty="ENT")

        resp = api.create_appointment(
            member["id"],
            create_appointment_payload(
                provider_id=provider["id"],
                slot_start="2026-09-10T14:00:00Z",
                slot_end="2026-09-10T14:30:00Z"),
            make_nurse_navigator_headers("nn-1"))
        validate_error(resp, ApiErrorId.ERR_CONSENT_REQUIRED,
                       expected_status=409)

        rows = validate_success(api.list_member_appointments(
            member["id"], platform_admin_headers))
        assert len(rows) == 0

    def test_booking_without_any_booking_consent_rejected(
            self, api, platform_admin_headers):
        """PRD §2.8: "Four operations are consent-gated: booking or
        rescheduling an appointment requires an `ACTIVE` `APPOINTMENT_BOOKING`
        grant".

        Design: Difficulty/cross_entity_state_dependency/appointment_booking_requires_active_booking_consent
        """
        set_clock()
        _, member = setup_employer_with_member()
        provider = setup_provider(name="Westside ENT", specialty="ENT")

        resp = api.create_appointment(
            member["id"],
            create_appointment_payload(
                provider_id=provider["id"],
                slot_start="2026-09-10T14:00:00Z",
                slot_end="2026-09-10T14:30:00Z"),
            make_nurse_navigator_headers("nn-1"))
        validate_error(resp, ApiErrorId.ERR_CONSENT_REQUIRED,
                       expected_status=409)
        rows = validate_success(api.list_member_appointments(
            member["id"], platform_admin_headers))
        assert len(rows) == 0

    def test_booking_without_consent_safety_beats_slot_conflict_constraint(
            self, api, platform_admin_headers):
        """PRD §2.6: "Only after all of these do business rules run — consent
        gates, uniqueness constraints, capacity limits, fiscal guards, temporal
        windows — each at the priority stated in §3 where the rule lives."
        PRD §2.8: "Four operations are consent-gated: booking or rescheduling
        an appointment requires an `ACTIVE` `APPOINTMENT_BOOKING` grant".

        Design: Difficulty/priority_pair_validation_conflict/booking_without_consent_safety_beats_slot_conflict_constraint
        """
        set_clock()
        emp = setup_employer()
        ma = validate_success(api.create_member(
            emp["id"], create_member_payload(
                full_name="Alice Foo", external_member_ref="K-001"),
            platform_admin_headers), expected_status=201)
        mb = validate_success(api.create_member(
            emp["id"], create_member_payload(
                full_name="Bob Bar", external_member_ref="K-002"),
            platform_admin_headers), expected_status=201)
        grant_consent(ma, "APPOINTMENT_BOOKING")
        provider = setup_provider(name="Downtown PT",
                                  specialty="PHYSICAL_THERAPY")
        setup_booked_appointment(ma, provider,
                                 "2026-09-05T10:00:00Z",
                                 "2026-09-05T10:30:00Z")

        resp = api.create_appointment(
            mb["id"],
            create_appointment_payload(
                provider_id=provider["id"],
                slot_start="2026-09-05T10:15:00Z",
                slot_end="2026-09-05T10:45:00Z"),
            make_care_advocate_headers("adv-1"))
        err = validate_error(resp, ApiErrorId.ERR_CONSENT_REQUIRED,
                             expected_status=409)
        assert err["error_id"] != "ERR_SLOT_CONFLICT"

    def test_consent_gate_runs_before_business_constraints_even_without_conflict(
            self, api, platform_admin_headers):
        """PRD §2.6: "Only after all of these do business rules run — consent
        gates, uniqueness constraints, capacity limits, fiscal guards, temporal
        windows — each at the priority stated in §3 where the rule lives."
        PRD §2.8: "Each gate fails with `ERR_CONSENT_REQUIRED` (409)."

        Design: Difficulty/priority_pair_validation_conflict/booking_without_consent_safety_beats_slot_conflict_constraint
        """
        set_clock()
        _, member = setup_employer_with_member()
        provider = setup_provider(name="Downtown PT",
                                  specialty="PHYSICAL_THERAPY")

        # No consent, and no pre-existing booking: the gate must still fire
        # before any slot-level check would even be evaluated.
        resp = api.create_appointment(
            member["id"],
            create_appointment_payload(
                provider_id=provider["id"],
                slot_start="2026-09-05T10:15:00Z",
                slot_end="2026-09-05T10:45:00Z"),
            make_care_advocate_headers("adv-1"))
        validate_error(resp, ApiErrorId.ERR_CONSENT_REQUIRED,
                       expected_status=409)


class TestAppointmentOverlap:
    def test_adjacency_allowed_but_overlap_rejected(
            self, api, platform_admin_headers):
        """PRD §3.4: "Slots are half-open intervals on a single provider: a new
        `[slot_start, slot_end)` conflicts with an existing `BOOKED` slot when
        the new start is before the existing end and the existing start is
        before the new end — pure adjacency, where one slot's end equals the
        other's start, is allowed. Overlaps are rejected with
        `ERR_SLOT_CONFLICT` (409)."

        Design: Difficulty/resource_temporal_overlap/appointment_half_open_adjacency_allowed_but_overlap_rejected
        """
        set_clock()
        _, member = setup_employer_with_member()
        grant_consent(member, "APPOINTMENT_BOOKING")
        provider = setup_provider(name="City Dental", specialty="DENTAL")
        setup_booked_appointment(member, provider,
                                 "2026-09-05T10:00:00Z",
                                 "2026-09-05T10:30:00Z")

        adjacent = api.create_appointment(
            member["id"],
            create_appointment_payload(
                provider_id=provider["id"],
                slot_start="2026-09-05T10:30:00Z",
                slot_end="2026-09-05T11:00:00Z"),
            make_care_advocate_headers("adv-1"))
        validate_success(adjacent, expected_status=201)

        overlapping = api.create_appointment(
            member["id"],
            create_appointment_payload(
                provider_id=provider["id"],
                slot_start="2026-09-05T10:29:00Z",
                slot_end="2026-09-05T10:59:00Z"),
            make_care_advocate_headers("adv-1"))
        validate_error(overlapping, ApiErrorId.ERR_SLOT_CONFLICT,
                       expected_status=409)

    def test_strict_interior_overlap_rejected(
            self, api, platform_admin_headers):
        """PRD §3.4: "a new `[slot_start, slot_end)` conflicts with an existing
        `BOOKED` slot when the new start is before the existing end and the
        existing start is before the new end — pure adjacency, where one slot's
        end equals the other's start, is allowed. Overlaps are rejected with
        `ERR_SLOT_CONFLICT` (409)."

        Design: Difficulty/resource_temporal_overlap/appointment_half_open_adjacency_allowed_but_overlap_rejected
        """
        set_clock()
        _, member = setup_employer_with_member()
        grant_consent(member, "APPOINTMENT_BOOKING")
        provider = setup_provider(name="City Dental", specialty="DENTAL")
        setup_booked_appointment(member, provider,
                                 "2026-09-05T10:00:00Z",
                                 "2026-09-05T10:30:00Z")

        resp = api.create_appointment(
            member["id"],
            create_appointment_payload(
                provider_id=provider["id"],
                slot_start="2026-09-05T10:15:00Z",
                slot_end="2026-09-05T10:45:00Z"),
            make_care_advocate_headers("adv-1"))
        validate_error(resp, ApiErrorId.ERR_SLOT_CONFLICT,
                       expected_status=409)


class TestProviderDayCapacity:
    def test_book_then_cancel_restores_provider_day_occupancy(
            self, api, platform_admin_headers):
        """PRD §3.4: "Independently, a provider takes at most eight `BOOKED`
        appointments per UTC calendar date of the slot's start: the eighth
        booking succeeds and the ninth is rejected with
        `ERR_PROVIDER_DAY_CAPACITY` (422)."
        PRD §3.4: "Cancellation — by a navigator, advocate, or the member —
        moves the appointment to `CANCELLED`, computes `late_cancel` as true
        exactly when the logical clock has reached the `slot_start` at
        cancellation time, and decrements the provider-day occupancy by one, so
        that a book followed by a cancel leaves occupancy unchanged."

        Design: Difficulty/compensating_invariant/book_then_cancel_restores_provider_day_occupancy
        """
        set_clock()
        _, member = setup_employer_with_member()
        grant_consent(member, "APPOINTMENT_BOOKING")
        provider = setup_provider(name="Harbor Clinic")
        appointments = fill_provider_day(member, provider, "2026-09-08",
                                         count=8)
        assert len(appointments) == 8

        ninth = api.create_appointment(
            member["id"],
            create_appointment_payload(
                provider_id=provider["id"],
                slot_start="2026-09-08T16:00:00Z",
                slot_end="2026-09-08T16:30:00Z"),
            make_care_advocate_headers("adv-1"))
        validate_error(ninth, ApiErrorId.ERR_PROVIDER_DAY_CAPACITY,
                       expected_status=422)

        validate_success(api.cancel_appointment(
            appointments[0]["id"], make_care_advocate_headers("adv-1")))

        freed = api.create_appointment(
            member["id"],
            create_appointment_payload(
                provider_id=provider["id"],
                slot_start="2026-09-08T16:00:00Z",
                slot_end="2026-09-08T16:30:00Z"),
            make_care_advocate_headers("adv-1"))
        validate_success(freed, expected_status=201)

        rows = validate_success(api.list_provider_appointments(
            provider["id"], platform_admin_headers,
            params={"status": "BOOKED", "limit": 100}))
        assert len(rows) == 8

    def test_ninth_booking_fails_and_replacement_after_cancel_succeeds(
            self, api, platform_admin_headers):
        """PRD §3.4: "Independently, a provider takes at most eight `BOOKED`
        appointments per UTC calendar date of the slot's start: the eighth
        booking succeeds and the ninth is rejected with
        `ERR_PROVIDER_DAY_CAPACITY` (422)."

        Design: Difficulty/compensating_invariant/book_then_cancel_restores_provider_day_occupancy
        """
        set_clock()
        _, member = setup_employer_with_member()
        grant_consent(member, "APPOINTMENT_BOOKING")
        provider = setup_provider(name="Harbor Clinic")
        appointments = fill_provider_day(member, provider, "2026-09-08",
                                         count=8)
        ninth = api.create_appointment(
            member["id"],
            create_appointment_payload(
                provider_id=provider["id"],
                slot_start="2026-09-08T16:00:00Z",
                slot_end="2026-09-08T16:30:00Z"),
            make_care_advocate_headers("adv-1"))
        validate_error(ninth, ApiErrorId.ERR_PROVIDER_DAY_CAPACITY,
                       expected_status=422)

        cancelled = validate_success(api.cancel_appointment(
            appointments[0]["id"], make_care_advocate_headers("adv-1")))
        assert cancelled["status"] == "CANCELLED"

        replacement = api.create_appointment(
            member["id"],
            create_appointment_payload(
                provider_id=provider["id"],
                slot_start="2026-09-08T16:00:00Z",
                slot_end="2026-09-08T16:30:00Z"),
            make_care_advocate_headers("adv-1"))
        validate_success(replacement, expected_status=201)


class TestAppointmentReschedule:
    def test_appointment_reschedule_rechecks_overlap_and_keeps_booked(
            self, api, platform_admin_headers):
        """PRD §3.4: "A `BOOKED` appointment may be rescheduled by a navigator
        or advocate to a new `slot_start` and `slot_end`; both the overlap and
        the daily-capacity checks run again against the new slot, and a
        successful reschedule keeps the appointment `BOOKED` while incrementing
        its `version`."

        Design: Corner/endpoints/appointment_reschedule_rechecks_overlap_and_keeps_booked
        """
        set_clock()
        _, member = setup_employer_with_member()
        grant_consent(member, "APPOINTMENT_BOOKING")
        provider = setup_provider(name="Sched Clinic")
        setup_booked_appointment(member, provider,
                                 "2026-09-06T09:00:00Z",
                                 "2026-09-06T09:30:00Z")
        a2 = setup_booked_appointment(member, provider,
                                      "2026-09-06T10:00:00Z",
                                      "2026-09-06T10:30:00Z")

        conflict = api.reschedule_appointment(
            a2["id"],
            {"slot_start": "2026-09-06T09:15:00Z",
             "slot_end": "2026-09-06T09:45:00Z"},
            make_care_advocate_headers("adv-1"))
        validate_error(conflict, ApiErrorId.ERR_SLOT_CONFLICT,
                       expected_status=409)

        ok = api.reschedule_appointment(
            a2["id"],
            {"slot_start": "2026-09-06T11:00:00Z",
             "slot_end": "2026-09-06T11:30:00Z"},
            make_care_advocate_headers("adv-1"))
        data = validate_success(ok)
        assert data["status"] == "BOOKED"
        assert data["slot_start"] == "2026-09-06T11:00:00Z"
        assert data["version"] == a2["version"] + 1


class TestAppointmentTemporalGating:
    def test_appointment_complete_before_slot_end_rejected(
            self, api, platform_admin_headers):
        """PRD §3.4: "Once the logical clock has reached the slot's end, a
        navigator or advocate completes the appointment (`COMPLETED`);
        completing before `slot_end` is rejected with
        `ERR_APPOINTMENT_NOT_DUE` (409). Marking a no-show is stricter: it
        requires the logical clock to be strictly past `slot_end`, moving the
        appointment to `NO_SHOW`, with the same `ERR_APPOINTMENT_NOT_DUE`
        rejection at or before the boundary."

        Design: Corner/validations/appointment_complete_before_slot_end_rejected
        """
        set_clock()
        _, member = setup_employer_with_member()
        grant_consent(member, "APPOINTMENT_BOOKING")
        provider = setup_provider(name="Gate PT",
                                  specialty="PHYSICAL_THERAPY")
        appt = setup_booked_appointment(member, provider,
                                        "2026-09-05T10:00:00Z",
                                        "2026-09-05T10:30:00Z")

        set_clock("2026-09-05T10:29:00Z")
        early = api.complete_appointment(
            appt["id"], make_nurse_navigator_headers("nn-1"))
        validate_error(early, ApiErrorId.ERR_APPOINTMENT_NOT_DUE,
                       expected_status=409)

        set_clock("2026-09-05T10:30:00Z")
        noshow_at_end = api.mark_no_show_appointment(
            appt["id"], make_nurse_navigator_headers("nn-1"))
        validate_error(noshow_at_end, ApiErrorId.ERR_APPOINTMENT_NOT_DUE,
                       expected_status=409)

        complete_at_end = api.complete_appointment(
            appt["id"], make_nurse_navigator_headers("nn-1"))
        data = validate_success(complete_at_end)
        assert data["status"] == "COMPLETED"

    def test_clock_default_is_fixed_2026_09_01(self, api,
                                               platform_admin_headers):
        """PRD §2.4: "Before any client sets it, the logical clock reads
        2026-09-01T00:00:00Z."

        Design: Corner/cross_cutting_layers/clock_default_is_fixed_2026_09_01
        """
        # Deliberately no set_clock call: the default logical clock applies.
        _, member = setup_employer_with_member()
        grant_consent(member, "APPOINTMENT_BOOKING")
        provider = setup_provider(name="Clock Clinic")
        appt = setup_booked_appointment(member, provider,
                                        "2026-09-02T09:00:00Z",
                                        "2026-09-02T09:30:00Z")

        resp = api.complete_appointment(
            appt["id"], make_nurse_navigator_headers("nn-1"))
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_NOT_DUE,
                       expected_status=409)
