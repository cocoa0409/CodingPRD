"""Request payload builders.

Unknown fields are rejected by the shape rung, so every builder emits exactly
the required inputs plus whatever optional inputs the caller asked for -- never
a speculative extra key. Money is always a JSON integer, never a string, and
every instant is a full ISO-8601 instant rather than a bare date.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import CEILINGS_BELOW_POSTED

_insurer_code_counter = itertools.count(1)
_claim_counter = itertools.count(1)
_vin_counter = itertools.count(1)
_operation_counter = itertools.count(1)
_part_counter = itertools.count(1)


def next_insurer_code() -> str:
    return f"PRG-{next(_insurer_code_counter):04d}"


def next_claim_number() -> str:
    return f"CLM-{next(_claim_counter):05d}"


def next_vin() -> str:
    """A 17-character vehicle identification number."""
    return f"1HGCV1F30LA{next(_vin_counter):06d}"


def next_operation_code() -> str:
    return f"OP-{next(_operation_counter):04d}"


def next_part_number() -> str:
    return f"PN-{next(_part_counter):05d}"


def _payload(required: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Merge caller overrides over the required block, dropping nothing."""
    body = dict(required)
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# Standing registries
# ---------------------------------------------------------------------------
def customer_payload(**overrides: Any) -> Dict[str, Any]:
    return _payload(
        {
            "full_name": "Dana Whitfield",
            "phone": "+1-555-0100",
            "email": "dana.whitfield@example.com",
        },
        overrides,
    )


def insurer_payload(
    rate_ceiling_cents: Optional[Dict[str, int]] = None, **overrides: Any
) -> Dict[str, Any]:
    return _payload(
        {
            "insurer_code": next_insurer_code(),
            "name": "Northbridge Mutual",
            "rate_ceiling_cents": dict(
                rate_ceiling_cents
                if rate_ceiling_cents is not None
                else CEILINGS_BELOW_POSTED
            ),
        },
        overrides,
    )


def parts_vendor_payload(
    part_types_offered: Optional[List[str]] = None, **overrides: Any
) -> Dict[str, Any]:
    return _payload(
        {
            "name": "Crown Auto Parts",
            "vendor_type": "OEM_DEALER",
            "part_types_offered": list(
                part_types_offered if part_types_offered is not None else ["OEM"]
            ),
        },
        overrides,
    )


def stall_payload(**overrides: Any) -> Dict[str, Any]:
    return _payload({"name": "Body 1", "stall_type": "BODY"}, overrides)


def calibration_bay_payload(
    supported_types: Optional[List[str]] = None, **overrides: Any
) -> Dict[str, Any]:
    return _payload(
        {
            "name": "Calibration Bay 1",
            "supported_types": list(
                supported_types if supported_types is not None else ["STATIC"]
            ),
        },
        overrides,
    )


def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}


