"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import (
    COVERAGE_INDEX_STEP_PERSONS,
    DEFAULT_CLOCK,
    SCHEDULE_DEFAULTS,
    STAFFING_INDEX_PER_FTE,
)

DEFAULTS = {
    # A station whose derived figures reproduce the PRD's own worked example:
    # coverage 600000 -> coverage_index 54, staffing 20 -> 100, newsroom 6 -> 60
    # gives 21.6 + 35 + 15 = 71.60; households 600000 -> index 60.
    "CALL_SIGN": "WQXR",
    "LICENSEE_NAME": "Hudson Licensee",
    "STATE_CODE": "NY",
    "DMA_MARKET_RANK": 60,
    "DMA_HOUSEHOLDS": 600000,
    "COVERAGE_POPULATION": 600000,
    "FULL_TIME_STAFF_COUNT": 20,
    "NEWSROOM_STAFF_COUNT": 6,
    "ANNUAL_LOCAL_REVENUE_CENTS": 4800000,
    "BOARD_SEAT_REGION": "REGION_NORTHEAST",
}


def create_station_payload(**overrides) -> dict:
    payload = {
        "call_sign": DEFAULTS["CALL_SIGN"],
        "licensee_name": DEFAULTS["LICENSEE_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "dma_market_rank": DEFAULTS["DMA_MARKET_RANK"],
        "dma_households": DEFAULTS["DMA_HOUSEHOLDS"],
        "coverage_population": DEFAULTS["COVERAGE_POPULATION"],
        "full_time_staff_count": DEFAULTS["FULL_TIME_STAFF_COUNT"],
        "newsroom_staff_count": DEFAULTS["NEWSROOM_STAFF_COUNT"],
        "annual_local_revenue_cents": DEFAULTS["ANNUAL_LOCAL_REVENUE_CENTS"],
        "board_seat_region": DEFAULTS["BOARD_SEAT_REGION"],
    }
    payload.update(overrides)
    return payload


def create_schedule_payload(**overrides) -> dict:
    payload = {
        "schedule_code": "FY2026A",
        "fiscal_year": SCHEDULE_DEFAULTS["fiscal_year"],
        "base_fee_cents": SCHEDULE_DEFAULTS["base_fee_cents"],
        "revenue_rate_bps": SCHEDULE_DEFAULTS["revenue_rate_bps"],
        "market_tier_1_max_rank": SCHEDULE_DEFAULTS["market_tier_1_max_rank"],
        "market_tier_2_max_rank": SCHEDULE_DEFAULTS["market_tier_2_max_rank"],
        "market_tier_3_max_rank": SCHEDULE_DEFAULTS["market_tier_3_max_rank"],
        "market_size_multiplier_bps": SCHEDULE_DEFAULTS["market_size_multiplier_bps"],
        "minimum_fee_cents": SCHEDULE_DEFAULTS["minimum_fee_cents"],
        "maximum_fee_cents": SCHEDULE_DEFAULTS["maximum_fee_cents"],
        "annual_adjustment_bps": SCHEDULE_DEFAULTS["annual_adjustment_bps"],
        "effective_from": SCHEDULE_DEFAULTS["effective_from"],
        "effective_to": SCHEDULE_DEFAULTS["effective_to"],
    }
    payload.update(overrides)
    return payload


def create_agreement_payload(**overrides) -> dict:
    payload = {
        "station_id": None,
        "program_code": "NP-1001",
        "obligation_type": "MANDATORY",
        "clearance_deadline": "2026-11-01T00:00:00Z",
        "exception_liability_cap_cents": 500000,
    }
    payload.update(overrides)
    return payload


def create_window_payload(**overrides) -> dict:
    payload = {
        "parent_agreement_id": None,
        "station_id": None,
        "program_code": "NP-1001",
        "window_start": "2026-10-05T14:00:00Z",
        "window_end": "2026-10-05T15:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_feed_payload(**overrides) -> dict:
    payload = {
        "feed_code": "FEED-A001",
        "feed_type": "SATELLITE",
        "total_capacity_units": 10,
        # PRD §2.5: a ratio is an integer basis-point figure, never a decimal
        # fraction, so four fifths is 8000 and not 0.8.
        "max_reserved_capacity_ratio": 8000,
    }
    payload.update(overrides)
    return payload


def create_slot_payload(**overrides) -> dict:
    payload = {
        "parent_feed_id": None,
        "station_id": None,
        "window_id": None,
        "slot_start": "2026-10-05T13:30:00Z",
        "slot_end": "2026-10-05T15:30:00Z",
        "priority_rank": 3,
        # PRD §3.4: the congestion rule compares a slot's `priority_rank`
        # against `preemptible_priority_rank_floor`; the floor is part of the
        # reservation contract, so the factory always supplies it.
        "preemptible_priority_rank_floor": 3,
    }
    payload.update(overrides)
    return payload


def create_underwriting_payload(**overrides) -> dict:
    payload = {
        "sponsor_name": "Cascade Coffee Roasters",
        "station_id": None,
        "program_code": "NP-1002",
        "ack_script_text": "Support for this program comes from Cascade Coffee Roasters",
        "consideration_cents": 250000,
        "compliance_segment_count": 2,
    }
    payload.update(overrides)
    return payload


def create_contribution_payload(**overrides) -> dict:
    payload = {
        "station_id": None,
        "program_id": None,
        "headline": "Harbor cleanup stalls",
        "duration_seconds": 180,
    }
    payload.update(overrides)
    return payload


def create_program_payload(**overrides) -> dict:
    payload = {
        "program_code": "NP-1001",
        "program_title": "Morning Edition Extra",
        "strand_type": "NEWS",
        "national_premiere_at": "2026-10-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_drive_payload(**overrides) -> dict:
    payload = {
        "station_id": None,
        "drive_name": "Fall 2026 Drive",
        "drive_close_at": "2026-10-15T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_audience_report_payload(**overrides) -> dict:
    payload = {
        "station_id": None,
        "fiscal_year": 2026,
        "cume_persons": 250000,
        "nielsen_share_bps": 2100,
        "local_content_hours": 1200,
    }
    payload.update(overrides)
    return payload


def create_proposal_payload(**overrides) -> dict:
    payload = {
        "fiscal_year": 2027,
        "proposed_base_fee_cents": 1350000,
        "proposed_revenue_rate_bps": 275,
        "quorum_required_votes": 1,
        "effective_from": "2027-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_election_payload(**overrides) -> dict:
    payload = {
        "board_region": "REGION_SOUTH",
        "fiscal_year": 2026,
        "seats_available": 1,
        "certification_deadline": "2026-11-15T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_candidate_payload(**overrides) -> dict:
    payload = {
        "parent_election_id": None,
        "station_id": None,
        "nomination_statement": "Serve the region",
    }
    payload.update(overrides)
    return payload


def create_seat_payload(**overrides) -> dict:
    payload = {
        "board_region": "REGION_SOUTH",
        "term_start": "2026-12-01T00:00:00Z",
        "term_end": "2028-12-01T00:00:00Z",
        "board_rank": 1,
    }
    payload.update(overrides)
    return payload


def station_payload_for_class(target_class: str, **overrides) -> dict:
    """Build a station payload whose derived class is `target_class` (PRD §3.1).

    Inputs are chosen so the operations score and the household index clear the
    target rung of the ladder while staying inside the PRD's own documented
    arithmetic (coverage 9/100k capped at 100, staffing 5/FTE, newsroom 10/FTE,
    households 5/50k).
    """
    presets = {
        # coverage 600000 -> 54; staffing 20 -> 100; newsroom 6 -> 60
        # score = 21.6 + 35 + 15 = 71.60 ; households 600000 -> index 60 (>= 30)
        "CLASS_B": dict(
            call_sign="WQXR", dma_market_rank=60, dma_households=600000,
            coverage_population=600000, full_time_staff_count=20, newsroom_staff_count=6,
        ),
        # coverage 10000000 -> 100; staffing 20 -> 100; newsroom 10 -> 100
        # score = 40 + 35 + 25 = 100.00 ; households 12000000 -> index 100 (>= 45)
        "CLASS_A": dict(
            call_sign="WNYC", dma_market_rank=1, dma_households=12000000,
            coverage_population=10000000, full_time_staff_count=20, newsroom_staff_count=10,
        ),
        # coverage 1000000 -> 90; staffing 6 -> 30; newsroom 9 -> 90
        # score = 36 + 10.5 + 22.5 = 69.00 ; households 150000 -> index 15 (>= 15)
        "CLASS_C": dict(
            call_sign="KUT", dma_market_rank=40, dma_households=150000,
            coverage_population=1000000, full_time_staff_count=6, newsroom_staff_count=9,
        ),
        # coverage 60000 -> 0; staffing 3 -> 15; newsroom 2 -> 20
        # score = 0 + 5.25 + 5 = 10.25 ; households 100000 -> index 10 (< 15)
        "CLASS_D": dict(
            call_sign="KAZU", dma_market_rank=118, dma_households=100000,
            coverage_population=60000, full_time_staff_count=3, newsroom_staff_count=2,
        ),
    }
    payload = create_station_payload(**presets[target_class])
    payload.update(overrides)
    return payload


def clock_payload(to_iso8601: str = DEFAULT_CLOCK) -> dict:
    return {"to_iso8601": to_iso8601}