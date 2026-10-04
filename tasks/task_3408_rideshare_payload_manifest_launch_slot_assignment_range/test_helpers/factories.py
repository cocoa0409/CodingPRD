"""Payload factories — one per creatable entity, input fields only (PRD §3)."""
from .constants import (
    CONTRACT_WINDOW_CLOSE,
    CONTRACT_WINDOW_OPEN,
    LICENSE_VALID_UNTIL,
    MISSION_WINDOW_CLOSE,
    MISSION_WINDOW_OPEN,
)


def customer_payload(**overrides) -> dict:
    """PRD §3.1: org_name + contact_email required; default_rebookings optional."""
    defaults = {
        "org_name": "Acme SmallSat Ventures",
        "contact_email": "ops@acme-ssv.example",
        "default_rebookings": 1,
    }
    defaults.update(overrides)
    return defaults


def mission_payload(**overrides) -> dict:
    """PRD §3.1: mission create inputs."""
    defaults = {
        "mission_name": "Transporter-X1",
        "target_orbit": "SSO",
        "window_open_utc": MISSION_WINDOW_OPEN,
        "window_close_utc": MISSION_WINDOW_CLOSE,
        "mass_capacity_kg": 300,
        "volume_capacity_m3": 6.0,
    }
    defaults.update(overrides)
    return defaults


def dispenser_port_payload(**overrides) -> dict:
    """PRD §3.1: dispenser port inputs."""
    defaults = {
        "port_code": "DSP-A",
        "stack_position": 4,
        "max_mass_kg": 150,
        "supported_interface_classes": ["RING_15", "RING_24"],
    }
    defaults.update(overrides)
    return defaults


def payload_entry(**overrides) -> dict:
    """PRD §3.2: one entry of the contract create payloads array."""
    defaults = {
        "payload_name": "PL1",
        "mass_kg": 100,
        "volume_m3": 2.0,
        "interface_class": "RING_15",
        "required_orbit": "SSO",
    }
    defaults.update(overrides)
    return defaults


def contract_payload(customer_id, payloads, **overrides) -> dict:
    """PRD §3.2: contract create inputs (payloads is the atomic array)."""
    defaults = {
        "customer_id": customer_id,
        "pricing_mode": "MARGINAL",
        "window_open_utc": CONTRACT_WINDOW_OPEN,
        "window_close_utc": CONTRACT_WINDOW_CLOSE,
        "payloads": payloads,
    }
    defaults.update(overrides)
    return defaults


def assignment_payload(mission_id, payload_id, dispenser_port_id, expected_mission_version) -> dict:
    """PRD §3.3 + §2.8: assignment create inputs including the OCC guard."""
    return {
        "mission_id": mission_id,
        "payload_id": payload_id,
        "dispenser_port_id": dispenser_port_id,
        "expected_mission_version": expected_mission_version,
    }


def verification_payload(**overrides) -> dict:
    """PRD §3.3: interface verification inputs."""
    defaults = {"check_type": "MECHANICAL", "outcome": "PASSED"}
    defaults.update(overrides)
    return defaults


def safety_review_payload(**overrides) -> dict:
    """PRD §3.3: safety review inputs."""
    defaults = {"decision": "APPROVE", "rationale": "interfaces nominal"}
    defaults.update(overrides)
    return defaults


def customer_license_payload(customer_id, **overrides) -> dict:
    """PRD §3.4: PAYLOAD_OPERATOR filing for a CUSTOMER subject."""
    defaults = {
        "subject_type": "CUSTOMER",
        "kind": "PAYLOAD_OPERATOR",
        "customer_id": customer_id,
        "valid_until": LICENSE_VALID_UNTIL,
        "debris_score": 80,
        "spectrum_score": 90,
        "operator_history_score": 80,
    }
    defaults.update(overrides)
    return defaults


def mission_license_payload(mission_id, **overrides) -> dict:
    """PRD §3.4: LAUNCH_AUTHORIZATION filing for a MISSION subject."""
    defaults = {
        "subject_type": "MISSION",
        "kind": "LAUNCH_AUTHORIZATION",
        "mission_id": mission_id,
        "valid_until": "2026-12-31T00:00:00Z",
        "debris_score": 90,
        "spectrum_score": 80,
        "operator_history_score": 90,
    }
    defaults.update(overrides)
    return defaults


def range_slot_payload(mission_id, **overrides) -> dict:
    """PRD §3.5: range slot request inputs."""
    defaults = {
        "mission_id": mission_id,
        "range_code": "CCAFS",
        "window_open_utc": MISSION_WINDOW_OPEN,
        "window_close_utc": MISSION_WINDOW_CLOSE,
    }
    defaults.update(overrides)
    return defaults


def exclusion_window_payload(**overrides) -> dict:
    """PRD §3.5: exclusion window inputs (half-open [start_utc, end_utc))."""
    defaults = {
        "scope_type": "RANGE",
        "scope_value": "CCAFS",
        "kind": "WEATHER",
        "start_utc": "2026-10-15T00:00:00Z",
        "end_utc": "2026-10-16T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def delay_payload(**overrides) -> dict:
    """PRD §3.7: delay inputs."""
    defaults = {
        "new_window_open_utc": "2026-11-01T00:00:00Z",
        "new_window_close_utc": "2026-11-10T00:00:00Z",
        "reason_code": "RANGE_CONFLICT",
    }
    defaults.update(overrides)
    return defaults


def rebook_payload(to_mission_id, expected_contract_version) -> dict:
    """PRD §3.7 + §2.8: rebook inputs including the OCC guard."""
    return {
        "to_mission_id": to_mission_id,
        "expected_contract_version": expected_contract_version,
    }
