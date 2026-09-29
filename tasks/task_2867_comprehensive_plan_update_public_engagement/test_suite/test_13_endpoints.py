"""Endpoint-surface compliance for the Comprehensive Plan Update API.

Five endpoint families are exercised here: the plan's computed compliance-summary
read, the two-foreign-key consistency-link association, the logical-clock control,
the preferred-alternative selector fenced between circulation and certification,
and the single partial-update endpoint of the whole service.
"""

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as a
from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ACTIVITY_NOT_ENDED,
    ERR_COMMENT_PERIOD_OPEN,
    ERR_ELEMENT_NOT_FOUND,
    ERR_PREFERRED_ALTERNATIVE_NOT_SELECTED,
    ERR_REVIEW_NOT_CIRCULATED,
)
from test_helpers.test_users import (
    ALL_ROLE_HEADERS,
    CLERK,
    CONSULTANT,
    DIRECTOR,
    STAFF,
    STATE,
)

# The twelve fields PRD section 2.11 declares for the plan's computed read.
SUMMARY_FIELDS = [
    "plan_update_id",
    "compliance_posture",
    "state_review_status",
    "required_elements_complete_count",
    "missing_element_types",
    "open_consistency_link_count",
    "housing_shortfall_total",
    "equity_share_pct",
    "land_capacity_units",
    "projected_demand_units",
    "capacity_gap_units",
    "monitoring_on_track_count",
]

# The acreage row of the reference plan: 400 vacant, 250 underutilized and 18
# allowed units per acre give a GROSS_CAPACITY of 11700 units.
REF_GROSS_CAPACITY = 11700
# TREND drivers: 20000 base households compounding at 1.2 percent over the twenty
# years from base_year 2025 to horizon_year 2045, plus 500 replacement units.
REF_BASE_HOUSEHOLDS = 20000
REF_GROWTH_RATE = 0.012
REF_JOB_GROWTH = 15000
REF_DEMOLITION_UNITS = 500
REF_DEMAND_UNITS = 6183
# 4000 / 3000 / 3000 / 4000 assigned against an 11700-unit pool.
REF_ASSIGNED = {
    C.TIER_VERY_LOW: 4000,
    C.TIER_LOW: 3000,
    C.TIER_MODERATE: 3000,
    C.TIER_ABOVE_MODERATE: 4000,
}
REF_SHORTFALL_TOTAL = 2300


def _plan_with_two_approved_elements(api):
    """A plan whose five elements exist but only LAND_USE and PARKS are APPROVED."""
    plan = fx.create_plan(api)
    inventories = fx.certified_inventory_set(
        api, plan["id"], land_use={"infrastructure_constrained_acres": 100}
    )
    elements = {
        element_type: fx.create_element(api, plan["id"], element_type)
        for element_type in C.STATUTORY_ELEMENT_TYPES
    }
    for element_type in (C.ELEMENT_LAND_USE, C.ELEMENT_PARKS):
        fx.submit_element(api, elements[element_type]["id"])
        fx.approve_element(api, elements[element_type]["id"])
    return {
        "plan_id": plan["id"],
        "inventories": inventories,
        "elements": elements,
    }


def _adopt_reference_scenario(api, ctx):
    """Adopt a TREND scenario and load all four income-tier allocations."""
    scenario = fx.create_scenario(
        api,
        ctx["plan_id"],
        ctx["inventories"][C.INVENTORY_LAND_USE]["id"],
        method=C.METHOD_TREND,
        label="Trend 2045",
        base_households=REF_BASE_HOUSEHOLDS,
        annual_household_growth_rate=REF_GROWTH_RATE,
        job_growth_total=REF_JOB_GROWTH,
        demolition_replacement_units=REF_DEMOLITION_UNITS,
    )
    for tier in C.TIER_ORDER:
        fx.create_allocation(api, ctx["plan_id"], tier, REF_ASSIGNED[tier])
    ctx["scenario"] = fx.adopt_scenario(api, scenario["id"])
    return ctx


