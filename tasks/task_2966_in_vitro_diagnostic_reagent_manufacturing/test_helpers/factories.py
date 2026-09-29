"""Payload factories — one per creatable resource, input fields only.

Every numeric quantity is emitted as a JSON number, and every field the PRD
declares as an ISO 8601 UTC instant is emitted as a full instant with three
fractional digits (PRD §2.4).  Codes are generated unique per call so a test
never collides with another test's reference data.
"""
import uuid
from typing import List, Optional

from .constants import TEST_DEFAULTS, clock_plus


def unique_suffix(width: int = 8) -> str:
    return uuid.uuid4().hex[:width].upper()


def unique_material_code(prefix: str = "MAT") -> str:
    """A material_code between 3 and 32 characters long (PRD §3.1)."""
    return f"{prefix}-{unique_suffix()}"


def unique_product_code(prefix: str = "PRD") -> str:
    return f"{prefix}-{unique_suffix()}"


def unique_vendor_lot_code(prefix: str = "VL") -> str:
    return f"{prefix}-{unique_suffix()}"


def unique_lot_code(prefix: str = "LOT") -> str:
    return f"{prefix}-{unique_suffix()}"


def unique_line_code(prefix: str = "LINE") -> str:
    return f"{prefix}-{unique_suffix(6)}"


def unique_chamber_code(prefix: str = "CHM") -> str:
    return f"{prefix}-{unique_suffix(6)}"


def unique_document_ref(prefix: str = "DOC") -> str:
    return f"{prefix}-{unique_suffix()}"


def unique_customer_code(prefix: str = "CUST") -> str:
    return f"{prefix}-{unique_suffix(6)}"


def unique_complaint_code(prefix: str = "CMP") -> str:
    return f"{prefix}-{unique_suffix()}"


# ---------------------------------------------------------------------------
# Raw material qualification
# ---------------------------------------------------------------------------
def material_specification_payload(**overrides) -> dict:
    """Acceptance specification for one raw material.

    Defaults describe a wide-open ANTIBODY specification requiring all four
    acceptance tests, so a single set of passing measurements works for both
    acceptance modes.
    """
    payload = {
        "material_code": unique_material_code(),
        "material_type": "ANTIBODY",
        "potency_min_pct": 90.0,
        "potency_max_pct": 110.0,
        "endotoxin_max_eu_per_ml": 10.0,
        "purity_min_pct": 95.0,
        "required_test_codes": ["POTENCY", "PURITY", "ENDOTOXIN", "IDENTITY"],
    }
    payload.update(overrides)
    return payload


def material_lot_payload(material_specification_id: str, **overrides) -> dict:
    payload = {
        "material_specification_id": material_specification_id,
        "vendor_lot_code": unique_vendor_lot_code(),
        "received_quantity_units": TEST_DEFAULTS["RECEIVED_QUANTITY_UNITS"],
        "expiry_date": clock_plus(days=365),
    }
    payload.update(overrides)
    return payload


def material_lot_disposition_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Design control and clearance
# ---------------------------------------------------------------------------
def product_specification_payload(**overrides) -> dict:
    payload = {
        "product_code": unique_product_code(),
        "reference_material_code": unique_material_code("REF"),
        "required_material_codes": [unique_material_code()],
        "release_test_codes": ["ACTIVITY", "PRECISION"],
        "shelf_life_months_claim": TEST_DEFAULTS["SHELF_LIFE_MONTHS_CLAIM"],
        "storage_condition": "TWO_TO_EIGHT_C",
    }
    payload.update(overrides)
    return payload


def design_control_record_payload(product_specification_id: str,
                                 record_type: str,
                                 expected_product_specification_version: int,
                                 traces_to_record_id: Optional[str] = None,
                                 **overrides) -> dict:
    """A design-control artifact. ``traces_to_record_id`` is omitted entirely
    for a DESIGN_INPUT, where the PRD requires it to be null."""
    payload = {
        "product_specification_id": product_specification_id,
        "record_type": record_type,
        "document_ref": unique_document_ref(),
        "expected_product_specification_version":
            expected_product_specification_version,
    }
    if traces_to_record_id is not None:
        payload["traces_to_record_id"] = traces_to_record_id
    payload.update(overrides)
    return payload


