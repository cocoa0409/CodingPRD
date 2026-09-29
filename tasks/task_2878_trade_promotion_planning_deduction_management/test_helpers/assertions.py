"""
Domain assertions for the Trade Promotion Deductions API.

The `assert_<entity>` helpers check the field set and the structural invariants
the PRD declares for one row; the invariant helpers check the conservation
identities of PRD section 2.9 and the derived-field rules of sections 2.10,
2.11, 3.2, 3.3 and 3.7.
"""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    ALLOWANCE_BAND_HIGH_FLOOR,
    ALLOWANCE_BAND_MID_FLOOR,
    ALLOWANCE_RATE_HIGH,
    ALLOWANCE_RATE_LOW,
    ALLOWANCE_RATE_MID,
    AUTO_CREDIT_HOLD_REASON_PREFIX,
    OVERSPENT_RATIO,
    OVERSPEND_WARNING_RATIO,
)
from .types import (
    AccrualEntryStatus,
    AllocationPosture,
    AllocationStatus,
    AuditStatus,
    ComplianceAuditStatus,
    DataStatus,
    DeductionStatus,
    DisputeStatus,
    DocumentStatus,
    EntryType,
    PerformanceFlag,
    ProgramStatus,
    PromotionLifecycleStatus,
    SpendStatus,
    TacticStatus,
    TradingStatus,
)

MONEY_TOLERANCE = 0.01
RATIO_TOLERANCE = 0.00005


# ─── Shared structural checks ─────────────────────────

