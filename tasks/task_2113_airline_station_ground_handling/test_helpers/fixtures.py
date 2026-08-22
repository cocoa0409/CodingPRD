"""Composite setup helpers — the multi-step preambles PRD workflows require.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only, and uses get_success_data() so a broken setup step surfaces as
a clear "Setup step failed" assertion rather than a confusing later failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    billing_period_transition_payload,
    bank_lifecycle_payload,
    create_agent_payload,
    create_agent_resource_payload,
    create_billing_line_payload,
    create_billing_period_payload,
    create_certification_payload,
    create_flight_bank_payload,
    create_gse_resource_payload,
    create_gse_unit_payload,
    create_incident_payload,
    create_station_payload,
    create_subcontractor_payload,
    create_turn_payload,
    gse_service_event_payload,
    incident_transition_payload,
    oversight_decision_payload,
    release_resource_payload,
    revoke_certification_payload,
    season_rollover_payload,
    set_clock_payload,
    staffing_transition_payload,
    station_lifecycle_payload,
    turn_lifecycle_payload,
    void_billing_line_payload,
)
from .test_users import (
    make_billing_controller_headers,
    make_contract_auditor_headers,
    make_duty_officer_headers,
    make_safety_officer_headers,
    make_station_manager_headers,
)

DEFAULT_CLOCK = TEST_DEFAULTS["CLOCK_BASE"]
AGENT_WINDOW = ("2026-04-10T05:50:00Z", "2026-04-10T06:30:00Z")
GSE_WINDOW = ("2026-04-10T05:55:00Z", "2026-04-10T06:25:00Z")


# ─── Logical clock ────────────────────────────────────────────────────────

def set_clock(current_utc, headers=None):
    """Move the server's logical clock to an explicit instant."""
    return get_success_data(api_client.set_current_utc(
        set_clock_payload(current_utc), headers or make_station_manager_headers()))


# ─── Reads ────────────────────────────────────────────────────────────────

def get_station(station_id, headers=None):
    return get_success_data(api_client.get_station(
        station_id, headers or make_station_manager_headers()))


def get_subcontractor(subcontractor_id, headers=None):
    return get_success_data(api_client.get_subcontractor(
        subcontractor_id, headers or make_station_manager_headers()))


def get_flight_bank(flight_bank_id, headers=None):
    return get_success_data(api_client.get_flight_bank(
        flight_bank_id, headers or make_duty_officer_headers()))


def get_turn(turn_id, headers=None):
    return get_success_data(api_client.get_turn(
        turn_id, headers or make_duty_officer_headers()))


def get_agent(agent_id, headers=None):
    return get_success_data(api_client.get_agent(
        agent_id, headers or make_station_manager_headers()))


def get_certification(certification_id, headers=None):
    return get_success_data(api_client.get_certification(
        certification_id, headers or make_station_manager_headers()))


def get_gse_unit(gse_unit_id, headers=None):
    return get_success_data(api_client.get_gse_unit(
        gse_unit_id, headers or make_station_manager_headers()))


def get_turn_resource(turn_resource_id, headers=None):
    return get_success_data(api_client.get_turn_resource(
        turn_resource_id, headers or make_duty_officer_headers()))


def get_incident(incident_id, headers=None):
    return get_success_data(api_client.get_incident(
        incident_id, headers or make_safety_officer_headers()))


def get_billing_period(billing_period_id, headers=None):
    return get_success_data(api_client.get_billing_period(
        billing_period_id, headers or make_billing_controller_headers()))


def get_billing_line(billing_line_id, headers=None):
    return get_success_data(api_client.get_billing_line(
        billing_line_id, headers or make_billing_controller_headers()))


# ─── Tier 1: single-record creation and lifecycle ─────────────────────────

def create_station(**overrides):
    return get_success_data(api_client.create_station(
        create_station_payload(**overrides), make_station_manager_headers()))


def drive_station(station_id, action, **payload_overrides):
    return get_success_data(api_client.station_lifecycle(
        station_id, station_lifecycle_payload(action, **payload_overrides),
        make_station_manager_headers()))


def open_station(station_id):
    return drive_station(station_id, "OPEN")


def suspend_station(station_id, reason="RUNWAY_CLOSURE"):
    return drive_station(station_id, "SUSPEND", reason=reason)


def resume_station(station_id):
    return drive_station(station_id, "RESUME")


def close_station(station_id):
    return drive_station(station_id, "CLOSE")


def roll_season(station_id, to_season_code, **overrides):
    return get_success_data(api_client.season_rollover(
        station_id, season_rollover_payload(to_season_code, **overrides),
        make_station_manager_headers()))


def create_open_station(clock=DEFAULT_CLOCK, **overrides):
    """Pin the logical clock, register a station and open it."""
    if clock is not None:
        set_clock(clock)
    station = create_station(**overrides)
    return open_station(station["id"])


