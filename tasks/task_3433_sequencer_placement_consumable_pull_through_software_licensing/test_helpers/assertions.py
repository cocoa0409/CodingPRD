"""Entity assertions and domain invariant checkers (PRD sections 2.5, 3.x).

assert_<entity>(data) validates the full read surface of a freshly fetched
resource: common fields (PRD section 2.5), field types, and enum membership.
Domain invariant helpers check derived quantities that must hold after any
operation (lot availability, license credit ledger, kit capacity, program
totals).
"""
from decimal import ROUND_HALF_UP, Decimal

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    CHEMISTRY_THROUGHPUT_MULT,
    FLOW_CELL_BASE_GB,
    SAMPLE_RATE_CENTS,
)
from .types import (
    AnalysisMode,
    ChemistryVersion,
    ClinicalValidationStatus,
    ColdChainClass,
    ColdChainStatus,
    ConditionFlag,
    ContractState,
    CreditEntryType,
    FlowCellVersion,
    ForecastState,
    GrantType,
    InstallState,
    LicenseState,
    OrderState,
    ProgramState,
    QcStatus,
    RegulatoryClass,
    RegulatoryClearance,
    ReleaseState,
    RunMode,
    RunOutcome,
    SupportStatus,
    TransitionProgramState,
)

__all__ = [
    "assert_account",
    "assert_instrument_model",
    "assert_reagent_kit",
    "assert_software_update",
    "assert_instrument",
    "assert_placement_program",
    "assert_reagent_lot",
    "assert_reagent_order",
    "assert_service_contract",
    "assert_software_license",
    "assert_run_record",
    "assert_transition_program",
    "assert_supply_forecast",
    "assert_uptime_reconciliation_result",
    "assert_billing_close_result",
    "assert_clock_set_result",
    "assert_kit_capacity",
    "assert_lot_invariants",
    "assert_license_invariants",
    "assert_program_invariants",
]


