"""Validation-ladder gates: the state filing checklist, the conditional venue
equity rule, the consistency-graph integrity rules, the three scope-uniqueness
rules and the cross-aggregate ownership rules.

Every test drives the API through real requests from an empty database with the
logical clock at its startup value of 2026-08-01T00:00:00Z.
"""

import pytest

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
    ERR_ALLOCATION_INCOMPLETE,
    ERR_CONSISTENCY_CYCLE,
    ERR_CONSISTENCY_UNRESOLVED,
    ERR_CROSS_PLAN_ACTION,
    ERR_CROSS_PLAN_LINK,
    ERR_DUPLICATE_ALLOCATION_TIER,
    ERR_DUPLICATE_CONSISTENCY_LINK,
    ERR_DUPLICATE_ELEMENT_TYPE,
    ERR_DUPLICATE_PARTICIPATION,
    ERR_ENVIRONMENTAL_REVIEW_MISSING,
    ERR_EQUITY_TARGET_NOT_MET,
    ERR_HORIZON_YEAR_MISMATCH,
    ERR_HOUSING_SHORTFALL,
    ERR_PLAN_NOT_DRAFTING,
    ERR_REQUIRED_ELEMENT_MISSING,
    ERR_RESUBMISSION_LIMIT_EXCEEDED,
    ERR_SELF_CONSISTENCY_LINK,
    ERR_VENUE_NOT_EQUITY_ELIGIBLE,
)
from test_helpers.test_users import DIRECTOR, STAFF, STATE

# --------------------------------------------------------------------- reference
# The projection drivers of the reference filing: a 20-year horizon on 20000
# households growing at 1.2 percent a year, which leaves the 11700-unit gross pool
# comfortably ahead of demand.
DRIVERS = {
    "base_households": 20000,
    "annual_household_growth_rate": 0.012,
    "job_growth_total": 15000,
    "demolition_replacement_units": 500,
}

# 9000 ABOVE_MODERATE units cannot be accommodated by the 7115-unit net pool but
# are fully accommodated by the 11700-unit gross pool.
ASSIGNED = {
    C.TIER_VERY_LOW: 900,
    C.TIER_LOW: 700,
    C.TIER_MODERATE: 800,
    C.TIER_ABOVE_MODERATE: 9000,
}
THREE_TIERS = {
    C.TIER_VERY_LOW: 900,
    C.TIER_LOW: 700,
    C.TIER_MODERATE: 800,
}

# Two of five respondents in underrepresented groups under STANDARD weighting:
# exactly 40.0 percent, the inclusive threshold.
ROSTER = [
    {"respondent_ref": "r-1", "demographic_group": C.GROUP_LOW_INCOME,
     "census_tract": "06001402100", "interpreter_used": True},
    {"respondent_ref": "r-2", "demographic_group": C.GROUP_RENTER,
     "census_tract": "06001402100"},
    {"respondent_ref": "r-3", "demographic_group": C.GROUP_GENERAL,
     "census_tract": "06001402200"},
    {"respondent_ref": "r-4", "demographic_group": C.GROUP_SENIOR,
     "census_tract": "06001402200"},
    {"respondent_ref": "r-5", "demographic_group": C.GROUP_GENERAL,
     "census_tract": "06001402300"},
]

FOUR_APPROVED = (
    C.ELEMENT_LAND_USE,
    C.ELEMENT_TRANSPORTATION,
    C.ELEMENT_PARKS,
    C.ELEMENT_INFRASTRUCTURE,
)


# ------------------------------------------------------------------- filing setup
def _plan_missing_housing(api):
    """A plan whose net-capacity projection is adopted and whose HOUSING chapter is
    still a draft: four of the five statutory chapters stand APPROVED."""
    plan = fx.create_plan(api)
    inventories = fx.certified_inventory_set(api, plan["id"])
    land_use_id = inventories[C.INVENTORY_LAND_USE]["id"]
    scenario = fx.create_scenario(
        api,
        plan["id"],
        land_use_id,
        method=C.METHOD_POLICY,
        label="Policy-constrained 2045",
        **DRIVERS,
    )
    scenario = fx.adopt_scenario(api, scenario["id"])
    elements = {t: fx.approved_element(api, plan["id"], t) for t in FOUR_APPROVED}
    elements[C.ELEMENT_HOUSING] = fx.create_element(api, plan["id"], C.ELEMENT_HOUSING)
    return {
        "plan_id": plan["id"],
        "land_use_inventory_id": land_use_id,
        "scenario": scenario,
        "elements": elements,
    }


def _approve_housing(api, ctx):
    element_id = ctx["elements"][C.ELEMENT_HOUSING]["id"]
    fx.submit_element(api, element_id)
    ctx["elements"][C.ELEMENT_HOUSING] = fx.approve_element(api, element_id)
    return ctx


def _with_full_allocations(api, ctx):
    """Five approved chapters and one allocation row per income tier."""
    _approve_housing(api, ctx)
    ctx["allocations"] = fx.create_all_allocations(api, ctx["plan_id"], ASSIGNED)
    return ctx


def _with_open_link(api, ctx):
    ctx["link"] = fx.create_link(
        api,
        ctx["elements"][C.ELEMENT_TRANSPORTATION]["id"],
        ctx["elements"][C.ELEMENT_LAND_USE]["id"],
        dependency_type=C.DEPENDENCY_CAPACITY_ASSUMPTION,
    )
    return ctx


def _with_reconciled_link(api, ctx):
    _with_open_link(api, ctx)
    ctx["link"] = fx.reconcile_link(
        api,
        ctx["link"]["id"],
        note="Mobility level-of-service assumptions realigned to the land use capacity.",
    )
    return ctx


def _with_circulated_review(api, ctx):
    ctx["review"] = fx.circulated_review(api, ctx["plan_id"])
    return ctx


def _with_gross_capacity(api, ctx):
    """Adopt the trend projection, which supersedes the policy one and lifts the
    capacity pool from 7115 to 11700."""
    scenario = fx.create_scenario(
        api,
        ctx["plan_id"],
        ctx["land_use_inventory_id"],
        method=C.METHOD_TREND,
        label="Trend 2045",
        **DRIVERS,
    )
    ctx["scenario"] = fx.adopt_scenario(api, scenario["id"])
    return ctx


def _submittable(api):
    """A plan satisfying every rung of the state-mandate checklist."""
    ctx = _plan_missing_housing(api)
    _with_full_allocations(api, ctx)
    _with_reconciled_link(api, ctx)
    _with_circulated_review(api, ctx)
    _with_gross_capacity(api, ctx)
    ctx["activity"] = fx.completed_workshop(api, ctx["plan_id"], roster=ROSTER)
    return ctx


