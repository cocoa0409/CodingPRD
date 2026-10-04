"""Validation-priority conflict claims (Difficulty queue A)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_member,
    create_confirmed_reservation,
    create_published_plan,
    enroll_member,
    get_success_data,
    make_member_headers,
    set_clock,
    setup_theater_with_on_sale_showtime,
    validate_error,
)

ADMIN = TEST_USERS["program_admin_headers"]
SERVICES = TEST_USERS["member_services_headers"]


class TestPriorityConflicts:

    def _no_show_reservation(self, api, email="m10@x.com"):
        """CONFIRMED reservation swept to NO_SHOW; clock at 2026-09-03 (well
        past the cancel_deadline of 2026-09-02T17:00:00Z)."""
        set_clock()
        plan = create_published_plan()
        _th, _aud, showtime = setup_theater_with_on_sale_showtime(
            showtime_overrides={"starts_at": "2026-09-02T19:00:00Z"})
        member = create_active_member(email=email, full_name=email)
        sub = enroll_member(member["id"], plan["id"])
        reservation = create_confirmed_reservation(member, sub, showtime)
        set_clock("2026-09-03T00:00:00Z")
        return member, sub, reservation

    def test_cancel_terminal_reservation_and_window_closed_state_beats_temporal(self, api):
        """PRD §2.10: "When several validations could reject the same request,
        they are evaluated in a fixed priority order, and the first failure
        encountered determines the error returned. The order is: ... (5) state
        admissibility of the requested transition ... (9) the member-initiated
        cancellation window"

        Design: Difficulty/priority_pair_validation_conflict/cancel_terminal_reservation_and_window_closed_state_beats_temporal
        """
        member, _sub, reservation = self._no_show_reservation(api)
        after = get_success_data(api.get_reservation(reservation["id"], SERVICES))
        assert after["status"] == "NO_SHOW"
        resp = api.cancel_reservation(reservation["id"], make_member_headers(member["id"]))
        # State (P5) outranks the temporal window (P9): ERR_INVALID_STATE, not
        # ERR_CANCEL_WINDOW_CLOSED, even though the window is also closed.
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_cancel_terminal_reservation_leaves_state_and_credit_untouched(self, api):
        """PRD §2.10: "When several validations could reject the same request,
        they are evaluated in a fixed priority order, and the first failure
        encountered determines the error returned."
        PRD §3.5: "the consumed credit is not refunded"

        Design: Difficulty/priority_pair_validation_conflict/cancel_terminal_reservation_and_window_closed_state_beats_temporal
        """
        member, _sub, reservation = self._no_show_reservation(api, email="m10b@x.com")
        bucket_before = get_success_data(
            api.get_bucket(reservation["bucket_id"], ADMIN))["credits_used"]
        resp = api.cancel_reservation(reservation["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_reservation(reservation["id"], SERVICES))
        assert after["status"] == "NO_SHOW", "rejected cancel must not move the reservation"
        bucket_after = get_success_data(
            api.get_bucket(reservation["bucket_id"], ADMIN))["credits_used"]
        assert bucket_after == bucket_before == 1, "no refund computation may run"
