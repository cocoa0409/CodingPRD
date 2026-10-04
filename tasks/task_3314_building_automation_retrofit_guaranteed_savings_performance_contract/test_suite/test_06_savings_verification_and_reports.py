"""Savings verification variants, period gating, and report listing."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_report_payload,
    eng_headers,
    make_actor_ids,
    own_headers,
    performance_contract,
    reset_clock,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_measured_vs_stipulated_savings_diverge_on_identical_meter_data(api):
    """PRD §3.5: "Under the stipulated variant (`IPMVP_A` and `IPMVP_D`),
    meter readings are ignored entirely: `verified_savings_cents` is 95
    percent of the sum of `annual_savings_cents` over the contract's
    `VERIFIED` measures, rounded half-up to integer cents."
    PRD §3.5: "The normalized kilowatt-hours, held at 4 decimal places, are
    priced through the baseline's current `rate_schedule` using the tiered
    walk of §2.8, and `verified_savings_cents` is the baseline's current
    `adjusted_annual_cost_cents` minus that period cost, rounded half-up to
    integer cents."

    Design: Difficulty/dual_variant_calc/measured_vs_stipulated_savings_diverge_on_identical_meter_data
    """
    from test_helpers import TIERED_RATE_SCHEDULE
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    measured, _b1, _bd1, _m1, _f1, _p1 = performance_contract(
        eng_id, owner_id, facility_name="North High", mv_protocol="IPMVP_C",
        baseline_rate_schedule=TIERED_RATE_SCHEDULE,
    )
    # The first fixture walk leaves the clock at the year-1 end instant; the
    # audit-completion gate requires guarantee_start_date to be later than
    # the (clock-driven) audit completion date, so rewind before the second
    # contract's lifecycle begins.
    reset_clock()
    stipulated, _b2, _bd2, _m2, _f2, _p2 = performance_contract(
        eng_id, owner_id, facility_name="South High", mv_protocol="IPMVP_A",
        baseline_rate_schedule=TIERED_RATE_SCHEDULE,
    )
    r1 = validate_success(
        api.create_report(measured["id"], create_report_payload(),
                          eng_headers(eng_id)),
        201,
    )
    r1 = validate_success(
        api.submit_report(measured["id"], r1["id"], eng_headers(eng_id))
    )
    r2 = validate_success(
        api.create_report(stipulated["id"], create_report_payload(),
                          eng_headers(eng_id)),
        201,
    )
    r2 = validate_success(
        api.submit_report(stipulated["id"], r2["id"], eng_headers(eng_id))
    )
    assert r1["verified_savings_cents"] == 240000
    assert r2["verified_savings_cents"] == 285000
    assert r1["verified_savings_cents"] != r2["verified_savings_cents"]
    assert r1["shortfall_cents"] == 10000
    assert r2["shortfall_cents"] == 0


def test_stipulated_variant_ignores_meter_readings(api):
    """PRD §3.5: "Under the stipulated variant (`IPMVP_A` and `IPMVP_D`),
    meter readings are ignored entirely: `verified_savings_cents` is 95
    percent of the sum of `annual_savings_cents` over the contract's
    `VERIFIED` measures, rounded half-up to integer cents. Identical weather
    and meter inputs therefore produce different verified savings under the
    two variants — a deliberate dual calculation."

    Design: Difficulty/dual_variant_calc/measured_vs_stipulated_savings_diverge_on_identical_meter_data
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, _f, _p = performance_contract(
        eng_id, owner_id, mv_protocol="IPMVP_A"
    )
    cid = contract["id"]
    # One VERIFIED measure at 300000 annual savings: 0.95 * 300000 = 285000,
    # regardless of what the meter says.
    report = validate_success(
        api.create_report(cid, create_report_payload(actual_energy_kwh=1),
                          eng_headers(eng_id)),
        201,
    )
    report = validate_success(
        api.submit_report(cid, report["id"], eng_headers(eng_id))
    )
    assert report["verified_savings_cents"] == 285000


def test_weather_occupancy_normalization_with_tier_straddle_mode_a(api):
    """PRD §3.5: "the occupancy adjustment multiplies by the baseline's
    `occupancy_factor` divided by the report's `period_occupancy_factor`"
    PRD §3.5: "The normalized kilowatt-hours, held at 4 decimal places, are
    priced through the baseline's current `rate_schedule` using the tiered
    walk of §2.8, and `verified_savings_cents` is the baseline's current
    `adjusted_annual_cost_cents` minus that period cost, rounded half-up to
    integer cents."
    PRD §3.5: "the report's `shortfall_cents` is then the larger of zero and
    the contract's `guaranteed_annual_savings_cents` minus the
    `verified_savings_cents`."

    Design: Difficulty/combinatorial_formula/weather_occupancy_normalization_with_tier_straddle_mode_a
    """
    from test_helpers import TIERED_RATE_SCHEDULE
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, baseline, _bd, _m, _f, _p = performance_contract(
        eng_id, owner_id, facility_name="West Elementary",
        mv_protocol="IPMVP_C", guaranteed_annual_savings_cents=300000,
        contract_value_cents=3000000,
        baseline_annual_energy_kwh=120000,
        baseline_rate_schedule=TIERED_RATE_SCHEDULE,
        measures=[{"measure_type": "HVAC", "installed_cost_cents": 1000000,
                   "annual_savings_cents": 300000}],
    )
    cid = contract["id"]
    assert baseline["adjusted_annual_cost_cents"] == 1500000
    report = validate_success(
        api.create_report(cid, create_report_payload(
            actual_energy_kwh=120000, period_occupancy_factor=0.58),
                          eng_headers(eng_id)),
        201,
    )
    report = validate_success(
        api.submit_report(cid, report["id"], eng_headers(eng_id))
    )
    # norm_kwh = 120000 * (0.5 / 0.58) = 103448.2759 straddles the 100000 tier.
    assert report["verified_savings_cents"] == 248276
    assert report["shortfall_cents"] == 51724