def _record_two_monitoring_readings(api, ctx):
    """One INCREASE action reading above its target and one DECREASE action above it."""
    on_track = fx.create_action(
        api,
        ctx["plan_id"],
        ctx["elements"][C.ELEMENT_LAND_USE]["id"],
        action_type=C.ACTION_ZONING_CODE_UPDATE,
        title="Rezone the eastside corridor",
        indicator_name="acres_rezoned",
        indicator_direction=C.DIRECTION_INCREASE,
        baseline_value=0,
        target_value=120,
    )
    off_track = fx.create_action(
        api,
        ctx["plan_id"],
        ctx["elements"][C.ELEMENT_PARKS]["id"],
        action_type=C.ACTION_MONITORING,
        title="Reduce park deficit tracts",
        indicator_name="deficit_tracts",
        indicator_direction=C.DIRECTION_DECREASE,
        baseline_value=30,
        target_value=12,
    )
    ctx["on_track_action"] = fx.record_reading(api, on_track["id"], 140)
    ctx["off_track_action"] = fx.record_reading(api, off_track["id"], 18)
    return ctx


# ===================================================================== summary
def test_compliance_summary_reports_every_declared_field_before_any_projection(api):
    """A plan with no adopted scenario answers the computed read with all twelve fields.

    "A dedicated computed read on the plan returns the state-mandate checklist and
    capacity/equity dashboard in one payload: `plan_update_id`, `compliance_posture`,
    `state_review_status`, `required_elements_complete_count`, `missing_element_types`
    (the statutory element types that still lack an element in `APPROVED` or
    `ADOPTED`), `open_consistency_link_count`, `housing_shortfall_total`,
    `equity_share_pct`, and — taken from the plan's adopted scenario —
    `land_capacity_units`, `projected_demand_units` and `capacity_gap_units`, plus
    `monitoring_on_track_count`."

    Design: Corner/endpoints/compliance_summary_computed_read_reports_all_twelve_fields
    """
    ctx = _plan_with_two_approved_elements(api)

    summary = validate_success(api.get_compliance_summary(ctx["plan_id"], CLERK))

    for field in SUMMARY_FIELDS:
        assert field in summary, f"the computed read must carry {field!r}"
    assert summary["plan_update_id"] == ctx["plan_id"]
    assert summary["compliance_posture"] == C.POSTURE_CAPACITY_HOLD
    assert summary["state_review_status"] == C.STATE_REVIEW_NOT_SUBMITTED
    assert summary["required_elements_complete_count"] == 2
    assert set(summary["missing_element_types"]) == {
        C.ELEMENT_HOUSING,
        C.ELEMENT_TRANSPORTATION,
        C.ELEMENT_INFRASTRUCTURE,
    }
    assert summary["open_consistency_link_count"] == 0
    assert summary["housing_shortfall_total"] == 0
    assert summary["equity_share_pct"] == 0.0
    assert summary["monitoring_on_track_count"] == 0


def test_compliance_summary_echoes_the_adopted_scenario_and_the_waterfall(api):
    """The dashboard's capacity figures come from the plan's adopted scenario.

    "The plan's `housing_shortfall_total` is then the sum of `shortfall_units` across
    the four tiers, counting zero for any tier that has no row."

    Design: Corner/endpoints/compliance_summary_computed_read_reports_all_twelve_fields
    """
    ctx = _adopt_reference_scenario(api, _plan_with_two_approved_elements(api))

    assert ctx["scenario"]["land_capacity_units"] == REF_GROSS_CAPACITY
    assert ctx["scenario"]["projected_demand_units"] == REF_DEMAND_UNITS
    assert ctx["scenario"]["capacity_gap_units"] == 0

    summary = validate_success(api.get_compliance_summary(ctx["plan_id"], STATE))

    assert summary["land_capacity_units"] == REF_GROSS_CAPACITY
    assert summary["projected_demand_units"] == REF_DEMAND_UNITS
    assert summary["capacity_gap_units"] == 0
    assert summary["housing_shortfall_total"] == REF_SHORTFALL_TOTAL
    assert summary["housing_shortfall_total"] == a.expected_shortfall_total(
        REF_GROSS_CAPACITY, REF_ASSIGNED
    )
    assert summary["compliance_posture"] == C.POSTURE_CAPACITY_HOLD


