"""Payload factories — one per resource, declared input fields only (PRD §3, §4)."""
import itertools

_SEQ = itertools.count(1)


def _next() -> int:
    return next(_SEQ)


def create_store_payload(**overrides) -> dict:
    payload = {
        "name": "Austin Card House",
        "region_code": "US-SOUTH",
        "daily_event_capacity": 8,
        "event_space_capacity": 8,
    }
    payload.update(overrides)
    return payload


def create_set_release_payload(**overrides) -> dict:
    payload = {
        "set_code": f"SET-{_next()}",
        "prerelease_start_date": "2026-09-11T00:00:00Z",
        "prerelease_end_date": "2026-09-13T23:59:59Z",
        "street_date": "2026-09-18T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_format_payload(**overrides) -> dict:
    payload = {
        "name": "Standard",
        "format_code": "STD",
        "rotation_policy": "FIXED",
    }
    payload.update(overrides)
    return payload


def create_event_application_payload(store_id, set_release_id, format_id, **overrides) -> dict:
    payload = {
        "store_id": store_id,
        "set_release_id": set_release_id,
        "format_id": format_id,
        "format_code": "STD",
        "tier": "LOCAL",
        "scheduled_date": "2026-09-26T18:00:00Z",
        "expected_headcount": 12,
    }
    payload.update(overrides)
    return payload


def create_prize_distribution_payload(prize_allocation_id, **overrides) -> dict:
    payload = {
        "prize_allocation_id": prize_allocation_id,
        "recipient_ref": f"PLAYER-{_next()}",
        "quantity": 10,
    }
    payload.update(overrides)
    return payload


def create_prize_report_payload(prize_allocation_id, **overrides) -> dict:
    payload = {
        "prize_allocation_id": prize_allocation_id,
        "unclaimed_tp": 0,
        "reported_headcount": 30,
    }
    payload.update(overrides)
    return payload


def create_code_redemption_payload(event_application_id, **overrides) -> dict:
    payload = {
        "redemption_code": f"CODE-{_next()}",
        "code_kind": "DIGITAL",
        "event_application_id": event_application_id,
    }
    payload.update(overrides)
    return payload


def create_redeem_payload(redemption_code, **overrides) -> dict:
    payload = {
        "redemption_code": redemption_code,
        "code_kind": "DIGITAL",
        "action": "REDEEM",
    }
    payload.update(overrides)
    return payload


def create_enforcement_case_payload(event_application_id, **overrides) -> dict:
    payload = {
        "event_application_id": event_application_id,
        "player_ref": f"PLAYER-{_next()}",
        "judge_ref": "JUDGE-1",
        "offense_class": "MINOR",
        "rules_enforcement_level": "REGULAR",
    }
    payload.update(overrides)
    return payload


def create_product_configuration_payload(set_release_id, **overrides) -> dict:
    payload = {
        "set_release_id": set_release_id,
        "configuration_kind": "COLLECTOR_BOOSTER",
        "pack_count": 12,
        "print_run_units": 50,
    }
    payload.update(overrides)
    return payload


def create_allocation_order_payload(product_configuration_id, **overrides) -> dict:
    payload = {
        "distributor_name": "Cascade Distribution",
        "product_configuration_id": product_configuration_id,
        "quantity": 10,
    }
    payload.update(overrides)
    return payload


def create_judge_payload(**overrides) -> dict:
    payload = {
        "judge_ref": f"JUDGE-{_next()}",
        "name": "A. Referee",
        "level": "LEVEL_2",
    }
    payload.update(overrides)
    return payload


def create_reprint_plan_payload(set_release_id, format_id, **overrides) -> dict:
    payload = {
        "card_name": "Accessible Card",
        "set_release_id": set_release_id,
        "format_id": format_id,
        "secondary_market_index": 10,
        "first_print_index": 9,
    }
    payload.update(overrides)
    return payload


def approve_payload(expected_store_version=None, **overrides) -> dict:
    """Transition body for action=APPROVE on an event application (PRD §3.3)."""
    payload = {
        "action": "APPROVE",
        "pool_mode": "BUNDLED",
        "pool_variant": "BUNDLED",
    }
    if expected_store_version is not None:
        payload["expected_store_version"] = expected_store_version
    payload.update(overrides)
    return payload


def transition_payload(action, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload