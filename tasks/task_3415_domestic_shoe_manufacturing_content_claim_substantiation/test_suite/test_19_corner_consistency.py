"""Corner coverage: immediate consistency, entity-specific 404 sweep, contract
clearance/policy gates, discontinued-model lockout, and the remaining claim
threshold rules."""
import pytest

from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, bom_line, certify_pair,
    claim_with_verified_docs, complete_run, create_report, get_claim,
    get_contract, get_order, get_run, lock_allocation, m70_completed_run,
    m95_completed_run, make_allocation, make_claim, make_component,
    make_contract, make_factory, make_lot, make_model, make_order, make_run,
    published_claim_95, reserve_run, set_clock, standard_kit, start_run,
    substantiate, validate_error, validate_paginated, validate_success,
)
from test_helpers import TEST_USERS, api_client

api = api_client
ADMIN = TEST_USERS["admin"]
SOURCING = TEST_USERS["sourcing"]
PLANNER = TEST_USERS["planner"]
COMPLIANCE = TEST_USERS["compliance"]
TRAINING = TEST_USERS["training"]
CUST1 = {"X-User-ID": "cust-1", "X-User-Role": "CustomProgramCustomer"}


def test_action_response_reflects_mutation_immediately():
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.5: "Reserving materials moves a run from `PLANNED` to
    `MATERIAL_RESERVED`"

    Design: Corner/consistency_model/action_response_reflects_mutation_immediately
    """
    kit = standard_kit()
    lock_allocation(kit["allocation"]["id"])
    resp = api.reserve_materials(kit["run"]["id"], PLANNER)
    run = validate_success(resp)
    # The mutation is visible in the action response itself.
    assert run["status"] == "MATERIAL_RESERVED" and run["version"] == 2
    assert run["consumed_lots"] == [{
        "lot_id": kit["lot"]["id"], "component_id": kit["component"]["id"],
        "units_consumed": 10, "unit_cost_cents": 100, "is_domestic": True,
    }]
    # A follow-up read returns byte-identical state.
    reread = get_run(kit["run"]["id"])
    assert reread["status"] == run["status"]
    assert reread["consumed_lots"] == run["consumed_lots"]


def test_not_found_sweep_covers_entity_specific_404s():
    """PRD §2.9: "The not-found family is resource-specific:
    `ERR_FACTORY_NOT_FOUND`, `ERR_MODEL_NOT_FOUND`, `ERR_COMPONENT_NOT_FOUND`,
    `ERR_LOT_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`,
    `ERR_ORDER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_DOC_NOT_FOUND`,
    `ERR_WORKER_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`,
    `ERR_ALLOCATION_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, and
    `ERR_CERTIFICATION_NOT_FOUND`, all HTTP 404."
    PRD §2.9: "`ERR_ALLOCATION_NOT_FOUND` has a second use beyond path
    resolution: at material-reservation time it signals that no capacity
    allocation exists at all for the run's `(factory_id, iso_week)` pair."
    PRD §2.9: "Body-supplied references are held to the same standard: a
    foreign key in a request payload that does not resolve is rejected with
    the matching not-found error rather than being dereferenced into a failure
    deeper in the workflow."

    Design: Corner/consistency_model/not_found_sweep_covers_entity_specific_404s
    """
    kit = standard_kit()
    claim = make_claim(kit["model"]["id"], "MADE_IN_USA")
    run_w37 = make_run(kit["model"]["id"], kit["factory"]["id"], planned_units=5,
                       line_index=2, start_day="2026-09-14",
                       end_day="2026-09-18", iso_week="2026-W37")

    checks = [
        (api.get_model(NON_EXISTENT_UUID, SOURCING),
         ApiErrorId.ERR_MODEL_NOT_FOUND),
        (api.get_run(NON_EXISTENT_UUID, PLANNER),
         ApiErrorId.ERR_RUN_NOT_FOUND),
        (api.get_custom_order(NON_EXISTENT_UUID, PLANNER),
         ApiErrorId.ERR_ORDER_NOT_FOUND),
        (api.get_label_claim(NON_EXISTENT_UUID, COMPLIANCE),
         ApiErrorId.ERR_CLAIM_NOT_FOUND),
        (api.get_evidence_document(NON_EXISTENT_UUID, COMPLIANCE),
         ApiErrorId.ERR_DOC_NOT_FOUND),
        (api.get_worker(NON_EXISTENT_UUID, TRAINING),
         ApiErrorId.ERR_WORKER_NOT_FOUND),
        (api.record_assessment(NON_EXISTENT_UUID, {"score": 90}, TRAINING),
         ApiErrorId.ERR_ENROLLMENT_NOT_FOUND),
        (api.get_allocation(NON_EXISTENT_UUID, ADMIN),
         ApiErrorId.ERR_ALLOCATION_NOT_FOUND),
        (api.get_gov_contract(NON_EXISTENT_UUID, ADMIN),
         ApiErrorId.ERR_CONTRACT_NOT_FOUND),
        (api.get_lot(NON_EXISTENT_UUID, SOURCING),
         ApiErrorId.ERR_LOT_NOT_FOUND),
        # Body-FK misses surface the matching not-found error too.
        (api.create_lot({
            "component_id": NON_EXISTENT_UUID, "supplier_name": "Ghost Supplier",
            "is_domestic": True, "quantity_received": 10, "unit_cost_cents": 100,
        }, SOURCING), ApiErrorId.ERR_COMPONENT_NOT_FOUND),
        (api.substantiate_claim(claim["id"], {"report_id": NON_EXISTENT_UUID},
                                COMPLIANCE), ApiErrorId.ERR_REPORT_NOT_FOUND),
        # Reserve into a week with no allocation: the derived (factory, week)
        # lookup is an existence check.
        (api.reserve_materials(run_w37["id"], PLANNER),
         ApiErrorId.ERR_ALLOCATION_NOT_FOUND),
    ]
    for resp, expected in checks:
        validate_error(resp, expected)


def test_contract_start_on_uncleared_factory_returns_factory_not_cleared():
    """PRD §3.9: "the factory must be both `DOMESTIC` and `government_cleared`
    (`ERR_FACTORY_NOT_CLEARED`, HTTP 422) and must be `ACTIVE`
    (`ERR_FACTORY_NOT_ACTIVE`)"

    Design: Corner/consistency_model/contract_start_on_uncleared_factory_returns_factory_not_cleared
    """
    set_clock()
    factory = make_factory()  # DOMESTIC, government_cleared false
    component = make_component("Ballistic nylon upper", "UPPER")
    model = make_model(component["id"], style_code="GOV1",
                       production_policy="DOMESTIC_ONLY",
                       bom_lines=[bom_line(component["id"],
                                           sourcing_requirement="DOMESTIC_REQUIRED",
                                           planned_unit_cost_cents=500,
                                           planned_is_domestic=True)])
    # Berry is satisfied for this (model, factory) pair via a STOCK run (a
    # GOVERNMENT run would itself require a cleared factory), so the
    # clearance gate is the failing rule regardless of whether §2.8 family 7
    # or the §3.9 gauntlet order is applied.
    make_lot(component["id"])
    allocation = make_allocation(factory["id"])
    run = make_run(model["id"], factory["id"])
    lock_allocation(allocation["id"])
    reserve_run(run["id"])
    certify_pair(factory["id"])
    start_run(run["id"])
    complete_run(run["id"])
    create_report(run["id"], "CERTIFIED")
    contract = make_contract(model["id"], factory["id"], contract_number="G-400",
                             awarded_units=10, fulfillment_start="2027-02-01",
                             fulfillment_end="2027-02-28")
    resp = api.start_fulfillment(contract["id"], COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_FACTORY_NOT_CLEARED)
    assert get_contract(contract["id"])["status"] == "AWARDED"


def test_import_only_model_on_domestic_factory_returns_policy_forbids_domestic():
    """PRD §3.5: "an `IMPORT_ONLY` model may not be produced at a `DOMESTIC`
    factory (`ERR_POLICY_FORBIDS_DOMESTIC`, HTTP 422); a `DUAL_SOURCE` model
    accepts either."

    Design: Corner/consistency_model/import_only_model_on_domestic_factory_returns_policy_forbids_domestic
    """
    set_clock()
    factory = make_factory()
    component = make_component()
    model = make_model(component["id"], style_code="MIMP",
                       production_policy="IMPORT_ONLY", base_price_cents=4000,
                       import_cost_basis_cents=1500)
    resp = api.create_run(
        {"model_id": model["id"], "factory_id": factory["id"],
         "run_type": "STOCK", "planned_units": 10, "line_index": 1,
         "start_day": "2026-09-07", "end_day": "2026-09-11",
         "iso_week": "2026-W36"}, PLANNER)
    validate_error(resp, ApiErrorId.ERR_POLICY_FORBIDS_DOMESTIC)
    runs, meta = validate_paginated(
        api.list_runs(PLANNER, params={"model_id": model["id"]}))
    assert runs == [] and meta["total_count"] == 0


def test_model_discontinue_blocked_by_published_claim():
    """PRD §3.3: "if any labeling claim of the model is currently `PUBLISHED`,
    it is rejected with `ERR_MODEL_HAS_PUBLISHED_CLAIMS` (HTTP 409)."

    Design: Corner/consistency_model/model_discontinue_blocked_by_published_claim
    """
    kit = published_claim_95()  # run COMPLETED (terminal); claim PUBLISHED
    resp = api.discontinue_model(kit["model"]["id"], SOURCING)
    validate_error(resp, ApiErrorId.ERR_MODEL_HAS_PUBLISHED_CLAIMS)
    assert validate_success(api.get_model(kit["model"]["id"], SOURCING))["status"] == "ACTIVE"
    assert get_claim(kit["claim"]["id"])["status"] == "PUBLISHED"


def test_operations_on_discontinued_model_return_model_not_active():
    """PRD §3.7: "Submission requires the model to be `ACTIVE` (a discontinued
    style rejects with `ERR_MODEL_NOT_ACTIVE`)"
    PRD §3.7: "Acceptance is a `ProductionPlanner` action from `SUBMITTED` —
    the model must still be `ACTIVE` (`ERR_MODEL_NOT_ACTIVE`)"
    PRD §3.9: "the model must be `ACTIVE` (`ERR_MODEL_NOT_ACTIVE`)"

    Design: Corner/consistency_model/operations_on_discontinued_model_return_model_not_active
    """
    set_clock()
    factory = make_factory(factory_name="Berry Works ME", government_cleared=True)
    component = make_component("Ballistic nylon upper", "UPPER")
    model = make_model(component["id"], style_code="GOV1",
                       production_policy="DOMESTIC_ONLY",
                       bom_lines=[bom_line(component["id"],
                                           sourcing_requirement="DOMESTIC_REQUIRED",
                                           planned_unit_cost_cents=500,
                                           planned_is_domestic=True)])
    order = make_order(model["id"], buyer="cust-1", quantity_units=1)
    contract = make_contract(model["id"], factory["id"], contract_number="G-401",
                             awarded_units=10, fulfillment_start="2027-03-01",
                             fulfillment_end="2027-03-31")
    validate_success(api.discontinue_model(model["id"], SOURCING))

    create_resp = api.create_custom_order(
        {"model_id": model["id"], "buyer_ref": "cust-1", "colorway": "RED",
         "size": "9", "quantity_units": 1}, CUST1)
    validate_error(create_resp, ApiErrorId.ERR_MODEL_NOT_ACTIVE)

    validate_error(api.accept_order(order["id"], PLANNER),
                   ApiErrorId.ERR_MODEL_NOT_ACTIVE)
    validate_error(api.start_fulfillment(contract["id"], COMPLIANCE),
                   ApiErrorId.ERR_MODEL_NOT_ACTIVE)

    assert validate_success(api.get_model(model["id"], SOURCING))["status"] == "DISCONTINUED"
    assert get_contract(contract["id"])["status"] == "AWARDED"
    assert get_order(order["id"])["production_status"] == "SUBMITTED"


def test_assembled_in_usa_threshold_and_imported_on_domestic_run():
    """PRD §3.8: "`ASSEMBLED_IN_USA` requires domestic final assembly and at
    least 20.00; and `IMPORTED` passes when final assembly is not domestic or
    the percentage is below 20.00."

    Design: Corner/consistency_model/assembled_in_usa_threshold_and_imported_on_domestic_run
    """
    kit70 = m70_completed_run()   # CERTIFIED report at exactly 70.00
    docs = claim_with_verified_docs(kit70["model"]["id"], "ASSEMBLED_IN_USA")
    claim = substantiate(docs["claim"]["id"], kit70["report"]["id"])
    assert kit70["report"]["us_content_pct"] == pytest.approx(70.00)
    assert claim["status"] == "SUBSTANTIATED"  # 70.00 >= 20.00, domestic

    kit95 = m95_completed_run()   # 95.00 with domestic final assembly
    imported = make_claim(kit95["model"]["id"], "IMPORTED")
    # IMPORTED requires foreign assembly or pct < 20.00: fails on this report
    # before the evidence folder is ever consulted.
    resp = api.substantiate_claim(imported["id"],
                                  {"report_id": kit95["report"]["id"]}, COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_CONTENT_THRESHOLD_NOT_MET)
