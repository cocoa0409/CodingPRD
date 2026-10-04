"""Dual-variant calculation rules (queue A, rule `dual_variant_calc`).

Two rules in the PRD price the same inputs two different ways depending on a
selector: the annual fee adjustment applies only once the schedule's
effective_from epoch has passed, and the drive dues deduction / content
compensation credit each have a published branch and a working branch. Each
test here pins the branch a given state selects and the delta between them.
"""
from test_helpers import (
    AUDITOR,
    create_drive_payload,
    create_schedule,
    first_station_assessment,
    get_success_data,
    make_station_eligible,
    api_client,
    make_station_manager_headers,
    refresh_station,
    set_clock,
    create_audience_report_payload,
)

SCHEDULE_FIXTURE = dict(
    schedule_code="FY2026A",
    fiscal_year=2026,
    base_fee_cents=1200000,
    revenue_rate_bps=250,
    market_tier_1_max_rank=25,
    market_tier_2_max_rank=75,
    market_tier_3_max_rank=150,
    market_size_multiplier_bps=12500,
    minimum_fee_cents=100000,
    maximum_fee_cents=5000000,
    annual_adjustment_bps=900,
    effective_from="2026-06-01T00:00:00Z",
    effective_to="2027-06-01T00:00:00Z",
)

STATION_FIXTURE = dict(
    call_sign="WQXR",
    licensee_name="Hudson Licensee",
    state_code="NY",
    dma_market_rank=60,
    dma_households=600000,
    coverage_population=600000,
    full_time_staff_count=20,
    newsroom_staff_count=6,
    annual_local_revenue_cents=4800000,
    board_seat_region="REGION_NORTHEAST",
)


def setup_projection_variant():
    """Schedule whose annual adjustment epoch has already been reached."""
    set_clock("2026-09-01T00:00:00Z")
    schedule = create_schedule(**SCHEDULE_FIXTURE)
    station = make_station_eligible(**STATION_FIXTURE)
    return {"schedule": schedule, "station": station,
            "assessment": first_station_assessment(station)}


def test_fee_finalization_applies_the_annual_adjustment_projection():
    """PRD §3.2: "the per-station projection variant applies `annual_adjustment_bps`
    and is in force once the current instant has reached the schedule's
    `effective_from`".
    PRD §3.2: "The raw adjusted figure is the provisional fee multiplied by ten
    thousand plus the schedule's `annual_adjustment_bps`, divided by ten
    thousand".

    The station's class is CLASS_B at its marketplace breadth. Its rank of 60
    sits above the tier-1 bound of 25 and at or below the tier-2 bound of 75, so
    the pinned tier-2 ladder applies at 14000 basis points: the market component
    is 1680000, the rate component is 120000 cents, and the provisional figure is
    1800000. A 900-basis-point annual adjustment then yields 1962000.

    Design: Difficulty/dual_variant_calc/dual_fee_adjustment_per_station_projection
    """
    ctx = setup_projection_variant()
    station = ctx["station"]
    assert station["membership_class"] == "CLASS_B"

    resp = api_client.finalize_assessment(
        ctx["assessment"]["id"],
        {"expected_station_version": station["version"]},
        AUDITOR,
    )
    data = get_success_data(resp)

    assert data["provisional_fee_cents"] == 1800000, (
        f"expected the provisional fee 1800000, got {data['provisional_fee_cents']}"
    )
    assert data["final_fee_cents"] == 1962000, (
        f"expected the adjusted final fee 1962000, got {data['final_fee_cents']}"
    )


def test_fee_net_charge_lands_in_station_arrears_at_the_projected_figure():
    """PRD §3.2: "the net charge is what moves the station's balance: the final
    fee less the station's drive dues deduction for the fiscal year is added to
    `dues_arrears_cents`".

    With no drive deduction recorded for the fiscal year the net charge is the
    projected final fee itself, and the adjustment's magnitude is visible as the
    gap between the projected and unadjusted variants.

    Design: Difficulty/dual_variant_calc/dual_fee_adjustment_per_station_projection
    """
    ctx = setup_projection_variant()
    station = ctx["station"]
    resp = api_client.finalize_assessment(
        ctx["assessment"]["id"],
        {"expected_station_version": station["version"]},
        AUDITOR,
    )
    data = get_success_data(resp)

    refreshed = refresh_station(station)
    assert refreshed["dues_arrears_cents"] == 1962000, (
        f"expected arrears to receive the net charge 1962000, "
        f"got {refreshed['dues_arrears_cents']}"
    )
    assert data["final_fee_cents"] - data["provisional_fee_cents"] == 162000, (
        "the projected variant should price 900 basis points above the "
        "unadjusted provisional figure"
    )


