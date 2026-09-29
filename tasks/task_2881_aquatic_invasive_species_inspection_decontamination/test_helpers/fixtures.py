"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because each test starts against an empty program database.
Setup calls go through the lenient success reader so a broken precondition
surfaces as a setup failure rather than as a confusing assertion.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_UTC, SEASON_CLOSES_AT, SEASON_OPENS_AT
from .factories import (
    acknowledgement_payload,
    breach_report_payload,
    campaign_evaluation_payload,
    campaign_payload,
    campaign_status_payload,
    clock_payload,
    decon_order_payload,
    detection_report_payload,
    disposition_payload,
    dry_verification_payload,
    enforcement_payload,
    inspection_record_payload,
    inspector_payload,
    inspector_status_payload,
    quarantine_order_payload,
    reciprocity_agreement_payload,
    reciprocity_status_payload,
    release_decision_payload,
    release_request_payload,
    screening_payload,
    station_hours_payload,
    station_payload,
    station_status_payload,
    submission_payload,
    training_record_payload,
    treatment_payload,
    water_body_payload,
    watercraft_payload,
)
from .test_users import (
    ENFORCEMENT_OFFICER,
    PROGRAM_ADMIN,
    STATE_DATA_STEWARD,
    TRAINING_OFFICER,
    make_decon_technician_headers,
    make_inspector_headers,
    make_release_verifier_headers,
)