# ---------------------------------------------------------------------------
# Intake and teardown
# ---------------------------------------------------------------------------
def repair_order_payload(
    customer_id: str, insurer_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _payload(
        {
            "customer_id": customer_id,
            "insurer_id": insurer_id,
            "claim_number": next_claim_number(),
            "vehicle_vin": next_vin(),
            "vehicle_model_year": 2019,
            "vehicle_make_model": "Honda Accord EX",
            "initial_authorized_cents": 400000,
        },
        overrides,
    )


def teardown_finding_payload(**overrides: Any) -> Dict[str, Any]:
    return _payload({"panel_code": "L_FRONT_DOOR", "severity": "MODERATE"}, overrides)


# ---------------------------------------------------------------------------
# The estimate
# ---------------------------------------------------------------------------
def estimate_line_payload(**overrides: Any) -> Dict[str, Any]:
    return _payload(
        {
            "operation_code": next_operation_code(),
            "labor_type": "BODY",
            "guide_hours": 4.5,
        },
        overrides,
    )


def total_loss_payload(**overrides: Any) -> Dict[str, Any]:
    return _payload({"total_loss_note": "Frame rail beyond economical repair."}, overrides)


# ---------------------------------------------------------------------------
# Supplements and consent
# ---------------------------------------------------------------------------
def supplement_payload(expected_repair_order_version: int, **overrides: Any) -> Dict[str, Any]:
    return _payload(
        {
            "reason_code": "HIDDEN_DAMAGE",
            "requested_amount_cents": 50000,
            "expected_repair_order_version": expected_repair_order_version,
        },
        overrides,
    )


def supplement_decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    return _payload({"decision": decision}, overrides)


def supplement_resubmit_payload(requested_amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    return _payload({"requested_amount_cents": requested_amount_cents}, overrides)


def consent_decision_payload(
    decision: str, alternate_parts_ok: bool, expected_repair_order_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _payload(
        {
            "decision": decision,
            "alternate_parts_ok": alternate_parts_ok,
            "expected_repair_order_version": expected_repair_order_version,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Parts
# ---------------------------------------------------------------------------
def parts_line_payload(**overrides: Any) -> Dict[str, Any]:
    return _payload(
        {
            "part_number": next_part_number(),
            "part_description": "Front bumper cover",
            "part_type": "OEM",
            "list_price_cents": 30000,
            "qty": 1,
        },
        overrides,
    )


def quote_payload(vendor_id: str, quoted_unit_price_cents: int) -> Dict[str, Any]:
    return {
        "vendor_id": vendor_id,
        "quoted_unit_price_cents": quoted_unit_price_cents,
    }


def counter_offer_payload(counter_unit_price_cents: int) -> Dict[str, Any]:
    return {"counter_unit_price_cents": counter_unit_price_cents}


def order_payload(promised_eta: str) -> Dict[str, Any]:
    return {"promised_eta": promised_eta}


def receive_payload(received_qty: int, condition: str = "CORRECT") -> Dict[str, Any]:
    return {"received_qty": received_qty, "condition": condition}


def return_payload(return_qty: int, return_reason: str) -> Dict[str, Any]:
    return {"return_qty": return_qty, "return_reason": return_reason}


# ---------------------------------------------------------------------------
# Procedure research and calibration
# ---------------------------------------------------------------------------
def procedure_record_payload(**overrides: Any) -> Dict[str, Any]:
    return _payload(
        {
            "procedure_code": "SEAM-SEAL",
            "source": "ALLDATA",
            "operation_scope": "STRUCTURAL",
        },
        overrides,
    )


def adherence_payload(adherence_documented: bool = True, **overrides: Any) -> Dict[str, Any]:
    return _payload({"adherence_documented": adherence_documented}, overrides)


def calibration_schedule_payload(
    bay_id: str, window_start: str, window_end: str
) -> Dict[str, Any]:
    return {
        "bay_id": bay_id,
        "window_start": window_start,
        "window_end": window_end,
    }


def calibration_result_payload(
    result: str, post_scan_dtc_count: int, **overrides: Any
) -> Dict[str, Any]:
    return _payload(
        {"result": result, "post_scan_dtc_count": post_scan_dtc_count}, overrides
    )


# ---------------------------------------------------------------------------
# Bookings, stages and quality control
# ---------------------------------------------------------------------------
def stage_assignment_payload(
    stall_id: str, stage: str, window_start: str, window_end: str
) -> Dict[str, Any]:
    return {
        "stall_id": stall_id,
        "stage": stage,
        "window_start": window_start,
        "window_end": window_end,
    }


def stage_advance_payload(to_stage: str) -> Dict[str, Any]:
    return {"to_stage": to_stage}


def qc_inspection_payload(
    checklist_passed: bool, post_scan_dtc_count: int, **overrides: Any
) -> Dict[str, Any]:
    return _payload(
        {
            "checklist_passed": checklist_passed,
            "post_scan_dtc_count": post_scan_dtc_count,
        },
        overrides,
    )