def assert_common_fields(data: Dict[str, Any]) -> None:
    """Every resource but a volume fact carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data["id"]), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be an ISO 8601 UTC timestamp: {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be an ISO 8601 UTC timestamp: {data.get('updated_at')!r}"
    )
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be an integer starting at 1: {data.get('version')!r}"
    )


def assert_append_only_fields(data: Dict[str, Any]) -> None:
    """A volume fact row carries only id and created_at: no updated_at, no version."""
    assert is_valid_uuid(data["id"]), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be an ISO 8601 UTC timestamp: {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "a volume fact must not carry updated_at"
    assert "version" not in data, "a volume fact must not carry version"


def assert_money(value: Any, expected: float, label: str = "amount") -> None:
    """A monetary figure equals the expected USD value to the cent."""
    assert isinstance(value, (int, float)), f"{label} must be a number: {value!r}"
    assert value == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        f"{label} expected {expected:.2f}, got {value}"
    )


def assert_ratio(value: Any, expected: float, label: str = "ratio") -> None:
    """A ratio figure equals the expected 4-decimal value."""
    assert isinstance(value, (int, float)), f"{label} must be a number: {value!r}"
    assert value == pytest.approx(expected, abs=RATIO_TOLERANCE), (
        f"{label} expected {expected:.4f}, got {value}"
    )


def assert_two_decimal_places(value: float, label: str = "amount") -> None:
    """A monetary figure carries at most 2 decimal places."""
    assert round(float(value), 2) == pytest.approx(float(value), abs=1e-9), (
        f"{label} carries more than 2 decimal places: {value}"
    )


def assert_four_decimal_places(value: float, label: str = "ratio") -> None:
    """A ratio carries at most 4 decimal places."""
    assert round(float(value), 4) == pytest.approx(float(value), abs=1e-9), (
        f"{label} carries more than 4 decimal places: {value}"
    )


# ─── Entity assertions ────────────────────────────────

def assert_program(data: Dict[str, Any]) -> None:
    """A trade program row: declared inputs, status and the budget rollup."""
    assert_common_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["fiscal_year"], int)
    assert 2020 <= data["fiscal_year"] <= 2100
    assert data["status"] in [s.value for s in ProgramStatus]
    assert data["accrual_method_default"] in ("SHIPMENT", "CONSUMPTION")
    assert_two_decimal_places(data["total_budget_amount"], "total_budget_amount")
    assert_two_decimal_places(data["allocated_amount"], "allocated_amount")
    assert_two_decimal_places(data["unallocated_amount"], "unallocated_amount")
    assert data["total_budget_amount"] > 0
    assert_money(
        data["unallocated_amount"],
        round(data["total_budget_amount"] - data["allocated_amount"], 2),
        "unallocated_amount",
    )


def assert_brand(data: Dict[str, Any]) -> None:
    """A brand row, with `unit_margin` derived from list price minus cost."""
    assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert data["list_price_per_case"] > 0
    assert data["cogs_per_case"] >= 0
    assert data["cogs_per_case"] < data["list_price_per_case"]
    assert isinstance(data["baseline_units_per_week"], int)
    assert data["baseline_units_per_week"] >= 0
    assert_money(
        data["unit_margin"],
        round(data["list_price_per_case"] - data["cogs_per_case"], 2),
        "unit_margin",
    )


def assert_customer(data: Dict[str, Any]) -> None:
    """A retail customer row with both state axes and the deduction rollups."""
    assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert data["channel"] in ("GROCERY", "MASS", "CLUB", "DOLLAR")
    assert data["deduction_validation_policy"] in ("EVIDENCE_BASED", "AGREEMENT_CAP")
    assert data["trading_status"] in [s.value for s in TradingStatus]
    assert data["audit_status"] in [s.value for s in AuditStatus]
    assert isinstance(data["compliance_penalty_points"], int)
    assert data["compliance_penalty_points"] >= 0
    assert_two_decimal_places(data["open_deduction_amount"], "open_deduction_amount")
    assert_two_decimal_places(data["write_off_ytd_amount"], "write_off_ytd_amount")


def assert_allocation(data: Dict[str, Any]) -> None:
    """A budget allocation row with its ledger rollup and the two axes."""
    assert_common_fields(data)
    for key in ("program_id", "customer_id", "brand_id"):
        assert is_valid_uuid(data[key]), f"{key} must be a UUID"
    assert data["event_type"] in ("SEASONAL", "EVERYDAY", "NEW_ITEM")
    assert data["status"] in [s.value for s in AllocationStatus]
    assert data["posture"] in [p.value for p in AllocationPosture]
    assert data["planned_amount"] > 0
    assert isinstance(data["baseline_units"], int) and data["baseline_units"] >= 0
    assert isinstance(data["planned_incremental_units"], int)
    assert data["planned_incremental_units"] >= 0
    assert isinstance(data["overspend_event_count"], int)
    assert data["overspend_event_count"] >= 0
    assert_allocation_identities(data)


def assert_promotion(data: Dict[str, Any]) -> None:
    """A promotion row: planning figures, accrual ledger and live spend view."""
    assert_common_fields(data)
    for key in ("allocation_id", "customer_id", "brand_id"):
        assert is_valid_uuid(data[key]), f"{key} must be a UUID"
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert data["window_end"] > data["window_start"]
    assert data["accrual_method"] in ("SHIPMENT", "CONSUMPTION")
    assert data["lifecycle_status"] in [s.value for s in PromotionLifecycleStatus]
    assert data["spend_status"] in [s.value for s in SpendStatus]
    assert data["performance_flag"] in [f.value for f in PerformanceFlag]
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0
    assert isinstance(data["commitment_verified"], bool)
    assert isinstance(data["committed_units"], int)
    assert_two_decimal_places(data["planned_total_spend"], "planned_total_spend")
    assert_four_decimal_places(data["spend_ratio"], "spend_ratio")
    assert_promotion_pricing_chain(data)
    assert_accrual_ledger_identity(data)
    assert_spend_status_band(data)


def assert_tactic(data: Dict[str, Any]) -> None:
    """A tactic line row with its exclusive money field and derived figures."""
    assert_common_fields(data)
    assert is_valid_uuid(data["promotion_id"])
    assert data["tactic_type"] in ("TPR", "DISPLAY", "FEATURE")
    assert data["status"] in [s.value for s in TacticStatus]
    assert isinstance(data["planned_units"], int) and data["planned_units"] >= 0
    assert data["window_end"] > data["window_start"]
    assert isinstance(data["week_count"], int) and data["week_count"] > 0
    if data["tactic_type"] == "TPR":
        assert data["rate_per_case"] is not None, "a TPR line must carry rate_per_case"
        assert data.get("fixed_fee") is None, "a TPR line must omit fixed_fee"
        assert data["rate_per_case"] > 0
        assert_money(
            data["line_planned_spend"],
            round(data["planned_units"] * data["rate_per_case"] + 1e-9, 2),
            "line_planned_spend",
        )
    else:
        assert data["fixed_fee"] is not None, "a fixed-fee line must carry fixed_fee"
        assert data.get("rate_per_case") is None, "a fixed-fee line must omit rate_per_case"
        assert data["fixed_fee"] > 0
        assert_money(data["line_planned_spend"], round(data["fixed_fee"], 2),
                     "line_planned_spend")


def assert_document(data: Dict[str, Any]) -> None:
    """A retailer document row with its class/type pairing."""
    assert_common_fields(data)
    assert is_valid_uuid(data["promotion_id"])
    assert data["doc_class"] in ("COMMITMENT", "EVIDENCE")
    assert data["doc_type"] in (
        "SIGNED_LOI", "PORTAL_ACK", "SCAN_DATA", "DISPLAY_PHOTO", "AD_TEARSHEET"
    )
    assert data["covers_tactic_type"] in ("TPR", "DISPLAY", "FEATURE", "ALL")
    assert data["status"] in [s.value for s in DocumentStatus]
    assert is_iso8601_timestamp(data["received_at"])
    assert isinstance(data["units_verified"], int) and data["units_verified"] >= 0
    if data["doc_class"] == "COMMITMENT":
        assert data["doc_type"] in ("SIGNED_LOI", "PORTAL_ACK")
        assert data["units_verified"] == 0, "a commitment document substantiates no cases"
    else:
        assert data["doc_type"] in ("SCAN_DATA", "DISPLAY_PHOTO", "AD_TEARSHEET")


def assert_volume_fact(data: Dict[str, Any]) -> None:
    """A volume fact row: append-only, so no updated_at and no version."""
    assert_append_only_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["brand_id"])
    assert data["fact_type"] in ("SHIPMENT", "CONSUMPTION")
    assert data["source"] in ("EDI_852", "EDI_856", "MANUAL")
    assert isinstance(data["units"], int) and data["units"] >= 0
    assert isinstance(data["period_start"], str)


def assert_accrual_entry(data: Dict[str, Any]) -> None:
    """A ledger entry row: accrual or its compensating reversal."""
    assert_common_fields(data)
    assert is_valid_uuid(data["promotion_id"])
    assert data["entry_type"] in [t.value for t in EntryType]
    assert data["status"] in [s.value for s in AccrualEntryStatus]
    assert data["method"] in ("SHIPMENT", "CONSUMPTION")
    assert isinstance(data["fact_units"], int) and data["fact_units"] >= 0
    assert_two_decimal_places(data["amount"], "amount")
    assert isinstance(data["tactic_line_amounts"], list)
    for line in data["tactic_line_amounts"]:
        assert is_valid_uuid(line["tactic_id"])
        assert_two_decimal_places(line["amount"], "tactic_line_amounts[].amount")
    if data["entry_type"] == "REVERSAL":
        assert data["status"] == "POSTED", "a reversal entry stays POSTED forever"
        assert is_valid_uuid(data["reverses_entry_id"])
        assert data["fact_units"] == 0
        assert data["tactic_line_amounts"] == []
    else:
        assert data["reverses_entry_id"] is None
        assert data["reversal_reason"] is None


def assert_deduction(data: Dict[str, Any]) -> None:
    """A deduction row with its valuation figures."""
    assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["claim_reference"], str)
    assert 1 <= len(data["claim_reference"]) <= 60
    assert data["claimed_amount"] > 0
    assert_two_decimal_places(data["claimed_amount"], "claimed_amount")
    assert data["status"] in [s.value for s in DeductionStatus]
    if data["status"] in ("VALIDATED", "SETTLED"):
        assert data["validation_basis"] in ("EVIDENCE_BASED", "AGREEMENT_CAP")
        assert_money(
            data["validated_amount"],
            min(data["claimed_amount"], data["entitled_amount"]),
            "validated_amount",
        )
        assert_money(
            data["variance_amount"],
            round(data["claimed_amount"] - data["validated_amount"], 2),
            "variance_amount",
        )


def assert_dispute(data: Dict[str, Any]) -> None:
    """A dispute row with its live aging figure and bounded round counter."""
    assert_common_fields(data)
    assert is_valid_uuid(data["deduction_id"])
    assert data["reason_code"] in (
        "NO_AGREEMENT", "NO_EVIDENCE", "RATE_MISMATCH", "DUPLICATE_CLAIM"
    )
    assert data["status"] in [s.value for s in DisputeStatus]
    assert data["disputed_amount"] > 0
    assert_two_decimal_places(data["disputed_amount"], "disputed_amount")
    assert is_iso8601_timestamp(data["opened_at"])
    assert isinstance(data["opened_by_user_id"], str) and data["opened_by_user_id"]
    assert isinstance(data["round_count"], int) and 0 <= data["round_count"] <= 2
    assert isinstance(data["aging_days"], int) and data["aging_days"] >= 0


def assert_post_event_analysis(data: Dict[str, Any]) -> None:
    """A post-event analysis row with its lift, cannibalisation and ROI chain."""
    assert_common_fields(data)
    assert is_valid_uuid(data["promotion_id"])
    assert data["baseline_method"] in ("TRAILING", "SEASONAL")
    assert data["data_status"] in [s.value for s in DataStatus]
    assert is_iso8601_timestamp(data["computed_at"])
    assert isinstance(data["promo_consumption_units"], int)
    assert isinstance(data["post_period_units"], int)
    assert_two_decimal_places(data["net_spend"], "net_spend")
    assert data["cannibalization_units"] >= 0
    if data["data_status"] == "INSUFFICIENT_DATA":
        assert data["roi"] is None, "an analysis without promoted-window facts is unrated"
    if data["roi"] is not None:
        assert_four_decimal_places(data["roi"], "roi")
    assert_money(
        data["net_incremental_units"],
        round(data["lift_units"] - data["cannibalization_units"], 2),
        "net_incremental_units",
    )


def assert_compliance_audit(data: Dict[str, Any]) -> None:
    """A compliance audit row with its findings tally."""
    assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert data["scope_end"] > data["scope_start"]
    assert data["status"] in [s.value for s in ComplianceAuditStatus]
    assert isinstance(data["findings_count"], int) and data["findings_count"] >= 0
    assert_two_decimal_places(data["recovery_claim_amount"], "recovery_claim_amount")
    assert isinstance(data["auditor_user_id"], str) and data["auditor_user_id"]
    if data["status"] == "FINDINGS_ISSUED":
        assert is_iso8601_timestamp(data["issued_at"])
    else:
        assert data["issued_at"] is None


def assert_activation_run(data: Dict[str, Any]) -> None:
    """The operations checkpoint response: the run instant and four id lists."""
    assert is_iso8601_timestamp(data["run_at"])
    for key in ("promotions_activated", "promotions_ended",
                "tactics_activated", "tactics_completed"):
        assert isinstance(data[key], list), f"{key} must be a list"
        for entity_id in data[key]:
            assert is_valid_uuid(entity_id), f"{key} must carry entity identifiers"


def assert_aging_run(data: Dict[str, Any]) -> None:
    """The aging sweep response: the run instant, the scan count and two lists."""
    assert is_iso8601_timestamp(data["run_at"])
    assert isinstance(data["disputes_scanned"], int) and data["disputes_scanned"] >= 0
    for key in ("disputes_escalated", "customers_penalized"):
        assert isinstance(data[key], list), f"{key} must be a list"
        for entity_id in data[key]:
            assert is_valid_uuid(entity_id), f"{key} must carry entity identifiers"


# ─── Invariant checkers ───────────────────────────────

def expected_allowance_rate(subtotal: float) -> float:
    """The off-invoice band read against the tactic subtotal and nothing else."""
    if subtotal >= ALLOWANCE_BAND_HIGH_FLOOR:
        return ALLOWANCE_RATE_HIGH
    if subtotal >= ALLOWANCE_BAND_MID_FLOOR:
        return ALLOWANCE_RATE_MID
    return ALLOWANCE_RATE_LOW


def assert_promotion_pricing_chain(promotion: Dict[str, Any]) -> None:
    """
    The four-step chain: subtotal, then band, then allowance, then total.

    The band is chosen from `tactic_subtotal_amount`, never from
    `planned_total_spend`.
    """
    subtotal = promotion["tactic_subtotal_amount"]
    rate = promotion["allowance_rate"]
    assert rate == pytest.approx(expected_allowance_rate(subtotal), abs=1e-9), (
        f"allowance_rate {rate} does not match the band of subtotal {subtotal}"
    )
    assert_money(
        promotion["off_invoice_allowance_amount"],
        round(subtotal * rate + 1e-9, 2),
        "off_invoice_allowance_amount",
    )
    assert_money(
        promotion["planned_total_spend"],
        round(subtotal + promotion["off_invoice_allowance_amount"], 2),
        "planned_total_spend",
    )


def assert_accrual_ledger_identity(promotion: Dict[str, Any]) -> None:
    """`gross_accrued_amount` = reversed + consumed + `accrued_balance`."""
    assert_money(
        promotion["gross_accrued_amount"],
        round(
            promotion["reversed_accrual_amount"]
            + promotion["consumed_deduction_amount"]
            + promotion["accrued_balance"],
            2,
        ),
        "gross_accrued_amount",
    )
    assert_money(
        promotion["recognized_spend_amount"],
        max(
            round(promotion["gross_accrued_amount"] - promotion["reversed_accrual_amount"], 2),
            round(promotion["consumed_deduction_amount"], 2),
        ),
        "recognized_spend_amount",
    )


def assert_spend_status_band(promotion: Dict[str, Any]) -> None:
    """`spend_status` follows the exact boundaries on `spend_ratio`."""
    ratio = promotion["spend_ratio"]
    if promotion["planned_total_spend"] == pytest.approx(0.0, abs=1e-9):
        assert_ratio(ratio, 0.0, "spend_ratio")
        assert promotion["spend_status"] == SpendStatus.WITHIN_BUDGET.value
        return
    if ratio > OVERSPENT_RATIO + 1e-9:
        expected = SpendStatus.OVERSPENT.value
    elif ratio >= OVERSPEND_WARNING_RATIO - 1e-9:
        expected = SpendStatus.OVERSPEND_WARNING.value
    else:
        expected = SpendStatus.WITHIN_BUDGET.value
    assert promotion["spend_status"] == expected, (
        f"spend_ratio {ratio} should give spend_status {expected}, "
        f"got {promotion['spend_status']}"
    )


def assert_allocation_identities(allocation: Dict[str, Any]) -> None:
    """
    The two conservation identities of the allocation ledger.

    `planned_amount` = `committed_amount` + `available_amount`, and
    `planned_incremental_units` = `committed_units` + `unreserved_units`.
    """
    assert_money(
        allocation["planned_amount"],
        round(allocation["committed_amount"] + allocation["available_amount"], 2),
        "planned_amount",
    )
    assert allocation["planned_incremental_units"] == (
        allocation["committed_units"] + allocation["unreserved_units"]
    ), (
        "planned_incremental_units must equal committed_units + unreserved_units: "
        f"{allocation['planned_incremental_units']} != "
        f"{allocation['committed_units']} + {allocation['unreserved_units']}"
    )


def assert_posture_precedence(allocation: Dict[str, Any], program_status: str) -> None:
    """FROZEN outranks RESTRICTED outranks OPEN."""
    if program_status == ProgramStatus.LOCKED.value:
        expected = AllocationPosture.FROZEN.value
    elif allocation["overspend_event_count"] >= 1:
        expected = AllocationPosture.RESTRICTED.value
    else:
        expected = AllocationPosture.OPEN.value
    assert allocation["posture"] == expected, (
        f"posture expected {expected}, got {allocation['posture']}"
    )


def assert_auto_credit_hold_reason(customer: Dict[str, Any]) -> None:
    """An automatic hold names the penalty score that triggered it."""
    reason = customer["credit_hold_reason"]
    assert isinstance(reason, str), "an automatic hold must record a reason"
    expected = f"{AUTO_CREDIT_HOLD_REASON_PREFIX} {customer['compliance_penalty_points']}"
    assert reason == expected, f"credit_hold_reason expected {expected!r}, got {reason!r}"


def assert_performance_flag_from_roi(analysis: Dict[str, Any], promotion: Dict[str, Any]) -> None:
    """A null roi gives UNRATED, below 1.0000 UNDERPERFORMING, at or above ON_TRACK."""
    roi = analysis["roi"]
    if roi is None:
        expected = PerformanceFlag.UNRATED.value
    elif roi < 1.0 - 1e-9:
        expected = PerformanceFlag.UNDERPERFORMING.value
    else:
        expected = PerformanceFlag.ON_TRACK.value
    assert promotion["performance_flag"] == expected, (
        f"roi {roi} should give performance_flag {expected}, "
        f"got {promotion['performance_flag']}"
    )


def assert_ordered_by(rows: List[Dict[str, Any]], key: str, descending: bool = False) -> None:
    """A list page is ordered by the declared sort key."""
    values = [row[key] for row in rows]
    expected = sorted(values, reverse=descending)
    assert values == expected, f"rows are not ordered by {key}: {values}"


def assert_tactic_line_breakdown(entry: Dict[str, Any], expected_pairs: List[Any]) -> None:
    """The per-line breakdown pairs each tactic with its own rounded component."""
    actual = [(line["tactic_id"], round(float(line["amount"]), 2))
              for line in entry["tactic_line_amounts"]]
    normalised = [(tactic_id, round(float(amount), 2))
                  for tactic_id, amount in expected_pairs]
    assert actual == normalised, (
        f"tactic_line_amounts expected {normalised}, got {actual}"
    )


def assert_field_absent(data: Dict[str, Any], field: str) -> None:
    """A field the PRD does not declare on this row is not present."""
    assert field not in data, f"{field} must not appear on this resource"


def assert_null_fields(data: Dict[str, Any], fields: List[str]) -> None:
    """A set of fields the PRD declares null at this point are all null."""
    for field in fields:
        assert data[field] is None, f"{field} must be null here, got {data[field]!r}"


def assert_version_is(data: Dict[str, Any], expected: int, label: str = "version") -> None:
    """A row's version carries exactly the expected value."""
    assert data["version"] == expected, (
        f"{label} expected {expected}, got {data['version']}"
    )


def get_by_id(rows: List[Dict[str, Any]], entity_id: str) -> Optional[Dict[str, Any]]:
    """Find one row of a list page by identifier."""
    for row in rows:
        if row.get("id") == entity_id:
            return row
    return None
