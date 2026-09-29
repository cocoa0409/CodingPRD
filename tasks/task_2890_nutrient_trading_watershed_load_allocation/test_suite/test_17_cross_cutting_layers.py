"""Cross-cutting layers: optimistic concurrency on both guarded version fields."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_STALE_TMDL_VERSION
from test_helpers.assertions import (
    assert_batch_buckets,
    assert_integer,
    assert_load,
    assert_pagination_meta,
)
from test_helpers.test_users import ADMIN, ANALYST, REGISTRY


def test_replaying_the_tmdl_version_the_first_run_consumed_is_rejected(api):
    """The accepted run bumps the parent, so the captured version is stale for the next.

    "The expected version must equal the assessment's current `version`, otherwise
    the request is rejected with `ERR_STALE_TMDL_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_layers/stale_expected_tmdl_version_on_an_allocation_run_is_rejected
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
    version_at_creation = assessment["version"]
    source = fx.make_source(
        api, assessment["id"], r_out["id"], "Village WWTP", "POINT", 5000.00, 0.5000
    )
    first_run = fx.make_allocation_run(
        api, assessment["id"], "RUN-1", expected_version=version_at_creation
    )
    assert_load(first_run["wla_total_lbs_yr"], 27360.00, "wla_total_lbs_yr")
    assert_load(first_run["la_total_lbs_yr"], 0.00, "la_total_lbs_yr")
    assert_load(first_run["reserve_allocation_lbs_yr"], 20640.00, "reserve_allocation_lbs_yr")

    replayed = api.create_allocation_run(
        assessment["id"],
        f.allocation_run_payload(
            "RUN-2", version_at_creation, method="CONTROLLABILITY_WEIGHTED"
        ),
        ANALYST,
    )

    validate_error(replayed, ERR_STALE_TMDL_VERSION, 412)

    _, meta = validate_paginated(
        api.list_allocation_runs(ANALYST, {"tmdl_assessment_id": assessment["id"]})
    )
    assert_pagination_meta(meta, 10, 0, 1, False)
    survivor = get_success_data(api.get_allocation_run(first_run["id"], ANALYST))
    assert survivor["status"] == "ACTIVE", survivor

    current_version = fx.read_assessment_version(api, assessment["id"])
    assert current_version > version_at_creation, (current_version, version_at_creation)

    second_run = validate_success(
        api.create_allocation_run(
            assessment["id"],
            f.allocation_run_payload(
                "RUN-2", current_version, method="CONTROLLABILITY_WEIGHTED"
            ),
            ANALYST,
        ),
        201,
    )

    assert second_run["status"] == "ACTIVE", second_run
    assert second_run["variant"] == "PROVISIONAL", second_run
    superseded = get_success_data(api.get_allocation_run(first_run["id"], ANALYST))
    assert superseded["status"] == "SUPERSEDED", superseded

    repointed = get_success_data(api.get_source_assessment(source["id"], ANALYST))
    assert repointed["allocation_run_id"] == second_run["id"], repointed
    assert_load(repointed["allocated_load_lbs_yr"], 27360.00, "allocated_load_lbs_yr")

    reserve = get_success_data(api.get_watershed(watershed["id"], ADMIN))
    assert_load(reserve["reserve_pool_lbs"], 20640.00, "reserve_pool_lbs")


def test_every_registry_write_to_a_batch_bumps_its_version_and_a_read_does_not(api):
    """Certification, listing and retirement each move the OCC field by exactly one.

    "Listing increments the batch's `version` by 1", "the batch's `version`
    increments by 1" on retirement, and the minted batch opens at version 1.

    Design: Corner/cross_cutting_layers/credit_batch_version_advances_on_every_registry_write
    """
    world = fx.scr_active_program(api)
    producer_id = fx.make_producer(api)["id"]
    project = fx.implemented_project(api, producer_id, world["reaches"]["r_up"]["id"], "T-101")

    issued = validate_success(api.certify_practice_project(project["id"], REGISTRY), 201)

    assert_integer(issued["version"], 1, "version at issue")
    assert issued["status"] == "ISSUED", issued

    listed = validate_success(api.list_credit_batch(issued["id"], REGISTRY))

    assert_integer(listed["version"], 2, "version after listing")
    assert listed["status"] == "LISTED", listed
    assert_batch_buckets(listed, available=520.00, reserved=0.00, retired=0.00, invalidated=0.00)

    retired = validate_success(
        api.retire_credit_batch(
            issued["id"], f.retire_payload(20.00, "Reserve-pool contribution."), REGISTRY
        )
    )

    assert_integer(retired["version"], 3, "version after retirement")
    assert_batch_buckets(retired, available=500.00, reserved=0.00, retired=20.00, invalidated=0.00)
    assert retired["status"] == "LISTED", retired

    reread = get_success_data(api.get_credit_batch(issued["id"], REGISTRY))
    assert_integer(reread["version"], 3, "version after a read")

    watershed = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert_load(watershed["reserve_pool_lbs"], 2420.40, "reserve_pool_lbs")
