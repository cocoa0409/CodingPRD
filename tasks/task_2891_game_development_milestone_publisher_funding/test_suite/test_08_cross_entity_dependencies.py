"""Admissibility that turns on the state of another entity: a BETA build waiting on
its predecessor milestone, and an invoice approval waiting on the agreement two hops
above it."""

from test_helpers import factories as f
from test_helpers.api_errors import ERR_AGREEMENT_NOT_ACTIVE, ERR_DEPENDENCY_NOT_ACCEPTED
from test_helpers.assertions import assert_budget_summary, assert_fields_equal, assert_pct_equals
from test_helpers.fixtures import (
    DEFAULT_CRITERIA_2,
    activate,
    add_milestone,
    create_engagement,
    draft_agreement,
    read_milestone,
    record_accepted_review,
    setup_aurora_drift,
    setup_registry,
    submit_build,
    submit_invoice,
)
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

ALPHA_PASSING = {
    "feature_completeness_pct": 75.00,
    "crash_free_sessions_pct": 96.00,
    "content_completeness_pct": 60.00,
    "known_blocker_count": 5,
}
BETA_PASSING = {
    "feature_completeness_pct": 95.00,
    "crash_free_sessions_pct": 98.50,
    "content_completeness_pct": 85.00,
    "known_blocker_count": 2,
}


def _alpha_under_review(api):
    scenario = setup_aurora_drift(api)
    build1 = submit_build(scenario.reg, scenario.m1["id"], 1, ALPHA_PASSING)
    assert read_milestone(scenario.reg, scenario.m1["id"])["status"] == "UNDER_REVIEW"
    return scenario, build1


def test_the_beta_build_is_refused_while_its_predecessor_is_only_under_review(api):
    """PRD §3.4: "when the milestone has a `depends_on_milestone_id` whose target has
    not reached `ACCEPTED`, the submission is refused with
    `ERR_DEPENDENCY_NOT_ACCEPTED`."

    Design: Difficulty/cross_entity_state_dependency/beta_build_blocked_until_predecessor_milestone_is_accepted
    """
    scenario, _build1 = _alpha_under_review(api)
    reg = scenario.reg

    response = api.create_build(
        f.build_payload_from_metrics(scenario.m2["id"], 1, BETA_PASSING), reg.dev
    )
    validate_error(response, ERR_DEPENDENCY_NOT_ACCEPTED, 409)

    milestone = read_milestone(reg, scenario.m2["id"])
    assert_fields_equal(
        milestone, {"status": "DEFINED", "latest_build_number": 0}, "M2"
    )
    rows, meta = validate_paginated(api.list_milestone_builds(scenario.m2["id"], reg.dev))
    assert rows == [] and meta["total_count"] == 0


def test_the_identical_beta_build_is_admitted_once_the_predecessor_is_accepted(api):
    """PRD §3.5: acceptance "promotes every milestone whose `depends_on_milestone_id`
    points at it and whose `status` is still `DEFINED` from `DEFINED →
    IN_DEVELOPMENT`", which is what makes the same payload admissible.

    Design: Difficulty/cross_entity_state_dependency/beta_build_blocked_until_predecessor_milestone_is_accepted
    """
    scenario, build1 = _alpha_under_review(api)
    reg = scenario.reg

    record_accepted_review(reg, build1["id"])
    assert read_milestone(reg, scenario.m1["id"])["status"] == "ACCEPTED"
    assert read_milestone(reg, scenario.m2["id"])["status"] == "IN_DEVELOPMENT"

    build = validate_success(
        api.create_build(
            f.build_payload_from_metrics(scenario.m2["id"], 1, BETA_PASSING), reg.dev
        ),
        201,
    )
    assert build["gate_state"] == "PASSED"
    assert_pct_equals(build["readiness_score"], 94.23, "readiness_score")

    assert_fields_equal(
        read_milestone(reg, scenario.m2["id"]),
        {"status": "UNDER_REVIEW", "latest_build_number": 1},
        "M2",
    )
    assert read_milestone(reg, scenario.m3["id"])["status"] == "DEFINED"


