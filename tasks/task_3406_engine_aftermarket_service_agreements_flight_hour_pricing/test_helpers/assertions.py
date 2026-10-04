"""Entity assertions and domain invariant checkers.

assert_<entity>(data) validates the server-returned shape of each resource:
field presence, primitive types, enum membership, common-fields contract
(PRD §2.5 — append-only Directive and RecognitionSnapshot carry only id and
created_at and MUST NOT expose updated_at or version).
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)


# ---------------------------------------------------------------------------
# Shared shape helpers
# ---------------------------------------------------------------------------

def _assert_common_fields(data: dict, entity_label: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be an integer >= 1"
    )


def _assert_append_only_fields(data: dict, entity_label: str):
    """Append-only records (PRD §2.5): only id + created_at; no updated_at,
    no version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be an ISO 8601 timestamp"
    )
    assert "updated_at" not in data, f"{entity_label} must not expose updated_at"
    assert "version" not in data, f"{entity_label} must not expose version"


def _assert_nullable_timestamp(data: dict, field: str, entity_label: str):
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), (
        f"{entity_label}.{field} must be null or an ISO 8601 timestamp"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_operator(data: dict):
    _assert_common_fields(data, "Operator")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["iata_code"], str) and len(data["iata_code"]) == 2
    assert data["credit_rating"] in ["A", "B", "C"]


def assert_engine(data: dict):
    _assert_common_fields(data, "Engine")
    assert is_valid_uuid(data.get("operator_id", "")), "Engine.operator_id must be a UUID"
    assert isinstance(data["esn"], str) and len(data["esn"]) > 0
    assert isinstance(data["engine_model"], str) and len(data["engine_model"]) > 0
    assert data["base_severity_tier"] in ["BENIGN", "MODERATE", "HARSH"]
    assert isinstance(data["cumulative_flight_hours"], (int, float))
    assert data["cumulative_flight_hours"] >= 0
    assert isinstance(data["cumulative_cycles"], int) and data["cumulative_cycles"] >= 0
    assert isinstance(data["llp_remaining_cycles"], int) and data["llp_remaining_cycles"] >= 0
    assert data.get("agreement_id") is None or is_valid_uuid(data["agreement_id"])
    _assert_nullable_timestamp(data, "enrolled_at", "Engine")
    _assert_nullable_timestamp(data, "projected_next_removal_date", "Engine")
    assert data["status"] in ["IN_SERVICE", "IN_SHOP"]


def assert_service_agreement(data: dict):
    _assert_common_fields(data, "ServiceAgreement")
    assert isinstance(data["contract_ref"], str) and len(data["contract_ref"]) > 0
    assert isinstance(data["base_rate_per_fh_usd"], (int, float))
    assert data["base_rate_per_fh_usd"] > 0
    assert isinstance(data["escalation_pct"], (int, float)) and data["escalation_pct"] >= 0
    assert is_iso8601_timestamp(data["escalation_anchor_date"])
    assert is_iso8601_timestamp(data["start_date"])
    assert is_iso8601_timestamp(data["end_date"])
    assert isinstance(data["allowed_sourcing_classes"], list)
    assert len(data["allowed_sourcing_classes"]) > 0
    assert set(data["allowed_sourcing_classes"]) <= {"NEW", "REPAIRED", "USM"}
    assert isinstance(data["max_workscope_cost_usd"], (int, float))
    assert data["max_workscope_cost_usd"] > 0
    assert data["status"] in ["DRAFT", "ACTIVE", "RENEGOTIATION", "EXPIRED"]
    assert isinstance(data["billed_to_date_usd"], (int, float))
    assert data["billed_to_date_usd"] >= 0
    assert isinstance(data["enrolled_engine_count"], int)
    assert data["enrolled_engine_count"] >= 0


def assert_flight_hour_report(data: dict):
    _assert_common_fields(data, "FlightHourReport")
    assert is_valid_uuid(data.get("engine_id", "")), "FlightHourReport.engine_id must be a UUID"
    period = data["period"]
    assert isinstance(period, str) and len(period) == 7 and period[4] == "-", (
        "period must be a YYYY-MM calendar-month string"
    )
    assert isinstance(data["flight_hours"], (int, float)) and data["flight_hours"] >= 0
    assert isinstance(data["cycles"], int) and data["cycles"] >= 0
    assert data["observed_severity"] in ["BENIGN", "MODERATE", "HARSH"]
    assert data["status"] in ["SUBMITTED", "VERIFIED"]
    _assert_nullable_timestamp(data, "verified_at", "FlightHourReport")


def assert_billing_line_item(line: dict):
    assert is_valid_uuid(line.get("engine_id", "")), "line.engine_id must be a UUID"
    assert isinstance(line["hours"], (int, float)) and line["hours"] >= 0
    assert isinstance(line["effective_rate_per_fh_usd"], (int, float))
    assert line["effective_rate_per_fh_usd"] > 0
    assert isinstance(line["line_amount_usd"], (int, float))
    assert line["line_amount_usd"] >= 0
    assert_cost_precision(line["line_amount_usd"])


