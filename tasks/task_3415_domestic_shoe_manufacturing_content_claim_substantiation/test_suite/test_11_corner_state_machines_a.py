"""Corner coverage: state machines, part A (claim publish/revoke lifecycle,
run completion gate, order scheduling guards and slot boundary, training
loop, worker/certification suspension)."""
import pytest

from test_helpers import (
    ApiErrorId, accept_order, assess, bom_line, certify_pair, certify_worker,
    complete_run, enroll, get_claim, get_order, get_run,
    lock_allocation, m95_completed_run, make_allocation, make_claim,
    make_component, make_factory, make_lot, make_model, make_order, make_run,
    make_worker, publish, published_claim_95, reserve_run, schedule_order,
    set_clock, standard_kit, start_run, substantiated_claim_95,
    validate_error, validate_success,
)
from test_helpers import TEST_USERS, api_client

api = api_client
ADMIN = TEST_USERS["admin"]
PLANNER = TEST_USERS["planner"]
COMPLIANCE = TEST_USERS["compliance"]
TRAINING = TEST_USERS["training"]


def _get_worker(worker_id):
    return validate_success(api.get_worker(worker_id, TRAINING))


def _make_order(model_id, qty=2, **overrides):
    return make_order(model_id, buyer="cust-1", quantity_units=qty, **overrides)["id"]


def test_claim_publish_happy_path():
    """PRD §3.8: "Publishing moves a claim from `SUBSTANTIATED` to `PUBLISHED`.
    The model must still be `ACTIVE` (`ERR_MODEL_NOT_ACTIVE`), and freshness is
    re-checked at the current logical clock: every `SUPPLIER_ORIGIN_CERT` and
    `ASSEMBLY_LABOR_RECORD` counted at substantiation must still be `VERIFIED`
    and unexpired, otherwise `ERR_EVIDENCE_STALE` (HTTP 422). A successful
    publish stamps `published_at` and increments `version`."

    Design: Corner/state_machines/claim_publish_happy_path
    """
    kit = substantiated_claim_95()
    claim = publish(kit["claim"]["id"])
    assert claim["status"] == "PUBLISHED" and claim["version"] == 3
    assert claim["published_at"].startswith("2026-09-01T00:00:00")
    assert claim["report_id"] == kit["report"]["id"]
    reports = validate_success(api.list_content_reports(
        kit["run"]["id"], PLANNER, params={"variant": "CERTIFIED", "status": "ACTIVE"}))
    assert len(reports) == 1
    assert reports[0]["us_content_pct"] == pytest.approx(95.00)


