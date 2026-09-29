"""Refusals raised by the operating-year workflows: execution, the ledger, the
cure clock, the exit obligations, consent decisions and deadline relief."""

from test_helpers import (
    BSD_HEADERS,
    FDM_HEADERS,
    QA_HEADERS,
    QA_SECOND_HEADERS,
    ApiErrorId,
    assert_instant,
    assert_integer,
    assert_money,
    factories,
    fixtures,
    get_success_data,
    make_owner_headers,
    validate_error,
    validate_paginated_list,
)

LIFE_SAFETY_CRITICAL_LINE = {
    "category": "LIFE_SAFETY",
    "priority": "CRITICAL",
    "description": "Stairwell pressurisation and emergency lighting",
    "estimated_cost": 480_000.00,
}
TECHNOLOGY_CRITICAL_LINE = {
    "category": "TECHNOLOGY",
    "priority": "CRITICAL",
    "description": "Property management system and network core replacement",
    "estimated_cost": 620_000.00,
}
GUESTROOM_MAJOR_LINE = {
    "category": "GUESTROOM",
    "priority": "MAJOR",
    "description": "Guestroom soft goods and case goods replacement",
    "estimated_cost": 2_400_000.00,
}


def test_execution_reads_the_live_capacity_band_and_not_the_frozen_snapshot(api):
    """PRD §3.2 and §3.6: execution consults the ownership entity's live band on
    the basis the review chose, so a profile restated downward after approval
    blocks the signing even though the frozen snapshot still reads STRONG at
    100.00.  The application has left UNDER_REVIEW, so the re-verification
    cascade cannot stale its review either - the block comes from the live band
    alone, and the entity is still only a prospect afterwards.

    Design: Corner/errors/execution_reads_the_owners_live_capacity_band_and_is_refused
    """
    world = fixtures.setup_drafted_agreement(api)
    assert world["application"]["capacity_basis"] == "PORTFOLIO_ADJUSTED"

    fixtures.set_clock(api, "2026-09-08T00:00:00Z")
    owner = get_success_data(
        api.update_owner_financial_profile(
            world["owner_id"],
            factories.build_financial_profile_payload(
                liquid_assets_amount=2_400_000.00,
                net_worth_amount=7_500_000.00,
                credit_score=680,
                existing_units_count=3,
            ),
            FDM_HEADERS,
        )
    )
    assert_money(owner["capacity_score_standalone"], 51.60, "capacity_score_standalone")
    assert owner["capacity_band_standalone"] == "INSUFFICIENT"
    assert_money(
        owner["capacity_score_portfolio_adjusted"], 49.35, "capacity_score_portfolio_adjusted"
    )
    assert owner["capacity_band_portfolio_adjusted"] == "INSUFFICIENT"
    assert_integer(owner["financial_profile_revision"], 1, "financial_profile_revision")

    fixtures.set_clock(api, "2026-09-10T00:00:00Z")
    version = fixtures.read_application_version(api, world["application_id"])
    response = api.execute_agreement(
        world["agreement_id"], factories.build_execute_payload(version), FDM_HEADERS
    )
    validate_error(response, ApiErrorId.OWNER_CAPACITY_INSUFFICIENT)
    assert response.status_code == 422

    application = get_success_data(api.get_application(world["application_id"], FDM_HEADERS))
    assert application["status"] == "APPROVED"
    assert application["financial_review_status"] == "PASSED", (
        "an application that has left UNDER_REVIEW is not staled by a re-verification"
    )
    assert application["capacity_basis"] == "PORTFOLIO_ADJUSTED"
    assert_money(application["capacity_score_at_review"], 100.00, "capacity_score_at_review")
    assert application["capacity_band_at_review"] == "STRONG"

    agreement = get_success_data(api.get_agreement(world["agreement_id"], FDM_HEADERS))
    assert agreement["status"] == "DRAFT"
    assert agreement["executed_at"] is None
    assert get_success_data(api.get_owner(world["owner_id"], FDM_HEADERS))["status"] == "PROSPECT"


