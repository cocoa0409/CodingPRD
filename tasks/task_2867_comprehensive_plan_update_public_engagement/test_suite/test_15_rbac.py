"""Role and identity compliance for the Comprehensive Plan Update API.

Three concerns are separated here: the positive direction of the authorization
table (each of the five roles performing the write only it owns), the negative
direction (a ring of cross-role refusals plus the authentication rung that sits
above them), and the identity comparison that guards the three approvals.
"""

import pytest

from prd_bench_local_runner.testing import (
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
    ERR_PLAN_NOT_CERTIFIED,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
)
from test_helpers.test_users import (
    ALL_ROLE_HEADERS,
    CLERK,
    CONSULTANT,
    DIRECTOR,
    DIRECTOR_ID,
    DIRECTOR_SHARED,
    MISSING_ROLE_HEADERS,
    MISSING_USER_HEADERS,
    NO_HEADERS,
    STAFF,
    STAFF_SHARED,
    STATE,
    UNKNOWN_ROLE_HEADERS,
)

# A commission slot ten clear days after its notice, so the calendar rules are
# satisfied and only the plan's status can stand in the way.
HEARING_START = "2026-10-05T18:00:00.000Z"
HEARING_END = "2026-10-05T21:00:00.000Z"
HEARING_NOTICE = "2026-09-25T18:00:00.000Z"


def _hearing_body(plan_id):
    return f.hearing_payload(
        plan_id,
        body_type=C.BODY_COMMISSION,
        scheduled_start=HEARING_START,
        scheduled_end=HEARING_END,
        notice_published_at=HEARING_NOTICE,
    )


# ================================================== the positive direction
def test_each_role_performs_the_create_that_belongs_to_it_alone(api):
    """Four disjoint exclusive lists, four accepted creates on the same plan.

    "Only a `PlanningDirector` may open a plan update cycle."

    Design: Corner/rbac/every_role_can_perform_its_own_signature_operation
    """
    plan = validate_success(api.create_plan_update(f.plan_update_payload(), DIRECTOR), 201)
    assert plan["status"] == C.PLAN_STATUS_DRAFTING

    inventory = validate_success(
        api.create_inventory_dataset(
            f.tabular_inventory_payload(plan["id"], C.INVENTORY_DEMOGRAPHIC), STAFF
        ),
        201,
    )
    assert inventory["inventory_type"] == C.INVENTORY_DEMOGRAPHIC

    review = validate_success(
        api.create_environmental_review(
            f.environmental_review_payload(
                plan["id"],
                C.DOC_NEGATIVE_DECLARATION,
                title="Horizon 2045 Negative Declaration",
            ),
            CONSULTANT,
        ),
        201,
    )
    assert review["document_type"] == C.DOC_NEGATIVE_DECLARATION

    allocation = validate_success(
        api.create_housing_allocation(
            f.housing_allocation_payload(
                plan["id"],
                C.TIER_VERY_LOW,
                900,
                cycle_deadline="2031-06-30T00:00:00.000Z",
            ),
            STATE,
        ),
        201,
    )
    assert allocation["income_tier"] == C.TIER_VERY_LOW


def test_the_clerk_clears_the_role_gate_where_staff_is_stopped_by_it(api):
    """The same hearing body yields a business refusal for the clerk and a role
    refusal for staff.

    "A hearing can only be put on the calendar once the state has certified the plan:
    the plan's status must be `STATE_CERTIFIED` or `COMMISSION_RECOMMENDED`, and
    anything earlier is refused with `ERR_PLAN_NOT_CERTIFIED`."

    Design: Corner/rbac/every_role_can_perform_its_own_signature_operation
    """
    plan = fx.create_plan(api)

    validate_error(
        api.create_hearing(_hearing_body(plan["id"]), CLERK), ERR_PLAN_NOT_CERTIFIED, 409
    )
    validate_error(
        api.create_hearing(_hearing_body(plan["id"]), STAFF), ERR_ROLE_NOT_PERMITTED, 403
    )

    # Neither refusal put a hearing on the calendar or moved the plan.
    _, meta = validate_paginated(api.list_plan_hearings(plan["id"], CLERK))
    assert meta["total_count"] == 0
    assert fx.read_plan(api, plan["id"])["version"] == plan["version"]