# ---------------------------------------------------------------------------
# Tier 0: single-call primitives
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock to an explicit instant."""
    return get_success_data(api_client.set_clock(clock_payload(to_iso8601), PROGRAM_ADMIN))


def create_water_body(**overrides) -> dict:
    return get_success_data(
        api_client.create_water_body(water_body_payload(**overrides), PROGRAM_ADMIN)
    )


def create_station(**overrides) -> dict:
    return get_success_data(
        api_client.create_station(station_payload(**overrides), PROGRAM_ADMIN)
    )


def add_station_hours(station_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_station_hours(
            station_id, station_hours_payload(**overrides), PROGRAM_ADMIN
        )
    )


def move_station(station_id, target_status) -> dict:
    return get_success_data(
        api_client.set_station_status(
            station_id, station_status_payload(target_status), PROGRAM_ADMIN
        )
    )


def log_training(inspector_id, hours, passed=True, **overrides) -> dict:
    return get_success_data(
        api_client.create_training_record(
            inspector_id, training_record_payload(hours, passed, **overrides),
            TRAINING_OFFICER,
        )
    )


def move_inspector(inspector_id, target_status) -> dict:
    return get_success_data(
        api_client.set_inspector_status(
            inspector_id, inspector_status_payload(target_status), PROGRAM_ADMIN
        )
    )


def register_watercraft(**overrides) -> dict:
    return get_success_data(
        api_client.create_watercraft(watercraft_payload(**overrides), PROGRAM_ADMIN)
    )


def create_reciprocity_agreement(**overrides) -> dict:
    return get_success_data(
        api_client.create_reciprocity_agreement(
            reciprocity_agreement_payload(**overrides), PROGRAM_ADMIN
        )
    )


def move_reciprocity_agreement(agreement_id, target_status) -> dict:
    return get_success_data(
        api_client.set_reciprocity_agreement_status(
            agreement_id, reciprocity_status_payload(target_status), PROGRAM_ADMIN
        )
    )


# ---------------------------------------------------------------------------
# Read helpers — observation of side effects
# ---------------------------------------------------------------------------
def fetch_water_body(water_body_id) -> dict:
    return get_success_data(api_client.get_water_body(water_body_id, PROGRAM_ADMIN))


def fetch_station(station_id) -> dict:
    return get_success_data(api_client.get_station(station_id, PROGRAM_ADMIN))


def fetch_station_hours(station_id) -> list:
    body = api_client.list_station_hours(station_id, PROGRAM_ADMIN, {"limit": 100}).json()
    return body["data"]


def fetch_inspector(inspector_id) -> dict:
    return get_success_data(api_client.get_inspector(inspector_id, PROGRAM_ADMIN))


def fetch_watercraft(watercraft_id) -> dict:
    return get_success_data(api_client.get_watercraft(watercraft_id, PROGRAM_ADMIN))


def fetch_record(record_id) -> dict:
    return get_success_data(api_client.get_inspection_record(record_id, PROGRAM_ADMIN))


def fetch_decon_order(order_id) -> dict:
    return get_success_data(api_client.get_decon_order(order_id, PROGRAM_ADMIN))


def fetch_quarantine_order(order_id) -> dict:
    return get_success_data(api_client.get_quarantine_order(order_id, PROGRAM_ADMIN))


def fetch_detection_report(report_id) -> dict:
    return get_success_data(api_client.get_detection_report(report_id, PROGRAM_ADMIN))


def fetch_campaign(campaign_id) -> dict:
    return get_success_data(api_client.get_campaign(campaign_id, PROGRAM_ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: state progression
# ---------------------------------------------------------------------------
def create_and_open_station(water_body_id=None, opens_at=SEASON_OPENS_AT,
                            closes_at=SEASON_CLOSES_AT, staffing_level=None,
                            **overrides) -> dict:
    """Site a station, declare one operating window, then open it for the season."""
    payload = dict(overrides)
    if water_body_id is not None:
        payload.setdefault("station_type", "WATERBODY_ACCESS")
        payload["water_body_id"] = water_body_id
    station = create_station(**payload)
    hours_overrides = {"opens_at": opens_at, "closes_at": closes_at}
    if staffing_level is not None:
        hours_overrides["staffing_level"] = staffing_level
    add_station_hours(station["id"], **hours_overrides)
    return move_station(station["id"], "OPEN")


def enroll_inspector(station_id, credited_hours=None, decon_endorsement=False,
                     completed_at=None, **overrides) -> dict:
    """Enroll an inspector and, when hours are supplied, credit them at once.

    Eight or more credited hours promote the trainee out of PROBATIONARY, so
    the returned inspector is ACTIVE whenever `credited_hours` reaches eight.
    """
    payload = dict(overrides)
    if decon_endorsement:
        payload["decon_endorsement"] = True
    inspector = get_success_data(
        api_client.create_inspector(inspector_payload(station_id, **payload), PROGRAM_ADMIN)
    )
    if credited_hours:
        training_overrides = {}
        if completed_at is not None:
            training_overrides["completed_at"] = completed_at
        log_training(inspector["id"], credited_hours, True, **training_overrides)
        inspector = fetch_inspector(inspector["id"])
    return inspector


# ---------------------------------------------------------------------------
# Tier 2: the program skeleton every scenario shares
# ---------------------------------------------------------------------------
def setup_program(clock=DEFAULT_CLOCK_UTC, risk_tier="HIGH",
                  infestation_status="CLEAN", state_code="MT",
                  decon_bay_count=1, hot_water_capable=True,
                  seal_stock_initial_count=2, mandatory_inspection=None,
                  opens_at=SEASON_OPENS_AT, closes_at=SEASON_CLOSES_AT,
                  staffing_level=None, open_station=True,
                  inspector_a_hours=8, inspector_b_hours=40,
                  inspector_c_hours=40) -> dict:
    """One water body, one station with one operating window, three inspectors.

    The three inspectors are the recurring cast: a field inspector credited
    with `inspector_a_hours`, a decon-endorsed technician credited with
    `inspector_b_hours`, and an independent verifier credited with
    `inspector_c_hours`.  Returns a mutable context dictionary.
    """
    set_clock(clock)
    water_body = create_water_body(
        state_code=state_code, risk_tier=risk_tier, infestation_status=infestation_status
    )
    station_overrides = {
        "station_type": "WATERBODY_ACCESS",
        "water_body_id": water_body["id"],
        "decon_bay_count": decon_bay_count,
        "hot_water_capable": hot_water_capable,
        "seal_stock_initial_count": seal_stock_initial_count,
    }
    if mandatory_inspection is not None:
        station_overrides["mandatory_inspection"] = mandatory_inspection
    station = create_station(**station_overrides)
    hours_overrides = {"opens_at": opens_at, "closes_at": closes_at}
    if staffing_level is not None:
        hours_overrides["staffing_level"] = staffing_level
    hours = add_station_hours(station["id"], **hours_overrides)
    inspector_a = enroll_inspector(
        station["id"], credited_hours=inspector_a_hours, full_name="Ada Field",
        completed_at=clock,
    )
    inspector_b = enroll_inspector(
        station["id"], credited_hours=inspector_b_hours, decon_endorsement=True,
        full_name="Bo Tech", completed_at=clock,
    )
    inspector_c = enroll_inspector(
        station["id"], credited_hours=inspector_c_hours, full_name="Cy Verify",
        completed_at=clock,
    )
    if open_station:
        station = move_station(station["id"], "OPEN")
    else:
        station = fetch_station(station["id"])
    return {
        "clock": clock,
        "water_body": water_body,
        "station": station,
        "hours": hours,
        "inspector_a": inspector_a,
        "inspector_b": inspector_b,
        "inspector_c": inspector_c,
        "inspector_headers": make_inspector_headers(inspector_a["id"]),
        "technician_headers": make_decon_technician_headers(inspector_b["id"]),
        "verifier_headers": make_release_verifier_headers(inspector_c["id"]),
    }


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts, one per declared operation
# ---------------------------------------------------------------------------
def open_record(station_id, watercraft_id, arrived_at, inspector_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_inspection_record(
            inspection_record_payload(station_id, watercraft_id, arrived_at, **overrides),
            make_inspector_headers(inspector_id),
        )
    )


def screen_record(record_id, inspector_id, expected_watercraft_version,
                  residual_water_present=False, **fields) -> dict:
    return get_success_data(
        api_client.screen_inspection_record(
            record_id,
            screening_payload(expected_watercraft_version, residual_water_present, **fields),
            make_inspector_headers(inspector_id),
        )
    )


def dispose_record(record_id, inspector_id, disposition, **overrides) -> dict:
    return get_success_data(
        api_client.dispose_inspection_record(
            record_id, disposition_payload(disposition, **overrides),
            make_inspector_headers(inspector_id),
        )
    )


def enforce_record(record_id, action, **overrides) -> dict:
    return get_success_data(
        api_client.enforce_inspection_record(
            record_id, enforcement_payload(action, **overrides), ENFORCEMENT_OFFICER
        )
    )


def order_decon(record_id, inspector_id, expected_inspection_record_version) -> dict:
    return get_success_data(
        api_client.create_decon_order(
            decon_order_payload(record_id, expected_inspection_record_version),
            make_inspector_headers(inspector_id),
        )
    )


def treat_order(order_id, technician_id, water_temp_f=140, pressure_psi=3000,
                dwell_seconds=120) -> dict:
    return get_success_data(
        api_client.treat_decon_order(
            order_id, treatment_payload(water_temp_f, pressure_psi, dwell_seconds),
            make_decon_technician_headers(technician_id),
        )
    )


def verify_dry(order_id, verifier_id, outcome) -> dict:
    return get_success_data(
        api_client.verify_decon_dry_time(
            order_id, dry_verification_payload(outcome),
            make_release_verifier_headers(verifier_id),
        )
    )


def issue_quarantine(record_id, inspector_id, seal_number, **overrides) -> dict:
    return get_success_data(
        api_client.create_quarantine_order(
            quarantine_order_payload(record_id, seal_number, **overrides),
            make_inspector_headers(inspector_id),
        )
    )


def request_release(order_id, inspector_id) -> dict:
    return get_success_data(
        api_client.request_quarantine_release(
            order_id, release_request_payload(), make_inspector_headers(inspector_id)
        )
    )


def decide_release(order_id, verifier_id, outcome) -> dict:
    return get_success_data(
        api_client.decide_quarantine_release(
            order_id, release_decision_payload(outcome),
            make_release_verifier_headers(verifier_id),
        )
    )


def report_breach(order_id, headers=None) -> dict:
    return get_success_data(
        api_client.report_quarantine_breach(
            order_id, breach_report_payload(), headers or ENFORCEMENT_OFFICER
        )
    )


def draft_detection_report(record_id, inspector_id, detection_class="LIVE_ORGANISM",
                           **overrides) -> dict:
    return get_success_data(
        api_client.create_detection_report(
            detection_report_payload(record_id, detection_class, **overrides),
            make_inspector_headers(inspector_id),
        )
    )


def submit_detection_report(report_id, inspector_id) -> dict:
    return get_success_data(
        api_client.submit_detection_report(
            report_id, submission_payload(), make_inspector_headers(inspector_id)
        )
    )


def acknowledge_detection_report(report_id, verdict, **overrides) -> dict:
    return get_success_data(
        api_client.acknowledge_detection_report(
            report_id, acknowledgement_payload(verdict, **overrides), STATE_DATA_STEWARD
        )
    )


def plan_campaign(target_water_body_id, start_at, end_at, budget_cents=100000,
                  **overrides) -> dict:
    return get_success_data(
        api_client.create_campaign(
            campaign_payload(target_water_body_id, start_at, end_at, budget_cents,
                             **overrides),
            PROGRAM_ADMIN,
        )
    )


def move_campaign(campaign_id, target_status) -> dict:
    return get_success_data(
        api_client.set_campaign_status(
            campaign_id, campaign_status_payload(target_status), PROGRAM_ADMIN
        )
    )


def run_campaign_evaluation(campaign_id, **overrides) -> dict:
    return get_success_data(
        api_client.evaluate_campaign(
            campaign_id, campaign_evaluation_payload(**overrides), PROGRAM_ADMIN
        )
    )


# ---------------------------------------------------------------------------
# Tier 4: inspections carried to a targeted screening outcome
# ---------------------------------------------------------------------------
AUTO = "__auto__"


def add_watercraft(ctx, last_water_body_id=AUTO, **overrides) -> dict:
    """Register a vessel whose declared last water body defaults to the context's."""
    payload = dict(overrides)
    if last_water_body_id == AUTO:
        payload["last_water_body_id"] = ctx["water_body"]["id"]
    elif last_water_body_id is not None:
        payload["last_water_body_id"] = last_water_body_id
    return register_watercraft(**payload)