def create_subcontractor(station_id, **overrides):
    return get_success_data(api_client.create_subcontractor(
        create_subcontractor_payload(station_id, **overrides),
        make_station_manager_headers()))


def decide_oversight(subcontractor_id, decision, **overrides):
    return get_success_data(api_client.oversight_decision(
        subcontractor_id, oversight_decision_payload(decision, **overrides),
        make_station_manager_headers()))


def create_approved_subcontractor(station_id, **overrides):
    subcontractor = create_subcontractor(station_id, **overrides)
    return decide_oversight(subcontractor["id"], "APPROVE")


def create_flight_bank(station_id, **overrides):
    return get_success_data(api_client.create_flight_bank(
        create_flight_bank_payload(station_id, **overrides),
        make_duty_officer_headers()))


def drive_bank(flight_bank_id, action, headers=None):
    headers = headers or (make_duty_officer_headers() if action == "PUBLISH"
                          else make_station_manager_headers())
    return get_success_data(api_client.flight_bank_lifecycle(
        flight_bank_id, bank_lifecycle_payload(action), headers))


def publish_bank(flight_bank_id):
    return drive_bank(flight_bank_id, "PUBLISH")


def lock_bank(flight_bank_id):
    return drive_bank(flight_bank_id, "LOCK")


def archive_bank(flight_bank_id):
    return drive_bank(flight_bank_id, "ARCHIVE")


def submit_staffing(flight_bank_id, user_id="duty-01", **overrides):
    return get_success_data(api_client.staffing_transition(
        flight_bank_id, staffing_transition_payload("SUBMIT", **overrides),
        make_duty_officer_headers(user_id)))


def approve_staffing(flight_bank_id, user_id="sm-01"):
    return get_success_data(api_client.staffing_transition(
        flight_bank_id, staffing_transition_payload("APPROVE"),
        make_station_manager_headers(user_id)))


def reject_staffing(flight_bank_id, user_id="sm-01"):
    return get_success_data(api_client.staffing_transition(
        flight_bank_id, staffing_transition_payload("REJECT"),
        make_station_manager_headers(user_id)))


def revise_staffing(flight_bank_id, user_id="duty-01", **overrides):
    return get_success_data(api_client.staffing_transition(
        flight_bank_id, staffing_transition_payload("REVISE", **overrides),
        make_duty_officer_headers(user_id)))


def publish_and_approve_staffing(flight_bank_id, manager_user_id="sm-01"):
    """PUBLISH the bank, then walk its staffing plan DRAFT → SUBMITTED → APPROVED."""
    publish_bank(flight_bank_id)
    submit_staffing(flight_bank_id)
    return approve_staffing(flight_bank_id, manager_user_id)


def create_turn(station_id, flight_bank_id, **overrides):
    return get_success_data(api_client.create_turn(
        create_turn_payload(station_id, flight_bank_id, **overrides),
        make_duty_officer_headers()))


def start_turn(turn_id, actual_in="2026-04-10T06:00:00Z"):
    return get_success_data(api_client.turn_lifecycle(
        turn_id, turn_lifecycle_payload("START", actual_in=actual_in),
        make_duty_officer_headers()))


def complete_turn(turn_id, actual_out, delay_code="NONE"):
    return get_success_data(api_client.turn_lifecycle(
        turn_id,
        turn_lifecycle_payload("COMPLETE", actual_out=actual_out,
                               delay_code=delay_code),
        make_duty_officer_headers()))


def cancel_turn(turn_id, reason="SLOT_WITHDRAWN"):
    return get_success_data(api_client.turn_lifecycle(
        turn_id, turn_lifecycle_payload("CANCEL", reason=reason),
        make_duty_officer_headers()))


def create_agent(station_id, headers=None, **overrides):
    return get_success_data(api_client.create_agent(
        create_agent_payload(station_id, **overrides),
        headers or make_station_manager_headers()))


def issue_certification(agent_id, station_id, headers=None, **overrides):
    return get_success_data(api_client.create_certification(
        create_certification_payload(agent_id, station_id, **overrides),
        headers or make_station_manager_headers()))


def revoke_certification(certification_id, reason="TRAINING_AUDIT_FAILURE",
                         user_id="safety-01"):
    return get_success_data(api_client.revoke_certification(
        certification_id, revoke_certification_payload(reason),
        make_safety_officer_headers(user_id)))


def create_certified_agent(station_id, cert_types=("RAMP_SAFETY",),
                           issued_at=TEST_DEFAULTS["CERT_ISSUED_AT"],
                           expires_at=TEST_DEFAULTS["CERT_EXPIRES_AT"],
                           **agent_overrides):
    """Register an agent and issue each requested endorsement at its station."""
    agent = create_agent(station_id, **agent_overrides)
    for cert_type in cert_types:
        issue_certification(agent["id"], station_id, cert_type=cert_type,
                            issued_at=issued_at, expires_at=expires_at)
    return agent


