"""Cross-entity state gates: the referenced entity's state blocks an admissible target."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_paginated

from test_helpers import api_errors as E
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers import test_users as U
from test_helpers import types as T
from test_helpers.assertions import assert_fields, assert_null


def _suspended_policy_with_reported_claim(api):
    world = S.underwritten_policy(api)
    claim = S.report_claim(
        api,
        world["policy_id"],
        claim_type=T.CLAIM_TYPE_WRONGFUL_TERMINATION,
        claimant_class=T.CLAIMANT_EMPLOYEE,
        notice_type=T.NOTICE_DEMAND_LETTER,
        alleged_damages_cents=6000000,
    )
    get_success_data(
        api.suspend_policy(
            world["policy_id"], "Premium instalment 2 unpaid past the grace period", U.UW_MANAGER
        )
    )
    world["claim_id"] = claim["id"]
    return world


def test_start_review_is_refused_while_the_owning_policy_is_suspended(api):
    """The claim's own status permits the move; the parent policy does not.

    PRD: "Starting a review moves the claim `REPORTED → UNDER_REVIEW`. On any
    other status the answer is `ERR_CLAIM_NOT_REVIEWABLE`; and even from
    `REPORTED` the transition is refused when the owning policy is not `BOUND`
    or `ACTIVE`, or when the claim is coverage-gated, which is the cross-entity
    guard that yields `ERR_POLICY_NOT_IN_FORCE`."

    Design: Difficulty/cross_entity_state_dependency/claim_review_gated_by_policy_suspension_state
    """
    world = _suspended_policy_with_reported_claim(api)
    validate_error(
        api.start_claim_review(world["claim_id"], U.ADJUSTER), E.ERR_POLICY_NOT_IN_FORCE, 409
    )

    policy = get_success_data(api.get_policy(world["policy_id"], U.ADJUSTER))
    assert_fields(
        policy,
        {
            "status": T.POLICY_SUSPENDED,
            "suspension_reason": "Premium instalment 2 unpaid past the grace period",
        },
    )
    claim = get_success_data(api.get_claim(world["claim_id"], U.ADJUSTER))
    assert_fields(claim, {"status": T.CLAIM_REPORTED, "coverage_gated": False})


def test_the_identical_review_request_succeeds_once_the_policy_is_reinstated(api):
    """Reinstatement restores the cross-entity precondition and nothing else changes.

    PRD: "On success `suspension_reason` and `suspended_at` are both cleared to
    null, and each of the three hops is reversed in turn: every claim of this
    policy carrying `coverage_gated` true has it cleared to false; every defense
    assignment on those claims that is in `SUSPENDED_FUNDING` with `hold_reason`
    equal to `POLICY_SUSPENDED` transitions `SUSPENDED_FUNDING → ACTIVE` with
    `hold_reason` cleared to null; and every defense invoice on those
    assignments whose `hold_reason` is `POLICY_SUSPENDED` has it cleared to
    null."

    Design: Difficulty/cross_entity_state_dependency/claim_review_gated_by_policy_suspension_state
    """
    world = _suspended_policy_with_reported_claim(api)
    validate_error(
        api.start_claim_review(world["claim_id"], U.ADJUSTER), E.ERR_POLICY_NOT_IN_FORCE, 409
    )

    policy = get_success_data(api.reinstate_policy(world["policy_id"], U.UW_MANAGER))
    assert policy["status"] == T.POLICY_ACTIVE
    assert_null(policy, ["suspension_reason", "suspended_at"])

    claim = get_success_data(api.start_claim_review(world["claim_id"], U.ADJUSTER))
    assert claim["status"] == T.CLAIM_UNDER_REVIEW


def _two_firm_world(api):
    """A suspended NATIONAL firm and an active REGIONAL firm, plus one accepted claim."""
    S.create_jurisdictions(api, ["CA", "TX"])
    plan_id = S.create_active_rate_plan(api)["id"]
    firm_a = S.create_panel_firm(
        api,
        name="Ashford & Vance LLP",
        tier=T.TIER_NATIONAL,
        jurisdiction_codes=["CA", "TX"],
        partner_rate_cents_per_hour=92000,
        associate_rate_cents_per_hour=51000,
        paralegal_rate_cents_per_hour=18000,
        capacity_open_matters=3,
    )
    firm_b = S.create_panel_firm(
        api,
        name="Bellweather Rowe LLP",
        tier=T.TIER_REGIONAL,
        jurisdiction_codes=["CA"],
        partner_rate_cents_per_hour=70000,
        associate_rate_cents_per_hour=43000,
        paralegal_rate_cents_per_hour=16000,
        capacity_open_matters=2,
    )
    applicant = S.create_applicant(api)
    assessment = S.create_approved_assessment(api, applicant["id"], plan_id)
    policy = S.bind_policy(api, assessment["id"])
    claim = S.accepted_claim(
        api,
        policy["id"],
        claim_type=T.CLAIM_TYPE_DISCRIMINATION,
        claimant_class=T.CLAIMANT_EMPLOYEE,
        notice_type=T.NOTICE_LAWSUIT,
        alleged_damages_cents=11000000,
    )
    get_success_data(api.suspend_panel_firm(firm_a["id"], U.ADMIN))
    return {"firm_a_id": firm_a["id"], "firm_b_id": firm_b["id"], "claim_id": claim["id"]}


def _engagement(firm_id):
    return F.assignment(
        engagement_from="2026-08-01T00:00:00.000Z",
        engagement_to="2026-11-01T00:00:00.000Z",
        budget_cap_cents=3000000,
        panel_firm_id=firm_id,
    )


def test_a_client_directed_firm_in_panel_suspended_cannot_be_engaged(api):
    """Coverage and capacity are both fine; only the firm's panel state refuses.

    PRD: "a named firm in `PANEL_SUSPENDED` is `ERR_PANEL_FIRM_NOT_ACTIVE`"

    Design: Difficulty/cross_entity_state_dependency/assignment_creation_gated_by_panel_firm_suspension_state
    """
    world = _two_firm_world(api)
    validate_error(
        api.create_assignment(world["claim_id"], _engagement(world["firm_a_id"]), U.ADJUSTER),
        E.ERR_PANEL_FIRM_NOT_ACTIVE,
        409,
    )

    firm = get_success_data(api.get_panel_firm(world["firm_a_id"], U.ADMIN))
    assert_fields(firm, {"status": T.PANEL_SUSPENDED, "open_matter_count": 0})
    assert "CA" in firm["jurisdiction_codes"]

    claim = get_success_data(api.get_claim(world["claim_id"], U.ADJUSTER))
    assert claim["status"] == T.CLAIM_COVERAGE_ACCEPTED


def test_naming_the_still_active_firm_engages_it_on_the_same_terms(api):
    """The suspension is forward-looking only for the firm it names.

    PRD: "When `panel_firm_id` **is** supplied the selector does not run and
    `selection_reason` becomes `CLIENT_DIRECTED`, but the same eligibility
    conditions are still enforced and each failure gets its own code"

    Design: Difficulty/cross_entity_state_dependency/assignment_creation_gated_by_panel_firm_suspension_state
    """
    world = _two_firm_world(api)
    validate_error(
        api.create_assignment(world["claim_id"], _engagement(world["firm_a_id"]), U.ADJUSTER),
        E.ERR_PANEL_FIRM_NOT_ACTIVE,
        409,
    )

    assignment = get_success_data(
        api.create_assignment(world["claim_id"], _engagement(world["firm_b_id"]), U.ADJUSTER), 201
    )
    assert_fields(
        assignment,
        {
            "panel_firm_id": world["firm_b_id"],
            "selection_reason": T.SELECTION_CLIENT_DIRECTED,
            "status": T.ASSIGNMENT_ACTIVE,
            "partner_rate_cents_per_hour": 70000,
            "associate_rate_cents_per_hour": 43000,
            "paralegal_rate_cents_per_hour": 16000,
            "budget_remaining_cents": 3000000,
        },
    )

    firm_b = get_success_data(api.get_panel_firm(world["firm_b_id"], U.ADMIN))
    assert_fields(
        firm_b,
        {"status": T.PANEL_ACTIVE, "open_matter_count": 1, "blended_rate_cents": 48400},
    )

    claim = get_success_data(api.get_claim(world["claim_id"], U.ADJUSTER))
    assert claim["status"] == T.CLAIM_DEFENSE_OPEN


def _draft_plan_world(api):
    S.create_jurisdictions(api, ["CA", "TX"])
    plan = S.create_draft_rate_plan(api)
    applicant = S.create_applicant(api)
    return {
        "plan_id": plan["id"],
        "applicant_id": applicant["id"],
        "applicant_version": applicant["version"],
    }


def test_an_assessment_may_not_reference_a_rate_plan_still_in_draft(api):
    """Every rate factor is present; only the plan's lifecycle state refuses.

    PRD: "Only an `ACTIVE` plan may be referenced by a new exposure assessment,
    and referencing a `DRAFT` plan is `ERR_RATE_PLAN_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/assessment_creation_gated_by_rate_plan_draft_state
    """
    world = _draft_plan_world(api)
    payload = F.assessment(world["applicant_id"], world["plan_id"], world["applicant_version"])
    validate_error(
        api.create_assessment(payload, U.UNDERWRITER), E.ERR_RATE_PLAN_NOT_ACTIVE, 409
    )

    plan = get_success_data(api.get_rate_plan(world["plan_id"], U.ADMIN))
    assert_fields(
        plan,
        {
            "status": T.RATE_PLAN_DRAFT,
            "base_rate_per_employee_cents": 41750,
            "wage_hour_sublimit_pct": 0.25,
        },
    )

    _, meta = validate_paginated(
        api.list_assessments(U.UNDERWRITER, {"applicant_id": world["applicant_id"]})
    )
    assert meta["total_count"] == 0

    applicant = get_success_data(api.get_applicant(world["applicant_id"], U.UNDERWRITER))
    assert applicant["version"] == world["applicant_version"]


def test_the_identical_payload_creates_a_draft_assessment_once_the_plan_is_active(api):
    """Activation flips the referenced state and the same OCC token is still current.

    PRD: "Activating it moves it `DRAFT → ACTIVE`, which is the only transition
    on the plan's lifecycle and is refused with `ERR_RATE_PLAN_NOT_ACTIVATABLE`
    on a plan that is not currently `DRAFT`; `ACTIVE` is terminal."

    Design: Difficulty/cross_entity_state_dependency/assessment_creation_gated_by_rate_plan_draft_state
    """
    world = _draft_plan_world(api)
    payload = F.assessment(world["applicant_id"], world["plan_id"], world["applicant_version"])
    validate_error(
        api.create_assessment(payload, U.UNDERWRITER), E.ERR_RATE_PLAN_NOT_ACTIVE, 409
    )

    plan = get_success_data(api.activate_rate_plan(world["plan_id"], U.ADMIN))
    assert plan["status"] == T.RATE_PLAN_ACTIVE

    assessment = get_success_data(api.create_assessment(payload, U.UNDERWRITER), 201)
    assert_fields(
        assessment,
        {
            "status": T.ASSESSMENT_DRAFT,
            "rate_plan_id": world["plan_id"],
            "applicant_id": world["applicant_id"],
        },
    )
    assert_null(assessment, ["base_premium_cents", "indicated_premium_cents"])
