"""Values sitting exactly on a threshold, and the value one step past it.

Every comparison in this system has a declared inclusive or exclusive side.  Each
test here places a quantity precisely on a boundary and then one unit beyond it,
so an implementation that reversed a comparison or rounded the wrong way is
caught by the pair rather than by either half alone.
"""
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_MEETING_SEPARATION_VIOLATION
from test_helpers.assertions import assert_fields, assert_null_fields, assert_ratio_four_dp
from test_helpers.test_users import ADMIN


# --------------------------------------------------------------------------
# A weighted support figure that rounds onto the threshold, and one below it
# --------------------------------------------------------------------------
def _drive_signed_by_its_largest_property(api, name, revenues):
    """Build a three-property district whose assessable basis is exactly
    100000000 cents, then sign and tally its formation drive with the largest
    property alone."""
    fx.pin_clock_to_origin(api)
    ctx = fx.create_district(api, name=name, included_zones=["ZONE_CORE"])
    for index, (legal_name, room_count, revenue) in enumerate(revenues, start=1):
        fx.add_business(
            api,
            ctx,
            f.lodging_business_payload(
                ctx.d_id,
                legal_name=legal_name,
                room_count=room_count,
                prior_year_gross_room_revenue_cents=revenue,
            ),
            f"b{index}_id",
        )
    fx.open_formation_drive(api, ctx)
    fx.sign(api, ctx, "b1_id")
    fx.tally(api, ctx)
    return ctx


BAYFRONT_ROLL = [
    ("Bayfront Tower Hotel", 180, 59995000),
    ("Bayfront Court Inn", 90, 40000000),
    ("Bayfront Annex", 30, 5000),
]

NORTHSHORE_ROLL = [
    ("Northshore Tower Hotel", 180, 59994000),
    ("Northshore Court Inn", 90, 40000000),
    ("Northshore Annex", 30, 6000),
]


def test_weighted_support_that_rounds_up_onto_the_threshold_qualifies(api):
    """59995000 over 100000000 is 0.59995, which rounds half up to 0.6000 and so
    lands exactly on the 0.6000 threshold that the inclusive comparison accepts.

    PRD 3.2: "A drive qualifies when weighted_support_pct is greater than or
    equal to required_weighted_pct and headcount_support_pct is greater than or
    equal to required_headcount_pct. Both comparisons are inclusive, so support
    landing exactly on a threshold qualifies."

    Design: Difficulty/boundary_precision_check/petition_weighted_support_rounds_onto_the_threshold_and_qualifies
    """
    ctx = _drive_signed_by_its_largest_property(
        api, "Bayfront Tourism Improvement District", BAYFRONT_ROLL
    )

    drive = validate_success(api.get_petition_drive(ctx.pd_id))
    assert_fields(
        drive,
        assessable_basis_snapshot_cents=100000000,
        signed_basis_cents=59995000,
        status="QUALIFIED",
        short_reason="NONE",
    )
    assert_ratio_four_dp(drive["weighted_support_pct"], 0.6000, "weighted_support_pct")
    assert_ratio_four_dp(drive["required_weighted_pct"], 0.6000, "required_weighted_pct")


def test_weighted_support_one_thousandth_lower_rounds_below_and_falls_short(api):
    """59994000 over 100000000 is 0.59994, which rounds to 0.5999 and misses the
    threshold, so the weighted test is the one reported as failed.

    PRD 3.2: "the revenue-weighted test is evaluated first, so short_reason is
    WEIGHTED_BELOW_THRESHOLD whenever weighted_support_pct is below
    required_weighted_pct".

    Design: Difficulty/boundary_precision_check/petition_weighted_support_rounds_onto_the_threshold_and_qualifies
    """
    ctx = _drive_signed_by_its_largest_property(
        api, "Northshore Tourism Improvement District", NORTHSHORE_ROLL
    )

    drive = validate_success(api.get_petition_drive(ctx.pd_id))
    assert_fields(
        drive,
        assessable_basis_snapshot_cents=100000000,
        signed_basis_cents=59994000,
        status="SHORT_OF_THRESHOLD",
        short_reason="WEIGHTED_BELOW_THRESHOLD",
    )
    assert_ratio_four_dp(drive["weighted_support_pct"], 0.5999, "weighted_support_pct")


