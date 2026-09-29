"""Request payload builders.

Every builder returns a plain dict with valid defaults that a test may override
by keyword. Money is always an integer count of cents, never a string; lengths,
areas and hour figures are JSON numbers; instants are full ISO 8601 UTC
instants, never date-only strings, except `confirmed_date` which the PRD defines
as a calendar date written YYYY-MM-DD.
"""
import itertools
from typing import Any, Dict, List, Optional

from .types import (
    Application,
    CableCategory,
    IdentifierScheme,
    JacketRating,
    ManufacturerProgram,
    Milestone,
    OccupancyStatus,
    PathwayType,
    TestStandard,
    TicketType,
    Trade,
    WarrantyDecision,
)

_counter = itertools.count(1)


def _next() -> int:
    return next(_counter)


def _merge(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides, dropping any key whose override value is the sentinel."""
    for key, value in overrides.items():
        if value is OMIT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


class _Omit:
    """Sentinel: passing OMIT for a field removes it from the payload."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "OMIT"


OMIT = _Omit()


# ── Site codes and room / rack codes ───────────────────────────────────────
_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def unique_site_code() -> str:
    """A site code matching ^[A-Z]{2,4}[0-9]{1,2}$."""
    n = _next()
    return f"{_ALPHABET[n % 26]}{_ALPHABET[(n // 26) % 26]}{n % 100:02d}"


def unique_room_code() -> str:
    """A room code matching ^[A-Z]{2}[0-9]{2}$."""
    n = _next()
    return f"{_ALPHABET[n % 26]}{_ALPHABET[(n // 26) % 26]}{n % 100:02d}"


def unique_segment_code() -> str:
    return f"SEG-{_next():04d}"


def class_1_identifier(room_code: str = "TR01", rack_letter: str = "A", port: int = 14) -> str:
    """An identifier matching ^[A-Z]{2}[0-9]{2}-[A-Z][0-9]{2}$."""
    return f"{room_code}-{rack_letter}{port:02d}"


def class_2_identifier(
    floor_space: str = "03B",
    room_code: str = "TR01",
    rack_letter: str = "A",
    port: int = 14,
) -> str:
    """An identifier matching ^[0-9]{2}[A-Z]-[A-Z]{2}[0-9]{2}-[A-Z][0-9]{2}$."""
    return f"{floor_space}-{room_code}-{rack_letter}{port:02d}"


# ── Projects ───────────────────────────────────────────────────────────────
def project_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": f"Cabling Job {_next()}",
        "site_code": unique_site_code(),
        "plenum_ceiling": False,
        "identifier_scheme": IdentifierScheme.TIA_606_CLASS_1,
    }
    return _merge(payload, overrides)


def occupancy_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"occupancy_status": OccupancyStatus.OCCUPIED}
    return _merge(payload, overrides)


# ── Telecom rooms ──────────────────────────────────────────────────────────
def telecom_room_payload(project_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "project_id": project_id,
        "room_code": unique_room_code(),
        "floor": 3,
        "branch_circuit_amps": 20,
        "ups_capacity_va": 3000,
    }
    return _merge(payload, overrides)


def grounding_payload(**overrides: Any) -> Dict[str, Any]:
    """A compliant measurement: busbar present, #6 AWG, well under 5000 milliohms."""
    payload: Dict[str, Any] = {
        "tgb_installed": True,
        "bonding_conductor_awg": 6,
        "ground_resistance_milliohms": 1200,
    }
    return _merge(payload, overrides)


# ── Racks and elevation placements ─────────────────────────────────────────
def rack_payload(telecom_room_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "telecom_room_id": telecom_room_id,
        "rack_code": "A",
        "total_ru": 42,
    }
    return _merge(payload, overrides)


def rack_unit_assignment_payload(
    rack_id: str, expected_rack_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "rack_id": rack_id,
        "equipment_label": f"Switch {_next()}",
        "start_ru": 1,
        "end_ru": 4,
        "power_va": 1200,
        "expected_rack_version": expected_rack_version,
    }
    return _merge(payload, overrides)


def release_payload(expected_rack_version: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "released_reason": "Equipment returned to the warehouse",
        "expected_rack_version": expected_rack_version,
    }
    return _merge(payload, overrides)


# ── Pathway segments ───────────────────────────────────────────────────────
def pathway_segment_payload(project_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "project_id": project_id,
        "segment_code": unique_segment_code(),
        "pathway_type": PathwayType.CABLE_TRAY,
        "usable_area_sq_mm": 20000.0,
        "length_m": 30.0,
    }
    return _merge(payload, overrides)


def condemn_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "condemned_reason": "Tray crushed by the mechanical trade",
    }
    return _merge(payload, overrides)


def reparent_payload(
    upstream_segment_id: Optional[str], expected_segment_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "upstream_segment_id": upstream_segment_id,
        "expected_segment_version": expected_segment_version,
    }
    return _merge(payload, overrides)


