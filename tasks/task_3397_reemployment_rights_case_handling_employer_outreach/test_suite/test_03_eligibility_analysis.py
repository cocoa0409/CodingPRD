"""Statutory eligibility analysis: the STRICT/LENIENT notice variants, the
nested band/cap/notice thresholds, the 1,825-day cumulative cap boundary,
period selection, and the optimistic concurrency guard on analysis writes."""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    assert_analysis_band_consistency,
    assert_eligibility_analysis,
    assert_instant,
    assert_service_period,
    create_case,
    create_employer,
    create_member,
    create_service_period,
    eligibility_analysis_payload,
    read_case,
    run_analysis,
    set_clock,
    validate_error,
    validate_success,
)


def _strict_analysis(api: ApiClient, case: dict, coordinator_headers: dict) -> dict:
    analysis = run_analysis(api, case["id"], "STRICT", case["version"], headers=coordinator_headers)
    assert_eligibility_analysis(analysis)
    assert_analysis_band_consistency(analysis)
    return analysis


def test_notice_excuse_strict_variant_ignores_the_excuse(api: ApiClient, coordinator_headers: dict):
    """PRD §3.5: "Under the `STRICT` variant, `notice_satisfied` is true only when notice was given at least 24 hours before the start; the excuse fields are ignored entirely, so missing or short notice always fails strict review."
    PRD §3.5: "`notice_hours_advance` is the signed number of hours from the disputed period's `notice_given_at` to its `start_date` — negative when notice came after service began, and null when no notice was given at all."
    PRD §3.5: "The analysis's `overall_eligible` is the conjunction of `notice_satisfied`, `service_limit_ok`, and `deadline_satisfied`."

    Design: Difficulty/dual_variant_calc/notice_excuse_strict_vs_lenient_eligibility
    """
    set_clock(api)
    employer = create_employer(api)
    member = create_member(api)
    create_service_period(
        api, member["id"], employer["id"],
        start_date="2026-03-01T00:00:00Z", end_date="2026-04-15T00:00:00Z",
        orders_type="ACTIVE_DUTY", notice_given_at="2026-02-28T20:00:00Z",
    )
    case = create_case(
        api, member["id"], employer["id"],
        description="Refused reinstatement after 45-day activation",
        application_submitted_at="2026-04-20T00:00:00Z",
        excuse_claimed=True, excuse_category="ORDERS_SHORT_FUSE",
    )

    analysis = _strict_analysis(api, case, coordinator_headers)
    assert analysis["variant"] == "STRICT"
    assert analysis["notice_hours_advance"] == 4, "notice at 2026-02-28T20:00Z is 4 hours before the 2026-03-01 start"
    assert analysis["disputed_period_duration_days"] == 45
    assert analysis["duration_band"] == "MID"
    assert analysis["application_deadline_days"] == 14
    assert_instant(analysis["application_deadline_date"], "2026-04-29T00:00:00Z", "application_deadline_date")
    assert analysis["deadline_satisfied"] is True
    assert analysis["cumulative_chargeable_days"] == 45
    assert analysis["service_limit_ok"] is True
    assert analysis["notice_satisfied"] is False, "4 hours of notice fails the STRICT 24-hour floor despite the claimed excuse"
    assert analysis["overall_eligible"] is False


