"""Request-payload builders.

Every builder returns a plain dict that satisfies the PRD's field-level rules,
and every one accepts ``**overrides`` so a test can bend exactly one field.
Money is always an integer number of cents sent as a JSON *number*, never a
string; percentages are JSON numbers with two decimals; instants are full
ISO-8601 strings carrying an explicit UTC offset, never date-only values.
"""
import copy
import itertools
from typing import Any, Dict, List, Optional

from test_helpers.constants import BASE_BYLAWS
from test_helpers.types import (
    AwardType,
    CarryoverPolicy,
    EntryType,
    HandicapAverageBasis,
    LanePairAction,
    MemberClass,
    ProtestCategory,
    RosterRole,
)

_email_counter = itertools.count(1)


def unique_email(stem: str = "bowler") -> str:
    """A fresh address; ``email`` is unique across all registered members."""
    return f"{stem}.{next(_email_counter)}@example.test"


# ─── §3.1 members, leagues, bylaws, schedule ───────────

def member_payload(
    full_name: str = "Dana Kegler",
    member_class: MemberClass = MemberClass.ADULT,
    email: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name,
        "email": email if email is not None else unique_email(),
        "member_class": _value(member_class),
    }
    payload.update(overrides)
    return payload


def league_payload(
    secretary_member_id: str,
    treasurer_member_id: str,
    name: str = "Thursday Night Classic",
    season_year: int = 2026,
    center_name: str = "Sunset Lanes",
    declared_team_count: int = 2,
    organizational_meeting_at: str = "2026-08-05T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name,
        "season_year": season_year,
        "center_name": center_name,
        "declared_team_count": declared_team_count,
        "organizational_meeting_at": organizational_meeting_at,
        "secretary_member_id": secretary_member_id,
        "treasurer_member_id": treasurer_member_id,
    }
    payload.update(overrides)
    return payload


def bylaws_payload(expected_league_version: int, **overrides: Any) -> Dict[str, Any]:
    """The eighteen bylaw values plus the league's concurrency echo."""
    payload: Dict[str, Any] = {"expected_league_version": expected_league_version}
    payload.update(copy.deepcopy(BASE_BYLAWS))
    payload.update(overrides)
    payload["handicap_average_basis"] = _value(payload["handicap_average_basis"])
    payload["carryover_policy"] = _value(payload["carryover_policy"])
    return payload


