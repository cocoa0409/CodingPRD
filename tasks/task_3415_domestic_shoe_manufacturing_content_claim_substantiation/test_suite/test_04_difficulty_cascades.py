"""Depth probes: transitive cascades (evidence rejection -> report -> claim ->
contract; factory suspension -> runs -> lots -> orders)."""
import pytest

from test_helpers import (
    accept_order, api_client, berry_completed_run, bom_line, certify_pair,
    get_claim, get_contract, get_lot, get_order, get_run, lock_allocation,
    make_allocation, make_claim, make_component, make_contract, make_factory,
    make_lot, make_model, make_order, make_run, make_verified_document,
    publish, reserve_run, schedule_order, set_clock, start_run, substantiate,
    validate_success,
)
from test_helpers import TEST_USERS

api = api_client
ADMIN = TEST_USERS["admin"]
PLANNER = TEST_USERS["planner"]
CO1 = {"X-User-ID": "co-1", "X-User-Role": "ComplianceOfficer"}


def _berry_stack():
    """Berry fixture + PUBLISHED MADE_IN_USA claim + IN_FULFILLMENT contract,
    plus a VERIFIED lot-linked origin cert (the cascade trigger surface)."""
    kit = berry_completed_run()
    lot_cert = make_verified_document(
        "SUPPLIER_ORIGIN_CERT", "material_lot_id", kit["l_g"]["id"])
    claim = make_claim(kit["model"]["id"], "MADE_IN_USA")
    make_verified_document("SUPPLIER_ORIGIN_CERT", "claim_id", claim["id"])
    make_verified_document("ASSEMBLY_LABOR_RECORD", "claim_id", claim["id"])
    substantiate(claim["id"], kit["report"]["id"])
    claim = publish(claim["id"])
    contract = make_contract(
        kit["model"]["id"], kit["factory"]["id"], contract_number="GOV-2026-001",
        awarded_units=100, fulfillment_start="2026-10-01",
        fulfillment_end="2026-10-31")
    contract = validate_success(api.start_fulfillment(contract["id"], CO1))
    kit.update({"claim": claim, "contract": contract, "lot_cert": lot_cert})
    return kit


def test_origin_cert_rejection_supersedes_and_recomputes_report():
    """PRD §3.8: "In hop one, a rejected `SUPPLIER_ORIGIN_CERT` linked to a lot
    forces a recompute for every run whose `consumed_lots` reference that lot
    and which currently has an `ACTIVE` `CERTIFIED` report: the system creates
    a superseding `CERTIFIED` report recomputed with that lot's consumed units
    treated as non-domestic, the old report becomes `SUPERSEDED`, and the run's
    `version` increments by 1 for the mutation."

    Design: Difficulty/transitive_cascade/origin_cert_rejection_report_claim_contract_cascade
    """
    kit = _berry_stack()
    validate_success(api.reject_document(kit["lot_cert"]["id"], CO1))

    reports = validate_success(api.list_content_reports(
        kit["run"]["id"], PLANNER, params={"variant": "CERTIFIED"}))
    by_id = {r["id"]: r for r in reports}
    assert by_id[kit["report"]["id"]]["status"] == "SUPERSEDED"
    active = [r for r in reports if r["status"] == "ACTIVE"]
    assert len(active) == 1
    # Lot's 100 units forced non-domestic: material 500, domestic 0 -> 0.00.
    assert active[0]["us_content_pct"] == pytest.approx(0.00)
    assert active[0]["material_cost_cents"] == 500
    assert active[0]["domestic_material_cost_cents"] == 0


def test_origin_cert_rejection_challenges_claim_and_audits_contract():
    """PRD §3.8: "In hop two, every labeling claim in `SUBSTANTIATED` or
    `PUBLISHED` on the model of any recomputed run has its `report_id`
    re-pointed to the superseding `ACTIVE` report and its content threshold
    re-evaluated; a claim that now fails becomes `CHALLENGED`."
    PRD §3.8: "In hop three, every government contract whose `model_id` matches
    a claim that just became `CHALLENGED`, and which is currently
    `IN_FULFILLMENT`, is pushed to `COMPLIANCE_AUDIT` with its `version`
    incremented."

    Design: Difficulty/transitive_cascade/origin_cert_rejection_report_claim_contract_cascade
    """
    kit = _berry_stack()
    validate_success(api.reject_document(kit["lot_cert"]["id"], CO1))

    claim = get_claim(kit["claim"]["id"])
    assert claim["status"] == "CHALLENGED"
    assert claim["report_id"] is not None and claim["report_id"] != kit["report"]["id"]
    assert claim["published_at"] is None

    contract = get_contract(kit["contract"]["id"])
    assert contract["status"] == "COMPLIANCE_AUDIT"


