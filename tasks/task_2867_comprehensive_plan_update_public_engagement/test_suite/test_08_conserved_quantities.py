"""The two quantities PRD section 2.10 declares conserved across a compensation.

The first is the plan's weighted participation ledger, which must always equal the
sum over the plan's completed activities, so cancelling a completed activity has to
give back exactly what completing it took — including the doubled weights an
interpreter earns at an outreach session. The second is an element's policy
inventory: rescinding an adopted amendment must reverse all four links of the
adoption cascade and leave the element exactly where it stood before the vote,
while the amendment row keeps its own history as an audit trail.
"""

from test_helpers import constants as C
from test_helpers import fixtures as fx
from test_helpers.test_users import CLERK, DIRECTOR, STAFF
from prd_bench_local_runner.testing import validate_success

# Two interpreter-using respondents, one further underrepresented respondent and two
# general respondents: the five-record roster PRD section 3.6 works through.
OUTREACH_ROSTER = [
    {
        "respondent_ref": "o2-01",
        "demographic_group": C.GROUP_LIMITED_ENGLISH,
        "interpreter_used": True,
    },
    {
        "respondent_ref": "o2-02",
        "demographic_group": C.GROUP_LIMITED_ENGLISH,
        "interpreter_used": True,
    },
    {"respondent_ref": "o2-03", "demographic_group": C.GROUP_RENTER},
    {"respondent_ref": "o2-04", "demographic_group": C.GROUP_GENERAL},
    {"respondent_ref": "o2-05", "demographic_group": C.GROUP_GENERAL},
]

OUTREACH_START = "2026-07-11T18:00:00.000Z"
OUTREACH_END = "2026-07-11T20:00:00.000Z"


def _plan_with_two_completed_activities(api):
    """A workshop at 10.0/4.0 and an outreach session at 7.0/5.0, both closed."""
    plan = fx.create_plan(api)
    venue = fx.create_equity_venue(api, turnover_buffer_minutes=0)
    workshop = fx.completed_workshop(api, plan["id"], venue_id=venue["id"])
    outreach = fx.create_activity(
        api,
        plan["id"],
        activity_type=C.ACTIVITY_TARGETED_OUTREACH,
        title="Renter and Limited-English Outreach",
        venue_id=venue["id"],
        start_at=OUTREACH_START,
        end_at=OUTREACH_END,
        interpretation_offered=True,
    )
    fx.add_roster(api, outreach["id"], OUTREACH_ROSTER)
    completed_outreach = fx.complete_activity(api, outreach["id"])
    return plan, workshop, completed_outreach


# --------------------------------------------------------------------------
# The weighted participation ledger
# --------------------------------------------------------------------------
def test_completing_the_outreach_session_lifts_the_ledger_to_seventeen_of_which_nine(api):
    """The interpreter-doubled session contributes 7.0 weighted units of which 5.0
    are underrepresented, moving the plan from 10.0/4.0 to 17.0/9.0.

    "Under `OUTREACH_WEIGHTED`, interpreter-using respondents count double, so five
    records that would give 60.0 under standard weighting — three of five
    underrepresented — instead give 71.4 when the two interpreter-using respondents
    are both underrepresented, because the arithmetic is 5.0 of 7.0 weighted units."

    Design: Difficulty/compensating_invariant/activity_cancellation_restores_participation_weight_ledger
    """
    plan, _, outreach = _plan_with_two_completed_activities(api)

    assert outreach["weighting_variant"] == C.VARIANT_OUTREACH_WEIGHTED
    assert outreach["total_weighted_count"] == 7.0
    assert outreach["underrepresented_weighted_count"] == 5.0
    assert outreach["equity_share_pct"] == 71.4

    after = fx.read_plan(api, plan["id"])
    assert after["participation_weight_total"] == 17.0
    assert after["underrepresented_weight_total"] == 9.0
    assert after["equity_share_pct"] == 52.9


def test_cancelling_the_completed_session_returns_the_ledger_to_ten_of_which_four(api):
    """The compensation lands back on the pre-completion figures to the tenth, with
    the share exactly at the 40.0 threshold again.

    "After an activity has been completed and then cancelled, the plan's
    `participation_weight_total` must once again equal the sum of
    `total_weighted_count` over the plan's activities in status `COMPLETED`"

    Design: Difficulty/compensating_invariant/activity_cancellation_restores_participation_weight_ledger
    """
    plan, workshop, outreach = _plan_with_two_completed_activities(api)
    before = fx.read_plan(api, plan["id"])
    assert before["participation_weight_total"] == 17.0

    cancelled = fx.cancel_activity(
        api,
        outreach["id"],
        reason="Outreach session voided after a data-integrity review.",
    )

    assert cancelled["status"] == C.ACTIVITY_STATUS_CANCELLED
    after = fx.read_plan(api, plan["id"])
    assert after["participation_weight_total"] == workshop["total_weighted_count"] == 10.0
    assert (
        after["underrepresented_weight_total"]
        == workshop["underrepresented_weighted_count"]
        == 4.0
    )
    assert after["equity_share_pct"] == 40.0


