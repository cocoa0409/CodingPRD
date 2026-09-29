"""Field-level, cross-entity, aggregate and temporal validation: which rule fires, which
error it carries, and in what order the checks are consulted."""

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_AGREEMENT_FUNDING_EXCEEDED,
    ERR_AGREEMENT_HAS_BREACH,
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_BUILD_GATE_NOT_MET,
    ERR_BUILD_NUMBER_NOT_INCREASING,
    ERR_CURE_WINDOW_STILL_OPEN,
    ERR_INVALID_CONDITION_INDEX,
    ERR_INVALID_DATE_RANGE,
    ERR_INVALID_REQUEST,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SEQUENCE_INDEX_TAKEN,
)
from test_helpers.assertions import (
    assert_budget_summary,
    assert_fields_equal,
    assert_ledger,
    assert_payment_components,
    assert_pct_equals,
)
from test_helpers.constants import ALPHA_PASSING_METRICS
from test_helpers.fixtures import (
    DEFAULT_CRITERIA_1,
    DEFAULT_CRITERIA_2,
    add_milestone,
    create_engagement,
    draft_agreement,
    payment_of_milestone,
    read_agreement,
    read_milestone,
    record_accepted_review,
    record_conditional_review,
    record_rejected_review,
    setup_registry,
    setup_single_alpha,
    submit_build,
    submit_invoice,
)
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

TRIPLE_VIOLATION = {
    "feature_completeness_pct": 10.00,
    "crash_free_sessions_pct": 40.00,
    "content_completeness_pct": 5.00,
    "known_blocker_count": 99,
}


def _draftbook_and_aurora_solo(api):
    """A DRAFT agreement holding sequence_index 1, plus an ACTIVE deal with an open
    milestone and no engagements yet."""
    reg = setup_registry(api, with_reviewer=False)
    draftbook = draft_agreement(reg, "Draftbook", 12000000, 2500, "2027-09-30",
                                live_ops_quarterly_funding_cents=100000)
    draft_m1 = add_milestone(reg, draftbook["id"], 1, "Alpha", "ALPHA", 3600000, 0,
                             DEFAULT_CRITERIA_1)
    scenario = setup_single_alpha(api, title="Aurora Solo", advance_total_cents=3600000,
                                 contractor_budget_cents=800000,
                                 acceptance_criteria=DEFAULT_CRITERIA_1,
                                 live_ops_quarterly_funding_cents=100000, reg=reg)
    return reg, draftbook, draft_m1, scenario


def test_a_taken_sequence_index_and_a_backwards_date_range_write_nothing(api):
    """PRD §2.10 rule 28: "The submitted `sequence_index` is free within the agreement, on
    milestone creation — `ERR_SEQUENCE_INDEX_TAKEN`." PRD §3.8: "The dates must be well
    formed, with an `end_date` earlier than `start_date` reported as
    `ERR_INVALID_DATE_RANGE`."

    Design: Corner/validations/corner_duplicate_sequence_index_and_backwards_engagement_dates_are_refused
    """
    reg, draftbook, _, scenario = _draftbook_and_aurora_solo(api)

    validate_error(
        api.create_milestone(
            f.milestone_payload(draftbook["id"], 1, "Alpha rework", "BETA", 5400000, 0,
                                ["Online co-op"]),
            reg.dev,
        ),
        ERR_SEQUENCE_INDEX_TAKEN, 409,
    )
    rows, meta = validate_paginated(
        api.list_milestones(reg.finance, {"agreement_id": draftbook["id"]})
    )
    assert len(rows) == 1 and meta["total_count"] == 1

    validate_error(
        api.create_engagement(
            f.engagement_payload(scenario.m1["id"], "ART-QUILL", 400000,
                                 "2026-09-10", "2026-09-01", "Concept art"),
            reg.dev,
        ),
        ERR_INVALID_DATE_RANGE, 422,
    )
    engagements, engagement_meta = validate_paginated(
        api.list_engagements(reg.dev, {"milestone_id": scenario.m1["id"]})
    )
    assert engagements == [] and engagement_meta["total_count"] == 0

    assert_ledger(read_agreement(reg, draftbook["id"]), committed_cents=3600000)


