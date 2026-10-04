"""Farm probation cycle, welfare incidents, and the removal cascade."""
from test_helpers import (
    ApiErrorId,
    api_client,
    complete_audit,
    create_active_farm,
    create_commitment,
    create_forecast,
    create_retailer,
    get_commitment,
    get_farm,
    get_route,
    list_audit_corrective_actions,
    reinstate_farm,
    report_incident,
    resolve_incident,
    schedule_audit,
    set_clock,
    setup_route_with_stop,
    submit_corrective_action,
    validate_error,
    validate_paginated,
    validate_success,
    verify_corrective_action,
)
from test_helpers import TEST_USERS

NM = TEST_USERS["network_manager_headers"]
QM = TEST_USERS["quality_manager_headers"]


def _fail_audit_and_remediate(farm_id, audit_type, scheduled_for, complete_at,
                              finding_description):
    """Complete an audit FAILED with one MAJOR finding, then close its CA."""
    audit = schedule_audit(farm_id, audit_type, scheduled_for)
    set_clock(complete_at)
    complete_audit(audit["id"], "FAILED",
                   findings=[{"severity": "MAJOR", "description": finding_description}])
    cas = list_audit_corrective_actions(audit["id"])
    assert len(cas) == 1
    submit_corrective_action(cas[0]["id"], "remediation filed")
    verify_corrective_action(cas[0]["id"], "VERIFY_CLOSED", auditor_user_id="auditor-b")
    return audit["id"]


def test_farm_probation_cycle_first_failed_audit_keeps_certification(api):
    """PRD §2.7: "a failed audit moves an `ACTIVE` farm to `PROBATION` while its
    `certification_status` remains `CERTIFIED` until the certification clock
    says otherwise."
    PRD §3.2: "When the outcome is `FAILED`, the audit moves `SCHEDULED → FAILED`
    with the same auditor and completion stamps; one corrective action is
    created per entry in `findings`, and if the farm is currently `ACTIVE` it
    drops to `PROBATION` with its `version` incremented"

    Design: Difficulty/non_linear_state_machine/farm_probation_cycle_and_parallel_cert_dimension
    """
    bundle = create_active_farm(name="Willow Creek Farm")
    farm_id = bundle["farm"]["id"]

    audit2 = schedule_audit(farm_id, "ANNUAL", "2026-10-05T00:00:00Z")
    set_clock("2026-10-05T10:00:00Z")
    complete_audit(audit2["id"], "FAILED",
                   findings=[{"severity": "MAJOR", "description": "torn perimeter fencing"}])

    farm = get_farm(farm_id)
    assert farm["status"] == "PROBATION", f"FAILED audit probates the farm, got {farm['status']}"
    assert farm["certification_status"] == "CERTIFIED", (
        "the certification dimension stays CERTIFIED — the two state dimensions "
        "evolve independently"
    )


def test_farm_probation_cycle_traversed_twice_returns_active(api):
    """PRD §3.1: "Reinstatement by a `NetworkManager` moves a farm from
    `PROBATION` or `SUSPENDED` back to `ACTIVE`, but only when the farm's record
    is clean: no corrective action on any audit of that farm may be in `OPEN`,
    `OVERDUE`, or `SUBMITTED`, and no welfare incident of the farm may still be
    `REPORTED`."
    PRD §2.7: "a failed audit moves an `ACTIVE` farm to `PROBATION` while its
    `certification_status` remains `CERTIFIED` until the certification clock
    says otherwise."

    Design: Difficulty/non_linear_state_machine/farm_probation_cycle_and_parallel_cert_dimension
    """
    bundle = create_active_farm(name="Willow Creek Farm")
    farm_id = bundle["farm"]["id"]

    # First ACTIVE -> PROBATION -> ACTIVE traversal.
    _fail_audit_and_remediate(
        farm_id, "ANNUAL", "2026-10-05T00:00:00Z", "2026-10-05T10:00:00Z",
        "torn perimeter fencing",
    )
    assert get_farm(farm_id)["status"] == "PROBATION"
    reinstated = reinstate_farm(farm_id)
    assert reinstated["status"] == "ACTIVE"

    # Second traversal of the same cycle.
    _fail_audit_and_remediate(
        farm_id, "FOR_CAUSE", "2026-11-10T00:00:00Z", "2026-11-10T10:00:00Z",
        "fencing damaged again",
    )
    farm = get_farm(farm_id)
    assert farm["status"] == "PROBATION", "the cycle is traversed a second time"

    reinstated2 = reinstate_farm(farm_id)
    assert reinstated2["status"] == "ACTIVE"
    final = get_farm(farm_id)
    assert final["certification_status"] == "CERTIFIED", (
        "last pass 2026-09-03 is within 365 days of 2026-11-10 — CERTIFIED throughout"
    )


