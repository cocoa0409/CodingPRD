"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)


def _assert_common_fields(data: dict):
    """Every resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_money(data: dict, field: str):
    value = data[field]
    assert isinstance(value, int) and not isinstance(value, bool), \
        f"{field} must be an integer number of cents"
    assert value >= 0, f"{field} must not be negative"
    assert_cost_precision(value)


def assert_manufacturer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["manufacturer_name"], str) and data["manufacturer_name"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_drug(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["drug_name"], str) and data["drug_name"]
    assert isinstance(data["strength"], str) and data["strength"]
    assert data["dosage_form"] in ("Tablet", "Capsule", "Solution")
    assert isinstance(data["is_controlled"], bool)
    assert data["state"] in ("FORMULARY", "NON_FORMULARY", "DELISTED")
    assert data["sourcing_status"] in ("SOURCED", "UNDER_REVIEW", "UNSOURCED", "SUSPENDED")
    assert isinstance(data["retail_reference_price_cents"], int)
    assert isinstance(data["insured_reference_price_cents"], int)
    assert isinstance(data["demand_units_30d"], int)
    assert isinstance(data["supply_units"], int)


def assert_price_row(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["drug_id"])
    assert is_valid_uuid(data["manufacturer_id"])
    assert data["price_status"] in ("PROPOSED", "ACTIVE", "REVOKED")
    assert data["sourcing_status"] in ("SOURCED", "UNDER_REVIEW", "SUPPRESSED")
    assert data["reliability_tier"] in ("A", "B", "C")
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 1
    assert isinstance(data["available_units"], int) and data["available_units"] >= 0


def assert_pharmacy(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["pharmacy_name"], str) and data["pharmacy_name"]
    assert isinstance(data["domicile_state_code"], str) and len(data["domicile_state_code"]) == 2
    assert isinstance(data["shipping_enabled"], bool)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_license(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["pharmacy_id"])
    assert data["status"] in ("PENDING", "ACTIVE", "EXPIRED", "REVOKED", "SUPERSEDED")
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2


def assert_patient(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_prescriber(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["prescriber_name"], str) and data["prescriber_name"]
    assert isinstance(data["npi"], str) and data["npi"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_prescription(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["prescriber_id"])
    assert is_valid_uuid(data["drug_id"])
    assert data["status"] in ("DRAFT", "INTAKE_REVIEW", "ACTIVE", "REJECTED",
                              "DEPLETED", "TERMINATED")
    assert isinstance(data["total_refills_authorized"], int)
    assert isinstance(data["refills_consumed"], int)


def assert_intake_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["prescription_id"])
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "ACCEPTED", "REJECTED")
    assert isinstance(data["packaged_quantity"], int)
    assert isinstance(data["consumed_quantity"], int)


def assert_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["prescription_id"])
    assert is_valid_uuid(data["request_id"])
    assert is_valid_uuid(data["pharmacy_id"])
    assert data["status"] in ("CREATED", "PAID", "FULFILLING", "SHIPPED",
                              "DELIVERED", "CANCELED")
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["is_blended_cost"], bool)


def assert_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["prescription_id"])
    assert data["status"] in ("PENDING", "AUTHORIZED", "SHIPPED", "DENIED", "CANCELED")
    assert isinstance(data["claim_seq"], int)
    assert isinstance(data["reserved_quantity"], int)


def assert_shipment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert data["status"] in ("PENDING", "DISPATCHED", "IN_TRANSIT", "DELIVERED", "RETURNED")
    assert isinstance(data["shipment_seq"], int)


def assert_comparison(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert data["state"] in ("FRESH", "REFRESH_REQUIRED", "STALE")
    assert data["status"] in ("UNSUBSTANTIATED", "SUBSTANTIATED", "BLOCKED")
    assert isinstance(data["substantiated"], bool)


def assert_substantiation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert data["source_kind"] in ("RETAIL_SURVEY", "BENEFIT_INDEX", "MANUFACTURER_NOTICE")
    assert data["status"] in ("PENDING", "ENABLED", "DISABLED")


# ─── Domain invariants ────────────────────────────────

def assert_order_price_invariant(data: dict):
    """patient_price_cents must equal the exact sum of its four parts, and no
    component may be negative."""
    assert data["patient_price_cents"] == (
        data["acquisition_cost_cents"]
        + data["markup_cents"]
        + data["pharmacy_fee_cents"]
        + data["shipping_fee_cents"]
    ), "patient_price_cents must equal the exact sum of its parts"
    for field in ("acquisition_cost_cents", "markup_cents", "pharmacy_fee_cents",
                  "shipping_fee_cents", "patient_price_cents"):
        assert data[field] >= 0, f"{field} must not be negative"
        assert_cost_precision(data[field])


def assert_drug_supply_is_non_negative(data: dict):
    assert data["supply_units"] >= 0
    assert data["demand_units_30d"] >= 0


def assert_claim_denial(data: dict, expected_reason: str):
    assert data["status"] == "DENIED"
    assert data["denial_reason_code"] == expected_reason
    assert data["reserved_quantity"] == 0
    assert data["denied_at"] is not None