def test_the_same_two_writes_are_admitted_once_they_comply(api):
    """PRD §3.2 admits a milestone whose `sequence_index` "is free within the agreement"
    and whose predecessor has a strictly smaller index; PRD §3.8 admits an engagement over
    "the closed calendar interval the vendor will work across as `start_date` and
    `end_date`, where the end may equal but never precede the start."

    Design: Corner/validations/corner_the_same_operations_succeed_once_the_violations_are_removed
    """
    reg, draftbook, draft_m1, scenario = _draftbook_and_aurora_solo(api)

    second = validate_success(
        api.create_milestone(
            f.milestone_payload(draftbook["id"], 2, "Beta", "BETA", 5400000, 0,
                                ["Online co-op"], draft_m1["id"]),
            reg.dev,
        ),
        201,
    )
    assert_fields_equal(
        second,
        {"sequence_index": 2, "status": "DEFINED",
         "depends_on_milestone_id": draft_m1["id"]},
        "milestone",
    )
    assert_ledger(read_agreement(reg, draftbook["id"]), committed_cents=9000000,
                  available_funding_cents=3000000)

    engagement = validate_success(
        api.create_engagement(
            f.engagement_payload(scenario.m1["id"], "ART-QUILL", 400000,
                                 "2026-09-01", "2026-09-10", "Concept art"),
            reg.dev,
        ),
        201,
    )
    assert_fields_equal(
        engagement,
        {"status": "ACTIVE", "committed_cents": 400000,
         "start_date": "2026-09-01", "end_date": "2026-09-10"},
        "engagement",
    )
    assert_budget_summary(
        validate_success(api.get_budget_summary(scenario.m1["id"], reg.dev)),
        scenario.m1["id"], budget=800000, committed_basis=400000, incurred_basis=0,
        available_committed=400000, overrun=0,
    )


def test_a_dual_operator_may_accept_or_pay_but_never_both(api):
    """PRD §3.1: "the operator authorizing a milestone payment must not be the same
    `PublisherUser` recorded as `reviewer_user_id` on the accepting review of that
    milestone. When they match, the authorization is refused with
    `ERR_SEGREGATION_OF_DUTIES` (403). A `DUAL` operator may therefore accept a milestone
    or pay for it, but never both."

    Design: Corner/validations/corner_dual_licensed_operator_cannot_authorize_the_payment_it_accepted
    """
    scenario = setup_single_alpha(api, title="Aurora Solo", advance_total_cents=3600000,
                                 contractor_budget_cents=0,
                                 acceptance_criteria=DEFAULT_CRITERIA_1,
                                 live_ops_quarterly_funding_cents=100000, with_dual=True)
    reg = scenario.reg
    build = submit_build(reg, scenario.m1["id"], 1, ALPHA_PASSING_METRICS)
    review = record_accepted_review(reg, build["id"], end_hour=12,
                                    reviewer_headers=reg.dual_reviewer)
    assert review["reviewer_user_id"] == reg.dual_id

    payment = payment_of_milestone(reg, scenario.m1["id"])
    validate_error(
        api.authorize_payment(payment["id"], reg.dual_finance,
                              {"memo": "Self-authorization attempt"}),
        ERR_SEGREGATION_OF_DUTIES, 403,
    )
    assert validate_success(
        api.get_payment(payment["id"], reg.finance)
    )["status"] == "PENDING_AUTHORIZATION"

    authorized = validate_success(
        api.authorize_payment(payment["id"], reg.finance,
                              {"memo": "Independent authorization"})
    )
    assert_fields_equal(authorized,
                        {"status": "AUTHORIZED", "authorized_by_user_id": reg.finance_id},
                        "payment")
    assert_payment_components(authorized, scheduled=3600000, overrun=0, gross=3600000,
                              holdback_bps=500, holdback=180000, net=3420000)
    assert_ledger(scenario.read_agreement(), advance_disbursed_cents=3420000,
                  holdback_reserve_cents=180000)


