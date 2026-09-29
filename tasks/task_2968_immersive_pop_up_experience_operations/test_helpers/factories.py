"""Payload factories - one per creatable resource, client-supplied fields only.

Money is always a whole number of cents expressed as a JSON number, never a
string and never a decimal.  Instants always carry a full ISO 8601 UTC value
ending in Z; calendar dates are always exactly ten characters.  Every factory
accepts overrides so a test can move one field and leave the rest legal.
"""

from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


def kit_code(suffix: int = 1) -> str:
    """A kit code in the declared shape: uppercase letters, digits, hyphens."""
    return f"KIT-P9B-{suffix:03d}"


# ── Pop-up venue ───────────────────────────────────────────────────────────

def venue_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "city_code": TEST_DEFAULTS["CITY_CODE"],
        "site_name": "Pier 9 Shed",
        "lease_start_date": TEST_DEFAULTS["LEASE_START_DATE"],
        "lease_end_date": TEST_DEFAULTS["LEASE_END_DATE"],
        "base_monthly_rent_cents": TEST_DEFAULTS["BASE_MONTHLY_RENT_CENTS"],
        "buildout_allowance_cents": TEST_DEFAULTS["BUILDOUT_ALLOWANCE_CENTS"],
        "buildout_cap_cents": TEST_DEFAULTS["BUILDOUT_CAP_CENTS"],
        "requested_occupancy_load": TEST_DEFAULTS["REQUESTED_OCCUPANCY_LOAD"],
        "egress_width_cm": TEST_DEFAULTS["EGRESS_WIDTH_CM"],
        "sprinklered": True,
    }
    payload.update(overrides)
    return payload


def permit_submission_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"package_note": "assembly occupancy package"}
    payload.update(overrides)
    return payload


def permit_decision_payload(decision: str = "ISSUED",
                            note: Optional[str] = "occupancy 180 granted",
                            **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if note is not None:
        payload["note"] = note
    payload.update(overrides)
    return payload


def buildout_draw_payload(draw_amount_cents: int = 500000,
                          **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "draw_amount_cents": draw_amount_cents,
        "memo": "scenic fabrication deposit",
    }
    payload.update(overrides)
    return payload


# ── Licence agreement ──────────────────────────────────────────────────────

def agreement_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "licensor_name": "Halcyon Studios",
        "ip_title": "Neon Atrium",
        "licensor_rep_user_id": "rep-1",
        "royalty_rate_bps": TEST_DEFAULTS["ROYALTY_RATE_BPS"],
        "merch_royalty_rate_bps": TEST_DEFAULTS["MERCH_ROYALTY_RATE_BPS"],
        "minimum_guarantee_cents": TEST_DEFAULTS["MINIMUM_GUARANTEE_CENTS"],
        "approval_scopes": ["CREATIVE_EXECUTION"],
        "territory_city_codes": [TEST_DEFAULTS["CITY_CODE"]],
        "term_start_date": TEST_DEFAULTS["TERM_START_DATE"],
        "term_end_date": TEST_DEFAULTS["TERM_END_DATE"],
    }
    payload.update(overrides)
    return payload


# ── Creative submission ────────────────────────────────────────────────────

def submission_payload(agreement_id: str, run_id: str, expected_agreement_version: int,
                       **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "license_agreement_id": agreement_id,
        "run_id": run_id,
        "scope": "CREATIVE_EXECUTION",
        "asset_code": "ATRIUM-SCRIPT-01",
        "title": "Atrium scripted beat sheet",
        "expected_agreement_version": expected_agreement_version,
    }
    payload.update(overrides)
    return payload


def submission_decision_payload(decision: str = "APPROVED",
                                note: Optional[str] = "cleared for build",
                                **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if note is not None:
        payload["note"] = note
    payload.update(overrides)
    return payload


# ── Experience run ─────────────────────────────────────────────────────────

def run_payload(venue_id: str, agreement_id: str, kit_id: str,
                **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "venue_id": venue_id,
        "license_agreement_id": agreement_id,
        "build_kit_id": kit_id,
        "run_name": "Neon Atrium NYC",
        "scheduled_open_date": TEST_DEFAULTS["SCHEDULED_OPEN_DATE"],
        "scheduled_close_date": TEST_DEFAULTS["SCHEDULED_CLOSE_DATE"],
        "base_ticket_price_cents": TEST_DEFAULTS["BASE_TICKET_PRICE_CENTS"],
        "timed_slot_minutes": TEST_DEFAULTS["TIMED_SLOT_MINUTES"],
        "max_group_size": TEST_DEFAULTS["MAX_GROUP_SIZE"],
    }
    payload.update(overrides)
    return payload


def extension_payload(requested_extension_days: int = 14,
                      **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "requested_extension_days": requested_extension_days,
        "memo": "demand held through the run",
    }
    payload.update(overrides)
    return payload


def closure_decision_payload(decision: str = "START_CLOSING",
                             **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision, "memo": "strike complete"}
    payload.update(overrides)
    return payload


def lift_suspension_payload(clearing_inspection_id: str,
                            **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "clearing_inspection_id": clearing_inspection_id,
        "note": "corridor cleared and re-measured",
    }
    payload.update(overrides)
    return payload


# ── Themed room ────────────────────────────────────────────────────────────

def room_payload(run_id: str, room_sequence: int = 1,
                 **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "run_id": run_id,
        "room_sequence": room_sequence,
        "name": "Vestibule",
        "room_occupancy_cap": 40,
        "target_dwell_minutes": 15,
        "min_dwell_minutes": 5,
        "sensory_intensity_level": 2,
        "has_quiet_bypass": True,
        "wheelchair_accessible": True,
    }
    payload.update(overrides)
    return payload


# ── Timed-entry slot ───────────────────────────────────────────────────────

def slot_payload(run_id: str,
                 slot_start_utc: str = "2026-09-05T14:00:00Z",
                 slot_end_utc: str = "2026-09-05T14:45:00Z",
                 base_capacity: int = 20,
                 **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "run_id": run_id,
        "slot_start_utc": slot_start_utc,
        "slot_end_utc": slot_end_utc,
        "pricing_tier": "STANDARD",
        "base_capacity": base_capacity,
        "wheelchair_positions": 2,
    }
    payload.update(overrides)
    return payload


def slot_status_decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def price_quote_params(order_type: str = "SINGLE", loyalty_tier: str = "VISITOR",
                       party_size: int = 2, **overrides: Any) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "order_type": order_type,
        "loyalty_tier": loyalty_tier,
        "party_size": party_size,
    }
    params.update(overrides)
    return params


