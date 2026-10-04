"""Corner coverage: role-based access control refusals.

Breadth file (queue B).
"""

from test_helpers import (
    TEST_USERS,
    api_client,
    create_and_approve_budget,
    create_member_payload,
    create_open_region,
    create_regional_budget,
    current_member_version,
    enroll_member,
    get_success_data,
    make_provider_headers,
    set_logical_clock,
    setup_basic_scenario,
    setup_bookable_scenario,
    setup_region_site_department_provider,
    submit_claim,
    validate_error,
)

_RFO = TEST_USERS["regional_finance_officer_headers"]
_AS = TEST_USERS["access_scheduler_headers"]
_UR = TEST_USERS["utilization_reviewer_headers"]
_BAC = TEST_USERS["budget_appropriations_committee_headers"]
_ADMIN = TEST_USERS["platform_admin_headers"]


def test_utilization_reviewer_cannot_adjudicate_a_claim(api):
    """PRD §2.1: "`UtilizationReviewer` exclusively decides referral
    authorizations, referral denials, referral appeals, and claim denials and
    claim appeals."
    PRD §4: "| POST | `/outside-service-claims/{id}/adjudicate` | Adjudicate a
    claim and pin its final liability | `RegionalFinanceOfficer` |"

    Design: Corner/rbac/utilization_reviewer_cannot_adjudicate_a_claim
    """
    set_logical_clock()
    region, care_site, department, provider, member, budget = setup_bookable_scenario()
    claim = submit_claim(
        region["id"], member["id"], current_member_version(member["id"]),
        billed_amount_cents=420000,
    )

    res = api_client.adjudicate_claim(claim["id"], {}, _UR)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)
    assert api_client.get_outside_service_claim(claim["id"], _UR).json()["data"]["status"] == "SUBMITTED"

    allowed = api_client.adjudicate_claim(claim["id"], {}, _RFO)
    assert allowed.status_code == 200, allowed.text


def test_access_scheduler_cannot_approve_a_regional_budget(api):
    """PRD §2.1: "`BudgetAppropriationsCommittee` exclusively approves, returns
    and reopens regional budgets".
    PRD §4: "| POST | `/regional-budgets/{id}/approve` | Approve a submitted
    budget | `BudgetAppropriationsCommittee` |"

    Design: Corner/rbac/access_scheduler_cannot_approve_a_regional_budget
    """
    set_logical_clock()
    region = create_open_region()
    budget = create_regional_budget(region["id"])
    get_success_data(api_client.submit_budget(budget["id"], {}, _RFO))

    res = api_client.approve_budget(budget["id"], {}, _AS)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)
    assert api_client.get_regional_budget(budget["id"], _BAC).json()["data"]["status"] == "SUBMITTED"


def test_care_team_member_cannot_book_an_appointment(api):
    """PRD §2.1: "`AccessScheduler` exclusively owns department creation and
    capacity-flag adjustment, network-service declaration, referral intake,
    appointment booking and cancellation".
    PRD §4: "| POST | `/appointments` | Book an Appointment slot for a Member |
    `AccessScheduler` |"

    Design: Corner/rbac/care_team_member_cannot_book_appointments
    """
    from test_helpers import create_appointment_payload

    set_logical_clock()
    region, care_site, department, provider, member, budget = setup_bookable_scenario()

    res = api_client.book_appointment(
        create_appointment_payload(
            department["id"], provider["id"], member["id"],
            current_member_version(member["id"]), start_utc="2026-09-10T09:00:00Z",
        ),
        TEST_USERS["care_team_member_headers"],
    )
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)
    listed = api_client.list_appointments(_AS, {"member_id": member["id"]})
    assert listed.json()["data"] == []


def test_provider_role_cannot_terminate_a_member(api):
    """PRD §2.1: "For `Provider`, the `X-User-Role` header value `Provider`
    means `X-User-ID` is the `id` of the acting `Provider`; ownership checks on
    any resource that references a `Provider` compare that resource's
    provider-reference field to `X-User-ID`, so a `Provider` principal reads
    only its own row and the region-scoped reads around it."
    PRD §2.1: "`RegionalFinanceOfficer` owns enrollment, compensation, facility
    cost, outside-services spend, capacity-plan activation and adjustment,
    member transfers and the regional operating budget lifecycle, and is the
    sole writer of member termination".

    Design: Corner/rbac/provider_role_cannot_terminate_a_member
    """
    set_logical_clock()
    region, care_site, department, provider, member = setup_basic_scenario()

    res = api_client.terminate_member(
        member["id"],
        {"expected_member_version": current_member_version(member["id"])},
        make_provider_headers(provider["id"]),
    )
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)
    assert api_client.get_member(member["id"], _RFO).json()["data"]["status"] == "ACTIVE"


def test_platform_admin_cannot_enroll_a_member(api):
    """PRD §2.1: "`PlatformAdmin` exclusively creates regions and exclusively
    operates the logical clock."
    PRD §2.1: "`RegionalFinanceOfficer` owns enrollment".

    Design: Corner/rbac/platform_admin_cannot_enroll_a_member
    """
    set_logical_clock()
    region, care_site, department, provider = setup_region_site_department_provider()

    res = api_client.create_member(
        region["id"],
        create_member_payload(provider["id"], member_ref="M-ADMIN"),
        _ADMIN,
    )
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)
    listed = api_client.list_region_members(region["id"], _RFO)
    assert listed.json()["data"] == []


def test_quality_review_board_cannot_create_a_capacity_plan(api):
    """PRD §2.1: "`QualityReviewBoard` exclusively opens, finalizes and reopens
    quality metrics."
    PRD §4: "| POST | `/regions/{id}/capacity-plans` | Budget appointment supply
    for a department and period | `RegionalFinanceOfficer` |"

    Design: Corner/rbac/quality_review_board_cannot_create_a_capacity_plan
    """
    set_logical_clock()
    region, care_site, department = setup_region_site_department_provider()[:3]

    res = api_client.create_capacity_plan(
        region["id"],
        {
            "department_id": department["id"],
            "period": "2026-09",
            "budgeted_slots": 100,
            "panel_target": 3,
        },
        TEST_USERS["quality_review_board_headers"],
    )
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)
    listed = api_client.list_region_capacity_plans(region["id"], _RFO)
    assert listed.json()["data"] == []