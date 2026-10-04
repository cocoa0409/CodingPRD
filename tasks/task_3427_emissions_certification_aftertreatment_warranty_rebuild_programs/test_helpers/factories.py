"""Payload factories — one per create/action endpoint, input fields only.

Defaults form a happy path consistent with the PRD narrative defaults
(e.g. a 0.35/0.01-limit standard, a 14.9L family, passing measured
emissions). Program-wide or scoped-unique fields (codes, serials, badge ids)
are minted unique per call so multiple resources can coexist in one test;
tests that exercise uniqueness pass explicit values via **overrides.

Required foreign keys and OCC version fields are keyword-only arguments with
no defaults — a payload can never silently omit them.
"""
import uuid

from .constants import DEFAULT_CLOCK_UTC


def _uniq() -> str:
    return uuid.uuid4().hex[:8].upper()


# ---------------------------------------------------------------------------
# clock (test-driving endpoint outside the /emissions prefix, PRD §2.4)
# ---------------------------------------------------------------------------
def set_clock_payload(current_utc: str) -> dict:
    return {"current_utc": current_utc}


# ---------------------------------------------------------------------------
# regulation standards (PRD §3.1)
# ---------------------------------------------------------------------------
def create_regulation_standard_payload(**overrides) -> dict:
    payload = {
        "code": f"STD-{_uniq()}",
        "nox_limit_g_per_bhp_hr": 0.35,
        "pm_limit_g_per_bhp_hr": 0.01,
        "useful_life_miles": 435000,
        "useful_life_hours": 22000,
        "useful_life_years": 10,
        "base_warranty_years": 2,
        "base_warranty_miles": 50000,
        "effective_model_year_first": 2027,
        "effective_model_year_last": 2030,
    }
    payload.update(overrides)
    return payload


def supersede_payload(successor_standard_id: str) -> dict:
    return {"successor_standard_id": successor_standard_id}


