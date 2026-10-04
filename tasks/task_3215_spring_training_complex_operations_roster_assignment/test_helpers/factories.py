"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_seq = itertools.count(1)


def next_idp_number() -> str:
    return f"IDP-{next(_seq):05d}"


def create_complex_payload(**overrides) -> dict:
    payload = {
        "name": "Cubs Mesa Complex",
        "host_city": TEST_DEFAULTS["COMPLEX_HOST_CITY"],
        "season_split_track": "DEDICATED",
        "timezone": TEST_DEFAULTS["COMPLEX_TIMEZONE"],
        "facility_capacity_units": TEST_DEFAULTS["COMPLEX_CAPACITY"],
    }
    payload.update(overrides)
    return payload


def create_agreement_payload(complex_id, **overrides) -> dict:
    payload = {
        "complex_id": complex_id,
        "stadium_name": "Sloan Park",
        "lease_start_date": TEST_DEFAULTS["AGREEMENT_LEASE_START"],
        "lease_end_date": TEST_DEFAULTS["AGREEMENT_LEASE_END"],
        "annual_rent_cents": TEST_DEFAULTS["ANNUAL_RENT_CENTS"],
        "sponsorship_minor_league_base_cents": TEST_DEFAULTS["SPONSORSHIP_MINOR_BASE_CENTS"],
        "sponsorship_major_league_base_cents": TEST_DEFAULTS["SPONSORSHIP_MAJOR_BASE_CENTS"],
        "ticket_price_cents": TEST_DEFAULTS["TICKET_PRICE_CENTS"],
        "ticket_sellout_capacity": TEST_DEFAULTS["TICKET_SELLOUT_CAPACITY"],
    }
    payload.update(overrides)
    return payload


def create_player_payload(home_complex_id, **overrides) -> dict:
    payload = {
        "full_name": "Test Player",
        "idp_number": next_idp_number(),
        "position_code": "P",
        "acquisition_channel": "NRI_ASSIGNMENT",
        "mlb_service_days": 0,
        "minor_league_option_years_used": 1,
        "home_country": "United States",
        "home_complex_id": home_complex_id,
    }
    payload.update(overrides)
    return payload


def create_workout_group_payload(complex_id, **overrides) -> dict:
    payload = {
        "complex_id": complex_id,
        "roster_bucket": "MAJOR",
        "group_name": "Pitchers Group A",
        "facility_kind": "FIELD",
        "capacity_units": 40,
    }
    payload.update(overrides)
    return payload


def create_assignment_payload(group_id, player_id, expected_group_version, **overrides) -> dict:
    payload = {
        "workout_group_id": group_id,
        "player_id": player_id,
        "roster_bucket": "MAJOR",
        "assignment_kind": "ACTIVE_WORKOUT",
        "expected_group_version": expected_group_version,
    }
    payload.update(overrides)
    return payload


def create_throw_program_payload(assignment_id, **overrides) -> dict:
    payload = {
        "group_assignment_id": assignment_id,
        "target_catch_play_throws": 200,
        "target_bullpen_sessions": 2,
    }
    payload.update(overrides)
    return payload


def log_session_payload(program_id, session_kind="CATCH_PLAY", **overrides) -> dict:
    payload = {
        "throw_program_id": program_id,
        "logged_at": "2026-01-05T00:00:00Z",
        "session_kind": session_kind,
        "play_catch_throws": 0,
    }
    payload.update(overrides)
    return payload


def create_workout_session_payload(group_id, session_date, session_end_datetime, **overrides) -> dict:
    payload = {
        "workout_group_id": group_id,
        "session_date": session_date,
        "session_end_datetime": session_end_datetime,
        "session_kind": "BULLPEN",
        "field_units": 1,
    }
    payload.update(overrides)
    return payload


def create_invitation_payload(player_id, **overrides) -> dict:
    payload = {"player_id": player_id, "invitation_kind": "CAMP_INVITEE"}
    payload.update(overrides)
    return payload


def create_travel_arrangement_payload(invitation_id, expected_invitation_version, **overrides) -> dict:
    payload = {
        "camp_invitation_id": invitation_id,
        "mode": "AIR",
        "travel_radius_miles": 300,
        "departure_at": TEST_DEFAULTS["DEPARTURE_AT"],
        "travel_cost_cents": 50000,
        "confirm": True,
        "expected_invitation_version": expected_invitation_version,
    }
    payload.update(overrides)
    return payload


def create_physical_payload(player_id, **overrides) -> dict:
    payload = {"player_id": player_id, "scheduled_visit_date": TEST_DEFAULTS["PHYSICAL_VISIT"]}
    payload.update(overrides)
    return payload


def create_sponsorship_payload(record_id, **overrides) -> dict:
    payload = {
        "host_community_record_id": record_id,
        "sponsor_name": "Desert Auto Group",
        "sponsor_tier": "LOCAL",
        "committed_amount_cents": 20000,
    }
    payload.update(overrides)
    return payload


def create_game_payload(complex_id, **overrides) -> dict:
    payload = {
        "complex_id": complex_id,
        "opponent_name": "Colorado Rockies",
        "home_away": "HOME",
        "game_datetime": "2026-02-12T19:00:00Z",
        "travel_radius_miles": 0,
        "duration_units": 3,
        "split_squad": False,
    }
    payload.update(overrides)
    return payload


def create_participation_payload(game_id, player_id, **overrides) -> dict:
    payload = {
        "game_schedule_id": game_id,
        "player_id": player_id,
        "squad_side": "HOME_SQUAD",
        "throw_count": 0,
    }
    payload.update(overrides)
    return payload


def create_minor_league_assignment_payload(player_id, record_id, **overrides) -> dict:
    payload = {
        "player_id": player_id,
        "roster_record_id": record_id,
        "assigned_level": "AAA",
        "affiliate_name": "Iowa Cubs",
        "effective_datetime": "2026-03-15T00:00:00Z",
    }
    payload.update(overrides)
    return payload