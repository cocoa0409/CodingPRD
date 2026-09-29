"""State-machine breadth: legal moves, terminal states and refused repeats."""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    assert_acre_feet,
    assert_cents,
    assert_cfs,
    assert_instant,
    assert_score,
    assert_storage_conservation,
)
from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    ASSESSMENT_CERTIFIED,
    CANCEL_REASON_EVENT_STOOD_DOWN,
    CANCEL_REASON_STATE_INTERVENTION,
    CATEGORY_SEEPAGE,
    CLOCK_ORIGIN,
    DECISION_ISSUE,
    DEFICIENCY_CLOSED_VERIFIED,
    DEFICIENCY_OPEN,
    DELINQUENCY_CURRENT,
    DRAWDOWN_CANCELLED,
    DRAWDOWN_COORDINATED,
    DRAWDOWN_REQUESTED,
    EAP_NONE,
    ENTRY_PAYMENT_RECEIVED,
    EVENT_MONITORING,
    EVENT_STOOD_DOWN,
    HAZARD_SIGNIFICANT,
    INSPECTION_ACCEPTED,
    INSPECTION_RETURNED,
    INSPECTION_SCHEDULED,
    INSPECTION_SUBMITTED,
    INSPECTION_TYPE_FOLLOW_UP,
    INTERVENTION_ABANDONMENT_TAKEOVER,
    INTERVENTION_BREACH_ORDER,
    PERMIT_ISSUED,
    PERMIT_TYPE_REMOVAL,
    REG_BREACHED,
    REG_REGISTERED,
    REG_REMOVAL_PERMITTED,
    REG_STATE_INTERVENTION,
    SAFETY_CONDITIONALLY_SATISFACTORY,
    SAFETY_POOR,
    SAFETY_UNRATED,
    SEVERITY_SERIOUS,
    SOURCE_INSPECTION,
)
from test_helpers.test_users import TEST_USERS, make_engineer_headers

RETURN_REASON = "Narrative lacks the downstream toe drain observations."
FIRST_NARRATIVE = "Crest and spillway walked; the toe area is not described."
SECOND_NARRATIVE = "Toe drain flowing clear; minor spalling on the training wall."
BREACH_JUSTIFICATION = "Abandoned structure with progressive internal erosion."


@pytest.fixture()
def certified(program, base):
    """The dam's first certified consequence assessment, filed by its engineer."""
    assessment = program.create_assessment(
        f.assessment_a1(base.dam_id), base.engineer_a_id
    )
    return program.certify_assessment(assessment["id"], base.engineer_a_id)


# ---------------------------------------------------------------------------
# DRAFT -> CERTIFIED on a dam that never had a plan
# ---------------------------------------------------------------------------
def test_the_first_certification_writes_the_certified_variant_onto_the_row(certified):
    """Certification publishes the certified score and class and stamps the row.

    PRD 3.2: "On success `certified_score` and `certified_hazard_class` are written from the certified variant and `certified_at` is stamped with the logical clock."

    Design: Corner/state_machines/first_certification_publishes_the_classification_without_opening_an_eap_deficiency
    """
    assert certified["status"] == ASSESSMENT_CERTIFIED
    assert_instant(certified["certified_at"], CLOCK_ORIGIN, "certified_at")
    assert certified["superseded_at"] is None
    # A 200-minute travel time is forced to a 1.0 multiplier while screening and
    # takes the 0.6 slow-travel band once the breach analysis is certified.
    assert_score(certified["screening_score"], 9.00, "screening_score")
    assert_score(certified["certified_score"], 6.60, "certified_score")
    assert certified["certified_hazard_class"] == HAZARD_SIGNIFICANT


def test_the_dam_takes_the_new_class_score_and_rebuilt_inspection_clock(
    program, base, certified
):
    """The classification cascade moves the dam onto the 24-month interval.

    PRD 3.2: "Because link 1 replaced the classification source, the dam's `hazard_class` is set to the new `certified_hazard_class`, its `current_consequence_score` to the new `certified_score`, its `eap_required` flag is recomputed, and its `next_inspection_due_at` and `inspection_overdue` are recomputed on the new class's interval."

    Design: Corner/state_machines/first_certification_publishes_the_classification_without_opening_an_eap_deficiency
    """
    dam = program.get_dam(base.dam_id)
    assert dam["hazard_class"] == HAZARD_SIGNIFICANT
    assert_score(dam["current_consequence_score"], 6.60, "current_consequence_score")
    assert dam["eap_required"] is True
    # 2019-04-15 registration advanced by the SIGNIFICANT interval of 24 months.
    assert_instant(
        dam["next_inspection_due_at"],
        "2021-04-15T00:00:00Z",
        "next_inspection_due_at",
    )
    assert dam["inspection_overdue"] is True
    assert dam["version"] == 2
    assert dam["safety_status"] == SAFETY_UNRATED


