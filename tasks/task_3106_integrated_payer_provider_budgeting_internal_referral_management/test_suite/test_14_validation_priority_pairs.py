"""Validation ordering: which of two competing rules reports first.

Depth file (queue A).
"""

from test_helpers import (
    TEST_USERS,
    api_client,
    create_appointment_payload,
    create_care_site,
    create_department,
    create_open_region,
    create_provider,
    current_member_version,
    create_referral_payload,
    create_regional_budget,
    enroll_member,
    get_region,
    get_success_data,
    setup_region_at_staffing_line,
    submit_claim,
)

_RFO = TEST_USERS["regional_finance_officer_headers"]
_AS = TEST_USERS["access_scheduler_headers"]
_UR = TEST_USERS["utilization_reviewer_headers"]
_BAC = TEST_USERS["budget_appropriations_committee_headers"]


def test_adjudication_without_an_approved_budget_reports_the_budget_error(api):
    """PRD §3.6: "Adjudication by a `RegionalFinanceOfficer` is available from
    `SUBMITTED`, `PENDED` or `APPEALED` status — but only when the region's
    committed outside-services figure is at or below the budget line, and only
    when the region holds an `APPROVED` `RegionalBudget` for the period."
    PRD §3.6: "The budget requirement is reported as `ERR_BUDGET_NOT_APPROVED`
    (HTTP 409)".

    Design: Difficulty/priority_pair_validation_conflict/priority_state_vs_business_constraint_on_claim_adjudication
    """
    region, care_site, department, provider, member, budget = (
        setup_region_at_staffing_line(
            1.0, 0.8,
            budget_overrides={
                "outside_services_budget_cents": 1,
                "facility_investment_cents": 0,
            },
        )
    )
    claim = submit_claim(
        region["id"], member["id"], current_member_version(member["id"]),
        billed_amount_cents=420000,
    )

    # The region's latest budget is returned to DRAFT, so it holds no APPROVED
    # budget and the claim's period is uncovered.
    get_success_data(api_client.reopen_budget(budget["id"], {}, _BAC))

    res = api_client.adjudicate_claim(claim["id"], {}, _RFO)
    assert res.status_code == 409, res.text
    assert res.json()["data"]["error_id"] == "ERR_BUDGET_NOT_APPROVED", (
        "the approved-budget requirement is the state check that governs adjudication"
    )


def test_claim_is_pended_when_the_outside_services_line_is_already_exceeded(api):
    """PRD §3.6: "A claim begins in `SUBMITTED` status, or in `PENDED` status
    when the region's committed outside-services figure already exceeds its
    budget line."
    PRD §2.4: "While a region sits in `FROZEN`, mutations of its `Member`,
    `CareSite`, `Department`, `Provider`, `CapacityPlan`, `Referral` and
    `OutsideServiceClaim` rows are refused with `ERR_REGION_POSTURE_FROZEN`".

    Design: Difficulty/priority_pair_validation_conflict/priority_state_vs_business_constraint_on_claim_adjudication
    """
    region, care_site, department, provider, member, budget = (
        setup_region_at_staffing_line(
            1.0, 0.8,
            budget_overrides={
                "staffing_budget_cents": 1000000,
                "outside_services_budget_cents": 1,
                "facility_investment_cents": 0,
            },
        )
    )
    claim = submit_claim(
        region["id"], member["id"], current_member_version(member["id"]),
        billed_amount_cents=420000,
    )
    assert claim["status"] == "PENDED", (
        f"Expected PENDED, got {claim['status']}"
    )
    assert get_region(region["id"])["posture"] != "FROZEN", (
        "the claim was accepted, so the posture gate never applied"
    )


