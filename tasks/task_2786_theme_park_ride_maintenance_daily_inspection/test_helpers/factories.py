"""Payload factories — one per entity, carrying only caller-supplied input fields."""

from typing import Optional

from .constants import TEST_DEFAULTS

DEFAULTS = {
    "ATTRACTION_NAME": "Test Attraction",
    "MANUFACTURER": "Vekoma",
    "MODEL_CODE": "TA-1",
    "COMPONENT_NAME": "Test Component",
    "PART_NUMBER": "PN-0001",
    "BAY_NAME": "Test Bay",
}


# --- Attractions (PRD §3.1) -------------------------------------------------
def create_attraction_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["ATTRACTION_NAME"],
        "park_area": "FRONTIER",
        "manufacturer": DEFAULTS["MANUFACTURER"],
        "model_code": DEFAULTS["MODEL_CODE"],
        "ride_class": "THRILL",
        "theoretical_hourly_capacity": TEST_DEFAULTS["THEORETICAL_HOURLY_CAPACITY"],
        "min_operators_required": TEST_DEFAULTS["MIN_OPERATORS_REQUIRED"],
        "parts_budget_cents": TEST_DEFAULTS["PARTS_BUDGET_CENTS"],
    }
    payload.update(overrides)
    return payload


def log_cycles_payload(service_date: str, cycles_added: int, **overrides) -> dict:
    payload = {"service_date": service_date, "cycles_added": cycles_added}
    payload.update(overrides)
    return payload


# --- Components (PRD §3.1) --------------------------------------------------
def create_component_payload(attraction_id: str, **overrides) -> dict:
    payload = {
        "attraction_id": attraction_id,
        "name": DEFAULTS["COMPONENT_NAME"],
        "component_type": "BRAKE",
        "criticality": "ESSENTIAL",
        "ndt_interval_cycles": TEST_DEFAULTS["NDT_INTERVAL_CYCLES"],
        "ndt_interval_days": TEST_DEFAULTS["NDT_INTERVAL_DAYS"],
    }
    payload.update(overrides)
    return payload


def record_ndt_payload(ndt_method: str = "ULTRASONIC", result: str = "PASS") -> dict:
    return {"ndt_method": ndt_method, "result": result}


# --- Templates and checklist lines (PRD §3.1) -------------------------------
def create_inspection_template_payload(
    attraction_id: str, effective_from_date: str = "2026-08-01", **overrides
) -> dict:
    payload = {
        "attraction_id": attraction_id,
        "effective_from_date": effective_from_date,
    }
    payload.update(overrides)
    return payload


def append_checklist_item_payload(
    sequence_no: int = 1,
    description: str = "Verify the safety check",
    severity_class: str = "ADVISORY",
    **overrides,
) -> dict:
    payload = {
        "sequence_no": sequence_no,
        "description": description,
        "severity_class": severity_class,
    }
    payload.update(overrides)
    return payload


def activate_inspection_template_payload(expected_attraction_version: int) -> dict:
    return {"expected_attraction_version": expected_attraction_version}


# --- Daily inspections (PRD §3.2, §3.3) -------------------------------------
def create_daily_inspection_payload(
    attraction_id: str, service_date: str = "2026-08-01", **overrides
) -> dict:
    payload = {"attraction_id": attraction_id, "service_date": service_date}
    payload.update(overrides)
    return payload


def record_item_result_payload(outcome: str, note: Optional[str] = None) -> dict:
    payload = {"outcome": outcome}
    if note is not None:
        payload["note"] = note
    return payload


def reject_inspection_payload(rejection_reason: str = "Rework required") -> dict:
    return {"rejection_reason": rejection_reason}


# --- Downtime events (PRD §3.4) ---------------------------------------------
def create_downtime_event_payload(
    attraction_id: str,
    started_at: str = "2026-08-01T09:00:00.000Z",
    cause_category: str = "MECHANICAL",
    **overrides,
) -> dict:
    payload = {
        "attraction_id": attraction_id,
        "started_at": started_at,
        "cause_category": cause_category,
    }
    payload.update(overrides)
    return payload


def diagnose_downtime_payload(
    root_cause_code: str = "RC-0001", failed_component_id: Optional[str] = None
) -> dict:
    payload = {"root_cause_code": root_cause_code}
    if failed_component_id is not None:
        payload["failed_component_id"] = failed_component_id
    return payload


def resolve_downtime_payload(ended_at: str) -> dict:
    return {"ended_at": ended_at}


def void_downtime_payload(void_reason: str = "Logged in error") -> dict:
    return {"void_reason": void_reason}


