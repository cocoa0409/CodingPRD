"""Parent reports, risk scoring, and the suspension / refund cascades they trigger."""
from test_helpers import (
    ApiErrorId,
    cancel_section,
    confirm_seat,
    create_learner,
    create_section,
    declare_minimum_met,
    dispose_report,
    file_report,
    get_enrollment,
    get_listing,
    get_payout,
    get_report,
    get_section,
    get_teacher,
    make_parent_headers,
    make_platform_admin_headers,
    onboard_active_teacher,
    reserve_seat,
    run_ops,
    set_clock,
    setup_listing,
    setup_refund_cascade_scenario,
    validate_error,
)


def test_reopened_report_reaches_a_new_disposition(api):
    """PRD §3.7: "`START_REVIEW` moves a report from `OPEN` to `UNDER_REVIEW`, and the same
    action may also be used to reopen a `RESOLVED` report back into `UNDER_REVIEW`, in
    which case the existing `disposition` is retained until a new one is written."
    PRD §3.7: "`UPHOLD_WARNING` lands the report in `RESOLVED` with a disposition of
    `WARNING`, and `UPHOLD_MORE_SEVERE` lands it in `CLOSED` with a disposition of
    `MORE_SEVERE`. Both upheld dispositions run the same three-hop risk cascade."

    Design: Difficulty/non_linear_state_machine/report_reopen_cycle
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher)
    report = file_report(teacher, listing, severity="LOW", category="TECHNICAL")
    assert report["severity_weight"] == 5

    dispose_report(report["id"], "START_REVIEW")
    dismissed = dispose_report(report["id"], "DISMISS")
    assert dismissed["status"] == "RESOLVED"
    assert dismissed["disposition"] == "DISMISSED"

    reopened = dispose_report(report["id"], "START_REVIEW")
    assert reopened["status"] == "UNDER_REVIEW", (
        "the report left RESOLVED and re-entered review, so the machine is cyclic"
    )

    final = dispose_report(report["id"], "UPHOLD_MORE_SEVERE")
    assert final["status"] == "CLOSED"
    assert final["disposition"] == "MORE_SEVERE"

    fresh_teacher = get_teacher(teacher["id"])
    assert fresh_teacher["upheld_report_risk_score"] == 5
    assert fresh_teacher["actionable_risk_score"] == 5


def test_reopen_retains_the_first_disposition_until_it_is_replaced(api):
    """PRD §3.7: "`START_REVIEW` moves a report from `OPEN` to `UNDER_REVIEW`, and the same
    action may also be used to reopen a `RESOLVED` report back into `UNDER_REVIEW`, in
    which case the existing `disposition` is retained until a new one is written."

    Design: Difficulty/non_linear_state_machine/report_reopen_cycle
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher)
    report = file_report(teacher, listing, severity="LOW", category="TECHNICAL")

    dispose_report(report["id"], "START_REVIEW")
    dispose_report(report["id"], "DISMISS")

    reopened = dispose_report(report["id"], "START_REVIEW")
    assert reopened["disposition"] == "DISMISSED", (
        "the earlier disposition survives the reopen until a new one is written"
    )

    upheld = dispose_report(report["id"], "UPHOLD_MORE_SEVERE")
    assert upheld["disposition"] == "MORE_SEVERE", "the second round replaces the disposition"
    assert upheld["status"] == "CLOSED"
    assert upheld["is_terminal"] is True

    fresh = get_report(report["id"])
    assert fresh["status"] == "CLOSED"
    assert fresh["disposition"] == "MORE_SEVERE"

    teacher_after = get_teacher(teacher["id"])
    assert teacher_after["actionable_risk_score"] == 5
    assert teacher_after["status"] == "ACTIVE", "a score of 5 stays below the suspension threshold"


