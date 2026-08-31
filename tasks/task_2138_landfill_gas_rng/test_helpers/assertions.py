"""Entity assertions and domain invariant checkers."""

from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# Money, energy, durations and percentages are carried to two decimal places.
MONEY_TOL = 0.005
# Hourly nomination rates, eligibility factors and LCFS credits: four places.
FOUR_DP_TOL = 0.00005
# Carbon-intensity figures: three places.
THREE_DP_TOL = 0.0005


def approx_2dp(expected: float):
    return pytest.approx(expected, abs=MONEY_TOL)


def approx_3dp(expected: float):
    return pytest.approx(expected, abs=THREE_DP_TOL)


def approx_4dp(expected: float):
    return pytest.approx(expected, abs=FOUR_DP_TOL)


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant as returned by this API."""
    assert isinstance(value, str), f"Expected an ISO 8601 timestamp, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected_iso: str, field: str = "timestamp"):
    """Compare two ISO 8601 UTC instants by value, not by string spelling."""
    assert actual is not None, f"{field} must not be null"
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"Expected {field} {expected_iso}, got {actual}"
    )


def assert_common_fields(data: dict, entity_name: str = "resource"):
    """id / created_at / updated_at / version, carried by every resource that
    is not one of the two append-only event records."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be an ISO 8601 UTC timestamp, "
        f"got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be an ISO 8601 UTC timestamp, "
        f"got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"{entity_name}.version must be an integer, got {data.get('version')!r}"
    )
    assert data["version"] >= 1, f"{entity_name}.version starts at 1"