def setup_inspection(ctx=None, *, arrived_at="2026-08-05T09:00:00Z", screen_at=None,
                     vessel_type="OPEN_HULL", last_removed_at=None,
                     last_water_body_id=AUTO, prior_water_body_id=None,
                     residual_water_present=False, standing_water_ml=None,
                     presented_seal_number=None, presented_seal_state_code=None,
                     presented_seal_issued_at=None, screen=True, disposition=None,
                     inspector_id=None, watercraft=None, **program_kwargs) -> dict:
    """Build the program, register a vessel, open an inspection and screen it.

    `screen_at` moves the logical clock before the screening call, which is
    what separates the arrival basis of the risk score from its screening
    basis.  When `disposition` is supplied the screened record is disposed
    with it.  Returns the context extended with `watercraft` and `record`.
    """
    ctx = ctx or setup_program(**program_kwargs)
    inspector_id = inspector_id or ctx["inspector_a"]["id"]
    if watercraft is None:
        vessel_overrides = {"vessel_type": vessel_type}
        if last_removed_at is not None:
            vessel_overrides["last_removed_at"] = last_removed_at
        watercraft = add_watercraft(ctx, last_water_body_id, **vessel_overrides)
    ctx["watercraft"] = watercraft
    record = open_record(ctx["station"]["id"], watercraft["id"], arrived_at, inspector_id)
    ctx["record"] = record
    if screen:
        if screen_at is not None:
            set_clock(screen_at)
            ctx["clock"] = screen_at
        fields = {}
        if standing_water_ml is not None:
            fields["standing_water_ml"] = standing_water_ml
        if prior_water_body_id is not None:
            fields["prior_water_body_id"] = prior_water_body_id
        if presented_seal_number is not None:
            fields["presented_seal_number"] = presented_seal_number
        if presented_seal_state_code is not None:
            fields["presented_seal_state_code"] = presented_seal_state_code
        if presented_seal_issued_at is not None:
            fields["presented_seal_issued_at"] = presented_seal_issued_at
        current_version = fetch_watercraft(watercraft["id"])["version"]
        ctx["record"] = screen_record(
            record["id"], inspector_id, current_version,
            residual_water_present=residual_water_present, **fields
        )
    if disposition is not None:
        ctx["record"] = dispose_record(ctx["record"]["id"], inspector_id, disposition)
    ctx["watercraft"] = fetch_watercraft(watercraft["id"])
    return ctx