def create_gse_unit(station_id, **overrides):
    return get_success_data(api_client.create_gse_unit(
        create_gse_unit_payload(station_id, **overrides),
        make_station_manager_headers()))


def schedule_service_hold(gse_unit_id, hold_start, hold_end, headers=None):
    return get_success_data(api_client.gse_service_event(
        gse_unit_id,
        gse_service_event_payload("HOLD_SCHEDULED", hold_start=hold_start,
                                  hold_end=hold_end),
        headers or make_station_manager_headers()))


def complete_service(gse_unit_id, headers=None):
    return get_success_data(api_client.gse_service_event(
        gse_unit_id, gse_service_event_payload("SERVICE_COMPLETED"),
        headers or make_safety_officer_headers()))


# ─── Tier 2: occupations (each re-reads the turn's live version) ───────────

def add_agent_occupation(turn_id, agent_id, window_start=AGENT_WINDOW[0],
                         window_end=AGENT_WINDOW[1], role_on_turn="RAMP"):
    """Commit an agent to a turnaround, proving the client's view is current."""
    turn = get_turn(turn_id)
    return get_success_data(api_client.create_turn_resource(
        create_agent_resource_payload(
            turn_id, agent_id, turn["version"], role_on_turn=role_on_turn,
            window_start=window_start, window_end=window_end),
        make_duty_officer_headers()))


def add_gse_occupation(turn_id, gse_unit_id=None, gse_type=None,
                       window_start=GSE_WINDOW[0], window_end=GSE_WINDOW[1]):
    """Commit a named unit — or ask the server to select one — to a turnaround."""
    turn = get_turn(turn_id)
    return get_success_data(api_client.create_turn_resource(
        create_gse_resource_payload(
            turn_id, turn["version"], gse_unit_id=gse_unit_id, gse_type=gse_type,
            window_start=window_start, window_end=window_end),
        make_duty_officer_headers()))


def release_occupation(turn_resource_id, reason="TUG_REALLOCATED"):
    return get_success_data(api_client.release_turn_resource(
        turn_resource_id, release_resource_payload(reason=reason),
        make_duty_officer_headers()))


# ─── Tier 2: incidents ────────────────────────────────────────────────────

def report_incident(station_id, user_id="duty-01", role="DutyOfficer", **overrides):
    headers = (make_safety_officer_headers(user_id) if role == "SafetyOfficer"
               else make_duty_officer_headers(user_id))
    return get_success_data(api_client.create_incident(
        create_incident_payload(station_id, **overrides), headers))


def drive_incident(incident_id, action, user_id="safety-01", **overrides):
    return get_success_data(api_client.incident_transition(
        incident_id, incident_transition_payload(action, **overrides),
        make_safety_officer_headers(user_id)))


def investigate_incident(incident_id, user_id="safety-01"):
    return drive_incident(incident_id, "INVESTIGATE", user_id=user_id)


def issue_findings(incident_id, liability_party="HANDLER",
                   root_cause_code="SOP_DEVIATION", user_id="safety-01",
                   **overrides):
    return drive_incident(incident_id, "ISSUE_FINDINGS", user_id=user_id,
                          root_cause_code=root_cause_code,
                          liability_party=liability_party, **overrides)


def close_incident(incident_id, user_id="safety-02"):
    return drive_incident(incident_id, "CLOSE", user_id=user_id)


def reopen_incident(incident_id, user_id="safety-02", **overrides):
    return drive_incident(incident_id, "REOPEN", user_id=user_id, **overrides)


def close_out_incident(incident_id, liability_party="HANDLER",
                       root_cause_code="SOP_DEVIATION", **findings_overrides):
    """Walk REPORTED → UNDER_INVESTIGATION → FINDINGS_ISSUED → CLOSED."""
    investigate_incident(incident_id, user_id="safety-01")
    issue_findings(incident_id, liability_party=liability_party,
                   root_cause_code=root_cause_code, user_id="safety-01",
                   **findings_overrides)
    return close_incident(incident_id, user_id="safety-02")


# ─── Tier 2: billing ──────────────────────────────────────────────────────

def create_billing_period(station_id, **overrides):
    return get_success_data(api_client.create_billing_period(
        create_billing_period_payload(station_id, **overrides),
        make_billing_controller_headers()))


def add_billing_line(billing_period_id, turn_id):
    """Accrue a charge, proving the client has seen the period's current version."""
    period = get_billing_period(billing_period_id)
    return get_success_data(api_client.create_billing_line(
        create_billing_line_payload(billing_period_id, turn_id, period["version"]),
        make_billing_controller_headers()))


