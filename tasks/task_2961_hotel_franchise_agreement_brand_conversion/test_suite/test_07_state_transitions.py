"""Entry states, refused repeat transitions and the terminal states."""

from test_helpers import (
    BSD_HEADERS,
    FDM_DECIDER_HEADERS,
    FDM_HEADERS,
    QA_HEADERS,
    QA_SECOND_HEADERS,
    ApiErrorId,
    assert_instant,
    assert_integer,
    assert_money,
    assert_plan_counter_partition,
    factories,
    fixtures,
    get_success_data,
    make_owner_headers,
    validate_error,
    validate_paginated_list,
)

NEARBY_UNIT = {
    "unit_name": "Solaris Lakeside",
    "market_code": "SEADT",
    "x_miles": 1.20,
    "y_miles": 1.60,
    "room_count": 100,
    "adr_amount": 310.00,
    "occupancy_pct": 72.00,
    "territory_start_date": "2016-06-01",
    "territory_end_date": "2026-09-30",
}
FAR_UNIT = {
    "unit_name": "Solaris Eastgate",
    "market_code": "SEAEA",
    "x_miles": 8.00,
    "y_miles": 0.00,
    "room_count": 140,
    "adr_amount": 205.00,
    "occupancy_pct": 66.00,
    "territory_start_date": "2015-03-01",
    "territory_end_date": "2030-03-01",
}