# ── Guest account ──────────────────────────────────────────────────────────

def guest_payload(email: str = "mira@example.com",
                  display_name: str = "Mira Adeyemi",
                  **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"email": email, "display_name": display_name}
    payload.update(overrides)
    return payload


# ── Ticket order ───────────────────────────────────────────────────────────

def order_payload(slot_id: str, guest_account_id: str, party_size: int = 2,
                  **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "slot_id": slot_id,
        "guest_account_id": guest_account_id,
        "order_type": "SINGLE",
        "party_size": party_size,
    }
    payload.update(overrides)
    return payload


def attendance_payload(decision: str = "CHECK_IN", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def cancel_payload(reason: str = "guest rebooked", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


# ── Staff member ───────────────────────────────────────────────────────────

def staff_member_payload(run_id: str, staff_role: str = "PERFORMER",
                         certifications: Optional[List[str]] = None,
                         **overrides: Any) -> Dict[str, Any]:
    from .constants import REQUIRED_CERTIFICATIONS

    payload: Dict[str, Any] = {
        "run_id": run_id,
        "full_name": "Ines Okafor",
        "staff_role": staff_role,
        "certifications": list(
            REQUIRED_CERTIFICATIONS[staff_role] if certifications is None
            else certifications
        ),
    }
    payload.update(overrides)
    return payload


def training_record_payload(training_score: int = 90,
                            completed_rehearsal_count: int = 4,
                            **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "training_score": training_score,
        "completed_rehearsal_count": completed_rehearsal_count,
    }
    payload.update(overrides)
    return payload


def staff_status_decision_payload(decision: str = "CLEAR",
                                  **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


# ── Staff shift ────────────────────────────────────────────────────────────

def shift_payload(staff_member_id: str,
                  shift_start_utc: str = "2026-09-05T10:00:00Z",
                  shift_end_utc: str = "2026-09-05T14:00:00Z",
                  **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "staff_member_id": staff_member_id,
        "shift_start_utc": shift_start_utc,
        "shift_end_utc": shift_end_utc,
        "station": "FLOOR",
    }
    payload.update(overrides)
    return payload


def shift_status_decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


# ── Safety inspection ──────────────────────────────────────────────────────

def inspection_payload(run_id: str, inspection_type: str = "EGRESS",
                       scheduled_for_utc: str = "2026-08-05T09:00:00Z",
                       **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "run_id": run_id,
        "inspection_type": inspection_type,
        "scheduled_for_utc": scheduled_for_utc,
    }
    payload.update(overrides)
    return payload


def inspection_finalize_payload(measured_egress_width_cm: float = 400,
                                findings_count: int = 0,
                                severity: str = "NONE",
                                findings_note: Optional[str] = None,
                                **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "measured_egress_width_cm": measured_egress_width_cm,
        "findings_count": findings_count,
        "severity": severity,
    }
    if findings_note is not None:
        payload["findings_note"] = findings_note
    payload.update(overrides)
    return payload


def inspection_void_payload(note: str = "inspector unavailable; reinspection rebooked",
                            **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"note": note}
    payload.update(overrides)
    return payload


# ── Build kit ──────────────────────────────────────────────────────────────

def kit_payload(code: Optional[str] = None, module_count: int = 20,
                **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "kit_code": code or kit_code(1),
        "module_count": module_count,
        "initial_condition_score": 100.00,
        "localization_language": "en-US",
    }
    payload.update(overrides)
    return payload


def localize_payload(localization_language: str = "fr-FR",
                     **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"localization_language": localization_language}
    payload.update(overrides)
    return payload


# ── Royalty statement ──────────────────────────────────────────────────────

def statement_payload(run_id: str, expected_run_version: int,
                      period_start_date: str = "2026-08-01",
                      period_end_date: str = "2026-08-31",
                      **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "run_id": run_id,
        "period_start_date": period_start_date,
        "period_end_date": period_end_date,
        "expected_run_version": expected_run_version,
    }
    payload.update(overrides)
    return payload