def test_section_cancellation_claws_back_the_payout_and_restores_the_tax_status(api):
    """PRD §3.8: "The third hop re-sums `lifetime_net_earnings_cents` from all non-`VOIDED`
    payouts and re-derives `payout_tax_document_status` from that total, which means a
    refund large enough to drop lifetime earnings to or below 20000 cents returns the
    teacher from `REQUIRED_UPDATE` to `ON_FILE`".
    PRD §3.8: "the payout's status becomes `FAILED`; and its `approval_status` becomes
    `pending_approval`."

    Design: Difficulty/transitive_cascade/refund_cascade_section_to_teacher_tax_document
    """
    scenario = setup_refund_cascade_scenario()
    teacher, listing, payout = scenario["teacher"], scenario["listing"], scenario["payout"]
    open_section = scenario["sections"][2]

    assert payout["gross_earnings_cents"] == 24000
    assert payout["net_payout_cents"] == 20400
    assert get_teacher(teacher["id"])["payout_tax_document_status"] == "REQUIRED_UPDATE"

    cancel_section(listing["id"], open_section["id"], teacher["id"])

    after = get_payout(payout["id"])
    assert after["status"] == "FAILED", "the recompute moved the payout without any request naming it"
    assert after["approval_status"] == "pending_approval"
    assert after["gross_earnings_cents"] == 16000
    assert after["platform_fee_cents"] == 2400
    assert after["net_payout_cents"] == 13600
    assert after["platform_fee_reversed_cents"] == 1200
    assert after["teacher_liability_cents"] == 3400

    fresh_teacher = get_teacher(teacher["id"])
    assert fresh_teacher["lifetime_net_earnings_cents"] == 13600
    assert fresh_teacher["lifetime_fee_reversed_cents"] == 1200
    assert fresh_teacher["lifetime_teacher_liability_cents"] == 3400
    assert fresh_teacher["payout_tax_document_status"] == "ON_FILE", (
        "the recomputed lifetime total fell back to or below the reporting threshold"
    )


def test_refund_cascade_refunds_the_cancelled_sections_enrollment_in_full(api):
    """PRD §3.4: "The section's `outcome` is written as `CANCELLED_BY_TEACHER`, and every
    `RESERVED` or `CONFIRMED` enrollment of that section moves to `CANCELLED_BY_TEACHER`
    with `cancelled_by` set to `teacher`, a `refund_category` of `FULL`, `refund_cents`
    equal to the enrollment's `discounted_price_cents`".

    Design: Difficulty/transitive_cascade/refund_cascade_section_to_teacher_tax_document
    """
    scenario = setup_refund_cascade_scenario()
    teacher, listing = scenario["teacher"], scenario["listing"]
    open_section = scenario["sections"][2]
    enrollment = scenario["enrollments"][2]

    before = get_teacher(teacher["id"])
    assert before["payout_tax_document_status"] == "REQUIRED_UPDATE"
    assert before["lifetime_net_earnings_cents"] == 20400

    cancel_section(listing["id"], open_section["id"], teacher["id"])

    refunded = get_enrollment(enrollment["id"])
    assert refunded["status"] == "CANCELLED_BY_TEACHER"
    assert refunded["refund_category"] == "FULL"
    assert refunded["refund_cents"] == 8000
    assert refunded["cancelled_by"] == "teacher"

    cancelled_section = get_section(listing["id"], open_section["id"])
    assert cancelled_section["status"] == "CANCELLED"
    assert cancelled_section["outcome"] == "CANCELLED_BY_TEACHER"

    after = get_teacher(teacher["id"])
    assert after["payout_tax_document_status"] == "ON_FILE"
    assert after["lifetime_net_earnings_cents"] == 13600
    assert get_payout(scenario["payout"]["id"])["status"] == "FAILED"


