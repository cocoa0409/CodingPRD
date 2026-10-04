"""Corner coverage: optimistic concurrency on report creation and allocation
shift (sequential stale-version replays)."""
from test_helpers import (
    ApiErrorId, create_report, get_allocation, lock_allocation, reserve_run,
    run_version, shift_allocation_payload, standard_kit, validate_error,
    validate_paginated, validate_success,
)
from test_helpers import TEST_USERS, api_client

api = api_client
ADMIN = TEST_USERS["admin"]
PLANNER = TEST_USERS["planner"]


def test_occ_report_create_with_stale_run_version_returns_412():
    """PRD §2.7: "A request to create a content report on a production run must
    carry `expected_run_version`, a non-optional field holding the `version` of
    the run as the client last observed it. If the run's current `version` has
    advanced past the supplied value, the request is rejected with
    `ERR_STALE_RUN_VERSION` (HTTP 412). This guard exists because a successful
    creation supersedes the previously `ACTIVE` report of the same variant — a
    legitimate supersede under the report lifecycle — so a writer holding a
    stale run version would otherwise supersede a report it never saw."

    Design: Corner/complexity_layers/occ_report_create_with_stale_run_version_returns_412
    """
    kit = standard_kit()
    lock_allocation(kit["allocation"]["id"])
    run = reserve_run(kit["run"]["id"])
    observed = run["version"]  # 2 after reserve

    created = create_report(kit["run"]["id"], "PROVISIONAL")
    assert created["status"] == "ACTIVE"
    assert run_version(kit["run"]["id"]) == observed + 1

    replay = api.create_content_report(
        kit["run"]["id"],
        {"variant": "PROVISIONAL", "expected_run_version": observed}, PLANNER)
    validate_error(replay, ApiErrorId.ERR_STALE_RUN_VERSION)

    # A stale writer does not supersede: still exactly one PROVISIONAL report.
    reports, meta = validate_paginated(
        api.list_content_reports(kit["run"]["id"], PLANNER,
                                 params={"variant": "PROVISIONAL"}))
    assert len(reports) == 1 and reports[0]["id"] == created["id"]
    assert reports[0]["status"] == "ACTIVE"


def test_occ_shift_with_stale_allocation_version_returns_412():
    """PRD §2.7: "A request to shift units between the domestic and import
    pools of a capacity allocation must carry `expected_allocation_version`, a
    non-optional field holding the allocation's last observed `version`. If the
    allocation's current `version` has advanced — for example because a lock
    waterfall or a prior shift moved the buckets — the request is rejected with
    `ERR_STALE_ALLOCATION_VERSION` (HTTP 412), preventing a stale writer from
    re-splitting pools it never saw."

    Design: Corner/complexity_layers/occ_shift_with_stale_allocation_version_returns_412
    """
    kit = standard_kit(with_run=False)
    allocation = lock_allocation(kit["allocation"]["id"])
    observed = allocation["version"]  # 2 after lock; zero demand -> 0 / 100

    first = validate_success(api.shift_allocation(
        allocation["id"],
        shift_allocation_payload("TO_DOMESTIC", 10, observed), ADMIN))
    assert first["domestic_reserved_units"] == 10
    assert first["import_reserved_units"] == 90

    replay = api.shift_allocation(
        allocation["id"],
        shift_allocation_payload("TO_DOMESTIC", 10, observed), ADMIN)
    validate_error(replay, ApiErrorId.ERR_STALE_ALLOCATION_VERSION)

    after = get_allocation(allocation["id"])
    assert after["domestic_reserved_units"] == 10
    assert after["import_reserved_units"] == 90
