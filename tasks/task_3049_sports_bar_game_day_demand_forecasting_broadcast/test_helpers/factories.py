"""Payload factories — one per creatable resource, input fields only."""

from typing import Any, Dict

from .constants import DEFAULT_VENUE


def venue_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = dict(DEFAULT_VENUE)
    payload.update(overrides)
    return payload


def event_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "kind": "BASE",
        "league": "FF_NFL",
        "title": "Game",
        "home_market_zip": "14201",
        "expected_attendance": 5000,
        "scheduled_start": "2026-09-13T19:00:00Z",
        "scheduled_end": "2026-09-13T22:00:00Z",
    }
    payload.update(overrides)
    return payload


def license_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "league": "NCAA",
        "blackout_radius_miles": 75,
        "fee_per_head_cents": 100,
    }
    payload.update(overrides)
    return payload


def zone_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"name": "Main Bar", "screen_ids": ["S1"]}
    payload.update(overrides)
    return payload


def screen_assignment_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "event_id": None,
        "screen_id": "S1",
        "audio_enabled": True,
    }
    payload.update(overrides)
    return payload


def guest_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "venue_id": None,
        "name": "Alex",
        "phone": "555-0100",
    }
    payload.update(overrides)
    return payload


def waitlist_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "venue_id": None,
        "guest_id": None,
        "party_size": 4,
    }
    payload.update(overrides)
    return payload


def check_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "venue_id": None,
        "guest_id": None,
        "party_size": 2,
        "kind": "REGULAR",
    }
    payload.update(overrides)
    return payload


def order_line_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"kind": "TRADITIONAL", "portion_count": 1}
    payload.update(overrides)
    return payload


def promo_rule_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "day_of_week": 6,
        "wing_kind": "TRADITIONAL",
        "promo_price_cents_per_10": 900,
        "start_date": "2026-09-01T00:00:00Z",
        "end_date": "2026-09-30T23:59:59Z",
    }
    payload.update(overrides)
    return payload


def staffing_plan_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"name": "Sunday Shift"}
    payload.update(overrides)
    return payload


def shift_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "role": "FOH",
        "start_time": "2026-09-14T16:00:00Z",
        "end_time": "2026-09-15T00:00:00Z",
        "headcount": 10,
        "expected_covers": 3600,
    }
    payload.update(overrides)
    return payload


def trivia_session_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"title": "Trivia Night"}
    payload.update(overrides)
    return payload


def trivia_answer_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"is_correct": True, "response_time_ms": 10000}
    payload.update(overrides)
    return payload


def fantasy_contest_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "entry_fee_cents": 2500,
        "rake_pct": 0.10,
        "prize_structure": [0.5, 0.3, 0.2],
    }
    payload.update(overrides)
    return payload


def fantasy_entry_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"guest_id": None, "lineup": {"qb": "Allen"}}
    payload.update(overrides)
    return payload


def ppv_event_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "event_id": None,
        "commercial_fee_cents": 100000,
        "cover_charge_cents": 2000,
    }
    payload.update(overrides)
    return payload


def wing_quote_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "guest_id": None,
        "wing_kind": "TRADITIONAL",
        "pieces": 20,
        "event_date": "2026-09-13",
    }
    payload.update(overrides)
    return payload
