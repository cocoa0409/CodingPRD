"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import TEST_DEFAULTS

_card_seq = {"n": 1000}
_tag_seq = {"n": 100}


def _next_card(prefix="PRCA"):
    _card_seq["n"] += 1
    return f"{prefix}-{_card_seq['n']}"


def _next_tag(prefix="A"):
    _tag_seq["n"] += 1
    return f"{prefix}{_tag_seq['n']}"


def create_rodeo_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Rodeo",
        "city": "Test City",
        "entries_close_at": TEST_DEFAULTS["ENTRIES_CLOSE_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_rodeo_event_payload(rodeo_id, **overrides) -> dict:
    defaults = {
        "rodeo_id": rodeo_id,
        "event_code": "BULL_RIDING",
        "go_rounds": 1,
        "entry_fee_cents": TEST_DEFAULTS["ENTRY_FEE_CENTS"],
        "added_money_cents": TEST_DEFAULTS["ADDED_MONEY_CENTS"],
        "per_performance_slots": 10,
        "payout_places": 1,
    }
    defaults.update(overrides)
    return defaults


def create_performance_payload(rodeo_id, **overrides) -> dict:
    defaults = {
        "rodeo_id": rodeo_id,
        "label": "Friday Night",
        "arena": "Main",
        "starts_at": TEST_DEFAULTS["PERF_STARTS_AT"],
        "ends_at": TEST_DEFAULTS["PERF_ENDS_AT"],
        "arena_capacity": TEST_DEFAULTS["ARENA_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_contestant_payload(**overrides) -> dict:
    defaults = {
        "card_number": _next_card(),
        "full_name": "Test Rider",
    }
    defaults.update(overrides)
    return defaults


def create_stock_contract_payload(rodeo_id, **overrides) -> dict:
    defaults = {
        "rodeo_id": rodeo_id,
        "contractor_name": "Bar None Ranch",
        "day_rate_cents": TEST_DEFAULTS["DAY_RATE_CENTS"],
        "per_out_fee_cents": TEST_DEFAULTS["PER_OUT_FEE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_stock_animal_payload(contract_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "tag_number": _next_tag(),
        "event_code": "BULL_RIDING",
    }
    defaults.update(overrides)
    return defaults


def create_judge_payload(**overrides) -> dict:
    defaults = {
        "card_number": _next_card("J"),
        "full_name": "Test Judge",
        "certification": "PRCA_CARD",
    }
    defaults.update(overrides)
    return defaults


def create_judge_assignment_payload(judge_id, performance_id, **overrides) -> dict:
    defaults = {
        "judge_id": judge_id,
        "performance_id": performance_id,
        "position": "ARENA_1",
    }
    defaults.update(overrides)
    return defaults


def create_entry_payload(contestant_id, rodeo_event_id, **overrides) -> dict:
    defaults = {
        "contestant_id": contestant_id,
        "rodeo_event_id": rodeo_event_id,
    }
    defaults.update(overrides)
    return defaults


def create_run_result_payload(draw_assignment_id, **overrides) -> dict:
    defaults = {
        "draw_assignment_id": draw_assignment_id,
        "qualified_flag": True,
    }
    defaults.update(overrides)
    return defaults


def create_vet_report_payload(**overrides) -> dict:
    defaults = {
        "subject_type": "ANIMAL",
        "findings": "Routine findings",
        "disposition": "CLEARED",
        "veterinarian_name": "Dr. Ellis",
    }
    defaults.update(overrides)
    return defaults


def create_ticket_order_payload(performance_id, **overrides) -> dict:
    defaults = {
        "performance_id": performance_id,
        "section": "GA",
        "quantity": 1,
        "unit_price_cents": TEST_DEFAULTS["TICKET_UNIT_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults
