"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, Optional, TypedDict


class UserRole(str, Enum):
    NETWORK_ARCHITECT = "NetworkArchitect"
    RF_ENGINEER = "RFEngineer"
    SPECTRUM_COORDINATOR = "SpectrumCoordinator"
    SPECTRUM_REGULATOR = "SpectrumRegulator"
    FIELD_TECHNICIAN = "FieldTechnician"


class EnterpriseStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    OFFBOARDED = "OFFBOARDED"


class SiteStatus(str, Enum):
    PLANNED = "PLANNED"
    SURVEYED = "SURVEYED"
    DESIGNED = "DESIGNED"
    COORDINATED = "COORDINATED"
    DEPLOYED = "DEPLOYED"
    OPERATIONAL = "OPERATIONAL"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"
    DECOMMISSIONED = "DECOMMISSIONED"


class SitePosture(str, Enum):
    DORMANT = "DORMANT"
    DESIGNING = "DESIGNING"
    COORDINATING = "COORDINATING"
    DEPLOYING = "DEPLOYING"
    OPERATIONAL = "OPERATIONAL"
    REMEDIATING = "REMEDIATING"


class SiteSurveyStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class CoverageDesignStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class CellSectorStatus(str, Enum):
    PLANNED = "PLANNED"
    CONFIGURED = "CONFIGURED"
    ON_AIR = "ON_AIR"
    DEGRADED = "DEGRADED"
    OFF_AIR = "OFF_AIR"
    DECOMMISSIONED = "DECOMMISSIONED"


class SpectrumLeaseStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class CoordinationRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    COORDINATING = "COORDINATING"
    APPROVED = "APPROVED"
    REGISTERED = "REGISTERED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class SpectrumAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    REVOKED = "REVOKED"


class DeviceStatus(str, Enum):
    INVENTORY = "INVENTORY"
    PROVISIONING = "PROVISIONING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DECOMMISSIONED = "DECOMMISSIONED"


class SIMProfileStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    BOUND = "BOUND"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class NetworkSliceStatus(str, Enum):
    DEFINED = "DEFINED"
    ACTIVATED = "ACTIVATED"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class ServiceContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    BREACHED = "BREACHED"
    RENEWED = "RENEWED"
    TERMINATED = "TERMINATED"


class MonitoringAlertStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    MITIGATING = "MITIGATING"
    RESOLVED = "RESOLVED"
    FALSE_ALARM = "FALSE_ALARM"


class CoverageRemediationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    REOPENED = "REOPENED"


# ---- Entity TypedDicts ----------------------------------------------------
# Most resources carry common fields (id, created_at, updated_at, version).
# SliceBinding and MonitoringAlert are deliberately lighter-weight: they carry
# only id and created_at.


class Enterprise(TypedDict, total=False):
    id: str
    legal_name: str
    erp_account_code: str
    industry_vertical: str
    security_posture: str
    status: str
    sla_credit_balance_cents: int
    active_site_count: int
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict, total=False):
    id: str
    enterprise_id: str
    site_code: str
    address: str
    geo_latitude: float
    geo_longitude: float
    site_area_sqm: float
    target_capacity_mbps: int
    target_availability_pct: float
    posture: str
    spectrum_utilization_mhz: int
    device_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SiteSurvey(TypedDict, total=False):
    id: str
    site_id: str
    surveyor_id: str
    survey_date: str
    measured_rsrp_dbm: int
    measured_sinr_db: int
    floor_plan_area_sqm: float
    building_material_class: str
    attenuation_factor_db: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CoverageDesign(TypedDict, total=False):
    id: str
    site_id: str
    design_revision: int
    based_on_survey_id: str
    predicted_capacity_mbps: int
    final_capacity_mbps: Optional[int]
    capacity_shortfall_mbps: int
    required_cell_count: int
    edge_compute_required: bool
    edge_compute_placement: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CellSector(TypedDict, total=False):
    id: str
    site_id: str
    sector_label: str
    azimuth_degrees: int
    height_m: float
    max_eirp_dbm: int
    cell_radius_m: int
    interference_margin_db: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SpectrumLease(TypedDict, total=False):
    id: str
    enterprise_id: str
    band_class: str
    center_frequency_mhz: float
    bandwidth_mhz: int
    lease_start_utc: str
    lease_end_utc: str
    priority_access_tier: str
    monthly_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SpectrumCoordinationRequest(TypedDict, total=False):
    id: str
    site_id: str
    requesting_coordinator_id: str
    band_class: str
    requested_bandwidth_mhz: int
    requested_start_utc: str
    requested_end_utc: str
    sas_registration_id: Optional[str]
    interference_report: Optional[Dict[str, Any]]
    status: str
    created_at: str
    updated_at: str
    version: int


class SpectrumAssignment(TypedDict, total=False):
    id: str
    cell_sector_id: str
    coordination_request_id: str
    spectrum_lease_id: str
    assigned_bandwidth_mhz: int
    assignment_start_utc: str
    assignment_end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict, total=False):
    id: str
    cell_sector_id: str
    site_id: str
    serial_number: str
    device_type: str
    imei: str
    sim_profile_id: Optional[str]
    provisioned_at_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SIMProfile(TypedDict, total=False):
    id: str
    enterprise_id: str
    iccid: str
    imsi: str
    ki_key_ref: str
    subscription_profile: str
    monthly_quota_mb: int
    status: str
    created_at: str
    updated_at: str
    version: int


class NetworkSlice(TypedDict, total=False):
    id: str
    site_id: str
    slice_name: str
    slice_type: str
    guaranteed_bandwidth_mbps: int
    max_latency_ms: int
    max_devices: int
    bound_device_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SliceBinding(TypedDict, total=False):
    # Deliberately lightweight: only id + created_at plus own fields.
    # updated_at and version are absent.
    id: str
    slice_id: str
    device_id: str
    bound_at_utc: str
    unbound_at_utc: Optional[str]
    created_at: str


class ServiceContract(TypedDict, total=False):
    id: str
    enterprise_id: str
    contract_code: str
    sla_tier: str
    contracted_availability_pct: float
    contracted_max_outage_minutes_per_month: int
    onsite_support_window: str
    contract_start_utc: str
    contract_end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MonitoringAlert(TypedDict, total=False):
    # Deliberately lightweight: only id + created_at plus own fields.
    # updated_at and version are absent.
    id: str
    site_id: str
    alert_class: str
    severity: str
    raised_at_utc: str
    resolved_at_utc: Optional[str]
    sla_credit_applied_cents: int
    status: str
    created_at: str


class CoverageRemediation(TypedDict, total=False):
    id: str
    site_id: str
    triggered_by_alert_id: str
    supersedes_remediation_id: Optional[str]
    remediation_plan: str
    additional_cells_planned: int
    additional_spectrum_mhz: int
    in_progress_started_at_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