def test_compliance_summary_counts_only_the_on_track_monitoring_actions(api):
    """Two actions with one reading each yield a monitoring count of one, not two.

    "The plan's `monitoring_on_track_count` is then recomputed as the number of the
    plan's implementation actions whose `on_track` is true, and the action's `version`
    is incremented by one."

    Design: Corner/endpoints/compliance_summary_computed_read_reports_all_twelve_fields
    """
    ctx = _adopt_reference_scenario(api, _plan_with_two_approved_elements(api))
    ctx = _record_two_monitoring_readings(api, ctx)

    assert ctx["on_track_action"]["on_track"] is True
    assert ctx["on_track_action"]["reading_count"] == 1
    assert ctx["off_track_action"]["on_track"] is False
    assert ctx["off_track_action"]["reading_count"] == 1

    summary = validate_success(api.get_compliance_summary(ctx["plan_id"], STAFF))

    assert summary["monitoring_on_track_count"] == 1


def test_compliance_summary_reports_the_first_matching_posture_hold(api):
    """With an open dependency, a shortfall and no participation, the hold is the first.

    "The posture is decided by a precedence ladder in which the first matching rule
    wins, and that precedence is part of the contract"

    Design: Corner/endpoints/compliance_summary_computed_read_reports_all_twelve_fields
    """
    ctx = _adopt_reference_scenario(api, _plan_with_two_approved_elements(api))
    ctx = _record_two_monitoring_readings(api, ctx)
    before = fx.read_plan(api, ctx["plan_id"])

    fx.create_link(
        api,
        ctx["elements"][C.ELEMENT_TRANSPORTATION]["id"],
        ctx["elements"][C.ELEMENT_LAND_USE]["id"],
        dependency_type=C.DEPENDENCY_LEVEL_OF_SERVICE,
    )

    summary = validate_success(api.get_compliance_summary(ctx["plan_id"], STAFF))

    # All three of the lower rungs are also unsatisfied, and the first still wins.
    assert summary["open_consistency_link_count"] == 1
    assert summary["housing_shortfall_total"] == REF_SHORTFALL_TOTAL
    assert summary["equity_share_pct"] == 0.0
    assert summary["compliance_posture"] == C.POSTURE_CONSISTENCY_HOLD
    assert summary["monitoring_on_track_count"] == 1
    assert summary["required_elements_complete_count"] == 2
    assert summary["land_capacity_units"] == REF_GROSS_CAPACITY

    # The summary is a projection of the stored plan, not a second computation.
    plan = fx.read_plan(api, ctx["plan_id"])
    for field in (
        "compliance_posture",
        "open_consistency_link_count",
        "housing_shortfall_total",
        "equity_share_pct",
        "required_elements_complete_count",
        "monitoring_on_track_count",
    ):
        assert plan[field] == summary[field], f"the plan and the summary disagree on {field}"
    a.assert_posture_consistent(plan)

    # A read is not a mutation: "version ... increments by exactly 1 on every
    # mutation of that row".
    version_before_reads = plan["version"]
    validate_success(api.get_compliance_summary(ctx["plan_id"], DIRECTOR))
    validate_success(api.get_compliance_summary(ctx["plan_id"], CONSULTANT))
    assert fx.read_plan(api, ctx["plan_id"])["version"] == version_before_reads
    assert before["version"] <= version_before_reads


