"""Optimistic guards on two families, the failure tally one short of the exit,
and counters read in the same request that moves them."""

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
    factories,
    fixtures,
    get_success_data,
    make_owner_headers,
    validate_error,
)

BELLEVUE_UNIT = {
    "unit_name": "Solaris Bellevue",
    "market_code": "SEADT",
    "x_miles": 4.50,
    "y_miles": 0.00,
    "room_count": 140,
    "adr_amount": 210.00,
    "occupancy_pct": 72.00,
    "territory_start_date": "2016-06-01",
    "territory_end_date": "2026-09-30",
}


def test_the_second_license_off_one_approval_must_execute_against_the_moved_version(api):
    """PRD §2.7 and §3.6: several licenses may legitimately be drafted from one
    approval, and a successful execution advances the application's version - so
    the writer of the second license, still holding the version it read before
    the first execution, is turned away with the concurrency guard and succeeds
    only on the refreshed value.  Each license keeps its own frozen term dates.

    Design: Corner/cross_cutting_complexity_layers/execute_with_a_stale_expected_application_version_is_rejected
    """
    world = fixtures.setup_approved_application(api)
    fixtures.set_clock(api, "2026-09-05T00:00:00Z")
    first = fixtures.draft_agreement(api, world["application_id"], "2026-10-01")
    second = fixtures.draft_agreement(api, world["application_id"], "2026-11-01")
    assert first["id"] != second["id"]

    version_before = fixtures.read_application_version(api, world["application_id"])
    fixtures.set_clock(api, "2026-09-10T00:00:00Z")
    executed_first = get_success_data(
        api.execute_agreement(
            first["id"], factories.build_execute_payload(version_before), FDM_HEADERS
        )
    )
    assert executed_first["status"] == "EXECUTED"
    version_after_first = fixtures.read_application_version(api, world["application_id"])
    assert version_after_first == version_before + 1, (
        f"one execution advances the version by exactly one, got "
        f"{version_before} then {version_after_first}"
    )

    stale = api.execute_agreement(
        second["id"], factories.build_execute_payload(version_before), FDM_HEADERS
    )
    validate_error(stale, ApiErrorId.STALE_APPLICATION_VERSION)
    assert stale.status_code == 412

    blocked = get_success_data(api.get_agreement(second["id"], FDM_HEADERS))
    assert blocked["status"] == "DRAFT"
    assert blocked["executed_at"] is None
    assert_integer(
        fixtures.read_application_version(api, world["application_id"]),
        version_after_first,
        "version",
    )

    executed_second = get_success_data(
        api.execute_agreement(
            second["id"], factories.build_execute_payload(version_after_first), FDM_HEADERS
        )
    )
    assert executed_second["status"] == "EXECUTED"
    assert_instant(executed_second["executed_at"], "2026-09-10T00:00:00.000Z", "executed_at")
    assert_integer(
        fixtures.read_application_version(api, world["application_id"]),
        version_after_first + 1,
        "version",
    )

    assert executed_first["effective_date"] == "2026-10-01"
    assert executed_first["expiry_date"] == "2046-10-01"
    assert executed_second["effective_date"] == "2026-11-01"
    assert executed_second["expiry_date"] == "2046-11-01"


