"""
Comparisons observed from both sides of their boundary.

Three different metrics are pinned here at the exact step where the predicate
flips: a per-participant cap at equality and one cent past it, a documentation
percentage at 60.0 and then at exactly 80.0, and a report denominator at zero,
where the rates are null rather than nought.
"""

from test_helpers.api_errors import ERR_PARTICIPANT_CAP_EXCEEDED
from test_helpers.assertions import (
    assert_int_field,
    assert_money_cents,
    assert_nullable_rate,
    assert_one_decimal_place,
    validate_error,
    validate_paginated,
    validate_unpaginated,
)
from test_helpers.constants import (
    BARRIER_TIER_HIGH,
    CATEGORY_TOOLS,
    DOC_BIRTH_CERTIFICATE,
    DOC_SSN_CARD,
    DOC_STATE_ID,
    DOC_WORK_HISTORY,
    EMPLOYMENT_OFFERED,
    POSTURE_OPEN,
    READINESS_DOC_COMPLETENESS_THRESHOLD,
    RELEASE_PLAN_APPROVED,
    REPORT_VARIANT_COHORT,
    REPORT_VARIANT_EXIT_BASED,
    REQUEST_SUBMITTED,
    STAGE_PRE_RELEASE,
    STAGE_RELEASE_READY,
)
from test_helpers import factories as f
from test_helpers.test_users import CASE_MANAGER, FUNDER_ANALYST

TOOL_CHEST = "Full mechanic tool chest"


def _cap_sized_grant_and_two_participants(api, build):
    """One grant capped at 60,000 cents and two participants with their own budgets."""
    grant = build.grant(authorized_cents=5000000, per_participant_cap_cents=60000)
    first = build.participant(full_name="Andre Colwell")
    second = build.participant(full_name="Denise Whitlock")
    return grant, first, second


def _tools_request(api, build, participant_id, grant_id, unit_cost_cents):
    payload = f.support_request_payload(
        participant_id,
        grant_id,
        build.grant_version(grant_id),
        [f.line_item(TOOL_CHEST, unit_cost_cents)],
        category=CATEGORY_TOOLS,
    )
    return api.create_support_request(payload, CASE_MANAGER)


def test_a_request_landing_exactly_on_the_per_participant_cap_is_accepted(api, build):
    """
    A 67,227-cent line at 0.85 coverage requests 57,143 cents, and the top fee
    tier lifts the total to exactly the 60,000-cent cap, which the inclusive
    boundary accepts.

    PRD section 3.8: "A `requested_cents` of 5,000 selects the lowest tier for a
    fee of 0 and a total of 5,000; 5,001 selects the middle tier for a fee of 150
    and a total of 5,151; 13,959 selects the middle tier for a fee of 419 and a
    total of 14,378; and 57,143 selects the highest tier for a fee of 2,857 and a
    total of exactly 60,000."

    Design: Difficulty/boundary_precision_check/per_participant_cap_allows_exact_equality_and_refuses_one_cent_more
    """
    grant, first, second = _cap_sized_grant_and_two_participants(api, build)

    accepted = validate_unpaginated(
        _tools_request(api, build, first["id"], grant["id"], 67227), 201
    )
    assert_money_cents(accepted, "requested_cents", 57143)
    assert_money_cents(accepted, "admin_fee_cents", 2857)
    assert_money_cents(accepted, "total_charge_cents", 60000)
    assert accepted["status"] == REQUEST_SUBMITTED

    stored_grant = validate_unpaginated(api.get_grant(grant["id"], FUNDER_ANALYST))
    assert accepted["total_charge_cents"] == stored_grant["per_participant_cap_cents"]


