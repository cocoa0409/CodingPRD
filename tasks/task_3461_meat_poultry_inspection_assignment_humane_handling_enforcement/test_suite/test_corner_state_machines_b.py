"""Breadth tests: state machines — enforcement lifting, appeal lockdown, the
inspector-deactivation cascade, and humane-event adjudication."""

from test_helpers import (
    ApiErrorId,
    DISTRICT_MANAGER_HEADERS,
    PROGRAM_ADMINISTRATOR_HEADERS,
    assert_enforcement_action,
    factories as f,
    fixtures as fx,
    make_supervisory_reviewer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_enforcement_lift_requires_in_effect(api):
    """PRD §3.4: "Lifting requires the action to be `IN_EFFECT` (otherwise
    `ERR_INVALID_STATE`) and requires `abatement_evidence` of at least 20
    characters (otherwise `ERR_INVALID_REQUEST`); the evidence is stored on the
    action, which moves to the terminal `LIFTED` status."
    PRD §3.4: "A manually proposed action is born `PROPOSED` with
    `auto_created` false and no `effective_at`."

    Design: Corner/state_machines/enforcement_lift_requires_in_effect
    """
    base = fx.create_granted_establishment(api, species_classes=["CATTLE"], name="SM7 Plant")
    est_id = base["establishment"]["id"]
    inspector = fx.create_inspector(api, species_qualifications=["CATTLE"])
    fx.issue_nr(api, est_id, inspector["id"], regulation_family="SANITATION",
                description="qualifying nr")
    action = fx.create_enforcement_action(
        api, est_id, action_type="WITHHOLD_MARKS", basis="NR_LINKAGE", regulation_family="SANITATION"
    )
    assert action["status"] == "PROPOSED"

    resp = api.lift_enforcement_action(action["id"], f.lift_payload(), DISTRICT_MANAGER_HEADERS)

    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    actions = fx.list_enforcement_actions(api, est_id)
    assert len(actions) == 1 and actions[0]["status"] == "PROPOSED", "the action stays PROPOSED"


def test_appeal_decide_terminal_lockdown(api):
    """PRD §3.9: "Deciding requires the appeal to be `FILED` and the underlying
    record to be `APPEALED` — a decision attempted when either has moved on is
    rejected with `ERR_INVALID_STATE` — and the caller's `X-User-ID` must
    differ from the record's `issued_by_inspector_id`, otherwise
    `ERR_SOD_REVIEWER_IS_ISSUER` (HTTP 403); per §2.7 the state check fires
    first, so a segregation violation on a stale appeal still reports the state
    error."
    PRD §3.9: "An `outcome` of `AFFIRM` moves the appeal to `AFFIRMED` and the
    record from `APPEALED` to `ESCALATED`."

    Design: Corner/state_machines/appeal_decide_terminal_lockdown
    """
    est = fx.create_establishment(api, name="SM8 Plant", species_classes=["CATTLE"])
    pair = fx.create_inspector_pair(api, ["CATTLE"])
    record = fx.issue_nr(api, est["id"], pair["issuer"]["id"], regulation_family="HACCP",
                         description="nr under appeal")
    appeal = fx.file_appeal(api, record["id"], est["id"], grounds="grounds-text-aa")

    decided = fx.decide_appeal(api, appeal["id"], pair["reviewer"]["id"], "AFFIRM")
    assert decided["status"] == "AFFIRMED"
    assert decided["decided_by_reviewer_id"] == pair["reviewer"]["id"]

    second = api.decide_appeal(
        appeal["id"], f.appeal_decision_payload("VACATE"),
        make_supervisory_reviewer_headers(pair["reviewer"]["id"]),
    )
    validate_error(second, ApiErrorId.ERR_INVALID_STATE)

    rows, _meta = validate_paginated(api.list_appeals(record["id"], DISTRICT_MANAGER_HEADERS))
    assert len(rows) == 1
    assert rows[0]["status"] == "AFFIRMED"
    assert rows[0]["decided_by_reviewer_id"] == pair["reviewer"]["id"]
    assert fx.get_nr(api, record["id"])["status"] == "ESCALATED", "the affirm side effect persists"


def test_inspector_deactivate_cancels_scheduled_assignments(api):
    """PRD §3.2: "Deactivation, also a `ProgramAdministrator` operation, moves
    an `ACTIVE` inspector to `INACTIVE` (calling it on an already-inactive
    inspector is rejected with `ERR_INVALID_STATE`) and, in the same request,
    cancels every one of that inspector's assignments still in `SCHEDULED`
    status, moving each to `CANCELLED`."

    Design: Corner/state_machines/inspector_deactivate_cancels_scheduled_assignments
    """
    base = fx.setup_granted_with_window(
        api, species_classes=["CATTLE"], name="SM9 Plant",
        shift_type="PROCESSING", planned_line_count=2,
    )
    window = base["window"]
    insp_a = fx.create_inspector(api, full_name="Ann A", species_qualifications=["CATTLE"])
    insp_b = fx.create_inspector(api, full_name="Bob B", species_qualifications=["CATTLE"])
    a1 = fx.add_assignment(api, window["id"], insp_a["id"], line_index=1,
                           start_utc="2026-09-02T06:00:00Z", end_utc="2026-09-02T10:00:00Z")
    a2 = fx.add_assignment(api, window["id"], insp_b["id"], line_index=2,
                           start_utc="2026-09-02T06:00:00Z", end_utc="2026-09-02T10:00:00Z")
    a3 = fx.add_assignment(api, window["id"], insp_a["id"], line_index=1,
                           start_utc="2026-09-02T10:00:00Z", end_utc="2026-09-02T12:00:00Z")
    fx.confirm_assignment(api, a3["id"], insp_a["id"])

    deactivated = api.deactivate_inspector(insp_a["id"], PROGRAM_ADMINISTRATOR_HEADERS)
    deactivated_data = validate_success(deactivated, 200)
    assert deactivated_data["employment_status"] == "INACTIVE"

    a1_after = validate_success(api.get_shift_assignment(a1["id"], DISTRICT_MANAGER_HEADERS), 200)
    a2_after = validate_success(api.get_shift_assignment(a2["id"], DISTRICT_MANAGER_HEADERS), 200)
    a3_after = validate_success(api.get_shift_assignment(a3["id"], DISTRICT_MANAGER_HEADERS), 200)
    assert a1_after["status"] == "CANCELLED", "SCHEDULED assignment of the deactivated inspector"
    assert a3_after["status"] == "CONFIRMED", "CONFIRMED assignments are not cancelled"
    assert a2_after["status"] == "SCHEDULED", "the other inspector's assignment is untouched"


def test_humane_dismiss_reaches_terminal_dismissed(api):
    """PRD §3.5: "Both decisions require the event to be `REPORTED` (otherwise
    `ERR_INVALID_STATE`), and per §2.7 the state check is evaluated before the
    segregation check, so a decision attempted on an already-decided event
    reports the state error. Dismissal moves the event to the terminal
    `DISMISSED` status with no side effects."

    Design: Corner/state_machines/humane_dismiss_reaches_terminal_dismissed
    """
    est = fx.create_establishment(api, name="SM10 Plant", species_classes=["CATTLE"])
    pair = fx.create_inspector_pair(api, ["CATTLE"])
    event = fx.report_humane_event(
        api, est["id"], pair["issuer"]["id"], species="CATTLE", severity="NON_EGREGIOUS",
        description="gate latch squeal stress",
    )

    dismissed = fx.dismiss_humane_event(api, event["id"], pair["reviewer"]["id"])
    assert dismissed["status"] == "DISMISSED"

    confirm = api.confirm_humane_event(
        event["id"], make_supervisory_reviewer_headers(pair["reviewer"]["id"])
    )
    validate_error(confirm, ApiErrorId.ERR_INVALID_STATE)

    assert fx.list_enforcement_actions(api, est["id"]) == [], "dismissal has no side effects"


def test_non_egregious_confirm_creates_no_enforcement(api):
    """PRD §3.5: "Confirmation moves the event to `CONFIRMED`, and its
    consequences depend on severity. A confirmed `NON_EGREGIOUS` event triggers
    no enforcement cascade."

    Design: Corner/state_machines/non_egregious_confirm_creates_no_enforcement
    """
    est = fx.create_establishment(api, name="SM11 Plant", species_classes=["CATTLE"])
    pair = fx.create_inspector_pair(api, ["CATTLE"])
    event = fx.report_humane_event(
        api, est["id"], pair["issuer"]["id"], species="CATTLE", severity="NON_EGREGIOUS",
        description="minor prod overuse",
    )

    confirmed = fx.confirm_humane_event(api, event["id"], pair["reviewer"]["id"])

    assert confirmed["status"] == "CONFIRMED"
    assert fx.list_enforcement_actions(api, est["id"]) == []
    data = fx.get_establishment(api, est["id"])
    assert data["inspection_status"] == "INACTIVE", "no suspension without an egregious event"
    assert data["suspension_count"] == 0


def test_nr_affirm_reevaluates_escalation_threshold(api):
    """PRD §3.9: "An `outcome` of `AFFIRM` moves the appeal to `AFFIRMED` and
    the record from `APPEALED` to `ESCALATED`. The escalation count of §3.3 is
    re-evaluated at affirm time, so an affirmance that pushes the family's
    qualifying-record count to 3 within the trailing 90 days auto-creates the
    `PROPOSED` `NR_LINKAGE` suspension exactly as a direct escalation would."
    PRD §3.3: "the system counts the establishment's qualifying records in the
    same `regulation_family`: those with status `OPEN`, `RESPONSE_SUBMITTED`,
    or `ESCALATED` (records in `APPEALED` or `VACATED` never qualify), whose
    `issued_at` lies within the trailing 90 days of the logical clock inclusive
    of the boundary day, including the record that just escalated, now counted
    in its `ESCALATED` state."

    Design: Corner/state_machines/nr_affirm_reevaluates_escalation_threshold
    """
    est = fx.create_establishment(api, name="SM12 Plant", species_classes=["CATTLE"])
    pair = fx.create_inspector_pair(api, ["CATTLE"])
    # Two SANITATION records escalated directly (qualifying count 2).
    fx.issue_and_escalate_nrs(api, est["id"], pair["issuer"]["id"], "SANITATION", 2)
    # A third SANITATION record is appealed: APPEALED never qualifies.
    third = fx.issue_nr(api, est["id"], pair["issuer"]["id"], regulation_family="SANITATION",
                        description="sanitation finding three")
    appeal = fx.file_appeal(api, third["id"], est["id"], grounds="grounds-text-cc")
    assert fx.list_enforcement_actions(api, est["id"]) == [], (
        "2 qualifying records sit below the threshold of 3"
    )

    decided = fx.decide_appeal(api, appeal["id"], pair["reviewer"]["id"], "AFFIRM")

    assert decided["status"] == "AFFIRMED"
    assert fx.get_nr(api, third["id"])["status"] == "ESCALATED"
    actions = fx.list_enforcement_actions(api, est["id"])
    assert len(actions) == 1, "the affirm pushes the count to 3 and auto-creates the proposal"
    action = actions[0]
    assert_enforcement_action(action)
    assert action["action_type"] == "SUSPENSION"
    assert action["basis"] == "NR_LINKAGE"
    assert action["regulation_family"] == "SANITATION"
    assert action["status"] == "PROPOSED"
    assert action["auto_created"] is True