def test_a_dam_that_never_had_an_approved_plan_gets_no_eap_deficiency(
    api, program, base, certified
):
    """The automatic plan deficiency fires only behind a plan leaving APPROVED.

    PRD 3.2: "This link fires **only** as a consequence of link 3 actually moving a plan out of `APPROVED`: certifying an assessment on a dam that has never had an approved plan opens no deficiency at all, however high its new class."

    Design: Corner/state_machines/first_certification_publishes_the_classification_without_opening_an_eap_deficiency
    """
    dam = program.get_dam(base.dam_id)
    assert dam["open_deficiency_count"] == 0
    assert dam["latest_eap_status"] == EAP_NONE

    rows, meta = validate_paginated(
        api.list_deficiencies(program.admin, {"dam_id": base.dam_id})
    )
    assert rows == []
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# CERTIFIED is not a state certification can be applied to again
# ---------------------------------------------------------------------------
def test_certifying_the_same_assessment_twice_is_an_invalid_state(
    api, base, certified
):
    """The second certification of one row is refused on the state check.

    PRD 2.5: "**Assessment state** — certification requires the assessment to be `DRAFT`; otherwise `ERR_ASSESSMENT_INVALID_STATE` (409). A second certification of the same row fails here."

    Design: Corner/state_machines/certifying_an_already_certified_assessment_is_rejected_as_invalid_state
    """
    response = api.certify_assessment(
        certified["id"], None, make_engineer_headers(base.engineer_a_id)
    )
    validate_error(response, ApiErrorId.ERR_ASSESSMENT_INVALID_STATE.value, 409)


def test_the_refused_second_certification_leaves_the_row_and_the_dam_untouched(
    api, program, base, certified
):
    """No second cascade runs, so no stamp moves and the dam keeps one version.

    PRD 3.2: "The dam's `version` increments by 1 across the whole certification, and its safety rating is left exactly as it was — reclassification is a consequence judgement, not a condition judgement."

    Design: Corner/state_machines/certifying_an_already_certified_assessment_is_rejected_as_invalid_state
    """
    api.certify_assessment(
        certified["id"], None, make_engineer_headers(base.engineer_a_id)
    )

    stored = program.assessments_for(base.dam_id)
    assert len(stored) == 1
    assert stored[0]["status"] == ASSESSMENT_CERTIFIED
    assert_instant(stored[0]["certified_at"], CLOCK_ORIGIN, "certified_at")
    assert stored[0]["superseded_at"] is None

    dam = program.get_dam(base.dam_id)
    assert dam["version"] == 2
    assert dam["safety_status"] == SAFETY_UNRATED


# ---------------------------------------------------------------------------
# SUBMITTED -> RETURNED -> SUBMITTED -> ACCEPTED
# ---------------------------------------------------------------------------
@pytest.fixture()
def submitted_visit(program, base, certified):
    """A periodic inspection submitted for review with the clock past the visit."""
    inspection = program.schedule_inspection(
        base.dam_id,
        base.engineer_a_id,
        window_start="2026-08-04T00:00:00Z",
        window_end="2026-08-06T00:00:00Z",
    )
    assert inspection["status"] == INSPECTION_SCHEDULED
    assert inspection["return_count"] == 0
    assert inspection["deficiency_count"] == 0
    program.set_clock("2026-08-05T13:00:00Z")
    return program.submit_inspection(
        inspection["id"],
        base.engineer_a_id,
        performed_at="2026-08-05T12:00:00Z",
        condition_rating=SAFETY_CONDITIONALLY_SATISFACTORY,
        narrative=FIRST_NARRATIVE,
        deficiencies=[],
    )