def setup_decon_required(ctx=None, **kwargs) -> dict:
    """Screen a vessel into a decon-mandatory band and dispose it DECON_REQUIRED."""
    kwargs.setdefault("residual_water_present", True)
    kwargs.setdefault("standing_water_ml", 500)
    kwargs["disposition"] = "DECON"
    return setup_inspection(ctx, **kwargs)


def setup_decon_order(ctx=None, **kwargs) -> dict:
    """Carry a record to DECON_REQUIRED and open a decontamination order."""
    ctx = setup_decon_required(ctx, **kwargs)
    inspector_id = ctx["inspector_a"]["id"]
    ctx["decon_order"] = order_decon(
        ctx["record"]["id"], inspector_id, ctx["record"]["version"]
    )
    ctx["record"] = fetch_record(ctx["record"]["id"])
    return ctx


def setup_treated_order(ctx=None, *, treat_at="2026-08-05T09:00:00Z",
                        water_temp_f=140, pressure_psi=3000, dwell_seconds=120,
                        **kwargs) -> dict:
    """Open a decontamination order and run one hot-water treatment on it."""
    ctx = setup_decon_order(ctx, **kwargs)
    set_clock(treat_at)
    ctx["clock"] = treat_at
    ctx["decon_order"] = treat_order(
        ctx["decon_order"]["id"], ctx["inspector_b"]["id"],
        water_temp_f, pressure_psi, dwell_seconds,
    )
    ctx["record"] = fetch_record(ctx["record"]["id"])
    ctx["station"] = fetch_station(ctx["station"]["id"])
    return ctx


