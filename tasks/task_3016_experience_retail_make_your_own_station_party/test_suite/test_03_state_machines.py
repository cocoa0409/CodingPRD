"""State machine coverage: cyclic animal recovery, party auto-confirm branching,
payment -> guest attendance cascade, and finalize gating on guest resolution."""
from test_helpers import (
    MANAGER,
    complete_guest_session,
    create_customer,
    create_paid_walk_in,
    create_party,
    create_store,
    make_customer_headers,
    pay_party_deposit,
    set_clock,
    setup_confirmed_party,
    setup_workshop_env,
    validate_error,
    validate_success,
)
from test_helpers import ApiErrorId


class TestStuffedAnimalLostRecoveryCycle:
    def test_completed_lost_found_cancel_returns_to_completed(self, api):
        """PRD §3.9: "Reporting a `COMPLETED` animal lost moves it to `LOST_REPORTED`.
        From there the owner may mark it `RECOVERED` when the toy turns up, or cancel
        the lost report to return the animal to `COMPLETED`."

        Design: Difficulty/non_linear_state_machine/stuffed_animal_lost_recovery_cycle
        """
        env = setup_workshop_env(
            store_name="Cycle Store",
            fiber_qty=5000,
            chip_qty=None,
            station_capacity=2,
            model_overrides={
                "name": "Cycle Cat",
                "sku": "CC-01",
                "base_price_cents": 3200,
                "required_stuffing_grams": 250,
            },
        )
        customer = env["customer"]
        _, animal_id = create_paid_walk_in(env)
        headers = make_customer_headers(customer["id"])
        lost = validate_success(api.report_animal_lost(animal_id, headers))
        assert lost["status"] == "LOST_REPORTED"
        back = validate_success(api.mark_animal_found_cancel(animal_id, headers))
        assert back["status"] == "COMPLETED", (
            "the lost report may be cancelled, cycling back to COMPLETED"
        )

    def test_second_loop_terminates_recovered(self, api):
        """PRD §3.9: "From there the owner may mark it `RECOVERED` when the toy turns
        up, or cancel the lost report to return the animal to `COMPLETED`. `RECOVERED`
        is terminal."

        Design: Difficulty/non_linear_state_machine/stuffed_animal_lost_recovery_cycle
        """
        env = setup_workshop_env(
            store_name="Cycle Store",
            fiber_qty=5000,
            chip_qty=None,
            station_capacity=2,
            model_overrides={
                "name": "Cycle Cat",
                "sku": "CC-01",
                "base_price_cents": 3200,
                "required_stuffing_grams": 250,
            },
        )
        customer = env["customer"]
        _, animal_id = create_paid_walk_in(env)
        headers = make_customer_headers(customer["id"])
        validate_success(api.report_animal_lost(animal_id, headers))
        validate_success(api.mark_animal_found_cancel(animal_id, headers))
        validate_success(api.report_animal_lost(animal_id, headers))
        recovered = validate_success(api.mark_animal_recovered(animal_id, headers))
        assert recovered["status"] == "RECOVERED"


class TestPartyAutoConfirmation:
    def test_deposit_paid_before_threshold_stays_put(self, api):
        """PRD §3.7: "Twenty-four hours before `party_start`, the system
        auto-transitions the reservation from `DEPOSIT_PAID` to `CONFIRMED`; the
        transition is evaluated when the logical clock crosses the threshold."

        Design: Difficulty/non_linear_state_machine/party_reservation_branching_confirm_vs_cancel_with_auto_transition
        """
        store = create_store(name="Branch Store", party_room_count=1)
        customer = create_customer(email="c6@example.com", full_name="Casey Six")
        set_clock("2026-10-01T00:00:00Z")
        party = create_party(
            customer,
            store["id"],
            party_start="2026-10-05T18:00:00Z",
            guest_count=6,
            package_tier="BASIC",
            staffing_mode="SELF_GUIDED",
        )
        party = pay_party_deposit(party, customer["id"])
        assert party["status"] == "DEPOSIT_PAID"

    def test_clock_crossing_threshold_confirms_party(self, api):
        """PRD §3.7: "Twenty-four hours before `party_start`, the system
        auto-transitions the reservation from `DEPOSIT_PAID` to `CONFIRMED`; the
        transition is evaluated when the logical clock crosses the threshold."

        Design: Difficulty/non_linear_state_machine/party_reservation_branching_confirm_vs_cancel_with_auto_transition
        """
        store = create_store(name="Branch Store", party_room_count=1)
        customer = create_customer(email="c6@example.com", full_name="Casey Six")
        set_clock("2026-10-01T00:00:00Z")
        party = create_party(
            customer,
            store["id"],
            party_start="2026-10-05T18:00:00Z",
            guest_count=6,
            package_tier="BASIC",
            staffing_mode="SELF_GUIDED",
        )
        party = pay_party_deposit(party, customer["id"])
        # 2026-10-05T00:00:00Z is 18h before party_start, past the 24h threshold
        # (2026-10-04T18:00:00Z).
        set_clock("2026-10-05T00:00:00Z")
        after = validate_success(
            api.get_party(party["id"], make_customer_headers(customer["id"]))
        )
        assert after["status"] == "CONFIRMED", (
            "crossing party_start - 24h must auto-transition DEPOSIT_PAID -> CONFIRMED"
        )


