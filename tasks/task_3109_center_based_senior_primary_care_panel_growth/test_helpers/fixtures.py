"""Composite setup helpers for multi-step test prerequisites.

Setup calls use get_success_data() (lenient) so setup failures surface as clear
"errors during setup" instead of confusing assertion failures. Identity
threading: appointment completion is ownership-gated to the acting care team,
so completion always uses make_care_team_lead_headers(team["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_UTC
from .factories import (
    create_appointment_payload,
    create_attribution_payload,
    create_care_team_payload,
    create_center_payload,
    create_cost_claim_payload,
    create_health_plan_payload,
    create_monthly_settlement_payload,
    create_outreach_event_payload,
    create_patient_payload,
    create_room_payload,
    create_triage_case_payload,
    create_vehicle_payload,
)
from .test_users import TEST_USERS, make_care_team_lead_headers

NET = TEST_USERS["network_operator_headers"]
ENR = TEST_USERS["enrollment_coordinator_headers"]
FRONT = TEST_USERS["front_desk_headers"]
DISP = TEST_USERS["transport_dispatcher_headers"]
NURSE = TEST_USERS["triage_nurse_headers"]
ADJ = TEST_USERS["claims_adjudicator_headers"]
FA = TEST_USERS["finance_analyst_headers"]
FC = TEST_USERS["finance_controller_headers"]


def set_clock(current_utc):
    """Advance the logical clock (NetworkOperator-only test-driving capability)."""
    return get_success_data(api_client.set_clock(current_utc, NET))


# ─── Tier 1: State progression ──────────────────────────────────────────────

def create_center(**overrides):
    """Create a center (PRE_OPEN). Returns the center."""
    return get_success_data(api_client.create_center(create_center_payload(**overrides), NET))


def create_open_center(opened_on="2026-01-01", supports_behavioral=True, **center_overrides):
    """Center + one care team + one room, opened. Returns (center, team, room)."""
    center = create_center(opened_on=opened_on, **center_overrides)
    team = get_success_data(
        api_client.create_care_team(center["id"], create_care_team_payload(), NET)
    )
    room = get_success_data(
        api_client.create_room(
            center["id"], create_room_payload(supports_behavioral=supports_behavioral), NET
        )
    )
    center = get_success_data(api_client.open_center(center["id"], NET))
    return center, team, room


def create_health_plan(**overrides):
    return get_success_data(
        api_client.create_health_plan(create_health_plan_payload(**overrides), FC)
    )


def create_patient(**overrides):
    return get_success_data(api_client.create_patient(create_patient_payload(**overrides), ENR))


# ─── Tier 2: Entity hierarchy / attribution lifecycle ───────────────────────

def create_attribution(patient_id, health_plan_id, care_team_id, **overrides):
    """Create a PENDING attribution. Returns the attribution."""
    return get_success_data(
        api_client.create_attribution(
            create_attribution_payload(patient_id, health_plan_id, care_team_id, **overrides),
            ENR,
        )
    )


def activate_attribution(attribution_id):
    """Activate a PENDING attribution with the team's current version (OCC).
    Returns the activated attribution."""
    attr = get_success_data(api_client.get_attribution(attribution_id, ENR))
    team = get_success_data(api_client.get_care_team(attr["care_team_id"], NET))
    return get_success_data(
        api_client.activate_attribution(
            attribution_id, {"expected_care_team_version": team["version"]}, ENR
        )
    )


def create_active_attribution(patient_id, health_plan_id, care_team_id, **overrides):
    """Create + activate an attribution. Returns the ACTIVE attribution."""
    attr = create_attribution(patient_id, health_plan_id, care_team_id, **overrides)
    return activate_attribution(attr["id"])


def setup_panel_with_active_patient(**overrides):
    """Open center + plan + one ACTIVE-attributed patient.
    Returns (center, team, room, plan, patient, attribution)."""
    center, team, room = create_open_center(**overrides)
    plan = create_health_plan()
    patient = create_patient()
    attr = create_active_attribution(patient["id"], plan["id"], team["id"])
    return center, team, room, plan, patient, attr


# ─── Tier 3: Visit and ride lifecycles ──────────────────────────────────────

def create_appointment(care_team_id, patient_id, room_id, **overrides):
    """Schedule an appointment. Returns the SCHEDULED appointment."""
    return get_success_data(
        api_client.create_appointment(
            create_appointment_payload(care_team_id, patient_id, room_id, **overrides),
            FRONT,
        )
    )


def create_no_show_appointment(team, patient_id, room_id, sweep_utc, **overrides):
    """Create a SCHEDULED appointment, then advance the clock so the nightly
    sweep marks it COMPLETED_NO_SHOW and recomputes strikes. Returns the
    appointment as seen after the sweep."""
    appt = create_appointment(team["id"], patient_id, room_id, **overrides)
    set_clock(sweep_utc)
    return get_success_data(api_client.get_appointment(appt["id"], FRONT))


def create_checked_in_appointment(team, patient_id, room_id, start_utc, checkin_clock, **overrides):
    """Create an appointment at start_utc, move the clock inside the check-in
    window, and check in. Returns the CHECKED_IN appointment."""
    appt = create_appointment(team["id"], patient_id, room_id, start_utc=start_utc, **overrides)
    set_clock(checkin_clock)
    return get_success_data(api_client.check_in_appointment(appt["id"], FRONT))


def create_completed_appointment(team, patient_id, room_id, start_utc, checkin_clock, **overrides):
    """Create + check-in + complete (completed by the team's own lead).
    Returns the COMPLETED appointment."""
    appt = create_checked_in_appointment(
        team, patient_id, room_id, start_utc, checkin_clock, **overrides
    )
    return get_success_data(
        api_client.complete_appointment(appt["id"], make_care_team_lead_headers(team["id"]))
    )


def create_dispatched_ride(appointment_id, vehicle_id, patient_id=None):
    """Create a ride request for the appointment and dispatch it to the vehicle.
    Returns (ride, dispatched_ride)."""
    ride = get_success_data(api_client.create_ride_request(appointment_id, DISP))
    dispatched = get_success_data(
        api_client.dispatch_ride(ride["id"], {"vehicle_id": vehicle_id}, DISP)
    )
    return ride, dispatched


def create_en_route_ride(appointment_id, vehicle_id, pickup_clock):
    """Create + dispatch + start pickup (clock inside the pickup window).
    Returns the EN_ROUTE ride."""
    _, dispatched = create_dispatched_ride(appointment_id, vehicle_id)
    set_clock(pickup_clock)
    return get_success_data(api_client.start_pickup_ride(dispatched["id"], DISP))


# ─── Tier 4: Threshold / accumulation targeting ─────────────────────────────

def create_saturated_center(cap=2):
    """Open center whose single team has panel_cap == cap, with cap ACTIVE
    attributions (the last activation trips the saturation cascade) and two
    additional PENDING attributions that the cascade flips to WAITLISTED.
    Returns dict with center/team/room/plan, active attributions list, and
    waitlisted attributions list."""
    center, team, room = create_open_center()
    get_success_data(
        api_client.patch_care_team(team["id"], {"panel_cap": cap}, NET)
    )
    plan = create_health_plan()
    patients = [create_patient(full_name=f"Patient {i}") for i in range(cap + 2)]
    attrs = [
        create_attribution(p["id"], plan["id"], team["id"])
        for p in patients
    ]
    active = [activate_attribution(a["id"]) for a in attrs[:cap]]
    waitlisted = [
        get_success_data(api_client.get_attribution(a["id"], ENR)) for a in attrs[cap:]
    ]
    return {
        "center": get_success_data(api_client.get_center(center["id"], NET)),
        "team": get_success_data(api_client.get_care_team(team["id"], NET)),
        "room": room,
        "plan": plan,
        "patients": patients,
        "active": active,
        "waitlisted": waitlisted,
    }


def give_patient_no_show_strikes(center, team, room, patient_id, count):
    """Accumulate `count` COMPLETED_NO_SHOW appointments for the patient by
    scheduling appointments and sweeping past their end times. Returns the
    patient as seen after the last sweep."""
    for i in range(count):
        day = 10 + i
        start_utc = f"2026-09-{day:02d}T14:00:00Z"
        sweep_utc = f"2026-09-{day:02d}T15:00:00Z"
        create_no_show_appointment(
            team, patient_id, room["id"],
            sweep_utc=sweep_utc,
            start_utc=start_utc, duration_minutes=40,
        )
    return get_success_data(api_client.get_patient(patient_id, ENR))


# ─── Tier 5: Settlement close / finalization ────────────────────────────────

def create_open_settlement(center_id, period_month):
    return get_success_data(
        api_client.create_monthly_settlement(
            create_monthly_settlement_payload(center_id, period_month=period_month), FA
        )
    )


def setup_provisional_settlement(period_month="2026-09", clock_after="2026-10-01T00:00:00Z"):
    """Open center (opened 2026-01-01) + OPEN settlement for period_month, clock
    moved past the period, settlement closed provisionally.
    Returns (center, team, room, settlement)."""
    center, team, room = create_open_center()
    settlement = create_open_settlement(center["id"], period_month)
    set_clock(clock_after)
    center_now = get_success_data(api_client.get_center(center["id"], NET))
    settlement = get_success_data(
        api_client.close_provisional_settlement(
            settlement["id"], {"expected_center_version": center_now["version"]}, FA
        )
    )
    return center, team, room, settlement


def setup_finalized_center(period_month="2026-08", clock_after="2026-09-15T00:00:00Z"):
    """Open center with a FINALIZED settlement for period_month (no claims).
    Returns (center, team, room, settlement)."""
    center, team, room = create_open_center()
    settlement = create_open_settlement(center["id"], period_month)
    set_clock(clock_after)
    center_now = get_success_data(api_client.get_center(center["id"], NET))
    get_success_data(
        api_client.close_provisional_settlement(
            settlement["id"], {"expected_center_version": center_now["version"]}, FA
        )
    )
    settlement = get_success_data(api_client.finalize_settlement(settlement["id"], FC))
    center = get_success_data(api_client.get_center(center["id"], NET))
    return center, team, room, settlement


def adjudicate_claim(claim_id, adjudicated_amount_cents):
    return get_success_data(
        api_client.adjudicate_cost_claim(
            claim_id, {"adjudicated_amount_cents": adjudicated_amount_cents}, ADJ
        )
    )
