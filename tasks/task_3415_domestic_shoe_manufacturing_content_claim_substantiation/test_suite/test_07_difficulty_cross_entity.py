"""Depth probes: cross-entity state dependencies (run gated on factory state;
claim substantiation gated on report variant/status)."""
from test_helpers import (
    ApiErrorId, claim_with_verified_docs, create_report, get_claim, get_lot,
    get_run, lock_allocation, m95_completed_run, make_allocation, make_run,
    reserve_run, set_clock, standard_kit, substantiate, validate_error,
    validate_success,
)
from test_helpers import TEST_USERS, api_client

api = api_client
ADMIN = TEST_USERS["admin"]
PLANNER = TEST_USERS["planner"]
COMPLIANCE = TEST_USERS["compliance"]


def _suspended_run_kit():
    """MX13 standard kit: STOCK run of 50 in 2026-W36 (allocation total 100,
    locked -> domestic pool 50); factory then SUSPENDED (the PLANNED run is not
    touched by the suspension cascade)."""
    kit = standard_kit(alloc_total=100, run_units=50,
                       model_overrides={"style_code": "MX13"})
    lock_allocation(kit["allocation"]["id"])
    validate_success(api.suspend_factory(kit["factory"]["id"], ADMIN))
    return kit


def test_reserve_rejected_while_factory_suspended():
    """PRD §3.5: "then state — the run must be `PLANNED` (otherwise
    `ERR_INVALID_STATE`), its model must be `ACTIVE` (`ERR_MODEL_NOT_ACTIVE`,
    HTTP 409), its factory must be `ACTIVE` (`ERR_FACTORY_NOT_ACTIVE`, HTTP
    409), and the allocation must already be `LOCKED`
    (`ERR_ALLOCATION_NOT_LOCKED`)"

    Design: Difficulty/cross_entity_state_dependency/run_reserve_requires_factory_active_cross_entity
    """
    kit = _suspended_run_kit()
    resp = api.reserve_materials(kit["run"]["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_FACTORY_NOT_ACTIVE)
    assert get_run(kit["run"]["id"])["status"] == "PLANNED"


def test_reserve_succeeds_after_factory_reactivation():
    """PRD §3.1: "Reactivation is deliberately inert: nothing auto-resumes.
    Runs reverted to `PLANNED` stay `PLANNED` until a planner explicitly
    reserves materials again"
    PRD §3.5: "Reserving materials moves a run from `PLANNED` to
    `MATERIAL_RESERVED`"

    Design: Difficulty/cross_entity_state_dependency/run_reserve_requires_factory_active_cross_entity
    """
    kit = _suspended_run_kit()
    validate_error(api.reserve_materials(kit["run"]["id"], PLANNER),
                   ApiErrorId.ERR_FACTORY_NOT_ACTIVE)
    validate_success(api.reactivate_factory(kit["factory"]["id"], ADMIN))
    run = reserve_run(kit["run"]["id"])
    assert run["status"] == "MATERIAL_RESERVED"
    assert get_lot(kit["lot"]["id"])["quantity_remaining"] == 950  # 50 consumed


def _three_report_kit():
    """M95 fixture (CERTIFIED report on file) plus a PROVISIONAL report and two
    further CERTIFIED reports; the first extra CERTIFIED is left SUPERSEDED."""
    kit = m95_completed_run()
    rep_prov = create_report(kit["run"]["id"], "PROVISIONAL")
    rep_c1 = create_report(kit["run"]["id"], "CERTIFIED")
    rep_c2 = create_report(kit["run"]["id"], "CERTIFIED")
    docs = claim_with_verified_docs(kit["model"]["id"], "MADE_IN_USA")
    kit.update({"rep_prov": rep_prov, "rep_c1": rep_c1, "rep_c2": rep_c2,
                "claim": docs["claim"]})
    return kit


def test_substantiate_rejects_provisional_and_superseded_reports():
    """PRD §3.8: "the report's `variant` must be `CERTIFIED`
    (`ERR_REPORT_NOT_CERTIFIED`, HTTP 409) and its status `ACTIVE`
    (`ERR_REPORT_NOT_ACTIVE`, HTTP 409)"

    Design: Difficulty/cross_entity_state_dependency/claim_substantiate_requires_certified_active_report_cross_entity
    """
    kit = _three_report_kit()
    resp1 = api.substantiate_claim(kit["claim"]["id"],
                                   {"report_id": kit["rep_prov"]["id"]}, COMPLIANCE)
    validate_error(resp1, ApiErrorId.ERR_REPORT_NOT_CERTIFIED)
    resp2 = api.substantiate_claim(kit["claim"]["id"],
                                   {"report_id": kit["rep_c1"]["id"]}, COMPLIANCE)
    validate_error(resp2, ApiErrorId.ERR_REPORT_NOT_ACTIVE)
    assert get_claim(kit["claim"]["id"])["status"] == "DRAFT"


def test_substantiate_accepts_current_certified_active_report():
    """PRD §3.8: "A `ComplianceOfficer` substantiates a `DRAFT` claim — or
    re-substantiates a `CHALLENGED` one, which is the loop that closes the
    `PUBLISHED` → `CHALLENGED` → `SUBSTANTIATED` cycle — by supplying a
    `report_id`."

    Design: Difficulty/cross_entity_state_dependency/claim_substantiate_requires_certified_active_report_cross_entity
    """
    kit = _three_report_kit()
    validate_error(api.substantiate_claim(kit["claim"]["id"],
                                          {"report_id": kit["rep_prov"]["id"]},
                                          COMPLIANCE),
                   ApiErrorId.ERR_REPORT_NOT_CERTIFIED)
    validate_error(api.substantiate_claim(kit["claim"]["id"],
                                          {"report_id": kit["rep_c1"]["id"]},
                                          COMPLIANCE),
                   ApiErrorId.ERR_REPORT_NOT_ACTIVE)
    claim = substantiate(kit["claim"]["id"], kit["rep_c2"]["id"])
    assert claim["status"] == "SUBSTANTIATED"
    assert claim["report_id"] == kit["rep_c2"]["id"]
