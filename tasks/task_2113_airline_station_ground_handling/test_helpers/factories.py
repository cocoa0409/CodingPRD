"""Payload factories — one per record type, input fields only."""
from .constants import TEST_DEFAULTS


def create_station_payload(**overrides) -> dict:
    payload = {
        "iata_code": "ZRH",
        "name": "Zurich",
        "handler_code": "SWP",
        "season_code": "SUMMER",
    }
    payload.update(overrides)
    return payload


def station_lifecycle_payload(action, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def season_rollover_payload(to_season_code, **overrides) -> dict:
    payload = {
        "to_season_code": to_season_code,
        "season_start_date": "2026-10-25T00:00:00Z",
        "season_end_date": "2027-03-27T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_subcontractor_payload(station_id, **overrides) -> dict:
    payload = {"station_id": station_id, "legal_name": "Alpine Ramp AG"}
    payload.update(overrides)
    return payload


def oversight_decision_payload(decision, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_flight_bank_payload(station_id, **overrides) -> dict:
    payload = {
        "station_id": station_id,
        "bank_code": "AM1",
        "season_code": "SUMMER",
        "window_start": TEST_DEFAULTS["BANK_WINDOW_START"],
        "window_end": TEST_DEFAULTS["BANK_WINDOW_END"],
        "planned_headcount": 1,
    }
    payload.update(overrides)
    return payload


def bank_lifecycle_payload(action) -> dict:
    return {"action": action}


def staffing_transition_payload(action, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def create_turn_payload(station_id, flight_bank_id, **overrides) -> dict:
    payload = {
        "station_id": station_id,
        "flight_bank_id": flight_bank_id,
        "flight_number": "LX318",
        "turn_type": "TOWING_ONLY",
        "scheduled_in": "2026-04-10T06:00:00Z",
        "scheduled_out": "2026-04-10T06:20:00Z",
    }
    payload.update(overrides)
    return payload


def turn_lifecycle_payload(action, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def create_agent_payload(station_id, **overrides) -> dict:
    payload = {
        "station_id": station_id,
        "employee_code": "E001",
        "full_name": "Ana Ruiz",
    }
    payload.update(overrides)
    return payload


def create_certification_payload(agent_id, station_id, **overrides) -> dict:
    payload = {
        "agent_id": agent_id,
        "station_id": station_id,
        "cert_type": "RAMP_SAFETY",
        "issued_at": TEST_DEFAULTS["CERT_ISSUED_AT"],
        "expires_at": TEST_DEFAULTS["CERT_EXPIRES_AT"],
    }
    payload.update(overrides)
    return payload


def revoke_certification_payload(reason="TRAINING_AUDIT_FAILURE") -> dict:
    return {"reason": reason}


def create_gse_unit_payload(station_id, **overrides) -> dict:
    payload = {
        "station_id": station_id,
        "asset_tag": "TUG-01",
        "gse_type": "PUSHBACK_TUG",
    }
    payload.update(overrides)
    return payload


def gse_service_event_payload(event_type, **overrides) -> dict:
    payload = {"event_type": event_type}
    payload.update(overrides)
    return payload


def create_agent_resource_payload(turn_id, agent_id, expected_turn_version,
                                  **overrides) -> dict:
    payload = {
        "turn_id": turn_id,
        "resource_kind": "AGENT",
        "agent_id": agent_id,
        "role_on_turn": "RAMP",
        "window_start": "2026-04-10T05:50:00Z",
        "window_end": "2026-04-10T06:30:00Z",
        "expected_turn_version": expected_turn_version,
    }
    payload.update(overrides)
    return payload


def create_gse_resource_payload(turn_id, expected_turn_version, gse_unit_id=None,
                                gse_type=None, **overrides) -> dict:
    payload = {
        "turn_id": turn_id,
        "resource_kind": "GSE",
        "window_start": "2026-04-10T05:55:00Z",
        "window_end": "2026-04-10T06:25:00Z",
        "expected_turn_version": expected_turn_version,
    }
    if gse_unit_id is not None:
        payload["gse_unit_id"] = gse_unit_id
    if gse_type is not None:
        payload["gse_type"] = gse_type
    payload.update(overrides)
    return payload


def release_resource_payload(**overrides) -> dict:
    payload = {"reason": "REALLOCATED"}
    payload.update(overrides)
    return payload


def create_incident_payload(station_id, **overrides) -> dict:
    payload = {
        "station_id": station_id,
        "incident_type": "NEAR_MISS",
        "severity": "MINOR",
        "occurred_at": "2026-03-30T09:00:00Z",
    }
    payload.update(overrides)
    return payload


def incident_transition_payload(action, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def create_billing_period_payload(station_id, **overrides) -> dict:
    payload = {
        "station_id": station_id,
        "period_code": "2026-04",
        "window_start": TEST_DEFAULTS["PERIOD_WINDOW_START"],
        "window_end": TEST_DEFAULTS["PERIOD_WINDOW_END"],
    }
    payload.update(overrides)
    return payload


def billing_period_transition_payload(action, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def create_billing_line_payload(billing_period_id, turn_id,
                                expected_billing_period_version, **overrides) -> dict:
    payload = {
        "billing_period_id": billing_period_id,
        "turn_id": turn_id,
        "expected_billing_period_version": expected_billing_period_version,
    }
    payload.update(overrides)
    return payload


def void_billing_line_payload(reason="ACCRUED_TO_WRONG_PERIOD") -> dict:
    return {"reason": reason}


def set_clock_payload(current_utc) -> dict:
    return {"current_utc": current_utc}