def test_a_formation_drive_pins_the_headcount_requirement_to_zero(api):
    """A single signature out of three properties is a headcount of 0.3333, which
    binds on nothing because a formation drive snapshots the requirement as
    0.0000, and the failing formation branch is what fails the district.

    PRD 3.2: "For a formation drive, required_weighted_pct is copied from the
    district's formation_threshold_pct and required_headcount_pct is snapshotted
    as 0.0000, so that only the revenue-weighted test binds."

    Design: Difficulty/boundary_precision_check/petition_weighted_support_rounds_onto_the_threshold_and_qualifies
    """
    qualified = _drive_signed_by_its_largest_property(
        api, "Bayfront Tourism Improvement District", BAYFRONT_ROLL
    )
    drive = validate_success(api.get_petition_drive(qualified.pd_id))
    assert_ratio_four_dp(drive["required_headcount_pct"], 0.0000, "required_headcount_pct")
    district = validate_success(api.get_district(qualified.d_id))
    assert_fields(district, status="PETITION_CIRCULATING")

    short = _drive_signed_by_its_largest_property(
        api, "Northshore Tourism Improvement District", NORTHSHORE_ROLL
    )
    failed_drive = validate_success(api.get_petition_drive(short.pd_id))
    assert_ratio_four_dp(failed_drive["required_headcount_pct"], 0.0000, "required_headcount_pct")
    failed = validate_success(api.get_district(short.d_id))
    assert_fields(failed, status="FORMATION_FAILED")


# --------------------------------------------------------------------------
# Public meeting separation: exactly 10 whole days, then 9
# --------------------------------------------------------------------------
def _district_with_a_first_public_meeting(api):
    """Schedule one public meeting for 2026-09-10 so later meetings have something
    to be measured against."""
    ctx = fx.active_district(api)
    fx.schedule_transparency_record(
        api,
        ctx,
        key="tr_first",
        record_type="PUBLIC_MEETING",
        fiscal_year=2027,
        scheduled_for="2026-09-10T00:00:00Z",
        required_by="2026-12-31T00:00:00Z",
    )
    return ctx


def _meeting_payload(district_id, scheduled_for):
    return f.transparency_record_payload(
        district_id,
        record_type="PUBLIC_MEETING",
        fiscal_year=2027,
        scheduled_for=scheduled_for,
        required_by="2026-12-31T00:00:00Z",
    )


def test_a_second_meeting_exactly_ten_whole_days_later_is_accepted(api):
    """2026-09-20 is exactly 10 whole days after 2026-09-10, which the rule
    admits.

    PRD 3.9: "two PUBLIC_MEETING records of the same district must have
    scheduled_for instants at least 10 whole days apart. A separation of exactly
    10 days is accepted and 9 days is rejected with
    ERR_MEETING_SEPARATION_VIOLATION."

    Design: Difficulty/boundary_precision_check/public_meeting_separation_of_exactly_ten_days_is_accepted_and_nine_is_not
    """
    ctx = _district_with_a_first_public_meeting(api)

    record = validate_success(
        api.create_transparency_record(
            _meeting_payload(ctx.d_id, "2026-09-20T00:00:00Z"), headers=ADMIN
        ),
        expected_status=201,
    )
    assert_fields(record, status="SCHEDULED", record_type="PUBLIC_MEETING")
    assert_null_fields(record, "noticed_on", "completed_on", "published_on", "document_reference")


def test_a_meeting_only_nine_whole_days_after_another_is_refused(api):
    """2026-09-29 is 9 whole days after the accepted 2026-09-20 meeting, one day
    short of the separation the rule demands.

    PRD 3.9: "A separation of exactly 10 days is accepted and 9 days is rejected
    with ERR_MEETING_SEPARATION_VIOLATION."

    Design: Difficulty/boundary_precision_check/public_meeting_separation_of_exactly_ten_days_is_accepted_and_nine_is_not
    """
    ctx = _district_with_a_first_public_meeting(api)
    validate_success(
        api.create_transparency_record(
            _meeting_payload(ctx.d_id, "2026-09-20T00:00:00Z"), headers=ADMIN
        ),
        expected_status=201,
    )

    response = api.create_transparency_record(
        _meeting_payload(ctx.d_id, "2026-09-29T00:00:00Z"), headers=ADMIN
    )
    validate_error(response, ERR_MEETING_SEPARATION_VIOLATION, expected_status=409)

    rows, meta = validate_paginated(
        api.list_district_transparency_records(ctx.d_id, params={"record_type": "PUBLIC_MEETING"})
    )
    assert meta["total_count"] == 2, f"expected the refused meeting not to be stored: {meta}"