def test_returning_the_report_counts_the_loop_and_keeps_the_field_record(
    program, base, submitted_visit
):
    """A return hands the report back without discarding what was filed.

    PRD 3.3: "Returning it — an administrator's act carrying a `reason` — moves it `SUBMITTED → RETURNED`, increments `return_count` by one, and retains both `narrative` and `performed_at` for the record."

    Design: Corner/state_machines/inspection_return_cycles_to_returned_then_resubmission_and_acceptance_land_the_rating
    """
    assert submitted_visit["status"] == INSPECTION_SUBMITTED

    returned = program.return_inspection(submitted_visit["id"], reason=RETURN_REASON)
    assert returned["status"] == INSPECTION_RETURNED
    assert returned["return_count"] == 1
    assert_instant(returned["performed_at"], "2026-08-05T12:00:00Z", "performed_at")
    assert returned["narrative"] == FIRST_NARRATIVE

    # A return never rates the dam, so its clock is still the certified baseline.
    dam = program.get_dam(base.dam_id)
    assert dam["safety_status"] == SAFETY_UNRATED
    assert_instant(
        dam["next_inspection_due_at"],
        "2021-04-15T00:00:00Z",
        "next_inspection_due_at",
    )


def test_the_resubmission_overwrites_the_findings_without_advancing_the_counter(
    program, base, submitted_visit
):
    """RETURNED goes back to SUBMITTED with the newly reported values in place.

    PRD 3.3: "On resubmission `performed_at`, `condition_rating` and `narrative` are overwritten with the newly submitted values; deficiency rows created by the previous submission that are still `OPEN` are deleted and replaced by the rows implied by the new `deficiencies` array, the dam's `open_deficiency_count` is recomputed from scratch, and the dam's `version` increments by 1 when that count changes."

    Design: Corner/state_machines/inspection_return_cycles_to_returned_then_resubmission_and_acceptance_land_the_rating
    """
    program.return_inspection(submitted_visit["id"], reason=RETURN_REASON)
    resubmitted = program.submit_inspection(
        submitted_visit["id"],
        base.engineer_a_id,
        performed_at="2026-08-05T12:30:00Z",
        condition_rating=SAFETY_CONDITIONALLY_SATISFACTORY,
        narrative=SECOND_NARRATIVE,
        deficiencies=[],
    )
    assert resubmitted["status"] == INSPECTION_SUBMITTED
    assert resubmitted["return_count"] == 1
    assert_instant(resubmitted["performed_at"], "2026-08-05T12:30:00Z", "performed_at")
    assert resubmitted["narrative"] == SECOND_NARRATIVE
    assert resubmitted["deficiency_count"] == 0
    assert program.get_dam(base.dam_id)["open_deficiency_count"] == 0


def test_acceptance_lands_the_rating_and_rebuilds_the_periodic_schedule(
    program, base, submitted_visit
):
    """The resubmitted visit becomes the schedule baseline once it is accepted.

    PRD 3.3: "When — and only when — the accepted inspection's `inspection_type` is `PERIODIC`, the dam's schedule is rebuilt from that visit."

    Design: Corner/state_machines/inspection_return_cycles_to_returned_then_resubmission_and_acceptance_land_the_rating
    """
    program.return_inspection(submitted_visit["id"], reason=RETURN_REASON)
    program.submit_inspection(
        submitted_visit["id"],
        base.engineer_a_id,
        performed_at="2026-08-05T12:30:00Z",
        condition_rating=SAFETY_CONDITIONALLY_SATISFACTORY,
        narrative=SECOND_NARRATIVE,
        deficiencies=[],
    )
    accepted = program.accept_inspection(submitted_visit["id"], program.admin)
    assert accepted["status"] == INSPECTION_ACCEPTED
    assert_instant(accepted["accepted_at"], "2026-08-05T13:00:00Z", "accepted_at")
    assert accepted["accepted_by_user_id"] == TEST_USERS["program_admin"]["user_id"]
    assert accepted["return_count"] == 1

    dam = program.get_dam(base.dam_id)
    assert dam["safety_status"] == SAFETY_CONDITIONALLY_SATISFACTORY
    assert dam["regulatory_status"] == REG_REGISTERED
    # The resubmitted performed_at advanced by the SIGNIFICANT interval.
    assert_instant(
        dam["next_inspection_due_at"],
        "2028-08-05T12:30:00Z",
        "next_inspection_due_at",
    )
    assert dam["inspection_overdue"] is False

    assert program.get_engineer(base.engineer_a_id)["open_inspection_count"] == 0