def test_the_cancelled_session_keeps_its_own_history_and_the_workshop_is_untouched(api):
    """Only the plan-level ledger excludes the cancelled row; the row itself, its
    surviving sibling and the plan's posture are all unchanged.

    "Cancelling from `COMPLETED` is a compensation: it requires that the plan not yet
    be adopted, it debits the plan's `participation_weight_total` by the activity's
    `total_weighted_count` and its `underrepresented_weight_total` by the activity's
    `underrepresented_weighted_count`, recomputes the plan's `equity_share_pct` and
    then its `compliance_posture`, and releases the venue interval."

    Design: Difficulty/compensating_invariant/activity_cancellation_restores_participation_weight_ledger
    """
    plan, workshop, outreach = _plan_with_two_completed_activities(api)
    assert fx.read_plan(api, plan["id"])["compliance_posture"] == C.POSTURE_CAPACITY_HOLD

    fx.cancel_activity(
        api,
        outreach["id"],
        reason="Outreach session voided after a data-integrity review.",
    )

    stale = validate_success(api.get_engagement_activity(outreach["id"], STAFF))
    assert stale["status"] == C.ACTIVITY_STATUS_CANCELLED
    assert stale["total_weighted_count"] == 7.0
    assert stale["underrepresented_weighted_count"] == 5.0
    assert stale["equity_share_pct"] == 71.4

    survivor = validate_success(api.get_engagement_activity(workshop["id"], STAFF))
    assert survivor["status"] == C.ACTIVITY_STATUS_COMPLETED
    assert survivor["total_weighted_count"] == 10.0
    assert survivor["underrepresented_weighted_count"] == 4.0

    after = fx.read_plan(api, plan["id"])
    assert after["compliance_posture"] == C.POSTURE_CAPACITY_HOLD
    assert after["participation_weight_total"] == 10.0


# --------------------------------------------------------------------------
# The element policy inventory
# --------------------------------------------------------------------------
SECOND_HEARING_START = "2026-10-09T18:00:00.000Z"
SECOND_HEARING_END = "2026-10-09T21:00:00.000Z"
FIRST_HEARING_START = "2026-09-25T18:00:00.000Z"
RECONCILIATION_NOTE = (
    "Transportation level-of-service assumptions aligned with the land use diagram."
)


def _adopted_amendment_on_an_open_hearing(api):
    """A certified plan with a cleared dependency, one open and one scheduled
    hearing, and an amendment adopted on the floor of the open one."""
    ctx = fx.state_certified_plan(api)
    plan_id = ctx["plan_id"]
    land_use = ctx["elements"][C.ELEMENT_LAND_USE]
    transportation = ctx["elements"][C.ELEMENT_TRANSPORTATION]

    link = fx.create_link(
        api,
        transportation["id"],
        land_use["id"],
        dependency_type=C.DEPENDENCY_CAPACITY_ASSUMPTION,
    )
    fx.reconcile_link(api, link["id"], note=RECONCILIATION_NOTE)

    sitting = fx.scheduled_commission_hearing(api, plan_id)
    later = fx.create_hearing(
        api,
        plan_id,
        body_type=C.BODY_COMMISSION,
        scheduled_start=SECOND_HEARING_START,
        scheduled_end=SECOND_HEARING_END,
    )
    fx.set_clock(api, FIRST_HEARING_START)
    fx.open_hearing(api, sitting["id"])

    proposed = fx.propose_amendment(
        api,
        sitting["id"],
        land_use["id"],
        policy_delta=2,
        summary="Add two infill overlay policies to the land use element.",
    )
    adopted = fx.adopt_amendment(api, proposed["id"])
    return {
        "plan_id": plan_id,
        "land_use_id": land_use["id"],
        "transportation_id": transportation["id"],
        "link_id": link["id"],
        "sitting_id": sitting["id"],
        "later_id": later["id"],
        "amendment": adopted,
    }