def setup_quarantined_record(ctx=None, *, seal_number="MT-SEAL-0001", **kwargs) -> dict:
    """Screen a vessel into a quarantine-warranting posture and seal it."""
    kwargs.setdefault("residual_water_present", True)
    kwargs.setdefault("standing_water_ml", 550)
    kwargs.setdefault("infestation_status", "SUSPECT")
    kwargs.setdefault("disposition", "DECON")
    ctx = setup_inspection(ctx, **kwargs)
    ctx["quarantine_order"] = issue_quarantine(
        ctx["record"]["id"], ctx["inspector_a"]["id"], seal_number
    )
    ctx["station"] = fetch_station(ctx["station"]["id"])
    ctx["watercraft"] = fetch_watercraft(ctx["watercraft"]["id"])
    return ctx


def setup_release_requested(ctx=None, *, request_at="2026-08-10T09:00:00Z",
                            seal_number="MT-SEAL-0001", **kwargs) -> dict:
    """Seal a vessel, wait out the hold, and raise the release request."""
    ctx = setup_quarantined_record(ctx, seal_number=seal_number, **kwargs)
    set_clock(request_at)
    ctx["clock"] = request_at
    ctx["quarantine_order"] = request_release(
        ctx["quarantine_order"]["id"], ctx["inspector_a"]["id"]
    )
    return ctx


def setup_accepted_detection_report(ctx=None, *, species_code="DREISSENA",
                                    detection_class="LIVE_ORGANISM",
                                    ack_id="ACK-0001", **kwargs) -> dict:
    """Draft, submit and accept one detection report against the context record."""
    ctx = setup_inspection(ctx, **kwargs)
    report = draft_detection_report(
        ctx["record"]["id"], ctx["inspector_a"]["id"], detection_class,
        species_code=species_code,
    )
    submit_detection_report(report["id"], ctx["inspector_a"]["id"])
    ctx["detection_report"] = acknowledge_detection_report(
        report["id"], "ACCEPTED", state_db_ack_id=ack_id
    )
    ctx["water_body"] = fetch_water_body(ctx["water_body"]["id"])
    return ctx