# --- Part requisitions (PRD §3.5) -------------------------------------------
def create_part_requisition_payload(
    attraction_id: str,
    quantity: int = 1,
    unit_cost_cents: int = 1000,
    needed_by_date: str = "2026-08-10",
    part_number: Optional[str] = None,
    **overrides,
) -> dict:
    payload = {
        "attraction_id": attraction_id,
        "part_number": part_number or DEFAULTS["PART_NUMBER"],
        "quantity": quantity,
        "unit_cost_cents": unit_cost_cents,
        "needed_by_date": needed_by_date,
    }
    payload.update(overrides)
    return payload


def cancel_requisition_payload(cancel_reason: str = "No longer required") -> dict:
    return {"cancel_reason": cancel_reason}


# --- Bulletins and fleet actions (PRD §3.6) ---------------------------------
def create_bulletin_payload(
    bulletin_ref: str,
    manufacturer: str = DEFAULTS["MANUFACTURER"],
    model_code: str = DEFAULTS["MODEL_CODE"],
    severity: str = "MANDATORY",
    issued_date: str = "2026-07-01",
    compliance_deadline_date: str = "2026-10-01",
    **overrides,
) -> dict:
    payload = {
        "bulletin_ref": bulletin_ref,
        "manufacturer": manufacturer,
        "model_code": model_code,
        "severity": severity,
        "issued_date": issued_date,
        "compliance_deadline_date": compliance_deadline_date,
    }
    payload.update(overrides)
    return payload


def defer_bulletin_action_payload(
    deferral_reason: str = "Awaiting factory kit",
    deferred_until_date: str = "2026-09-01",
) -> dict:
    return {
        "deferral_reason": deferral_reason,
        "deferred_until_date": deferred_until_date,
    }


# --- Operator certifications (PRD §3.7) -------------------------------------
def create_operator_certification_payload(
    attraction_id: str,
    operator_user_id: str = "op-1",
    effective_from: str = "2026-08-01T00:00:00.000Z",
    expires_at: str = "2026-12-01T00:00:00.000Z",
    restraint_verification_score: int = 90,
    dispatch_procedure_score: int = 90,
    **overrides,
) -> dict:
    payload = {
        "attraction_id": attraction_id,
        "operator_user_id": operator_user_id,
        "effective_from": effective_from,
        "expires_at": expires_at,
        "restraint_verification_score": restraint_verification_score,
        "dispatch_procedure_score": dispatch_procedure_score,
    }
    payload.update(overrides)
    return payload


def suspend_certification_payload(suspension_reason: str = "Safety finding") -> dict:
    return {"suspension_reason": suspension_reason}


# --- Incident reports (PRD §3.8) --------------------------------------------
def create_incident_payload(
    attraction_id: str,
    occurred_at: str = "2026-08-01T10:00:00.000Z",
    injury_severity: str = "MINOR",
    guest_count_affected: int = 1,
    narrative: str = "Guest reported discomfort on the exit ramp.",
    **overrides,
) -> dict:
    payload = {
        "attraction_id": attraction_id,
        "occurred_at": occurred_at,
        "injury_severity": injury_severity,
        "guest_count_affected": guest_count_affected,
        "narrative": narrative,
    }
    payload.update(overrides)
    return payload


def notify_regulator_payload(regulator_case_ref: str = "REG-CASE-1") -> dict:
    return {"regulator_case_ref": regulator_case_ref}


def clear_incident_payload(regulator_clearance_ref: Optional[str] = None) -> dict:
    if regulator_clearance_ref is None:
        return {}
    return {"regulator_clearance_ref": regulator_clearance_ref}


# --- Shop bays and overhaul work orders (PRD §3.9) --------------------------
def create_shop_bay_payload(
    name: Optional[str] = None, concurrent_slot_capacity: int = 1, **overrides
) -> dict:
    payload = {
        "name": name or DEFAULTS["BAY_NAME"],
        "concurrent_slot_capacity": concurrent_slot_capacity,
    }
    payload.update(overrides)
    return payload


def create_overhaul_work_order_payload(
    attraction_id: str,
    component_id: str,
    shop_bay_id: str,
    expected_shop_bay_version: int,
    window_start_date: str = "2026-11-01",
    window_end_date: str = "2026-11-05",
    parts_subtotal_cents: int = 100000,
    labor_hours: float = 10,
    **overrides,
) -> dict:
    payload = {
        "attraction_id": attraction_id,
        "component_id": component_id,
        "shop_bay_id": shop_bay_id,
        "expected_shop_bay_version": expected_shop_bay_version,
        "window_start_date": window_start_date,
        "window_end_date": window_end_date,
        "parts_subtotal_cents": parts_subtotal_cents,
        "labor_hours": labor_hours,
    }
    payload.update(overrides)
    return payload


def advance_work_order_payload(target_phase: str) -> dict:
    return {"target_phase": target_phase}


# --- Logical clock (PRD §2.4) -----------------------------------------------
def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
