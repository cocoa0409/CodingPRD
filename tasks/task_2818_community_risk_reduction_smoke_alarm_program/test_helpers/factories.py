"""Request payload builders.

Each builder produces a body that satisfies the PRD's required-field list for one
endpoint, with keyword overrides for the field under test. Monetary amounts are
whole cents expressed as JSON integers; percentages are decimal numbers; calendar
dates use ``YYYY-MM-DD`` while instants carry a full ISO 8601 UTC timestamp.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    AppointmentOption,
    AssessmentBasis,
    CertificationLevel,
    ContactMethod,
    DeviceType,
    FollowUpOutcome,
    InstallOutcome,
    IssuedChannel,
    OrgType,
    PlacementLocation,
    ReimbursementBasis,
    ReportDecision,
)


def _apply(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Merge overrides; a value of ``...`` removes the key entirely."""
    for key, value in overrides.items():
        if value is ...:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# ---------------------------------------------------------------------------
# Risk zones
# ---------------------------------------------------------------------------
def zone_payload(**overrides: Any) -> Dict[str, Any]:
    """A leaf zone that scores in the middle tier on the demographic basis."""
    payload: Dict[str, Any] = {
        "zone_code": "Z-B54",
        "name": "Birchwood Leaf",
        "occupied_units": 2000,
        "structure_fire_count_5yr": 15,
        "fire_injury_count_5yr": 2,
        "pre_1980_unit_pct": 40.0,
        "senior_household_pct": 20.0,
        "under5_household_pct": 8.0,
        "disability_household_pct": 4.0,
        "assumed_alarm_absence_pct": 50.0,
        "daily_visit_cap": 12,
    }
    return _apply(payload, overrides)


def district_payload(**overrides: Any) -> Dict[str, Any]:
    """A zone intended to become a district once a child is nested beneath it."""
    payload = zone_payload(
        zone_code="Z-DIST",
        name="Birchwood District",
        occupied_units=100,
        structure_fire_count_5yr=0,
        fire_injury_count_5yr=0,
        pre_1980_unit_pct=0.0,
        senior_household_pct=0.0,
        under5_household_pct=0.0,
        disability_household_pct=0.0,
        assumed_alarm_absence_pct=0.0,
        daily_visit_cap=4,
    )
    return _apply(payload, overrides)


def assessment_payload(expected_zone_version: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "basis": AssessmentBasis.PROVISIONAL,
        "expected_zone_version": expected_zone_version,
    }
    return _apply(payload, overrides)


def fire_incident_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "incident_number": "INC-0001",
        "occurred_at": "2026-05-01T03:15:00Z",
        "working_alarm_present": False,
    }
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Households and follow-ups
# ---------------------------------------------------------------------------
def household_payload(zone_id: str, **overrides: Any) -> Dict[str, Any]:
    """A single-storey, single-sleeping-area household with no vulnerabilities."""
    payload: Dict[str, Any] = {
        "zone_id": zone_id,
        "address_line": "1 Birch Road",
        "occupant_count": 2,
        "sleeping_areas_count": 1,
        "storeys": 1,
    }
    return _apply(payload, overrides)


def follow_up_payload(household_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "household_id": household_id,
        "contact_method": ContactMethod.PHONE,
        "outcome": FollowUpOutcome.NO_ANSWER,
    }
    return _apply(payload, overrides)


def follow_up_reached_present_payload(
    household_id: str, alarms_present_count: int = 2, plan_practiced: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "household_id": household_id,
        "contact_method": ContactMethod.PHONE,
        "outcome": FollowUpOutcome.REACHED_ALARM_PRESENT,
        "alarms_present_count": alarms_present_count,
        "plan_practiced": plan_practiced,
    }
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Crews, routes and visits
# ---------------------------------------------------------------------------
def crew_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "crew_code": "CREW-B1",
        "member_count": 2,
        "certification_level": CertificationLevel.ADVANCED,
        "max_daily_minutes": 480,
    }
    return _apply(payload, overrides)


def route_payload(zone_id: str, crew_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "zone_id": zone_id,
        "crew_id": crew_id,
        "service_date": "2026-08-03",
        "window_start_utc": "2026-08-03T13:00:00Z",
        "window_end_utc": "2026-08-03T21:00:00Z",
        "planned_slots": 2,
    }
    return _apply(payload, overrides)


def visit_payload(household_id: str, route_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "household_id": household_id,
        "route_id": route_id,
        "scheduled_start_utc": "2026-08-03T14:00:00Z",
        "appointment_option": AppointmentOption.SCHEDULED_APPOINTMENT,
    }
    return _apply(payload, overrides)


def reschedule_payload(route_id: str, scheduled_start_utc: str) -> Dict[str, Any]:
    return {"route_id": route_id, "scheduled_start_utc": scheduled_start_utc}


def cancel_payload(cancel_reason: str) -> Dict[str, Any]:
    return {"cancel_reason": cancel_reason}


