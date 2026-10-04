"""Composite setup helpers.

Each helper builds one PRD-reachable state from an empty database using only
public endpoints, and validates each step with get_success_data so a setup
failure surfaces as a clear "Setup failed" assertion. Every test runs against
a fresh server, so helpers never assume pre-existing state.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_START_ISO, WEEK_36, RUN_START_DAY, RUN_END_DAY,
    DOC_VALID_FROM, DOC_VALID_UNTIL,
)
from .factories import (
    bom_line, complete_run_payload, create_allocation_payload, create_claim_payload,
    create_component_payload, create_contract_payload, create_document_payload,
    create_enrollment_payload, create_factory_payload, create_lot_payload,
    create_model_payload, create_order_payload, create_report_payload,
    create_run_payload, create_worker_payload, record_assessment_payload,
)
from .test_users import (
    TEST_USERS, make_compliance_headers, make_customer_headers, make_sourcing_headers,
)

ADMIN = TEST_USERS["admin"]
SOURCING = TEST_USERS["sourcing"]
PLANNER = TEST_USERS["planner"]
COMPLIANCE = TEST_USERS["compliance"]
TRAINING = TEST_USERS["training"]


# ---------------------------------------------------------------------------
# Primitive steps
# ---------------------------------------------------------------------------

def set_clock(iso=CLOCK_START_ISO):
    """Advance (or pin) the logical clock."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, ADMIN))


def make_factory(**overrides):
    resp = api_client.create_factory(create_factory_payload(**overrides), ADMIN)
    return get_success_data(resp)


def make_component(name="Bonded nylon thread", ctype="THREAD"):
    resp = api_client.create_component(
        create_component_payload(component_name=name, component_type=ctype), SOURCING
    )
    return get_success_data(resp)


def make_lot(component_id, **overrides):
    resp = api_client.create_lot(create_lot_payload(component_id, **overrides), SOURCING)
    return get_success_data(resp)


def make_model(component_id=None, bom_lines=None, **overrides):
    resp = api_client.create_model(
        create_model_payload(component_id=component_id, bom_lines=bom_lines, **overrides),
        SOURCING,
    )
    return get_success_data(resp)


def make_allocation(factory_id, week=WEEK_36, total=100):
    resp = api_client.create_allocation(
        create_allocation_payload(factory_id, iso_week=week, total_reserved_units=total),
        ADMIN,
    )
    return get_success_data(resp)


def make_run(model_id, factory_id, **overrides):
    resp = api_client.create_run(create_run_payload(model_id, factory_id, **overrides), PLANNER)
    return get_success_data(resp)


def lock_allocation(allocation_id):
    return get_success_data(api_client.lock_allocation(allocation_id, ADMIN))


def get_run(run_id):
    return get_success_data(api_client.get_run(run_id, PLANNER))


def run_version(run_id):
    return get_run(run_id)["version"]


def reserve_run(run_id):
    return get_success_data(api_client.reserve_materials(run_id, PLANNER))


def release_run(run_id):
    return get_success_data(api_client.release_materials(run_id, PLANNER))


def start_run(run_id):
    return get_success_data(api_client.start_run(run_id, PLANNER))


def complete_run(run_id, minutes=(0, 0, 0)):
    return get_success_data(
        api_client.complete_run(run_id, complete_run_payload(*minutes), PLANNER)
    )


def get_lot(lot_id):
    return get_success_data(api_client.get_lot(lot_id, SOURCING))


def get_allocation(allocation_id):
    return get_success_data(api_client.get_allocation(allocation_id, ADMIN))


def get_claim(claim_id):
    return get_success_data(api_client.get_label_claim(claim_id, COMPLIANCE))


def get_order(order_id):
    return get_success_data(api_client.get_custom_order(order_id, PLANNER))


def get_document(doc_id):
    return get_success_data(api_client.get_evidence_document(doc_id, COMPLIANCE))


def create_report(run_id, variant):
    """Create a content report carrying the run's current version (OCC)."""
    version = run_version(run_id)
    resp = api_client.create_content_report(
        run_id, create_report_payload(variant, version), PLANNER
    )
    return get_success_data(resp)


def enroll(worker_id, operation, target_level=1):
    resp = api_client.create_enrollment(
        create_enrollment_payload(worker_id, operation, target_level), TRAINING
    )
    return get_success_data(resp)