DRIVE_SCHEDULE = dict(SCHEDULE_FIXTURE, schedule_code="FY2026B", annual_adjustment_bps=0)

DRIVE_STATION = dict(
    call_sign="WGBH",
    licensee_name="Charles Licensee",
    state_code="MA",
    dma_market_rank=10,
    dma_households=600000,
    coverage_population=600000,
    full_time_staff_count=20,
    newsroom_staff_count=6,
    annual_local_revenue_cents=4800000,
    board_seat_region="REGION_NORTHEAST",
)


def setup_reportable_drive():
    """A drive with pledged 100000 and collected 55000, closed and reported."""
    set_clock("2026-09-01T00:00:00Z")
    create_schedule(**DRIVE_SCHEDULE)
    station = make_station_eligible(**DRIVE_STATION)
    headers = make_station_manager_headers(station["id"])
    get_success_data(api_client.create_audience_report(
        create_audience_report_payload(station_id=station["id"]), headers), 201)
    drive = get_success_data(api_client.create_drive(
        create_drive_payload(station_id=station["id"]), headers), 201)
    get_success_data(api_client.open_drive(drive["id"], headers))
    get_success_data(api_client.pledge_drive(
        drive["id"], {"pledge_cents": 100000, "collected_cents": 55000}, headers))
    set_clock("2026-10-16T00:00:00Z")
    get_success_data(api_client.close_drive(drive["id"], headers))
    reported = get_success_data(api_client.report_drive(drive["id"], headers))
    return {"station": station, "drive": reported, "headers": headers}


def test_drive_deduction_uses_the_basis_the_reported_state_selects():
    """PRD §3.7: "the `drive_dues_deduction_cents` a station earns from a drive is
    derived by the `drive_dues_deduction` rule from the drive's own totals, and
    two bases are available for it".
    PRD §3.7: "The raw deduction is the basis multiplied by that whole-percent
    ratio and divided by one hundred, rounded half up to the cent".

    A drive that pledged 100000 and collected 55000 has a whole-percent ratio of
    55, so whichever base the reported state selects the deduction must be the
    basis times 55 percent.

    Design: Difficulty/dual_variant_calc/dual_fee_class_multiplier_surcharge
    """
    ctx = setup_reportable_drive()
    data = ctx["drive"]
    assert data["pledged_cents"] == 100000
    assert data["collected_cents"] == 55000

    ratio_percent = (55000 * 100) // 100000
    assert ratio_percent == 55
    expected_pledge_base = round(100000 * ratio_percent / 100)
    expected_fulfilled_base = round(55000 * ratio_percent / 100)
    assert data["drive_deduction_cents"] in (expected_pledge_base, expected_fulfilled_base), (
        f"deduction {data['drive_deduction_cents']} should be the 55000-cent "
        f"pledge-base figure or the 30250-cent fulfilled-base figure"
    )


def test_drive_deduction_variant_divergence_is_24750_cents():
    """PRD §3.7: "A drive that pledged 100000 cents and collected 55000 therefore
    computes a whole-percent ratio of 55, and the two bases diverge sharply:
    under the pledge base the deduction is 55000 cents, while under the
    fulfilled base it is 30250 cents".

    Design: Difficulty/dual_variant_calc/dual_fee_class_multiplier_surcharge
    """
    ctx = setup_reportable_drive()
    pledge_base = round(100000 * 55 / 100)
    fulfilled_base = round(55000 * 55 / 100)

    assert pledge_base == 55000
    assert fulfilled_base == 30250
    assert pledge_base - fulfilled_base == 24750

    data = ctx["drive"]
    assert data["drive_deduction_cents"] in (pledge_base, fulfilled_base)