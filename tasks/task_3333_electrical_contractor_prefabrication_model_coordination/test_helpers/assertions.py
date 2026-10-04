"""Entity assertions and domain invariant checkers (PRD §2.4, §2.7, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

COMMON_FIELDS = ("id", "created_at", "updated_at", "version")


def assert_common_fields(data: dict):
    """Every resource in this service carries the common field set (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 0, "version must be non-negative"


def assert_project(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("project_code"), str) and data["project_code"]
    assert data.get("project_posture") in [
        "ON_TRACK", "RELEASE_PENDING", "RECOVERY_MODE", "HOLD", "FROZEN",
    ]
    assert data.get("credit_policy") in ["FIRST_ACCEPTED", "HIGHEST_TOTAL"]


def assert_worker(data: dict):
    assert_common_fields(data)
    assert data.get("classification") in [
        "APPRENTICE", "JOURNEYMAN", "FOREMAN", "GENERAL_FOREMAN",
    ]


def assert_model_version(data: dict):
    assert_common_fields(data)
    assert data.get("status") in ["DRAFT", "COORDINATED", "SUPERSEDED"]


def assert_takeoff_line(data: dict):
    assert_common_fields(data)
    assert data.get("takeoff_hash"), "takeoff_hash is stamped by the server"


def assert_rack(data: dict):
    assert_common_fields(data)
    assert "reserved_streams_and_phase_cf" in data


def assert_prefab_order(data: dict):
    assert_common_fields(data)
    assert data.get("fabricate_status") in [
        "PLANNED", "RELEASED", "IN_FABRICATION", "FABRICATED", "CANCELLED",
    ]
    assert data.get("deliver_status") in [
        "AWAITING", "STAGED", "LOADED", "IN_TRANSIT", "DELIVERED",
    ]
    assert data.get("shipment_status") in [
        "PENDING", "RESERVED", "STAGED", "LOADED", "IN_TRANSIT",
        "DELIVERED", "LOST", "LOCKED",
    ]


def assert_prefab_component(data: dict):
    assert_common_fields(data)
    assert data.get("install_status") in [
        "PLANNED", "FABRICATED", "LOADED", "SET", "REWORK", "SCRAPPED",
    ]


def assert_trade_activity(data: dict):
    assert_common_fields(data)
    assert data.get("status") in [
        "PLANNED", "PERMITTED", "ACTIVE", "DISALLOWED", "COMPLETE",
    ]


def assert_crew_day(data: dict):
    assert_common_fields(data)


def assert_compliance_ledger(data: dict):
    assert_common_fields(data)


def assert_revision(data: dict):
    assert_common_fields(data)
    assert data.get("status") in [
        "DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED",
    ]


def assert_material_release(data: dict):
    assert_common_fields(data)
    assert data.get("status") in [
        "PLANNED", "RELEASED", "SHIPPED", "RECEIVED", "RESTRICTED",
    ]


def assert_prefab_order_invariants(data: dict):
    """Derived-field invariants that must hold on any work package read."""
    if data.get("laydown_slot_index") is not None:
        assert data["laydown_slot_index"] >= 1
    if data.get("hoisting_start_iso") and data.get("hoisting_end_iso"):
        assert data["hoisting_start_iso"] < data["hoisting_end_iso"], (
            "hoisting window must be a forward interval"
        )
    d = data.get("hoisting_duration_days")
    if d is not None:
        assert 1 <= d <= 10, "hoisting_duration_days is clamped to the inclusive range 1..10"
    assert data.get("rework_order_count", 0) >= 0


def assert_project_invariants(data: dict):
    """Rollups that must never violate their definitions (PRD §3.8)."""
    assert data["installed_pct"] >= 0.0
    assert data["slippage_pct"] >= 0.0
    assert data["craft_hours_credit"] >= 0.0, "release credit is floored at zero"
    assert data["pipeline_value_cents"] >= 0
    assert data["completed_value_cents"] >= 0
    total = data["pipeline_value_cents"] + data["completed_value_cents"]
    if total == 0:
        assert data["installed_pct"] == 0.0
    else:
        assert data["installed_pct"] <= 1.0


def assert_revision_impact_values(revision: dict):
    """Each impact is priced twice and the two variants are written side by side."""
    values = revision.get("impact_values") or []
    assert len(values) == len(revision.get("impact_keys") or []), (
        "impact_values carries one entry per impact key"
    )
    for entry in values:
        assert "rework_value_cents" in entry
        assert "negotiated_value_cents" in entry


def assert_apprentice_ratio_invariant(ledger: dict):
    """excess = apprentice hours above ratio_limit x journeyman hours (PRD §3.6)."""
    excess = ledger["apprentice_hours"] - ledger["ratio_limit"] * ledger["journeyman_hours"]
    expected = max(excess, 0.0)
    assert abs(ledger["excess_apprentice_hours"] - expected) < 1e-6, (
        f"excess_apprentice_hours {ledger['excess_apprentice_hours']} does not match "
        f"apprentice - ratio_limit * journeyman = {expected}"
    )