"""Declared formulas, their constants, their input sets and their rounding order."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_NO_INCLUDED_SOURCES, ERR_ZONE_NOT_ELIGIBLE
from test_helpers.assertions import (
    assert_batch_buckets,
    assert_instant_equals,
    assert_integer,
    assert_is_null,
    assert_load,
    assert_load_conservation,
    assert_pagination_meta,
    assert_pct,
    assert_ratio,
)
from test_helpers.constants import CLOCK_BASE
from test_helpers.test_users import (
    ADMIN,
    ANALYST,
    PERMITTEE_1,
    PERMITTEE_2,
    PERMIT_WRITER,
    REGISTRY,
)


def test_the_sample_load_multiplies_in_both_declared_constants(api):
    """Four samples on one reach pin the 5.393 and 365 constants and the half-up rounding.

    "multiply the measured concentration by the flow, multiply that product by the
    concentration-to-pounds-per-day conversion factor of 5.393, multiply again by 365
    days in the year, and round the result half-up to 2 decimal places"

    Design: Corner/calculations/monitoring_sample_load_applies_the_declared_conversion_constants
    """
    fx.pin_clock(api)
    watershed = fx.scr_watershed(api)
    r_bg = fx.make_reach(
        api,
        watershed["id"],
        "R_BG",
        trading_zone_code="Z3",
        reach_class="BACKGROUND",
        delivery_factor=0.7000,
    )

    expected = (
        ("2026-04-01T12:00:00Z", 0.0549, 1000.00, 108067.63),
        ("2026-04-02T12:00:00Z", 0.0500, 1000.00, 98422.25),
        ("2026-04-03T12:00:00Z", 0.0250, 100.00, 4921.11),
        ("2026-04-04T12:00:00Z", 0.0200, 100.00, 3936.89),
    )
    for sample_datetime, conc, flow, load in expected:
        created = validate_success(
            api.create_monitoring_sample(
                f.monitoring_sample_payload(r_bg["id"], sample_datetime, conc, flow), ANALYST
            ),
            201,
        )
        assert_load(created["computed_load_lbs_yr"], load, "computed_load_lbs_yr")
        assert created["qa_status"] == "ACCEPTED", created
        assert created["reach_id"] == r_bg["id"], created

    _, meta = validate_paginated(api.list_monitoring_samples(ANALYST, {"reach_id": r_bg["id"]}))
    assert_pagination_meta(meta, 10, 0, 4, False)


def test_the_allocation_waterfall_pins_every_pool_and_every_per_source_share(api):
    """One run on the canonical fixture reproduces the whole seven-step waterfall.

    "The run's `wla_total_lbs_yr` is the sum of the rounded point allocations and its
    `la_total_lbs_yr` the sum of the rounded nonpoint allocations. ... The run also
    publishes its work as an `allocations` array in the same pinned order"

    Design: Corner/calculations/wasteload_allocation_waterfall_produces_the_pinned_pools_and_per_source_shares
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

    assert run["variant"] == "PROVISIONAL", run
    assert run["status"] == "ACTIVE", run
    assert_load(run["effective_background_lbs_yr"], 6000.00, "effective_background_lbs_yr")
    assert_load(run["margin_of_safety_lbs_yr"], 6000.00, "margin_of_safety_lbs_yr")
    assert_load(run["allocable_load_lbs_yr"], 48000.00, "allocable_load_lbs_yr")
    assert_load(run["point_pool_lbs_yr"], 27360.00, "point_pool_lbs_yr")
    assert_load(run["nonpoint_pool_lbs_yr"], 18240.00, "nonpoint_pool_lbs_yr")
    assert_load(run["wla_total_lbs_yr"], 27360.00, "wla_total_lbs_yr")
    assert_load(run["la_total_lbs_yr"], 18240.00, "la_total_lbs_yr")
    assert_load(run["reserve_allocation_lbs_yr"], 2400.00, "reserve_allocation_lbs_yr")
    assert_integer(run["included_source_count"], 4, "included_source_count")

    allocations = run["allocations"]
    assert len(allocations) == 4, allocations
    assert [row["source_assessment_id"] for row in allocations] == [
        world["sa_p1"]["id"],
        world["sa_p2"]["id"],
        world["sa_n1"]["id"],
        world["sa_n2"]["id"],
    ], allocations
    assert [row["source_type"] for row in allocations] == [
        "POINT",
        "POINT",
        "NONPOINT",
        "NONPOINT",
    ], allocations
    for row, weight, allocated in zip(
        allocations,
        (20000.00, 5000.00, 30000.00, 10000.00),
        (21888.00, 5472.00, 13680.00, 4560.00),
    ):
        assert_load(row["existing_load_lbs_yr"], weight, "existing_load_lbs_yr")
        assert_load(row["weight"], weight, "weight under PRO_RATA_BY_EXISTING_LOAD")
        assert_load(row["allocated_load_lbs_yr"], allocated, "allocated_load_lbs_yr")

    total = (
        run["effective_background_lbs_yr"]
        + run["margin_of_safety_lbs_yr"]
        + run["wla_total_lbs_yr"]
        + run["la_total_lbs_yr"]
        + run["reserve_allocation_lbs_yr"]
    )
    assert_load(total, 60000.00, "background + MOS + WLA + LA + reserve")

    first = get_success_data(api.get_source_assessment(world["sa_p1"]["id"], ANALYST))
    assert_load(first["allocated_load_lbs_yr"], 21888.00, "allocated_load_lbs_yr")
    assert first["allocation_run_id"] == run["id"], first
    last = get_success_data(api.get_source_assessment(world["sa_n2"]["id"], ANALYST))
    assert_load(last["allocated_load_lbs_yr"], 4560.00, "allocated_load_lbs_yr")

    assessment = get_success_data(api.get_tmdl_assessment(world["assessment_id"], ANALYST))
    assert_load(assessment["allocable_load_lbs_yr"], 48000.00, "allocable_load_lbs_yr")
    assert_load(assessment["wla_total_lbs_yr"], 27360.00, "wla_total_lbs_yr")
    assert_load_conservation(assessment)

    watershed = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert_load(watershed["reserve_pool_lbs"], 2400.00, "reserve_pool_lbs")


