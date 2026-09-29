"""Payload factories — one per resource kind, client-supplied fields only.

Money is always an integer number of cents, proportions are always integer
basis points, and every temporal field except ``Player.birth_date`` is a full
ISO 8601 UTC instant.
"""

from .constants import (
    CONTRACT_EFFECTIVE_AT,
    LEAGUE_DEFAULTS,
    ORG_DEFAULTS,
    ROSTER_LOCK_AT,
    SEASON_END_AT,
    SEASON_START_AT,
    TEAM_HOUSE_DEFAULTS,
    TEST_DEFAULTS,
    TRANSFER_WINDOW_CLOSE_AT,
    TRANSFER_WINDOW_OPEN_AT,
)


def create_league_payload(**overrides) -> dict:
    payload = {
        "name": "Apex Masters League",
        "season_start_at": SEASON_START_AT,
        "season_end_at": SEASON_END_AT,
        "roster_lock_at": ROSTER_LOCK_AT,
        "transfer_window_open_at": TRANSFER_WINDOW_OPEN_AT,
        "transfer_window_close_at": TRANSFER_WINDOW_CLOSE_AT,
    }
    payload.update(LEAGUE_DEFAULTS)
    payload.update(overrides)
    return payload


def create_minimal_league_payload(**overrides) -> dict:
    """Only the fields the PRD marks required, so the optional ones default."""
    payload = {
        "name": "Apex Masters League",
        "season_start_at": SEASON_START_AT,
        "season_end_at": SEASON_END_AT,
        "roster_lock_at": ROSTER_LOCK_AT,
        "transfer_window_open_at": TRANSFER_WINDOW_OPEN_AT,
        "transfer_window_close_at": TRANSFER_WINDOW_CLOSE_AT,
    }
    payload.update(overrides)
    return payload


def create_organization_payload(league_id: str, **overrides) -> dict:
    payload = {
        "league_id": league_id,
        "name": "Vertex Vanguard",
        "tax_jurisdiction_code": "US-CA",
        "annual_salary_budget_cents": ORG_DEFAULTS["annual_salary_budget_cents"],
        "org_prize_share_bp": ORG_DEFAULTS["org_prize_share_bp"],
    }
    payload.update(overrides)
    return payload


def create_player_payload(**overrides) -> dict:
    payload = {
        "full_name": "Rin Adachi",
        "birth_date": "2001-05-14",
        "region_code": "JP",
        "association_member": True,
        "education_enrollment_status": "NOT_ENROLLED",
    }
    payload.update(overrides)
    return payload


def create_minor_player_payload(**overrides) -> dict:
    payload = {
        "full_name": "Ilya Novak",
        "birth_date": "2010-02-20",
        "region_code": "US",
        "association_member": False,
        "education_enrollment_status": "NOT_ENROLLED",
    }
    payload.update(overrides)
    return payload


def guardian_consent_payload(**overrides) -> dict:
    payload = {
        "guardian_name": "Vera Novak",
        "guardian_email": "vera@example.com",
        "guardian_weekly_cap_minutes": 1080,
    }
    payload.update(overrides)
    return payload


def create_contract_offer_payload(organization_id: str, player_id: str, **overrides) -> dict:
    payload = {
        "organization_id": organization_id,
        "player_id": player_id,
        "base_salary_cents": TEST_DEFAULTS["BASE_SALARY_CENTS"],
        "term_months": TEST_DEFAULTS["TERM_MONTHS"],
        "prize_split_player_pct_bp": TEST_DEFAULTS["PRIZE_SPLIT_PLAYER_PCT_BP"],
        "streaming_hours_per_week": TEST_DEFAULTS["STREAMING_HOURS_PER_WEEK"],
        "tax_residency_code": TEST_DEFAULTS["TAX_RESIDENCY_CODE"],
        "signing_bonus_cents": TEST_DEFAULTS["SIGNING_BONUS_CENTS"],
        "buyout_multiplier_bp": TEST_DEFAULTS["BUYOUT_MULTIPLIER_BP"],
    }
    payload.update(overrides)
    return payload


def counter_offer_payload(**overrides) -> dict:
    payload = {
        "counter_base_salary_cents": 13500000,
        "counter_prize_split_player_pct_bp": 5000,
        "counter_streaming_hours_per_week": 8,
        "counter_note": "counter round",
    }
    payload.update(overrides)
    return payload


