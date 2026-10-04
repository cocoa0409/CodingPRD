"""Depth probes: resource temporal overlap (half-open line windows; closed
contract fulfillment windows)."""
from test_helpers import (
    ApiErrorId, get_lot, get_run, lock_allocation, make_allocation,
    make_component, make_contract, make_factory, make_lot, make_model,
    make_run, reserve_run, set_clock, standard_kit, validate_error,
    validate_success,
)
from test_helpers import TEST_USERS, api_client

api = api_client
PLANNER = TEST_USERS["planner"]
ADMIN = TEST_USERS["admin"]


def _line_window_kit():
    """Single-line DOMESTIC factory; MWIN; lot 1000 @100; allocation total 100;
    runs A [09-07,09-11), B [09-11,09-14), C [09-10,09-12) — all STOCK 10 on
    line 1, created before lock."""
    kit = standard_kit(with_run=False, factory_overrides={"line_count": 1},
                       model_overrides={"style_code": "MWIN"})
    ra = make_run(kit["model"]["id"], kit["factory"]["id"], planned_units=10,
                  line_index=1, start_day="2026-09-07", end_day="2026-09-11")
    rb = make_run(kit["model"]["id"], kit["factory"]["id"], planned_units=10,
                  line_index=1, start_day="2026-09-11", end_day="2026-09-14")
    rc = make_run(kit["model"]["id"], kit["factory"]["id"], planned_units=10,
                  line_index=1, start_day="2026-09-10", end_day="2026-09-12")
    lock_allocation(kit["allocation"]["id"])
    kit.update({"ra": ra, "rb": rb, "rc": rc})
    return kit


def test_line_window_touching_boundaries_do_not_conflict():
    """PRD §3.5: "The line-window rule treats each run's `[start_day, end_day)`
    as half-open: if any other run on the same factory and `line_index` is in
    `MATERIAL_RESERVED`, `IN_PRODUCTION`, or `QUALITY_HOLD` with a window that
    intersects this run's, the reservation is rejected with
    `ERR_LINE_WINDOW_CONFLICT` (HTTP 409) — but windows that merely touch,
    where one run's `end_day` equals the other's `start_day`, do not conflict."

    Design: Difficulty/resource_temporal_overlap/line_window_half_open_overlap_semantics
    """
    kit = _line_window_kit()
    assert reserve_run(kit["ra"]["id"])["status"] == "MATERIAL_RESERVED"
    # B.start_day == A.end_day (2026-09-11): adjacency is not a conflict.
    assert reserve_run(kit["rb"]["id"])["status"] == "MATERIAL_RESERVED"
    assert get_lot(kit["lot"]["id"])["quantity_remaining"] == 980


def test_line_window_interior_overlap_is_rejected():
    """PRD §3.5: "if any other run on the same factory and `line_index` is in
    `MATERIAL_RESERVED`, `IN_PRODUCTION`, or `QUALITY_HOLD` with a window that
    intersects this run's, the reservation is rejected with
    `ERR_LINE_WINDOW_CONFLICT` (HTTP 409)"

    Design: Difficulty/resource_temporal_overlap/line_window_half_open_overlap_semantics
    """
    kit = _line_window_kit()
    reserve_run(kit["ra"]["id"])
    reserve_run(kit["rb"]["id"])
    resp = api.reserve_materials(kit["rc"]["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_LINE_WINDOW_CONFLICT)
    assert get_run(kit["rc"]["id"])["status"] == "PLANNED"
    assert get_lot(kit["lot"]["id"])["quantity_remaining"] == 980


def _contract_window_kit():
    """DOMESTIC factory; DOMESTIC_ONLY model MGOV2 (contract creation checks
    the window only, not Berry content); contract G-100 for
    [2026-10-01, 2026-10-31]."""
    set_clock()
    factory = make_factory()
    component = make_component("Full-grain leather upper", "UPPER")
    model = make_model(component["id"], style_code="MGOV2",
                       production_policy="DOMESTIC_ONLY", base_price_cents=20000,
                       import_cost_basis_cents=8000,
                       bom_lines=[{
                           "component_id": component["id"],
                           "quantity_per_pair": 1.0,
                           "sourcing_requirement": "DOMESTIC_REQUIRED",
                           "planned_unit_cost_cents": 500,
                           "planned_is_domestic": True,
                       }])
    g1 = make_contract(model["id"], factory["id"], contract_number="G-100",
                       awarded_units=10, fulfillment_start="2026-10-01",
                       fulfillment_end="2026-10-31")
    return {"factory": factory, "model": model, "g1": g1}


def test_contract_window_touching_endpoint_conflicts():
    """PRD §3.9: "Two contracts at the same factory may not share even a single
    day: a new contract whose closed window intersects — including merely
    touching endpoints — another contract at the same factory in `AWARDED`,
    `IN_FULFILLMENT`, or `COMPLIANCE_AUDIT` is rejected with
    `ERR_GOV_CONTRACT_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/contract_window_closed_interval_overlap_semantics
    """
    kit = _contract_window_kit()
    resp = api.create_gov_contract({
        "contract_number": "G-101", "model_id": kit["model"]["id"],
        "factory_id": kit["factory"]["id"], "awarded_units": 10,
        "fulfillment_start": "2026-10-31", "fulfillment_end": "2026-11-15",
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_GOV_CONTRACT_WINDOW_CONFLICT)


def test_contract_window_starting_after_inclusive_end_is_accepted():
    """PRD §3.9: "Unlike production line windows, contract windows are closed
    intervals — both boundary days are inclusive — and `fulfillment_end` must
    be strictly after `fulfillment_start` (otherwise `ERR_INVALID_REQUEST`)."
    PRD §3.9: "A fresh contract is `AWARDED`, with `fulfilled_units` 0 and
    `audit_passed` null until the audit completes."

    Design: Difficulty/resource_temporal_overlap/contract_window_closed_interval_overlap_semantics
    """
    kit = _contract_window_kit()
    resp = api.create_gov_contract({
        "contract_number": "G-102", "model_id": kit["model"]["id"],
        "factory_id": kit["factory"]["id"], "awarded_units": 10,
        "fulfillment_start": "2026-11-01", "fulfillment_end": "2026-11-30",
    }, ADMIN)
    contract = validate_success(resp, 201)
    assert contract["status"] == "AWARDED"
    assert contract["fulfilled_units"] == 0 and contract["audit_passed"] is None