def _assert_common_fields(data: dict, label: str) -> None:
    """Common fields per PRD section 2.5 (all entities except run records)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer >= 1"
    )


def _enum_values(enum_cls) -> set:
    return {member.value for member in enum_cls}


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_account(data: dict) -> None:
    _assert_common_fields(data, "Account")
    assert isinstance(data.get("name"), str) and data["name"]
    assert data.get("regulatory_class") in _enum_values(RegulatoryClass)
    assert isinstance(data.get("region"), str)
    assert isinstance(data.get("credit_hold"), bool)
    assert isinstance(data.get("credit_balance_cents"), int)
    assert data["credit_balance_cents"] >= 0


def assert_instrument_model(data: dict) -> None:
    _assert_common_fields(data, "InstrumentModel")
    assert isinstance(data.get("model_code"), str) and data["model_code"]
    assert isinstance(data.get("generation"), int) and data["generation"] >= 1
    assert isinstance(data.get("base_price_cents"), int) and data["base_price_cents"] >= 0
    chem = data.get("supported_chemistry_versions")
    assert isinstance(chem, list) and all(c in _enum_values(ChemistryVersion) for c in chem)
    modes = data.get("base_run_modes")
    assert isinstance(modes, list) and all(m in _enum_values(RunMode) for m in modes)
    assert data.get("support_status") in _enum_values(SupportStatus)


def assert_reagent_kit(data: dict) -> None:
    _assert_common_fields(data, "ReagentKit")
    assert isinstance(data.get("kit_code"), str) and data["kit_code"]
    assert data.get("run_type") in _enum_values(RunMode)
    assert data.get("flow_cell_version") in _enum_values(FlowCellVersion)
    assert data.get("chemistry_version") in _enum_values(ChemistryVersion)
    assert data.get("regulatory_clearance") in _enum_values(RegulatoryClearance)
    assert isinstance(data.get("shelf_life_days"), int) and data["shelf_life_days"] > 0
    assert data.get("cold_chain_class") in _enum_values(ColdChainClass)
    assert isinstance(data.get("price_cents"), int) and data["price_cents"] >= 0
    assert isinstance(data.get("samples_per_kit"), int) and data["samples_per_kit"] >= 0
    assert isinstance(data.get("min_model_generation"), int)
    assert isinstance(data.get("capacity_gb"), (int, float))


def assert_software_update(data: dict) -> None:
    _assert_common_fields(data, "SoftwareUpdate")
    assert isinstance(data.get("update_version"), str) and data["update_version"]
    assert isinstance(data.get("min_model_generation"), int)
    modes = data.get("unlocks_run_modes")
    assert isinstance(modes, list) and all(m in _enum_values(RunMode) for m in modes)
    assert data.get("clinical_validation_status") in _enum_values(ClinicalValidationStatus)
    assert data.get("release_state") in _enum_values(ReleaseState)


def assert_instrument(data: dict) -> None:
    _assert_common_fields(data, "Instrument")
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("model_id", ""))
    assert isinstance(data.get("serial_number"), str) and data["serial_number"]
    assert data.get("regulatory_mode") in _enum_values(RegulatoryClass)
    installed_at = data.get("installed_at")
    assert installed_at is None or is_iso8601_timestamp(installed_at)
    assert data.get("install_state") in _enum_values(InstallState)
    assert isinstance(data.get("software_version"), str) and data["software_version"]
    assert isinstance(data.get("applied_update_ids"), list)
    modes = data.get("unlocked_run_modes")
    assert isinstance(modes, list) and all(m in _enum_values(RunMode) for m in modes)
    windows = data.get("service_windows")
    assert isinstance(windows, list)
    for w in windows:
        assert is_iso8601_timestamp(w.get("opened_at", ""))
        assert w.get("closed_at") is None or is_iso8601_timestamp(w["closed_at"])
    decom = data.get("decommissioned_at")
    assert decom is None or is_iso8601_timestamp(decom)


def assert_placement_program(data: dict) -> None:
    _assert_common_fields(data, "PlacementProgram")
    assert is_valid_uuid(data.get("account_id", ""))
    assert data.get("term_months") in (12, 24, 36)
    assert isinstance(data.get("committed_annual_reagent_cents"), int)
    assert data["committed_annual_reagent_cents"] >= 0
    assert isinstance(data.get("subsidy_pct"), (int, float))
    assert 0 < data["subsidy_pct"] <= 1
    lines = data.get("hardware_lines")
    assert isinstance(lines, list)
    for line in lines:
        assert isinstance(line.get("description"), str)
        assert isinstance(line.get("quantity"), int) and line["quantity"] >= 1
        assert isinstance(line.get("unit_price_cents"), int)
        assert line["unit_price_cents"] >= 0
    assert data.get("program_state") in _enum_values(ProgramState)
    assert isinstance(data.get("subsidy_pool_cents"), int)
    pinned = data.get("pinned_kit_prices")
    assert pinned is None or isinstance(pinned, dict)
    assert isinstance(data.get("committed_total_cents"), int)
    assert isinstance(data.get("delivered_spend_cents"), int)
    assert isinstance(data.get("pipeline_spend_cents"), int)
    assert isinstance(data.get("shortfall_flag"), bool)
    assert isinstance(data.get("penalty_cents"), int) and data["penalty_cents"] >= 0
    assert isinstance(data.get("period_index"), int) and data["period_index"] >= 1
    assert isinstance(data.get("created_by_user_id"), str)
    approver = data.get("approved_by_user_id")
    assert approver is None or isinstance(approver, str)
    pending = data.get("pending_amendment")
    assert pending is None or isinstance(pending, dict)


def assert_reagent_lot(data: dict) -> None:
    _assert_common_fields(data, "ReagentLot")
    assert is_valid_uuid(data.get("kit_id", ""))
    assert isinstance(data.get("lot_number"), str) and data["lot_number"]
    assert is_iso8601_timestamp(data.get("manufacture_date", ""))
    assert isinstance(data.get("quantity_units"), int) and data["quantity_units"] >= 0
    assert data.get("qc_status") in _enum_values(QcStatus)
    assert data.get("cold_chain_status") in _enum_values(ColdChainStatus)
    assert is_iso8601_timestamp(data.get("expiry_date", ""))
    assert isinstance(data.get("reserved_units"), int) and data["reserved_units"] >= 0
    assert isinstance(data.get("consumed_units"), int) and data["consumed_units"] >= 0
    assert isinstance(data.get("available_units"), int)


def assert_reagent_order(data: dict) -> None:
    _assert_common_fields(data, "ReagentOrder")
    assert is_valid_uuid(data.get("account_id", ""))
    program_id = data.get("program_id")
    assert program_id is None or is_valid_uuid(program_id)
    lines = data.get("lines")
    assert isinstance(lines, list) and len(lines) >= 1
    for line in lines:
        assert isinstance(line.get("kit_code"), str) and line["kit_code"]
        assert isinstance(line.get("quantity"), int) and line["quantity"] >= 1
    assert data.get("order_state") in _enum_values(OrderState)
    assert isinstance(data.get("total_cents"), int) and data["total_cents"] >= 0
    assert isinstance(data.get("attributed_total_cents"), int)
    assert data["attributed_total_cents"] >= 0
    reservations = data.get("line_reservations")
    assert isinstance(reservations, list)
    for r in reservations:
        assert isinstance(r.get("kit_code"), str)
        assert is_valid_uuid(r.get("lot_id", ""))
        assert isinstance(r.get("quantity"), int) and r["quantity"] >= 1
    submitted = data.get("submitted_at")
    assert submitted is None or is_iso8601_timestamp(submitted)
    delivered = data.get("delivered_at")
    assert delivered is None or is_iso8601_timestamp(delivered)


def assert_service_contract(data: dict) -> None:
    _assert_common_fields(data, "ServiceContract")
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("instrument_id", ""))
    assert is_iso8601_timestamp(data.get("coverage_start", ""))
    assert is_iso8601_timestamp(data.get("coverage_end", ""))
    assert isinstance(data.get("committed_uptime_percent"), (int, float))
    assert isinstance(data.get("monthly_fee_cents"), int) and data["monthly_fee_cents"] >= 0
    assert isinstance(data.get("annual_credit_cap_cents"), int)
    assert data["annual_credit_cap_cents"] >= 0
    assert isinstance(data.get("reagent_guarantee"), bool)
    assert data.get("contract_state") in _enum_values(ContractState)
    assert isinstance(data.get("credits_issued_ytd_cents"), int)
    assert data["credits_issued_ytd_cents"] >= 0
    last_end = data.get("last_reconciliation_end")
    assert last_end is None or is_iso8601_timestamp(last_end)
    reason = data.get("terminated_reason")
    assert reason is None or reason == "AUTO_DECOMMISSION"


def assert_software_license(data: dict) -> None:
    _assert_common_fields(data, "SoftwareLicense")
    assert is_valid_uuid(data.get("account_id", ""))
    assert data.get("license_state") in _enum_values(LicenseState)
    activated = data.get("activated_at")
    assert activated is None or is_iso8601_timestamp(activated)
    pinned = data.get("pinned_sample_rate_cents")
    if pinned is not None:
        assert isinstance(pinned, dict)
        for tier, rate in SAMPLE_RATE_CENTS.items():
            assert pinned.get(tier) == rate
    ledger = data.get("credit_ledger")
    assert isinstance(ledger, list)
    for entry in ledger:
        assert entry.get("entry_type") in _enum_values(CreditEntryType)
        assert isinstance(entry.get("credits"), int)
        granted_on = entry.get("granted_on")
        assert granted_on is None or isinstance(granted_on, str)
        assert is_iso8601_timestamp(entry.get("created_at", ""))
    assert isinstance(data.get("credits_balance"), int)
    assert isinstance(data.get("samples_this_period"), int)
    assert data["samples_this_period"] >= 0
    assert isinstance(data.get("period_index"), int) and data["period_index"] >= 1


def assert_run_record(data: dict) -> None:
    """Run records are immutable event records: id + created_at only from the
    common set (PRD section 2.5) — version and updated_at must be absent."""
    assert is_valid_uuid(data.get("id", "")), "RunRecord.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "RunRecord.created_at must be ISO 8601"
    )
    assert "version" not in data, "RunRecord must not carry a version field"
    assert "updated_at" not in data, "RunRecord must not carry an updated_at field"
    assert is_valid_uuid(data.get("instrument_id", ""))
    assert is_valid_uuid(data.get("lot_id", ""))
    assert is_valid_uuid(data.get("license_id", ""))
    assert is_iso8601_timestamp(data.get("run_at", ""))
    assert data.get("run_mode") in _enum_values(RunMode)
    assert data.get("analysis_mode") in _enum_values(AnalysisMode)
    assert isinstance(data.get("samples_count"), int) and data["samples_count"] >= 0
    assert isinstance(data.get("output_gb"), (int, float))
    assert data.get("outcome") in _enum_values(RunOutcome)
    assert isinstance(data.get("credits_consumed"), int) and data["credits_consumed"] >= 0


def assert_transition_program(data: dict) -> None:
    _assert_common_fields(data, "TransitionProgram")
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("old_instrument_id", ""))
    assert is_valid_uuid(data.get("new_model_id", ""))
    assert is_iso8601_timestamp(data.get("enrollment_window_end", ""))
    assert data.get("program_state") in _enum_values(TransitionProgramState)
    assert isinstance(data.get("provisional_credit_cents"), int)
    assert data["provisional_credit_cents"] >= 0
    flags = data.get("condition_flags")
    assert isinstance(flags, list)
    assert all(f in _enum_values(ConditionFlag) for f in flags)
    final = data.get("final_credit_cents")
    assert final is None or (isinstance(final, int) and final >= 0)
    assert isinstance(data.get("created_by_user_id"), str)
    appraiser = data.get("appraised_by_user_id")
    assert appraiser is None or isinstance(appraiser, str)
    appraised_at = data.get("appraised_at")
    assert appraised_at is None or is_iso8601_timestamp(appraised_at)


def assert_supply_forecast(data: dict) -> None:
    _assert_common_fields(data, "SupplyForecast")
    assert is_valid_uuid(data.get("account_id", ""))
    lines = data.get("lines")
    assert isinstance(lines, list) and len(lines) >= 1
    for line in lines:
        assert isinstance(line.get("kit_code"), str) and line["kit_code"]
        assert is_iso8601_timestamp(line.get("week_start", ""))
        assert isinstance(line.get("quantity"), int) and line["quantity"] >= 1
    assert data.get("forecast_state") in _enum_values(ForecastState)
    variance = data.get("variance_lines")
    assert isinstance(variance, list)
    for v in variance:
        assert isinstance(v.get("kit_code"), str)
        assert is_iso8601_timestamp(v.get("week_start", ""))
        assert isinstance(v.get("forecast_quantity"), int)
        assert isinstance(v.get("actual_delivered_units"), int)
        assert isinstance(v.get("variance"), int)
        assert isinstance(v.get("coverage_optimistic_units"), int)
        assert isinstance(v.get("coverage_conservative_units"), int)


# ---------------------------------------------------------------------------
# Non-entity response payloads
# ---------------------------------------------------------------------------
def assert_uptime_reconciliation_result(data: dict) -> None:
    assert isinstance(data.get("downtime_minutes"), int) and data["downtime_minutes"] >= 0
    assert isinstance(data.get("uptime_percent"), (int, float))
    assert isinstance(data.get("credit_cents"), int) and data["credit_cents"] >= 0
    assert isinstance(data.get("credits_issued_ytd_cents"), int)
    assert data["credits_issued_ytd_cents"] >= 0


def assert_billing_close_result(data: dict) -> None:
    assert isinstance(data.get("billable_samples"), int) and data["billable_samples"] >= 0
    assert data.get("tier") in ("T1", "T2", "T3")
    assert isinstance(data.get("gross_cents"), int) and data["gross_cents"] >= 0
    assert isinstance(data.get("expired_credits"), int) and data["expired_credits"] >= 0
    assert isinstance(data.get("offset_credits"), int) and data["offset_credits"] >= 0
    assert isinstance(data.get("offset_cents"), int) and data["offset_cents"] >= 0
    assert isinstance(data.get("net_cents"), int) and data["net_cents"] >= 0
    assert isinstance(data.get("credits_balance"), int) and data["credits_balance"] >= 0
    assert isinstance(data.get("provisional_samples"), int)
    assert data["provisional_samples"] >= 0
    assert isinstance(data.get("provisional_gross_cents"), int)
    assert data["provisional_gross_cents"] >= 0


def assert_clock_set_result(data: dict) -> None:
    assert is_iso8601_timestamp(data.get("current_utc", ""))
    assert isinstance(data.get("lots_expired"), int) and data["lots_expired"] >= 0
    assert isinstance(data.get("contracts_expired"), int) and data["contracts_expired"] >= 0
    assert isinstance(data.get("transitions_expired"), int) and data["transitions_expired"] >= 0


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_kit_capacity(kit: dict) -> None:
    """capacity_gb = FLOW_CELL_BASE_GB[flow_cell] * CHEMISTRY_THROUGHPUT_MULT[chem],
    rounded half up to 1 decimal (PRD section 3.1)."""
    base = FLOW_CELL_BASE_GB[kit["flow_cell_version"]]
    mult = CHEMISTRY_THROUGHPUT_MULT[kit["chemistry_version"]]
    expected = float(
        Decimal(str(base)) * Decimal(str(mult))
    )
    expected = float(Decimal(str(expected)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    assert float(kit["capacity_gb"]) == pytest.approx(expected, abs=1e-9), (
        f"capacity_gb must be {expected} for "
        f"{kit['flow_cell_version']} x {kit['chemistry_version']}, got {kit['capacity_gb']}"
    )


def assert_lot_invariants(lot: dict) -> None:
    """available_units == quantity_units - reserved_units - consumed_units (PRD 3.4)."""
    expected = lot["quantity_units"] - lot["reserved_units"] - lot["consumed_units"]
    assert lot["available_units"] == expected, (
        f"available_units must equal quantity - reserved - consumed "
        f"({lot['quantity_units']} - {lot['reserved_units']} - {lot['consumed_units']}), "
        f"got {lot['available_units']}"
    )
    assert lot["available_units"] >= 0


def assert_license_invariants(license_data: dict) -> None:
    """credits_balance == sum of ledger entry credits, never negative (PRD 3.7)."""
    total = sum(entry["credits"] for entry in license_data.get("credit_ledger", []))
    assert license_data["credits_balance"] == total, (
        f"credits_balance must equal the ledger sum {total}, "
        f"got {license_data['credits_balance']}"
    )
    assert license_data["credits_balance"] >= 0, "credits_balance may never go negative"


def assert_program_invariants(program: dict) -> None:
    """Program money invariants (PRD section 3.3)."""
    assert program["delivered_spend_cents"] >= 0
    assert program["pipeline_spend_cents"] >= 0
    assert program["penalty_cents"] >= 0
    annual = program["committed_annual_reagent_cents"]
    term = program["term_months"]
    if (annual * term) % 12 == 0:
        assert program["committed_total_cents"] == annual * term // 12, (
            "committed_total_cents must equal committed_annual_reagent_cents "
            f"* term_months / 12 ({annual} * {term} / 12)"
        )