def assess(enrollment_id, score):
    return get_success_data(
        api_client.record_assessment(enrollment_id, record_assessment_payload(score), TRAINING)
    )


def make_worker(factory_id, name="Ada Lovelace"):
    resp = api_client.create_worker(create_worker_payload(factory_id, full_name=name), TRAINING)
    return get_success_data(resp)


def certify_worker(factory_id, name, operations=("STITCHING", "LASTING", "ASSEMBLY"),
                   level=2, score=85):
    """Hire a worker and drive one enrollment per operation to CERTIFIED."""
    worker = make_worker(factory_id, name)
    for op in operations:
        enrollment = enroll(worker["id"], op, target_level=level)
        assess(enrollment["id"], score)
    return worker


def certify_pair(factory_id):
    """Two fully certified workers — satisfies the per-run workforce minimum
    (2 STITCHING, 1 LASTING, 1 ASSEMBLY)."""
    w1 = certify_worker(factory_id, "Ada Lovelace")
    w2 = certify_worker(factory_id, "Grace Hopper")
    return w1, w2


def make_claim(model_id, claim_type="MADE_IN_USA"):
    resp = api_client.create_label_claim(create_claim_payload(model_id, claim_type), COMPLIANCE)
    return get_success_data(resp)


def upload_document(doc_type, link_field, link_id, uploader_id="sm-1", **overrides):
    resp = api_client.create_evidence_document(
        create_document_payload(doc_type, link_field=link_field, link_id=link_id, **overrides),
        make_sourcing_headers(uploader_id),
    )
    return get_success_data(resp)


def verify_document(doc_id, reviewer_id="co-1"):
    return get_success_data(
        api_client.verify_document(doc_id, make_compliance_headers(reviewer_id))
    )


def make_verified_document(doc_type, link_field, link_id, uploader_id="sm-1", **overrides):
    doc = upload_document(doc_type, link_field, link_id, uploader_id=uploader_id, **overrides)
    return verify_document(doc["id"])


def claim_with_verified_docs(model_id, claim_type="MADE_IN_USA",
                             valid_from=DOC_VALID_FROM, valid_until=DOC_VALID_UNTIL):
    """DRAFT claim carrying one VERIFIED SUPPLIER_ORIGIN_CERT and one VERIFIED
    ASSEMBLY_LABOR_RECORD attached via claim_id."""
    claim = make_claim(model_id, claim_type)
    d_oc = make_verified_document(
        "SUPPLIER_ORIGIN_CERT", "claim_id", claim["id"],
        valid_from=valid_from, valid_until=valid_until,
    )
    d_lr = make_verified_document(
        "ASSEMBLY_LABOR_RECORD", "claim_id", claim["id"],
        valid_from=valid_from, valid_until=valid_until,
    )
    return {"claim": get_claim(claim["id"]), "d_oc": d_oc, "d_lr": d_lr}


def substantiate(claim_id, report_id):
    return get_success_data(
        api_client.substantiate_claim(claim_id, {"report_id": report_id}, COMPLIANCE)
    )


def publish(claim_id):
    return get_success_data(api_client.publish_claim(claim_id, COMPLIANCE))


def make_order(model_id, buyer="cust-1", as_customer=True, **overrides):
    headers = make_customer_headers(buyer) if as_customer else PLANNER
    resp = api_client.create_custom_order(
        create_order_payload(model_id, buyer_ref=buyer, **overrides), headers
    )
    return get_success_data(resp)


def accept_order(order_id):
    return get_success_data(api_client.accept_order(order_id, PLANNER))


def accepted_order(model_id, buyer="cust-1", **overrides):
    order = make_order(model_id, buyer=buyer, **overrides)
    return accept_order(order["id"])


def schedule_order(order_id, run_id):
    return get_success_data(
        api_client.schedule_order(order_id, {"production_run_id": run_id}, PLANNER)
    )


# ---------------------------------------------------------------------------
# Composite: the standard kit (factory + thread component + thread lot +
# DUAL_SOURCE model + optional allocation + optional run)
# ---------------------------------------------------------------------------