def test_the_logical_clock_is_the_one_write_every_role_holds(api):
    """Five successive clock moves, one per role, all accepted.

    "All five roles may read every single-resource read, list and computed-read
    endpoint under `/planning`, and all five may drive the logical clock."

    Design: Corner/rbac/every_role_can_perform_its_own_signature_operation
    """
    instants = {
        C.ROLE_PLANNING_STAFF: "2026-08-02T00:00:00.000Z",
        C.ROLE_PLANNING_DIRECTOR: "2026-08-03T00:00:00.000Z",
        C.ROLE_ENVIRONMENTAL_CONSULTANT: "2026-08-04T00:00:00.000Z",
        C.ROLE_COMMISSION_CLERK: "2026-08-05T00:00:00.000Z",
        C.ROLE_STATE_REVIEWER: "2026-08-06T00:00:00.000Z",
    }

    for role in C.ALL_ROLES:
        data = validate_success(api.set_clock(instants[role], ALL_ROLE_HEADERS[role]))
        a.assert_instant_equals(data["current_utc"], instants[role], "current_utc")


def test_all_five_roles_read_the_same_plan(api):
    """A single-resource read is identical whoever asks for it, and changes nothing.

    "All five roles may read every single-resource read, list and computed-read
    endpoint under `/planning`, and all five may drive the logical clock."

    Design: Corner/rbac/every_role_can_perform_its_own_signature_operation
    """
    plan = fx.create_plan(api)

    bodies = [
        validate_success(api.get_plan_update(plan["id"], ALL_ROLE_HEADERS[role]))
        for role in C.ALL_ROLES
    ]

    for body in bodies:
        assert body == bodies[0]
        assert body["version"] == plan["version"]


# ================================================== the negative direction
def _plan_inventory_and_element(api):
    plan = fx.create_plan(api)
    inventory = fx.create_tabular_inventory(
        api, plan["id"], C.INVENTORY_DEMOGRAPHIC, STAFF, record_count=1200
    )
    element = fx.create_element(api, plan["id"], C.ELEMENT_PARKS, STAFF, policy_count=3)
    return {"plan": plan, "inventory": inventory, "element": element}


FORBIDDEN_WRITES = [
    pytest.param(
        lambda api, ctx: api.create_plan_update(
            f.plan_update_payload(
                title="A plan staff may not open", jurisdiction_code="CA0453"
            ),
            STAFF,
        ),
        id="staff_opens_a_cycle",
    ),
    pytest.param(
        lambda api, ctx: api.create_inventory_dataset(
            f.tabular_inventory_payload(
                ctx["plan"]["id"], C.INVENTORY_HOUSING, record_count=900
            ),
            DIRECTOR,
        ),
        id="director_assembles_an_inventory",
    ),
    pytest.param(
        lambda api, ctx: api.create_plan_element(
            f.plan_element_payload(
                ctx["plan"]["id"],
                C.ELEMENT_TRANSPORTATION,
                title="Mobility Element",
                draft_body="Not the consultant's work.",
                policy_count=3,
            ),
            CONSULTANT,
        ),
        id="consultant_drafts_an_element",
    ),
    pytest.param(
        lambda api, ctx: api.create_housing_allocation(
            f.housing_allocation_payload(
                ctx["plan"]["id"],
                C.TIER_LOW,
                700,
                cycle_deadline="2031-06-30T00:00:00.000Z",
            ),
            CLERK,
        ),
        id="clerk_assigns_an_allocation",
    ),
    pytest.param(
        lambda api, ctx: api.create_environmental_review(
            f.environmental_review_payload(
                ctx["plan"]["id"],
                C.DOC_NEGATIVE_DECLARATION,
                title="Not the state's document",
            ),
            STATE,
        ),
        id="state_reviewer_opens_an_environmental_document",
    ),
    pytest.param(
        lambda api, ctx: api.patch_plan_element(
            ctx["element"]["id"], {"policy_count": 9}, CLERK
        ),
        id="clerk_revises_an_element",
    ),
]