def test_the_second_consent_decision_must_echo_the_version_the_first_one_moved(api):
    """PRD §2.7 and §3.9: every consent decision advances the license's version,
    so a decision taken on a second request against the view held before the
    first decision is turned away.  The refused attempt records nothing, and the
    accepted refusal that follows stores the discretionary reason.  Neither
    request is re-priced by any decision: both keep the flat refinance fee frozen
    at filing.

    Design: Corner/cross_cutting_complexity_layers/transfer_decision_with_a_stale_expected_agreement_version_is_rejected
    """
    world = fixtures.setup_executed_agreement(api)
    owner_headers = make_owner_headers(world["owner_id"])
    fixtures.set_clock(api, "2026-09-14T00:00:00Z")
    first = get_success_data(
        api.file_transfer_request(
            world["agreement_id"],
            factories.build_refinance_request_payload("Cascade Mutual Bank"),
            owner_headers,
        ),
        201,
    )
    second = get_success_data(
        api.file_transfer_request(
            world["agreement_id"],
            factories.build_refinance_request_payload("Puget Mezzanine Capital"),
            owner_headers,
        ),
        201,
    )

    version_before = fixtures.read_agreement_version(api, world["agreement_id"])
    consented = get_success_data(
        api.decide_transfer_request(
            first["id"],
            factories.build_transfer_decision_payload(
                "CONSENT", version_before,
                decision_notes="First refinancing consented to.",
            ),
            FDM_HEADERS,
        )
    )
    assert consented["status"] == "CONSENTED"
    version_after_first = fixtures.read_agreement_version(api, world["agreement_id"])
    assert version_after_first == version_before + 1

    stale = api.decide_transfer_request(
        second["id"],
        factories.build_transfer_decision_payload(
            "CONSENT", version_before,
            decision_notes="Second refinancing consented against a stale view.",
        ),
        FDM_HEADERS,
    )
    validate_error(stale, ApiErrorId.STALE_AGREEMENT_VERSION)
    assert stale.status_code == 412

    blocked = get_success_data(api.get_transfer_request(second["id"], FDM_HEADERS))
    assert blocked["status"] == "SUBMITTED"
    assert blocked["decided_at"] is None
    assert blocked["decision_user_id"] is None
    assert_integer(
        fixtures.read_agreement_version(api, world["agreement_id"]),
        version_after_first,
        "version",
    )

    refused = get_success_data(
        api.decide_transfer_request(
            second["id"],
            factories.build_transfer_decision_payload(
                "REFUSE", version_after_first,
                decision_notes="Second lender declined on refreshed review.",
            ),
            FDM_HEADERS,
        )
    )
    assert refused["status"] == "REFUSED"
    assert refused["refusal_reason"] == "DISCRETION"
    assert_instant(refused["decided_at"], "2026-09-14T00:00:00.000Z", "decided_at")

    agreement = get_success_data(api.get_agreement(world["agreement_id"], FDM_HEADERS))
    assert_integer(agreement["transfer_consent_count"], 1, "transfer_consent_count")
    assert_integer(agreement["version"], version_after_first + 1, "version")

    for request in (
        get_success_data(api.get_transfer_request(first["id"], FDM_HEADERS)),
        refused,
    ):
        assert_money(request["transfer_fee"], 15_000.00, "transfer_fee")
        assert_money(request["non_compliance_surcharge"], 0.00, "non_compliance_surcharge")
        assert_money(request["total_consent_fee"], 15_000.00, "total_consent_fee")
        assert request["proposed_owner_capacity_band"] is None


def _fail_a_cure_cycle(api, world, inspection_clock, cure_clock):
    """Score below PASS, let the franchisee cure it, and have a second inspector
    fail the review - one turn of the consecutive-failure tally."""
    fixtures.set_clock(api, inspection_clock)
    inspection = fixtures.score_inspection(
        api, world["agreement_id"], QA_HEADERS,
        cleanliness_score=60, condition_score=60,
        brand_standard_score=60, guest_experience_score=60,
    )
    assert_money(inspection["total_score"], 60.00, "total_score")
    assert inspection["grade"] == "FAIL"
    fixtures.set_clock(api, cure_clock)
    fixtures.submit_cure(api, inspection["id"], world["owner_id"])
    return fixtures.review_cure(api, inspection["id"], "FAIL", QA_SECOND_HEADERS)


def test_two_failed_cures_stop_one_short_of_the_quality_assurance_exit(api):
    """PRD §3.8 and §3.9: the second failed cure leaves the tally at two, which
    is DEFAULT_NOTICE and not the eligibility the quality-assurance exit demands,
    so that termination is refused - while the improvement-plan exit, which
    accepts DEFAULT_NOTICE, succeeds on the same license at the same instant.
    A failed cure never sets a plan cure deadline, because no plan deadline was
    missed.

    Design: Corner/cross_cutting_complexity_layers/two_consecutive_cure_failures_stop_one_short_of_termination_eligibility
    """
    world = fixtures.setup_open_agreement(api)
    first = _fail_a_cure_cycle(api, world, "2026-11-15T00:00:00Z", "2026-12-01T00:00:00Z")
    second = _fail_a_cure_cycle(api, world, "2027-02-13T00:00:00Z", "2027-03-02T00:00:00Z")
    assert first["status"] == "CURE_FAILED"
    assert second["status"] == "CURE_FAILED"

    before = get_success_data(api.get_agreement(world["agreement_id"], FDM_HEADERS))
    assert_integer(
        before["consecutive_qa_failure_count"], 2, "consecutive_qa_failure_count"
    )
    assert before["compliance_status"] == "DEFAULT_NOTICE"
    assert before["transfer_consent_blocked"] is True
    assert before["channel_status"] == "SUSPENDED"
    assert_instant(
        before["default_notice_issued_at"], "2027-03-02T00:00:00.000Z",
        "default_notice_issued_at",
    )
    assert before["pip_cure_deadline"] is None, (
        "a failed cure sets no improvement-plan deadline"
    )

    premature = api.terminate_agreement(
        world["agreement_id"],
        factories.build_termination_payload(
            "FOR_CAUSE_QA",
            termination_notes="Two failed cures; attempting the QA exit one failure early.",
        ),
        BSD_HEADERS,
    )
    validate_error(premature, ApiErrorId.TERMINATION_NOT_ELIGIBLE)
    assert premature.status_code == 409
    still_open = get_success_data(api.get_agreement(world["agreement_id"], FDM_HEADERS))
    assert still_open["status"] == "OPEN"
    assert still_open["terminated_at"] is None

    terminated = get_success_data(
        api.terminate_agreement(
            world["agreement_id"],
            factories.build_termination_payload(
                "FOR_CAUSE_PIP",
                termination_notes="Default notice outstanding; exercising the default remedy.",
            ),
            BSD_HEADERS,
        )
    )
    assert terminated["status"] == "TERMINATION_PENDING"
    assert terminated["termination_cause"] == "FOR_CAUSE_PIP"
    assert terminated["liquidated_damages_formula"] == "CONTRACTUAL_MULTIPLE"
    assert_instant(terminated["terminated_at"], "2027-03-02T00:00:00.000Z", "terminated_at")
    assert_instant(
        terminated["de_identification_deadline"], "2027-04-01T00:00:00.000Z",
        "de_identification_deadline",
    )
    assert_integer(terminated["reported_period_count"], 0, "reported_period_count")
    assert_money(terminated["trailing_avg_monthly_fee"], 0.00, "trailing_avg_monthly_fee")
    assert_integer(
        terminated["remaining_term_months_at_termination"], 235,
        "remaining_term_months_at_termination",
    )
    assert_integer(
        terminated["liquidated_damages_cap_months"], 36, "liquidated_damages_cap_months"
    )
    assert_money(terminated["liquidated_damages_amount"], 0.00, "liquidated_damages_amount")