def test_specialty_booking_against_an_undecided_referral_is_refused_first(api):
    """PRD §3.4: "When `appointment_type` is `SPECIALTY`, the referral named by
    `referral_id` must exist, must belong to the supplied `member_id`, must name
    the supplied `department_id` as its `target_department_id`, and must itself
    be in `AUTHORIZED` status."
    PRD §3.4: "the mismatch is reported as `ERR_REFERRAL_NOT_AUTHORIZED`
    (HTTP 409)".

    Design: Difficulty/priority_pair_validation_conflict/priority_business_safety_vs_business_fiscal_on_appointment_booking
    """
    region = create_open_region()
    care_site = create_care_site(
        region["id"], staffing_fte_budget=2.0, facility_investment_budget_cents=0
    )
    get_success_data(
        api_client.set_staffing(care_site["id"], {"staffing_fte_filled": 2.0}, _RFO)
    )
    requesting = create_department(
        care_site["id"], specialty="PRIMARY_CARE", appointment_slots_budgeted=200
    )
    target = create_department(
        care_site["id"], specialty="CARDIOLOGY", appointment_slots_budgeted=100,
        wait_threshold_days=21,
    )
    provider = create_provider(
        care_site["id"], specialty="CARDIOLOGY",
        compensation_model="SALARY", base_component_cents=1250000,
    )
    member = enroll_member(region["id"], provider["id"], member_ref="M-CI-1")
    create_regional_budget(
        region["id"],
        period="2026-09",
        staffing_budget_cents=2500000,
        outside_services_budget_cents=0,
        facility_investment_cents=0,
        system_deductible_cents=0,
    )

    referral = get_success_data(
        api_client.create_referral(
            create_referral_payload(
                member["id"], requesting["id"], target["id"], member["version"],
                service_code="CARDIOLOGY", referral_type="INTERNAL",
            ),
            _AS,
        )
    )
    assert referral["status"] == "PENDING_TRIAGE"

    res = api_client.book_appointment(
        create_appointment_payload(
            target["id"], provider["id"], member["id"],
            current_member_version(member["id"]),
            referral_id=referral["id"], appointment_type="SPECIALTY",
            start_utc="2026-09-15T10:00:00Z",
        ),
        _AS,
    )
    assert res.status_code == 409, res.text
    assert res.json()["data"]["error_id"] == "ERR_REFERRAL_NOT_AUTHORIZED"


def test_authorized_specialty_booking_at_the_fiscal_line_reports_the_fiscal_error(api):
    """PRD §3.4: "A specialty booking against a referral whose logical-clock
    position has reached the referral's `expires_at` is refused".
    PRD §2.10: "an outside-service-claim submission, a member enrollment or an
    appointment booking that pushes the figure to or above the line while the
    region's latest budget is not in `APPROVED` status, is rejected with
    `ERR_BUDGET_FISCAL_LINE_EXCEEDED` (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/priority_business_safety_vs_business_fiscal_on_appointment_booking
    """
    region = create_open_region()
    care_site = create_care_site(
        region["id"], staffing_fte_budget=2.0, facility_investment_budget_cents=0
    )
    get_success_data(
        api_client.set_staffing(care_site["id"], {"staffing_fte_filled": 2.0}, _RFO)
    )
    requesting = create_department(
        care_site["id"], specialty="PRIMARY_CARE", appointment_slots_budgeted=200
    )
    target = create_department(
        care_site["id"], specialty="CARDIOLOGY", appointment_slots_budgeted=100,
        wait_threshold_days=21,
    )
    provider = create_provider(
        care_site["id"], specialty="CARDIOLOGY",
        compensation_model="SALARY", base_component_cents=1250000,
    )
    member = enroll_member(region["id"], provider["id"], member_ref="M-CI-1")
    budget = create_regional_budget(
        region["id"],
        period="2026-09",
        staffing_budget_cents=2500000,
        outside_services_budget_cents=0,
        facility_investment_cents=0,
        system_deductible_cents=0,
    )

    # The region's staffing and facility figure sits exactly on the budget line.
    region_after = get_region(region["id"])
    assert region_after["staffing_and_facility_cents"] == 2500000
    assert region_after["staffing_and_facility_cents"] == budget["staffing_budget_cents"]
    assert budget["status"] == "DRAFT", "the budget is never approved in this scenario"

    referral = get_success_data(
        api_client.create_referral(
            create_referral_payload(
                member["id"], requesting["id"], target["id"], member["version"],
                service_code="CARDIOLOGY", referral_type="INTERNAL",
            ),
            _AS,
        )
    )
    get_success_data(api_client.authorize_referral(referral["id"], {}, _UR))

    booking = api_client.book_appointment(
        create_appointment_payload(
            target["id"], provider["id"], member["id"],
            current_member_version(member["id"]),
            referral_id=referral["id"], appointment_type="SPECIALTY",
            start_utc="2026-09-15T10:00:00Z",
        ),
        _AS,
    )
    assert booking.status_code == 402, booking.text
    assert booking.json()["data"]["error_id"] == "ERR_BUDGET_FISCAL_LINE_EXCEEDED", (
        "with a valid referral the fiscal line is the governing business check"
    )
    listed = api_client.list_appointments(_AS, {"member_id": member["id"]})
    assert len(listed.json()["data"]) == 0, "no appointment row is created"