def void_billing_line(billing_line_id, reason="ACCRUED_TO_WRONG_PERIOD"):
    return get_success_data(api_client.void_billing_line(
        billing_line_id, void_billing_line_payload(reason),
        make_billing_controller_headers()))


def finalize_period(billing_period_id, user_id="bc-01"):
    return get_success_data(api_client.billing_period_transition(
        billing_period_id, billing_period_transition_payload("FINALIZE"),
        make_billing_controller_headers(user_id)))


def approve_period(billing_period_id, user_id="ca-01", **overrides):
    return get_success_data(api_client.billing_period_transition(
        billing_period_id, billing_period_transition_payload("APPROVE", **overrides),
        make_contract_auditor_headers(user_id)))


def reject_period(billing_period_id, user_id="ca-01", **overrides):
    return get_success_data(api_client.billing_period_transition(
        billing_period_id, billing_period_transition_payload("REJECT", **overrides),
        make_contract_auditor_headers(user_id)))


# ─── Tier 3: composite scenarios ──────────────────────────────────────────

def setup_station_with_bank(clock=DEFAULT_CLOCK, station_overrides=None,
                            bank_overrides=None):
    """Pinned clock → OPEN station → DRAFT flight bank. Returns (station, bank)."""
    station = create_open_station(clock=clock, **(station_overrides or {}))
    bank = create_flight_bank(station["id"], **(bank_overrides or {}))
    return station, bank


def setup_turn_scenario(clock=DEFAULT_CLOCK, station_overrides=None,
                        bank_overrides=None, turn_overrides=None,
                        with_agent=True, agent_cert_types=("RAMP_SAFETY",),
                        agent_overrides=None, with_gse=True,
                        gse_overrides=None, approve_plan=False,
                        subcontracted=False):
    """OPEN station + bank + one SCHEDULED turn, plus the workforce it needs.

    Returns a dict with the station, bank, turn and (when requested) the
    certified agent, the equipment unit and the employing subcontractor.
    """
    station, bank = setup_station_with_bank(clock, station_overrides, bank_overrides)
    turn = create_turn(station["id"], bank["id"], **(turn_overrides or {}))

    scenario = {"station": station, "bank": bank, "turn": turn,
                "agent": None, "gse": None, "subcontractor": None}

    if subcontracted:
        scenario["subcontractor"] = create_approved_subcontractor(station["id"])

    if with_agent:
        agent_kwargs = dict(agent_overrides or {})
        if subcontracted:
            agent_kwargs.setdefault("employee_code", "E010")
            agent_kwargs.setdefault("full_name", "Cleo Marin")
            agent_kwargs["subcontractor_id"] = scenario["subcontractor"]["id"]
        scenario["agent"] = create_certified_agent(
            station["id"], cert_types=agent_cert_types, **agent_kwargs)

    if with_gse:
        scenario["gse"] = create_gse_unit(station["id"], **(gse_overrides or {}))

    if approve_plan:
        publish_and_approve_staffing(bank["id"])
        scenario["bank"] = get_flight_bank(bank["id"])

    return scenario


def setup_resourced_turn(agent_window=AGENT_WINDOW, gse_window=GSE_WINDOW,
                         role_on_turn="RAMP", **scenario_kwargs):
    """A turn covered by one agent occupation and one equipment occupation.

    Returns the scenario dict extended with agent_resource and gse_resource.
    """
    scenario = setup_turn_scenario(**scenario_kwargs)
    scenario["agent_resource"] = add_agent_occupation(
        scenario["turn"]["id"], scenario["agent"]["id"],
        window_start=agent_window[0], window_end=agent_window[1],
        role_on_turn=role_on_turn)
    scenario["gse_resource"] = add_gse_occupation(
        scenario["turn"]["id"], gse_unit_id=scenario["gse"]["id"],
        window_start=gse_window[0], window_end=gse_window[1])
    scenario["turn"] = get_turn(scenario["turn"]["id"])
    return scenario


def setup_completed_turn(actual_in="2026-04-10T06:00:00Z",
                         actual_out="2026-04-10T06:20:00Z",
                         delay_code="NONE", **resourced_kwargs):
    """Drive a fully resourced turn through START and COMPLETE."""
    resourced_kwargs.setdefault("approve_plan", True)
    scenario = setup_resourced_turn(**resourced_kwargs)
    start_turn(scenario["turn"]["id"], actual_in=actual_in)
    scenario["turn"] = complete_turn(scenario["turn"]["id"], actual_out=actual_out,
                                     delay_code=delay_code)
    return scenario


def setup_period_with_line(station_id, turn_id, period_overrides=None):
    """An OPEN billing period carrying one PROVISIONAL line for the turn."""
    period = create_billing_period(station_id, **(period_overrides or {}))
    line = add_billing_line(period["id"], turn_id)
    return get_billing_period(period["id"]), line
