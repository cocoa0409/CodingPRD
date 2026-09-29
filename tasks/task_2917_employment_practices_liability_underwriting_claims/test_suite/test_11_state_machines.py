"""Lifecycle entry points, refused replays and the clock-driven transitions."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import api_errors as E
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers import test_users as U
from test_helpers import types as T
from test_helpers.assertions import assert_fields, assert_null, assert_same_instant


def _tx_book(api):
    """A TX jurisdiction and a small Bayline applicant on an ACTIVE plan."""
    S.create_jurisdiction(api, "TX")
    plan_id = S.create_active_rate_plan(api)["id"]
    applicant = S.create_applicant(
        api,
        legal_name="Bayline Foods LLC",
        total_headcount=40,
        prior_year_separations=4,
        jurisdiction_headcounts=[{"code": "TX", "headcount": 40}],
        primary_jurisdiction_code="TX",
    )
    return {"plan_id": plan_id, "applicant_id": applicant["id"]}


def _small_tx_policy(api):
    """A bound 10,000,000-cent TX policy with a 2,500,000-cent retention."""
    book = _tx_book(api)
    assessment = S.create_approved_assessment(
        api,
        book["applicant_id"],
        book["plan_id"],
        requested_aggregate_limit_cents=10000000,
        requested_retention_cents=2500000,
        third_party_coverage_requested=None,
    )
    policy = S.bind_policy(api, assessment["id"])
    book.update({"assessment_id": assessment["id"], "policy_id": policy["id"]})
    return book


def test_every_newly_created_entity_sits_in_its_declared_initial_state(api):
    """Plans start DRAFT, firms PANEL_ACTIVE, services PENDING and assessments DRAFT.

    PRD: "Services are created in `PENDING` and contribute nothing there."

    Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_state
    """
    S.create_jurisdiction(api, "TX")
    plan = get_success_data(api.create_rate_plan(F.rate_plan(), U.ADMIN), expected_status=201)
    assert plan["status"] == T.RATE_PLAN_DRAFT

    firm = S.create_panel_firm(
        api,
        name="Lonestar Defense Group",
        tier=T.TIER_REGIONAL,
        jurisdiction_codes=["TX"],
        partner_rate_cents_per_hour=70000,
        associate_rate_cents_per_hour=43000,
        paralegal_rate_cents_per_hour=16000,
        capacity_open_matters=2,
    )
    assert_fields(firm, {"status": T.PANEL_ACTIVE, "open_matter_count": 0})

    applicant = S.create_applicant(
        api,
        legal_name="Bayline Foods LLC",
        total_headcount=40,
        prior_year_separations=4,
        jurisdiction_headcounts=[{"code": "TX", "headcount": 40}],
        primary_jurisdiction_code="TX",
    )
    service = S.create_risk_service(
        api,
        applicant["id"],
        effective_from="2026-08-01T00:00:00.000Z",
        effective_to="2026-09-01T00:00:00.000Z",
    )
    assert service["status"] == T.SERVICE_PENDING
    assert_null(service, ["completed_at"])

    fresh = get_success_data(api.get_applicant(applicant["id"], U.UNDERWRITER))
    assert fresh["risk_credit_pct"] == 0.00

    get_success_data(api.activate_rate_plan(plan["id"], U.ADMIN))
    assessment = S.create_assessment(
        api,
        applicant["id"],
        plan["id"],
        requested_aggregate_limit_cents=10000000,
        requested_retention_cents=2500000,
        third_party_coverage_requested=None,
    )
    assert assessment["status"] == T.ASSESSMENT_DRAFT


def test_activating_the_plan_is_what_unblocks_assessment_creation(api):
    """A DRAFT plan is inert; the same payload succeeds once the plan is ACTIVE.

    PRD: "Only an `ACTIVE` plan may be referenced by a new exposure assessment,
    and referencing a `DRAFT` plan is `ERR_RATE_PLAN_NOT_ACTIVE`."

    Design: Corner/state_machines/rate_plan_activate_moves_draft_to_active_and_unblocks_assessments
    """
    S.create_jurisdiction(api, "TX")
    plan = S.create_draft_rate_plan(api)
    applicant = S.create_applicant(
        api,
        legal_name="Bayline Foods LLC",
        total_headcount=40,
        prior_year_separations=4,
        jurisdiction_headcounts=[{"code": "TX", "headcount": 40}],
        primary_jurisdiction_code="TX",
    )
    payload = F.assessment(
        applicant["id"],
        plan["id"],
        applicant["version"],
        requested_aggregate_limit_cents=10000000,
        requested_retention_cents=2500000,
        third_party_coverage_requested=None,
    )
    validate_error(
        api.create_assessment(payload, U.UNDERWRITER), E.ERR_RATE_PLAN_NOT_ACTIVE, 409
    )
    unchanged = get_success_data(api.get_applicant(applicant["id"], U.UNDERWRITER))
    assert unchanged["version"] == applicant["version"]

    activated = get_success_data(api.activate_rate_plan(plan["id"], U.ADMIN))
    assert_fields(activated, {"status": T.RATE_PLAN_ACTIVE, "version": 2})

    created = get_success_data(api.create_assessment(payload, U.UNDERWRITER), expected_status=201)
    assert_fields(
        created, {"status": T.ASSESSMENT_DRAFT, "rate_plan_id": plan["id"]}
    )


def test_a_second_activation_of_the_same_plan_is_refused(api):
    """ACTIVE is terminal, so the activate action is not idempotent.

    PRD: "Activating it moves it `DRAFT → ACTIVE`, which is the only transition
    on the plan's lifecycle and is refused with
    `ERR_RATE_PLAN_NOT_ACTIVATABLE` on a plan that is not currently `DRAFT`;
    `ACTIVE` is terminal."

    Design: Corner/state_machines/second_rate_plan_activate_is_rate_plan_not_activatable
    """
    plan = S.create_active_rate_plan(api)
    validate_error(
        api.activate_rate_plan(plan["id"], U.ADMIN), E.ERR_RATE_PLAN_NOT_ACTIVATABLE, 409
    )
    after = get_success_data(api.get_rate_plan(plan["id"], U.UNDERWRITER))
    assert_fields(after, {"status": T.RATE_PLAN_ACTIVE, "version": 2})


def test_neither_review_nor_the_coverage_decision_can_be_replayed(api):
    """Each claim lifecycle step is a one-shot transition guarded by its own error.

    PRD: "Starting a review moves the claim `REPORTED → UNDER_REVIEW`. On any
    other status the answer is `ERR_CLAIM_NOT_REVIEWABLE`"

    Design: Corner/state_machines/claim_start_review_and_coverage_decision_cannot_be_replayed
    """
    world = _small_tx_policy(api)
    claim = S.report_claim(
        api,
        world["policy_id"],
        first_notice_at="2026-08-05T00:00:00.000Z",
        alleged_damages_cents=5000000,
    )
    get_success_data(api.start_claim_review(claim["id"], U.ADJUSTER))
    validate_error(
        api.start_claim_review(claim["id"], U.ADJUSTER), E.ERR_CLAIM_NOT_REVIEWABLE, 409
    )

    get_success_data(
        api.coverage_decision(claim["id"], F.coverage_decision(T.DECISION_ACCEPT), U.ADJUSTER)
    )
    validate_error(
        api.coverage_decision(
            claim["id"],
            F.coverage_decision(T.DECISION_DENY, denial_reason="late notice"),
            U.ADJUSTER,
        ),
        E.ERR_COVERAGE_ALREADY_DECIDED,
        409,
    )

    final = get_success_data(api.get_claim(claim["id"], U.ADJUSTER))
    assert_fields(
        final,
        {
            "status": T.CLAIM_COVERAGE_ACCEPTED,
            "coverage_bucket": T.BUCKET_FIRST_PARTY,
            "per_claim_retention_cents": 2500000,
            "applied_retention_cents": 2500000,
        },
    )
    assert_null(final, ["denial_reason"])


def test_a_submitted_invoice_can_neither_be_voided_nor_approved(api):
    """Void needs APPROVED and approve needs UNDER_AUDIT or ADJUSTED.

    PRD: "Invoices are created in `SUBMITTED` with every audit output field
    unpopulated."

    Design: Corner/state_machines/void_on_a_submitted_defense_invoice_is_invoice_not_voidable
    """
    world = _small_tx_policy(api)
    firm = S.create_panel_firm(
        api,
        name="Lonestar Defense Group",
        tier=T.TIER_REGIONAL,
        jurisdiction_codes=["TX"],
        partner_rate_cents_per_hour=92000,
        associate_rate_cents_per_hour=51000,
        paralegal_rate_cents_per_hour=18000,
        capacity_open_matters=2,
    )
    claim = S.accepted_claim(
        api,
        world["policy_id"],
        first_notice_at="2026-08-05T00:00:00.000Z",
        alleged_damages_cents=5000000,
    )
    assignment = S.create_assignment(
        api,
        claim["id"],
        engagement_from="2026-08-05T00:00:00.000Z",
        engagement_to="2026-11-01T00:00:00.000Z",
        budget_cap_cents=3000000,
        panel_firm_id=firm["id"],
    )
    invoice = S.submit_invoice(
        api,
        assignment["id"],
        firm["id"],
        period_start="2026-08-10T00:00:00.000Z",
        period_end="2026-08-31T00:00:00.000Z",
        partner_hours=None,
        associate_hours=10.0,
        paralegal_hours=None,
        block_billed_hours=None,
        expenses_cents=None,
    )
    assert invoice["status"] == T.INVOICE_SUBMITTED
    assert_null(
        invoice,
        [
            "billed_fees_cents",
            "rate_cap_excess_cents",
            "allowed_amount_cents",
            "void_reason",
        ],
    )

    validate_error(
        api.void_invoice(invoice["id"], "billed to the wrong matter", U.CLAIMS_MANAGER),
        E.ERR_INVOICE_NOT_VOIDABLE,
        409,
    )
    validate_error(
        api.approve_invoice(invoice["id"], U.ADJUSTER_2), E.ERR_INVOICE_NOT_APPROVABLE, 409
    )

    still = get_success_data(api.get_invoice(invoice["id"], U.ADJUSTER))
    assert still["status"] == T.INVOICE_SUBMITTED
    assert_null(still, ["void_reason"])

    audited = get_success_data(api.audit_invoice(invoice["id"], U.ADJUSTER))
    assert_fields(
        audited,
        {
            "billed_fees_cents": 510000,
            "rate_cap_excess_cents": 60000,
            "allowed_amount_cents": 450000,
        },
    )

    assignment = get_success_data(api.get_assignment(assignment["id"], U.ADJUSTER))
    assert_fields(
        assignment, {"budget_spent_cents": 0, "budget_remaining_cents": 3000000}
    )
    policy = get_success_data(api.get_policy(world["policy_id"], U.ADJUSTER))
    assert policy["defense_spend_cents"] == 0


def test_completing_a_service_before_its_window_opens_is_refused(api):
    """PENDING → ACTIVE needs the logical clock inside the half-open window.

    PRD: "Completing a service moves it `PENDING → ACTIVE` and requires the
    logical clock to be inside the service's half-open window — at or after
    `effective_from` and strictly before `effective_to`; a service that is not
    `PENDING`, or a clock outside that window, is `ERR_SERVICE_NOT_COMPLETABLE`
    (HTTP 409)."

    Design: Corner/state_machines/risk_service_complete_outside_its_window_is_service_not_completable
    """
    S.create_jurisdiction(api, "TX")
    applicant = S.create_applicant(
        api,
        legal_name="Bayline Foods LLC",
        total_headcount=40,
        prior_year_separations=4,
        jurisdiction_headcounts=[{"code": "TX", "headcount": 40}],
        primary_jurisdiction_code="TX",
    )
    service = S.create_risk_service(
        api,
        applicant["id"],
        effective_from="2026-09-01T00:00:00.000Z",
        effective_to="2027-09-01T00:00:00.000Z",
    )
    validate_error(
        api.complete_risk_service(service["id"], U.UNDERWRITER),
        E.ERR_SERVICE_NOT_COMPLETABLE,
        409,
    )
    still = get_success_data(api.get_risk_service(service["id"], U.UNDERWRITER))
    assert still["status"] == T.SERVICE_PENDING
    assert_null(still, ["completed_at"])
    unchanged = get_success_data(api.get_applicant(applicant["id"], U.UNDERWRITER))
    assert_fields(
        unchanged, {"risk_credit_pct": 0.00, "exposure_score": 28.00, "version": 1}
    )

    S.advance_clock(api, "2026-09-01T00:00:00.000Z")
    completed = get_success_data(api.complete_risk_service(service["id"], U.UNDERWRITER))
    assert completed["status"] == T.SERVICE_ACTIVE
    assert_same_instant(
        completed["completed_at"], "2026-09-01T00:00:00.000Z", "completed_at"
    )

    credited = get_success_data(api.get_applicant(applicant["id"], U.UNDERWRITER))
    assert_fields(
        credited, {"risk_credit_pct": 0.08, "exposure_score": 22.00, "version": 2}
    )


def test_one_clock_advance_activates_a_policy_and_lapses_a_service(api):
    """The clock setter reports all four transition lists it drove.

    PRD: "The response body reports the resulting state as `current_utc`,
    together with the four lists `activated_policy_ids`, `expired_policy_ids`,
    `lapsed_service_ids` and `lapsed_resolution_ids`."

    Design: Corner/state_machines/clock_advance_activates_a_bound_policy_and_lapses_an_active_service
    """
    S.create_jurisdiction(api, "TX")
    plan_id = S.create_active_rate_plan(api)["id"]
    applicant = S.create_applicant(
        api,
        legal_name="Bayline Foods LLC",
        total_headcount=40,
        prior_year_separations=4,
        jurisdiction_headcounts=[{"code": "TX", "headcount": 40}],
        primary_jurisdiction_code="TX",
    )
    service = S.create_active_risk_service(
        api,
        applicant["id"],
        effective_from="2026-08-01T00:00:00.000Z",
        effective_to="2026-09-01T00:00:00.000Z",
    )
    assessment = S.create_approved_assessment(
        api,
        applicant["id"],
        plan_id,
        requested_aggregate_limit_cents=10000000,
        requested_retention_cents=2500000,
        third_party_coverage_requested=None,
    )
    policy = S.bind_policy(
        api,
        assessment["id"],
        effective_from="2026-10-01T00:00:00.000Z",
        effective_to="2027-10-01T00:00:00.000Z",
    )
    assert policy["status"] == T.POLICY_BOUND

    report = S.advance_clock(api, "2026-10-01T00:00:00.000Z")
    assert_same_instant(report["current_utc"], "2026-10-01T00:00:00.000Z", "current_utc")
    assert report["activated_policy_ids"] == [policy["id"]]
    assert report["lapsed_service_ids"] == [service["id"]]
    assert report["expired_policy_ids"] == []
    assert report["lapsed_resolution_ids"] == []

    fresh_policy = get_success_data(api.get_policy(policy["id"], U.UW_MANAGER))
    assert_fields(
        fresh_policy, {"status": T.POLICY_ACTIVE, "limit_posture": T.POSTURE_OPEN}
    )
    lapsed = get_success_data(api.get_risk_service(service["id"], U.UNDERWRITER))
    assert lapsed["status"] == T.SERVICE_LAPSED
    applicant_after = get_success_data(api.get_applicant(applicant["id"], U.UNDERWRITER))
    assert_fields(applicant_after, {"risk_credit_pct": 0.00, "exposure_score": 28.00})
    assessment_after = get_success_data(api.get_assessment(assessment["id"], U.UNDERWRITER))
    assert_fields(
        assessment_after, {"status": T.ASSESSMENT_BOUND, "credit_basis_stale": False}
    )


def test_an_expired_policy_refuses_suspend_reinstate_and_new_claims(api):
    """EXPIRED is terminal on the availability axis and closes intake as well.

    PRD: "Any non-expired policy — `BOUND`, `ACTIVE` or `SUSPENDED` alike —
    moves to `EXPIRED` as soon as the logical clock reaches or passes its
    `effective_to`. `EXPIRED` is terminal."

    Design: Corner/state_machines/expired_policy_refuses_suspend_reinstate_and_new_claims
    """
    book = _tx_book(api)
    assessment = S.create_approved_assessment(
        api,
        book["applicant_id"],
        book["plan_id"],
        requested_aggregate_limit_cents=10000000,
        requested_retention_cents=2500000,
        third_party_coverage_requested=None,
    )
    policy = S.bind_policy(
        api,
        assessment["id"],
        effective_from="2026-08-01T00:00:00.000Z",
        effective_to="2026-09-01T00:00:00.000Z",
    )
    report = S.advance_clock(api, "2026-09-01T00:00:00.000Z")
    assert report["expired_policy_ids"] == [policy["id"]]
    expired = get_success_data(api.get_policy(policy["id"], U.UW_MANAGER))
    version_at_expiry = expired["version"]

    validate_error(
        api.suspend_policy(policy["id"], "premium audit dispute", U.UW_MANAGER),
        E.ERR_POLICY_NOT_SUSPENDABLE,
        409,
    )
    validate_error(
        api.reinstate_policy(policy["id"], U.UW_MANAGER), E.ERR_POLICY_NOT_REINSTATABLE, 409
    )
    validate_error(
        api.report_claim(
            policy["id"],
            F.claim(
                claim_type=T.CLAIM_TYPE_HARASSMENT,
                first_notice_at="2026-08-15T00:00:00.000Z",
                alleged_damages_cents=4000000,
            ),
            U.ADJUSTER,
        ),
        E.ERR_POLICY_NOT_IN_FORCE,
        409,
    )

    after = get_success_data(api.get_policy(policy["id"], U.UW_MANAGER))
    assert_fields(after, {"status": T.POLICY_EXPIRED, "version": version_at_expiry})
    assert_null(after, ["suspension_reason", "suspended_at"])

    _, meta = validate_paginated(api.list_claims(U.ADJUSTER, {"policy_id": policy["id"]}))
    assert meta["total_count"] == 0