def test_upheld_report_suspends_the_teacher_and_freezes_the_catalogue(api):
    """PRD §3.7: "The third hop suspends the teacher when `actionable_risk_score` has
    reached 40 and the teacher is `ACTIVE`, using the policy suspension path described in
    §3.2 with its listing, section and enrollment cascade."
    PRD §3.2: "the teacher is suspended with `suspension_reason` reading `automatic policy
    suspension` and `suspension_trigger` set to `POLICY`."

    Design: Difficulty/transitive_cascade/report_upheld_cascade_to_teacher_suspension_and_listing_freeze
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher, list_price_cents=2000)
    section = create_section(
        listing, teacher, start_utc="2026-11-05T14:00:00Z", end_utc="2026-11-05T16:00:00Z",
        min_learners=1, capacity=6,
    )
    learner = create_learner(tier="FAMILY")
    enrollment = reserve_seat(listing, section, learner)
    confirmed = confirm_seat(enrollment["id"])
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["discounted_price_cents"] == 1600

    safety_report = file_report(teacher, listing, severity="HIGH", category="SAFETY")
    assert safety_report["severity_weight"] == 65
    technical_report = file_report(teacher, listing, severity="LOW", category="TECHNICAL")
    assert technical_report["severity_weight"] == 5

    dispose_report(safety_report["id"], "START_REVIEW")
    dispose_report(safety_report["id"], "UPHOLD_MORE_SEVERE")

    upheld = get_report(safety_report["id"])
    assert upheld["disposition"] == "MORE_SEVERE"
    assert upheld["status"] == "CLOSED"

    fresh_teacher = get_teacher(teacher["id"])
    assert fresh_teacher["upheld_report_risk_score"] == 65
    assert fresh_teacher["actionable_risk_score"] == 65
    assert fresh_teacher["peak_actionable_risk_score"] == 65
    assert fresh_teacher["status"] == "SUSPENDED"
    assert fresh_teacher["suspension_trigger"] == "POLICY"

    assert get_listing(listing["id"])["lifecycle_state"] == "SUSPENDED"
    cancelled_section = get_section(listing["id"], section["id"])
    assert cancelled_section["status"] == "CANCELLED"
    assert cancelled_section["outcome"] == "CANCELLED_BY_TEACHER"

    refunded = get_enrollment(enrollment["id"])
    assert refunded["status"] == "CANCELLED_BY_TEACHER"
    assert refunded["refund_category"] == "FULL"
    assert refunded["refund_cents"] == 1600


def test_policy_suspended_teacher_cannot_be_reinstated_while_the_peak_stands(api):
    """PRD §3.2: "Reinstatement returns a `SUSPENDED` teacher to `ACTIVE` and requires two
    conditions beyond the state itself: the tax-document status must be `ON_FILE`, and
    `peak_actionable_risk_score` must be strictly below 40."
    PRD §3.7: "Because `actionable_risk_score` is their maximum, resolving a report away
    cannot un-suspend a teacher whose complaint was upheld, and only a peak that has come
    back below 40 allows reinstatement."

    Design: Difficulty/transitive_cascade/report_upheld_cascade_to_teacher_suspension_and_listing_freeze
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher, list_price_cents=2000)
    section = create_section(
        listing, teacher, start_utc="2026-11-05T14:00:00Z", end_utc="2026-11-05T16:00:00Z",
        min_learners=1, capacity=6,
    )
    learner = create_learner(tier="FAMILY")
    enrollment = reserve_seat(listing, section, learner)
    confirm_seat(enrollment["id"])

    safety_report = file_report(teacher, listing, severity="HIGH", category="SAFETY")
    dispose_report(safety_report["id"], "START_REVIEW")
    dispose_report(safety_report["id"], "UPHOLD_MORE_SEVERE")

    suspended = get_teacher(teacher["id"])
    assert suspended["status"] == "SUSPENDED"
    assert suspended["peak_actionable_risk_score"] == 65
    assert suspended["payout_tax_document_status"] == "ON_FILE"

    response = api.reinstate_teacher(teacher["id"], make_platform_admin_headers())
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert get_teacher(teacher["id"])["status"] == "SUSPENDED", (
        "the peak risk still sits above the threshold, so reinstatement stays closed"
    )


def test_third_report_against_the_same_listing_is_refused(api):
    """PRD §3.7: "A parent operator may file at most 2 reports against any one listing, and
    a filing beyond that cap is refused with `ERR_REPORT_WINDOW_CLOSED` (409)."

    Design: Corner/validations/report_filing_cap_enforced_per_listing
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher)

    first = file_report(teacher, listing, severity="LOW", category="TECHNICAL")
    second = file_report(teacher, listing, severity="LOW", category="CONDUCT")
    assert first["status"] == "OPEN"
    assert second["status"] == "OPEN"

    third = api.create_report(
        {
            "teacher_id": teacher["id"],
            "class_listing_id": listing["id"],
            "reported_by_user_id": "p_1",
            "severity": "LOW",
            "category": "OTHER",
        },
        make_parent_headers(),
    )
    validate_error(third, ApiErrorId.ERR_REPORT_WINDOW_CLOSED)
