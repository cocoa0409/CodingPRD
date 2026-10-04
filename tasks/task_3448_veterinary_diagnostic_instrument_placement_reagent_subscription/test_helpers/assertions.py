"""Entity assertions and domain invariant checkers.

STATUS-CODE CONVENTION (PRD §4): operations that CREATE a new resource —
group pricing agreements, clinics, placement agreements, analyzers, service
cases, reagent orders, and lab test orders — return ``201 Created``. ALL
other successful operations (state drives, action endpoints, reads, the
clock advance) return ``200 OK``. The framework's ``validate_success``
defaults to 200, so callers asserting a creation response MUST pass 201
explicitly::

    data = validate_success(resp, 201)          # resource-creating POST
    data = validate_success(resp)               # everything else (200)

For error-precedence relaxation (a PRD rule names one error but does not
pre-empt a state-check path), use the framework's
``validate_error_is_one_of([ERR_A, ERR_B])``. Assertion helpers in this
module never silently swallow an unexpected status: they only accept the
response ``data`` payload AFTER the caller has validated the envelope.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .constants import (
    ALLOWED_TERM_MONTHS, KNOWN_SKUS, PRICE_TABLE, UPTIME_WINDOW_HOURS,
)
from .types import (
    AgreementStatus, AnalyzerModel, BillingStatus, ClinicStatus,
    ConnectivityStatus, DeliveryStatus, GroupPricingAgreementStatus,
    GroupType, LabResultSource, LabTestOrderStatus, OperationalStatus,
    PeriodStatus, PriceSource, ProficiencyStanding, ProficiencyVerdict,
    ProgramType, ReagentOrderStatus, ServiceCaseStatus, ServiceCaseType,
    TestOrderKind, TestOrderOrigin,
)

__all__ = [
    "assert_common_fields", "assert_group_pricing_agreement", "assert_clinic",
    "assert_placement_agreement", "assert_analyzer", "assert_reagent_order",
    "assert_commitment_period", "assert_lab_test_order", "assert_lab_result",
    "assert_service_case", "assert_agreement_ledger_invariants",
    "assert_analyzer_fresh_dimensions", "assert_money_cents",
    "assert_uptime_ratio", "extract_pricing_lines", "assert_pricing_line",
    "assert_open_period_shape", "assert_closed_period_shape",
]


# ---------------------------------------------------------------------------
# Shared field checkers
# ---------------------------------------------------------------------------
def assert_common_fields(data: dict, label: str = "resource"):
    """id + created_at + updated_at + version (PRD §2.5 primary resources)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive int, got {data.get('version')!r}"
    )


def assert_money_cents(value, name: str):
    """Money is integer cents; fractional cents never appear (PRD §2.6)."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{name} must be integer cents, got {value!r}"
    )


def assert_uptime_ratio(value, name: str):
    """Uptime ratios are 0..1 with at most 4 decimal places (PRD §2.6, §3.9)."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{name} must be numeric, got {value!r}"
    )
    assert 0.0 <= float(value) <= 1.0, f"{name} must lie in [0, 1], got {value!r}"
    assert round(float(value), 4) == float(value), (
        f"{name} must carry at most 4 decimal places, got {value!r}"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_group_pricing_agreement(data: dict):
    assert_common_fields(data, "GroupPricingAgreement")
    assert data["group_type"] in [e.value for e in GroupType]
    assert isinstance(data["group_code"], str) and len(data["group_code"]) > 0
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])
    assert 0 <= float(data["discount_pct"]) <= 0.40, (
        "discount_pct must respect the 0.40 platform ceiling"
    )
    assert isinstance(data["sku_overrides"], list)
    for entry in data["sku_overrides"]:
        assert entry["sku"] in PRICE_TABLE, f"override sku {entry['sku']} not in price table"
        assert_money_cents(entry["unit_price_cents"], "sku_overrides[].unit_price_cents")
    assert data["status"] in [e.value for e in GroupPricingAgreementStatus]


