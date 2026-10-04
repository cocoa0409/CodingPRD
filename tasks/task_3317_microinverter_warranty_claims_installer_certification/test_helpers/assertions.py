"""Entity assertions and domain invariant checkers (PRD §1-§3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ─── Audit-convention entities (PRD §2.4) ─────────────

def assert_audit_fields(data: dict):
    """id/created_at/updated_at/version are present on the entities that
    participate fully in the audit convention (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_id_and_created_at_only(data: dict):
    """ProductionLot, WarrantyTransfer, and ReplacementOrder expose only id and
    created_at: no updated_at and no version field at all (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data.get("updated_at") is None, "updated_at must be absent on this entity"
    assert data.get("version") is None, "version must be absent on this entity"


def assert_installer(data: dict):
    assert_audit_fields(data)
    assert isinstance(data.get("company_name"), str) and data["company_name"]
    assert isinstance(data.get("installer_code"), str) and data["installer_code"]
    assert data.get("certification_level") in ("CERTIFIED", "GOLD", "PLATINUM")
    assert data.get("certification_status") in ("PENDING", "ACTIVE", "SUSPENDED", "EXPIRED")
    assert isinstance(data.get("design_tool_enabled"), bool)
    assert isinstance(data.get("commissioning_enabled"), bool)
    assert isinstance(data.get("active_system_count"), int)
    assert isinstance(data.get("labor_approved_cents_total"), int)
    assert isinstance(data.get("labor_reversed_cents_total"), int)
    assert isinstance(data.get("labor_paid_cents_total"), int)


def assert_design_project(data: dict):
    assert_audit_fields(data)
    assert is_valid_uuid(data.get("installer_id", ""))
    assert isinstance(data.get("module_count"), int)
    assert isinstance(data.get("dc_capacity_watts"), int)
    assert data.get("status") in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "COMMISSIONED")


def assert_production_lot(data: dict):
    assert_id_and_created_at_only(data)
    assert isinstance(data.get("lot_code"), str)
    assert data.get("lot_status") in ("NORMAL", "WATCH", "RECALL")
    assert isinstance(data.get("defect_rate_cumulative_pct"), (int, float))
    assert isinstance(data.get("corrective_action_required"), bool)


def assert_system_registration(data: dict):
    assert_audit_fields(data)
    assert is_valid_uuid(data.get("installer_id", ""))
    assert data.get("warranty_status") in ("ACTIVE", "EXPIRED", "TRANSFERRED")
    assert isinstance(data.get("unit_count"), int)
    assert isinstance(data.get("owner_change_count"), int)


def assert_unit(data: dict):
    assert_audit_fields(data)
    assert isinstance(data.get("serial_number"), str)
    assert data.get("model_code") in ("IQ7", "IQ8", "IQ8HC", "IQ7X_DISCONTINUED")
    assert data.get("commissioning_state") in ("PENDING", "COMMISSIONED", "DECOMMISSIONED")
    assert data.get("monitored_status") in ("ONLINE", "UNDERPERFORMING", "FAILED", "OFFLINE")
    assert isinstance(data.get("underperformance_streak_hours"), int)
    assert isinstance(data.get("replacement_count"), int)
    assert isinstance(data.get("replacement_window_position"), int)
    assert isinstance(data.get("rma_eligible"), bool)
    assert isinstance(data.get("campaign_eligible"), bool)


def assert_warranty_claim(data: dict):
    assert_audit_fields(data)
    assert is_valid_uuid(data.get("unit_id", ""))
    assert is_valid_uuid(data.get("installer_id", ""))
    assert data.get("claim_kind") in ("DEFECT", "UNDERPERFORMANCE", "NO_POWER", "COMMUNICATION")
    assert data.get("status") in (
        "DRAFT", "SUBMITTED", "DIAGNOSED", "APPROVED", "DENIED", "DISPATCHED", "CLOSED", "REOPENED",
    )
    assert isinstance(data.get("reopen_count"), int)


def assert_labor_reimbursement(data: dict):
    assert_audit_fields(data)
    assert is_valid_uuid(data.get("claim_id", ""))
    assert data.get("status") in ("PENDING", "APPROVED", "REJECTED", "PAID")
    assert isinstance(data.get("net_amount_cents"), int)
    assert isinstance(data.get("labor_component_cents"), int)
    assert isinstance(data.get("diagnostic_component_cents"), int)
    assert data.get("age_factor") in (1.000, 0.750, 0.375, 0.000)


def assert_warranty_transfer(data: dict):
    assert_id_and_created_at_only(data)
    assert data.get("transfer_kind") in ("SALE", "INHERITANCE", "FORECLOSURE")
    assert data.get("status") in ("SUBMITTED", "APPROVED", "REJECTED")
    assert isinstance(data.get("preserved_months"), int)
    assert data.get("approval_source") in ("AUTO", "HOMEOWNER_APPROVAL")


def assert_proactive_campaign(data: dict):
    assert_audit_fields(data)
    assert data.get("origin") in ("LOT_TREND", "MANUAL")
    assert data.get("status") in ("DRAFT", "DISPATCHING", "COMPLETED", "CANCELED")
    assert isinstance(data.get("target_unit_count"), int)
    assert isinstance(data.get("dispatched_count"), int)
    assert isinstance(data.get("canceled_count"), int)


def assert_replacement_order(data: dict):
    assert_id_and_created_at_only(data)
    assert is_valid_uuid(data.get("unit_id", ""))
    assert data.get("replacement_model_code") in ("IQ7", "IQ8", "IQ8HC")
    assert data.get("compatibility_class") in ("IDENTICAL", "COMPATIBLE_UPGRADE", "INCOMPATIBLE")
    assert data.get("status") in ("PENDING_DISPATCH", "DISPATCHED", "INSTALLED", "CANCELED")


# ─── Domain invariant checkers ────────────────────────

def assert_installer_invariants(data: dict):
    """The installer aggregates must stay internally consistent (PRD §3.1)."""
    assert data["labor_reversed_cents_total"] >= 0
    assert data["labor_paid_cents_total"] <= data["labor_approved_cents_total"], (
        "the paid total is a subset of the approved total"
    )
    assert data["active_system_count"] >= 0


def assert_system_invariants(data: dict):
    """Replacement-ratio and unit-count invariants (PRD §3.3)."""
    ratio = data.get("replacement_ratio")
    assert 0.0 <= ratio <= 1.0, f"replacement_ratio {ratio} must lie in [0, 1]"
    assert data["unit_count"] >= 0


def assert_unit_invariants(data: dict):
    """Monitoring and replacement-budget invariants (PRD §3.4)."""
    assert 0 <= data["replacement_window_position"] <= 5
    assert data["replacement_count"] >= 0
    if data.get("monitored_status") == "FAILED":
        assert data.get("failed_at") is not None, "a FAILED unit carries a failed_at instant"


def assert_lot_invariants(data: dict):
    """Cumulative/window rate invariants (PRD §3.5)."""
    assert 0.0 <= data["defect_rate_cumulative_pct"] <= 100.0
    assert 0.0 <= data["defect_rate_window_pct"] <= 100.0
    assert data["failed_unit_count"] <= data["units_registered_count"]
    assert data["window_failed_unit_count"] <= data["failed_unit_count"]
    assert data["corrective_action_required"] == (data["lot_status"] == "RECALL")


def assert_campaign_invariants(data: dict):
    """Dispatch accounting invariant (PRD §3.5)."""
    assert data["canceled_count"] <= data["dispatched_count"]
    assert data["target_unit_count"] >= 0