def test_occupancy_ratio_is_load_bearing_in_normalization(api):
    """PRD §3.5: "the occupancy adjustment multiplies by the baseline's
    `occupancy_factor` divided by the report's `period_occupancy_factor`"

    Design: Difficulty/combinatorial_formula/weather_occupancy_normalization_with_tier_straddle_mode_a
    """
    from test_helpers import TIERED_RATE_SCHEDULE
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, _f, _p = performance_contract(
        eng_id, owner_id, facility_name="West Elementary",
        mv_protocol="IPMVP_C", guaranteed_annual_savings_cents=300000,
        contract_value_cents=3000000,
        baseline_annual_energy_kwh=120000,
        baseline_rate_schedule=TIERED_RATE_SCHEDULE,
        measures=[{"measure_type": "HVAC", "installed_cost_cents": 1000000,
                   "annual_savings_cents": 300000}],
    )
    cid = contract["id"]
    # Occupancy below the baseline's: period_occupancy_factor 0.4 against the
    # baseline's 0.5 gives a ratio of 1.25, so norm = 120000 * 1.25 = 150000
    # kwh priced at 1950000 — above the adjusted baseline cost of 1500000, so
    # verified savings go negative and the occupancy ratio is load-bearing.
    report = validate_success(
        api.create_report(cid, create_report_payload(
            actual_energy_kwh=120000, period_occupancy_factor=0.4),
                          eng_headers(eng_id)),
        201,
    )
    report = validate_success(
        api.submit_report(cid, report["id"], eng_headers(eng_id))
    )
    assert report["verified_savings_cents"] == 1500000 - 1950000
    assert report["shortfall_cents"] == 300000 - (1500000 - 1950000)


def test_report_submit_before_period_end_rejected(api):
    """PRD §3.5: "the guarantee year must actually have ended: the logical
    clock must have reached the `guarantee_start_date` plus `period_year`
    years minus one day, otherwise the submission is rejected with
    `ERR_PERIOD_NOT_ENDED` (HTTP 422)."

    Design: Corner/validations/report_submit_before_period_end_rejected
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, _f, _p = performance_contract(
        eng_id, owner_id, end_year_1=False
    )
    cid = contract["id"]
    set_clock("2027-06-01T00:00:00Z")
    report = validate_success(
        api.create_report(cid, create_report_payload(), eng_headers(eng_id)), 201
    )
    response = api.submit_report(cid, report["id"], eng_headers(eng_id))
    validate_error(response, ApiErrorId.ERR_PERIOD_NOT_ENDED.value, 422)
    set_clock("2027-09-30T12:00:00Z")
    submitted = validate_success(
        api.submit_report(cid, report["id"], eng_headers(eng_id))
    )
    assert submitted["status"] == "SUBMITTED"


def test_reconcile_duplicate_period_year_rejected(api):
    """PRD §3.5: "Only one report may exist per `period_year` per contract; a
    duplicate guarantee-year report is rejected with
    `ERR_DUPLICATE_REPORT_PERIOD`."

    Design: Corner/state_machines/reconcile_duplicate_period_year_rejected
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, _f, _p = performance_contract(eng_id, owner_id)
    cid = contract["id"]
    validate_success(
        api.create_report(cid, create_report_payload(period_year=1),
                          eng_headers(eng_id)),
        201,
    )
    response = api.create_report(
        cid, create_report_payload(period_year=1, actual_energy_kwh=79000),
        eng_headers(eng_id),
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_REPORT_PERIOD.value, 409)


def test_reports_list_filtered_by_contract_paginates(api):
    """PRD §2.3: "`limit` defaults to 10, with a minimum of 1 and a maximum
    of 100; `offset` defaults to 0. Every list response carries the pagination
    fields `limit`, `offset`, `total_count`, and `has_more` inside `meta`."

    Design: Corner/entities/reports_list_filtered_by_contract_paginates
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, _f, _p = performance_contract(eng_id, owner_id)
    cid = contract["id"]
    validate_success(
        api.create_report(cid, create_report_payload(period_year=1),
                          eng_headers(eng_id)),
        201,
    )
    validate_success(
        api.create_report(cid, create_report_payload(period_year=2,
                                                     actual_energy_kwh=81000,
                                                     period_hdd=3100,
                                                     period_cdd=1100),
                          eng_headers(eng_id)),
        201,
    )
    response = api.list_reports(cid, own_headers(owner_id))
    data, meta = validate_paginated(response)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert len(data) == 2
