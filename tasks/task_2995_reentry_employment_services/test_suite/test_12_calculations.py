"""
Derived numbers: where the rounding point sits, which rows feed a sum, and which
order the inputs are consumed in.

Every figure asserted here is worked from the PRD's own arithmetic, and each test
is chosen at a point where a plausible shortcut — normalising too early, rounding
per segment, reading a tier off the wrong figure, walking rows in creation order —
produces a visibly different number.
"""

from test_helpers.assertions import (
    assert_int_field,
    assert_ledger_identity,
    assert_match_breakdown,
    assert_money_cents,
    assert_one_decimal_place,
    assert_array_equals,
    validate_paginated,
    validate_unpaginated,
)
from test_helpers.constants import (
    BARRIER_TIER_HIGH,
    CATEGORY_TRANSIT_PASS,
    COMPLIANCE_OUT_OF_COMPLIANCE,
    CONFLICT_WORK_AUTHORIZATION_SUSPENDED,
    DOC_BIRTH_CERTIFICATE,
    DOC_SSN_CARD,
    DOC_STATE_ID,
    FUNDING_POSTURE_OPEN,
    POSTURE_FROZEN,
    POSTURE_RESTRICTED,
    RECORD_DRUG_OFFENSE,
    REQUEST_DEFERRED,
    REQUEST_SUBMITTED,
    SHIFT_CANCELLED,
    SHIFT_CONFLICTED,
    SHIFT_SCHEDULED,
    STAGE_PRE_RELEASE,
    SUSPENSION_LIFTED,
    SUSPENSION_NONE,
    SUSPENSION_SUSPENDED,
    WORK_AUTH_SUSPENDED,
)
from test_helpers import factories as f
from test_helpers.test_users import (
    CASE_MANAGER,
    FUNDER_ANALYST,
    PROGRAM_DIRECTOR,
    SUPERVISION_OFFICER,
)

SUSPENSION_REASON = "Missed two supervision appointments"


def _subsidised_placement(api, build, authorized_cents=30000):
    """An active, subsidised placement whose participant may legally work 08:00-17:00."""
    grant = build.grant(
        authorized_cents=authorized_cents, per_participant_cap_cents=60000,
        retention_benchmark_pct=75.0,
    )
    partnership = build.partnership_active()
    opening = build.job_opening(partnership["id"], openings_count=2)
    participant = build.participant_released()
    case = build.case_authorized(participant["id"], 480, 1020)
    placement = build.placement_active(participant["id"], opening["id"], grant["id"])
    return grant, participant, case, placement