def assert_append_only_event(data: dict, entity_name: str = "event"):
    """The two append-only records expose only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "version" not in data, (
        f"{entity_name} must not carry a version field: {data.get('version')!r}"
    )
    assert "updated_at" not in data, (
        f"{entity_name} must not carry an updated_at field: {data.get('updated_at')!r}"
    )


# ─── Per-entity assertions ────────────────────────────

def assert_landfill_site(data: dict):
    assert_common_fields(data, "LandfillSite")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert 0 < data["host_royalty_pct"] <= 0.50
    assert data["royalty_variant"] in ("GROSS_REVENUE_SHARE", "NETBACK_SHARE")
    assert data["royalty_floor_usd_per_mmbtu"] >= 0
    assert data["permit_nmoc_limit_lb_per_hr"] > 0
    assert data["compliance_posture"] in ("COMPLIANT", "WATCH", "VIOLATION")
    for counter in (
        "rin_generated_total",
        "rin_available_count",
        "rin_retired_count",
        "rin_reversed_count",
    ):
        assert isinstance(data[counter], int), f"{counter} must be an exact integer"
        assert data[counter] >= 0


def assert_gas_well(data: dict):
    assert_common_fields(data, "GasWell")
    assert is_valid_uuid(data["site_id"])
    assert isinstance(data["well_code"], str) and 0 < len(data["well_code"]) <= 20
    assert data["target_flow_scfm"] > 0
    assert data["operating_state"] in (
        "ONLINE",
        "THROTTLED",
        "ISOLATED",
        "MAINTENANCE_LOCKOUT",
        "DECOMMISSIONED",
    )
    assert data["last_quality_class"] in ("NONE", "GOOD", "WATCH", "ALARM")
    assert data["current_flow_scfm"] >= 0
    assert isinstance(data["consecutive_good_readings"], int)


def assert_well_tuning_reading(data: dict):
    assert_append_only_event(data, "WellTuningReading")
    assert is_valid_uuid(data["well_id"])
    assert is_iso8601_timestamp(data["taken_at"])
    assert 0 <= data["methane_pct"] <= 100
    assert 0 <= data["oxygen_pct"] <= 25
    assert 0 <= data["nitrogen_pct"] <= 100
    assert 0 <= data["temperature_f"] <= 250
    assert data["flow_scfm"] >= 0
    assert data["vacuum_inhg"] >= 0
    assert data["quality_class"] in ("GOOD", "WATCH", "ALARM")
    assert data["resulting_well_state"] in ("ONLINE", "THROTTLED", "ISOLATED")
    assert isinstance(data["recorded_by_user_id"], str) and data["recorded_by_user_id"]


def assert_work_order(data: dict):
    assert_common_fields(data, "WorkOrder")
    assert is_valid_uuid(data["well_id"])
    assert data["work_type"] in (
        "WELL_RETUNE",
        "LATERAL_REPAIR",
        "SUMP_PUMP_SERVICE",
        "HEADER_DEWATERING",
    )
    assert data["status"] in ("PLANNED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert parse_instant(data["window_end"]) > parse_instant(data["window_start"])
    assert data["condensate_gallons_removed"] >= 0


def assert_condensate_haul(data: dict):
    assert_append_only_event(data, "CondensateHaul")
    assert is_valid_uuid(data["work_order_id"])
    assert data["gallons"] > 0
    assert (
        isinstance(data["disposal_manifest_no"], str)
        and 0 < len(data["disposal_manifest_no"]) <= 40
    )
    assert isinstance(data["is_hazardous"], bool)


def assert_processing_plant(data: dict):
    assert_common_fields(data, "ProcessingPlant")
    assert is_valid_uuid(data["site_id"])
    assert data["receipt_point_mdq_dth_per_day"] > 0
    assert data["min_feed_scfm"] > 0
    assert data["process_mode"] in (
        "STARTUP",
        "UPGRADING",
        "FLARING",
        "DOWN",
        "DECOMMISSIONED",
    )
    assert data["spec_status"] in ("ON_SPEC", "OFF_SPEC", "QUARANTINE")
    assert 0 <= data["availability_factor_pct"] <= 100
    assert data["downtime_minutes_mtd"] >= 0
    assert data["flare_minutes_mtd"] >= 0


def assert_downtime_event(data: dict):
    assert_common_fields(data, "DowntimeEvent")
    assert is_valid_uuid(data["plant_id"])
    assert data["cause"] in (
        "PLANNED_MAINTENANCE",
        "COMPRESSOR_TRIP",
        "OFF_SPEC_TRIP",
        "WELLFIELD_SHORTFALL",
        "PIPELINE_CURTAILMENT",
    )
    assert data["disposition"] in ("FLARED", "VENTED", "BYPASS")
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["auto_generated"], bool)
    assert data["duration_minutes"] >= 0


def assert_offtake_contract(data: dict):
    assert_common_fields(data, "OfftakeContract")
    assert is_valid_uuid(data["site_id"])
    assert data["contract_mdq_dth_per_day"] > 0
    assert data["price_usd_per_dth"] > 0
    assert data["status"] in ("PENDING", "ACTIVE", "SUSPENDED", "TERMINATED")
    assert parse_instant(data["term_end"]) > parse_instant(data["term_start"])
    assert data["delivered_dth_mtd"] >= 0


def assert_pipeline_nomination(data: dict):
    assert_common_fields(data, "PipelineNomination")
    assert is_valid_uuid(data["contract_id"])
    assert is_valid_uuid(data["plant_id"])
    assert data["nominated_dth"] > 0
    assert data["hourly_rate_dth"] >= 0
    assert data["status"] in (
        "DRAFT",
        "CONFIRMED",
        "SCHEDULED",
        "DELIVERED",
        "CURTAILED",
        "CANCELLED",
    )
    assert data["committed_dth"] >= 0
    assert data["delivered_dth"] >= 0
    assert parse_instant(data["gas_day_end"]) > parse_instant(data["gas_day_start"])


def assert_injection_batch(data: dict):
    assert_common_fields(data, "InjectionBatch")
    assert is_valid_uuid(data["plant_id"])
    assert isinstance(data["hourly_volumes_mscf"], list)
    assert 1 <= len(data["hourly_volumes_mscf"]) <= 24
    assert all(v >= 0 for v in data["hourly_volumes_mscf"])
    assert 0 <= data["methane_pct"] <= 100
    assert 0 <= data["oxygen_pct"] <= 25
    assert 0 <= data["co2_pct"] <= 100
    assert data["gross_mmbtu"] >= 0
    assert data["status"] in (
        "DRAFT",
        "PENDING_ANALYSIS",
        "ON_SPEC",
        "OFF_SPEC",
        "NOMINATED",
        "INJECTED",
        "DIVERTED_TO_FLARE",
        "VOIDED",
    )
    assert data["spec_failure_reason"] in (
        "NONE",
        "LOW_METHANE",
        "HIGH_OXYGEN",
        "HIGH_CO2",
    )


def assert_attribute_batch(data: dict):
    assert_common_fields(data, "AttributeBatch")
    assert is_valid_uuid(data["injection_batch_id"])
    assert data["program"] in ("RIN_D3", "LCFS")
    assert data["basis"] in ("PROVISIONAL_NOMINATED", "SETTLED_METERED")
    assert data["status"] in (
        "PENDING",
        "GENERATED",
        "QA_HOLD",
        "SEPARATED",
        "RETIRED",
        "REVERSED",
    )
    assert isinstance(data["rin_count"], int), "rin_count is a whole number"
    assert data["rin_count"] >= 0
    assert data["energy_basis_mmbtu"] >= 0
    assert data["eligibility_factor"] >= 0


def assert_compliance_report(data: dict):
    assert_common_fields(data, "ComplianceReport")
    assert is_valid_uuid(data["site_id"])
    assert data["report_type"] in (
        "NSPS_ANNUAL",
        "QUARTERLY_RIN_QAP",
        "LCFS_QUARTERLY",
        "TITLE_V_SEMIANNUAL",
    )
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "UNDER_REVIEW",
        "RETURNED",
        "ACCEPTED",
    )
    assert isinstance(data["exceedance_flag"], bool)
    assert data["nmoc_lb_per_hr_reported"] >= 0
    assert isinstance(data["revision_count"], int)


def assert_royalty_statement(data: dict):
    assert_common_fields(data, "RoyaltyStatement")
    assert is_valid_uuid(data["site_id"])
    assert data["variant_applied"] in ("GROSS_REVENUE_SHARE", "NETBACK_SHARE")
    assert data["status"] in ("DRAFT", "ISSUED", "DISPUTED", "PAID")
    assert data["billable_mmbtu"] >= 0
    assert data["royalty_amount_usd"] >= 0


# ─── Domain invariants ────────────────────────────────

def assert_energy_identity(data: dict):
    """energy_produced_mmbtu always equals injected + flared + vented."""
    total = (
        round(data["energy_injected_mmbtu"], 2)
        + round(data["energy_flared_mmbtu"], 2)
        + round(data["energy_vented_mmbtu"], 2)
    )
    assert round(data["energy_produced_mmbtu"], 2) == approx_2dp(total), (
        "energy_produced_mmbtu must equal injected + flared + vented, got "
        f"{data['energy_produced_mmbtu']} vs {total}"
    )


def assert_rin_identity(data: dict):
    """rin_generated_total always equals available + retired + reversed."""
    total = (
        data["rin_available_count"] + data["rin_retired_count"] + data["rin_reversed_count"]
    )
    assert data["rin_generated_total"] == total, (
        "rin_generated_total must equal available + retired + reversed, got "
        f"{data['rin_generated_total']} vs {total}"
    )


def assert_energy_balance_read(data: dict):
    """The computed read exposes both conserved-quantity invariants."""
    assert is_valid_uuid(data["site_id"])
    assert isinstance(data["balance_ok"], bool)
    assert isinstance(data["rin_ledger_ok"], bool)
    assert_energy_identity(data)
    assert_rin_identity(data)
