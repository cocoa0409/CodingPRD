"""Mill capacity week tests: allocation constraints, OCC on allocate, and the
closing waterfall."""
from test_helpers import (
    ApiErrorId,
    allocate_week,
    create_branch,
    create_capacity_week,
    validate_error,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers.fixtures import MILL, set_clock


def test_allocate_over_total_capacity_rejected():
    """PRD §3.1: "The sum of the two allocation legs may not exceed
    total_capacity_mbf; when it does, the request is rejected with
    ERR_CAPACITY_EXCEEDED (HTTP 409)."

    Design: Corner/errors/allocate_over_total_capacity_rejected
    """
    week = create_capacity_week(total_capacity_mbf=1000)
    version = week["version"]

    resp = api.allocate_capacity_week(
        week["id"],
        {
            "internal_alloc_mbf": 700,
            "market_alloc_mbf": 400,
            "expected_capacity_week_version": version,
        },
        MILL,
    )
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)

    updated = allocate_week(week["id"], 600, 400, version)
    assert updated["internal_alloc_mbf"] == 600
    assert updated["market_alloc_mbf"] == 400


def test_capacity_close_waterfall_grants_by_activity_then_exhausts_pool():
    """PRD §3.1: "The candidate branches are exactly those whose
    replenishment_enabled flag is true ... ranked by activity_score
    descending ... walking the ranked branches in order, each branch is
    granted the smaller of its demand and the remaining pool ... When the
    walk completes, committed_internal_mbf is the original internal_alloc_mbf
    minus whatever remains in the pool, committed_market_mbf equals
    market_alloc_mbf in full, and fill_rate_pct is the sum of the two
    committed legs divided by total_capacity_mbf, rounded half-up to 4
    decimal places."

    Design: Difficulty/combinatorial_formula/capacity_close_waterfall_grants_by_activity_then_exhausts_pool
    """
    br_a = create_branch(
        branch_code="BR-BOI", target_stock_mbf=500, activity_score=90
    )
    br_b = create_branch(
        branch_code="BR-SPO",
        species_preference="SPRUCE_PINE_FIR",
        target_stock_mbf=300,
        activity_score=70,
    )
    br_c = create_branch(
        branch_code="BR-MIS",
        region_code="MT",
        target_stock_mbf=400,
        activity_score=99,
        replenishment_enabled=False,
    )

    week = create_capacity_week(
        mill_code="MILL-ALX", week_start_date="2026-09-07",
        total_capacity_mbf=1000,
    )
    allocate_week(week["id"], 600, 400, week["version"])

    resp = api.close_capacity_week(week["id"], MILL)
    closed = validate_success(resp)
    assert closed["week_status"] == "CLOSED"
    assert closed["internal_grants"] == [
        {"branch_id": br_a["id"], "granted_mbf": 500},
        {"branch_id": br_b["id"], "granted_mbf": 100},
    ], f"grants must be ranked by activity_score desc with a depleting pool: {closed['internal_grants']}"
    assert all(g["branch_id"] != br_c["id"] for g in closed["internal_grants"])
    assert closed["committed_internal_mbf"] == 600
    assert closed["committed_market_mbf"] == 400
    assert closed["fill_rate_pct"] == 1.0


def test_capacity_close_waterfall_tiebreak_created_at_not_id():
    """PRD §3.1: "ranked by activity_score descending, with ties broken by
    the branch's created_at ascending (never by id)". With two equal-score
    branches and a 100 mbf pool, the earlier-created branch takes the whole
    pool and the later-created branch gets 0.

    Design: Difficulty/combinatorial_formula/capacity_close_waterfall_grants_by_activity_then_exhausts_pool
    """
    set_clock("2026-09-01T00:00:00Z")
    br_first = create_branch(
        branch_code="BR-EARLY", target_stock_mbf=100, activity_score=80
    )
    set_clock("2026-09-01T00:00:01Z")
    br_second = create_branch(
        branch_code="BR-LATE", target_stock_mbf=100, activity_score=80
    )

    week = create_capacity_week(
        mill_code="MILL-ALX", week_start_date="2026-09-07",
        total_capacity_mbf=1000,
    )
    allocate_week(week["id"], 100, 0, week["version"])

    closed = validate_success(api.close_capacity_week(week["id"], MILL))
    assert closed["internal_grants"] == [
        {"branch_id": br_first["id"], "granted_mbf": 100},
        {"branch_id": br_second["id"], "granted_mbf": 0},
    ], f"tie on activity_score must resolve by created_at ascending: {closed['internal_grants']}"


def test_occ_stale_capacity_week_version_rejected_412():
    """PRD §2.7: "Adjusting the allocation split of a mill capacity week
    requires the request body to carry expected_capacity_week_version, the
    client-last-observed version of the MillCapacityWeek. Each successful
    allocation bumps the week's version, so a mismatch against the week's
    current version is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_capacity_week_version_rejected_412
    """
    week = create_capacity_week(total_capacity_mbf=1000)
    v1 = week["version"]

    updated = allocate_week(week["id"], 500, 300, v1)
    v2 = updated["version"]
    assert v2 == v1 + 1

    resp = api.allocate_capacity_week(
        week["id"],
        {
            "internal_alloc_mbf": 600,
            "market_alloc_mbf": 400,
            "expected_capacity_week_version": v1,
        },
        MILL,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    final = allocate_week(week["id"], 600, 400, v2)
    assert final["internal_alloc_mbf"] == 600
    assert final["market_alloc_mbf"] == 400
