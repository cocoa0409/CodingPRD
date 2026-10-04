"""Depth probes: boundary precision (inclusive 95.00 claim threshold; exact-fit
weekly capacity pool)."""
import pytest

from test_helpers import (
    ApiErrorId, claim_with_verified_docs, get_lot, get_run, lock_allocation,
    m95_completed_run, make_allocation, make_run, reserve_run, set_clock,
    standard_kit, substantiate, validate_error, validate_success,
)
from test_helpers import TEST_USERS, api_client

api = api_client
PLANNER = TEST_USERS["planner"]
COMPLIANCE = TEST_USERS["compliance"]


def test_substantiate_accepts_exactly_95_percent():
    """PRD §3.8: "The threshold check compares against the report's stored
    two-decimal `us_content_pct` and its `final_assembly_domestic` flag, with
    all thresholds inclusive: `MADE_IN_USA` requires domestic final assembly
    and a `us_content_pct` of at least 95.00"

    Design: Difficulty/boundary_precision_check/content_threshold_95_inclusive_boundary
    """
    kit = m95_completed_run()
    assert kit["report"]["us_content_pct"] == pytest.approx(95.00)
    docs = claim_with_verified_docs(kit["model"]["id"], "MADE_IN_USA")

    claim = substantiate(docs["claim"]["id"], kit["report"]["id"])
    assert claim["status"] == "SUBSTANTIATED"
    assert claim["report_id"] == kit["report"]["id"]


def test_substantiate_at_95_pins_report_and_stamps_time():
    """PRD §3.8: "On success the claim pins `report_id` to the substantiating
    report, stamps `substantiated_at` from the logical clock — and, on the
    re-substantiation path, clears `published_at` to null — increments its
    `version`, and sits in `SUBSTANTIATED`."

    Design: Difficulty/boundary_precision_check/content_threshold_95_inclusive_boundary
    """
    kit = m95_completed_run()
    docs = claim_with_verified_docs(kit["model"]["id"], "MADE_IN_USA")
    claim = substantiate(docs["claim"]["id"], kit["report"]["id"])
    # 95.00 satisfies the inclusive boundary; the pin and stamp are observable.
    assert claim["version"] == 2
    assert claim["substantiated_at"].startswith("2026-09-01T00:00:00")
    assert claim["published_at"] is None


def _capacity_boundary_kit():
    """Cleared DOMESTIC factory (3 lines); MCAP (one IMPORT_ALLOWED thread
    line, lot 1000 @100); allocation total 60; STOCK runs of 40 / 20 / 1 on
    lines 1-3, all created before lock (waterfall fills the domestic pool to
    exactly 60)."""
    kit = standard_kit(with_run=False, with_allocation=False, factory_overrides={
        "factory_name": "Norridgewock ME Plant", "government_cleared": True,
    }, model_overrides={"style_code": "MCAP"})
    kit["allocation"] = make_allocation(kit["factory"]["id"], "2026-W36", 60)
    r1 = make_run(kit["model"]["id"], kit["factory"]["id"], planned_units=40,
                  line_index=1)
    r2 = make_run(kit["model"]["id"], kit["factory"]["id"], planned_units=20,
                  line_index=2)
    r3 = make_run(kit["model"]["id"], kit["factory"]["id"], planned_units=1,
                  line_index=3)
    lock_allocation(kit["allocation"]["id"])
    kit.update({"r1": r1, "r2": r2, "r3": r3})
    return kit


def test_weekly_pool_exact_fit_is_allowed():
    """PRD §3.5: "The reservation is rejected with
    `ERR_CAPACITY_WEEK_EXCEEDED` (HTTP 422) unless the consumed total plus this
    run's `planned_units` stays within the pool — equality is allowed, so a run
    may take the week's last pair."

    Design: Difficulty/boundary_precision_check/weekly_capacity_pool_exact_fit_boundary
    """
    kit = _capacity_boundary_kit()
    r1 = reserve_run(kit["r1"]["id"])
    r2 = reserve_run(kit["r2"]["id"])
    assert r1["status"] == "MATERIAL_RESERVED"
    assert r2["status"] == "MATERIAL_RESERVED"
    # 40 + 20 == 60 == domestic pool: exact fit reserved successfully.
    assert get_lot(kit["lot"]["id"])["quantity_remaining"] == 940


def test_weekly_pool_one_unit_overflow_is_rejected():
    """PRD §3.5: "The reservation is rejected with
    `ERR_CAPACITY_WEEK_EXCEEDED` (HTTP 422) unless the consumed total plus this
    run's `planned_units` stays within the pool — equality is allowed, so a run
    may take the week's last pair."

    Design: Difficulty/boundary_precision_check/weekly_capacity_pool_exact_fit_boundary
    """
    kit = _capacity_boundary_kit()
    reserve_run(kit["r1"]["id"])
    reserve_run(kit["r2"]["id"])

    resp = api.reserve_materials(kit["r3"]["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_CAPACITY_WEEK_EXCEEDED)  # 60 + 1 > 60
    assert get_run(kit["r3"]["id"])["status"] == "PLANNED"
    assert get_lot(kit["lot"]["id"])["quantity_remaining"] == 940