# ── Cable catalogue ────────────────────────────────────────────────────────
def cable_type_payload(**overrides: Any) -> Dict[str, Any]:
    """A plenum-rated CAT6A: 7.9 mm outside diameter, cross section 49.02 sq mm."""
    payload: Dict[str, Any] = {
        "category": CableCategory.CAT6A,
        "jacket_rating": JacketRating.CMP,
        "outer_diameter_mm": 7.9,
        "max_channel_length_m": 100.0,
        "shielded": False,
        "cost_per_meter_cents": 150,
        "applications": [
            Application.DATA_HORIZONTAL,
            Application.WAP,
            Application.CAMERA,
        ],
    }
    return _merge(payload, overrides)


# ── Links ──────────────────────────────────────────────────────────────────
def link_payload(
    project_id: str, telecom_room_id: str, cable_type_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "project_id": project_id,
        "telecom_room_id": telecom_room_id,
        "cable_type_id": cable_type_id,
        "identifier": class_1_identifier(),
        "application": Application.DATA_HORIZONTAL,
        "horizontal_length_m": 60.0,
        "consolidation_point_stub_m": 0.0,
        "patch_cord_allowance_m": 5.0,
    }
    return _merge(payload, overrides)


def label_payload(applied_identifier: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"applied_identifier": applied_identifier}
    return _merge(payload, overrides)


def record_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"drawing_sheet_ref": f"E-10{_next() % 10}"}
    return _merge(payload, overrides)


# ── Link routings ──────────────────────────────────────────────────────────
def link_route_payload(
    link_id: str,
    pathway_segment_id: str,
    expected_segment_version: int,
    sequence_index: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "link_id": link_id,
        "pathway_segment_id": pathway_segment_id,
        "sequence_index": sequence_index,
        "expected_segment_version": expected_segment_version,
    }
    return _merge(payload, overrides)


def withdraw_payload(expected_segment_version: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"expected_segment_version": expected_segment_version}
    return _merge(payload, overrides)


# ── Field test results ─────────────────────────────────────────────────────
def test_result_payload(link_id: str, **overrides: Any) -> Dict[str, Any]:
    """A clean permanent-link PASS: both margins well outside the accuracy band."""
    payload: Dict[str, Any] = {
        "link_id": link_id,
        "test_standard": TestStandard.PERMANENT_LINK,
        "tester_model": "Fluke DSX-8000",
        "insertion_loss_db": 5.0,
        "next_margin_db": 3.2,
        "return_loss_margin_db": 2.8,
        "length_measured_m": 60.0,
    }
    return _merge(payload, overrides)


# ── Warranty registrations ─────────────────────────────────────────────────
def warranty_registration_payload(project_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "project_id": project_id,
        "manufacturer_program": ManufacturerProgram.STANDARD_15Y,
    }
    return _merge(payload, overrides)


def warranty_submit_payload(expected_project_version: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"expected_project_version": expected_project_version}
    return _merge(payload, overrides)


def warranty_register_decision_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "decision": WarrantyDecision.REGISTER,
        "registration_number": f"MW-{_next():06d}",
    }
    return _merge(payload, overrides)


def warranty_reject_decision_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "decision": WarrantyDecision.REJECT,
        "rejection_reason": "Certification evidence incomplete",
    }
    return _merge(payload, overrides)


# ── Moves-adds-changes tickets ─────────────────────────────────────────────
def mac_ticket_payload(
    project_id: str, link_id: str, telecom_room_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "project_id": project_id,
        "link_id": link_id,
        "telecom_room_id": telecom_room_id,
        "ticket_type": TicketType.MOVE,
        "requested_window_start": "2026-08-10T09:00:00Z",
        "requested_window_end": "2026-08-10T12:00:00Z",
        "labor_hours_estimate": 2.0,
        "expedite_requested": False,
    }
    return _merge(payload, overrides)


def schedule_payload(
    scheduled_window_start: str = "2026-08-10T09:00:00Z",
    scheduled_window_end: str = "2026-08-10T12:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "scheduled_window_start": scheduled_window_start,
        "scheduled_window_end": scheduled_window_end,
    }
    return _merge(payload, overrides)


def complete_payload(actual_labor_hours: float = 2.0, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"actual_labor_hours": actual_labor_hours}
    return _merge(payload, overrides)


# ── Trade coordinations ────────────────────────────────────────────────────
def trade_coordination_payload(project_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "project_id": project_id,
        "trade": Trade.CEILING,
        "milestone": Milestone.PATHWAY_ROUGH_IN,
    }
    return _merge(payload, overrides)


def confirm_payload(confirmed_date: str = "2026-08-05", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"confirmed_date": confirmed_date}
    return _merge(payload, overrides)


def block_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"block_reason": "Mechanical ductwork is in the way"}
    return _merge(payload, overrides)


def applications_all() -> List[str]:
    return [
        Application.DATA_HORIZONTAL,
        Application.BACKBONE,
        Application.WAP,
        Application.CAMERA,
        Application.ACCESS_CONTROL,
        Application.AV_DISTRIBUTION,
    ]
