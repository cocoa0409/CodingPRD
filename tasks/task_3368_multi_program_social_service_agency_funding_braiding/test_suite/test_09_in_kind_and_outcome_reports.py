"""In-kind contributions, match credit and funder outcome reporting."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, set_clock,
    create_funder, create_program, create_grant, record_in_kind, open_outcome_report,
    setup_landscape, setup_match_eligible_grant, setup_donor_window_scenario,
    setup_outcome_window, ApiErrorId, PROGRAM, COMPLIANCE,
)


def test_in_kind_hours_rolling_seven_day_window_blocks_adjacent_repeat_donor():
    """PRD §3.8: "the sum of `hours` for the same `donor_reference` across the
    rolling seven-day window ending at the donation date must not exceed 40
    hours, and a record that would push it over is refused with
    `ERR_INKIND_HOURS_EXCEEDED` (HTTP 422)."

    Design: Corner/calculations/in_kind_hours_rolling_seven_day_window_blocks_adjacent_repeat_donor
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_donor_window_scenario(hours_first=40, donor_reference="PARISH-01",
                                      clock="2026-09-01T00:00:00Z")

    refused = api_client.create_in_kind_donation(
        {"grant_id": ctx["grant"]["id"], "donor_type": "PARISH",
         "donor_reference": "PARISH-01", "donation_date": "2026-09-07T00:00:00Z",
         "hours": 1, "valuation_method": "APPRAISAL", "rate_cents": 3000},
        PROGRAM,
    )
    validate_error(refused, ApiErrorId.ERR_INKIND_HOURS_EXCEEDED)

    aged_out = api_client.create_in_kind_donation(
        {"grant_id": ctx["grant"]["id"], "donor_type": "PARISH",
         "donor_reference": "PARISH-01", "donation_date": "2026-09-09T00:00:00Z",
         "hours": 1, "valuation_method": "APPRAISAL", "rate_cents": 3000},
        PROGRAM,
    )
    validate_success(aged_out, expected_status=201)


def test_irs_standard_rate_valuation_must_equal_3390():
    """PRD §3.8: "when `valuation_method` is `IRS_STANDARD_RATE`, the
    `rate_cents` supplied must equal exactly 3390 — the IRS volunteer hour rate
    of $33.90 — and any other figure is refused with
    `ERR_INKIND_VALUATION_INVALID` (HTTP 422)."

    Design: Corner/validations/irs_standard_rate_valuation_must_equal_3390
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_match_eligible_grant()
    grant_id = ctx["grant"]["id"]

    refused = api_client.create_in_kind_donation(
        {"grant_id": grant_id, "donor_type": "VOLUNTEER", "donor_reference": "VOL-7",
         "donation_date": "2026-09-02T00:00:00Z", "hours": 3,
         "valuation_method": "IRS_STANDARD_RATE", "rate_cents": 3000},
        PROGRAM,
    )
    validate_error(refused, ApiErrorId.ERR_INKIND_VALUATION_INVALID)

    accepted = api_client.create_in_kind_donation(
        {"grant_id": grant_id, "donor_type": "VOLUNTEER", "donor_reference": "VOL-8",
         "donation_date": "2026-09-02T00:00:00Z", "hours": 3,
         "valuation_method": "APPRAISAL", "rate_cents": 3000},
        PROGRAM,
    )
    data = validate_success(accepted, expected_status=201)
    assert data["value_cents"] == 9000


def test_match_requirement_unmet_blocks_outcome_report_submission():
    """PRD §3.8: "Before an outcome report for a grant may be submitted, the
    grant's credited in-kind total must stand at or above its
    `matching_requirement_pct` multiplied by its `total_award_cents`; a
    submission attempted below that line is refused with
    `ERR_MATCH_REQUIREMENT_UNMET` (HTTP 422)."

    PRD §3.9: "when the credited total falls short, the report is not advanced
    and lands in `RETURNED` instead."

    Design: Corner/errors/match_requirement_unmet_blocks_outcome_report_submission
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_match_eligible_grant()
    report = open_outcome_report(ctx["grant"]["id"], measure_code="HOUSING_PLACEMENTS",
                                 reporting_period_start="2026-09-01T00:00:00Z",
                                 reporting_period_end="2026-09-30T00:00:00Z",
                                 numerator=4, denominator=10)

    resp = api_client.submit_outcome_report(report["id"], PROGRAM)
    validate_error(resp, ApiErrorId.ERR_MATCH_REQUIREMENT_UNMET)

    listed = get_success_data(
        api_client.list_grant_outcome_reports(ctx["grant"]["id"], COMPLIANCE))
    assert len(listed) == 1
    assert listed[0]["status"] == "RETURNED", (
        "the shortfall does not advance the report to SUBMITTED; it lands in RETURNED"
    )
    assert listed[0]["rate_pct"] is None