def standard_kit(alloc_total=100, week=WEEK_36, with_allocation=True, with_run=True,
                 run_type="STOCK", run_units=10, line=1, start_day=RUN_START_DAY,
                 end_day=RUN_END_DAY, lock=False, reserve=False,
                 factory_overrides=None, model_overrides=None,
                 lot_qty=1000, lot_cost=100, lot_domestic=True):
    """Clock pinned at the default; DOMESTIC factory (capacity 1000, 3 lines,
    rate 50, overhead 600); THREAD component; domestic thread lot; model with
    one IMPORT_ALLOWED line of 1.0 unit/pair planned 100c; OPEN allocation and
    PLANNED run as requested."""
    set_clock()
    factory = make_factory(**(factory_overrides or {}))
    component = make_component()
    lot = make_lot(component["id"], quantity_received=lot_qty,
                   unit_cost_cents=lot_cost, is_domestic=lot_domestic)
    model = make_model(component["id"], **(model_overrides or {}))
    allocation = make_allocation(factory["id"], week, alloc_total) if with_allocation else None
    run = None
    if with_run:
        run = make_run(
            model["id"], factory["id"], run_type=run_type, planned_units=run_units,
            line_index=line, start_day=start_day, end_day=end_day, iso_week=week,
        )
    if lock and allocation is not None:
        allocation = lock_allocation(allocation["id"])
    if reserve and run is not None:
        run = reserve_run(run["id"])
    return {
        "factory": factory, "component": component, "lot": lot, "model": model,
        "allocation": allocation, "run": run,
    }


def completed_run_kit(minutes=(0, 0, 0), **kwargs):
    """Standard kit driven to COMPLETED: lock, reserve, workforce pair, start,
    complete. Returns the kit with the run at its post-complete state."""
    kwargs["lock"] = True
    kwargs["reserve"] = True
    kit = standard_kit(**kwargs)
    certify_pair(kit["factory"]["id"])
    kit["run"] = start_run(kit["run"]["id"])
    kit["run"] = complete_run(kit["run"]["id"], minutes)
    return kit


# ---------------------------------------------------------------------------
# Composite: the 95.00 / 70.00 / 100.00 certified-report fixtures
# ---------------------------------------------------------------------------

def m95_completed_run():
    """DOMESTIC factory; model with a DOMESTIC_REQUIRED upper line (planned
    1000c, planned-domestic) and an IMPORT_ALLOWED midsole line (planned 100c);
    lots 200 @1000 domestic + 200 @100 imported; STOCK run of 100 in 2026-W36
    (allocation total 300) completed at 2/2/2; CERTIFIED report at 95.00."""
    set_clock()
    factory = make_factory(factory_name="Skowhegan ME Plant", line_count=1)
    c_a = make_component("Pigskin upper", "UPPER")
    c_b = make_component("Foam midsole", "MIDSOLE")
    l_a = make_lot(c_a["id"], supplier_name="Maine Tanning", quantity_received=200,
                   unit_cost_cents=1000, is_domestic=True)
    l_b = make_lot(c_b["id"], supplier_name="Incheon Foam", quantity_received=200,
                   unit_cost_cents=100, is_domestic=False)
    model = make_model(bom_lines=[
        bom_line(c_a["id"], sourcing_requirement="DOMESTIC_REQUIRED",
                 planned_unit_cost_cents=1000, planned_is_domestic=True),
        bom_line(c_b["id"], planned_unit_cost_cents=100, planned_is_domestic=False),
    ], style_code="M95", base_price_cents=15000, import_cost_basis_cents=4000,
        standard_stitching_minutes=2, standard_lasting_minutes=2,
        standard_assembly_minutes=2)
    allocation = make_allocation(factory["id"], WEEK_36, 300)
    run = make_run(model["id"], factory["id"], planned_units=100)
    allocation = lock_allocation(allocation["id"])
    run = reserve_run(run["id"])
    certify_pair(factory["id"])
    run = start_run(run["id"])
    run = complete_run(run["id"], (2, 2, 2))
    report = create_report(run["id"], "CERTIFIED")
    return {"factory": factory, "c_a": c_a, "c_b": c_b, "l_a": l_a, "l_b": l_b,
            "model": model, "allocation": allocation, "run": run, "report": report}


