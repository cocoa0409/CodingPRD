"""Interval endpoints and pinned precision at their boundaries.

Each test below translates exactly one designed instance; the `Design:` line at
the end of every docstring names the instance it comes from.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_cents,
    assert_error,
    assert_instant_equals,
    assert_is_none,
    assert_ratio,
    assert_score,
)
from test_helpers.constants import (
    CooperationStatus,
    EscalationStatus,
    FulfillmentStatus,
    LimitationType,
    NetworkTier,
    ParityResult,
    RejectionReason,
    SubClassification,
    SubmissionStatus,
    SubmissionType,
    TestBasis,
)


def _two_baselines_astride_the_two_thirds_boundary(api):
    """Two classifications whose medical/surgical baselines differ by one cent.

    The IN_NETWORK slice carries 2,000,000 subject cents out of 3,000,000, which
    is exactly two thirds.  The OUT_OF_NETWORK slice carries the same subject
    weight out of 3,000,001, one cent past the boundary.  The two rows differ in
    `network_tier`, so the measurement-period rule never compares them.
    """
    scenario = fx.registered_plan(api)
    at_boundary = fx.create_classification(
        api,
        scenario.plan_year_id,
        network_tier=NetworkTier.IN_NETWORK,
        sub_classification=SubClassification.OFFICE_VISITS,
    )
    past_boundary = fx.create_classification(
        api,
        scenario.plan_year_id,
        network_tier=NetworkTier.OUT_OF_NETWORK,
        sub_classification=SubClassification.OFFICE_VISITS,
    )
    fx.add_limitations(
        api,
        at_boundary["id"],
        [
            f.ms_limitation(20, 2000000, 400),
            f.ms_limitation(0, 1000000, 200),
            f.mh_limitation(20, 900000, 120),
        ],
    )
    fx.add_limitations(
        api,
        past_boundary["id"],
        [
            f.ms_limitation(20, 2000000, 400),
            f.ms_limitation(0, 1000001, 200),
            f.mh_limitation(20, 900000, 120),
        ],
    )
    scenario.at_boundary_id = at_boundary["id"]
    scenario.past_boundary_id = past_boundary["id"]
    return scenario


def test_a_subject_weight_at_exactly_two_thirds_satisfies_the_substantially_all_standard(
    api, officer_headers
):
    """The two-thirds endpoint is inclusive, so the boundary case passes.

    2,000,000 subject cents against 3,000,000 total cents cross-multiplies to
    6,000,000 against 6,000,000, which satisfies the standard; the predominant
    step then runs and the MH level of 20 matches the predominant level of 20.

    PRD: "That comparison is made by integer cross-multiplication and never by
    division: `substantially_all_met` is true exactly when the subject weight
    multiplied by 3 is greater than or equal to the total weight multiplied by 2."

    Design: Difficulty/boundary_precision_check/substantially_all_ratio_exactly_two_thirds_versus_one_cent_below
    """
    scenario = _two_baselines_astride_the_two_thirds_boundary(api)

    test = validate_success(
        api.create_parity_test(
            scenario.at_boundary_id,
            f.parity_test_payload(LimitationType.COPAY, TestBasis.PLAN_PAYMENTS),
            officer_headers,
        ),
        201,
    )

    assert_cents(test["total_ms_payments_cents"], 3000000, "total_ms_payments_cents")
    assert_cents(test["subject_payments_cents"], 2000000, "subject_payments_cents")
    assert_ratio(test["substantially_all_ratio"], 0.666667, 6, "substantially_all_ratio")
    assert test["substantially_all_met"] is True
    assert test["predominant_level"] == 20
    assert test["mh_level_value"] == 20
    assert test["result"] == ParityResult.PASS


def test_one_extra_cent_in_the_denominator_flips_the_standard_the_display_ratio_hides(
    api, officer_headers
):
    """A denominator one cent larger fails the standard while the ratio barely moves.

    The six-place ratio slips only from 0.666667 to 0.666666, but the exact
    comparison of 6,000,000 against 6,000,002 fails, so the predominant step is
    skipped entirely and the verdict is NOT_APPLICABLE rather than a failure.

    PRD: "The rounded ratio must never be used for the threshold decision — a
    ratio that rounds up to 0.666667 can still fail the two-thirds standard, and
    only the cross-multiplication gets the boundary right."

    Design: Difficulty/boundary_precision_check/substantially_all_ratio_exactly_two_thirds_versus_one_cent_below
    """
    scenario = _two_baselines_astride_the_two_thirds_boundary(api)

    test = validate_success(
        api.create_parity_test(
            scenario.past_boundary_id,
            f.parity_test_payload(LimitationType.COPAY, TestBasis.PLAN_PAYMENTS),
            officer_headers,
        ),
        201,
    )

    assert_cents(test["total_ms_payments_cents"], 3000001, "total_ms_payments_cents")
    assert_cents(test["subject_payments_cents"], 2000000, "subject_payments_cents")
    assert_ratio(test["substantially_all_ratio"], 0.666666, 6, "substantially_all_ratio")
    assert test["substantially_all_met"] is False
    assert_is_none(test["predominant_level"], "predominant_level")
    assert test["result"] == ParityResult.NOT_APPLICABLE

    assert fx.read_plan_year(api, scenario.plan_year_id)["failing_parity_test_count"] == 0


AT_THRESHOLD = {"mh_denials": 200, "mh_adjudicated_claims": 1000, "ms_denials": 100, "ms_adjudicated_claims": 1000}
JUST_BELOW_THRESHOLD = {
    "mh_denials": 1999,
    "mh_adjudicated_claims": 10000,
    "ms_denials": 1000,
    "ms_adjudicated_claims": 10000,
}


def _request_for_two_denial_rate_sets(api):
    """A production request that expects two denial-rate sets against one classification.

    Both sets validate, so the pair can be produced against the same request and
    the second one closes it out.
    """
    scenario = fx.classified_plan(api, sub_classification=SubClassification.OFFICE_VISITS)
    request = fx.issue_vendor_request(
        api,
        scenario.admin_id,
        scenario.plan_year_id,
        requested_item_count=2,
        requested_submission_types=[SubmissionType.DENIAL_RATES],
    )
    scenario.vendor_request_id = request["id"]
    return scenario


def test_a_disparity_ratio_of_exactly_two_raises_the_as_applied_flag(api):
    """The as-applied threshold is inclusive at its endpoint.

    200 denials in 1,000 claims against 100 in 1,000 divides out to exactly
    2.0000, and the flag is raised rather than withheld.

    PRD: "`as_applied_flag` is then true exactly when `disparity_ratio` is not null
    and stands at or above 2.0: the same counters at 137 out of 1,919 against 71
    out of 1,913 give 1.9235 and a false flag, 200 out of 1,000 against 100 out of
    1,000 give exactly 2.0000 and a true flag because the threshold is inclusive,
    and 1,999 out of 10,000 against 1,000 out of 10,000 give 1.9990 and a false
    flag."

    Design: Difficulty/boundary_precision_check/disparity_ratio_exactly_at_threshold_versus_one_ten_thousandth_below
    """
    scenario = _request_for_two_denial_rate_sets(api)

    submission = fx.produce_submission(
        api,
        scenario.vendor_request_id,
        f.denial_rate_submission_payload(scenario.classification_id, **AT_THRESHOLD),
        scenario.admin_id,
    )

    assert submission["status"] == SubmissionStatus.VALIDATED
    assert submission["rejection_reason"] == RejectionReason.NONE
    assert_ratio(submission["mh_denial_rate"], 0.200000, 6, "mh_denial_rate")
    assert_ratio(submission["ms_denial_rate"], 0.100000, 6, "ms_denial_rate")
    assert_ratio(submission["disparity_ratio"], 2.0000, 4, "disparity_ratio")
    assert submission["as_applied_flag"] is True


def test_a_disparity_one_ten_thousandth_below_two_leaves_the_flag_down(api):
    """One ten-thousandth short of the threshold is short of it.

    1,999 in 10,000 against 1,000 in 10,000 publishes 1.9990 — the nearest value
    below the endpoint at the pinned four-place precision — and the flag stays
    down even though the six-place MH rate reads 0.199900.  Both sets validate, so
    the second one also brings the request to FULFILLED.

    PRD: "The rounding order is pinned and consequential: the ratio is taken from
    the two **unrounded** quotients and rounded exactly once, at the end, to four
    places."

    Design: Difficulty/boundary_precision_check/disparity_ratio_exactly_at_threshold_versus_one_ten_thousandth_below
    """
    scenario = _request_for_two_denial_rate_sets(api)
    fx.produce_submission(
        api,
        scenario.vendor_request_id,
        f.denial_rate_submission_payload(scenario.classification_id, **AT_THRESHOLD),
        scenario.admin_id,
    )

    submission = fx.produce_submission(
        api,
        scenario.vendor_request_id,
        f.denial_rate_submission_payload(scenario.classification_id, **JUST_BELOW_THRESHOLD),
        scenario.admin_id,
    )

    assert submission["status"] == SubmissionStatus.VALIDATED
    assert submission["rejection_reason"] == RejectionReason.NONE
    assert_ratio(submission["mh_denial_rate"], 0.199900, 6, "mh_denial_rate")
    assert_ratio(submission["ms_denial_rate"], 0.100000, 6, "ms_denial_rate")
    assert_ratio(submission["disparity_ratio"], 1.9990, 4, "disparity_ratio")
    assert submission["as_applied_flag"] is False

    request = fx.read_vendor_request(api, scenario.vendor_request_id)
    assert request["validated_submission_count"] == 2
    assert request["fulfillment_status"] == FulfillmentStatus.FULFILLED


def _request_with_a_deadline_to_stand_on(api):
    """One production request issued at the clock's start value.

    The administrator keeps the default 45 contractual days, so `due_at` lands on
    2026-09-15T00:00:00.000Z and the regulatory deadline, fixed at 30 days, lands
    on 2026-08-31T00:00:00.000Z.
    """
    scenario = fx.registered_plan(api)
    request = fx.issue_vendor_request(api, scenario.admin_id, scenario.plan_year_id)
    scenario.vendor_request_id = request["id"]
    scenario.vendor_request = request
    return scenario


def test_a_clock_standing_exactly_on_the_deadline_is_not_yet_overdue(api):
    """The lateness comparison is strict, so the deadline instant itself is timely.

    The clock is moved to precisely `due_at`.  The notice rung is refused, the
    derived overdue flag is still false and the enforcement dimension has not
    moved.

    PRD: "Strictness applies on both rungs — a clock standing exactly at `due_at`,
    or exactly at the end of the grace period, is not yet overdue — and a premature
    escalation is refused with `ERR_NOT_YET_OVERDUE` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/escalation_ripeness_at_exactly_due_at_versus_one_second_later
    """
    scenario = _request_with_a_deadline_to_stand_on(api)
    assert_instant_equals(scenario.vendor_request["issued_at"], "2026-08-01T00:00:00.000Z", "issued_at")
    assert_instant_equals(scenario.vendor_request["due_at"], "2026-09-15T00:00:00.000Z", "due_at")
    assert_instant_equals(
        scenario.vendor_request["regulatory_due_at"], "2026-08-31T00:00:00.000Z", "regulatory_due_at"
    )

    fx.advance_clock(api, "2026-09-15T00:00:00Z")

    assert_error(
        api.escalate_vendor_request(scenario.vendor_request_id, {}, scenario.sponsor_headers),
        ApiErrorId.NOT_YET_OVERDUE,
    )

    request = fx.read_vendor_request(api, scenario.vendor_request_id)
    assert request["is_overdue"] is False
    assert request["escalation_status"] == EscalationStatus.NONE


def test_one_second_past_the_deadline_ripens_the_notice_but_not_the_breach(api):
    """A single second carries the notice rung and leaves the breach rung green.

    At `due_at` plus one second the request is overdue, so the notice is sent and
    the administrator books its first late request, dropping both cooperation
    scores to 85.00.  The breach rung, which is measured from a seven-day grace
    period rather than from `due_at`, is refused at that same instant.

    PRD: "The second rung moves `NOTICE_SENT` to `BREACH_DECLARED` and requires the
    clock to stand strictly later than `due_at` advanced by a grace period of seven
    calendar days."

    Design: Difficulty/boundary_precision_check/escalation_ripeness_at_exactly_due_at_versus_one_second_later
    """
    scenario = _request_with_a_deadline_to_stand_on(api)
    fx.advance_clock(api, "2026-09-15T00:00:01Z")

    escalated = validate_success(
        api.escalate_vendor_request(scenario.vendor_request_id, {}, scenario.sponsor_headers)
    )
    assert escalated["escalation_status"] == EscalationStatus.NOTICE_SENT
    assert escalated["is_overdue"] is True

    admin = fx.read_administrator(api, scenario.admin_id)
    assert admin["late_request_count"] == 1
    assert_score(admin["cooperation_score"], 85.00, "cooperation_score")
    assert_score(
        admin["regulatory_basis_cooperation_score"], 85.00, "regulatory_basis_cooperation_score"
    )
    assert admin["cooperation_status"] == CooperationStatus.COOPERATIVE

    assert_error(
        api.escalate_vendor_request(scenario.vendor_request_id, {}, scenario.sponsor_headers),
        ApiErrorId.NOT_YET_OVERDUE,
    )
