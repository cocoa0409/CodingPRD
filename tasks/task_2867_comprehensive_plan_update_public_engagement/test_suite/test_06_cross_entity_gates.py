"""Writes that are legal or illegal depending on another row's state.

Three transitions in this service are gated by a sibling entity rather than by
their own row: a growth scenario may only be pinned to a certified land use
dataset, an environmental review may only be circulated and certified once its
alternatives are numerous enough and one of them has been picked, and the housing
chapter may only be approved once the plan carries an adopted projection. Each is
exercised twice with the identical request body, once against the blocking state
and once against the permitting one.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_INSUFFICIENT_ALTERNATIVES,
    ERR_INVENTORY_NOT_CERTIFIED,
    ERR_PREFERRED_ALTERNATIVE_NOT_SELECTED,
    ERR_SCENARIO_NOT_ADOPTED,
)
from test_helpers.assertions import (
    expected_capacity_gap,
    expected_gross_capacity,
    expected_impact_triple,
    expected_projected_demand,
)
from test_helpers.test_users import CONSULTANT, DIRECTOR, DIRECTOR_ID, STAFF

# The reference acreage of the PRD's worked example.
REF_VACANT = 400
REF_UNDERUTILIZED = 250
REF_CONSTRAINED = 60
REF_DENSITY = 18


# ------------------------------------------- a scenario needs a certified dataset
def _plan_with_draft_land_use(api):
    plan = fx.create_plan(api)
    dataset = fx.create_land_use_inventory(
        api,
        plan["id"],
        vacant_acres=REF_VACANT,
        underutilized_acres=REF_UNDERUTILIZED,
        infrastructure_constrained_acres=REF_CONSTRAINED,
        allowed_density_units_per_acre=REF_DENSITY,
    )
    assert dataset["status"] == C.INVENTORY_STATUS_DRAFT
    assert dataset["version"] == 1
    return plan, dataset


def _scenario_body(plan_id, dataset):
    return f.growth_scenario_payload(plan_id, dataset["id"], dataset["version"])


def test_a_scenario_cannot_be_pinned_to_an_uncertified_land_use_dataset(api):
    """The acreage is not yet official, so the projection cannot be written.

    PRD: "a dataset still in `DRAFT`, or already `SUPERSEDED`, is refused with
    `ERR_INVENTORY_NOT_CERTIFIED`. Uncertified acreage is never silently skipped or
    substituted."

    Design: Difficulty/cross_entity_state_dependency/scenario_create_requires_certified_land_use_inventory
    """
    plan, dataset = _plan_with_draft_land_use(api)

    refused = api.create_growth_scenario(_scenario_body(plan["id"], dataset), STAFF)
    validate_error(refused, ERR_INVENTORY_NOT_CERTIFIED)

    stored = validate_success(api.get_inventory_dataset(dataset["id"], STAFF))
    assert stored["status"] == C.INVENTORY_STATUS_DRAFT
    assert stored["version"] == 1
    assert stored["referencing_scenario_count"] == 0
    assert fx.read_plan(api, plan["id"])["adopted_scenario_id"] is None


def test_the_same_request_body_is_accepted_once_the_dataset_is_certified(api):
    """Certification alone turns the refused write into a scored projection.

    PRD: "When the scenario is accepted it enters `DRAFT`, the pinned dataset's
    `referencing_scenario_count` is incremented by one and the dataset's `version` is
    incremented by one — which is exactly why a second scenario pinned to the same
    dataset must re-read it first."

    Design: Difficulty/cross_entity_state_dependency/scenario_create_requires_certified_land_use_inventory
    """
    plan, dataset = _plan_with_draft_land_use(api)
    validate_error(
        api.create_growth_scenario(_scenario_body(plan["id"], dataset), STAFF),
        ERR_INVENTORY_NOT_CERTIFIED,
    )

    certified = fx.certify_inventory(api, dataset["id"])
    assert certified["status"] == C.INVENTORY_STATUS_CERTIFIED
    assert certified["version"] == 2

    body = _scenario_body(plan["id"], certified)
    scenario = validate_success(
        api.create_growth_scenario(body, STAFF), expected_status=201
    )
    assert scenario["capacity_variant"] == C.CAPACITY_VARIANT_GROSS
    assert scenario["land_capacity_units"] == expected_gross_capacity(
        REF_VACANT, REF_UNDERUTILIZED, REF_DENSITY
    ) == 11700
    demand = expected_projected_demand(
        body["method"],
        body["base_households"],
        body["annual_household_growth_rate"],
        body["horizon_year"],
        plan["base_year"],
        body["job_growth_total"],
        body["demolition_replacement_units"],
    )
    assert scenario["projected_demand_units"] == demand == 12144
    assert scenario["capacity_gap_units"] == expected_capacity_gap(demand, 11700) == 444

    counted = validate_success(api.get_inventory_dataset(dataset["id"], STAFF))
    assert counted["referencing_scenario_count"] == 1
    assert counted["version"] == 3


def test_writing_a_scenario_is_not_the_same_as_adopting_one(api):
    """The accepted write leaves the plan without an official projection.

    PRD: "because a brand-new plan has no adopted scenario, the answer is always
    `CAPACITY_HOLD` — a plan is never born `CLEAR`."

    Design: Difficulty/cross_entity_state_dependency/scenario_create_requires_certified_land_use_inventory
    """
    plan, dataset = _plan_with_draft_land_use(api)
    certified = fx.certify_inventory(api, dataset["id"])
    scenario = validate_success(
        api.create_growth_scenario(_scenario_body(plan["id"], certified), STAFF),
        expected_status=201,
    )
    assert scenario["status"] == C.SCENARIO_STATUS_DRAFT

    stored = fx.read_plan(api, plan["id"])
    assert stored["adopted_scenario_id"] is None
    assert stored["compliance_posture"] == C.POSTURE_CAPACITY_HOLD
    assert stored["status"] == C.PLAN_STATUS_DRAFTING


# ------------------------------- a review needs alternatives, then a chosen one
ALT_LOW = {
    "label": "Transit-Focused Alternative",
    "traffic_vmt_index": 49,
    "ghg_index": 49,
    "habitat_index": 49,
    "water_index": 49,
}
ALT_HIGH = {
    "label": "Auto-Oriented Alternative",
    "traffic_vmt_index": 70,
    "ghg_index": 70,
    "habitat_index": 70,
    "water_index": 70,
}


def _review_with_one_alternative(api):
    plan = fx.create_plan(api)
    review = fx.create_review(api, plan["id"], C.DOC_EIR)
    assert review["status"] == C.REVIEW_STATUS_DRAFT
    low = fx.add_alternative(api, review["id"], **ALT_LOW)
    return plan, review, low


def _circulated_pair(api):
    plan, review, low = _review_with_one_alternative(api)
    high = fx.add_alternative(api, review["id"], **ALT_HIGH)
    circulated = fx.circulate_review(api, review["id"])
    return plan, circulated, low, high


def test_a_review_carrying_one_alternative_cannot_be_circulated(api):
    """A second alternative is the price of releasing the document for comment.

    PRD: "a review must carry at least two alternatives before it may circulate, and
    a review carrying fewer is refused with `ERR_INSUFFICIENT_ALTERNATIVES`."

    Design: Difficulty/cross_entity_state_dependency/review_certify_requires_selected_preferred_alternative
    """
    plan, review, low = _review_with_one_alternative(api)
    assert low["status"] == C.ALTERNATIVE_STATUS_EVALUATED

    refused = api.circulate_environmental_review(review["id"], {}, CONSULTANT)
    validate_error(refused, ERR_INSUFFICIENT_ALTERNATIVES)
    held = validate_success(api.get_environmental_review(review["id"], CONSULTANT))
    assert held["status"] == C.REVIEW_STATUS_DRAFT
    assert held["alternative_count"] == 1 < C.MIN_ALTERNATIVES_FOR_CIRCULATION
    assert held["circulated_at"] is None

    fx.add_alternative(api, review["id"], **ALT_HIGH)
    circulated = fx.circulate_review(api, review["id"])
    assert circulated["status"] == C.REVIEW_STATUS_CIRCULATED
    assert circulated["alternative_count"] == 2
    assert circulated["comment_period_days"] == C.COMMENT_PERIOD_DAYS[C.DOC_EIR] == 45
    assert circulated["circulated_at"] == C.CLOCK_STARTUP
    assert circulated["comment_period_ends_at"] == fx.T_COMMENT_END_EIR


def test_certification_is_refused_while_no_alternative_has_been_preferred(api):
    """With the comment window exactly elapsed, the unchosen alternative is the
    only remaining obstacle.

    PRD: "a preferred alternative must already have been selected, so a review whose
    `preferred_alternative_id` is still null is refused with
    `ERR_PREFERRED_ALTERNATIVE_NOT_SELECTED`, a check that sits below the clock gate
    on the ladder."

    Design: Difficulty/cross_entity_state_dependency/review_certify_requires_selected_preferred_alternative
    """
    plan, circulated, low, high = _circulated_pair(api)
    assert circulated["preferred_alternative_id"] is None

    fx.set_clock(api, circulated["comment_period_ends_at"])
    refused = api.certify_environmental_review(circulated["id"], {}, DIRECTOR)
    validate_error(refused, ERR_PREFERRED_ALTERNATIVE_NOT_SELECTED)

    held = validate_success(api.get_environmental_review(circulated["id"], DIRECTOR))
    assert held["status"] == C.REVIEW_STATUS_CIRCULATED
    assert held["preferred_alternative_id"] is None
    assert held["certified_at"] is None


def test_the_selector_unblocks_certification_and_leaves_the_loser_evaluated(api):
    """Once the lowest-impact alternative is preferred the same call certifies.

    PRD: "the candidates are ordered by `net_impact_score` ascending, because the
    lowest environmental impact wins"

    Design: Difficulty/cross_entity_state_dependency/review_certify_requires_selected_preferred_alternative
    """
    plan, circulated, low, high = _circulated_pair(api)
    assert low["net_impact_score"] == expected_impact_triple(49, 49, 49, 49)[2] == 49.00
    assert high["net_impact_score"] == expected_impact_triple(70, 70, 70, 70)[2] == 59.50

    fx.set_clock(api, circulated["comment_period_ends_at"])
    validate_error(
        api.certify_environmental_review(circulated["id"], {}, DIRECTOR),
        ERR_PREFERRED_ALTERNATIVE_NOT_SELECTED,
    )

    picked = fx.select_preferred(api, circulated["id"])
    assert picked["id"] == low["id"]
    assert picked["status"] == C.ALTERNATIVE_STATUS_PREFERRED
    chosen = validate_success(api.get_environmental_review(circulated["id"], DIRECTOR))
    assert chosen["preferred_alternative_id"] == low["id"]

    certified = fx.certify_review(api, circulated["id"])
    assert certified["status"] == C.REVIEW_STATUS_CERTIFIED
    assert certified["certified_at"] == fx.T_COMMENT_END_EIR

    rows = fx.rows_of(
        api.list_review_alternatives(circulated["id"], CONSULTANT, limit=C.MAX_LIMIT)
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id[high["id"]]["status"] == C.ALTERNATIVE_STATUS_EVALUATED
    assert by_id[low["id"]]["status"] == C.ALTERNATIVE_STATUS_PREFERRED


# ----------------------- the housing chapter needs an adopted projection
def _plan_with_two_chapters_in_review(api):
    """Four certified datasets, a projection that is still a draft, and both the
    housing and transportation chapters in front of the director."""
    plan = fx.create_plan(api)
    inventories = fx.certified_inventory_set(api, plan["id"])
    scenario = fx.create_scenario(
        api, plan["id"], inventories[C.INVENTORY_LAND_USE]["id"], method=C.METHOD_TREND
    )
    assert scenario["status"] == C.SCENARIO_STATUS_DRAFT
    assert fx.read_plan(api, plan["id"])["adopted_scenario_id"] is None

    chapters = {}
    for element_type in (C.ELEMENT_HOUSING, C.ELEMENT_TRANSPORTATION):
        element = fx.create_element(api, plan["id"], element_type)
        chapters[element_type] = fx.submit_element(api, element["id"])
        assert chapters[element_type]["status"] == C.ELEMENT_STATUS_IN_REVIEW
    return plan, scenario, chapters


def test_the_housing_chapter_cannot_be_approved_without_an_adopted_projection(api):
    """The refused decision is not recorded as a revision round either.

    PRD: "when the element under review is the `HOUSING` element, the plan must
    already have an adopted projection — its `adopted_scenario_id` must be set and the
    scenario it names must be in status `ADOPTED` — because a housing element cannot
    be blessed without the capacity numbers it is written against; failing that, the
    decision is refused with `ERR_SCENARIO_NOT_ADOPTED`."

    Design: Difficulty/cross_entity_state_dependency/element_approve_requires_adopted_growth_scenario
    """
    plan, scenario, chapters = _plan_with_two_chapters_in_review(api)
    housing = chapters[C.ELEMENT_HOUSING]

    refused = api.record_review_decision(
        housing["id"],
        f.review_decision_payload(
            C.DECISION_APPROVE, "Approve subject to the adopted projection."
        ),
        DIRECTOR,
    )
    validate_error(refused, ERR_SCENARIO_NOT_ADOPTED)

    held = fx.read_element(api, housing["id"])
    assert held["status"] == C.ELEMENT_STATUS_IN_REVIEW
    assert held["revision_round"] == 0
    assert held["reviewed_by_user_id"] is None
    assert held["consistency_status"] == housing["consistency_status"]
    assert fx.read_plan(api, plan["id"])["required_elements_complete_count"] == 0


def test_the_transportation_chapter_is_approved_against_the_same_draft_projection(api):
    """The gate is conditional on the chapter, not on the plan's projection alone.

    PRD: "An approval moves the element `IN_REVIEW → APPROVED`, stamps
    `reviewed_by_user_id` with the deciding director's identifier, sets the element's
    `consistency_status` to `CLEARED`, and increments the element's `version`."

    Design: Difficulty/cross_entity_state_dependency/element_approve_requires_adopted_growth_scenario
    """
    plan, scenario, chapters = _plan_with_two_chapters_in_review(api)
    validate_error(
        api.record_review_decision(
            chapters[C.ELEMENT_HOUSING]["id"],
            f.review_decision_payload(C.DECISION_APPROVE),
            DIRECTOR,
        ),
        ERR_SCENARIO_NOT_ADOPTED,
    )

    transportation = fx.approve_element(api, chapters[C.ELEMENT_TRANSPORTATION]["id"])
    assert transportation["status"] == C.ELEMENT_STATUS_APPROVED
    assert transportation["reviewed_by_user_id"] == DIRECTOR_ID
    assert transportation["consistency_status"] == C.CONSISTENCY_CLEARED

    still_draft = validate_success(api.get_growth_scenario(scenario["id"], STAFF))
    assert still_draft["status"] == C.SCENARIO_STATUS_DRAFT
    plan_row = fx.read_plan(api, plan["id"])
    assert plan_row["adopted_scenario_id"] is None
    assert plan_row["required_elements_complete_count"] == 1


def test_adopting_the_projection_lets_the_housing_chapter_through(api):
    """The identical decision succeeds once the projection is official.

    PRD: "`required_elements_complete_count` is recomputed as the number of distinct
    element types now standing in `APPROVED` or `ADOPTED`, `compliance_posture` is
    recomputed, and the plan's `version` is incremented by one."

    Design: Difficulty/cross_entity_state_dependency/element_approve_requires_adopted_growth_scenario
    """
    plan, scenario, chapters = _plan_with_two_chapters_in_review(api)
    validate_error(
        api.record_review_decision(
            chapters[C.ELEMENT_HOUSING]["id"],
            f.review_decision_payload(C.DECISION_APPROVE),
            DIRECTOR,
        ),
        ERR_SCENARIO_NOT_ADOPTED,
    )
    fx.approve_element(api, chapters[C.ELEMENT_TRANSPORTATION]["id"])

    adopted = fx.adopt_scenario(api, scenario["id"])
    assert adopted["status"] == C.SCENARIO_STATUS_ADOPTED
    assert fx.read_plan(api, plan["id"])["adopted_scenario_id"] == scenario["id"]

    housing = fx.approve_element(api, chapters[C.ELEMENT_HOUSING]["id"])
    assert housing["status"] == C.ELEMENT_STATUS_APPROVED
    assert housing["reviewed_by_user_id"] == DIRECTOR_ID
    assert housing["consistency_status"] == C.CONSISTENCY_CLEARED

    plan_row = fx.read_plan(api, plan["id"])
    assert plan_row["required_elements_complete_count"] == 2
    assert plan_row["housing_shortfall_total"] == 0
    assert plan_row["equity_share_pct"] == 0.0
    assert plan_row["compliance_posture"] == C.POSTURE_EQUITY_HOLD