# ---------------------------------------------------------------------------
# ACCEPTED is terminal in both directions
# ---------------------------------------------------------------------------
@pytest.fixture()
def accepted_visit(program, base, certified):
    """A periodic inspection accepted at 13:00 with a conditional rating."""
    program.set_clock("2026-08-05T13:00:00Z")
    return program.accepted_inspection(
        base.dam_id,
        base.engineer_a_id,
        condition_rating=SAFETY_CONDITIONALLY_SATISFACTORY,
        deficiencies=[],
        submission={"narrative": FIRST_NARRATIVE},
    )


def test_a_second_acceptance_of_the_same_report_is_refused(
    api, program, base, accepted_visit
):
    """ACCEPTED is terminal, so the acceptance act cannot be replayed.

    PRD 3.3: "Acceptance moves the inspection `SUBMITTED → ACCEPTED`, which is terminal, stamps `accepted_at` with the logical clock and records `accepted_by_user_id` as the acting identifier, and decrements the engineer's `open_inspection_count`."

    Design: Corner/state_machines/accepting_an_already_accepted_inspection_is_rejected_with_no_further_effects
    """
    assert accepted_visit["status"] == INSPECTION_ACCEPTED

    response = api.accept_inspection(
        accepted_visit["id"], None, base.engineer_b_headers
    )
    validate_error(response, ApiErrorId.ERR_INSPECTION_INVALID_STATE.value, 409)

    stored = next(
        row
        for row in program.inspections_for(base.dam_id)
        if row["id"] == accepted_visit["id"]
    )
    assert_instant(stored["accepted_at"], "2026-08-05T13:00:00Z", "accepted_at")
    assert stored["accepted_by_user_id"] == TEST_USERS["program_admin"]["user_id"]
    assert program.get_engineer(base.engineer_a_id)["open_inspection_count"] == 0


def test_a_late_return_against_an_accepted_report_is_equally_refused(
    api, program, base, accepted_visit
):
    """Return also demands SUBMITTED, so an objection filed afterwards fails.

    PRD 2.5: "**Inspection state** — submission requires `SCHEDULED` or `RETURNED`; acceptance and return both require `SUBMITTED`; `ACCEPTED` is terminal. Otherwise `ERR_INSPECTION_INVALID_STATE` (409)."

    Design: Corner/state_machines/accepting_an_already_accepted_inspection_is_rejected_with_no_further_effects
    """
    response = api.return_inspection(
        accepted_visit["id"],
        f.inspection_return_payload(reason="Late objection filed after acceptance."),
        program.admin,
    )
    validate_error(response, ApiErrorId.ERR_INSPECTION_INVALID_STATE.value, 409)

    stored = next(
        row
        for row in program.inspections_for(base.dam_id)
        if row["id"] == accepted_visit["id"]
    )
    assert stored["status"] == INSPECTION_ACCEPTED
    assert stored["return_count"] == 0

    dam = program.get_dam(base.dam_id)
    assert dam["safety_status"] == SAFETY_CONDITIONALLY_SATISFACTORY
    assert_instant(
        dam["next_inspection_due_at"],
        "2028-08-05T12:00:00Z",
        "next_inspection_due_at",
    )
    # One version for the certification and one for the acceptance.
    assert dam["version"] == 3


# ---------------------------------------------------------------------------
# BREACHED is the end of the road
# ---------------------------------------------------------------------------
@pytest.fixture()
def poor_dam_with_defect(program, base, certified):
    """A POOR-rated dam carrying one OPEN seepage deficiency."""
    program.set_clock("2026-08-05T13:00:00Z")
    program.accepted_inspection(
        base.dam_id,
        base.engineer_a_id,
        accepter_headers=base.engineer_b_headers,
        condition_rating=SAFETY_POOR,
        deficiencies=[
            f.deficiency_item(
                category=CATEGORY_SEEPAGE,
                severity=SEVERITY_SERIOUS,
                description="Concentrated seepage at the downstream toe.",
            )
        ],
    )
    return base


