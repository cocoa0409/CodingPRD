"""Valid-by-default request payload builders.

Every factory returns a payload that satisfies the contract on its own, and
accepts keyword overrides for the one field a test wants to bend. All numeric
fields are emitted as JSON numbers (``int``/``float``), never as strings.
"""

import itertools
from typing import Any, Dict, List, Optional

from . import constants as C

_facility_seq = itertools.count(1)
_batch_seq = itertools.count(1)
_site_seq = itertools.count(1)
_outlet_seq = itertools.count(1)
_truck_seq = itertools.count(1)
_permit_seq = itertools.count(1)


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides; an override of ``None`` keeps the explicit JSON null."""
    payload = dict(base)
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------ clock
def clock_payload(now: str = C.SEED_CLOCK) -> Dict[str, Any]:
    return {"now": now}


# ------------------------------------------------------------------ facility
def facility_payload(**overrides: Any) -> Dict[str, Any]:
    n = next(_facility_seq)
    base = {
        "name": "North Water Reclamation Plant",
        "npdes_permit_number": f"NP-{1000 + n}",
        "storage_capacity_wet_tons": 5000.00,
        "daily_production_wet_tons": 40.00,
        "loadout_bay_count": 2,
    }
    return _merge(base, overrides)


# ------------------------------------------------------------------ limits
def pollutant_limit_payload(**overrides: Any) -> Dict[str, Any]:
    base = {
        "analyte": "CADMIUM",
        "ceiling_mg_kg": 85.0,
        "monthly_avg_mg_kg": 39.0,
        "aplr_kg_per_hectare_yr": 1.9,
        "cplr_kg_per_hectare": 39.0,
    }
    return _merge(base, overrides)


# ------------------------------------------------------------------ batch
def batch_payload(facility_id: str, **overrides: Any) -> Dict[str, Any]:
    n = next(_batch_seq)
    base = {
        "facility_id": facility_id,
        "batch_code": f"B-2026-{n:03d}",
        "wet_tons": 800.00,
        "dry_tons_in": 200.000,
        "volatile_solids_in_pct": 70.00,
        "percent_solids": 20.0,
        "detention_days": 20.0,
        "digester_temp_c": 36.0,
        "stabilization_process": C.STABILIZATION_ANAEROBIC,
        "pathogen_option": C.PATHOGEN_OPTION_PSRP_TIME_TEMP,
        "vector_option": C.VECTOR_OPTION_1_VSR,
        "nh4_n_mg_kg": 4000.0,
        "organic_n_mg_kg": 30000.0,
        "nitrate_n_mg_kg": 100.0,
        "total_p_mg_kg": 25000.0,
    }
    return _merge(base, overrides)


def digest_payload(**overrides: Any) -> Dict[str, Any]:
    base = {
        "to_status": C.PROCESS_DIGESTED,
        "dry_tons_out": 160.000,
        "volatile_solids_out_pct": 55.00,
        "detention_days": 20.0,
        "digester_temp_c": 36.0,
    }
    return _merge(base, overrides)


def dewater_payload(**overrides: Any) -> Dict[str, Any]:
    base = {"to_status": C.PROCESS_DEWATERED, "percent_solids": 20.0}
    return _merge(base, overrides)


def advance_payload(to_status: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"to_status": to_status}, overrides)


# ------------------------------------------------------------------ lab result
def lab_result_payload(**overrides: Any) -> Dict[str, Any]:
    base = {
        "analyte": "CADMIUM",
        "concentration_mg_kg": 20.0,
        "sampling_event_index": 0,
        "analyzed_at": C.SEED_CLOCK,
        "method_code": "EPA-6010D",
    }
    return _merge(base, overrides)


# ------------------------------------------------------------------ site
def site_payload(facility_id: str, **overrides: Any) -> Dict[str, Any]:
    n = next(_site_seq)
    base = {
        "facility_id": facility_id,
        "site_code": f"S-{n:02d}",
        "acres": 100.0,
        "crop_type": C.CROP_CORN,
        "crop_n_demand_lb_per_acre": 160.0,
        "crop_p_removal_lb_per_acre": 60.0,
        "soil_p_index": 40,
        "setback_to_well_ft": 200,
        "setback_to_surface_water_ft": 150,
        "allowed_application_months": [8, 9, 10],
        "soil_ph": 6.5,
        "depth_to_groundwater_ft": 10.0,
        "slope_pct": 3.0,
        "nearest_residence_ft": 3000,
        "reapplication_interval_days": 10,
    }
    return _merge(base, overrides)


def permit_approval_payload(**overrides: Any) -> Dict[str, Any]:
    base = {"decision": "APPROVE", "permit_number": f"LAP-{next(_permit_seq):04d}"}
    return _merge(base, overrides)


def permit_rejection_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": "REJECT"}, overrides)


def restrict_payload(reason: str = "CPLR_HEADROOM_LOW", **overrides: Any) -> Dict[str, Any]:
    return _merge({"restriction_reason": reason}, overrides)


# ------------------------------------------------------------------ agreement
def agreement_payload(
    site_id: str, expected_site_version: int, **overrides: Any
) -> Dict[str, Any]:
    base = {
        "site_id": site_id,
        "expected_site_version": expected_site_version,
        "farmer_user_id": "farmer-jones",
        "farm_name": "Jones Family Farm",
        "term_start": C.SEED_CLOCK,
        "term_end": "2026-12-31T00:00:00Z",
        "max_dry_tons_per_acre": 20.0,
        "notice_days": 3,
    }
    return _merge(base, overrides)


def counter_payload(max_dry_tons_per_acre: float = 18.0, **overrides: Any) -> Dict[str, Any]:
    return _merge({"max_dry_tons_per_acre": max_dry_tons_per_acre}, overrides)


def terminate_payload(reason: str = "Farmer request", **overrides: Any) -> Dict[str, Any]:
    return _merge({"termination_reason": reason}, overrides)


# ------------------------------------------------------------------ event
def event_payload(
    site_id: str,
    batch_id: str,
    agreement_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    base = {
        "site_id": site_id,
        "batch_id": batch_id,
        "agreement_id": agreement_id,
        "window_start": "2026-08-20T00:00:00Z",
        "window_end": "2026-08-21T00:00:00Z",
        "application_method": C.METHOD_SURFACE,
        "acres_treated": 100.0,
        "planned_dry_tons": 80.000,
    }
    return _merge(base, overrides)


def reschedule_payload(
    window_start: str, window_end: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge({"window_start": window_start, "window_end": window_end}, overrides)


def weather_hold_payload(hold_reason: str = C.HOLD_RAINFALL, **overrides: Any) -> Dict[str, Any]:
    return _merge({"hold_reason": hold_reason}, overrides)


def haul_ticket_payload(**overrides: Any) -> Dict[str, Any]:
    base = {
        "truck_id": f"TRK-{next(_truck_seq):02d}",
        "wet_tons": 400.00,
        "depart_at": "2026-08-20T06:00:00Z",
        "return_at": "2026-08-20T08:00:00Z",
        "odometer_miles": 24.0,
    }
    return _merge(base, overrides)


def complete_payload(**overrides: Any) -> Dict[str, Any]:
    return dict(overrides)


# ------------------------------------------------------------------ weather
def weather_payload(site_id: str, **overrides: Any) -> Dict[str, Any]:
    base = {
        "site_id": site_id,
        "rainfall_in_24h": 0.0,
        "forecast_rainfall_in_48h": 0.0,
        "frozen_ground": False,
    }
    return _merge(base, overrides)


# ------------------------------------------------------------------ outlet
def outlet_payload(**overrides: Any) -> Dict[str, Any]:
    n = next(_outlet_seq)
    base = {
        "name": f"Green Valley Compost {n}",
        "outlet_type": C.OUTLET_COMPOST,
        "gate_fee_per_wet_ton": 45.00,
        "haul_rate_per_mile_per_wet_ton": 0.28,
        "min_load_wet_tons": 20.00,
        "max_annual_wet_tons": 5000.00,
        "min_percent_solids": 15.0,
    }
    return _merge(base, overrides)


def diversion_order_payload(
    batch_id: str, outlet_id: str, expected_batch_version: int, **overrides: Any
) -> Dict[str, Any]:
    base = {
        "batch_id": batch_id,
        "outlet_id": outlet_id,
        "expected_batch_version": expected_batch_version,
        "dry_tons": 40.000,
        "wet_tons": 200.00,
        "haul_miles": 12.0,
    }
    return _merge(base, overrides)


def outlet_status_payload(status: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"status": status}, overrides)


# ------------------------------------------------------------------ complaint
def complaint_payload(facility_id: str, **overrides: Any) -> Dict[str, Any]:
    base = {
        "facility_id": facility_id,
        "received_at": C.SEED_CLOCK,
        "severity": "MODERATE",
    }
    return _merge(base, overrides)


def resolve_payload(outcome: str = C.COMPLAINT_SUBSTANTIATED, **overrides: Any) -> Dict[str, Any]:
    return _merge({"outcome": outcome}, overrides)


# ------------------------------------------------------------------ report
def annual_report_payload(facility_id: str, report_year: int = 2026, **overrides: Any):
    base = {"facility_id": facility_id, "report_year": report_year}
    return _merge(base, overrides)


# ------------------------------------------------------------------ helpers
def months(*values: int) -> List[int]:
    return list(values)


def optional(value: Optional[Any]) -> Optional[Any]:
    return value
