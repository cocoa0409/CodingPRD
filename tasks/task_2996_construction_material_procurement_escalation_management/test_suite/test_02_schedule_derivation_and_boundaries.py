"""The release-for-fabrication schedule arithmetic and the project variance ledgers.

Covers lead_time_days, release_for_fabrication_date, the long-lead classification at
its inclusive 90-day boundary, the rff_risk_band cut-points at 0 / 14 / 15 float days,
the floor-toward-negative-infinity float derivation against the logical clock, and the
project's two contrasting variance flavours.
"""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_clock_state,
    assert_instant_equals,
    assert_material_package,
    assert_package_schedule_invariants,
    assert_project,
    assert_rff_risk_band,
    build_released_scenario,
    expected_escalation_accrued,
    register_package,
    round_half_up,
    validate_success,
)
from test_helpers.factories import (
    create_material_package_payload,
    create_project_payload,
    set_clock_payload,
)

BUYOUT_MANAGER = TEST_USERS["buyout_manager_headers"]

_PROJECT_LITERALS = {
    "name": "Riverside Medical Tower",
    "contract_number": "GC-2996-A",
    "owner_name": "Riverside Health System",
    "schedule_data_date": "2026-08-01T00:00:00.000Z",
    "escalation_contingency_budget": 500000.00,
}

# fabrication 70 + transit 20 + submittal 21 == 111 lead days.
_BASE_DURATIONS = {
    "commodity_index_code": "PPI_STEEL_MILL",
    "estimated_cost": 1200000.00,
    "required_onsite_date": "2027-03-01T00:00:00.000Z",
    "fabrication_duration_days": 70,
    "delivery_transit_days": 20,
    "submittal_review_days": 21,
}


def _open_project() -> dict:
    """Open the literal project the design instances use."""
    return validate_success(
        api_client.create_project(
            create_project_payload(**_PROJECT_LITERALS), BUYOUT_MANAGER
        ),
        201,
    )


def _register(project_id, scope_code, description, **overrides) -> dict:
    """Register a package with the literal durations, overriding as named."""
    payload = create_material_package_payload(
        project_id=project_id,
        scope_code=scope_code,
        description=description,
        **{**_BASE_DURATIONS, **overrides},
    )
    return validate_success(
        api_client.create_material_package(payload, BUYOUT_MANAGER), 201
    )


def _advance_clock(to_iso8601) -> dict:
    """Advance the logical clock and return the clock response payload."""
    clock = validate_success(
        api_client.set_clock(set_clock_payload(to_iso8601), BUYOUT_MANAGER), 200
    )
    assert_clock_state(clock)
    return clock


def _read(package_id) -> dict:
    return validate_success(
        api_client.get_material_package(package_id, BUYOUT_MANAGER), 200
    )


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check / long_lead_threshold_inclusive_at_exactly_ninety_days
# ---------------------------------------------------------------------------

def test_schedule_long_lead_true_at_exactly_ninety_fabrication_plus_transit_days():
    """Just inside the boundary: fabrication 70 plus transit 20 is exactly 90, and the
    threshold is an inclusive lower bound, so the package is long-lead.

    PRD §3.1: "`is_long_lead` is a deliberately narrower test: it is true when
    `fabrication_duration_days` plus `delivery_transit_days` alone reaches at least 90
    days — three months of pure market lead time — and it excludes
    `submittal_review_days` entirely, even though that duration *is* included in
    `lead_time_days`."
    PRD §3.1: "`lead_time_days` is the sum of `submittal_review_days`,
    `fabrication_duration_days` and `delivery_transit_days`."
    PRD §3.1: "`release_for_fabrication_date` is the `required_onsite_date` moved
    backwards by `lead_time_days` calendar days."

    Design: Difficulty/boundary_precision_check/long_lead_threshold_inclusive_at_exactly_ninety_days
    """
    project = _open_project()
    package = _register(
        project["id"], "STRUCT-STEEL-01", "Package at the long-lead boundary"
    )
    assert_material_package(package)

    assert package["fabrication_duration_days"] + package["delivery_transit_days"] == 90
    assert package["is_long_lead"] is True, "90 days reaches the inclusive threshold"
    assert package["lead_time_days"] == 111
    assert_instant_equals(
        package["release_for_fabrication_date"], "2026-11-10T00:00:00.000Z"
    )


