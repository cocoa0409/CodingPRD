"""Composite setup helpers.

The harness restarts the API server before every test, so every test begins
against an empty database and a clock at its startup value.  Every precondition
these helpers build is therefore built from scratch through declared endpoints
only -- there is no seeded reference data to lean on.

The helpers are ordinary functions rather than pytest fixtures so that a test can
call one twice (two facilities, two rooms, two sibling cases) and so that the
call site can see the ids it is threading.  Each uses ``get_success_data`` so a
broken precondition surfaces as a setup failure rather than as a misleading
assertion failure inside the test body.

Roles whose identity is an entity id are always threaded with the real id:
``FacilityCoordinator`` carries the facility id, and ``Interventionalist``,
``SedationRN`` and ``Coder`` each carry their own clinician id.  Using the shared
role constants for an ownership-gated call would be rejected by the
assigned-clinician, attestation-identity and facility-scope checks.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import CLOCK_STARTUP_UTC
from .test_users import (
    make_coder_headers,
    make_facility_coordinator_headers,
    make_interventionalist_headers,
    make_sedation_rn_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["center_admin_headers"]
COORDINATOR = TEST_USERS["access_coordinator_headers"]

# Default timeline, anchored on the clock's startup value.
DEFAULT_PLACED_ON = "2026-06-20"
EARLIER_READING_AT = "2026-07-25T09:00:00Z"
LATEST_READING_AT = "2026-07-31T09:00:00Z"
DEFAULT_SLOT_START = "2026-08-01T13:00:00Z"
DEFAULT_SLOT_END = "2026-08-01T14:00:00Z"
DEFAULT_SEDATION_END_AT = "2026-08-01T14:00:00Z"

# A case is booked while the clock still reads its startup value, so the slot lies in
# the future; the clock is then moved onto the slot before the case enters the room and
# onto the discharge instant before the patient leaves, because every server-written
# instant (consumed_at, discharged_at, completed_at, abandoned_at, converted_at) is the
# clock at the moment of the request.
CASE_START_CLOCK = "2026-08-01T13:00:00Z"
CASE_DISCHARGE_CLOCK = "2026-08-01T14:30:00Z"


# ─── Tier 1: reference data ───────────────────────────────────────────────────

def set_clock(api, to_iso8601: str, headers: Dict[str, str] = ADMIN) -> Dict[str, Any]:
    """Move the logical clock; every temporal rule reads it rather than wall time."""
    return get_success_data(api.set_clock(to_iso8601, headers))


def reset_clock(api, headers: Dict[str, str] = ADMIN) -> Dict[str, Any]:
    return set_clock(api, CLOCK_STARTUP_UTC, headers)


def seed_facility(api, headers: Dict[str, str] = ADMIN, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_dialysis_facility(f.dialysis_facility_payload(**overrides), headers)
    )


def seed_patient(
    api, facility_id: str, headers: Dict[str, str] = ADMIN, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_patient(f.patient_payload(facility_id, **overrides), headers)
    )


def seed_interventionalist(api, headers: Dict[str, str] = ADMIN, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_clinician(f.clinician_payload("INTERVENTIONALIST", **overrides), headers)
    )


def seed_sedation_rn(api, headers: Dict[str, str] = ADMIN, **overrides: Any) -> Dict[str, Any]:
    """A nurse credentialed for moderate sedation unless the caller overrides it."""
    return get_success_data(api.create_clinician(f.sedation_rn_payload(**overrides), headers))


def seed_coder(api, headers: Dict[str, str] = ADMIN, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_clinician(f.clinician_payload("CODER", **overrides), headers)
    )


def seed_room(api, headers: Dict[str, str] = ADMIN, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_procedure_room(f.procedure_room_payload(**overrides), headers)
    )


def seed_lot(
    api,
    device_type: str = "BALLOON",
    headers: Dict[str, str] = ADMIN,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_device_lot(f.device_lot_payload(device_type, **overrides), headers)
    )


# ─── Tier 2: the entity hierarchy ────────────────────────────────────────────

def seed_center(api, **facility_overrides: Any) -> Dict[str, Any]:
    """Facility, patient, one operator, one sedation nurse, one coder and one room,
    together with the headers each entity-backed principal must use."""
    facility = seed_facility(api, **facility_overrides)
    patient = seed_patient(api, facility["id"])
    operator = seed_interventionalist(api)
    nurse = seed_sedation_rn(api)
    coder = seed_coder(api)
    room = seed_room(api)
    return {
        "facility": facility,
        "facility_id": facility["id"],
        "facility_headers": make_facility_coordinator_headers(facility["id"]),
        "patient": patient,
        "patient_id": patient["id"],
        "operator": operator,
        "operator_id": operator["id"],
        "operator_headers": make_interventionalist_headers(operator["id"]),
        "nurse": nurse,
        "nurse_id": nurse["id"],
        "nurse_headers": make_sedation_rn_headers(nurse["id"]),
        "coder": coder,
        "coder_id": coder["id"],
        "coder_headers": make_coder_headers(coder["id"]),
        "room": room,
        "room_id": room["id"],
    }


def seed_access(
    api, patient_id: str, headers: Dict[str, str] = COORDINATOR, **overrides: Any
) -> Dict[str, Any]:
    overrides.setdefault("placed_on", DEFAULT_PLACED_ON)
    return get_success_data(
        api.create_vascular_access(f.vascular_access_payload(patient_id, **overrides), headers)
    )


def seed_catheter_access(
    api, patient_id: str, headers: Dict[str, str] = COORDINATOR, **overrides: Any
) -> Dict[str, Any]:
    overrides.setdefault("placed_on", DEFAULT_PLACED_ON)
    return get_success_data(
        api.create_vascular_access(f.catheter_access_payload(patient_id, **overrides), headers)
    )


def move_access(
    api, access_id: str, to_status: str, headers: Dict[str, str] = COORDINATOR
) -> Dict[str, Any]:
    return get_success_data(
        api.set_vascular_access_status(access_id, f.access_status_payload(to_status), headers)
    )


def seed_access_in_use(
    api, patient_id: str, headers: Dict[str, str] = COORDINATOR, **overrides: Any
) -> Dict[str, Any]:
    """A fistula walked PLANNED -> PLACED -> MATURING -> IN_USE."""
    access = seed_access(api, patient_id, headers, **overrides)
    move_access(api, access["id"], "PLACED", headers)
    move_access(api, access["id"], "MATURING", headers)
    return move_access(api, access["id"], "IN_USE", headers)


def seed_access_maturing(
    api, patient_id: str, headers: Dict[str, str] = COORDINATOR, **overrides: Any
) -> Dict[str, Any]:
    access = seed_access(api, patient_id, headers, **overrides)
    move_access(api, access["id"], "PLACED", headers)
    return move_access(api, access["id"], "MATURING", headers)


def seed_catheter_in_use(
    api, patient_id: str, headers: Dict[str, str] = COORDINATOR, **overrides: Any
) -> Dict[str, Any]:
    """A tunnelled catheter walked PLANNED -> PLACED -> IN_USE, skipping MATURING."""
    access = seed_catheter_access(api, patient_id, headers, **overrides)
    move_access(api, access["id"], "PLACED", headers)
    return move_access(api, access["id"], "IN_USE", headers)


def seed_reading(
    api,
    access_id: str,
    facility_id: str,
    reading_at: str = LATEST_READING_AT,
    headers: Dict[str, str] = COORDINATOR,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_surveillance_reading(
            f.surveillance_reading_payload(access_id, facility_id, reading_at, **overrides),
            headers,
        )
    )


def seed_reading_pair(
    api,
    access_id: str,
    facility_id: str,
    earlier_flow: int = 900,
    latest_flow: int = 850,
    headers: Dict[str, str] = COORDINATOR,
    **latest_overrides: Any,
) -> List[Dict[str, Any]]:
    """Two in-window readings, which is what makes triage TREND_BASED."""
    earlier = seed_reading(
        api,
        access_id,
        facility_id,
        EARLIER_READING_AT,
        headers,
        access_flow_ml_min=earlier_flow,
    )
    latest = seed_reading(
        api,
        access_id,
        facility_id,
        LATEST_READING_AT,
        headers,
        access_flow_ml_min=latest_flow,
        **latest_overrides,
    )
    return [earlier, latest]


# ─── Tier 3: referral and case lifecycle shortcuts ───────────────────────────

def seed_referral(
    api,
    access_id: str,
    facility_id: str,
    headers: Dict[str, str] = COORDINATOR,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_referral(f.referral_payload(access_id, facility_id, **overrides), headers)
    )


def triage(api, referral_id: str, headers: Dict[str, str] = COORDINATOR) -> Dict[str, Any]:
    return get_success_data(api.triage_referral(referral_id, headers))


def seed_triaged_referral(
    api,
    center: Dict[str, Any],
    access_id: Optional[str] = None,
    earlier_flow: int = 900,
    latest_flow: int = 850,
    **referral_overrides: Any,
) -> Dict[str, Any]:
    """An access with two in-window readings and a referral carried through triage.

    With the default flows the score bands to ROUTINE, which carries no
    scheduling-date constraint, so a booking may be placed on any future slot.
    """
    if access_id is None:
        access_id = seed_access_in_use(api, center["patient_id"])["id"]
    readings = seed_reading_pair(
        api, access_id, center["facility_id"], earlier_flow, latest_flow
    )
    referral = seed_referral(api, access_id, center["facility_id"], **referral_overrides)
    triaged = triage(api, referral["id"])
    return {
        "access_id": access_id,
        "readings": readings,
        "reading_id": readings[-1]["id"],
        "referral": triaged,
        "referral_id": triaged["id"],
    }


def book_case(
    api,
    referral_id: str,
    room_id: str,
    operator_id: str,
    expected_referral_version: int,
    scheduled_start: str = DEFAULT_SLOT_START,
    scheduled_end: str = DEFAULT_SLOT_END,
    headers: Dict[str, str] = COORDINATOR,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_procedure(
            f.procedure_payload(
                referral_id,
                room_id,
                operator_id,
                scheduled_start,
                scheduled_end,
                expected_referral_version,
                **overrides,
            ),
            headers,
        )
    )


def seed_scheduled_case(
    api,
    center: Optional[Dict[str, Any]] = None,
    access_id: Optional[str] = None,
    scheduled_start: str = DEFAULT_SLOT_START,
    scheduled_end: str = DEFAULT_SLOT_END,
    sedation_level: str = "NONE",
    procedure_type: str = "ANGIOPLASTY",
    earlier_flow: int = 900,
    latest_flow: int = 850,
    **referral_overrides: Any,
) -> Dict[str, Any]:
    """Reference data, an IN_USE access, two readings, a triaged referral and a
    booked case -- the common starting point for every room-flow scenario."""
    if center is None:
        center = seed_center(api)
    triaged = seed_triaged_referral(
        api, center, access_id, earlier_flow, latest_flow, **referral_overrides
    )
    sedation_rn_id = center["nurse_id"] if sedation_level == "MODERATE" else None
    procedure = book_case(
        api,
        triaged["referral_id"],
        center["room_id"],
        center["operator_id"],
        triaged["referral"]["version"],
        scheduled_start,
        scheduled_end,
        sedation_level=sedation_level,
        sedation_rn_id=sedation_rn_id,
        procedure_type=procedure_type,
    )
    bundle: Dict[str, Any] = dict(center)
    bundle.update(triaged)
    bundle["procedure"] = procedure
    bundle["procedure_id"] = procedure["id"]
    return bundle


def reserve_units(
    api,
    procedure_id: str,
    lot: Dict[str, Any],
    quantity: int,
    headers: Dict[str, str] = COORDINATOR,
) -> Dict[str, Any]:
    """Explicit reservation, declaring the lot version the caller last observed."""
    return get_success_data(
        api.create_device_usage(
            procedure_id, f.device_usage_payload(lot["id"], quantity, lot["version"]), headers
        )
    )


def start_case(api, bundle: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(
        api.start_procedure(bundle["procedure_id"], bundle["operator_headers"])
    )


def move_to_recovery(
    api, bundle: Dict[str, Any], sedation_end_at: str = DEFAULT_SEDATION_END_AT
) -> Dict[str, Any]:
    return get_success_data(
        api.move_procedure_to_recovery(
            bundle["procedure_id"], f.recovery_payload(sedation_end_at), bundle["operator_headers"]
        )
    )


def chart_observation(
    api,
    bundle: Dict[str, Any],
    observed_at: str,
    aldrete_score: int = 9,
    on_room_air: bool = True,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_recovery_observation(
            bundle["procedure_id"],
            f.recovery_observation_payload(observed_at, aldrete_score, on_room_air),
            bundle["nurse_headers"],
        )
    )


def chart_discharge_ready_observations(
    api,
    bundle: Dict[str, Any],
    first_at: str = "2026-08-01T14:05:00Z",
    last_at: str = "2026-08-01T14:25:00Z",
) -> List[Dict[str, Any]]:
    """Two observations twenty minutes apart, the later one Aldrete 9 on room air --
    comfortably clear of the fifteen-minute span the criteria require."""
    return [
        chart_observation(api, bundle, first_at),
        chart_observation(api, bundle, last_at),
    ]


def discharge(api, bundle: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(
        api.discharge_procedure(bundle["procedure_id"], bundle["nurse_headers"])
    )


def abort(api, bundle: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.abort_procedure(
            bundle["procedure_id"], f.abort_payload(**overrides), bundle["operator_headers"]
        )
    )


def seed_case_in_room(
    api, start_clock: Optional[str] = CASE_START_CLOCK, **kwargs: Any
) -> Dict[str, Any]:
    bundle = seed_scheduled_case(api, **kwargs)
    if start_clock is not None:
        set_clock(api, start_clock)
    bundle["procedure"] = start_case(api, bundle)
    return bundle


def seed_case_in_recovery(
    api, sedation_end_at: str = DEFAULT_SEDATION_END_AT, **kwargs: Any
) -> Dict[str, Any]:
    kwargs.setdefault("sedation_level", "MODERATE")
    bundle = seed_case_in_room(api, **kwargs)
    bundle["procedure"] = move_to_recovery(api, bundle, sedation_end_at)
    return bundle


def seed_discharged_case(
    api, discharge_clock: Optional[str] = CASE_DISCHARGE_CLOCK, **kwargs: Any
) -> Dict[str, Any]:
    """A moderate-sedation case carried all the way to DISCHARGED, which fires the
    five-hop consumption, completion, access, conversion and abandonment chain."""
    bundle = seed_case_in_recovery(api, **kwargs)
    bundle["observations"] = chart_discharge_ready_observations(api, bundle)
    if discharge_clock is not None:
        set_clock(api, discharge_clock)
    bundle["procedure"] = discharge(api, bundle)
    return bundle


def seed_aborted_case(api, **kwargs: Any) -> Dict[str, Any]:
    """Aborted from the room, so the consumption instant is the in-room clock."""
    bundle = seed_case_in_room(api, **kwargs)
    bundle["procedure"] = abort(api, bundle)
    return bundle


# ─── Tier 4: revenue-cycle shortcuts ─────────────────────────────────────────

def file_code_line(
    api,
    bundle: Dict[str, Any],
    hcpcs_code: str = "35476",
    code_family: str = "ANGIOPLASTY",
    base_allowed_cents: int = 180050,
    rank: int = 1,
    modifier: Optional[str] = None,
) -> Dict[str, Any]:
    """Filed by the coder, who is a third principal distinct from the operator and
    the sedation nurse."""
    return get_success_data(
        api.create_procedure_code(
            bundle["procedure_id"],
            f.procedure_code_payload(
                hcpcs_code, code_family, base_allowed_cents, rank, modifier
            ),
            bundle["coder_headers"],
        )
    )


def attest(api, bundle: Dict[str, Any], reading_id: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    """Attestation is the primary operator's act and cites a reading on the case's
    own access inside the thirty-day lookback ending at scheduled_start."""
    return get_success_data(
        api.attest_procedure(
            bundle["procedure_id"],
            f.attest_payload(reading_id or bundle["reading_id"], **overrides),
            bundle["operator_headers"],
        )
    )


def bill(api, bundle: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(api.bill_procedure(bundle["procedure_id"], ADMIN))


def deny(api, bundle: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.deny_procedure(bundle["procedure_id"], f.deny_payload(**overrides), ADMIN)
    )


def rebill(api, bundle: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(api.rebill_procedure(bundle["procedure_id"], ADMIN))


def seed_case_with_consumed_balloon(
    api,
    quantity: int = 1,
    received_quantity: int = 10,
    terminal: str = "DISCHARGED",
    **kwargs: Any,
) -> Dict[str, Any]:
    """A case that reserved units from a balloon lot before entering the room and then
    reached a terminal clinical state, which consumes the reservation.

    A consumed balloon is what the code-to-device gate demands of an unbundled
    ``ANGIOPLASTY`` line at billing time.
    """
    kwargs.setdefault("sedation_level", "MODERATE")
    bundle = seed_scheduled_case(api, **kwargs)
    lot = seed_lot(api, "BALLOON", received_quantity=received_quantity)
    usage = reserve_units(api, bundle["procedure_id"], lot, quantity)
    bundle["lot"] = lot
    bundle["lot_id"] = lot["id"]
    bundle["usage"] = usage
    bundle["usage_id"] = usage["id"]
    set_clock(api, CASE_START_CLOCK)
    bundle["procedure"] = start_case(api, bundle)
    if terminal == "ABORTED":
        bundle["procedure"] = abort(api, bundle)
    else:
        bundle["procedure"] = move_to_recovery(api, bundle)
        bundle["observations"] = chart_discharge_ready_observations(api, bundle)
        set_clock(api, CASE_DISCHARGE_CLOCK)
        bundle["procedure"] = discharge(api, bundle)
    return bundle


def seed_attested_case(
    api,
    base_allowed_cents: int = 180050,
    code_family: str = "ANGIOPLASTY",
    **kwargs: Any,
) -> Dict[str, Any]:
    """One code line filed by the coder and then attested by the primary operator, on a
    case whose balloon reservation was consumed so that billing can also pass."""
    bundle = seed_case_with_consumed_balloon(api, **kwargs)
    bundle["code"] = file_code_line(
        api, bundle, code_family=code_family, base_allowed_cents=base_allowed_cents
    )
    bundle["procedure"] = attest(api, bundle)
    return bundle


def seed_billed_case(api, **kwargs: Any) -> Dict[str, Any]:
    bundle = seed_attested_case(api, **kwargs)
    bundle["procedure"] = bill(api, bundle)
    return bundle


def seed_denied_case(api, **kwargs: Any) -> Dict[str, Any]:
    bundle = seed_billed_case(api, **kwargs)
    bundle["procedure"] = deny(api, bundle)
    return bundle


# ─── Tier 4: conversion planning ─────────────────────────────────────────────

def seed_draft_plan(
    api,
    patient_id: str,
    from_access: Dict[str, Any],
    target_access_id: Optional[str] = None,
    headers: Dict[str, str] = COORDINATOR,
    **overrides: Any,
) -> Dict[str, Any]:
    """Plan creation declares the source access version it observed, because creating a
    plan supersedes any existing draft on the same source access."""
    return get_success_data(
        api.create_conversion_plan(
            f.conversion_plan_payload(
                patient_id,
                from_access["id"],
                from_access["version"],
                target_access_id=target_access_id,
                **overrides,
            ),
            headers,
        )
    )


def activate_plan(api, plan_id: str, headers: Dict[str, str] = COORDINATOR) -> Dict[str, Any]:
    return get_success_data(api.activate_conversion_plan(plan_id, headers))


def seed_active_plan(
    api,
    patient_id: str,
    from_access: Dict[str, Any],
    target_access_id: str,
    headers: Dict[str, str] = COORDINATOR,
    **overrides: Any,
) -> Dict[str, Any]:
    plan = seed_draft_plan(
        api, patient_id, from_access, target_access_id, headers, **overrides
    )
    return activate_plan(api, plan["id"], headers)


def file_maturation_check(
    api,
    plan_id: str,
    diameter_mm: float = 6.0,
    flow_ml_min: int = 600,
    depth_mm: float = 6.0,
    headers: Dict[str, str] = COORDINATOR,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_maturation_check(
            plan_id, f.maturation_check_payload(diameter_mm, flow_ml_min, depth_mm), headers
        )
    )


# ─── Tier 5: facility posture and inventory sweeps ───────────────────────────

def update_missed_treatments(
    api, referral_id: str, count: int, headers: Dict[str, str] = COORDINATOR
) -> Dict[str, Any]:
    """Overwrites the absolute missed-treatment count and rescores the facility, which
    is the ordinary way a posture degrades mid-flight."""
    return get_success_data(
        api.update_referral_missed_treatments(
            referral_id, f.missed_treatments_payload(count), headers
        )
    )


def request_info(
    api, referral_id: str, headers: Dict[str, str] = COORDINATOR, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.request_referral_info(referral_id, f.request_info_payload(**overrides), headers)
    )


def resubmit(
    api, referral_id: str, facility_headers: Dict[str, str], **overrides: Any
) -> Dict[str, Any]:
    """Resubmission is exclusive to the referring facility's own coordinator."""
    return get_success_data(
        api.resubmit_referral(referral_id, f.resubmit_payload(**overrides), facility_headers)
    )