# ---------------------------------------------------------------------------
# engine families (PRD §3.2)
# ---------------------------------------------------------------------------
def create_engine_family_payload(*, regulation_standard_id: str, **overrides) -> dict:
    payload = {
        "family_code": f"FAM-{_uniq()}",
        "model_year": 2027,
        "regulation_standard_id": regulation_standard_id,
        "displacement_liters": 14.9,
        "architecture": "DOC_DPF_SCR",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# aftertreatment specs (PRD §3.3) — OCC: expected_engine_family_version
# ---------------------------------------------------------------------------
def create_aftertreatment_spec_payload(*, expected_engine_family_version: int,
                                       **overrides) -> dict:
    payload = {
        "scr_catalyst_part": "SCR-900",
        "dpf_part": "DPF-450",
        "doser_part": "DSR-12",
        "nox_sensor_count": 2,
        "expected_engine_family_version": expected_engine_family_version,
    }
    payload.update(overrides)
    return payload


def occ_spec_payload(family: dict, **overrides) -> dict:
    """OCC-correct spec payload for the family's currently observed version."""
    return create_aftertreatment_spec_payload(
        expected_engine_family_version=family["version"], **overrides
    )


def calibrate_spec_payload(**overrides) -> dict:
    """Default observation calibrates a 14.9L family: target 7.45 g/kWh,
    deviation 0.0067 <= 0.05 and NOx 250 <= 400 (PRD §3.3)."""
    payload = {
        "observed_nox_ppm_avg": 250,
        "observed_def_consumption_g_per_kwh": 7.4,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# certification test runs (PRD §3.3)
# ---------------------------------------------------------------------------
def create_test_run_payload(**overrides) -> dict:
    payload = {
        "test_type": "FTP",
        "lab_code": f"LAB-{_uniq()}",
        "scheduled_start": "2026-10-05T00:00:00Z",
        "scheduled_end": "2026-10-07T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def record_results_payload(**overrides) -> dict:
    """Defaults PASS against the default standard: adjusted NOx 0.33 <= 0.35,
    adjusted PM 0.0088 <= 0.01 (PRD §3.3)."""
    payload = {
        "measured_nox_g_per_bhp_hr": 0.30,
        "measured_pm_g_per_bhp_hr": 0.008,
        "deterioration_factor": 1.1,
    }
    payload.update(overrides)
    return payload


def review_test_run_payload(decision: str = "ACCEPT") -> dict:
    return {"decision": decision}


def invalidate_test_run_payload(reason: str = "lab audit finding") -> dict:
    return {"reason": reason}


# ---------------------------------------------------------------------------
# fleets and engine units (PRD §3.4)
# ---------------------------------------------------------------------------
def create_fleet_payload(**overrides) -> dict:
    payload = {
        "name": f"Fleet {_uniq()}",
        "fleet_code": f"FL-{_uniq()}",
        "notification_contact": f"ops-{_uniq().lower()}@example.com",
    }
    payload.update(overrides)
    return payload


def create_engine_unit_payload(*, engine_family_id: str, fleet_id: str,
                               **overrides) -> dict:
    payload = {
        "engine_family_id": engine_family_id,
        "fleet_id": fleet_id,
        "serial_number": f"SN-{_uniq()}",
        # equal to the startup clock is accepted; strictly after is rejected
        "in_service_date": DEFAULT_CLOCK_UTC,
    }
    payload.update(overrides)
    return payload


def create_maintenance_record_payload(**overrides) -> dict:
    payload = {
        "performed_at": "2026-10-20T00:00:00Z",
        "maintenance_type": "OIL_CHANGE",
        "odometer_at_service": 0,
        "def_quality_ok": True,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# telematics (PRD §3.5)
# ---------------------------------------------------------------------------
def fault_code(code: str, severity: str) -> dict:
    return {"code": code, "severity": severity}


def create_telematics_snapshot_payload(**overrides) -> dict:
    """Defaults are monotonic-safe for a fresh unit (miles/hours 0)."""
    payload = {
        "recorded_at": "2026-10-15T00:00:00Z",
        "odometer_miles": 0,
        "engine_hours": 0,
        "fault_codes": [],
        "def_consumption_gal": 10.0,
        "nox_sensor_drift_ppm": 0,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# service network (PRD §3.6)
# ---------------------------------------------------------------------------
def create_service_center_payload(**overrides) -> dict:
    payload = {
        "name": f"Service Center {_uniq()}",
        "region": "SW",
        "bay_capacity_per_day": 2,
    }
    payload.update(overrides)
    return payload


def authorize_service_center_payload(authorization_tier: str = "CERTIFIED") -> dict:
    return {"authorization_tier": authorization_tier}


def create_technician_payload(**overrides) -> dict:
    payload = {
        "full_name": f"Tech {_uniq()}",
        "badge_id": f"T-{_uniq()}",
        "certification_level": "LEVEL_2",
        "emissions_endorsed": True,
    }
    payload.update(overrides)
    return payload


def recertify_technician_payload(new_level: str = None) -> dict:
    payload: dict = {}
    if new_level is not None:
        payload["new_level"] = new_level
    return payload


def create_diagnostic_tool_payload(**overrides) -> dict:
    payload = {
        "tool_serial": f"DT-{_uniq()}",
        "software_version": "7.3.1",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# warranty claims (PRD §3.7)
# ---------------------------------------------------------------------------
def create_warranty_claim_payload(*, engine_unit_id: str, service_center_id: str,
                                  **overrides) -> dict:
    payload = {
        "engine_unit_id": engine_unit_id,
        "service_center_id": service_center_id,
        "failed_component_class": "AFTERTREATMENT_SCR",
        "failure_code": f"FC-{_uniq()}",
        "claimed_amount_cents": 100000,
    }
    payload.update(overrides)
    return payload


def adjudicate_claim_payload(decision: str) -> dict:
    return {"decision": decision}


def resubmit_claim_payload(supplemental_note: str = "additional records attached") -> dict:
    return {"supplemental_note": supplemental_note}


# ---------------------------------------------------------------------------
# field campaigns (PRD §3.8)
# ---------------------------------------------------------------------------
def create_field_campaign_payload(*, engine_family_id: str, **overrides) -> dict:
    payload = {
        "engine_family_id": engine_family_id,
        "campaign_code": f"CMP-{_uniq()}",
        "campaign_type": "RECALL",
        "defect_summary": "aftertreatment component degradation",
        "remedy_description": "replace affected component and reflash",
        "remedy_bay_days": 1,
    }
    # completion_threshold is optional (PRD default 0.95); include only on demand
    if "completion_threshold" in overrides:
        payload["completion_threshold"] = overrides.pop("completion_threshold")
    payload.update(overrides)
    return payload


def create_campaign_work_order_payload(*, engine_unit_id: str, service_center_id: str,
                                       assigned_technician_id: str, **overrides) -> dict:
    payload = {
        "engine_unit_id": engine_unit_id,
        "service_center_id": service_center_id,
        "assigned_technician_id": assigned_technician_id,
        "scheduled_start_day": "2027-01-04T00:00:00Z",
        "bay_days": 1,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# reman orders (PRD §3.9) — OCC: expected_engine_unit_version
# ---------------------------------------------------------------------------
def create_reman_order_payload(*, engine_unit_id: str, service_center_id: str,
                               expected_engine_unit_version: int, **overrides) -> dict:
    payload = {
        "engine_unit_id": engine_unit_id,
        "service_center_id": service_center_id,
        "reman_scope": "ENGINE",
        "spec_level": "STANDARD",
        "quoted_price_cents": 500000,
        "quoted_core_value_cents": 200000,
        "expected_core_return_by": "2027-03-01T00:00:00Z",
        "expected_engine_unit_version": expected_engine_unit_version,
    }
    component_type = overrides.pop("component_type", None)
    reman_scope = overrides.get("reman_scope", payload["reman_scope"])
    if reman_scope == "COMPONENT":
        # component_type is required exactly when the scope is COMPONENT
        payload["component_type"] = component_type or "TURBO"
    elif component_type is not None:
        payload["component_type"] = component_type
    payload.update(overrides)
    return payload


def occ_reman_order_payload(unit: dict, *, service_center_id: str, **overrides) -> dict:
    """OCC-correct reman payload for the unit's currently observed version."""
    return create_reman_order_payload(
        engine_unit_id=unit["id"],
        service_center_id=service_center_id,
        expected_engine_unit_version=unit["version"],
        **overrides,
    )


def grade_core_payload(core_grade: str) -> dict:
    return {"core_grade": core_grade}


# ---------------------------------------------------------------------------
# in-use compliance (PRD §3.4)
# ---------------------------------------------------------------------------
def create_in_use_result_payload(**overrides) -> dict:
    payload = {
        "test_period_label": f"PERIOD-{_uniq()}",
        "sample_size": 10,
        "passing_units": 9,
    }
    payload.update(overrides)
    return payload
