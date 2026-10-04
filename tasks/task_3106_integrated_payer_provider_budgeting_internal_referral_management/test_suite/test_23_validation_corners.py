"""Corner coverage: validation rules — auth context, permissions and refusals.

Breadth file (queue B).
"""

from test_helpers import (
    TEST_USERS,
    api_client,
    create_and_approve_budget,
    current_member_version,
    enroll_member,
    get_member,
    get_region,
    get_success_data,
    set_logical_clock,
    setup_basic_scenario,
    setup_region_site_department_provider,
    validate_error,
    validate_success,
)

_RFO = TEST_USERS["regional_finance_officer_headers"]
_AS = TEST_USERS["access_scheduler_headers"]
_BAC = TEST_USERS["budget_appropriations_committee_headers"]
_ADMIN = TEST_USERS["platform_admin_headers"]
_UR = TEST_USERS["utilization_reviewer_headers"]


def test_member_enrollment_without_the_role_header_is_refused_first(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    identifying the acting principal, and `X-User-Role`, declaring the
    operational capacity in which that principal acts. A request missing either
    header, or carrying a value the system does not recognise, is refused with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
    PRD §3.7: "Header presence and validity is checked first, so a request with
    a missing or malformed `X-User-ID` or `X-User-Role` reports
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` even if the request would also
    fail on permissions or on business grounds."

    Design: Corner/validations/member_create_without_user_context_headers_returns_context_header_error
    """
    set_logical_clock()
    headers = {"X-User-ID": "test-operator-1", "Content-Type": "application/json"}
    res = api_client.create_member(
        "00000000-0000-4000-8000-000000000000",
        {
            "member_ref": "M-HEADER",
            "plan_product": "COMMERCIAL_HMO",
            "benefit_tier": "TIER_1",
            "risk_score": 1.0,
            "coverage_effective_date": "2026-09-01T00:00:00Z",
        },
        headers,
    )
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", expected_status=400)


def test_region_creation_is_confined_to_the_platform_operator(api):
    """PRD §4: "| POST | `/regions` | Create an operating Region |
    `PlatformAdmin` |"
    PRD §2.1: "A well-formed request whose role does not hold the invoked
    operation — either exclusively or in its shared read set — is refused with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/validations/care_team_member_cannot_create_a_region
    """
    set_logical_clock()
    res = api_client.create_region(
        {
            "name": "Forbidden Region",
            "state_codes": ["CA"],
            "margin_target_pct": 0.03,
            "capitation_index": 1.0,
        },
        TEST_USERS["care_team_member_headers"],
    )
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)


def test_booking_a_member_into_another_regions_department_is_refused(api):
    """PRD §2.5: "The member, department, provider, referral and claim rows
    named in a single request must all resolve to the same region of record; a
    request that mixes regions is rejected with `ERR_CROSS_REGION_REFERENCE`
    (HTTP 422)."

    Design: Corner/validations/appointment_with_a_department_in_another_region_returns_cross_region_reference
    """
    from test_helpers import create_appointment_payload

    set_logical_clock()
    region_a, care_site_a, department_a, provider_a = setup_region_site_department_provider()
    member = enroll_member(region_a["id"], provider_a["id"], member_ref="M-T-1")
    create_and_approve_budget(region_a["id"])

    region_b, care_site_b, department_b, provider_b = setup_region_site_department_provider(
        region_overrides={"name": "Other Region", "state_codes": ["NV"]}
    )

    res = api_client.book_appointment(
        create_appointment_payload(
            department_b["id"], provider_b["id"], member["id"],
            current_member_version(member["id"]), start_utc="2026-09-10T09:00:00Z",
        ),
        _AS,
    )
    assert res.status_code == 422, res.text
    assert res.json()["data"]["error_id"] == "ERR_CROSS_REGION_REFERENCE"
    listed = api_client.list_appointments(_AS, {"member_id": member["id"]})
    assert listed.json()["data"] == []


def test_referral_decision_after_the_triage_window_is_refused(api):
    """PRD §3.5: "Decisions are also bounded in time: the logical clock must be
    at or before the referral's `created_at` plus the triage window, or the
    decision is refused with `ERR_REFERRAL_TRIAGE_WINDOW_EXPIRED` (HTTP 409)".

    Design: Corner/validations/referral_decision_after_triage_window_returns_window_expired
    """
    from test_helpers import create_referral_payload

    set_logical_clock("2026-09-01T00:00:00Z")
    region, care_site, department, provider, member = setup_basic_scenario()
    referral = get_success_data(
        api_client.create_referral(
            create_referral_payload(
                member["id"], department["id"], department["id"], member["version"]
            ),
            _AS,
        )
    )
    assert referral["status"] == "PENDING_TRIAGE"

    # A decision is only timely while the clock is inside the triage window; the
    # window is a server-side constant that never surfaces as a field, so at a
    # far later instant a faithful implementation refuses the decision.
    set_logical_clock("2100-01-01T00:00:00Z")
    res = api_client.authorize_referral(referral["id"], {}, _UR)

    assert res.status_code == 409, res.text
    assert res.json()["data"]["error_id"] == "ERR_REFERRAL_TRIAGE_WINDOW_EXPIRED"
    after = api_client.get_referral(referral["id"], _UR).json()["data"]
    assert after["status"] == "PENDING_TRIAGE", (
        "the refused decision leaves the referral undecided"
    )


def test_referral_above_the_external_contract_ceiling_is_refused(api):
    """PRD §3.5: "First, `external_contract_count` may not exceed the
    external-contract maximum; a value above it is an unauthorized external
    network expansion and is refused with `ERR_UNAUTHORIZED_NETWORK_EXPANSION`
    (HTTP 409)."

    Design: Corner/validations/referral_with_too_many_external_contracts_returns_unauthorized_network_expansion
    """
    from test_helpers import create_referral_payload

    set_logical_clock()
    region, care_site, department, provider, member = setup_basic_scenario()

    res = api_client.create_referral(
        create_referral_payload(
            member["id"], department["id"], department["id"], member["version"],
            external_contract_count=9999,
        ),
        _AS,
    )
    assert res.status_code == 409, res.text
    assert res.json()["data"]["error_id"] == "ERR_UNAUTHORIZED_NETWORK_EXPANSION"
    listed = api_client.list_referrals(_UR, {"member_id": member["id"]})
    assert listed.json()["data"] == []


def test_a_second_capacity_plan_for_the_same_department_and_period_is_refused(api):
    """PRD §3.3: "Only one plan may exist for a given department and period; a
    second is rejected with `ERR_DUPLICATE_CAPACITY_PLAN` (HTTP 409)."

    Design: Corner/validations/second_capacity_plan_for_the_same_department_and_period_returns_duplicate
    """
    set_logical_clock()
    region, care_site, department = setup_region_site_department_provider()[:3]
    first = get_success_data(
        api_client.create_capacity_plan(
            region["id"],
            {
                "department_id": department["id"],
                "period": "2026-09",
                "budgeted_slots": 100,
                "panel_target": 3,
            },
            _RFO,
        )
    )
    duplicate = api_client.create_capacity_plan(
        region["id"],
        {
            "department_id": department["id"],
            "period": "2026-09",
            "budgeted_slots": 50,
            "panel_target": 3,
        },
        _RFO,
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["data"]["error_id"] == "ERR_DUPLICATE_CAPACITY_PLAN"

    other_period = api_client.create_capacity_plan(
        region["id"],
        {
            "department_id": department["id"],
            "period": "2026-10",
            "budgeted_slots": 50,
            "panel_target": 3,
        },
        _RFO,
    )
    assert other_period.status_code == 201, other_period.text

    listed = api_client.list_region_capacity_plans(region["id"], _RFO, {"period": "2026-09"})
    assert len(listed.json()["data"]) == 1


def test_staffing_above_the_site_fte_budget_is_refused(api):
    """PRD §3.3: "Filled staffing may never exceed the site's own
    `staffing_fte_budget`: a staffing change that would cross it is rejected
    with `ERR_FTE_BUDGET_EXCEEDED` (HTTP 409)."

    Design: Corner/validations/staffing_set_above_the_site_fte_budget_returns_fte_budget_exceeded
    """
    from test_helpers import create_care_site, create_open_region

    set_logical_clock()
    region = create_open_region()
    care_site = create_care_site(region["id"], staffing_fte_budget=8.0)

    res = api_client.set_staffing(
        care_site["id"], {"staffing_fte_filled": 9.0}, _RFO
    )
    validate_error(res, "ERR_FTE_BUDGET_EXCEEDED", expected_status=409)
    site_after = api_client.get_care_site(care_site["id"], _RFO).json()["data"]
    assert site_after["staffing_fte_filled"] == 0

    at_boundary = api_client.set_staffing(
        care_site["id"], {"staffing_fte_filled": 8.0}, _RFO
    )
    validate_success(at_boundary, 200)
    assert at_boundary.json()["data"]["staffing_fte_filled"] == 8.0


def test_a_second_metric_for_the_same_code_and_period_is_refused(api):
    """PRD §3.10: "A region may hold only one metric for a given `metric_code`
    and `period` pair; a second is rejected with `ERR_DUPLICATE_QUALITY_METRIC`
    (HTTP 409)."

    Design: Corner/validations/second_quality_metric_for_the_same_code_and_period_returns_duplicate
    """
    set_logical_clock()
    region, care_site, department, provider = setup_region_site_department_provider()
    first = get_success_data(
        api_client.create_quality_metric(
            region["id"],
            {
                "metric_code": "QUALITY_COMPOSITE",
                "period": "2026-09",
                "target_value": 80,
                "accountable_provider_id": provider["id"],
            },
            TEST_USERS["quality_review_board_headers"],
        )
    )
    duplicate = api_client.create_quality_metric(
        region["id"],
        {
            "metric_code": "QUALITY_COMPOSITE",
            "period": "2026-09",
            "target_value": 90,
            "accountable_provider_id": provider["id"],
        },
        TEST_USERS["quality_review_board_headers"],
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["data"]["error_id"] == "ERR_DUPLICATE_QUALITY_METRIC"

    different_code = api_client.create_quality_metric(
        region["id"],
        {
            "metric_code": "ACCESS_WAIT_DAYS",
            "period": "2026-09",
            "target_value": 14,
            "accountable_provider_id": provider["id"],
        },
        TEST_USERS["quality_review_board_headers"],
    )
    assert different_code.status_code == 201, different_code.text


def test_region_scoped_read_reports_the_region_miss_first(api):
    """PRD §2.5: "the identifiers in the path are resolved left to right and the
    first identifier that fails to resolve determines the response."
    PRD §5: "`ERR_REGION_NOT_FOUND` | 404".

    Design: Corner/errors/region_get_unknown_id_returns_region_not_found
    """
    set_logical_clock()
    res = api_client.list_region_members(
        "00000000-0000-4000-8000-000000000000", _RFO
    )
    assert res.status_code == 404, res.text
    assert res.json()["data"]["error_id"] == "ERR_REGION_NOT_FOUND"