def schedule_match(
    week_number: int,
    home_team_id: str,
    away_team_id: str,
    lane_pair_id: str,
    starts_at: str,
    ends_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "week_number": week_number,
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
        "lane_pair_id": lane_pair_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    payload.update(overrides)
    return payload


def schedule_payload(
    total_weeks: int,
    matches: List[Dict[str, Any]],
    **overrides: Any,
) -> Dict[str, Any]:
    """Schedule adoption takes no version echo — only bylaws, lineups and plan
    drafting carry one, per the PRD's explicit statement that no other endpoint
    takes a version field of any kind."""
    payload: Dict[str, Any] = {"total_weeks": total_weeks, "matches": matches}
    payload.update(overrides)
    return payload


# ─── §3.2 teams and memberships ────────────────────────

def team_payload(league_id: str, name: str = "Alley Cats", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"league_id": league_id, "name": name}
    payload.update(overrides)
    return payload


def membership_payload(
    league_id: str,
    member_id: str,
    team_id: Optional[str] = None,
    roster_role: RosterRole = RosterRole.REGULAR,
    prior_season_average: Optional[int] = None,
    prior_season_games: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "league_id": league_id,
        "member_id": member_id,
        "team_id": team_id,
        "roster_role": _value(roster_role),
        "prior_season_average": prior_season_average,
        "prior_season_games": prior_season_games,
    }
    payload.update(overrides)
    return payload


# ─── §3.3 fee remittances ──────────────────────────────

def fee_remittance_payload(
    league_id: str,
    membership_ids: List[str],
    declared_amount_cents: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "league_id": league_id,
        "membership_ids": list(membership_ids),
        "declared_amount_cents": declared_amount_cents,
    }
    payload.update(overrides)
    return payload


def remittance_submit_payload(
    declared_amount_cents: Optional[int] = None, **overrides: Any
) -> Dict[str, Any]:
    """``declared_amount_cents`` is optional on submission; when supplied it
    overwrites the value recorded at drafting (the correction path)."""
    payload: Dict[str, Any] = {}
    if declared_amount_cents is not None:
        payload["declared_amount_cents"] = declared_amount_cents
    payload.update(overrides)
    return payload


def national_accept_payload(
    national_receipt_no: str = "NRC-2026-000001", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "decision": "ACCEPT",
        "national_receipt_no": national_receipt_no,
    }
    payload.update(overrides)
    return payload


def national_reject_payload(
    rejection_reason: str = "Member roster does not match the receipted list.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "decision": "REJECT",
        "rejection_reason": rejection_reason,
    }
    payload.update(overrides)
    return payload


# ─── §3.4 lane pairs and lineups ───────────────────────

def lane_pair_payload(
    league_id: str,
    pair_number: int = 1,
    certified_through: str = "2026-12-31T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "league_id": league_id,
        "pair_number": pair_number,
        "certified_through": certified_through,
    }
    payload.update(overrides)
    return payload


def recertify_payload(certified_through: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "action": _value(LanePairAction.RECERTIFY),
        "certified_through": certified_through,
    }
    payload.update(overrides)
    return payload


def revoke_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": _value(LanePairAction.REVOKE)}
    payload.update(overrides)
    return payload


def slot(
    position: int,
    entry_type: EntryType = EntryType.REGULAR,
    membership_id: Optional[str] = None,
    prebowled_at: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """One element of a lineup's ``slots`` array.

    A ``VACANCY`` slot carries no ``membership_id`` key at all — the PRD says the
    field is null on such a slot and is *never supplied* on one — and
    ``prebowled_at`` appears only when the caller asks for it.
    """
    payload: Dict[str, Any] = {"position": position, "entry_type": _value(entry_type)}
    if _value(entry_type) != _value(EntryType.VACANCY):
        payload["membership_id"] = membership_id
    if prebowled_at is not None:
        payload["prebowled_at"] = prebowled_at
    payload.update(overrides)
    return payload


def vacancy_slot(position: int, **overrides: Any) -> Dict[str, Any]:
    return slot(position, EntryType.VACANCY, **overrides)


def absentee_slot(position: int, membership_id: str, **overrides: Any) -> Dict[str, Any]:
    return slot(position, EntryType.ABSENTEE, membership_id, **overrides)


def prebowl_slot(
    position: int, membership_id: str, prebowled_at: str, **overrides: Any
) -> Dict[str, Any]:
    return slot(position, EntryType.PREBOWL, membership_id, prebowled_at, **overrides)


def lineup_payload(
    expected_match_version: int,
    team_id: str,
    slots: List[Dict[str, Any]],
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_match_version": expected_match_version,
        "team_id": team_id,
        "slots": list(slots),
    }
    payload.update(overrides)
    return payload


# ─── §3.5 scores and forfeits ──────────────────────────

def score_entry(
    series_entry_id: str,
    game1_pins: Optional[int],
    game2_pins: Optional[int],
    game3_pins: Optional[int],
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "series_entry_id": series_entry_id,
        "game1_pins": game1_pins,
        "game2_pins": game2_pins,
        "game3_pins": game3_pins,
    }
    payload.update(overrides)
    return payload


def absentee_score_entry(series_entry_id: str, **overrides: Any) -> Dict[str, Any]:
    """An absentee slot appears in ``entries`` with its three game fields null,
    because the bowler did not roll."""
    return score_entry(series_entry_id, None, None, None, **overrides)


def scores_payload(entries: List[Dict[str, Any]], **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"entries": list(entries)}
    payload.update(overrides)
    return payload


def forfeit_payload(forfeiting_team_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"forfeiting_team_id": forfeiting_team_id}
    payload.update(overrides)
    return payload


# ─── §3.7 dues, plans, awards ──────────────────────────

def dues_payload(week_number: int, amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "week_number": week_number,
        "amount_cents": amount_cents,
    }
    payload.update(overrides)
    return payload


def distribution_plan_payload(
    expected_prize_fund_version: int,
    basis_variant: Any,
    place_count: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_prize_fund_version": expected_prize_fund_version,
        "basis_variant": _value(basis_variant),
        "place_count": place_count,
    }
    payload.update(overrides)
    return payload


def reversal_payload(
    reversal_reason: str = "Award paid to the wrong team.", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reversal_reason": reversal_reason}
    payload.update(overrides)
    return payload


# ─── §3.8 honor-score applications ─────────────────────

def award_application_payload(
    league_id: str,
    membership_id: str,
    series_entry_id: str,
    award_type: Any,
    claimed_game_number: Optional[int] = None,
    evidence_note: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """``claimed_game_number`` is required for the two game categories and
    forbidden for the two series categories, so it is omitted entirely rather
    than sent as null when the caller does not supply it."""
    payload: Dict[str, Any] = {
        "league_id": league_id,
        "membership_id": membership_id,
        "series_entry_id": series_entry_id,
        "award_type": _value(award_type),
    }
    if claimed_game_number is not None:
        payload["claimed_game_number"] = claimed_game_number
    if evidence_note is not None:
        payload["evidence_note"] = evidence_note
    payload.update(overrides)
    return payload


def league_verification_payload(
    decision: str = "VERIFY", evidence_note: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if evidence_note is not None:
        payload["evidence_note"] = evidence_note
    payload.update(overrides)
    return payload


def evidence_payload(
    evidence_note: str = "Attached the signed scoresheet and the lane audit.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"evidence_note": evidence_note}
    payload.update(overrides)
    return payload


def association_decision_payload(
    decision: str = "CERTIFY",
    association_ruling_note: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if association_ruling_note is not None:
        payload["association_ruling_note"] = association_ruling_note
    payload.update(overrides)
    return payload


# ─── §3.9 protests ─────────────────────────────────────

def protest_payload(
    league_id: str,
    filed_by_membership_id: str,
    category: Any = ProtestCategory.SCORE_ERROR,
    protest_note: str = "The away side's third game was transcribed incorrectly.",
    match_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """``match_id`` is required for every category except a pure
    ``RULES_INTERPRETATION`` question, so it is omitted when not supplied."""
    payload: Dict[str, Any] = {
        "league_id": league_id,
        "filed_by_membership_id": filed_by_membership_id,
        "category": _value(category),
        "protest_note": protest_note,
    }
    if match_id is not None:
        payload["match_id"] = match_id
    payload.update(overrides)
    return payload


def review_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def ruling_payload(
    decision: str,
    ruling_note: str = "The hearing panel recorded its rationale in full.",
    remedy: Optional[Any] = None,
    forfeiting_team_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision, "ruling_note": ruling_note}
    if remedy is not None:
        payload["remedy"] = _value(remedy)
    if forfeiting_team_id is not None:
        payload["forfeiting_team_id"] = forfeiting_team_id
    payload.update(overrides)
    return payload


def association_ruling_payload(
    association_ruling: str = "The association affirms the league's reading of the bylaw.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"association_ruling": association_ruling}
    payload.update(overrides)
    return payload


# ─── shared plumbing ───────────────────────────────────

def _value(candidate: Any) -> Any:
    """Unwrap a string enum into its wire value, passing anything else through
    so a test can deliberately send an unrecognised literal."""
    return candidate.value if hasattr(candidate, "value") else candidate
