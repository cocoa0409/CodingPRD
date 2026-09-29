"""Lifecycle walks over the plan aggregate.

Each test drives one entity, or one chain of entities, through the statuses the PRD
declares for it: the status a freshly created row is born in, the transitions a
trigger is allowed to make, the triggers refused from the wrong status, the
one-shot approvals that refuse a replay, and the council chain that carries the
plan to its terminal state and locks the aggregate behind it.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ACTION_ALREADY_COMPLETED,
    ERR_ACTION_NOT_SCHEDULED,
    ERR_ACTIVITY_CLOSED,
    ERR_ACTIVITY_NOT_ENDED,
    ERR_ACTIVITY_NOT_SCHEDULED,
    ERR_COMMISSION_RECOMMENDATION_REQUIRED,
    ERR_ELEMENT_NOT_AMENDABLE,
    ERR_ELEMENT_NOT_DRAFT,
    ERR_ELEMENT_NOT_IN_REVIEW,
    ERR_ESCALATION_OVERRIDE_REQUIRED,
    ERR_INDICATOR_OFF_TRACK,
    ERR_INVENTORY_NOT_DRAFT,
    ERR_LINK_ALREADY_CLEARED,
    ERR_NO_INDICATOR_READING,
    ERR_NO_PARTICIPATION_RECORDS,
    ERR_OUTCOME_NOT_VALID_FOR_BODY,
    ERR_PLAN_ALREADY_ADOPTED,
)
from test_helpers.test_users import CLERK, CONSULTANT, DIRECTOR, DIRECTOR_ID, STAFF

# The workshop window used where a test needs an activity that has not happened yet:
# it opens after the logical clock's startup instant of 2026-08-01T00:00:00Z.
FUTURE_ACTIVITY_START = "2026-08-20T18:00:00.000Z"
FUTURE_ACTIVITY_END = "2026-08-20T20:00:00.000Z"


def test_initial_states_of_every_directly_created_entity(api):
    """Every row a caller creates directly is born in the status its lifecycle declares.

    "A freshly opened plan starts in `DRAFTING` with `state_review_status` at
    `NOT_SUBMITTED`, `state_findings` and `adopted_scenario_id` and `adopted_at` all
    null" and "`version`, an integer that starts at 1 on creation and increments by
    exactly 1 on every mutation of that row".

    Design: Corner/state_machines/initial_states_of_every_directly_created_entity
    """
    plan = validate_success(
        api.create_plan_update(f.plan_update_payload(), DIRECTOR), 201
    )
    assert plan["status"] == C.PLAN_STATUS_DRAFTING
    assert plan["state_review_status"] == C.STATE_REVIEW_NOT_SUBMITTED
    assert plan["version"] == 1

    # "A Venue carries only id and created_at: it has no updated_at and no version."
    venue = validate_success(
        api.create_venue(f.equity_eligible_venue_payload(turnover_buffer_minutes=0), STAFF),
        201,
    )
    A.assert_config_row(venue)

    # "A new dataset enters DRAFT with referencing_scenario_count at zero."
    inventory = validate_success(
        api.create_inventory_dataset(
            f.tabular_inventory_payload(
                plan["id"], C.INVENTORY_DEMOGRAPHIC, record_count=4200
            ),
            STAFF,
        ),
        201,
    )
    assert inventory["status"] == C.INVENTORY_STATUS_DRAFT
    assert inventory["referencing_scenario_count"] == 0
    assert inventory["version"] == 1

    # "A new element ... starts in DRAFT with consistency_status at PENDING and
    #  revision_round at zero."
    source = validate_success(
        api.create_plan_element(
            f.plan_element_payload(plan["id"], C.ELEMENT_LAND_USE), STAFF
        ),
        201,
    )
    target = validate_success(
        api.create_plan_element(
            f.plan_element_payload(plan["id"], C.ELEMENT_TRANSPORTATION), STAFF
        ),
        201,
    )
    for element in (source, target):
        assert element["status"] == C.ELEMENT_STATUS_DRAFT
        assert element["consistency_status"] == C.CONSISTENCY_PENDING
        assert element["revision_round"] == 0
        assert element["version"] == 1

    # "A newly declared link enters OPEN."
    link = validate_success(
        api.create_consistency_link(
            f.consistency_link_payload(
                source["id"],
                target["id"],
                dependency_type=C.DEPENDENCY_CAPACITY_ASSUMPTION,
            ),
            STAFF,
        ),
        201,
    )
    assert link["status"] == C.LINK_STATUS_OPEN
    assert link["version"] == 1

    # "An accepted activity enters SCHEDULED with record_count,
    #  underrepresented_record_count, total_weighted_count,
    #  underrepresented_weighted_count and equity_share_pct all at zero."
    activity = validate_success(
        api.create_engagement_activity(
            f.engagement_activity_payload(
                plan["id"],
                activity_type=C.ACTIVITY_WORKSHOP,
                title="Eastside Workshop",
                venue_id=venue["id"],
                start_at=FUTURE_ACTIVITY_START,
                end_at=FUTURE_ACTIVITY_END,
            ),
            STAFF,
        ),
        201,
    )
    assert activity["status"] == C.ACTIVITY_STATUS_SCHEDULED
    assert activity["record_count"] == 0
    assert activity["underrepresented_record_count"] == 0
    assert activity["total_weighted_count"] == 0
    assert activity["underrepresented_weighted_count"] == 0
    assert activity["equity_share_pct"] == 0
    assert activity["version"] == 1

    # "A new review enters DRAFT with alternative_count at zero and
    #  comment_period_days, circulated_at, comment_period_ends_at,
    #  preferred_alternative_id and certified_at all null."
    review = validate_success(
        api.create_environmental_review(
            f.environmental_review_payload(plan["id"], C.DOC_EIR), CONSULTANT
        ),
        201,
    )
    assert review["status"] == C.REVIEW_STATUS_DRAFT
    assert review["alternative_count"] == 0
    assert review["comment_period_days"] is None
    assert review["preferred_alternative_id"] is None
    assert review["version"] == 1

    # "Adding an alternative increments the parent review's alternative_count by one
    #  and its version by one, and the new alternative enters EVALUATED."
    alternative = validate_success(
        api.create_plan_alternative(
            f.plan_alternative_payload(
                review["id"],
                traffic_vmt_index=49,
                ghg_index=49,
                habitat_index=49,
                water_index=49,
            ),
            CONSULTANT,
        ),
        201,
    )
    assert alternative["status"] == C.ALTERNATIVE_STATUS_EVALUATED
    assert alternative["raw_impact_score"] == 49.00
    assert alternative["mitigation_credit"] == 0.00
    assert alternative["net_impact_score"] == 49.00
    A.assert_alternative_scores(alternative)
    assert alternative["version"] == 1

    reread_review = validate_success(api.get_environmental_review(review["id"], CONSULTANT))
    assert reread_review["alternative_count"] == 1

    # "A new action enters PENDING with reading_count at zero, on_track false, and
    #  latest_reading_value, latest_reading_at and due_at all null."
    action = validate_success(
        api.create_implementation_action(
            f.implementation_action_payload(plan["id"], source["id"]), STAFF
        ),
        201,
    )
    assert action["status"] == C.ACTION_STATUS_PENDING
    assert action["reading_count"] == 0
    assert action["on_track"] is False
    assert action["latest_reading_value"] is None
    assert action["latest_reading_at"] is None
    assert action["due_at"] is None
    assert action["version"] == 1


def test_element_draft_to_approved_is_the_happy_path(api):
    """A parks element with no consistency links walks DRAFT to IN_REVIEW to APPROVED.

    "An approval moves the element `IN_REVIEW → APPROVED`, stamps `reviewed_by_user_id`
    with the deciding director's identifier, sets the element's `consistency_status` to
    `CLEARED`, and increments the element's `version`."

    Design: Corner/state_machines/element_draft_to_approved_is_the_happy_path
    """
    plan = fx.create_plan(api)
    element = fx.create_element(
        api,
        plan["id"],
        C.ELEMENT_PARKS,
        title="Parks and Recreation Element",
        draft_body="Parks level-of-service policies.",
        policy_count=6,
    )
    assert element["version"] == 1

    submitted = validate_success(api.submit_element_review(element["id"], {}, STAFF))
    assert submitted["status"] == C.ELEMENT_STATUS_IN_REVIEW
    assert submitted["version"] == 2

    approved = validate_success(
        api.record_review_decision(
            element["id"],
            f.review_decision_payload(
                C.DECISION_APPROVE, "Consistent with the land use element."
            ),
            DIRECTOR,
        )
    )
    assert approved["status"] == C.ELEMENT_STATUS_APPROVED
    assert approved["consistency_status"] == C.CONSISTENCY_CLEARED
    assert approved["reviewed_by_user_id"] == DIRECTOR_ID
    assert approved["revision_round"] == 0
    assert approved["version"] == 3

    # "required_elements_complete_count is the number of distinct element types on this
    #  plan for which an element exists in status APPROVED or ADOPTED".
    plan_after = validate_success(api.get_plan_update(plan["id"], DIRECTOR))
    assert plan_after["required_elements_complete_count"] == 1
    # No scenario has been adopted, so the capacity rung outranks the equity rung.
    assert plan_after["compliance_posture"] == C.POSTURE_CAPACITY_HOLD
    A.assert_posture_consistent(plan_after)


def _plan_with_future_workshop(api):
    """One plan, one venue and one workshop whose window is still ahead of the clock."""
    plan = fx.create_plan(api)
    venue = fx.create_equity_venue(api, turnover_buffer_minutes=0)
    activity = fx.create_activity(
        api,
        plan["id"],
        activity_type=C.ACTIVITY_WORKSHOP,
        title="Eastside Workshop",
        venue_id=venue["id"],
        start_at=FUTURE_ACTIVITY_START,
        end_at=FUTURE_ACTIVITY_END,
    )
    return plan, activity


def test_activity_cannot_be_completed_before_the_clock_reaches_end_at(api):
    """With the clock still short of end_at the completion fails on the clock gate.

    "completing an activity requires the clock to have reached `end_at`
    (`ERR_ACTIVITY_NOT_ENDED`)"

    Design: Corner/state_machines/activity_complete_preconditions_fail_one_at_a_time
    """
    _plan, activity = _plan_with_future_workshop(api)

    # The clock sits at its startup value, well before the 2026-08-20T20:00Z close, and
    # the clock gate is reached before the empty-set guard that would also fail here.
    validate_error(
        api.complete_engagement_activity(activity["id"], {}, STAFF),
        ERR_ACTIVITY_NOT_ENDED,
        409,
    )
    still_scheduled = validate_success(api.get_engagement_activity(activity["id"], STAFF))
    assert still_scheduled["status"] == C.ACTIVITY_STATUS_SCHEDULED


def test_activity_at_end_at_with_no_records_fails_the_empty_set_guard(api):
    """Once the clock stands exactly at end_at the refusal moves to the record guard.

    "at least one participation record must have been captured, otherwise
    `ERR_NO_PARTICIPATION_RECORDS`"

    Design: Corner/state_machines/activity_complete_preconditions_fail_one_at_a_time
    """
    _plan, activity = _plan_with_future_workshop(api)
    fx.set_clock(api, FUTURE_ACTIVITY_END)

    validate_error(
        api.complete_engagement_activity(activity["id"], {}, STAFF),
        ERR_NO_PARTICIPATION_RECORDS,
        409,
    )
    still_scheduled = validate_success(api.get_engagement_activity(activity["id"], STAFF))
    assert still_scheduled["status"] == C.ACTIVITY_STATUS_SCHEDULED
    assert still_scheduled["record_count"] == 0


def test_activity_completes_once_both_preconditions_hold(api):
    """With the clock at end_at and one record captured the completion succeeds and rolls up.

    "the plan's `participation_weight_total` is increased by the activity's
    `total_weighted_count` and its `underrepresented_weight_total` by the activity's
    `underrepresented_weighted_count`"

    Design: Corner/state_machines/activity_complete_preconditions_fail_one_at_a_time
    """
    plan, activity = _plan_with_future_workshop(api)
    fx.set_clock(api, FUTURE_ACTIVITY_END)
    fx.add_participation(
        api,
        activity["id"],
        respondent_ref="R-001",
        demographic_group=C.GROUP_LOW_INCOME,
    )

    completed = validate_success(api.complete_engagement_activity(activity["id"], {}, STAFF))
    assert completed["status"] == C.ACTIVITY_STATUS_COMPLETED
    assert completed["record_count"] == 1
    assert completed["equity_share_pct"] == 100.0
    A.assert_one_decimal(completed["equity_share_pct"], "equity_share_pct")

    plan_after = validate_success(api.get_plan_update(plan["id"], STAFF))
    assert plan_after["participation_weight_total"] == 1.0
    assert plan_after["underrepresented_weight_total"] == 1.0
    assert plan_after["equity_share_pct"] == 100.0
    # The equity rung is only reached once a scenario is adopted, so the plan is still
    # held one rung higher.
    assert plan_after["compliance_posture"] == C.POSTURE_CAPACITY_HOLD
    A.assert_posture_consistent(plan_after)


def test_link_reconcile_side_effects_reach_element_and_plan(api):
    """One reconcile writes the link, its source element and the plan in one cycle.

    "On success the link records the supplied note, stamps `reconciled_by_user_id` with
    the reconciling director's identifier and clears `staled_by_amendment_id` back to
    null. The source element's `consistency_status` becomes `CLEARED` only if every link
    sourced from it is now `CLEARED`"

    Design: Corner/state_machines/link_reconcile_side_effects_reach_element_and_plan
    """
    plan = fx.create_plan(api)
    source = fx.create_element(
        api, plan["id"], C.ELEMENT_LAND_USE, draft_body="Land use draft."
    )
    target = fx.create_element(
        api, plan["id"], C.ELEMENT_TRANSPORTATION, draft_body="Transportation draft."
    )
    link = fx.create_link(
        api,
        source["id"],
        target["id"],
        dependency_type=C.DEPENDENCY_LEVEL_OF_SERVICE,
    )

    # "with at least one open link, necessarily yields CONSISTENCY_HOLD".
    plan_before = validate_success(api.get_plan_update(plan["id"], STAFF))
    assert plan_before["open_consistency_link_count"] == 1
    assert plan_before["compliance_posture"] == C.POSTURE_CONSISTENCY_HOLD
    A.assert_posture_consistent(plan_before)

    # "The target element must additionally be far enough along to be relied upon — its
    #  status must be IN_REVIEW, APPROVED or ADOPTED".
    fx.submit_element(api, target["id"])

    note = "Level-of-service assumptions aligned with the land use build-out."
    reconciled = validate_success(
        api.reconcile_consistency_link(link["id"], f.reconcile_payload(note), DIRECTOR)
    )
    assert reconciled["status"] == C.LINK_STATUS_CLEARED
    assert reconciled["reconciliation_note"] == note
    assert reconciled["reconciled_by_user_id"] == DIRECTOR_ID
    assert reconciled["staled_by_amendment_id"] is None

    source_after = validate_success(api.get_plan_element(source["id"], STAFF))
    assert source_after["consistency_status"] == C.CONSISTENCY_CLEARED

    plan_after = validate_success(api.get_plan_update(plan["id"], STAFF))
    assert plan_after["open_consistency_link_count"] == 0
    assert plan_after["compliance_posture"] == C.POSTURE_CAPACITY_HOLD
    A.assert_posture_consistent(plan_after)


def test_element_rejects_every_trigger_absent_from_its_current_state(api):
    """Each element trigger is refused from the state where it is not declared, by name.

    "An element in `IN_REVIEW`, `APPROVED` or `ADOPTED` cannot be revised at all and the
    attempt is refused with `ERR_ELEMENT_NOT_AMENDABLE`."

    Design: Corner/state_machines/element_rejects_every_trigger_absent_from_its_current_state
    """
    plan = fx.create_plan(api)
    element = fx.create_element(
        api,
        plan["id"],
        C.ELEMENT_PARKS,
        title="Parks Element",
        draft_body="Parks draft.",
    )

    # "The element must be IN_REVIEW, otherwise ERR_ELEMENT_NOT_IN_REVIEW."
    validate_error(
        api.record_review_decision(
            element["id"], f.review_decision_payload(C.DECISION_APPROVE), DIRECTOR
        ),
        ERR_ELEMENT_NOT_IN_REVIEW,
        409,
    )

    submitted = validate_success(api.submit_element_review(element["id"], {}, STAFF))
    assert submitted["status"] == C.ELEMENT_STATUS_IN_REVIEW

    # "An element in any other status is refused with ERR_ELEMENT_NOT_DRAFT."
    validate_error(
        api.submit_element_review(element["id"], {}, STAFF), ERR_ELEMENT_NOT_DRAFT, 409
    )
    validate_error(
        api.patch_plan_element(
            element["id"],
            {"draft_body": "Sneaking a revision past the reviewer."},
            STAFF,
        ),
        ERR_ELEMENT_NOT_AMENDABLE,
        409,
    )

    final = validate_success(api.get_plan_element(element["id"], STAFF))
    assert final["status"] == C.ELEMENT_STATUS_IN_REVIEW
    assert final["draft_body"] == "Parks draft."
    # Only the one legal submit-review bumped the row.
    assert final["version"] == 2


def test_cancelled_activity_accepts_no_further_trigger(api):
    """A cancelled activity refuses records, completion and a second cancellation.

    "An activity already `CANCELLED` cannot be cancelled again and is refused with
    `ERR_ACTIVITY_CLOSED`."

    Design: Corner/state_machines/cancelled_activity_accepts_no_further_trigger
    """
    plan, activity = _plan_with_future_workshop(api)

    cancelled = validate_success(
        api.cancel_engagement_activity(
            activity["id"], {"cancellation_reason": "Venue flooded."}, STAFF
        )
    )
    assert cancelled["status"] == C.ACTIVITY_STATUS_CANCELLED

    # "attaching a record to an activity that has been completed or cancelled is refused
    #  with ERR_ACTIVITY_NOT_SCHEDULED".
    validate_error(
        api.create_participation_record(
            f.participation_record_payload(
                activity["id"],
                respondent_ref="R-001",
                demographic_group=C.GROUP_LOW_INCOME,
            ),
            STAFF,
        ),
        ERR_ACTIVITY_NOT_SCHEDULED,
        409,
    )
    # The state precondition is a higher rung than the clock gate, so the completion
    # reports the wrong status rather than the unreached end_at.
    validate_error(
        api.complete_engagement_activity(activity["id"], {}, STAFF),
        ERR_ACTIVITY_NOT_SCHEDULED,
        409,
    )
    validate_error(
        api.cancel_engagement_activity(
            activity["id"], {"cancellation_reason": "Cancelling again."}, STAFF
        ),
        ERR_ACTIVITY_CLOSED,
        409,
    )

    final = validate_success(api.get_engagement_activity(activity["id"], STAFF))
    assert final["status"] == C.ACTIVITY_STATUS_CANCELLED
    assert final["record_count"] == 0

    # "Cancelling from SCHEDULED ... changes no plan-level counter at all."
    plan_after = validate_success(api.get_plan_update(plan["id"], STAFF))
    assert plan_after["participation_weight_total"] == 0
    assert plan_after["equity_share_pct"] == 0


def test_second_certify_of_one_dataset_is_an_error_not_a_no_op(api):
    """Certification is one-shot: the replay is refused and the row is untouched.

    "A dataset already `CERTIFIED` or `SUPERSEDED` cannot be certified again
    (`ERR_INVENTORY_NOT_DRAFT`)."

    Design: Corner/state_machines/certify_and_reconcile_are_not_idempotent
    """
    plan = fx.create_plan(api)
    inventory = fx.create_tabular_inventory(
        api, plan["id"], C.INVENTORY_DEMOGRAPHIC, record_count=4200
    )

    certified = validate_success(
        api.certify_inventory_dataset(inventory["id"], {}, DIRECTOR)
    )
    assert certified["status"] == C.INVENTORY_STATUS_CERTIFIED
    assert certified["certified_by_user_id"] == DIRECTOR_ID
    assert certified["version"] == 2

    validate_error(
        api.certify_inventory_dataset(inventory["id"], {}, DIRECTOR),
        ERR_INVENTORY_NOT_DRAFT,
        409,
    )

    final = validate_success(api.get_inventory_dataset(inventory["id"], DIRECTOR))
    assert final["status"] == C.INVENTORY_STATUS_CERTIFIED
    assert final["certified_by_user_id"] == DIRECTOR_ID
    assert final["version"] == 2


def test_second_reconcile_of_one_link_is_an_error_not_a_no_op(api):
    """Reconciliation is one-shot: the replay is refused and the first note stands.

    "A link already `CLEARED` is refused with `ERR_LINK_ALREADY_CLEARED`."

    Design: Corner/state_machines/certify_and_reconcile_are_not_idempotent
    """
    plan = fx.create_plan(api)
    source = fx.create_element(
        api, plan["id"], C.ELEMENT_LAND_USE, draft_body="Land use draft."
    )
    target = fx.create_element(
        api,
        plan["id"],
        C.ELEMENT_INFRASTRUCTURE,
        draft_body="Water and sewer draft.",
    )
    link = fx.create_link(
        api,
        source["id"],
        target["id"],
        dependency_type=C.DEPENDENCY_FUNDING_ASSUMPTION,
    )
    fx.submit_element(api, target["id"])

    first_note = "Sewer capacity aligned with the build-out."
    cleared = validate_success(
        api.reconcile_consistency_link(
            link["id"], f.reconcile_payload(first_note), DIRECTOR
        )
    )
    assert cleared["status"] == C.LINK_STATUS_CLEARED
    # "version, an integer that starts at 1 on creation and increments by exactly 1 on
    #  every mutation of that row".
    assert cleared["version"] == 2

    validate_error(
        api.reconcile_consistency_link(
            link["id"], f.reconcile_payload("Reconciling twice."), DIRECTOR
        ),
        ERR_LINK_ALREADY_CLEARED,
        409,
    )

    final = validate_success(api.get_consistency_link(link["id"], DIRECTOR))
    assert final["status"] == C.LINK_STATUS_CLEARED
    assert final["reconciliation_note"] == first_note
    assert final["version"] == 2


def _escalated_element(api):
    """Drive one element to ESCALATED through three revision requests."""
    plan = fx.create_plan(api)
    element = fx.create_element(
        api, plan["id"], C.ELEMENT_TRANSPORTATION, draft_body="Round 0 body."
    )
    for round_number in (1, 2):
        fx.submit_element(api, element["id"])
        validate_success(
            api.record_review_decision(
                element["id"],
                f.review_decision_payload(
                    C.DECISION_REQUEST_REVISION, f"Round {round_number}."
                ),
                DIRECTOR,
            )
        )
        validate_success(
            api.patch_plan_element(
                element["id"], {"draft_body": f"Round {round_number} body."}, STAFF
            )
        )
    fx.submit_element(api, element["id"])
    escalated = validate_success(
        api.record_review_decision(
            element["id"],
            f.review_decision_payload(
                C.DECISION_REQUEST_REVISION, "Round 3, escalating."
            ),
            DIRECTOR,
        )
    )
    assert escalated["status"] == C.ELEMENT_STATUS_ESCALATED
    assert escalated["revision_round"] == C.MAX_REVISION_ROUNDS
    return element["id"], escalated


def test_escalated_element_refuses_the_staff_author(api):
    """Staff cannot revise or re-submit an escalated element, and write nothing trying.

    "`PlanningStaff` attempting to revise an `ESCALATED` element are refused with
    `ERR_ESCALATION_OVERRIDE_REQUIRED`, which is checked at the very bottom of the
    validation ladder — after the element's status has already been found revisable."

    Design: Corner/state_machines/escalated_element_refuses_the_staff_author_but_not_the_director
    """
    element_id, escalated = _escalated_element(api)

    # Revision is shared with PlanningStaff, so the role rung passes and the refusal is
    # the iteration-ceiling rung at the very bottom of the ladder.
    validate_error(
        api.patch_plan_element(
            element_id,
            {"draft_body": "Staff tries to rewrite an escalated element."},
            STAFF,
        ),
        ERR_ESCALATION_OVERRIDE_REQUIRED,
        403,
    )
    validate_error(
        api.submit_element_review(element_id, {}, STAFF), ERR_ELEMENT_NOT_DRAFT, 409
    )

    unchanged = validate_success(api.get_plan_element(element_id, STAFF))
    assert unchanged["status"] == C.ELEMENT_STATUS_ESCALATED
    assert unchanged["draft_body"] == "Round 2 body."
    assert unchanged["revision_round"] == C.MAX_REVISION_ROUNDS
    assert unchanged["version"] == escalated["version"]


def test_escalated_element_accepts_the_director_override(api):
    """The director's override alone reopens the element and resets its revision counter.

    "An element in `ESCALATED` is a special case: it moves `ESCALATED → DRAFT`, but only
    a `PlanningDirector` may perform that revision, and the director's override
    additionally resets `revision_round` back to zero."

    Design: Corner/state_machines/escalated_element_refuses_the_staff_author_but_not_the_director
    """
    element_id, escalated = _escalated_element(api)

    overridden = validate_success(
        api.patch_plan_element(
            element_id, {"draft_body": "Director override body."}, DIRECTOR
        )
    )
    assert overridden["status"] == C.ELEMENT_STATUS_DRAFT
    assert overridden["revision_round"] == 0
    assert overridden["draft_body"] == "Director override body."
    assert overridden["version"] == escalated["version"] + 1


# A second commission sitting ten days after its notice, used to prove that the ADOPT
# refusal on a commission hearing is the outcome-legality rule and not the plan state.
SECOND_COMMISSION_NOTICE = "2026-09-25T18:00:00.000Z"
SECOND_COMMISSION_START = "2026-10-05T18:00:00.000Z"
SECOND_COMMISSION_END = "2026-10-05T21:00:00.000Z"


def test_council_hearing_cannot_be_scheduled_before_the_commission_recommends(api):
    """A state-certified plan may not book its council sitting yet, and books no row.

    "a `COUNCIL` hearing may only be scheduled once the plan has reached
    `COMMISSION_RECOMMENDED`, and an earlier attempt is refused with
    `ERR_COMMISSION_RECOMMENDATION_REQUIRED`."

    Design: Corner/state_machines/council_adoption_pipeline_and_terminal_plan_lockdown
    """
    ctx = fx.state_certified_plan(api)
    plan_id = ctx["plan_id"]
    assert ctx["plan"]["status"] == C.PLAN_STATUS_STATE_CERTIFIED
    assert ctx["plan"]["compliance_posture"] == C.POSTURE_CLEAR
    assert ctx["plan"]["housing_shortfall_total"] == 0
    assert ctx["plan"]["equity_share_pct"] == C.MIN_EQUITY_SHARE_PCT
    assert ctx["scenario"]["land_capacity_units"] == A.expected_gross_capacity(400, 250, 18)
    assert ctx["scenario"]["capacity_variant"] == C.CAPACITY_VARIANT_GROSS

    validate_error(
        api.create_hearing(
            f.hearing_payload(
                plan_id,
                body_type=C.BODY_COUNCIL,
                scheduled_start=fx.T_COUNCIL_START,
                scheduled_end=fx.T_COUNCIL_END,
                notice_published_at=fx.T_COUNCIL_NOTICE,
            ),
            CLERK,
        ),
        ERR_COMMISSION_RECOMMENDATION_REQUIRED,
        409,
    )

    rows, meta = validate_paginated(api.list_plan_hearings(plan_id, CLERK))
    assert meta["total_count"] == 0
    assert rows == []


def test_adopt_is_refused_on_a_commission_hearing(api):
    """ADOPT is a council-only outcome even after the plan is recommended.

    "It is legal only on a `COUNCIL` hearing; on a commission hearing it is refused with
    `ERR_OUTCOME_NOT_VALID_FOR_BODY`."

    Design: Corner/state_machines/council_adoption_pipeline_and_terminal_plan_lockdown
    """
    ctx = fx.recommended_plan(api)
    plan_id = ctx["plan_id"]
    assert ctx["plan"]["status"] == C.PLAN_STATUS_COMMISSION_RECOMMENDED
    assert ctx["commission_hearing"]["status"] == C.HEARING_STATUS_RECOMMENDED
    assert ctx["commission_hearing"]["outcome"] == C.OUTCOME_RECOMMEND

    hearing = fx.scheduled_commission_hearing(
        api,
        plan_id,
        scheduled_start=SECOND_COMMISSION_START,
        scheduled_end=SECOND_COMMISSION_END,
        notice_published_at=SECOND_COMMISSION_NOTICE,
    )
    fx.set_clock(api, SECOND_COMMISSION_START)
    opened = fx.open_hearing(api, hearing["id"])
    assert opened["status"] == C.HEARING_STATUS_OPEN

    # The plan is already COMMISSION_RECOMMENDED, so the state precondition passes and
    # the outcome-legality rule further down the ladder is the one that fires.
    validate_error(
        api.record_hearing_outcome(
            hearing["id"],
            f.outcome_payload(C.OUTCOME_ADOPT, "Commission tries to adopt."),
            CLERK,
        ),
        ERR_OUTCOME_NOT_VALID_FOR_BODY,
        409,
    )

    still_open = validate_success(api.get_hearing(hearing["id"], CLERK))
    assert still_open["status"] == C.HEARING_STATUS_OPEN
    assert still_open["outcome"] is None
    assert validate_success(api.get_plan_update(plan_id, DIRECTOR))["status"] == (
        C.PLAN_STATUS_COMMISSION_RECOMMENDED
    )


def test_council_adoption_cascade_and_terminal_plan_lockdown(api):
    """ADOPT on the council hearing stamps the plan, promotes elements and schedules actions.

    "On success the plan moves `COMMISSION_RECOMMENDED → ADOPTED`, its `adopted_at` is
    stamped with the logical clock instant, every element of the plan standing in
    `APPROVED` moves `APPROVED → ADOPTED` with its `version` incremented, every
    implementation action of the plan standing in `PENDING` moves `PENDING → SCHEDULED`
    with its `due_at` stamped and its `version` incremented, and the plan's `version` is
    incremented by one. `ADOPTED` is terminal for the plan and locks its whole aggregate
    against further writes."

    Design: Corner/state_machines/council_adoption_pipeline_and_terminal_plan_lockdown
    """
    ctx = fx.recommended_plan(api)
    plan_id = ctx["plan_id"]
    elements = ctx["elements"]

    action_a = fx.create_action(
        api,
        plan_id,
        elements[C.ELEMENT_LAND_USE]["id"],
        action_type=C.ACTION_ZONING_CODE_UPDATE,
        title="Mixed-use overlay rezone",
        indicator_name="Corridor VMT per capita",
        indicator_direction=C.DIRECTION_DECREASE,
        baseline_value=100,
        target_value=80,
    )
    action_b = fx.create_action(
        api,
        plan_id,
        elements[C.ELEMENT_PARKS]["id"],
        action_type=C.ACTION_CAPITAL_PROJECT,
        title="Riverfront park acquisition",
        indicator_name="Park acres per 1000 residents",
        indicator_direction=C.DIRECTION_INCREASE,
        baseline_value=3,
        target_value=5,
    )
    action_c = fx.create_action(
        api,
        plan_id,
        elements[C.ELEMENT_INFRASTRUCTURE]["id"],
        action_type=C.ACTION_PROGRAM,
        title="Sewer capacity monitoring program",
        indicator_name="Peak wet-weather overflow events",
        indicator_direction=C.DIRECTION_DECREASE,
        baseline_value=100,
        target_value=80,
    )

    # Completion is unavailable before adoption, though readings are already legal.
    validate_error(
        api.complete_implementation_action(action_a["id"], {}, STAFF),
        ERR_ACTION_NOT_SCHEDULED,
        409,
    )

    # "for a DECREASE indicator it is on track when latest_reading_value is less than or
    #  equal to target_value".
    read_a = validate_success(
        api.record_indicator_reading(action_a["id"], {"reading_value": 76}, STAFF)
    )
    assert read_a["on_track"] is True
    assert read_a["reading_count"] == 1
    assert read_a["latest_reading_value"] == 76
    A.assert_instant_equals(
        read_a["latest_reading_at"], fx.T_COMMISSION_START, "latest_reading_at"
    )
    read_c = validate_success(
        api.record_indicator_reading(action_c["id"], {"reading_value": 95}, STAFF)
    )
    assert read_c["on_track"] is False

    council = fx.scheduled_council_hearing(api, plan_id)
    fx.set_clock(api, fx.T_COUNCIL_START)
    assert fx.open_hearing(api, council["id"])["status"] == C.HEARING_STATUS_OPEN

    adopted_out = validate_success(
        api.record_hearing_outcome(
            council["id"],
            f.outcome_payload(C.OUTCOME_ADOPT, "Adopted as recommended."),
            CLERK,
        )
    )
    assert adopted_out["status"] == C.HEARING_STATUS_ADOPTED_OUT
    assert adopted_out["outcome"] == C.OUTCOME_ADOPT

    plan_after = validate_success(api.get_plan_update(plan_id, DIRECTOR))
    assert plan_after["status"] == C.PLAN_STATUS_ADOPTED
    A.assert_instant_equals(plan_after["adopted_at"], fx.T_COUNCIL_START, "adopted_at")
    assert plan_after["required_elements_complete_count"] == len(C.STATUTORY_ELEMENT_TYPES)

    for element_type in C.STATUTORY_ELEMENT_TYPES:
        row = validate_success(
            api.get_plan_element(elements[element_type]["id"], DIRECTOR)
        )
        assert row["status"] == C.ELEMENT_STATUS_ADOPTED

    # "its due_at stamped as the plan's adopted_at instant advanced by the fixed
    #  implementation lead time of 365 days".
    for action in (action_a, action_b, action_c):
        row = validate_success(api.get_implementation_action(action["id"], STAFF))
        assert row["status"] == C.ACTION_STATUS_SCHEDULED
        A.assert_instant_equals(row["due_at"], fx.T_ACTION_DUE, "due_at")

    completed = validate_success(
        api.complete_implementation_action(action_a["id"], {}, STAFF)
    )
    assert completed["status"] == C.ACTION_STATUS_COMPLETED
    validate_error(
        api.complete_implementation_action(action_a["id"], {}, STAFF),
        ERR_ACTION_ALREADY_COMPLETED,
        409,
    )
    validate_error(
        api.complete_implementation_action(action_b["id"], {}, STAFF),
        ERR_NO_INDICATOR_READING,
        409,
    )
    validate_error(
        api.complete_implementation_action(action_c["id"], {}, STAFF),
        ERR_INDICATOR_OFF_TRACK,
        409,
    )

    validate_error(
        api.create_inventory_dataset(
            f.tabular_inventory_payload(
                plan_id, C.INVENTORY_DEMOGRAPHIC, record_count=4300
            ),
            STAFF,
        ),
        ERR_PLAN_ALREADY_ADOPTED,
        409,
    )

    rows, meta = validate_paginated(api.list_plan_hearings(plan_id, CLERK))
    assert meta["total_count"] == 2
    assert sorted(row["body_type"] for row in rows) == [C.BODY_COMMISSION, C.BODY_COUNCIL]