def assert_clinic(data: dict):
    assert_common_fields(data, "Clinic")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["corporate_group_code"] is None or isinstance(data["corporate_group_code"], str)
    assert data["buying_group_code"] is None or isinstance(data["buying_group_code"], str)
    assert isinstance(data["caseload_baseline_tests"], int) and data["caseload_baseline_tests"] > 0
    assert isinstance(data["caseload_current_tests"], int)
    assert data["status"] in [e.value for e in ClinicStatus]


def assert_placement_agreement(data: dict):
    assert_common_fields(data, "PlacementAgreement")
    assert is_valid_uuid(data.get("clinic_id", "")), "clinic_id must be a UUID"
    assert data["model"] in [e.value for e in AnalyzerModel]
    assert data["program_type"] in [e.value for e in ProgramType]
    assert data["term_months"] in ALLOWED_TERM_MONTHS
    assert is_iso8601_timestamp(data["start_date"])
    assert is_iso8601_timestamp(data["end_date"]), "end_date is computed at creation"
    # Program-conditional commercial fields (PRD §3.3)
    pt = data["program_type"]
    if pt == ProgramType.REAGENT_COMMITMENT.value:
        assert_money_cents(data["monthly_minimum_cents"], "monthly_minimum_cents")
        assert data["monthly_minimum_cents"] >= 50000
    else:
        assert data["monthly_minimum_cents"] is None
    if pt == ProgramType.LEASE.value:
        assert_money_cents(data["lease_rate_cents"], "lease_rate_cents")
    else:
        assert data["lease_rate_cents"] is None
    if pt == ProgramType.PURCHASE.value:
        assert_money_cents(data["purchase_price_cents"], "purchase_price_cents")
    else:
        assert data["purchase_price_cents"] is None
    # System / computed fields
    assert data["baseline_caseload_snapshot"] is None or isinstance(
        data["baseline_caseload_snapshot"], int
    )
    assert data["proposed_minimum_cents"] is None or isinstance(
        data["proposed_minimum_cents"], int
    )
    assert_money_cents(data["cumulative_billed_cents"], "cumulative_billed_cents")
    assert_money_cents(data["cumulative_unpaid_billed_cents"], "cumulative_unpaid_billed_cents")
    assert_money_cents(data["service_credit_cents"], "service_credit_cents")
    assert data["status"] in [e.value for e in AgreementStatus]


def assert_agreement_ledger_invariants(data: dict):
    """Ledger invariants that must hold after any operation (PRD §3.5)."""
    assert_placement_agreement(data)
    assert data["cumulative_billed_cents"] >= 0
    assert data["cumulative_unpaid_billed_cents"] >= 0
    assert data["cumulative_unpaid_billed_cents"] <= data["cumulative_billed_cents"], (
        "payments/waivers only ever reduce the unpaid ledger, never the billed ledger"
    )
    assert data["service_credit_cents"] >= 0


def assert_analyzer(data: dict):
    assert_common_fields(data, "Analyzer")
    assert is_valid_uuid(data.get("clinic_id", "")), "clinic_id must be a UUID"
    assert is_valid_uuid(data.get("agreement_id", "")), "agreement_id must be a UUID"
    assert data["model"] in [e.value for e in AnalyzerModel]
    assert isinstance(data["serial_number"], str) and len(data["serial_number"]) > 0
    assert isinstance(data["is_loaner_unit"], bool)
    assert data["operational_status"] in [e.value for e in OperationalStatus]
    assert data["connectivity_status"] in [e.value for e in ConnectivityStatus]
    assert data["proficiency_standing"] in [e.value for e in ProficiencyStanding]
    assert data["qc_valid_until"] is None or is_iso8601_timestamp(data["qc_valid_until"])
    assert isinstance(data["total_downtime_hours"], int) and data["total_downtime_hours"] >= 0
    assert_uptime_ratio(data["reported_uptime_pct"], "reported_uptime_pct")
    assert_uptime_ratio(data["breach_uptime_pct"], "breach_uptime_pct")