def test_both_brand_counters_are_visible_on_the_next_read_of_the_brand(api):
    """PRD §2.8 and §3.1: the two brand counters are maintained synchronously
    inside the requests that move them, so each read of the brand reports the
    tally as at that instant.  Filing raises the pipeline counter and registering
    a hotel raises the estate counter, each touching only its own; opening the
    review file moves neither, because both stages count as open; and the
    approval retires the file from the pipeline while leaving the estate alone.

    Design: Corner/consistency_model/brand_counters_are_visible_in_the_same_request_that_changes_them
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    brand = fixtures.create_solaris_brand(api)
    owner = fixtures.create_strong_owner(api)

    at_rest = get_success_data(api.get_brand(brand["id"], BSD_HEADERS))
    assert_integer(at_rest["open_application_count"], 0, "open_application_count")
    assert_integer(at_rest["operating_unit_count"], 0, "operating_unit_count")

    application = fixtures.create_application(api, owner["id"], brand["id"])
    assert application["status"] == "SUBMITTED"
    after_filing = get_success_data(api.get_brand(brand["id"], BSD_HEADERS))
    assert_integer(after_filing["open_application_count"], 1, "open_application_count")
    assert_integer(after_filing["operating_unit_count"], 0, "operating_unit_count")

    fixtures.create_existing_unit(api, brand["id"], **BELLEVUE_UNIT)
    after_unit = get_success_data(api.get_brand(brand["id"], BSD_HEADERS))
    assert_integer(after_unit["operating_unit_count"], 1, "operating_unit_count")
    assert_integer(after_unit["open_application_count"], 1, "open_application_count")

    fixtures.start_review(api, application["id"])
    after_start = get_success_data(api.get_brand(brand["id"], BSD_HEADERS))
    assert_integer(
        after_start["open_application_count"], 1,
        "open_application_count (submitted and under-review are both open)",
    )
    assert_integer(after_start["operating_unit_count"], 1, "operating_unit_count")

    fixtures.set_clock(api, "2026-08-05T00:00:00Z")
    fixtures.run_financial_review(api, application["id"], "STANDALONE")
    fixtures.run_impact_analysis(api, application["id"])
    fixtures.finalize_impact(api, application["id"])
    approved = get_success_data(
        api.decide_application(
            application["id"],
            factories.build_decision_payload("APPROVE", decision_notes="Approved for conversion."),
            FDM_DECIDER_HEADERS,
        )
    )

    assert approved["status"] == "APPROVED"
    assert approved["capacity_basis"] == "STANDALONE"
    assert_money(approved["capacity_score_at_review"], 96.67, "capacity_score_at_review")
    assert approved["capacity_band_at_review"] == "STRONG"
    assert_money(approved["final_impact_score"], 4.62, "final_impact_score")
    assert approved["encroachment_verdict"] == "CLEAR"

    after_approval = get_success_data(api.get_brand(brand["id"], BSD_HEADERS))
    assert_integer(after_approval["open_application_count"], 0, "open_application_count")
    assert_integer(after_approval["operating_unit_count"], 1, "operating_unit_count")