def add_strike(ctx, *, registration_number=None, arrived_at="2026-08-05T09:00:00Z",
               watercraft=None) -> dict:
    """Record a refusal against a vessel, which refers it and adds one strike."""
    overrides = {}
    if registration_number is not None:
        overrides["registration_number"] = registration_number
    vessel = watercraft or add_watercraft(ctx, **overrides)
    record = open_record(
        ctx["station"]["id"], vessel["id"], arrived_at, ctx["inspector_a"]["id"]
    )
    version = fetch_watercraft(vessel["id"])["version"]
    screen_record(record["id"], ctx["inspector_a"]["id"], version,
                  residual_water_present=False)
    record = dispose_record(record["id"], ctx["inspector_a"]["id"], "REFUSE")
    return {"watercraft": fetch_watercraft(vessel["id"]), "record": record}


# ---------------------------------------------------------------------------
# Tier 5: multi-station and multi-window campaign scenarios
# ---------------------------------------------------------------------------
def add_candidate_station(ctx, name, target_status=None, water_body_id=AUTO,
                          **overrides) -> dict:
    """Site one more station on a water body and walk it to `target_status`."""
    payload = dict(overrides)
    payload["name"] = name
    payload["station_type"] = "WATERBODY_ACCESS"
    payload["water_body_id"] = (
        ctx["water_body"]["id"] if water_body_id == AUTO else water_body_id
    )
    station = create_station(**payload)
    if target_status in ("OPEN", "SUSPENDED"):
        add_station_hours(station["id"])
        station = move_station(station["id"], "OPEN")
        if target_status == "SUSPENDED":
            station = move_station(station["id"], "SUSPENDED")
    elif target_status == "CLOSED":
        station = move_station(station["id"], "CLOSED")
    return station


def add_site(ctx, key, *, risk_tier="LOW", infestation_status="CLEAN",
             station_name=None, **station_overrides) -> dict:
    """Add a second water body with its own open station and one active inspector."""
    water_body = create_water_body(
        risk_tier=risk_tier, infestation_status=infestation_status
    )
    overrides = dict(station_overrides)
    if station_name is not None:
        overrides["name"] = station_name
    station = create_and_open_station(water_body["id"], **overrides)
    inspector = enroll_inspector(
        station["id"], credited_hours=8, full_name=f"Site {key} Inspector",
        completed_at=ctx.get("clock", DEFAULT_CLOCK_UTC),
    )
    site = {"water_body": water_body, "station": station, "inspector": inspector}
    ctx[key] = site
    return site


def add_disposed_record(ctx, *, arrived_at, disposition, site=None,
                        residual_water_present=False, standing_water_ml=None,
                        registration_number=None) -> dict:
    """Register a fresh vessel and carry one inspection through to a disposition."""
    station = (site or ctx)["station"]
    inspector = (site or {}).get("inspector") or ctx["inspector_a"]
    water_body = (site or ctx)["water_body"]
    overrides = {"last_water_body_id": water_body["id"]}
    if registration_number is not None:
        overrides["registration_number"] = registration_number
    vessel = register_watercraft(**overrides)
    record = open_record(station["id"], vessel["id"], arrived_at, inspector["id"])
    fields = {}
    if standing_water_ml is not None:
        fields["standing_water_ml"] = standing_water_ml
    version = fetch_watercraft(vessel["id"])["version"]
    screen_record(record["id"], inspector["id"], version,
                  residual_water_present=residual_water_present, **fields)
    return dispose_record(record["id"], inspector["id"], disposition)


def setup_campaign_ready(ctx=None, *, station_names=("Alpha", "Bravo", "Charlie"),
                         station_statuses=None, budget_cents=100000,
                         start_at="2026-08-01T00:00:00Z", end_at="2026-09-01T00:00:00Z",
                         **program_kwargs) -> dict:
    """A water body with several candidate stations and one planned campaign."""
    ctx = ctx or setup_program(open_station=False, **program_kwargs)
    statuses = station_statuses or [None] * len(station_names)
    ctx["candidate_stations"] = [
        add_candidate_station(ctx, name, status)
        for name, status in zip(station_names, statuses)
    ]
    ctx["campaign"] = plan_campaign(
        ctx["water_body"]["id"], start_at, end_at, budget_cents
    )
    return ctx
