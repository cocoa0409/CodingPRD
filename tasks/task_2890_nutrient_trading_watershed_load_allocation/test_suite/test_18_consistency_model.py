"""Immediate consistency: one multi-family write is visible in every dependent read."""

from prd_bench_local_runner.testing import get_success_data, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_integer,
    assert_load,
    assert_pagination_meta,
    field_sequence,
)
from test_helpers.test_users import ADMIN, ANALYST


def test_the_allocation_run_is_visible_in_every_dependent_read_at_once(api):
    """The run response, the sources, the assessment and the watershed all agree immediately.

    "Every write is immediately visible to every subsequent read, and every
    derived or denormalised field named in this specification is recomputed
    within the same request that changes its inputs."

    Design: Corner/consistency_model/allocation_run_write_is_immediately_visible_in_every_dependent_read
    """
    world = fx.scr_base(api)

    run = validate_success(
        api.create_allocation_run(
            world["assessment_id"],
            f.allocation_run_payload(
                "RUN-1", fx.read_assessment_version(api, world["assessment_id"])
            ),
            ANALYST,
        ),
        201,
    )

    assert_load(run["allocable_load_lbs_yr"], 48000.00, "allocable_load_lbs_yr")
    assert_load(run["wla_total_lbs_yr"], 27360.00, "wla_total_lbs_yr")
    assert_load(run["la_total_lbs_yr"], 18240.00, "la_total_lbs_yr")
    assert_load(run["reserve_allocation_lbs_yr"], 2400.00, "reserve_allocation_lbs_yr")

    watershed = get_success_data(api.get_watershed(world["watershed_id"], ANALYST))
    assert_load(watershed["allocated_wla_total_lbs_yr"], 27360.00, "allocated_wla_total_lbs_yr")
    assert_load(watershed["allocated_la_total_lbs_yr"], 18240.00, "allocated_la_total_lbs_yr")
    assert_load(watershed["reserve_pool_lbs"], 2400.00, "reserve_pool_lbs")

    assessment = get_success_data(api.get_tmdl_assessment(world["assessment_id"], ANALYST))
    assert_load(assessment["allocable_load_lbs_yr"], 48000.00, "allocable_load_lbs_yr")
    assert_load(assessment["margin_of_safety_lbs_yr"], 6000.00, "margin_of_safety_lbs_yr")
    assert_load(
        assessment["effective_background_lbs_yr"], 6000.00, "effective_background_lbs_yr"
    )

    rows, meta = validate_paginated(
        api.list_source_assessments(ANALYST, {"allocation_run_id": run["id"]})
    )
    assert len(rows) == 4, rows
    assert_pagination_meta(meta, 10, 0, 4, False)
    allocated = field_sequence(rows, "allocated_load_lbs_yr")
    for amount in allocated:
        assert amount is not None, rows
    assert_load(sum(allocated), 45600.00, "sum of the four per-source allocations")

    reread_run = get_success_data(api.get_allocation_run(run["id"], ANALYST))
    for field in (
        "effective_background_lbs_yr",
        "margin_of_safety_lbs_yr",
        "allocable_load_lbs_yr",
        "point_pool_lbs_yr",
        "nonpoint_pool_lbs_yr",
        "wla_total_lbs_yr",
        "la_total_lbs_yr",
        "reserve_allocation_lbs_yr",
    ):
        assert_load(reread_run[field], run[field], field)
    assert_integer(reread_run["included_source_count"], 4, "included_source_count")
    assert reread_run["status"] == "ACTIVE", reread_run
    assert reread_run["variant"] == run["variant"], (reread_run, run)

    expected = {"sa_p1": 21888.00, "sa_p2": 5472.00, "sa_n1": 13680.00, "sa_n2": 4560.00}
    for key, amount in expected.items():
        source = get_success_data(api.get_source_assessment(world[key]["id"], ANALYST))
        assert_load(source["allocated_load_lbs_yr"], amount, "{} allocated_load_lbs_yr".format(key))
        assert source["allocation_run_id"] == run["id"], source

    unchanged_watershed = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert_load(unchanged_watershed["reserve_pool_lbs"], 2400.00, "reserve_pool_lbs on re-read")
