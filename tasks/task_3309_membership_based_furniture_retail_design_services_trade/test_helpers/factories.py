"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "GALLERY_NAME": "Test Gallery",
    "GALLERY_REGION": "WEST",
    "GALLERY_ROUTE_CAPACITY": 480,
    "PRODUCT_NAME": "Test Product",
    "PRODUCT_PRICE": 10000,
    "MEMBER_NAME": "Test Member",
    "PAYMENT_TOKEN": "tok",
    "BUSINESS_NAME": "Test Design Co",
    "CREDENTIAL_DOC": "doc-1",
    "LICENSE_NUMBER": "LIC-1",
    "BOOK_TITLE": "Test Book",
}


def create_member_payload(**overrides) -> dict:
    defaults = {
        "email": "member@example.com",
        "full_name": DEFAULTS["MEMBER_NAME"],
        "auto_renew": False,
        "payment_token": DEFAULTS["PAYMENT_TOKEN"],
    }
    defaults.update(overrides)
    return defaults


def create_trade_account_payload(**overrides) -> dict:
    defaults = {
        "email": "trade@example.com",
        "business_name": DEFAULTS["BUSINESS_NAME"],
        "credential_document_id": DEFAULTS["CREDENTIAL_DOC"],
        "license_number": DEFAULTS["LICENSE_NUMBER"],
    }
    defaults.update(overrides)
    return defaults


def create_gallery_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["GALLERY_NAME"],
        "region": DEFAULTS["GALLERY_REGION"],
        "daily_route_minutes_capacity": DEFAULTS["GALLERY_ROUTE_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": "SKU-0001",
        "name": DEFAULTS["PRODUCT_NAME"],
        "list_price_cents": DEFAULTS["PRODUCT_PRICE"],
        "line_kind": "STOCK",
    }
    defaults.update(overrides)
    return defaults


def create_source_book_payload(**overrides) -> dict:
    defaults = {
        "title": DEFAULTS["BOOK_TITLE"],
        "product_ids": [],
        "print_ready_date": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(gallery_id, **overrides) -> dict:
    defaults = {"gallery_id": gallery_id}
    defaults.update(overrides)
    return defaults


def add_order_line_payload(product_id, **overrides) -> dict:
    defaults = {"product_id": product_id, "qty": 1}
    defaults.update(overrides)
    return defaults


def create_production_slot_payload(gallery_id, **overrides) -> dict:
    defaults = {
        "gallery_id": gallery_id,
        "starts_at": "2026-09-10T09:00:00Z",
        "ends_at": "2026-09-10T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_design_consultation_payload(member_id, order_id, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "order_id": order_id,
        "scheduled_at": "2026-09-03T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_delivery_appointment_payload(order_id, gallery_id, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "gallery_id": gallery_id,
        "delivery_date": "2026-09-05",
        "duration_minutes": 60,
        "room_placement": True,
        "assembly_required": True,
    }
    defaults.update(overrides)
    return defaults


def create_return_payload(order_id, order_line_ids, **overrides) -> dict:
    defaults = {"order_id": order_id, "order_line_ids": order_line_ids}
    defaults.update(overrides)
    return defaults
