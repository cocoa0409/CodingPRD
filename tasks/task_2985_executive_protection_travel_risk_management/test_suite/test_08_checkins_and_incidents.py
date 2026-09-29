"""Check-in cadence, the consent boundary, duress and the incident triage fork."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx

INCIDENT_CLOCK = "2026-09-10T06:00:00Z"
GROUND_VENDOR = {
    "vendor_name": "Lisboa Ground Security",
    "vendor_type": c.VENDOR_GROUND_SECURITY,
    "country_code": c.COUNTRY_PT,
    "max_concurrent_engagements": 2,
    "sla_response_minutes": 60,
    "hourly_rate_cents": 20_000,
    "retainer_cents": 100_000,
}


def _incident_row(api, dep, trip_id, incident_id):
    """Incidents have no single-resource read, so re-observe one through the list."""
    rows, _meta = validate_paginated(api.list_incidents(trip_id, dep.mgr))
    matches = [row for row in rows if row["id"] == incident_id]
    assert len(matches) == 1, "the incident must be discoverable from its trip"
    return matches[0]


def _incident_engagements(api, dep, incident_id):
    return validate_paginated(
        api.list_vendor_engagements(dep.mgr, incident_id=incident_id)
    )


def _extraction_world(api):
    """An approved, in-flight trip carrying a running detail and a future one."""
    w = fx.bootstrap_world(api)
    dep = w.dep
    w.drv_id = fx.register_staff(api, "Dee Driver", c.STAFF_ROLE_ANALYST, 9_000)["id"]
    w.vendor = fx.register_vendor(api, dep, **GROUND_VENDOR)
    trip = fx.create_trip(
        api,
        dep,
        w.exec_id,
        w.ra_id,
        insurance_policy_id=w.policy_id,
        depart_at="2026-09-10T00:00:00Z",
        return_at="2026-09-11T00:00:00Z",
        cost_allocation_method=c.ALLOCATION_PRORATA,
    )
    leg = fx.add_leg(
        api,
        dep,
        trip["id"],
        arrive_at="2026-09-10T00:00:00Z",
        depart_at="2026-09-10T12:00:00Z",
    )
    w.trip_id = trip["id"]
    w.leg_id = leg["id"]
    w.pda_a = fx.assign_detail(
        api,
        dep,
        leg["id"],
        dep.lead_id,
        c.DETAIL_LEAD_AGENT,
        "2026-09-10T00:00:00Z",
        "2026-09-10T12:00:00Z",
    )
    w.pda_b = fx.assign_detail(
        api,
        dep,
        leg["id"],
        w.drv_id,
        c.DETAIL_DRIVER,
        "2026-09-10T08:00:00Z",
        "2026-09-10T12:00:00Z",
    )
    fx.record_advance(api, dep, leg["id"], c.ITEM_ROUTE_SURVEY)
    w.submitted = fx.submit_trip(api, dep, trip["id"])
    fx.ack_briefing(api, w.exec_id, trip["id"])
    w.approved = fx.decide_trip(api, dep, trip["id"], c.DECISION_APPROVE)
    fx.set_clock(api, INCIDENT_CLOCK)
    w.incident = fx.report_incident(
        api,
        dep,
        trip["id"],
        affected_leg_sequence_no=1,
        incident_type=c.INCIDENT_UNREST,
        severity=5,
        narrative="Riot cordon two blocks from the venue",
    )
    return w


def test_the_extraction_fork_stands_down_only_the_detail_not_yet_under_way(api):
    """The future driver is voided while the lead agent standing by the principal stays.

    PRD §3.8: "Uniquely to this branch, the standing detail is stood down: every protective-detail assignment on the trip's legs whose `status` is `CONFIRMED` and whose `starts_at` is strictly after the current clock reading moves `CONFIRMED → CANCELLED` with `cost_cents` forced to 0, `cost_basis` set to `VOID` and `cancelled_reason` set to `EXTRACTION`."

    Design: Difficulty/non_linear_state_machine/incident_extraction_fork_cancels_only_future_assignments_then_joins
    """
    w = _extraction_world(api)
    dep = w.dep

    a.assert_cents(
        w.submitted["provisional_security_cost_cents"],
        165_600,
        "provisional_security_cost_cents",
    )
    assert w.incident["status"] == c.INCIDENT_REPORTED
    assert w.incident["duress_flag"] is False

    triaged = validate_success(
        api.triage_incident(
            w.incident["id"], f.triage_payload(c.TRACK_EXTRACTION), dep.mgr
        )
    )
    assert triaged["status"] == c.INCIDENT_EXTRACTION_ACTIVE
    assert triaged["response_track"] == c.TRACK_EXTRACTION
    assert triaged["triaged_at"] == "2026-09-10T06:00:00.000Z"

    cancelled = validate_success(api.get_detail_assignment(w.pda_b["id"], dep.mgr))
    assert cancelled["status"] == c.ASSIGNMENT_CANCELLED
    assert cancelled["cancelled_reason"] == c.CANCELLED_REASON_EXTRACTION
    assert cancelled["cost_basis"] == c.COST_BASIS_VOID
    a.assert_cents(cancelled["cost_cents"], 0, "cancelled cost_cents")

    running = validate_success(api.get_detail_assignment(w.pda_a["id"], dep.mgr))
    assert running["status"] == c.ASSIGNMENT_CONFIRMED, (
        "an assignment already under way is never stood down"
    )
    a.assert_cents(running["cost_cents"], 135_000, "running cost_cents")

    a.assert_staff_hours(fx.read_staff(api, dep, w.drv_id), committed=0)
    a.assert_staff_hours(fx.read_staff(api, dep, dep.lead_id), committed=12)
    assert fx.read_leg(api, dep, w.leg_id)["lead_agent_covered"] is True

    trip = fx.read_trip(api, dep, w.trip_id)
    a.assert_trip_states(trip, c.APPROVAL_APPROVED, c.READINESS_DEGRADED)
    assert trip["check_in_interval_hours"] == 2
    a.assert_cents(
        trip["provisional_security_cost_cents"],
        165_600,
        "provisional_security_cost_cents",
    )
    executive = fx.read_executive(api, dep, w.exec_id)
    assert executive["open_degraded_trip_count"] == 1
    a.assert_budget_ledger(executive, committed=165_600, spent=0)

    rows, meta = _incident_engagements(api, dep, w.incident["id"])
    assert meta["total_count"] == 1
    engagement = rows[0]
    assert engagement["vendor_id"] == w.vendor["id"]
    assert engagement["trip_leg_id"] == w.leg_id
    assert engagement["engagement_purpose"] == c.VENDOR_GROUND_SECURITY
    assert engagement["status"] == c.ENGAGEMENT_ACTIVE
    assert engagement["starts_at"] == "2026-09-10T06:00:00.000Z"
    assert engagement["ends_at"] == "2026-09-11T06:00:00.000Z"
    assert engagement["engagement_hours"] == 24
    a.assert_cents(
        engagement["engagement_cost_cents"], 580_000, "engagement_cost_cents"
    )
    a.assert_vendor_hours(fx.read_vendor(api, dep, w.vendor["id"]), 24)


def test_the_join_gate_holds_until_the_extraction_engagement_is_settled(api):
    """Resolve is refused while the branch is still draining, then the cost freezes.

    PRD §3.8: "Resolving an incident requires its `status` to be `MEDEVAC_ACTIVE`, `SHELTER_ACTIVE` or `EXTRACTION_ACTIVE`, and requires that every vendor engagement whose `incident_id` names this incident has a `status` of `COMPLETED` or `CANCELLED` — an engagement still `ACTIVE` blocks the join with `ERR_INCIDENT_INVALID_STATE`."

    Design: Difficulty/non_linear_state_machine/incident_extraction_fork_cancels_only_future_assignments_then_joins
    """
    w = _extraction_world(api)
    dep = w.dep
    incident_id = w.incident["id"]
    fx.triage_incident(api, dep, incident_id, c.TRACK_EXTRACTION)

    rows, _meta = _incident_engagements(api, dep, incident_id)
    engagement_id = rows[0]["id"]

    blocked = api.resolve_incident(
        incident_id,
        dep.mgr,
        f.resolve_payload(resolution_note="join gate closed while the engagement runs"),
    )
    validate_error(blocked, e.ERR_INCIDENT_INVALID_STATE, 409)
    assert (
        _incident_row(api, dep, w.trip_id, incident_id)["status"]
        == c.INCIDENT_EXTRACTION_ACTIVE
    )

    completed = fx.complete_engagement(api, dep, engagement_id)
    assert completed["status"] == c.ENGAGEMENT_COMPLETED
    a.assert_cents(
        completed["engagement_cost_cents"], 580_000, "engagement_cost_cents"
    )
    a.assert_vendor_hours(fx.read_vendor(api, dep, w.vendor["id"]), 0)

    resolved = validate_success(
        api.resolve_incident(
            incident_id,
            dep.mgr,
            f.resolve_payload(resolution_note="principal extracted, cordon cleared"),
        )
    )
    assert resolved["status"] == c.INCIDENT_RESOLVED
    assert resolved["resolved_at"] == "2026-09-10T06:00:00.000Z"

    closed = validate_success(api.close_incident(incident_id, dep.dir))
    assert closed["status"] == c.INCIDENT_CLOSED
    assert closed["closed_at"] == "2026-09-10T06:00:00.000Z"
    a.assert_cents(closed["response_cost_cents"], 580_000, "response_cost_cents")
    assert closed["response_cost_cents"] != 580_000 + c.MEDEVAC_SURCHARGE_CENTS, (
        "the evacuation surcharge belongs to the medevac track alone"
    )


def _medevac_world(api):
    """An approved trip whose verified cover is a kidnap-and-ransom policy."""
    w = fx.bootstrap_world(
        api, policy_type=c.POLICY_KIDNAP_RANSOM, coverage_cents=60_000_000
    )
    dep = w.dep
    assert w.policy["status"] == c.POLICY_VERIFIED
    assert w.policy["policy_type"] == c.POLICY_KIDNAP_RANSOM
    w.evac_vendor = fx.register_vendor(
        api,
        dep,
        vendor_name="AeroMed Lisboa",
        vendor_type=c.VENDOR_MEDICAL_EVAC,
        country_code=c.COUNTRY_PT,
        max_concurrent_engagements=2,
        sla_response_minutes=30,
        hourly_rate_cents=20_000,
        retainer_cents=100_000,
    )
    w.gs_vendor = fx.register_vendor(
        api,
        dep,
        vendor_name="Guarda Atlantica",
        vendor_type=c.VENDOR_GROUND_SECURITY,
        country_code=c.COUNTRY_PT,
        max_concurrent_engagements=2,
        sla_response_minutes=45,
        hourly_rate_cents=10_000,
        retainer_cents=50_000,
    )
    w = fx.trip_world(
        api,
        world=w,
        trip={"cost_allocation_method": c.ALLOCATION_PRORATA},
    )
    w.submitted = fx.submit_trip(api, dep, w.trip_id)
    fx.ack_briefing(api, w.exec_id, w.trip_id)
    w.approved = fx.decide_trip(api, dep, w.trip_id, c.DECISION_APPROVE)
    fx.set_clock(api, "2026-09-10T10:00:00Z")
    w.incident = fx.report_incident(
        api,
        dep,
        w.trip_id,
        affected_leg_sequence_no=1,
        incident_type=c.INCIDENT_NATURAL_DISASTER,
        severity=3,
        narrative="wildfire closing the coastal corridor",
    )
    return w


def test_the_medevac_fork_is_refused_over_the_policy_type_it_carries(api):
    """A verified kidnap-and-ransom policy clears the submit gate but not the medevac one.

    PRD §3.8: "The trip must have a non-null `insurance_policy_id` whose `status` is `VERIFIED` and whose `policy_type` is `MEDICAL_EVAC`, or the triage is rejected with `ERR_INSURANCE_NOT_VERIFIED`"

    Design: Difficulty/cross_entity_state_dependency/medevac_triage_gated_on_carried_policy_type_while_shelter_branch_is_not
    """
    w = _medevac_world(api)
    dep = w.dep

    a.assert_cents(
        w.submitted["provisional_security_cost_cents"],
        112_500,
        "provisional_security_cost_cents",
    )
    a.assert_trip_states(w.approved, c.APPROVAL_APPROVED)

    assert w.incident["status"] == c.INCIDENT_REPORTED
    assert w.incident["response_track"] is None
    assert w.incident["triaged_at"] is None
    reported_trip = fx.read_trip(api, dep, w.trip_id)
    a.assert_trip_states(reported_trip, c.APPROVAL_APPROVED, c.READINESS_DEGRADED)
    assert reported_trip["check_in_interval_hours"] == 2
    assert reported_trip["next_check_in_due_at"] == "2026-09-10T12:00:00.000Z"
    assert fx.read_executive(api, dep, w.exec_id)["open_degraded_trip_count"] == 1

    refused = api.triage_incident(
        w.incident["id"], f.triage_payload(c.TRACK_MEDEVAC), dep.mgr
    )
    validate_error(refused, e.ERR_INSURANCE_NOT_VERIFIED, 409)
    assert w.evac_vendor["activation_status"] == c.VENDOR_AVAILABLE
    assert w.evac_vendor["vendor_type"] == c.VENDOR_MEDICAL_EVAC
    assert w.evac_vendor["country_code"] == c.COUNTRY_PT, (
        "the candidate set is non-empty, so ERR_NO_ELIGIBLE_VENDOR cannot be what fired"
    )

    unchanged = _incident_row(api, dep, w.trip_id, w.incident["id"])
    assert unchanged["status"] == c.INCIDENT_REPORTED
    assert unchanged["response_track"] is None
    assert unchanged["triaged_at"] is None

    evac = fx.read_vendor(api, dep, w.evac_vendor["id"])
    a.assert_vendor_hours(evac, 0)
    assert evac["version"] == w.evac_vendor["version"]
    _rows, meta = _incident_engagements(api, dep, w.incident["id"])
    assert meta["total_count"] == 0


def test_the_shelter_fork_of_the_same_incident_needs_no_insurance_at_all(api):
    """The branch the insurer never underwrites carries no insurance precondition.

    PRD §3.8: "The shelter-in-place branch has **no insurance precondition whatsoever** — that absence is the deliberate branch divergence, because sheltering costs the department nothing an insurer would underwrite."

    Design: Difficulty/cross_entity_state_dependency/medevac_triage_gated_on_carried_policy_type_while_shelter_branch_is_not
    """
    w = _medevac_world(api)
    dep = w.dep
    validate_error(
        api.triage_incident(
            w.incident["id"], f.triage_payload(c.TRACK_MEDEVAC), dep.mgr
        ),
        e.ERR_INSURANCE_NOT_VERIFIED,
        409,
    )

    sheltered = validate_success(
        api.triage_incident(
            w.incident["id"], f.triage_payload(c.TRACK_SHELTER_IN_PLACE), dep.mgr
        )
    )
    assert sheltered["status"] == c.INCIDENT_SHELTER_ACTIVE
    assert sheltered["response_track"] == c.TRACK_SHELTER_IN_PLACE
    assert sheltered["triaged_at"] == "2026-09-10T10:00:00.000Z"

    rows, meta = _incident_engagements(api, dep, w.incident["id"])
    assert meta["total_count"] == 1
    engagement = rows[0]
    assert engagement["vendor_id"] == w.gs_vendor["id"]
    assert engagement["engagement_purpose"] == c.VENDOR_GROUND_SECURITY
    assert engagement["status"] == c.ENGAGEMENT_ACTIVE
    assert engagement["starts_at"] == "2026-09-10T10:00:00.000Z"
    assert engagement["ends_at"] == "2026-09-11T10:00:00.000Z"
    assert engagement["engagement_hours"] == 24
    a.assert_cents(
        engagement["engagement_cost_cents"], 290_000, "engagement_cost_cents"
    )
    a.assert_vendor_hours(fx.read_vendor(api, dep, w.gs_vendor["id"]), 24)
    a.assert_vendor_hours(fx.read_vendor(api, dep, w.evac_vendor["id"]), 0)

    trip = fx.read_trip(api, dep, w.trip_id)
    a.assert_trip_states(trip, c.APPROVAL_APPROVED, c.READINESS_DEGRADED)
    assert trip["check_in_interval_hours"] == 2
    assert fx.read_executive(api, dep, w.exec_id)["open_degraded_trip_count"] == 1, (
        "the shelter edge must not double-charge a trip that was already degraded"
    )


def _check_in(api, w, kind, location_country_code=None, note=None):
    """File a check-in as the protectee, naming a location only when asked to."""
    payload = f.check_in_payload(kind=kind)
    if location_country_code is not None:
        payload["location_country_code"] = location_country_code
    if note is not None:
        payload["note"] = note
    return validate_success(
        api.create_check_in(w.trip_id, payload, w.exec_headers), 201
    )


def test_a_duress_report_forces_the_hourly_cadence_and_opens_its_own_incident(api):
    """One protectee-filed row moves the trip, the incident log and the protectee ledger.

    PRD §3.7: "Hop three opens an incident automatically: its `incident_type` is `UNREST`, its `severity` is 5, its `duress_flag` is true, and its `affected_leg_sequence_no` is the `sequence_no` of the lowest-numbered leg whose on-ground window contains the current clock reading, or, when no leg's window contains it, simply the lowest `sequence_no` on the trip."

    Design: Corner/state_machines/duress_check_in_forces_one_hour_cadence_and_opens_an_unrest_incident
    """
    w = fx.approved_trip_world(
        api,
        trip={"depart_at": "2026-09-10T00:00:00Z", "return_at": "2026-09-11T00:00:00Z"},
        leg={"arrive_at": "2026-09-10T00:00:00Z", "depart_at": "2026-09-10T12:00:00Z"},
    )
    dep = w.dep
    a.assert_trip_states(w.trip, c.APPROVAL_APPROVED, c.READINESS_READY)
    assert w.trip["check_in_interval_hours"] == 24
    assert w.trip["next_check_in_due_at"] == "2026-09-11T00:00:00.000Z"
    assert w.trip["duress_active"] is False
    assert w.exec_row["consent_scope"] == c.CONSENT_NONE

    fx.set_clock(api, "2026-09-10T06:00:00Z")
    row = _check_in(api, w, c.CHECK_IN_DURESS, location_country_code=c.COUNTRY_PT)

    assert row["kind"] == c.CHECK_IN_DURESS
    assert row["reported_at"] == "2026-09-10T06:00:00.000Z"
    assert row["late"] is False, "lateness is computed for scheduled rows alone"
    assert row["consent_scope_snapshot"] == c.CONSENT_NONE
    assert row["recorded_location_country_code"] is None
    assert row["location_withheld"] is True

    trip = fx.read_trip(api, dep, w.trip_id)
    assert trip["duress_active"] is True
    assert trip["check_in_interval_hours"] == 1, (
        "duress outranks the degraded floor of 2 and the LOW band's 24"
    )
    a.assert_trip_states(trip, c.APPROVAL_APPROVED, c.READINESS_DEGRADED)
    assert trip["next_check_in_due_at"] == "2026-09-10T07:00:00.000Z"
    assert trip["missed_check_in_count"] == 0

    incidents, meta = validate_paginated(api.list_incidents(w.trip_id, dep.mgr))
    assert meta["total_count"] == 1
    opened = incidents[0]
    assert opened["incident_type"] == c.INCIDENT_UNREST
    assert opened["severity"] == 5
    assert opened["duress_flag"] is True
    assert opened["status"] == c.INCIDENT_REPORTED
    assert opened["response_track"] is None
    assert opened["affected_leg_sequence_no"] == 1

    assert fx.read_executive(api, dep, w.exec_id)["open_degraded_trip_count"] == 1


def test_restoring_lead_agent_coverage_walks_the_trip_back_to_ready(api):
    """The readiness dimension is cyclic: the degraded counter goes up and back down.

    PRD §3.7: "A trip moves `DEGRADED → READY` only when all five of these hold: its `readiness_state` is `DEGRADED`, its `approval_state` is `APPROVED`, its `duress_active` is false, its `missed_check_in_count` is strictly below 2, and every one of its legs has both `advance_complete` and `lead_agent_covered` of true."

    Design: Corner/state_machines/degraded_trip_returns_to_ready_when_lead_agent_coverage_is_restored
    """
    w = fx.approved_trip_world(api)
    dep = w.dep
    leg_v0 = fx.leg_version(api, dep, w.leg_id)

    released = fx.release_assignment(api, dep, w.lead_assignment["id"], c.LEG_DEPART_AT)
    assert released["status"] == c.ASSIGNMENT_RELEASED
    assert released["cost_basis"] == c.COST_BASIS_FINAL
    assert released["final_billable_hours"] == 10
    a.assert_cents(released["cost_cents"], 112_500, "cost_cents")

    degraded_leg = fx.read_leg(api, dep, w.leg_id)
    assert degraded_leg["lead_agent_covered"] is False
    assert degraded_leg["advance_complete"] is True
    leg_v1 = degraded_leg["version"]
    assert leg_v1 > leg_v0, "the release advanced the leg past the version it carried"

    degraded_trip = fx.read_trip(api, dep, w.trip_id)
    a.assert_trip_states(degraded_trip, c.APPROVAL_APPROVED, c.READINESS_DEGRADED)
    assert degraded_trip["check_in_interval_hours"] == 2
    assert degraded_trip["briefing_ack_at"] is not None
    assert fx.read_executive(api, dep, w.exec_id)["open_degraded_trip_count"] == 1

    replacement_id = fx.register_staff(
        api, "Lou Lead", c.STAFF_ROLE_ANALYST, 9_000
    )["id"]
    replacement = validate_success(
        api.create_detail_assignment(
            f.detail_assignment_payload(
                w.leg_id,
                replacement_id,
                leg_v1,
                role_on_detail=c.DETAIL_LEAD_AGENT,
                starts_at=c.LEG_ARRIVE_AT,
                ends_at=c.LEG_DEPART_AT,
            ),
            dep.mgr,
        ),
        201,
    )
    assert replacement["status"] == c.ASSIGNMENT_CONFIRMED

    assert fx.read_leg(api, dep, w.leg_id)["lead_agent_covered"] is True
    recovered = fx.read_trip(api, dep, w.trip_id)
    a.assert_trip_states(recovered, c.APPROVAL_APPROVED, c.READINESS_READY)
    assert recovered["check_in_interval_hours"] == 24, (
        "recovery restores the plain band value with no degradation floor"
    )
    assert fx.read_executive(api, dep, w.exec_id)["open_degraded_trip_count"] == 0

    rows, meta = validate_paginated(
        api.list_detail_assignments(dep.mgr, trip_leg_id=w.leg_id)
    )
    assert meta["total_count"] == 2
    assert sorted(row["status"] for row in rows) == [
        c.ASSIGNMENT_CONFIRMED,
        c.ASSIGNMENT_RELEASED,
    ]


def test_a_scheduled_report_at_the_due_instant_re_anchors_and_ad_hoc_does_not(api):
    """Arriving exactly on the due instant is on time, and only the scheduled kind re-anchors.

    PRD §3.7: "A `SCHEDULED` check-in sets `next_check_in_due_at` to its own `reported_at` plus the interval currently in force. An `AD_HOC` check-in leaves `next_check_in_due_at` exactly as it was — reporting in early buys no extension."

    Design: Corner/calculations/on_time_scheduled_check_in_at_the_due_instant_re_anchors_the_next_one
    """
    w = fx.approved_trip_world(
        api, executive={"consent_scope": c.CONSENT_TRIP_ONLY}
    )
    dep = w.dep
    assert w.exec_row["consent_scope"] == c.CONSENT_TRIP_ONLY
    assert w.exec_row["consent_expires_at"] is None
    assert w.trip["check_in_interval_hours"] == 24
    assert w.trip["next_check_in_due_at"] == "2026-09-11T00:00:00.000Z"

    fx.set_clock(api, "2026-09-11T00:00:00Z")
    scheduled = _check_in(
        api, w, c.CHECK_IN_SCHEDULED, location_country_code=c.COUNTRY_PT
    )
    assert scheduled["reported_at"] == "2026-09-11T00:00:00.000Z"
    assert scheduled["late"] is False, "the lateness comparison is strict"
    assert scheduled["consent_scope_snapshot"] == c.CONSENT_TRIP_ONLY
    assert scheduled["recorded_location_country_code"] == c.COUNTRY_PT
    assert scheduled["location_withheld"] is False

    after_scheduled = fx.read_trip(api, dep, w.trip_id)
    assert after_scheduled["next_check_in_due_at"] == "2026-09-12T00:00:00.000Z"
    assert after_scheduled["missed_check_in_count"] == 0

    ad_hoc = _check_in(api, w, c.CHECK_IN_AD_HOC, location_country_code=c.COUNTRY_PT)
    assert ad_hoc["late"] is False
    after_ad_hoc = fx.read_trip(api, dep, w.trip_id)
    assert after_ad_hoc["next_check_in_due_at"] == "2026-09-12T00:00:00.000Z", (
        "an ad-hoc contact does not re-anchor the cadence"
    )
    assert after_ad_hoc["missed_check_in_count"] == 0
    a.assert_trip_states(after_ad_hoc, c.APPROVAL_APPROVED, c.READINESS_READY)
    assert after_ad_hoc["check_in_interval_hours"] == 24

    rows, meta = validate_paginated(api.list_check_ins(w.trip_id, dep.mgr))
    assert meta["total_count"] == 2
    assert {row["kind"] for row in rows} == {c.CHECK_IN_SCHEDULED, c.CHECK_IN_AD_HOC}


def test_only_the_second_late_scheduled_report_crosses_the_escalation_threshold(api):
    """Three rows fail to increment the counter for three different reasons.

    PRD §3.7: "Two missed contacts are the escalation threshold. When `missed_check_in_count` reaches 2, a trip whose `readiness_state` is `READY` moves `READY → DEGRADED`."

    Design: Corner/cross_cutting_complexity_layers/two_late_scheduled_check_ins_cross_the_escalation_threshold
    """
    w = fx.approved_trip_world(api, trip={"return_at": "2026-09-20T00:00:00Z"})
    dep = w.dep
    assert w.trip["check_in_interval_hours"] == 24
    assert w.trip["next_check_in_due_at"] == "2026-09-11T00:00:00.000Z"

    fx.set_clock(api, "2026-09-11T00:00:00Z")
    on_time = _check_in(
        api, w, c.CHECK_IN_SCHEDULED, location_country_code=c.COUNTRY_PT
    )
    assert on_time["late"] is False
    assert on_time["consent_scope_snapshot"] == c.CONSENT_NONE
    assert on_time["recorded_location_country_code"] is None
    assert on_time["location_withheld"] is True
    first = fx.read_trip(api, dep, w.trip_id)
    assert first["missed_check_in_count"] == 0
    assert first["next_check_in_due_at"] == "2026-09-12T00:00:00.000Z"

    fx.set_clock(api, "2026-09-12T00:00:01Z")
    one_second_late = _check_in(api, w, c.CHECK_IN_SCHEDULED)
    assert one_second_late["late"] is True
    second = fx.read_trip(api, dep, w.trip_id)
    assert second["missed_check_in_count"] == 1
    a.assert_trip_states(second, c.APPROVAL_APPROVED, c.READINESS_READY)
    assert second["check_in_interval_hours"] == 24
    assert second["next_check_in_due_at"] == "2026-09-13T00:00:01.000Z"

    fx.set_clock(api, "2026-09-13T05:00:00Z")
    ad_hoc = _check_in(api, w, c.CHECK_IN_AD_HOC)
    assert ad_hoc["late"] is False, "an ad-hoc report is never late by construction"
    third = fx.read_trip(api, dep, w.trip_id)
    assert third["missed_check_in_count"] == 1
    assert third["next_check_in_due_at"] == "2026-09-13T00:00:01.000Z"
    a.assert_trip_states(third, c.APPROVAL_APPROVED, c.READINESS_READY)

    crossing = _check_in(api, w, c.CHECK_IN_SCHEDULED)
    assert crossing["late"] is True
    fourth = fx.read_trip(api, dep, w.trip_id)
    assert fourth["missed_check_in_count"] == 2
    a.assert_trip_states(fourth, c.APPROVAL_APPROVED, c.READINESS_DEGRADED)
    assert fourth["check_in_interval_hours"] == 2
    assert fourth["next_check_in_due_at"] == "2026-09-13T07:00:00.000Z"
    assert fourth["duress_active"] is False
    assert fx.read_executive(api, dep, w.exec_id)["open_degraded_trip_count"] == 1
