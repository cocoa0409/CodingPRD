"""Payload factories, one per write operation. Input fields only.

Every monetary value is an integer count of cents, never a string and never a
float, exactly as the PRD requires.
"""

import itertools

from .constants import TEST_DEFAULTS

_seq = itertools.count(1)


def next_seq() -> int:
    """Monotonic counter for unique skus, handles and email addresses."""
    return next(_seq)


def clock_payload(current_utc: str) -> dict:
    return {"current_utc": current_utc}


def create_host_payload(**overrides) -> dict:
    n = next_seq()
    defaults = {
        "full_name": TEST_DEFAULTS["HOST_FULL_NAME"],
        "handle": f"host-{n}",
        "commission_pct": TEST_DEFAULTS["HOST_COMMISSION_PCT"],
    }
    defaults.update(overrides)
    return defaults


def certify_host_payload(**overrides) -> dict:
    defaults = {"certified_until": TEST_DEFAULTS["CERT_UNTIL"]}
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    n = next_seq()
    defaults = {
        "sku": f"SKU-{n:04d}",
        "title": TEST_DEFAULTS["PRODUCT_TITLE"],
        "base_price_cents": TEST_DEFAULTS["PRODUCT_BASE_PRICE_CENTS"],
        "unit_cost_cents": TEST_DEFAULTS["PRODUCT_UNIT_COST_CENTS"],
        "on_hand_qty": TEST_DEFAULTS["PRODUCT_ON_HAND_QTY"],
        "claim_text": "Machine washable mulberry silk",
    }
    defaults.update(overrides)
    return defaults


def inventory_adjustment_payload(**overrides) -> dict:
    defaults = {"reason": "CYCLE_COUNT"}
    defaults.update(overrides)
    return defaults


def claim_substantiation_payload(**overrides) -> dict:
    defaults = {"decision": "SUBSTANTIATED", "evidence_ref": "LAB-88"}
    defaults.update(overrides)
    return defaults


def create_viewer_payload(**overrides) -> dict:
    n = next_seq()
    defaults = {
        "display_name": f"Viewer {n}",
        "email": f"viewer.{n}@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_show_payload(**overrides) -> dict:
    defaults = {
        "title": TEST_DEFAULTS["SHOW_TITLE"],
        "scheduled_start_at": TEST_DEFAULTS["SHOW_START"],
        "scheduled_end_at": TEST_DEFAULTS["SHOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_stream_channel_payload(show_id: str, **overrides) -> dict:
    defaults = {
        "show_id": show_id,
        "platform": "FLAGSHIP_APP",
        "target_latency_ms": 1500,
    }
    defaults.update(overrides)
    return defaults


def health_report_payload(**overrides) -> dict:
    defaults = {"latency_ms": 1500, "dropped_frame_pct": 0.0}
    defaults.update(overrides)
    return defaults


def create_host_booking_payload(show_id: str, host_id: str, **overrides) -> dict:
    defaults = {
        "show_id": show_id,
        "host_id": host_id,
        "role": "PRIMARY",
        "call_time_at": "2026-08-10T17:00:00Z",
        "release_time_at": "2026-08-10T20:30:00Z",
        "fee_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def cancel_booking_payload(**overrides) -> dict:
    defaults = {"cancel_reason": "HOST_ILLNESS"}
    defaults.update(overrides)
    return defaults


def create_lineup_slot_payload(show_id: str, product_id: str, **overrides) -> dict:
    defaults = {
        "show_id": show_id,
        "product_id": product_id,
        "slot_sequence": 1,
        "planned_start_at": "2026-08-10T18:05:00Z",
        "planned_end_at": "2026-08-10T18:35:00Z",
        "planned_qty": 20,
    }
    defaults.update(overrides)
    return defaults


def replay_marker_payload(**overrides) -> dict:
    defaults = {
        "marker_offset_sec": 600,
        "product_link_url": "https://shop.example.com/robe",
    }
    defaults.update(overrides)
    return defaults


def replay_conversion_payload(viewer_id: str, **overrides) -> dict:
    defaults = {
        "viewer_id": viewer_id,
        "net_revenue_cents": 4000,
        "occurred_at": "2026-08-10T23:30:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_flash_offer_payload(lineup_slot_id: str, expected_lineup_slot_version: int, **overrides) -> dict:
    defaults = {
        "lineup_slot_id": lineup_slot_id,
        "offer_price_cents": TEST_DEFAULTS["OFFER_PRICE_CENTS"],
        "window_start_at": TEST_DEFAULTS["OFFER_WINDOW_START"],
        "window_end_at": TEST_DEFAULTS["OFFER_WINDOW_END"],
        "max_qty": TEST_DEFAULTS["OFFER_MAX_QTY"],
        "expected_lineup_slot_version": expected_lineup_slot_version,
    }
    defaults.update(overrides)
    return defaults


def create_disclosure_record_payload(show_id: str, host_booking_id: str, **overrides) -> dict:
    defaults = {
        "show_id": show_id,
        "host_booking_id": host_booking_id,
        "disclosure_type": "PAID_ENDORSEMENT",
        "required_script_code": TEST_DEFAULTS["SCRIPT_CODE"],
    }
    defaults.update(overrides)
    return defaults


def acknowledge_payload(**overrides) -> dict:
    defaults = {"script_code_spoken": TEST_DEFAULTS["SCRIPT_CODE"]}
    defaults.update(overrides)
    return defaults


def create_cart_payload(show_id: str, **overrides) -> dict:
    defaults = {"show_id": show_id}
    defaults.update(overrides)
    return defaults


def add_cart_item_payload(flash_offer_id: str, qty: int = 1, **overrides) -> dict:
    defaults = {"flash_offer_id": flash_offer_id, "qty": qty}
    defaults.update(overrides)
    return defaults


def checkout_payload(expected_cart_version: int, **overrides) -> dict:
    defaults = {"expected_cart_version": expected_cart_version}
    defaults.update(overrides)
    return defaults


def cancel_order_payload(**overrides) -> dict:
    defaults = {"cancel_reason": "VIEWER_CHANGED_MIND"}
    defaults.update(overrides)
    return defaults


def create_chat_payload(show_id: str, **overrides) -> dict:
    defaults = {"show_id": show_id, "kind": "CHAT", "body": "Love this robe"}
    defaults.update(overrides)
    return defaults


def create_question_payload(show_id: str, **overrides) -> dict:
    defaults = {"show_id": show_id, "kind": "QUESTION", "body": "Does the silk shrink?"}
    defaults.update(overrides)
    return defaults


def create_poll_payload(show_id: str, **overrides) -> dict:
    defaults = {
        "show_id": show_id,
        "kind": "POLL",
        "body": "Which colour next?",
        "options": ["Ivory", "Indigo"],
    }
    defaults.update(overrides)
    return defaults


def moderate_payload(action: str = "APPROVE", **overrides) -> dict:
    defaults = {"action": action}
    defaults.update(overrides)
    return defaults


def host_action_payload(action: str, **overrides) -> dict:
    defaults = {"action": action}
    defaults.update(overrides)
    return defaults


def vote_payload(option_index: int = 0, **overrides) -> dict:
    defaults = {"option_index": option_index}
    defaults.update(overrides)
    return defaults


def signoff_payload(**overrides) -> dict:
    defaults = {"attestation_note": "Reviewed on-air claims and disclosures."}
    defaults.update(overrides)
    return defaults
