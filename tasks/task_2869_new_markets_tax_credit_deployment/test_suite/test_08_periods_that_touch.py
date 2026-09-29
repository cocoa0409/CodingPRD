"""Intervals that meet at a single instant, and the two conventions that decide.

Reporting periods are closed, so sharing one endpoint is a collision; a project
company's occupancy of an award's compliance period is half-open with a 30-day
buffer, and placements from the same award are exempt from it.
"""
from test_helpers import (
    ApiErrorId,
    assert_cents,
    assert_instant,
    create_cba,
    create_fund,
    close_fund,
    create_qlici_payload,
    deploy_qlici,
    file_job_report,
    issue_qei,
    job_report_payload,
    make_agency_headers,
    make_qalicb_sponsor_headers,
    read_award,
    read_cba,
    read_qalicb,
    read_qei,
    set_clock,
    setup_active_award,
    setup_certified_project_company,
    setup_funded_fund,
    setup_two_awards_one_entity,
    validate_error,
    validate_paginated,
    validate_success,
)

AGREEMENT_CLOCK = "2026-09-01T00:00:00.000Z"
FILING_CLOCK = "2027-09-01T00:00:00.000Z"

FIRST_PERIOD_START = "2026-09-01T00:00:00.000Z"
FIRST_PERIOD_END = "2027-02-28T00:00:00.000Z"
SECOND_PERIOD_START = "2027-03-01T00:00:00.000Z"
SECOND_PERIOD_END = "2027-08-31T00:00:00.000Z"

#: A wage-passing first half-year: 1950 cents an hour clears the 1800 floor.
FIRST_HALF = {
    "headcount": 20,
    "qualifying_headcount": 18,
    "total_hours": 46000,
    "qualifying_hours": 45000,
    "local_hires": 12,
    "avg_hourly_wage_cents": 1950,
}
#: A wage-failing second half-year: 1750 cents an hour is under the floor.
SECOND_HALF = {
    "headcount": 10,
    "qualifying_headcount": 6,
    "total_hours": 20800,
    "qualifying_hours": 12480,
    "local_hires": 5,
    "avg_hourly_wage_cents": 1750,
}


def _agreement_with_one_filed_period(api):
    scenario = setup_active_award(
        api, clock=AGREEMENT_CLOCK, certification_suffix="014"
    )
    setup_certified_project_company(api, scenario)
    scenario.cba = create_cba(api, scenario.cde, scenario.qalicb, scenario.award)
    set_clock(api, FILING_CLOCK)
    scenario.extras["first_report"] = file_job_report(
        api, scenario.cba, FIRST_PERIOD_START, FIRST_PERIOD_END, **FIRST_HALF
    )
    return scenario


def test_a_period_starting_on_the_previous_period_end_instant_is_refused(api):
    """Closed intervals share no endpoint, and there is no buffer between them.

    PRD: "Reporting periods are **closed** intervals and may not overlap any
    existing period of the same agreement: two reports that share even a single
    endpoint instant collide, there is no buffer between them, and the collision is
    `ERR_REPORT_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/job_report_periods_are_closed_intervals_so_a_shared_endpoint_instant_collides
    """
    scenario = _agreement_with_one_filed_period(api)

    refused = api.file_job_report(
        scenario.cba["id"],
        job_report_payload(FIRST_PERIOD_END, SECOND_PERIOD_END, **SECOND_HALF),
        make_qalicb_sponsor_headers(),
    )
    validate_error(refused, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP.value, 409)

    _rows, meta = validate_paginated(
        api.list_job_reports(scenario.cba["id"], make_agency_headers())
    )
    assert meta["total_count"] == 1


def test_a_period_starting_the_next_day_is_accepted_and_its_wage_gate_frozen(api):
    """The adjoining period is filed, and its wage answer is decided once.

    PRD: "At filing time the server evaluates the wage gate once and freezes the
    answer in `wage_floor_met`, which is true exactly when `avg_hourly_wage_cents`
    is greater than or equal to the agreement's `wage_floor_cents_per_hour`."

    Design: Difficulty/resource_temporal_overlap/job_report_periods_are_closed_intervals_so_a_shared_endpoint_instant_collides
    """
    scenario = _agreement_with_one_filed_period(api)

    second = validate_success(
        api.file_job_report(
            scenario.cba["id"],
            job_report_payload(SECOND_PERIOD_START, SECOND_PERIOD_END, **SECOND_HALF),
            make_qalicb_sponsor_headers(),
        ),
        201,
    )
    assert_instant(second["period_start_at"], SECOND_PERIOD_START, "period_start_at")
    assert second["wage_floor_met"] is False

    first = scenario.extras["first_report"]
    assert_instant(first["period_end_at"], FIRST_PERIOD_END, "period_end_at")
    assert first["wage_floor_met"] is True

    _rows, meta = validate_paginated(
        api.list_job_reports(scenario.cba["id"], make_agency_headers())
    )
    assert meta["total_count"] == 2
    assert read_cba(api, scenario.cba["id"])["status"] == "ACTIVE"