def test_element_requirement_is_reported_before_the_allocation_requirement(api):
    """With four chapters approved and no allocation rows at all, the filing reports
    the missing chapter rather than the missing allocation.

    "The plan must carry an element in status `APPROVED` or `ADOPTED` for each of the
    five statutory types `LAND_USE`, `HOUSING`, `TRANSPORTATION`, `PARKS` and
    `INFRASTRUCTURE` — that is, `required_elements_complete_count` must be 5.
    Otherwise `ERR_REQUIRED_ELEMENT_MISSING`."

    Design: Corner/validations/state_submission_readiness_gauntlet
    """
    ctx = _plan_missing_housing(api)

    response = api.submit_plan_to_state(
        ctx["plan_id"],
        {"submission_note": "Four of five chapters approved, no allocations yet."},
        DIRECTOR,
    )
    validate_error(response, ERR_REQUIRED_ELEMENT_MISSING)

    plan = fx.read_plan(api, ctx["plan_id"])
    assert plan["status"] == C.PLAN_STATUS_DRAFTING
    assert plan["required_elements_complete_count"] == 4


def test_allocation_completeness_counts_all_four_income_tiers(api):
    """With every chapter approved the filing reports the missing allocation rows, and
    it keeps reporting them while only three of the four tiers are on file.

    "An allocation row must exist for each of the four income tiers `VERY_LOW`,
    `LOW`, `MODERATE` and `ABOVE_MODERATE`. Otherwise `ERR_ALLOCATION_INCOMPLETE`."

    Design: Corner/validations/state_submission_readiness_gauntlet
    """
    ctx = _plan_missing_housing(api)
    _approve_housing(api, ctx)
    plan_id = ctx["plan_id"]

    plan = fx.read_plan(api, plan_id)
    assert plan["required_elements_complete_count"] == 5

    response = api.submit_plan_to_state(
        plan_id, {"submission_note": "No allocation rows yet."}, DIRECTOR
    )
    validate_error(response, ERR_ALLOCATION_INCOMPLETE)

    fx.create_all_allocations(api, plan_id, THREE_TIERS)
    rows, meta = validate_paginated(api.list_plan_housing_allocations(plan_id, STATE))
    assert meta["total_count"] == 3

    response = api.submit_plan_to_state(
        plan_id, {"submission_note": "Three of four tiers on file."}, DIRECTOR
    )
    validate_error(response, ERR_ALLOCATION_INCOMPLETE)


def test_above_moderate_tier_absorbs_the_carryover_of_the_net_capacity_pool(api):
    """On the 7115-unit net-capacity pool the top tier receives a 2135-unit share plus
    2581 units of carryover, so 9000 assigned units leave a 4284-unit shortfall.

    "Otherwise, the tier's `tier_capacity_units` is the pool multiplied by that
    tier's suitability share, rounded half up to whole units. The shares are 30
    percent for `VERY_LOW`, 20 percent for `LOW`, 20 percent for `MODERATE` and 30
    percent for `ABOVE_MODERATE`."

    Design: Corner/validations/state_submission_readiness_gauntlet
    """
    ctx = _plan_missing_housing(api)
    _approve_housing(api, ctx)
    plan_id = ctx["plan_id"]

    assert ctx["scenario"]["capacity_variant"] == C.CAPACITY_VARIANT_NET
    assert ctx["scenario"]["land_capacity_units"] == 7115

    fx.create_all_allocations(api, plan_id, THREE_TIERS)
    row = validate_success(
        api.create_housing_allocation(
            f.housing_allocation_payload(
                plan_id, C.TIER_ABOVE_MODERATE, ASSIGNED[C.TIER_ABOVE_MODERATE]
            ),
            STATE,
        ),
        201,
    )

    expected = A.expected_waterfall(7115, ASSIGNED)[C.TIER_ABOVE_MODERATE]
    assert expected["tier_capacity_units"] == 2135
    assert expected["carryover_in_units"] == 2581
    assert expected["accommodated_units"] == 4716
    assert expected["shortfall_units"] == 4284
    assert row["tier_capacity_units"] == 2135
    assert row["carryover_in_units"] == 2581
    assert row["accommodated_units"] == 4716
    assert row["shortfall_units"] == 4284

    plan = fx.read_plan(api, plan_id)
    assert plan["housing_shortfall_total"] == 4284


def test_open_consistency_link_is_reported_before_the_housing_shortfall(api):
    """A plan carrying both an open dependency and a 4284-unit shortfall reports the
    dependency, because internal consistency sits above capacity adequacy.

    "The plan's `open_consistency_link_count` must be exactly zero — no link of the
    plan may still be `OPEN` or `STALE`. Otherwise `ERR_CONSISTENCY_UNRESOLVED`."

    Design: Corner/validations/state_submission_readiness_gauntlet
    """
    ctx = _plan_missing_housing(api)
    _with_full_allocations(api, ctx)
    _with_open_link(api, ctx)

    plan = fx.read_plan(api, ctx["plan_id"])
    assert plan["open_consistency_link_count"] == 1
    assert plan["housing_shortfall_total"] == 4284

    response = api.submit_plan_to_state(
        ctx["plan_id"], {"submission_note": "One dependency still outstanding."}, DIRECTOR
    )
    validate_error(response, ERR_CONSISTENCY_UNRESOLVED)


def test_absent_environmental_review_is_reported_before_the_housing_shortfall(api):
    """With the dependency reconciled but no environmental document on file, the
    filing reports the missing review rather than the shortfall.

    "At least one environmental review of the plan must stand in `CIRCULATED` or
    `CERTIFIED`; a document still in `DRAFT` is not enough at filing time. Otherwise
    `ERR_ENVIRONMENTAL_REVIEW_MISSING`."

    Design: Corner/validations/state_submission_readiness_gauntlet
    """
    ctx = _plan_missing_housing(api)
    _with_full_allocations(api, ctx)
    _with_reconciled_link(api, ctx)

    plan = fx.read_plan(api, ctx["plan_id"])
    assert plan["open_consistency_link_count"] == 0
    assert plan["housing_shortfall_total"] == 4284

    response = api.submit_plan_to_state(
        ctx["plan_id"], {"submission_note": "No environmental document yet."}, DIRECTOR
    )
    validate_error(response, ERR_ENVIRONMENTAL_REVIEW_MISSING)


