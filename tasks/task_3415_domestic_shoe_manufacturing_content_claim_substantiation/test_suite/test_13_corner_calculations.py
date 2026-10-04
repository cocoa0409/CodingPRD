"""Corner coverage: calculations (FIFO ordering, pinned rounding, variant
gate, capacity waterfall, claim thresholds, recompute overrides)."""
import pytest

from test_helpers import (
    ApiErrorId, bom_line, certify_pair, claim_with_verified_docs,
    complete_run, completed_run_kit, create_report, get_lot, get_run,
    lock_allocation, m70_completed_run, m95_completed_run, make_allocation,
    make_claim, make_component, make_factory, make_lot, make_model,
    make_run, make_verified_document, reserve_run, run_version, set_clock,
    standard_kit, start_run, substantiate, validate_error, validate_success,
)
from test_helpers import TEST_USERS, api_client

api = api_client
ADMIN = TEST_USERS["admin"]
SOURCING = TEST_USERS["sourcing"]
PLANNER = TEST_USERS["planner"]
COMPLIANCE = TEST_USERS["compliance"]
CO1 = {"X-User-ID": "co-1", "X-User-Role": "ComplianceOfficer"}


def test_fifo_consumption_respects_received_at_then_unit_cost():
    """PRD §3.5: "A `DOMESTIC_PREFERRED` line orders its eligible lots with all
    domestic lots first and import lots after; within any eligibility group,
    lots are consumed oldest first by `received_at`, breaking ties by ascending
    `unit_cost_cents`."

    Design: Corner/calculations/fifo_consumption_respects_received_at_then_unit_cost
    """
    set_clock()
    factory = make_factory()
    c_t = make_component()
    # Lot A received 2026-09-01 @500; lot B received 2026-09-02 @300.
    lot_a = make_lot(c_t["id"], quantity_received=10, unit_cost_cents=500)
    set_clock("2026-09-02T00:00:00Z")
    lot_b = make_lot(c_t["id"], quantity_received=10, unit_cost_cents=300)
    m1 = make_model(c_t["id"], style_code="MFIFO1")
    a1 = make_allocation(factory["id"], "2026-W36", 100)
    r1 = make_run(m1["id"], factory["id"], planned_units=3)
    lock_allocation(a1["id"])
    r1 = reserve_run(r1["id"])

    set_clock("2026-09-03T00:00:00Z")
    c_u = make_component("Full-grain leather upper", "UPPER")
    # Same-clock tie: lot C @700 and lot D @300 — cheaper D wins.
    lot_c = make_lot(c_u["id"], quantity_received=10, unit_cost_cents=700)
    lot_d = make_lot(c_u["id"], quantity_received=10, unit_cost_cents=300)
    m2 = make_model(c_u["id"], style_code="MFIFO2")
    a2 = make_allocation(factory["id"], "2026-W37", 250)
    r2 = make_run(m2["id"], factory["id"], planned_units=2,
                  start_day="2026-09-14", end_day="2026-09-18",
                  iso_week="2026-W37")
    lock_allocation(a2["id"])
    r2 = reserve_run(r2["id"])

    # Earlier received_at beats the cheaper price.
    assert [(e["lot_id"], e["units_consumed"], e["unit_cost_cents"])
            for e in r1["consumed_lots"]] == [(lot_a["id"], 3, 500)]
    assert get_lot(lot_a["id"])["quantity_remaining"] == 7
    assert get_lot(lot_b["id"])["quantity_remaining"] == 10
    # received_at tie broken by ascending unit cost.
    assert [(e["lot_id"], e["units_consumed"], e["unit_cost_cents"])
            for e in r2["consumed_lots"]] == [(lot_d["id"], 2, 300)]
    assert get_lot(lot_d["id"])["quantity_remaining"] == 8
    assert get_lot(lot_c["id"])["quantity_remaining"] == 10