def decline(api, referral_id: str, headers: Dict[str, str] = COORDINATOR, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.decline_referral(referral_id, f.decline_payload(**overrides), headers)
    )


def quarantine_lot(api, lot_id: str, headers: Dict[str, str] = ADMIN, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.quarantine_device_lot(lot_id, f.quarantine_payload(**overrides), headers)
    )


def release_lot(api, lot_id: str, headers: Dict[str, str] = ADMIN) -> Dict[str, Any]:
    return get_success_data(api.release_device_lot(lot_id, headers))


def run_expiry_sweep(api, headers: Dict[str, str] = ADMIN) -> Dict[str, Any]:
    return get_success_data(api.run_expiry_sweep(headers))


def cancel_case(api, procedure_id: str, headers: Dict[str, str] = COORDINATOR, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.cancel_procedure(procedure_id, headers, f.cancel_payload(**overrides))
    )


# ─── Read-back helpers ───────────────────────────────────────────────────────

def read_facility(api, facility_id: str, headers: Dict[str, str] = ADMIN) -> Dict[str, Any]:
    return get_success_data(api.get_dialysis_facility(facility_id, headers))


def read_patient(api, patient_id: str, headers: Dict[str, str] = ADMIN) -> Dict[str, Any]:
    return get_success_data(api.get_patient(patient_id, headers))


