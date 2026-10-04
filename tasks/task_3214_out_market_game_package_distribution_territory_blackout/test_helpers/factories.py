"""Payload factories — one per entity, input fields only.

Every factory produces a minimal valid create payload; overrides are merged
on top of the defaults.
"""
from .constants import TEST_DEFAULTS


def create_rights_grant_payload(**overrides) -> dict:
    defaults = {
        "distributor_name": "StreamMax",
        "scope": "OUT_OF_MARKET",
        "exclusivity": "EXCLUSIVE",
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_until": "2027-06-01T00:00:00Z",
        "max_commercial_occupancy_cap": TEST_DEFAULTS["OCCUPANCY_CAP"],
    }
    defaults.update(overrides)
    return defaults


def create_season_payload(rights_grant_id, **overrides) -> dict:
    defaults = {
        "rights_grant_id": rights_grant_id,
        "label": "2026-Regular",
        "regular_season_weeks": TEST_DEFAULTS["REGULAR_SEASON_WEEKS_18"],
        "season_start_date": TEST_DEFAULTS["SEASON_START_18W"],
        "season_end_date": TEST_DEFAULTS["SEASON_END_18W"],
    }
    defaults.update(overrides)
    return defaults


def create_market_payload(**overrides) -> dict:
    defaults = {
        "code": "DAL",
        "name": "Dallas",
        "zip_prefixes": ["750"],
        "home_team_codes": ["DAL"],
    }
    defaults.update(overrides)
    return defaults


def create_game_payload(season_id, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "week_index": 4,
        "away_team_code": "KC",
        "home_team_code": "DAL",
        "kickoff_at": TEST_DEFAULTS["WEEK4_GAME_KICKOFF_EARLY"],
        "home_market_code": "DAL",
    }
    defaults.update(overrides)
    return defaults


def create_week_slate_payload(season_id, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "week_index": 4,
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(season_id, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "plan_tier": "BASE",
        "base_price_cents": TEST_DEFAULTS["BASE_PRICE_CENTS"],
        "includes_multiview": False,
        "includes_companion": False,
        "valid_from": TEST_DEFAULTS["OFFER_VALID_FROM"],
        "valid_until": TEST_DEFAULTS["OFFER_VALID_UNTIL"],
    }
    defaults.update(overrides)
    return defaults


def register_account_payload(**overrides) -> dict:
    defaults = {
        "email": "user@x.com",
        "full_name": "Test User",
        "account_kind": "RESIDENTIAL",
        "billing_zip": "10001",
    }
    defaults.update(overrides)
    return defaults


def create_student_verification_payload(account_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "institution_name": "State U",
        "verification_method": "SHEERID",
        "valid_through": "2027-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_venue_license_payload(account_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "venue_name": "Sports Bar",
        "venue_zip": "75001",
        "fire_code_occupancy": 80,
    }
    defaults.update(overrides)
    return defaults