def test_the_separation_rule_is_measured_against_every_earlier_meeting(api):
    """2026-09-30 clears 2026-09-20 by exactly 10 days and 2026-09-10 by 20, so it
    is accepted where 2026-09-29 was not, leaving three meetings on the record.

    PRD 3.9: "The rule is scoped to public meetings only, so an annual report may
    be targeted for the same day as a meeting."

    Design: Difficulty/boundary_precision_check/public_meeting_separation_of_exactly_ten_days_is_accepted_and_nine_is_not
    """
    ctx = _district_with_a_first_public_meeting(api)
    validate_success(
        api.create_transparency_record(
            _meeting_payload(ctx.d_id, "2026-09-20T00:00:00Z"), headers=ADMIN
        ),
        expected_status=201,
    )
    validate_error(
        api.create_transparency_record(
            _meeting_payload(ctx.d_id, "2026-09-29T00:00:00Z"), headers=ADMIN
        ),
        ERR_MEETING_SEPARATION_VIOLATION,
        expected_status=409,
    )
    validate_success(
        api.create_transparency_record(
            _meeting_payload(ctx.d_id, "2026-09-30T00:00:00Z"), headers=ADMIN
        ),
        expected_status=201,
    )

    rows, meta = validate_paginated(
        api.list_district_transparency_records(ctx.d_id, params={"record_type": "PUBLIC_MEETING"})
    )
    assert meta["total_count"] == 3, f"expected exactly three meetings: {meta}"

    report = validate_success(
        api.create_transparency_record(
            f.transparency_record_payload(
                ctx.d_id,
                record_type="ANNUAL_REPORT",
                fiscal_year=2027,
                scheduled_for="2026-09-10T00:00:00Z",
                required_by="2026-12-31T00:00:00Z",
            ),
            headers=ADMIN,
        ),
        expected_status=201,
    )
    assert_fields(report, record_type="ANNUAL_REPORT", status="SCHEDULED")


# --------------------------------------------------------------------------
# Efficiency tier: exactly 1500 cents, one cent past it, and no nights at all
# --------------------------------------------------------------------------
def _three_programs_measured_on_the_same_plan(api):
    """Run three programs off one approved plan: one that lands exactly on the
    1500-cent tier edge, one a single cent past it, and one whose only claim is
    rejected so it closes with no verified nights."""
    ctx = fx.statements_filed(api)
    fx.approved_work_plan(api, ctx)
    fx.execute_dmo_agreement(api, ctx)
    fx.create_program(api, ctx)
    fx.create_program(
        api,
        ctx,
        key="mp_edge",
        name="Shoulder Season Paid Search",
        channel="PAID_SEARCH",
        committed_cents=30000,
    )
    fx.create_program(
        api,
        ctx,
        key="mp_over",
        name="Shoulder Season OTA Campaign",
        channel="OTA_CAMPAIGN",
        committed_cents=30020,
    )
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    for key in ("mp_id", "mp_edge", "mp_over"):
        fx.launch_program(api, ctx, program_key=key)
    fx.set_clock(api, "2026-09-25T00:00:00Z")

    fx.submit_claim(
        api,
        ctx,
        business_key="b1_id",
        program_key="mp_id",
        key="rnc_rejected",
        stay_start="2026-09-01T00:00:00Z",
        stay_end="2026-09-08T00:00:00Z",
        room_nights=20,
        attribution_method="LOOKBACK_WINDOW",
    )
    fx.verify_claim(
        api, ctx, claim_key="rnc_rejected", decision="REJECT", rejection_reason="UNVERIFIABLE"
    )
    for program_key, claim_key in (("mp_edge", "rnc_edge"), ("mp_over", "rnc_over")):
        fx.submit_claim(
            api,
            ctx,
            business_key="b1_id",
            program_key=program_key,
            key=claim_key,
            stay_start="2026-09-01T00:00:00Z",
            stay_end="2026-09-08T00:00:00Z",
            room_nights=20,
        )
        fx.verify_claim(api, ctx, claim_key=claim_key, decision="ALLOW", verified_room_nights=20)

    for key in ("mp_id", "mp_edge", "mp_over"):
        fx.close_program(api, ctx, program_key=key)
    return ctx


def test_a_gross_cost_of_exactly_1500_cents_is_tier_efficient(api):
    """30000 over 20 verified nights is exactly 1500, the inclusive top of the
    efficient band, so the DMO absorbs the 0.40 share.

    PRD 3.8: "the tier is read off that gross figure: TIER_EFFICIENT at 1500 cents
    or below, otherwise TIER_STANDARD at 3000 cents or below, otherwise
    TIER_MARGINAL at 6000 cents or below, otherwise TIER_UNPRODUCTIVE."

    Design: Difficulty/boundary_precision_check/program_efficiency_tier_edges_at_1500_and_the_zero_verified_night_null_path
    """
    ctx = _three_programs_measured_on_the_same_plan(api)

    program = validate_success(api.get_marketing_program(ctx.mp_edge, headers=ADMIN))
    assert_fields(
        program,
        status="CLOSED",
        verified_room_nights=20,
        gross_cost_per_room_night_cents=1500,
        efficiency_tier="TIER_EFFICIENT",
        dmo_cost_share_cents=12000,
        net_district_cost_cents=18000,
        net_cost_per_room_night_cents=900,
        performance_flag="MEETS_BENCHMARK",
    )
    assert_ratio_four_dp(program["performance_index"], 2.7778, "performance_index")


def test_a_gross_cost_one_cent_over_1500_falls_into_tier_standard(api):
    """30020 over the same 20 nights is 1501, one cent past the efficient band, so
    the share drops from 0.40 to 0.25 and the net cost per night rounds 1125.75 up
    to 1126.

    PRD 3.8: "net_cost_per_room_night_cents is net_district_cost_cents divided by
    the verified night count, rounded half up to a whole cent, and
    performance_index is a benchmark of 2500 cents divided by
    net_cost_per_room_night_cents, rounded half up to four decimal places."

    Design: Difficulty/boundary_precision_check/program_efficiency_tier_edges_at_1500_and_the_zero_verified_night_null_path
    """
    ctx = _three_programs_measured_on_the_same_plan(api)

    program = validate_success(api.get_marketing_program(ctx.mp_over, headers=ADMIN))
    assert_fields(
        program,
        status="CLOSED",
        verified_room_nights=20,
        gross_cost_per_room_night_cents=1501,
        efficiency_tier="TIER_STANDARD",
        dmo_cost_share_cents=7505,
        net_district_cost_cents=22515,
        net_cost_per_room_night_cents=1126,
        performance_flag="MEETS_BENCHMARK",
    )
    assert_ratio_four_dp(program["performance_index"], 2.2202, "performance_index")


def test_zero_verified_nights_publish_null_costs_rather_than_zero(api):
    """The program whose only claim was rejected closes with no verified nights, so
    both cost-per-night fields are null rather than 0 and the index is 0.0000.

    PRD 3.8: "A program that closes with no verified nights therefore publishes
    null costs per room night, TIER_UNPRODUCTIVE, an index of 0.0000 and the
    UNDERPERFORMING flag."

    Design: Difficulty/boundary_precision_check/program_efficiency_tier_edges_at_1500_and_the_zero_verified_night_null_path
    """
    ctx = _three_programs_measured_on_the_same_plan(api)

    program = validate_success(api.get_marketing_program(ctx.mp_id, headers=ADMIN))
    assert_fields(
        program,
        status="CLOSED",
        verified_room_nights=0,
        efficiency_tier="TIER_UNPRODUCTIVE",
        dmo_cost_share_cents=0,
        net_district_cost_cents=62000,
        performance_flag="UNDERPERFORMING",
    )
    assert_null_fields(program, "gross_cost_per_room_night_cents", "net_cost_per_room_night_cents")
    assert_ratio_four_dp(program["performance_index"], 0.0000, "performance_index")

    claim = validate_success(api.get_room_night_claim(ctx.rnc_rejected, headers=ADMIN))
    assert_fields(claim, status="REJECTED", rejection_reason="UNVERIFIABLE")
    assert_null_fields(claim, "verified_room_nights")
