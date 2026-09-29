"""Request-body builders for every write endpoint of the CCR contract.

Each builder returns a fresh dict of contract-valid defaults which a caller
overrides field by field. Overrides are applied by merging into the default
dict rather than by passing keywords through to another builder, so a derived
builder can never hand the same field twice.

Money arrives as an integer count of cents, tonnage as a whole-ton integer,
measurements as JSON numbers at their declared precision, and dates as plain
``YYYY-MM-DD`` strings - never as quoted numbers and never as instants where
the contract asks for a calendar date.
"""

from typing import Any, Dict, Optional

from .constants import (
    BASIS_INTERWELL,
    DISCIPLINE_CIVIL,
    DISCIPLINE_GEOTECHNICAL,
    DISCIPLINE_HYDROGEOLOGY,
    DISCIPLINE_STATISTICS,
    DOC_SHA256,
    DOC_URI,
    EVENT_TYPE_BACKGROUND,
    EROSION_MAJOR,
    EROSION_NONE,
    FLAG_DETECTED,
    HAZARD_SIGNIFICANT,
    JUSTIFICATION_NO_ALTERNATIVE_CAPACITY,
    LINER_COMPOSITE_LINED,
    METHOD_CLOSURE_IN_PLACE,
    PARAM_SULFATE,
    POSTING_STABILITY_ASSESSMENT,
    PRODUCT_CONCRETE_POZZOLAN,
    UNIT_TYPE_SURFACE_IMPOUNDMENT,
    UOM_MG_PER_L,
    WELL_ROLE_BACKGROUND,
    WELL_ROLE_DOWNGRADIENT,
)


