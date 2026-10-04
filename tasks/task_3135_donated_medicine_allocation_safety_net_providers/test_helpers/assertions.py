"""Entity assertions and domain invariant checkers.

Each ``assert_<entity>`` verifies the shape a faithful implementation must
return: a server-minted UUID id, ISO-8601 timestamps, the integer version, and
the entity's own declared fields. Invariant checkers encode the PRD's
cross-field rules (quantity conservation, temperature-band coherence).
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def assert_common_fields(data: Dict[str, Any]) -> None:
    """Every resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an int >= 1, got {data.get('version')!r}"
    )


def assert_manufacturer_donor(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("legal_name"), str) and data["legal_name"]
    assert isinstance(data.get("country_code"), str) and len(data["country_code"]) == 2
    assert isinstance(data.get("tax_id"), str) and data["tax_id"]
    assert data.get("status") in ("ACTIVE", "SUSPENDED", "DEACTIVATED")


def assert_product_lot(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("donor_id"), str) and data["donor_id"]
    assert isinstance(data.get("ndc_code"), str) and data["ndc_code"]
    assert data.get("product_class") in ("STANDARD", "COLD_CHAIN", "CONTROLLED", "RESTRICTED_USE")
    assert data.get("lot_posture") in ("RELEASABLE", "QUARANTINED", "RECALLED", "EXPIRED")
    for counter in (
        "quantity_received",
        "quantity_available",
        "quantity_quarantined",
        "quantity_committed",
        "quantity_shipped",
        "quantity_expired",
    ):
        assert isinstance(data.get(counter), int) and data[counter] >= 0, (
            f"{counter} must be a non-negative int, got {data.get(counter)!r}"
        )
    assert isinstance(data.get("requires_cold_chain"), bool)
    assert isinstance(data.get("is_controlled"), bool)
    # Derived flags track product_class exactly.
    assert data["requires_cold_chain"] == (data["product_class"] == "COLD_CHAIN")
    assert data["is_controlled"] == (data["product_class"] == "CONTROLLED")


def assert_lot_quantity_conservation(data: Dict[str, Any]) -> None:
    """quantity_received reconciles with the four buckets plus available."""
    total = (
        data["quantity_quarantined"]
        + data["quantity_committed"]
        + data["quantity_shipped"]
        + data["quantity_expired"]
        + data["quantity_available"]
    )
    assert total == data["quantity_received"], (
        f"quantity ledger must reconcile: received {data['quantity_received']} != "
        f"sum of buckets {total}"
    )
    assert data["quantity_available"] >= 0


def assert_recipient_site(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("organization_name"), str) and data["organization_name"]
    assert data.get("site_type") in (
        "FREE_CLINIC",
        "FQHC",
        "RURAL_HEALTH_CENTER",
        "DISASTER_RESPONDER",
        "HOSPITAL_CHARITY",
    )
    assert isinstance(data.get("country_code"), str) and len(data["country_code"]) == 2
    assert isinstance(data.get("is_international"), bool)
    assert data["is_international"] == (data["country_code"] != "US")
    assert data.get("qualification_status") in (
        "PENDING_REVIEW",
        "QUALIFIED",
        "SUSPENDED",
        "REVOKED",
    )
    assert isinstance(data.get("active_license_count"), int) and data["active_license_count"] >= 0


def assert_license(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("site_id"), str) and data["site_id"]
    assert data.get("license_type") in (
        "PHARMACY",
        "MEDICAL_DIRECTOR",
        "DEA",
        "WHOLESALER",
        "IMPORT",
    )
    assert isinstance(data.get("issuing_authority"), str) and data["issuing_authority"]
    assert isinstance(data.get("license_number"), str) and data["license_number"]
    assert data.get("verification_status") in ("PENDING", "VERIFIED", "REJECTED", "EXPIRED")


def assert_allocation_request(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("site_id"), str) and data["site_id"]
    assert isinstance(data.get("quantity_requested"), int) and data["quantity_requested"] > 0
    assert isinstance(data.get("quantity_approved"), int) and data["quantity_approved"] >= 0
    assert data.get("status") in (
        "SUBMITTED",
        "UNDER_REVIEW",
        "APPROVED",
        "PARTIALLY_APPROVED",
        "REJECTED",
        "CANCELLED",
    )


def assert_allocation_decision(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("request_id"), str) and data["request_id"]
    assert isinstance(data.get("reviewer_user_id"), str) and data["reviewer_user_id"]
    assert data.get("status") in ("DRAFT", "FINALIZED", "SUPERSEDED", "VOID")


def assert_allocation_line(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("decision_id"), str) and data["decision_id"]
    assert isinstance(data.get("lot_id"), str) and data["lot_id"]
    assert isinstance(data.get("quantity"), int) and data["quantity"] > 0
    assert data.get("status") in (
        "RESERVED",
        "PICKED",
        "SHIPPED",
        "DELIVERED",
        "RELEASED",
        "FORFEITED",
    )


def assert_shipment(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("allocation_decision_id"), str) and data["allocation_decision_id"]
    assert isinstance(data.get("carrier_name"), str) and data["carrier_name"]
    assert isinstance(data.get("is_international"), bool)
    assert data.get("status") in (
        "PACKING",
        "AWAITING_CUSTOMS_DOCS",
        "READY_TO_DISPATCH",
        "DISPATCHED",
        "DELIVERED",
        "DELIVERY_FAILED",
        "CANCELLED",
    )


def assert_customs_declaration(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("shipment_id"), str) and data["shipment_id"]
    assert isinstance(data.get("hs_code"), str) and data["hs_code"]
    assert data.get("status") in ("DRAFT", "SUBMITTED", "CLEARED", "REJECTED")


def assert_emergency_event(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("event_name"), str) and data["event_name"]
    assert isinstance(data.get("severity"), int) and 1 <= data["severity"] <= 5
    assert isinstance(data.get("affected_country_codes"), list)
    assert data.get("status") in ("DECLARED", "ACTIVE", "STAND_DOWN", "CLOSED")


def assert_prepositioned_module(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("module_code"), str) and data["module_code"]
    assert data.get("intended_use") in (
        "PRIMARY_CARE",
        "TRAUMA",
        "CHOLERA",
        "MATERNAL",
        "COLD_CHAIN_VACCINE",
    )
    assert data.get("status") in (
        "AVAILABLE",
        "RESERVED",
        "DEPLOYED",
        "CONSUMED",
        "DECOMMISSIONED",
    )


def assert_valuation_snapshot(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("donor_id"), str) and data["donor_id"]
    assert isinstance(data.get("snapshot_period"), str) and len(data["snapshot_period"]) == 7
    assert data.get("method") in ("ACQUISITION_COST", "WHOLESALE_REFERENCE")
    assert isinstance(data.get("lot_count"), int) and data["lot_count"] >= 0
    assert isinstance(data.get("total_value_usd"), (int, float))


def assert_distribution_report(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("site_id"), str) and data["site_id"]
    assert isinstance(data.get("shipment_id"), str) and data["shipment_id"]
    assert isinstance(data.get("units_distributed"), int) and data["units_distributed"] >= 0
    assert isinstance(data.get("patients_reached"), int) and data["patients_reached"] >= 0
    assert isinstance(data.get("wastage_units"), int) and data["wastage_units"] >= 0
    assert data.get("status") in ("DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED")


def assert_money_two_dp(value: float) -> None:
    """Dollar figures are rounded half-up to two decimal places."""
    cents = round(value * 1000)
    assert cents % 10 == 0, f"expected a 2-decimal-place dollar figure, got {value!r}"
