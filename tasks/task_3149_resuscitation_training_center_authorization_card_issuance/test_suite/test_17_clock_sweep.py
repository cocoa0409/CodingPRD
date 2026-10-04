"""Corner coverage: cross-cutting complexity — the logical-clock expiry sweep."""
from test_helpers import (
    ADMIN,
    TC,
    get_success_data,
    setup_completed_session_with_cards,
    validate_success,
)


class TestClockSweepExpiryCheckpoint:
    def test_clock_sweep_expires_cards_and_instructors(self, api):
        """PRD §2.4: "Setting the clock performs an expiry sweep across the
        entire dataset, and the response body reports the new value as
        `current_utc`. The sweep has two effects. Every `Instructor` in
        `CERTIFIED` status whose `renewal_due_at` is strictly earlier than the
        new clock value transitions to `EXPIRED`. Every `CourseCompletionCard`
        in `ACTIVE` status whose `expires_at` is strictly earlier than the new
        clock value transitions to `EXPIRED`, and the issuing center's
        `active_card_count` is decremented by one for each card expired (the
        lifetime `cards_issued_count` is never touched by an expiry)."

        Design: Corner/cross_cutting_complexity_layers/clock_sweep_expires_cards_and_instructors
        """
        built = setup_completed_session_with_cards(num_students=1)
        card = built["cards"][0]
        lead_id = built["lead"]["id"]
        faculty_id = built["faculty"]["id"]
        center_id = built["center"]["id"]
        # lead and faculty both have renewal_due_at 2028-09-01T00:00:00Z;
        # the card expires 2028-09-30T23:59:59Z.
        assert card["expires_at"] == "2028-09-30T23:59:59Z"

        get_success_data(api.set_clock("2028-11-01T00:00:00Z", ADMIN))

        lead = validate_success(api.get_instructor(lead_id, TC))
        assert lead["status"] == "EXPIRED"
        faculty = validate_success(api.get_instructor(faculty_id, TC))
        assert faculty["status"] == "EXPIRED"

        card_now = validate_success(api.get_card(card["id"], TC))
        assert card_now["status"] == "EXPIRED"

        center = validate_success(api.get_training_center(center_id, TC))
        assert center["active_card_count"] == 0
        assert center["cards_issued_count"] == 1

    def test_clock_at_exact_expiry_keeps_card_active(self, api):
        """PRD §2.4: "A card whose `expires_at` equals the new clock value
        exactly is still `ACTIVE` after the sweep; likewise an instructor whose
        `renewal_due_at` equals the new clock remains `CERTIFIED`. The boundary
        is strict-greater in both cases."

        Design: Corner/cross_cutting_complexity_layers/clock_sweep_expires_cards_and_instructors
        """
        built = setup_completed_session_with_cards(num_students=1)
        card = built["cards"][0]
        lead_id = built["lead"]["id"]

        # Clock == instructor renewal_due_at exactly: still CERTIFIED.
        get_success_data(api.set_clock("2028-09-01T00:00:00Z", ADMIN))
        lead = validate_success(api.get_instructor(lead_id, TC))
        assert lead["status"] == "CERTIFIED"

        # Clock == card expires_at exactly (2028-09-30T23:59:59Z): still ACTIVE.
        get_success_data(api.set_clock("2028-09-30T23:59:59Z", ADMIN))
        card_now = validate_success(api.get_card(card["id"], TC))
        assert card_now["status"] == "ACTIVE"