def test_provisional_report_per_line_rounding_order():
    """PRD §3.6: "The calculation behind a report follows a pinned order:
    extended costs are rounded per line before summing, and the content
    percentage is computed last from the already-rounded components."
    PRD §2.6: "In the domestic content calculation, each bill-of-materials
    line's extended cost is rounded half up to integer cents *before* the line
    costs are summed, and the content percentage is computed last, from the
    already-rounded cost components."

    Design: Corner/calculations/provisional_report_per_line_rounding_order
    """
    set_clock()
    factory = make_factory()
    c_t = make_component()
    c_u = make_component("Full-grain leather upper", "UPPER")
    model = make_model(bom_lines=[
        bom_line(c_t["id"], quantity_per_pair=1.5, planned_unit_cost_cents=333,
                 planned_is_domestic=True),
        bom_line(c_u["id"], quantity_per_pair=1.5, planned_unit_cost_cents=333,
                 planned_is_domestic=True),
    ], style_code="MRND")
    allocation = make_allocation(factory["id"], "2026-W36", 100)
    run = make_run(model["id"], factory["id"], planned_units=1)

    report = create_report(run["id"], "PROVISIONAL")
    # round_half_up(1.5*333) = 500 per line, summed after rounding -> 1000;
    # summing first would give round(999.0) = 999.
    assert report["material_cost_cents"] == 1000
    assert report["domestic_material_cost_cents"] == 1000
    # total 1000 + 0 labor + 600 overhead = 1600; domestic value 1600.
    assert report["total_cost_cents"] == 1600
    assert report["us_content_pct"] == pytest.approx(100.00)


def test_certified_report_requires_completed_run():
    """PRD §3.6: "A `PROVISIONAL` report is a planning-time estimate and may be
    created against a run in any state other than `CANCELLED` — before
    completion and after it alike; a `CERTIFIED` report is the audited actual
    and requires the run to be `COMPLETED`, otherwise `ERR_RUN_NOT_COMPLETED`
    (HTTP 409)."

    Design: Corner/calculations/certified_report_requires_completed_run
    """
    kit = standard_kit()
    lock_allocation(kit["allocation"]["id"])
    kit["run"] = reserve_run(kit["run"]["id"])
    version = kit["run"]["version"]

    blocked = api.create_content_report(
        kit["run"]["id"], {"variant": "CERTIFIED", "expected_run_version": version},
        PLANNER)
    validate_error(blocked, ApiErrorId.ERR_RUN_NOT_COMPLETED)
    assert run_version(kit["run"]["id"]) == version  # rejection mutates nothing

    report = create_report(kit["run"]["id"], "PROVISIONAL")
    assert report["status"] == "ACTIVE"
    # material 100 (import-planned); domestic value = labor 0 + overhead 600.
    assert report["us_content_pct"] == pytest.approx(85.71)


def test_waterfall_lock_partial_fill_and_overseas_zero():
    """PRD §3.4: "For an `OVERSEAS` factory the answer is fixed:
    `domestic_reserved_units` stays 0. For a `DOMESTIC` factory, demand is
    summed over the runs of that factory and week currently in `PLANNED` or
    `MATERIAL_RESERVED`, bucketed by `run_type`: first the `GOVERNMENT` bucket,
    then `CUSTOM_BATCH`, then `STOCK`. The waterfall then fills the domestic
    pool in that strict priority order — government demand first, custom-batch
    demand second, stock demand last — each bucket taking the smaller of its
    full demand and whatever budget remains, so a bucket partially fills when
    the pool runs out mid-bucket and later buckets get nothing."

    Design: Corner/calculations/waterfall_lock_partial_fill_and_overseas_zero
    """
    set_clock()
    factory = make_factory()
    f_os = make_factory(factory_name="Hanoi Partner Plant", location_type="OVERSEAS",
                        weekly_capacity_units=2000, line_count=2,
                        labor_rate_cents_per_minute=10, overhead_cents_per_pair=100)
    component = make_component()
    make_lot(component["id"])
    model = make_model(component["id"])
    a_d = make_allocation(factory["id"], "2026-W38", 50)
    make_run(model["id"], factory["id"], run_type="CUSTOM_BATCH", planned_units=40,
             line_index=1, start_day="2026-09-14", end_day="2026-09-18",
             iso_week="2026-W38")
    make_run(model["id"], factory["id"], run_type="STOCK", planned_units=40,
             line_index=2, start_day="2026-09-14", end_day="2026-09-18",
             iso_week="2026-W38")
    a_o = make_allocation(f_os["id"], "2026-W38", 50)
    make_run(model["id"], f_os["id"], run_type="STOCK", planned_units=40,
             line_index=1, start_day="2026-09-14", end_day="2026-09-18",
             iso_week="2026-W38")

    locked_d = lock_allocation(a_d["id"])
    # GOVERNMENT 0, CUSTOM_BATCH 40 fills, STOCK partially fills 10 of 40.
    assert locked_d["domestic_reserved_units"] == 50
    assert locked_d["import_reserved_units"] == 0

    locked_o = lock_allocation(a_o["id"])
    assert locked_o["domestic_reserved_units"] == 0
    assert locked_o["import_reserved_units"] == 50