def assert_billing_statement(data: dict):
    _assert_common_fields(data, "BillingStatement")
    assert is_valid_uuid(data.get("agreement_id", "")), (
        "BillingStatement.agreement_id must be a UUID"
    )
    period = data["period"]
    assert isinstance(period, str) and len(period) == 7 and period[4] == "-", (
        "period must be a YYYY-MM calendar-month string"
    )
    assert data["status"] in ["ISSUED", "SETTLED"]
    assert isinstance(data["line_items"], list)
    for line in data["line_items"]:
        assert_billing_line_item(line)
    assert isinstance(data["provisional_total_usd"], (int, float))
    assert data["provisional_total_usd"] >= 0
    assert_cost_precision(data["provisional_total_usd"])
    if data["status"] == "ISSUED":
        assert data.get("final_total_usd") is None, "final_total_usd is null until settled"
        assert data.get("adjustment_usd") is None, "adjustment_usd is null until settled"
    else:
        assert isinstance(data["final_total_usd"], (int, float))
        assert isinstance(data["adjustment_usd"], (int, float))
        assert_cost_precision(data["final_total_usd"])
        assert_cost_precision(data["adjustment_usd"])


def assert_shop_visit(data: dict):
    _assert_common_fields(data, "ShopVisit")
    assert is_valid_uuid(data.get("engine_id", "")), "ShopVisit.engine_id must be a UUID"
    assert is_iso8601_timestamp(data["planned_induction_date"])
    assert is_iso8601_timestamp(data["forecast_induction_date"])
    assert data["forecast_method"] in ["CYCLE_BASED", "CALENDAR_BASED"]
    _assert_nullable_timestamp(data, "actual_induction_date", "ShopVisit")
    _assert_nullable_timestamp(data, "completion_date", "ShopVisit")
    assert data["status"] in ["SCHEDULED", "INDUCTED", "COMPLETED"]
    assert isinstance(data["projected_cost_usd"], (int, float))
    assert data["projected_cost_usd"] > 0
    assert isinstance(data["committed_parts_cost_usd"], (int, float))
    assert data["committed_parts_cost_usd"] >= 0
    assert_cost_precision(data["committed_parts_cost_usd"])


def assert_workscope_item(item: dict):
    assert isinstance(item["item_code"], str) and len(item["item_code"]) > 0
    assert item["item_type"] in [
        "MANDATORY_DIRECTIVE",
        "LLP_REPLACEMENT",
        "MODULE_OVERHAUL",
        "INSPECTION",
    ]
    assert isinstance(item["estimated_cost_usd"], (int, float))
    assert item["estimated_cost_usd"] >= 0
    assert isinstance(item["restores_cycles"], int) and item["restores_cycles"] >= 0
    if item["item_type"] == "MANDATORY_DIRECTIVE":
        assert isinstance(item.get("directive_ref"), str) and len(item["directive_ref"]) > 0, (
            "a MANDATORY_DIRECTIVE item must carry its directive_ref"
        )
    else:
        assert item.get("directive_ref") is None, (
            "directive_ref must be null unless the item is a MANDATORY_DIRECTIVE"
        )


def assert_workscope(data: dict):
    _assert_common_fields(data, "Workscope")
    assert is_valid_uuid(data.get("shop_visit_id", "")), "Workscope.shop_visit_id must be a UUID"
    assert isinstance(data["scope_version"], int) and data["scope_version"] >= 1
    assert data["status"] in ["SUBMITTED", "APPROVED", "REJECTED", "REOPENED", "SUPERSEDED"]
    assert isinstance(data["items"], list)
    for item in data["items"]:
        assert_workscope_item(item)
    assert isinstance(data["total_cost_usd"], (int, float))
    assert data["total_cost_usd"] >= 0
    assert_cost_precision(data["total_cost_usd"])
    assert isinstance(data["restores_llp_cycles"], int) and data["restores_llp_cycles"] >= 0
    _assert_nullable_timestamp(data, "decided_at", "Workscope")


def assert_part_requisition(data: dict):
    _assert_common_fields(data, "PartRequisition")
    assert is_valid_uuid(data.get("workscope_id", "")), (
        "PartRequisition.workscope_id must be a UUID"
    )
    assert isinstance(data["part_number"], str) and len(data["part_number"]) > 0
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["list_price_usd"], (int, float)) and data["list_price_usd"] > 0
    assert data["requested_class"] in ["NEW", "REPAIRED", "USM"]
    assert is_iso8601_timestamp(data["required_by_date"])
    assert data.get("sourced_class") is None or data["sourced_class"] in [
        "NEW",
        "REPAIRED",
        "USM",
    ]
    assert data.get("unit_cost_usd") is None or isinstance(
        data["unit_cost_usd"], (int, float)
    )
    if data.get("unit_cost_usd") is not None:
        assert_cost_precision(data["unit_cost_usd"])
    assert data["status"] in ["REQUESTED", "SOURCED", "ESCALATED", "CANCELLED"]


