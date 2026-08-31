"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ApprovalStatus, BandResult, ClaimStatus, ConditionGrade, CoreUnitStatus,
    CreditNoteKind, CreditNoteStatus, InspectionStatus, InstallationStatus,
    IsoZone, PartLineStatus, ReservationStatus, WorkStatus,
)

_GRADES = [g.value for g in ConditionGrade]


def assert_common_mutable_fields(data: dict, label: str = "record"):
    """Every mutable record carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID with no prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1"
    )


def assert_append_only_fields(data: dict, label: str = "record"):
    """Immutable observations carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID with no prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{label} must not carry updated_at"
    assert "version" not in data, f"{label} must not carry version"


def assert_customer(data: dict):
    assert_common_mutable_fields(data, "Customer")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["account_code"], str) and 1 <= len(data["account_code"]) <= 32
    for field in (
        "core_credit_balance_cents", "warranty_credit_balance_cents",
        "manual_credit_balance_cents", "total_credit_balance_cents",
    ):
        assert isinstance(data[field], int), f"Customer.{field} must be integer cents"
    assert_customer_ledger_invariants(data)


def assert_customer_ledger_invariants(data: dict):
    """total_credit_balance_cents is the sum of the three streams."""
    expected = (
        data["core_credit_balance_cents"]
        + data["warranty_credit_balance_cents"]
        + data["manual_credit_balance_cents"]
    )
    assert data["total_credit_balance_cents"] == expected, (
        "total_credit_balance_cents must equal the sum of the core, warranty and "
        f"manual streams: expected {expected}, got {data['total_credit_balance_cents']}"
    )


def assert_customer_asset(data: dict):
    assert_common_mutable_fields(data, "CustomerAsset")
    assert data["criticality"] in ("CRITICAL", "STANDARD")
    assert data["duty_class"] in ("CONTINUOUS", "INTERMITTENT", "STANDBY")
    assert isinstance(data["asset_tag"], str) and data["asset_tag"]
    assert isinstance(data["site_code"], str) and data["site_code"]


def assert_clearance_standard(data: dict):
    assert_common_mutable_fields(data, "ClearanceStandard")
    assert isinstance(data["model_code"], str) and data["model_code"]
    assert isinstance(data["base_core_value_cents"], int) and data["base_core_value_cents"] >= 0
    assert isinstance(data["max_rebuild_count"], int) and data["max_rebuild_count"] >= 0
    assert data["warranty_hours"] > 0 and data["warranty_months"] > 0
    assert isinstance(data["cleanroom_required"], bool)
    assert isinstance(data["required_feature_codes"], list) and data["required_feature_codes"]
    assert isinstance(data["feature_bands"], list) and data["feature_bands"]
    codes = [b["feature_code"] for b in data["feature_bands"]]
    assert len(codes) == len(set(codes)), "feature_code must be unique within feature_bands"
    for band in data["feature_bands"]:
        assert band["max_um"] > band["min_um"], "max_um must be strictly greater than min_um"
        assert 0 <= band["deduction_pct"] <= 1
        assert band["weight"] > 0
    for code in data["required_feature_codes"]:
        assert code in codes, "every required_feature_codes entry must appear in feature_bands"


def assert_bench(data: dict):
    assert_common_mutable_fields(data, "Bench")
    assert isinstance(data["bench_code"], str) and data["bench_code"]
    assert isinstance(data["parallel_slots"], int) and data["parallel_slots"] >= 1
    assert isinstance(data["cleanroom"], bool)
    assert isinstance(data["committed_minutes"], int) and data["committed_minutes"] >= 0


def assert_core_unit(data: dict):
    assert_common_mutable_fields(data, "CoreUnit")
    assert data["status"] in [s.value for s in CoreUnitStatus]
    assert data["declared_condition_grade"] in _GRADES
    assert data["condition_grade"] is None or data["condition_grade"] in _GRADES
    assert isinstance(data["rebuild_count"], int) and data["rebuild_count"] >= 0
    assert isinstance(data["provisional_core_credit_cents"], int)
    assert data["provisional_core_credit_cents"] >= 0
    assert data["final_core_credit_cents"] is None or data["final_core_credit_cents"] >= 0
    assert isinstance(data["model_code"], str) and data["model_code"]


def assert_rebuild_order(data: dict):
    assert_common_mutable_fields(data, "RebuildOrder")
    assert data["work_status"] in [s.value for s in WorkStatus]
    assert data["approval_status"] in [s.value for s in ApprovalStatus]
    assert isinstance(data["expedited"], bool)
    assert isinstance(data["part_revision_counter"], int) and data["part_revision_counter"] >= 0
    assert data["labor_hours"] > 0


