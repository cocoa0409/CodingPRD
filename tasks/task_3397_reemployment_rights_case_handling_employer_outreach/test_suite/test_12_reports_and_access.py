"""Trend reporting and access control corners: the half-open aggregation
window with repeat employers and top issue type, empty-window zeroes,
sub-resource isolation, case-read ownership, the authentication tier, and
the per-family 404 sweep."""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    NON_EXISTENT_UUID,
    ROLE_SERVICE_MEMBER,
    assert_sector_trend_report,
    create_case,
    create_certified_ombudsman,
    create_employer,
    create_member,
    create_service_period,
    create_statement,
    headers_without_user_id,
    make_employer_headers,
    make_ombudsman_headers,
    make_service_member_headers,
    read_case,
    resolve_case_informally,
    set_clock,
    service_period_payload,
    setup_basic_world,
    transition_case,
    triage_case,
    assign_case,
    validate_error,
    validate_success,
)


def test_sector_trend_aggregation_window_and_repeat_employers(api: ApiClient, coordinator_headers: dict):
    """PRD §3.9: "The sector-trend report takes a `sector`, a `period_start`, and a `period_end`, and considers the cases whose `created_at` falls in the half-open window from `period_start` up to but not including `period_end` and whose employer's sector matches. The report echoes the `sector`, `period_start`, and `period_end` and computes `total_cases`, the count of cases in the window; `resolved_count`, those in `RESOLVED_INFORMAL`; `repeat_employer_count`, the number of distinct employers with at least 2 cases in the window; and `top_issue_type`, the most frequent `issue_type` in the window, with ties broken in favor of the tied issue type whose earliest-created case in the window comes first."

    Design: Corner/calculations/sector_trend_aggregation_window_and_repeat_employers
    """
    set_clock(api)
    retail_x = create_employer(api, legal_name="Retail X", sector="RETAIL", size_tier="LARGE")
    retail_y = create_employer(api, legal_name="Retail Y", sector="RETAIL", size_tier="SMALL")
    tech_z = create_employer(api, legal_name="Tech Z", sector="TECHNOLOGY", size_tier="MEDIUM")
    ombudsman = create_certified_ombudsman(api)
    member_one = create_member(api)
    member_two = create_member(api, full_name="M Two", email="m2@example.com",
                               branch="ARMY", component="ARMY_GUARD")
    member_three = create_member(api, full_name="M Three", email="m3@example.com",
                                 branch="ARMY", component="ARMY_GUARD")
    member_four = create_member(api, full_name="M Four", email="m4@example.com",
                                branch="ARMY", component="ARMY_GUARD")

    case_a = create_case(api, member_one["id"], retail_x["id"], description="Case A")
    case_a = triage_case(api, case_a["id"])
    case_a = assign_case(api, case_a["id"], ombudsman["id"], case_a["version"])
    resolve_case_informally(api, case_a["id"], ombudsman["id"], employer_id=retail_x["id"])

    set_clock(api, "2026-09-05T00:00:00Z")
    create_case(api, member_two["id"], retail_x["id"], description="Case B")
    create_case(api, member_three["id"], retail_y["id"], issue_type="BENEFITS", description="Case C")
    create_case(api, member_four["id"], tech_z["id"], description="Case D")

    set_clock(api, "2026-10-01T00:00:00Z")
    create_case(api, member_one["id"], retail_x["id"], issue_type="RETALIATION",
                description="Case E at window end")

    window = {"period_start": "2026-09-01T00:00:00Z", "period_end": "2026-10-01T00:00:00Z"}
    retail = validate_success(api.get_sector_trends({"sector": "RETAIL", **window}, coordinator_headers))
    assert_sector_trend_report(retail)
    assert retail["total_cases"] == 3, "cases A, B and C - case E created at exactly period_end is excluded"
    assert retail["repeat_employer_count"] == 1, "only Retail X holds at least 2 cases in the window"
    assert retail["resolved_count"] == 1, "case A resolved informally"
    assert retail["top_issue_type"] == "REEMPLOYMENT", "2 REEMPLOYMENT against 1 BENEFITS"

    tech = validate_success(api.get_sector_trends({"sector": "TECHNOLOGY", **window}, coordinator_headers))
    assert tech["total_cases"] == 1
    assert tech["top_issue_type"] == "REEMPLOYMENT"