def test_claim_revoke_from_published_returns_invalid_state():
    """PRD §3.8: "There is deliberately no direct path from `PUBLISHED` to
    `REVOKED` — a published claim must first be challenged, whether by evidence
    rejection or by a failing report recompute, before it can be revoked."

    Design: Corner/state_machines/claim_revoke_from_published_returns_invalid_state
    """
    kit = published_claim_95()
    resp = api.revoke_claim(kit["claim"]["id"], COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    claim = get_claim(kit["claim"]["id"])
    assert claim["status"] == "PUBLISHED" and claim["version"] == 3


def test_revoked_claim_rejects_further_transitions():
    """PRD §3.8: "`REVOKED` is terminal."
    PRD §2.8 (family 6): "the generic `ERR_INVALID_STATE` (HTTP 409) covers
    wrong-state targets"

    Design: Corner/state_machines/revoked_claim_rejects_further_transitions
    """
    kit = m95_completed_run()
    claim = make_claim(kit["model"]["id"], "MADE_IN_USA")
    validate_success(api.revoke_claim(claim["id"], COMPLIANCE))

    resp = api.substantiate_claim(claim["id"], {"report_id": kit["report"]["id"]},
                                  COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    claim = get_claim(claim["id"])
    assert claim["status"] == "REVOKED" and claim["report_id"] is None


def test_run_complete_from_planned_returns_invalid_state():
    """PRD §3.5: "Completing a run is a `ProductionPlanner` action from
    `IN_PRODUCTION`."
    PRD §2.8 (family 6): "the generic `ERR_INVALID_STATE` (HTTP 409) covers
    wrong-state targets"

    Design: Corner/state_machines/run_complete_from_planned_returns_invalid_state
    """
    kit = standard_kit()  # run PLANNED, allocation OPEN
    resp = api.complete_run(kit["run"]["id"], {
        "actual_stitching_minutes": 1, "actual_lasting_minutes": 1,
        "actual_assembly_minutes": 1}, PLANNER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    run = get_run(kit["run"]["id"])
    assert run["status"] == "PLANNED"
    assert run["certified_unit_cost_cents"] is None


def _in_production_custom_order():
    """CUSTOM_BATCH run of 10 reserved and started; order (qty 2) accepted,
    scheduled, and now IN_PRODUCTION on the running run."""
    kit = standard_kit(run_type="CUSTOM_BATCH", run_units=10)
    lock_allocation(kit["allocation"]["id"])
    kit["run"] = reserve_run(kit["run"]["id"])
    order = accept_order(_make_order(kit["model"]["id"]))
    order = schedule_order(order["id"], kit["run"]["id"])
    certify_pair(kit["factory"]["id"])
    kit["run"] = start_run(kit["run"]["id"])
    kit["order"] = get_order(order["id"])
    return kit


def test_order_fulfill_before_run_completion_returns_run_not_completed():
    """PRD §3.7: "Fulfillment is the happy ending: a `ProductionPlanner` may
    fulfill an order only from `IN_PRODUCTION`, and only once its linked run
    has reached `COMPLETED` — attempting it earlier fails with
    `ERR_RUN_NOT_COMPLETED` (HTTP 409) — moving the order to `FULFILLED`, a
    terminal state."

    Design: Corner/state_machines/order_fulfill_before_run_completion_returns_run_not_completed
    """
    kit = _in_production_custom_order()
    assert kit["order"]["production_status"] == "IN_PRODUCTION"

    early = api.fulfill_order(kit["order"]["id"], PLANNER)
    validate_error(early, ApiErrorId.ERR_RUN_NOT_COMPLETED)
    assert get_order(kit["order"]["id"])["production_status"] == "IN_PRODUCTION"

    complete_run(kit["run"]["id"], (2, 2, 2))
    fulfilled = validate_success(api.fulfill_order(kit["order"]["id"], PLANNER))
    assert fulfilled["production_status"] == "FULFILLED"


def test_order_schedule_onto_stock_run_returns_not_a_custom_run():
    """PRD §3.7: "A `ProductionPlanner` supplies the target
    `production_run_id`, which must resolve to an existing run
    (`ERR_RUN_NOT_FOUND`, HTTP 404); that run must be a `CUSTOM_BATCH` run
    (`ERR_NOT_A_CUSTOM_RUN`, HTTP 422)"

    Design: Corner/state_machines/order_schedule_onto_stock_run_returns_not_a_custom_run
    """
    kit = standard_kit()  # STOCK run of 10
    lock_allocation(kit["allocation"]["id"])
    reserve_run(kit["run"]["id"])
    order = accept_order(_make_order(kit["model"]["id"]))

    resp = api.schedule_order(order["id"], {"production_run_id": kit["run"]["id"]},
                              PLANNER)
    validate_error(resp, ApiErrorId.ERR_NOT_A_CUSTOM_RUN)
    order = get_order(order["id"])
    assert order["production_status"] == "ACCEPTED"
    assert order["production_run_id"] is None


def test_order_schedule_with_other_models_run_returns_model_mismatch():
    """PRD §3.7: "its `model_id` must equal the order's `model_id`
    (`ERR_MODEL_MISMATCH`, HTTP 422)"

    Design: Corner/state_machines/order_schedule_with_other_models_run_returns_model_mismatch
    """
    set_clock()
    factory = make_factory()
    c_a = make_component("Pigskin upper", "UPPER")
    c_b = make_component("Foam midsole", "MIDSOLE")
    make_lot(c_a["id"], supplier_name="Maine Tanning", quantity_received=200,
             unit_cost_cents=1000, is_domestic=True)
    make_lot(c_b["id"], supplier_name="Incheon Foam", quantity_received=200,
             unit_cost_cents=100, is_domestic=False)
    c_t = make_component()
    make_lot(c_t["id"])
    m95 = make_model(bom_lines=[
        bom_line(c_a["id"], sourcing_requirement="DOMESTIC_REQUIRED",
                 planned_unit_cost_cents=1000, planned_is_domestic=True),
        bom_line(c_b["id"], planned_unit_cost_cents=100, planned_is_domestic=False),
    ], style_code="M95", base_price_cents=15000, import_cost_basis_cents=4000,
        standard_stitching_minutes=2, standard_lasting_minutes=2,
        standard_assembly_minutes=2)
    allocation = make_allocation(factory["id"], "2026-W36", 100)
    run95 = make_run(m95["id"], factory["id"], run_type="CUSTOM_BATCH",
                     planned_units=4)
    mstd = make_model(c_t["id"], style_code="MSTD")
    lock_allocation(allocation["id"])
    reserve_run(run95["id"])
    order = accept_order(_make_order(mstd["id"]))

    resp = api.schedule_order(order["id"], {"production_run_id": run95["id"]}, PLANNER)
    validate_error(resp, ApiErrorId.ERR_MODEL_MISMATCH)
    assert get_order(order["id"])["production_status"] == "ACCEPTED"
    assert get_run(run95["id"])["status"] == "MATERIAL_RESERVED"


def test_order_schedule_onto_unreserved_run_returns_run_not_ready():
    """PRD §3.7: "and the run must be sitting in `MATERIAL_RESERVED` —
    materials committed but production not yet started — otherwise
    `ERR_RUN_NOT_READY` (HTTP 409)."

    Design: Corner/state_machines/order_schedule_onto_unreserved_run_returns_run_not_ready
    """
    kit = standard_kit(run_type="CUSTOM_BATCH", run_units=10)
    lock_allocation(kit["allocation"]["id"])
    order = accept_order(_make_order(kit["model"]["id"]))

    early = api.schedule_order(order["id"], {"production_run_id": kit["run"]["id"]},
                               PLANNER)
    validate_error(early, ApiErrorId.ERR_RUN_NOT_READY)

    reserve_run(kit["run"]["id"])
    scheduled = schedule_order(order["id"], kit["run"]["id"])
    assert scheduled["production_status"] == "SCHEDULED"
    assert scheduled["production_run_id"] == kit["run"]["id"]


def test_order_schedule_onto_overseas_run_returns_custom_requires_domestic():
    """PRD §3.7: "its factory must be `DOMESTIC`, because the custom program
    never runs overseas (`ERR_CUSTOM_REQUIRES_DOMESTIC`)"

    Design: Corner/state_machines/order_schedule_onto_overseas_run_returns_custom_requires_domestic
    """
    set_clock()
    f_os = make_factory(factory_name="Hanoi Partner Plant", location_type="OVERSEAS",
                        weekly_capacity_units=2000, line_count=2,
                        labor_rate_cents_per_minute=10, overhead_cents_per_pair=100)
    component = make_component()
    make_lot(component["id"])
    model = make_model(component["id"])
    allocation = make_allocation(f_os["id"], "2026-W36", 100)
    run = make_run(model["id"], f_os["id"], run_type="CUSTOM_BATCH", planned_units=10)
    lock_allocation(allocation["id"])
    reserve_run(run["id"])
    order = accept_order(_make_order(model["id"]))

    resp = api.schedule_order(order["id"], {"production_run_id": run["id"]}, PLANNER)
    validate_error(resp, ApiErrorId.ERR_CUSTOM_REQUIRES_DOMESTIC)
    order = get_order(order["id"])
    assert order["production_status"] == "ACCEPTED"
    assert order["production_run_id"] is None


def test_order_slots_exact_fit_then_overflow():
    """PRD §3.7: "the sum of `quantity_units` over the orders already on the
    run in `SCHEDULED` or `IN_PRODUCTION` status plus the incoming order's
    `quantity_units` must not exceed the run's `planned_units`, with equality
    allowed; an overflow is rejected with `ERR_RUN_ORDER_CAPACITY_EXCEEDED`
    (HTTP 422)."

    Design: Corner/state_machines/order_slots_exact_fit_then_overflow
    """
    kit = standard_kit(run_type="CUSTOM_BATCH", run_units=4)
    lock_allocation(kit["allocation"]["id"])
    reserve_run(kit["run"]["id"])
    o1 = accept_order(_make_order(kit["model"]["id"]))
    o2 = accept_order(_make_order(kit["model"]["id"], 2, size="11"))
    o3 = accept_order(_make_order(kit["model"]["id"], 1, size="9", colorway="RED"))

    assert schedule_order(o1["id"], kit["run"]["id"])["production_status"] == "SCHEDULED"
    assert schedule_order(o2["id"], kit["run"]["id"])["production_status"] == "SCHEDULED"
    over = api.schedule_order(o3["id"], {"production_run_id": kit["run"]["id"]}, PLANNER)
    validate_error(over, ApiErrorId.ERR_RUN_ORDER_CAPACITY_EXCEEDED)  # 4 + 1 > 4
    assert get_order(o3["id"])["production_status"] == "ACCEPTED"


def test_enrollment_remediation_then_certified_loop():
    """PRD §3.2: "From `ENROLLED`, a score of at least 80 moves the enrollment
    to `CERTIFIED`, while a score below 80 routes it to `REMEDIATION`; from
    `REMEDIATION`, a score of at least 80 completes the retry loop to
    `CERTIFIED`, while another score below 80 terminates it as `FAILED`."
    PRD §3.2: "When an enrollment reaches `CERTIFIED`, the worker's
    `certifications` list is upserted: the entry for the trained `operation` is
    set to the enrollment's `target_level` with `cert_status` `CERTIFIED`, and
    the worker's `version` increments by 1."

    Design: Corner/state_machines/enrollment_remediation_then_certified_loop
    """
    set_clock()
    factory = make_factory()
    worker = make_worker(factory["id"], "Ada Lovelace")
    enrollment = enroll(worker["id"], "STITCHING", target_level=2)

    mid = assess(enrollment["id"], 70)
    assert mid["status"] == "REMEDIATION"
    assert mid["attempt_count"] == 1 and mid["last_score"] == 70
    assert _get_worker(worker["id"])["certifications"] == []

    end = assess(enrollment["id"], 85)
    assert end["status"] == "CERTIFIED"
    assert end["attempt_count"] == 2 and end["version"] == 3
    assert _get_worker(worker["id"])["certifications"] == [
        {"operation": "STITCHING", "level": 2, "cert_status": "CERTIFIED"}]


def test_assessment_score_80_certifies_79_routes_to_remediation():
    """PRD §3.2: "The pass mark is 80. From `ENROLLED`, a score of at least 80
    moves the enrollment to `CERTIFIED`, while a score below 80 routes it to
    `REMEDIATION`; from `REMEDIATION`, a score of at least 80 completes the
    retry loop to `CERTIFIED`, while another score below 80 terminates it as
    `FAILED`. `CERTIFIED` and `FAILED` are both terminal."

    Design: Corner/state_machines/assessment_score_80_certifies_79_routes_to_remediation
    """
    set_clock()
    factory = make_factory()
    ada = make_worker(factory["id"], "Ada Lovelace")
    grace = make_worker(factory["id"], "Grace Hopper")
    e80 = enroll(ada["id"], "STITCHING", target_level=1)
    e79 = enroll(grace["id"], "LASTING", target_level=1)

    assert assess(e80["id"], 80)["status"] == "CERTIFIED"     # inclusive pass mark
    assert assess(e79["id"], 79)["status"] == "REMEDIATION"
    failed = assess(e79["id"], 79)
    assert failed["status"] == "FAILED" and failed["attempt_count"] == 2


def test_second_open_enrollment_same_operation_is_rejected():
    """PRD §3.2: "At most one open enrollment may exist per worker and
    operation: an existing enrollment in `ENROLLED` or `REMEDIATION` status
    blocks a new one with `ERR_ENROLLMENT_ALREADY_OPEN` (HTTP 409)."

    Design: Corner/state_machines/second_open_enrollment_same_operation_is_rejected
    """
    set_clock()
    factory = make_factory()
    worker = make_worker(factory["id"], "Ada Lovelace")
    first = enroll(worker["id"], "STITCHING", target_level=1)

    dup = api.create_enrollment(
        {"worker_id": worker["id"], "operation": "STITCHING", "target_level": 2},
        TRAINING)
    validate_error(dup, ApiErrorId.ERR_ENROLLMENT_ALREADY_OPEN)

    assess(first["id"], 90)  # CERTIFIED (terminal)
    resp = api.create_enrollment(
        {"worker_id": worker["id"], "operation": "STITCHING", "target_level": 2},
        TRAINING)
    enrollment = validate_success(resp, 201)
    assert enrollment["status"] == "ENROLLED"


def test_certification_suspend_unknown_operation_returns_not_found():
    """PRD §3.2: "Addressing an operation for which the worker holds no
    certification entry is rejected with `ERR_CERTIFICATION_NOT_FOUND` (HTTP
    404)."

    Design: Corner/state_machines/certification_suspend_unknown_operation_returns_not_found
    """
    set_clock()
    factory = make_factory()
    worker = make_worker(factory["id"], "Ada Lovelace")
    resp = api.suspend_certification(worker["id"], "STITCHING", TRAINING)
    validate_error(resp, ApiErrorId.ERR_CERTIFICATION_NOT_FOUND)
    assert _get_worker(worker["id"])["certifications"] == []


def test_worker_suspend_holds_understaffed_run():
    """PRD §3.2: "Suspension cascades immediately: for each run currently
    `IN_PRODUCTION` at that worker's factory, the system re-evaluates the
    start-time workforce requirement of §3.5 *without* this worker, and if any
    operation falls below its required headcount the run is forced to
    `QUALITY_HOLD` with its `version` incremented."
    PRD §3.5: "For each of the three operations, the plant must field at least
    the per-run requirement of `ACTIVE` workers holding a certification for
    that operation with `cert_status` `CERTIFIED` — 2 for `STITCHING`, 1 for
    `LASTING`, and 1 for `ASSEMBLY` — and a shortfall in any operation rejects
    the start with `ERR_WORKFORCE_SHORTFALL` (HTTP 422)."

    Design: Corner/state_machines/worker_suspend_holds_understaffed_run
    """
    kit = standard_kit()
    lock_allocation(kit["allocation"]["id"])
    reserve_run(kit["run"]["id"])
    # Ada certified in all three; Grace in STITCHING only -> minimal coverage.
    ada = certify_worker(kit["factory"]["id"], "Ada Lovelace")
    grace = make_worker(kit["factory"]["id"], "Grace Hopper")
    assess(enroll(grace["id"], "STITCHING", target_level=2)["id"], 85)
    kit["run"] = start_run(kit["run"]["id"])

    validate_success(api.suspend_worker(ada["id"], TRAINING))
    assert get_run(kit["run"]["id"])["status"] == "QUALITY_HOLD"
    worker = _get_worker(ada["id"])
    assert worker["status"] == "SUSPENDED"
    assert all(c["cert_status"] == "CERTIFIED" for c in worker["certifications"])
