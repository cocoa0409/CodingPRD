"""Difficulty rule: resource_temporal_overlap — half-open adjacency and turnover buffer."""
from test_helpers import (
    TEST_USERS, api_client, validate_success, validate_error, ApiErrorId,
    create_venue_slot_payload, reset_clock, create_venue_slot,
    create_level, create_term_draft, create_showcase_payload, create_student,
)

PD = TEST_USERS["program_director_headers"]


def _reserve_mainstage_19_to_21():
    """Create Mainstage slot 19:00-21:00 and reserve it via a showcase schedule."""
    reset_clock()
    slot = create_venue_slot(venue_name="Mainstage",
                             start_utc="2027-04-01T19:00:00Z",
                             end_utc="2027-04-01T21:00:00Z")
    level = create_level()
    term = create_term_draft()
    showcase = validate_success(api_client.create_showcase(
        create_showcase_payload(level["id"], term["id"], slot["id"], []), PD), 201)
    validate_success(api_client.schedule_showcase(showcase["id"], PD))
    return slot


class TestHalfOpenAdjacency:
    def test_adjacent_slot_allowed(self):
        """PRD §2.9: "Two slots that merely touch — one ending exactly when the
        other begins — do not conflict on overlap grounds."

        Design: Difficulty/resource_temporal_overlap/venue_slot_half_open_adjacency_allowed
        """
        _reserve_mainstage_19_to_21()
        adjacent = validate_success(api_client.create_venue_slot(
            create_venue_slot_payload(venue_name="Mainstage",
                                      start_utc="2027-04-01T21:00:00Z",
                                      end_utc="2027-04-01T23:00:00Z"), PD), 201)
        assert adjacent["id"]

    def test_overlapping_slot_rejected(self):
        """PRD §2.9: "Two slots on the same `venue_name` conflict when the first
        slot's start is strictly before the second slot's end and the second slot's
        start is strictly before the first slot's end."

        Design: Difficulty/resource_temporal_overlap/venue_slot_half_open_adjacency_allowed
        """
        _reserve_mainstage_19_to_21()
        resp = api_client.create_venue_slot(
            create_venue_slot_payload(venue_name="Mainstage",
                                      start_utc="2027-04-01T20:30:00Z",
                                      end_utc="2027-04-01T22:00:00Z"), PD)
        validate_error(resp, ApiErrorId.ERR_VENUE_SLOT_CONFLICT, 409)


class TestTurnoverBuffer:
    def test_15_minute_gap_rejected(self):
        """PRD §2.9: "between two RESERVED or BOOKED slots on the same venue there
        must be either no gap at all or a gap of at least 30 minutes; a positive gap
        shorter than 30 minutes violates the turnover buffer."

        Design: Difficulty/resource_temporal_overlap/venue_slot_turnover_buffer_gap_rule
        """
        _reserve_mainstage_19_to_21()
        resp = api_client.create_venue_slot(
            create_venue_slot_payload(venue_name="Mainstage",
                                      start_utc="2027-04-01T21:15:00Z",
                                      end_utc="2027-04-01T22:00:00Z"), PD)
        validate_error(resp, ApiErrorId.ERR_VENUE_SLOT_CONFLICT, 409)

    def test_45_minute_gap_allowed(self):
        """PRD §2.9: "between two RESERVED or BOOKED slots on the same venue there
        must be either no gap at all or a gap of at least 30 minutes; a positive gap
        shorter than 30 minutes violates the turnover buffer."

        Design: Difficulty/resource_temporal_overlap/venue_slot_turnover_buffer_gap_rule
        """
        _reserve_mainstage_19_to_21()
        ok = validate_success(api_client.create_venue_slot(
            create_venue_slot_payload(venue_name="Mainstage",
                                      start_utc="2027-04-01T21:45:00Z",
                                      end_utc="2027-04-01T22:30:00Z"), PD), 201)
        assert ok["id"]