def test_housing_shortfall_surfaces_once_the_document_is_circulated(api):
    """With a circulated environmental document the filing finally reaches the
    capacity rung and reports the 4284-unit shortfall.

    "The plan's `housing_shortfall_total` must be exactly zero, meaning every tier's
    `assigned_units` is fully accommodated by the adopted scenario's capacity
    waterfall. Otherwise `ERR_HOUSING_SHORTFALL`."

    Design: Corner/validations/state_submission_readiness_gauntlet
    """
    ctx = _plan_missing_housing(api)
    _with_full_allocations(api, ctx)
    _with_reconciled_link(api, ctx)
    _with_circulated_review(api, ctx)

    assert ctx["review"]["review"]["status"] == C.REVIEW_STATUS_CIRCULATED

    response = api.submit_plan_to_state(
        ctx["plan_id"], {"submission_note": "Capacity still short."}, DIRECTOR
    )
    validate_error(response, ERR_HOUSING_SHORTFALL)


def test_equity_target_is_the_last_gate_the_filing_reaches(api):
    """Adopting the trend projection lifts the pool to 11700 units and clears the
    shortfall, leaving the plan-wide equity share of 0.0 percent as the sole failure.

    "The plan's `equity_share_pct` must be at least the minimum plan-wide
    underrepresented share of 40.0 percent, compared inclusively so that exactly 40.0
    passes. Otherwise `ERR_EQUITY_TARGET_NOT_MET`."

    Design: Corner/validations/state_submission_readiness_gauntlet
    """
    ctx = _plan_missing_housing(api)
    _with_full_allocations(api, ctx)
    _with_reconciled_link(api, ctx)
    _with_circulated_review(api, ctx)
    _with_gross_capacity(api, ctx)

    assert ctx["scenario"]["capacity_variant"] == C.CAPACITY_VARIANT_GROSS
    assert ctx["scenario"]["land_capacity_units"] == 11700

    rows, meta = validate_paginated(
        api.list_plan_housing_allocations(ctx["plan_id"], STATE)
    )
    top = [r for r in rows if r["income_tier"] == C.TIER_ABOVE_MODERATE][0]
    assert top["tier_capacity_units"] == 3510
    assert top["accommodated_units"] == 9000
    assert top["shortfall_units"] == 0

    plan = fx.read_plan(api, ctx["plan_id"])
    assert plan["housing_shortfall_total"] == 0
    assert plan["equity_share_pct"] == 0.0

    response = api.submit_plan_to_state(
        ctx["plan_id"], {"submission_note": "Equity share still zero."}, DIRECTOR
    )
    validate_error(response, ERR_EQUITY_TARGET_NOT_MET)


def test_completed_workshop_at_exactly_forty_percent_lets_the_filing_through(api):
    """Two underrepresented respondents out of five put the plan at exactly 40.0
    percent, the inclusive threshold, and the filing then succeeds.

    "`GENERAL` and `SENIOR` are deliberately **not** underrepresented groups."

    Design: Corner/validations/state_submission_readiness_gauntlet
    """
    ctx = _submittable(api)

    activity = ctx["activity"]
    assert activity["status"] == C.ACTIVITY_STATUS_COMPLETED
    assert activity["weighting_variant"] == C.VARIANT_STANDARD
    assert activity["record_count"] == 5
    assert activity["underrepresented_record_count"] == 2
    assert activity["total_weighted_count"] == pytest.approx(5.0, abs=0.01)
    assert activity["underrepresented_weighted_count"] == pytest.approx(2.0, abs=0.01)
    assert activity["equity_share_pct"] == 40.0

    plan = fx.read_plan(api, ctx["plan_id"])
    assert plan["equity_share_pct"] == 40.0

    filed = validate_success(
        api.submit_plan_to_state(
            ctx["plan_id"], {"submission_note": "Complete filing."}, DIRECTOR
        )
    )
    assert filed["status"] == C.PLAN_STATUS_STATE_SUBMITTED
    assert filed["state_review_status"] == C.STATE_REVIEW_SUBMITTED
    assert filed["resubmission_count"] == 0
    assert filed["state_findings"] is None


def test_filing_a_plan_that_is_already_with_the_state_is_refused(api):
    """A second filing of a plan sitting in STATE_SUBMITTED is refused on the state
    rung, before any checklist item is examined.

    "It is available from two plan statuses only, `DRAFTING` for a first filing and
    `STATE_DEFICIENT` for a resubmission; from any other status it is refused with
    `ERR_PLAN_NOT_DRAFTING`."

    Design: Corner/validations/state_submission_readiness_gauntlet
    """
    ctx = _submittable(api)
    validate_success(
        api.submit_plan_to_state(
            ctx["plan_id"], {"submission_note": "First filing."}, DIRECTOR
        )
    )

    response = api.submit_plan_to_state(
        ctx["plan_id"], {"submission_note": "Filed again by mistake."}, DIRECTOR
    )
    validate_error(response, ERR_PLAN_NOT_DRAFTING)

    plan = fx.read_plan(api, ctx["plan_id"])
    assert plan["status"] == C.PLAN_STATUS_STATE_SUBMITTED
    assert plan["resubmission_count"] == 0


def _deficient_round(api, ctx, element_type):
    """One deficiency round: the state finds a single chapter deficient, staff redraft
    it and the director approves it again."""
    validate_success(
        api.record_state_determination(
            ctx["plan_id"],
            f.state_determination_payload(
                C.STATE_REVIEW_DEFICIENT,
                f"The {element_type} chapter does not satisfy the mandate.",
                [element_type],
            ),
            STATE,
        )
    )
    element_id = ctx["elements"][element_type]["id"]
    demoted = fx.read_element(api, element_id)
    assert demoted["status"] == C.ELEMENT_STATUS_REVISION_REQUESTED
    assert demoted["revision_round"] == 1

    validate_success(
        api.patch_plan_element(
            element_id,
            {"policy_count": 7, "draft_body": "Redrafted after the state findings."},
            STAFF,
        )
    )
    fx.submit_element(api, element_id)
    ctx["elements"][element_type] = fx.approve_element(api, element_id)