@pytest.mark.parametrize("forbidden", FORBIDDEN_WRITES)
def test_a_write_reserved_to_another_role_is_refused(api, forbidden):
    """The five exclusive lists are disjoint peers, so seniority buys nothing.

    "When both headers are well formed but the named role is not authorized for the
    requested operation, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/cross_role_and_unauthenticated_refusals
    """
    ctx = _plan_inventory_and_element(api)

    validate_error(forbidden(api, ctx), ERR_ROLE_NOT_PERMITTED, 403)


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param(NO_HEADERS, id="no_headers"),
        pytest.param(MISSING_ROLE_HEADERS, id="no_role_header"),
        pytest.param(MISSING_USER_HEADERS, id="no_user_header"),
        pytest.param(UNKNOWN_ROLE_HEADERS, id="undeclared_role"),
    ],
)
def test_the_authentication_rung_answers_before_the_role_rung(api, headers):
    """A caller with no usable identity is unauthenticated, never merely forbidden.

    "If either header is absent, or if `X-User-Role` is not one of the five roles
    declared below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/cross_role_and_unauthenticated_refusals
    """
    ctx = _plan_inventory_and_element(api)

    # A write the caller would have been forbidden even with a declared role.
    validate_error(
        api.create_plan_update(
            f.plan_update_payload(
                title="An anonymous plan", jurisdiction_code="CA0454"
            ),
            headers,
        ),
        ERR_UNAUTHENTICATED,
        401,
    )
    # And a read that every declared role may perform.
    validate_error(
        api.get_plan_update(ctx["plan"]["id"], headers), ERR_UNAUTHENTICATED, 401
    )


def test_the_role_rung_answers_before_the_duties_comparison(api):
    """Staff certifying their own dataset are refused on the role, not on the identity.

    "Validation is therefore a strictly ordered ladder, evaluated from the top, and the
    first rule that fails determines the response."

    Design: Corner/rbac/cross_role_and_unauthenticated_refusals
    """
    ctx = _plan_inventory_and_element(api)

    error = validate_error(
        api.certify_inventory_dataset(ctx["inventory"]["id"], {}, STAFF),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )

    assert error["error_id"] != ERR_SEGREGATION_OF_DUTIES


def test_the_refused_calls_leave_no_trace(api):
    """Eight refusals in a row and not one stored field moves.

    "When both headers are well formed but the named role is not authorized for the
    requested operation, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/cross_role_and_unauthenticated_refusals
    """
    ctx = _plan_inventory_and_element(api)

    for forbidden in FORBIDDEN_WRITES:
        validate_error(forbidden.values[0](api, ctx), ERR_ROLE_NOT_PERMITTED, 403)
    validate_error(
        api.certify_inventory_dataset(ctx["inventory"]["id"], {}, STAFF),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.create_plan_update(f.plan_update_payload(), NO_HEADERS),
        ERR_UNAUTHENTICATED,
        401,
    )

    _, meta = validate_paginated(api.list_plan_updates(DIRECTOR))
    assert meta["total_count"] == 1

    inventory = validate_success(
        api.get_inventory_dataset(ctx["inventory"]["id"], STAFF)
    )
    assert inventory["status"] == C.INVENTORY_STATUS_DRAFT
    assert inventory["certified_by_user_id"] is None
    assert inventory["version"] == ctx["inventory"]["version"]

    element = validate_success(api.get_plan_element(ctx["element"]["id"], STAFF))
    assert element["policy_count"] == 3
    assert element["version"] == ctx["element"]["version"]


