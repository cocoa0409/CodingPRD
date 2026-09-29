"""Boundary values one cent or one millisecond either side of a declared edge."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_ALLOCABLE_LOAD_NEGATIVE
from test_helpers.assertions import (
    assert_instant_equals,
    assert_integer,
    assert_is_null,
    assert_load,
    assert_pagination_meta,
    assert_pct,
    assert_trading_gate,
)
from test_helpers.test_users import ADMIN, ANALYST


def _boundary_creek(api):
    """Boundary Creek, whose capacity is consumed almost exactly by margin plus background."""
    fx.pin_clock(api)
    watershed = fx.make_watershed(
        api,
        name="Boundary Creek",
        state_code="OH",
        watershed_code="BND",
        pollutant="TOTAL_PHOSPHORUS",
        baseline_year=2020,
        baseline_load_lbs_yr=5000.00,
        eligible_zone_codes=["Z1", "Z2"],
    )
    b_out = fx.make_reach(
        api,
        watershed["id"],
        "B_OUT",
        trading_zone_code="Z2",
        reach_class="COMPLIANCE_POINT",
        delivery_factor=1.0000,
    )
    b_mid = fx.make_reach(
        api,
        watershed["id"],
        "B_MID",
        trading_zone_code="Z2",
        reach_class="MAINSTEM",
        delivery_factor=0.9000,
        downstream_reach_id=b_out["id"],
    )
    return {"watershed": watershed, "b_out": b_out, "b_mid": b_mid}


def test_allocable_load_of_exactly_zero_is_accepted_and_allocates_nothing(api):
    """A capacity fully consumed by margin and background still produces a run.

    "an allocable load of exactly 0.00 is accepted and results in every included
    source being allocated 0.00."

    Design: Difficulty/boundary_precision_check/allocable_load_exactly_zero_accepted_but_one_cent_negative_rejected
    """
    bnd = _boundary_creek(api)
    assessment = fx.make_assessment(
        api,
        bnd["watershed"]["id"],
        assessment_code="TMDL-ZERO",
        loading_capacity_lbs_yr=1000.00,
        margin_of_safety_pct=0.1000,
        background_load_lbs_yr=900.00,
    )
    point = fx.make_source(
        api, assessment["id"], bnd["b_mid"]["id"], "Zero Point", "POINT", 5000.00, 0.5000
    )
    nonpoint = fx.make_source(
        api, assessment["id"], bnd["b_mid"]["id"], "Zero Nonpoint", "NONPOINT", 3000.00, 0.4000
    )

    run = validate_success(
        api.create_allocation_run(
            assessment["id"],
            f.allocation_run_payload("RUN-ZERO", assessment["version"]),
            ANALYST,
        ),
        201,
    )

    assert_load(run["margin_of_safety_lbs_yr"], 100.00, "margin_of_safety_lbs_yr")
    assert_load(run["effective_background_lbs_yr"], 900.00, "effective_background_lbs_yr")
    assert_load(run["allocable_load_lbs_yr"], 0.00, "allocable_load_lbs_yr")
    assert_load(run["point_pool_lbs_yr"], 0.00, "point_pool_lbs_yr")
    assert_load(run["nonpoint_pool_lbs_yr"], 0.00, "nonpoint_pool_lbs_yr")
    assert_load(run["wla_total_lbs_yr"], 0.00, "wla_total_lbs_yr")
    assert_load(run["la_total_lbs_yr"], 0.00, "la_total_lbs_yr")
    assert_load(run["reserve_allocation_lbs_yr"], 0.00, "reserve_allocation_lbs_yr")
    assert_integer(run["included_source_count"], 2, "included_source_count")

    allocations = {
        row["source_assessment_id"]: row["allocated_load_lbs_yr"] for row in run["allocations"]
    }
    assert_load(allocations[point["id"]], 0.00, "point source allocation")
    assert_load(allocations[nonpoint["id"]], 0.00, "nonpoint source allocation")

    watershed = get_success_data(api.get_watershed(bnd["watershed"]["id"], ADMIN))
    assert_load(watershed["reserve_pool_lbs"], 0.00, "reserve_pool_lbs")


def test_allocable_load_one_cent_below_zero_is_rejected_and_writes_nothing(api):
    """One extra cent of background pushes the run below zero and nothing is written.

    "If the allocable load comes out strictly below 0.00 the entire run is
    rejected with `ERR_ALLOCABLE_LOAD_NEGATIVE` and nothing is written"

    Design: Difficulty/boundary_precision_check/allocable_load_exactly_zero_accepted_but_one_cent_negative_rejected
    """
    bnd = _boundary_creek(api)
    assessment = fx.make_assessment(
        api,
        bnd["watershed"]["id"],
        assessment_code="TMDL-NEG",
        loading_capacity_lbs_yr=1000.00,
        margin_of_safety_pct=0.1000,
        background_load_lbs_yr=900.01,
    )
    point = fx.make_source(
        api, assessment["id"], bnd["b_mid"]["id"], "Neg Point", "POINT", 5000.00, 0.5000
    )
    fx.make_source(
        api, assessment["id"], bnd["b_mid"]["id"], "Neg Nonpoint", "NONPOINT", 3000.00, 0.4000
    )

    refused = api.create_allocation_run(
        assessment["id"], f.allocation_run_payload("RUN-NEG", assessment["version"]), ANALYST
    )

    validate_error(refused, ERR_ALLOCABLE_LOAD_NEGATIVE, 422)

    untouched = get_success_data(api.get_source_assessment(point["id"], ANALYST))
    assert_is_null(untouched["allocated_load_lbs_yr"], "allocated_load_lbs_yr")
    assert_is_null(untouched["allocation_run_id"], "allocation_run_id")

    _, meta = validate_paginated(
        api.list_allocation_runs(ANALYST, {"tmdl_assessment_id": assessment["id"]})
    )
    assert_pagination_meta(meta, 10, 0, 0, False)

    watershed = get_success_data(api.get_watershed(bnd["watershed"]["id"], ADMIN))
    assert_load(watershed["reserve_pool_lbs"], 0.00, "reserve_pool_lbs")


def _review_sample_world(api):
    """An ACTIVE SCR program plus four samples, only one of which can ever qualify.

    S_MID sits on the mainstem rather than the compliance point, S_PROV is
    flagged PROVISIONAL, S_EDGE lands one millisecond past the end of the 2026
    window, and S_LATE lands inside the 2027 window.
    """
    world = fx.scr_active_program(api)
    r_out = world["reaches"]["r_out"]["id"]
    r_mid = world["reaches"]["r_mid"]["id"]
    world["s_mid"] = fx.make_sample(api, r_mid, "2026-07-01T12:00:00Z", 0.0549, 1000.00)
    world["s_prov"] = fx.make_sample(
        api, r_out, "2026-07-01T12:00:00Z", 0.0549, 1000.00, qa_status="PROVISIONAL"
    )
    world["s_edge"] = fx.make_sample(api, r_out, "2027-01-01T00:00:00.000Z", 0.0549, 1000.00)
    world["s_late"] = fx.make_sample(api, r_out, "2027-03-01T00:00:00Z", 0.0500, 1000.00)
    return world


def test_an_empty_qualifying_set_reads_indeterminate_and_leaves_the_program_open(api):
    """No qualifying sample is honestly reported rather than treated as failure.

    "If no sample qualifies, the review is honest about it:
    `observed_load_lbs_yr` and `achieved_reduction_pct` stay null and the
    `verdict` is `INDETERMINATE`. This empty-set edge is deliberately not treated
    as failure — an absence of data is not evidence of a failing watershed."

    Design: Difficulty/boundary_precision_check/adaptive_review_empty_qualifying_set_yields_indeterminate_not_off_track
    """
    world = _review_sample_world(api)
    assert_load(world["s_edge"]["computed_load_lbs_yr"], 108067.63, "S_EDGE computed load")
    review = fx.make_adaptive_review(
        api, world["watershed_id"], "AR-EMPTY", "2026-01-01", "2026-12-31"
    )
    fx.pin_clock(api, "2028-01-01T00:00:00Z")

    finalized = fx.finalize_adaptive_review(api, review["id"])

    assert finalized["status"] == "FINALIZED", finalized
    assert_integer(finalized["sample_count"], 0, "sample_count")
    assert_is_null(finalized["observed_load_lbs_yr"], "observed_load_lbs_yr")
    assert_is_null(finalized["achieved_reduction_pct"], "achieved_reduction_pct")
    assert finalized["verdict"] == "INDETERMINATE", finalized
    assert_integer(finalized["voided_transaction_count"], 0, "voided_transaction_count")
    assert_instant_equals(finalized["finalized_at"], "2028-01-01T00:00:00Z", "finalized_at")

    watershed = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert_trading_gate(watershed, "ACTIVE")


def test_a_sample_one_millisecond_past_the_window_end_falls_into_the_next_review(api):
    """The 2026 window closes at 23:59:59.999, so the 2027 sample is the one counted.

    "its `sample_datetime` falls between the start of `period_start_date` —
    00:00:00.000 UTC on that date — and the last millisecond of `period_end_date`
    — 23:59:59.999 UTC — inclusive at both ends."

    Design: Difficulty/boundary_precision_check/adaptive_review_empty_qualifying_set_yields_indeterminate_not_off_track
    """
    world = _review_sample_world(api)
    assert_load(world["s_late"]["computed_load_lbs_yr"], 98422.25, "S_LATE computed load")
    empty_review = fx.make_adaptive_review(
        api, world["watershed_id"], "AR-EMPTY", "2026-01-01", "2026-12-31"
    )
    late_review = fx.make_adaptive_review(
        api, world["watershed_id"], "AR-LATE", "2027-01-02", "2027-12-31"
    )
    fx.pin_clock(api, "2028-01-01T00:00:00Z")

    finalized_empty = fx.finalize_adaptive_review(api, empty_review["id"])
    finalized_late = fx.finalize_adaptive_review(api, late_review["id"])

    assert_integer(finalized_empty["sample_count"], 0, "AR-EMPTY sample_count")
    assert finalized_empty["verdict"] == "INDETERMINATE", finalized_empty

    assert_integer(finalized_late["sample_count"], 1, "AR-LATE sample_count")
    assert_load(finalized_late["observed_load_lbs_yr"], 98422.25, "observed_load_lbs_yr")
    assert_pct(finalized_late["achieved_reduction_pct"], 35.96, "achieved_reduction_pct")
    assert finalized_late["verdict"] == "ON_TRACK", finalized_late
    assert_integer(finalized_late["voided_transaction_count"], 0, "voided_transaction_count")

    watershed = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert_trading_gate(watershed, "ACTIVE")