def test_a_run_with_only_excluded_sources_is_refused_then_one_source_takes_the_pool(api):
    """EXCLUDED rows are invisible: first there is nothing to allocate, then one row wins all.

    "Rows in status `INVENTORIED` and `ADJUSTED` enter allocation; rows in status
    `EXCLUDED` never do, and are omitted both from the weight denominators and from
    the run's per-source output. ... When a group is empty its entire pool is absorbed
    into this reserve term."

    Design: Corner/calculations/allocation_run_with_only_excluded_sources_is_rejected
    """
    fx.pin_clock(api)
    watershed = fx.scr_watershed(api)
    r_out = fx.make_reach(
        api,
        watershed["id"],
        "R_OUT",
        trading_zone_code="Z2",
        reach_class="COMPLIANCE_POINT",
        delivery_factor=1.0000,
    )
    assessment = fx.make_assessment(api, watershed["id"])
    sa_x1 = fx.make_source(
        api,
        assessment["id"],
        r_out["id"],
        "Decommissioned Outfall",
        "POINT",
        40000.00,
        0.9000,
        status="EXCLUDED",
    )
    sa_x2 = fx.make_source(
        api,
        assessment["id"],
        r_out["id"],
        "Retired Feedlot",
        "NONPOINT",
        10000.00,
        0.2000,
        status="EXCLUDED",
    )

    refused = api.create_allocation_run(
        assessment["id"],
        f.allocation_run_payload("RUN-EMPTY", fx.read_assessment_version(api, assessment["id"])),
        ANALYST,
    )

    validate_error(refused, ERR_NO_INCLUDED_SOURCES, 422)
    _, meta = validate_paginated(
        api.list_allocation_runs(ANALYST, {"tmdl_assessment_id": assessment["id"]})
    )
    assert_pagination_meta(meta, 10, 0, 0, False)

    sa_p = fx.make_source(
        api, assessment["id"], r_out["id"], "Village WWTP", "POINT", 5000.00, 0.5000
    )

    run = fx.make_allocation_run(api, assessment["id"], "RUN-1")

    assert_integer(run["included_source_count"], 1, "included_source_count")
    assert_load(run["allocable_load_lbs_yr"], 48000.00, "allocable_load_lbs_yr")
    assert_load(run["point_pool_lbs_yr"], 27360.00, "point_pool_lbs_yr")
    assert_load(run["nonpoint_pool_lbs_yr"], 18240.00, "nonpoint_pool_lbs_yr")
    assert_load(run["wla_total_lbs_yr"], 27360.00, "wla_total_lbs_yr")
    assert_load(run["la_total_lbs_yr"], 0.00, "la_total_lbs_yr")
    assert_load(run["reserve_allocation_lbs_yr"], 20640.00, "reserve_allocation_lbs_yr")
    assert len(run["allocations"]) == 1, run
    assert run["allocations"][0]["source_assessment_id"] == sa_p["id"], run
    assert_load(run["allocations"][0]["allocated_load_lbs_yr"], 27360.00, "allocated_load_lbs_yr")

    excluded_point = get_success_data(api.get_source_assessment(sa_x1["id"], ANALYST))
    assert_is_null(excluded_point["allocated_load_lbs_yr"], "allocated_load_lbs_yr")
    assert_is_null(excluded_point["allocation_run_id"], "allocation_run_id")
    excluded_nonpoint = get_success_data(api.get_source_assessment(sa_x2["id"], ANALYST))
    assert_is_null(excluded_nonpoint["allocated_load_lbs_yr"], "allocated_load_lbs_yr")