def revise_offer_payload(**overrides) -> dict:
    payload = {
        "base_salary_cents": 13000000,
        "prize_split_player_pct_bp": 4800,
        "streaming_hours_per_week": 9,
    }
    payload.update(overrides)
    return payload


def accept_offer_payload(effective_at: str = CONTRACT_EFFECTIVE_AT, **overrides) -> dict:
    payload = {"effective_at": effective_at}
    payload.update(overrides)
    return payload


def decline_offer_payload(**overrides) -> dict:
    payload = {"decline_note": "agent walked away"}
    payload.update(overrides)
    return payload


def suspend_contract_payload(**overrides) -> dict:
    payload = {"suspension_reason": "disciplinary review"}
    payload.update(overrides)
    return payload


def wellness_report_payload(**overrides) -> dict:
    payload = {"last_self_reported_load": 0, "reported_streaming_minutes_7d": 0}
    payload.update(overrides)
    return payload


def create_team_house_payload(**overrides) -> dict:
    payload = {
        "name": "Vanguard House",
        "timezone": "UTC",
        "turnaround_buffer_minutes": TEAM_HOUSE_DEFAULTS["turnaround_buffer_minutes"],
        "concurrent_seat_capacity": TEAM_HOUSE_DEFAULTS["concurrent_seat_capacity"],
    }
    payload.update(overrides)
    return payload


def create_practice_block_payload(
    organization_id: str,
    team_house_id: str,
    starts_at: str,
    ends_at: str,
    participant_player_ids,
    block_type: str = "SCRIM",
    **overrides,
) -> dict:
    payload = {
        "organization_id": organization_id,
        "team_house_id": team_house_id,
        "block_type": block_type,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "participant_player_ids": list(participant_player_ids),
    }
    payload.update(overrides)
    return payload


def cancel_block_payload(**overrides) -> dict:
    payload = {"cancel_reason": "COACH_CANCELLED"}
    payload.update(overrides)
    return payload


def create_sponsorship_deal_payload(organization_id: str, **overrides) -> dict:
    payload = {
        "organization_id": organization_id,
        "sponsor_name": "Kestrel Peripherals",
        "exclusivity_category": "PERIPHERALS",
        "total_fee_cents": TEST_DEFAULTS["DEAL_TOTAL_FEE_CENTS"],
        "deliverable_count_required": 2,
        "starts_at": CONTRACT_EFFECTIVE_AT,
        "ends_at": "2026-12-31T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_deliverable_payload(
    contract_id: str, expected_deal_version: int, **overrides
) -> dict:
    payload = {
        "contract_id": contract_id,
        "deliverable_type": "SOCIAL_POST",
        "due_at": "2026-09-01T00:00:00Z",
        "expected_deal_version": expected_deal_version,
    }
    payload.update(overrides)
    return payload


def submit_deliverable_payload(**overrides) -> dict:
    payload = {"submission_note": "posted"}
    payload.update(overrides)
    return payload


def review_deliverable_payload(decision: str = "APPROVE", **overrides) -> dict:
    payload = {"decision": decision, "review_note": "on brand"}
    payload.update(overrides)
    return payload


def create_prize_distribution_payload(
    organization_id: str, league_id: str, **overrides
) -> dict:
    payload = {
        "organization_id": organization_id,
        "league_id": league_id,
        "tournament_name": "Summer Invitational",
        "placement": 2,
        "gross_prize_cents": TEST_DEFAULTS["GROSS_PRIZE_CENTS"],
        "tournament_end_at": "2026-08-20T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def void_distribution_payload(**overrides) -> dict:
    payload = {"void_reason": "tournament result overturned by the referee panel"}
    payload.update(overrides)
    return payload


def create_roster_move_payload(
    organization_id: str,
    player_id: str,
    move_type: str,
    contract_id: str,
    expected_organization_version: int,
    **overrides,
) -> dict:
    payload = {
        "organization_id": organization_id,
        "player_id": player_id,
        "move_type": move_type,
        "contract_id": contract_id,
        "expected_organization_version": expected_organization_version,
    }
    payload.update(overrides)
    return payload


def move_decision_payload(decision: str = "APPROVE", **overrides) -> dict:
    payload = {"decision": decision, "decision_note": "league review"}
    payload.update(overrides)
    return payload


def reverse_move_payload(**overrides) -> dict:
    payload = {"reversal_reason": "release filed against the wrong player"}
    payload.update(overrides)
    return payload


def set_clock_payload(current_utc: str) -> dict:
    return {"current_utc": current_utc}