def test_schedule_long_lead_false_at_eighty_nine_fabrication_plus_transit_days():
    """Just outside the boundary: fabrication 60 plus transit 29 is 89, so the package
    is not long-lead even though its 21 submittal-review days push lead_time_days to
    110 — the review span is excluded from the long-lead test alone.

    PRD §3.1: "`is_long_lead` is a deliberately narrower test: it is true when
    `fabrication_duration_days` plus `delivery_transit_days` alone reaches at least 90
    days — three months of pure market lead time — and it excludes
    `submittal_review_days` entirely, even though that duration *is* included in
    `lead_time_days`."
    PRD §3.1: "a package with a fifty-day fabrication, a thirty-day transit and the
    same sixty-day review has a hundred-and-forty-day lead time and is not."
    PRD §3.1: "`float_days` measures how much room is left before the release date
    arrives: it is the number of whole days from the current logical clock forward to
    `release_for_fabrication_date`, taken toward negative infinity"

    Design: Difficulty/boundary_precision_check/long_lead_threshold_inclusive_at_exactly_ninety_days
    """
    project = _open_project()
    package = _register(
        project["id"],
        "STRUCT-STEEL-02",
        "Package one day below the long-lead boundary",
        fabrication_duration_days=60,
        delivery_transit_days=29,
    )
    assert_material_package(package)

    assert package["fabrication_duration_days"] + package["delivery_transit_days"] == 89
    assert package["is_long_lead"] is False, "89 days is one day short of the threshold"
    assert package["submittal_review_days"] == 21
    assert package["lead_time_days"] == 110
    assert_instant_equals(
        package["release_for_fabrication_date"], "2026-11-11T00:00:00.000Z"
    )
    assert package["float_days"] == 102
    assert package["rff_risk_band"] == "ON_TRACK"


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check / rff_risk_band_boundaries_at_zero_fourteen_and_fifteen_float_days
# ---------------------------------------------------------------------------

def test_schedule_rff_band_is_critical_at_exactly_zero_float_days():
    """The CRITICAL rung is an inclusive upper bound at zero: a release date that lands
    exactly on the startup clock reads CRITICAL, not AT_RISK.

    PRD §3.1: "`rff_risk_band` reads `CRITICAL` when `float_days` is zero or less,
    `AT_RISK` when it is between 1 and 14 inclusive, and `ON_TRACK` when it is 15 or
    more."
    PRD §3.1: "`release_for_fabrication_date` is the `required_onsite_date` moved
    backwards by `lead_time_days` calendar days."
    PRD §2.5: "Before the clock has ever been set, it reads exactly
    `2026-08-01T00:00:00Z`"

    Design: Difficulty/boundary_precision_check/rff_risk_band_boundaries_at_zero_fourteen_and_fifteen_float_days
    """
    project = _open_project()
    package = _register(
        project["id"],
        "STRUCT-STEEL-01",
        "Package whose release date is today",
        required_onsite_date="2026-11-20T00:00:00.000Z",
    )
    assert_material_package(package)

    assert package["lead_time_days"] == 111
    assert package["is_long_lead"] is True
    assert_instant_equals(
        package["release_for_fabrication_date"], "2026-08-01T00:00:00.000Z"
    )
    assert package["float_days"] == 0
    assert package["rff_risk_band"] == "CRITICAL", "zero float is CRITICAL, not AT_RISK"
    assert_rff_risk_band(package["float_days"], package["rff_risk_band"])


def test_schedule_rff_band_is_at_risk_at_exactly_fourteen_float_days():
    """The AT_RISK rung runs to 14 inclusive, so fourteen days of float is still
    AT_RISK rather than ON_TRACK.

    PRD §3.1: "`rff_risk_band` reads `CRITICAL` when `float_days` is zero or less,
    `AT_RISK` when it is between 1 and 14 inclusive, and `ON_TRACK` when it is 15 or
    more."
    PRD §3.1: "`float_days` measures how much room is left before the release date
    arrives: it is the number of whole days from the current logical clock forward to
    `release_for_fabrication_date`, taken toward negative infinity"

    Design: Difficulty/boundary_precision_check/rff_risk_band_boundaries_at_zero_fourteen_and_fifteen_float_days
    """
    project = _open_project()
    package = _register(
        project["id"],
        "STRUCT-STEEL-02",
        "Package with 14 days of float",
        required_onsite_date="2026-12-04T00:00:00.000Z",
    )
    assert_material_package(package)

    assert package["lead_time_days"] == 111
    assert package["is_long_lead"] is True
    assert_instant_equals(
        package["release_for_fabrication_date"], "2026-08-15T00:00:00.000Z"
    )
    assert package["float_days"] == 14
    assert package["rff_risk_band"] == "AT_RISK", "14 days of float is still AT_RISK"
    assert_rff_risk_band(package["float_days"], package["rff_risk_band"])