def test_the_gap_is_measured_against_the_applicable_limit_and_floored_at_zero(api):
    """One permit reports over its interim limit, the other under its own, and neither goes negative.

    "It computes `compliance_gap_lbs` as the reported annual load less the applicable
    limit less the credits already applied ... with the result floored at zero so an
    over-complying permit shows a gap of exactly 0.00"

    Design: Corner/calculations/permit_compliance_gap_is_reported_load_less_the_applicable_limit_and_credits
    """
    world = fx.scr_allocated(api)
    permit_1 = fx.make_permit(
        api,
        world["watershed_id"],
        world["sa_p1"]["id"],
        permit_number="OH-0001",
        permittee_user_id="user-permittee-1",
        design_flow_mgd=4.5000,
        current_annual_load_lbs=30000.00,
    )
    permit_2 = fx.make_permit(
        api,
        world["watershed_id"],
        world["sa_p2"]["id"],
        permit_number="OH-0002",
        permittee_user_id="user-permittee-2",
        design_flow_mgd=1.2000,
        current_annual_load_lbs=6000.00,
    )
    fx.derive_limits(api, permit_1["id"])
    fx.derive_limits(api, permit_2["id"])

    short = fx.file_annual_report(api, permit_1["id"], 25000.00, permittee_headers=PERMITTEE_1)

    assert_load(short["applicable_limit_lbs_yr"], 23916.00, "applicable_limit_lbs_yr")
    assert_load(short["final_limit_lbs_yr"], 21888.00, "final_limit_lbs_yr")
    assert_load(short["compliance_gap_lbs"], 1084.00, "compliance_gap_lbs")
    assert short["compliance_status"] == "SHORTFALL", short
    assert_load(short["credit_applied_lbs"], 0.00, "credit_applied_lbs")
    assert short["enforcement_flag"] is False, short

    under = fx.file_annual_report(api, permit_2["id"], 4000.00, permittee_headers=PERMITTEE_2)

    assert_load(under["applicable_limit_lbs_yr"], 5472.00, "applicable_limit_lbs_yr")
    assert under["schedule_tier"] == "TIER_A", under
    assert_load(under["compliance_gap_lbs"], 0.00, "compliance_gap_lbs is floored at zero")
    assert under["compliance_status"] == "IN_COMPLIANCE", under

    reread = validate_success(api.get_permit(permit_1["id"], PERMIT_WRITER))
    assert_load(reread["reported_annual_load_lbs"], 25000.00, "reported_annual_load_lbs")
    assert reread["schedule_tier"] == "TIER_B", reread
    assert_pct(reread["required_reduction_pct"], 27.04, "required_reduction_pct")

    _, meta = validate_paginated(
        api.list_permits(
            PERMIT_WRITER,
            {"watershed_id": world["watershed_id"], "compliance_status": "SHORTFALL"},
        )
    )
    assert_pagination_meta(meta, 10, 0, 1, False)