def clearance_payload(**overrides) -> dict:
    payload = {"submission_ref": f"SUB-{unique_suffix()}"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Finished lots, dispensing, filling
# ---------------------------------------------------------------------------
def reagent_lot_payload(product_specification_id: str, **overrides) -> dict:
    payload = {
        "product_specification_id": product_specification_id,
        "lot_code": unique_lot_code(),
        "planned_units": TEST_DEFAULTS["PLANNED_UNITS"],
    }
    payload.update(overrides)
    return payload


def lot_component_payload(material_lot_id: str, component_role: str,
                          expected_reagent_lot_version: int,
                          quantity_used: float = None, **overrides) -> dict:
    payload = {
        "material_lot_id": material_lot_id,
        "component_role": component_role,
        "quantity_used": (TEST_DEFAULTS["QUANTITY_USED"]
                          if quantity_used is None else quantity_used),
        "expected_reagent_lot_version": expected_reagent_lot_version,
    }
    payload.update(overrides)
    return payload


def reagent_lot_disposition_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def distribution_status_payload(distribution_status: str, **overrides) -> dict:
    payload = {"distribution_status": distribution_status}
    payload.update(overrides)
    return payload


def fill_run_payload(reagent_lot_id: str, line_code: str = None,
                     scheduled_start: str = None, scheduled_end: str = None,
                     **overrides) -> dict:
    payload = {
        "reagent_lot_id": reagent_lot_id,
        "line_code": line_code or unique_line_code(),
        "formulation_batch_code": f"BULK-{unique_suffix()}",
        "scheduled_start": scheduled_start or clock_plus(days=1),
        "scheduled_end": scheduled_end or clock_plus(days=1, hours=4),
        "planned_fill_units": TEST_DEFAULTS["PLANNED_FILL_UNITS"],
    }
    payload.update(overrides)
    return payload


def monitoring_sample_payload(sample_type: str, result_value: float,
                              sampled_at: str = None, **overrides) -> dict:
    payload = {
        "sample_type": sample_type,
        "location_code": f"LOC-{unique_suffix(4)}",
        "result_value": result_value,
        "sampled_at": sampled_at or clock_plus(days=1, hours=1),
    }
    payload.update(overrides)
    return payload


def fill_run_complete_payload(filled_units: int, **overrides) -> dict:
    payload = {"filled_units": filled_units}
    payload.update(overrides)
    return payload


def fill_run_abort_payload(abort_reason: str = "Line deviation", **overrides) -> dict:
    payload = {"abort_reason": abort_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Measurements
# ---------------------------------------------------------------------------
def material_test_result_payload(material_lot_id: str, test_code: str,
                                measured_value: float, is_retest: bool = None,
                                **overrides) -> dict:
    """A MATERIAL_LOT measurement carries material_lot_id and nothing else
    subject-specific (PRD §3.1)."""
    payload = {
        "subject_type": "MATERIAL_LOT",
        "material_lot_id": material_lot_id,
        "test_code": test_code,
        "measured_value": measured_value,
    }
    if is_retest is not None:
        payload["is_retest"] = is_retest
    payload.update(overrides)
    return payload


def release_test_result_payload(reagent_lot_id: str, test_code: str,
                                measured_value: float,
                                reference_measured_value: float,
                                **overrides) -> dict:
    """A REAGENT_LOT measurement carries reagent_lot_id and
    reference_measured_value (PRD §3.5)."""
    payload = {
        "subject_type": "REAGENT_LOT",
        "reagent_lot_id": reagent_lot_id,
        "test_code": test_code,
        "measured_value": measured_value,
        "reference_measured_value": reference_measured_value,
    }
    payload.update(overrides)
    return payload


def stability_test_result_payload(stability_study_id: str, month_index: int,
                                 test_code: str, measured_value: float,
                                 **overrides) -> dict:
    """A STABILITY_TIMEPOINT measurement carries stability_study_id and
    month_index (PRD §3.6)."""
    payload = {
        "subject_type": "STABILITY_TIMEPOINT",
        "stability_study_id": stability_study_id,
        "month_index": month_index,
        "test_code": test_code,
        "measured_value": measured_value,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Stability and bridging
# ---------------------------------------------------------------------------
def stability_study_payload(product_specification_id: str, reagent_lot_id: str,
                            study_type: str = "REAL_TIME",
                            chamber_code: str = None,
                            planned_timepoints_months: List[int] = None,
                            protocol_start: str = None,
                            protocol_end: str = None, **overrides) -> dict:
    payload = {
        "product_specification_id": product_specification_id,
        "reagent_lot_id": reagent_lot_id,
        "study_type": study_type,
        "chamber_code": chamber_code or unique_chamber_code(),
        "storage_temp_c": 5.0 if study_type == "REAL_TIME" else 35.0,
        "protocol_start": protocol_start or clock_plus(days=0),
        "protocol_end": protocol_end or clock_plus(days=365),
        "planned_timepoints_months": (list(planned_timepoints_months)
                                      if planned_timepoints_months is not None
                                      else [0, 3, 6, 9, 12]),
        "baseline_value": TEST_DEFAULTS["BASELINE_VALUE"],
    }
    payload.update(overrides)
    return payload


def bridging_study_payload(predicate_lot_id: str, candidate_lot_id: str,
                           changed_material_lot_id: str,
                           paired_test_codes: List[str] = None,
                           **overrides) -> dict:
    payload = {
        "predicate_lot_id": predicate_lot_id,
        "candidate_lot_id": candidate_lot_id,
        "changed_material_lot_id": changed_material_lot_id,
        "paired_test_codes": (list(paired_test_codes)
                              if paired_test_codes is not None
                              else ["ACTIVITY"]),
    }
    payload.update(overrides)
    return payload


def bridging_decision_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Complaints
# ---------------------------------------------------------------------------
def complaint_payload(reagent_lot_id: str, **overrides) -> dict:
    payload = {
        "reagent_lot_id": reagent_lot_id,
        "complaint_code": unique_complaint_code(),
        "narrative": "Customer reports no signal on the calibration channel.",
    }
    payload.update(overrides)
    return payload


def triage_payload(severity: str, malfunction_suspected: bool, **overrides) -> dict:
    payload = {"severity": severity, "malfunction_suspected": malfunction_suspected}
    payload.update(overrides)
    return payload


def malfunction_report_payload(**overrides) -> dict:
    payload = {"report_ref": f"MDR-{unique_suffix()}"}
    payload.update(overrides)
    return payload


def field_action_payload(field_action: str, **overrides) -> dict:
    payload = {"field_action": field_action}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Distribution
# ---------------------------------------------------------------------------
def distribution_order_payload(product_specification_id: str,
                               requested_units: int = None,
                               required_min_shelf_life_days: int = 0,
                               ship_by: str = None, **overrides) -> dict:
    payload = {
        "product_specification_id": product_specification_id,
        "customer_code": unique_customer_code(),
        "requested_units": (TEST_DEFAULTS["REQUESTED_UNITS"]
                            if requested_units is None else requested_units),
        "required_min_shelf_life_days": required_min_shelf_life_days,
        "ship_by": ship_by or clock_plus(days=30),
    }
    payload.update(overrides)
    return payload


def cold_chain_event_payload(excursion_minutes: float, max_temp_c: float,
                             delivery_confirmed: bool = None, **overrides) -> dict:
    payload = {
        "excursion_minutes": excursion_minutes,
        "max_temp_c": max_temp_c,
    }
    if delivery_confirmed is not None:
        payload["delivery_confirmed"] = delivery_confirmed
    payload.update(overrides)
    return payload


def cancel_allocation_payload(reason: str = "Customer cancelled", **overrides) -> dict:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload
