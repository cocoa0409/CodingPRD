"""Resource temporal overlap: three calendars with three different semantics.

A program's data windows are half-open and may touch, an organisation's fee
schedule windows are closed and may not even touch, and a verifier's fieldwork
calendar is counted after each existing window is widened by a two-day buffer.
"""

from test_helpers import (
    ApiErrorId,
    EngagementStatus,
    FeeScheduleStatus,
    REGULATOR_HEADERS,
    SubmissionStatus,
    VERIFIER_USER_ID,
    assert_engagement,
    assert_fee_schedule,
    assert_report,
    assert_reporting_period,
    assert_weight,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Reporting periods: half-open data windows, so touching is legal
# ---------------------------------------------------------------------------
def _program_with_a_first_half_period(api):
    """A CA program holding one period whose data window runs to 2026-07-01."""
    program = fx.make_deep_ca_program(api)
    period = fx.make_reporting_period(
        api,
        program["id"],
        period_label="CA-2026-H1",
        data_start="2026-01-01",
        data_end="2026-07-01",
        submission_open="2026-08-01T00:00:00Z",
        submission_deadline="2026-09-30T23:59:59Z",
    )
    assert_reporting_period(period, data_start="2026-01-01", data_end="2026-07-01")
    return {"program": program, "first": period}


def test_a_period_starting_where_another_ends_is_accepted(api):
    """Two data windows that merely touch are not an overlap.

    The second period starts on the very day the first one ends, and because the
    window is inclusive at its start and exclusive at its end the two share no day
    at all, so both rows live in the same program.

    Design: Difficulty/resource_temporal_overlap/reporting_period_half_open_windows_allow_touching
    """
    built = _program_with_a_first_half_period(api)

    second = validate_success(
        api.create_reporting_period(
            built["program"]["id"],
            f.reporting_period_payload(
                period_label="CA-2026-H2",
                data_start="2026-07-01",
                data_end="2027-01-01",
                submission_open="2026-08-15T00:00:00Z",
                submission_deadline="2026-09-30T23:59:59Z",
            ),
            REGULATOR_HEADERS,
        ),
        201,
    )

    assert_reporting_period(second, data_start="2026-07-01", data_end="2027-01-01")
    assert second["data_start"] == built["first"]["data_end"]
    periods, meta = validate_paginated(
        api.list_reporting_periods(built["program"]["id"], REGULATOR_HEADERS)
    )
    assert meta["total_count"] == 2
    assert {row["period_label"] for row in periods} == {"CA-2026-H1", "CA-2026-H2"}


def test_a_period_straddling_two_windows_is_refused_while_the_far_end_still_touches(api):
    """A window that genuinely intersects is refused; the far-end touch is not.

    The straddling window covers days belonging to both existing periods and is
    rejected without leaving a row, while a period beginning exactly where the
    second one ends is accepted, leaving three rows in the program.

    Design: Difficulty/resource_temporal_overlap/reporting_period_half_open_windows_allow_touching
    """
    built = _program_with_a_first_half_period(api)
    fx.make_reporting_period(
        api,
        built["program"]["id"],
        period_label="CA-2026-H2",
        data_start="2026-07-01",
        data_end="2027-01-01",
        submission_open="2026-08-15T00:00:00Z",
        submission_deadline="2026-09-30T23:59:59Z",
    )

    validate_error(
        api.create_reporting_period(
            built["program"]["id"],
            f.reporting_period_payload(
                period_label="CA-2026-MID",
                data_start="2026-06-01",
                data_end="2026-12-01",
                submission_open="2026-08-15T00:00:00Z",
                submission_deadline="2026-09-30T23:59:59Z",
            ),
            REGULATOR_HEADERS,
        ),
        ApiErrorId.PERIOD_WINDOW_OVERLAP,
        409,
    )

    far = validate_success(
        api.create_reporting_period(
            built["program"]["id"],
            f.reporting_period_payload(
                period_label="CA-2027-H1",
                data_start="2027-01-01",
                data_end="2027-07-01",
                submission_open="2027-08-01T00:00:00Z",
                submission_deadline="2027-09-30T23:59:59Z",
            ),
            REGULATOR_HEADERS,
        ),
        201,
    )
    assert_reporting_period(far, data_start="2027-01-01")

    periods, meta = validate_paginated(
        api.list_reporting_periods(built["program"]["id"], REGULATOR_HEADERS)
    )
    assert meta["total_count"] == 3
    assert "CA-2026-MID" not in {row["period_label"] for row in periods}


# ---------------------------------------------------------------------------
# Fee schedules: closed effective windows, so even touching is refused
# ---------------------------------------------------------------------------
GLASS_BAND = [f.material_rate("GLASS", 0, None, 9)]


def _pro_with_a_second_half_schedule(api):
    """One organisation holding a closed window from 2026-07-01 to 2026-12-31."""
    program = fx.make_deep_ca_program(api)
    pro = fx.make_pro(api, name="PRO West", contact_email="pro@x.com")
    base = fx.make_fee_schedule(
        api,
        pro,
        program["id"],
        effective_from="2026-07-01",
        effective_to="2026-12-31",
        admin_fee_bps_high=300,
        material_rates=GLASS_BAND,
    )
    assert_fee_schedule(
        base,
        effective_from="2026-07-01",
        effective_to="2026-12-31",
        status=FeeScheduleStatus.DRAFT,
    )
    return {"program": program, "pro": pro, "base": base, "headers": fx.admin(pro)}


def test_a_schedule_window_sharing_one_day_is_refused(api):
    """Sharing the single boundary day is enough to be an overlap.

    The candidate window ends on the day the existing one begins, and because both
    ends of a schedule window are inclusive that one shared day is a collision;
    backing the candidate off by a single day is accepted.

    Design: Difficulty/resource_temporal_overlap/fee_schedule_closed_windows_forbid_touching_and_open_ended_blocks_later
    """
    built = _pro_with_a_second_half_schedule(api)

    validate_error(
        api.create_fee_schedule(
            f.fee_schedule_payload(
                built["pro"]["id"],
                built["program"]["id"],
                effective_from="2026-01-01",
                effective_to="2026-07-01",
                membership_fee_cents=240000,
                admin_fee_bps_high=300,
                material_rates=[f.material_rate("GLASS", 0, None, 8)],
            ),
            built["headers"],
        ),
        ApiErrorId.FEE_SCHEDULE_EFFECTIVE_OVERLAP,
        409,
    )

    earlier = validate_success(
        api.create_fee_schedule(
            f.fee_schedule_payload(
                built["pro"]["id"],
                built["program"]["id"],
                effective_from="2026-01-01",
                effective_to="2026-06-30",
                membership_fee_cents=240000,
                admin_fee_bps_high=300,
                material_rates=[f.material_rate("GLASS", 0, None, 8)],
            ),
            built["headers"],
        ),
        201,
    )
    assert_fee_schedule(
        earlier,
        effective_from="2026-01-01",
        effective_to="2026-06-30",
        status=FeeScheduleStatus.DRAFT,
    )


def test_an_open_ended_schedule_blocks_every_later_window(api):
    """A null end date locks the calendar from its start date onwards.

    The open-ended window is accepted because it begins after the existing closed
    one ends, and it then refuses a window opening five months later, leaving three
    schedules for the pairing.

    Design: Difficulty/resource_temporal_overlap/fee_schedule_closed_windows_forbid_touching_and_open_ended_blocks_later
    """
    built = _pro_with_a_second_half_schedule(api)
    fx.make_fee_schedule(
        api,
        built["pro"],
        built["program"]["id"],
        effective_from="2026-01-01",
        effective_to="2026-06-30",
        membership_fee_cents=240000,
        admin_fee_bps_high=300,
        material_rates=[f.material_rate("GLASS", 0, None, 8)],
    )

    open_ended = validate_success(
        api.create_fee_schedule(
            f.fee_schedule_payload(
                built["pro"]["id"],
                built["program"]["id"],
                effective_from="2027-01-01",
                effective_to=None,
                membership_fee_cents=260000,
                admin_fee_bps_high=300,
                material_rates=[f.material_rate("GLASS", 0, None, 10)],
            ),
            built["headers"],
        ),
        201,
    )
    assert_fee_schedule(open_ended, effective_from="2027-01-01", effective_to=None)

    validate_error(
        api.create_fee_schedule(
            f.fee_schedule_payload(
                built["pro"]["id"],
                built["program"]["id"],
                effective_from="2027-06-01",
                effective_to="2027-12-31",
                membership_fee_cents=270000,
                admin_fee_bps_high=300,
                material_rates=[f.material_rate("GLASS", 0, None, 11)],
            ),
            built["headers"],
        ),
        ApiErrorId.FEE_SCHEDULE_EFFECTIVE_OVERLAP,
        409,
    )

    schedules, meta = validate_paginated(
        api.list_fee_schedules(
            built["headers"],
            {"pro_id": built["pro"]["id"], "state_program_id": built["program"]["id"]},
        )
    )
    assert meta["total_count"] == 3
    assert len(schedules) == 3


# ---------------------------------------------------------------------------
# A verifier's calendar: each open window is widened by two days on each side
# ---------------------------------------------------------------------------
def _verifier_holding_two_open_engagements(api):
    """Three submitted reports, two of them already assigned to the same verifier."""
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    program = fx.make_deep_ca_program(api)
    periods = [
        fx.make_reporting_period(
            api,
            program["id"],
            period_label=label,
            data_start=start,
            data_end=end,
            submission_open="2026-08-01T00:00:00Z",
            submission_deadline="2026-09-30T23:59:59Z",
        )
        for label, start, end in (
            ("CA-2026-P1", "2026-01-01", "2026-04-01"),
            ("CA-2026-P2", "2026-04-01", "2026-07-01"),
            ("CA-2026-P3", "2026-07-01", "2027-01-01"),
        )
    ]
    pro = fx.make_pro(api, name="PRO West", contact_email="pro@x.com")
    built = fx.determined_producer(
        api,
        components=[f.component_payload(material_type="GLASS", unit_weight_grams=50)],
        sku_kwargs=dict(name="Load Jar", product_category="HOUSEHOLD_CHEM"),
        legal_name="Verifier Load Co",
        annual_gross_revenue_usd=8000000,
        contact_email="pv@x.com",
    )
    producer, sku = built["producer"], built["sku"]
    schedule = fx.published_fee_schedule(
        api,
        pro,
        program["id"],
        effective_from="2026-01-01",
        effective_to=None,
        admin_fee_bps_high=300,
        material_rates=GLASS_BAND,
    )
    registration = fx.active_registration(api, producer, program["id"])
    fx.paid_membership(api, producer, registration, pro, schedule)

    reports = []
    for period in periods:
        report = fx.make_report(api, producer, registration, period)
        fx.add_line(api, producer, report, sku, 110)
        reports.append(fx.submit_report(api, producer, report))

    officer_headers = fx.officer(producer)
    registration_now = validate_success(
        api.get_registration(registration["id"], officer_headers)
    )
    assert_weight(registration_now["reported_weight_kg_ytd"], 16.500, "reported_weight_kg_ytd")

    first = fx.assign_engagement(api, reports[0], VERIFIER_USER_ID, "2026-09-08", "2026-09-10")
    second = fx.assign_engagement(api, reports[1], VERIFIER_USER_ID, "2026-09-14", "2026-09-16")
    assert_engagement(first, status=EngagementStatus.ASSIGNED)
    assert_engagement(second, status=EngagementStatus.ASSIGNED)

    return {
        "registration": registration,
        "reports": reports,
        "officer_headers": officer_headers,
    }


def test_a_window_inside_both_buffers_exceeds_the_verifier_capacity(api):
    """Two buffered windows already cover the requested days.

    The requested window touches neither raw window, but widening each existing
    window by two days at each end makes it intersect both of them, so the count of
    open overlapping engagements reaches two and the assignment is refused.

    Design: Difficulty/resource_temporal_overlap/verifier_buffered_aggregate_capacity_across_reports
    """
    built = _verifier_holding_two_open_engagements(api)
    third = built["reports"][2]

    validate_error(
        api.create_engagement(
            f.engagement_payload(third["id"], VERIFIER_USER_ID, "2026-09-12", "2026-09-13"),
            REGULATOR_HEADERS,
        ),
        ApiErrorId.VERIFIER_CAPACITY_EXCEEDED,
        409,
    )

    report = validate_success(api.get_report(third["id"], built["officer_headers"]))
    assert_report(report, submission_status=SubmissionStatus.SUBMITTED)
    engagements, meta = validate_paginated(
        api.list_engagements(REGULATOR_HEADERS, {"packaging_report_id": third["id"]})
    )
    assert engagements == [] and meta["total_count"] == 0


def test_a_window_clear_of_both_buffers_is_assigned(api):
    """Four days past the last fieldwork day the calendar is free again.

    The requested window lies beyond both widened windows, so the count is zero and
    the third report moves into verification while the year-to-date tonnage of the
    registration is untouched by the assignment.

    Design: Difficulty/resource_temporal_overlap/verifier_buffered_aggregate_capacity_across_reports
    """
    built = _verifier_holding_two_open_engagements(api)
    third = built["reports"][2]

    engagement = validate_success(
        api.create_engagement(
            f.engagement_payload(third["id"], VERIFIER_USER_ID, "2026-09-22", "2026-09-23"),
            REGULATOR_HEADERS,
        ),
        201,
    )
    assert_engagement(
        engagement,
        status=EngagementStatus.ASSIGNED,
        round_index=1,
        verifier_user_id=VERIFIER_USER_ID,
        fieldwork_start="2026-09-22",
        fieldwork_end="2026-09-23",
        opinion=None,
        findings_note=None,
        opinion_issued_at=None,
    )

    report = validate_success(api.get_report(third["id"], built["officer_headers"]))
    assert_report(report, submission_status=SubmissionStatus.UNDER_VERIFICATION)
    registration = validate_success(
        api.get_registration(built["registration"]["id"], built["officer_headers"])
    )
    assert_weight(registration["reported_weight_kg_ytd"], 16.500, "reported_weight_kg_ytd")
