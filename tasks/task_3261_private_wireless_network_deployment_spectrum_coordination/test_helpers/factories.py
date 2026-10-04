"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _next(prefix: str) -> str:
    return f"{prefix}-{next(_counter):04d}"


def create_enterprise_payload(**overrides) -> dict:
    defaults = {
        "legal_name": _next("Ent"),
        "erp_account_code": _next("ERP"),
        "industry_vertical": "CAMPUS",
        "security_posture": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_site_payload(**overrides) -> dict:
    defaults = {
        "site_code": _next("SITE"),
        "address": "1 Test Way",
        "geo_latitude": 40.0,
        "geo_longitude": -75.0,
        "site_area_sqm": 2000,
        "target_capacity_mbps": 1000,
        "target_availability_pct": 99.9,
    }
    defaults.update(overrides)
    return defaults


def create_survey_payload(**overrides) -> dict:
    defaults = {
        "surveyor_id": _next("ft"),
        "survey_date": "2026-09-01T10:00:00Z",
        "measured_rsrp_dbm": -80,
        "measured_sinr_db": 20,
        "floor_plan_area_sqm": 1000,
        "building_material_class": "OPEN",
    }
    defaults.update(overrides)
    return defaults


def create_design_payload(**overrides) -> dict:
    defaults = {
        "edge_compute_required": False,
        "edge_compute_placement": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_cell_payload(**overrides) -> dict:
    defaults = {
        "sector_label": _next("SEC"),
        "azimuth_degrees": 0,
        "height_m": 25,
        "max_eirp_dbm": 40,
    }
    defaults.update(overrides)
    return defaults


def create_lease_payload(**overrides) -> dict:
    defaults = {
        "band_class": "SHARED_CBRS",
        "center_frequency_mhz": 3550,
        "bandwidth_mhz": 40,
        "lease_start_utc": "2026-09-01T00:00:00Z",
        "lease_end_utc": "2027-09-01T00:00:00Z",
        "priority_access_tier": "GAA",
        "monthly_cost_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_coordination_request_payload(**overrides) -> dict:
    defaults = {
        "requesting_coordinator_id": _next("sc"),
        "band_class": "SHARED_CBRS",
        "requested_bandwidth_mhz": 20,
        "requested_start_utc": "2026-10-01T00:00:00Z",
        "requested_end_utc": "2027-10-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(**overrides) -> dict:
    defaults = {
        "assigned_bandwidth_mhz": 10,
        "assignment_start_utc": "2026-10-01T00:00:00Z",
        "assignment_end_utc": "2026-11-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_sim_profile_payload(**overrides) -> dict:
    # ICCID must be 19-20 digits; generate unique numeric strings.
    n = 8901000000000000000 + next(_counter)
    defaults = {"iccid": str(n)}
    defaults.update(overrides)
    return defaults


def create_device_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "serial_number": f"SN-{n:06d}",
        "device_type": "CPE",
        "imei": f"{100000000000000 + n:015d}",
    }
    defaults.update(overrides)
    return defaults


def create_slice_payload(**overrides) -> dict:
    defaults = {
        "slice_name": _next("SLICE"),
        "slice_type": "EMBB",
        "guaranteed_bandwidth_mbps": 100,
        "max_latency_ms": 50,
        "max_devices": 10,
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(**overrides) -> dict:
    defaults = {
        "contract_code": _next("K"),
        "sla_tier": "STANDARD",
        "contracted_availability_pct": 99.9,
        "contracted_max_outage_minutes_per_month": 30,
        "onsite_support_window": "NEXT_BUSINESS_DAY",
        "contract_start_utc": "2026-09-01T00:00:00Z",
        "contract_end_utc": "2027-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_alert_payload(**overrides) -> dict:
    defaults = {
        "alert_class": "OUTAGE",
        "severity": "MAJOR",
    }
    defaults.update(overrides)
    return defaults


def create_remediation_payload(**overrides) -> dict:
    defaults = {
        "remediation_plan": "Add capacity",
        "additional_cells_planned": 1,
    }
    defaults.update(overrides)
    return defaults