def m70_completed_run():
    """Same shape as m95_completed_run but the midsole lot costs 600c, landing
    the CERTIFIED report at exactly 70.00."""
    set_clock()
    factory = make_factory(factory_name="Skowhegan ME Plant", line_count=1)
    c_a = make_component("Pigskin upper", "UPPER")
    c_b = make_component("Foam midsole", "MIDSOLE")
    l_a = make_lot(c_a["id"], supplier_name="Maine Tanning", quantity_received=100,
                   unit_cost_cents=500, is_domestic=True)
    l_b = make_lot(c_b["id"], supplier_name="Incheon Foam", quantity_received=100,
                   unit_cost_cents=600, is_domestic=False)
    model = make_model(bom_lines=[
        bom_line(c_a["id"], sourcing_requirement="DOMESTIC_REQUIRED",
                 planned_unit_cost_cents=500, planned_is_domestic=True),
        bom_line(c_b["id"], planned_unit_cost_cents=600, planned_is_domestic=False),
    ], style_code="M70", base_price_cents=15000, import_cost_basis_cents=4000,
        standard_stitching_minutes=2, standard_lasting_minutes=2,
        standard_assembly_minutes=2)
    allocation = make_allocation(factory["id"], WEEK_36, 300)
    run = make_run(model["id"], factory["id"], planned_units=100)
    allocation = lock_allocation(allocation["id"])
    run = reserve_run(run["id"])
    certify_pair(factory["id"])
    run = start_run(run["id"])
    run = complete_run(run["id"], (2, 2, 2))
    report = create_report(run["id"], "CERTIFIED")
    return {"factory": factory, "c_a": c_a, "c_b": c_b, "l_a": l_a, "l_b": l_b,
            "model": model, "allocation": allocation, "run": run, "report": report}


def berry_completed_run():
    """Government-cleared DOMESTIC factory (labor rate 0, overhead 0);
    DOMESTIC_ONLY model with one DOMESTIC_REQUIRED line planned 500c; domestic
    lot of 300 @500; GOVERNMENT run of 100 in 2026-W40 (allocation total 300)
    completed at 0/0/0; CERTIFIED report at exactly 100.00 (Berry-proof)."""
    set_clock()
    factory = make_factory(
        factory_name="Berry Works ME", government_cleared=True, line_count=1,
        labor_rate_cents_per_minute=0, overhead_cents_per_pair=0,
    )
    c_g = make_component("Ballistic nylon upper", "UPPER")
    l_g = make_lot(c_g["id"], supplier_name="Maine Tanning", quantity_received=300,
                   unit_cost_cents=500, is_domestic=True)
    model = make_model(bom_lines=[
        bom_line(c_g["id"], sourcing_requirement="DOMESTIC_REQUIRED",
                 planned_unit_cost_cents=500, planned_is_domestic=True),
    ], style_code="GOV1", production_policy="DOMESTIC_ONLY",
        base_price_cents=20000, import_cost_basis_cents=8000)
    allocation = make_allocation(factory["id"], "2026-W40", 300)
    run = make_run(model["id"], factory["id"], run_type="GOVERNMENT",
                   planned_units=100, start_day="2026-10-05", end_day="2026-10-09",
                   iso_week="2026-W40")
    allocation = lock_allocation(allocation["id"])
    run = reserve_run(run["id"])
    certify_pair(factory["id"])
    run = start_run(run["id"])
    run = complete_run(run["id"], (0, 0, 0))
    report = create_report(run["id"], "CERTIFIED")
    return {"factory": factory, "c_g": c_g, "l_g": l_g, "model": model,
            "allocation": allocation, "run": run, "report": report}


def substantiated_claim_95():
    """M95 fixture + DRAFT MADE_IN_USA claim with both claim-attached VERIFIED
    documents, substantiated against the 95.00 CERTIFIED report."""
    kit = m95_completed_run()
    docs = claim_with_verified_docs(kit["model"]["id"], "MADE_IN_USA")
    claim = substantiate(docs["claim"]["id"], kit["report"]["id"])
    kit.update(docs)
    kit["claim"] = claim
    return kit


def published_claim_95():
    """substantiated_claim_95 driven one step further to PUBLISHED."""
    kit = substantiated_claim_95()
    kit["claim"] = publish(kit["claim"]["id"])
    return kit


def make_contract(model_id, factory_id, **overrides):
    resp = api_client.create_gov_contract(
        create_contract_payload(model_id, factory_id, **overrides), ADMIN
    )
    return get_success_data(resp)


def get_contract(contract_id):
    return get_success_data(api_client.get_gov_contract(contract_id, COMPLIANCE))