def test_schedule_rff_band_is_on_track_at_exactly_fifteen_float_days():
    """One day further out the band flips: 15 float days is the inclusive lower bound
    of ON_TRACK.

    PRD §3.1: "`rff_risk_band` reads `CRITICAL` when `float_days` is zero or less,
    `AT_RISK` when it is between 1 and 14 inclusive, and `ON_TRACK` when it is 15 or
    more."
    PRD §3.1: "`lead_time_days` is the sum of `submittal_review_days`,
    `fabrication_duration_days` and `delivery_transit_days`."

    Design: Difficulty/boundary_precision_check/rff_risk_band_boundaries_at_zero_fourteen_and_fifteen_float_days
    """
    project = _open_project()
    package = _register(
        project["id"],
        "STRUCT-STEEL-03",
        "Package with 15 days of float",
        required_onsite_date="2026-12-05T00:00:00.000Z",
    )
    assert_material_package(package)

    assert package["lead_time_days"] == 111
    assert package["is_long_lead"] is True
    assert_instant_equals(
        package["release_for_fabrication_date"], "2026-08-16T00:00:00.000Z"
    )
    assert package["float_days"] == 15
    assert package["rff_risk_band"] == "ON_TRACK", "15 days of float reaches ON_TRACK"
    assert_rff_risk_band(package["float_days"], package["rff_risk_band"])


# ---------------------------------------------------------------------------
# Queue A: dual_variant_calc / buyout_variance_full_program_versus_bought_out_scope_only
# ---------------------------------------------------------------------------

def _setup_two_package_variance_program() -> dict:
    """One BOUGHT_OUT package with a released commitment plus one untouched package.

    STRUCT-STEEL-01 is estimated at 1200000.00 and bought out at a committed base cost
    of 1150000.00 with a provisional escalation recognised at the 2026-09-10 release.
    STRUCT-STEEL-02 is estimated at 300000.00 and never receives a quote.
    """
    scenario = build_released_scenario(release_at="2026-09-10T00:00:00.000Z")
    scenario["package_2"] = register_package(
        scenario["project"]["id"],
        scope_code="STRUCT-STEEL-02",
        description="Miscellaneous metals package",
        commodity_index_code="PPI_STEEL_MILL",
        estimated_cost=300000.00,
        required_onsite_date="2027-04-01T00:00:00.000Z",
        fabrication_duration_days=40,
        delivery_transit_days=15,
        submittal_review_days=21,
    )
    return scenario


def test_schedule_buyout_variance_covers_the_full_programme_estimate():
    """Variant one: `buyout_variance` takes `estimated_total_cost` across EVERY package —
    including the un-quoted 300000.00 scope — less the committed total, so it reads
    317058.02.

    PRD §3.1: "`buyout_variance` is the full-programme figure: `estimated_total_cost`
    across every package, less `committed_total_cost`, rounded half up to 2 decimal
    places."
    PRD §3.1: "`estimated_total_cost` is the sum of `estimated_cost` over every scope
    package belonging to the project — every package, with no status filter at all,
    because there is no soft delete here and a package sitting in `IDENTIFIED` is still
    scope somebody has to buy."
    PRD §3.1: "`committed_total_cost` is the sum, over the project's commitments whose
    `commitment_status` is `COMMITTED` or `CLOSED`, of each commitment's
    `committed_base_cost` plus its `escalation_accrued`"
    PRD §3.1: "the full-programme variance reads 317058.02 while the bought-out variance
    reads 17058.02."

    Design: Difficulty/dual_variant_calc/buyout_variance_full_program_versus_bought_out_scope_only
    """
    scenario = _setup_two_package_variance_program()
    project = validate_success(
        api_client.get_project(scenario["project"]["id"], BUYOUT_MANAGER), 200
    )
    assert_project(project)

    accrued = expected_escalation_accrued(
        committed_base_cost=1150000.00,
        baseline_index_value=310.00,
        current_index_value=331.00,
        deadband_pct=2.0,
        cap_pct=8.0,
        contractor_share_pct=40.0,
    )
    assert accrued == 32941.98

    assert project["estimated_total_cost"] == 1500000.00
    assert project["committed_total_cost"] == 1182941.98
    assert project["committed_total_cost"] == 1150000.00 + accrued
    assert project["buyout_variance"] == 317058.02
    assert project["buyout_variance"] == 1500000.00 - 1182941.98