def test_incident_low_resolve_none_leaves_farm_active(api):
    """PRD §3.4: "A disposition of `NONE` leaves the farm untouched."
    PRD §3.4: "The incident moves to the terminal `RESOLVED` state, stamping the
    chosen `disposition` and the `resolved_at` instant, and the disposition
    drives the farm."

    Design: Corner/state_machines/incident_low_resolve_none_leaves_farm_active
    """
    bundle = create_active_farm(name="Calm Farm")
    farm_id = bundle["farm"]["id"]

    incident = report_incident(
        farm_id,
        role_headers=QM,
        severity="LOW",
        incident_type="RECORD_KEEPING",
        description="minor log gap found during visit",
    )
    assert incident["status"] == "REPORTED"
    version_before = get_farm(farm_id)["version"]

    resolved = resolve_incident(incident["id"], "NONE", resolution_notes="no action required")
    assert resolved["status"] == "RESOLVED"
    assert resolved["disposition"] == "NONE"

    farm = get_farm(farm_id)
    assert farm["status"] == "ACTIVE"
    assert farm["version"] == version_before, (
        "resolve with disposition NONE performs no farm mutation at all"
    )


def _setup_incident_removal():
    """ACTIVE farm with contract, retailer, forecast (week 2026-09-14), a
    40-dozen ACTIVE commitment, and a SCHEDULED 3-case stop on a capacity-10
    route dated 2026-09-21; clock at 2026-09-08T12:00:00Z; CRITICAL incident
    reported by an auditor."""
    bundle = create_active_farm(name="Fox Den Farm")
    farm_id = bundle["farm"]["id"]
    retailer = create_retailer()
    create_forecast(farm_id, "2026-09-14", "AUTUMN", "NONE")
    commitment = create_commitment(retailer["id"], farm_id, "2026-09-14", 40)
    route_bundle = setup_route_with_stop(
        farm_id, route_date="2026-09-21", planned_cases=3, capacity_cases=10
    )
    route_id = route_bundle["route"]["id"]
    set_clock("2026-09-08T12:00:00Z")
    from test_helpers import make_auditor_headers

    incident = report_incident(
        farm_id,
        role_headers=make_auditor_headers("auditor-c"),
        severity="CRITICAL",
        incident_type="PREDATOR_BREACH",
        description="coyote breached the perimeter, flock losses",
    )
    return {
        "farm_id": farm_id,
        "contract": bundle["contract"],
        "commitment": commitment,
        "route_id": route_id,
        "incident": incident,
    }


def test_incident_critical_report_suspends_then_removal_decertifies(api):
    """PRD §3.4: "Reporting is a creation, not a transition — but a `CRITICAL`
    report cascades immediately, before any resolution: if the farm is `ACTIVE`
    or `PROBATION`, it moves to `SUSPENDED` at report time, its `version`
    increments, and the stop-skip cascade runs."
    PRD §3.4: "`REMOVAL` removes the farm outright, running the full removal
    cascade below."
    PRD §3.4: "First, the farm's `status` becomes `REMOVED`, its
    `certification_status` becomes `DECERTIFIED`, the `removal_reason` is set,
    and the farm's `version` increments by one."

    Design: Difficulty/transitive_cascade/incident_removal_cascades_contract_termination_commitment_cancellation
    """
    ctx = _setup_incident_removal()
    farm_id = ctx["farm_id"]

    # Report-time cascade: CRITICAL auto-suspends and skips the stop.
    farm_at_report = get_farm(farm_id)
    assert farm_at_report["status"] == "SUSPENDED", (
        f"CRITICAL report suspends the farm immediately, got {farm_at_report['status']}"
    )
    route_at_report = get_route(ctx["route_id"])
    stop_at_report = next(s for s in route_at_report["stops"] if s["stop_sequence"] == 1)
    assert stop_at_report["status"] == "SKIPPED"

    resolve_incident(ctx["incident"]["id"], "REMOVAL",
                     resolution_notes="repeated predator breaches; farm removed from network")

    farm = get_farm(farm_id)
    assert farm["status"] == "REMOVED"
    assert farm["certification_status"] == "DECERTIFIED"


def test_incident_removal_terminates_contract_and_cancels_commitment(api):
    """PRD §3.4: "Second, the farm's contract in `ACTIVE` status, if one exists,
    moves to `TERMINATED`. Third, every supply commitment of the farm still
    `ACTIVE` whose `week_start` falls strictly after the current date moves to
    `CANCELLED` — commitments for the current or past weeks are left for
    settlement to judge. Fourth, every stop naming the farm still `SCHEDULED` on
    any `PLANNED` route flips to `SKIPPED`, with route loads recomputed."

    Design: Difficulty/transitive_cascade/incident_removal_cascades_contract_termination_commitment_cancellation
    """
    ctx = _setup_incident_removal()
    farm_id = ctx["farm_id"]

    resolve_incident(ctx["incident"]["id"], "REMOVAL",
                     resolution_notes="repeated predator breaches; farm removed from network")

    rows, _ = validate_paginated(api.list_contracts(farm_id, NM))
    by_id = {row["id"]: row for row in rows}
    assert by_id[ctx["contract"]["id"]]["status"] == "TERMINATED", (
        "the removal cascade terminates the farm's ACTIVE contract"
    )

    commitment = get_commitment(ctx["commitment"]["id"])
    assert commitment["status"] == "CANCELLED", (
        "week_start 2026-09-14 is strictly after the current date 2026-09-08 — "
        "the cascade cancels the commitment"
    )

    route = get_route(ctx["route_id"])
    stop = next(s for s in route["stops"] if s["stop_sequence"] == 1)
    assert stop["status"] == "SKIPPED"
    assert route["available_cases"] == 10, (
        f"skipping the 3-case stop restores full capacity, got {route['available_cases']}"
    )
