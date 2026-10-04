"""Payload factories — one per entity, input fields only (PRD Section 4)."""

DEFAULTS = {
    "STORE_CODE": "PHX-01",
    "STORE_NAME": "Phoenix",
    "REGION": "WEST",
    "CUSTOMER_NAME": "Customer One",
    "CUSTOMER_EMAIL": "c1@x.com",
    "CREDIT_SCORE": 720,
    "ANNUAL_INCOME_CENTS": 9000000,
    "ASSOCIATE_NAME": "Associate One",
    "VIN": "VAAAAAAAAAAAAAAAA",
    "MAKE": "Honda",
    "MODEL": "Accord",
    "MODEL_YEAR": 2022,
    "ODOMETER": 30000,
    "BOOK_VALUE_CENTS": 2000000,
}


def create_store_payload(**overrides) -> dict:
    defaults = {
        "store_code": DEFAULTS["STORE_CODE"],
        "display_name": DEFAULTS["STORE_NAME"],
        "region": DEFAULTS["REGION"],
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["CUSTOMER_NAME"],
        "email": DEFAULTS["CUSTOMER_EMAIL"],
        "credit_score": DEFAULTS["CREDIT_SCORE"],
        "stated_annual_income_cents": DEFAULTS["ANNUAL_INCOME_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_associate_payload(store_id, role_kind="MANAGER", **overrides) -> dict:
    defaults = {
        "display_name": DEFAULTS["ASSOCIATE_NAME"],
        "store_id": store_id,
        "role_kind": role_kind,
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(current_store_id, **overrides) -> dict:
    defaults = {
        "vin": DEFAULTS["VIN"],
        "make": DEFAULTS["MAKE"],
        "model": DEFAULTS["MODEL"],
        "model_year": DEFAULTS["MODEL_YEAR"],
        "odometer_miles": DEFAULTS["ODOMETER"],
        "book_value_cents": DEFAULTS["BOOK_VALUE_CENTS"],
        "current_store_id": current_store_id,
    }
    defaults.update(overrides)
    return defaults


def create_appraisal_payload(vehicle_id, customer_id, appraiser_id, **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "customer_id": customer_id,
        "appraiser_id": appraiser_id,
    }
    defaults.update(overrides)
    return defaults


def open_inspection_payload(inspector_id, **overrides) -> dict:
    defaults = {"inspector_id": inspector_id}
    defaults.update(overrides)
    return defaults


def add_line_item_payload(**overrides) -> dict:
    defaults = {"category": "MECHANICAL", "cost_cents": 100000}
    defaults.update(overrides)
    return defaults


def create_transfer_request_payload(vehicle_id, customer_id, to_store_id,
                                    expected_vehicle_version, **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "customer_id": customer_id,
        "to_store_id": to_store_id,
        "expected_vehicle_version": expected_vehicle_version,
    }
    defaults.update(overrides)
    return defaults


def create_sale_payload(vehicle_id, customer_id, associate_id, **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "customer_id": customer_id,
        "associate_id": associate_id,
    }
    defaults.update(overrides)
    return defaults


def accept_financing_payload(lender_code, **overrides) -> dict:
    defaults = {"lender_code": lender_code}
    defaults.update(overrides)
    return defaults


def create_return_payload(sale_id, **overrides) -> dict:
    defaults = {
        "sale_id": sale_id,
        "reason_code": "CHANGED_MIND",
        "odometer_at_return": 30100,
    }
    defaults.update(overrides)
    return defaults


def create_auction_lot_payload(vehicle_id, **overrides) -> dict:
    defaults = {"vehicle_id": vehicle_id}
    defaults.update(overrides)
    return defaults


def close_auction_lot_payload(hammer_price_cents, **overrides) -> dict:
    defaults = {"hammer_price_cents": hammer_price_cents}
    defaults.update(overrides)
    return defaults
