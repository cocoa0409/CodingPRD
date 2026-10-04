"""Depth probes: priority-pair validation conflicts (state beats fiscal;
content-threshold beats evidence-referential)."""
import pytest

from test_helpers import (
    ApiErrorId, bom_line, certify_pair, claim_with_verified_docs, complete_run,
    create_report, get_claim, get_lot, get_run, lock_allocation,
    make_allocation, make_claim, make_component, make_factory, make_lot,
    make_model, make_run, reserve_run, set_clock, start_run, validate_error,
    validate_success,
)
from test_helpers import TEST_USERS, api_client

api = api_client
ADMIN = TEST_USERS["admin"]
PLANNER = TEST_USERS["planner"]
COMPLIANCE = TEST_USERS["compliance"]


def _suspended_factory_capacity_kit():
    """DOMESTIC factory (weekly capacity 100, 1 line); MPRIO with one
    IMPORT_ALLOWED thread line; lot 1000 @100; allocation total 10; STOCK run
    of 20 created before lock (waterfall caps the domestic pool at 10);
    factory SUSPENDED while the run is still PLANNED."""
    set_clock()
    factory = make_factory(factory_name="Cap 100 Plant", weekly_capacity_units=100,
                           line_count=1)
    component = make_component()
    lot = make_lot(component["id"], quantity_received=1000, unit_cost_cents=100)
    model = make_model(component["id"], style_code="MPRIO")
    allocation = make_allocation(factory["id"], "2026-W36", 10)
    run = make_run(model["id"], factory["id"], planned_units=20)
    lock_allocation(allocation["id"])
    validate_success(api.suspend_factory(factory["id"], ADMIN))
    return {"factory": factory, "lot": lot, "model": model, "run": run}


