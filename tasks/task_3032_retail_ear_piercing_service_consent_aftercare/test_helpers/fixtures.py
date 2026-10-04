"""Composite setup helpers.

Most testable claims require the system to already be in a specific state,
which takes a chain of API calls. These helpers encapsulate those chains so
tests focus on the behaviour under assertion.

Every helper builds its preconditions from scratch: the harness restarts the
server before each individual test, so each test begins against an empty
database. Setup calls use the lenient ``get_success_data()`` validator so a
broken precondition surfaces as a clear "setup failed" error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK, TEST_DEFAULTS
from .factories import (
    create_appointment_payload,
    create_cartridge_lot_payload,
    create_certification_payload,
    create_consent_payload,
    create_customer_payload,
    create_healing_assessment_payload,
    create_healing_outcome_payload,
    create_incident_payload,
    create_jurisdiction_payload,
    create_piercer_payload,
    create_screening_payload,
    create_session_payload,
    create_sterilization_cycle_payload,
    create_store_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_piercer_headers,
)

INTAKE = TEST_USERS["intake_associate_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
TECHNICIAN = TEST_USERS["sterilization_technician_headers"]
READER = TEST_USERS["any_authenticated_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


# ─── Tier 1: primitives and state progression ──────────────────────────────

def set_clock(instant: str = DEFAULT_CLOCK):
    """Set the evaluator-controlled logical clock."""
    return get_success_data(api_client.set_clock(instant, COMPLIANCE))


def create_jurisdiction(**overrides) -> dict:
    """Create a jurisdiction profile with the Illinois defaults."""
    return get_success_data(
        api_client.create_jurisdiction(create_jurisdiction_payload(**overrides), COMPLIANCE)
    )


def create_store(jurisdiction_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_store(create_store_payload(jurisdiction_id, **overrides), COMPLIANCE)
    )


def create_piercer(store_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_piercer(create_piercer_payload(store_id, **overrides), MANAGER)
    )


def certify(piercer_id: str, **overrides) -> dict:
    """Issue a certification against a piercer, reading its version first."""
    piercer = get_success_data(api_client.get_piercer(piercer_id, READER))
    return get_success_data(
        api_client.create_certification(
            create_certification_payload(piercer_id, piercer["version"], **overrides), COMPLIANCE
        )
    )


def create_customer(**overrides) -> dict:
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), INTAKE))


def create_minor_customer(**overrides) -> dict:
    payload = create_customer_payload(
        full_name="Young Client",
        date_of_birth="2015-01-01T00:00:00Z",
        guardian_name="Parent Client",
        guardian_contact="p@x.com",
    )
    payload.update(overrides)
    return get_success_data(api_client.create_customer(payload, INTAKE))


def create_consent(customer_id: str, jurisdiction_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_consent(
            create_consent_payload(customer_id, jurisdiction_id, **overrides), INTAKE
        )
    )


def verify_consent(consent_id: str) -> dict:
    return get_success_data(api_client.verify_consent(consent_id, INTAKE))


def activate_self_consent(customer_id: str, jurisdiction_id: str, **overrides) -> dict:
    """Capture a SELF consent and verify it into ACTIVE."""
    consent = create_consent(customer_id, jurisdiction_id, consent_type="SELF", **overrides)
    return verify_consent(consent["id"])


def create_appointment(store_id, customer_id, piercer_id, jurisdiction_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_appointment(
            create_appointment_payload(store_id, customer_id, piercer_id, jurisdiction_id, **overrides),
            INTAKE,
        )
    )


def confirm_appointment(appointment_id: str) -> dict:
    return get_success_data(api_client.confirm_appointment(appointment_id, INTAKE))


def check_in_appointment(appointment_id: str) -> dict:
    return get_success_data(api_client.check_in_appointment(appointment_id, INTAKE))


def check_in_at_slot(appointment_id: str, slot_start: str) -> dict:
    """Check an appointment in after advancing the logical clock into its window.

    PRD §3.3: check-in requires the clock to be at or after `slot_start_at`
    minus the 30-minute lead of `CHECK_IN_LEAD_MINUTES`, so a caller checking in
    an appointment whose slot has not yet begun must move the clock first. The
    instant chosen is the slot's own start, which is inside the window and still
    strictly before `slot_end_at`, so no automatic `NO_SHOW` fires.
    """
    api_client.set_clock(slot_start, COMPLIANCE)
    return check_in_appointment(appointment_id)


def screen_appointment(appointment_id: str, piercer_id: str, **overrides) -> dict:
    """Drive CHECKED_IN -> SCREENED via POST /appointments/{id}/screen (PRD §3.4).

    The `/screen` step moves the appointment to SCREENED and sets the
    screening's outcome "via the screening evaluator as part of the same step",
    so the returned appointment's own screening already carries a terminal
    outcome. Evaluating it again through `POST /screenings/{id}/evaluate` would
    be a second evaluation of a terminal screening, which PRD §3.4 refuses with
    `ERR_SCREENING_ALREADY_EVALUATED`. Returns the governing screening.
    """
    appointment = get_success_data(api_client.get_appointment(appointment_id, READER))
    get_success_data(
        api_client.screen_appointment(
            appointment_id,
            create_screening_payload(appointment_id, piercer_id, appointment["version"], **overrides),
            make_piercer_headers(piercer_id),
        )
    )
    rows = get_success_data(api_client.list_appointment_screenings(appointment_id, READER))
    rows = rows if isinstance(rows, list) else rows.get("data", rows)
    assert rows, f"no screening recorded against appointment {appointment_id}"
    return rows[-1]


def start_service(appointment_id: str, piercer_id: str) -> dict:
    return get_success_data(
        api_client.start_service(appointment_id, make_piercer_headers(piercer_id))
    )


def complete_appointment(appointment_id: str, piercer_id: str) -> dict:
    return get_success_data(
        api_client.complete_appointment(appointment_id, make_piercer_headers(piercer_id))
    )


def read_version(path_value: dict) -> int:
    return path_value["version"]


def get_piercer(piercer_id: str) -> dict:
    return get_success_data(api_client.get_piercer(piercer_id, READER))


def get_store(store_id: str) -> dict:
    return get_success_data(api_client.get_store(store_id, READER))


def get_appointment(appointment_id: str) -> dict:
    return get_success_data(api_client.get_appointment(appointment_id, READER))


def get_session(session_id: str) -> dict:
    return get_success_data(api_client.get_session(session_id, READER))


def get_customer(customer_id: str) -> dict:
    return get_success_data(api_client.get_customer(customer_id, READER))


def get_incident(incident_id: str) -> dict:
    return get_success_data(api_client.get_incident(incident_id, READER))


def get_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.get_sterilization_cycle(cycle_id, READER))


def get_lot(lot_id: str) -> dict:
    return get_success_data(api_client.get_cartridge_lot(lot_id, READER))


def get_certification(certification_id: str) -> dict:
    return get_success_data(api_client.get_certification(certification_id, READER))


def get_healing_outcome(outcome_id: str) -> dict:
    return get_success_data(api_client.get_healing_outcome(outcome_id, READER))


def session_of(appointment_id: str) -> dict:
    """The single session recorded against an appointment."""
    data = get_success_data(api_client.list_appointment_sessions(appointment_id, READER))
    sessions = data if isinstance(data, list) else data.get("data", data)
    assert sessions, f"no session recorded against appointment {appointment_id}"
    return sessions[0]


# ─── Tier 2: entity hierarchy ──────────────────────────────────────────────

def setup_store_with_certified_piercer(
    jurisdiction_overrides=None, store_overrides=None, certification_overrides=None, piercer_overrides=None
):
    """Jurisdiction + store + piercer holding one VALID STANDARD certification.

    Returns (jurisdiction, store, piercer, certification).
    """
    set_clock(DEFAULT_CLOCK)
    jurisdiction = create_jurisdiction(**(jurisdiction_overrides or {}))
    store = create_store(jurisdiction["id"], **(store_overrides or {}))
    piercer = create_piercer(store["id"], **(piercer_overrides or {}))
    certification = certify(piercer["id"], **(certification_overrides or {}))
    return jurisdiction, store, piercer, certification


def setup_customer_with_active_consent(jurisdiction_id: str, **customer_overrides):
    """Customer holding one ACTIVE self consent.

    Returns (customer, consent).
    """
    customer = create_customer(**customer_overrides)
    consent = activate_self_consent(customer["id"], jurisdiction_id)
    return customer, consent


# ─── Tier 3: sterilization evidence and inventory ──────────────────────────

def setup_cycle_and_lot(store_id: str, passed: bool = True, **lot_overrides):
    """Open a cycle with a bound lot, optionally closing the cycle as PASSED.

    PRD §2.7 makes the cycle interval closed on a given `autoclave_unit_id`, so
    two cycles on the same unit whose closed intervals merely touch are rejected
    with `ERR_AUTOCLAVE_CYCLE_OVERLAP`. Callers that build a second cycle for the
    same store pass a distinct `autoclave_unit_id` through `lot_overrides` to
    avoid that collision.
    Returns (cycle, lot).
    """
    cycle_overrides = {}
    for field in ("autoclave_unit_id", "cycle_start_at", "cycle_end_at"):
        if field in lot_overrides:
            cycle_overrides[field] = lot_overrides.pop(field)
    cycle = get_success_data(
        api_client.create_sterilization_cycle(
            create_sterilization_cycle_payload(store_id, **cycle_overrides), TECHNICIAN
        )
    )
    store = get_store(store_id)
    lot = get_success_data(
        api_client.create_cartridge_lot(
            create_cartridge_lot_payload(store_id, cycle["id"], store["version"], **lot_overrides),
            MANAGER,
        )
    )
    if passed:
        cycle = get_success_data(
            api_client.complete_sterilization_cycle(
                cycle["id"], {"temperature_celsius": 135.0, "biological_indicator_passed": True}, TECHNICIAN
            )
        )
    return cycle, lot


# ─── Tier 4: full service lifecycle shortcuts ──────────────────────────────

def setup_ready_appointment(
    store_id, customer_id, piercer_id, jurisdiction_id, slot_start="2026-09-01T09:00:00Z", slot_end="2026-09-01T09:30:00Z"
) -> dict:
    """A CONFIRMED appointment whose customer holds an ACTIVE consent."""
    appointment = create_appointment(
        store_id, customer_id, piercer_id, jurisdiction_id,
        slot_start_at=slot_start, slot_end_at=slot_end,
    )
    return confirm_appointment(appointment["id"])


def setup_screened_appointment(
    store_id, customer_id, piercer_id, jurisdiction_id,
    slot_start="2026-09-01T09:00:00Z", slot_end="2026-09-01T09:30:00Z",
    contraindication_codes=None, site_requested="LOBE",
):
    """Drive an appointment through CONFIRMED -> CHECKED_IN -> SCREENED.

    Per PRD §3.3 check-in requires the clock to be at or after `slot_start_at`
    minus the 30-minute lead, so the setup first advances the logical clock to
    the slot's start instant (inside the window, and still before `slot_end_at`
    so no show fires). Returns (appointment, screening).
    """
    appointment = setup_ready_appointment(
        store_id, customer_id, piercer_id, jurisdiction_id, slot_start, slot_end
    )
    api_client.set_clock(slot_start, COMPLIANCE)
    appointment = check_in_appointment(appointment["id"])
    screening = screen_appointment(
        appointment["id"], piercer_id,
        contraindication_codes=contraindication_codes or [],
        anatomy_sites_examined=[site_requested],
    )
    return get_appointment(appointment["id"]), screening


def setup_in_service_appointment(
    store_id, customer_id, piercer_id, jurisdiction_id,
    slot_start="2026-09-01T09:00:00Z", slot_end="2026-09-01T09:30:00Z", site_requested="LOBE",
):
    """Drive an appointment through to IN_SERVICE with a live session.

    Returns (appointment, screening, session).
    """
    appointment, screening = setup_screened_appointment(
        store_id, customer_id, piercer_id, jurisdiction_id, slot_start, slot_end, site_requested=site_requested
    )
    start_service(appointment["id"], piercer_id)
    session = session_of(appointment["id"])
    return get_appointment(appointment["id"]), screening, session


def setup_completed_service(
    store_id, customer_id, piercer_id, jurisdiction_id,
    slot_start="2026-09-01T09:00:00Z", slot_end="2026-09-01T09:30:00Z", site_requested="LOBE",
    completed_at=None,
):
    """Drive an appointment through to COMPLETED with a completed session.

    ``completed_at``, when supplied, advances the logical clock immediately
    before completion so the service lands at that instant (the aftercare
    follow-up reminder of PRD §3.6 is then scheduled relative to it).

    Returns (appointment, screening, session).
    """
    appointment, screening, session = setup_in_service_appointment(
        store_id, customer_id, piercer_id, jurisdiction_id, slot_start, slot_end, site_requested=site_requested
    )
    if completed_at is not None:
        api_client.set_clock(completed_at, COMPLIANCE)
    complete_appointment(appointment["id"], piercer_id)
    return get_appointment(appointment["id"]), screening, get_session(session["id"])


def setup_full_service(
    store_overrides=None, slot_start="2026-09-01T09:00:00Z", slot_end="2026-09-01T09:30:00Z",
    customer_overrides=None, certification_overrides=None, site_requested="LOBE",
    completed_at=None,
):
    """A complete service chain: certified piercer at an open store, an ACTIVE
    consent, a PASSED cycle with a bound lot, and one COMPLETED appointment
    whose session was completed through the real service path.

    Returns a dict with jurisdiction, store, piercer, certification, customer,
    consent, cycle, lot, appointment, screening and session.
    """
    jurisdiction, store, piercer, certification = setup_store_with_certified_piercer(
        store_overrides=store_overrides, certification_overrides=certification_overrides
    )
    cycle, lot = setup_cycle_and_lot(store["id"])
    customer, consent = setup_customer_with_active_consent(
        jurisdiction["id"], **(customer_overrides or {})
    )
    appointment, screening, session = setup_completed_service(
        store["id"], customer["id"], piercer["id"], jurisdiction["id"],
        slot_start=slot_start, slot_end=slot_end, site_requested=site_requested,
        completed_at=completed_at,
    )
    return {
        "jurisdiction": jurisdiction,
        "store": store,
        "piercer": piercer,
        "certification": certification,
        "customer": customer,
        "consent": consent,
        "cycle": cycle,
        "lot": lot,
        "appointment": appointment,
        "screening": screening,
        "session": session,
    }


def setup_in_service_saga(
    store_overrides=None, slot_start="2026-09-01T09:00:00Z", slot_end="2026-09-01T09:30:00Z",
):
    """One appointment held at IN_SERVICE with a live session and the piercer's
    concurrent-load counter already incremented.

    Returns the same dict shape as ``setup_full_service``.
    """
    jurisdiction, store, piercer, certification = setup_store_with_certified_piercer(
        store_overrides=store_overrides
    )
    cycle, lot = setup_cycle_and_lot(store["id"])
    customer, consent = setup_customer_with_active_consent(jurisdiction["id"])
    appointment, screening, session = setup_in_service_appointment(
        store["id"], customer["id"], piercer["id"], jurisdiction["id"], slot_start, slot_end
    )
    return {
        "jurisdiction": jurisdiction,
        "store": store,
        "piercer": piercer,
        "certification": certification,
        "customer": customer,
        "consent": consent,
        "cycle": cycle,
        "lot": lot,
        "appointment": appointment,
        "screening": screening,
        "session": session,
    }


# ─── Tier 5: incident / healing / posture composites ───────────────────────

def file_and_triage_incident(session, severity="MODERATE", **overrides) -> dict:
    """File an incident against a session and triage it.

    When ``escalate`` is passed true the incident is additionally escalated to
    `ESCALATED` (PRD §3.7 requires a `SEVERE`/`MEDICAL_EMERGENCY` incident to be
    escalated before it can be resolved).

    Returns the TRIAGED (or ESCALATED) incident.
    """
    escalate = overrides.pop("escalate", False)
    fresh = get_session(session["id"])
    incident = get_success_data(
        api_client.create_incident(
            create_incident_payload(fresh["id"], fresh["version"], severity=severity, **overrides),
            COMPLIANCE,
        )
    )
    incident = get_success_data(api_client.triage_incident(incident["id"], COMPLIANCE))
    if escalate:
        incident = get_success_data(api_client.escalate_incident(incident["id"], COMPLIANCE))
    return incident


def file_and_resolve_incident(session, severity="SEVERE", **overrides) -> dict:
    """File, triage and resolve an incident. Returns the RESOLVED incident.

    PRD §3.7: "A `TRIAGED` incident may instead be resolved directly, but only
    when its `severity` is `MINOR` or `MODERATE`"; a `SEVERE` or
    `MEDICAL_EMERGENCY` incident must be escalated to `ESCALATED` before it can
    be resolved. The fixture therefore escalates those severities first, so the
    precondition it builds matches the ladder the PRD declares.
    """
    incident = file_and_triage_incident(
        session, severity=severity,
        escalate=severity in ("SEVERE", "MEDICAL_EMERGENCY"), **overrides
    )
    return get_success_data(
        api_client.resolve_incident(
            incident["id"], {"resolution_note": "Medical review complete."}, COMPLIANCE
        )
    )


def add_open_incident(store_id, session, severity="MINOR",
                      reported_at="2026-09-05T00:00:00Z", **overrides) -> dict:
    """Add one more non-terminal incident reachable from a store's sessions.

    The incident is triaged so that it counts toward the store's open incident
    count; pass ``escalate=True`` to obtain an `ESCALATED` incident. Returns the
    resulting store view.
    """
    incident = file_and_triage_incident(
        session, severity=severity, reported_at=reported_at, **overrides
    )
    return get_store(store_id), incident


def setup_store_near_incident_threshold(store_overrides=None, completed_at=None):
    """An open store carrying exactly two triaged MINOR incidents, i.e. one
    short of the restriction threshold, plus the session they hang from.

    Returns the ``setup_full_service`` dict with the two incidents added and
    the store re-read, under key ``incidents``.
    """
    ctx = setup_full_service(store_overrides=store_overrides, completed_at=completed_at)
    incidents = []
    for day in ("2026-09-05T00:00:00Z", "2026-09-06T00:00:00Z"):
        _, incident = add_open_incident(ctx["store"]["id"], ctx["session"], reported_at=day)
        incidents.append(incident)
    ctx["incidents"] = incidents
    ctx["store"] = get_store(ctx["store"]["id"])
    return ctx


def setup_store_with_failed_cycle(store_overrides=None, eligibility_drop=True, completed_at=None):
    """A store whose bound cycle has failed, so its open incident count has
    risen and any ACTIVE piercer has lost 20 eligibility points.

    PRD §2.7 counts a store's `SterilizationCycle` rows whose `status` is
    `FAILED` directly (the failed cycle raises `open_incident_count` by one per
    bound lot), so this fixture does not additionally file an incident.

    Returns the ``setup_full_service`` dict with ``failed_cycle`` added and the
    store and piercer re-read.
    """
    ctx = setup_full_service(store_overrides=store_overrides, completed_at=completed_at)
    cycle, _ = setup_cycle_and_lot(
        ctx["store"]["id"], passed=False, lot_number="L-2", autoclave_unit_id="AUTO-FAIL"
    )
    failed = get_success_data(
        api_client.complete_sterilization_cycle(
            cycle["id"], {"temperature_celsius": 124.0, "biological_indicator_passed": False}, TECHNICIAN
        )
    )
    ctx["failed_cycle"] = failed
    ctx["store"] = get_store(ctx["store"]["id"])
    ctx["piercer"] = get_piercer(ctx["piercer"]["id"])
    return ctx


def setup_healed_session(slot_start="2026-09-01T09:00:00Z", slot_end="2026-09-01T09:30:00Z",
                         site_requested="HELIX", assessed_at="2026-09-15T00:00:00Z",
                         completed_at=None):
    """A completed service whose healing assessment recorded a healed result.

    Returns the ``setup_full_service`` dict with ``outcome`` added and the
    session re-read.
    """
    ctx = setup_full_service(slot_start=slot_start, slot_end=slot_end, site_requested=site_requested,
                             completed_at=completed_at)
    get_success_data(
        api_client.record_healing_assessment(
            ctx["session"]["id"],
            create_healing_assessment_payload(assessed_at=assessed_at, failure_codes=[]),
            make_piercer_headers(ctx["piercer"]["id"]),
        )
    )
    outcomes = get_success_data(api_client.list_session_healing_outcomes(ctx["session"]["id"], READER))
    outcomes = outcomes if isinstance(outcomes, list) else outcomes.get("data", outcomes)
    ctx["outcome"] = outcomes[0]
    ctx["session"] = get_session(ctx["session"]["id"])
    return ctx


def setup_healing_outcome_for_session(ctx, assessed_at="2026-09-20T00:00:00Z"):
    """Create an explicit healing outcome against a completed session.

    Returns (updated ctx, outcome).
    """
    session = get_session(ctx["session"]["id"])
    outcome = get_success_data(
        api_client.create_healing_outcome(
            create_healing_outcome_payload(session["id"], session["version"], assessed_at=assessed_at),
            make_piercer_headers(ctx["piercer"]["id"]),
        )
    )
    ctx["outcome"] = outcome
    return ctx, outcome


def open_explicit_session(ctx, **session_overrides):
    """Screen a fresh appointment and open its session explicitly, supplying the
    cartridge lot and the fee inputs directly.

    Returns (appointment, response) where ``response`` is the raw response of the
    session-opening call so negative cases can assert the refusal.
    """
    store = ctx["store"]
    jurisdiction = ctx["jurisdiction"]
    piercer = ctx["piercer"]
    customer = ctx["customer"]
    appointment = setup_screened_appointment(
        store["id"], customer["id"], piercer["id"], jurisdiction["id"],
        slot_start=session_overrides.pop("slot_start", "2026-09-01T15:00:00Z"),
        slot_end=session_overrides.pop("slot_end", "2026-09-01T15:30:00Z"),
    )[0]
    payload = create_session_payload(
        appointment["id"], piercer["id"], ctx["lot"]["id"], **session_overrides
    )
    response = api_client.create_session(payload, make_piercer_headers(piercer["id"]))
    return appointment, response


def setup_expiring_certification(issued_at="2025-11-01T00:00:00Z", expires_at="2026-11-01T00:00:00Z",
                                 clock="2026-10-02T00:00:00Z"):
    """A piercer whose certification has crossed into EXPIRING_SOON.

    Returns (jurisdiction, store, piercer, certification) with the clock set
    past recertification_due_at.
    """
    jurisdiction, store, piercer, certification = setup_store_with_certified_piercer(
        certification_overrides={"issued_at": issued_at, "expires_at": expires_at}
    )
    set_clock(clock)
    refreshed = get_success_data(api_client.get_certification(certification["id"], READER))
    return jurisdiction, store, piercer, refreshed