def test_third_resubmission_is_refused_by_the_ceiling_of_two(api):
    """Two resubmissions are accepted and counted; the third is refused even though
    every other checklist item passes, and the closing dashboard shows the frozen plan.

    "On a resubmission only, the plan's `resubmission_count` must still be below the
    ceiling of two. Otherwise `ERR_RESUBMISSION_LIMIT_EXCEEDED`."

    Design: Corner/validations/state_submission_readiness_gauntlet
    """
    ctx = _submittable(api)
    plan_id = ctx["plan_id"]
    validate_success(
        api.submit_plan_to_state(plan_id, {"submission_note": "First filing."}, DIRECTOR)
    )

    _deficient_round(api, ctx, C.ELEMENT_PARKS)
    refiled = validate_success(
        api.submit_plan_to_state(plan_id, {"submission_note": "Resubmission one."}, DIRECTOR)
    )
    assert refiled["status"] == C.PLAN_STATUS_STATE_SUBMITTED
    assert refiled["resubmission_count"] == 1

    _deficient_round(api, ctx, C.ELEMENT_INFRASTRUCTURE)
    refiled = validate_success(
        api.submit_plan_to_state(plan_id, {"submission_note": "Resubmission two."}, DIRECTOR)
    )
    assert refiled["resubmission_count"] == 2

    _deficient_round(api, ctx, C.ELEMENT_TRANSPORTATION)
    before = fx.read_plan(api, plan_id)
    response = api.submit_plan_to_state(
        plan_id, {"submission_note": "Resubmission three."}, DIRECTOR
    )
    validate_error(response, ERR_RESUBMISSION_LIMIT_EXCEEDED)

    after = fx.read_plan(api, plan_id)
    assert after["status"] == C.PLAN_STATUS_STATE_DEFICIENT
    assert after["state_review_status"] == C.STATE_REVIEW_DEFICIENT
    assert after["resubmission_count"] == 2
    assert after["version"] == before["version"]


def test_closing_dashboard_reports_the_frozen_plan_after_the_ceiling_is_reached(api):
    """The dashboard of the exhausted plan shows a frozen posture, a deficient state
    review, five complete chapters, no missing chapter and no capacity gap.

    "A dedicated computed read on the plan returns the state-mandate checklist and
    capacity/equity dashboard in one payload: `plan_update_id`, `compliance_posture`,
    `state_review_status`, `required_elements_complete_count`, `missing_element_types`"

    Design: Corner/validations/state_submission_readiness_gauntlet
    """
    ctx = _submittable(api)
    plan_id = ctx["plan_id"]
    validate_success(
        api.submit_plan_to_state(plan_id, {"submission_note": "First filing."}, DIRECTOR)
    )
    _deficient_round(api, ctx, C.ELEMENT_PARKS)
    validate_success(
        api.submit_plan_to_state(plan_id, {"submission_note": "Resubmission one."}, DIRECTOR)
    )
    _deficient_round(api, ctx, C.ELEMENT_INFRASTRUCTURE)
    validate_success(
        api.submit_plan_to_state(plan_id, {"submission_note": "Resubmission two."}, DIRECTOR)
    )
    _deficient_round(api, ctx, C.ELEMENT_TRANSPORTATION)
    validate_error(
        api.submit_plan_to_state(
            plan_id, {"submission_note": "Resubmission three."}, DIRECTOR
        ),
        ERR_RESUBMISSION_LIMIT_EXCEEDED,
    )

    summary = fx.read_summary(api, plan_id)
    assert summary["plan_update_id"] == plan_id
    assert summary["compliance_posture"] == C.POSTURE_FROZEN
    assert summary["state_review_status"] == C.STATE_REVIEW_DEFICIENT
    assert summary["required_elements_complete_count"] == 5
    assert summary["missing_element_types"] == []
    assert summary["open_consistency_link_count"] == 0
    assert summary["housing_shortfall_total"] == 0
    assert summary["equity_share_pct"] == 40.0
    assert summary["land_capacity_units"] == 11700
    assert summary["capacity_gap_units"] == 0


# ------------------------------------------------- venue accessibility and equity
INELIGIBLE_VENUES = [
    (False, False, "neither-accessible-nor-transit-served"),
    (True, False, "accessible-but-not-transit-served"),
    (False, True, "transit-served-but-not-accessible"),
]


def _venue(api, name, ada, transit):
    return validate_success(
        api.create_venue(
            f.venue_payload(name=name, ada_accessible=ada, transit_served=transit), STAFF
        ),
        201,
    )