def assert_analyzer_fresh_dimensions(data: dict):
    """A newly installed analyzer (PRD §3.7): INSTALLED / NOT_CONFIGURED /
    LAPSED, qc_valid_until null, zero downtime, both uptime ratios 1.0."""
    assert_analyzer(data)
    assert data["operational_status"] == OperationalStatus.INSTALLED.value
    assert data["connectivity_status"] == ConnectivityStatus.NOT_CONFIGURED.value
    assert data["proficiency_standing"] == ProficiencyStanding.LAPSED.value
    assert data["qc_valid_until"] is None
    assert data["total_downtime_hours"] == 0
    assert float(data["reported_uptime_pct"]) == 1.0
    assert float(data["breach_uptime_pct"]) == 1.0
    assert data["version"] == 1


def assert_reagent_order(data: dict):
    assert_common_fields(data, "ReagentOrder")
    assert is_valid_uuid(data.get("clinic_id", "")), "clinic_id must be a UUID"
    assert is_valid_uuid(data.get("agreement_id", "")), "agreement_id must be a UUID"
    assert isinstance(data["order_month"], str) and len(data["order_month"]) == 7, (
        "order_month must be YYYY-MM"
    )
    assert isinstance(data["lines"], list) and len(data["lines"]) > 0
    for line in data["lines"]:
        assert line["sku"] in KNOWN_SKUS, f"line sku {line['sku']} not in price table"
        assert isinstance(line["quantity"], int) and line["quantity"] > 0
    assert_money_cents(data["list_total_cents"], "list_total_cents")
    assert_money_cents(data["final_total_cents"], "final_total_cents")
    assert data["final_total_cents"] <= data["list_total_cents"], (
        "discounts and program-included lines can only lower the total"
    )
    assert data["fulfilled_at"] is None or is_iso8601_timestamp(data["fulfilled_at"])
    assert data["status"] in [e.value for e in ReagentOrderStatus]


def assert_commitment_period(data: dict):
    assert_common_fields(data, "CommitmentPeriod")
    assert is_valid_uuid(data.get("agreement_id", "")), "agreement_id must be a UUID"
    assert isinstance(data["period_month"], str) and len(data["period_month"]) == 7
    assert_money_cents(data["minimum_cents"], "minimum_cents")
    assert data["period_status"] in [e.value for e in PeriodStatus]
    assert data["billing_status"] in [e.value for e in BillingStatus]


def assert_open_period_shape(data: dict):
    """An OPEN period (PRD §3.5): provisional total present; final-variant
    fields null until the close locks them."""
    assert_commitment_period(data)
    assert data["period_status"] == PeriodStatus.OPEN.value
    assert data["billing_status"] == BillingStatus.NONE.value
    assert data["provisional_fulfilled_cents"] is not None
    assert_money_cents(data["provisional_fulfilled_cents"], "provisional_fulfilled_cents")
    assert data["fulfilled_cents"] is None
    assert data["shortfall_cents"] is None
    assert data["billed_cents"] is None


def assert_closed_period_shape(data: dict):
    """A CLOSED period (PRD §3.5): final attribution locked, provisional null."""
    assert_commitment_period(data)
    assert data["period_status"] == PeriodStatus.CLOSED.value
    assert data["provisional_fulfilled_cents"] is None
    assert_money_cents(data["fulfilled_cents"], "fulfilled_cents")
    assert_money_cents(data["shortfall_cents"], "shortfall_cents")
    assert_money_cents(data["billed_cents"], "billed_cents")
    assert data["shortfall_cents"] == max(0, data["minimum_cents"] - data["fulfilled_cents"])
    if data["billed_cents"] > 0:
        assert data["billing_status"] in (
            BillingStatus.ISSUED.value, BillingStatus.PAID.value, BillingStatus.WAIVED.value,
        )
    else:
        assert data["billing_status"] == BillingStatus.NONE.value


