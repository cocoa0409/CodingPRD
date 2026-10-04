"""Compensating invariants: seat conservation and card stock partition."""
from test_helpers import (
    ADMIN,
    COORD,
    QA,
    create_scheduled_session,
    enroll_student,
    get_success_data,
    setup_completed_session_with_cards,
    setup_teaching_scenario,
    validate_success,
)


class TestRosterSeatConservation:
    def test_enroll_cancel_enroll_keeps_invariant(self, api):
        """PRD §3.11: "Seat conservation: for every session, `seats_available`
        plus the number of roster entries on that session whose status is
        `ENROLLED` equals the session's `capacity`. Roster adds decrement the
        seat count, manual roster cancels increment it, and any session-level
        cancellation (manual or cascade) recomputes `seats_available` to
        `capacity` because no entry remains `ENROLLED`."

        Design: Difficulty/compensating_invariant/roster_seat_conservation
        """
        ctx = setup_teaching_scenario()
        session = create_scheduled_session(ctx)
        assert session["seats_available"] == 6  # 6 - 0 enrolled

        e1 = enroll_student(session["id"], "Sam Student", "sam@x.example")
        e2 = enroll_student(session["id"], "Rita Rescuer", "rita@x.example")
        s_mid = validate_success(api.get_course_session(session["id"], COORD))
        assert s_mid["seats_available"] == 4  # 6 - 2 enrolled

        validate_success(api.cancel_roster_entry(e1["id"], COORD))
        s_end = validate_success(api.get_course_session(session["id"], COORD))
        assert s_end["seats_available"] == 5  # 6 - 1 enrolled
        e1_now = validate_success(api.get_roster_entry(e1["id"], COORD))
        e2_now = validate_success(api.get_roster_entry(e2["id"], COORD))
        assert e1_now["status"] == "CANCELLED"
        assert e2_now["status"] == "ENROLLED"

    def test_session_cancel_releases_all_seats(self, api):
        """PRD §3.4: "Either way `cancel_reason` is set to `MANUAL`, no cards
        are issued for any roster entry on the session, every `ENROLLED` roster
        entry is cancelled, and `seats_available` is recomputed back to
        `capacity`."

        Design: Difficulty/compensating_invariant/roster_seat_conservation
        """
        ctx = setup_teaching_scenario()
        session = create_scheduled_session(ctx)
        e1 = enroll_student(session["id"], "Sam Student", "sam@x.example")
        e2 = enroll_student(session["id"], "Rita Rescuer", "rita@x.example")
        cancelled = validate_success(api.cancel_session(session["id"], COORD))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancel_reason"] == "MANUAL"
        assert cancelled["seats_available"] == 6
        for e in (e1, e2):
            now = validate_success(api.get_roster_entry(e["id"], COORD))
            assert now["status"] == "CANCELLED"


class TestCardStockConservation:
    def test_issue_revoke_expire_partition_holds(self, api):
        """PRD §3.11: "Card stock partition: for every center,
        `cards_issued_count` equals `active_card_count` plus the count of that
        center's cards in `EXPIRED` status plus the count in `REVOKED` status.
        Issuance increments both `cards_issued_count` and `active_card_count`;
        revocation and clock-sweep expiry each move one unit out of
        `active_card_count` into the corresponding terminal bucket without
        touching `cards_issued_count`."

        Design: Difficulty/compensating_invariant/card_stock_conservation
        """
        built = setup_completed_session_with_cards(num_students=2)
        center_id = built["center"]["id"]
        card_a, card_b = built["cards"]

        c0 = validate_success(api.get_training_center(center_id, QA))
        assert c0["cards_issued_count"] == 2
        assert c0["active_card_count"] == 2  # 2 == 2 + 0 expired + 0 revoked

        validate_success(api.revoke_card(card_a["id"], QA))
        c1 = validate_success(api.get_training_center(center_id, QA))
        # Revoke never touches cards_issued_count.
        assert c1["cards_issued_count"] == 2
        assert c1["active_card_count"] == 1

        # Card B expires at 2028-09-30T23:59:59Z; the sweep at 2028-10-15
        # expires it and moves one unit out of active.
        get_success_data(api.set_clock("2028-10-15T00:00:00Z", ADMIN))
        b_now = validate_success(api.get_card(card_b["id"], QA))
        assert b_now["status"] == "EXPIRED"
        c2 = validate_success(api.get_training_center(center_id, QA))
        assert c2["cards_issued_count"] == 2
        assert c2["active_card_count"] == 0  # 2 == 0 + 1 expired + 1 revoked

    def test_revoke_releases_only_active_bucket(self, api):
        """PRD §3.7: "A `QAAuditor` or `NationalAdmin` may revoke it, which
        requires the card to currently be `ACTIVE` (otherwise
        `ERR_CARD_NOT_ACTIVE`) and moves it to terminal `REVOKED`, decrementing
        the issuing center's `active_card_count` by 1 without touching
        `cards_issued_count`."

        Design: Difficulty/compensating_invariant/card_stock_conservation
        """
        built = setup_completed_session_with_cards(num_students=1)
        center_id = built["center"]["id"]
        card = built["cards"][0]

        revoked = validate_success(api.revoke_card(card["id"], ADMIN))
        assert revoked["status"] == "REVOKED"
        c = validate_success(api.get_training_center(center_id, QA))
        assert c["cards_issued_count"] == 1
        assert c["active_card_count"] == 0
