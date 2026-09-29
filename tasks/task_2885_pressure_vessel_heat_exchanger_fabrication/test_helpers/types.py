"""Typed shapes for the request payloads and response records of the API.

These are documentation-grade ``TypedDict`` definitions used by the factories and
fixtures so that a reader can see, at a glance, which fields the PRD declares
required and which it declares optional.
"""

from typing import Any, Dict, List, Optional, TypedDict


Headers = Dict[str, str]
Json = Dict[str, Any]


# --- §2.2 envelope -----------------------------------------------------------
class EnvelopeMeta(TypedDict, total=False):
    api_request_id: str
    api_request_timestamp: str
    limit: int
    offset: int
    total_count: int
    has_more: bool


class ErrorData(TypedDict):
    error_id: str
    message: str


# --- §3.1 certificate and audits --------------------------------------------
class CertificatePayload(TypedDict, total=False):
    cert_number: str
    scope_codes: List[str]
    issued_on: str
    expires_on: str


class AuditPayload(TypedDict, total=False):
    certificate_id: str
    audit_type: str
    scheduled_date: str


class Finding(TypedDict):
    finding_code: str
    severity: str
    clause_reference: str


class AuditClosePayload(TypedDict, total=False):
    closed_on: str
    findings: List[Finding]


class RenewalPayload(TypedDict, total=False):
    expected_certificate_version: int
    renewal_audit_id: str
    new_expires_on: str


# --- §3.2 personnel and jobs -------------------------------------------------
class PersonnelPayload(TypedDict, total=False):
    full_name: str
    role_code: str
    stamp_initials: str
    ai_agency: Optional[str]


class VesselJobPayload(TypedDict, total=False):
    certificate_id: str
    job_number: str
    customer_name: str
    vessel_type: str
    design_code: str
    mawp_psi: float
    design_temp_f: float
    mdmt_f: float
    inside_radius_in: float
    stress_ratio: float
    pneumatic_justification: Optional[str]


class CancelPayload(TypedDict):
    cancel_reason: str


# --- §3.3 design calculations ------------------------------------------------
class DesignCalculationPayload(TypedDict, total=False):
    expected_job_version: int
    component: str
    allowable_stress_psi: float
    corrosion_allowance_in: float
    thickness_nominal_in: float
    rt_extent_declared: str


class RejectPayload(TypedDict):
    reject_reason: str


class RevisePayload(TypedDict, total=False):
    rt_extent_declared: str
    allowable_stress_psi: float
    corrosion_allowance_in: float
    thickness_nominal_in: float


# --- §3.4 material heats and parts ------------------------------------------
class MaterialHeatPayload(TypedDict, total=False):
    heat_number: str
    spec: str
    form: str
    mtr_received: bool
    mtr_certified_yield_ksi: Optional[float]
    mtr_certified_tensile_ksi: Optional[float]
    quantity_received_lb: float


class MtrReviewPayload(TypedDict, total=False):
    decision: str
    reason: Optional[str]


class PartPayload(TypedDict, total=False):
    heat_id: str
    part_mark: str
    component_type: str
    issued_quantity_lb: float


class ScrapPayload(TypedDict):
    scrap_reason: str


# --- §3.5 procedures, qualifications, weld map ------------------------------
class WpsPayload(TypedDict, total=False):
    wps_number: str
    process: str
    base_metal_p_number: int
    filler_f_number: int
    thickness_min_in: float
    thickness_max_in: float
    position: str
    pwht_required: bool
    preheat_min_f: float
    supporting_pqr_number: str


class WelderQualificationPayload(TypedDict, total=False):
    welder_stamp: str
    welder_name: str
    wps_id: str
    position_qualified: str
    thickness_range_max_in: float
    qualified_on: str


class ContinuityLogPayload(TypedDict, total=False):
    continuity_date: str
    process: str


class ProductionWeldPayload(TypedDict, total=False):
    weld_number: str
    joint_category: str
    joint_type: str
    thickness_in: float
    wps_id: str
    part_a_id: str
    part_b_id: Optional[str]


class WeldCompletePayload(TypedDict, total=False):
    welder_qualification_id: str
    welded_at: str


# --- §3.6 examinations -------------------------------------------------------
class ExamResultPayload(TypedDict, total=False):
    result: str
    examined_coverage_pct: float
    indications_count: int
    exam_date: str


# --- §3.7 nonconformances ----------------------------------------------------
class DispositionPayload(TypedDict, total=False):
    disposition: str
    disposition_notes: str


class RepairWeldPayload(TypedDict, total=False):
    weld_number: str
    wps_id: str


# --- §3.8 heat treatment and pressure testing -------------------------------
class PwhtBatchPayload(TypedDict, total=False):
    job_id: str
    furnace_code: str
    scheduled_start: str
    scheduled_end: str
    soak_temp_f: float
    weld_ids: List[str]


class PwhtCompletePayload(TypedDict, total=False):
    actual_soak_minutes: int
    chart_record_number: str
    chart_uploaded: bool


class PressureTestPayload(TypedDict, total=False):
    job_id: str
    test_side: str
    test_type: str
    test_bay_code: str
    scheduled_start: str
    scheduled_end: str


class PressureTestResultPayload(TypedDict, total=False):
    result: str
    observed_pressure_psi: float
    observed_hold_minutes: int
    test_medium_temp_f: float


# --- §3.9 data package ------------------------------------------------------
class DataReportPayload(TypedDict, total=False):
    expected_job_version: int
    form_type: str


class StampPayload(TypedDict):
    nameplate_serial: str


# --- §2.5 clock -------------------------------------------------------------
class ClockPayload(TypedDict):
    current_utc: str