def test_sector_trend_empty_window_returns_zeroes_and_null_top(api: ApiClient, coordinator_headers: dict):
    """PRD §3.9: "An empty window reports zero counts and a null `top_issue_type`."

    Design: Corner/calculations/sector_trend_empty_window_returns_zeroes_and_null_top
    """
    set_clock(api)
    report = validate_success(api.get_sector_trends(
        {"sector": "GOVERNMENT", "period_start": "2026-09-01T00:00:00Z",
         "period_end": "2026-10-01T00:00:00Z"},
        coordinator_headers,
    ))
    assert_sector_trend_report(report)
    assert report["total_cases"] == 0
    assert report["resolved_count"] == 0
    assert report["repeat_employer_count"] == 0
    assert report["top_issue_type"] is None


def test_fk_reverse_subresources_return_only_own_children(api: ApiClient, coordinator_headers: dict):
    """PRD §2.10: "The same left-to-right discipline governs sub-resource reads: rounds, notes, analyses, benefit assessments, and referrals hang beneath a case; service periods are listed beneath a member or an employer; statements of support and recognition awards beneath an employer; training records beneath an ombudsman."

    Design: Corner/endpoints/fk_reverse_subresources_return_only_own_children
    """
    set_clock(api)
    employer = create_employer(api)
    other = create_employer(api, legal_name="Other Corp", sector="LOGISTICS", size_tier="SMALL")
    member_a = create_member(api)
    member_b = create_member(api, full_name="B B", email="bb@example.com",
                             branch="NAVY", component="NAVY_RESERVE")
    create_service_period(api, member_a["id"], employer["id"],
                          start_date="2026-01-01T00:00:00Z", end_date="2026-02-01T00:00:00Z",
                          orders_type="DRILL")
    create_service_period(api, member_b["id"], other["id"],
                          start_date="2026-03-01T00:00:00Z", end_date="2026-04-01T00:00:00Z",
                          orders_type="DRILL")
    create_statement(api, employer["id"])

    periods_a = validate_success(api.list_member_service_periods(member_a["id"], coordinator_headers))
    assert len(periods_a) == 1 and periods_a[0]["employer_id"] == employer["id"]

    periods_b = validate_success(api.list_member_service_periods(member_b["id"], coordinator_headers))
    assert len(periods_b) == 1 and periods_b[0]["employer_id"] == other["id"]

    statements_own = validate_success(api.list_employer_statements(employer["id"], coordinator_headers))
    assert len(statements_own) == 1 and statements_own[0]["employer_id"] == employer["id"]

    statements_other = validate_success(api.list_employer_statements(other["id"], coordinator_headers))
    assert statements_other == []


def test_member_b_cannot_read_member_a_case(api: ApiClient):
    """PRD §3.1: "Reading a single case is restricted to its parties and its overseer: the filing member, the respondent employer, the assigned ombudsman, and coordinators."
    PRD §2.8: "Entity-backed actors touch only their own rows. For resources that exist, the server compares the acting identity against the row's owning field — `member_id` for a service member, `employer_id` for an employer, `assigned_ombudsman_id` for an ombudsman acting on a case — as applicable per endpoint, and a mismatch is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/member_b_cannot_read_member_a_case
    """
    world = setup_basic_world(api)
    other_employer = create_employer(api, legal_name="Unrelated Inc", sector="GOVERNMENT", size_tier="LARGE")
    member_b = create_member(api, full_name="B B", email="bb@example.com",
                             branch="NAVY", component="NAVY_RESERVE")
    case = create_case(api, world["member"]["id"], world["employer"]["id"])
    case = triage_case(api, case["id"])
    case = assign_case(api, case["id"], world["ombudsman"]["id"], case["version"])

    by_other_member = api.get_case(case["id"], make_service_member_headers(member_b["id"]))
    validate_error(by_other_member, ApiErrorId.ERR_OWNERSHIP_VIOLATION)

    by_other_employer = api.get_case(case["id"], make_employer_headers(other_employer["id"]))
    validate_error(by_other_employer, ApiErrorId.ERR_OWNERSHIP_VIOLATION)

    by_member = validate_success(api.get_case(case["id"], make_service_member_headers(world["member"]["id"])))
    assert by_member["status"] == "ASSIGNED"
    by_employer = validate_success(api.get_case(case["id"], make_employer_headers(world["employer"]["id"])))
    assert by_employer["status"] == "ASSIGNED"
    by_ombudsman = validate_success(api.get_case(case["id"], make_ombudsman_headers(world["ombudsman"]["id"])))
    assert by_ombudsman["status"] == "ASSIGNED"


