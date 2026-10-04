"""Payload factories — one per resource, input fields only."""
import uuid

from .constants import TEST_DEFAULTS


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


def production_payload(**overrides) -> dict:
    """Payload for registering a partnership.

    ``exchange_allowed`` is genuinely optional: the producer states it explicitly
    if it is to be anything other than its default of false.
    """
    payload = {
        "title": TEST_DEFAULTS["PRODUCTION_TITLE"],
        "producer_org": TEST_DEFAULTS["PRODUCER_ORG"],
        "refund_window_hours": TEST_DEFAULTS["REFUND_WINDOW_HOURS"],
        "exchange_fee_cents": TEST_DEFAULTS["EXCHANGE_FEE_CENTS"],
    }
    payload.update(overrides)
    return payload


def market_payload(**overrides) -> dict:
    """Payload for declaring a market.

    ``desk_code`` and ``daily_capacity`` accompany the declaration when the
    handoff model is not MOBILE_PUSH; a MOBILE_PUSH market ignores both.
    """
    payload = {
        "market_code": "NYC",
        "city": TEST_DEFAULTS["CITY"],
        "handoff_model": "MOBILE_PUSH",
    }
    payload.update(overrides)
    return payload


def performance_payload(production_id, **overrides) -> dict:
    payload = {
        "production_id": production_id,
        "market_code": TEST_DEFAULTS["MARKET_CODE"],
        "venue_name": TEST_DEFAULTS["VENUE_NAME"],
        "starts_at": "2026-10-05T19:00:00Z",
        "face_value_cents": TEST_DEFAULTS["FACE_VALUE_CENTS"],
        "total_seat_capacity": TEST_DEFAULTS["TOTAL_SEAT_CAPACITY"],
    }
    payload.update(overrides)
    return payload


def allocation_payload(**overrides) -> dict:
    """Payload for granting discounted inventory.

    ``claim_window_minutes``, ``winner_basis_points`` and ``waitlist_multiplier``
    are the three optional inputs that may accompany the grant.
    """
    payload = {
        "ticket_type": "RUSH",
        "daily_quantity": TEST_DEFAULTS["DAILY_QUANTITY"],
        "discount_pct": TEST_DEFAULTS["DISCOUNT_PCT"],
        "release_time_local": TEST_DEFAULTS["RELEASE_TIME_LOCAL"],
        "refundable": True,
        "per_order_limit": TEST_DEFAULTS["PER_ORDER_LIMIT"],
    }
    payload.update(overrides)
    return payload


def patron_payload(**overrides) -> dict:
    payload = {
        "email": f"patron_{_suffix()}@example.com",
        "display_name": "Test Patron",
        "market_code": TEST_DEFAULTS["MARKET_CODE"],
    }
    payload.update(overrides)
    return payload


def draw_entry_payload(allocation_id, **overrides) -> dict:
    payload = {
        "allocation_id": allocation_id,
        "declaration_text": "I would like to attend",
    }
    payload.update(overrides)
    return payload


def seat_hold_payload(allocation_id, seat_label, **overrides) -> dict:
    """Payload for placing a hold.

    An ALLOCATION hold carries no ``origin_ref`` because its origin is the
    platform itself; the other kinds carry the external reference.
    """
    payload = {
        "allocation_id": allocation_id,
        "seat_label": seat_label,
        "hold_kind": "ALLOCATION",
    }
    payload.update(overrides)
    return payload


def purchase_payload(performance_id, allocation_id, **overrides) -> dict:
    payload = {
        "performance_id": performance_id,
        "allocation_id": allocation_id,
        "quantity": 1,
        "idempotency_key": f"idem-{_suffix()}",
    }
    payload.update(overrides)
    return payload


def handoff_payload(purchase_id, desk_code, redemption_code, **overrides) -> dict:
    payload = {
        "purchase_id": purchase_id,
        "desk_code": desk_code,
        "redemption_code": redemption_code,
        "idempotency_key": f"handoff-{_suffix()}",
    }
    payload.update(overrides)
    return payload


def refund_request_payload(**overrides) -> dict:
    payload = {"reason_code": "PATRON_REQUEST"}
    payload.update(overrides)
    return payload


def exchange_request_payload(target_allocation_id, original_amount_cents,
                             **overrides) -> dict:
    payload = {
        "target_allocation_id": target_allocation_id,
        "original_amount_cents": original_amount_cents,
    }
    payload.update(overrides)
    return payload


def reconciliation_payload(seat_count_claimed, seat_labels_claimed, **overrides) -> dict:
    payload = {
        "seat_count_claimed": seat_count_claimed,
        "seat_labels_claimed": seat_labels_claimed,
    }
    payload.update(overrides)
    return payload