def _two_custom_runs_kit():
    """DOMESTIC factory (2 lines, rate 50, overhead 600); MCRM with one
    IMPORT_ALLOWED upper line (lot 500 @1250); two CUSTOM_BATCH runs of 10 in
    2026-W37 (allocation total 500 -> domestic pool 20), both MATERIAL_RESERVED;
    order O1 (qty 2) SCHEDULED on run 1, O2 (qty 2) SCHEDULED on run 2; run 1
    IN_PRODUCTION (O1 IN_PRODUCTION), run 2 still MATERIAL_RESERVED."""
    set_clock()
    factory = make_factory(factory_name="Lawrence MA Plant", line_count=2)
    c_up = make_component("Full-grain leather upper", "UPPER")
    lot = make_lot(c_up["id"], supplier_name="Lawrence Leather Co",
                   quantity_received=500, unit_cost_cents=1250, is_domestic=True)
    model = make_model(bom_lines=[
        bom_line(c_up["id"], planned_unit_cost_cents=1250, planned_is_domestic=False),
    ], style_code="MCRM", base_price_cents=9900, import_cost_basis_cents=3000,
        standard_stitching_minutes=5, standard_lasting_minutes=5,
        standard_assembly_minutes=5)
    allocation = make_allocation(factory["id"], "2026-W37", 500)
    r1 = make_run(model["id"], factory["id"], run_type="CUSTOM_BATCH",
                  planned_units=10, line_index=1, start_day="2026-09-14",
                  end_day="2026-09-18", iso_week="2026-W37")
    r2 = make_run(model["id"], factory["id"], run_type="CUSTOM_BATCH",
                  planned_units=10, line_index=2, start_day="2026-09-14",
                  end_day="2026-09-18", iso_week="2026-W37")
    lock_allocation(allocation["id"])
    r1 = reserve_run(r1["id"])
    r2 = reserve_run(r2["id"])
    o1 = accept_order(make_order(model["id"], buyer="cust-1", quantity_units=2)["id"])
    o2 = accept_order(
        make_order(model["id"], buyer="cust-1", quantity_units=2, size="11")["id"])
    o1 = schedule_order(o1["id"], r1["id"])
    o2 = schedule_order(o2["id"], r2["id"])
    certify_pair(factory["id"])
    r1 = start_run(r1["id"])
    return {"factory": factory, "lot": lot, "model": model,
            "r1": r1, "r2": r2, "o1": o1, "o2": o2}


def test_factory_suspension_holds_and_reverts_runs():
    """PRD §3.1: "In the first hop, every production run of that factory
    currently `IN_PRODUCTION` is moved to `QUALITY_HOLD` with its `version`
    incremented, while every run in `MATERIAL_RESERVED` is reverted to
    `PLANNED` — and that reversion itself re-credits every lot in the run's
    `consumed_lots` (each lot's `quantity_remaining` is increased by the
    consumed units and the lot's `version` increments) and clears the run's
    `consumed_lots`, a second cascade hop."

    Design: Difficulty/transitive_cascade/factory_suspension_run_lot_order_cascade
    """
    kit = _two_custom_runs_kit()
    validate_success(api.suspend_factory(kit["factory"]["id"], ADMIN))

    r1 = get_run(kit["r1"]["id"])
    r2 = get_run(kit["r2"]["id"])
    assert r1["status"] == "QUALITY_HOLD"          # held run keeps its lots
    assert r2["status"] == "PLANNED" and r2["consumed_lots"] == []
    # 500 - 10 (held run 1) = 490: run 2's 10 units flowed back.
    assert get_lot(kit["lot"]["id"])["quantity_remaining"] == 490


def test_factory_suspension_unschedules_only_reverted_run_orders():
    """PRD §3.1: "Also in the second hop, each custom order in `SCHEDULED`
    status whose `production_run_id` names one of the reverted runs is moved
    back to `ACCEPTED` with its `production_run_id` cleared to null and its
    `version` incremented. Runs already `COMPLETED` or `CANCELLED` are
    untouched, and runs sitting in `QUALITY_HOLD` at suspension time keep both
    their reserved lots and their `IN_PRODUCTION` orders."

    Design: Difficulty/transitive_cascade/factory_suspension_run_lot_order_cascade
    """
    kit = _two_custom_runs_kit()
    validate_success(api.suspend_factory(kit["factory"]["id"], ADMIN))

    o1 = get_order(kit["o1"]["id"])
    o2 = get_order(kit["o2"]["id"])
    # O1 rides the merely-held run 1: untouched.
    assert o1["production_status"] == "IN_PRODUCTION"
    # O2 was SCHEDULED on the reverted run 2: back to ACCEPTED, run cleared.
    assert o2["production_status"] == "ACCEPTED"
    assert o2["production_run_id"] is None
