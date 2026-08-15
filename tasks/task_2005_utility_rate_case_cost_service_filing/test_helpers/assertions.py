"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from datetime import datetime, timezone
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    RateCaseStatus, IntervenorStatus, TestYearEntryStatus, AdjustmentStatus,
    RateBaseItemStatus, DataRequestStatus, SettlementProposalStatus,
    SettlementSignatoryStatus, RegulatoryAssetStatus, AmortizationEntryStatus,
    TariffRateStatus, ComplianceFilingStatus,
)


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating optional fractional digits."""
    assert isinstance(value, str), f"expected ISO string, got {type(value)}"
    v = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def assert_instant_equals(actual: str, expected_iso: str, label: str = "instant"):
    """Two ISO strings denote the same instant (rendering may differ)."""
    assert _parse_instant(actual) == _parse_instant(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_rate_case(data: dict):
    _assert_common(data, "RateCase")
    assert isinstance(data["case_number"], str) and data["case_number"]
    assert isinstance(data["utility_name"], str) and data["utility_name"]
    assert isinstance(data["return_on_rate_base_bp"], int)
    assert 1 <= data["return_on_rate_base_bp"] <= 3000
    assert isinstance(data["proposed_revenue_requirement_cents"], int)
    assert data["allocation_method"] in ("COINCIDENT_PEAK", "ENERGY_AVERAGE")
    assert data["status"] in [s.value for s in RateCaseStatus]
    assert isinstance(data["overdue_data_request_count"], int)
    assert isinstance(data["assented_proposal_count"], int)


def assert_intervenor(data: dict):
    _assert_common(data, "Intervenor")
    assert isinstance(data["party_name"], str) and data["party_name"]
    assert isinstance(data["representative_name"], str)
    assert isinstance(data["contact_email"], str)
    assert data["status"] in [s.value for s in IntervenorStatus]


def assert_test_year_entry(data: dict):
    _assert_common(data, "TestYearEntry")
    assert data["category"] in ("O_AND_M", "DEPRECIATION", "TAXES")
    assert isinstance(data["booked_amount_cents"], int)
    assert data["booked_amount_cents"] >= 0
    assert isinstance(data["adjusted_amount_cents"], int)
    assert data["status"] in [s.value for s in TestYearEntryStatus]


def assert_adjustment(data: dict):
    _assert_common(data, "Adjustment")
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] != 0
    assert isinstance(data["reason"], str)
    assert isinstance(data["proposed_by_user_id"], str)
    assert data["status"] in [s.value for s in AdjustmentStatus]


def assert_rate_base_item(data: dict):
    _assert_common(data, "RateBaseItem")
    for f in ("plant_in_service_cents", "accumulated_depreciation_cents",
              "working_capital_cents", "accumulated_deferred_taxes_cents"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be a non-negative integer"
    assert isinstance(data["net_rate_base_cents"], int)
    assert data["net_rate_base_cents"] == (
        data["plant_in_service_cents"]
        - data["accumulated_depreciation_cents"]
        + data["working_capital_cents"]
        - data["accumulated_deferred_taxes_cents"]
    ), "net_rate_base_cents must equal plant - depreciation + working capital - deferred taxes"
    assert data["status"] in [s.value for s in RateBaseItemStatus]


def assert_customer_class(data: dict):
    _assert_common(data, "CustomerClass")
    assert isinstance(data["class_code"], str) and data["class_code"]
    for f in ("customer_count", "monthly_kwh_per_customer", "annual_kwh",
              "coincident_peak_kw", "average_demand_kw"):
        assert isinstance(data[f], int) and data[f] > 0, f"{f} must be a positive integer"
    assert isinstance(data["present_customer_charge_cents"], int)
    assert data["present_customer_charge_cents"] >= 0
    tiers = data["present_tiers"]
    assert isinstance(tiers, list) and tiers, "present_tiers must be a non-empty array"
    null_terminals = [t for t in tiers if t.get("up_to_kwh") is None]
    assert len(null_terminals) == 1, "exactly one terminal tier has up_to_kwh null"
    assert isinstance(data["present_revenue_cents"], int)


def assert_data_request(data: dict):
    _assert_common(data, "DataRequest")
    assert data["issuer_kind"] in ("INTERVENOR", "STAFF")
    assert isinstance(data["subject"], str)
    assert isinstance(data["body"], str)
    assert data["status"] in [s.value for s in DataRequestStatus]
    _parse_instant(data["issued_at"])  # must be a parseable ISO 8601 instant


def assert_settlement_proposal(data: dict):
    _assert_common(data, "SettlementProposal")
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert isinstance(data["proposed_revenue_requirement_cents"], int)
    assert isinstance(data["signature_count"], int)
    assert isinstance(data["required_signature_count"], int)
    assert data["status"] in [s.value for s in SettlementProposalStatus]


def assert_settlement_signatory(data: dict):
    _assert_common(data, "SettlementSignatory")
    assert is_valid_uuid(data.get("settlement_proposal_id", ""))
    assert is_valid_uuid(data.get("intervenor_id", ""))
    assert data["status"] in [s.value for s in SettlementSignatoryStatus]


def assert_regulatory_asset(data: dict):
    _assert_common(data, "RegulatoryAsset")
    assert isinstance(data["principal_cents"], int) and data["principal_cents"] > 0
    assert isinstance(data["amortization_months"], int) and data["amortization_months"] > 0
    assert isinstance(data["monthly_base_cents"], int)
    assert isinstance(data["final_month_cents"], int)
    assert isinstance(data["amortized_to_date_cents"], int)
    assert data["status"] in [s.value for s in RegulatoryAssetStatus]
    # PRD §3.6: remainder is absorbed by the final installment.
    assert (
        data["monthly_base_cents"] * (data["amortization_months"] - 1)
        + data["final_month_cents"]
        == data["principal_cents"]
    ), "monthly_base*(months-1) + final_month must equal principal exactly"


def assert_amortization_entry(data: dict):
    _assert_common(data, "AmortizationEntry")
    assert is_valid_uuid(data.get("regulatory_asset_id", ""))
    assert isinstance(data["period_index"], int) and data["period_index"] >= 1
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in [s.value for s in AmortizationEntryStatus]


def assert_tariff_rate(data: dict):
    _assert_common(data, "TariffRate")
    assert isinstance(data["proposed_customer_charge_cents"], int)
    assert data["proposed_customer_charge_cents"] >= 0
    tiers = data["proposed_tiers"]
    assert isinstance(tiers, list) and tiers
    null_terminals = [t for t in tiers if t.get("up_to_kwh") is None]
    assert len(null_terminals) == 1
    assert isinstance(data["proposed_revenue_cents"], int)
    assert data["status"] in [s.value for s in TariffRateStatus]


def assert_compliance_filing(data: dict):
    _assert_common(data, "ComplianceFiling")
    assert isinstance(data["period_label"], str)
    assert isinstance(data["actual_revenue_by_class"], list)
    assert isinstance(data["actual_total_revenue_cents"], int)
    assert data["status"] in [s.value for s in ComplianceFilingStatus]


def assert_amortization_coverage_invariant(asset: dict, entries: list):
    """PRD §3.6 invariant, composed from two verbatim rules: "the sum of all
    generated `amount_cents` equals `principal_cents` exactly", and
    `amortized_to_date_cents` accumulates exactly the POSTED rows (initialized
    to zero; "adds the entry's `amount_cents`" on post; "subtracts its
    `amount_cents`" on reverse). Composing both over the PENDING / POSTED /
    REVERSED partition gives the checked identity:
    amortized_to_date + sum(PENDING amounts) + sum(REVERSED amounts) == principal.
    Callers must pass the asset's full entry list so no bucket is hidden."""
    pending_total = sum(e["amount_cents"] for e in entries if e["status"] == "PENDING")
    reversed_total = sum(e["amount_cents"] for e in entries if e["status"] == "REVERSED")
    covered = asset["amortized_to_date_cents"] + pending_total + reversed_total
    assert covered == asset["principal_cents"], (
        f"coverage drift: {asset['amortized_to_date_cents']} amortized + "
        f"{pending_total} pending + {reversed_total} reversed "
        f"!= principal {asset['principal_cents']}"
    )
