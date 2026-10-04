"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "COMPANY_NAME": "Test Studio",
    "CONTACT_EMAIL": "contact@studio.example",
    "TITLE_NAME": "Test Game",
    "BASE_PRICE_USD_CENTS": 1000,
    "USER_EMAIL": "player@players.example",
    "CURRENCY": "USD",
    "REFUND_REASON": "changed my mind",
    "REVIEW_BODY": "solid experience",
    "ITEM_NAME": "Mod Pack",
    "ITEM_PRICE_CENTS": 500,
    "CREATOR_SHARE_BPS": 2500,
    "REQUESTED_QUANTITY": 10,
}


def create_developer_account_payload(**overrides) -> dict:
    defaults = {
        "company_name": DEFAULTS["COMPANY_NAME"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_title_payload(developer_account_id: str, **overrides) -> dict:
    defaults = {
        "developer_account_id": developer_account_id,
        "title_name": DEFAULTS["TITLE_NAME"],
        "base_price_usd_cents": DEFAULTS["BASE_PRICE_USD_CENTS"],
        "early_access": False,
    }
    defaults.update(overrides)
    return defaults


def create_user_account_payload(**overrides) -> dict:
    defaults = {"email": DEFAULTS["USER_EMAIL"]}
    defaults.update(overrides)
    return defaults


def create_purchase_payload(user_account_id: str, title_id: str, **overrides) -> dict:
    defaults = {
        "user_account_id": user_account_id,
        "title_id": title_id,
        "currency": DEFAULTS["CURRENCY"],
    }
    defaults.update(overrides)
    return defaults


def create_refund_request_payload(purchase_id: str, **overrides) -> dict:
    defaults = {
        "purchase_id": purchase_id,
        "reason": DEFAULTS["REFUND_REASON"],
    }
    defaults.update(overrides)
    return defaults


def create_review_payload(title_id: str, user_account_id: str, expected_title_version: int, **overrides) -> dict:
    defaults = {
        "title_id": title_id,
        "user_account_id": user_account_id,
        "is_positive": True,
        "body": DEFAULTS["REVIEW_BODY"],
        "expected_title_version": expected_title_version,
    }
    defaults.update(overrides)
    return defaults


def create_key_batch_payload(title_id: str, **overrides) -> dict:
    defaults = {
        "title_id": title_id,
        "requested_quantity": DEFAULTS["REQUESTED_QUANTITY"],
        "free_keys_in_batch": 0,
    }
    defaults.update(overrides)
    return defaults


def create_regional_price_payload(title_id: str, currency: str, price_cents: int, expected_title_version: int, **overrides) -> dict:
    defaults = {
        "title_id": title_id,
        "currency": currency,
        "price_cents": price_cents,
        "expected_title_version": expected_title_version,
    }
    defaults.update(overrides)
    return defaults


def create_workshop_item_payload(title_id: str, creator_account_id: str, **overrides) -> dict:
    defaults = {
        "title_id": title_id,
        "creator_account_id": creator_account_id,
        "item_name": DEFAULTS["ITEM_NAME"],
        "price_cents": DEFAULTS["ITEM_PRICE_CENTS"],
        "creator_share_bps": DEFAULTS["CREATOR_SHARE_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_workshop_sale_payload(workshop_item_id: str, buyer_account_id: str, **overrides) -> dict:
    defaults = {
        "workshop_item_id": workshop_item_id,
        "buyer_account_id": buyer_account_id,
    }
    defaults.update(overrides)
    return defaults
