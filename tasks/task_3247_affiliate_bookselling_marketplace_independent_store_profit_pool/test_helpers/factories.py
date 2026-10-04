"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import (
    DEFAULT_PARTNER_COMMISSION,
    DEFAULT_PUBLISHER_DISCOUNT,
    DEFAULT_RETURN_CREDIT_PCT,
    DEFAULT_RETURN_WINDOW_DAYS,
    DEFAULT_STORE_COMMISSION,
)

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def create_publisher_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "name": f"Test Publisher {n}",
        "discount_pct": DEFAULT_PUBLISHER_DISCOUNT,
        "returns_allowed": True,
        "return_window_days": DEFAULT_RETURN_WINDOW_DAYS,
        "return_credit_pct": DEFAULT_RETURN_CREDIT_PCT,
    }
    defaults.update(overrides)
    return defaults


def create_book_payload(publisher_id, **overrides) -> dict:
    n = _n()
    defaults = {
        "publisher_id": publisher_id,
        "isbn": f"978{n:010d}"[-13:],
        "title": f"Test Book {n}",
        "format": "PRINT",
        "list_price_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_store_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "shop_name": f"Test Books {n}",
        "slug": f"test-books-{n}",
        "commission_pct": DEFAULT_STORE_COMMISSION,
    }
    defaults.update(overrides)
    return defaults


def create_partner_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "display_name": f"Test Partner {n}",
        "partner_kind": "AUTHOR",
        "commission_pct": DEFAULT_PARTNER_COMMISSION,
    }
    defaults.update(overrides)
    return defaults


def create_list_payload(owner_store_id, **overrides) -> dict:
    n = _n()
    defaults = {
        "owner_store_id": owner_store_id,
        "title": f"Test List {n}",
        "items": [],
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(customer_id, book_id=None, lines=None, **overrides) -> dict:
    if lines is None:
        lines = [{"book_id": book_id, "quantity": 1}]
    defaults = {
        "customer_id": customer_id,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_return_payload(**overrides) -> dict:
    defaults = {
        "line_index": 0,
        "quantity": 1,
        "reason_code": "DAMAGED",
    }
    defaults.update(overrides)
    return defaults


def create_pool_distribution_payload(**overrides) -> dict:
    defaults = {
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-09-01T00:00:00Z",
        "pool_cents": 10000,
        "share_mode": "EQUAL_SPLIT",
    }
    defaults.update(overrides)
    return defaults


def create_ticket_payload(order_id, customer_id, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "opened_by_customer_id": customer_id,
        "issue_kind": "BILLING",
    }
    defaults.update(overrides)
    return defaults


def create_promotion_payload(book_isbn, **overrides) -> dict:
    defaults = {
        "book_isbn": book_isbn,
        "discount_pct": 0.10,
        "window_start": "2026-09-01T00:00:00Z",
        "window_end": "2026-09-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