def test_one_cent_past_the_per_participant_cap_is_refused(api, build):
    """
    A single extra cent on the line pushes the total to 60,001 and the strictly
    greater comparison refuses it, leaving only the first request on the grant.

    PRD section 3.8: "If that sum is strictly greater than the grant's
    `per_participant_cap_cents`, the request is refused with
    `ERR_PARTICIPANT_CAP_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/per_participant_cap_allows_exact_equality_and_refuses_one_cent_more
    """
    grant, first, second = _cap_sized_grant_and_two_participants(api, build)
    accepted = validate_unpaginated(
        _tools_request(api, build, first["id"], grant["id"], 67227), 201
    )

    refused = _tools_request(api, build, second["id"], grant["id"], 67228)
    validate_error(refused, ERR_PARTICIPANT_CAP_EXCEEDED, 409)

    rows, meta = validate_paginated(
        api.list_support_requests(CASE_MANAGER, f.page_params(grant_id=grant["id"]))
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == accepted["id"]

    stored_grant = validate_unpaginated(api.get_grant(grant["id"], FUNDER_ANALYST))
    assert_int_field(stored_grant, "open_request_count", 1)
    assert_money_cents(stored_grant, "committed_cents", 0)


def _participant_three_documents_short_of_readiness(api, build):
    """Assessed, plan approved, three of five documents confirmed."""
    participant = build.participant_assessed(full_name="Andre Colwell")
    build.verify_documents(
        participant["id"], [DOC_STATE_ID, DOC_SSN_CARD, DOC_BIRTH_CERTIFICATE]
    )
    before = build.release_plan_approved(participant["id"])
    return participant, before


def test_three_of_five_documents_stands_at_sixty_and_holds_pre_release(api, build):
    """
    60.0 sits below the inclusive documentation boundary, so the participant stays
    in `PRE_RELEASE` even with every other readiness input satisfied.

    PRD section 3.1: "The documentation boundary is inclusive, so a participant
    sitting at exactly 80.0 — four of five required documents verified — does
    advance, while three of five at 60.0 does not."

    Design: Difficulty/boundary_precision_check/doc_completeness_exactly_eighty_advances_release_ready
    """
    participant, before = _participant_three_documents_short_of_readiness(api, build)

    assert_one_decimal_place(before, "doc_completeness_pct", 60.0)
    assert before["stage"] == STAGE_PRE_RELEASE
    assert before["release_plan_status"] == RELEASE_PLAN_APPROVED
    assert before["doc_completeness_pct"] < READINESS_DOC_COMPLETENESS_THRESHOLD


def test_the_fourth_document_reaches_exactly_eighty_and_advances_release_ready(
    api, build
):
    """
    The fourth of five documents lands on exactly 80.0 and the at-least predicate
    holds, so the same write that recounts the documents also advances the stage.

    PRD section 3.1: "A participant in `PRE_RELEASE` advances to `RELEASE_READY`
    when all four of these hold simultaneously: `doc_completeness_pct` is at least
    80.0, `barrier_score` is not null, `release_plan_status` is `APPROVED`, and
    `suspension_status` is `NONE`."

    Design: Difficulty/boundary_precision_check/doc_completeness_exactly_eighty_advances_release_ready
    """
    participant, before = _participant_three_documents_short_of_readiness(api, build)

    after = validate_unpaginated(
        api.verify_document(
            participant["id"], f.document_verification_payload(DOC_WORK_HISTORY), CASE_MANAGER
        )
    )
    assert_one_decimal_place(after, "doc_completeness_pct", 80.0)
    assert after["doc_completeness_pct"] == READINESS_DOC_COMPLETENESS_THRESHOLD
    assert after["stage"] == STAGE_RELEASE_READY
    assert len(after["verified_document_types"]) == 4
    assert after["release_plan_status"] == RELEASE_PLAN_APPROVED
    assert after["engagement_posture"] == POSTURE_OPEN
    assert_one_decimal_place(after, "barrier_score", 66.3)
    assert after["barrier_tier"] == BARRIER_TIER_HIGH


def _grant_whose_only_placement_is_unanswered(api, build):
    """A grant carrying one placement that never started."""
    grant = build.grant(
        authorized_cents=5000000,
        per_participant_cap_cents=60000,
        retention_benchmark_pct=50.0,
    )
    participant = build.participant_released()
    partnership = build.partnership_active()
    opening = build.job_opening(partnership["id"], openings_count=2)
    placement = build.placement_offered(participant["id"], opening["id"], grant["id"])
    return grant, placement


def test_an_empty_cohort_reports_null_rates_rather_than_zero(api, build):
    """
    An `OFFERED` placement never entered either input set, so the denominator is
    zero and both rates arrive present-and-null.

    PRD section 3.9: "`retention_rate_pct` is 100 multiplied by
    `retained_placements` divided by `denominator_placements`, rounded half up to
    one decimal place, and is exactly null — not 0.0, and not omitted from the
    body — when `denominator_placements` is 0."

    Design: Difficulty/boundary_precision_check/empty_cohort_outcome_report_returns_null_rates_not_zero
    """
    grant, placement = _grant_whose_only_placement_is_unanswered(api, build)

    report = validate_unpaginated(
        api.get_outcome_report(
            grant["id"], FUNDER_ANALYST, f.outcome_report_params(REPORT_VARIANT_COHORT)
        )
    )
    assert report["variant"] == REPORT_VARIANT_COHORT
    assert_int_field(report, "denominator_placements", 0)
    assert_int_field(report, "retained_placements", 0)
    assert_int_field(report, "participants_served", 0)
    assert_nullable_rate(report, "retention_rate_pct", None)
    assert_nullable_rate(report, "recidivism_rate_pct", None)
    assert report["benchmark_met"] is False

    unanswered = validate_unpaginated(api.get_placement(placement["id"], CASE_MANAGER))
    assert unanswered["employment_status"] == EMPLOYMENT_OFFERED


def test_the_exit_based_variant_is_equally_empty_and_fails_the_benchmark(api, build):
    """
    Narrowing to exited participants cannot rescue an empty cohort, and a null
    retention rate never meets the benchmark.

    PRD section 3.9: "`benchmark_met` is false whenever `retention_rate_pct` is
    null, and otherwise true exactly when `retention_rate_pct` is greater than or
    equal to the grant's `retention_benchmark_pct`, so landing exactly on the
    benchmark meets it."

    Design: Difficulty/boundary_precision_check/empty_cohort_outcome_report_returns_null_rates_not_zero
    """
    grant, placement = _grant_whose_only_placement_is_unanswered(api, build)

    report = validate_unpaginated(
        api.get_outcome_report(
            grant["id"], FUNDER_ANALYST, f.outcome_report_params(REPORT_VARIANT_EXIT_BASED)
        )
    )
    assert report["variant"] == REPORT_VARIANT_EXIT_BASED
    assert_int_field(report, "denominator_placements", 0)
    assert_nullable_rate(report, "retention_rate_pct", None)
    assert_nullable_rate(report, "recidivism_rate_pct", None)
    assert report["benchmark_met"] is False

    stored_grant = validate_unpaginated(api.get_grant(grant["id"], FUNDER_ANALYST))
    assert_one_decimal_place(stored_grant, "retention_benchmark_pct", 50.0)