@pytest.mark.parametrize(
    "ada_accessible,transit_served,venue_name",
    INELIGIBLE_VENUES,
    ids=[case[2] for case in INELIGIBLE_VENUES],
)
def test_targeted_outreach_needs_a_venue_that_is_both_accessible_and_transit_served(
    api, ada_accessible, transit_served, venue_name
):
    """A targeted-outreach session is refused at a venue that fails either half of the
    equity test, and nothing is booked.

    "A targeted-outreach session carries an additional equity requirement: its venue
    must be both `transit_served` and `ada_accessible`, and a booking at a venue
    failing either test is refused with `ERR_VENUE_NOT_EQUITY_ELIGIBLE`."

    Design: Corner/validations/venue_equity_eligibility_is_conditional_on_activity_type
    """
    plan = fx.create_plan(api)
    venue = _venue(api, venue_name, ada_accessible, transit_served)

    response = api.create_engagement_activity(
        f.engagement_activity_payload(
            plan["id"],
            activity_type=C.ACTIVITY_TARGETED_OUTREACH,
            title="Targeted Outreach Session",
            venue_id=venue["id"],
            start_at="2026-09-12T18:00:00.000Z",
            end_at="2026-09-12T20:00:00.000Z",
        ),
        STAFF,
    )
    validate_error(response, ERR_VENUE_NOT_EQUITY_ELIGIBLE)

    rows, meta = validate_paginated(
        api.list_engagement_activities(STAFF, params={"plan_update_id": plan["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_a_workshop_is_welcome_at_a_venue_no_outreach_session_could_use(api):
    """The same venue that fails the outreach equity test carries a workshop without
    complaint, and the workshop is weighted as a standard activity.

    "An accepted activity enters `SCHEDULED` with `record_count`,
    `underrepresented_record_count`, `total_weighted_count`,
    `underrepresented_weighted_count` and `equity_share_pct` all at zero, and with its
    `weighting_variant` fixed at creation: `OUTREACH_WEIGHTED` for a
    `TARGETED_OUTREACH` session, `STANDARD` for a workshop or a survey."

    Design: Corner/validations/venue_equity_eligibility_is_conditional_on_activity_type
    """
    plan = fx.create_plan(api)
    venue = _venue(api, "Basement Annex", False, False)

    activity = validate_success(
        api.create_engagement_activity(
            f.engagement_activity_payload(
                plan["id"],
                activity_type=C.ACTIVITY_WORKSHOP,
                title="Neighbourhood Workshop",
                venue_id=venue["id"],
                start_at="2026-09-10T18:00:00.000Z",
                end_at="2026-09-10T20:00:00.000Z",
            ),
            STAFF,
        ),
        201,
    )
    assert activity["status"] == C.ACTIVITY_STATUS_SCHEDULED
    assert activity["weighting_variant"] == C.VARIANT_STANDARD
    assert activity["venue_id"] == venue["id"]


def test_targeted_outreach_at_a_fully_equipped_venue_is_scheduled(api):
    """A venue that is both accessible and transit served carries the outreach session,
    which starts empty and weighted for outreach.

    "An accepted activity enters `SCHEDULED` with `record_count`,
    `underrepresented_record_count`, `total_weighted_count`,
    `underrepresented_weighted_count` and `equity_share_pct` all at zero, and with its
    `weighting_variant` fixed at creation: `OUTREACH_WEIGHTED` for a
    `TARGETED_OUTREACH` session, `STANDARD` for a workshop or a survey."

    Design: Corner/validations/venue_equity_eligibility_is_conditional_on_activity_type
    """
    plan = fx.create_plan(api)
    venue = _venue(api, "Transit Plaza Community Room", True, True)

    activity = validate_success(
        api.create_engagement_activity(
            f.engagement_activity_payload(
                plan["id"],
                activity_type=C.ACTIVITY_TARGETED_OUTREACH,
                title="Targeted Outreach Session",
                venue_id=venue["id"],
                start_at="2026-09-14T18:00:00.000Z",
                end_at="2026-09-14T20:00:00.000Z",
            ),
            STAFF,
        ),
        201,
    )
    assert activity["status"] == C.ACTIVITY_STATUS_SCHEDULED
    assert activity["weighting_variant"] == C.VARIANT_OUTREACH_WEIGHTED
    assert activity["record_count"] == 0
    assert activity["underrepresented_record_count"] == 0
    assert activity["total_weighted_count"] == pytest.approx(0.0, abs=0.01)
    assert activity["underrepresented_weighted_count"] == pytest.approx(0.0, abs=0.01)
    assert activity["equity_share_pct"] == 0.0


def test_a_survey_occupies_no_room_and_faces_no_venue_test(api):
    """A survey carries no venue at all, so the accessibility question never arises.

    "A workshop and a targeted-outreach session both occupy a room and must therefore
    carry a `venue_id`; a survey occupies no room and must not carry one."

    Design: Corner/validations/venue_equity_eligibility_is_conditional_on_activity_type
    """
    plan = fx.create_plan(api)

    activity = validate_success(
        api.create_engagement_activity(
            f.engagement_activity_payload(
                plan["id"],
                activity_type=C.ACTIVITY_SURVEY,
                title="Citywide Mail Survey",
                start_at="2026-09-16T09:00:00.000Z",
                end_at="2026-09-16T17:00:00.000Z",
            ),
            STAFF,
        ),
        201,
    )
    assert activity["status"] == C.ACTIVITY_STATUS_SCHEDULED
    assert activity["weighting_variant"] == C.VARIANT_STANDARD
    assert activity.get("venue_id") is None


def test_only_the_eligible_outreach_booking_reaches_the_engagement_record(api):
    """Three refused outreach bookings leave no trace: filtering the plan's engagement
    record by activity type finds only the session at the fully equipped venue.

    "Where a list endpoint also accepts filters, the filters narrow the result set
    before pagination is applied, so `total_count` reports the number of rows matching
    the filters, not the number of rows in the collection."

    Design: Corner/validations/venue_equity_eligibility_is_conditional_on_activity_type
    """
    plan = fx.create_plan(api)
    for index, (ada, transit, name) in enumerate(INELIGIBLE_VENUES):
        venue = _venue(api, name, ada, transit)
        validate_error(
            api.create_engagement_activity(
                f.engagement_activity_payload(
                    plan["id"],
                    activity_type=C.ACTIVITY_TARGETED_OUTREACH,
                    title=f"Refused Outreach {index}",
                    venue_id=venue["id"],
                    start_at="2026-09-12T18:00:00.000Z",
                    end_at="2026-09-12T20:00:00.000Z",
                ),
                STAFF,
            ),
            ERR_VENUE_NOT_EQUITY_ELIGIBLE,
        )

    eligible = _venue(api, "Transit Plaza Community Room", True, True)
    accepted = validate_success(
        api.create_engagement_activity(
            f.engagement_activity_payload(
                plan["id"],
                activity_type=C.ACTIVITY_TARGETED_OUTREACH,
                title="Targeted Outreach Session",
                venue_id=eligible["id"],
                start_at="2026-09-14T18:00:00.000Z",
                end_at="2026-09-14T20:00:00.000Z",
            ),
            STAFF,
        ),
        201,
    )

    rows, meta = validate_paginated(
        api.list_engagement_activities(
            STAFF,
            params={
                "plan_update_id": plan["id"],
                "activity_type": C.ACTIVITY_TARGETED_OUTREACH,
            },
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [accepted["id"]]


# ------------------------------------------------------- consistency graph rules
GRAPH_TYPES = (
    C.ELEMENT_LAND_USE,
    C.ELEMENT_TRANSPORTATION,
    C.ELEMENT_PARKS,
    C.ELEMENT_INFRASTRUCTURE,
)


def _draft_graph(api):
    """A plan with four drafted chapters and no dependencies between them."""
    plan = fx.create_plan(api)
    elements = {t: fx.create_element(api, plan["id"], t) for t in GRAPH_TYPES}
    return plan["id"], elements


def test_an_element_may_not_depend_on_itself(api):
    """A dependency whose source and target are the same chapter is rejected outright.

    "An element may not depend on itself, so a payload whose two ids are equal is
    refused with `ERR_SELF_CONSISTENCY_LINK` — the only 422 in this group."

    Design: Corner/validations/consistency_graph_integrity_triad
    """
    plan_id, elements = _draft_graph(api)
    land_use_id = elements[C.ELEMENT_LAND_USE]["id"]

    response = api.create_consistency_link(
        f.consistency_link_payload(
            land_use_id, land_use_id, dependency_type=C.DEPENDENCY_POLICY_ALIGNMENT
        ),
        STAFF,
    )
    validate_error(response, ERR_SELF_CONSISTENCY_LINK)

    plan = fx.read_plan(api, plan_id)
    assert plan["open_consistency_link_count"] == 0


def test_the_same_ordered_pair_may_not_be_declared_twice(api):
    """A second dependency between the same two chapters in the same direction is a
    duplicate even when it names a different kind of dependency.

    "The same ordered pair may not be declared twice, so a repeat is refused with
    `ERR_DUPLICATE_CONSISTENCY_LINK`."

    Design: Corner/validations/consistency_graph_integrity_triad
    """
    plan_id, elements = _draft_graph(api)
    land_use_id = elements[C.ELEMENT_LAND_USE]["id"]
    transport_id = elements[C.ELEMENT_TRANSPORTATION]["id"]

    first = validate_success(
        api.create_consistency_link(
            f.consistency_link_payload(
                land_use_id, transport_id, dependency_type=C.DEPENDENCY_POLICY_ALIGNMENT
            ),
            STAFF,
        ),
        201,
    )
    assert first["status"] == C.LINK_STATUS_OPEN

    response = api.create_consistency_link(
        f.consistency_link_payload(
            land_use_id, transport_id, dependency_type=C.DEPENDENCY_CAPACITY_ASSUMPTION
        ),
        STAFF,
    )
    validate_error(response, ERR_DUPLICATE_CONSISTENCY_LINK)

    plan = fx.read_plan(api, plan_id)
    assert plan["open_consistency_link_count"] == 1


def test_the_reverse_of_an_existing_dependency_closes_a_two_node_cycle(api):
    """Once land use depends on transportation, transportation may not depend back on
    land use, but it may depend on a third chapter.

    "And the new edge may not close a directed cycle: walking the plan's existing links
    in the source-to-target direction, counting every link whose status is `OPEN`,
    `CLEARED` or `STALE`, the proposed edge must not create a path from the target back
    to the source. A cycle is refused with `ERR_CONSISTENCY_CYCLE`."

    Design: Corner/validations/consistency_graph_integrity_triad
    """
    plan_id, elements = _draft_graph(api)
    land_use_id = elements[C.ELEMENT_LAND_USE]["id"]
    transport_id = elements[C.ELEMENT_TRANSPORTATION]["id"]
    parks_id = elements[C.ELEMENT_PARKS]["id"]

    fx.create_link(api, land_use_id, transport_id)

    response = api.create_consistency_link(
        f.consistency_link_payload(transport_id, land_use_id), STAFF
    )
    validate_error(response, ERR_CONSISTENCY_CYCLE)

    onward = validate_success(
        api.create_consistency_link(
            f.consistency_link_payload(transport_id, parks_id), STAFF
        ),
        201,
    )
    assert onward["status"] == C.LINK_STATUS_OPEN

    plan = fx.read_plan(api, plan_id)
    assert plan["open_consistency_link_count"] == 2


def test_a_three_edge_cycle_is_caught_on_the_closing_edge(api):
    """With land use depending on transportation and transportation on parks, parks may
    not depend back on land use, but it may depend on a chapter outside the chain.

    "And the new edge may not close a directed cycle: walking the plan's existing links
    in the source-to-target direction, counting every link whose status is `OPEN`,
    `CLEARED` or `STALE`, the proposed edge must not create a path from the target back
    to the source. A cycle is refused with `ERR_CONSISTENCY_CYCLE`."

    Design: Corner/validations/consistency_graph_integrity_triad
    """
    plan_id, elements = _draft_graph(api)
    land_use_id = elements[C.ELEMENT_LAND_USE]["id"]
    transport_id = elements[C.ELEMENT_TRANSPORTATION]["id"]
    parks_id = elements[C.ELEMENT_PARKS]["id"]
    infrastructure_id = elements[C.ELEMENT_INFRASTRUCTURE]["id"]

    fx.create_link(api, land_use_id, transport_id)
    fx.create_link(api, transport_id, parks_id)

    response = api.create_consistency_link(
        f.consistency_link_payload(parks_id, land_use_id), STAFF
    )
    validate_error(response, ERR_CONSISTENCY_CYCLE)

    onward = validate_success(
        api.create_consistency_link(
            f.consistency_link_payload(parks_id, infrastructure_id), STAFF
        ),
        201,
    )
    assert onward["status"] == C.LINK_STATUS_OPEN

    plan = fx.read_plan(api, plan_id)
    assert plan["open_consistency_link_count"] == 3


def test_refused_dependencies_leave_the_graph_and_its_counter_untouched(api):
    """Across a self link, a duplicate, a two-node cycle and a three-node cycle the plan
    ends up with exactly the three accepted edges, one of them sourced at land use.

    "A newly declared link enters `OPEN`. Its source element's `consistency_status` is
    set to `PENDING` if it had previously reached `CLEARED`, the plan's
    `open_consistency_link_count` is incremented by one"

    Design: Corner/validations/consistency_graph_integrity_triad
    """
    plan_id, elements = _draft_graph(api)
    land_use_id = elements[C.ELEMENT_LAND_USE]["id"]
    transport_id = elements[C.ELEMENT_TRANSPORTATION]["id"]
    parks_id = elements[C.ELEMENT_PARKS]["id"]
    infrastructure_id = elements[C.ELEMENT_INFRASTRUCTURE]["id"]

    validate_error(
        api.create_consistency_link(
            f.consistency_link_payload(land_use_id, land_use_id), STAFF
        ),
        ERR_SELF_CONSISTENCY_LINK,
    )
    accepted = [fx.create_link(api, land_use_id, transport_id)]
    validate_error(
        api.create_consistency_link(
            f.consistency_link_payload(
                land_use_id, transport_id, dependency_type=C.DEPENDENCY_LEVEL_OF_SERVICE
            ),
            STAFF,
        ),
        ERR_DUPLICATE_CONSISTENCY_LINK,
    )
    validate_error(
        api.create_consistency_link(
            f.consistency_link_payload(transport_id, land_use_id), STAFF
        ),
        ERR_CONSISTENCY_CYCLE,
    )
    accepted.append(fx.create_link(api, transport_id, parks_id))
    validate_error(
        api.create_consistency_link(
            f.consistency_link_payload(parks_id, land_use_id), STAFF
        ),
        ERR_CONSISTENCY_CYCLE,
    )
    accepted.append(fx.create_link(api, parks_id, infrastructure_id))

    rows, meta = validate_paginated(
        api.list_consistency_links(STAFF, params={"source_element_id": land_use_id})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [accepted[0]["id"]]

    plan = fx.read_plan(api, plan_id)
    assert plan["open_consistency_link_count"] == 3


# --------------------------------------------------------- uniqueness of scope
def _two_plans(api):
    """Two independent plan cycles in two jurisdictions."""
    first = fx.create_plan(api)
    second = fx.create_plan(
        api, title="Riverbend General Plan 2045", jurisdiction_code="CA0452"
    )
    return first["id"], second["id"]


def test_one_element_of_each_type_per_plan_but_the_next_plan_starts_afresh(api):
    """A second land use chapter on the same plan is a duplicate; the same chapter type
    on a different plan is perfectly ordinary.

    "A plan holds at most one element of each type, so a duplicate `element_type` is
    refused with `ERR_DUPLICATE_ELEMENT_TYPE`."

    Design: Corner/validations/scope_uniqueness_triad
    """
    first_plan_id, second_plan_id = _two_plans(api)
    fx.create_element(api, first_plan_id, C.ELEMENT_LAND_USE)

    response = api.create_plan_element(
        f.plan_element_payload(
            first_plan_id, C.ELEMENT_LAND_USE, title="Land Use Element, Second Take"
        ),
        STAFF,
    )
    validate_error(response, ERR_DUPLICATE_ELEMENT_TYPE)

    twin = validate_success(
        api.create_plan_element(
            f.plan_element_payload(second_plan_id, C.ELEMENT_LAND_USE), STAFF
        ),
        201,
    )
    assert twin["plan_update_id"] == second_plan_id
    assert twin["element_type"] == C.ELEMENT_LAND_USE


def test_one_allocation_of_each_tier_per_plan_but_the_next_plan_starts_afresh(api):
    """A second very-low-income row on the same plan is a duplicate even when it assigns
    a different number of units; the same tier on another plan is accepted.

    "A tier may be assigned only once per plan; a second row for the same tier is
    refused with `ERR_DUPLICATE_ALLOCATION_TIER`."

    Design: Corner/validations/scope_uniqueness_triad
    """
    first_plan_id, second_plan_id = _two_plans(api)
    fx.create_allocation(api, first_plan_id, C.TIER_VERY_LOW, 900)

    response = api.create_housing_allocation(
        f.housing_allocation_payload(first_plan_id, C.TIER_VERY_LOW, 1000), STATE
    )
    validate_error(response, ERR_DUPLICATE_ALLOCATION_TIER)

    twin = validate_success(
        api.create_housing_allocation(
            f.housing_allocation_payload(second_plan_id, C.TIER_VERY_LOW, 900), STATE
        ),
        201,
    )
    assert twin["plan_update_id"] == second_plan_id
    assert twin["income_tier"] == C.TIER_VERY_LOW


def test_one_record_per_respondent_handle_per_activity(api):
    """The same respondent handle cannot be captured twice at one activity, even under a
    different demographic group, but the same person may answer a second activity.

    "The same `respondent_ref` may not be captured twice at one activity; a repeat is
    refused with `ERR_DUPLICATE_PARTICIPATION`."

    Design: Corner/validations/scope_uniqueness_triad
    """
    plan_id, _ = _two_plans(api)
    venue = _venue(api, "Civic Center Hall", True, True)
    workshop = fx.create_activity(
        api,
        plan_id,
        activity_type=C.ACTIVITY_WORKSHOP,
        title="Community Workshop A",
        venue_id=venue["id"],
    )
    survey = fx.create_activity(
        api,
        plan_id,
        activity_type=C.ACTIVITY_SURVEY,
        title="Citywide Mail Survey",
        start_at="2026-09-16T09:00:00.000Z",
        end_at="2026-09-16T17:00:00.000Z",
    )
    fx.add_participation(
        api,
        workshop["id"],
        respondent_ref="resident-77",
        demographic_group=C.GROUP_GENERAL,
    )

    response = api.create_participation_record(
        f.participation_record_payload(
            workshop["id"],
            respondent_ref="resident-77",
            demographic_group=C.GROUP_RENTER,
        ),
        STAFF,
    )
    validate_error(response, ERR_DUPLICATE_PARTICIPATION)

    elsewhere = validate_success(
        api.create_participation_record(
            f.participation_record_payload(
                survey["id"],
                respondent_ref="resident-77",
                demographic_group=C.GROUP_GENERAL,
            ),
            STAFF,
        ),
        201,
    )
    assert elsewhere["activity_id"] == survey["id"]
    assert elsewhere["respondent_ref"] == "resident-77"


def test_refused_duplicates_leave_every_counter_where_it_was(api):
    """After the three refusals the plan still holds one land use chapter and the
    workshop still counts one respondent at one weighted unit.

    "`record_count` rises by one, `underrepresented_record_count` rises by one if the
    record is flagged as underrepresented, `total_weighted_count` rises by the record's
    weight"

    Design: Corner/validations/scope_uniqueness_triad
    """
    plan_id, _ = _two_plans(api)
    fx.create_element(api, plan_id, C.ELEMENT_LAND_USE)
    fx.create_allocation(api, plan_id, C.TIER_VERY_LOW, 900)
    venue = _venue(api, "Civic Center Hall", True, True)
    workshop = fx.create_activity(
        api,
        plan_id,
        activity_type=C.ACTIVITY_WORKSHOP,
        title="Community Workshop A",
        venue_id=venue["id"],
    )
    fx.add_participation(
        api,
        workshop["id"],
        respondent_ref="resident-77",
        demographic_group=C.GROUP_GENERAL,
    )

    validate_error(
        api.create_plan_element(
            f.plan_element_payload(plan_id, C.ELEMENT_LAND_USE), STAFF
        ),
        ERR_DUPLICATE_ELEMENT_TYPE,
    )
    validate_error(
        api.create_housing_allocation(
            f.housing_allocation_payload(plan_id, C.TIER_VERY_LOW, 1000), STATE
        ),
        ERR_DUPLICATE_ALLOCATION_TIER,
    )
    validate_error(
        api.create_participation_record(
            f.participation_record_payload(
                workshop["id"],
                respondent_ref="resident-77",
                demographic_group=C.GROUP_RENTER,
            ),
            STAFF,
        ),
        ERR_DUPLICATE_PARTICIPATION,
    )

    rows, meta = validate_paginated(
        api.list_plan_elements(plan_id, STAFF, params={"element_type": C.ELEMENT_LAND_USE})
    )
    assert meta["total_count"] == 1

    reread = validate_success(api.get_engagement_activity(workshop["id"], STAFF))
    assert reread["record_count"] == 1
    assert reread["total_weighted_count"] == pytest.approx(1.0, abs=0.01)

    records, record_meta = validate_paginated(
        api.list_activity_participation_records(workshop["id"], STAFF)
    )
    assert record_meta["total_count"] == 1
    assert records[0]["respondent_ref"] == "resident-77"


# ----------------------------------------- ownership and horizon agreement rules
def _two_plans_with_acreage(api):
    """Two plan cycles on different horizons, each with its own certified acreage
    dataset and its own land use chapter."""
    first = fx.create_plan(api)
    second = fx.create_plan(
        api,
        title="Riverbend General Plan 2050",
        jurisdiction_code="CA0452",
        horizon_year=2050,
    )
    first_acreage = fx.certify_inventory(
        api, fx.create_land_use_inventory(api, first["id"])["id"]
    )
    second_acreage = fx.certify_inventory(
        api,
        fx.create_land_use_inventory(
            api,
            second["id"],
            vacant_acres=300,
            underutilized_acres=100,
            infrastructure_constrained_acres=50,
            allowed_density_units_per_acre=12,
        )["id"],
    )
    return {
        "first_plan_id": first["id"],
        "second_plan_id": second["id"],
        "first_acreage": first_acreage,
        "second_acreage": second_acreage,
        "first_element": fx.create_element(api, first["id"], C.ELEMENT_LAND_USE),
        "second_element": fx.create_element(api, second["id"], C.ELEMENT_LAND_USE),
    }


def test_a_dependency_may_not_span_two_plans(api):
    """A dependency from one plan's land use chapter to another plan's is an ownership
    violation.

    "Both ids must resolve to existing elements, otherwise `ERR_ELEMENT_NOT_FOUND`;
    both elements must belong to the same plan, otherwise `ERR_CROSS_PLAN_LINK`"

    Design: Corner/validations/cross_aggregate_ownership_and_horizon_agreement
    """
    ctx = _two_plans_with_acreage(api)

    response = api.create_consistency_link(
        f.consistency_link_payload(
            ctx["first_element"]["id"], ctx["second_element"]["id"]
        ),
        STAFF,
    )
    validate_error(response, ERR_CROSS_PLAN_LINK)

    plan = fx.read_plan(api, ctx["first_plan_id"])
    assert plan["open_consistency_link_count"] == 0


def test_an_implementation_action_may_not_cite_another_plans_chapter(api):
    """An action recorded against one plan may not name a chapter belonging to another.

    "An implementation action names the `plan_update_id`, the `source_element_id` of
    the element whose policy it implements — which must belong to the same plan,
    otherwise `ERR_CROSS_PLAN_ACTION`"

    Design: Corner/validations/cross_aggregate_ownership_and_horizon_agreement
    """
    ctx = _two_plans_with_acreage(api)

    response = api.create_implementation_action(
        f.implementation_action_payload(
            ctx["first_plan_id"], ctx["second_element"]["id"]
        ),
        STAFF,
    )
    validate_error(response, ERR_CROSS_PLAN_ACTION)

    rows, meta = validate_paginated(
        api.list_implementation_actions(
            STAFF, params={"plan_update_id": ctx["first_plan_id"]}
        )
    )
    assert meta["total_count"] == 0


def test_a_projection_may_not_borrow_another_plans_acreage_dataset(api):
    """A scenario of the first plan may not be computed from the second plan's certified
    acreage, and the borrowed dataset is left exactly as it was.

    "A dataset belonging to a different plan is an ownership violation and is refused
    with `ERR_CROSS_PLAN_LINK`."

    Design: Corner/validations/cross_aggregate_ownership_and_horizon_agreement
    """
    ctx = _two_plans_with_acreage(api)
    borrowed = validate_success(
        api.get_inventory_dataset(ctx["second_acreage"]["id"], STAFF)
    )

    response = api.create_growth_scenario(
        f.growth_scenario_payload(
            ctx["first_plan_id"],
            borrowed["id"],
            borrowed["version"],
            label="Borrowed acreage",
            **DRIVERS,
        ),
        STAFF,
    )
    validate_error(response, ERR_CROSS_PLAN_LINK)

    after = validate_success(api.get_inventory_dataset(borrowed["id"], STAFF))
    assert after["referencing_scenario_count"] == 0
    assert after["version"] == borrowed["version"]
    assert after["status"] == C.INVENTORY_STATUS_CERTIFIED


def test_a_projection_must_share_its_plans_horizon_year(api):
    """A scenario naming a horizon the plan does not run to is rejected as malformed.

    "a `horizon_year` that must equal the parent plan's `horizon_year` exactly — a
    mismatch is refused with `ERR_HORIZON_YEAR_MISMATCH`, and that comparison is the
    last check performed on a scenario creation, after the pinned version and the
    ownership tests have both passed."

    Design: Corner/validations/cross_aggregate_ownership_and_horizon_agreement
    """
    ctx = _two_plans_with_acreage(api)
    acreage = validate_success(
        api.get_inventory_dataset(ctx["first_acreage"]["id"], STAFF)
    )

    response = api.create_growth_scenario(
        f.growth_scenario_payload(
            ctx["first_plan_id"],
            acreage["id"],
            acreage["version"],
            label="Wrong horizon",
            horizon_year=2050,
            **DRIVERS,
        ),
        STAFF,
    )
    validate_error(response, ERR_HORIZON_YEAR_MISMATCH)

    after = validate_success(api.get_inventory_dataset(acreage["id"], STAFF))
    assert after["referencing_scenario_count"] == 0
    assert after["version"] == acreage["version"]


def test_the_agreeing_projection_is_the_only_one_the_plan_ends_up_with(api):
    """After the borrowed-acreage and wrong-horizon refusals, the one scenario that owns
    its acreage and shares its plan's horizon is accepted at 11700 units.

    "When the scenario is accepted it enters `DRAFT`, the pinned dataset's
    `referencing_scenario_count` is incremented by one and the dataset's `version` is
    incremented by one"

    Design: Corner/validations/cross_aggregate_ownership_and_horizon_agreement
    """
    ctx = _two_plans_with_acreage(api)
    acreage = validate_success(
        api.get_inventory_dataset(ctx["first_acreage"]["id"], STAFF)
    )
    borrowed = validate_success(
        api.get_inventory_dataset(ctx["second_acreage"]["id"], STAFF)
    )

    validate_error(
        api.create_growth_scenario(
            f.growth_scenario_payload(
                ctx["first_plan_id"],
                borrowed["id"],
                borrowed["version"],
                label="Borrowed acreage",
                **DRIVERS,
            ),
            STAFF,
        ),
        ERR_CROSS_PLAN_LINK,
    )
    validate_error(
        api.create_growth_scenario(
            f.growth_scenario_payload(
                ctx["first_plan_id"],
                acreage["id"],
                acreage["version"],
                label="Wrong horizon",
                horizon_year=2050,
                **DRIVERS,
            ),
            STAFF,
        ),
        ERR_HORIZON_YEAR_MISMATCH,
    )

    scenario = validate_success(
        api.create_growth_scenario(
            f.growth_scenario_payload(
                acreage["plan_update_id"],
                acreage["id"],
                acreage["version"],
                label="Trend 2045",
                **DRIVERS,
            ),
            STAFF,
        ),
        201,
    )
    assert scenario["status"] == C.SCENARIO_STATUS_DRAFT
    assert scenario["capacity_variant"] == C.CAPACITY_VARIANT_GROSS
    assert scenario["land_capacity_units"] == 11700
    assert scenario["horizon_year"] == 2045

    pinned = validate_success(api.get_inventory_dataset(acreage["id"], STAFF))
    assert pinned["referencing_scenario_count"] == 1
    assert pinned["version"] == acreage["version"] + 1

    rows, meta = validate_paginated(
        api.list_growth_scenarios(
            STAFF, params={"plan_update_id": ctx["first_plan_id"]}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [scenario["id"]]

    untouched = validate_success(api.get_inventory_dataset(borrowed["id"], STAFF))
    assert untouched["referencing_scenario_count"] == 0
    assert untouched["version"] == borrowed["version"]