def test_the_breach_order_moves_the_dam_to_breached_and_force_closes_its_defects(
    api, program, poor_dam_with_defect
):
    """With no structure left to remediate every live deficiency is closed out.

    PRD 3.9: "Because there is no longer a structure to remediate, every deficiency on the dam whose status is `OPEN`, `ORDERED`, `REMEDIATION_SUBMITTED` or `ESCALATED` is closed as `CLOSED_VERIFIED` with `closed_at` stamped at the logical clock, and the dam's `open_deficiency_count` becomes 0."

    Design: Corner/state_machines/breach_order_is_terminal_so_later_certification_is_rejected
    """
    base = poor_dam_with_defect
    before = program.deficiencies_for(base.dam_id)
    assert len(before) == 1
    assert before[0]["status"] == DEFICIENCY_OPEN
    assert before[0]["source"] == SOURCE_INSPECTION

    validate_success(
        api.state_intervention(
            base.dam_id,
            f.state_intervention_payload(
                INTERVENTION_BREACH_ORDER, justification=BREACH_JUSTIFICATION
            ),
            program.admin,
        )
    )

    dam = program.get_dam(base.dam_id)
    assert dam["regulatory_status"] == REG_BREACHED
    assert dam["open_deficiency_count"] == 0

    closed = program.deficiencies_for(base.dam_id)
    assert len(closed) == 1
    assert closed[0]["status"] == DEFICIENCY_CLOSED_VERIFIED
    assert_instant(closed[0]["closed_at"], "2026-08-05T13:00:00Z", "closed_at")


def test_every_later_program_act_against_the_breached_dam_is_inoperable(
    api, program, poor_dam_with_defect
):
    """A new consequence filing and a new field visit are both turned away.

    PRD 3.9: "A breached dam is out of the program, and every subsequent consequence certification, inspection scheduling, permit application, event declaration, plan draft and drawdown request against it is rejected with `ERR_DAM_NOT_OPERABLE`."

    Design: Corner/state_machines/breach_order_is_terminal_so_later_certification_is_rejected
    """
    base = poor_dam_with_defect
    validate_success(
        api.state_intervention(
            base.dam_id,
            f.state_intervention_payload(
                INTERVENTION_BREACH_ORDER, justification=BREACH_JUSTIFICATION
            ),
            program.admin,
        )
    )

    filing = api.create_assessment(
        f.assessment_a1(base.dam_id, inundation_map_ref="IM-2027-Z"),
        make_engineer_headers(base.engineer_a_id),
    )
    validate_error(filing, ApiErrorId.ERR_DAM_NOT_OPERABLE.value, 409)

    scheduling = api.create_inspection(
        f.inspection_payload(
            base.dam_id,
            base.engineer_a_id,
            inspection_type=INSPECTION_TYPE_FOLLOW_UP,
            window_start="2026-08-10T00:00:00Z",
            window_end="2026-08-11T00:00:00Z",
        ),
        program.admin,
    )
    validate_error(scheduling, ApiErrorId.ERR_DAM_NOT_OPERABLE.value, 409)


def test_the_regulatory_end_of_road_leaves_the_safety_rating_alone(
    api, program, poor_dam_with_defect
):
    """The breach order writes the regulatory dial and nothing on the safety dial.

    PRD 2.9: "No transition on the safety dimension ever touches the regulatory dimension, and no transition on the regulatory dimension ever touches the safety dimension; an operation that legitimately writes both does so through two separately specified rules."

    Design: Corner/state_machines/breach_order_is_terminal_so_later_certification_is_rejected
    """
    base = poor_dam_with_defect
    assert program.get_dam(base.dam_id)["safety_status"] == SAFETY_POOR

    validate_success(
        api.state_intervention(
            base.dam_id,
            f.state_intervention_payload(
                INTERVENTION_BREACH_ORDER, justification=BREACH_JUSTIFICATION
            ),
            program.admin,
        )
    )

    dam = program.get_dam(base.dam_id)
    assert dam["regulatory_status"] == REG_BREACHED
    assert dam["safety_status"] == SAFETY_POOR
    assert dam["hazard_class"] == HAZARD_SIGNIFICANT


# ---------------------------------------------------------------------------
# State intervention cascades onto the coordinated releases
# ---------------------------------------------------------------------------
@pytest.fixture()
def coordinated_under_monitoring(program, base, certified):
    """A COORDINATED 400-cfs release under an event still only MONITORING."""
    event = program.declare_event(
        base.dam_id,
        declared_at=CLOCK_ORIGIN,
        trigger_description="Rain on a melting snowpack across the basin.",
        declared_inflow_cfs=900,
    )
    order = program.request_drawdown(
        base.dam_id,
        event["id"],
        requested_release_cfs=400,
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-02T06:00:00Z",
    )
    coordinated = program.coordinate_drawdown(order["id"], reach_id=base.reach_id)
    return {"event": event, "order": coordinated}