# ============================================================== consistency links
def _plan_with_three_draft_elements(api):
    plan = fx.create_plan(api)
    return {
        "plan_id": plan["id"],
        "source": fx.create_element(
            api, plan["id"], C.ELEMENT_TRANSPORTATION, policy_count=3
        ),
        "target": fx.create_element(api, plan["id"], C.ELEMENT_LAND_USE, policy_count=3),
        "other": fx.create_element(api, plan["id"], C.ELEMENT_PARKS, policy_count=3),
    }


@pytest.mark.parametrize("bad_side", ["source_element_id", "target_element_id"])
def test_an_unknown_element_on_either_side_of_a_dependency_is_the_same_refusal(
    api, bad_side
):
    """Both foreign keys in the body resolve against the same collection.

    "Both ids must resolve to existing elements, otherwise `ERR_ELEMENT_NOT_FOUND`;
    both elements must belong to the same plan, otherwise `ERR_CROSS_PLAN_LINK`; and
    that plan must not already be adopted."

    Design: Corner/endpoints/consistency_link_is_a_cross_reference_endpoint
    """
    ctx = _plan_with_three_draft_elements(api)
    payload = f.consistency_link_payload(ctx["source"]["id"], ctx["target"]["id"])
    payload[bad_side] = NON_EXISTENT_UUID

    validate_error(api.create_consistency_link(payload, STAFF), ERR_ELEMENT_NOT_FOUND, 404)

    rows, meta = validate_paginated(api.list_consistency_links(STAFF))
    assert meta["total_count"] == 0
    assert rows == []


def test_a_declared_dependency_records_the_directed_pair_and_starts_open(api):
    """The row keeps source, target and dependency type, and enters OPEN unreconciled.

    "A newly declared link enters `OPEN`."

    Design: Corner/endpoints/consistency_link_is_a_cross_reference_endpoint
    """
    ctx = _plan_with_three_draft_elements(api)

    link = validate_success(
        api.create_consistency_link(
            f.consistency_link_payload(
                ctx["source"]["id"],
                ctx["target"]["id"],
                dependency_type=C.DEPENDENCY_LEVEL_OF_SERVICE,
            ),
            STAFF,
        ),
        201,
    )

    a.assert_fields_equal(
        link,
        {
            "source_element_id": ctx["source"]["id"],
            "target_element_id": ctx["target"]["id"],
            "dependency_type": C.DEPENDENCY_LEVEL_OF_SERVICE,
            "status": C.LINK_STATUS_OPEN,
            "reconciled_by_user_id": None,
            "reconciliation_note": None,
            "staled_by_amendment_id": None,
        },
    )
    a.assert_versioned_row(link, 1)

    # Reads are open to all five roles while declaring one is staff-only.
    assert validate_success(api.get_consistency_link(link["id"], CLERK)) == link

    # Neither endpoint of the dependency has to be reviewed for it to exist.
    for role_key in ("source", "target"):
        element = fx.read_element(api, ctx[role_key]["id"])
        assert element["status"] == C.ELEMENT_STATUS_DRAFT
        assert element["consistency_status"] == C.CONSISTENCY_PENDING

    # The counter follows the source element's plan.
    assert fx.read_plan(api, ctx["plan_id"])["open_consistency_link_count"] == 1


def test_dependency_filters_are_directed_and_narrow_the_total_count(api):
    """The same element does not answer to both the source and the target filter.

    "Those filters are the documented reverse lookup for the corresponding stored
    reference"

    Design: Corner/endpoints/consistency_link_is_a_cross_reference_endpoint
    """
    ctx = _plan_with_three_draft_elements(api)
    link = fx.create_link(
        api,
        ctx["source"]["id"],
        ctx["target"]["id"],
        dependency_type=C.DEPENDENCY_LEVEL_OF_SERVICE,
    )

    rows, meta = validate_paginated(
        api.list_consistency_links(
            STAFF,
            params={"source_element_id": ctx["source"]["id"], "status": C.LINK_STATUS_OPEN},
        )
    )
    assert meta["total_count"] == 1
    assert a.ids_of(rows) == [link["id"]]

    _, meta = validate_paginated(
        api.list_consistency_links(
            STAFF, params={"target_element_id": ctx["source"]["id"]}
        )
    )
    assert meta["total_count"] == 0

    rows, meta = validate_paginated(
        api.list_consistency_links(
            STAFF, params={"dependency_type": C.DEPENDENCY_LEVEL_OF_SERVICE}
        )
    )
    assert meta["total_count"] == 1
    assert a.ids_of(rows) == [link["id"]]

    _, meta = validate_paginated(
        api.list_consistency_links(
            STAFF, params={"source_element_id": ctx["other"]["id"]}
        )
    )
    assert meta["total_count"] == 0


