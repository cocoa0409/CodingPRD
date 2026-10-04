"""Composite setup helpers.

Multi-step PRD-legal preambles so tests can focus on assertions. Every
fixture builds its preconditions from scratch through the public API (the
server restarts, with an empty database and the startup clock, before every
test). Setup calls use the lenient get_success_data() validator so failures
surface as clear "Setup step failed" errors.

Time-sensitive fixtures take explicit ISO timestamps and set the logical
clock BEFORE creating the entities that depend on it. Identity threading:
ownership-gated calls use make_ngb_admin_headers(body_id) /
make_athlete_headers(athlete_id) with the real entity ids — never the shared
placeholder constants. Segregated pairs use distinct opaque auditor ids
(issuer/triager AUDITOR_ISSUER_ID vs closer/resolver AUDITOR_CLOSER_ID).
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .constants import CLOCK_STARTUP_DEFAULT, INSURANCE_WAIT_DAYS
from .test_users import (
    ARBITRATOR_ID,
    AUDITOR_CLOSER_ID,
    AUDITOR_ISSUER_ID,
    INTERIM_MANAGER_ID,
    RESULTS_OFFICIAL_ID,
    SAFE_SPORT_OFFICER_ID,
    TEST_USERS,
    make_athlete_headers,
    make_auditor_headers,
    make_committee_admin_headers,
    make_ngb_admin_headers,
    make_results_official_headers,
    make_safe_sport_officer_headers,
    make_arbitrator_headers,
)

_COMMITTEE = TEST_USERS["committee_admin_headers"]


def _client(api):
    if api is not None:
        return api
    from .api_client import api_client
    return api_client


# ---------------------------------------------------------------------------
# ISO 8601 helpers (logical-clock arithmetic)
# ---------------------------------------------------------------------------

def parse_iso(iso: str) -> datetime:
    """Parse an ISO 8601 UTC instant (accepts trailing Z or +00:00 and
    optional fractional seconds)."""
    text = iso.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt: datetime) -> str:
    """Format as YYYY-MM-DDTHH:MM:SSZ (the clock literal form)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_plus_days(iso: str, days: float) -> str:
    return format_iso(parse_iso(iso) + timedelta(days=days))


def iso_plus_hours(iso: str, hours: float) -> str:
    return format_iso(parse_iso(iso) + timedelta(hours=hours))


def iso_plus_seconds(iso: str, seconds: float) -> str:
    return format_iso(parse_iso(iso) + timedelta(seconds=seconds))


# ---------------------------------------------------------------------------
# Logical clock (unprefixed platform endpoint)
# ---------------------------------------------------------------------------

_last_clock = CLOCK_STARTUP_DEFAULT


def set_logical_clock(to_iso8601: str, api=None) -> str:
    """Advance the logical clock via POST /_clock/set_current_utc
    (CommitteeAdmin only). Returns the reported current_utc. Tolerant of the
    value arriving enveloped (data.current_utc) or bare (current_utc)."""
    global _last_clock
    client = _client(api)
    resp = client.set_clock(to_iso8601, _COMMITTEE)
    if not (200 <= resp.status_code < 300):
        raise AssertionError(
            f"Setup step failed setting clock to {to_iso8601}: "
            f"HTTP {resp.status_code}: {resp.text}"
        )
    body = resp.json()
    current = None
    if isinstance(body, dict):
        if isinstance(body.get("data"), dict) and "current_utc" in body["data"]:
            current = body["data"]["current_utc"]
        elif "current_utc" in body:
            current = body["current_utc"]
    _last_clock = to_iso8601
    return current if isinstance(current, str) else to_iso8601


def current_clock() -> str:
    """Last value this process set the logical clock to. The server restarts
    (resetting to the startup default) before every test; conftest calls
    reset_clock_tracker() per test to keep this in sync."""
    return _last_clock


def reset_clock_tracker():
    global _last_clock
    _last_clock = CLOCK_STARTUP_DEFAULT


# ---------------------------------------------------------------------------
# Governing bodies and certification cycles
# ---------------------------------------------------------------------------

def create_governing_body(api=None, **overrides) -> dict:
    client = _client(api)
    resp = client.create_governing_body(
        factories.create_governing_body_payload(**overrides), _COMMITTEE
    )
    return get_success_data(resp, 201)


def read_governing_body(governing_body_id: str, api=None) -> dict:
    client = _client(api)
    return get_success_data(client.get_governing_body(governing_body_id, _COMMITTEE))