def _willowmark_suspended_with_open_invoice(api):
    """A submitted vendor invoice whose grandparent agreement has been suspended."""
    reg = setup_registry(api, studio_name="Willowmark Studio",
                         studio_email="dev@willowmark.example", studio_country="IE",
                         with_reviewer=False)
    agreement = draft_agreement(reg, "Willowmark", 1000000, 2500, "2027-03-31",
                                live_ops_quarterly_funding_cents=100000)
    milestone = add_milestone(reg, agreement["id"], 1, "Alpha", "ALPHA",
                              1000000, 200000, DEFAULT_CRITERIA_2)
    activate(reg, agreement["id"])
    engagement = create_engagement(
        reg, milestone["id"], "UI-WILLOW", 200000, "2026-08-05", "2026-09-20"
    )
    assert engagement["status"] == "ACTIVE"
    invoice = submit_invoice(reg, engagement["id"], "WIL-001", 100000, "2026-08-31")

    validate_success(
        api.suspend_agreement(agreement["id"], reg.finance,
                              {"reason": "Publisher liquidity review"})
    )
    return reg, agreement, milestone, engagement, invoice


def test_the_invoice_approval_is_refused_while_the_agreement_is_suspended(api):
    """PRD §2.10 rule 23 and PRD §3.3: "No invoice is voided by a suspension: invoices
    already sitting in `SUBMITTED` stay pending, but they cannot be approved while
    their engagement is not `ACTIVE`." The agreement-status rule is checked first, so
    the answer is `ERR_AGREEMENT_NOT_ACTIVE`.

    Design: Difficulty/cross_entity_state_dependency/invoice_approval_depends_on_agreement_status_two_hops_above_the_invoice
    """
    reg, _agreement, _milestone, engagement, invoice = _willowmark_suspended_with_open_invoice(api)

    response = api.decide_invoice(invoice["id"], f.approve_invoice_payload(), reg.finance)
    validate_error(response, ERR_AGREEMENT_NOT_ACTIVE, 409)

    assert validate_success(api.get_invoice(invoice["id"], reg.dev))["status"] == "SUBMITTED"
    reread = validate_success(api.get_engagement(engagement["id"], reg.dev))
    assert reread["approved_invoice_total_cents"] == 0


def test_reinstatement_returns_the_agreement_and_its_engagement(api):
    """PRD §3.3: reinstatement "restores each engagement that is currently
    `SUSPENDED`" and that an engagement returns "to `ACTIVE` when its milestone's
    `status` is `IN_DEVELOPMENT`, `UNDER_REVIEW`, `CURE_PENDING` or `ACCEPTED`". Step three
    "recomputes `funding_posture`, which after a reinstatement can only be `OPEN` or
    `RESTRICTED` and never `FROZEN`".

    Design: Difficulty/cross_entity_state_dependency/invoice_approval_depends_on_agreement_status_two_hops_above_the_invoice
    """
    reg, agreement, _milestone, engagement, _invoice = _willowmark_suspended_with_open_invoice(api)

    reinstated = validate_success(
        api.reinstate_agreement(agreement["id"], reg.finance,
                                {"reason": "Liquidity review cleared"})
    )
    assert_fields_equal(
        reinstated, {"status": "ACTIVE", "funding_posture": "OPEN"}, "agreement"
    )
    assert validate_success(api.get_engagement(engagement["id"], reg.dev))["status"] == "ACTIVE"


def test_the_same_approval_succeeds_after_the_agreement_is_reinstated(api):
    """PRD §3.8: "An approval sets the invoice's `status` to `APPROVED`, stamps
    `decided_at` from the logical clock, adds `amount_cents` to the engagement's
    `approved_invoice_total_cents`, and grows the milestone's incurred basis."

    Design: Difficulty/cross_entity_state_dependency/invoice_approval_depends_on_agreement_status_two_hops_above_the_invoice
    """
    reg, agreement, milestone, engagement, invoice = _willowmark_suspended_with_open_invoice(api)

    api.decide_invoice(invoice["id"], f.approve_invoice_payload(), reg.finance)
    validate_success(
        api.reinstate_agreement(agreement["id"], reg.finance,
                                {"reason": "Liquidity review cleared"})
    )
    approved = validate_success(
        api.decide_invoice(invoice["id"], f.approve_invoice_payload(), reg.finance)
    )
    assert approved["status"] == "APPROVED"
    assert approved["decided_at"] is not None

    reread = validate_success(api.get_engagement(engagement["id"], reg.dev))
    assert reread["approved_invoice_total_cents"] == 100000

    assert_budget_summary(
        validate_success(api.get_budget_summary(milestone["id"], reg.dev)),
        milestone_id=milestone["id"],
        budget=200000,
        committed_basis=200000,
        incurred_basis=100000,
        available_committed=0,
        overrun=0,
    )
