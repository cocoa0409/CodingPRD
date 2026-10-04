"""Tests for patient reliability: provisional vs effective score, strike aging
at the epoch run, and the reliability gate boundary (PRD §3.8 and §3.4).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    book_slot,
    create_patient,
    get_booking,
    get_patient,
    get_slot,
    make_patient_headers,
    make_practice_staff_headers,
    set_clock,
    setup_bookable_practice,
    slot_time,
    validate_error,
    validate_success,
)


def _book_and_no_show(ctx, slot, patient):
    """Book a slot and mark the booking NO_SHOW (clock advanced past start)."""
    booking = book_slot(slot["id"], patient["id"], ctx["type"]["id"])
    start = slot["start_at"]
    # Advance clock to just past the start.
    hh, mm = start[11:13], start[14:16]
    day = start[8:10]
    set_clock(f"2026-09-{day}T{hh}:{int(mm)+5:02d}:00Z")
    api_client.mark_no_show(booking["id"], make_practice_staff_headers(ctx["practice"]["id"]))
    return booking


class TestReliabilityProvisionalVsEffectiveWithRecovery:
    def test_identical_strike_data_provisional_75_effective_85(self, api):
        """PRD §3.8: "Identical strike data therefore yields a higher effective
        score whenever the patient has completed visits: one active no-show
        strike plus one completed-visit recovery gives a provisional score of
        75 and an effective score of 85."

        Design: Difficulty/dual_variant_calc/reliability_provisional_vs_effective_with_recovery
        """
        ctx = setup_bookable_practice(
            slot_windows=[slot_time(48), slot_time(49)]
        )
        patient = create_patient()
        b1 = book_slot(ctx["slots"][0]["id"], patient["id"], ctx["type"]["id"])
        b2 = book_slot(ctx["slots"][1]["id"], patient["id"], ctx["type"]["id"])
        set_clock("2026-09-03T10:05:00Z")
        api_client.mark_no_show(b1["id"], make_practice_staff_headers(ctx["practice"]["id"]))
        api_client.check_in_booking(b2["id"], make_practice_staff_headers(ctx["practice"]["id"]))
        api_client.complete_booking(b2["id"], make_practice_staff_headers(ctx["practice"]["id"]))
        patient_after = get_patient(patient["id"])
        assert patient_after["provisional_score"] == 75
        assert patient_after["reliability_score"] == 85

    def test_strikes_array_and_recovery_count_observable(self, api):
        """PRD §3.8: "A patient's `strikes` is an array of entries each carrying an `epoch`, a `magnitude`, and a `kind` of `NO_SHOW` or `LATE_CANCEL`."
        PRD §3.5: "Completion also rewards reliability: the patient's `recovery_count` increases by 1, the reliability scores are recomputed (§3.8), and the occupied slot moves from `BOOKED` to `CLOSED` with `close_reason` `PROVIDER_CLOSED`."

        Design: Difficulty/dual_variant_calc/reliability_provisional_vs_effective_with_recovery
        """
        ctx = setup_bookable_practice(slot_windows=[slot_time(48), slot_time(49)])
        patient = create_patient()
        b1 = book_slot(ctx["slots"][0]["id"], patient["id"], ctx["type"]["id"])
        b2 = book_slot(ctx["slots"][1]["id"], patient["id"], ctx["type"]["id"])
        set_clock("2026-09-03T10:05:00Z")
        api_client.mark_no_show(b1["id"], make_practice_staff_headers(ctx["practice"]["id"]))
        api_client.check_in_booking(b2["id"], make_practice_staff_headers(ctx["practice"]["id"]))
        api_client.complete_booking(b2["id"], make_practice_staff_headers(ctx["practice"]["id"]))
        patient_after = get_patient(patient["id"])
        assert len(patient_after["strikes"]) == 1
        strike = patient_after["strikes"][0]
        assert strike["kind"] == "NO_SHOW"
        assert strike["magnitude"] == 25
        assert patient_after["recovery_count"] == 1


class TestReliabilityStrikeAgingAtEpochRun:
    def test_strike_active_through_epoch_4_ages_out_at_epoch_5(self, api):
        """PRD §3.8: "The current epoch starts at 1, and a strike is active while its `epoch` is greater than or equal to the current epoch minus 3 — a four-epoch window counting the current epoch."
        PRD §3.8: "An `OpsAdmin` advances time's erosion through the epoch run capability, which increments the current epoch by 1, recomputes both scores for every patient that has at least one strike (strikes whose `epoch` falls below the window's edge simply stop counting), and expires every `VERIFIED` attestation whose `effective_to` is at or before now."

        Design: Corner/calculations/reliability_strike_aging_at_epoch_run
        """
        ctx = setup_bookable_practice(slot_windows=[slot_time(48)])
        patient = create_patient()
        booking = book_slot(ctx["slots"][0]["id"], patient["id"], ctx["type"]["id"])
        set_clock("2026-09-03T10:05:00Z")
        api_client.mark_no_show(booking["id"], make_practice_staff_headers(ctx["practice"]["id"]))
        # Strike is at epoch 1. Advance to epoch 4: still active (1 >= 4-3).
        for _ in range(3):
            api_client.run_epoch(TEST_USERS["ops_admin_headers"])
        patient_at_4 = get_patient(patient["id"])
        assert patient_at_4["reliability_score"] == 75, (
            f"at epoch 4 the strike is still active, expected 75, got {patient_at_4['reliability_score']}"
        )
        # Advance to epoch 5: aged out (1 < 5-3).
        api_client.run_epoch(TEST_USERS["ops_admin_headers"])
        patient_at_5 = get_patient(patient["id"])
        assert patient_at_5["reliability_score"] == 100, (
            f"at epoch 5 the strike has aged out, expected 100, got {patient_at_5['reliability_score']}"
        )

    def test_epoch_run_reports_new_epoch(self, api):
        """PRD §3.8: "The current epoch starts at 1, and a strike is active while its `epoch` is greater than or equal to the current epoch minus 3 — a four-epoch window counting the current epoch."
        PRD §3.8: "The response reports the new `epoch`, the number of `decayed_strikes`, and the count of `patients_updated`."

        Design: Corner/calculations/reliability_strike_aging_at_epoch_run
        """
        ctx = setup_bookable_practice(slot_windows=[slot_time(48)])
        patient = create_patient()
        booking = book_slot(ctx["slots"][0]["id"], patient["id"], ctx["type"]["id"])
        set_clock("2026-09-03T10:05:00Z")
        api_client.mark_no_show(booking["id"], make_practice_staff_headers(ctx["practice"]["id"]))
        resp = api_client.run_epoch(TEST_USERS["ops_admin_headers"])
        data = validate_success(resp)
        assert data["epoch"] == 2, f"epoch starts at 1, first run advances to 2, got {data['epoch']}"


class TestReliabilityGateExactly50Passes35Fails:
    def _setup_patients_at_scores(self):
        """Build a practice with 7 slots and two patients: A with two NO_SHOW
        strikes (score 50), B with two NO_SHOW + one LATE_CANCEL (score 35)."""
        windows = [
            ("2026-09-03T10:00:00Z", "2026-09-03T10:30:00Z"),
            ("2026-09-03T11:00:00Z", "2026-09-03T11:30:00Z"),
            ("2026-09-03T12:00:00Z", "2026-09-03T12:30:00Z"),
            ("2026-09-03T13:00:00Z", "2026-09-03T13:30:00Z"),
            ("2026-09-04T10:00:00Z", "2026-09-04T10:30:00Z"),
            ("2026-09-05T10:00:00Z", "2026-09-05T10:30:00Z"),
            ("2026-09-05T11:00:00Z", "2026-09-05T11:30:00Z"),
        ]
        ctx = setup_bookable_practice(slot_windows=windows)
        pat_a = create_patient(email="pa@x.com", full_name="Pat A")
        pat_b = create_patient(email="pb@x.com", full_name="Pat B")
        a1 = book_slot(ctx["slots"][0]["id"], pat_a["id"], ctx["type"]["id"])
        a2 = book_slot(ctx["slots"][1]["id"], pat_a["id"], ctx["type"]["id"])
        b1 = book_slot(ctx["slots"][2]["id"], pat_b["id"], ctx["type"]["id"])
        b2 = book_slot(ctx["slots"][3]["id"], pat_b["id"], ctx["type"]["id"])
        b3 = book_slot(ctx["slots"][4]["id"], pat_b["id"], ctx["type"]["id"])
        staff = make_practice_staff_headers(ctx["practice"]["id"])
        set_clock("2026-09-03T11:05:00Z")
        api_client.mark_no_show(a1["id"], staff)
        api_client.mark_no_show(a2["id"], staff)
        set_clock("2026-09-03T13:05:00Z")
        api_client.mark_no_show(b1["id"], staff)
        api_client.mark_no_show(b2["id"], staff)
        # Late-cancel b3 at 2026-09-03T13:05:00Z — b3 starts 2026-09-04T10:00,
        # which is ~20h55m ahead, inside [2, 24).
        api_client.cancel_booking(b3["id"], make_patient_headers(pat_b["id"]))
        return ctx, pat_a, pat_b, b3

    def test_patient_at_exactly_50_books_successfully(self, api):
        """PRD §3.4: "The patient's `reliability_score` must be at least 50 — exactly 50 passes, 49 fails with `ERR_RELIABILITY_GATE` (HTTP 403)."

        Design: Difficulty/boundary_precision_check/reliability_gate_exactly_50_passes_35_fails
        """
        ctx, pat_a, pat_b, _ = self._setup_patients_at_scores()
        patient_a = get_patient(pat_a["id"])
        assert patient_a["reliability_score"] == 50
        resp = api_client.create_booking(
            ctx["slots"][5]["id"],
            {"patient_id": pat_a["id"], "appointment_type_id": ctx["type"]["id"]},
            make_patient_headers(pat_a["id"]),
        )
        validate_success(resp, 201)

    def test_patient_at_35_rejected_with_reliability_gate(self, api):
        """PRD §3.4: "The patient's `reliability_score` must be at least 50 — exactly 50 passes, 49 fails with `ERR_RELIABILITY_GATE` (HTTP 403)."

        Design: Difficulty/boundary_precision_check/reliability_gate_exactly_50_passes_35_fails
        """
        ctx, pat_a, pat_b, b3 = self._setup_patients_at_scores()
        patient_b = get_patient(pat_b["id"])
        assert patient_b["reliability_score"] == 35
        assert patient_b["provisional_score"] == 35
        b3_after = get_booking(b3["id"])
        assert b3_after["late_cancel"] is True
        assert b3_after["cancel_reason"] == "PATIENT"
        resp = api_client.create_booking(
            ctx["slots"][6]["id"],
            {"patient_id": pat_b["id"], "appointment_type_id": ctx["type"]["id"]},
            make_patient_headers(pat_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RELIABILITY_GATE)


class TestNoShowReliabilityGateCascade:
    def _setup_four_bookings(self):
        windows = [
            ("2026-09-03T10:00:00Z", "2026-09-03T10:30:00Z"),
            ("2026-09-03T11:00:00Z", "2026-09-03T11:30:00Z"),
            ("2026-09-03T12:00:00Z", "2026-09-03T12:30:00Z"),
            ("2026-09-04T10:00:00Z", "2026-09-04T10:30:00Z"),
        ]
        ctx = setup_bookable_practice(slot_windows=windows)
        patient = create_patient()
        bookings = [book_slot(s["id"], patient["id"], ctx["type"]["id"]) for s in ctx["slots"]]
        return ctx, patient, bookings

    def test_third_no_show_triggers_reliability_gate_cascade(self, api):
        """PRD §3.5: "Whenever a strike — no-show or late-cancel — causes the patient's recomputed `reliability_score` to fall below 50, every other `CONFIRMED` booking of that patient whose `start_at` is in the future is cancelled by the system with `cancel_reason` `RELIABILITY_GATE`, and each such booking's slot is released from `BOOKED` back to `OPEN`."

        Design: Difficulty/transitive_cascade/no_show_reliability_gate_cascade
        """
        ctx, patient, bookings = self._setup_four_bookings()
        staff = make_practice_staff_headers(ctx["practice"]["id"])
        set_clock("2026-09-03T10:05:00Z")
        api_client.mark_no_show(bookings[0]["id"], staff)
        set_clock("2026-09-03T11:05:00Z")
        api_client.mark_no_show(bookings[1]["id"], staff)
        set_clock("2026-09-03T12:05:00Z")
        api_client.mark_no_show(bookings[2]["id"], staff)

        patient_after = get_patient(patient["id"])
        assert patient_after["reliability_score"] == 25, (
            f"100 - 3*25 = 25, got {patient_after['reliability_score']}"
        )
        b4_after = get_booking(bookings[3]["id"])
        assert b4_after["status"] == "CANCELLED"
        assert b4_after["cancel_reason"] == "RELIABILITY_GATE"
        s4_after = get_slot(ctx["slots"][3]["id"])
        assert s4_after["status"] == "OPEN"

    def test_no_show_closes_slot_and_leaves_charge_billable(self, api):
        """PRD §3.5: "A no-show appends a strike of kind `NO_SHOW` with magnitude 25 to the patient's `strikes`, stamped with the current epoch, recomputes reliability, and closes the slot from `BOOKED` to `CLOSED` with `close_reason` `PROVIDER_SUSPENDED`. The marketplace fee is not refunded on a no-show — any charge remains `BILLABLE`."

        Design: Difficulty/transitive_cascade/no_show_reliability_gate_cascade
        """
        ctx, patient, bookings = self._setup_four_bookings()
        staff = make_practice_staff_headers(ctx["practice"]["id"])
        set_clock("2026-09-03T10:05:00Z")
        api_client.mark_no_show(bookings[0]["id"], staff)
        b1_after = get_booking(bookings[0]["id"])
        assert b1_after["status"] == "NO_SHOW"
        s1_after = get_slot(ctx["slots"][0]["id"])
        assert s1_after["status"] == "CLOSED"
        assert s1_after["close_reason"] == "PROVIDER_SUSPENDED"
        from test_helpers import list_charges_for_booking
        charges = list_charges_for_booking(bookings[0]["id"])
        assert len(charges) == 1
        assert charges[0]["status"] == "BILLABLE"


class TestNoShowTooEarly:
    def test_mark_no_show_before_start_rejected(self, api):
        """PRD §3.5: "If the patient never arrives, `PracticeStaff` mark the booking as a no-show — but only once the appointment time has actually been reached; marking before the booking's `start_at` is rejected with `ERR_NO_SHOW_TOO_EARLY`."

        Design: Corner/state_machines/no_show_too_early_rejected
        """
        ctx = setup_bookable_practice(slot_windows=[("2026-09-03T10:00:00Z", "2026-09-03T10:30:00Z")])
        patient = create_patient()
        booking = book_slot(ctx["slots"][0]["id"], patient["id"], ctx["type"]["id"])
        # Clock still at default 2026-09-01 — before the booking start.
        resp = api_client.mark_no_show(
            booking["id"], make_practice_staff_headers(ctx["practice"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_NO_SHOW_TOO_EARLY)
        booking_after = get_booking(booking["id"])
        assert booking_after["status"] == "CONFIRMED"

    def test_mark_no_show_at_start_succeeds(self, api):
        """PRD §3.5: "If the patient never arrives, `PracticeStaff` mark the booking as a no-show — but only once the appointment time has actually been reached; marking before the booking's `start_at` is rejected with `ERR_NO_SHOW_TOO_EARLY`."

        Design: Corner/state_machines/no_show_too_early_rejected
        """
        ctx = setup_bookable_practice(slot_windows=[("2026-09-03T10:00:00Z", "2026-09-03T10:30:00Z")])
        patient = create_patient()
        booking = book_slot(ctx["slots"][0]["id"], patient["id"], ctx["type"]["id"])
        set_clock("2026-09-03T10:05:00Z")
        resp = api_client.mark_no_show(
            booking["id"], make_practice_staff_headers(ctx["practice"]["id"])
        )
        data = validate_success(resp)
        assert data["status"] == "NO_SHOW"
