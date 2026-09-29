"""Non-linear state machines: revision loops and parallel status dimensions.

Each test below translates exactly one designed instance; the `Design:` line at
the end of every docstring names the instance it comes from.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_error, assert_instant_equals, assert_score
from test_helpers.constants import (
    AnalysisStatus,
    CompliancePosture,
    CooperationStatus,
    EscalationStatus,
    FulfillmentStatus,
    NqtlItemStatus,
    PlanYearStatus,
    ReviewOutcome,
    StringencyFinding,
    SubClassification,
    SubmissionType,
)


def _item_with_a_submitted_analysis(api):
    """One OPEN plan year, one classification and one item in ANALYSIS_SUBMITTED.

    The analysis documents 3 factors and 2 evidentiary standards and reports both
    stringency findings as COMPARABLE, so it clears the submission gate without
    any as-applied evidence existing at all.
    """
    scenario = fx.inventoried_item(api, sub_classification=SubClassification.OFFICE_VISITS)
    analysis = fx.draft_analysis(
        api,
        scenario.item_id,
        scenario.item_version,
        factor_count=3,
        evidentiary_standard_count=2,
        stringency_written_finding=StringencyFinding.COMPARABLE,
        stringency_operation_finding=StringencyFinding.COMPARABLE,
    )
    scenario.analysis = fx.submit_analysis(api, analysis["id"])
    scenario.analysis_id = analysis["id"]
    return scenario


def test_the_insufficient_reopen_cycle_returns_to_draft_and_raises_the_revision_round(
    api, officer_alt_headers
):
    """One full lap of the revision loop lands back where it started, one round on.

    The insufficient review pushes the analysis to INSUFFICIENT and drags the
    owning item back to ANALYSIS_DRAFTED; the reopen returns the analysis to
    DRAFT with `revision_round` 1; the second submit returns both rows to the
    states they held before the review, with the round still reading 1.

    PRD: "The insufficient branch moves `SUBMITTED` to `INSUFFICIENT`, imposes no
    evidence requirement at all, and moves the owning item back from
    `ANALYSIS_SUBMITTED` to `ANALYSIS_DRAFTED`, incrementing the item's `version`
    by 1, so that the author can revise."

    Design: Difficulty/non_linear_state_machine/comparative_analysis_insufficient_reopen_cycle_increments_revision_round
    """
    scenario = _item_with_a_submitted_analysis(api)

    reviewed = validate_success(
        api.review_analysis(
            scenario.analysis_id,
            f.review_payload(
                ReviewOutcome.INSUFFICIENT,
                review_note=(
                    "The written factors are recited but the in-operation stringency "
                    "comparison is absent."
                ),
            ),
            officer_alt_headers,
        )
    )
    assert reviewed["status"] == AnalysisStatus.INSUFFICIENT
    assert reviewed["revision_round"] == 0
    assert fx.read_item(api, scenario.item_id)["status"] == NqtlItemStatus.ANALYSIS_DRAFTED

    reopened = fx.reopen_analysis(api, scenario.analysis_id)
    assert reopened["status"] == AnalysisStatus.DRAFT
    assert reopened["revision_round"] == 1

    resubmitted = fx.submit_analysis(api, scenario.analysis_id)
    assert resubmitted["status"] == AnalysisStatus.SUBMITTED
    assert resubmitted["revision_round"] == 1
    assert fx.read_item(api, scenario.item_id)["status"] == NqtlItemStatus.ANALYSIS_SUBMITTED


def test_the_revision_loop_can_only_be_re_entered_through_an_insufficient_review(
    api, officer_alt_headers
):
    """A second reopen straight off SUBMITTED is refused, so the loop is not a cycle.

    Having completed one lap, the analysis sits in SUBMITTED again.  Reopening
    from there is refused, which is what makes the machine non-linear rather than
    freely cyclic: the only door back into DRAFT is an insufficient review.  The
    unresolved analysis is meanwhile not itself a compliance failure.

    PRD: "A `PlanSponsor` or an `Administrator` reopens an analysis that is in
    `INSUFFICIENT` — anything else is refused with `ERR_ANALYSIS_NOT_INSUFFICIENT`
    (HTTP 409) — which moves it back to `DRAFT` and increments both
    `revision_round` and `version` by 1."

    Design: Difficulty/non_linear_state_machine/comparative_analysis_insufficient_reopen_cycle_increments_revision_round
    """
    scenario = _item_with_a_submitted_analysis(api)
    fx.review_analysis(api, scenario.analysis_id, ReviewOutcome.INSUFFICIENT, officer_alt_headers)
    fx.reopen_analysis(api, scenario.analysis_id)
    fx.submit_analysis(api, scenario.analysis_id)

    assert_error(
        api.reopen_analysis(scenario.analysis_id, {}, scenario.sponsor_headers),
        ApiErrorId.ANALYSIS_NOT_INSUFFICIENT,
    )

    plan_year = fx.read_plan_year(api, scenario.plan_year_id)
    assert plan_year["compliance_posture"] == CompliancePosture.COMPLIANT
    assert plan_year["status"] == PlanYearStatus.OPEN


def _partially_produced_request(api):
    """A two-item production request with one validated DENIAL_RATES set against it.

    The request is issued at the clock's start value, so its contractual
    `due_at` falls 45 days later, on 2026-09-15T00:00:00.000Z.
    """
    scenario = fx.classified_plan(api, sub_classification=SubClassification.OFFICE_VISITS)
    request = fx.issue_vendor_request(
        api,
        scenario.admin_id,
        scenario.plan_year_id,
        requested_item_count=2,
        requested_submission_types=[
            SubmissionType.DENIAL_RATES,
            SubmissionType.NETWORK_COMPOSITION,
        ],
    )
    fx.produce_submission(
        api,
        request["id"],
        f.denial_rate_submission_payload(scenario.classification_id),
        scenario.admin_id,
    )
    scenario.vendor_request_id = request["id"]
    scenario.vendor_request = request
    return scenario


def test_escalating_a_partially_produced_request_leaves_the_fulfilment_dimension_alone(api):
    """The two status dimensions of a production request move independently.

    With one of two requested sets produced, fulfilment reads PARTIAL and
    escalation reads NONE.  Sending the contract notice advances escalation only,
    and the second validated set then advances fulfilment to FULFILLED without
    rewinding the notice — the combined state (FULFILLED, NOTICE_SENT) is
    reachable and is not expressible as one linear status.

    PRD: "`fulfillment_status` tracks production and advances only on validated
    submissions; `escalation_status` tracks contract enforcement and advances only
    when the sponsor escalates. Neither dimension touches the other."

    Design: Difficulty/non_linear_state_machine/vendor_request_fulfilment_and_escalation_dimensions_advance_independently
    """
    scenario = _partially_produced_request(api)

    before = fx.read_vendor_request(api, scenario.vendor_request_id)
    assert before["fulfillment_status"] == FulfillmentStatus.PARTIAL
    assert before["escalation_status"] == EscalationStatus.NONE
    assert before["validated_submission_count"] == 1
    assert_instant_equals(before["due_at"], "2026-09-15T00:00:00.000Z", "due_at")

    fx.advance_clock(api, "2026-09-16T00:00:00Z")
    escalated = fx.escalate(api, scenario.vendor_request_id)
    assert escalated["escalation_status"] == EscalationStatus.NOTICE_SENT
    assert escalated["fulfillment_status"] == FulfillmentStatus.PARTIAL
    assert escalated["is_overdue"] is True

    fx.produce_submission(
        api,
        scenario.vendor_request_id,
        f.network_composition_submission_payload(
            scenario.classification_id,
            mh_in_network_provider_pct=0.34,
            ms_in_network_provider_pct=0.62,
        ),
        scenario.admin_id,
    )

    after = fx.read_vendor_request(api, scenario.vendor_request_id)
    assert after["fulfillment_status"] == FulfillmentStatus.FULFILLED
    assert after["escalation_status"] == EscalationStatus.NOTICE_SENT
    assert after["validated_submission_count"] == 2


def test_a_fulfilled_request_under_notice_still_closes_the_administrators_obligation(api):
    """Full production clears the lateness the notice was sent about.

    The request was escalated while overdue, yet once both sets arrive it stops
    being late on the contractual basis, so the obligation counters return to
    zero and the cooperation score returns to a perfect 100.00.  A third
    escalation — the one that would declare a breach — is refused because the
    request is now fulfilled.

    PRD: "A request counts as late only while it is still live — that is, while
    its `fulfillment_status` is `OPEN` or `PARTIAL` — and only when the logical
    clock stands strictly later than the relevant deadline; a request that was
    eventually produced in full stops being late even if it was produced after its
    deadline."

    Design: Difficulty/non_linear_state_machine/vendor_request_fulfilment_and_escalation_dimensions_advance_independently
    """
    scenario = _partially_produced_request(api)
    fx.advance_clock(api, "2026-09-16T00:00:00Z")
    fx.escalate(api, scenario.vendor_request_id)
    fx.produce_submission(
        api,
        scenario.vendor_request_id,
        f.network_composition_submission_payload(
            scenario.classification_id,
            mh_in_network_provider_pct=0.34,
            ms_in_network_provider_pct=0.62,
        ),
        scenario.admin_id,
    )

    admin = fx.read_administrator(api, scenario.admin_id)
    assert admin["outstanding_request_count"] == 0
    assert admin["late_request_count"] == 0
    assert admin["breach_count"] == 0
    assert_score(admin["cooperation_score"], 100.00, "cooperation_score")
    assert admin["cooperation_status"] == CooperationStatus.COOPERATIVE

    assert_error(
        api.escalate_vendor_request(scenario.vendor_request_id, {}, scenario.sponsor_headers),
        ApiErrorId.REQUEST_ALREADY_FULFILLED,
    )
