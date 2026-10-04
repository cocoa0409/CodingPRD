"""Colony availability forecasts (CONFIRMED_ONLY vs PROJECTED variants) and
the derived cohort age read at the logical clock.
"""
from test_helpers import (
    TEST_USERS,
    CLOCK_DEFAULT_ISO,
    advance_clock,
    assert_colony,
    compute_age_weeks,
    compute_projected_pipeline,
    hold_cohort,
    read_colony,
    read_cohort,
    record_snp_panel_result,
    setup_colony_with_cohorts,
    setup_sourcing_order,
    allocate_order_to_cohort,
)

_FM = TEST_USERS["facility_manager_headers"]


def test_forecast_projected_adds_litter_term_confirmed_excludes_weaned():
    """PRD Section 3.2: "The `confirmed_available_count` sums, over those
    cohorts, each cohort's live headcount minus its reservations — that is,
    `count_male` plus `count_female` minus `reserved_male` minus
    `reserved_female`."
    PRD Section 3.2: "when the colony's `lifecycle_status` is `PRODUCTION` and
    its `genetic_status` is not `DRIFT_DETECTED`, the expected next-litter
    yield is the floor of `breeding_pair_count` multiplied by the strain's
    `typical_litter_size` multiplied by the survival rate 0.8; in any other
    lifecycle or genetic state the term is 0."
    PRD Section 3.2: "the colony's cohorts in `HOLD` or `PARTIALLY_ALLOCATED`
    (cohorts in `WEANED`, `FULLY_ALLOCATED`, `SHIPPED`, or `CULLED` never
    contribute)".

    Design: Difficulty/dual_variant_calc/colony_forecast_projected_vs_confirmed
    """
    bundle = setup_colony_with_cohorts(
        breeding_pair_count=10, cohorts=[{"count_male": 10, "count_female": 10}]
    )
    colony = read_colony(bundle["colony"]["id"])
    # The only cohort is WEANED: excluded from the CONFIRMED_ONLY input set.
    assert colony["confirmed_available_count"] == 0
    # PROJECTED adds floor(10 pairs * 6 litter * 0.8 survival) = 48.
    assert colony["projected_pipeline_count"] == compute_projected_pipeline(
        0, 10, 6, "PRODUCTION", "CLEAR"
    )
    assert colony["projected_pipeline_count"] == 48
    assert colony["lifecycle_status"] == "PRODUCTION"


def test_forecast_variants_diverge_once_cohort_on_hold():
    """PRD Section 3.2: "The confirmed figure is the `CONFIRMED_ONLY` variant
    and counts only physically present, unreserved animals; the projected
    figure is the `PROJECTED` variant used by order sourcing feasibility, and
    identical inputs always yield a projected value greater than or equal to
    the confirmed one."

    Design: Difficulty/dual_variant_calc/colony_forecast_projected_vs_confirmed
    """
    bundle = setup_colony_with_cohorts(
        breeding_pair_count=10, cohorts=[{"count_male": 10, "count_female": 10}]
    )
    cohort = bundle["cohorts"][0]
    hold_cohort(cohort["id"])

    colony = read_colony(bundle["colony"]["id"])
    assert colony["confirmed_available_count"] == 20
    assert colony["projected_pipeline_count"] == compute_projected_pipeline(
        20, 10, 6, "PRODUCTION", "CLEAR"
    )
    assert colony["projected_pipeline_count"] == 68
    assert colony["projected_pipeline_count"] > colony["confirmed_available_count"]


def test_drift_colony_forecast_drops_pipeline():
    """PRD Section 3.2: "when the colony's `lifecycle_status` is `PRODUCTION`
    and its `genetic_status` is not `DRIFT_DETECTED`, the expected next-litter
    yield is the floor of `breeding_pair_count` multiplied by the strain's
    `typical_litter_size` multiplied by the survival rate 0.8; in any other
    lifecycle or genetic state the term is 0."

    Design: Corner/calculations/drift_colony_forecast_drops_pipeline
    """
    bundle = setup_colony_with_cohorts(cohorts=[{"count_male": 5, "count_female": 5}])
    colony = bundle["colony"]
    assert read_colony(colony["id"])["projected_pipeline_count"] == 48

    record_snp_panel_result(colony["id"], "DRIFT_DETECTED")

    colony = read_colony(colony["id"])
    assert colony["genetic_status"] == "DRIFT_DETECTED"
    assert colony["lifecycle_status"] == "PHASING_OUT"
    assert colony["projected_pipeline_count"] == 0
    assert colony["confirmed_available_count"] == 0
    assert_colony(colony)


def test_confirmed_available_excludes_reserved():
    """PRD Section 3.2: "The `confirmed_available_count` sums, over those
    cohorts, each cohort's live headcount minus its reservations — that is,
    `count_male` plus `count_female` minus `reserved_male` minus
    `reserved_female`."

    Design: Corner/calculations/confirmed_available_excludes_reserved
    """
    bundle = setup_sourcing_order(quantity_male=4, quantity_female=4)
    order = bundle["order"]
    cohort = bundle["cohorts"][0]
    allocate_order_to_cohort(order, cohort, 4, 4)

    colony = read_colony(bundle["colony"]["id"])
    # 20 live - 8 reserved = 12 confirmed free.
    assert colony["confirmed_available_count"] == 12
    # PROJECTED adds the litter term on top: 12 + floor(10*6*0.8) = 60.
    assert colony["projected_pipeline_count"] == compute_projected_pipeline(
        12, 10, 6, "PRODUCTION", "CLEAR"
    )
    assert colony["projected_pipeline_count"] == 60


def test_cohort_age_weeks_computed_from_logical_clock():
    """PRD Section 3.3: "Its `age_weeks` is computed by taking the difference
    between an as-of instant and `birth_date`, flooring that difference to
    whole days (a day is 86400 seconds), then flooring the days to whole weeks
    (7 days per week). On plain cohort reads the as-of instant is the current
    logical clock".

    Design: Corner/entities/cohort_age_weeks_computed_from_logical_clock
    """
    bundle = setup_colony_with_cohorts(
        cohorts=[{"count_male": 5, "count_female": 5,
                  "birth_date": "2026-08-18T00:00:00Z"}],
        advance_to_production=False,
    )
    cohort = bundle["cohorts"][0]

    data = read_cohort(cohort["id"])
    assert data["age_weeks"] == compute_age_weeks(
        "2026-08-18T00:00:00Z", CLOCK_DEFAULT_ISO
    )
    assert data["age_weeks"] == 2  # floor(14 days / 7)

    advance_clock("2026-09-08T00:00:00Z")
    data = read_cohort(cohort["id"])
    assert data["age_weeks"] == compute_age_weeks(
        "2026-08-18T00:00:00Z", "2026-09-08T00:00:00Z"
    )
    assert data["age_weeks"] == 3  # floor(21 days / 7)
