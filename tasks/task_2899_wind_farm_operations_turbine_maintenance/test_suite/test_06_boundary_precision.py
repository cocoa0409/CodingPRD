"""Figures probed one tick either side of the exact boundary that decides them."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.assertions import assert_cents, assert_four_dp, assert_two_dp
from test_helpers.constants import (
    AGREEMENT_IN_SETTLEMENT,
    BAND_CRITICAL,
    BAND_HIGH,
    BAND_LOW,
    BAND_MEDIUM,
    BLADE_OPEN,
    CERT_GWO_BASIC,
    DAMAGE_CRACK_TRANSVERSE,
    DAMAGE_LEADING_EDGE_EROSION,
    DAMAGE_LIGHTNING_STRIKE,
    INSPECTION_DRONE,
    INSPECTION_GROUND_OPTICAL,
    INSPECTION_ROPE_ACCESS,
    WO_DRAFT,
    WORK_TYPE_SCHEDULED_SERVICE,
)
from test_helpers.factories import blade_damage_payload, work_order_payload
from test_helpers.fixtures import (
    post_scada,
    read_turbine,
    setup_blade_band_boundaries,
    setup_lda_boundary_agreements,
    setup_service_due_boundaries,
)
from test_helpers.test_users import (
    ENGINEER_USER_ID,
    make_commercial_headers,
    make_engineer_headers,
    make_planner_headers,
)


def _service_order(api, turbine_id):
    """Attempt a scheduled-service order on ``turbine_id`` as a planner."""
    return api.create_work_order(
        work_order_payload(
            turbine_id,
            work_type=WORK_TYPE_SCHEDULED_SERVICE,
            required_certification=CERT_GWO_BASIC,
            estimated_hours=6,
        ),
        make_planner_headers(),
    )


def test_the_service_creation_gate_refuses_3799_and_admits_exactly_3800(api):
    """One tenth of an operating hour separates a refusal from an accepted order.

    The contract states: "`service_due_operating_hours` is the turbine's
    `last_service_operating_hours` plus the model's `service_interval_hours`."  Of
    the creation gate it states: "It may be raised only once the turbine's
    `operating_hours` has reached the point 200 operating hours before its
    `service_due_operating_hours` — that is, at or above `service_due_operating_hours`
    minus 200.  The comparison is inclusive: landing exactly on that
    earliest-creation point is allowed.  Below it the request is refused with
    `ERR_SERVICE_NOT_DUE`, which stops planners from burning a service window on a
    turbine that is nowhere near due."

    Design: Difficulty/boundary_precision_check/service_due_gate_and_tolerance_breach_walk_four_exact_operating_hour_boundaries
    """
    site = setup_service_due_boundaries(api)
    turbine_id = site["t1"]["id"]

    too_early = _service_order(api, turbine_id)
    validate_error(too_early, "ERR_SERVICE_NOT_DUE", 422)

    post_scada(api, turbine_id, 1.0, 2000, 2000)

    at_the_boundary = validate_success(_service_order(api, turbine_id), 201)
    assert at_the_boundary["state"] == WO_DRAFT
    assert at_the_boundary["work_type"] == WORK_TYPE_SCHEDULED_SERVICE

    turbine = read_turbine(api, turbine_id)
    assert turbine["operating_hours"] == 3800.0
    assert turbine["service_due_operating_hours"] == 4000
    assert turbine["service_due_flag"] is False
    assert turbine["service_interval_breached"] is False


def test_the_due_flag_is_inclusive_while_the_tolerance_breach_is_strict(api):
    """Two comparisons on the same pair of counters, one at-or-above and one strict.

    The contract states: "`service_due_flag` is true when the turbine's
    `operating_hours` has reached or passed `service_due_operating_hours`, using an
    at-or-above comparison."  It continues: "`service_interval_breached` is true
    only when `operating_hours` has passed `service_due_operating_hours` plus the
    model's `service_interval_tolerance_hours` **strictly** — landing exactly on the
    tolerated boundary is not yet a breach."

    Design: Difficulty/boundary_precision_check/service_due_gate_and_tolerance_breach_walk_four_exact_operating_hour_boundaries
    """
    site = setup_service_due_boundaries(api)
    turbine_id = site["t1"]["id"]

    post_scada(api, turbine_id, 1.0, 2000, 2000)
    post_scada(api, turbine_id, 200.0, 400000, 400000)
    at_the_due_point = read_turbine(api, turbine_id)
    assert at_the_due_point["operating_hours"] == 4000.0
    assert at_the_due_point["service_due_flag"] is True
    assert at_the_due_point["service_interval_breached"] is False

    post_scada(api, turbine_id, 250.0, 500000, 500000)
    at_the_tolerance = read_turbine(api, turbine_id)
    assert at_the_tolerance["operating_hours"] == 4250.0
    assert at_the_tolerance["service_due_flag"] is True
    assert at_the_tolerance["service_interval_breached"] is False

    post_scada(api, turbine_id, 0.1, 200, 200)
    past_the_tolerance = read_turbine(api, turbine_id)
    assert_two_dp(past_the_tolerance["operating_hours"], 4250.1, "t1.operating_hours")
    assert past_the_tolerance["service_due_flag"] is True
    assert past_the_tolerance["service_interval_breached"] is True


def test_each_band_minimum_is_inclusive_at_eighty_sixty_and_forty(api):
    """Three findings land exactly on the three band minima.

    The contract states: "`repair_priority_band` is `CRITICAL` when
    `severity_score` is at least 80, `HIGH` when it is at least 60 but below 80,
    `MEDIUM` when it is at least 40 but below 60, and `LOW` otherwise."  It adds:
    "`repair_due_days` follows directly from the band: 14 days for `CRITICAL`, 45
    for `HIGH`, 120 for `MEDIUM` and 365 for `LOW`."  Of the weighting it states:
    "Each factor is then weighted: 30 for category, 30 for type, 20 for length and
    20 for exposure."

    Design: Difficulty/boundary_precision_check/blade_severity_bands_pinned_at_forty_sixty_and_eighty_with_one_cent_neighbours
    """
    site = setup_blade_band_boundaries(api)

    critical = validate_success(
        api.record_blade_damage(
            site["t1"]["id"],
            blade_damage_payload(
                inspection_method=INSPECTION_DRONE,
                blade_position="A",
                inspected_at="2026-08-01T00:00:00Z",
                damage_category=5,
                damage_type=DAMAGE_CRACK_TRANSVERSE,
                chord_position_pct=30,
                damage_length_mm=3000,
                exposed_area_cm2=0,
            ),
            make_engineer_headers(),
        ),
        201,
    )
    assert_two_dp(critical["severity_score"], 80.00, "critical.severity_score")
    assert critical["repair_priority_band"] == BAND_CRITICAL
    assert critical["repair_due_days"] == 14
    assert critical["state"] == BLADE_OPEN
    assert critical["recorded_by_user_id"] == ENGINEER_USER_ID

    high = validate_success(
        api.record_blade_damage(
            site["t1"]["id"],
            blade_damage_payload(
                inspection_method=INSPECTION_ROPE_ACCESS,
                blade_position="B",
                inspected_at="2026-08-01T00:00:00Z",
                damage_category=5,
                damage_type=DAMAGE_LIGHTNING_STRIKE,
                chord_position_pct=45,
                damage_length_mm=0,
                exposed_area_cm2=1350,
            ),
            make_engineer_headers(),
        ),
        201,
    )
    assert_two_dp(high["severity_score"], 60.00, "high.severity_score")
    assert high["repair_priority_band"] == BAND_HIGH
    assert high["repair_due_days"] == 45

    medium = validate_success(
        api.record_blade_damage(
            site["t1"]["id"],
            blade_damage_payload(
                inspection_method=INSPECTION_GROUND_OPTICAL,
                blade_position="C",
                inspected_at="2026-08-01T00:00:00Z",
                damage_category=2,
                damage_type=DAMAGE_LEADING_EDGE_EROSION,
                chord_position_pct=10,
                damage_length_mm=0,
                exposed_area_cm2=2850,
            ),
            make_engineer_headers(),
        ),
        201,
    )
    assert_two_dp(medium["severity_score"], 40.00, "medium.severity_score")
    assert medium["repair_priority_band"] == BAND_MEDIUM
    assert medium["repair_due_days"] == 120


def test_one_hundredth_below_each_minimum_drops_into_the_band_beneath(api):
    """A couple of millimetres of length or square centimetres of area moves the band.

    The contract states: "Each of the four weighted terms is rounded half up to two
    decimal places **first**; the four already-rounded terms are then added; and the
    resulting sum is rounded half up to two decimal places again."  It also states:
    "`repair_priority_band` is `CRITICAL` when `severity_score` is at least 80,
    `HIGH` when it is at least 60 but below 80, `MEDIUM` when it is at least 40 but
    below 60, and `LOW` otherwise."  And: "`repair_due_days` follows directly from
    the band: 14 days for `CRITICAL`, 45 for `HIGH`, 120 for `MEDIUM` and 365 for
    `LOW`."

    Design: Difficulty/boundary_precision_check/blade_severity_bands_pinned_at_forty_sixty_and_eighty_with_one_cent_neighbours
    """
    site = setup_blade_band_boundaries(api)
    turbine_id = site["t2"]["id"]

    just_below_critical = validate_success(
        api.record_blade_damage(
            turbine_id,
            blade_damage_payload(
                inspection_method=INSPECTION_DRONE,
                blade_position="A",
                inspected_at="2026-08-01T00:00:00Z",
                damage_category=5,
                damage_type=DAMAGE_CRACK_TRANSVERSE,
                chord_position_pct=30,
                damage_length_mm=2999,
                exposed_area_cm2=0,
            ),
            make_engineer_headers(),
        ),
        201,
    )
    assert_two_dp(just_below_critical["severity_score"], 79.99, "79.99 severity_score")
    assert just_below_critical["repair_priority_band"] == BAND_HIGH
    assert just_below_critical["repair_due_days"] == 45
    assert just_below_critical["state"] == BLADE_OPEN

    just_below_high = validate_success(
        api.record_blade_damage(
            turbine_id,
            blade_damage_payload(
                inspection_method=INSPECTION_ROPE_ACCESS,
                blade_position="B",
                inspected_at="2026-08-01T00:00:00Z",
                damage_category=5,
                damage_type=DAMAGE_LIGHTNING_STRIKE,
                chord_position_pct=45,
                damage_length_mm=0,
                exposed_area_cm2=1348,
            ),
            make_engineer_headers(),
        ),
        201,
    )
    assert_two_dp(just_below_high["severity_score"], 59.99, "59.99 severity_score")
    assert just_below_high["repair_priority_band"] == BAND_MEDIUM
    assert just_below_high["repair_due_days"] == 120

    just_below_medium = validate_success(
        api.record_blade_damage(
            turbine_id,
            blade_damage_payload(
                inspection_method=INSPECTION_GROUND_OPTICAL,
                blade_position="C",
                inspected_at="2026-08-01T00:00:00Z",
                damage_category=2,
                damage_type=DAMAGE_LEADING_EDGE_EROSION,
                chord_position_pct=10,
                damage_length_mm=0,
                exposed_area_cm2=2848,
            ),
            make_engineer_headers(),
        ),
        201,
    )
    assert_two_dp(just_below_medium["severity_score"], 39.99, "39.99 severity_score")
    assert just_below_medium["repair_priority_band"] == BAND_LOW
    assert just_below_medium["repair_due_days"] == 365


def test_zero_potential_energy_reads_one_hundred_and_an_equal_guarantee_costs_nothing(api):
    """The division guard and the shortfall floor, on one farm with no telemetry.

    The contract states: "`energy_based_availability_pct` reads only telemetry: it
    is 100 multiplied by the sum of `period_actual_energy_kwh` across the turbine
    set divided by the sum of `period_potential_energy_kwh` across the same set,
    rounded half up to four decimal places — except that when the potential sum is
    exactly 0 the figure is `100.0000` by definition rather than a division."  Of
    the shortfall it states: "The shortfall is `guaranteed_availability_pct` minus
    the basis figure, treated as 0 whenever the basis figure meets or exceeds the
    guarantee, rounded half up to four decimal places; and it is taken from the
    **already-rounded** four-decimal basis figure, never from the raw quotient."

    Design: Difficulty/boundary_precision_check/availability_shortfall_and_lda_cap_pinned_at_zero_equality_and_one_cent_of_cap
    """
    site = setup_lda_boundary_agreements(api)

    on_energy = validate_success(
        api.settle_agreement(site["ag_zero_energy"]["id"], make_commercial_headers())
    )
    assert on_energy["state"] == AGREEMENT_IN_SETTLEMENT
    assert_four_dp(
        on_energy["energy_based_availability_pct"], 100.0000, "energy_based_availability_pct"
    )
    assert_four_dp(
        on_energy["time_based_availability_pct"], 98.3333, "time_based_availability_pct"
    )
    assert_cents(on_energy["assessed_lda_cents"], 0, "zero-energy assessed_lda_cents")

    on_equality = validate_success(
        api.settle_agreement(site["ag_equal"]["id"], make_commercial_headers())
    )
    assert on_equality["state"] == AGREEMENT_IN_SETTLEMENT
    assert_four_dp(
        on_equality["time_based_availability_pct"], 98.3333, "time_based_availability_pct"
    )
    assert_cents(on_equality["assessed_lda_cents"], 0, "equal-guarantee assessed_lda_cents")


def test_the_cap_binds_one_cent_below_the_uncapped_assessment(api):
    """One ten-thousandth of a point costs 100 cents, and the cap is the lesser of two.

    The contract states: "`assessed_lda_cents` is that shortfall multiplied by
    `lda_rate_cents_per_pct_point`, rounded half up to a whole cent, and then capped
    at `lda_cap_cents` — the assessment is the lesser of the two."  Of the basis
    figure it states: "`time_based_availability_pct` is then 100 multiplied by the
    quantity one minus counted downtime divided by that denominator, rounded half up
    to four decimal places."

    Design: Difficulty/boundary_precision_check/availability_shortfall_and_lda_cap_pinned_at_zero_equality_and_one_cent_of_cap
    """
    site = setup_lda_boundary_agreements(api)

    one_tick = validate_success(
        api.settle_agreement(site["ag_one_tick"]["id"], make_commercial_headers())
    )
    assert one_tick["state"] == AGREEMENT_IN_SETTLEMENT
    assert_four_dp(
        one_tick["time_based_availability_pct"], 98.3333, "time_based_availability_pct"
    )
    assert_cents(one_tick["assessed_lda_cents"], 100, "one-tick assessed_lda_cents")

    cap_equal = validate_success(
        api.settle_agreement(site["ag_cap_equal"]["id"], make_commercial_headers())
    )
    assert cap_equal["state"] == AGREEMENT_IN_SETTLEMENT
    assert_cents(cap_equal["assessed_lda_cents"], 666700, "cap-equal assessed_lda_cents")

    cap_binds = validate_success(
        api.settle_agreement(site["ag_cap_binds"]["id"], make_commercial_headers())
    )
    assert cap_binds["state"] == AGREEMENT_IN_SETTLEMENT
    assert_cents(cap_binds["assessed_lda_cents"], 666699, "cap-binding assessed_lda_cents")
