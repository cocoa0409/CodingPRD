"""Request-payload factories.

Each builder emits only the fields the PRD declares as *input* for that
endpoint — never a server-computed or system field, because §2.8 rejects unknown
body fields with `ERR_INVALID_REQUEST`.

Type discipline
---------------
Loads, ratios, percentages, flows and acreages are declared as decimal numbers,
so they are emitted as JSON numbers (never as strings). `sample_datetime` and
`current_utc` are ISO-8601 *instants*; `period_start_date`, `period_end_date`,
`effective_date`, `effective_start_date` and `effective_end_date` are ISO
*calendar dates* in year-month-day form. The two shapes are never interchanged.
"""

from typing import Any, Dict, List, Optional

from .constants import CLOCK_BASE


def _drop_none(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Omit keys whose value is None so an optional field genuinely goes unsent."""
    return {key: value for key, value in payload.items() if value is not None}


# ----------------------------------------------------------------------- clock
def clock_payload(current_utc: str = CLOCK_BASE) -> Dict[str, Any]:
    return {"current_utc": current_utc}


# ------------------------------------------------------------------ watersheds
def watershed_payload(
    name: str = "Scioto Headwaters",
    state_code: str = "OH",
    watershed_code: str = "SCR",
    pollutant: str = "TOTAL_PHOSPHORUS",
    baseline_year: int = 2020,
    baseline_load_lbs_yr: float = 120000.00,
    eligible_zone_codes: Optional[List[str]] = None,
    interim_target_pct: Optional[float] = None,
    uncertainty_ratio: Optional[float] = None,
    retirement_ratio: Optional[float] = None,
    equivalence_ratio: Optional[float] = None,
    **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "name": name,
        "state_code": state_code,
        "watershed_code": watershed_code,
        "pollutant": pollutant,
        "baseline_year": baseline_year,
        "baseline_load_lbs_yr": baseline_load_lbs_yr,
        "eligible_zone_codes": (
            list(eligible_zone_codes) if eligible_zone_codes is not None else ["Z1", "Z2"]
        ),
        "interim_target_pct": interim_target_pct,
        "uncertainty_ratio": uncertainty_ratio,
        "retirement_ratio": retirement_ratio,
        "equivalence_ratio": equivalence_ratio,
    }
    payload = _drop_none(payload)
    payload.update(overrides)
    return payload


def program_status_payload(target_status: str, reason: Optional[str] = None) -> Dict[str, Any]:
    return _drop_none({"target_status": target_status, "reason": reason})


# ---------------------------------------------------------------------- reaches
def reach_payload(
    watershed_id: str,
    reach_code: str,
    trading_zone_code: str = "Z2",
    reach_class: str = "MAINSTEM",
    delivery_factor: float = 1.0000,
    downstream_reach_id: Optional[str] = None,
    **overrides: Any
) -> Dict[str, Any]:
    payload = _drop_none(
        {
            "watershed_id": watershed_id,
            "reach_code": reach_code,
            "trading_zone_code": trading_zone_code,
            "reach_class": reach_class,
            "delivery_factor": delivery_factor,
            "downstream_reach_id": downstream_reach_id,
        }
    )
    payload.update(overrides)
    return payload


# ------------------------------------------------------------ monitoring samples
def monitoring_sample_payload(
    reach_id: str,
    sample_datetime: str,
    measured_conc_mg_l: float,
    flow_cfs: float,
    qa_status: Optional[str] = None,
    **overrides: Any
) -> Dict[str, Any]:
    payload = _drop_none(
        {
            "reach_id": reach_id,
            "sample_datetime": sample_datetime,
            "measured_conc_mg_l": measured_conc_mg_l,
            "flow_cfs": flow_cfs,
            "qa_status": qa_status,
        }
    )
    payload.update(overrides)
    return payload


# -------------------------------------------------------------- tmdl assessments
def tmdl_assessment_payload(
    watershed_id: str,
    assessment_code: str = "TMDL-P-2026",
    loading_capacity_lbs_yr: float = 60000.00,
    margin_of_safety_pct: float = 0.1000,
    background_load_lbs_yr: float = 6000.00,
    period_start_date: str = "2026-01-01",
    period_end_date: str = "2035-12-31",
    **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "watershed_id": watershed_id,
        "assessment_code": assessment_code,
        "loading_capacity_lbs_yr": loading_capacity_lbs_yr,
        "margin_of_safety_pct": margin_of_safety_pct,
        "background_load_lbs_yr": background_load_lbs_yr,
        "period_start_date": period_start_date,
        "period_end_date": period_end_date,
    }
    payload.update(overrides)
    return payload


def assessment_status_payload(target_status: str, reason: Optional[str] = None) -> Dict[str, Any]:
    return _drop_none({"target_status": target_status, "reason": reason})


# ------------------------------------------------------------ source assessments
def source_assessment_payload(
    tmdl_assessment_id: str,
    reach_id: str,
    source_name: str,
    source_type: str,
    existing_load_lbs_yr: float,
    controllability_index: float,
    status: Optional[str] = None,
    **overrides: Any
) -> Dict[str, Any]:
    payload = _drop_none(
        {
            "tmdl_assessment_id": tmdl_assessment_id,
            "reach_id": reach_id,
            "source_name": source_name,
            "source_type": source_type,
            "existing_load_lbs_yr": existing_load_lbs_yr,
            "controllability_index": controllability_index,
            "status": status,
        }
    )
    payload.update(overrides)
    return payload


# --------------------------------------------------------------- allocation runs
def allocation_run_payload(
    run_label: str,
    expected_tmdl_assessment_version: int,
    method: str = "PRO_RATA_BY_EXISTING_LOAD",
    **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "run_label": run_label,
        "method": method,
        "expected_tmdl_assessment_version": expected_tmdl_assessment_version,
    }
    payload.update(overrides)
    return payload


def rescind_payload(reason: str = "Allocation error found in the source inventory") -> Dict[str, Any]:
    return {"reason": reason}


# ---------------------------------------------------------------------- permits
def permit_payload(
    watershed_id: str,
    source_assessment_id: str,
    permit_number: str,
    permittee_user_id: str,
    design_flow_mgd: float = 5.0000,
    effective_date: str = "2026-03-01",
    current_annual_load_lbs: float = 30000.00,
    **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "watershed_id": watershed_id,
        "source_assessment_id": source_assessment_id,
        "permit_number": permit_number,
        "permittee_user_id": permittee_user_id,
        "design_flow_mgd": design_flow_mgd,
        "effective_date": effective_date,
        "current_annual_load_lbs": current_annual_load_lbs,
    }
    payload.update(overrides)
    return payload


def annual_report_payload(
    reported_annual_load_lbs: float, reporting_period_year: int = 2026, **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "reported_annual_load_lbs": reported_annual_load_lbs,
        "reporting_period_year": reporting_period_year,
    }
    payload.update(overrides)
    return payload


# -------------------------------------------------------------------- producers
def producer_payload(
    legal_name: str = "Bluegrass Farms LLC",
    county_code: str = "OH-041",
    contact_email: str = "ops@bluegrass.example",
    **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "legal_name": legal_name,
        "county_code": county_code,
        "contact_email": contact_email,
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------- practice projects
def practice_project_payload(
    producer_id: str,
    reach_id: str,
    tract_code: str,
    practice_type: str = "COVER_CROP",
    enrolled_acres: float = 100.00,
    baseline_met: bool = True,
    pre_load_lbs_yr: float = 950.50,
    post_load_lbs_yr: float = 300.00,
    effective_start_date: str = "2026-01-01",
    effective_end_date: str = "2027-01-01",
    vintage_year: int = 2026,
    **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "producer_id": producer_id,
        "reach_id": reach_id,
        "tract_code": tract_code,
        "practice_type": practice_type,
        "enrolled_acres": enrolled_acres,
        "baseline_met": baseline_met,
        "pre_load_lbs_yr": pre_load_lbs_yr,
        "post_load_lbs_yr": post_load_lbs_yr,
        "effective_start_date": effective_start_date,
        "effective_end_date": effective_end_date,
        "vintage_year": vintage_year,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------- verification events
def verification_event_payload(
    practice_project_id: str,
    event_type: str,
    outcome: str,
    narrative: str = "Field inspection completed and documented.",
    verified_acres: Optional[float] = None,
    **overrides: Any
) -> Dict[str, Any]:
    payload = _drop_none(
        {
            "practice_project_id": practice_project_id,
            "event_type": event_type,
            "outcome": outcome,
            "narrative": narrative,
            "verified_acres": verified_acres,
        }
    )
    payload.update(overrides)
    return payload


# --------------------------------------------------------------- credit batches
def retire_payload(
    retire_lbs: float, reason: str = "Program retirement into the reserve pool"
) -> Dict[str, Any]:
    return {"retire_lbs": retire_lbs, "reason": reason}


# ----------------------------------------------------------- credit transactions
def credit_transaction_payload(
    credit_batch_id: str,
    permit_id: str,
    requested_gross_lbs: float,
    reporting_period_year: int,
    expected_credit_batch_version: int,
    **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "credit_batch_id": credit_batch_id,
        "permit_id": permit_id,
        "requested_gross_lbs": requested_gross_lbs,
        "reporting_period_year": reporting_period_year,
        "expected_credit_batch_version": expected_credit_batch_version,
    }
    payload.update(overrides)
    return payload


def void_payload(reason: str = "REGISTRY_ACTION") -> Dict[str, Any]:
    return {"reason": reason}


# -------------------------------------------------------------- adaptive reviews
def adaptive_review_payload(
    review_label: str,
    period_start_date: str,
    period_end_date: str,
    **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "review_label": review_label,
        "period_start_date": period_start_date,
        "period_end_date": period_end_date,
    }
    payload.update(overrides)
    return payload