def test_notice_excuse_lenient_variant_honors_the_excuse(api: ApiClient, coordinator_headers: dict):
    """PRD §3.5: "Under the `LENIENT` variant, `notice_satisfied` is the strict result or, failing that, true when the case's `excuse_claimed` is true and its `excuse_category` is non-null — a claimed, categorized excuse cures even missing or short notice."
    PRD §3.5: "Each run records a new `EligibilityAnalysis` whose `case_id` is bound to the case addressed by the request rather than supplied in the payload, whose per-case `sequence_number` starts at 1 and climbs by one per run — the case's current analysis is the one with the highest `sequence_number` — and whose creation increments the case's `version` by 1."
    PRD §3.5: "A case's analyses are listed in sequence order, the newest last, and are readable by all four case parties."

    Design: Difficulty/dual_variant_calc/notice_excuse_strict_vs_lenient_eligibility
    """
    set_clock(api)
    employer = create_employer(api)
    member = create_member(api)
    create_service_period(
        api, member["id"], employer["id"],
        start_date="2026-03-01T00:00:00Z", end_date="2026-04-15T00:00:00Z",
        orders_type="ACTIVE_DUTY", notice_given_at="2026-02-28T20:00:00Z",
    )
    case = create_case(
        api, member["id"], employer["id"],
        description="Refused reinstatement after 45-day activation",
        application_submitted_at="2026-04-20T00:00:00Z",
        excuse_claimed=True, excuse_category="ORDERS_SHORT_FUSE",
    )

    strict = run_analysis(api, case["id"], "STRICT", case["version"], headers=coordinator_headers)
    assert strict["overall_eligible"] is False

    refreshed = read_case(api, case["id"])
    assert refreshed["version"] == case["version"] + 1, "the stored analysis bumped the case version"
    lenient = run_analysis(api, case["id"], "LENIENT", refreshed["version"], headers=coordinator_headers)
    assert_eligibility_analysis(lenient)
    assert lenient["variant"] == "LENIENT"
    assert lenient["notice_satisfied"] is True, "the claimed, categorized excuse cures the 4-hour notice under LENIENT"
    assert lenient["deadline_satisfied"] is True and lenient["service_limit_ok"] is True
    assert lenient["overall_eligible"] is True
    assert lenient["escalator_position_class"] == "SENIORITY_ESCALATED"

    analyses = validate_success(api.list_eligibility_analyses(case["id"], coordinator_headers))
    assert [a["sequence_number"] for a in analyses] == [1, 2], "analyses list newest last in sequence order"


def test_eligibility_long_band_nested_thresholds(api: ApiClient, coordinator_headers: dict):
    """PRD §3.5: "The deadline band keys on the disputed period's length: at most 30 days is `SHORT`, 31 through 180 days is `MID`, and 181 days or more is `LONG`, stored as `duration_band`."
    PRD §3.5: "The band fixes `application_deadline_days` — 1 day for `SHORT`, 14 for `MID`, 90 for `LONG` — and `application_deadline_date` is the disputed period's `end_date` plus that many days."
    PRD §3.5: "The band also fixes the statutory remedy class: `escalator_position_class` is `SAME_POSITION` for `SHORT`, `SENIORITY_ESCALATED` for `MID`, and `ESCALATED_WITH_RETRAINING` for `LONG`."

    Design: Difficulty/combinatorial_formula/eligibility_band_nested_thresholds
    """
    set_clock(api)
    employer = create_employer(api)
    member = create_member(api, full_name="Lee Park", email="lee@example.com",
                           branch="AIR_FORCE", component="AIR_GUARD")
    create_service_period(
        api, member["id"], employer["id"],
        start_date="2026-01-01T00:00:00Z", end_date="2026-07-20T00:00:00Z",
        orders_type="ACTIVE_DUTY", notice_given_at="2025-12-20T00:00:00Z",
    )
    case = create_case(
        api, member["id"], employer["id"],
        description="Escalator position dispute after 200-day deployment",
        application_submitted_at="2026-09-05T00:00:00Z",
    )

    analysis = _strict_analysis(api, case, coordinator_headers)
    assert analysis["disputed_period_duration_days"] == 200
    assert analysis["duration_band"] == "LONG"
    assert analysis["application_deadline_days"] == 90
    assert_instant(analysis["application_deadline_date"], "2026-10-18T00:00:00Z", "application_deadline_date")
    assert analysis["deadline_satisfied"] is True, "2026-09-05 falls on or before the 2026-10-18 deadline"
    assert analysis["escalator_position_class"] == "ESCALATED_WITH_RETRAINING"