def arrive_payload(
    pre_existing_working_smoke_alarms: int = 0,
    pre_existing_working_co_alarms: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "occupant_present": True,
        "pre_existing_working_smoke_alarms": pre_existing_working_smoke_alarms,
        "pre_existing_working_co_alarms": pre_existing_working_co_alarms,
    }
    return _apply(payload, overrides)


def education_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "education_outcome": "DELIVERED",
        "topics_covered": ["ALARM_TESTING"],
        "escape_plan_walkthrough": True,
    }
    return _apply(payload, overrides)


def education_declined_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"education_outcome": "DECLINED"}
    return _apply(payload, overrides)


def complete_payload(
    occupant_signature_name: str = "L. Osei", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "install_outcome": InstallOutcome.COMPLETE,
        "occupant_signature_name": occupant_signature_name,
    }
    return _apply(payload, overrides)


def deferred_payload(deferral_reason: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "install_outcome": InstallOutcome.DEFERRED,
        "deferral_reason": deferral_reason,
    }
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Partners, grants, lots and installations
# ---------------------------------------------------------------------------
def partner_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "org_name": "Firesafe Trust",
        "org_type": OrgType.NONPROFIT,
        "contact_email": "ops@firesafe.example",
        "agreement_signed": True,
    }
    return _apply(payload, overrides)


def grant_payload(partner_id: str, **overrides: Any) -> Dict[str, Any]:
    """A unit-rate grant funding smoke and CO alarms across the second half of 2026."""
    payload: Dict[str, Any] = {
        "partner_id": partner_id,
        "grant_code": "G-UNIT-1",
        "authorized_cents": 500000,
        "period_start_date": "2026-07-01",
        "period_end_date": "2026-12-31",
        "allowed_device_types": [DeviceType.SMOKE_10YR, DeviceType.CO_ALARM],
        "unit_rate_cents_by_type": {
            DeviceType.SMOKE_10YR: 2195,
            DeviceType.CO_ALARM: 3495,
        },
        "reimbursement_basis": ReimbursementBasis.UNIT_RATE,
        "reimbursement_pct": 87.5,
        "indirect_rate_pct": 12.5,
        "match_pct": 20.0,
    }
    return _apply(payload, overrides)


def smoke_only_grant_payload(partner_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = grant_payload(
        partner_id,
        allowed_device_types=[DeviceType.SMOKE_10YR],
        unit_rate_cents_by_type={DeviceType.SMOKE_10YR: 2195},
    )
    return _apply(payload, overrides)


def device_lot_payload(grant_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "funding_grant_id": grant_id,
        "sku": "SMK-10Y-A",
        "device_type": DeviceType.SMOKE_10YR,
        "unit_cost_cents": 1850,
        "received_qty": 10,
        "expiry_date": "2028-06-30",
    }
    return _apply(payload, overrides)


def co_lot_payload(grant_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = device_lot_payload(
        grant_id,
        sku="CO-A",
        device_type=DeviceType.CO_ALARM,
        unit_cost_cents=2990,
        received_qty=5,
    )
    return _apply(payload, overrides)


def installation_payload(visit_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "visit_id": visit_id,
        "device_type": DeviceType.SMOKE_10YR,
        "placement_location": PlacementLocation.SLEEPING_AREA,
        "storey": 1,
    }
    return _apply(payload, overrides)


def void_payload(voided_reason: str) -> Dict[str, Any]:
    return {"voided_reason": voided_reason}


# ---------------------------------------------------------------------------
# Escape plans
# ---------------------------------------------------------------------------
def escape_plan_payload(
    household_id: str,
    expected_household_version: int,
    secondary_exit_count: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "household_id": household_id,
        "expected_household_version": expected_household_version,
        "primary_exit_per_sleeping_area": True,
        "secondary_exit_count": secondary_exit_count,
        "meeting_point_description": "Mailbox at 1 Birch Road",
    }
    return _apply(payload, overrides)


def issue_plan_payload(
    issued_channel: str = IssuedChannel.IN_PERSON, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"issued_channel": issued_channel}
    return _apply(payload, overrides)


# ---------------------------------------------------------------------------
# Grant reports
# ---------------------------------------------------------------------------
def grant_report_payload(grant_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "grant_id": grant_id,
        "period_start_date": "2026-08-01",
        "period_end_date": "2026-08-31",
    }
    return _apply(payload, overrides)


def submit_report_payload(
    attestation_name: str = "P. Nakamura", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"attestation_name": attestation_name}
    return _apply(payload, overrides)


def decision_payload(
    decision: str = ReportDecision.ACCEPT,
    reviewer_note: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if reviewer_note is not None:
        payload["reviewer_note"] = reviewer_note
    return _apply(payload, overrides)


def unit_rates_for(types: List[str], rate_cents: int = 2195) -> Dict[str, int]:
    """A funded unit rate for every device type in ``types``."""
    return {device_type: rate_cents for device_type in types}
