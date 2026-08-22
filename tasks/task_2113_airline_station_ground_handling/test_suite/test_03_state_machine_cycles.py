"""State-machine shape: the incident investigation cycle, the flight bank's two
independent axes, terminal lockdown and the automatic turnaround promotion."""
from test_helpers import (
    ApiErrorId,
    add_agent_occupation,
    add_gse_occupation,
    assert_instant,
    assert_pct,
    close_incident,
    close_out_incident,
    create_certified_agent,
    create_flight_bank,
    create_gse_unit,
    create_open_station,
    create_turn,
    drive_bank,
    get_agent,
    get_certification,
    get_flight_bank,
    get_gse_unit,
    get_incident,
    get_station,
    get_turn,
    investigate_incident,
    issue_certification,
    issue_findings,
    make_duty_officer_headers,
    make_safety_officer_headers,
    make_station_manager_headers,
    open_station,
    publish_bank,
    reopen_incident,
    report_incident,
    revoke_certification,
    submit_staffing,
    approve_staffing,
    reject_staffing,
    revise_staffing,
    close_station,
    create_agent,
    create_station,
    set_clock,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Queue A: non_linear_state_machine /
#          incident_closed_reopened_under_investigation_cycle
# ---------------------------------------------------------------------------

def _setup_closed_major_incident():
    """A MAJOR personal-injury file reported by duty-01 and closed by
    safety-02, leaving the station's posture at NORMAL."""
    station = create_open_station()
    incident = report_incident(
        station["id"], user_id="duty-01", incident_type="PERSONAL_INJURY",
        severity="MAJOR", occurred_at="2026-03-30T09:00:00Z",
        description="Slip on stand 12")
    close_out_incident(incident["id"], liability_party="HANDLER",
                       root_cause_code="SURFACE_CONTAMINATION")
    return station, incident


def test_closed_incident_reopens_and_re_enters_investigation(api):
    """PRD §3.8: "Reopening with `REOPEN` moves the file `CLOSED → REOPENED`
    and is admissible only while `reopen_count` is strictly less than 2; a
    third attempt is refused with `ERR_REOPEN_LIMIT_REACHED`."
    PRD §3.8: "Taking the file into investigation with `INVESTIGATE` moves it
    `REPORTED → UNDER_INVESTIGATION` or `REOPENED → UNDER_INVESTIGATION` and
    stamps `investigator_user_id`; the acting `X-User-ID` must differ from
    `reported_by_user_id`."

    Design: Difficulty/non_linear_state_machine/incident_closed_reopened_under_investigation_cycle
    """
    _station, incident = _setup_closed_major_incident()
    assert get_incident(incident["id"])["status"] == "CLOSED"
    assert get_incident(incident["id"])["reopen_count"] == 0

    reopened = reopen_incident(incident["id"], user_id="safety-02",
                               note="New CCTV evidence")
    assert reopened["status"] == "REOPENED"
    assert reopened["reopen_count"] == 1

    reinvestigated = investigate_incident(incident["id"], user_id="safety-03")
    assert reinvestigated["status"] == "UNDER_INVESTIGATION", (
        "the same state is visited twice in one lifetime")
    assert reinvestigated["investigator_user_id"] == "safety-03"
    assert get_incident(incident["id"])["reopen_count"] == 1


def test_reopening_a_major_incident_pushes_the_station_back_to_enhanced(api):
    """PRD §3.8: "Reopening adds 1 to `reopen_count`, recomputes the station's
    counters and posture — the incident counts as open again, so a reopened
    `CRITICAL` file pushes the station straight back to `RESTRICTED` — and
    recomputes both compliance figures on any linked firm."
    PRD §2.10: "Otherwise it is `ENHANCED` if either `open_major_incident_count`
    is at least 1, or the station has completed at least 3 turnarounds and its
    `otp_rolling_pct` is strictly below its `otp_target_pct`."

    Design: Difficulty/non_linear_state_machine/incident_closed_reopened_under_investigation_cycle
    """
    station, incident = _setup_closed_major_incident()
    before = get_station(station["id"])
    assert before["oversight_posture"] == "NORMAL"
    assert before["open_major_incident_count"] == 0

    reopen_incident(incident["id"], user_id="safety-02", note="New CCTV evidence")
    investigate_incident(incident["id"], user_id="safety-03")

    after = get_station(station["id"])
    assert after["open_major_incident_count"] == 1
    assert after["oversight_posture"] == "ENHANCED"


# ---------------------------------------------------------------------------
# Queue A: non_linear_state_machine / flight_bank_two_status_axes_move_independently
# ---------------------------------------------------------------------------

def _setup_bank_with_one_turn():
    """A DRAFT/DRAFT bank with planned_headcount 0 holding one TOWING_ONLY
    turn, so required_headcount is 1 and publication is admissible."""
    station = create_open_station()
    bank = create_flight_bank(station["id"], planned_headcount=0)
    create_turn(station["id"], bank["id"])
    return station, bank


def test_staffing_axis_cycles_while_bank_status_stays_published(api):
    """PRD §3.3: "Nothing that moves one axis touches the other."
    PRD §3.3: "A `DutyOfficer` then revises with `REVISE`, moving
    `staffing_status` `REVISION_REQUIRED → DRAFT`; revision replaces
    `planned_headcount` when the field is supplied, leaves it untouched when it
    is omitted, and recomputes `staffing_coverage_pct` either way."
    PRD §3.3: "`DRAFT → SUBMITTED → REVISION_REQUIRED → DRAFT` is the staffing
    revision cycle, and it may be walked as many times as the station needs."

    Design: Difficulty/non_linear_state_machine/flight_bank_two_status_axes_move_independently
    """
    _station, bank = _setup_bank_with_one_turn()

    published = publish_bank(bank["id"])
    assert published["bank_status"] == "PUBLISHED"
    assert published["staffing_status"] == "DRAFT"

    submitted = submit_staffing(bank["id"])
    assert submitted["bank_status"] == "PUBLISHED"
    assert submitted["staffing_status"] == "SUBMITTED"
    assert_pct(submitted["staffing_coverage_pct"], 0.00, "staffing_coverage_pct")

    rejected = reject_staffing(bank["id"], user_id="sm-01")
    assert rejected["bank_status"] == "PUBLISHED"
    assert rejected["staffing_status"] == "REVISION_REQUIRED"

    revised = revise_staffing(bank["id"], planned_headcount=1)
    assert revised["bank_status"] == "PUBLISHED"
    assert revised["staffing_status"] == "DRAFT"
    assert_pct(revised["staffing_coverage_pct"], 100.00, "staffing_coverage_pct")

    resubmitted = submit_staffing(bank["id"])
    assert resubmitted["bank_status"] == "PUBLISHED"
    assert resubmitted["staffing_status"] == "SUBMITTED"


def test_locking_the_bank_moves_only_the_publication_axis(api):
    """PRD §3.3: "A `StationManager` locks the bank with `LOCK`, moving
    `bank_status` `PUBLISHED → LOCKED`, which is admissible only when
    `staffing_status` is `APPROVED`; once locked, no further turnaround may be
    created inside the bank."
    PRD §3.3: "Both approval and rejection stamp
    `last_staffing_decision_by_user_id` with the acting `X-User-ID`."
    PRD §3.3: "The bank's `required_headcount` is the sum, over every
    turnaround in the bank whose `status` is `SCHEDULED`, `RESOURCED`,
    `IN_PROGRESS` or `COMPLETED`, of the agent requirement of that turnaround's
    service level; turnarounds in `CANCELLED` or `DISRUPTED` are excluded from
    the sum entirely."

    Design: Difficulty/non_linear_state_machine/flight_bank_two_status_axes_move_independently
    """
    _station, bank = _setup_bank_with_one_turn()
    publish_bank(bank["id"])
    submit_staffing(bank["id"])
    reject_staffing(bank["id"], user_id="sm-01")
    revise_staffing(bank["id"], planned_headcount=1)
    submit_staffing(bank["id"])

    approved = approve_staffing(bank["id"], user_id="sm-02")
    assert approved["bank_status"] == "PUBLISHED"
    assert approved["staffing_status"] == "APPROVED"

    locked = drive_bank(bank["id"], "LOCK")
    assert locked["bank_status"] == "LOCKED"
    assert locked["staffing_status"] == "APPROVED", (
        "locking the publication axis must not disturb the staffing axis")

    bank = get_flight_bank(bank["id"])
    assert bank["required_headcount"] == 1
    assert bank["planned_headcount"] == 1
    assert bank["last_staffing_decision_by_user_id"] == "sm-02"


# ---------------------------------------------------------------------------
# Queue B: state_machines / incident_third_reopen_returns_reopen_limit_reached
# ---------------------------------------------------------------------------

def test_third_reopen_is_refused_once_the_cycle_cap_is_reached(api):
    """PRD §3.8: "Reopening with `REOPEN` moves the file `CLOSED → REOPENED`
    and is admissible only while `reopen_count` is strictly less than 2; a
    third attempt is refused with `ERR_REOPEN_LIMIT_REACHED`."
    PRD §3.8: "`CLOSED → REOPENED → UNDER_INVESTIGATION` is a genuine cycle,
    and `CLOSED` becomes effectively terminal only once `reopen_count` has
    reached 2."

    Design: Corner/state_machines/incident_third_reopen_returns_reopen_limit_reached
    """
    station = create_open_station()
    incident = report_incident(station["id"], user_id="duty-01",
                               incident_type="NEAR_MISS", severity="MINOR",
                               occurred_at="2026-03-30T09:00:00Z")
    close_out_incident(incident["id"], liability_party="HANDLER",
                       root_cause_code="COMMS_BREAKDOWN")
    for _lap in range(2):
        reopen_incident(incident["id"], user_id="safety-02")
        investigate_incident(incident["id"], user_id="safety-01")
        issue_findings(incident["id"], liability_party="HANDLER",
                       root_cause_code="COMMS_BREAKDOWN", user_id="safety-01")
        closed = close_incident(incident["id"], user_id="safety-02")
    assert closed["status"] == "CLOSED"
    assert closed["reopen_count"] == 2

    resp = api.incident_transition(incident["id"], {"action": "REOPEN"},
                                   make_safety_officer_headers("safety-02"))
    validate_error(resp, ApiErrorId.ERR_REOPEN_LIMIT_REACHED, 409)

    incident = get_incident(incident["id"])
    assert incident["status"] == "CLOSED"
    assert incident["reopen_count"] == 2


# ---------------------------------------------------------------------------
# Queue B: state_machines / issue_findings_from_reported_returns_invalid_state
# ---------------------------------------------------------------------------

def test_issuing_findings_on_a_reported_incident_is_refused(api):
    """PRD §3.8: "Issuing findings with `ISSUE_FINDINGS` moves it
    `UNDER_INVESTIGATION → FINDINGS_ISSUED` and requires both a
    `root_cause_code` and a `liability_party`, the latter being one of
    `HANDLER`, `SUBCONTRACTOR`, `CARRIER` or `THIRD_PARTY`; when the
    `incident_type` is `AIRCRAFT_DAMAGE` or `GSE_DAMAGE`, an
    `assessed_damage_cents` valuation is required as well and may not be
    negative."
    PRD §2.6: "The target record's own status admits the requested transition,
    including terminal-state lockdown, the incident reopen cap, the rule that
    billing lines may only be written against an `OPEN` period, and the rule
    that resource occupations may only be written against a `SCHEDULED` or
    `RESOURCED` turnaround."

    Design: Corner/state_machines/issue_findings_from_reported_returns_invalid_state
    """
    station = create_open_station()
    incident = report_incident(station["id"], user_id="duty-01",
                               incident_type="NEAR_MISS", severity="MINOR",
                               occurred_at="2026-03-30T09:00:00Z")

    resp = api.incident_transition(
        incident["id"],
        {"action": "ISSUE_FINDINGS", "root_cause_code": "COMMS_BREAKDOWN",
         "liability_party": "HANDLER"},
        make_safety_officer_headers("safety-01"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    incident = get_incident(incident["id"])
    assert incident["status"] == "REPORTED"
    assert incident["root_cause_code"] is None
    assert incident["liability_party"] is None
    assert incident["findings_issued_by_user_id"] is None


# ---------------------------------------------------------------------------
# Queue B: state_machines /
#          suspended_agent_returns_to_active_on_new_ramp_safety_certification
# ---------------------------------------------------------------------------

def test_fresh_ramp_safety_endorsement_reactivates_a_suspended_agent(api):
    """PRD §3.5: "Issuing one makes the owning agent recompute
    `certification_posture`, and when that agent was `SUSPENDED` and the new
    endorsement is a currently-effective `RAMP_SAFETY` at the agent's own
    station, the agent moves `SUSPENDED → ACTIVE`."
    PRD §3.5: "On revocation the endorsement's `revoked_at` is stamped from the
    logical clock, the supplied text is stored as `revoked_reason`, and
    `currency_state` becomes `REVOKED`."
    PRD §3.5: "The reverse edge exists too: `ACTIVE ↔ SUSPENDED` is a genuine
    cycle driven entirely by certification currency, and a suspended agent
    returns to `ACTIVE` the moment a fresh, currently-effective `RAMP_SAFETY`
    is issued to them at their own station."

    Design: Corner/state_machines/suspended_agent_returns_to_active_on_new_ramp_safety_certification
    """
    station = create_open_station()
    agent = create_agent(station["id"])
    old_cert = issue_certification(agent["id"], station["id"])
    revoke_certification(old_cert["id"], reason="TRAINING_AUDIT_FAILURE",
                         user_id="safety-01")

    before = get_agent(agent["id"])
    assert before["status"] == "SUSPENDED"
    assert before["certification_posture"] == "LAPSED"

    new_cert = issue_certification(agent["id"], station["id"],
                                   issued_at="2026-03-01T00:00:00Z",
                                   expires_at="2027-06-01T00:00:00Z")
    assert new_cert["currency_state"] == "CURRENT"

    after = get_agent(agent["id"])
    assert after["status"] == "ACTIVE"
    assert after["certification_posture"] == "CURRENT"

    old_cert = get_certification(old_cert["id"])
    assert old_cert["status"] == "REVOKED"
    assert old_cert["currency_state"] == "REVOKED"
    assert old_cert["revoked_reason"] == "TRAINING_AUDIT_FAILURE"


# ---------------------------------------------------------------------------
# Queue B: state_machines / open_station_twice_returns_invalid_state
# ---------------------------------------------------------------------------

def test_opening_an_already_open_station_is_refused(api):
    """PRD §3.1: "Any action that is not an edge out of the station's present
    status — opening a station that is already `OPEN`, resuming one that was
    never suspended, or anything at all attempted on a `CLOSED` station, which
    is terminal — is refused with `ERR_INVALID_STATE`."
    PRD §3.1: "Opening a station with `OPEN` moves it `PLANNED → OPEN`, stamps
    `opened_at` from the logical clock, and recomputes `oversight_posture`,
    which on a fresh station evaluates to `NORMAL`."

    Design: Corner/state_machines/open_station_twice_returns_invalid_state
    """
    set_clock("2026-04-01T00:00:00Z")
    station = create_station()
    opened = open_station(station["id"])
    assert_instant(opened["opened_at"], "2026-04-01T00:00:00Z", "opened_at")
    first_version = opened["version"]

    resp = api.station_lifecycle(station["id"], {"action": "OPEN"},
                                 make_station_manager_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    station = get_station(station["id"])
    assert station["status"] == "OPEN"
    assert station["version"] == first_version, (
        "a refused lifecycle action mutates nothing")


# ---------------------------------------------------------------------------
# Queue B: state_machines / closed_station_rejects_every_further_lifecycle_action
# ---------------------------------------------------------------------------

def test_closed_station_refuses_suspend_and_resume(api):
    """PRD §3.1: "Any action that is not an edge out of the station's present
    status — opening a station that is already `OPEN`, resuming one that was
    never suspended, or anything at all attempted on a `CLOSED` station, which
    is terminal — is refused with `ERR_INVALID_STATE`."
    PRD §3.1: "When the close succeeds, `closed_at` is stamped from the logical
    clock, every flight bank at the station whose `bank_status` is not already
    `ARCHIVED` moves to `ARCHIVED`, and every GSE unit at the station whose
    `status` is not already `RETIRED` moves to `RETIRED`."

    Design: Corner/state_machines/closed_station_rejects_every_further_lifecycle_action
    """
    station = create_open_station()
    gse = create_gse_unit(station["id"])
    closed = close_station(station["id"])
    assert closed["status"] == "CLOSED"
    assert_instant(closed["closed_at"], "2026-04-01T00:00:00Z", "closed_at")

    for action in ("SUSPEND", "RESUME"):
        resp = api.station_lifecycle(station["id"], {"action": action},
                                     make_station_manager_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    assert get_gse_unit(gse["id"])["status"] == "RETIRED"
    assert get_station(station["id"])["status"] == "CLOSED"


# ---------------------------------------------------------------------------
# Queue B: state_machines / start_turn_from_scheduled_returns_invalid_state
# ---------------------------------------------------------------------------

def test_starting_a_scheduled_turn_with_no_occupations_is_refused(api):
    """PRD §3.4: "Starting the turnaround with `START` moves it `RESOURCED →
    IN_PROGRESS`; it must be `RESOURCED`, the station must be `OPEN`, the
    owning bank's `bank_status` must be `PUBLISHED` or `LOCKED` (otherwise
    `ERR_BANK_NOT_PUBLISHED`), and its `staffing_status` must be `APPROVED`
    (otherwise `ERR_STAFFING_NOT_APPROVED`)."
    PRD §2.6: "The target record's own status admits the requested transition,
    including terminal-state lockdown, the incident reopen cap, the rule that
    billing lines may only be written against an `OPEN` period, and the rule
    that resource occupations may only be written against a `SCHEDULED` or
    `RESOURCED` turnaround."

    Design: Corner/state_machines/start_turn_from_scheduled_returns_invalid_state
    """
    station = create_open_station()
    bank = create_flight_bank(station["id"], planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])
    publish_bank(bank["id"])
    submit_staffing(bank["id"])
    approve_staffing(bank["id"])

    resp = api.turn_lifecycle(
        turn["id"], {"action": "START", "actual_in": "2026-04-10T06:00:00Z"},
        make_duty_officer_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    turn = get_turn(turn["id"])
    assert turn["status"] == "SCHEDULED"
    assert turn["actual_in"] is None


# ---------------------------------------------------------------------------
# Queue B: state_machines / publish_flight_bank_with_no_turns_returns_invalid_state
# ---------------------------------------------------------------------------

def test_publishing_an_empty_bank_is_refused(api):
    """PRD §3.3: "A `DutyOfficer` publishes the bank with `PUBLISH`, moving
    `bank_status` `DRAFT → PUBLISHED`; publication requires that the bank still
    be `DRAFT` on that axis, that the owning station be `OPEN`, and that
    `turn_count` be at least 1 — an empty bank cannot be published."
    PRD §3.3: "When `required_headcount` is zero, `staffing_coverage_pct` is
    100.00 by convention — an empty bank is fully covered."
    PRD §3.3: "The optional `planned_headcount` is the agent headcount the
    station intends to roster for the bank; it defaults to 0 and may not be
    negative."

    Design: Corner/state_machines/publish_flight_bank_with_no_turns_returns_invalid_state
    """
    station = create_open_station()
    bank = validate_success(api.create_flight_bank(
        {"station_id": station["id"], "bank_code": "AM1",
         "season_code": "SUMMER", "window_start": "2026-04-10T04:00:00Z",
         "window_end": "2026-04-10T22:00:00Z"},
        make_duty_officer_headers()), 201)
    assert bank["planned_headcount"] == 0
    assert_pct(bank["staffing_coverage_pct"], 100.00, "staffing_coverage_pct")

    resp = api.flight_bank_lifecycle(bank["id"], {"action": "PUBLISH"},
                                     make_duty_officer_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    reread = get_flight_bank(bank["id"])
    assert reread["bank_status"] == "DRAFT"
    assert reread["staffing_status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Queue B: state_machines / turn_auto_promotes_to_resourced_only_when_both_counts_are_met
# ---------------------------------------------------------------------------

def test_turn_promotes_to_resourced_only_once_both_requirements_are_met(api):
    """PRD §3.4: "When an occupation is added and the turnaround's
    `assigned_agent_count` reaches or exceeds `required_agent_count` **and**
    its `assigned_gse_count` reaches or exceeds `required_gse_count`, the
    turnaround promotes `SCHEDULED → RESOURCED`; no ledger moves on this hop,
    only the turnaround's own `status` and `version`."
    PRD §3.4: "A quick narrowbody turn needs 2 agents and 1 unit, bills at
    42000 cents, and is standard at 30 minutes."

    Design: Corner/state_machines/turn_auto_promotes_to_resourced_only_when_both_counts_are_met
    """
    station = create_open_station()
    bank = create_flight_bank(station["id"], planned_headcount=2)
    turn = create_turn(station["id"], bank["id"], turn_type="NARROWBODY_QUICK",
                       scheduled_out="2026-04-10T06:30:00Z")
    first_agent = create_certified_agent(station["id"], employee_code="E001",
                                         full_name="Ana Ruiz")
    second_agent = create_certified_agent(station["id"], employee_code="E002",
                                          full_name="Bo Keller")
    gse = create_gse_unit(station["id"])

    add_agent_occupation(turn["id"], first_agent["id"],
                         window_start="2026-04-10T05:50:00Z",
                         window_end="2026-04-10T06:40:00Z")
    assert get_turn(turn["id"])["status"] == "SCHEDULED"

    add_gse_occupation(turn["id"], gse_unit_id=gse["id"],
                       window_start="2026-04-10T05:55:00Z",
                       window_end="2026-04-10T06:35:00Z")
    assert get_turn(turn["id"])["status"] == "SCHEDULED", (
        "one agent short of the requirement, so the turn stays SCHEDULED")

    add_agent_occupation(turn["id"], second_agent["id"],
                         window_start="2026-04-10T05:50:00Z",
                         window_end="2026-04-10T06:40:00Z")
    turn = get_turn(turn["id"])
    assert turn["status"] == "RESOURCED"
    assert turn["assigned_agent_count"] == 2
    assert turn["assigned_gse_count"] == 1
    assert turn["required_agent_count"] == 2
    assert turn["required_gse_count"] == 1
    assert get_agent(first_agent["id"])["assigned_duty_minutes"] == 50
    assert get_agent(second_agent["id"])["assigned_duty_minutes"] == 50
