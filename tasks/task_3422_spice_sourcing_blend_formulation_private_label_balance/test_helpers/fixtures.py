"""Composite setup helpers built only from PRD-declared endpoints.

The harness restarts the server before every test, so each fixture builds its
preconditions from scratch against an empty database. Setup calls use the
lenient get_success_data / explicit-status validate_success so a broken chain
fails loudly at the exact step that broke.
"""
from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import api_client
from .factories import (
    supplier_payload, lot_payload, test_payload, disposition_payload,
    formula_payload, formula_line_payload, blend_run_payload, line_payload,
    production_run_payload, agreement_payload,
)
from .test_users import (
    TEST_USERS, make_quality_analyst_headers, make_quality_manager_headers,
)

ALL_CHANGEOVER_CLASSES = ["NONE", "DRY_CLEAN", "WET_WASH", "FULL_SANITATION"]

# Default pass values: below every action level in PRD §3.2
PASS_MICRO = 50000          # < 100000
PASS_ADULTERANT = 1.0       # < 2.00
PASS_MOISTURE = 8.0         # <= 12.0


def create_supplier(name="Malabar Exports", origin_country="IN", **overrides) -> dict:
    resp = api_client.create_supplier(
        supplier_payload(name=name, origin_country=origin_country, **overrides),
        TEST_USERS["supply_planner_headers"])
    return validate_success(resp, 201)


def create_received_lot(supplier_id, **overrides) -> dict:
    resp = api_client.create_lot(lot_payload(supplier_id, **overrides),
                                 TEST_USERS["supply_planner_headers"])
    return validate_success(resp, 201)


def post_test(lot_id, test_type, measured_value, lab_code="LAB-A",
              analyst_id="qa-1") -> dict:
    resp = api_client.post_test(
        lot_id, test_payload(test_type, measured_value, lab_code),
        make_quality_analyst_headers(analyst_id))
    return validate_success(resp, 201)


def post_pass_suite(lot_id, analyst_id="qa-1"):
    """Post one PASS test per required-suite member (PRD §3.2)."""
    post_test(lot_id, "MICRO", PASS_MICRO, analyst_id=analyst_id)
    post_test(lot_id, "ADULTERANT_SCREEN", PASS_ADULTERANT, analyst_id=analyst_id)
    post_test(lot_id, "MOISTURE", PASS_MOISTURE, analyst_id=analyst_id)


def disposition_lot(lot_id, action, manager_id="qm-1", **payload_overrides) -> dict:
    resp = api_client.disposition_lot(
        lot_id, disposition_payload(action, **payload_overrides),
        make_quality_manager_headers(manager_id))
    return validate_success(resp, 200)


def accept_lot(lot_id, analyst_id="qa-1", manager_id="qm-1") -> dict:
    """Full PASS suite (posted by analyst_id) then ACCEPT by a different
    manager_id — satisfies the segregation-of-duties rule (PRD §3.2)."""
    assert analyst_id != manager_id, "segregation of duties requires distinct ids"
    post_pass_suite(lot_id, analyst_id=analyst_id)
    return disposition_lot(lot_id, "ACCEPT", manager_id=manager_id)


def create_accepted_lot(supplier_id, analyst_id="qa-1", manager_id="qm-1",
                        **overrides) -> dict:
    lot = create_received_lot(supplier_id, **overrides)
    return accept_lot(lot["id"], analyst_id=analyst_id, manager_id=manager_id)


def setup_accepted_lots(costs=(100, 200, 300), quantity_kg=100, flavor=100.0,
                        moisture=8.0, spice_code="BLACK_PEPPER", crop_years=None,
                        organic=False, allergen="NONE",
                        supplier_name="Malabar Exports",
                        supplier_country="IN"):
    """Supplier plus one ACCEPTED lot per cost entry. Returns (supplier, lots)."""
    supplier = create_supplier(name=supplier_name, origin_country=supplier_country)
    years = crop_years if crop_years is not None else [2025] * len(costs)
    lots = []
    for cost, year in zip(costs, years):
        lots.append(create_accepted_lot(
            supplier["id"], cost_per_kg_cents=cost, quantity_kg=quantity_kg,
            flavor_intensity_units=flavor, moisture_pct=moisture,
            spice_code=spice_code, crop_year=year, organic_certified=organic,
            allergen_profile=allergen))
    return supplier, lots


def create_active_formula(product_code, lines=None, **overrides) -> dict:
    """DRAFT formula + the given lines + activate. Default: one BLACK_PEPPER
    100% line with min_lot_flavor_units 50."""
    resp = api_client.create_formula(formula_payload(product_code, **overrides),
                                     TEST_USERS["flavor_scientist_headers"])
    formula = validate_success(resp, 201)
    if lines is None:
        lines = [dict(spice_code="BLACK_PEPPER", target_proportion_pct=100.0,
                      min_lot_flavor_units=50.0)]
    for line in lines:
        resp = api_client.add_formula_line(
            formula["id"], formula_line_payload(**line),
            TEST_USERS["flavor_scientist_headers"])
        validate_success(resp, 201)
    resp = api_client.activate_formula(formula["id"],
                                       TEST_USERS["flavor_scientist_headers"])
    return validate_success(resp, 200)


def create_blend_run(formula_id, selection_policy="COST_MIN",
                     target_batch_kg=100) -> dict:
    resp = api_client.create_blend_run(
        blend_run_payload(formula_id, selection_policy, target_batch_kg),
        TEST_USERS["flavor_scientist_headers"])
    return validate_success(resp, 201)