def test_the_cure_sweep_waits_for_the_deadline_and_then_breaches(api):
    """PRD §3.3: "If no `CURE_PENDING` milestone has actually run out of time — that is, if
    every open cure deadline is still greater than or equal to the logical clock — there is
    nothing to sweep and the request is refused with `ERR_CURE_WINDOW_STILL_OPEN`." A
    successful sweep "moves the agreement `ACTIVE → SUSPENDED` with `funding_posture` set
    to `FROZEN`", after which "reinstatement is additionally refused while `breach_count`
    is greater than zero, with `ERR_AGREEMENT_HAS_BREACH`".

    Design: Corner/validations/corner_cure_sweep_is_refused_before_the_deadline_and_breaches_after_it
    """
    scenario = setup_single_alpha(api, title="Aurora Solo", advance_total_cents=3600000,
                                 contractor_budget_cents=0,
                                 acceptance_criteria=DEFAULT_CRITERIA_2,
                                 live_ops_quarterly_funding_cents=100000)
    reg = scenario.reg
    build = submit_build(reg, scenario.m1["id"], 1, ALPHA_PASSING_METRICS)
    record_conditional_review(reg, build["id"], [0], 14, end_hour=12)

    assert_fields_equal(
        read_milestone(reg, scenario.m1["id"]),
        {"status": "CURE_PENDING", "cure_count": 1, "open_condition_indexes": [0],
         "cure_deadline_at": "2026-08-15T00:00:00.000Z"},
        "milestone",
    )

    validate_error(api.cure_sweep(scenario.agreement_id, reg.finance),
                   ERR_CURE_WINDOW_STILL_OPEN, 409)
    assert read_milestone(reg, scenario.m1["id"])["status"] == "CURE_PENDING"

    validate_success(api.set_clock("2026-08-15T00:00:00.001Z", reg.admin))
    validate_success(api.cure_sweep(scenario.agreement_id, reg.finance))

    assert read_milestone(reg, scenario.m1["id"])["status"] == "BREACHED"
    swept = scenario.read_agreement()
    assert_fields_equal(swept,
                        {"status": "SUSPENDED", "funding_posture": "FROZEN"},
                        "agreement")
    assert_ledger(swept, breach_count=1)

    validate_error(
        api.reinstate_agreement(scenario.agreement_id, reg.finance,
                                {"reason": "Try to resume anyway"}),
        ERR_AGREEMENT_HAS_BREACH, 409,
    )
    assert scenario.read_agreement()["status"] == "SUSPENDED"


def test_individually_modest_milestones_may_still_overrun_the_pool_by_a_cent(api):
    """PRD §3.2: "Last, the money must fit: a `funded_amount_cents` greater than the
    agreement's current `available_funding_cents` is `ERR_AGREEMENT_FUNDING_EXCEEDED`."

    Design: Corner/validations/corner_individually_valid_milestones_collectively_exceed_the_funding_pool
    """
    reg = setup_registry(api, with_reviewer=False)
    agreement = draft_agreement(reg, "Aurora Drift", 12000000,
                                live_ops_quarterly_funding_cents=500000)
    m1 = add_milestone(reg, agreement["id"], 1, "Alpha", "ALPHA", 3600000, 0,
                       DEFAULT_CRITERIA_1)
    m2 = add_milestone(reg, agreement["id"], 2, "Beta", "BETA", 5400000, 0,
                       ["Online co-op"], m1["id"])

    validate_error(
        api.create_milestone(
            f.milestone_payload(agreement["id"], 3, "Gold too rich", "GOLD", 3000001, 0,
                                ["Zero blockers"], m2["id"]),
            reg.dev,
        ),
        ERR_AGREEMENT_FUNDING_EXCEEDED, 422,
    )
    assert_ledger(read_agreement(reg, agreement["id"]), committed_cents=9000000)

    m3 = validate_success(
        api.create_milestone(
            f.milestone_payload(agreement["id"], 3, "Gold", "GOLD", 3000000, 0,
                                ["Zero blockers"], m2["id"]),
            reg.dev,
        ),
        201,
    )
    assert m3["funded_amount_cents"] == 3000000
    assert_ledger(read_agreement(reg, agreement["id"]), committed_cents=12000000,
                  available_funding_cents=0)

    rows, meta = validate_paginated(
        api.list_milestones(reg.finance, {"agreement_id": agreement["id"]})
    )
    assert len(rows) == 3 and meta["total_count"] == 3