# ============================================== the second pair of eyes
def _work_authored_by_one_operator(api):
    """A dataset and a submitted element both authored by the same user id."""
    plan = fx.create_plan(api)
    inventory = fx.create_tabular_inventory(
        api, plan["id"], C.INVENTORY_DEMOGRAPHIC, STAFF_SHARED, record_count=1200
    )
    element = fx.create_element(
        api, plan["id"], C.ELEMENT_PARKS, STAFF_SHARED, policy_count=3
    )
    submitted = get_success_data(
        api.submit_element_review(element["id"], {}, STAFF_SHARED)
    )
    assert submitted["status"] == C.ELEMENT_STATUS_IN_REVIEW
    return {
        "plan_id": plan["id"],
        "inventory": inventory,
        "element": submitted,
    }


def test_a_director_may_not_approve_the_element_they_drafted(api):
    """The refused approval consumes nothing, and a second operator can still approve.

    "Recording a review decision on a plan element requires that `X-User-ID` differ from
    the element's `authored_by_user_id`."

    Design: Corner/rbac/approvals_require_a_second_pair_of_eyes
    """
    ctx = _work_authored_by_one_operator(api)
    decision = f.review_decision_payload(C.DECISION_APPROVE, "Approving my own draft.")

    validate_error(
        api.record_review_decision(ctx["element"]["id"], decision, DIRECTOR_SHARED),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    still_open = validate_success(api.get_plan_element(ctx["element"]["id"], STAFF))
    assert still_open["status"] == C.ELEMENT_STATUS_IN_REVIEW
    assert still_open["reviewed_by_user_id"] is None
    assert still_open["version"] == ctx["element"]["version"]
    assert fx.read_summary(api, ctx["plan_id"])["required_elements_complete_count"] == 0

    approved = validate_success(
        api.record_review_decision(
            ctx["element"]["id"],
            f.review_decision_payload(C.DECISION_APPROVE, "Reviewed independently."),
            DIRECTOR,
        )
    )

    assert approved["status"] == C.ELEMENT_STATUS_APPROVED
    assert approved["reviewed_by_user_id"] == DIRECTOR_ID
    assert fx.read_summary(api, ctx["plan_id"])["required_elements_complete_count"] == 1


def test_a_director_may_not_certify_the_dataset_they_assembled(api):
    """The same comparison guards a different entity, with the same shape of outcome.

    "Certifying an inventory dataset requires that `X-User-ID` differ from the dataset's
    `authored_by_user_id`."

    Design: Corner/rbac/approvals_require_a_second_pair_of_eyes
    """
    ctx = _work_authored_by_one_operator(api)

    validate_error(
        api.certify_inventory_dataset(ctx["inventory"]["id"], {}, DIRECTOR_SHARED),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    untouched = validate_success(
        api.get_inventory_dataset(ctx["inventory"]["id"], STAFF)
    )
    assert untouched["status"] == C.INVENTORY_STATUS_DRAFT
    assert untouched["certified_by_user_id"] is None
    assert untouched["version"] == ctx["inventory"]["version"]

    certified = validate_success(
        api.certify_inventory_dataset(ctx["inventory"]["id"], {}, DIRECTOR)
    )

    assert certified["status"] == C.INVENTORY_STATUS_CERTIFIED
    assert certified["certified_by_user_id"] == DIRECTOR_ID


def test_role_and_identity_are_two_independent_gates(api):
    """Both refusals are 403 on the same endpoint, and only the error id separates them.

    "The rule compares identifiers, not roles. Two different `PlanningDirector` operators
    may certify each other's datasets freely; one director cannot certify their own."

    Design: Corner/rbac/approvals_require_a_second_pair_of_eyes
    """
    ctx = _work_authored_by_one_operator(api)

    role_refusal = validate_error(
        api.certify_inventory_dataset(ctx["inventory"]["id"], {}, STATE),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    duties_refusal = validate_error(
        api.certify_inventory_dataset(ctx["inventory"]["id"], {}, DIRECTOR_SHARED),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    assert role_refusal["error_id"] != duties_refusal["error_id"]
    assert (
        validate_success(api.get_inventory_dataset(ctx["inventory"]["id"], STAFF))[
            "status"
        ]
        == C.INVENTORY_STATUS_DRAFT
    )
