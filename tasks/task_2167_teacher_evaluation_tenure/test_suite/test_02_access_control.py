"""Authentication, role authorisation, resource ownership and segregation of duties."""

from test_helpers import (
    ApiErrorId,
    HR_DECIDER_HEADERS,
    HR_DECIDER_ID,
    HR_RECOMMENDER_HEADERS,
    HR_RECOMMENDER_ID,
    TEST_USERS,
    add_observation,
    create_school,
    evaluation_cycle_payload,
    get_educator,
    make_evaluator_headers,
    make_teacher_headers,
    setup_cycle,
    setup_district,
    setup_finalized_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)

HR = TEST_USERS["hr_admin_headers"]


def test_request_without_role_header_is_unauthenticated(api):
    """PRD §2.1: "Every request to the API must carry two headers: `X-User-ID`,
    identifying the acting principal, and `X-User-Role`, naming the capacity in
    which they act. If either header is absent, or if `X-User-Role` does not name
    one of the five declared roles, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_x_user_role_header_returns_unauthenticated
    """
    school = create_school()

    response = api.get_school(school["id"], {"Content-Type": "application/json"})
    error_data = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    assert "name" not in error_data and "evaluation_budget_allocated_cents" not in error_data, (
        "an unauthenticated response must carry no School fields"
    )


def test_teacher_may_not_open_an_evaluation_cycle(api):
    """PRD §2.1: "When both headers are well-formed but the named role is not
    among the roles authorised for the endpoint being called, the rejection is
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.1: "An evaluation cycle is opened by an `HrAdmin` for one educator in
    one school year."

    Design: Corner/rbac/teacher_cannot_open_an_evaluation_cycle
    """
    ctx = setup_district(certify=False)
    educator = ctx["educator"]

    response = api.create_evaluation_cycle(
        evaluation_cycle_payload(educator["id"], ctx["policy"]["id"]),
        make_teacher_headers(educator["id"]),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    cycles, _meta = validate_paginated(
        api.list_evaluation_cycles(HR, params={"educator_id": educator["id"]})
    )
    assert cycles == [], "the rejected request must open no cycle"



def test_evaluator_may_not_conduct_another_evaluators_observation(api):
    """PRD §2.1: "An entity-backed role acting on a resource whose owning foreign
    key is not its `X-User-ID` is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP
    403)."
    PRD §3.3: "Marking the visit as having happened advances the observation from
    `SCHEDULED` to `CONDUCTED`, and only the assigned evaluator may do it — the
    acting `X-User-ID` must equal the observation's `evaluator_id`."

    Design: Corner/rbac/evaluator_cannot_conduct_another_evaluators_observation
    """
    ctx = setup_cycle(second_evaluator=True)
    observation = add_observation(ctx, stop_at="SCHEDULED")

    response = api.conduct_observation(
        observation["id"], make_evaluator_headers(ctx["evaluator2"]["id"])
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    reread = validate_success(api.get_observation(observation["id"], HR))
    assert reread["status"] == "SCHEDULED", "the rejected conduct must not move the state"
    cycle = validate_success(api.get_evaluation_cycle(ctx["cycle"]["id"], HR))
    assert cycle["status"] == "SCHEDULING", "no bubble-up may fire from a rejected conduct"


def test_tenure_decision_requires_a_second_administrator(api):
    """PRD §2.8: "The rejection is `ERR_OBSERVATION_STATE_INVALID`,
    `ERR_CYCLE_STATE_INVALID`, `ERR_PLAN_STATE_INVALID`,
    `ERR_APPEAL_STATE_INVALID`, `ERR_GRIEVANCE_STATE_INVALID` or
    `ERR_TENURE_STATE_INVALID` according to the entity whose state was wrong,
    each HTTP 409."
    PRD §3.9: "A `RECOMMEND` moves `tenure_status` from `PROBATIONARY` to
    `RECOMMENDED` and stamps the acting operator's `X-User-ID` onto
    `tenure_recommended_by_user_id`"
    PRD §3.9: "A `decision` of `GRANT` moves a `RECOMMENDED` educator to
    `TENURED`; a `decision` of `DENY` moves them to `DENIED`. Both require the
    deciding operator's `X-User-ID` to differ from the stored
    `tenure_recommended_by_user_id`, and both are available only from
    `RECOMMENDED`."
    PRD §2.11: "A tenure decision may not be taken by the operator who
    recommended it: the deciding `HrAdmin`'s `X-User-ID` must differ from the
    educator's stored `tenure_recommended_by_user_id`. Either breach yields
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/tenure_decision_by_the_recommender_is_rejected_then_a_second_admin_grants
    """
    ctx = setup_finalized_cycle(
        clock="2026-08-01T00:00:00Z",
        policy_overrides={"required_formal_count": 1, "required_informal_count": 0,
                          "tenure_required_years": 3,
                          "tenure_min_consecutive_effective": 1,
                          "evidence_min_artifacts": 2},
        educator_overrides={"employee_number": "E-K301",
                            "service_start_date": "2023-08-02"},
        formal_scores=(3, 3, 4, 3), artifacts=2,
        growth_index=3.00, growth_coverage=100,
    )
    educator_id = ctx["educator"]["id"]

    # Deciding before any recommendation exists is a state violation.
    early = api.tenure_decision(educator_id, {"decision": "GRANT"}, HR_DECIDER_HEADERS)
    validate_error(early, ApiErrorId.ERR_TENURE_STATE_INVALID.value, 409)

    recommended = validate_success(
        api.tenure_recommendation(educator_id, {"recommendation": "RECOMMEND"},
                                  HR_RECOMMENDER_HEADERS)
    )
    assert recommended["tenure_status"] == "RECOMMENDED"
    assert recommended["tenure_recommended_by_user_id"] == HR_RECOMMENDER_ID

    # The recommending operator may not also decide.
    self_decision = api.tenure_decision(educator_id, {"decision": "GRANT"},
                                        HR_RECOMMENDER_HEADERS)
    validate_error(self_decision, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    assert get_educator(educator_id)["tenure_status"] == "RECOMMENDED", (
        "the rejected self-decision must leave the educator RECOMMENDED"
    )

    granted = validate_success(
        api.tenure_decision(educator_id, {"decision": "GRANT"}, HR_DECIDER_HEADERS)
    )
    assert granted["tenure_status"] == "TENURED", (
        f"a second operator ({HR_DECIDER_ID}) must be able to grant tenure"
    )