def test_eligibility_long_band_notice_and_cap_legs(api: ApiClient, coordinator_headers: dict):
    """PRD §3.5: "Under the `STRICT` variant, `notice_satisfied` is true only when notice was given at least 24 hours before the start; the excuse fields are ignored entirely, so missing or short notice always fails strict review."
    PRD §3.5: "`service_limit_ok` holds when that total is at most 1,825 days — the five-year cumulative cap — and a total of exactly 1,825 passes."
    PRD §3.5: "The analysis's `overall_eligible` is the conjunction of `notice_satisfied`, `service_limit_ok`, and `deadline_satisfied`."

    Design: Difficulty/combinatorial_formula/eligibility_band_nested_thresholds
    """
    set_clock(api)
    employer = create_employer(api)
    member = create_member(api, full_name="Lee Park", email="lee@example.com",
                           branch="AIR_FORCE", component="AIR_GUARD")
    create_service_period(
        api, member["id"], employer["id"],
        start_date="2026-01-01T00:00:00Z", end_date="2026-07-20T00:00:00Z",
        orders_type="ACTIVE_DUTY", notice_given_at="2025-12-20T00:00:00Z",
    )
    case = create_case(
        api, member["id"], employer["id"],
        description="Escalator position dispute after 200-day deployment",
        application_submitted_at="2026-09-05T00:00:00Z",
    )

    analysis = _strict_analysis(api, case, coordinator_headers)
    assert analysis["notice_hours_advance"] == 288, "2025-12-20 to 2026-01-01 is 12 days = 288 hours"
    assert analysis["notice_satisfied"] is True
    assert analysis["cumulative_chargeable_days"] == 200
    assert analysis["service_limit_ok"] is True
    assert analysis["overall_eligible"] is True


def test_service_cap_1825_exactly_eligible(api: ApiClient, coordinator_headers: dict):
    """PRD §3.5: "`service_limit_ok` holds when that total is at most 1,825 days — the five-year cumulative cap — and a total of exactly 1,825 passes."
    PRD §3.5: "`cumulative_chargeable_days` totals `duration_days` over completed periods of the pair whose orders are not `NATIONAL_EMERGENCY` or `PRESIDENTIAL_CALLUP`, ongoing periods excluded."
    PRD §3.5: "`deadline_satisfied` holds when the case's `application_submitted_at` is set and falls on or before the deadline date; an application on exactly the deadline date passes, and a member who never applied fails."

    Design: Difficulty/boundary_precision_check/service_cap_1825_exactly_eligible
    """
    set_clock(api)
    employer = create_employer(api)
    member = create_member(api, full_name="Ana Bol", email="ana@example.com")
    create_service_period(
        api, member["id"], employer["id"],
        start_date="2020-01-01T00:00:00Z", end_date="2022-09-27T00:00:00Z", orders_type="ACTIVE_DUTY",
    )
    create_service_period(
        api, member["id"], employer["id"],
        start_date="2023-01-01T00:00:00Z", end_date="2025-04-05T00:00:00Z",
        orders_type="ACTIVE_DUTY", notice_given_at="2022-12-01T00:00:00Z",
    )
    case = create_case(api, member["id"], employer["id"], description="At-cap member",
                       application_submitted_at="2025-05-01T00:00:00Z")

    analysis = _strict_analysis(api, case, coordinator_headers)
    assert analysis["cumulative_chargeable_days"] == 1825, "1000 + 825 chargeable days"
    assert analysis["service_limit_ok"] is True, "exactly 1,825 days passes the cap"
    assert analysis["duration_band"] == "LONG" and analysis["application_deadline_days"] == 90
    assert_instant(analysis["application_deadline_date"], "2025-07-04T00:00:00Z", "application_deadline_date")
    assert analysis["deadline_satisfied"] is True
    assert analysis["notice_satisfied"] is True
    assert analysis["overall_eligible"] is True