def test_the_takeover_cancels_the_coordinated_release_and_releases_the_reach(
    api, program, base, coordinated_under_monitoring
):
    """Taking operational control hands back every commitment the order held.

    PRD 3.9: "Because the state is taking operational control, every drawdown order on that dam whose status is `REQUESTED`, `COORDINATED` or `ACTIVE` is cancelled with `cancel_reason` set to `STATE_INTERVENTION`, each cancellation releasing the reach capacity and reservoir storage it had committed under the conservation discipline of §3.7."

    Design: Corner/state_machines/state_intervention_cancels_coordinated_drawdowns_and_releases_commitments
    """
    order = coordinated_under_monitoring["order"]
    assert order["status"] == DRAWDOWN_COORDINATED
    # 400 cfs held for six hours.
    assert_acre_feet(
        order["planned_release_acre_ft"], 198.347, "planned_release_acre_ft"
    )
    taken = program.get_reach(base.reach_id)
    assert_cfs(taken["committed_release_cfs"], 400.000, "committed_release_cfs")
    assert taken["active_drawdown_count"] == 1
    assert taken["version"] == 2

    validate_success(
        api.state_intervention(
            base.dam_id,
            f.state_intervention_payload(
                INTERVENTION_ABANDONMENT_TAKEOVER,
                justification="Owner abandoned the structure mid-event.",
            ),
            program.admin,
        )
    )

    cancelled = program.get_drawdown(order["id"])
    assert cancelled["status"] == DRAWDOWN_CANCELLED
    assert cancelled["cancel_reason"] == CANCEL_REASON_STATE_INTERVENTION
    assert_instant(cancelled["cancelled_at"], CLOCK_ORIGIN, "cancelled_at")

    released = program.get_reach(base.reach_id)
    assert_cfs(released["committed_release_cfs"], 0.000, "committed_release_cfs")
    assert released["active_drawdown_count"] == 0
    assert released["version"] == 3

    dam = program.get_dam(base.dam_id)
    assert_acre_feet(
        dam["committed_drawdown_acre_ft"], 0.000, "committed_drawdown_acre_ft"
    )
    assert_acre_feet(
        dam["available_conservation_storage_acre_ft"],
        1500.000,
        "available_conservation_storage_acre_ft",
    )
    assert_storage_conservation(dam)


def test_the_dam_moves_to_state_intervention_while_the_event_keeps_monitoring(
    api, program, base, coordinated_under_monitoring
):
    """The takeover writes the regulatory dial and leaves the event where it was.

    PRD 3.9: "Two of the three types — `ABANDONMENT_TAKEOVER` and `EMERGENCY_REPAIR` — move the dam onto `STATE_INTERVENTION`, and either `REGISTERED → STATE_INTERVENTION` or `UNDER_ENFORCEMENT → STATE_INTERVENTION` is a legal move."

    Design: Corner/state_machines/state_intervention_cancels_coordinated_drawdowns_and_releases_commitments
    """
    assert program.get_dam(base.dam_id)["regulatory_status"] == REG_REGISTERED

    validate_success(
        api.state_intervention(
            base.dam_id,
            f.state_intervention_payload(
                INTERVENTION_ABANDONMENT_TAKEOVER,
                justification="Owner abandoned the structure mid-event.",
            ),
            program.admin,
        )
    )

    dam = program.get_dam(base.dam_id)
    assert dam["regulatory_status"] == REG_STATE_INTERVENTION
    assert dam["safety_status"] == SAFETY_UNRATED

    event = program.get_event(coordinated_under_monitoring["event"]["id"])
    assert event["status"] == EVENT_MONITORING
    assert event["stood_down_at"] is None