def test_outcome_report_create_initializes_draft_with_null_rate():
    """PRD §3.9: "A new report opens in `DRAFT` status with `rate_pct` null."
    PRD §3.9: "Submission is where the rate is computed".

    Design: Corner/endpoints/outcome_report_create_initializes_draft_with_null_rate
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_landscape()
    resp = api_client.create_outcome_report(
        {"grant_id": ctx["grant"]["id"], "measure_code": "HOUSING_PLACEMENTS",
         "reporting_period_start": "2026-09-01T00:00:00Z",
         "reporting_period_end": "2026-09-30T00:00:00Z",
         "numerator": 4, "denominator": 10},
        PROGRAM,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT"
    assert data["rate_pct"] is None, "the rate is not computed until submit"
    assert data["denominator_basis"] == "ALL_SERVED"
    assert data["grant_id"] == ctx["grant"]["id"]
    assert data["measure_code"] == "HOUSING_PLACEMENTS"
    assert data["version"] >= 1


def test_outcome_report_accept_from_draft_returns_invalid_state():
    """PRD §3.9: "Acceptance and rejection belong to a `ComplianceOfficer` and
    are available only on a report in `SUBMITTED` status."
    PRD §3.9: "An operation attempted against a report whose status is not the
    from-state of any transition it may trigger is refused with
    `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/state_machines/outcome_report_accept_from_draft_returns_invalid_state
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_landscape()
    report = open_outcome_report(ctx["grant"]["id"])

    resp = api_client.accept_outcome_report(report["id"], COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    listed = get_success_data(
        api_client.list_grant_outcome_reports(ctx["grant"]["id"], COMPLIANCE))
    assert listed[0]["status"] == "DRAFT"
    assert listed[0]["rate_pct"] is None


def test_outcome_rate_uses_window_denominator_not_the_submitted_denominator_field():
    """PRD §3.9: "The effective denominator is the size of that set."
    PRD §3.9: "When it is below 5, the sample is too small to report a rate at
    all: `rate_pct` is set to null and the report is forced into `RETURNED`
    rather than `SUBMITTED`."

    Design: Corner/calculations/outcome_rate_uses_window_denominator_not_the_submitted_denominator_field
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_landscape(grants=[{"matching_requirement_pct": 0.0}])
    report = open_outcome_report(ctx["grant"]["id"], measure_code="HOUSING_PLACEMENTS",
                                 reporting_period_start="2026-09-01T00:00:00Z",
                                 reporting_period_end="2026-09-30T00:00:00Z",
                                 numerator=12, denominator=10)

    resp = api_client.submit_outcome_report(report["id"], PROGRAM)
    data = validate_success(resp)
    assert data["status"] == "RETURNED"
    assert data["rate_pct"] is None
    assert data["numerator"] == 12
    assert data["denominator"] == 10, (
        "the input field is echoed but never used as the rate denominator"
    )


def test_outcome_report_closed_interval_requires_one_day_gap():
    """PRD §3.9: "Unlike the half-open windows used for authorizations, these
    intervals are closed and carry a mandatory one-day gap: an existing report
    whose `reporting_period_end` equals the new report's
    `reporting_period_start` is an overlap, and the attempt is refused with
    `ERR_OUTCOME_PERIOD_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/outcome_report_closed_interval_requires_one_day_gap
    """
    set_clock("2026-10-02T00:00:00Z")
    funder = create_funder(name="FED", funder_type="FEDERAL",
                           allow_faith_based_activity=False,
                           requires_time_and_effort_documentation=True,
                           max_admin_rate_pct=0.25, fiscal_year_start_month=10)
    program = create_program(name="COUNSELING_PGM", service_domain="COUNSELING",
                             capacity_slots=40, match_eligible=False)
    grant = create_grant(funder["id"], program["id"], grant_code="G1",
                         total_award_cents=500000, admin_rate_pct=0.05,
                         matching_requirement_pct=0.0, restricted_purpose="CLINICAL_COUNSELING",
                         period_start="2026-01-01T00:00:00Z",
                         period_end="2027-12-31T00:00:00Z")
    open_outcome_report(grant["id"], measure_code="COUNSELING_COMPLETION",
                        reporting_period_start="2026-10-01T00:00:00Z",
                        reporting_period_end="2026-10-31T00:00:00Z",
                        numerator=12, denominator=30)

    abutting = api_client.create_outcome_report(
        {"grant_id": grant["id"], "measure_code": "COUNSELING_COMPLETION",
         "reporting_period_start": "2026-10-31T00:00:00Z",
         "reporting_period_end": "2026-12-15T00:00:00Z",
         "numerator": 5, "denominator": 20},
        PROGRAM,
    )
    validate_error(abutting, ApiErrorId.ERR_OUTCOME_PERIOD_OVERLAP)

    spaced = api_client.create_outcome_report(
        {"grant_id": grant["id"], "measure_code": "COUNSELING_COMPLETION",
         "reporting_period_start": "2026-11-01T00:00:00Z",
         "reporting_period_end": "2026-11-30T00:00:00Z",
         "numerator": 5, "denominator": 20},
        PROGRAM,
    )
    accepted = validate_success(spaced, expected_status=201)

    rows = get_success_data(api_client.list_grant_outcome_reports(grant["id"], PROGRAM))
    assert len(rows) == 2, "the abutting request created no row"
    assert accepted["id"] in [row["id"] for row in rows]


def test_in_kind_credit_ceiling_remaining_requirement_and_valuation_branch():
    """PRD §3.8: "the per-hour value credited is the lower of its `rate_cents`
    and the grant's `max_in_kind_rate_cents`; the resulting `value_cents` is the
    hours multiplied by that credited hourly value, rounded half up to whole
    cents."
    PRD §3.8: "The new contribution's `match_credit_cents` is the smaller of its
    computed value and the remaining requirement, so a grant whose requirement
    is already satisfied credits nothing further to later donations even though
    those donations still have value."

    Design: Difficulty/combinatorial_formula/in_kind_credit_ceiling_remaining_requirement_and_valuation_branch
    """
    set_clock("2026-10-02T00:00:00Z")
    ctx = setup_match_eligible_grant()
    grant_id = ctx["grant"]["id"]

    don_1 = record_in_kind(grant_id, donor_type="PARISH", donor_reference="PARISH-01",
                           donation_date="2026-10-02T00:00:00Z", hours=12,
                           valuation_method="IRS_STANDARD_RATE", rate_cents=3390)
    set_clock("2026-10-03T00:00:00Z")
    don_2 = record_in_kind(grant_id, donor_type="VOLUNTEER", donor_reference="VOL-01",
                           donation_date="2026-10-03T00:00:00Z", hours=6,
                           valuation_method="APPRAISAL", rate_cents=3000)
    set_clock("2026-10-04T00:00:00Z")
    don_3 = record_in_kind(grant_id, donor_type="VOLUNTEER", donor_reference="VOL-02",
                           donation_date="2026-10-04T00:00:00Z", hours=10,
                           valuation_method="APPRAISAL", rate_cents=3000)

    assert don_1["value_cents"] == 36000, "12 * min(3390, 3000) = 36000"
    assert don_1["uncapped_value_cents"] == 40680, "the raw rate would have given 40680"
    assert don_1["match_credit_cents"] == 36000
    assert don_2["value_cents"] == 18000
    assert don_2["match_credit_cents"] == 14000, "capped by the remaining requirement"
    assert don_3["value_cents"] == 30000
    assert don_3["match_credit_cents"] == 0, "the requirement is already satisfied"
    assert (don_1["match_credit_cents"] + don_2["match_credit_cents"]
            + don_3["match_credit_cents"]) == 50000, (
        "the credited total equals round_half_up(0.25 * 200000)"
    )