def _merged(defaults: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides onto a copy of the defaults, dropping explicit removals.

    An override whose value is the sentinel ``OMIT`` deletes the field, which is
    how a test asks for a payload that is missing a required field.
    """
    payload = dict(defaults)
    for key, value in overrides.items():
        if value is OMIT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


class _Omit:
    """Sentinel meaning "leave this field out of the payload entirely"."""

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return "OMIT"


OMIT = _Omit()


# ── Logical clock (§2.5) ──────────────────────────────────────────────────


def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}


# ── Disposal units (§3.1) ─────────────────────────────────────────────────


def unit_payload(unit_code: str = "IMP-0101", **overrides: Any) -> Dict[str, Any]:
    """A composite-lined surface impoundment that sites cleanly.

    Its five siting measurements clear every clause of the location-restriction
    chain, so the verdict is UNRESTRICTED and the posture COMPLIANT.
    """
    defaults = {
        "unit_code": unit_code,
        "unit_name": "Ash Pond A",
        "unit_type": UNIT_TYPE_SURFACE_IMPOUNDMENT,
        "plant_code": "PLNT01",
        "liner_class": LINER_COMPOSITE_LINED,
        "hazard_potential_class": HAZARD_SIGNIFICANT,
        "original_ash_in_place_tons": 480000,
        "cessation_date": "2026-03-31",
        "uppermost_aquifer_separation_ft": 12.50,
        "wetland_distance_ft": 2000.00,
        "seismic_pga_g": 0.050,
        "fault_distance_ft": 1200.00,
        "unstable_area_flag": False,
    }
    return _merged(defaults, overrides)


def begin_closure_payload(initiated_on: str = "2026-08-01", **overrides: Any) -> Dict[str, Any]:
    return _merged({"initiated_on": initiated_on}, overrides)


def complete_closure_payload(completed_on: str = "2026-08-01", **overrides: Any) -> Dict[str, Any]:
    return _merged({"completed_on": completed_on}, overrides)


# ── Qualified professionals (§3.2) ────────────────────────────────────────


def professional_payload(
    full_name: str = "Dana Reyes",
    license_number: str = "PE-11001",
    discipline: str = DISCIPLINE_GEOTECHNICAL,
    **overrides: Any,
) -> Dict[str, Any]:
    """A North Carolina licensee; license_status is deliberately omitted so the
    server's ACTIVE default is exercised unless a test supplies one."""
    defaults = {
        "full_name": full_name,
        "license_number": license_number,
        "license_state": "NC",
        "discipline": discipline,
    }
    return _merged(defaults, overrides)


def geotechnical_engineer_payload(**overrides: Any) -> Dict[str, Any]:
    defaults = professional_payload("Dana Reyes", "PE-11001", DISCIPLINE_GEOTECHNICAL)
    return _merged(defaults, overrides)


def civil_engineer_payload(**overrides: Any) -> Dict[str, Any]:
    defaults = professional_payload("Owen Park", "PE-22002", DISCIPLINE_CIVIL)
    return _merged(defaults, overrides)


def hydrogeologist_payload(**overrides: Any) -> Dict[str, Any]:
    defaults = professional_payload("Mia Chen", "HG-33003", DISCIPLINE_HYDROGEOLOGY)
    return _merged(defaults, overrides)


def statistician_payload(**overrides: Any) -> Dict[str, Any]:
    defaults = professional_payload("Rae Novak", "ST-44004", DISCIPLINE_STATISTICS)
    return _merged(defaults, overrides)


def second_civil_engineer_payload(**overrides: Any) -> Dict[str, Any]:
    defaults = professional_payload("Lena Ortiz", "PE-55005", DISCIPLINE_CIVIL)
    return _merged(defaults, overrides)


def license_status_payload(
    license_status: str, effective_on: str = "2026-08-01", **overrides: Any
) -> Dict[str, Any]:
    return _merged({"license_status": license_status, "effective_on": effective_on}, overrides)


# ── Structural stability assessments (§3.2) ───────────────────────────────


def stability_payload(unit_id: str, assessed_on: str = "2026-07-15", **overrides: Any) -> Dict[str, Any]:
    """Factors of safety that clear all three minima, so the verdict is ADEQUATE."""
    defaults = {
        "unit_id": unit_id,
        "assessed_on": assessed_on,
        "factor_of_safety_static": 1.60,
        "factor_of_safety_seismic": 1.10,
        "factor_of_safety_liquefaction": 1.30,
    }
    return _merged(defaults, overrides)


# ── Monitoring wells (§3.3) ───────────────────────────────────────────────


def well_payload(
    unit_id: str,
    well_code: str,
    well_role: str = WELL_ROLE_DOWNGRADIENT,
    screen_top_ft: float = 20.00,
    screen_bottom_ft: float = 40.00,
    **overrides: Any,
) -> Dict[str, Any]:
    defaults = {
        "unit_id": unit_id,
        "well_code": well_code,
        "well_role": well_role,
        "aquifer_zone": "UPPER SAND",
        "screen_top_ft": screen_top_ft,
        "screen_bottom_ft": screen_bottom_ft,
        "installed_on": "2024-06-01",
    }
    return _merged(defaults, overrides)


def background_well_payload(
    unit_id: str, well_code: str = "BG-01", **overrides: Any
) -> Dict[str, Any]:
    defaults = well_payload(
        unit_id, well_code, WELL_ROLE_BACKGROUND, screen_top_ft=22.00, screen_bottom_ft=42.00
    )
    return _merged(defaults, overrides)


def downgradient_well_payload(
    unit_id: str, well_code: str = "DG-01", **overrides: Any
) -> Dict[str, Any]:
    defaults = well_payload(
        unit_id, well_code, WELL_ROLE_DOWNGRADIENT, screen_top_ft=20.00, screen_bottom_ft=40.00
    )
    return _merged(defaults, overrides)


def decommission_payload(
    decommissioned_on: str = "2026-07-01", reason: str = "Casing failure during redevelopment"
) -> Dict[str, Any]:
    return {"decommissioned_on": decommissioned_on, "decommission_reason": reason}


# ── Monitoring programs (§3.3) ────────────────────────────────────────────


def program_config_payload(
    background_window_start_on: str = "2025-01-01",
    background_window_end_on: str = "2025-12-31",
    **overrides: Any,
) -> Dict[str, Any]:
    """The standard interwell configuration over the whole of calendar 2025."""
    defaults = {
        "comparison_basis": BASIS_INTERWELL,
        "background_window_start_on": background_window_start_on,
        "background_window_end_on": background_window_end_on,
    }
    return _merged(defaults, overrides)


def certify_network_payload(certified_on: str = "2026-01-05", **overrides: Any) -> Dict[str, Any]:
    return _merged({"certified_on": certified_on}, overrides)


def assurance_payload(
    remedy_base_cost_usd_cents: int = 480000000,
    remedy_duration_years: int = 20,
    **overrides: Any,
) -> Dict[str, Any]:
    defaults = {
        "remedy_base_cost_usd_cents": remedy_base_cost_usd_cents,
        "remedy_duration_years": remedy_duration_years,
        "remedy_description": "Pump-and-treat with a downgradient interception trench",
    }
    return _merged(defaults, overrides)


# ── Sampling rounds and laboratory results (§3.4) ─────────────────────────


def sampling_event_payload(
    program_id: str,
    event_code: str,
    sampled_on: str,
    event_type: str = EVENT_TYPE_BACKGROUND,
    **overrides: Any,
) -> Dict[str, Any]:
    defaults = {
        "program_id": program_id,
        "event_code": event_code,
        "event_type": event_type,
        "sampled_on": sampled_on,
    }
    return _merged(defaults, overrides)


def result_payload(
    sampling_event_id: str,
    well_id: str,
    concentration: float,
    expected_sampling_event_version: int,
    parameter_code: str = PARAM_SULFATE,
    **overrides: Any,
) -> Dict[str, Any]:
    """A detected result; reporting_limit is omitted, as the contract permits."""
    defaults = {
        "sampling_event_id": sampling_event_id,
        "well_id": well_id,
        "parameter_code": parameter_code,
        "concentration": concentration,
        "unit_of_measure": UOM_MG_PER_L,
        "detection_flag": FLAG_DETECTED,
        "expected_sampling_event_version": expected_sampling_event_version,
    }
    return _merged(defaults, overrides)


def validate_event_payload(validated_on: str, **overrides: Any) -> Dict[str, Any]:
    return _merged({"validated_on": validated_on}, overrides)


# ── Statistical evaluations (§3.5) ────────────────────────────────────────


def evaluation_payload(
    program_id: str,
    compliance_well_id: str,
    evaluation_code: str,
    parameter_code: str = PARAM_SULFATE,
    **overrides: Any,
) -> Dict[str, Any]:
    defaults = {
        "program_id": program_id,
        "compliance_well_id": compliance_well_id,
        "evaluation_code": evaluation_code,
        "parameter_code": parameter_code,
    }
    return _merged(defaults, overrides)


def asd_submission_payload(
    certifying_professional_id: str, submitted_on: str = "2026-08-01", **overrides: Any
) -> Dict[str, Any]:
    defaults = {
        "submitted_on": submitted_on,
        "asd_narrative": "Upgradient agricultural sulfate loading explains the increase",
        "certifying_professional_id": certifying_professional_id,
    }
    return _merged(defaults, overrides)


def asd_decision_payload(decision: str, decided_on: str = "2026-08-05", **overrides: Any) -> Dict[str, Any]:
    return _merged({"decision": decision, "decided_on": decided_on}, overrides)


# ── Closure plans (§3.6) ──────────────────────────────────────────────────


def closure_plan_payload(
    unit_id: str,
    plan_code: str = "PLAN-01",
    selected_method: str = METHOD_CLOSURE_IN_PLACE,
    **overrides: Any,
) -> Dict[str, Any]:
    """The cheap-cap cost basis: closure in place is both cheaper and recommended.

    Nominal totals come out 130000000 and 930000000; the discounted variant
    lands on 119600444 and 919600444 for a 86.99 percent variance, so the
    recommendation is CLOSURE_IN_PLACE and the matching selection needs no
    justification.
    """
    defaults = {
        "unit_id": unit_id,
        "plan_code": plan_code,
        "selected_method": selected_method,
        "in_place_capital_usd_cents": 100000000,
        "in_place_annual_care_usd_cents": 1000000,
        "removal_capital_usd_cents": 900000000,
        "removal_annual_care_usd_cents": 1000000,
        "care_period_years": 30,
    }
    return _merged(defaults, overrides)


def engineering_certification_payload(certified_on: str = "2026-08-01", **overrides: Any) -> Dict[str, Any]:
    defaults = {
        "certified_on": certified_on,
        "design_narrative": (
            "Composite cap with 24-inch protective layer and perimeter toe drain regrade"
        ),
    }
    return _merged(defaults, overrides)


def cost_certification_payload(certified_on: str = "2026-08-01", **overrides: Any) -> Dict[str, Any]:
    defaults = {
        "certified_on": certified_on,
        "cost_basis_note": "Unit-price bid tabulation, 2026 dollars, 3 percent discount basis",
    }
    return _merged(defaults, overrides)


def approve_plan_payload(
    approved_on: str = "2026-08-01", permit_reference: str = "PERMIT-2026-A", **overrides: Any
) -> Dict[str, Any]:
    return _merged({"approved_on": approved_on, "permit_reference": permit_reference}, overrides)


# ── Closure extension requests (§3.6) ─────────────────────────────────────


def extension_request_payload(
    unit_id: str, requested_months: int = 12, **overrides: Any
) -> Dict[str, Any]:
    defaults = {
        "unit_id": unit_id,
        "requested_months": requested_months,
        "justification_category": JUSTIFICATION_NO_ALTERNATIVE_CAPACITY,
        "narrative": "No permitted alternative disposal capacity is available in the service area",
    }
    return _merged(defaults, overrides)


def extension_decision_payload(
    decision: str,
    decided_on: str = "2026-08-01",
    granted_months: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"decision": decision, "decided_on": decided_on}
    if granted_months is not None:
        defaults["granted_months"] = granted_months
    return _merged(defaults, overrides)


def rescind_extension_payload(
    rescinded_on: str = "2026-08-01", reason: str = "Alternative capacity became available"
) -> Dict[str, Any]:
    return {"rescinded_on": rescinded_on, "rescission_reason": reason}


# ── Beneficial reuse agreements and shipments (§3.7) ──────────────────────


def reuse_agreement_payload(
    unit_id: str,
    agreement_code: str = "AGR-01",
    committed_tons: int = 30000,
    **overrides: Any,
) -> Dict[str, Any]:
    """Class F pozzolan ash at a 60-mile haul: score 70.30, specification met."""
    defaults = {
        "unit_id": unit_id,
        "agreement_code": agreement_code,
        "product_type": PRODUCT_CONCRETE_POZZOLAN,
        "offtaker_name": "Piedmont Ready-Mix",
        "committed_tons": committed_tons,
        "commitment_start_on": "2026-07-01",
        "commitment_end_on": "2026-12-31",
        "loi_percent": 6.00,
        "retained_325_percent": 20.00,
        "oxide_sum_percent": 82.00,
        "market_price_usd_cents_per_ton": 3200,
        "haul_distance_miles": 60,
    }
    return _merged(defaults, overrides)


def qualify_agreement_payload(qualified_on: str = "2026-08-01", **overrides: Any) -> Dict[str, Any]:
    return _merged({"qualified_on": qualified_on}, overrides)


def activate_agreement_payload(activated_on: str = "2026-08-01", **overrides: Any) -> Dict[str, Any]:
    return _merged({"activated_on": activated_on}, overrides)


def shipment_payload(
    agreement_id: str,
    shipment_code: str,
    tons: int,
    expected_unit_version: int,
    shipped_on: str = "2026-08-01",
    **overrides: Any,
) -> Dict[str, Any]:
    defaults = {
        "agreement_id": agreement_id,
        "shipment_code": shipment_code,
        "tons": tons,
        "shipped_on": shipped_on,
        "expected_unit_version": expected_unit_version,
    }
    return _merged(defaults, overrides)


def return_shipment_payload(
    expected_unit_version: int,
    returned_on: str = "2026-08-01",
    reason: str = "Offtaker rejected the load on fineness",
    **overrides: Any,
) -> Dict[str, Any]:
    defaults = {
        "returned_on": returned_on,
        "return_reason": reason,
        "expected_unit_version": expected_unit_version,
    }
    return _merged(defaults, overrides)


# ── Cap inspections (§3.8) ────────────────────────────────────────────────


def cap_inspection_payload(unit_id: str, inspected_on: str, **overrides: Any) -> Dict[str, Any]:
    """A clean cover: no erosion, settlement inside 6.00 inches, cover above 70 percent."""
    defaults = {
        "unit_id": unit_id,
        "inspected_on": inspected_on,
        "erosion_severity": EROSION_NONE,
        "settlement_inches": 1.50,
        "vegetation_cover_pct": 92.00,
    }
    return _merged(defaults, overrides)


def deficient_cap_inspection_payload(
    unit_id: str, inspected_on: str, **overrides: Any
) -> Dict[str, Any]:
    """A cover that fails all three criteria, for a DEFICIENT verdict."""
    defaults = cap_inspection_payload(unit_id, inspected_on)
    defaults.update(
        {
            "erosion_severity": EROSION_MAJOR,
            "settlement_inches": 9.00,
            "vegetation_cover_pct": 40.00,
        }
    )
    return _merged(defaults, overrides)


# ── Public postings (§3.9) ────────────────────────────────────────────────


def posting_payload(
    unit_id: str,
    posted_on: str,
    posting_type: str = POSTING_STABILITY_ASSESSMENT,
    **overrides: Any,
) -> Dict[str, Any]:
    defaults = {
        "unit_id": unit_id,
        "posting_type": posting_type,
        "posted_on": posted_on,
        "document_uri": DOC_URI,
        "document_sha256": DOC_SHA256,
    }
    return _merged(defaults, overrides)


def withdraw_posting_payload(
    withdrawn_on: str, reason: str = "Superseded by a corrected digest"
) -> Dict[str, Any]:
    return {"withdrawn_on": withdrawn_on, "withdrawal_reason": reason}