def create_certification_cycle(governing_body_id: str, api=None, **overrides) -> dict:
    client = _client(api)
    resp = client.create_certification_cycle(
        governing_body_id, factories.create_certification_cycle_payload(**overrides),
        _COMMITTEE,
    )
    return get_success_data(resp, 201)


def open_cycle(cycle_id: str, auditor_id: str = AUDITOR_ISSUER_ID, api=None) -> dict:
    client = _client(api)
    resp = client.transition_certification_cycle(
        cycle_id, {"to_state": "OPEN"}, make_auditor_headers(auditor_id)
    )
    return get_success_data(resp)


def issue_findings(cycle_id: str, governance_score, athlete_rep_score, financial_score,
                   auditor_id: str = AUDITOR_ISSUER_ID, api=None) -> dict:
    client = _client(api)
    resp = client.transition_certification_cycle(
        cycle_id,
        factories.issue_findings_payload(governance_score, athlete_rep_score, financial_score),
        make_auditor_headers(auditor_id),
    )
    return get_success_data(resp)


def move_cycle_to_remediation(cycle_id: str, auditor_id: str = AUDITOR_ISSUER_ID,
                              api=None) -> dict:
    client = _client(api)
    resp = client.transition_certification_cycle(
        cycle_id, {"to_state": "REMEDIATION"}, make_auditor_headers(auditor_id)
    )
    return get_success_data(resp)


def close_cycle(cycle_id: str, outcome: str = "CLOSED_PASSED",
                auditor_id: str = AUDITOR_CLOSER_ID, api=None) -> dict:
    """Close a cycle. `auditor_id` MUST differ from the issuer (segregation)."""
    client = _client(api)
    resp = client.transition_certification_cycle(
        cycle_id, {"to_state": outcome}, make_auditor_headers(auditor_id)
    )
    return get_success_data(resp)


def setup_certified_body(api=None, scores=(90, 88, 92), **body_overrides) -> dict:
    """APPLIED body + cycle opened, findings issued (default 89.8 >= 85) and
    fast-path closed passed by a distinct auditor. Returns the CERTIFIED body
    re-read after the cascade."""
    body = create_governing_body(api=api, **body_overrides)
    cycle = create_certification_cycle(body["id"], api=api)
    open_cycle(cycle["id"], api=api)
    issue_findings(cycle["id"], scores[0], scores[1], scores[2], api=api)
    close_cycle(cycle["id"], "CLOSED_PASSED", api=api)
    return read_governing_body(body["id"], api=api)


def setup_probation_body(api=None, fail_scores=(60, 60, 60),
                         second_window=("2026-12-01T00:00:00Z", "2027-03-01T00:00:00Z"),
                         **body_overrides) -> dict:
    """CERTIFIED body then a CLOSED_FAILED cycle -> PROBATION.

    The failing cycle's window starts where the certifying cycle's window
    ends (half-open adjacency is allowed), and the clock advances to that
    start so the cycle can open. The closed-failed cycle doubles as
    decertification evidence within the trailing window.
    """
    body = setup_certified_body(api=api, **body_overrides)
    set_logical_clock(second_window[0], api=api)
    cycle = create_certification_cycle(
        body["id"], api=api,
        window_start=second_window[0], window_end=second_window[1],
    )
    open_cycle(cycle["id"], api=api)
    issue_findings(cycle["id"], fail_scores[0], fail_scores[1], fail_scores[2], api=api)
    close_cycle(cycle["id"], "CLOSED_FAILED", api=api)
    return read_governing_body(body["id"], api=api)


def appoint_interim_manager(governing_body_id: str,
                            manager_id: str = INTERIM_MANAGER_ID, api=None) -> dict:
    """PROBATION -> INTERIM_MANAGED (or the INTERIM_MANAGED self-loop that
    appoints/replaces the manager); interim_manager_id required."""
    client = _client(api)
    resp = client.transition_governing_body(
        governing_body_id,
        {"to_state": "INTERIM_MANAGED", "interim_manager_id": manager_id},
        _COMMITTEE,
    )
    return get_success_data(resp)


def setup_interim_managed_body(api=None, manager_id: str = INTERIM_MANAGER_ID,
                               **body_overrides) -> dict:
    """PROBATION body moved to INTERIM_MANAGED with an appointed manager."""
    body = setup_probation_body(api=api, **body_overrides)
    appoint_interim_manager(body["id"], manager_id, api=api)
    return read_governing_body(body["id"], api=api)