def test_certification_prorates_by_verified_acres_and_serializes_whole_pounds(api):
    """The verified acreage drives the mint, the floor keeps the residual, and the counter advances.

    "it is the verified acreage, not the enrolled acreage, that prorates the reduction.
    The registry then serializes in whole pounds: `issued_lbs` is that gross reduction
    rounded down to the next lower whole number, and `residual_lbs` is the gross
    reduction less that whole number"

    Design: Corner/calculations/certification_serializes_whole_pounds_and_keeps_the_fractional_residual
    """
    world = fx.scr_active_program(api)
    before = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert_integer(before["serial_counter"], 0, "serial_counter before any mint")
    producer_id = fx.make_producer(api)["id"]
    project = fx.implemented_project(api, producer_id, world["reaches"]["r_up"]["id"], "T-101")

    batch = validate_success(api.certify_practice_project(project["id"], REGISTRY), 201)

    assert batch["status"] == "ISSUED", batch
    assert_load(batch["gross_reduction_lbs_yr"], 520.40, "gross_reduction_lbs_yr")
    assert_integer(batch["issued_lbs"], 520, "issued_lbs")
    assert_load(batch["residual_lbs"], 0.40, "residual_lbs")
    assert_batch_buckets(batch, available=520.00, reserved=0.00, retired=0.00, invalidated=0.00)
    assert_ratio(batch["verified_ratio"], 1.0000, "verified_ratio")
    assert_integer(batch["vintage_year"], 2026, "vintage_year")
    assert batch["serial_prefix"] == "OH-SCR-2026", batch
    assert_integer(batch["serial_start"], 1, "serial_start")
    assert_integer(batch["serial_end"], 520, "serial_end")
    assert batch["practice_project_id"] == project["id"], batch

    watershed = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert_integer(watershed["serial_counter"], 520, "serial_counter after the mint")

    certified = get_success_data(api.get_practice_project(project["id"], REGISTRY))
    assert certified["status"] == "CERTIFIED", certified
    assert_instant_equals(certified["certified_at"], CLOCK_BASE, "certified_at")


def test_a_batch_on_the_outlet_reach_cannot_serve_a_permit_upstream_of_it(api):
    """The downstream walk runs off the end of the network immediately.

    "If the current reach has no downstream neighbour, the walk has run off the end of
    the network and the proposal is rejected with `ERR_ZONE_NOT_ELIGIBLE`. ... Because
    the walk only ever moves downstream, a buyer sitting upstream of the generator, or
    on a disconnected branch, is never eligible."

    Design: Corner/calculations/credit_transaction_to_an_upstream_permit_is_rejected_as_zone_not_eligible
    """
    world = fx.scr_trading_ready(api)
    outlet = fx.listed_batch(
        api,
        world["producer_id"],
        world["reaches"]["r_out"]["id"],
        "T-900",
        practice_type="RIPARIAN_BUFFER",
    )
    batch_id = outlet["batch"]["id"]
    version_before = fx.read_batch_version(api, batch_id)
    assert_batch_buckets(
        outlet["batch"], available=520.00, reserved=0.00, retired=0.00, invalidated=0.00
    )

    refused = api.propose_credit_transaction(
        f.credit_transaction_payload(batch_id, world["permit_id"], 500.00, 2026, version_before),
        PERMITTEE_1,
    )

    validate_error(refused, ERR_ZONE_NOT_ELIGIBLE, 422)

    _, meta = validate_paginated(
        api.list_credit_transactions(REGISTRY, {"permit_id": world["permit_id"]})
    )
    assert_pagination_meta(meta, 10, 0, 0, False)

    untouched = get_success_data(api.get_credit_batch(batch_id, REGISTRY))
    assert_batch_buckets(untouched, available=520.00, reserved=0.00, retired=0.00, invalidated=0.00)
    assert_integer(untouched["version"], version_before, "version after a rejected proposal")

    permit = validate_success(api.get_permit(world["permit_id"], PERMITTEE_1))
    assert_load(permit["compliance_gap_lbs"], 1084.00, "compliance_gap_lbs")
    assert_load(permit["credit_applied_lbs"], 0.00, "credit_applied_lbs")
    assert permit["compliance_status"] == "SHORTFALL", permit
