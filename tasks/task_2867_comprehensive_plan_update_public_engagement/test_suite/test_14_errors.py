"""Error reachability: the not-found codes of every addressable entity, the
inventory and scenario lifecycle refusals, the content-readiness and wrong-phase
refusals, and the refusals a certified plan meets on its way through its adoption
hearings.

Every test drives the API through real requests from an empty database with the
logical clock at its startup value of 2026-08-01T00:00:00Z.
"""

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ACTION_NOT_FOUND,
    ERR_ACTIVITY_NOT_FOUND,
    ERR_ADOPTED_SCENARIO_PINNED,
    ERR_AMENDMENT_NOT_FOUND,
    ERR_ELEMENT_HAS_NO_POLICIES,
    ERR_ELEMENT_NOT_FOUND,
    ERR_ENVIRONMENTAL_REVIEW_NOT_CERTIFIED,
    ERR_HEARING_NOT_FOUND,
    ERR_HEARING_NOT_OPEN,
    ERR_HEARING_NOT_SCHEDULED,
    ERR_HEARING_NOT_YET_STARTED,
    ERR_INVENTORY_NOT_FOUND,
    ERR_INVENTORY_SET_INCOMPLETE,
    ERR_LINK_NOT_FOUND,
    ERR_NOTICE_PERIOD_TOO_SHORT,
    ERR_PLAN_NOT_CERTIFIED,
    ERR_PLAN_NOT_RECOMMENDED,
    ERR_PLAN_NOT_SUBMITTED,
    ERR_PLAN_UPDATE_NOT_FOUND,
    ERR_REVIEW_NOT_DRAFT,
    ERR_REVIEW_NOT_FOUND,
    ERR_SCENARIO_NOT_DRAFT,
    ERR_SCENARIO_NOT_FOUND,
    ERR_VENUE_NOT_FOUND,
)
from test_helpers.test_users import CLERK, CONSULTANT, DIRECTOR, STAFF, STATE

# --------------------------------------------------------------------- reference
# The hearing calendar of the reference adoption run. The commission slot is
# noticed exactly ten days ahead, which is the inclusive limit of the lead rule;
# the two council slots are noticed a fortnight ahead each.
T_COMMISSION_NOTICE_SHORT = "2026-09-26T18:00:00.000Z"
T_COMMISSION_NOTICE_OK = "2026-09-25T18:00:00.000Z"
T_COMMISSION_START = "2026-10-05T18:00:00.000Z"
T_COMMISSION_END = "2026-10-05T21:00:00.000Z"

T_COUNCIL_A_NOTICE = "2026-10-05T18:00:00.000Z"
T_COUNCIL_A_START = "2026-10-19T18:00:00.000Z"
T_COUNCIL_A_END = "2026-10-19T21:00:00.000Z"

T_COUNCIL_B_NOTICE = "2026-10-19T18:00:00.000Z"
T_COUNCIL_B_START = "2026-11-02T18:00:00.000Z"
T_COUNCIL_B_END = "2026-11-02T21:00:00.000Z"

# A second acreage row for the same plan, describing the same jurisdiction from a
# later survey: 380 vacant, 240 underutilized, 90 constrained, 20 units per acre.
SECOND_ACREAGE = {
    "vacant_acres": 380,
    "underutilized_acres": 240,
    "infrastructure_constrained_acres": 90,
    "allowed_density_units_per_acre": 20,
    "vintage_year": 2024,
}

# The neighbouring jurisdiction used as the second plan of the lifecycle sweep.
NEIGHBOUR_ACREAGE = {
    "vacant_acres": 300,
    "underutilized_acres": 100,
    "infrastructure_constrained_acres": 50,
    "allowed_density_units_per_acre": 12,
}


def _populated_plan(api):
    """One plan carrying a row of every kind that can be addressed by id: a
    certified acreage dataset, a draft projection, two chapters, a dependency
    between them, a workshop at a venue, an environmental document and an
    implementation action."""
    plan = fx.create_plan(api)
    plan_id = plan["id"]
    inventory = fx.certify_inventory(
        api, fx.create_land_use_inventory(api, plan_id)["id"]
    )
    scenario = fx.create_scenario(api, plan_id, inventory["id"])
    land_use = fx.create_element(api, plan_id, C.ELEMENT_LAND_USE)
    transportation = fx.create_element(api, plan_id, C.ELEMENT_TRANSPORTATION)
    link = fx.create_link(
        api,
        transportation["id"],
        land_use["id"],
        dependency_type=C.DEPENDENCY_CAPACITY_ASSUMPTION,
    )
    venue = fx.create_venue(
        api,
        name="Eastside Community Center",
        turnover_buffer_minutes=0,
        ada_accessible=True,
        transit_served=True,
    )
    activity = fx.create_activity(
        api,
        plan_id,
        activity_type=C.ACTIVITY_WORKSHOP,
        title="Eastside Neighborhood Workshop",
        venue_id=venue["id"],
        start_at="2026-08-20T18:00:00.000Z",
        end_at="2026-08-20T20:00:00.000Z",
    )
    review = fx.create_review(
        api, plan_id, document_type=C.DOC_NEGATIVE_DECLARATION
    )
    action = fx.create_action(api, plan_id, land_use["id"])
    return {
        "plan_id": plan_id,
        "inventory_id": inventory["id"],
        "scenario_id": scenario["id"],
        "land_use_id": land_use["id"],
        "link_id": link["id"],
        "venue_id": venue["id"],
        "activity_id": activity["id"],
        "review_id": review["id"],
        "action_id": action["id"],
    }


