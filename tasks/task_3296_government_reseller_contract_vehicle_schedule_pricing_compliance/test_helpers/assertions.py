"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AgreementPosture,
    AgreementStatus,
    AuditStatus,
    DisputeStatus,
    InvoiceStatus,
    ManufacturerStatus,
    ManufacturerType,
    OrderBillingStatus,
    OrderComplianceStatus,
    OriginFlag,
    PriceListStatus,
    PriceModificationStatus,
    SalesReportStatus,
    TeamingStatus,
    VehicleKind,
    VehicleStatus,
)


def _assert_common(data, with_version=True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
        )
        assert isinstance(data.get("version"), int), (
            f"version must be an integer, got {data.get('version')!r}"
        )


def assert_manufacturer(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["duns"], str) and len(data["duns"]) == 9 and data["duns"].isdigit()
    assert data["manufacturer_type"] in [t.value for t in ManufacturerType]
    assert isinstance(data["headquarters_country"], str) and len(data["headquarters_country"]) == 2
    assert data["status"] in [s.value for s in ManufacturerStatus]


def assert_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["manufacturer_id"])
    assert isinstance(data["scope_tiers"], list) and len(data["scope_tiers"]) >= 1
    assert 0 <= data["mfc_discount_pct"] <= 0.5
    assert 0 <= data["small_business_goal_pct"] <= 1
    assert isinstance(data["product_scope"], list)
    assert isinstance(data["dispute_credit_cents"], int)
    assert data["posture"] in [p.value for p in AgreementPosture]
    assert data["status"] in [s.value for s in AgreementStatus]


def assert_vehicle(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["agreement_id"])
    assert data["vehicle_kind"] in [k.value for k in VehicleKind]
    assert isinstance(data["buyer_tiers"], list) and len(data["buyer_tiers"]) >= 1
    assert isinstance(data["ceiling_cents"], int) and data["ceiling_cents"] > 0
    assert isinstance(data["taa_required"], bool)
    assert isinstance(data["prc_accumulator_cents"], int)
    assert data["status"] in [s.value for s in VehicleStatus]


def assert_price_list(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["vehicle_id"])
    assert data["status"] in [s.value for s in PriceListStatus]


def assert_price_line(data: dict):
    # PRD §2.4: PriceLine carries only id and created_at among common fields.
    _assert_common(data, with_version=False)
    assert "updated_at" not in data, "PriceLine must not carry updated_at"
    assert "version" not in data, "PriceLine must not carry version"
    assert isinstance(data["basis_price_cents"], int) and data["basis_price_cents"] > 0
    assert isinstance(data["offered_price_cents"], int) and data["offered_price_cents"] > 0
    assert isinstance(data["origin_country"], str) and len(data["origin_country"]) == 2
    assert isinstance(data.get("sold_qty", 0), int)


def assert_teaming(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["agreement_id"])
    assert isinstance(data["integrator_name"], str) and data["integrator_name"]
    assert isinstance(data["small_business"], bool)
    assert 0 <= data["revenue_share_pct"] <= 0.4
    assert data["status"] in [s.value for s in TeamingStatus]


def assert_teaming_scope(data: dict):
    # PRD §2.4: TeamingScope carries only id and created_at among common fields.
    _assert_common(data, with_version=False)
    assert "updated_at" not in data, "TeamingScope must not carry updated_at"
    assert "version" not in data, "TeamingScope must not carry version"
    assert is_valid_uuid(data["teaming_id"])
    assert is_valid_uuid(data["vehicle_id"])
    assert isinstance(data["sku_prefixes"], list) and len(data["sku_prefixes"]) >= 1


def assert_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["vehicle_id"])
    assert is_valid_uuid(data["price_list_id"])
    assert data["compliance_status"] in [s.value for s in OrderComplianceStatus]
    assert data["billing_status"] in [s.value for s in OrderBillingStatus]
    assert data["origin_flag"] in [f.value for f in OriginFlag]
    assert isinstance(data["order_total_cents"], int) and data["order_total_cents"] > 0
    assert isinstance(data["teaming_surcharge_cents"], int)
    assert isinstance(data["subcontract_cents"], int)


def assert_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["amount_cents"], int)
    assert data["payment_terms_days"] in (15, 30, 45, 60)
    assert data["status"] in [s.value for s in InvoiceStatus]


def assert_dispute(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] != 0
    assert data["status"] in [s.value for s in DisputeStatus]


def assert_sales_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["agreement_id"])
    assert isinstance(data["period_label"], str)
    assert isinstance(data["total_sales_cents"], int)
    assert isinstance(data["total_sb_subcontract_cents"], int)
    assert isinstance(data["sb_goal_met"], bool)
    assert data["status"] in [s.value for s in SalesReportStatus]


def assert_audit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["agreement_id"])
    assert isinstance(data["mfc_attestation_cents"], int)
    assert isinstance(data["mfc_variance_cents"], int)
    assert isinstance(data["disclosed_total_cents"], int)
    assert data["status"] in [s.value for s in AuditStatus]


def assert_price_modification(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["price_list_id"])
    assert isinstance(data["new_offered_price_cents"], int)
    assert data["new_offered_price_cents"] > 0
    assert data["status"] in [s.value for s in PriceModificationStatus]