def return_body_to_probation(governing_body_id: str, api=None) -> dict:
    """INTERIM_MANAGED -> PROBATION; clears interim_manager_id."""
    client = _client(api)
    resp = client.transition_governing_body(
        governing_body_id, {"to_state": "PROBATION"}, _COMMITTEE
    )
    return get_success_data(resp)


def decertify_body(governing_body_id: str, api=None) -> dict:
    """PROBATION|INTERIM_MANAGED -> DECERTIFIED. The caller must arrange the
    evidence (a CLOSED_FAILED cycle or SUBSTANTIATED CRITICAL complaint
    within the trailing 365 days) — setup_probation_body qualifies."""
    client = _client(api)
    resp = client.transition_governing_body(
        governing_body_id, {"to_state": "DECERTIFIED"}, _COMMITTEE
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Complaints
# ---------------------------------------------------------------------------

def file_complaint(governing_body_id: str, api=None, headers=None, **overrides) -> dict:
    client = _client(api)
    resp = client.create_complaint(
        governing_body_id, factories.create_complaint_payload(**overrides),
        headers or _COMMITTEE,
    )
    return get_success_data(resp, 201)


def triage_complaint(complaint_id: str, auditor_id: str = AUDITOR_ISSUER_ID,
                     api=None) -> dict:
    client = _client(api)
    resp = client.transition_complaint(
        complaint_id, {"to_state": "TRIAGED"}, make_auditor_headers(auditor_id)
    )
    return get_success_data(resp)


def investigate_complaint(complaint_id: str, auditor_id: str = AUDITOR_ISSUER_ID,
                          api=None) -> dict:
    client = _client(api)
    resp = client.transition_complaint(
        complaint_id, {"to_state": "INVESTIGATING"}, make_auditor_headers(auditor_id)
    )
    return get_success_data(resp)


def resolve_complaint(complaint_id: str, outcome: str = "SUBSTANTIATED",
                      auditor_id: str = AUDITOR_CLOSER_ID, api=None) -> dict:
    """Resolve INVESTIGATING -> SUBSTANTIATED|DISMISSED. `auditor_id` MUST
    differ from the triager (segregation)."""
    client = _client(api)
    resp = client.transition_complaint(
        complaint_id, {"to_state": outcome}, make_auditor_headers(auditor_id)
    )
    return get_success_data(resp)


def substantiate_complaint(governing_body_id: str, severity: str = "MINOR",
                           category: str = "GOVERNANCE",
                           triager: str = AUDITOR_ISSUER_ID,
                           resolver: str = AUDITOR_CLOSER_ID,
                           api=None, **overrides) -> dict:
    """Full chain: file -> triage -> investigate -> SUBSTANTIATED with
    distinct triager/resolver. Returns the resolved complaint."""
    complaint = file_complaint(
        governing_body_id, api=api, severity=severity, category=category, **overrides
    )
    triage_complaint(complaint["id"], triager, api=api)
    investigate_complaint(complaint["id"], triager, api=api)
    return resolve_complaint(complaint["id"], "SUBSTANTIATED", resolver, api=api)


# ---------------------------------------------------------------------------
# Athletes (safe-sport + eligibility dimensions)
# ---------------------------------------------------------------------------

def create_athlete(governing_body_id: str, api=None, as_ngb_admin: bool = False,
                   **overrides) -> dict:
    client = _client(api)
    headers = (make_ngb_admin_headers(governing_body_id) if as_ngb_admin else _COMMITTEE)
    resp = client.create_athlete(
        factories.create_athlete_payload(governing_body_id, **overrides), headers
    )
    return get_success_data(resp, 201)


def read_athlete(athlete_id: str, api=None) -> dict:
    client = _client(api)
    return get_success_data(client.get_athlete(athlete_id, _COMMITTEE))


def _athlete_transition(athlete_id: str, to_state: str, headers, api) -> dict:
    client = _client(api)
    resp = client.transition_athlete(athlete_id, {"to_state": to_state}, headers)
    return get_success_data(resp)


def clear_screening(athlete_id: str, officer_id: str = SAFE_SPORT_OFFICER_ID,
                    api=None) -> dict:
    return _athlete_transition(
        athlete_id, "SCREENING_CLEARED", make_safe_sport_officer_headers(officer_id), api
    )


def flag_screening(athlete_id: str, officer_id: str = SAFE_SPORT_OFFICER_ID,
                   api=None) -> dict:
    return _athlete_transition(
        athlete_id, "SCREENING_FLAGGED", make_safe_sport_officer_headers(officer_id), api
    )


def record_training(athlete_id: str, officer_id: str = SAFE_SPORT_OFFICER_ID,
                    api=None) -> dict:
    return _athlete_transition(
        athlete_id, "TRAINING_CURRENT", make_safe_sport_officer_headers(officer_id), api
    )


def make_eligible(athlete_id: str, officer_id: str = SAFE_SPORT_OFFICER_ID,
                  api=None) -> dict:
    return _athlete_transition(
        athlete_id, "ELIGIBLE", make_safe_sport_officer_headers(officer_id), api
    )


def suspend_athlete(athlete_id: str, officer_id: str = SAFE_SPORT_OFFICER_ID,
                    api=None) -> dict:
    return _athlete_transition(
        athlete_id, "SUSPENDED", make_safe_sport_officer_headers(officer_id), api
    )


def retire_athlete(athlete_id: str, api=None) -> dict:
    """Self-retirement: X-User-ID must equal the athlete's own id."""
    return _athlete_transition(
        athlete_id, "RETIRED", make_athlete_headers(athlete_id), api
    )


def setup_eligible_athlete(governing_body_id: str, api=None, **overrides) -> dict:
    """Registered athlete with screening cleared, training recorded, and
    eligibility ELIGIBLE. Returns the athlete after the ELIGIBLE move."""
    athlete = create_athlete(governing_body_id, api=api, **overrides)
    clear_screening(athlete["id"], api=api)
    record_training(athlete["id"], api=api)
    return make_eligible(athlete["id"], api=api)


# ---------------------------------------------------------------------------
# Performance results
# ---------------------------------------------------------------------------

def submit_result(athlete_id: str, api=None, **overrides) -> dict:
    """Submitted by the owning athlete (entity-backed headers)."""
    client = _client(api)
    resp = client.create_result(
        athlete_id, factories.create_result_payload(**overrides),
        make_athlete_headers(athlete_id),
    )
    return get_success_data(resp, 201)


def verify_result(result_id: str, official_id: str = RESULTS_OFFICIAL_ID,
                  api=None) -> dict:
    """ResultsOfficial verification; official must differ from the submitter."""
    client = _client(api)
    resp = client.transition_result(
        result_id, {"to_state": "VERIFIED"}, make_results_official_headers(official_id)
    )
    return get_success_data(resp)


def reject_result(result_id: str, official_id: str = RESULTS_OFFICIAL_ID,
                  api=None) -> dict:
    client = _client(api)
    resp = client.transition_result(
        result_id, {"to_state": "REJECTED"}, make_results_official_headers(official_id)
    )
    return get_success_data(resp)


def resubmit_result(result_id: str, athlete_id: str, api=None) -> dict:
    """REJECTED -> SUBMITTED by the owning athlete only."""
    client = _client(api)
    resp = client.transition_result(
        result_id, {"to_state": "SUBMITTED"}, make_athlete_headers(athlete_id)
    )
    return get_success_data(resp)


def add_verified_result(athlete_id: str, event_grade: str = "A", placing: int = 1,
                        event_date: str = "2026-08-01T00:00:00Z",
                        event_name: str = None,
                        official_id: str = RESULTS_OFFICIAL_ID, api=None) -> dict:
    """Submit + verify one result; returns the VERIFIED result."""
    overrides = {"event_grade": event_grade, "placing": placing, "event_date": event_date}
    if event_name is not None:
        overrides["event_name"] = event_name
    result = submit_result(athlete_id, api=api, **overrides)
    return verify_result(result["id"], official_id, api=api)


def add_verified_results(athlete_id: str, specs, api=None) -> list:
    """Submit + verify a batch. Each spec is a dict with event_grade, placing,
    event_date (and optional event_name). Returns the VERIFIED results in
    order."""
    return [add_verified_result(athlete_id, api=api, **spec) for spec in specs]


# ---------------------------------------------------------------------------
# Funding agreements and insurance
# ---------------------------------------------------------------------------

def create_funding_agreement(athlete_id: str, api=None, **overrides) -> dict:
    """Offer an agreement (OFFERED); points/tier/stipend computed from the
    athlete's VERIFIED results as of the current logical clock."""
    client = _client(api)
    resp = client.create_funding_agreement(
        athlete_id, factories.create_funding_agreement_payload(**overrides), _COMMITTEE
    )
    return get_success_data(resp, 201)


def read_funding_agreement(agreement_id: str, api=None) -> dict:
    client = _client(api)
    return get_success_data(client.get_funding_agreement(agreement_id, _COMMITTEE))


def _agreement_transition(agreement_id: str, to_state: str, api) -> dict:
    client = _client(api)
    resp = client.transition_funding_agreement(agreement_id, {"to_state": to_state},
                                               _COMMITTEE)
    return get_success_data(resp)


def activate_agreement(agreement_id: str, api=None) -> dict:
    """OFFERED -> ACTIVE (or resume/reassess from the ACTIVE surface)."""
    return _agreement_transition(agreement_id, "ACTIVE", api)


def reassess_agreement(agreement_id: str, api=None) -> dict:
    """ACTIVE self-loop: recompute points/tier/stipend as of the clock."""
    return _agreement_transition(agreement_id, "ACTIVE", api)


def terminate_agreement(agreement_id: str, api=None) -> dict:
    return _agreement_transition(agreement_id, "TERMINATED", api)


def enroll_insurance(agreement_id: str, api=None) -> dict:
    """INS_NONE|INS_LAPSED -> INS_ENROLLED; caller arranges the points and
    30-day-wait gates before calling."""
    return _agreement_transition(agreement_id, "INS_ENROLLED", api)


def setup_active_agreement(athlete_id: str, api=None, result_specs=None,
                           activate_at: str = None, **agreement_overrides) -> dict:
    """Create + activate an agreement for an ELIGIBLE athlete.

    result_specs (optional) are added as VERIFIED results first. activate_at
    (optional) sets the logical clock before the offer so points compute and
    activated_at stamps at that instant. Default: one VERIFIED 1st/A result
    dated 2026-08-01 -> 60.00 points (TIER_B) under either method at the
    default 2026-10-01 activation clock.
    """
    if result_specs is None:
        result_specs = [{"event_grade": "A", "placing": 1,
                         "event_date": "2026-08-01T00:00:00Z"}]
        if activate_at is None:
            activate_at = "2026-10-01T00:00:00Z"
    if result_specs:
        add_verified_results(athlete_id, result_specs, api=api)
    if activate_at is not None:
        set_logical_clock(activate_at, api=api)
    agreement = create_funding_agreement(athlete_id, api=api, **agreement_overrides)
    return activate_agreement(agreement["id"], api=api)


def setup_enrolled_agreement(athlete_id: str, api=None, result_specs=None,
                             activate_at: str = None,
                             wait_days: int = INSURANCE_WAIT_DAYS,
                             **agreement_overrides) -> dict:
    """ACTIVE agreement with insurance enrolled: activates, then advances the
    clock exactly `wait_days` past the server-stamped activated_at (the
    inclusive boundary) and enrolls. Returns the agreement re-read."""
    agreement = setup_active_agreement(
        athlete_id, api=api, result_specs=result_specs, activate_at=activate_at,
        **agreement_overrides,
    )
    enroll_at = iso_plus_days(agreement["activated_at"], wait_days)
    set_logical_clock(enroll_at, api=api)
    enroll_insurance(agreement["id"], api=api)
    return read_funding_agreement(agreement["id"], api=api)


# ---------------------------------------------------------------------------
# Abuse reports
# ---------------------------------------------------------------------------

def file_abuse_report(athlete_id: str, api=None, headers=None, **overrides) -> dict:
    """File an allegation concerning the subject athlete; default filer is a
    SafeSportOfficer (one of the PRD-allowed filing roles)."""
    client = _client(api)
    resp = client.create_abuse_report(
        athlete_id, factories.create_abuse_report_payload(**overrides),
        headers or make_safe_sport_officer_headers(),
    )
    return get_success_data(resp, 201)


def forward_abuse_report(report_id: str, officer_id: str = SAFE_SPORT_OFFICER_ID,
                         api=None) -> dict:
    client = _client(api)
    resp = client.transition_abuse_report(
        report_id, {"to_state": "FORWARDED"}, make_safe_sport_officer_headers(officer_id)
    )
    return get_success_data(resp)


def adjudicate_abuse_report(report_id: str, outcome: str = "ADJUDICATED_SUBSTANTIATED",
                            officer_id: str = SAFE_SPORT_OFFICER_ID, api=None) -> dict:
    client = _client(api)
    resp = client.transition_abuse_report(
        report_id, {"to_state": outcome}, make_safe_sport_officer_headers(officer_id)
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Selection procedures and trials
# ---------------------------------------------------------------------------

def create_selection_procedure(governing_body_id: str, api=None, **overrides) -> dict:
    """Draft a procedure as the body's own NGBAdmin (entity-backed)."""
    client = _client(api)
    resp = client.create_selection_procedure(
        governing_body_id, factories.create_selection_procedure_payload(**overrides),
        make_ngb_admin_headers(governing_body_id),
    )
    return get_success_data(resp, 201)


def read_procedure(governing_body_id: str, procedure_id: str, api=None) -> dict:
    """Read one procedure via the body's list endpoint (no single-GET exists
    on the procedure surface)."""
    client = _client(api)
    data = get_success_data(
        client.list_selection_procedures(governing_body_id, _COMMITTEE)
    )
    for proc in data:
        if proc.get("id") == procedure_id:
            return proc
    raise AssertionError(f"Setup: procedure {procedure_id} not found in list")


def _procedure_transition(procedure_id: str, governing_body_id: str, payload: dict,
                          api) -> dict:
    client = _client(api)
    resp = client.transition_selection_procedure(
        procedure_id, payload, make_ngb_admin_headers(governing_body_id)
    )
    return get_success_data(resp)


def publish_procedure(procedure_id: str, governing_body_id: str, api=None) -> dict:
    return _procedure_transition(procedure_id, governing_body_id,
                                 {"to_state": "PUBLISHED"}, api)


def lock_procedure(procedure_id: str, governing_body_id: str, api=None) -> dict:
    return _procedure_transition(procedure_id, governing_body_id,
                                 {"to_state": "LOCKED"}, api)


def open_registration(procedure_id: str, governing_body_id: str, api=None) -> dict:
    return _procedure_transition(procedure_id, governing_body_id,
                                 {"to_state": "REGISTRATION_OPEN"}, api)


def enter_trials(procedure_id: str, athlete_id: str, governing_body_id: str,
                 api=None) -> dict:
    """Register one athlete into the trials; returns the updated procedure."""
    client = _client(api)
    resp = client.create_trials_entry(
        procedure_id, {"athlete_id": athlete_id},
        make_ngb_admin_headers(governing_body_id),
    )
    return get_success_data(resp, 201)


def hold_trials(procedure: dict, governing_body_id: str, api=None,
                at: str = None) -> dict:
    """REGISTRATION_OPEN -> HELD; advances the clock to trials_start first
    (pass `at` to hold at a later instant)."""
    set_logical_clock(at or procedure["trials_start"], api=api)
    return _procedure_transition(procedure["id"], governing_body_id,
                                 {"to_state": "HELD"}, api)


def finalize_results(procedure: dict, results, governing_body_id: str, api=None,
                     at: str = None) -> dict:
    """HELD -> RESULTS_FINALIZED; advances the clock to trials_end first
    (pass `at` to finalize later). `results` is the full atomic array of
    {"athlete_id", "score"} pairs covering every still-REGISTERED entry."""
    set_logical_clock(at or procedure["trials_end"], api=api)
    return _procedure_transition(
        procedure["id"], governing_body_id,
        factories.finalize_results_payload(results), api,
    )


def setup_locked_procedure(governing_body_id: str, api=None, **overrides) -> dict:
    """DRAFT -> PUBLISHED -> LOCKED (body must be CERTIFIED/PROBATION/
    INTERIM_MANAGED; default dates satisfy the publish lead)."""
    proc = create_selection_procedure(governing_body_id, api=api, **overrides)
    publish_procedure(proc["id"], governing_body_id, api=api)
    return lock_procedure(proc["id"], governing_body_id, api=api)


def setup_procedure_with_entries(governing_body_id: str, athlete_ids, api=None,
                                 **overrides) -> dict:
    """LOCKED procedure with trials REGISTRATION_OPEN and every athlete in
    `athlete_ids` entered (clock must sit at/before registration_deadline —
    the startup default qualifies for the default dates)."""
    proc = setup_locked_procedure(governing_body_id, api=api, **overrides)
    proc = open_registration(proc["id"], governing_body_id, api=api)
    for athlete_id in athlete_ids:
        proc = enter_trials(proc["id"], athlete_id, governing_body_id, api=api)
    return proc


def setup_finalized_procedure(governing_body_id: str, entrant_scores, api=None,
                              **overrides) -> dict:
    """Full trials chain: entries -> HELD -> RESULTS_FINALIZED.

    entrant_scores maps athlete_id -> trials score. Returns the procedure
    with all entries scored and QUALIFIED/UNQUALIFIED assigned."""
    proc = setup_procedure_with_entries(
        governing_body_id, list(entrant_scores.keys()), api=api, **overrides
    )
    proc = hold_trials(proc, governing_body_id, api=api)
    results = [{"athlete_id": aid, "score": score}
               for aid, score in entrant_scores.items()]
    return finalize_results(proc, results, governing_body_id, api=api)


# ---------------------------------------------------------------------------
# Rosters, nominations, slot decisions
# ---------------------------------------------------------------------------

def create_roster(procedure_id: str, governing_body_id: str, api=None) -> dict:
    """Empty DRAFT roster for the procedure (version 1)."""
    client = _client(api)
    resp = client.create_roster(procedure_id, {},
                                make_ngb_admin_headers(governing_body_id))
    return get_success_data(resp, 201)


def read_roster(roster_id: str, api=None) -> dict:
    client = _client(api)
    return get_success_data(client.get_roster(roster_id, _COMMITTEE))


def run_nominations(roster: dict, governing_body_id: str, api=None) -> dict:
    """Run/re-run the selector, OCC-guarded by the roster dict's current
    version. Pass a freshly read roster after any mutation."""
    client = _client(api)
    resp = client.run_nominations(
        roster["id"],
        factories.nomination_payload(roster["version"]),
        make_ngb_admin_headers(governing_body_id),
    )
    return get_success_data(resp)


def answer_slot(roster_id: str, athlete_id: str, decision: str, api=None) -> dict:
    """Athlete answers their own slot (ACCEPTED|DECLINED) on the NOMINATED
    self-loop; entity-backed headers bind the caller to the athlete."""
    client = _client(api)
    resp = client.transition_roster(
        roster_id,
        factories.slot_decisions_payload(
            [{"athlete_id": athlete_id, "decision": decision}]
        ),
        make_athlete_headers(athlete_id),
    )
    return get_success_data(resp)


def submit_roster(roster_id: str, headers, api=None) -> dict:
    """NOMINATED -> SUBMITTED. `headers` select the submitter per the body's
    standing: the body's NGBAdmin while CERTIFIED/PROBATION, or a
    CommitteeAdmin (e.g. the appointed interim manager) while INTERIM_MANAGED."""
    client = _client(api)
    resp = client.transition_roster(roster_id, {"to_state": "SUBMITTED"}, headers)
    return get_success_data(resp)


def confirm_roster(roster_id: str, api=None) -> dict:
    """SUBMITTED -> CONFIRMED (CommitteeAdmin); cascades procedure COMPLETED."""
    client = _client(api)
    resp = client.transition_roster(roster_id, {"to_state": "CONFIRMED"}, _COMMITTEE)
    return get_success_data(resp)


def setup_nominated_roster(governing_body_id: str, entrant_scores, api=None,
                           nominate_at: str = "2026-12-20T00:00:00Z",
                           **procedure_overrides):
    """Full chain: finalized procedure -> DRAFT roster -> nomination run.

    The clock advances to `nominate_at` before the selector runs (the roster's
    nominated_at anchors the 72-hour appeal window there). Returns
    (procedure, roster) with the roster NOMINATED."""
    proc = setup_finalized_procedure(
        governing_body_id, entrant_scores, api=api, **procedure_overrides
    )
    roster = create_roster(proc["id"], governing_body_id, api=api)
    if nominate_at is not None:
        set_logical_clock(nominate_at, api=api)
    roster = run_nominations(roster, governing_body_id, api=api)
    return proc, roster


# ---------------------------------------------------------------------------
# Appeals
# ---------------------------------------------------------------------------

def file_appeal(roster_id: str, athlete_id: str, api=None, **overrides) -> dict:
    """Filed by the athlete (entity-backed); the caller sets the clock so the
    filing lands inside the appeal window when testing the success path."""
    client = _client(api)
    resp = client.create_appeal(
        roster_id, factories.create_appeal_payload(**overrides),
        make_athlete_headers(athlete_id),
    )
    return get_success_data(resp, 201)


def move_appeal_to_hearing(appeal_id: str, arbitrator_id: str = ARBITRATOR_ID,
                           api=None) -> dict:
    client = _client(api)
    resp = client.transition_appeal(
        appeal_id, {"to_state": "HEARING"}, make_arbitrator_headers(arbitrator_id)
    )
    return get_success_data(resp)


def decide_appeal(appeal_id: str, outcome: str = "UPHELD",
                  decision_rationale: str = "Arbitrator rationale on the record.",
                  arbitrator_id: str = ARBITRATOR_ID, api=None) -> dict:
    """HEARING -> UPHELD|DENIED with rationale."""
    client = _client(api)
    resp = client.transition_appeal(
        appeal_id,
        {"to_state": outcome, "decision_rationale": decision_rationale},
        make_arbitrator_headers(arbitrator_id),
    )
    return get_success_data(resp)


def withdraw_appeal(appeal_id: str, athlete_id: str, api=None) -> dict:
    """FILED -> WITHDRAWN by the filing athlete only."""
    client = _client(api)
    resp = client.transition_appeal(
        appeal_id, {"to_state": "WITHDRAWN"}, make_athlete_headers(athlete_id)
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Commercial deals (OCC-guarded transitions)
# ---------------------------------------------------------------------------

def create_commercial_deal(athlete_id: str, api=None, as_ngb_admin_for_body: str = None,
                           **overrides) -> dict:
    """Propose a deal (PROPOSED). Default proposer is CommitteeAdmin; pass
    as_ngb_admin_for_body=<governing body id> to propose as the athlete's own
    body's NGBAdmin."""
    client = _client(api)
    headers = (make_ngb_admin_headers(as_ngb_admin_for_body)
               if as_ngb_admin_for_body else _COMMITTEE)
    resp = client.create_commercial_deal(
        athlete_id, factories.create_commercial_deal_payload(**overrides), headers
    )
    return get_success_data(resp, 201)


def consent_deal(deal: dict, athlete_id: str, api=None) -> dict:
    """PROPOSED -> CONSENT_GRANTED by the subject athlete, OCC-guarded by the
    deal dict's current version."""
    client = _client(api)
    resp = client.transition_commercial_deal(
        deal["id"],
        factories.deal_transition_payload("CONSENT_GRANTED", deal["version"]),
        make_athlete_headers(athlete_id),
    )
    return get_success_data(resp)


def activate_deal(deal: dict, api=None) -> dict:
    """CONSENT_GRANTED -> ACTIVE (CommitteeAdmin), OCC-guarded; computes the
    revenue shares. Pass the post-consent deal dict so the version matches."""
    client = _client(api)
    resp = client.transition_commercial_deal(
        deal["id"],
        factories.deal_transition_payload("ACTIVE", deal["version"]),
        _COMMITTEE,
    )
    return get_success_data(resp)


def terminate_deal(deal: dict, api=None) -> dict:
    client = _client(api)
    resp = client.transition_commercial_deal(
        deal["id"],
        factories.deal_transition_payload("TERMINATED", deal["version"]),
        _COMMITTEE,
    )
    return get_success_data(resp)


def setup_active_deal(athlete_id: str, api=None, **overrides) -> dict:
    """PROPOSED -> CONSENT_GRANTED -> ACTIVE with OCC versions threaded
    through each response. Athlete's body must stand CERTIFIED/PROBATION/
    INTERIM_MANAGED for activation."""
    deal = create_commercial_deal(athlete_id, api=api, **overrides)
    deal = consent_deal(deal, athlete_id, api=api)
    return activate_deal(deal, api=api)


# ---------------------------------------------------------------------------
# Composite scenarios
# ---------------------------------------------------------------------------

def setup_funded_athlete(api=None, body_overrides=None, athlete_overrides=None,
                         result_specs=None, activate_at: str = None,
                         **agreement_overrides):
    """CERTIFIED body + ELIGIBLE athlete + ACTIVE funding agreement.

    Returns (body, athlete, agreement). Default funding shape: one VERIFIED
    1st/A result dated 2026-08-01 (60.00 points, TIER_B, stipend 200000) and
    activation at 2026-10-01.
    """
    body = setup_certified_body(api=api, **(body_overrides or {}))
    athlete = setup_eligible_athlete(body["id"], api=api, **(athlete_overrides or {}))
    agreement = setup_active_agreement(
        athlete["id"], api=api, result_specs=result_specs, activate_at=activate_at,
        **agreement_overrides,
    )
    return body, athlete, agreement


def setup_interim_manager_headers(manager_id: str = INTERIM_MANAGER_ID) -> dict:
    """CommitteeAdmin headers for the appointed interim manager — the
    committee-side submitter while a body is INTERIM_MANAGED."""
    return make_committee_admin_headers(manager_id)