# ---------------------------------------------------------------------------
# STOOD_DOWN is terminal and cancels the releases the event authorised
# ---------------------------------------------------------------------------
@pytest.fixture()
def monitoring_with_request(program, base, certified):
    """A MONITORING event with one reading and one uncoordinated release request."""
    event = program.declare_event(
        base.dam_id,
        declared_at=CLOCK_ORIGIN,
        trigger_description="Warm rain falling on a deep snowpack.",
        declared_inflow_cfs=900,
    )
    program.add_reading(event["id"], CLOCK_ORIGIN, 1040.0, observed_inflow_cfs=1000)
    order = program.request_drawdown(
        base.dam_id,
        event["id"],
        requested_release_cfs=400,
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-02T06:00:00Z",
    )
    return {"event": event, "order": order}


def test_standing_down_cancels_the_requested_order_without_touching_the_reach(
    program, base, monitoring_with_request
):
    """A REQUESTED order had committed nothing, so its cancellation releases nothing.

    PRD 3.7: "Standing down also cancels the releases the event authorised: every drawdown order on the event whose status is `REQUESTED`, `COORDINATED` or `ACTIVE` is moved to `CANCELLED` with `cancel_reason` set to `EVENT_STOOD_DOWN`, and each cancellation releases exactly the reach capacity and reservoir storage that order had committed, incrementing the reach's `version` and the dam's `version` for the changes it makes."

    Design: Corner/state_machines/readings_after_stand_down_are_rejected_and_requested_orders_cancel_without_release
    """
    order = monitoring_with_request["order"]
    assert order["status"] == DRAWDOWN_REQUESTED
    # PRD 3.7: the planned volume is computed at request time; nothing is committed yet.
    assert_acre_feet(
        order["planned_release_acre_ft"], 198.347, "planned_release_acre_ft"
    )

    stood_down = program.stand_down(
        monitoring_with_request["event"]["id"], final_pool_elevation_ft=1038.0
    )
    assert stood_down["status"] == EVENT_STOOD_DOWN
    assert_instant(stood_down["stood_down_at"], CLOCK_ORIGIN, "stood_down_at")

    cancelled = program.get_drawdown(order["id"])
    assert cancelled["status"] == DRAWDOWN_CANCELLED
    assert cancelled["cancel_reason"] == CANCEL_REASON_EVENT_STOOD_DOWN
    assert cancelled["coordinated_at"] is None

    reach = program.get_reach(base.reach_id)
    assert_cfs(reach["committed_release_cfs"], 0.000, "committed_release_cfs")
    assert reach["active_drawdown_count"] == 0
    # No commitment was ever taken, so no reach version was ever spent.
    assert reach["version"] == 1

    dam = program.get_dam(base.dam_id)
    assert_acre_feet(
        dam["committed_drawdown_acre_ft"], 0.000, "committed_drawdown_acre_ft"
    )
    assert_acre_feet(
        dam["available_conservation_storage_acre_ft"],
        1500.000,
        "available_conservation_storage_acre_ft",
    )
    assert_storage_conservation(dam)


def test_a_stood_down_event_takes_no_further_reading_and_no_second_stand_down(
    api, program, monitoring_with_request
):
    """Both monitoring acts require a live event, and a stood-down one is not.

    PRD 2.5: "**High-water event state** — recording a reading and standing an event down both require `MONITORING` or `EMERGENCY`; requesting a drawdown against a `STOOD_DOWN` event fails here. Otherwise `ERR_EVENT_INVALID_STATE` (409)."

    Design: Corner/state_machines/readings_after_stand_down_are_rejected_and_requested_orders_cancel_without_release
    """
    event_id = monitoring_with_request["event"]["id"]
    program.stand_down(event_id, final_pool_elevation_ft=1038.0)

    reading = api.create_reading(
        event_id,
        f.reading_payload(CLOCK_ORIGIN, 1039.0, observed_inflow_cfs=800),
        program.coordinator,
    )
    validate_error(reading, ApiErrorId.ERR_EVENT_INVALID_STATE.value, 409)

    again = api.stand_down_event(
        event_id,
        f.stand_down_payload(final_pool_elevation_ft=1037.0),
        program.coordinator,
    )
    validate_error(again, ApiErrorId.ERR_EVENT_INVALID_STATE.value, 409)

    event = program.get_event(event_id)
    assert event["status"] == EVENT_STOOD_DOWN
    assert event["reading_count"] == 1
    assert event["peak_pool_elevation_ft"] == pytest.approx(1040.0, abs=0.005)