def test_a_second_filing_and_a_correction_of_an_unreported_month_are_both_duplicates(api):
    """PRD §3.8 and §3.9: the ledger is append-only and the correction flag
    decides which way the duplicate rule points - a second ordinary filing for a
    reported month and a correction for a month never reported are refused with
    the same identifier.  A quality-assurance termination on a hotel that is
    still COMPLIANT is refused too, and none of the three refusals disturbs the
    single surviving entry or its four running totals.

    Design: Corner/errors/duplicate_period_and_premature_termination_on_an_open_agreement_are_rejected
    """
    world = fixtures.setup_open_agreement(api)
    owner_headers = make_owner_headers(world["owner_id"])
    fixtures.set_clock(api, "2026-12-06T00:00:00Z")
    fixtures.report_revenue(
        api, world["agreement_id"], world["owner_id"], "2026-11", 320_000.16
    )

    duplicate = api.report_revenue(
        world["agreement_id"],
        factories.build_revenue_report_payload("2026-11", 330_000.00),
        owner_headers,
    )
    validate_error(duplicate, ApiErrorId.DUPLICATE_REVENUE_PERIOD)
    unreported_correction = api.report_revenue(
        world["agreement_id"],
        factories.build_revenue_report_payload("2026-10", 210_000.00, correction=True),
        owner_headers,
    )
    validate_error(unreported_correction, ApiErrorId.DUPLICATE_REVENUE_PERIOD)
    premature = api.terminate_agreement(
        world["agreement_id"],
        factories.build_termination_payload(
            "FOR_CAUSE_QA", termination_notes="No failed cure reviews on file."
        ),
        BSD_HEADERS,
    )
    validate_error(premature, ApiErrorId.TERMINATION_NOT_ELIGIBLE)
    for response in (duplicate, unreported_correction, premature):
        assert response.status_code == 409

    agreement = get_success_data(api.get_agreement(world["agreement_id"], FDM_HEADERS))
    assert_integer(agreement["reported_period_count"], 1, "reported_period_count")
    assert len(agreement["revenue_periods"]) == 1, (
        f"no refused filing may append an entry, got {len(agreement['revenue_periods'])}"
    )
    assert_money(agreement["royalty_fee_to_date"], 17_400.01, "royalty_fee_to_date")
    assert_money(
        agreement["marketing_fund_contributed_total"], 8_000.00, "marketing_fund_contributed_total"
    )
    assert_money(agreement["reservation_fee_to_date"], 5_600.00, "reservation_fee_to_date")
    assert_money(agreement["total_fees_assessed"], 31_000.01, "total_fees_assessed")
    assert agreement["status"] == "OPEN"
    assert agreement["compliance_status"] == "COMPLIANT"
    assert agreement["termination_cause"] is None
    assert agreement["terminated_at"] is None