def test_service_cap_1826_days_over_limit(api: ApiClient, coordinator_headers: dict):
    """PRD §3.5: "`service_limit_ok` holds when that total is at most 1,825 days — the five-year cumulative cap — and a total of exactly 1,825 passes."
    PRD §3.5: "Every run follows a pinned evaluation order: disputed-period selection first, then notice, then the cumulative service cap, then the deadline band; the three component booleans are always computed and stored even when an earlier one is already false."

    Design: Difficulty/boundary_precision_check/service_cap_1825_exactly_eligible
    """
    set_clock(api)
    employer = create_employer(api)
    member = create_member(api, full_name="Ben Dul", email="ben@example.com")
    create_service_period(
        api, member["id"], employer["id"],
        start_date="2020-01-01T00:00:00Z", end_date="2022-09-27T00:00:00Z", orders_type="ACTIVE_DUTY",
    )
    create_service_period(
        api, member["id"], employer["id"],
        start_date="2023-01-01T00:00:00Z", end_date="2025-04-06T00:00:00Z",
        orders_type="ACTIVE_DUTY", notice_given_at="2022-12-01T00:00:00Z",
    )
    case = create_case(api, member["id"], employer["id"], description="Over-cap member",
                       application_submitted_at="2025-05-01T00:00:00Z")

    analysis = _strict_analysis(api, case, coordinator_headers)
    assert analysis["cumulative_chargeable_days"] == 1826, "1000 + 826 chargeable days"
    assert analysis["service_limit_ok"] is False, "1,826 days breaches the cap"
    assert analysis["deadline_satisfied"] is True, "the deadline leg still computes and stores true"
    assert analysis["notice_satisfied"] is True
    assert analysis["overall_eligible"] is False, "only the cap leg flips the conjunction"


def test_exempt_orders_excluded_from_cumulative_cap(api: ApiClient, coordinator_headers: dict):
    """PRD §3.5: "`cumulative_chargeable_days` totals `duration_days` over completed periods of the pair whose orders are not `NATIONAL_EMERGENCY` or `PRESIDENTIAL_CALLUP`, ongoing periods excluded."
    PRD §3.2: "`chargeable`, which is true for every orders category except `NATIONAL_EMERGENCY` and `PRESIDENTIAL_CALLUP` — service under those two categories is exempt from the five-year cumulative cap discussed in §3.5."

    Design: Corner/calculations/exempt_orders_excluded_from_cumulative_cap
    """
    set_clock(api)
    employer = create_employer(api)
    member = create_member(api)
    exempt = create_service_period(
        api, member["id"], employer["id"],
        start_date="2020-01-01T00:00:00Z", end_date="2022-09-27T00:00:00Z", orders_type="NATIONAL_EMERGENCY",
    )
    assert_service_period(exempt)
    assert exempt["chargeable"] is False and exempt["duration_days"] == 1000
    create_service_period(
        api, member["id"], employer["id"],
        start_date="2023-01-01T00:00:00Z", end_date="2025-06-19T00:00:00Z",
        orders_type="ACTIVE_DUTY", notice_given_at="2022-12-01T00:00:00Z",
    )
    case = create_case(api, member["id"], employer["id"], description="Cap-exempt service dispute",
                       application_submitted_at="2025-08-01T00:00:00Z")

    analysis = _strict_analysis(api, case, coordinator_headers)
    assert analysis["cumulative_chargeable_days"] == 900, "the 1000-day NATIONAL_EMERGENCY period is cap-exempt"
    assert analysis["service_limit_ok"] is True
    assert analysis["disputed_period_duration_days"] == 900
    assert analysis["duration_band"] == "LONG" and analysis["application_deadline_days"] == 90
    assert analysis["overall_eligible"] is True