def test_service_period_create_missing_user_header_returns_unauthenticated(api: ApiClient, coordinator_headers: dict):
    """PRD §2.1: "A request whose `X-User-Role` header is missing or names no declared role, or whose `X-User-ID` header is missing or empty for any role other than `Anonymous`, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/service_period_create_missing_user_header_returns_unauthenticated
    """
    set_clock(api)
    employer = create_employer(api)
    member = create_member(api)

    response = api.create_service_period(
        service_period_payload(member["id"], employer["id"],
                               start_date="2026-01-01T00:00:00Z", end_date="2026-02-01T00:00:00Z",
                               orders_type="DRILL"),
        headers_without_user_id(ROLE_SERVICE_MEMBER),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)
    assert response.status_code == 401

    periods = validate_success(api.list_member_service_periods(member["id"], coordinator_headers))
    assert periods == []


def test_unknown_id_sweep_returns_entity_specific_not_found(api: ApiClient, coordinator_headers: dict):
    """PRD §2.10: "Each resource family has its own miss error — `ERR_MEMBER_NOT_FOUND`, `ERR_EMPLOYER_NOT_FOUND`, `ERR_OMBUDSMAN_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_ROUND_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`, and `ERR_AWARD_NOT_FOUND` — so the response always names the kind of thing that could not be found."
    PRD §2.7: "Fourth, existence: path identifiers are validated left to right, and body foreign keys are validated in the endpoint's declared input order — `member_id` before `employer_id`, and so on — each miss producing the corresponding 404 error."

    Design: Corner/errors/unknown_id_sweep_returns_entity_specific_not_found
    """
    set_clock(api)
    probes = [
        (api.get_case(NON_EXISTENT_UUID, coordinator_headers), ApiErrorId.ERR_CASE_NOT_FOUND),
        (api.respond_to_round(NON_EXISTENT_UUID, {"response": "ACCEPT"},
                              make_employer_headers("00000000-0000-4000-8000-0000000000ee")),
         ApiErrorId.ERR_ROUND_NOT_FOUND),
        (api.transition_referral(NON_EXISTENT_UUID, {"to_status": "SUBMITTED"}, coordinator_headers),
         ApiErrorId.ERR_REFERRAL_NOT_FOUND),
        (api.transition_event(NON_EXISTENT_UUID, {"to_status": "OPEN"}, coordinator_headers),
         ApiErrorId.ERR_EVENT_NOT_FOUND),
        (api.transition_statement(NON_EXISTENT_UUID, {"to_status": "SIGNED"}, coordinator_headers),
         ApiErrorId.ERR_STATEMENT_NOT_FOUND),
        (api.transition_award(NON_EXISTENT_UUID, {"to_status": "VETTED"}, coordinator_headers),
         ApiErrorId.ERR_AWARD_NOT_FOUND),
        (api.get_member(NON_EXISTENT_UUID, coordinator_headers), ApiErrorId.ERR_MEMBER_NOT_FOUND),
        (api.get_employer(NON_EXISTENT_UUID, coordinator_headers), ApiErrorId.ERR_EMPLOYER_NOT_FOUND),
        (api.get_ombudsman(NON_EXISTENT_UUID, coordinator_headers), ApiErrorId.ERR_OMBUDSMAN_NOT_FOUND),
    ]
    for response, expected_error in probes:
        validate_error(response, expected_error)
        assert response.status_code == 404, f"{expected_error} must be a 404, got {response.status_code}"