# ================================================================= logical clock
CLOCK_MOVES = [
    (C.ROLE_PLANNING_STAFF, "2026-08-05T00:00:00.000Z"),
    (C.ROLE_PLANNING_DIRECTOR, "2026-09-01T09:30:00.000Z"),
    (C.ROLE_ENVIRONMENTAL_CONSULTANT, "2026-10-15T12:00:00.000Z"),
    (C.ROLE_COMMISSION_CLERK, "2026-07-20T06:15:00.000Z"),
    (C.ROLE_STATE_REVIEWER, "2026-12-31T23:59:59.000Z"),
]


@pytest.mark.parametrize("role, instant", CLOCK_MOVES)
def test_every_role_may_set_the_logical_clock(api, role, instant):
    """Driving time is the one write that is not reserved to a single role.

    "All five roles may read every single-resource read, list and computed-read
    endpoint under `/planning`, and all five may drive the logical clock."

    Design: Corner/endpoints/logical_clock_action_endpoint_is_shared_by_every_role
    """
    data = validate_success(api.set_clock(instant, ALL_ROLE_HEADERS[role]))

    a.assert_instant_equals(data["current_utc"], instant, "current_utc")


def test_setting_the_same_instant_twice_is_not_an_advance(api):
    """The control sets an absolute instant, so a repeat call is a no-op.

    "An administrative capability accepts a `to_iso8601` instant and sets the clock to
    it, returning the new value as `current_utc`."

    Design: Corner/endpoints/logical_clock_action_endpoint_is_shared_by_every_role
    """
    first = validate_success(api.set_clock("2026-09-01T09:30:00.000Z", STATE))
    second = validate_success(api.set_clock("2026-09-01T09:30:00.000Z", CONSULTANT))

    assert first["current_utc"] == second["current_utc"]
    a.assert_instant_equals(second["current_utc"], "2026-09-01T09:30:00.000Z", "current_utc")

    # Backwards is equally legal, and the echo is the value that was asked for.
    third = validate_success(api.set_clock("2026-08-10T00:00:00.000Z", CLERK))
    a.assert_instant_equals(third["current_utc"], "2026-08-10T00:00:00.000Z", "current_utc")


def test_a_time_gate_recloses_when_the_clock_is_moved_backwards(api):
    """An activity closable at 2026-09-01 is refused again once time is wound back.

    "The clock may be moved both forward and backward, and setting it mutates no
    entity — subsequent requests simply evaluate every temporal rule against the new
    instant."

    Design: Corner/endpoints/logical_clock_action_endpoint_is_shared_by_every_role
    """
    plan = fx.create_plan(api)
    venue = fx.create_venue(
        api,
        name="Eastside Community Center",
        turnover_buffer_minutes=0,
        ada_accessible=True,
        transit_served=True,
    )
    activity = fx.create_activity(
        api,
        plan["id"],
        activity_type=C.ACTIVITY_WORKSHOP,
        title="Eastside workshop",
        venue_id=venue["id"],
        start_at="2026-08-20T18:00:00.000Z",
        end_at="2026-08-20T20:00:00.000Z",
    )
    fx.add_participation(
        api,
        activity["id"],
        respondent_ref="resident-1",
        demographic_group=C.GROUP_LOW_INCOME,
        census_tract="06001402100",
    )

    # The startup clock of 2026-08-01T00:00:00Z sits before the activity's end.
    validate_error(
        api.complete_engagement_activity(activity["id"], {}, STAFF),
        ERR_ACTIVITY_NOT_ENDED,
        409,
    )

    fx.set_clock(api, "2026-09-01T09:30:00.000Z", STATE)
    fx.set_clock(api, "2026-08-10T00:00:00.000Z", CLERK)

    validate_error(
        api.complete_engagement_activity(activity["id"], {}, STAFF),
        ERR_ACTIVITY_NOT_ENDED,
        409,
    )

    # Exactly at end_at the inclusive comparison passes.
    fx.set_clock(api, "2026-08-20T20:00:00.000Z", DIRECTOR)
    completed = validate_success(
        api.complete_engagement_activity(activity["id"], {}, STAFF)
    )

    assert completed["status"] == C.ACTIVITY_STATUS_COMPLETED
    assert completed["equity_share_pct"] == 100.0
    assert (
        validate_success(api.get_engagement_activity(activity["id"], CLERK))["status"]
        == C.ACTIVITY_STATUS_COMPLETED
    )


