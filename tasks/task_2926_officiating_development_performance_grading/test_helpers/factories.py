"""Payload factories — one per write endpoint, input fields only.

Optional fields are omitted unless a caller supplies them, so the server's
declared defaults apply. Decimal quantities are always JSON numbers, and every
instant is a full ISO 8601 UTC instant.
"""
from typing import Any, Dict, Optional

from .constants import INSTANT_G1_KICKOFF, TEST_DEFAULTS

_UNSET = object()


def _prune(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys the caller left unset; an explicit None is kept."""
    return {k: v for k, v in payload.items() if v is not _UNSET}


# ─── Season programs ──────────────────────────────────

def season_program_payload(season_year: int = None, **overrides) -> dict:
    """Only `season_year` is required; every threshold is optional and defaults."""
    payload: Dict[str, Any] = {
        "season_year": TEST_DEFAULTS["season_year"] if season_year is None else season_year
    }
    payload.update(overrides)
    return payload


# ─── Officials ────────────────────────────────────────

def official_payload(
    season_program_id: str,
    full_name: str = "Dan Ruiz",
    position: str = "UMPIRE",
    seasons_experience: int = 6,
    home_market_code: str = "MIA",
    tier: Any = _UNSET,
    affiliated_team_code: Any = _UNSET,
    **overrides,
) -> dict:
    payload = _prune(
        {
            "season_program_id": season_program_id,
            "full_name": full_name,
            "position": position,
            "seasons_experience": seasons_experience,
            "home_market_code": home_market_code,
            "tier": tier,
            "affiliated_team_code": affiliated_team_code,
        }
    )
    payload.update(overrides)
    return payload


# ─── Training records ─────────────────────────────────

def training_record_payload(
    record_type: str,
    session_code: str = "SESSION-1",
    score: Any = _UNSET,
    **overrides,
) -> dict:
    payload = _prune(
        {
            "record_type": record_type,
            "session_code": session_code,
            "score": score,
        }
    )
    payload.update(overrides)
    return payload


def rules_exam_payload(score: float = 88.00, session_code: str = "EXAM-1") -> dict:
    return training_record_payload("RULES_EXAM", session_code, score)


def physical_test_payload(score: float = 82.00, session_code: str = "PHYS-1") -> dict:
    return training_record_payload("PHYSICAL_TEST", session_code, score)


def rules_clinic_payload(session_code: str = "CLINIC-1") -> dict:
    return training_record_payload("RULES_CLINIC", session_code)


# ─── Advancement ──────────────────────────────────────

def advancement_application_payload(
    official_id: str, target_tier: str = "TIER_2", **overrides
) -> dict:
    payload = {"official_id": official_id, "target_tier": target_tier}
    payload.update(overrides)
    return payload


def field_evaluation_payload(
    mechanics_score: float = 80.00,
    rules_score: float = 76.00,
    presence_score: float = 70.00,
    **overrides,
) -> dict:
    payload = {
        "mechanics_score": mechanics_score,
        "rules_score": rules_score,
        "presence_score": presence_score,
    }
    payload.update(overrides)
    return payload


def return_for_tape_payload(note: str = "More tape on deep-third coverage.") -> dict:
    return {"note": note}


def application_decision_payload(outcome: str, note: Any = _UNSET) -> dict:
    return _prune({"outcome": outcome, "note": note})


# ─── Games ────────────────────────────────────────────

def game_payload(
    season_program_id: str,
    home_team_code: str = None,
    away_team_code: str = None,
    venue_market_code: str = None,
    kickoff_utc: str = INSTANT_G1_KICKOFF,
    **overrides,
) -> dict:
    payload = {
        "season_program_id": season_program_id,
        "home_team_code": TEST_DEFAULTS["home_team_code"]
        if home_team_code is None
        else home_team_code,
        "away_team_code": TEST_DEFAULTS["away_team_code"]
        if away_team_code is None
        else away_team_code,
        "venue_market_code": TEST_DEFAULTS["venue_market_code"]
        if venue_market_code is None
        else venue_market_code,
        "kickoff_utc": kickoff_utc,
    }
    payload.update(overrides)
    return payload


# ─── Crew assignments ─────────────────────────────────

def crew_assignment_payload(
    game_id: str,
    official_id: str,
    position: str,
    expected_game_version: int,
    **overrides,
) -> dict:
    payload = {
        "game_id": game_id,
        "official_id": official_id,
        "position": position,
        "expected_game_version": expected_game_version,
    }
    payload.update(overrides)
    return payload


def withdraw_assignment_payload(reason: Optional[str] = None) -> Optional[dict]:
    return None if reason is None else {"reason": reason}


# ─── Play grades ──────────────────────────────────────

def play_grade_payload(
    game_id: str,
    official_id: str,
    play_ref: str = "Q1-P01",
    call_category: str = "HOLDING",
    grade_code: str = "CORRECT",
    impact: str = "MEDIUM",
    **overrides,
) -> dict:
    payload = {
        "game_id": game_id,
        "official_id": official_id,
        "play_ref": play_ref,
        "call_category": call_category,
        "grade_code": grade_code,
        "impact": impact,
    }
    payload.update(overrides)
    return payload


# ─── Grade appeals ────────────────────────────────────

def grade_appeal_payload(play_grade_id: str, basis_note: str = None, **overrides) -> dict:
    payload = {
        "play_grade_id": play_grade_id,
        "basis_note": TEST_DEFAULTS["basis_note"] if basis_note is None else basis_note,
    }
    payload.update(overrides)
    return payload


def appeal_decision_payload(
    outcome: str,
    decision_note: Any = _UNSET,
    revised_grade_code: Any = _UNSET,
) -> dict:
    return _prune(
        {
            "outcome": outcome,
            "decision_note": decision_note,
            "revised_grade_code": revised_grade_code,
        }
    )


# ─── Replay ───────────────────────────────────────────

def replay_station_payload(
    station_code: str = None,
    concurrent_capacity: Any = _UNSET,
    status: Any = _UNSET,
    **overrides,
) -> dict:
    payload = _prune(
        {
            "station_code": TEST_DEFAULTS["station_code"]
            if station_code is None
            else station_code,
            "concurrent_capacity": concurrent_capacity,
            "status": status,
        }
    )
    payload.update(overrides)
    return payload


def replay_review_payload(
    game_id: str,
    station_id: str,
    play_ref: str = "Q2-P11",
    category: str = "SCORING_PLAY",
    **overrides,
) -> dict:
    payload = {
        "game_id": game_id,
        "station_id": station_id,
        "play_ref": play_ref,
        "category": category,
    }
    payload.update(overrides)
    return payload


def replay_decision_payload(decision: str = "CONFIRMED") -> dict:
    return {"decision": decision}


# ─── Pool reports ─────────────────────────────────────

def pool_report_payload(
    game_id: str,
    play_grade_id: str,
    report_type: str = "POOL_REPORT",
    body: str = None,
    supersedes_id: Any = _UNSET,
    **overrides,
) -> dict:
    payload = _prune(
        {
            "game_id": game_id,
            "play_grade_id": play_grade_id,
            "report_type": report_type,
            "body": TEST_DEFAULTS["report_body"] if body is None else body,
            "supersedes_id": supersedes_id,
        }
    )
    payload.update(overrides)
    return payload


# ─── Discipline ───────────────────────────────────────

def discipline_action_payload(
    official_id: str,
    reason_category: str,
    severity: str,
    expected_official_version: int,
    suspension_games: Any = _UNSET,
    **overrides,
) -> dict:
    payload = _prune(
        {
            "official_id": official_id,
            "reason_category": reason_category,
            "severity": severity,
            "expected_official_version": expected_official_version,
            "suspension_games": suspension_games,
        }
    )
    payload.update(overrides)
    return payload


def remediation_payload(remediation_plan: str = None) -> dict:
    return {
        "remediation_plan": TEST_DEFAULTS["remediation_plan"]
        if remediation_plan is None
        else remediation_plan
    }


def resolve_discipline_payload(outcome: str, note: Any = _UNSET) -> dict:
    return _prune({"outcome": outcome, "note": note})
