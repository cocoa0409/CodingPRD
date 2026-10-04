"""Corner coverage: response envelopes, list filtering, and FK reverse
reachability."""
from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, create_model_payload, create_report,
    enroll, is_iso8601_timestamp, is_valid_uuid, lock_allocation,
    make_allocation, make_claim, make_model, make_run, make_worker,
    reserve_run, set_clock, standard_kit, validate_error, validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS, api_client

api = api_client
ADMIN = TEST_USERS["admin"]
SOURCING = TEST_USERS["sourcing"]
PLANNER = TEST_USERS["planner"]
COMPLIANCE = TEST_USERS["compliance"]
TRAINING = TEST_USERS["training"]


def test_success_envelope_shape_on_create():
    """PRD §2.2: "All successful API responses (those with 2xx status codes)
    follow this standard envelope format in their JSON body"
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §4: "Operations that create a new resource — factories, models,
    components, lots, runs, content reports, custom orders, claims, evidence
    documents, workers, training enrollments, capacity allocations, and
    government contracts — return `201 Created`."

    Design: Corner/endpoints/success_envelope_shape_on_create
    """
    resp = api.create_component(
        {"component_name": "Bonded nylon thread", "component_type": "THREAD"},
        SOURCING)
    assert resp.status_code == 201
    body = resp.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    component = body["data"]
    assert is_valid_uuid(component["id"])
    assert is_iso8601_timestamp(component["created_at"])
    assert is_iso8601_timestamp(component["updated_at"])
    assert component["version"] == 1


def test_error_envelope_shape_on_business_error():
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format"
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."

    Design: Corner/endpoints/error_envelope_shape_on_business_error
    """
    kit = standard_kit(with_allocation=False, with_run=False)
    resp = api.create_model(
        create_model_payload(kit["component"]["id"], style_code="MSTD",
                             production_policy="IMPORT_ONLY",
                             base_price_cents=9000, import_cost_basis_cents=4000),
        SOURCING)
    error = validate_error(resp, ApiErrorId.ERR_STYLE_CODE_EXISTS)
    body = resp.json()
    assert body["response_type"] == "error"
    assert error["error_id"] == "ERR_STYLE_CODE_EXISTS"
    assert isinstance(error["message"], str) and error["message"].strip()
    assert body["meta"]["api_request_id"]


def test_runs_list_filters_by_factory_status_and_week():
    """PRD §2.3: "List endpoints also accept resource-specific filter
    parameters described in §3 (for example `status`, `location_type`,
    `production_policy`, `component_id`, `is_domestic`, `model_id`,
    `factory_id`, `iso_week`, `variant`, `production_run_id`,
    `production_status`, `buyer_ref`, `claim_id`, `material_lot_id`,
    `doc_type`, `report_id`, and `claim_type` on the collections where they
    are meaningful)."

    Design: Corner/endpoints/runs_list_filters_by_factory_status_and_week
    """
    kit = standard_kit()  # run A: 2026-W36, PLANNED
    run_a = kit["run"]
    a37 = make_allocation(kit["factory"]["id"], "2026-W37", 250)
    run_b = make_run(kit["model"]["id"], kit["factory"]["id"], planned_units=10,
                     line_index=1, start_day="2026-09-14", end_day="2026-09-18",
                     iso_week="2026-W37")
    lock_allocation(a37["id"])
    reserve_run(run_b["id"])  # run B: 2026-W37, MATERIAL_RESERVED

    w37, meta = validate_paginated(api.list_runs(
        PLANNER, params={"factory_id": kit["factory"]["id"], "iso_week": "2026-W37"}))
    assert [r["id"] for r in w37] == [run_b["id"]]

    planned, _ = validate_paginated(api.list_runs(
        PLANNER, params={"factory_id": kit["factory"]["id"], "status": "PLANNED"}))
    assert [r["id"] for r in planned] == [run_a["id"]]

    all_runs, meta_all = validate_paginated(api.list_runs(
        PLANNER, params={"factory_id": kit["factory"]["id"]}))
    assert len(all_runs) == 2 and meta_all["total_count"] == 2


def test_fk_reverse_reachability_spot_checks():
    """PRD §2.3: "List endpoints also accept resource-specific filter
    parameters described in §3 (for example `status`, `location_type`,
    `production_policy`, `component_id`, `is_domestic`, `model_id`,
    `factory_id`, `iso_week`, `variant`, `production_run_id`,
    `production_status`, `buyer_ref`, `claim_id`, `material_lot_id`,
    `doc_type`, `report_id`, and `claim_type` on the collections where they
    are meaningful)."
    PRD §2.9: "Whenever an endpoint path contains resource identifiers —
    including nested paths such as a worker's certification addressed by
    operation — the identifiers are validated in strict left-to-right order"

    Design: Corner/endpoints/fk_reverse_reachability_spot_checks
    """
    kit = standard_kit()
    worker = make_worker(kit["factory"]["id"], "Ada Lovelace")
    enrollment = enroll(worker["id"], "STITCHING", target_level=1)
    claim = make_claim(kit["model"]["id"], "MADE_IN_USA")
    report = create_report(kit["run"]["id"], "PROVISIONAL")

    lots, _ = validate_paginated(
        api.list_lots(SOURCING, params={"component_id": kit["component"]["id"]}))
    assert [l["id"] for l in lots] == [kit["lot"]["id"]]

    enrollments, _ = validate_paginated(
        api.list_worker_enrollments(worker["id"], TRAINING))
    assert [e["id"] for e in enrollments] == [enrollment["id"]]

    claims, _ = validate_paginated(
        api.list_label_claims(COMPLIANCE, params={"model_id": kit["model"]["id"]}))
    assert [c["id"] for c in claims] == [claim["id"]]

    reports, _ = validate_paginated(
        api.list_content_reports(kit["run"]["id"], PLANNER))
    assert [r["id"] for r in reports] == [report["id"]]

    # Filters are not path ids: an unknown filter value yields an empty page.
    empty, meta_empty = validate_paginated(
        api.list_label_claims(COMPLIANCE, params={"model_id": NON_EXISTENT_UUID}))
    assert empty == [] and meta_empty["total_count"] == 0