# ======================================================== preferred alternative
ALT_A_LABEL = "Alternative A - infill focus"
ALT_B_LABEL = "Alternative B - corridor focus"


def _review_with_two_scored_alternatives(api):
    """A DRAFT EIR carrying an all-40 and an all-60 alternative."""
    plan = fx.create_plan(api)
    review = fx.create_review(api, plan["id"], C.DOC_EIR, title="Horizon 2045 Draft EIR")
    alt_a = fx.add_alternative(api, review["id"], label=ALT_A_LABEL)
    alt_b = fx.add_alternative(
        api,
        review["id"],
        label=ALT_B_LABEL,
        traffic_vmt_index=60,
        ghg_index=60,
        habitat_index=60,
        water_index=60,
    )
    return {
        "plan_id": plan["id"],
        "review_id": review["id"],
        "alt_a": alt_a,
        "alt_b": alt_b,
    }


def _alternatives_by_id(api, review_id):
    rows, meta = validate_paginated(api.list_review_alternatives(review_id, CONSULTANT))
    return {row["id"]: row for row in rows}, meta


def test_the_selector_cannot_run_before_the_document_is_circulated(api):
    """A DRAFT review has not been seen by the public, so nothing may be preferred yet.

    "The review must be `CIRCULATED`, otherwise `ERR_REVIEW_NOT_CIRCULATED`."

    Design: Corner/endpoints/preferred_alternative_selection_is_conditional_on_circulation
    """
    ctx = _review_with_two_scored_alternatives(api)

    validate_error(
        api.select_preferred_alternative(ctx["review_id"], {}, CONSULTANT),
        ERR_REVIEW_NOT_CIRCULATED,
        409,
    )

    rows, _ = _alternatives_by_id(api, ctx["review_id"])
    for alt_id in (ctx["alt_a"]["id"], ctx["alt_b"]["id"]):
        assert rows[alt_id]["status"] == C.ALTERNATIVE_STATUS_EVALUATED
    review = validate_success(api.get_environmental_review(ctx["review_id"], CONSULTANT))
    assert review["preferred_alternative_id"] is None
    assert review["status"] == C.REVIEW_STATUS_DRAFT