def test_conditionally_required_fields_bind_only_on_their_trigger_value(api):
    """PRD §2.10: structural validation "also covers *conditionally* required fields, which
    become required the moment their trigger value is present: rejecting an invoice requires
    a present, non-blank `rejection_reason`; a `CONDITIONAL` verdict requires `conditions`
    to be a non-empty array; an `ACCEPTED` or `REJECTED` verdict requires `conditions` to be
    absent or an empty array". PRD §3.5 adds that "every value in `conditions` must be a
    valid zero-based index into the target milestone's `acceptance_criteria` array, and an
    out-of-range or otherwise invalid index is `ERR_INVALID_CONDITION_INDEX`."

    Design: Corner/validations/corner_conditionally_required_fields_apply_only_for_their_trigger_value
    """
    scenario = setup_single_alpha(api, title="Aurora Solo", advance_total_cents=3600000,
                                 contractor_budget_cents=800000,
                                 acceptance_criteria=DEFAULT_CRITERIA_2,
                                 live_ops_quarterly_funding_cents=100000)
    reg = scenario.reg
    engagement = create_engagement(reg, scenario.m1["id"], "ART-QUILL", 400000,
                                   "2026-08-05", "2026-09-05", "Concept art")
    invoice = submit_invoice(reg, engagement["id"], "QUILL-001", 150000)
    build = submit_build(reg, scenario.m1["id"], 1, ALPHA_PASSING_METRICS)

    window = f.review_window("2026-08-01", 9, 10)
    validate_error(
        api.create_review(
            f.review_payload(build["id"], "CONDITIONAL", window["review_window_start_at"],
                             window["review_window_end_at"],
                             notes="Conditions forgotten"),
            reg.reviewer,
        ),
        ERR_INVALID_REQUEST, 400,
    )
    validate_error(
        api.create_review(
            f.review_payload(build["id"], "ACCEPTED", window["review_window_start_at"],
                             window["review_window_end_at"], conditions=[0],
                             notes="Accepted with conditions"),
            reg.reviewer,
        ),
        ERR_INVALID_REQUEST, 400,
    )
    validate_error(
        api.create_review(
            f.review_payload(build["id"], "CONDITIONAL", window["review_window_start_at"],
                             window["review_window_end_at"], conditions=[5],
                             notes="Index out of range"),
            reg.reviewer,
        ),
        ERR_INVALID_CONDITION_INDEX, 422,
    )
    validate_error(
        api.decide_invoice(invoice["id"], {"decision": "REJECT"}, reg.finance),
        ERR_INVALID_REQUEST, 400,
    )
    assert validate_success(
        api.get_invoice(invoice["id"], reg.dev)
    )["status"] == "SUBMITTED"

    rows, meta = validate_paginated(api.list_reviews(reg.reviewer, {"build_id": build["id"]}))
    assert rows == [] and meta["total_count"] == 0
    assert_fields_equal(read_milestone(reg, scenario.m1["id"]),
                        {"status": "UNDER_REVIEW", "cure_count": 0}, "milestone")


def test_the_delivery_checks_surface_one_at_a_time_in_priority_order(api):
    """PRD §3.4: "Delivery is guarded by a short chain of state rules ahead of the gate
    arithmetic. The agreement must be `ACTIVE`, or the answer is
    `ERR_AGREEMENT_NOT_ACTIVE`." PRD §2.10 fixes the remaining order, rule 46 for
    `ERR_BUILD_GATE_NOT_MET` ahead of rule 48: "A `build_number` that fails to exceed
    `latest_build_number` is `ERR_BUILD_NUMBER_NOT_INCREASING`."

    Design: Corner/validations/corner_build_submission_checks_run_in_declared_priority_order
    """
    scenario = setup_single_alpha(api, title="Aurora Solo", advance_total_cents=3600000,
                                 contractor_budget_cents=0,
                                 acceptance_criteria=DEFAULT_CRITERIA_1,
                                 live_ops_quarterly_funding_cents=100000)
    reg = scenario.reg
    build = submit_build(reg, scenario.m1["id"], 1, ALPHA_PASSING_METRICS)
    record_rejected_review(reg, build["id"])
    validate_success(api.suspend_agreement(scenario.agreement_id, reg.finance,
                                          {"reason": "Funding review"}))

    triple = f.build_payload_from_metrics(scenario.m1["id"], 1, TRIPLE_VIOLATION)
    validate_error(api.create_build(triple, reg.dev), ERR_AGREEMENT_NOT_ACTIVE, 409)

    reinstated = validate_success(
        api.reinstate_agreement(scenario.agreement_id, reg.finance,
                                {"reason": "Funding confirmed"})
    )
    assert reinstated["status"] == "ACTIVE"
    assert read_milestone(reg, scenario.m1["id"])["status"] == "IN_DEVELOPMENT"

    validate_error(api.create_build(triple, reg.dev), ERR_BUILD_GATE_NOT_MET, 422)
    validate_error(
        api.create_build(
            f.build_payload_from_metrics(scenario.m1["id"], 1, ALPHA_PASSING_METRICS),
            reg.dev,
        ),
        ERR_BUILD_NUMBER_NOT_INCREASING, 409,
    )

    second = validate_success(
        api.create_build(
            f.build_payload_from_metrics(scenario.m1["id"], 2, ALPHA_PASSING_METRICS),
            reg.dev,
        ),
        201,
    )
    assert second["gate_state"] == "PASSED"
    assert_pct_equals(second["readiness_score"], 79.35, "readiness_score")
    assert_fields_equal(read_milestone(reg, scenario.m1["id"]),
                        {"status": "UNDER_REVIEW", "latest_build_number": 2}, "milestone")

    rows, meta = validate_paginated(
        api.list_milestone_builds(scenario.m1["id"], reg.dev)
    )
    assert meta["total_count"] == 2
    assert {row["build_number"]: row["gate_state"] for row in rows} == {
        1: "SUPERSEDED", 2: "PASSED"
    }