def test_the_barrier_score_normalises_once_after_the_weighted_sum(api, build):
    """
    The five weights are applied to the raw domain scores and only the weighted sum
    is divided by four and scaled to a hundred, so 2.65 becomes 66.25 and rounds up
    to 66.3.

    PRD section 3.1: "The weights add to exactly 1.00, so no drift is tolerated: a
    participant scoring housing 3, transportation 2, health 1, work history 4, and
    documentation 2 yields a weighted raw figure of 2.65, which normalises to 66.25
    and rounds to a `barrier_score` of 66.3."

    PRD section 3.1: "The normalisation by 4 and by 100 happens once, after the
    weighted sum, and never domain by domain — normalising per domain and then summing
    rounds differently and is wrong."

    Design: Corner/calculations/barrier_score_normalises_after_the_weighted_sum
    """
    participant = build.participant()

    scored = validate_unpaginated(
        api.record_assessment(participant["id"], f.assessment_payload(), CASE_MANAGER)
    )
    assert_one_decimal_place(scored, "barrier_score", 66.3)
    assert scored["barrier_tier"] == BARRIER_TIER_HIGH
    assert scored["assessment_domain_scores"] == {
        "housing_score": 3,
        "transportation_score": 2,
        "health_score": 1,
        "work_history_score": 4,
        "documentation_score": 2,
    }
    assert scored["stage"] == STAGE_PRE_RELEASE
    assert_one_decimal_place(scored, "doc_completeness_pct", 0.0)

    rows, meta = validate_paginated(
        api.list_participants(CASE_MANAGER, f.page_params(barrier_tier=BARRIER_TIER_HIGH))
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == participant["id"]


def test_cancelling_a_shift_drops_it_out_of_the_projected_sum_but_not_the_collection(
    api, build
):
    """
    The projected variant reads only scheduled and worked rows, so cancelling the
    middle four-hour shift takes the projection from 11,100 to exactly 7,400 while
    the cancelled row stays in the collection.

    PRD section 3.7: "The **projected** variant, stored in
    `projected_subsidy_cents`, reads the placement's shifts whose `status` is
    `SCHEDULED` or `WORKED`; this is the figure the grant's `committed_cents` holds
    while the placement is active."

    PRD section 3.7: "Shifts that are `CONFLICTED` or `CANCELLED` are excluded from
    both variants."

    Design: Corner/calculations/projected_subsidy_drops_cancelled_shifts_from_the_input_set
    """
    grant, participant, case, placement = _subsidised_placement(api, build)
    first = build.work_shift(
        placement["id"], "2026-08-03T09:00:00.000Z", "2026-08-03T13:00:00.000Z"
    )
    middle = build.work_shift(
        placement["id"], "2026-08-04T09:00:00.000Z", "2026-08-04T13:00:00.000Z"
    )
    last = build.work_shift(
        placement["id"], "2026-08-05T09:00:00.000Z", "2026-08-05T13:00:00.000Z"
    )
    for shift in (first, middle, last):
        assert shift["scheduled_hours"] == 4.0

    cancelled = validate_unpaginated(
        api.set_work_shift_status(
            middle["id"], f.shift_status_payload(SHIFT_CANCELLED), CASE_MANAGER
        )
    )
    assert cancelled["status"] == SHIFT_CANCELLED

    stored = validate_unpaginated(api.get_placement(placement["id"], CASE_MANAGER))
    assert_money_cents(stored, "projected_subsidy_cents", 7400)
    assert_money_cents(stored, "actual_subsidy_cents", 0)

    all_rows, all_meta = validate_paginated(
        api.list_placement_work_shifts(placement["id"], CASE_MANAGER)
    )
    assert all_meta["total_count"] == 3

    live_rows, live_meta = validate_paginated(
        api.list_placement_work_shifts(
            placement["id"], CASE_MANAGER, f.page_params(status=SHIFT_SCHEDULED)
        )
    )
    assert live_meta["total_count"] == 2
    assert {row["id"] for row in live_rows} == {first["id"], last["id"]}

    ledger = validate_unpaginated(api.get_grant_ledger(grant["id"], FUNDER_ANALYST))
    assert_money_cents(ledger, "committed_cents", 7400)
    assert_money_cents(ledger, "available_cents", 22600)
    assert_ledger_identity(ledger)


def test_a_shift_straddling_eighty_hours_is_rounded_once_after_its_segments(api, build):
    """
    The tenth shift spans the first tier boundary: eight hours at half rate and one
    at quarter rate sum to 7,862.5 cents, and the single half-up rounding of that sum
    is 7,863.

    PRD section 3.7: "A shift whose hours straddle a boundary is split across the
    segments it spans and each segment is priced at its own rate. Each segment
    contributes its hours multiplied by the opening's `hourly_wage_cents` multiplied by
    that segment's rate; the segments of one shift are summed and only then rounded
    half up to whole cents, producing that shift's amount."

    Nine eight-hour shifts at 1850 cents an hour sit wholly in the fifty-percent tier
    for 66,600 cents, and the straddling tenth adds 7,863 for a total of 74,463.

    Design: Corner/calculations/subsidy_ladder_straddle_rounds_once_per_shift
    """
    grant, participant, case, placement = _subsidised_placement(
        api, build, authorized_cents=5000000
    )
    for day in range(3, 12):
        shift = build.work_shift(
            placement["id"],
            f"2026-08-{day:02d}T09:00:00.000Z",
            f"2026-08-{day:02d}T17:00:00.000Z",
        )
        assert shift["scheduled_hours"] == 8.0

    before = validate_unpaginated(api.get_placement(placement["id"], CASE_MANAGER))
    assert_money_cents(before, "projected_subsidy_cents", 66600)

    straddling = validate_unpaginated(
        api.create_work_shift(
            placement["id"],
            f.work_shift_payload("2026-08-12T08:00:00.000Z", "2026-08-12T17:00:00.000Z"),
            CASE_MANAGER,
        ),
        201,
    )
    assert straddling["scheduled_hours"] == 9.0

    after = validate_unpaginated(api.get_placement(placement["id"], CASE_MANAGER))
    assert_money_cents(after, "projected_subsidy_cents", 74463)
    assert_money_cents(after, "actual_subsidy_cents", 0)

    ledger = validate_unpaginated(api.get_grant_ledger(grant["id"], FUNDER_ANALYST))
    assert_money_cents(ledger, "committed_cents", 74463)
    assert_money_cents(ledger, "available_cents", 4925537)
    assert ledger["funding_posture"] == FUNDING_POSTURE_OPEN
    assert_ledger_identity(ledger)


def test_the_lowest_admin_fee_tier_includes_its_own_five_thousand_cent_ceiling(
    api, build
):
    """
    A 5,000-cent request pays nothing and a 5,001-cent request pays 150, so the
    boundary is inclusive on the low side and the fee is read from the request rather
    than from the total.

    PRD section 3.8: "The administrative fee is then tiered off `requested_cents`
    alone and never off the total. When `requested_cents` is at most 5,000, the fee
    rate is 0.00; when `requested_cents` is strictly greater than 5,000 and at most
    20,000, the rate is 0.03; when `requested_cents` is strictly greater than 20,000,
    the rate is 0.05."

    PRD section 3.8: "A `requested_cents` of 5,000 selects the lowest tier for a fee
    of 0 and a total of 5,000; 5,001 selects the middle tier for a fee of 150 and a
    total of 5,151"

    Design: Corner/calculations/admin_fee_tier_one_ceiling_is_inclusive_at_five_thousand_cents
    """
    grant = build.grant(authorized_cents=100000, per_participant_cap_cents=60000)
    participant = build.participant_zero_barrier_draft(
        record_categories=[RECORD_DRUG_OFFENSE]
    )

    on_the_ceiling = build.support_request(
        participant["id"],
        grant["id"],
        [f.line_item("Monthly bus pass", 5000)],
        category=CATEGORY_TRANSIT_PASS,
        justification="Commute to Northgate Logistics",
    )
    assert_money_cents(on_the_ceiling, "requested_cents", 5000)
    assert_money_cents(on_the_ceiling, "admin_fee_cents", 0)
    assert_money_cents(on_the_ceiling, "total_charge_cents", 5000)

    one_cent_past = build.support_request(
        participant["id"],
        grant["id"],
        [f.line_item("Monthly bus pass plus one day", 5001)],
        category=CATEGORY_TRANSIT_PASS,
        justification="Commute plus one day extension",
    )
    assert_money_cents(one_cent_past, "requested_cents", 5001)
    assert_money_cents(one_cent_past, "admin_fee_cents", 150)
    assert_money_cents(one_cent_past, "total_charge_cents", 5151)

    for request in (on_the_ceiling, one_cent_past):
        assert request["status"] == REQUEST_SUBMITTED

    ledger = validate_unpaginated(api.get_grant_ledger(grant["id"], FUNDER_ANALYST))
    assert_money_cents(ledger, "committed_cents", 0)
    assert_money_cents(ledger, "available_cents", 100000)
    assert_int_field(ledger, "open_request_count", 2)
    assert_ledger_identity(ledger)


def _grant_with_two_deferred_requests(api, build):
    """
    A grant holding one approved request and a two-row deferral queue whose head is
    larger than the tail.
    """
    grant, participant, case, placement = _subsidised_placement(api, build)
    first_shift = build.work_shift(
        placement["id"], "2026-08-03T09:00:00.000Z", "2026-08-03T13:00:00.000Z"
    )
    build.work_shift(
        placement["id"], "2026-08-04T09:00:00.000Z", "2026-08-04T13:00:00.000Z"
    )
    build.work_shift(
        placement["id"], "2026-08-05T09:00:00.000Z", "2026-08-05T13:00:00.000Z"
    )

    approved = build.support_request_approved(
        participant["id"],
        grant["id"],
        [f.line_item("Six-month transit pass", 17000)],
        category=CATEGORY_TRANSIT_PASS,
        justification="Commute for the full subsidised placement",
    )
    assert_money_cents(approved, "total_charge_cents", 17510)

    other = build.participant_zero_barrier_draft(
        full_name="Dana Whitfield", record_categories=[RECORD_DRUG_OFFENSE]
    )
    head = build.support_request_approved(
        other["id"],
        grant["id"],
        [f.line_item("Monthly bus pass", 8000)],
        category=CATEGORY_TRANSIT_PASS,
        justification="Commute to interview cycle",
    )
    tail = build.support_request_approved(
        other["id"],
        grant["id"],
        [f.line_item("Single-ride tickets", 2000)],
        category=CATEGORY_TRANSIT_PASS,
        justification="Two weeks of interviews",
    )
    assert_money_cents(head, "total_charge_cents", 8240)
    assert_money_cents(tail, "total_charge_cents", 2000)
    for deferred in (head, tail):
        assert deferred["status"] == REQUEST_DEFERRED
    return grant, placement, first_shift, head, tail


def test_a_release_that_covers_only_the_second_deferred_request_promotes_nothing(
    api, build
):
    """
    Cancelling a shift frees 3,700 cents into a balance of 1,390, which covers the
    2,000-cent tail but not the 8,240-cent head — so the waterfall promotes nothing at
    all rather than reaching past the head.

    PRD section 3.8: "Look only at the head of that queue. If a head exists and its
    `total_charge_cents` is at most the grant's `available_cents`, promote that head
    from `DEFERRED` to `APPROVED`, stamp `promoted_at` from the logical clock, and add
    its `total_charge_cents` to `committed_cents`, then recompute the ledger and
    `funding_posture`. Otherwise promote nothing."

    PRD section 3.8: "It runs after any write that raises a grant's `available_cents`
    — a voided settlement, a work-shift cancellation, a placement separation, or a
    participant exit that voids approved requests."

    Design: Corner/calculations/deferred_promotion_never_skips_the_queue_head
    """
    grant, placement, first_shift, head, tail = _grant_with_two_deferred_requests(
        api, build
    )

    cancelled = validate_unpaginated(
        api.set_work_shift_status(
            first_shift["id"], f.shift_status_payload(SHIFT_CANCELLED), CASE_MANAGER
        )
    )
    assert cancelled["status"] == SHIFT_CANCELLED

    stored = validate_unpaginated(api.get_placement(placement["id"], CASE_MANAGER))
    assert_money_cents(stored, "projected_subsidy_cents", 7400)

    ledger = validate_unpaginated(api.get_grant_ledger(grant["id"], FUNDER_ANALYST))
    assert_money_cents(ledger, "committed_cents", 24910)
    assert_money_cents(ledger, "disbursed_cents", 0)
    assert_money_cents(ledger, "available_cents", 5090)
    assert ledger["funding_posture"] == FUNDING_POSTURE_OPEN
    assert_int_field(ledger, "deferred_request_count", 2)
    assert_int_field(ledger, "open_request_count", 2)
    assert_ledger_identity(ledger)

    for request_id in (head["id"], tail["id"]):
        still_queued = validate_unpaginated(
            api.get_support_request(request_id, PROGRAM_DIRECTOR)
        )
        assert still_queued["status"] == REQUEST_DEFERRED
        assert still_queued["promoted_at"] is None


def test_a_suspension_outranks_the_restriction_a_conflicted_shift_imposes(api, build):
    """
    The posture ladder is evaluated top down, so a suspension shows `FROZEN` over an
    already-conflicted shift, and lifting it falls back to `RESTRICTED` rather than to
    `OPEN` because the conflicted shift is still there.

    PRD section 3.2: "It is evaluated strictly in this order, so the first matching
    condition wins: the posture is `FROZEN` when `suspension_status` is `SUSPENDED` or
    `stage` is `EXITED`; otherwise it is `RESTRICTED` when any placement of this
    participant has `schedule_compliance` of `OUT_OF_COMPLIANCE`, or when
    `license_relief_status` is `PETITION_DENIED`; otherwise it is `OPEN`."

    PRD section 3.9: "Driving `to_status` to `LIFTED` requires that
    `suspension_status` is currently `SUSPENDED`; it clears `suspension_reason` back
    to null and recomputes `engagement_posture` to `OPEN` or `RESTRICTED`."

    Design: Corner/calculations/frozen_engagement_posture_outranks_restricted
    """
    grant, participant, case, placement = _subsidised_placement(api, build)
    shift = build.work_shift(
        placement["id"], "2026-08-03T09:00:00.000Z", "2026-08-03T17:00:00.000Z"
    )
    validate_unpaginated(
        api.decide_work_authorization(
            case["id"], f.work_authorization_payload(WORK_AUTH_SUSPENDED), SUPERVISION_OFFICER
        )
    )

    suspended = validate_unpaginated(
        api.set_suspension(
            participant["id"],
            f.suspension_payload(SUSPENSION_SUSPENDED, SUSPENSION_REASON),
            PROGRAM_DIRECTOR,
        )
    )
    assert suspended["suspension_status"] == SUSPENSION_SUSPENDED
    assert suspended["engagement_posture"] == POSTURE_FROZEN

    lifted = validate_unpaginated(
        api.set_suspension(
            participant["id"], f.suspension_payload(SUSPENSION_LIFTED), PROGRAM_DIRECTOR
        )
    )
    assert lifted["suspension_status"] == SUSPENSION_NONE
    assert lifted["suspension_reason"] is None
    assert lifted["engagement_posture"] == POSTURE_RESTRICTED

    stored_shift = validate_unpaginated(api.get_work_shift(shift["id"], CASE_MANAGER))
    assert stored_shift["status"] == SHIFT_CONFLICTED
    assert stored_shift["conflict_reason"] == CONFLICT_WORK_AUTHORIZATION_SUSPENDED

    stored_placement = validate_unpaginated(api.get_placement(placement["id"], CASE_MANAGER))
    assert stored_placement["schedule_compliance"] == COMPLIANCE_OUT_OF_COMPLIANCE
    assert_money_cents(stored_placement, "projected_subsidy_cents", 0)

    rows, meta = validate_paginated(
        api.list_participants(CASE_MANAGER, f.page_params(engagement_posture=POSTURE_RESTRICTED))
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == participant["id"]


def test_two_of_three_documents_is_stored_as_sixty_six_point_seven(api, build):
    """
    Two thirds is 66.666..., and the half-up rounding to a single decimal stores
    66.7 — still short of the 80.0 readiness threshold.

    PRD section 3.1: "`doc_completeness_pct` is then recomputed as one hundred times
    the count of document types that appear in both `verified_document_types` and
    `required_document_types`, divided by the count of `required_document_types`,
    rounded half up to one decimal place."

    PRD section 3.1: "Five required types with four verified therefore stand at
    exactly 80.0, three of five at 60.0, and two of three at 66.7."

    Design: Corner/calculations/doc_completeness_rounds_to_one_decimal
    """
    participant = build.participant(
        required_document_types=[DOC_STATE_ID, DOC_SSN_CARD, DOC_BIRTH_CERTIFICATE]
    )
    validate_unpaginated(
        api.record_assessment(participant["id"], f.assessment_payload(), CASE_MANAGER)
    )

    validate_unpaginated(
        api.verify_document(
            participant["id"], f.document_verification_payload(DOC_STATE_ID), CASE_MANAGER
        )
    )
    second = validate_unpaginated(
        api.verify_document(
            participant["id"], f.document_verification_payload(DOC_SSN_CARD), CASE_MANAGER
        )
    )
    assert_one_decimal_place(second, "doc_completeness_pct", 66.7)
    assert_array_equals(second, "verified_document_types", [DOC_STATE_ID, DOC_SSN_CARD])
    assert second["stage"] == STAGE_PRE_RELEASE

    summary = validate_unpaginated(
        api.get_readiness_summary(participant["id"], CASE_MANAGER)
    )
    assert_int_field(summary, "required_document_count", 3)
    assert_int_field(summary, "verified_document_count", 2)
    assert_one_decimal_place(summary, "doc_completeness_pct", 66.7)
    assert summary["readiness_met"] is False


def test_a_shift_created_first_but_dated_last_is_still_charged_last(api, build):
    """
    The nine-hour shift is created before any other, when the ladder would price it
    at 8,325, but its `starts_at` is the latest of the ten — so once the earlier shifts
    exist it must be re-charged as the straddling shift and the placement must report
    74,463 rather than the creation-ordered 74,925.

    PRD section 3.7: "Within a variant, the placement's qualifying shifts are
    processed in chronological order — by `starts_at` ascending, and where two shifts
    share a `starts_at`, by `created_at` ascending."

    PRD section 3.7: "Because the ladder is cumulative per placement and walked in
    `starts_at` order, shifts created out of chronological order must still be charged
    in chronological order."

    Design: Corner/calculations/out_of_order_shift_creation_still_charges_in_starts_at_order
    """
    grant, participant, case, placement = _subsidised_placement(
        api, build, authorized_cents=5000000
    )
    late = build.work_shift(
        placement["id"], "2026-08-12T08:00:00.000Z", "2026-08-12T17:00:00.000Z"
    )
    assert late["scheduled_hours"] == 9.0

    alone = validate_unpaginated(api.get_placement(placement["id"], CASE_MANAGER))
    assert_money_cents(alone, "projected_subsidy_cents", 8325)

    for day in range(3, 11):
        build.work_shift(
            placement["id"],
            f"2026-08-{day:02d}T09:00:00.000Z",
            f"2026-08-{day:02d}T17:00:00.000Z",
        )

    ninth = validate_unpaginated(
        api.create_work_shift(
            placement["id"],
            f.work_shift_payload("2026-08-11T09:00:00.000Z", "2026-08-11T17:00:00.000Z"),
            CASE_MANAGER,
        ),
        201,
    )
    assert ninth["scheduled_hours"] == 8.0

    stored = validate_unpaginated(api.get_placement(placement["id"], CASE_MANAGER))
    assert_money_cents(stored, "projected_subsidy_cents", 74463)
    assert stored["projected_subsidy_cents"] != 74925

    stored_late = validate_unpaginated(api.get_work_shift(late["id"], CASE_MANAGER))
    assert stored_late["scheduled_hours"] == 9.0
    assert stored_late["status"] == SHIFT_SCHEDULED

    ledger = validate_unpaginated(api.get_grant_ledger(grant["id"], FUNDER_ANALYST))
    assert_money_cents(ledger, "committed_cents", 74463)
    assert_ledger_identity(ledger)


def test_a_transit_pass_plan_against_an_unreachable_opening_scores_five_for_access(
    api, build
):
    """
    The access component is a lookup on the pair, not on the plan alone: a
    `TRANSIT_PASS` plan against an opening that is not transit-accessible scores 5
    rather than 15, taking the whole preview to 65.

    PRD section 3.6: "The `access_component` translates the participant's
    release-plan `transportation_plan_type` against the opening's `transit_accessible`
    flag: 15 when the plan is `OWN_VEHICLE`; 15 when the plan is `EMPLOYER_SHUTTLE`; 15
    when the plan is `TRANSIT_PASS` and the opening's `transit_accessible` is true; 5
    when the plan is `TRANSIT_PASS` and `transit_accessible` is false; 10 when the plan
    is `RIDE_SHARE_STIPEND`; and 0 when the plan is `NONE` or has not been set at all."

    PRD section 3.6: "When `eligible` is true, `blocking_error_id` is null."

    Design: Corner/calculations/match_score_access_component_drops_to_five_without_transit_access
    """
    partnership = build.partnership_active()
    opening = build.job_opening(partnership["id"], transit_accessible=False)
    participant = build.participant_released()

    preview = validate_unpaginated(
        api.get_match_preview(
            opening["id"], CASE_MANAGER, {"participant_id": participant["id"]}
        )
    )
    assert preview["job_opening_id"] == opening["id"]
    assert preview["participant_id"] == participant["id"]
    assert_int_field(preview, "match_score", 65)
    assert_match_breakdown(preview["match_breakdown"], 28, 20, 7, 5, 0, 5)
    assert preview["eligible"] is True
    assert preview["blocking_error_id"] is None