def assert_quoted_order_arithmetic(order: dict):
    """The eight-step pricing chain must hold together on a quoted order."""
    assert order["pre_credit_subtotal_cents"] == (
        order["parts_subtotal_cents"] + order["labor_cents"]
    ), "pre_credit_subtotal_cents must be the parts subtotal plus the labour"
    assert order["gross_total_cents"] == (
        order["pre_credit_subtotal_cents"] + order["expedite_surcharge_cents"]
    ), "gross_total_cents must be the pre-credit subtotal plus the surcharge"
    assert order["quote_total_cents"] == (
        order["gross_total_cents"] - order["core_credit_applied_cents"]
    ), "quote_total_cents must be the gross total less the applied credit"


def assert_inspection(data: dict):
    assert_common_mutable_fields(data, "Inspection")
    assert data["status"] in [s.value for s in InspectionStatus]
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    if data["remaining_life_score"] is not None:
        assert 0 <= data["remaining_life_score"] <= 100
    assert data["remaining_life_grade"] is None or data["remaining_life_grade"] in _GRADES


def assert_measurement(data: dict):
    assert_append_only_fields(data, "Measurement")
    assert data["band_result"] in [b.value for b in BandResult]
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert 0 <= data["deviation_ratio"] <= 1
    assert 0 <= data["feature_score"] <= 100
    assert abs(data["feature_score"] - 100 * (1 - data["deviation_ratio"])) < 0.0001, (
        "feature_score must be one hundred multiplied by one minus deviation_ratio"
    )


def assert_part_line(data: dict):
    assert_common_mutable_fields(data, "PartLine")
    assert data["approval_status"] in [s.value for s in PartLineStatus]
    assert data["source_class"] in ("OEM", "AFTERMARKET")
    assert data["qty"] >= 1 and data["unit_cost_cents"] >= 0
    assert data["line_total_cents"] == data["qty"] * data["unit_cost_cents"], (
        "line_total_cents must be the quantity multiplied by the unit cost"
    )


def assert_vibration_reading(data: dict):
    assert_append_only_fields(data, "VibrationReading")
    assert data["iso_zone"] in [z.value for z in IsoZone]
    assert data["baseline_amplitude_g"] > 0
    assert data["defect_ratio_outer"] >= 0 and data["defect_ratio_inner"] >= 0


def assert_bench_reservation(data: dict):
    assert_common_mutable_fields(data, "BenchReservation")
    assert data["status"] in [s.value for s in ReservationStatus]
    assert isinstance(data["window_minutes"], int) and data["window_minutes"] >= 0
    assert isinstance(data["queue_if_full"], bool)


def assert_installation(data: dict):
    assert_common_mutable_fields(data, "Installation")
    assert data["status"] in [s.value for s in InstallationStatus]
    assert is_iso8601_timestamp(data["in_service_start_at"])
    assert data["run_hours"] >= 0
    assert data["warranty_hours_snapshot"] > 0 and data["warranty_months_snapshot"] > 0
    assert isinstance(data["covered_base_cents_snapshot"], int)


def assert_warranty_claim(data: dict):
    assert_common_mutable_fields(data, "WarrantyClaim")
    assert data["status"] in [s.value for s in ClaimStatus]
    assert data["governing_basis"] in ("HOURS", "CALENDAR", "GOODWILL")
    assert isinstance(data["elapsed_days"], int) and data["elapsed_days"] >= 0
    assert 0 <= data["hours_consumed_fraction"] <= 1
    assert 0 <= data["calendar_consumed_fraction"] <= 1
    assert 0 <= data["remaining_fraction"] <= 1
    assert isinstance(data["pro_rata_credit_cents"], int)


def assert_credit_note(data: dict):
    assert_common_mutable_fields(data, "CreditNote")
    assert data["kind"] in [k.value for k in CreditNoteKind]
    assert data["status"] in [s.value for s in CreditNoteStatus]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    if data["kind"] != "CORE_EXCHANGE":
        assert data["core_unit_id"] is None, "core_unit_id is set only on CORE_EXCHANGE notes"
    if data["kind"] != "WARRANTY_PRORATA":
        assert data["warranty_claim_id"] is None, (
            "warranty_claim_id is set only on WARRANTY_PRORATA notes"
        )
    if data["status"] == "POSTED":
        assert data["voided_at"] is None and data["void_reason"] is None


def assert_ledger_matches_notes(customer: dict, notes: list):
    """Recompute the four balances from the surviving POSTED notes."""
    def total(kind):
        return sum(n["amount_cents"] for n in notes
                   if n["status"] == "POSTED" and n["kind"] == kind)

    assert customer["core_credit_balance_cents"] == total("CORE_EXCHANGE")
    assert customer["warranty_credit_balance_cents"] == total("WARRANTY_PRORATA")
    assert customer["manual_credit_balance_cents"] == total("MANUAL_ADJUSTMENT")
    assert_customer_ledger_invariants(customer)