def assert_spare_engine(data: dict):
    _assert_common_fields(data, "SpareEngine")
    assert isinstance(data["spare_serial"], str) and len(data["spare_serial"]) > 0
    assert isinstance(data["engine_model"], str) and len(data["engine_model"]) > 0
    assert isinstance(data["daily_lease_rate_usd"], (int, float))
    assert data["daily_lease_rate_usd"] > 0
    assert data["status"] in ["AVAILABLE", "LEASED"]


def assert_spare_engine_lease(data: dict):
    _assert_common_fields(data, "SpareEngineLease")
    assert is_valid_uuid(data.get("spare_engine_id", "")), (
        "SpareEngineLease.spare_engine_id must be a UUID"
    )
    assert is_valid_uuid(data.get("shop_visit_id", "")), (
        "SpareEngineLease.shop_visit_id must be a UUID"
    )
    assert is_iso8601_timestamp(data["start_date"])
    assert is_iso8601_timestamp(data["end_date"])
    assert data["end_date"] > data["start_date"], "lease window is half-open [start, end)"
    assert data["status"] in ["RESERVED", "ACTIVE", "RETURNED", "CANCELLED"]
    assert isinstance(data["lease_cost_usd"], (int, float))
    assert data["lease_cost_usd"] >= 0
    assert_cost_precision(data["lease_cost_usd"])
    assert isinstance(data["deposit_usd"], (int, float)) and data["deposit_usd"] >= 0
    assert_cost_precision(data["deposit_usd"])


def assert_directive(data: dict):
    _assert_append_only_fields(data, "Directive")
    assert isinstance(data["directive_ref"], str) and len(data["directive_ref"]) > 0
    assert data["directive_type"] in ["AD", "SB", "ED"]
    assert isinstance(data["applicability_model"], str) and len(data["applicability_model"]) > 0
    assert isinstance(data["mandatory"], bool)
    assert data.get("compliance_cycles") is None or (
        isinstance(data["compliance_cycles"], int) and data["compliance_cycles"] > 0
    )
    _assert_nullable_timestamp(data, "compliance_date", "Directive")
    assert data.get("compliance_cycles") is not None or data.get("compliance_date") is not None, (
        "a directive declares at least one of compliance_cycles / compliance_date"
    )
    assert isinstance(data["estimated_cost_usd"], (int, float))
    assert data["estimated_cost_usd"] > 0


def assert_recognition_snapshot(data: dict):
    _assert_append_only_fields(data, "RecognitionSnapshot")
    assert is_valid_uuid(data.get("agreement_id", "")), (
        "RecognitionSnapshot.agreement_id must be a UUID"
    )
    for field in (
        "lifetime_revenue_projection_usd",
        "lifetime_cost_projection_usd",
        "cost_to_date_usd",
        "recognized_revenue_projected_usd",
        "recognized_revenue_actual_usd",
        "onerous_loss_accrual_usd",
    ):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
        assert data[field] >= 0, f"{field} must be non-negative"
        assert_cost_precision(data[field])
    assert isinstance(data["recognition_pct"], (int, float))
    assert 0 <= data["recognition_pct"] <= 1, "recognition_pct is capped at 1"


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------

def assert_agreement_invariants(data: dict):
    """Invariants that must hold on any ServiceAgreement read (PRD §3.2):
    billed_to_date is a running non-negative money figure; the enrolled count
    is non-negative."""
    assert_service_agreement(data)
    assert_cost_precision(data["billed_to_date_usd"])


def assert_engine_invariants(data: dict):
    """PRD §3.3: llp_remaining_cycles is floored at zero; lifetime counters
    only grow."""
    assert_engine(data)
    assert data["llp_remaining_cycles"] >= 0
    assert data["cumulative_flight_hours"] >= 0
    assert data["cumulative_cycles"] >= 0
    if data.get("agreement_id") is None:
        assert data.get("enrolled_at") is None, (
            "enrolled_at is null until the engine is enrolled"
        )


def assert_recognition_invariants(data: dict):
    """PRD §3.9: recognition_pct = min(1, cost / lifetime cost projection);
    the onerous accrual is the shortfall when the projected margin falls
    below the floor, else 0."""
    assert_recognition_snapshot(data)
    assert data["lifetime_cost_projection_usd"] >= data["cost_to_date_usd"], (
        "the lifetime cost projection includes cost_to_date"
    )
    if data["lifetime_cost_projection_usd"] > 0:
        assert data["recognition_pct"] <= 1