def test_a_filed_application_starts_submitted_with_both_review_axes_not_started(api):
    """PRD §3.3: intake stamps the primary axis SUBMITTED, revision_round zero
    and both review axes NOT_STARTED, leaves every field the reviews would
    derive null, defaults the waiver to false and raises the brand's
    open-application counter.

    Design: Corner/state_machines/application_starts_in_submitted_state_on_both_review_axes_not_started
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    brand = fixtures.create_solaris_brand(api)
    owner = fixtures.create_strong_owner(api)
    response = api.create_application(
        factories.build_harbor_point_application_payload(owner["id"], brand["id"]), FDM_HEADERS
    )
    application = get_success_data(response, 201)

    assert application["status"] == "SUBMITTED"
    assert_integer(application["revision_round"], 0, "revision_round")
    assert application["financial_review_status"] == "NOT_STARTED"
    assert application["impact_study_status"] == "NOT_STARTED"
    for field in (
        "capacity_basis",
        "capacity_score_at_review",
        "capacity_band_at_review",
        "preliminary_impact_score",
        "final_impact_score",
        "encroachment_verdict",
    ):
        assert application[field] is None, f"{field} must start null, got {application[field]!r}"
    assert_integer(application["sustained_claim_count"], 0, "sustained_claim_count")
    assert application["encroachment_waiver_granted"] is False

    read_brand = get_success_data(api.get_brand(brand["id"], BSD_HEADERS))
    assert_integer(read_brand["open_application_count"], 1, "open_application_count")


def test_starting_review_a_second_time_is_refused_on_the_stage_check(api):
    """PRD §3.3: the review may only be started from SUBMITTED, so a second
    start on an application already UNDER_REVIEW is refused with 409 and
    nothing moves - not the primary axis, not the revision counter and not the
    brand counter.

    Design: Corner/state_machines/second_start_review_returns_application_stage_invalid
    """
    world = fixtures.setup_reviewable_application(api)
    response = api.start_application_review(world["application_id"], {}, FDM_HEADERS)
    validate_error(response, ApiErrorId.APPLICATION_STAGE_INVALID)
    assert response.status_code == 409

    application = get_success_data(api.get_application(world["application_id"], FDM_HEADERS))
    assert application["status"] == "UNDER_REVIEW"
    assert_integer(application["revision_round"], 0, "revision_round")
    brand = get_success_data(api.get_brand(world["brand_id"], BSD_HEADERS))
    assert_integer(brand["open_application_count"], 1, "open_application_count")


def test_resolving_an_already_overruled_claim_a_second_time_is_refused(api):
    """PRD §3.4: a resolution requires the claim to still be FILED, so a
    SUSTAIN aimed at a claim already OVERRULED is refused with 409 - the claim
    keeps its outcome and its zero penalty, and neither the sustained-claim
    counter nor the study axis moves.

    Design: Corner/state_machines/resolve_an_already_overruled_claim_returns_claim_not_filed
    """
    world = fixtures.setup_reviewable_application(api, existing_units=[NEARBY_UNIT])
    fixtures.set_clock(api, "2026-08-05T00:00:00Z")
    fixtures.run_impact_analysis(api, world["application_id"])
    claim = fixtures.file_claim(api, world["application_id"], world["units"][0]["id"])
    fixtures.resolve_claim(api, claim["id"], "OVERRULE")

    response = api.resolve_encroachment_claim(
        claim["id"],
        factories.build_claim_resolution_payload(
            "SUSTAIN", resolution_notes="Second bite at the apple."
        ),
        BSD_HEADERS,
    )
    validate_error(response, ApiErrorId.CLAIM_NOT_FILED)
    assert response.status_code == 409

    read_claim = get_success_data(api.get_encroachment_claim(claim["id"], BSD_HEADERS))
    assert read_claim["status"] == "OVERRULED"
    assert_money(read_claim["penalty_points_applied"], 0.00, "penalty_points_applied")
    application = get_success_data(api.get_application(world["application_id"], FDM_HEADERS))
    assert_integer(application["sustained_claim_count"], 0, "sustained_claim_count")
    assert application["impact_study_status"] == "PRELIMINARY"


def test_skipping_the_provisioned_rung_of_the_systems_ladder_is_refused(api):
    """PRD §3.6: each onboarding ladder is climbed one rung at a time, so
    jumping straight to VALIDATED from NOT_STARTED is refused with 409 and all
    three axes stay exactly where they were.

    Design: Corner/state_machines/onboarding_systems_skip_rung_returns_sequence_invalid
    """
    world = fixtures.setup_executed_agreement(api)
    response = api.advance_onboarding_milestone(
        world["agreement_id"],
        factories.build_onboarding_milestone_payload("SYSTEMS", "VALIDATED"),
        FDM_HEADERS,
    )
    validate_error(response, ApiErrorId.ONBOARDING_SEQUENCE_INVALID)
    assert response.status_code == 409

    agreement = get_success_data(api.get_agreement(world["agreement_id"], FDM_HEADERS))
    assert agreement["systems_status"] == "NOT_STARTED"
    assert agreement["training_status"] == "NOT_STARTED"
    assert agreement["channel_status"] == "NOT_CONNECTED"
    assert agreement["status"] == "EXECUTED"


def test_executing_an_already_executed_license_is_refused_on_the_stage_check(api):
    """PRD §3.6: execution requires the license to be DRAFT, so a replay is
    refused with 409 before the version guard is reached and executed_at is not
    restamped; the ownership entity stays ACTIVE, as the first execution made
    it.

    Design: Corner/state_machines/execute_an_already_executed_agreement_returns_agreement_not_draft
    """
    world = fixtures.setup_executed_agreement(api)
    stale_version = fixtures.read_application_version(api, world["application_id"])

    response = api.execute_agreement(
        world["agreement_id"],
        factories.build_execute_payload(stale_version),
        FDM_HEADERS,
    )
    validate_error(response, ApiErrorId.AGREEMENT_NOT_DRAFT)
    assert response.status_code == 409

    agreement = get_success_data(api.get_agreement(world["agreement_id"], FDM_HEADERS))
    assert agreement["status"] == "EXECUTED"
    assert_instant(agreement["executed_at"], "2026-09-10T00:00:00.000Z", "executed_at")
    owner = get_success_data(api.get_owner(world["owner_id"], FDM_HEADERS))
    assert owner["status"] == "ACTIVE"


def test_second_sustained_claim_counts_without_replaying_the_knock_back_cascade(api):
    """PRD §3.4: sustaining advances the counter and applies the penalty every
    time, but the knock-back leg only fires from FINAL and the voiding leg only
    reaches agreements still in DRAFT - so a second sustain on an application
    already knocked back to PRELIMINARY leaves the derived fields null, the
    preliminary figures untouched and the already-voided license as it stands.

    Design: Corner/state_machines/second_sustained_claim_increments_the_counter_without_re_running_the_impact_cascade
    """
    world = fixtures.setup_reviewable_application(api, existing_units=[NEARBY_UNIT, FAR_UNIT])
    fixtures.set_clock(api, "2026-08-05T00:00:00Z")
    fixtures.run_financial_review(api, world["application_id"], "PORTFOLIO_ADJUSTED")
    fixtures.run_impact_analysis(api, world["application_id"])
    fixtures.finalize_impact(api, world["application_id"])
    fixtures.set_clock(api, "2026-08-10T00:00:00Z")
    fixtures.decide_application(
        api, world["application_id"], "APPROVE", encroachment_waiver_granted=True
    )
    fixtures.set_clock(api, "2026-08-12T00:00:00Z")
    agreement = fixtures.draft_agreement(api, world["application_id"], "2026-10-01")

    fixtures.set_clock(api, "2026-08-15T00:00:00Z")
    near_claim = fixtures.file_claim(api, world["application_id"], world["units"][0]["id"])
    far_claim = fixtures.file_claim(
        api, world["application_id"], world["units"][1]["id"],
        narrative="Eastgate reports group displacement to the converted property.",
    )
    fixtures.set_clock(api, "2026-08-18T00:00:00Z")
    fixtures.resolve_claim(api, near_claim["id"], "SUSTAIN")

    fixtures.set_clock(api, "2026-08-20T00:00:00Z")
    resolved = fixtures.resolve_claim(
        api, far_claim["id"], "SUSTAIN",
        resolution_notes="Eastgate group displacement accepted.",
    )
    assert resolved["status"] == "SUSTAINED"
    assert_money(resolved["penalty_points_applied"], 7.50, "penalty_points_applied")
    assert_instant(resolved["resolved_at"], "2026-08-20T00:00:00.000Z", "resolved_at")

    application = get_success_data(api.get_application(world["application_id"], FDM_HEADERS))
    assert_integer(application["sustained_claim_count"], 2, "sustained_claim_count")
    assert application["impact_study_status"] == "PRELIMINARY"
    for field in (
        "base_impact_score",
        "final_impact_score",
        "encroachment_verdict",
        "impact_unit_count_final",
    ):
        assert application[field] is None, f"{field} must stay null, got {application[field]!r}"
    assert_money(application["preliminary_impact_score"], 32.73, "preliminary_impact_score")
    assert_integer(
        application["impact_unit_count_preliminary"], 1, "impact_unit_count_preliminary"
    )
    assert application["status"] == "APPROVED"

    read_agreement = get_success_data(api.get_agreement(agreement["id"], FDM_HEADERS))
    assert read_agreement["status"] == "VOIDED"


def test_a_passed_cure_review_restores_the_channel_and_zeroes_the_failure_tally(api):
    """PRD §3.8: a cure review that passes moves the compliance axis back to
    COMPLIANT, resets consecutive_qa_failure_count to zero rather than merely
    holding it, restores a SUSPENDED channel to CONNECTED and drops the
    transfer block - while the earlier failed inspection keeps its own record.

    Design: Corner/state_machines/failed_then_passed_cure_review_restores_the_channel_and_zeroes_the_failure_count
    """
    world = fixtures.setup_open_agreement(api)

    fixtures.set_clock(api, "2026-11-15T00:00:00Z")
    first = fixtures.score_inspection(
        api, world["agreement_id"], QA_HEADERS,
        cleanliness_score=96, condition_score=94, brand_standard_score=98,
        guest_experience_score=92, critical_defect_count=0, life_safety_defect=True,
    )
    assert_money(first["total_score"], 95.50, "total_score")
    assert first["grade"] == "FAIL", "a life-safety defect forces FAIL whatever the sections say"
    assert_instant(first["cure_deadline"], "2026-12-15T00:00:00.000Z", "cure_deadline")

    fixtures.set_clock(api, "2026-12-01T00:00:00Z")
    fixtures.submit_cure(api, first["id"], world["owner_id"])
    fixtures.set_clock(api, "2026-12-05T00:00:00Z")
    fixtures.review_cure(api, first["id"], "FAIL", QA_SECOND_HEADERS)

    fixtures.set_clock(api, "2027-02-20T00:00:00Z")
    second = fixtures.score_inspection(
        api, world["agreement_id"], QA_HEADERS,
        cleanliness_score=60, condition_score=60, brand_standard_score=60,
        guest_experience_score=60, critical_defect_count=0, life_safety_defect=False,
    )
    fixtures.set_clock(api, "2027-03-01T00:00:00Z")
    fixtures.submit_cure(api, second["id"], world["owner_id"])
    fixtures.set_clock(api, "2027-03-05T00:00:00Z")
    reviewed = fixtures.review_cure(api, second["id"], "PASS", QA_SECOND_HEADERS)

    assert reviewed["status"] == "CURE_PASSED"
    assert_instant(reviewed["cure_reviewed_at"], "2027-03-05T00:00:00.000Z", "cure_reviewed_at")
    assert_money(reviewed["total_score"], 60.00, "total_score")
    assert reviewed["grade"] == "FAIL"
    assert_instant(reviewed["cure_deadline"], "2027-03-22T00:00:00.000Z", "cure_deadline")

    agreement = get_success_data(api.get_agreement(world["agreement_id"], FDM_HEADERS))
    assert agreement["compliance_status"] == "COMPLIANT"
    assert_integer(
        agreement["consecutive_qa_failure_count"], 0, "consecutive_qa_failure_count"
    )
    assert agreement["channel_status"] == "CONNECTED"
    assert agreement["transfer_consent_blocked"] is False
    assert agreement["status"] == "OPEN"

    rows, _ = validate_paginated_list(
        api.list_agreement_qa_inspections(world["agreement_id"], QA_HEADERS)
    )
    earlier = [row for row in rows if row["id"] == first["id"]][0]
    assert earlier["status"] == "CURE_FAILED", "the earlier record must not be rewritten"
    assert_money(earlier["total_score"], 95.50, "earlier total_score")
    assert earlier["grade"] == "FAIL"


def test_verifying_the_last_open_scope_line_completes_the_plan(api):
    """PRD §3.7: the plan completes when every line is VERIFIED, so verifying
    the last one moves the plan to COMPLETED with all three lines in the
    verified bucket and the other three buckets empty.  The overall deadline is
    unchanged and the license does not open of its own accord.

    Design: Corner/state_machines/plan_completes_when_its_last_unverified_item_is_verified
    """
    world = fixtures.setup_accepted_plan(api)
    order = ("LIFE_SAFETY", "GUESTROOM", "EXTERIOR")
    fixtures.set_clock(api, "2026-10-20T00:00:00Z")
    for category in order:
        fixtures.complete_item(api, world["items_by_category"][category]["id"], world["owner_id"])
    fixtures.set_clock(api, "2026-10-22T00:00:00Z")
    for category in order[:2]:
        fixtures.verify_item(api, world["items_by_category"][category]["id"], "VERIFY")

    fixtures.set_clock(api, "2026-11-22T00:00:00Z")
    item = fixtures.verify_item(
        api, world["items_by_category"]["EXTERIOR"]["id"], "VERIFY",
        verification_notes="Exterior scope verified; scope complete.",
    )
    assert item["status"] == "VERIFIED"
    assert_instant(item["verified_at"], "2026-11-22T00:00:00.000Z", "verified_at")

    plan = get_success_data(api.get_pip(world["plan_id"], BSD_HEADERS))
    assert plan["status"] == "COMPLETED"
    assert_integer(plan["items_total_count"], 3, "items_total_count")
    assert_integer(plan["items_verified_count"], 3, "items_verified_count")
    assert_integer(plan["items_pending_count"], 0, "items_pending_count")
    assert_integer(plan["items_submitted_count"], 0, "items_submitted_count")
    assert_integer(plan["items_overdue_count"], 0, "items_overdue_count")
    assert_plan_counter_partition(plan)
    assert_instant(plan["overall_deadline"], "2027-06-02T00:00:00.000Z", "overall_deadline")

    agreement = get_success_data(api.get_agreement(world["agreement_id"], FDM_HEADERS))
    assert agreement["status"] == "EXECUTED", "completing the plan must not open the hotel"


def test_late_de_identification_breaches_the_license_and_raises_the_close_out_floor(api):
    """PRD §3.9: with no revenue reported the trailing average and the
    liquidated damages are both 0.00, so the whole settlement floor is the
    breach penalty a late certification creates - certifying after the deadline
    marks the axis BREACHED at 50,000.00, and a close-out tendering exactly that
    amount closes every obligation and reaches the terminal state.

    Design: Corner/state_machines/late_de_identification_marks_the_license_breached_and_raises_the_close_out_floor
    """
    world = fixtures.setup_open_agreement(api)
    world = fixtures.setup_termination_pending_agreement(
        api, world, cause="MUTUAL", terminate_clock="2026-11-10T00:00:00Z"
    )
    agreement = world["agreement"]
    assert agreement["termination_cause"] == "MUTUAL"
    assert agreement["liquidated_damages_formula"] == "DISCOUNTED_PV"
    assert_money(agreement["trailing_avg_monthly_fee"], 0.00, "trailing_avg_monthly_fee")
    assert_integer(
        agreement["remaining_term_months_at_termination"], 239,
        "remaining_term_months_at_termination",
    )
    assert_money(agreement["liquidated_damages_amount"], 0.00, "liquidated_damages_amount")
    assert_instant(
        agreement["de_identification_deadline"], "2026-12-10T00:00:00.000Z",
        "de_identification_deadline",
    )
    assert agreement["channel_status"] == "SUSPENDED"
    assert agreement["post_termination_status"] == "OPEN"
    plan = get_success_data(api.get_pip(world["plan_id"], BSD_HEADERS))
    assert plan["status"] == "SUSPENDED"

    fixtures.set_clock(api, "2026-12-20T00:00:00Z")
    certified = fixtures.certify_de_identification(api, world)
    assert certified["de_identification_status"] == "BREACHED"
    assert_money(
        certified["de_identification_breach_penalty"], 50_000.00, "de_identification_breach_penalty"
    )
    assert set(certified["de_identification_items_completed"]) == {
        "SIGNAGE",
        "INTERIOR_BRANDING",
        "DIGITAL_LISTINGS",
        "LINENS_AND_COLLATERAL",
        "RESERVATION_CODES",
    }

    closed = get_success_data(
        api.close_out_agreement(
            world["agreement_id"], factories.build_close_out_payload(50_000.00), BSD_HEADERS
        )
    )
    assert closed["status"] == "TERMINATED"
    assert closed["de_identification_status"] == "VERIFIED"
    assert closed["post_termination_status"] == "CLOSED"
    assert_money(
        closed["liquidated_damages_paid_amount"], 50_000.00, "liquidated_damages_paid_amount"
    )
    assert_instant(closed["closed_out_at"], "2026-12-20T00:00:00.000Z", "closed_out_at")


def test_a_declined_application_needs_no_review_and_accepts_nothing_afterwards(api):
    """PRD §3.5: a decline has no preconditions beyond the stage and duties
    checks, so it lands with both review axes still NOT_STARTED and releases the
    brand counter at once.  DECLINED is terminal, and the stage check outranks
    every later gate, so a revision request, a resubmission and a drafting
    attempt are all refused with the same stage error.

    Design: Corner/state_machines/declined_application_is_terminal_and_needs_no_review_to_decline
    """
    world = fixtures.setup_reviewable_application(api)
    application_id = world["application_id"]
    fixtures.set_clock(api, "2026-08-20T00:00:00Z")
    declined = fixtures.decide_application(
        api, application_id, "DECLINE",
        decision_notes="Market does not support a second flag at this address.",
    )

    assert declined["status"] == "DECLINED"
    assert declined["decision_outcome"] == "DECLINE"
    assert declined["decision_user_id"] == "fdm-decision-02"
    assert_instant(declined["decided_at"], "2026-08-20T00:00:00.000Z", "decided_at")
    assert_integer(declined["revision_round"], 0, "revision_round")
    assert declined["financial_review_status"] == "NOT_STARTED"
    assert declined["impact_study_status"] == "NOT_STARTED"
    for field in (
        "capacity_basis",
        "capacity_score_at_review",
        "capacity_band_at_review",
        "final_impact_score",
    ):
        assert declined[field] is None, f"{field} must stay null, got {declined[field]!r}"

    brand = get_success_data(api.get_brand(world["brand_id"], BSD_HEADERS))
    assert_integer(brand["open_application_count"], 0, "open_application_count")

    refusals = (
        api.request_application_revision(
            application_id, {"revision_notes": "Reopening the declined file."}, FDM_HEADERS
        ),
        api.resubmit_application(
            application_id,
            {"revision_response": "Revised package attached."},
            make_owner_headers(world["owner_id"]),
        ),
        api.draft_agreement(
            application_id, factories.build_agreement_payload("2026-10-01"), FDM_HEADERS
        ),
    )
    for response in refusals:
        validate_error(response, ApiErrorId.APPLICATION_STAGE_INVALID)
        assert response.status_code == 409

    final = get_success_data(api.get_application(application_id, FDM_HEADERS))
    assert final["status"] == "DECLINED"
    assert final["revision_notes"] is None
    assert final["revision_response"] is None
    _, meta = validate_paginated_list(
        api.list_application_agreements(application_id, FDM_HEADERS)
    )
    assert_integer(meta["total_count"], 0, "total_count")