def test_schedule_bought_out_variance_restricts_to_bought_out_scope_only():
    """Variant two: from the identical rows, `bought_out_variance` restricts the estimate
    side to BOUGHT_OUT/CLOSED packages, dropping the IDENTIFIED 300000.00 scope and
    reading 17058.02 — exactly 300000.00 tighter than the full-programme figure.

    PRD §3.1: "`bought_out_variance` is the apples-to-apples figure: the sum of
    `estimated_cost` restricted to packages whose status is `BOUGHT_OUT` or `CLOSED`,
    less the same `committed_total_cost`, rounded the same way."
    PRD §3.1: "the full-programme variance reads 317058.02 while the bought-out variance
    reads 17058.02."
    PRD §3.1: "`escalation_contingency_committed` is the sum of `escalation_accrued` over
    that same `COMMITTED`-or-`CLOSED` set, and `escalation_contingency_remaining` is the
    budget less that figure, rounded half up to 2 decimal places."
    PRD §3.1: "It begins `IDENTIFIED` with an `open_quote_count` of 0."

    Design: Difficulty/dual_variant_calc/buyout_variance_full_program_versus_bought_out_scope_only
    """
    scenario = _setup_two_package_variance_program()
    project = validate_success(
        api_client.get_project(scenario["project"]["id"], BUYOUT_MANAGER), 200
    )
    assert_project(project)

    assert project["bought_out_variance"] == 17058.02
    # PRD §3.1 pins the subtrahend and minuend as well as the answer, and §2.6 pins the
    # 2-decimal round-half-up discipline every money figure is returned under, so the
    # difference must be re-rounded before it is compared (the raw IEEE-754 subtraction
    # yields 17058.02000000002, a figure the PRD forbids the server from returning).
    assert project["bought_out_variance"] == round_half_up(1200000.00 - 1182941.98, 2)
    assert (
        project["buyout_variance"] - project["bought_out_variance"] == 300000.00
    ), "the excluded scope is exactly the un-bought-out package's estimate"
    assert project["escalation_contingency_committed"] == 32941.98
    assert project["escalation_contingency_remaining"] == 467058.02

    second = _read(scenario["package_2"]["id"])
    assert_material_package(second)
    assert second["status"] == "IDENTIFIED"
    assert second["open_quote_count"] == 0


# ---------------------------------------------------------------------------
# Queue B: calculations / correct_result_lead_time_and_release_date_derive_from_three_day_counts
# ---------------------------------------------------------------------------

def test_schedule_all_four_derived_fields_land_in_one_package_create():
    """The create response already carries the whole derived schedule: 21 + 70 + 20 = 111
    lead days counted back from 2027-03-01 gives a release date of 2026-11-10, which is
    101 whole days past the 2026-08-01 startup clock, hence ON_TRACK.

    PRD §3.1: "`lead_time_days` is the sum of `submittal_review_days`,
    `fabrication_duration_days` and `delivery_transit_days`."
    PRD §3.1: "`release_for_fabrication_date` is the `required_onsite_date` moved
    backwards by `lead_time_days` calendar days."
    PRD §3.1: "`float_days` measures how much room is left before the release date
    arrives: it is the number of whole days from the current logical clock forward to
    `release_for_fabrication_date`, taken toward negative infinity"
    PRD §3.1: "`rff_risk_band` reads `CRITICAL` when `float_days` is zero or less,
    `AT_RISK` when it is between 1 and 14 inclusive, and `ON_TRACK` when it is 15 or
    more."
    PRD §3.1: "It begins `IDENTIFIED` with an `open_quote_count` of 0."

    Design: Corner/calculations/correct_result_lead_time_and_release_date_derive_from_three_day_counts
    """
    project = _open_project()
    package = _register(
        project["id"], "STRUCT-STEEL-01", "Structural steel frame package"
    )
    assert_material_package(package)
    assert_package_schedule_invariants(package)

    assert package["lead_time_days"] == 111
    assert_instant_equals(
        package["release_for_fabrication_date"], "2026-11-10T00:00:00.000Z"
    )
    assert package["is_long_lead"] is True
    assert package["float_days"] == 101
    assert package["rff_risk_band"] == "ON_TRACK"
    assert package["status"] == "IDENTIFIED"
    assert package["open_quote_count"] == 0