# ---------------------------------------------------------------------------
# REMOVAL issuance moves the regulatory dial to REMOVAL_PERMITTED
# ---------------------------------------------------------------------------
@pytest.fixture()
def removal_permit(program, base, certified):
    """A REMOVAL application with its fee settled and a reviewer assigned."""
    permit = program.apply_permit(
        base.dam_id,
        base.owner_id,
        permit_type=PERMIT_TYPE_REMOVAL,
        scope_description="Full breach of the embankment and channel restoration.",
        estimated_project_cost_cents=8_000_000,
    )
    program.post_ledger_entry(
        base.owner_id,
        entry_type=ENTRY_PAYMENT_RECEIVED,
        amount_cents=-130_800,
        memo="Removal application fee paid in full.",
    )
    program.assign_permit_review(permit["id"], base.engineer_b_id)
    return permit


def test_issuing_the_removal_permit_moves_the_dam_to_removal_permitted(
    program, base, removal_permit
):
    """The state authorises the structure's removal and the dam's posture follows.

    PRD 3.6: "When the `permit_type` is `REMOVAL`, issuance also moves the dam `REGISTERED → REMOVAL_PERMITTED` on the regulatory dimension and increments the dam's `version` by 1 — the state has authorised the structure's removal, and from that point no new consequence assessment or construction permit may be filed against it."

    Design: Corner/state_machines/removal_permit_issuance_moves_the_dam_to_removal_permitted
    """
    # Base tier 100,000 plus 0.35 percent of cost uplifted 1.10 for SIGNIFICANT.
    assert_cents(removal_permit["base_fee_cents"], 100000, "base_fee_cents")
    assert_cents(
        removal_permit["engineering_review_fee_cents"],
        30800,
        "engineering_review_fee_cents",
    )
    assert_cents(
        removal_permit["delinquency_surcharge_cents"],
        0,
        "delinquency_surcharge_cents",
    )
    assert_cents(removal_permit["volume_credit_cents"], 0, "volume_credit_cents")
    assert_cents(removal_permit["total_fee_cents"], 130800, "total_fee_cents")

    issued = program.decide_permit(
        removal_permit["id"],
        base.engineer_b_id,
        decision=DECISION_ISSUE,
        findings="Breach sequence and restoration plan are acceptable.",
        conditions="Notify the program 10 days before breaching.",
    )
    assert issued["status"] == PERMIT_ISSUED
    assert_instant(issued["issued_at"], CLOCK_ORIGIN, "issued_at")
    assert issued["conditions"] == "Notify the program 10 days before breaching."

    dam = program.get_dam(base.dam_id)
    assert dam["regulatory_status"] == REG_REMOVAL_PERMITTED
    assert dam["safety_status"] == SAFETY_UNRATED

    owner = program.get_owner(base.owner_id)
    assert_cents(owner["fee_balance_cents"], 0, "fee_balance_cents")
    assert owner["delinquency_status"] == DELINQUENCY_CURRENT
    _rows, meta = program.ledger(base.owner_id)
    assert meta["total_count"] == 2


def test_a_removal_permitted_dam_refuses_a_new_assessment_but_still_takes_inspections(
    api, program, base, removal_permit
):
    """The removal-permitted posture is narrower than the breached one.

    PRD 2.5: "A breached dam is out of the program entirely; a removal-permitted dam still accepts inspections and high-water events but no new consequence assessments and no new construction permits."

    Design: Corner/state_machines/removal_permit_issuance_moves_the_dam_to_removal_permitted
    """
    program.decide_permit(
        removal_permit["id"],
        base.engineer_b_id,
        decision=DECISION_ISSUE,
        findings="Breach sequence and restoration plan are acceptable.",
    )
    assert program.get_dam(base.dam_id)["regulatory_status"] == REG_REMOVAL_PERMITTED

    filing = api.create_assessment(
        f.assessment_a1(base.dam_id, inundation_map_ref="IM-2027-Z"),
        make_engineer_headers(base.engineer_a_id),
    )
    validate_error(filing, ApiErrorId.ERR_DAM_NOT_OPERABLE.value, 409)

    scheduled = program.schedule_inspection(
        base.dam_id,
        base.engineer_a_id,
        inspection_type=INSPECTION_TYPE_FOLLOW_UP,
        window_start="2026-08-10T00:00:00Z",
        window_end="2026-08-11T00:00:00Z",
    )
    assert scheduled["status"] == INSPECTION_SCHEDULED
    assert scheduled["dam_id"] == base.dam_id