def test_reserve_reports_factory_state_not_capacity_overflow():
    """PRD §2.8: "The twelve families below are evaluated in ascending priority
    order, and within each family the checks run as described. A failure in an
    earlier family masks every later family"
    PRD §3.5: "then state — the run must be `PLANNED` (otherwise
    `ERR_INVALID_STATE`), its model must be `ACTIVE` (`ERR_MODEL_NOT_ACTIVE`,
    HTTP 409), its factory must be `ACTIVE` (`ERR_FACTORY_NOT_ACTIVE`, HTTP
    409), and the allocation must already be `LOCKED`
    (`ERR_ALLOCATION_NOT_LOCKED`)"

    Design: Difficulty/priority_pair_validation_conflict/reserve_factory_state_error_beats_capacity_fiscal_error
    """
    kit = _suspended_factory_capacity_kit()
    resp = api.reserve_materials(kit["run"]["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_FACTORY_NOT_ACTIVE)
    # The fiscal error (20 > domestic pool 10) is masked by the state family.
    assert get_run(kit["run"]["id"])["status"] == "PLANNED"
    assert get_lot(kit["lot"]["id"])["quantity_remaining"] == 1000


def test_reserve_capacity_overflow_surfaces_once_factory_recovers():
    """PRD §3.5: "The reservation is rejected with
    `ERR_CAPACITY_WEEK_EXCEEDED` (HTTP 422) unless the consumed total plus this
    run's `planned_units` stays within the pool — equality is allowed, so a run
    may take the week's last pair."

    Design: Difficulty/priority_pair_validation_conflict/reserve_factory_state_error_beats_capacity_fiscal_error
    """
    kit = _suspended_factory_capacity_kit()
    validate_success(api.reactivate_factory(kit["factory"]["id"], ADMIN))
    resp = api.reserve_materials(kit["run"]["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_CAPACITY_WEEK_EXCEEDED)
    assert get_run(kit["run"]["id"])["status"] == "PLANNED"


def _ninety_four_ninety_nine_kit(with_docs):
    """Factory (rate 40, overhead 500, 1 line); M9499 (DOMESTIC_REQUIRED upper
    planned 999 + IMPORT_ALLOWED midsole planned 501); lots 10 @999 domestic +
    10 @501 imported; STOCK run of 10 COMPLETED at 190/5/5 -> CERTIFIED report
    at 94.99; DRAFT MADE_IN_USA claim (documents only when with_docs)."""
    set_clock()
    factory = make_factory(factory_name="Rate 40 Plant", line_count=1,
                           labor_rate_cents_per_minute=40,
                           overhead_cents_per_pair=500)
    c_a = make_component("Pigskin upper", "UPPER")
    c_b = make_component("Foam midsole", "MIDSOLE")
    make_lot(c_a["id"], supplier_name="Maine Tanning", quantity_received=10,
             unit_cost_cents=999, is_domestic=True)
    make_lot(c_b["id"], supplier_name="Incheon Foam", quantity_received=10,
             unit_cost_cents=501, is_domestic=False)
    model = make_model(bom_lines=[
        bom_line(c_a["id"], sourcing_requirement="DOMESTIC_REQUIRED",
                 planned_unit_cost_cents=999, planned_is_domestic=True),
        bom_line(c_b["id"], planned_unit_cost_cents=501, planned_is_domestic=False),
    ], style_code="M9499", base_price_cents=15000, import_cost_basis_cents=4000,
        standard_stitching_minutes=190, standard_lasting_minutes=5,
        standard_assembly_minutes=5)
    allocation = make_allocation(factory["id"], "2026-W36", 100)
    run = make_run(model["id"], factory["id"], planned_units=10)
    lock_allocation(allocation["id"])
    reserve_run(run["id"])
    certify_pair(factory["id"])
    start_run(run["id"])
    complete_run(run["id"], (190, 5, 5))
    report = create_report(run["id"], "CERTIFIED")
    assert report["us_content_pct"] == pytest.approx(94.99)
    if with_docs:
        claim = claim_with_verified_docs(model["id"], "MADE_IN_USA")["claim"]
    else:
        claim = make_claim(model["id"], "MADE_IN_USA")
    return {"model": model, "run": run, "report": report, "claim": claim}


def test_substantiate_threshold_failure_masks_missing_evidence():
    """PRD §2.8 (family 10, referential evidence): "This check deliberately
    sits after the threshold check: a claim whose content fails is reported as
    a content failure even if its evidence folder is also empty."
    PRD §3.8: "the content threshold for the claim type must pass (otherwise
    `ERR_CONTENT_THRESHOLD_NOT_MET`, HTTP 422); and finally the evidence folder
    must contain at least one `VERIFIED` unexpired `SUPPLIER_ORIGIN_CERT` and
    at least one `VERIFIED` unexpired `ASSEMBLY_LABOR_RECORD` attached to this
    claim via `claim_id` (otherwise `ERR_REQUIRED_EVIDENCE_MISSING`, HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/substantiate_threshold_safety_beats_evidence_referential
    """
    kit = _ninety_four_ninety_nine_kit(with_docs=False)
    resp = api.substantiate_claim(kit["claim"]["id"],
                                  {"report_id": kit["report"]["id"]}, COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_CONTENT_THRESHOLD_NOT_MET)
    claim = get_claim(kit["claim"]["id"])
    assert claim["status"] == "DRAFT" and claim["report_id"] is None


def test_substantiate_threshold_failure_alone_still_blocks_with_evidence():
    """PRD §3.8: "The threshold check compares against the report's stored
    two-decimal `us_content_pct` and its `final_assembly_domestic` flag, with
    all thresholds inclusive: `MADE_IN_USA` requires domestic final assembly
    and a `us_content_pct` of at least 95.00"

    Design: Difficulty/priority_pair_validation_conflict/substantiate_threshold_safety_beats_evidence_referential
    """
    kit = _ninety_four_ninety_nine_kit(with_docs=True)
    resp = api.substantiate_claim(kit["claim"]["id"],
                                  {"report_id": kit["report"]["id"]}, COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_CONTENT_THRESHOLD_NOT_MET)
    assert get_claim(kit["claim"]["id"])["status"] == "DRAFT"