def test_disputed_period_selector_prefers_latest_completed(api: ApiClient, coordinator_headers: dict):
    """PRD §3.5: "Among the candidates the disputed period is the most recent — ordered by `end_date` latest first, ties broken by later `start_date`, then by later `created_at`, and never by identifier."
    PRD §3.5: "Selection picks the disputed period from the member's completed service for this employer: periods of the member-employer pair whose `end_date` is set and falls on or before the logical clock."

    Design: Corner/calculations/disputed_period_selector_prefers_latest_completed
    """
    set_clock(api)
    employer = create_employer(api)
    member = create_member(api)
    create_service_period(api, member["id"], employer["id"],
                          start_date="2024-01-01T00:00:00Z", end_date="2024-01-21T00:00:00Z", orders_type="DRILL")
    create_service_period(api, member["id"], employer["id"],
                          start_date="2025-01-01T00:00:00Z", end_date="2025-07-20T00:00:00Z",
                          orders_type="ACTIVE_DUTY", notice_given_at="2024-12-01T00:00:00Z")
    create_service_period(api, member["id"], employer["id"],
                          start_date="2026-08-01T00:00:00Z", orders_type="DRILL")
    case = create_case(api, member["id"], employer["id"], description="Selector case",
                       application_submitted_at="2025-08-01T00:00:00Z")

    analysis = _strict_analysis(api, case, coordinator_headers)
    assert analysis["disputed_period_duration_days"] == 200, \
        "the 200-day period ending 2025-07-20 wins over the 20-day 2024 period; the ongoing period is ignored"
    assert analysis["duration_band"] == "LONG"
    assert_instant(analysis["application_deadline_date"], "2025-10-18T00:00:00Z", "application_deadline_date")


def test_analysis_without_completed_period_returns_no_completed_service_period(
    api: ApiClient, coordinator_headers: dict
):
    """PRD §3.5: "When no completed period exists for the pair, the analysis aborts with `ERR_NO_COMPLETED_SERVICE_PERIOD` (HTTP 422)."
    PRD §3.5: "Selection picks the disputed period from the member's completed service for this employer: periods of the member-employer pair whose `end_date` is set and falls on or before the logical clock."

    Design: Corner/calculations/disputed_period_selector_prefers_latest_completed
    """
    set_clock(api)
    employer = create_employer(api)
    member = create_member(api, full_name="On Going", email="on@example.com",
                           branch="NAVY", component="NAVY_RESERVE")
    create_service_period(api, member["id"], employer["id"],
                          start_date="2026-08-01T00:00:00Z", orders_type="ACTIVE_DUTY")
    case = create_case(api, member["id"], employer["id"], description="No completed period")

    response = api.create_eligibility_analysis(
        case["id"], eligibility_analysis_payload("STRICT", expected_case_version=case["version"]), coordinator_headers
    )
    validate_error(response, ApiErrorId.ERR_NO_COMPLETED_SERVICE_PERIOD)
    analyses = validate_success(api.list_eligibility_analyses(case["id"], coordinator_headers))
    assert analyses == [], "the aborted run stores no analysis"