def test_certification_waits_for_the_comment_window_and_then_for_the_selection(api):
    """The clock gate and the selection gate are two separate rungs, in that order.

    "The comment period must have elapsed — the logical clock must have reached
    `comment_period_ends_at` — otherwise the attempt is refused with
    `ERR_COMMENT_PERIOD_OPEN`."

    Design: Corner/endpoints/preferred_alternative_selection_is_conditional_on_circulation
    """
    ctx = _review_with_two_scored_alternatives(api)

    circulated = fx.circulate_review(api, ctx["review_id"])

    assert circulated["comment_period_days"] == C.COMMENT_PERIOD_DAYS[C.DOC_EIR] == 45
    a.assert_instant_equals(circulated["circulated_at"], C.CLOCK_STARTUP, "circulated_at")
    a.assert_instant_equals(
        circulated["comment_period_ends_at"], "2026-09-15T00:00:00.000Z",
        "comment_period_ends_at",
    )

    validate_error(
        api.certify_environmental_review(ctx["review_id"], {}, DIRECTOR),
        ERR_COMMENT_PERIOD_OPEN,
        409,
    )

    fx.set_clock(api, "2026-09-14T23:59:59.000Z")
    validate_error(
        api.certify_environmental_review(ctx["review_id"], {}, DIRECTOR),
        ERR_COMMENT_PERIOD_OPEN,
        409,
    )

    # On the instant itself the window has elapsed and the next rung answers.
    fx.set_clock(api, "2026-09-15T00:00:00.000Z")
    validate_error(
        api.certify_environmental_review(ctx["review_id"], {}, DIRECTOR),
        ERR_PREFERRED_ALTERNATIVE_NOT_SELECTED,
        409,
    )
    assert (
        validate_success(api.get_environmental_review(ctx["review_id"], DIRECTOR))["status"]
        == C.REVIEW_STATUS_CIRCULATED
    )


def test_the_selector_returns_the_winning_alternative_and_certification_follows(api):
    """The response body is the winning alternative, not the review named in the path.

    "The winner moves `EVALUATED → PREFERRED` with its `version` incremented, any
    incumbent alternative in `PREFERRED` moves `PREFERRED → SUPERSEDED` with its
    `version` incremented, and the review's `preferred_alternative_id` is pointed at the
    winner while the review's `version` is incremented by one."

    Design: Corner/endpoints/preferred_alternative_selection_is_conditional_on_circulation
    """
    ctx = _review_with_two_scored_alternatives(api)
    fx.circulate_review(api, ctx["review_id"])
    fx.set_clock(api, "2026-09-15T00:00:00.000Z")

    winner = validate_success(
        api.select_preferred_alternative(ctx["review_id"], {}, CONSULTANT)
    )

    assert winner["id"] == ctx["alt_a"]["id"]
    assert winner["label"] == ALT_A_LABEL
    assert winner["status"] == C.ALTERNATIVE_STATUS_PREFERRED
    assert winner["net_impact_score"] == 40.00
    a.assert_alternative_scores(winner)

    # The losing alternative is left exactly as it was scored.
    rows, meta = _alternatives_by_id(api, ctx["review_id"])
    loser = rows[ctx["alt_b"]["id"]]
    assert loser["status"] == C.ALTERNATIVE_STATUS_EVALUATED
    assert loser["raw_impact_score"] == 60.00
    assert loser["mitigation_credit"] == 6.00
    assert loser["net_impact_score"] == 54.00
    assert meta["total_count"] == 2
    assert [
        row for row in rows.values() if row["status"] == C.ALTERNATIVE_STATUS_PREFERRED
    ] == [rows[ctx["alt_a"]["id"]]]

    # Selecting is not certifying.
    review = validate_success(api.get_environmental_review(ctx["review_id"], CONSULTANT))
    assert review["preferred_alternative_id"] == ctx["alt_a"]["id"]
    assert review["status"] == C.REVIEW_STATUS_CIRCULATED

    certified = validate_success(
        api.certify_environmental_review(ctx["review_id"], {}, DIRECTOR)
    )
    assert certified["status"] == C.REVIEW_STATUS_CERTIFIED
    a.assert_instant_equals(
        certified["certified_at"], "2026-09-15T00:00:00.000Z", "certified_at"
    )


# ================================================================ element revision
ORIGINAL_TITLE = "Housing Element"
ORIGINAL_BODY = "Sites inventory and constraints analysis."
REVISED_TITLE = "Housing Element - 6th Cycle"
REVISED_BODY = "Sites inventory, constraints analysis and AFFH programs."


