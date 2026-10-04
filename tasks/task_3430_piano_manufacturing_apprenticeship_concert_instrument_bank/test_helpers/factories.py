"""Payload factories — one per request body, input fields only.

Convention: optional fields left as None are omitted from the payload (the
server applies its own default). Pass an explicit value (including via
**overrides) to send a key; overrides may also add extra keys for
strict-validation tests.
"""

from .constants import MOISTURE_READY_PCT


def create_wood_batch_payload(species="MAPLE", moisture_content_pct=12.0, **overrides):
    payload = {"species": species, "moisture_content_pct": moisture_content_pct}
    payload.update(overrides)
    return payload


def moisture_reading_payload(moisture_content_pct=MOISTURE_READY_PCT, **overrides):
    payload = {"moisture_content_pct": moisture_content_pct}
    payload.update(overrides)
    return payload


def create_build_order_payload(model="MODEL_B", wood_batch_id=None, commissioned_note=None,
                               **overrides):
    payload = {"model": model}
    if wood_batch_id is not None:
        payload["wood_batch_id"] = wood_batch_id
    if commissioned_note is not None:
        payload["commissioned_note"] = commissioned_note
    payload.update(overrides)
    return payload


def advance_build_payload(to_stage, hours_applied, expected_build_order_version,
                          supervising_craftsman_id=None, wood_batch_id=None, **overrides):
    payload = {
        "to_stage": to_stage,
        "hours_applied": hours_applied,
        "expected_build_order_version": expected_build_order_version,
    }
    if supervising_craftsman_id is not None:
        payload["supervising_craftsman_id"] = supervising_craftsman_id
    if wood_batch_id is not None:
        payload["wood_batch_id"] = wood_batch_id
    payload.update(overrides)
    return payload


def create_craftsman_payload(name="Test Craftsman", specialty="RIM_BENDING", **overrides):
    payload = {"name": name, "specialty": specialty}
    payload.update(overrides)
    return payload


def create_apprentice_payload(name="Test Apprentice", **overrides):
    payload = {"name": name}
    payload.update(overrides)
    return payload


def create_endorsement_payload(apprentice_id=None, operation_type="RIM_BENDING", **overrides):
    payload = {"operation_type": operation_type}
    if apprentice_id is not None:
        payload["apprentice_id"] = apprentice_id
    payload.update(overrides)
    return payload


def log_hours_payload(hours=10, supervising_craftsman_id=None, **overrides):
    """supervising_craftsman_id defaults to null (endorsed unsupervised work);
    pass a craftsman id for a supervised entry."""
    payload = {"hours": hours, "supervising_craftsman_id": supervising_craftsman_id}
    payload.update(overrides)
    return payload


def assess_payload(outcome="ENDORSE", **overrides):
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def review_endorsement_payload(action="REVOKE", **overrides):
    payload = {"action": action}
    payload.update(overrides)
    return payload


def create_artist_payload(name="Test Artist", tier="STANDARD", performance_quota=2, **overrides):
    payload = {"name": name, "tier": tier, "performance_quota": performance_quota}
    payload.update(overrides)
    return payload


def performance_payload(venue="Test Hall", performed_at="2026-09-01T00:00:00Z", **overrides):
    payload = {"venue": venue, "performed_at": performed_at}
    payload.update(overrides)
    return payload


def create_loan_payload(desired_model="MODEL_B", tour_start="2027-01-10T00:00:00Z",
                        tour_end="2027-01-24T00:00:00Z", **overrides):
    payload = {
        "desired_model": desired_model,
        "tour_start": tour_start,
        "tour_end": tour_end,
    }
    payload.update(overrides)
    return payload


def confirm_loan_payload(technician_id=None, instrument_id=None, **overrides):
    payload = {}
    if technician_id is not None:
        payload["technician_id"] = technician_id
    if instrument_id is not None:
        payload["instrument_id"] = instrument_id
    payload.update(overrides)
    return payload


def return_loan_payload(condition_grade_observed="A", **overrides):
    payload = {"condition_grade_observed": condition_grade_observed}
    payload.update(overrides)
    return payload


def create_restoration_payload(instrument_id=None, lead_craftsman_id=None,
                               diagnosis="Restoration work", authentic_parts_value_cents=0,
                               total_parts_value_cents=0, waiver_accepted=None, **overrides):
    payload = {
        "diagnosis": diagnosis,
        "authentic_parts_value_cents": authentic_parts_value_cents,
        "total_parts_value_cents": total_parts_value_cents,
    }
    if instrument_id is not None:
        payload["instrument_id"] = instrument_id
    if lead_craftsman_id is not None:
        payload["lead_craftsman_id"] = lead_craftsman_id
    if waiver_accepted is not None:
        payload["waiver_accepted"] = waiver_accepted
    payload.update(overrides)
    return payload


def advance_restoration_payload(to_stage="DISASSEMBLED", authenticity_concern=None, **overrides):
    payload = {"to_stage": to_stage}
    if authenticity_concern is not None:
        payload["authenticity_concern"] = authenticity_concern
    payload.update(overrides)
    return payload


def resolve_authenticity_payload(authentic_parts_value_cents=0, total_parts_value_cents=0,
                                 waiver_accepted=None, **overrides):
    payload = {
        "authentic_parts_value_cents": authentic_parts_value_cents,
        "total_parts_value_cents": total_parts_value_cents,
    }
    if waiver_accepted is not None:
        payload["waiver_accepted"] = waiver_accepted
    payload.update(overrides)
    return payload


def complete_restoration_payload(final_authentic_value_cents=0,
                                 final_total_parts_value_cents=0, **overrides):
    payload = {
        "final_authentic_value_cents": final_authentic_value_cents,
        "final_total_parts_value_cents": final_total_parts_value_cents,
    }
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601, **overrides):
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
