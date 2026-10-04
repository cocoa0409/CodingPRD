"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)

DEFAULTS = {
    "LEAGUE_REGION": "WEST",
    "SEASON_YEAR": 2027,
    "CARRIER_NAME": "LL-INS",
    "COVERAGE_START": "2027-01-01",
    "COVERAGE_END": "2027-12-31",
    "PLAYER_BIRTH_DATE": "2015-03-10",   # league_age 12 in season 2027 -> MAJOR
    "GAMES_PLAYED": 3,
    "GAMES_SCHEDULED": 5,                # participation_pct 60.00
    "WAIVER_REASON": "waiver justification",
    "WAIVER_VALID_FROM": "2027-01-01",
    "WAIVER_VALID_UNTIL": "2027-12-01",
    "SCREENING_VALID_FROM": "2027-01-01",
    "SCREENING_VALID_THROUGH": "2027-12-31",
    "PROTEST_GROUNDS": "protest grounds",
}


def create_league_payload(**overrides) -> dict:
    defaults = {
        "league_name": f"Test League {next(_counter)}",
        "region_code": DEFAULTS["LEAGUE_REGION"],
        "season_year": DEFAULTS["SEASON_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_charter_renewal_payload(**overrides) -> dict:
    defaults = {"season_year": DEFAULTS["SEASON_YEAR"]}
    defaults.update(overrides)
    return defaults


def decide_charter_renewal_payload(**overrides) -> dict:
    defaults = {"action": "APPROVE", "late_fee_paid": False}
    defaults.update(overrides)
    return defaults


def patch_division_payload(**overrides) -> dict:
    defaults = {"team_count": 1}
    defaults.update(overrides)
    return defaults


def create_player_payload(**overrides) -> dict:
    defaults = {
        "first_name": "Test",
        "last_name": f"Player{next(_counter)}",
        "birth_date": DEFAULTS["PLAYER_BIRTH_DATE"],
        "residence_within_boundary": True,
        "school_within_boundary": False,
        "games_played": DEFAULTS["GAMES_PLAYED"],
        "games_scheduled": DEFAULTS["GAMES_SCHEDULED"],
    }
    defaults.update(overrides)
    return defaults


def create_eligibility_document_payload(**overrides) -> dict:
    defaults = {"doc_type": "BIRTH_CERTIFICATE", "issued_date": "2015-03-12"}
    defaults.update(overrides)
    return defaults


def create_boundary_waiver_payload(**overrides) -> dict:
    defaults = {
        "waiver_type": "RESIDENCY_BOUNDARY",
        "reason": DEFAULTS["WAIVER_REASON"],
        "valid_from": DEFAULTS["WAIVER_VALID_FROM"],
        "valid_until": DEFAULTS["WAIVER_VALID_UNTIL"],
    }
    defaults.update(overrides)
    return defaults


def decide_boundary_waiver_payload(**overrides) -> dict:
    defaults = {"action": "APPROVE"}
    defaults.update(overrides)
    return defaults


def create_volunteer_payload(**overrides) -> dict:
    defaults = {
        "full_name": f"Vol Unteer{next(_counter)}",
        "role_title": "COACH",
    }
    defaults.update(overrides)
    return defaults


def create_screening_payload(**overrides) -> dict:
    defaults = {
        "offense_category": "NONE",
        "valid_from": DEFAULTS["SCREENING_VALID_FROM"],
        "valid_through": DEFAULTS["SCREENING_VALID_THROUGH"],
    }
    defaults.update(overrides)
    return defaults


def adjudicate_screening_payload(**overrides) -> dict:
    defaults = {"action": "APPROVE"}
    defaults.update(overrides)
    return defaults


def create_insurance_certificate_payload(**overrides) -> dict:
    defaults = {
        "carrier_name": DEFAULTS["CARRIER_NAME"],
        "coverage_start": DEFAULTS["COVERAGE_START"],
        "coverage_end": DEFAULTS["COVERAGE_END"],
    }
    defaults.update(overrides)
    return defaults


def create_all_star_roster_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def add_selection_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_tournament_entry_payload(**overrides) -> dict:
    defaults = {"level": "DISTRICT"}
    defaults.update(overrides)
    return defaults


def finalize_game_payload(**overrides) -> dict:
    defaults = {"our_score": 5, "opponent_score": 3}
    defaults.update(overrides)
    return defaults


def record_appearance_payload(**overrides) -> dict:
    defaults = {"pitches_thrown": 10}
    defaults.update(overrides)
    return defaults


def file_protest_payload(**overrides) -> dict:
    defaults = {
        "protest_type": "RULE_INTERPRETATION",
        "grounds": DEFAULTS["PROTEST_GROUNDS"],
    }
    defaults.update(overrides)
    return defaults


def resolve_protest_payload(**overrides) -> dict:
    defaults = {"action": "UPHOLD"}
    defaults.update(overrides)
    return defaults
