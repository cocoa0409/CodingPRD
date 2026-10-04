"""Tests for attribution windowing, the visit lifecycle (complete side
effects), and review moderation (PRD §3.4, §3.5, §3.10).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    book_slot,
    create_patient,
    get_patient,
    get_slot,
    list_charges_for_booking,
    make_ops_admin_headers,
    make_patient_headers,
    make_practice_staff_headers,
    make_provider_headers,
    set_clock,
    setup_bookable_practice,
    setup_completed_booking,
    slot_time,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAttributionWindowExactly90Days:
    def test_contact_exactly_90_days_before_is_organic_no_charge(self, api):
        """PRD §3.4: "A contact exactly 90 days before `created_at` is inside the window (organic); one second earlier is outside (attributed)."

        Design: Difficulty/resource_temporal_overlap/attribution_window_exactly_90_days
        """
        ctx = setup_bookable_practice(slot_windows=[slot_time(48)])
        patient = create_patient()
        # ContactEvent at exactly 90 days before the default clock.
        api_client.create_contact_event(
            {
                "patient_id": patient["id"],
                "provider_id": ctx["provider"]["id"],
                "contacted_at": "2026-06-03T00:00:00Z",
                "channel": "PHONE",
            },
            make_practice_staff_headers(ctx["practice"]["id"]),
        )
        resp = api_client.create_booking(
            ctx["slots"][0]["id"],
            {"patient_id": patient["id"], "appointment_type_id": ctx["type"]["id"]},
            make_patient_headers(patient["id"]),
        )
        data = validate_success(resp, 201)
        assert data["attribution_status"] == "ORGANIC"
        charges = list_charges_for_booking(data["id"])
        assert len(charges) == 0, "organic bookings are never billed"

    def test_contact_one_second_before_window_is_attributed_with_charge(self, api):
        """PRD §3.4: "A contact exactly 90 days before `created_at` is inside the window (organic); one second earlier is outside (attributed)."

        Design: Difficulty/resource_temporal_overlap/attribution_window_exactly_90_days
        """
        ctx = setup_bookable_practice(slot_windows=[slot_time(48)])
        patient = create_patient()
        api_client.create_contact_event(
            {
                "patient_id": patient["id"],
                "provider_id": ctx["provider"]["id"],
                "contacted_at": "2026-06-02T23:59:59Z",
                "channel": "PHONE",
            },
            make_practice_staff_headers(ctx["practice"]["id"]),
        )
        resp = api_client.create_booking(
            ctx["slots"][0]["id"],
            {"patient_id": patient["id"], "appointment_type_id": ctx["type"]["id"]},
            make_patient_headers(patient["id"]),
        )
        data = validate_success(resp, 201)
        assert data["attribution_status"] == "ATTRIBUTED"
        charges = list_charges_for_booking(data["id"])
        assert len(charges) == 1
        assert charges[0]["marketplace_fee_cents"] == 1500


class TestCompleteSideEffects:
    def test_complete_creates_one_verified_visit_record_and_recovers(self, api):
        """PRD §3.5: "Completion creates a `VisitRecord` for the booking whose `verification` is always `VERIFIED` (records are created only by this transition), whose `booking_id`, `provider_id`, and `patient_id` are copied from the booking, and whose `completed_at` is the logical-clock timestamp of completion. There is at most one visit record per booking."
        PRD §3.5: "Completion also rewards reliability: the patient's `recovery_count` increases by 1, the reliability scores are recomputed (§3.8), and the occupied slot moves from `BOOKED` to `CLOSED` with `close_reason` `PROVIDER_CLOSED`."

        Design: Corner/state_machines/complete_side_effects_visit_record_and_recovery
        """
        # One NO_SHOW strike first so the +10 recovery is observable.
        ctx = setup_bookable_practice(slot_windows=[slot_time(48), slot_time(49)])
        patient = create_patient()
        b1 = book_slot(ctx["slots"][0]["id"], patient["id"], ctx["type"]["id"])
        b2 = book_slot(ctx["slots"][1]["id"], patient["id"], ctx["type"]["id"])
        set_clock("2026-09-03T10:05:00Z")
        staff = make_practice_staff_headers(ctx["practice"]["id"])
        api_client.mark_no_show(b1["id"], staff)
        api_client.check_in_booking(b2["id"], staff)
        resp = api_client.complete_booking(b2["id"], staff)
        data = validate_success(resp)
        assert data["status"] == "COMPLETED"
        patient_after = get_patient(patient["id"])
        assert patient_after["reliability_score"] == 85
        assert patient_after["recovery_count"] == 1

    def test_complete_closes_slot_and_lists_one_visit_record(self, api):
        """PRD §3.5: "Completion creates a `VisitRecord` for the booking whose `verification` is always `VERIFIED` (records are created only by this transition), whose `booking_id`, `provider_id`, and `patient_id` are copied from the booking, and whose `completed_at` is the logical-clock timestamp of completion."
        PRD §3.5: "There is at most one visit record per booking."
        PRD §3.5: "Completion also rewards reliability: the patient's `recovery_count` increases by 1, the reliability scores are recomputed (§3.8), and the occupied slot moves from `BOOKED` to `CLOSED` with `close_reason` `PROVIDER_CLOSED`."

        Design: Corner/state_machines/complete_side_effects_visit_record_and_recovery
        """
        ctx = setup_bookable_practice(slot_windows=[slot_time(48)])
        patient = create_patient()
        booking = book_slot(ctx["slots"][0]["id"], patient["id"], ctx["type"]["id"])
        set_clock("2026-09-03T10:05:00Z")
        staff = make_practice_staff_headers(ctx["practice"]["id"])
        api_client.check_in_booking(booking["id"], staff)
        api_client.complete_booking(booking["id"], staff)
        resp = api_client.list_booking_visit_records(booking["id"], staff)
        records, meta = validate_paginated(resp)
        assert len(records) == 1
        assert records[0]["verification"] == "VERIFIED"
        slot_after = get_slot(ctx["slots"][0]["id"])
        assert slot_after["status"] == "CLOSED"
        assert slot_after["close_reason"] == "PROVIDER_CLOSED"


class TestReviewRequiresVerifiedVisitRecord:
    def test_review_on_confirmed_booking_rejected(self, api):
        """PRD §3.10: "The booking must have a `VERIFIED` `VisitRecord` — which, since visit records are created only by the completion transition, means the visit actually happened; a booking without one is rejected with `ERR_VISIT_NOT_VERIFIED`."

        Design: Difficulty/cross_entity_state_dependency/review_requires_verified_visit_record
        """
        ctx = setup_bookable_practice(slot_windows=[slot_time(48)])
        patient = create_patient()
        booking = book_slot(ctx["slots"][0]["id"], patient["id"], ctx["type"]["id"])
        resp = api_client.create_review(
            {"booking_id": booking["id"], "rating": 4},
            make_patient_headers(patient["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VISIT_NOT_VERIFIED)

    def test_review_succeeds_after_completion(self, api):
        """PRD §3.10: "A review is born `PUBLISHED`."
        PRD §3.5: "Completion creates a `VisitRecord` for the booking whose `verification` is always `VERIFIED` (records are created only by this transition), whose `booking_id`, `provider_id`, and `patient_id` are copied from the booking, and whose `completed_at` is the logical-clock timestamp of completion."

        Design: Difficulty/cross_entity_state_dependency/review_requires_verified_visit_record
        """
        ctx = setup_completed_booking()
        patient = ctx["patient"]
        booking = ctx["booking"]
        resp = api_client.create_review(
            {"booking_id": booking["id"], "rating": 4},
            make_patient_headers(patient["id"]),
        )
        data = validate_success(resp, 201)
        assert data["status"] == "PUBLISHED"
        # Exactly one VERIFIED visit record exists for the booking.
        records, _ = validate_paginated(
            api_client.list_booking_visit_records(
                booking["id"], make_practice_staff_headers(ctx["practice"]["id"])
            )
        )
        assert len(records) == 1
        assert records[0]["verification"] == "VERIFIED"


class TestReviewFlagRestoreRemoveCycle:
    def _setup_published_review(self):
        ctx = setup_completed_booking()
        patient = ctx["patient"]
        booking = ctx["booking"]
        resp = api_client.create_review(
            {"booking_id": booking["id"], "rating": 5, "text": "great"},
            make_patient_headers(patient["id"]),
        )
        review = validate_success(resp, 201)
        return ctx, review

    def test_flag_restore_closes_loop_back_to_published(self, api):
        """PRD §3.10: "`RESTORE` on a `FLAGGED` review returns it to `PUBLISHED` and clears `flag_reason` to null."

        Design: Difficulty/non_linear_state_machine/review_flag_restore_remove_cycle
        """
        ctx, review = self._setup_published_review()
        api_client.flag_review(
            review["id"], {"reason": "spam"}, make_practice_staff_headers(ctx["practice"]["id"])
        )
        resp = api_client.moderate_review(
            review["id"], {"action": "RESTORE"}, TEST_USERS["ops_admin_headers"]
        )
        data = validate_success(resp)
        assert data["status"] == "PUBLISHED"
        assert data["flag_reason"] is None

    def test_remove_is_terminal_and_later_moderate_fails(self, api):
        """PRD §3.10: "`REMOVE` on a review in either `PUBLISHED` or `FLAGGED` moves it to terminal `REMOVED`. Any other combination is `ERR_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/review_flag_restore_remove_cycle
        """
        ctx, review = self._setup_published_review()
        api_client.flag_review(
            review["id"], {"reason": "spam again"}, make_provider_headers(ctx["provider"]["id"])
        )
        resp = api_client.moderate_review(
            review["id"], {"action": "REMOVE"}, TEST_USERS["ops_admin_headers"]
        )
        data = validate_success(resp)
        assert data["status"] == "REMOVED"
        resp2 = api_client.moderate_review(
            review["id"], {"action": "RESTORE"}, TEST_USERS["ops_admin_headers"]
        )
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)


class TestReviewRatingOutOfRange:
    def test_rating_6_rejected(self, api):
        """PRD §3.10: "Creating a review supplies the `booking_id`, an integer `rating` from 1 to 5 inclusive, and optional `text`; the review's `patient_id` and `provider_id` are copied from the booking."
        PRD §2.8: "Request schema.** Required fields present, types correct, enum members valid, `rating` within its 1-to-5 range, `end_at` strictly after `start_at`, and attestation `effective_to` strictly after `effective_from` (`ERR_INVALID_REQUEST`)."

        Design: Corner/validations/review_rating_out_of_range_rejected
        """
        ctx = setup_completed_booking()
        patient = ctx["patient"]
        booking = ctx["booking"]
        resp = api_client.create_review(
            {"booking_id": booking["id"], "rating": 6},
            make_patient_headers(patient["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_rating_0_rejected(self, api):
        """PRD §3.10: "Creating a review supplies the `booking_id`, an integer `rating` from 1 to 5 inclusive, and optional `text`; the review's `patient_id` and `provider_id` are copied from the booking."

        Design: Corner/validations/review_rating_out_of_range_rejected
        """
        ctx = setup_completed_booking()
        patient = ctx["patient"]
        booking = ctx["booking"]
        resp = api_client.create_review(
            {"booking_id": booking["id"], "rating": 0},
            make_patient_headers(patient["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