def assert_lab_test_order(data: dict):
    assert_common_fields(data, "LabTestOrder")
    assert is_valid_uuid(data.get("clinic_id", "")), "clinic_id must be a UUID"
    assert data["analyzer_id"] is None or is_valid_uuid(data["analyzer_id"])
    assert data["origin"] in [e.value for e in TestOrderOrigin]
    assert data["order_kind"] in [e.value for e in TestOrderKind]
    assert isinstance(data["test_code"], str) and len(data["test_code"]) > 0
    # Conditional shapes (PRD §3.8)
    if data["origin"] == TestOrderOrigin.IN_CLINIC.value:
        assert data["analyzer_id"] is not None, "IN_CLINIC orders must name analyzer_id"
    else:
        assert data["analyzer_id"] is None, "SEND_OUT orders must carry analyzer_id null"
    if data["order_kind"] == TestOrderKind.PROFICIENCY.value:
        assert data["origin"] == TestOrderOrigin.IN_CLINIC.value
        assert isinstance(data["expected_result"], (int, float))
    else:
        assert data["expected_result"] is None
    assert data["status"] in [e.value for e in LabTestOrderStatus]
    assert data["delivery_status"] in [e.value for e in DeliveryStatus]


def assert_lab_result(data: dict):
    """The immutable result record (PRD §2.5): id + created_at ONLY of the
    common fields — updated_at and version must be ABSENT."""
    assert is_valid_uuid(data.get("id", "")), "LabResult.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "LabResult.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "LabResult must not carry updated_at"
    assert "version" not in data, "LabResult must not carry version"
    assert is_valid_uuid(data.get("test_order_id", "")), "test_order_id must be a UUID"
    assert data["source"] in [e.value for e in LabResultSource]
    assert isinstance(data["result_value"], (int, float))
    assert data["expected_value"] is None or isinstance(data["expected_value"], (int, float))
    assert data["verdict"] is None or data["verdict"] in [e.value for e in ProficiencyVerdict]
    assert is_iso8601_timestamp(data["resulted_at"])


def assert_service_case(data: dict):
    assert_common_fields(data, "ServiceCase")
    assert is_valid_uuid(data.get("analyzer_id", "")), "analyzer_id must be a UUID"
    assert data["case_type"] in [e.value for e in ServiceCaseType]
    assert data["loaner_analyzer_id"] is None or is_valid_uuid(data["loaner_analyzer_id"])
    assert data["status"] in [e.value for e in ServiceCaseStatus]
    assert is_iso8601_timestamp(data["opened_at"])
    assert is_iso8601_timestamp(data["response_due_at"])
    assert data["resolved_at"] is None or is_iso8601_timestamp(data["resolved_at"])
    assert data["downtime_hours"] is None or (
        isinstance(data["downtime_hours"], int) and data["downtime_hours"] >= 0
    )
    assert data["sla_met"] is None or isinstance(data["sla_met"], bool)
    assert data["resolution_note"] is None or isinstance(data["resolution_note"], str)


# ---------------------------------------------------------------------------
# Pricing-detail helpers (PRD §3.4)
# ---------------------------------------------------------------------------
def extract_pricing_lines(pricing_detail) -> list:
    """Return the per-line list from a ReagentOrder's pricing_detail snapshot.

    The PRD pins the per-line content (``unit_price_cents``, ``price_source``,
    ``line_total_cents`` per line) but not the container shape, so this helper
    accepts either a bare list of lines or an object with a ``lines`` list.
    """
    if isinstance(pricing_detail, list):
        return pricing_detail
    assert isinstance(pricing_detail, dict), (
        f"pricing_detail must be an object or list, got {type(pricing_detail).__name__}"
    )
    lines = pricing_detail.get("lines")
    assert isinstance(lines, list), (
        "pricing_detail object must expose a 'lines' list of per-line snapshots"
    )
    return lines


def assert_pricing_line(line: dict, sku: str, unit_price_cents: int,
                        price_source: str, line_total_cents: int):
    """Assert one locked pricing line (PRD §3.4: computed once, immutable)."""
    assert line.get("sku") == sku, f"line sku {line.get('sku')!r} != expected {sku!r}"
    assert line.get("unit_price_cents") == unit_price_cents, (
        f"{sku}: unit_price_cents {line.get('unit_price_cents')} != {unit_price_cents}"
    )
    assert line.get("price_source") == price_source, (
        f"{sku}: price_source {line.get('price_source')!r} != {price_source!r}; "
        f"expected one of {[e.value for e in PriceSource]}"
    )
    assert line.get("line_total_cents") == line_total_cents, (
        f"{sku}: line_total_cents {line.get('line_total_cents')} != {line_total_cents}"
    )
