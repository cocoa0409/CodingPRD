"""Dual-failure requests: which tier of the validation ladder answers first."""
from test_helpers import (
    ApiErrorId,
    build_user_headers,
    create_placement_payload,
    err,
    validate_error,
    validate_success,
)

from test_helpers.fixtures import (
    DECIDER,
    PLACEMENT_COORDINATOR,
    REVIEWER,
    get_district,
    get_member,
    setup_exited_member,
    setup_member_scenario,
    setup_selection_pipeline,
)


class TestStateBeatsFiscal:
    """A placement request that breaks both the service gate and the fee ceiling."""

    def test_exited_member_reports_the_state_error_not_the_fiscal_one(self, api):
        """PRD §2.10: "Requests are screened in a fixed order, and the first failing tier decides the response. Later tiers are never reached once an earlier tier has rejected the request"
        PRD §2.10: "A member whose service is not `ACTIVE` where active service is required is `ERR_MEMBER_NOT_ACTIVE` (HTTP 409), reported on placement creation, confirmation and reinstatement."

        The district's 100000-cent ceiling is also breached by the 710000-cent
        invoice this placement would create, so both gates are violated.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_placement_create
        """
        scenario = setup_exited_member(district_overrides={"fee_budget_cents": 100000})
        member = get_member(scenario["member_id"])
        assert member["service_status"] == "EXITED"

        payload = create_placement_payload(
            scenario["member_id"], scenario["school"]["id"], member["version"]
        )
        response = api.create_placement(payload, PLACEMENT_COORDINATOR)
        validate_error(response, err(ApiErrorId.ERR_MEMBER_NOT_ACTIVE), 409)

        district = get_district(scenario["district"]["id"])
        assert district["committed_placement_count"] == 0, "no Placement row was created"

    def test_member_on_leave_also_reports_the_state_error(self, api):
        """PRD §2.10: "A member whose service is not `ACTIVE` where active service is required is `ERR_MEMBER_NOT_ACTIVE` (HTTP 409), reported on placement creation, confirmation and reinstatement."
        PRD §2.10: "Where two business rules could apply to the same request, the ordering above is the order in which they are evaluated."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_placement_create
        """
        scenario = setup_member_scenario(district_overrides={"fee_budget_cents": 100000})
        member_id = scenario["member_id"]
        validate_success(api.place_member_on_leave(member_id, PLACEMENT_COORDINATOR))

        member = get_member(member_id)
        assert member["service_status"] == "ON_LEAVE"
        payload = create_placement_payload(member_id, scenario["school"]["id"], member["version"])

        response = api.create_placement(payload, PLACEMENT_COORDINATOR)
        validate_error(response, err(ApiErrorId.ERR_MEMBER_NOT_ACTIVE), 409)


class TestSafetyBeatsConstraint:
    """A decision that breaks both segregation of duties and the score band."""

    def test_same_operator_decision_reports_the_sod_error(self, api):
        """PRD §2.9: "The operator who records a selection decision must not be the operator who ran the review: on a decision, `X-User-ID` must differ from the application's `reviewed_by_user_id`."
        PRD §2.9: "Either violation is rejected with `ERR_SOD_VIOLATION` (HTTP 403), regardless of whether the transition is otherwise legal."

        The final score is 84.96, so the score band is also violated; the
        safety gate answers first.

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_decision
        """
        same_operator = build_user_headers("sm_same", "SelectionManager")
        scenario = setup_selection_pipeline(
            applicant_overrides={"gpa": 4.00},
            application_overrides={"subject_area": "ENGLISH", "grade_preference": "HIGH"},
            verified_gpa=3.99,
            review_operator=same_operator,
            decision=None,
        )
        app_id = scenario["application"]["id"]

        response = api.decide_application(app_id, "SELECT", same_operator)
        validate_error(response, err(ApiErrorId.ERR_SOD_VIOLATION), 403)

        after = validate_success(api.get_application(app_id, REVIEWER))
        assert after["status"] == "UNDER_REVIEW"
        assert after.get("decided_by_user_id") is None

    def test_different_operator_reaches_the_score_gate(self, api):
        """PRD §3.3: "The first is the segregation-of-duties rule of §2.9: the deciding operator's `X-User-ID` must differ from the application's `reviewed_by_user_id`, and a decision recorded by the same operator who ran the review is refused with `ERR_SOD_VIOLATION` (HTTP 403)."
        PRD §3.3: "The second guard is the selection band, and it applies only to a positive decision: a `SELECT` requires the final selection score to be at or above 85.00, and a selection requested below that band is refused with `ERR_SCORE_BELOW_THRESHOLD` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_decision
        """
        scenario = setup_selection_pipeline(
            applicant_overrides={"gpa": 4.00},
            application_overrides={"subject_area": "ENGLISH", "grade_preference": "HIGH"},
            verified_gpa=3.99,
            review_operator=REVIEWER,
            decision=None,
        )
        app_id = scenario["application"]["id"]

        response = api.decide_application(app_id, "SELECT", DECIDER)
        validate_error(response, err(ApiErrorId.ERR_SCORE_BELOW_THRESHOLD), 422)