def test_adopting_the_amendment_stales_the_dependency_and_blocks_the_later_hearing(api):
    """The floor vote raises the policy count to 8, stales the link that pointed at
    the element, holds the plan on consistency and blocks the remaining hearing.

    "Because the element's text moved, every consistency link whose target is that
    element and whose status is `CLEARED` moves `CLEARED → STALE`, recording this
    amendment's id in `staled_by_amendment_id` and incrementing the link's `version`."

    Design: Difficulty/compensating_invariant/amendment_rescission_restores_element_policy_inventory
    """
    ctx = _adopted_amendment_on_an_open_hearing(api)

    amendment = ctx["amendment"]
    assert amendment["status"] == C.AMENDMENT_STATUS_ADOPTED
    assert amendment["applied_policy_count"] == 8
    assert amendment["prior_element_status"] == C.ELEMENT_STATUS_APPROVED

    element = fx.read_element(api, ctx["land_use_id"])
    assert element["policy_count"] == 8
    assert element["consistency_status"] == C.CONSISTENCY_STALE

    link = validate_success(api.get_consistency_link(ctx["link_id"], DIRECTOR))
    assert link["status"] == C.LINK_STATUS_STALE
    assert link["staled_by_amendment_id"] == amendment["id"]

    plan = fx.read_plan(api, ctx["plan_id"])
    assert plan["open_consistency_link_count"] == 1
    assert plan["compliance_posture"] == C.POSTURE_CONSISTENCY_HOLD

    sitting = validate_success(api.get_hearing(ctx["sitting_id"], CLERK))
    assert sitting["status"] == C.HEARING_STATUS_OPEN
    assert sitting["adopted_amendment_count"] == 1
    later = validate_success(api.get_hearing(ctx["later_id"], CLERK))
    assert later["status"] == C.HEARING_STATUS_BLOCKED


def test_rescinding_it_gives_the_element_and_the_link_back_exactly(api):
    """The policy count returns to its pre-adoption 6, the element's status comes back
    from the amendment's record and the dependency clears without being re-reconciled.

    "Because the element's text is restored, every consistency link carrying this
    amendment's id in `staled_by_amendment_id` moves `STALE → CLEARED` and has
    `staled_by_amendment_id` wiped back to null."

    Design: Difficulty/compensating_invariant/amendment_rescission_restores_element_policy_inventory
    """
    ctx = _adopted_amendment_on_an_open_hearing(api)
    assert fx.read_element(api, ctx["land_use_id"])["policy_count"] == 8

    fx.rescind_amendment(
        api,
        ctx["amendment"]["id"],
        reason="Overlay policies withdrawn before the vote was finalised.",
    )

    element = fx.read_element(api, ctx["land_use_id"])
    assert element["policy_count"] == 6
    assert element["status"] == ctx["amendment"]["prior_element_status"]
    assert element["status"] == C.ELEMENT_STATUS_APPROVED
    assert element["consistency_status"] == C.CONSISTENCY_CLEARED

    link = validate_success(api.get_consistency_link(ctx["link_id"], DIRECTOR))
    assert link["status"] == C.LINK_STATUS_CLEARED
    assert link["staled_by_amendment_id"] is None
    assert link["reconciliation_note"] == RECONCILIATION_NOTE
    assert link["reconciled_by_user_id"] is not None

    source = fx.read_element(api, ctx["transportation_id"])
    assert source["consistency_status"] == C.CONSISTENCY_CLEARED


def test_the_rescission_lifts_the_hold_unblocks_the_hearing_and_keeps_the_audit_trail(api):
    """The plan's counter and posture recompute back to a clear plan, the blocked
    hearing is restored, and the rescinded amendment still carries its figures.

    "Because the link population changed, the plan's `open_consistency_link_count` and
    `compliance_posture` are recomputed, and if the recomputed posture is `CLEAR`,
    every hearing of the plan sitting in `BLOCKED` returns to `SCHEDULED`."

    Design: Difficulty/compensating_invariant/amendment_rescission_restores_element_policy_inventory
    """
    ctx = _adopted_amendment_on_an_open_hearing(api)

    rescinded = fx.rescind_amendment(
        api,
        ctx["amendment"]["id"],
        reason="Overlay policies withdrawn before the vote was finalised.",
    )

    assert rescinded["status"] == C.AMENDMENT_STATUS_RESCINDED
    assert rescinded["policy_delta"] == 2
    assert rescinded["applied_policy_count"] == 8

    plan = fx.read_plan(api, ctx["plan_id"])
    assert plan["open_consistency_link_count"] == 0
    assert plan["compliance_posture"] == C.POSTURE_CLEAR
    assert plan["status"] == C.PLAN_STATUS_STATE_CERTIFIED
    assert plan["required_elements_complete_count"] == 5
    assert plan["equity_share_pct"] == 40.0

    sitting = validate_success(api.get_hearing(ctx["sitting_id"], CLERK))
    assert sitting["status"] == C.HEARING_STATUS_OPEN
    assert sitting["amendment_count"] == 1
    assert sitting["adopted_amendment_count"] == 0
    later = validate_success(api.get_hearing(ctx["later_id"], CLERK))
    assert later["status"] == C.HEARING_STATUS_SCHEDULED
