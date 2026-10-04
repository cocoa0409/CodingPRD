"""Entity assertions and domain invariant checkers (PRD §2.5 common fields)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ApplicationCaseStatus,
    ClearanceStatus,
    ComplianceStatus,
    ConverterStatus,
    CounterfeitReportStatus,
    DisclosureLevel,
    FormulationStatus,
    FulfillmentStatus,
    PhaseOutStatus,
    RebateAccrualStatus,
    RebateProgramStatus,
    RestrictionClass,
)


def _assert_common_fields(data):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version starts at 1"


def assert_jurisdiction(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["declaration_threshold_ppm"], int)
    assert isinstance(data["full_disclosure_threshold_ppm"], int)


def assert_substance(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["cas_number"], str) and data["cas_number"]
    assert data["restriction_class"] in [c.value for c in RestrictionClass]


def assert_formulation(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert data["status"] in [s.value for s in FormulationStatus]
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1
    assert isinstance(data["active_clearance_count"], int)


def assert_formulation_component(data: dict):
    # Immutable join row: id + created_at only; no updated_at, no version (PRD §2.5).
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "FormulationComponent must not carry updated_at"
    assert "version" not in data, "FormulationComponent must not carry version"
    assert isinstance(data["concentration_ppm"], int) and data["concentration_ppm"] > 0


def assert_clearance(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in ClearanceStatus]
    assert data["disclosure_package_level"] in [d.value for d in DisclosureLevel]
    assert isinstance(data["submission_count"], int) and data["submission_count"] >= 1


def assert_converter(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in ConverterStatus]
    assert isinstance(data["name"], str) and data["name"]


def assert_distributor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]


def assert_converter_authorization(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["converter_id"], str) and data["converter_id"]
    assert isinstance(data["territory_code"], str) and data["territory_code"]


def assert_application_case(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in ApplicationCaseStatus]
    assert isinstance(data["failure_count"], int) and data["failure_count"] >= 0


def assert_price_agreement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] > 0
    # exactly one buyer
    assert (data.get("converter_id") is None) != (data.get("distributor_id") is None)


def assert_order(data: dict):
    _assert_common_fields(data)
    assert data["fulfillment_status"] in [s.value for s in FulfillmentStatus]
    assert data["compliance_status"] in [s.value for s in ComplianceStatus]
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["unit_price_cents"], int)
    assert data["line_total_cents"] == data["unit_price_cents"] * data["quantity"]


def assert_rebate_program(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in RebateProgramStatus]
    assert isinstance(data["budget_cap_cents"], int) and data["budget_cap_cents"] > 0


def assert_rebate_accrual(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in RebateAccrualStatus]
    assert isinstance(data["excluded_order_count"], int)
    assert isinstance(data["provisional_amount_cents"], int)


def assert_phase_out_program(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in PhaseOutStatus]
    assert isinstance(data["qualified_customers"], list)
    assert data["qualified_customer_count"] == len(data["qualified_customers"])


def assert_counterfeit_report(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in CounterfeitReportStatus]
    assert isinstance(data["lot_code"], str) and data["lot_code"]


def assert_pool_invariant(formulation: dict):
    """PRD §3.6: remaining pool == pool quantity minus units still ALLOCATED/SHIPPED
    (callers pass a formulation whose orders they have tracked)."""
    assert isinstance(formulation["ltb_pool_quantity"], int)
    assert isinstance(formulation["ltb_pool_remaining"], int)
    assert 0 <= formulation["ltb_pool_remaining"] <= formulation["ltb_pool_quantity"]