# --- One company, two awards' compliance periods ---------------------------

SECOND_ISSUANCE_CLOCK = "2027-01-01T00:00:00.000Z"
TWO_STATES = {"service_area_state_codes": ["MS", "LA"]}


def _company_already_inside_another_awards_compliance_period(api):
    """Two awards of one entity, and a company funded under the earlier one."""
    scenario = setup_two_awards_one_entity(
        api,
        clock=AGREEMENT_CLOCK,
        certification_suffix="015",
        first_award_overrides=dict(TWO_STATES),
        second_award_overrides=dict(TWO_STATES),
    )
    second_award = scenario.extras["second_award"]
    setup_certified_project_company(api, scenario)
    scenario.cba = create_cba(api, scenario.cde, scenario.qalicb, scenario.award)
    create_cba(api, scenario.cde, scenario.qalicb, second_award)

    setup_funded_fund(api, scenario)
    scenario.award = read_award(api, scenario.award["id"])
    scenario.qei = issue_qei(api, scenario.cde, scenario.award, scenario.fund)
    scenario.qlici = deploy_qlici(api, scenario.cde, scenario.qei, scenario.qalicb)

    set_clock(api, SECOND_ISSUANCE_CLOCK)
    later_fund = close_fund(api, create_fund(api, legal_name="NMTC Fund B LLC"))
    second_award = read_award(api, second_award["id"])
    scenario.extras["second_award"] = second_award
    scenario.extras["later_fund"] = later_fund
    scenario.extras["second_qei"] = issue_qei(
        api, scenario.cde, second_award, later_fund
    )
    return scenario


def test_a_second_awards_placement_into_the_same_company_is_refused(api):
    """The earlier investment's occupancy interval still contains the new issuance.

    PRD: "A project company may not sit inside two awards' compliance periods at
    once: for every existing non-`VOIDED` investment from a *different* award that
    already funds this business, the interval that starts 30 days before that
    investment's `issued_at` and ends 30 days after that investment's `issued_at`
    advanced by 2555 days must not contain this investment's `issued_at`."

    Design: Difficulty/resource_temporal_overlap/qalicb_compliance_period_occupancy_is_half_open_with_a_30_day_buffer_and_a_same_award_exemption
    """
    scenario = _company_already_inside_another_awards_compliance_period(api)
    second_qei = scenario.extras["second_qei"]

    refused = api.create_qlici(
        create_qlici_payload(
            second_qei["id"], scenario.qalicb["id"], principal_cents=50_000_000
        ),
        scenario.cde_headers,
    )
    validate_error(refused, ApiErrorId.ERR_QALICB_COMPLIANCE_PERIOD_CONFLICT.value, 409)

    row = read_qei(api, second_qei["id"])
    assert_cents(row["uninvested_cash_cents"], 95_000_000, "uninvested_cash_cents")
    assert row["deployment_status"] == "ISSUED"

    _rows, meta = validate_paginated(
        api.list_qlicis(make_agency_headers(), params={"qei_id": second_qei["id"]})
    )
    assert meta["total_count"] == 0


def test_a_further_placement_from_the_same_award_is_exempt_from_the_check(api):
    """The occupancy rule looks only at investments of a different award.

    PRD: "The interval's lower bound is inclusive and its upper bound is exclusive,
    and sub-allocations funded from the *same* award are exempt from the check
    entirely; a collision is `ERR_QALICB_COMPLIANCE_PERIOD_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/qalicb_compliance_period_occupancy_is_half_open_with_a_30_day_buffer_and_a_same_award_exemption
    """
    scenario = _company_already_inside_another_awards_compliance_period(api)

    placed = validate_success(
        api.create_qlici(
            create_qlici_payload(
                scenario.qei["id"],
                scenario.qalicb["id"],
                loan_class="B",
                principal_cents=5_000_000,
            ),
            scenario.cde_headers,
        ),
        201,
    )
    assert_cents(
        placed["outstanding_principal_cents"], 5_000_000, "outstanding_principal_cents"
    )

    assert_cents(
        read_qei(api, scenario.qei["id"])["uninvested_cash_cents"],
        5_000_000,
        "uninvested_cash_cents",
    )
    assert read_qalicb(api, scenario.qalicb["id"])["funding_qlici_count"] == 2