def test_a_cure_is_refused_on_a_closed_inspection_and_again_once_the_window_expires(api):
    """PRD §3.8: a passing inspection closes with no cure obligation at all, so
    a cure tendered against it has no stage to be in.  The next inspection,
    taken at exactly the ninety-day boundary the rate limit permits, fails and
    opens a thirty-day window - and a tender one day past the deadline is
    refused on the clock instead, leaving the inspection unsubmitted.

    Design: Corner/errors/cure_submission_on_a_closed_inspection_and_after_the_deadline_is_rejected
    """
    world = fixtures.setup_open_agreement(api)
    owner_headers = make_owner_headers(world["owner_id"])

    fixtures.set_clock(api, "2026-11-15T00:00:00Z")
    passing = fixtures.score_inspection(
        api, world["agreement_id"], QA_HEADERS,
        cleanliness_score=96, condition_score=94,
        brand_standard_score=98, guest_experience_score=92,
    )
    assert_money(passing["total_score"], 95.50, "total_score")
    assert passing["grade"] == "PASS"
    assert passing["status"] == "CLOSED"
    assert passing["cure_period_days"] is None
    assert passing["cure_deadline"] is None

    on_closed = api.submit_inspection_cure(
        passing["id"], factories.build_cure_submission_payload(), owner_headers
    )
    validate_error(on_closed, ApiErrorId.INSPECTION_STAGE_INVALID)
    assert on_closed.status_code == 409

    fixtures.set_clock(api, "2027-02-13T00:00:00Z")
    failing = fixtures.score_inspection(
        api, world["agreement_id"], QA_SECOND_HEADERS,
        cleanliness_score=60, condition_score=60,
        brand_standard_score=60, guest_experience_score=60,
    )
    assert_money(failing["total_score"], 60.00, "total_score")
    assert failing["grade"] == "FAIL"
    assert_integer(failing["cure_period_days"], 30, "cure_period_days")
    assert_instant(failing["cure_deadline"], "2027-03-15T00:00:00.000Z", "cure_deadline")
    assert failing["status"] == "CURE_PENDING"

    fixtures.set_clock(api, "2027-03-16T00:00:00Z")
    too_late = api.submit_inspection_cure(
        failing["id"], factories.build_cure_submission_payload(), owner_headers
    )
    validate_error(too_late, ApiErrorId.CURE_WINDOW_EXPIRED)
    assert too_late.status_code == 422

    rows, _ = validate_paginated_list(
        api.list_agreement_qa_inspections(world["agreement_id"], QA_HEADERS, {"limit": 10})
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id[failing["id"]]["status"] == "CURE_PENDING"
    assert by_id[failing["id"]]["cure_submitted_at"] is None
    assert by_id[passing["id"]]["status"] == "CLOSED"

    agreement = get_success_data(api.get_agreement(world["agreement_id"], FDM_HEADERS))
    assert agreement["compliance_status"] == "CURE_PERIOD"
    assert_integer(
        agreement["consecutive_qa_failure_count"], 0, "consecutive_qa_failure_count"
    )
    assert_instant(
        agreement["last_inspection_at"], "2027-02-13T00:00:00.000Z", "last_inspection_at"
    )


def test_a_certification_missing_one_code_stores_nothing_and_starts_no_penalty(api):
    """PRD §3.9: de-identification is all-or-nothing, so a certification listing
    four of the five codes is refused and the stored array stays empty rather
    than partially filled.  The refusal is not a breach either: the penalty is
    still 0.00 and the deadline the termination set has not moved, while the
    exit state the mutual termination produced - a zero discounted present value
    over a hotel that never reported revenue - is undisturbed.

    Design: Corner/errors/de_identification_certification_missing_one_item_code_is_rejected
    """
    world = fixtures.setup_open_agreement(api, scope_lines=[LIFE_SAFETY_CRITICAL_LINE])
    world = fixtures.setup_termination_pending_agreement(
        api, world, cause="MUTUAL", terminate_clock="2026-11-05T00:00:00Z"
    )

    fixtures.set_clock(api, "2026-11-20T00:00:00Z")
    response = api.certify_de_identification(
        world["agreement_id"],
        factories.build_de_identification_payload(
            ["SIGNAGE", "INTERIOR_BRANDING", "DIGITAL_LISTINGS", "LINENS_AND_COLLATERAL"]
        ),
        make_owner_headers(world["owner_id"]),
    )
    validate_error(response, ApiErrorId.DEIDENTIFICATION_INCOMPLETE)
    assert response.status_code == 422

    agreement = get_success_data(api.get_agreement(world["agreement_id"], FDM_HEADERS))
    assert agreement["de_identification_status"] == "PENDING"
    assert agreement["de_identification_items_completed"] == [], (
        "a refused certification stores no codes at all, got "
        f"{agreement['de_identification_items_completed']!r}"
    )
    assert_money(
        agreement["de_identification_breach_penalty"], 0.00, "de_identification_breach_penalty"
    )
    assert_instant(
        agreement["de_identification_deadline"], "2026-12-05T00:00:00.000Z",
        "de_identification_deadline",
    )

    assert agreement["status"] == "TERMINATION_PENDING"
    assert agreement["post_termination_status"] == "OPEN"
    assert agreement["termination_cause"] == "MUTUAL"
    assert agreement["liquidated_damages_formula"] == "DISCOUNTED_PV"
    assert_integer(agreement["reported_period_count"], 0, "reported_period_count")
    assert_money(agreement["trailing_avg_monthly_fee"], 0.00, "trailing_avg_monthly_fee")
    assert_money(agreement["liquidated_damages_amount"], 0.00, "liquidated_damages_amount")
    assert agreement["channel_status"] == "SUSPENDED"

    plan = get_success_data(api.get_pip(world["plan_id"], BSD_HEADERS))
    assert plan["status"] == "COMPLETED", (
        "a completed plan is outside the termination suspension set"
    )


def test_a_consent_request_may_be_decided_only_once(api):
    """PRD §3.9: a decision is available only from SUBMITTED, so a second
    decision on a request already consented to is refused and the first
    decision stands - the refusal neither overwrites the outcome nor records a
    refusal reason.  The frozen flat refinance fee is not re-priced, and the
    agreement's consent tally and version are untouched by the refused call.

    Design: Corner/errors/deciding_an_already_consented_transfer_request_is_rejected
    """
    world = fixtures.setup_executed_agreement(api)
    request = fixtures.file_refinance_request(api, world, lender_name="Cascade Mutual Bank")
    assert_money(request["transfer_fee"], 15_000.00, "transfer_fee")
    assert_money(request["non_compliance_surcharge"], 0.00, "non_compliance_surcharge")
    assert_money(request["total_consent_fee"], 15_000.00, "total_consent_fee")

    fixtures.set_clock(api, "2026-09-14T00:00:00Z")
    version_before = fixtures.read_agreement_version(api, world["agreement_id"])
    consented = get_success_data(
        api.decide_transfer_request(
            request["id"],
            factories.build_transfer_decision_payload("CONSENT", version_before),
            FDM_HEADERS,
        )
    )
    assert consented["status"] == "CONSENTED"
    assert_instant(consented["decided_at"], "2026-09-14T00:00:00.000Z", "decided_at")
    version_after = fixtures.read_agreement_version(api, world["agreement_id"])
    assert version_after == version_before + 1

    fixtures.set_clock(api, "2026-09-20T00:00:00Z")
    second = api.decide_transfer_request(
        request["id"],
        factories.build_transfer_decision_payload(
            "REFUSE", version_after, decision_notes="Reconsidered after the fact."
        ),
        FDM_HEADERS,
    )
    validate_error(second, ApiErrorId.TRANSFER_REQUEST_NOT_SUBMITTED)
    assert second.status_code == 409

    stored = get_success_data(api.get_transfer_request(request["id"], FDM_HEADERS))
    assert stored["status"] == "CONSENTED"
    assert stored["refusal_reason"] is None
    assert_instant(stored["decided_at"], "2026-09-14T00:00:00.000Z", "decided_at")
    assert_money(stored["transfer_fee"], 15_000.00, "transfer_fee")
    assert_money(stored["total_consent_fee"], 15_000.00, "total_consent_fee")

    agreement = get_success_data(api.get_agreement(world["agreement_id"], FDM_HEADERS))
    assert_integer(agreement["transfer_consent_count"], 1, "transfer_consent_count")
    assert_integer(agreement["version"], version_after, "version")

    _, meta = validate_paginated_list(
        api.list_transfer_requests(FDM_HEADERS, {"agreement_id": world["agreement_id"]})
    )
    assert_integer(meta["total_count"], 1, "total_count")


def test_a_third_extension_request_on_one_scope_line_is_refused(api):
    """PRD §3.7: a scope line may be granted relief twice and no more, so a
    third request is refused on the count alone even though the line is still
    PENDING, well inside its extended deadline, and the sixty-day line budget is
    exactly exhausted rather than the plan pool.  Nothing about the second
    request is overwritten by the refused third one.

    Design: Corner/errors/third_extension_request_on_the_same_item_is_rejected
    """
    world = fixtures.setup_accepted_plan(api, scope_lines=[GUESTROOM_MAJOR_LINE])
    item_id = world["items"][0]["id"]
    assert world["items"][0]["category"] == "GUESTROOM"

    fixtures.set_clock(api, "2026-11-10T00:00:00Z")
    fixtures.request_extension(
        api, item_id, world["owner_id"], 30, reason="Mill slipped the millwork run."
    )
    first = fixtures.decide_extension(api, item_id, "GRANT")
    assert_instant(
        first["due_date"],
        "2027-05-03T00:00:00.000Z",
        "due_date (thirty days on from 2027-04-03)",
    )

    fixtures.set_clock(api, "2026-12-10T00:00:00Z")
    fixtures.request_extension(
        api, item_id, world["owner_id"], 30, reason="Freight consolidation delayed the shipment."
    )
    second = fixtures.decide_extension(api, item_id, "GRANT")
    assert_instant(
        second["due_date"],
        "2027-06-02T00:00:00.000Z",
        "due_date (thirty more days on from 2027-05-03)",
    )
    assert_integer(second["extension_request_count"], 2, "extension_request_count")
    assert_integer(second["extension_granted_days_total"], 60, "extension_granted_days_total")

    fixtures.set_clock(api, "2027-01-10T00:00:00Z")
    response = api.request_pip_item_extension(
        item_id,
        factories.build_extension_request_payload(
            15, reason="A third slip on the same package."
        ),
        make_owner_headers(world["owner_id"]),
    )
    validate_error(response, ApiErrorId.EXTENSION_LIMIT_EXCEEDED)
    assert response.status_code == 422

    rows, _ = validate_paginated_list(
        api.list_pip_items(world["plan_id"], BSD_HEADERS, {"limit": 10})
    )
    item = rows[0]
    assert_integer(item["extension_request_count"], 2, "extension_request_count")
    assert_integer(item["extension_granted_days_total"], 60, "extension_granted_days_total")
    assert item["extension_status"] == "GRANTED"
    assert_integer(item["extension_requested_days"], 30, "extension_requested_days")
    assert_instant(item["due_date"], "2027-06-02T00:00:00.000Z", "due_date")
    assert item["status"] == "PENDING"
    assert item["extension_reason"] == "Freight consolidation delayed the shipment.", (
        "the refused request must not overwrite the second request's reason"
    )

    plan = get_success_data(api.get_pip(world["plan_id"], BSD_HEADERS))
    assert_integer(plan["extension_granted_days_total"], 60, "extension_granted_days_total")
    assert plan["status"] == "ACCEPTED"
    assert_integer(plan["items_total_count"], 1, "items_total_count")
    assert_integer(plan["items_pending_count"], 1, "items_pending_count")


def test_an_unverified_critical_line_outside_life_safety_blocks_the_opening(api):
    """PRD §3.6: the opening checks life safety first and then every other
    CRITICAL line, so a plan whose life-safety work is verified but whose
    critical technology package is not is refused on the second gate rather than
    the first - and refused ahead of the onboarding, channel and acceptance
    gates, all of which are already satisfied.  Verifying the outstanding line
    completes the plan and the same opening then succeeds.

    Design: Corner/errors/open_with_an_unverified_critical_non_life_safety_item_is_rejected
    """
    world = fixtures.setup_accepted_plan(
        api, scope_lines=[LIFE_SAFETY_CRITICAL_LINE, TECHNOLOGY_CRITICAL_LINE]
    )
    life_safety = world["items_by_category"]["LIFE_SAFETY"]
    technology = world["items_by_category"]["TECHNOLOGY"]
    assert_instant(
        life_safety["due_date"], "2026-11-19T00:00:00.000Z",
        "LIFE_SAFETY due_date (min(90, 45) days from acceptance)",
    )
    assert_instant(
        technology["due_date"], "2027-01-03T00:00:00.000Z",
        "TECHNOLOGY due_date (min(90, 120) days from acceptance)",
    )

    fixtures.set_clock(api, "2026-10-20T00:00:00Z")
    fixtures.complete_item(api, life_safety["id"], world["owner_id"])
    fixtures.set_clock(api, "2026-10-22T00:00:00Z")
    fixtures.verify_item(api, life_safety["id"], "VERIFY")
    fixtures.climb_onboarding_ladders(api, world["agreement_id"])

    fixtures.set_clock(api, "2026-11-01T00:00:00Z")
    response = api.open_agreement(world["agreement_id"], {}, BSD_HEADERS)
    validate_error(response, ApiErrorId.CRITICAL_PIP_ITEMS_OPEN)
    assert response.status_code == 409

    blocked = get_success_data(api.get_agreement(world["agreement_id"], FDM_HEADERS))
    assert blocked["status"] == "EXECUTED"
    assert blocked["opened_at"] is None
    assert blocked["training_status"] == "COMPLETED"
    assert blocked["systems_status"] == "VALIDATED"
    assert blocked["channel_status"] == "CONNECTED"

    plan = get_success_data(api.get_pip(world["plan_id"], BSD_HEADERS))
    assert plan["status"] == "IN_PROGRESS"
    assert_integer(plan["items_total_count"], 2, "items_total_count")
    assert_integer(plan["items_verified_count"], 1, "items_verified_count")
    assert_integer(plan["items_pending_count"], 1, "items_pending_count")

    fixtures.complete_item(api, technology["id"], world["owner_id"])
    verified = fixtures.verify_item(api, technology["id"], "VERIFY")
    assert verified["status"] == "VERIFIED"
    plan = get_success_data(api.get_pip(world["plan_id"], BSD_HEADERS))
    assert plan["status"] == "COMPLETED"
    assert_integer(plan["items_verified_count"], 2, "items_verified_count")
    assert_integer(plan["items_pending_count"], 0, "items_pending_count")

    opened = fixtures.open_agreement(api, world["agreement_id"])
    assert opened["status"] == "OPEN"
    assert_instant(opened["opened_at"], "2026-11-01T00:00:00.000Z", "opened_at")
    assert opened["compliance_status"] == "COMPLIANT"
    assert opened["channel_status"] == "CONNECTED"
