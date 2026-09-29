"""Request payload shapes for the Biosolids Management & Land Application API.

Every numeric field is typed ``int`` or ``float`` so factories emit JSON numbers,
never strings.
"""

from typing import List, Optional

try:  # pragma: no cover - Python 3.11+ has NotRequired in typing
    from typing import NotRequired, TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import NotRequired, TypedDict


class FacilityPayload(TypedDict):
    name: str
    npdes_permit_number: str
    storage_capacity_wet_tons: float
    daily_production_wet_tons: float
    loadout_bay_count: int


class PollutantLimitPayload(TypedDict):
    analyte: str
    ceiling_mg_kg: float
    monthly_avg_mg_kg: float
    aplr_kg_per_hectare_yr: float
    cplr_kg_per_hectare: float


class BatchPayload(TypedDict):
    facility_id: str
    batch_code: str
    wet_tons: float
    dry_tons_in: float
    volatile_solids_in_pct: float
    percent_solids: float
    detention_days: NotRequired[float]
    digester_temp_c: NotRequired[float]
    stabilization_process: NotRequired[str]
    pathogen_option: NotRequired[str]
    vector_option: NotRequired[str]
    fecal_coliform_mpn_per_g: NotRequired[Optional[float]]
    salmonella_mpn_per_4g: NotRequired[Optional[float]]
    sour_mg_o2_per_g_hr: NotRequired[Optional[float]]
    aerobic_process_days: NotRequired[float]
    nh4_n_mg_kg: NotRequired[float]
    organic_n_mg_kg: NotRequired[float]
    nitrate_n_mg_kg: NotRequired[float]
    total_p_mg_kg: NotRequired[float]


class AdvanceProcessPayload(TypedDict):
    to_status: str
    dry_tons_out: NotRequired[float]
    volatile_solids_out_pct: NotRequired[float]
    detention_days: NotRequired[float]
    digester_temp_c: NotRequired[float]
    percent_solids: NotRequired[float]


class LabResultPayload(TypedDict):
    analyte: str
    concentration_mg_kg: float
    sampling_event_index: int
    analyzed_at: str
    method_code: NotRequired[str]


class SitePayload(TypedDict):
    facility_id: str
    site_code: str
    acres: float
    crop_type: str
    crop_n_demand_lb_per_acre: float
    crop_p_removal_lb_per_acre: float
    soil_p_index: int
    setback_to_well_ft: int
    setback_to_surface_water_ft: int
    allowed_application_months: List[int]
    soil_ph: NotRequired[float]
    depth_to_groundwater_ft: NotRequired[float]
    slope_pct: NotRequired[float]
    nearest_residence_ft: NotRequired[int]
    reapplication_interval_days: NotRequired[int]


class PermitDecisionPayload(TypedDict):
    decision: str
    permit_number: NotRequired[str]
    decision_note: NotRequired[str]


class AgreementPayload(TypedDict):
    site_id: str
    expected_site_version: int
    farmer_user_id: str
    farm_name: str
    term_start: str
    term_end: str
    max_dry_tons_per_acre: float
    notice_days: NotRequired[int]


class ApplicationEventPayload(TypedDict):
    site_id: str
    batch_id: str
    agreement_id: str
    window_start: str
    window_end: str
    application_method: str
    acres_treated: float
    planned_dry_tons: float
    incorporation_within_hours: NotRequired[Optional[float]]


class HaulTicketPayload(TypedDict):
    truck_id: str
    wet_tons: float
    depart_at: str
    return_at: str
    odometer_miles: NotRequired[float]


class CompletePayload(TypedDict):
    applied_dry_tons: NotRequired[float]
    incorporation_within_hours: NotRequired[Optional[float]]


class OutletPayload(TypedDict):
    name: str
    outlet_type: str
    gate_fee_per_wet_ton: float
    haul_rate_per_mile_per_wet_ton: float
    min_load_wet_tons: float
    max_annual_wet_tons: float
    min_percent_solids: NotRequired[float]


class DiversionOrderPayload(TypedDict):
    batch_id: str
    outlet_id: str
    expected_batch_version: int
    dry_tons: float
    wet_tons: float
    haul_miles: float


class ComplaintPayload(TypedDict):
    facility_id: str
    received_at: str
    severity: str
    site_id: NotRequired[Optional[str]]
    description: NotRequired[str]
    complainant_contact: NotRequired[str]


class ComplaintResolvePayload(TypedDict):
    outcome: str
    investigation_note: NotRequired[str]
    resolution_action: NotRequired[str]


class AnnualReportPayload(TypedDict):
    facility_id: str
    report_year: int
    public_summary: NotRequired[str]


class WeatherObservationPayload(TypedDict):
    site_id: str
    rainfall_in_24h: float
    forecast_rainfall_in_48h: float
    frozen_ground: bool


class ClockPayload(TypedDict):
    now: str