# ---------------------------------------------------------------------------
# Queue B: calculations / input_set_filtering_float_days_recomputes_on_the_clock_without_a_package_write
# ---------------------------------------------------------------------------

def test_schedule_float_days_recomputes_on_the_clock_without_a_package_write():
    """The float calculation's input set is the package row PLUS the clock. Advancing the
    clock onto the release date alone flips float 101 -> 0 and ON_TRACK -> CRITICAL on the
    next read, while the clock-independent fields and the audit columns stay put.

    PRD §3.1: "Both figures are re-derived against the clock on every read, so the same
    untouched package reports a different band tomorrow than it does today.
    `lead_time_days`, `release_for_fabrication_date` and `is_long_lead`, by contrast, are
    clock-independent."
    PRD §2.10: "A package's `lead_time_days`, `release_for_fabrication_date`,
    `is_long_lead`, `float_days`, `rff_risk_band` and `open_quote_count` are recomputed on
    every read of that package."
    PRD §2.10: "Nothing about a derivation counts as a mutation: it never refreshes
    `updated_at` and never increments `version`."
    PRD §2.5: "The clock response reports the resulting instant in `current_utc`"

    Design: Corner/calculations/input_set_filtering_float_days_recomputes_on_the_clock_without_a_package_write
    """
    project = _open_project()
    created = _register(
        project["id"], "STRUCT-STEEL-01", "Structural steel frame package"
    )

    before = _read(created["id"])
    assert before["float_days"] == 101
    assert before["rff_risk_band"] == "ON_TRACK"

    clock = _advance_clock("2026-11-10T00:00:00.000Z")
    assert_instant_equals(clock["current_utc"], "2026-11-10T00:00:00.000Z")
    assert clock["stalled_package_ids"] == [], "an IDENTIFIED package never stalls"

    after = _read(created["id"])
    assert_material_package(after)
    assert after["float_days"] == 0, "the clock has reached the release date"
    assert after["rff_risk_band"] == "CRITICAL"

    assert_instant_equals(
        after["release_for_fabrication_date"], "2026-11-10T00:00:00.000Z"
    )
    assert after["lead_time_days"] == 111
    assert after["is_long_lead"] is True
    assert_instant_equals(
        after["updated_at"], before["updated_at"], "a derivation must not touch updated_at"
    )
    assert after["version"] == before["version"]


# ---------------------------------------------------------------------------
# Queue B: calculations / precision_float_days_floors_toward_negative_infinity_on_a_half_day
# ---------------------------------------------------------------------------

def test_schedule_float_days_floors_toward_negative_infinity_on_a_half_day():
    """float_days is a floor, not a truncation or a round-to-nearest: half a day of
    remaining room floors to 0 (CRITICAL, not 1 / AT_RISK), and a -15.5 day span floors
    away from zero to -16, not -15.

    PRD §3.1: "`float_days` measures how much room is left before the release date
    arrives: it is the number of whole days from the current logical clock forward to
    `release_for_fabrication_date`, taken toward negative infinity, and it goes negative
    once that date is behind us."
    PRD §3.1: "`rff_risk_band` reads `CRITICAL` when `float_days` is zero or less,
    `AT_RISK` when it is between 1 and 14 inclusive, and `ON_TRACK` when it is 15 or
    more."
    PRD §3.1: "`lead_time_days`, `release_for_fabrication_date` and `is_long_lead`, by
    contrast, are clock-independent."

    Design: Corner/calculations/precision_float_days_floors_toward_negative_infinity_on_a_half_day
    """
    project = _open_project()
    created = _register(
        project["id"], "STRUCT-STEEL-01", "Structural steel frame package"
    )
    assert_instant_equals(
        created["release_for_fabrication_date"], "2026-11-10T00:00:00.000Z"
    )

    _advance_clock("2026-11-09T12:00:00.000Z")
    half_day_left = _read(created["id"])
    assert half_day_left["float_days"] == 0, "0.5 remaining days floor to 0, not 1"
    assert half_day_left["rff_risk_band"] == "CRITICAL", "0 float is CRITICAL, not AT_RISK"
    assert half_day_left["lead_time_days"] == 111

    _advance_clock("2026-11-25T12:00:00.000Z")
    overdue = _read(created["id"])
    assert overdue["float_days"] == -16, "-15.5 days floors toward negative infinity"
    assert overdue["rff_risk_band"] == "CRITICAL"
    assert overdue["lead_time_days"] == 111
    assert_rff_risk_band(overdue["float_days"], overdue["rff_risk_band"])
