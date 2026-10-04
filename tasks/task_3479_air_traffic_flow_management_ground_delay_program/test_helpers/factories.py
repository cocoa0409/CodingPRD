"""Request payload builders.

Each builder returns a valid body for one write endpoint, carrying only the
input fields that endpoint accepts; any test can override by keyword. Times
default to the scenario day shared by the design recipes - 2026-09-15, which
never precedes the clock's startup instant of 2026-09-01 - so a bare call is
always a legal, in-the-future window once the clock is pinned to midday.
"""

from typing import Any, Dict, Optional

# The scenario day every default window below is built on.
DEFAULT_DAY = "2026-09-15"


def at(hhmm: str, day: str = DEFAULT_DAY) -> str:
    """Render "13:05" as a full ISO 8601 UTC instant on the scenario day."""
    return f"{day}T{hhmm}:00Z"


def facility_payload(
    ident: str = "KEWR",
    facility_type: str = "AIRPORT",
    base_acceptance_rate: int = 30,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "ident": ident,
        "facility_type": facility_type,
        "base_acceptance_rate": base_acceptance_rate,
    }
    payload.update(overrides)
    return payload


def sector_payload(
    ident: str = "ZDC42",
    base_acceptance_rate: int = 2,
    **overrides: Any,
) -> Dict[str, Any]:
    """An en route sector, for reroute assignments."""
    return facility_payload(
        ident=ident,
        facility_type="EN_ROUTE_SECTOR",
        base_acceptance_rate=base_acceptance_rate,
        **overrides,
    )


def facility_patch_payload(**overrides: Any) -> Dict[str, Any]:
    """PATCH body: base_acceptance_rate and/or status."""
    return dict(overrides)


def operator_payload(
    name: str = "Alpha Air",
    operator_type: str = "SCHEDULED_CARRIER",
    cdm_member: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"name": name, "operator_type": operator_type}
    if cdm_member is not None:
        payload["cdm_member"] = cdm_member
    payload.update(overrides)
    return payload


def ga_operator_payload(name: str = "Golf Aviation", **overrides: Any) -> Dict[str, Any]:
    return operator_payload(name=name, operator_type="GENERAL_AVIATION", **overrides)


def charter_operator_payload(name: str = "Charter One", **overrides: Any) -> Dict[str, Any]:
    return operator_payload(name=name, operator_type="UNSCHEDULED_CHARTER", **overrides)


def constraint_event_payload(
    event_type: str = "WEATHER",
    severity: int = 2,
    window_start: str = None,
    window_end: str = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "event_type": event_type,
        "severity": severity,
        "window_start": window_start if window_start is not None else at("13:00"),
        "window_end": window_end if window_end is not None else at("15:00"),
    }
    payload.update(overrides)
    return payload


def constraint_event_extend_payload(
    window_end: str,
    severity: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"window_end": window_end}
    if severity is not None:
        payload["severity"] = severity
    payload.update(overrides)
    return payload


def capacity_forecast_payload(
    variant: str = "PLANNING",
    window_start: str = None,
    window_end: str = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "variant": variant,
        "window_start": window_start if window_start is not None else at("13:00"),
        "window_end": window_end if window_end is not None else at("15:00"),
    }
    payload.update(overrides)
    return payload


def tmi_payload(
    tmi_type: str = "GROUND_DELAY_PROGRAM",
    program_start: str = None,
    program_end: str = None,
    controlled_rate: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Propose body. ``controlled_rate`` is omitted unless given, so a REROUTE
    proposal (which stores 0) and a GDP proposal (which must carry a legal
    rate) are both faithful to the endpoint's input list."""
    payload: Dict[str, Any] = {
        "tmi_type": tmi_type,
        "program_start": program_start if program_start is not None else at("13:00"),
        "program_end": program_end if program_end is not None else at("15:00"),
    }
    if controlled_rate is not None:
        payload["controlled_rate"] = controlled_rate
    payload.update(overrides)
    return payload


def gdp_payload(
    program_start: str = None,
    program_end: str = None,
    controlled_rate: int = 6,
    **overrides: Any,
) -> Dict[str, Any]:
    return tmi_payload(
        tmi_type="GROUND_DELAY_PROGRAM",
        program_start=program_start,
        program_end=program_end,
        controlled_rate=controlled_rate,
        **overrides,
    )


def tmi_revision_payload(
    expected_tmi_version: int,
    reason: str = "weather improving",
    new_controlled_rate: Optional[int] = None,
    new_program_end: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "reason": reason,
        "expected_tmi_version": expected_tmi_version,
    }
    if new_controlled_rate is not None:
        payload["new_controlled_rate"] = new_controlled_rate
    if new_program_end is not None:
        payload["new_program_end"] = new_program_end
    payload.update(overrides)
    return payload


def flight_payload(
    designator: str = "AAL1",
    origin: str = "KORD",
    arrival_facility_id: str = "",
    scheduled_arrival: str = None,
    estimated_arrival: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "designator": designator,
        "origin": origin,
        "arrival_facility_id": arrival_facility_id,
        "scheduled_arrival": scheduled_arrival if scheduled_arrival is not None else at("13:05"),
    }
    if estimated_arrival is not None:
        payload["estimated_arrival"] = estimated_arrival
    payload.update(overrides)
    return payload


def flight_update_payload(
    expected_flight_version: int,
    new_eta: Optional[str] = None,
    new_ops_status: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"expected_flight_version": expected_flight_version}
    if new_eta is not None:
        payload["new_eta"] = new_eta
    if new_ops_status is not None:
        payload["new_ops_status"] = new_ops_status
    payload.update(overrides)
    return payload


def substitution_payload(
    flight_id_1: str,
    flight_id_2: str,
    note: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"flight_id_1": flight_id_1, "flight_id_2": flight_id_2}
    if note is not None:
        payload["note"] = note
    payload.update(overrides)
    return payload


def ga_request_payload(
    tmi_id: str,
    requested_window_start: str = None,
    requested_window_end: str = None,
    priority_class: str = "STANDARD",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "tmi_id": tmi_id,
        "requested_window_start": (
            requested_window_start if requested_window_start is not None else at("14:30")
        ),
        "requested_window_end": (
            requested_window_end if requested_window_end is not None else at("15:00")
        ),
        "priority_class": priority_class,
    }
    payload.update(overrides)
    return payload


def ga_adjudication_payload(decision: str = "ACCOMMODATE", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def reroute_assignment_payload(
    flight_id: str,
    via_sector_id: str,
    assigned_route: str = "J60",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "flight_id": flight_id,
        "via_sector_id": via_sector_id,
        "assigned_route": assigned_route,
    }
    payload.update(overrides)
    return payload


def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}
