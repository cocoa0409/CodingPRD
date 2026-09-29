"""Request payload builders.

Every builder emits exactly the field types the specification declares: money as
integer cents carried as JSON numbers, instants as full ISO 8601 UTC datetimes,
counts as integers and scope arrays as real arrays. Overrides are accepted so a
test can bend one field without restating a whole payload.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    DEFAULT_TARGET_RELEASE_UTC,
    MARKET_BOARD,
)

# ─── Titles ────────────────────────────────────────────────────────────


def title_payload(title_code: str = "NOVA-01", name: str = "Nova Drift",
                  source_language: str = "EN",
                  target_release_utc: str = DEFAULT_TARGET_RELEASE_UTC,
                  release_mode: str = "STAGGERED", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "title_code": title_code,
        "name": name,
        "source_language": source_language,
        "target_release_utc": target_release_utc,
        "release_mode": release_mode,
    }
    payload.update(overrides)
    return payload


# ─── String keys ───────────────────────────────────────────────────────

LEGAL_CONTEXT_NOTE = "Licence panel copy; keep the legal register formal."


def string_key_payload(title_id: str, key_name: str, source_text: str,
                       source_char_count: int, ui_surface: str,
                       display_char_limit: int, tm_match_pct: int,
                       context_note: Optional[str] = None,
                       **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "title_id": title_id,
        "key_name": key_name,
        "source_text": source_text,
        "source_char_count": source_char_count,
        "ui_surface": ui_surface,
        "display_char_limit": display_char_limit,
        "tm_match_pct": tm_match_pct,
    }
    # Legal copy is never handed to a translator without context, so a LEGAL
    # surface always carries a note unless a test deliberately clears it.
    if context_note is None and ui_surface == "LEGAL":
        context_note = LEGAL_CONTEXT_NOTE
    if context_note is not None:
        payload["context_note"] = context_note
    payload.update(overrides)
    return payload


# The four source strings the arithmetic examples are pinned on. Under the
# SCOPE_ESTIMATE variant these four sum to 4.30 effort units.
CANONICAL_KEY_SPECS: List[Dict[str, Any]] = [
    {
        "key_name": "menu.start",
        "source_text": "Start Game",
        "source_char_count": 125,
        "ui_surface": "MENU",
        "display_char_limit": 140,
        "tm_match_pct": 96,
    },
    {
        "key_name": "sub.intro",
        "source_text": "The colony fell before dawn.",
        "source_char_count": 250,
        "ui_surface": "SUBTITLE",
        "display_char_limit": 260,
        "tm_match_pct": 80,
    },
    {
        "key_name": "legal.eula",
        "source_text": "By continuing you accept the licence.",
        "source_char_count": 90,
        "ui_surface": "LEGAL",
        "display_char_limit": 100,
        "tm_match_pct": 40,
    },
    {
        "key_name": "hud.ammo",
        "source_text": "Ammo",
        "source_char_count": 175,
        "ui_surface": "HUD",
        "display_char_limit": 180,
        "tm_match_pct": 60,
    },
]

MENU_KEY_SPEC = CANONICAL_KEY_SPECS[0]
SUBTITLE_KEY_SPEC = CANONICAL_KEY_SPECS[1]
LEGAL_KEY_SPEC = CANONICAL_KEY_SPECS[2]
HUD_KEY_SPEC = CANONICAL_KEY_SPECS[3]


def canonical_key_payloads(title_id: str) -> List[Dict[str, Any]]:
    """The canonical four string keys, in extraction order."""
    return [string_key_payload(title_id, **spec) for spec in CANONICAL_KEY_SPECS]


def menu_key_payload(title_id: str, **overrides) -> Dict[str, Any]:
    return string_key_payload(title_id, **{**MENU_KEY_SPEC, **overrides})


def legal_key_payload(title_id: str, **overrides) -> Dict[str, Any]:
    return string_key_payload(title_id, **{**LEGAL_KEY_SPEC, **overrides})


def patch_string_key_payload(**fields) -> Dict[str, Any]:
    """Amend translator context or translation-memory match, or retire the key."""
    return dict(fields)


# ─── Market plans ──────────────────────────────────────────────────────


def market_plan_payload(title_id: str, market_code: str = "JP",
                        scope_tier: str = "TEXT_ONLY",
                        target_rating: str = "TEEN_12",
                        budget_cap_cents: int = 5000000,
                        required_voice_line_count: int = 0,
                        rating_board: Optional[str] = None,
                        cultural_adaptation_required: Optional[bool] = None,
                        **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "title_id": title_id,
        "market_code": market_code,
        "rating_board": rating_board if rating_board is not None
        else MARKET_BOARD[market_code],
        "target_rating": target_rating,
        "scope_tier": scope_tier,
        "cultural_adaptation_required": (
            cultural_adaptation_required if cultural_adaptation_required is not None
            else scope_tier == "FULL_CULTURAL"
        ),
        "budget_cap_cents": budget_cap_cents,
        "required_voice_line_count": required_voice_line_count,
    }
    payload.update(overrides)
    return payload


def block_payload(blocked_reason: str = "LEGAL_RESTRICTION", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"blocked_reason": blocked_reason}
    payload.update(overrides)
    return payload


# ─── Translation units ─────────────────────────────────────────────────


def translation_text_payload(target_text: str, target_char_count: int,
                             applied_tm_match_pct: int, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "target_text": target_text,
        "target_char_count": target_char_count,
        "applied_tm_match_pct": applied_tm_match_pct,
    }
    payload.update(overrides)
    return payload


def qa_mark_payload(qa_status: str = "PASSED", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"qa_status": qa_status}
    payload.update(overrides)
    return payload


# Target text matched to the canonical four keys, at the applied match
# percentages the DELIVERED_ACTUAL example is pinned on (96 / 60 / 40 / 60).
CANONICAL_DELIVERY_SPECS: List[Dict[str, Any]] = [
    {"target_text": "ゲーム開始", "target_char_count": 120, "applied_tm_match_pct": 96},
    {
        "target_text": "コロニーは夜明け前に陥落した。",
        "target_char_count": 240,
        "applied_tm_match_pct": 60,
    },
    {
        "target_text": "続行すると使用許諾に同意したものとみなされます。",
        "target_char_count": 95,
        "applied_tm_match_pct": 40,
    },
    {"target_text": "残弾", "target_char_count": 170, "applied_tm_match_pct": 60},
]


# ─── Booths, talents and contracts ─────────────────────────────────────


def booth_payload(booth_code: str = "BER-A", studio_city: str = "Berlin",
                  turnaround_buffer_minutes: Optional[int] = None,
                  **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "booth_code": booth_code,
        "studio_city": studio_city,
    }
    if turnaround_buffer_minutes is not None:
        payload["turnaround_buffer_minutes"] = turnaround_buffer_minutes
    payload.update(overrides)
    return payload


def voice_talent_payload(talent_name: str = "Anke Roth", language_code: str = "DE",
                         union_flag: bool = True,
                         max_daily_recording_minutes: Optional[int] = None,
                         **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "talent_name": talent_name,
        "language_code": language_code,
        "union_flag": union_flag,
    }
    if max_daily_recording_minutes is not None:
        payload["max_daily_recording_minutes"] = max_daily_recording_minutes
    payload.update(overrides)
    return payload


def talent_contract_payload(voice_talent_id: str, title_id: str,
                            expected_voice_talent_version: int,
                            territory_scope: Optional[List[str]] = None,
                            media_scope: str = "IN_GAME_AND_TRAILER",
                            buyout_fee_cents: int = 500000,
                            per_line_rate_cents: int = 250,
                            rights_start_utc: str = "2026-08-01T00:00:00Z",
                            rights_end_utc: str = "2026-12-31T00:00:00Z",
                            **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "voice_talent_id": voice_talent_id,
        "title_id": title_id,
        "territory_scope": list(territory_scope) if territory_scope else ["DE"],
        "media_scope": media_scope,
        "buyout_fee_cents": buyout_fee_cents,
        "per_line_rate_cents": per_line_rate_cents,
        "rights_start_utc": rights_start_utc,
        "rights_end_utc": rights_end_utc,
        "expected_voice_talent_version": expected_voice_talent_version,
    }
    payload.update(overrides)
    return payload


# ─── Voice sessions ────────────────────────────────────────────────────


def voice_session_payload(market_plan_id: str, voice_talent_id: str,
                          recording_booth_id: str, talent_contract_id: str,
                          start_utc: str = "2026-09-10T09:00:00Z",
                          end_utc: str = "2026-09-10T12:00:00Z",
                          planned_line_count: int = 120,
                          **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "market_plan_id": market_plan_id,
        "voice_talent_id": voice_talent_id,
        "recording_booth_id": recording_booth_id,
        "talent_contract_id": talent_contract_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "planned_line_count": planned_line_count,
    }
    payload.update(overrides)
    return payload


def complete_session_payload(recorded_line_count: int, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"recorded_line_count": recorded_line_count}
    payload.update(overrides)
    return payload


# ─── QA passes and defects ─────────────────────────────────────────────


def qa_pass_payload(market_plan_id: str, pass_type: str = "LINGUISTIC",
                    inspected_unit_count: int = 100, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "market_plan_id": market_plan_id,
        "pass_type": pass_type,
        "inspected_unit_count": inspected_unit_count,
    }
    payload.update(overrides)
    return payload


def lqa_bug_payload(qa_pass_id: str, bug_class: str = "MISTRANSLATION",
                    severity: str = "S2",
                    summary: str = "Honorific register wrong in the opening line.",
                    translation_unit_id: Optional[str] = None,
                    **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "qa_pass_id": qa_pass_id,
        "bug_class": bug_class,
        "severity": severity,
        "summary": summary,
    }
    if translation_unit_id is not None:
        payload["translation_unit_id"] = translation_unit_id
    payload.update(overrides)
    return payload


def triage_payload(triage_action: str = "ACCEPT",
                   duplicate_of_bug_id: Optional[str] = None,
                   **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"triage_action": triage_action}
    if duplicate_of_bug_id is not None:
        payload["duplicate_of_bug_id"] = duplicate_of_bug_id
    payload.update(overrides)
    return payload


def submit_fix_payload(target_text: Optional[str] = None, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if target_text is not None:
        payload["target_text"] = target_text
    payload.update(overrides)
    return payload


# ─── Rating submissions and content edits ──────────────────────────────


def rating_submission_payload(market_plan_id: str,
                              expected_market_plan_version: int,
                              disclosed_content_codes: Optional[List[str]] = None,
                              footage_asset_count: int = 1,
                              target_rating: str = "TEEN_12",
                              **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "market_plan_id": market_plan_id,
        "disclosed_content_codes": (
            list(disclosed_content_codes) if disclosed_content_codes is not None
            else ["VIOLENCE_STYLIZED"]
        ),
        "footage_asset_count": footage_asset_count,
        "target_rating": target_rating,
        "expected_market_plan_version": expected_market_plan_version,
    }
    payload.update(overrides)
    return payload


def record_outcome_payload(board_decision: str = "RATE",
                           assigned_rating: Optional[str] = None,
                           **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"board_decision": board_decision}
    if assigned_rating is not None:
        payload["assigned_rating"] = assigned_rating
    payload.update(overrides)
    return payload


def content_edit_payload(rating_submission_id: str, edit_kind: str = "CENSOR_ASSET",
                         rationale: str = "Blur the execution close-up and soften the "
                                          "ammo readout warning.",
                         affected_string_key_ids: Optional[List[str]] = None,
                         removed_content_codes: Optional[List[str]] = None,
                         **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "rating_submission_id": rating_submission_id,
        "edit_kind": edit_kind,
        "rationale": rationale,
        "affected_string_key_ids": list(affected_string_key_ids or []),
        "removed_content_codes": list(removed_content_codes or []),
    }
    payload.update(overrides)
    return payload