def commit_blend_run(run_id) -> dict:
    resp = api_client.commit_blend_run(run_id,
                                       TEST_USERS["flavor_scientist_headers"])
    return validate_success(resp, 200)


def create_committed_blend_run(formula_id, selection_policy="COST_MIN",
                               target_batch_kg=100) -> dict:
    run = create_blend_run(formula_id, selection_policy, target_batch_kg)
    return commit_blend_run(run["id"])


def create_line(name="Line-1", capacity_kg_per_shift=1000,
                supported_changeover_classes=None) -> dict:
    classes = (supported_changeover_classes if supported_changeover_classes
               is not None else list(ALL_CHANGEOVER_CLASSES))
    resp = api_client.create_line(
        line_payload(name, capacity_kg_per_shift,
                     supported_changeover_classes=classes),
        TEST_USERS["platform_admin_headers"])
    return validate_success(resp, 201)


def get_line_version(line_id) -> int:
    resp = api_client.get_line(line_id,
                               TEST_USERS["production_scheduler_headers"])
    return validate_success(resp, 200)["version"]


def schedule_run(line_id, formula_id, blend_run_id, quantity_kg, window_start,
                 window_end, private_label_agreement_id=None,
                 expected_line_version=None) -> dict:
    """Read the line's current version (OCC field, PRD §2.7) and schedule."""
    version = (expected_line_version if expected_line_version is not None
               else get_line_version(line_id))
    payload = production_run_payload(
        line_id, formula_id, blend_run_id, quantity_kg, window_start, window_end,
        version)
    if private_label_agreement_id is not None:
        payload["private_label_agreement_id"] = private_label_agreement_id
    resp = api_client.create_production_run(
        payload, TEST_USERS["production_scheduler_headers"])
    return validate_success(resp, 201)


def complete_run(run_id) -> dict:
    resp = api_client.complete_production_run(
        run_id, TEST_USERS["production_scheduler_headers"])
    return validate_success(resp, 200)


def cancel_run(run_id) -> dict:
    resp = api_client.cancel_production_run(
        run_id, TEST_USERS["production_scheduler_headers"])
    return validate_success(resp, 200)


def batch_for_run(run_id) -> dict:
    resp = api_client.list_batches(TEST_USERS["quality_manager_headers"],
                                   params={"production_run_id": run_id})
    data = get_success_data(resp)
    assert isinstance(data, list) and len(data) == 1, \
        f"expected exactly one batch for run {run_id}, got {data}"
    return data[0]


def setup_produced_batch(product_code="BATCH-1", costs=(100, 200, 300),
                         lot_quantity_kg=100, target_batch_kg=100,
                         window_start="2026-09-07T08:00:00Z",
                         window_end="2026-09-07T12:00:00Z",
                         line_capacity=1000):
    """Full chain: 3 ACCEPTED pepper lots + ACTIVE formula + COMMITTED blend
    + line + SCHEDULED then COMPLETED run. Returns all created entities."""
    supplier, lots = setup_accepted_lots(costs=costs, quantity_kg=lot_quantity_kg)
    formula = create_active_formula(product_code)
    blend_run = create_committed_blend_run(formula["id"], "COST_MIN",
                                           target_batch_kg)
    line = create_line(name=f"Line-{product_code}",
                       capacity_kg_per_shift=line_capacity)
    run = schedule_run(line["id"], formula["id"], blend_run["id"],
                       target_batch_kg, window_start, window_end)
    complete_run(run["id"])
    batch = batch_for_run(run["id"])
    return {"supplier": supplier, "lots": lots, "formula": formula,
            "blend_run": blend_run, "line": line, "run": run, "batch": batch}


def create_agreement(retailer_name="Riverbend Foods", product_codes=None,
                     annual_commitment_kg=500, **overrides) -> dict:
    resp = api_client.create_agreement(
        agreement_payload(retailer_name, product_codes, annual_commitment_kg,
                          **overrides),
        TEST_USERS["production_scheduler_headers"])
    return validate_success(resp, 201)


def set_clock(to_iso8601) -> str:
    """Set the server's logical clock (PRD §2.5). Returns current_utc."""
    resp = api_client.set_clock(to_iso8601, TEST_USERS["platform_admin_headers"])
    return validate_success(resp, 200)["current_utc"]


def get_lot(lot_id) -> dict:
    resp = api_client.get_lot(lot_id, TEST_USERS["quality_manager_headers"])
    return validate_success(resp, 200)


def get_blend_run(run_id) -> dict:
    resp = api_client.get_blend_run(run_id,
                                    TEST_USERS["flavor_scientist_headers"])
    return validate_success(resp, 200)


def get_batch(batch_id) -> dict:
    resp = api_client.get_batch(batch_id, TEST_USERS["quality_manager_headers"])
    return validate_success(resp, 200)


def get_agreement(agreement_id) -> dict:
    resp = api_client.get_agreement(
        agreement_id, TEST_USERS["production_scheduler_headers"])
    return validate_success(resp, 200)


def get_recall_case(case_id) -> dict:
    resp = api_client.get_recall_case(
        case_id, TEST_USERS["recall_coordinator_headers"])
    return validate_success(resp, 200)


def list_recall_cases(params=None) -> list:
    resp = api_client.list_recall_cases(
        TEST_USERS["recall_coordinator_headers"], params=params)
    return get_success_data(resp)