def test_claim_threshold_70_inclusive_for_qualified_claim():
    """PRD §3.8: "`MADE_IN_USA_OF_IMPORTED_MATERIALS` requires domestic final
    assembly and at least 70.00"
    PRD §3.8: "`MADE_IN_USA` requires domestic final assembly and a
    `us_content_pct` of at least 95.00"

    Design: Corner/calculations/claim_threshold_70_inclusive_for_qualified_claim
    """
    kit = m70_completed_run()
    assert kit["report"]["us_content_pct"] == pytest.approx(70.00)

    docs = claim_with_verified_docs(
        kit["model"]["id"], "MADE_IN_USA_OF_IMPORTED_MATERIALS")
    claim = substantiate(docs["claim"]["id"], kit["report"]["id"])
    assert claim["status"] == "SUBSTANTIATED"  # 70.00 >= 70.00 inclusive

    plain = make_claim(kit["model"]["id"], "MADE_IN_USA")
    resp = api.substantiate_claim(plain["id"], {"report_id": kit["report"]["id"]},
                                  COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_CONTENT_THRESHOLD_NOT_MET)  # 70.00 < 95.00


def test_imported_claim_substantiates_on_overseas_run():
    """PRD §3.8: "and `IMPORTED` passes when final assembly is not domestic or
    the percentage is below 20.00."
    PRD §3.6: "Finally, `final_assembly_domestic` is true exactly when the
    run's factory has `location_type` `DOMESTIC`."

    Design: Corner/calculations/imported_claim_substantiates_on_overseas_run
    """
    set_clock()
    f_os = make_factory(factory_name="Hanoi Partner Plant", location_type="OVERSEAS",
                        weekly_capacity_units=2000, line_count=2,
                        labor_rate_cents_per_minute=10, overhead_cents_per_pair=100)
    component = make_component()
    make_lot(component["id"])  # domestic thread lot @100
    model = make_model(component["id"])
    allocation = make_allocation(f_os["id"], "2026-W36", 300)
    run = make_run(model["id"], f_os["id"], planned_units=100)
    lock_allocation(allocation["id"])
    reserve_run(run["id"])
    certify_pair(f_os["id"])
    start_run(run["id"])
    complete_run(run["id"], (2, 2, 2))
    report = create_report(run["id"], "CERTIFIED")
    # material 100 (domestic lot) of total 100 + 60 labor + 100 overhead = 260;
    # foreign assembly excludes labor/overhead from the numerator.
    assert report["final_assembly_domestic"] is False
    assert report["us_content_pct"] == pytest.approx(38.46)

    docs = claim_with_verified_docs(model["id"], "IMPORTED")
    claim = substantiate(docs["claim"]["id"], report["id"])
    assert claim["status"] == "SUBSTANTIATED"

    miusa = make_claim(model["id"], "MADE_IN_USA")
    resp = api.substantiate_claim(miusa["id"], {"report_id": report["id"]},
                                  COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_CONTENT_THRESHOLD_NOT_MET)


def test_labor_record_rejection_recomputes_content():
    """PRD §3.8: "Likewise in hop one, a rejected `ASSEMBLY_LABOR_RECORD`
    linked to a run with an `ACTIVE` `CERTIFIED` report triggers a superseding
    recompute with labor and overhead treated as non-domestic."

    Design: Corner/calculations/labor_record_rejection_recomputes_content
    """
    kit = m95_completed_run()
    labor_doc = make_verified_document("ASSEMBLY_LABOR_RECORD",
                                       "production_run_id", kit["run"]["id"])
    validate_success(api.reject_document(labor_doc["id"], CO1))

    reports = validate_success(api.list_content_reports(
        kit["run"]["id"], PLANNER, params={"variant": "CERTIFIED"}))
    by_id = {r["id"]: r for r in reports}
    assert by_id[kit["report"]["id"]]["status"] == "SUPERSEDED"
    active = [r for r in reports if r["status"] == "ACTIVE"]
    assert len(active) == 1
    # Labor 300 + overhead 600 excluded: domestic value = 1000 of total 2000.
    assert active[0]["us_content_pct"] == pytest.approx(50.00)
    assert active[0]["material_cost_cents"] == 1100