def _draft_housing_element(api):
    plan = fx.create_plan(api)
    element = fx.create_element(
        api,
        plan["id"],
        C.ELEMENT_HOUSING,
        title=ORIGINAL_TITLE,
        draft_body=ORIGINAL_BODY,
        policy_count=9,
    )
    return plan["id"], element


def test_a_partial_revision_leaves_the_fields_it_omits_untouched(api):
    """A body carrying one field revises that field only; the others keep their text.

    "A revision may replace the `title`, the `draft_body` and the `policy_count`, in any
    combination, and each revision increments the element's `version`."

    Design: Corner/endpoints/plan_element_patch_is_the_only_update_and_it_is_partial
    """
    _, element = _draft_housing_element(api)
    base_version = element["version"]

    first = validate_success(
        api.patch_plan_element(element["id"], {"policy_count": 11}, STAFF)
    )
    a.assert_fields_equal(
        first,
        {
            "policy_count": 11,
            "title": ORIGINAL_TITLE,
            "draft_body": ORIGINAL_BODY,
            "version": base_version + 1,
        },
    )

    second = validate_success(
        api.patch_plan_element(element["id"], {"title": REVISED_TITLE}, STAFF)
    )
    a.assert_fields_equal(
        second,
        {
            "title": REVISED_TITLE,
            "policy_count": 11,
            "draft_body": ORIGINAL_BODY,
            "version": base_version + 2,
        },
    )


def test_the_revision_endpoint_is_shared_by_staff_and_the_director(api):
    """Both authoring roles may revise, and each revision is a self-loop out of DRAFT.

    "Revising an element that is already in `DRAFT` is a self-loop that changes nothing
    but content"

    Design: Corner/endpoints/plan_element_patch_is_the_only_update_and_it_is_partial
    """
    _, element = _draft_housing_element(api)
    base_version = element["version"]

    get_success_data(api.patch_plan_element(element["id"], {"policy_count": 11}, STAFF))
    get_success_data(api.patch_plan_element(element["id"], {"title": REVISED_TITLE}, STAFF))
    third = validate_success(
        api.patch_plan_element(
            element["id"], {"draft_body": REVISED_BODY, "policy_count": 12}, DIRECTOR
        )
    )

    a.assert_fields_equal(
        third,
        {
            "title": REVISED_TITLE,
            "draft_body": REVISED_BODY,
            "policy_count": 12,
            "status": C.ELEMENT_STATUS_DRAFT,
            "revision_round": 0,
            "version": base_version + 3,
        },
    )
    a.assert_instant_equals(third["created_at"], element["created_at"], "created_at")
    a.assert_three_digit_instant(third["updated_at"], "updated_at")


def test_a_revision_is_visible_to_the_read_and_the_parent_list_at_once(api):
    """The revised text is readable by every role and filterable in the same cycle.

    "there are no background jobs and no eventual reconciliation — by the time a
    mutating request returns, every derived counter, every cascaded child state and
    every recomputed gate on the plan already reflects the write."

    Design: Corner/endpoints/plan_element_patch_is_the_only_update_and_it_is_partial
    """
    plan_id, element = _draft_housing_element(api)
    get_success_data(
        api.patch_plan_element(
            element["id"],
            {"title": REVISED_TITLE, "draft_body": REVISED_BODY, "policy_count": 12},
            STAFF,
        )
    )

    read_back = validate_success(api.get_plan_element(element["id"], CLERK))
    a.assert_fields_equal(
        read_back,
        {
            "title": REVISED_TITLE,
            "draft_body": REVISED_BODY,
            "policy_count": 12,
            "status": C.ELEMENT_STATUS_DRAFT,
        },
    )

    rows, meta = validate_paginated(
        api.list_plan_elements(
            plan_id,
            STAFF,
            params={
                "element_type": C.ELEMENT_HOUSING,
                "status": C.ELEMENT_STATUS_DRAFT,
            },
        )
    )
    assert meta["total_count"] == 1
    assert rows[0] == read_back
