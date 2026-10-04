"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    CharterStatus, RenewalStatus, WindowClassification, DivisionCode,
    DivisionStatus, EligibilityStatus, DocType, WaiverType, WaiverStatus,
    VolunteerStatus, RoleTitle, OffenseCategory, ScreeningStatus,
    CertificateStatus, RosterStatus, SelectionStatus, TournamentLevel,
    EliminationFormat, EntryStatus, PlayStatus, ProtestStatus, GameResult,
    AppearanceStatus, ProtestType, ProtestDecision,
)


def _assert_common(data, entity_label):
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity_label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity_label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), \
        f"{entity_label}.version must be an integer"


def assert_league(data: dict):
    _assert_common(data, "League")
    assert isinstance(data["league_name"], str) and data["league_name"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert isinstance(data["season_year"], int)
    assert data["charter_status"] in [s.value for s in CharterStatus]
    assert isinstance(data["total_team_count"], int)


def assert_charter_renewal(data: dict):
    _assert_common(data, "CharterRenewal")
    assert is_valid_uuid(data["league_id"])
    assert isinstance(data["season_year"], int)
    assert data["window_classification"] in [c.value for c in WindowClassification]
    assert isinstance(data["provisional_fee_cents"], int)
    assert data["final_fee_cents"] is None or isinstance(data["final_fee_cents"], int)
    assert isinstance(data["late_fee_paid"], bool)
    assert data["status"] in [s.value for s in RenewalStatus]


def assert_division(data: dict):
    _assert_common(data, "Division")
    assert is_valid_uuid(data["league_id"])
    assert data["division_code"] in [c.value for c in DivisionCode]
    assert isinstance(data["min_league_age"], int)
    assert isinstance(data["max_league_age"], int)
    assert isinstance(data["team_count"], int)
    assert data["status"] in [s.value for s in DivisionStatus]


def assert_player(data: dict):
    _assert_common(data, "Player")
    assert is_valid_uuid(data["league_id"])
    assert data["division_id"] is None or is_valid_uuid(data["division_id"])
    assert isinstance(data["first_name"], str) and data["first_name"]
    assert isinstance(data["last_name"], str) and data["last_name"]
    assert isinstance(data["birth_date"], str)
    assert isinstance(data["residence_within_boundary"], bool)
    assert isinstance(data["school_within_boundary"], bool)
    assert isinstance(data["games_played"], int)
    assert isinstance(data["games_scheduled"], int)
    assert isinstance(data["participation_pct"], (int, float))
    assert isinstance(data["league_age"], int)
    assert data["eligibility_status"] in [s.value for s in EligibilityStatus]


def assert_eligibility_document(data: dict):
    # Immutable evidence: id + created_at only — no updated_at, no version.
    assert is_valid_uuid(data.get("id", "")), "EligibilityDocument.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "EligibilityDocument.created_at must be ISO 8601"
    assert "updated_at" not in data, "EligibilityDocument must not carry updated_at"
    assert "version" not in data, "EligibilityDocument must not carry version"
    assert is_valid_uuid(data["player_id"])
    assert data["doc_type"] in [t.value for t in DocType]
    assert isinstance(data["issued_date"], str)


def assert_boundary_waiver(data: dict):
    _assert_common(data, "BoundaryWaiver")
    assert is_valid_uuid(data["league_id"])
    assert is_valid_uuid(data["player_id"])
    assert data["waiver_type"] in [t.value for t in WaiverType]
    assert isinstance(data["reason"], str)
    assert isinstance(data["valid_from"], str)
    assert isinstance(data["valid_until"], str)
    assert data.get("target_division_id") is None or is_valid_uuid(data["target_division_id"])
    assert data["status"] in [s.value for s in WaiverStatus]


def assert_volunteer(data: dict):
    _assert_common(data, "Volunteer")
    assert is_valid_uuid(data["league_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["role_title"] in [t.value for t in RoleTitle]
    assert data["status"] in [s.value for s in VolunteerStatus]


def assert_background_screening(data: dict):
    _assert_common(data, "BackgroundScreening")
    assert is_valid_uuid(data["volunteer_id"])
    assert data["offense_category"] in [c.value for c in OffenseCategory]
    assert isinstance(data["valid_from"], str)
    assert isinstance(data["valid_through"], str)
    assert isinstance(data["auto_flagged"], bool)
    assert data["status"] in [s.value for s in ScreeningStatus]


def assert_insurance_certificate(data: dict):
    _assert_common(data, "InsuranceCertificate")
    assert is_valid_uuid(data["league_id"])
    assert isinstance(data["carrier_name"], str) and data["carrier_name"]
    assert isinstance(data["coverage_start"], str)
    assert isinstance(data["coverage_end"], str)
    assert data["status"] in [s.value for s in CertificateStatus]


def assert_all_star_roster(data: dict):
    _assert_common(data, "AllStarRoster")
    assert is_valid_uuid(data["league_id"])
    assert is_valid_uuid(data["division_id"])
    assert isinstance(data["season_year"], int)
    assert isinstance(data["selections"], list)
    for sel in data["selections"]:
        assert is_valid_uuid(sel["player_id"])
        assert sel["status"] in [s.value for s in SelectionStatus]
        assert "selected_at" in sel
    assert isinstance(data["roster_size"], int)
    assert data["status"] in [s.value for s in RosterStatus]


def assert_roster_size_invariant(roster: dict):
    """roster_size always equals the count of ACTIVE selections."""
    active = [s for s in roster["selections"] if s["status"] == "ACTIVE"]
    assert roster["roster_size"] == len(active), (
        f"roster_size {roster['roster_size']} != ACTIVE selection count {len(active)}")


def assert_tournament_entry(data: dict):
    _assert_common(data, "TournamentEntry")
    assert is_valid_uuid(data["league_id"])
    assert is_valid_uuid(data["roster_id"])
    assert data["level"] in [l.value for l in TournamentLevel]
    assert data["elimination_format"] in [f.value for f in EliminationFormat]
    assert isinstance(data["losses_count"], int)
    assert data["status"] in [s.value for s in EntryStatus]


def assert_tournament_game(data: dict):
    _assert_common(data, "TournamentGame")
    assert is_valid_uuid(data["entry_id"])
    assert data.get("opponent_entry_id") is None or is_valid_uuid(data["opponent_entry_id"])
    assert data["play_status"] in [s.value for s in PlayStatus]
    assert data["protest_status"] in [s.value for s in ProtestStatus]
    assert data.get("game_date") is None or isinstance(data["game_date"], str)
    assert data.get("our_score") is None or isinstance(data["our_score"], int)
    assert data.get("opponent_score") is None or isinstance(data["opponent_score"], int)
    assert data.get("result") is None or data["result"] in [r.value for r in GameResult]
    assert isinstance(data["recorded_pitch_total"], int)


def assert_pitching_appearance(data: dict):
    _assert_common(data, "PitchingAppearance")
    assert is_valid_uuid(data["game_id"])
    assert is_valid_uuid(data["player_id"])
    assert isinstance(data["pitches_thrown"], int)
    assert data.get("official_pitches") is None or isinstance(data["official_pitches"], int)
    assert isinstance(data["appearance_date"], str)
    assert isinstance(data["rest_days_required"], int)
    assert isinstance(data["eligible_again_on"], str)
    assert data["status"] in [s.value for s in AppearanceStatus]


def assert_protest(data: dict):
    _assert_common(data, "Protest")
    assert is_valid_uuid(data["game_id"])
    assert data["protest_type"] in [t.value for t in ProtestType]
    assert data.get("target_player_id") is None or is_valid_uuid(data["target_player_id"])
    assert isinstance(data["grounds"], str)
    assert data["status"] in [s.value for s in ProtestDecision]


def assert_recorded_pitch_total_invariant(game: dict, appearances: list):
    """recorded_pitch_total is the sum of effective pitches over RECORDED
    appearances; REVERSED appearances contribute zero."""
    total = 0
    for app in appearances:
        if app["status"] == "RECORDED":
            total += app["official_pitches"] if app.get("official_pitches") is not None \
                else app["pitches_thrown"]
    assert game["recorded_pitch_total"] == total, (
        f"recorded_pitch_total {game['recorded_pitch_total']} != "
        f"sum over RECORDED appearances {total}")
