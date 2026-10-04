"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    if with_version:
        assert is_iso8601_timestamp(
            data.get("updated_at", "")
        ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
        assert isinstance(
            data.get("version"), int
        ), f"version must be an integer, got {data.get('version')!r}"


def assert_agency(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("agency_code"), str) and data["agency_code"]
    assert isinstance(data.get("federally_funded"), bool)
    assert data.get("status") in ("ACTIVE", "SUSPENDED")


def assert_contract(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("base_quantity"), int)
    assert isinstance(data.get("base_unit_price_cents"), int)
    assert data.get("escalation_index") in ("PPI_1413", "CPI_U")
    assert data.get("status") in (
        "DRAFT",
        "AWARDED",
        "ACTIVE",
        "COMPLETED",
        "TERMINATED",
    )


def assert_option_order(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("option_year"), int)
    assert isinstance(data.get("quantity"), int)
    assert data.get("propulsion_type") in ("DIESEL", "CNG", "HEV", "BEV", "FCEV")
    assert data.get("status") in ("AVAILABLE", "EXERCISED", "EXPIRED")


def assert_bus_configuration(data: dict):
    assert_common_fields(data)
    assert data.get("propulsion_type") in ("DIESEL", "CNG", "HEV", "BEV", "FCEV")
    assert data.get("status") in (
        "DRAFT",
        "ENGINEERING_REVIEW",
        "FROZEN",
        "OBSOLETE",
    )


def assert_component(data: dict):
    assert_common_fields(data)
    assert data.get("category") in (
        "PROPULSION",
        "BODY",
        "AXLE",
        "ELECTRICAL",
        "FARE",
        "ACCESSIBILITY",
    )
    assert isinstance(data.get("unit_cost_cents"), int)
    assert isinstance(data.get("is_domestic"), bool)
    assert data.get("supplier_doc_status") in (
        "MISSING",
        "SUBMITTED",
        "VERIFIED",
        "REJECTED",
    )


def assert_compliance_certificate(data: dict):
    assert_common_fields(data)
    assert data.get("variant") in ("COST_BASED", "COMPONENT_COUNT")
    assert data.get("status") in ("ISSUED", "SUPERSEDED", "REVOKED")


def assert_audit_record(data: dict):
    assert_common_fields(data)
    assert data.get("audit_type") in ("PRE_AWARD", "POST_DELIVERY")
    assert data.get("status") in ("OPEN", "COMPLETED")
    assert isinstance(data.get("findings_count"), int)


def assert_production_slot(data: dict):
    assert_common_fields(data)
    assert data.get("line_id") in ("LINE_A", "LINE_B")
    assert data.get("kit_status") in ("NOT_KITTED", "KITTED")
    assert data.get("status") in (
        "OPEN",
        "ASSIGNED",
        "IN_PRODUCTION",
        "DONE",
        "CANCELLED",
    )


def assert_parts_kit(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("component_ids"), list)
    assert data.get("status") in ("STAGING", "COMPLETE", "CONSUMED")


def assert_bus_unit(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("serial_number"), str) and data["serial_number"]
    assert data.get("assembly_location") in ("US_MAIN", "US_ANNEX")
    assert data.get("payment_status") in ("UNPAID", "INVOICED", "PAID")
    assert data.get("status") in (
        "ORDERED",
        "ENGINEERED",
        "IN_PRODUCTION",
        "BUILT",
        "PLANT_INSPECTION",
        "IN_TRANSIT",
        "DELIVERED",
        "ACCEPTED",
        "REJECTED",
    )


def assert_inspection_record(data: dict):
    # Append-only observation: id + created_at only; no updated_at / version.
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), "created_at must be ISO 8601"
    assert data.get("inspection_type") in ("PLANT", "DELIVERY")
    assert data.get("result") in ("PASS", "FAIL")
    assert "version" not in data, "InspectionRecord must not carry a version field"
    assert (
        "updated_at" not in data
    ), "InspectionRecord must not carry an updated_at field"


def assert_warranty_claim(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("claimed_amount_cents"), int)
    assert data.get("status") in (
        "FILED",
        "UNDER_REVIEW",
        "APPROVED",
        "DENIED",
        "PAID",
        "CLOSED",
    )


def assert_training_session(data: dict):
    assert_common_fields(data)
    assert data.get("propulsion_type") in ("DIESEL", "CNG", "HEV", "BEV", "FCEV")
    assert isinstance(data.get("attendee_count"), int)
    assert data.get("status") in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_parts_stock(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("quantity"), int)
    assert isinstance(data.get("reserved_quantity"), int)
    assert data.get("status") in ("ACTIVE", "DEPLETED")


def assert_parts_stock_invariants(data: dict):
    """Available stock invariant: quantity - reserved_quantity >= 0."""
    assert data["quantity"] >= data["reserved_quantity"], (
        f"quantity {data['quantity']} below reserved_quantity "
        f"{data['reserved_quantity']}"
    )
    available = data["quantity"] - data["reserved_quantity"]
    if available == 0:
        assert (
            data["status"] == "DEPLETED"
        ), f"zero available stock must be DEPLETED, got {data['status']}"
    else:
        assert (
            data["status"] == "ACTIVE"
        ), f"positive available stock must be ACTIVE, got {data['status']}"