UNRESOLVED_PATH_READS = [
    ("get_plan_update", ERR_PLAN_UPDATE_NOT_FOUND),
    ("get_inventory_dataset", ERR_INVENTORY_NOT_FOUND),
    ("get_growth_scenario", ERR_SCENARIO_NOT_FOUND),
    ("get_plan_element", ERR_ELEMENT_NOT_FOUND),
    ("get_consistency_link", ERR_LINK_NOT_FOUND),
    ("get_engagement_activity", ERR_ACTIVITY_NOT_FOUND),
    ("get_environmental_review", ERR_REVIEW_NOT_FOUND),
    ("get_hearing", ERR_HEARING_NOT_FOUND),
    ("get_amendment", ERR_AMENDMENT_NOT_FOUND),
    ("get_implementation_action", ERR_ACTION_NOT_FOUND),
]


@pytest.mark.parametrize(
    "reader,expected_error_id",
    UNRESOLVED_PATH_READS,
    ids=[name for name, _ in UNRESOLVED_PATH_READS],
)
def test_each_kind_of_row_reports_its_own_not_found_code(
    api, reader, expected_error_id
):
    """A read addressed at an id of the right shape that names no row reports the
    not-found code of that kind of row, and never a neighbour's code.

    "Every id embedded in the URL path resolves to an existing row, validated
    left to right — the plan update id in a nested path is checked before the child
    id that follows it. The failing id determines the code:
    `ERR_PLAN_UPDATE_NOT_FOUND`, `ERR_INVENTORY_NOT_FOUND`,
    `ERR_SCENARIO_NOT_FOUND`, `ERR_ELEMENT_NOT_FOUND`, `ERR_LINK_NOT_FOUND`,
    `ERR_ACTIVITY_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_HEARING_NOT_FOUND`,
    `ERR_AMENDMENT_NOT_FOUND` or `ERR_ACTION_NOT_FOUND`, all HTTP 404."

    Design: Corner/errors/not_found_sweep_across_every_addressable_entity
    """
    _populated_plan(api)

    response = getattr(api, reader)(C.BOGUS_UUID, STAFF)

    error = validate_error(response, expected_error_id, 404)
    assert response.json()["response_type"] == "error"
    assert error["message"] and error["message"].strip() != ""