def test_duration_band_30_vs_31_days_flips_deadline_and_escalator(api: ApiClient, coordinator_headers: dict):
    """PRD §3.5: "The deadline band keys on the disputed period's length: at most 30 days is `SHORT`, 31 through 180 days is `MID`, and 181 days or more is `LONG`, stored as `duration_band`. The band fixes `application_deadline_days` — 1 day for `SHORT`, 14 for `MID`, 90 for `LONG` — and `application_deadline_date` is the disputed period's `end_date` plus that many days."
    PRD §3.5: "`deadline_satisfied` holds when the case's `application_submitted_at` is set and falls on or before the deadline date; an application on exactly the deadline date passes, and a member who never applied fails."
    PRD §3.5: "The band also fixes the statutory remedy class: `escalator_position_class` is `SAME_POSITION` for `SHORT`, `SENIORITY_ESCALATED` for `MID`, and `ESCALATED_WITH_RETRAINING` for `LONG`."

    Design: Corner/cross_cutting_complexity_layers/duration_band_30_vs_31_days_flips_deadline_and_escalator
    """
    set_clock(api)
    employer = create_employer(api)
    member_a = create_member(api)
    create_service_period(api, member_a["id"], employer["id"],
                          start_date="2026-01-01T00:00:00Z", end_date="2026-01-31T00:00:00Z",
                          orders_type="DRILL", notice_given_at="2025-12-20T00:00:00Z")
    case_a = create_case(api, member_a["id"], employer["id"], description="30-day band",
                         application_submitted_at="2026-02-01T00:00:00Z")
    member_b = create_member(api, full_name="B B", email="bb@example.com",
                             branch="NAVY", component="NAVY_RESERVE")
    create_service_period(api, member_b["id"], employer["id"],
                          start_date="2026-01-01T00:00:00Z", end_date="2026-02-01T00:00:00Z",
                          orders_type="DRILL", notice_given_at="2025-12-20T00:00:00Z")
    case_b = create_case(api, member_b["id"], employer["id"], description="31-day band",
                         application_submitted_at="2026-02-15T00:00:00Z")

    analysis_a = _strict_analysis(api, case_a, coordinator_headers)
    assert analysis_a["disputed_period_duration_days"] == 30
    assert analysis_a["duration_band"] == "SHORT"
    assert analysis_a["application_deadline_days"] == 1
    assert_instant(analysis_a["application_deadline_date"], "2026-02-01T00:00:00Z", "SHORT deadline date")
    assert analysis_a["escalator_position_class"] == "SAME_POSITION"
    assert analysis_a["deadline_satisfied"] is True, "an application on exactly the 1-day deadline passes"
    assert analysis_a["overall_eligible"] is True

    analysis_b = _strict_analysis(api, case_b, coordinator_headers)
    assert analysis_b["disputed_period_duration_days"] == 31
    assert analysis_b["duration_band"] == "MID"
    assert analysis_b["application_deadline_days"] == 14
    assert_instant(analysis_b["application_deadline_date"], "2026-02-15T00:00:00Z", "MID deadline date")
    assert analysis_b["escalator_position_class"] == "SENIORITY_ESCALATED"
    assert analysis_b["deadline_satisfied"] is True, "an application on exactly the 14-day deadline passes"
    assert analysis_b["overall_eligible"] is True


def test_occ_stale_version_on_analysis_returns_412(api: ApiClient, coordinator_headers: dict):
    """PRD §2.6: "The case assignment operation and the eligibility-analysis recording operation each require the client to supply `expected_case_version`, a non-optional field carrying the case `version` the client last observed. If the case's current `version` has advanced beyond that observed value — because another coordinator has assigned the case, or a prior analysis has been recorded against it — the request is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412), forcing the client to re-read the case rather than overwrite work it has not seen."
    PRD §2.6: "Both operations increment the case's `version` by 1 when they succeed."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_analysis_returns_412
    """
    set_clock(api)
    employer = create_employer(api)
    member = create_member(api)
    create_service_period(api, member["id"], employer["id"],
                          start_date="2026-03-01T00:00:00Z", end_date="2026-04-15T00:00:00Z",
                          orders_type="ACTIVE_DUTY", notice_given_at="2026-02-20T00:00:00Z")
    case = create_case(api, member["id"], employer["id"], description="Refused reinstatement",
                       application_submitted_at="2026-04-20T00:00:00Z")
    assert case["version"] == 1

    first = api.create_eligibility_analysis(
        case["id"], eligibility_analysis_payload("STRICT", expected_case_version=1), coordinator_headers
    )
    validate_success(first, 201)
    assert read_case(api, case["id"])["version"] == 2, "the stored analysis bumped the case version 1 -> 2"

    stale = api.create_eligibility_analysis(
        case["id"], eligibility_analysis_payload("LENIENT", expected_case_version=1), coordinator_headers
    )
    validate_error(stale, ApiErrorId.ERR_STALE_CASE_VERSION)
    assert stale.status_code == 412

    analyses = validate_success(api.list_eligibility_analyses(case["id"], coordinator_headers))
    assert len(analyses) == 1, "the stale run stored nothing"