class TestPaymentCascadesGuestAttendanceThenFinalBill:
    def test_payment_marks_guest_attended_before_finalize(self, api):
        """PRD §3.5: "When the paid session has `origin_type` `PARTY`, its linked
        guest is marked `ATTENDED`"

        Design: Difficulty/transitive_cascade/party_payment_cascades_guest_attendance_then_final_bill
        """
        env = setup_confirmed_party(
            guest_count=6,
            confirmed_guests=1,
            package_tier="BASIC",
            party_start="2026-10-08T18:00:00Z",
            clock_at_booking="2026-10-01T00:00:00Z",
            store_name="Cascade Store",
            party_room_count=1,
            station_capacity=4,
        )
        customer = env["customer"]
        guest = env["guests"][0]
        session_id = env["sessions"][0]["session_id"]
        assert session_id, "auto-confirm must create the guest's session"
        complete_guest_session(session_id, customer["id"])
        guest_after = validate_success(
            api.get_party_guest(guest["id"], make_customer_headers(customer["id"]))
        )
        assert guest_after["status"] == "ATTENDED", (
            "the guest's ATTENDED mark must come from the session payment, "
            "not from finalize"
        )

    def test_finalize_clamps_negative_due_to_zero(self, api):
        """PRD §3.7: "If the deposit exceeds the subtotal, the result is clamped to
        zero and the excess deposit is forfeited, never refunded."

        Design: Difficulty/transitive_cascade/party_payment_cascades_guest_attendance_then_final_bill
        """
        env = setup_confirmed_party(
            guest_count=6,
            confirmed_guests=1,
            package_tier="BASIC",
            party_start="2026-10-08T18:00:00Z",
            clock_at_booking="2026-10-01T00:00:00Z",
            store_name="Cascade Store",
            party_room_count=1,
            station_capacity=4,
        )
        customer = env["customer"]
        complete_guest_session(env["sessions"][0]["session_id"], customer["id"])
        set_clock("2026-10-08T20:00:00Z")
        finalized = validate_success(api.finalize_party(env["party"]["id"], MANAGER))
        assert finalized["status"] == "COMPLETED"
        # 1 billable guest: 1899 + 285 = 2184; minus deposit 10000 -> clamped to 0.
        assert finalized["final_amount_due_cents"] == 0, (
            f"negative result must clamp to 0, got {finalized['final_amount_due_cents']}"
        )


class TestFinalizeRequiresAllGuestSessionsTerminal:
    def test_finalize_rejected_while_guest_session_open(self, api):
        """PRD §3.7: "every guest in `CONFIRMED` status to have resolved to either
        `ATTENDED` (their session was paid) or `NO_SHOW` (their session was abandoned
        or cancelled); finalizing a reservation not in `CONFIRMED` status, or with
        unresolved guests, is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/party_finalize_requires_all_guest_sessions_terminal
        """
        env = setup_confirmed_party(
            guest_count=6,
            confirmed_guests=1,
            package_tier="BASIC",
            party_start="2026-10-06T18:00:00Z",
            clock_at_booking="2026-10-01T00:00:00Z",
            store_name="Finalize Store",
            party_room_count=1,
            station_capacity=2,
        )
        # Clock is at party_start (18:00); move past the block end.
        set_clock("2026-10-06T20:00:00Z")
        validate_error(
            api.finalize_party(env["party"]["id"], MANAGER),
            ApiErrorId.ERR_INVALID_STATE,
        )

    def test_abandoning_open_session_unblocks_finalize(self, api):
        """PRD §3.7: "every guest in `CONFIRMED` status to have resolved to either
        `ATTENDED` (their session was paid) or `NO_SHOW` (their session was abandoned
        or cancelled); finalizing a reservation not in `CONFIRMED` status, or with
        unresolved guests, is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/party_finalize_requires_all_guest_sessions_terminal
        """
        from test_helpers import ASSOCIATE

        env = setup_confirmed_party(
            guest_count=6,
            confirmed_guests=1,
            package_tier="BASIC",
            party_start="2026-10-06T18:00:00Z",
            clock_at_booking="2026-10-01T00:00:00Z",
            store_name="Finalize Store",
            party_room_count=1,
            station_capacity=2,
        )
        set_clock("2026-10-06T20:00:00Z")
        session_id = env["sessions"][0]["session_id"]
        validate_success(api.abandon_workshop(session_id, ASSOCIATE))
        guest = validate_success(
            api.get_party_guest(
                env["guests"][0]["id"], make_customer_headers(env["customer"]["id"])
            )
        )
        assert guest["status"] == "NO_SHOW"
        finalized = validate_success(api.finalize_party(env["party"]["id"], MANAGER))
        assert finalized["status"] == "COMPLETED"