def read_access(api, access_id: str, headers: Dict[str, str] = ADMIN) -> Dict[str, Any]:
    return get_success_data(api.get_vascular_access(access_id, headers))


def read_referral(api, referral_id: str, headers: Dict[str, str] = ADMIN) -> Dict[str, Any]:
    return get_success_data(api.get_referral(referral_id, headers))


def read_procedure(api, procedure_id: str, headers: Dict[str, str] = ADMIN) -> Dict[str, Any]:
    return get_success_data(api.get_procedure(procedure_id, headers))


def read_lot(api, lot_id: str, headers: Dict[str, str] = ADMIN) -> Dict[str, Any]:
    return get_success_data(api.get_device_lot(lot_id, headers))


def read_usage(api, usage_id: str, headers: Dict[str, str] = ADMIN) -> Dict[str, Any]:
    return get_success_data(api.get_device_usage(usage_id, headers))


def read_plan(api, plan_id: str, headers: Dict[str, str] = ADMIN) -> Dict[str, Any]:
    return get_success_data(api.get_conversion_plan(plan_id, headers))


def read_infection_event(api, event_id: str, headers: Dict[str, str] = ADMIN) -> Dict[str, Any]:
    return get_success_data(api.get_infection_event(event_id, headers))


def record_infection(
    api, procedure_id: str, onset_at: str, headers: Dict[str, str] = COORDINATOR, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_infection_event(
            f.infection_event_payload(procedure_id, onset_at, **overrides), headers
        )
    )