def test_a_booking_at_a_phantom_venue_reports_the_venue_not_found_code(api):
    """The venue reference travels in the body, so a booking naming no venue reports
    the venue's own not-found code and stores nothing.

    "Every foreign key supplied in the body resolves to an existing row,
    otherwise `ERR_PLAN_UPDATE_NOT_FOUND`, `ERR_INVENTORY_NOT_FOUND`,
    `ERR_ELEMENT_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`,
    `ERR_HEARING_NOT_FOUND` or `ERR_ACTIVITY_NOT_FOUND` (404)."

    Design: Corner/errors/not_found_sweep_across_every_addressable_entity
    """
    ctx = _populated_plan(api)

    response = api.create_engagement_activity(
        f.engagement_activity_payload(
            ctx["plan_id"],
            activity_type=C.ACTIVITY_WORKSHOP,
            title="Workshop at a room that does not exist",
            venue_id=C.BOGUS_UUID,
            start_at="2026-08-21T18:00:00.000Z",
            end_at="2026-08-21T20:00:00.000Z",
        ),
        STAFF,
    )

    validate_error(response, ERR_VENUE_NOT_FOUND, 404)
    rows, meta = validate_paginated(
        api.list_engagement_activities(STAFF, params={"plan_update_id": ctx["plan_id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [ctx["activity_id"]]


def test_a_child_collection_under_an_unknown_plan_reports_the_plan_not_found_code(api):
    """A nested collection resolves its parent first, so listing the chapters of a
    plan that does not exist is a 404 rather than an empty page.

    "path ids are resolved left to right: the parent id is looked up first, and
    a request naming a non-existent plan reports `ERR_PLAN_UPDATE_NOT_FOUND` even
    when the child id is also invalid."

    Design: Corner/errors/not_found_sweep_across_every_addressable_entity
    """
    ctx = _populated_plan(api)

    response = api.list_plan_elements(C.BOGUS_UUID, STAFF)

    validate_error(response, ERR_PLAN_UPDATE_NOT_FOUND, 404)
    rows, meta = validate_paginated(api.list_plan_elements(ctx["plan_id"], STAFF))
    assert meta["total_count"] == 2
    assert len(rows) == 2


def test_gavelling_in_a_hearing_that_does_not_exist_is_a_not_found(api):
    """Path resolution precedes the state preconditions, so an unknown hearing id
    reports the hearing not-found code rather than a status conflict.

    "3. **Path resolution.** Every id embedded in the URL path resolves to an
    existing row, validated left to right"

    Design: Corner/errors/not_found_sweep_across_every_addressable_entity
    """
    _populated_plan(api)

    response = api.open_hearing(C.BOGUS_UUID, {}, CLERK)

    error = validate_error(response, ERR_HEARING_NOT_FOUND, 404)
    assert response.json()["response_type"] == "error"
    assert error["message"].strip() != ""


def test_rescinding_an_amendment_that_does_not_exist_is_a_not_found(api):
    """A well-formed rescission body cannot rescue an unknown amendment id: the path
    is resolved before the body is examined.

    "Validation is therefore a strictly ordered ladder, evaluated from the top,
    and the first rule that fails determines the response."

    Design: Corner/errors/not_found_sweep_across_every_addressable_entity
    """
    _populated_plan(api)

    response = api.rescind_amendment(
        C.BOGUS_UUID, {"rescission_reason": "Motion reversed on the floor."}, CLERK
    )

    error = validate_error(response, ERR_AMENDMENT_NOT_FOUND, 404)
    assert response.json()["response_type"] == "error"
    assert error["message"].strip() != ""


# ------------------------------------- inventory and projection lifecycle refusals
def _neighbour_plan(api):
    """A second jurisdiction whose existing-conditions record is deliberately
    incomplete: acreage certified, population still in draft, no employment or
    housing dataset at all."""
    plan = fx.create_plan(api, jurisdiction_code="CA0452")
    plan_id = plan["id"]
    land_use = fx.certify_inventory(
        api,
        fx.create_land_use_inventory(api, plan_id, **NEIGHBOUR_ACREAGE)["id"],
    )
    demographic = fx.create_tabular_inventory(
        api, plan_id, C.INVENTORY_DEMOGRAPHIC
    )
    scenario = fx.create_scenario(api, plan_id, land_use["id"])
    return {
        "plan_id": plan_id,
        "land_use_id": land_use["id"],
        "demographic_id": demographic["id"],
        "scenario_id": scenario["id"],
    }


def test_a_projection_that_is_already_the_official_one_cannot_be_adopted_again(api):
    """Adoption is a one-way move out of draft, so re-adopting the plan's official
    projection is refused and the plan's own row is left where it was.

    "A scenario already `ADOPTED` or `SUPERSEDED` cannot be adopted
    (`ERR_SCENARIO_NOT_DRAFT`), and the plan must not yet be adopted."

    Design: Corner/errors/inventory_and_scenario_lifecycle_error_sweep
    """
    ctx = fx.plan_with_adopted_scenario(api)
    before = fx.read_plan(api, ctx["plan_id"])

    response = api.adopt_growth_scenario(ctx["scenario_id"], {}, DIRECTOR)

    validate_error(response, ERR_SCENARIO_NOT_DRAFT)
    after = fx.read_plan(api, ctx["plan_id"])
    assert after["version"] == before["version"]
    assert after["adopted_scenario_id"] == ctx["scenario_id"]


def test_replacement_acreage_cannot_be_certified_under_an_official_projection(api):
    """A fresher acreage survey may be drafted at any time, but certifying it while
    the plan's official projection is pinned to the old survey is refused.

    "if the plan's currently certified dataset of the same `inventory_type` is
    pinned by a growth scenario that has already been adopted, certifying a
    replacement would silently invalidate the plan's official projection, so the
    attempt is refused with `ERR_ADOPTED_SCENARIO_PINNED`."

    Design: Corner/errors/inventory_and_scenario_lifecycle_error_sweep
    """
    ctx = fx.plan_with_adopted_scenario(api)
    replacement = fx.create_land_use_inventory(
        api, ctx["plan_id"], **SECOND_ACREAGE
    )
    assert replacement["status"] == C.INVENTORY_STATUS_DRAFT

    response = api.certify_inventory_dataset(replacement["id"], {}, DIRECTOR)

    validate_error(response, ERR_ADOPTED_SCENARIO_PINNED)
    incumbent = validate_success(
        api.get_inventory_dataset(ctx["land_use_inventory_id"], STAFF)
    )
    assert incumbent["status"] == C.INVENTORY_STATUS_CERTIFIED
    assert incumbent["referencing_scenario_count"] == 1
    refused = validate_success(api.get_inventory_dataset(replacement["id"], STAFF))
    assert refused["status"] == C.INVENTORY_STATUS_DRAFT


def test_a_projection_cannot_be_adopted_on_an_incomplete_conditions_record(api):
    """A projection computed from certified acreage is still a legitimate draft, but
    it cannot become official while any of the four datasets is missing.

    "the plan must hold a `CERTIFIED` dataset for each of `DEMOGRAPHIC`,
    `HOUSING`, `EMPLOYMENT` and `LAND_USE`, and a plan missing any of the four is
    refused with `ERR_INVENTORY_SET_INCOMPLETE`."

    Design: Corner/errors/inventory_and_scenario_lifecycle_error_sweep
    """
    ctx = _neighbour_plan(api)
    assert (
        validate_success(api.get_growth_scenario(ctx["scenario_id"], STAFF))["status"]
        == C.SCENARIO_STATUS_DRAFT
    )

    response = api.adopt_growth_scenario(ctx["scenario_id"], {}, DIRECTOR)

    validate_error(response, ERR_INVENTORY_SET_INCOMPLETE)
    assert fx.read_plan(api, ctx["plan_id"])["adopted_scenario_id"] is None


def test_certifying_one_missing_dataset_is_not_enough_to_adopt_the_projection(api):
    """Certifying the population dataset closes one of the three gaps, so the same
    adoption is refused again and the plan stays held on capacity.

    "Otherwise, if `adopted_scenario_id` is null or `housing_shortfall_total` is
    greater than zero, the posture is `CAPACITY_HOLD`."

    Design: Corner/errors/inventory_and_scenario_lifecycle_error_sweep
    """
    ctx = _neighbour_plan(api)
    validate_error(
        api.adopt_growth_scenario(ctx["scenario_id"], {}, DIRECTOR),
        ERR_INVENTORY_SET_INCOMPLETE,
    )
    fx.certify_inventory(api, ctx["demographic_id"])

    response = api.adopt_growth_scenario(ctx["scenario_id"], {}, DIRECTOR)

    validate_error(response, ERR_INVENTORY_SET_INCOMPLETE)
    plan = fx.read_plan(api, ctx["plan_id"])
    assert plan["adopted_scenario_id"] is None
    assert plan["compliance_posture"] == C.POSTURE_CAPACITY_HOLD


# --------------------------- content readiness and wrong-phase refusals
def _parks_chapter_without_policies(api):
    """A drafting plan whose parks chapter was filed without a policy count."""
    plan_id = fx.create_plan(api)["id"]
    element = fx.create_element(api, plan_id, C.ELEMENT_PARKS, policy_count=None)
    return {"plan_id": plan_id, "element": element, "element_id": element["id"]}


def test_a_chapter_filed_without_a_policy_count_starts_at_zero_policies(api):
    """Omitting the optional policy count does not leave the field unset: the chapter
    starts with no numbered policies at all.

    "optionally an initial `policy_count`, the number of numbered policies the
    chapter contains, which defaults to 0 and can never be negative."

    Design: Corner/errors/content_readiness_and_wrong_phase_error_sweep
    """
    ctx = _parks_chapter_without_policies(api)

    element = fx.read_element(api, ctx["element_id"])

    assert element["policy_count"] == 0
    assert element["status"] == C.ELEMENT_STATUS_DRAFT


def test_a_chapter_with_no_numbered_policies_cannot_be_sent_for_review(api):
    """An empty chapter is refused on the content-readiness rung and stays in draft.

    "an element that carries no numbered policies at all — a `policy_count` of
    zero — is refused with `ERR_ELEMENT_HAS_NO_POLICIES` on the content-readiness
    rung."

    Design: Corner/errors/content_readiness_and_wrong_phase_error_sweep
    """
    ctx = _parks_chapter_without_policies(api)

    response = api.submit_element_review(ctx["element_id"], {}, STAFF)

    validate_error(response, ERR_ELEMENT_HAS_NO_POLICIES)
    assert fx.read_element(api, ctx["element_id"])["status"] == C.ELEMENT_STATUS_DRAFT


def test_adding_one_policy_lets_the_identical_submission_through(api):
    """The refusal is about content, not about the request: once a single policy is
    recorded the very same submission moves the chapter into review.

    "Submitting a drafted element for review moves it `DRAFT → IN_REVIEW` and
    increments its `version`."

    Design: Corner/errors/content_readiness_and_wrong_phase_error_sweep
    """
    ctx = _parks_chapter_without_policies(api)
    validate_error(
        api.submit_element_review(ctx["element_id"], {}, STAFF),
        ERR_ELEMENT_HAS_NO_POLICIES,
    )
    revised = validate_success(
        api.patch_plan_element(ctx["element_id"], {"policy_count": 1}, STAFF)
    )
    assert revised["policy_count"] == 1

    submitted = validate_success(
        api.submit_element_review(ctx["element_id"], {}, STAFF)
    )

    assert submitted["status"] == C.ELEMENT_STATUS_IN_REVIEW


def test_a_negative_declaration_circulates_for_thirty_days(api):
    """The shorter statutory window belongs to the negative declaration, and it is
    stamped on the document at circulation.

    "`comment_period_days` is stamped with the statutory period — 45 days for an
    `EIR` and 30 days for a `NEGATIVE_DECLARATION`"

    Design: Corner/errors/content_readiness_and_wrong_phase_error_sweep
    """
    plan_id = fx.create_plan(api)["id"]

    circulated = fx.circulated_review(
        api, plan_id, document_type=C.DOC_NEGATIVE_DECLARATION
    )["review"]

    assert circulated["status"] == C.REVIEW_STATUS_CIRCULATED
    assert circulated["comment_period_days"] == 30
    assert circulated["alternative_count"] == 2


def test_a_third_alternative_cannot_be_added_after_circulation(api):
    """Alternatives belong to the drafting stage: once the document is out for public
    comment its set of alternatives is closed.

    "Alternatives are added while the review is still `DRAFT`; adding one to a
    review that has been circulated, certified or superseded is refused with
    `ERR_REVIEW_NOT_DRAFT`."

    Design: Corner/errors/content_readiness_and_wrong_phase_error_sweep
    """
    plan_id = fx.create_plan(api)["id"]
    ctx = fx.circulated_review(api, plan_id, document_type=C.DOC_NEGATIVE_DECLARATION)

    response = api.create_plan_alternative(
        f.plan_alternative_payload(
            ctx["review_id"],
            label="No Project Alternative",
            traffic_vmt_index=20,
            ghg_index=20,
            habitat_index=20,
            water_index=20,
        ),
        CONSULTANT,
    )

    validate_error(response, ERR_REVIEW_NOT_DRAFT)
    review = validate_success(api.get_environmental_review(ctx["review_id"], CONSULTANT))
    assert review["alternative_count"] == 2
    rows, meta = validate_paginated(
        api.list_review_alternatives(ctx["review_id"], CONSULTANT)
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2


def test_a_circulated_document_cannot_be_circulated_a_second_time(api):
    """Circulation is available from draft only, so a repeat release is refused and
    the document keeps the window it already opened.

    "Circulation releases the document for public comment and is the
    consultant's act. The review must be in `DRAFT`."

    Design: Corner/errors/content_readiness_and_wrong_phase_error_sweep
    """
    plan_id = fx.create_plan(api)["id"]
    ctx = fx.circulated_review(api, plan_id, document_type=C.DOC_NEGATIVE_DECLARATION)
    first_window_end = ctx["review"]["comment_period_ends_at"]

    response = api.circulate_environmental_review(ctx["review_id"], {}, CONSULTANT)

    validate_error(response, ERR_REVIEW_NOT_DRAFT)
    review = validate_success(api.get_environmental_review(ctx["review_id"], CONSULTANT))
    assert review["status"] == C.REVIEW_STATUS_CIRCULATED
    assert review["comment_period_ends_at"] == first_window_end


def test_a_determination_cannot_be_recorded_against_a_plan_still_in_drafting(api):
    """The state can only answer a filing it has actually received, so a
    determination against a drafting plan is refused and nothing is recorded.

    "The plan's `state_review_status` must be `SUBMITTED`; a determination
    against a plan that is not awaiting one is refused with
    `ERR_PLAN_NOT_SUBMITTED`."

    Design: Corner/errors/content_readiness_and_wrong_phase_error_sweep
    """
    plan_id = fx.create_plan(api)["id"]

    response = api.record_state_determination(
        plan_id,
        f.state_determination_payload(
            C.STATE_REVIEW_CERTIFIED, "Findings recorded out of turn."
        ),
        STATE,
    )

    validate_error(response, ERR_PLAN_NOT_SUBMITTED)
    plan = fx.read_plan(api, plan_id)
    assert plan["status"] == C.PLAN_STATUS_DRAFTING
    assert plan["state_review_status"] == C.STATE_REVIEW_NOT_SUBMITTED
    assert plan["state_findings"] is None


def test_a_hearing_cannot_be_calendared_before_the_state_certifies_the_plan(api):
    """The calendar opens only after state certification, so a commission hearing on
    a drafting plan is refused on the state rung and no hearing is stored.

    "A hearing can only be put on the calendar once the state has certified the
    plan: the plan's status must be `STATE_CERTIFIED` or `COMMISSION_RECOMMENDED`,
    and anything earlier is refused with `ERR_PLAN_NOT_CERTIFIED`."

    Design: Corner/errors/content_readiness_and_wrong_phase_error_sweep
    """
    plan_id = fx.create_plan(api)["id"]

    response = api.create_hearing(
        f.hearing_payload(
            plan_id,
            body_type=C.BODY_COMMISSION,
            scheduled_start=T_COMMISSION_START,
            scheduled_end=T_COMMISSION_END,
            notice_published_at="2026-09-20T18:00:00.000Z",
        ),
        CLERK,
    )

    validate_error(response, ERR_PLAN_NOT_CERTIFIED)
    _, meta = validate_paginated(api.list_plan_hearings(plan_id, CLERK))
    assert meta["total_count"] == 0


# ---------------------- the adoption-hearing run of a state-certified plan
def _certified_plan_with_circulated_eir(api):
    """One plan carried all the way to state certification while its environmental
    document is still only out for public comment.

    The chapters are approved before the dependency is declared, so the dependency
    can be reconciled against a chapter the plan may rely on; the document is
    released while the clock still sits at its startup value.
    """
    ctx = fx.plan_with_adopted_scenario(api)
    plan_id = ctx["plan_id"]
    fx.create_all_allocations(api, plan_id)
    elements = fx.five_approved_elements(api, plan_id)
    link = fx.create_link(
        api,
        elements[C.ELEMENT_TRANSPORTATION]["id"],
        elements[C.ELEMENT_LAND_USE]["id"],
        dependency_type=C.DEPENDENCY_LEVEL_OF_SERVICE,
    )
    fx.reconcile_link(api, link["id"])
    review = fx.circulated_review(api, plan_id)
    fx.completed_workshop(api, plan_id)
    validate_success(
        api.submit_plan_to_state(
            plan_id, {"submission_note": "Mandate filing of record."}, DIRECTOR
        )
    )
    plan = validate_success(
        api.record_state_determination(
            plan_id,
            f.state_determination_payload(
                C.STATE_REVIEW_CERTIFIED, "The mandate elements are in order."
            ),
            STATE,
        )
    )
    assert plan["status"] == C.PLAN_STATUS_STATE_CERTIFIED
    assert plan["compliance_posture"] == C.POSTURE_CLEAR
    return {
        "plan_id": plan_id,
        "elements": elements,
        "link_id": link["id"],
        "review_id": review["review_id"],
    }


def _commission_hearing(api, plan_id):
    """The commission sitting of the reference calendar, noticed exactly ten days
    before it starts."""
    return fx.create_hearing(
        api,
        plan_id,
        body_type=C.BODY_COMMISSION,
        scheduled_start=T_COMMISSION_START,
        scheduled_end=T_COMMISSION_END,
        notice_published_at=T_COMMISSION_NOTICE_OK,
    )


def _open_commission_sitting(api):
    """Certified plan, commission sitting gavelled in at its scheduled instant."""
    ctx = _certified_plan_with_circulated_eir(api)
    hearing = _commission_hearing(api, ctx["plan_id"])
    fx.set_clock(api, T_COMMISSION_START)
    opened = fx.open_hearing(api, hearing["id"])
    ctx["hearing_id"] = hearing["id"]
    ctx["hearing"] = opened
    return ctx


def _recommended_plan(api):
    """The commission recommends the plan once its environmental document has been
    certified, which is what unlocks the council calendar."""
    ctx = _open_commission_sitting(api)
    fx.select_preferred(api, ctx["review_id"])
    fx.certify_review(api, ctx["review_id"])
    fx.record_outcome(api, ctx["hearing_id"], C.OUTCOME_RECOMMEND)
    return ctx


def _two_council_sittings_in_session(api):
    """Two council sittings a fortnight apart, both gavelled in."""
    ctx = _recommended_plan(api)
    plan_id = ctx["plan_id"]
    first = fx.create_hearing(
        api,
        plan_id,
        body_type=C.BODY_COUNCIL,
        scheduled_start=T_COUNCIL_A_START,
        scheduled_end=T_COUNCIL_A_END,
        notice_published_at=T_COUNCIL_A_NOTICE,
    )
    second = fx.create_hearing(
        api,
        plan_id,
        body_type=C.BODY_COUNCIL,
        scheduled_start=T_COUNCIL_B_START,
        scheduled_end=T_COUNCIL_B_END,
        notice_published_at=T_COUNCIL_B_NOTICE,
    )
    fx.set_clock(api, T_COUNCIL_A_START)
    fx.open_hearing(api, first["id"])
    fx.set_clock(api, T_COUNCIL_B_START)
    fx.open_hearing(api, second["id"])
    ctx["first_council_id"] = first["id"]
    ctx["second_council_id"] = second["id"]
    return ctx


def test_a_sitting_noticed_nine_days_ahead_is_refused(api):
    """A notice published nine days before the gavel is one day short of the lead the
    public is owed, and the sitting never reaches the calendar.

    "Third, the **public notice lead time**: `notice_published_at` must fall no
    later than ten days before `scheduled_start`, and a shorter lead time is refused
    with `ERR_NOTICE_PERIOD_TOO_SHORT`, the only 422 among the calendar rules."

    Design: Corner/errors/certified_plan_hearing_lifecycle_error_sweep
    """
    ctx = _certified_plan_with_circulated_eir(api)

    response = api.create_hearing(
        f.hearing_payload(
            ctx["plan_id"],
            body_type=C.BODY_COMMISSION,
            scheduled_start=T_COMMISSION_START,
            scheduled_end=T_COMMISSION_END,
            notice_published_at=T_COMMISSION_NOTICE_SHORT,
        ),
        CLERK,
    )

    validate_error(response, ERR_NOTICE_PERIOD_TOO_SHORT, 422)
    _, meta = validate_paginated(api.list_plan_hearings(ctx["plan_id"], CLERK))
    assert meta["total_count"] == 0


def test_the_same_sitting_noticed_exactly_ten_days_ahead_is_calendared(api):
    """Ten days of notice is enough, so the identical sitting is accepted and starts
    its life awaiting the gavel.

    "A scheduled hearing enters `SCHEDULED` with `amendment_count` and
    `adopted_amendment_count` at zero and `outcome`, `opened_at` and `closed_at` all
    null."

    Design: Corner/errors/certified_plan_hearing_lifecycle_error_sweep
    """
    ctx = _certified_plan_with_circulated_eir(api)
    validate_error(
        api.create_hearing(
            f.hearing_payload(
                ctx["plan_id"],
                body_type=C.BODY_COMMISSION,
                scheduled_start=T_COMMISSION_START,
                scheduled_end=T_COMMISSION_END,
                notice_published_at=T_COMMISSION_NOTICE_SHORT,
            ),
            CLERK,
        ),
        ERR_NOTICE_PERIOD_TOO_SHORT,
    )

    hearing = validate_success(
        api.create_hearing(
            f.hearing_payload(
                ctx["plan_id"],
                body_type=C.BODY_COMMISSION,
                scheduled_start=T_COMMISSION_START,
                scheduled_end=T_COMMISSION_END,
                notice_published_at=T_COMMISSION_NOTICE_OK,
            ),
            CLERK,
        ),
        201,
    )

    assert hearing["status"] == C.HEARING_STATUS_SCHEDULED
    assert hearing["opened_at"] is None
    assert hearing["outcome"] is None


def test_a_sitting_cannot_be_gavelled_in_before_its_scheduled_start(api):
    """The clock, not the clerk, decides when a sitting may begin.

    "the logical clock must have reached `scheduled_start`, otherwise
    `ERR_HEARING_NOT_YET_STARTED`"

    Design: Corner/errors/certified_plan_hearing_lifecycle_error_sweep
    """
    ctx = _certified_plan_with_circulated_eir(api)
    hearing = _commission_hearing(api, ctx["plan_id"])

    response = api.open_hearing(hearing["id"], {}, CLERK)

    validate_error(response, ERR_HEARING_NOT_YET_STARTED)
    still_waiting = validate_success(api.get_hearing(hearing["id"], CLERK))
    assert still_waiting["status"] == C.HEARING_STATUS_SCHEDULED
    assert still_waiting["opened_at"] is None


def test_gavelling_in_at_the_scheduled_instant_stamps_the_opening_time(api):
    """Once the clock reaches the scheduled start the sitting opens and records the
    clock instant as its opening time.

    "Gavelling a hearing in moves it `SCHEDULED → OPEN` and stamps `opened_at`
    with the logical clock instant, incrementing the hearing's `version`."

    Design: Corner/errors/certified_plan_hearing_lifecycle_error_sweep
    """
    ctx = _certified_plan_with_circulated_eir(api)
    hearing = _commission_hearing(api, ctx["plan_id"])
    validate_error(
        api.open_hearing(hearing["id"], {}, CLERK), ERR_HEARING_NOT_YET_STARTED
    )
    fx.set_clock(api, T_COMMISSION_START)

    opened = validate_success(api.open_hearing(hearing["id"], {}, CLERK))

    assert opened["status"] == C.HEARING_STATUS_OPEN
    assert opened["opened_at"] == "2026-10-05T18:00:00.000Z"


def test_a_sitting_already_in_session_cannot_be_gavelled_in_again(api):
    """The gavel comes down once: a second attempt on an open sitting is refused on
    the status guard rather than being treated as a no-op.

    "the hearing must be `SCHEDULED`, so a hearing that has been blocked by the
    plan's posture — or already opened, continued or concluded — is refused with
    `ERR_HEARING_NOT_SCHEDULED`"

    Design: Corner/errors/certified_plan_hearing_lifecycle_error_sweep
    """
    ctx = _open_commission_sitting(api)
    first_opened_at = ctx["hearing"]["opened_at"]

    response = api.open_hearing(ctx["hearing_id"], {}, CLERK)

    validate_error(response, ERR_HEARING_NOT_SCHEDULED)
    hearing = validate_success(api.get_hearing(ctx["hearing_id"], CLERK))
    assert hearing["status"] == C.HEARING_STATUS_OPEN
    assert hearing["opened_at"] == first_opened_at


def test_a_recommendation_needs_a_certified_environmental_document(api):
    """A document merely out for public comment is enough to file with the state but
    not enough for the commission to recommend the plan.

    "the plan must hold a `CERTIFIED` environmental review, otherwise
    `ERR_ENVIRONMENTAL_REVIEW_NOT_CERTIFIED`"

    Design: Corner/errors/certified_plan_hearing_lifecycle_error_sweep
    """
    ctx = _open_commission_sitting(api)

    response = api.record_hearing_outcome(
        ctx["hearing_id"], f.outcome_payload(C.OUTCOME_RECOMMEND), CLERK
    )

    validate_error(response, ERR_ENVIRONMENTAL_REVIEW_NOT_CERTIFIED)
    hearing = validate_success(api.get_hearing(ctx["hearing_id"], CLERK))
    assert hearing["status"] == C.HEARING_STATUS_OPEN
    assert hearing["outcome"] is None
    assert fx.read_plan(api, ctx["plan_id"])["status"] == (
        C.PLAN_STATUS_STATE_CERTIFIED
    )


def test_certifying_the_document_lets_the_same_recommendation_through(api):
    """Selecting the preferred alternative and certifying the document removes the
    only obstacle, and the identical motion carries the plan one step forward.

    "On success the plan moves `STATE_CERTIFIED → COMMISSION_RECOMMENDED` and
    the plan's `version` is incremented by one."

    Design: Corner/errors/certified_plan_hearing_lifecycle_error_sweep
    """
    ctx = _open_commission_sitting(api)
    validate_error(
        api.record_hearing_outcome(
            ctx["hearing_id"], f.outcome_payload(C.OUTCOME_RECOMMEND), CLERK
        ),
        ERR_ENVIRONMENTAL_REVIEW_NOT_CERTIFIED,
    )
    fx.select_preferred(api, ctx["review_id"])
    certified = fx.certify_review(api, ctx["review_id"])
    assert certified["status"] == C.REVIEW_STATUS_CERTIFIED

    hearing = validate_success(
        api.record_hearing_outcome(
            ctx["hearing_id"], f.outcome_payload(C.OUTCOME_RECOMMEND), CLERK
        )
    )

    assert hearing["status"] == C.HEARING_STATUS_RECOMMENDED
    assert hearing["outcome"] == C.OUTCOME_RECOMMEND
    assert (
        fx.read_plan(api, ctx["plan_id"])["status"]
        == C.PLAN_STATUS_COMMISSION_RECOMMENDED
    )


def test_a_concluded_sitting_takes_no_further_outcome(api):
    """All four outcome branches share one status guard, so a sitting that has already
    concluded cannot be continued afterwards.

    "In all four branches the hearing must be `OPEN`, otherwise
    `ERR_HEARING_NOT_OPEN`"

    Design: Corner/errors/certified_plan_hearing_lifecycle_error_sweep
    """
    ctx = _recommended_plan(api)

    response = api.record_hearing_outcome(
        ctx["hearing_id"], f.outcome_payload(C.OUTCOME_CONTINUE), CLERK
    )

    validate_error(response, ERR_HEARING_NOT_OPEN)
    hearing = validate_success(api.get_hearing(ctx["hearing_id"], CLERK))
    assert hearing["status"] == C.HEARING_STATUS_RECOMMENDED
    assert hearing["outcome"] == C.OUTCOME_RECOMMEND


def test_a_council_denial_demotes_the_plan_all_the_way_back(api):
    """The council's refusal sends the recommended plan back to drafting, reopens the
    chapters it had approved and reopens the dependency between them.

    "On a `COUNCIL` hearing against a plan in `COMMISSION_RECOMMENDED` the plan
    is demoted all the way back: it moves `COMMISSION_RECOMMENDED → DRAFTING`, its
    `state_review_status` is reset to `NOT_SUBMITTED`, every element standing in
    `APPROVED` moves `APPROVED → REVISION_REQUESTED` with `revision_round`
    incremented by one"

    Design: Corner/errors/certified_plan_hearing_lifecycle_error_sweep
    """
    ctx = _two_council_sittings_in_session(api)

    denied = validate_success(
        api.record_hearing_outcome(
            ctx["first_council_id"],
            f.outcome_payload(C.OUTCOME_DENY, "The council declines to adopt."),
            CLERK,
        )
    )

    assert denied["status"] == C.HEARING_STATUS_DENIED
    plan = fx.read_plan(api, ctx["plan_id"])
    assert plan["status"] == C.PLAN_STATUS_DRAFTING
    assert plan["state_review_status"] == C.STATE_REVIEW_NOT_SUBMITTED
    for element_type in C.STATUTORY_ELEMENT_TYPES:
        element = fx.read_element(api, ctx["elements"][element_type]["id"])
        assert element["status"] == C.ELEMENT_STATUS_REVISION_REQUESTED
        assert element["revision_round"] == 1
    link = validate_success(api.get_consistency_link(ctx["link_id"], STAFF))
    assert link["status"] == C.LINK_STATUS_OPEN
    assert plan["compliance_posture"] == C.POSTURE_CONSISTENCY_HOLD


def test_the_sitting_already_in_session_is_not_blocked_by_the_denial(api):
    """The posture cascade that follows the denial reaches only sittings still
    awaiting their gavel, so the second council sitting stays in session.

    "A hearing that has already been gavelled in is never blocked
    retroactively; only `SCHEDULED` hearings are affected."

    Design: Corner/errors/certified_plan_hearing_lifecycle_error_sweep
    """
    ctx = _two_council_sittings_in_session(api)

    validate_success(
        api.record_hearing_outcome(
            ctx["first_council_id"], f.outcome_payload(C.OUTCOME_DENY), CLERK
        )
    )

    survivor = validate_success(api.get_hearing(ctx["second_council_id"], CLERK))
    assert survivor["status"] == C.HEARING_STATUS_OPEN
    assert survivor["outcome"] is None


def test_adoption_is_refused_once_the_plan_has_been_denied(api):
    """The demoted plan is no longer the recommended plan the adoption motion needs,
    and the state guard is reported rather than the posture that also fails.

    "The plan must be in `COMMISSION_RECOMMENDED`, otherwise
    `ERR_PLAN_NOT_RECOMMENDED`"

    Design: Corner/errors/certified_plan_hearing_lifecycle_error_sweep
    """
    ctx = _two_council_sittings_in_session(api)
    validate_success(
        api.record_hearing_outcome(
            ctx["first_council_id"], f.outcome_payload(C.OUTCOME_DENY), CLERK
        )
    )

    response = api.record_hearing_outcome(
        ctx["second_council_id"], f.outcome_payload(C.OUTCOME_ADOPT), CLERK
    )

    validate_error(response, ERR_PLAN_NOT_RECOMMENDED)
    hearing = validate_success(api.get_hearing(ctx["second_council_id"], CLERK))
    assert hearing["status"] == C.HEARING_STATUS_OPEN
    assert hearing["outcome"] is None
    plan = fx.read_plan(api, ctx["plan_id"])
    assert plan["status"] == C.PLAN_STATUS_DRAFTING
    assert plan["adopted_at"] is None


def test_the_council_calendar_still_shows_both_sittings(api):
    """Filtering the plan's calendar on the council reports exactly the two council
    sittings, the concluded one and the one still in session.

    "Where a list endpoint also accepts filters, the filters narrow the result
    set before pagination is applied, so `total_count` reports the number of rows
    matching the filters, not the number of rows in the collection."

    Design: Corner/errors/certified_plan_hearing_lifecycle_error_sweep
    """
    ctx = _two_council_sittings_in_session(api)
    validate_success(
        api.record_hearing_outcome(
            ctx["first_council_id"], f.outcome_payload(C.OUTCOME_DENY), CLERK
        )
    )

    rows, meta = validate_paginated(
        api.list_plan_hearings(
            ctx["plan_id"], CLERK, params={"body_type": C.BODY_COUNCIL}
        )
    )

    assert meta["total_count"] == 2
    assert [row["status"] for row in rows] == [
        C.HEARING_STATUS_DENIED,
        C.HEARING_STATUS_OPEN,
    ]
