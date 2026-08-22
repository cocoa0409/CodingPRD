"""Identity, authorisation and stale-view protection: headers, role-per-action,
segregation of duties, subcontractor ownership and the turnaround version check."""
from test_helpers import (
    ApiErrorId,
    create_approved_subcontractor,
    create_certified_agent,
    create_flight_bank,
    create_open_station,
    create_turn,
    get_agent,
    get_flight_bank,
    get_station,
    get_turn,
    get_turn_resource,
    make_contract_auditor_headers,
    make_duty_officer_headers,
    make_safety_officer_headers,
    make_station_manager_headers,
    make_subcontractor_admin_headers,
    publish_bank,
    report_incident,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Queue B: rbac / missing_role_header_returns_unauthenticated
# ---------------------------------------------------------------------------

def test_a_request_without_identity_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request — without exception, including reads and
    including the test-driving clock endpoint — must carry two headers:
    `X-User-ID`, which identifies the acting user, and `X-User-Role`, which
    declares the capacity that user is acting in."
    PRD §2.1: "If either header is absent, or if `X-User-Role` carries any
    string other than those six, the request is rejected with
    `ERR_UNAUTHENTICATED` and HTTP 401."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    set_clock("2026-04-01T00:00:00Z")

    resp = api.create_station({"iata_code": "ZRH"},
                              {"Content-Type": "application/json"})
    error = validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value, (
        "authentication is decided before the payload is examined")


# ---------------------------------------------------------------------------
# Queue B: rbac / contract_auditor_cannot_schedule_a_turn
# ---------------------------------------------------------------------------

def test_a_contract_auditor_may_not_schedule_a_turnaround(api):
    """PRD §2.1: "If the headers are well-formed but the role is not one of the
    roles listed against the requested endpoint, the request is rejected with
    `ERR_FORBIDDEN_ROLE` and HTTP 403."
    PRD §3.4: "The **turnaround** is the unit of work. A `DutyOfficer`
    schedules one inside a bank by supplying the `station_id`, the
    `flight_bank_id`, the carrier's `flight_number`, the `turn_type`, and the
    scheduled on-block and off-block instants `scheduled_in` and
    `scheduled_out`."

    Design: Corner/rbac/contract_auditor_cannot_schedule_a_turn
    """
    station = create_open_station()
    bank = create_flight_bank(station["id"], planned_headcount=1)

    resp = api.create_turn(
        {"station_id": station["id"], "flight_bank_id": bank["id"],
         "flight_number": "LX318", "turn_type": "TOWING_ONLY",
         "scheduled_in": "2026-04-10T06:00:00Z",
         "scheduled_out": "2026-04-10T06:20:00Z"},
        make_contract_auditor_headers("ca-01"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
    assert get_flight_bank(bank["id"])["turn_count"] == 0


# ---------------------------------------------------------------------------
# Queue B: rbac / duty_officer_cannot_approve_a_staffing_plan
# ---------------------------------------------------------------------------

def test_staffing_actions_are_authorised_per_action_not_per_endpoint(api):
    """PRD §2.1: "Staffing `SUBMIT` and `REVISE` are open to `DutyOfficer`
    only; staffing `APPROVE` and `REJECT` are open to `StationManager` only."
    PRD §2.1: "A caller whose role is listed on the endpoint but not on the
    requested action receives the same `ERR_FORBIDDEN_ROLE` with HTTP 403."

    Design: Corner/rbac/duty_officer_cannot_approve_a_staffing_plan
    """
    station = create_open_station()
    bank = create_flight_bank(station["id"], planned_headcount=1)
    create_turn(station["id"], bank["id"])
    publish_bank(bank["id"])

    manager_submit = api.staffing_transition(
        bank["id"], {"action": "SUBMIT"}, make_station_manager_headers("sm-01"))
    validate_error(manager_submit, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    submitted = validate_success(api.staffing_transition(
        bank["id"], {"action": "SUBMIT"}, make_duty_officer_headers("do-01")))
    assert submitted["staffing_status"] == "SUBMITTED"

    officer_approve = api.staffing_transition(
        bank["id"], {"action": "APPROVE"}, make_duty_officer_headers("do-01"))
    validate_error(officer_approve, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    approved = validate_success(api.staffing_transition(
        bank["id"], {"action": "APPROVE"}, make_station_manager_headers("sm-01")))
    assert approved["staffing_status"] == "APPROVED"
    assert get_flight_bank(bank["id"])["last_staffing_decision_by_user_id"] == "sm-01"


# ---------------------------------------------------------------------------
# Queue B: rbac / incident_reporter_cannot_investigate_and_findings_issuer_cannot_close
# ---------------------------------------------------------------------------

def test_segregation_of_duties_is_enforced_on_the_acting_user_id(api):
    """PRD §2.1: "Independently of role, three operations enforce **segregation
    of duties** on the acting `X-User-ID` value rather than on the role name:
    the user who reported an incident may not be the user who takes it into
    investigation; the user who issued findings on an incident may not be the
    user who closes it; and the user who finalized a billing period may not be
    the user who approves it."
    PRD §2.1: "Note that this is a check on identity, not on capability — a
    second `SafetyOfficer` may perfectly well investigate a report filed by the
    first."

    Design: Corner/rbac/incident_reporter_cannot_investigate_and_findings_issuer_cannot_close
    """
    station = create_open_station()
    incident = report_incident(station["id"], user_id="safety-01",
                               role="SafetyOfficer", incident_type="NEAR_MISS",
                               severity="MINOR",
                               occurred_at="2026-03-30T09:00:00Z")
    assert incident["reported_by_user_id"] == "safety-01"

    self_investigation = api.incident_transition(
        incident["id"], {"action": "INVESTIGATE"},
        make_safety_officer_headers("safety-01"))
    validate_error(self_investigation, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    investigated = validate_success(api.incident_transition(
        incident["id"], {"action": "INVESTIGATE"},
        make_safety_officer_headers("safety-02")))
    assert investigated["status"] == "UNDER_INVESTIGATION"
    assert investigated["investigator_user_id"] == "safety-02"

    issued = validate_success(api.incident_transition(
        incident["id"],
        {"action": "ISSUE_FINDINGS", "root_cause_code": "COMMS_BREAKDOWN",
         "liability_party": "HANDLER"}, make_safety_officer_headers("safety-02")))
    assert issued["findings_issued_by_user_id"] == "safety-02"

    self_closure = api.incident_transition(
        incident["id"], {"action": "CLOSE"},
        make_safety_officer_headers("safety-02"))
    validate_error(self_closure, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    closed = validate_success(api.incident_transition(
        incident["id"], {"action": "CLOSE"},
        make_safety_officer_headers("safety-03")))
    assert closed["status"] == "CLOSED"
    assert closed["closed_by_user_id"] == "safety-03"


# ---------------------------------------------------------------------------
# Queue B: rbac / subcontractor_admin_cannot_register_an_agent_for_another_firm
# ---------------------------------------------------------------------------

def test_a_subcontractor_admin_registers_agents_only_for_its_own_firm(api):
    """PRD §2.1: "Concretely, a `SubcontractorAdmin` registering an agent must
    supply a `subcontractor_id` equal to `X-User-ID`, and a
    `SubcontractorAdmin` issuing an endorsement must name an agent whose
    `subcontractor_id` equals `X-User-ID`. A violation of either is rejected
    with `ERR_OWNERSHIP_VIOLATION` and HTTP 403."
    PRD §2.1: "When `X-User-Role` is `SubcontractorAdmin`, `X-User-ID` is the
    `id` of the acting `Subcontractor`; ownership checks on any resource that
    references a `Subcontractor` compare that resource's subcontractor foreign
    key to `X-User-ID`."

    Design: Corner/rbac/subcontractor_admin_cannot_register_an_agent_for_another_firm
    """
    station = create_open_station()
    own_firm = create_approved_subcontractor(station["id"],
                                             legal_name="Alpine Ramp AG")
    other_firm = create_approved_subcontractor(station["id"],
                                               legal_name="Rhone Handling SA")

    cross_firm = api.create_agent(
        {"station_id": station["id"], "employee_code": "E020",
         "full_name": "Dana Vogel", "subcontractor_id": other_firm["id"]},
        make_subcontractor_admin_headers(own_firm["id"]))
    validate_error(cross_firm, ApiErrorId.ERR_OWNERSHIP_VIOLATION, 403)

    own_agent = validate_success(api.create_agent(
        {"station_id": station["id"], "employee_code": "E021",
         "full_name": "Eli Brand", "subcontractor_id": own_firm["id"]},
        make_subcontractor_admin_headers(own_firm["id"])), 201)
    assert own_agent["employment_type"] == "SUBCONTRACTED"
    assert own_agent["subcontractor_id"] == own_firm["id"]
    assert own_agent["status"] == "ACTIVE"
    assert own_agent["certification_posture"] == "LAPSED"


# ---------------------------------------------------------------------------
# Queue B: cross_cutting_complexity_layers /
#          stale_expected_turn_version_returns_412_and_fresh_version_succeeds
# ---------------------------------------------------------------------------

def test_stale_expected_turn_version_is_refused_then_retried_successfully(api):
    """PRD §2.8: "Creating a resource occupation requires the non-optional
    field `expected_turn_version`, carrying the client's last observed
    `version` of the target `Turn`. If that value does not equal the
    turnaround's live `version` at the moment the write is processed, the
    request is rejected with `ERR_STALE_TURN_VERSION` and HTTP 412."
    PRD §2.8: "Adding a second, third or fourth occupation to the same
    turnaround is a perfectly legitimate repeatable operation — a client that
    re-reads the turnaround and retries with the fresh `version` succeeds — so
    this is not a state precondition in disguise."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_turn_version_returns_412_and_fresh_version_succeeds
    """
    station = create_open_station()
    bank = create_flight_bank(station["id"], planned_headcount=2)
    turn = create_turn(station["id"], bank["id"], turn_type="NARROWBODY_QUICK",
                       scheduled_out="2026-04-10T06:30:00Z")
    first_agent = create_certified_agent(station["id"], employee_code="E001",
                                         full_name="Ana Ruiz")
    second_agent = create_certified_agent(station["id"], employee_code="E002",
                                          full_name="Bo Keller")
    original_version = turn["version"]

    def occupation_payload(agent_id, expected_version):
        return {"turn_id": turn["id"], "resource_kind": "AGENT",
                "agent_id": agent_id, "role_on_turn": "RAMP",
                "window_start": "2026-04-10T05:50:00Z",
                "window_end": "2026-04-10T06:40:00Z",
                "expected_turn_version": expected_version}

    first = validate_success(api.create_turn_resource(
        occupation_payload(first_agent["id"], original_version),
        make_duty_officer_headers()), 201)

    stale = api.create_turn_resource(
        occupation_payload(second_agent["id"], original_version),
        make_duty_officer_headers())
    validate_error(stale, ApiErrorId.ERR_STALE_TURN_VERSION, 412)

    turn = get_turn(turn["id"])
    assert turn["assigned_agent_count"] == 1
    assert turn["version"] == original_version + 1

    second = validate_success(api.create_turn_resource(
        occupation_payload(second_agent["id"], turn["version"]),
        make_duty_officer_headers()), 201)

    final_turn = get_turn(turn["id"])
    assert final_turn["assigned_agent_count"] == 2
    assert final_turn["version"] == turn["version"] + 1
    assert get_turn_resource(first["id"])["status"] == "RESERVED"
    assert get_turn_resource(second["id"])["status"] == "RESERVED"
    assert get_agent(first_agent["id"])["assigned_duty_minutes"] == 50
    assert get_agent(second_agent["id"])["assigned_duty_minutes"] == 50


# ---------------------------------------------------------------------------
# Queue B: validations / incident_occurred_at_after_the_logical_clock_is_rejected
# ---------------------------------------------------------------------------

def test_an_incident_reported_from_the_future_is_rejected(api):
    """PRD §3.8: "The report names the `station_id` where the event happened,
    an `incident_type` of `AIRCRAFT_DAMAGE`, `GSE_DAMAGE`, `PERSONAL_INJURY` or
    `NEAR_MISS`, a `severity` of `MINOR`, `MAJOR` or `CRITICAL`, and the
    `occurred_at` instant, which must not be later than the current logical
    clock — a report of the future is rejected with `ERR_INVALID_REQUEST`."
    PRD §2.5: "Before any client has moved it, the logical clock reads exactly
    `2026-08-01T00:00:00Z`, and it must not fall back to real time under any
    circumstance."

    Design: Corner/validations/incident_occurred_at_after_the_logical_clock_is_rejected
    """
    station = create_open_station(clock="2026-04-01T00:00:00Z")

    resp = api.create_incident(
        {"station_id": station["id"], "incident_type": "NEAR_MISS",
         "severity": "MINOR", "occurred_at": "2026-04-02T00:00:00Z"},
        make_duty_officer_headers("duty-01"))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    station = get_station(station["id"])
    assert station["open_major_incident_count"] == 0
    assert station["oversight_posture"] == "NORMAL"
    rows, meta = validate_paginated(api.list_incidents(
        make_safety_officer_headers(), {"station_id": station["id"]}))
    assert meta["total_count"] == 0
    assert rows == []
