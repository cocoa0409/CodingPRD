"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}{next(_counter)}"


# --- users ---------------------------------------------------------------------

def create_user_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "username": f"user_{n}",
        "email": f"user_{n}@x.com",
        "date_of_birth": "1990-01-01",
    }
    defaults.update(overrides)
    return defaults


# --- identity & tax --------------------------------------------------------------

def create_identity_verification_payload(**overrides) -> dict:
    defaults = {
        "document_type": "PASSPORT",
        "document_country": "US",
        "expiry_date": "2030-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_tax_document_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "form_type": "W9",
        "tin_last4": f"{n % 10000:04d}",
        "legal_name": f"Legal Name {n}",
        "country_of_residence": "US",
    }
    defaults.update(overrides)
    return defaults


# --- parental controls -------------------------------------------------------------

def create_parental_controls_payload(child_user_id, expected_user_version, **overrides) -> dict:
    defaults = {
        "child_user_id": child_user_id,
        "pin_hash": "hash1234",
        "expected_user_version": expected_user_version,
    }
    defaults.update(overrides)
    return defaults


# --- experiences --------------------------------------------------------------------

def create_experience_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "title": f"Experience {n}",
        "description": f"Description for experience {n}",
    }
    defaults.update(overrides)
    return defaults


# --- marketplace items -----------------------------------------------------------------

def create_marketplace_item_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "title": f"Item {n}",
        "item_kind": "HAT",
        "price_robux": 100,
    }
    defaults.update(overrides)
    return defaults


def create_limited_item_payload(**overrides) -> dict:
    # Ensure a LIMITED_* kind so that total_supply / royalty_pct defaults are legal
    # under PRD §3.5 ("For non-limited kinds, `total_supply` must be null and
    # `royalty_pct` must be 0"). Callers may still override item_kind to LIMITED_GEAR.
    overrides.setdefault("item_kind", "LIMITED_HAT")
    defaults = create_marketplace_item_payload(**overrides)
    defaults.setdefault("total_supply", 5)
    defaults.setdefault("royalty_pct", 10)
    return defaults


# --- resale listings ----------------------------------------------------------------------

def create_resale_listing_payload(item_id, ask_price_robux, expected_item_version, **overrides) -> dict:
    defaults = {
        "item_id": item_id,
        "ask_price_robux": ask_price_robux,
        "expected_item_version": expected_item_version,
    }
    defaults.update(overrides)
    return defaults


# --- orders ---------------------------------------------------------------------------------

def create_currency_purchase_order_payload(**overrides) -> dict:
    defaults = {
        "fiat_amount_cents": 1000,
        "payment_method_token": "tok_x",
        "idempotency_key": _uniq("cur-"),
    }
    defaults.update(overrides)
    return defaults


def create_purchase_order_payload(item_type, item_id, price_robux, **overrides) -> dict:
    defaults = {
        "item_type": item_type,
        "item_id": item_id,
        "price_robux": price_robux,
        "idempotency_key": _uniq("po-"),
    }
    defaults.update(overrides)
    return defaults


# --- devex --------------------------------------------------------------------------------------

def create_devex_request_payload(requested_robux, expected_user_version, **overrides) -> dict:
    defaults = {
        "requested_robux": requested_robux,
        "expected_user_version": expected_user_version,
    }
    defaults.update(overrides)
    return defaults


# --- moderation / appeals -------------------------------------------------------------------------

def create_moderation_submission_payload(subject_type, subject_id, **overrides) -> dict:
    defaults = {"subject_type": subject_type, "subject_id": subject_id}
    defaults.update(overrides)
    return defaults


def create_moderation_appeal_payload(submission_id, **overrides) -> dict:
    defaults = {
        "submission_id": submission_id,
        "reason": "I believe this moderation decision was made in error.",
    }
    defaults.update(overrides)
    return defaults


# --- chat / reports ----------------------------------------------------------------------------------

def create_chat_message_payload(**overrides) -> dict:
    defaults = {"body_raw": f"hello world {next(_counter)}"}
    defaults.update(overrides)
    return defaults


def create_report_payload(**overrides) -> dict:
    defaults = {"reason_code": "HARASSMENT"}
    defaults.update(overrides)
    return defaults


# --- account termination --------------------------------------------------------------------------------

def create_account_termination_payload(user_id, **overrides) -> dict:
    defaults = {
        "user_id": user_id,
        "reason_code": "FRAUD",
        "earnings_disposition": "FORFEIT_TO_PLATFORM",
    }
    defaults.update(overrides)
    return defaults


# --- engagement ---------------------------------------------------------------------------------------------

def create_engagement_snapshot_payload(snapshot_date, minutes_engaged, **overrides) -> dict:
    defaults = {"snapshot_date": snapshot_date, "minutes_engaged": minutes_engaged}
    defaults.update(overrides)
    return defaults
