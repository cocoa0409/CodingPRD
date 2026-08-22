"""Composite setup helpers.

Every helper drives an empty database into a described state using only the
endpoints the PRD publishes, and uses the lenient success validator so a broken
precondition surfaces as a clear "Setup step failed" rather than as a confusing
assertion deep inside a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    blend_component,
    create_blend_trial_payload,
    create_bottling_line_payload,
    create_bottling_run_payload,
    create_client_payload,
    create_contract_payload,
    create_dry_goods_item_payload,
    create_harvest_intake_payload,
    create_lot_payload,
    create_release_order_payload,
    create_ttb_report_payload,
    create_vessel_payload,
    create_work_order_payload,
)
from .test_users import (
    TEST_USERS,
    make_client_rep_headers,
    make_cellar_supervisor_headers,
    make_compliance_officer_headers,
    make_facility_admin_headers,
)

ADMIN = TEST_USERS["facility_admin_headers"]
CELLAR = TEST_USERS["cellar_supervisor_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
SECOND_OFFICER = TEST_USERS["second_compliance_officer_headers"]

# ── Truckload presets (net weight → tonnage → gallons at the stated Brix) ──
# 42000 - 4000 = 38000 lb = 19.0 t at 23.50 Brix → 3135.00 gallons
LOAD_19T_CABERNET_OAKVILLE = {
    "gross_weight_lbs": 42000,
    "tare_weight_lbs": 4000,
    "varietal": "CABERNET_SAUVIGNON",
    "appellation": "OAKVILLE",
    "block_code": "B12",
    "brix": 23.50,
    "ph": 3.62,
}
# 24000 - 4000 = 20000 lb = 10.0 t at 26.40 Brix → 1565.00 gallons
LOAD_10T_CABERNET_OAKVILLE_HIGH_BRIX = {
    "gross_weight_lbs": 24000,
    "tare_weight_lbs": 4000,
    "varietal": "CABERNET_SAUVIGNON",
    "appellation": "OAKVILLE",
    "block_code": "B12",
    "brix": 26.40,
    "ph": 3.62,
}
# 14500 - 4000 = 10500 lb = 5.25 t at 24.00 Brix → 866.25 gallons
LOAD_5_25T_MERLOT_OAKVILLE = {
    "gross_weight_lbs": 14500,
    "tare_weight_lbs": 4000,
    "varietal": "MERLOT",
    "appellation": "OAKVILLE",
    "block_code": "B07",
    "brix": 24.00,
    "ph": 3.55,
}
# 14000 - 4000 = 10000 lb = 5.0 t at 23.50 Brix → 825.00 gallons
LOAD_5T_CHARDONNAY_NAPA = {
    "gross_weight_lbs": 14000,
    "tare_weight_lbs": 4000,
    "varietal": "CHARDONNAY",
    "appellation": "NAPA_VALLEY",
    "block_code": "C01",
    "brix": 23.50,
    "ph": 3.30,
}


# ── Tier 0: primitives ────────────────────────────────────────────────


def set_clock(to_iso8601: str, headers=None) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, headers or ADMIN))


def new_client(**overrides) -> dict:
    return get_success_data(
        api_client.create_client(create_client_payload(**overrides), ADMIN)
    )


def new_contract(client_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_contract(create_contract_payload(client_id, **overrides), ADMIN)
    )


def activate_contract(contract_id: str) -> dict:
    get_success_data(
        api_client.contract_transition(contract_id, {"action": "SUBMIT"}, ADMIN)
    )
    return get_success_data(
        api_client.contract_transition(contract_id, {"action": "ACTIVATE"}, ADMIN)
    )


def new_vessel(**overrides) -> dict:
    return get_success_data(
        api_client.create_vessel(create_vessel_payload(**overrides), ADMIN)
    )


def new_bottling_line(**overrides) -> dict:
    return get_success_data(
        api_client.create_bottling_line(create_bottling_line_payload(**overrides), ADMIN)
    )


def new_dry_goods_item(client_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_dry_goods_item(
            create_dry_goods_item_payload(client_id, **overrides), ADMIN
        )
    )


def weigh_in(contract_id: str, delivery_ticket: str, load=None, **overrides) -> dict:
    load = dict(load or LOAD_19T_CABERNET_OAKVILLE)
    load.pop("brix", None)
    load.pop("ph", None)
    load.update(overrides)
    payload = create_harvest_intake_payload(
        contract_id, delivery_ticket=delivery_ticket, **load
    )
    return get_success_data(api_client.create_harvest_intake(payload, CELLAR))


def sample_intake(intake_id: str, brix: float, ph: float) -> dict:
    return get_success_data(
        api_client.harvest_intake_transition(
            intake_id, {"action": "SAMPLE", "brix": brix, "ph": ph}, CELLAR
        )
    )


def accept_intake(intake_id: str) -> dict:
    return get_success_data(
        api_client.harvest_intake_transition(intake_id, {"action": "ACCEPT"}, CELLAR)
    )


def new_accepted_intake(contract_id: str, delivery_ticket: str, load=None, **overrides) -> dict:
    load = dict(load or LOAD_19T_CABERNET_OAKVILLE)
    brix = overrides.pop("brix", load["brix"])
    ph = overrides.pop("ph", load["ph"])
    intake = weigh_in(contract_id, delivery_ticket, load=load, **overrides)
    sample_intake(intake["id"], brix, ph)
    return accept_intake(intake["id"])


def new_lot(contract_id: str, intake_ids, **overrides) -> dict:
    return get_success_data(
        api_client.create_lot(create_lot_payload(contract_id, intake_ids, **overrides), CELLAR)
    )


def read_vessel_version(vessel_id: str) -> int:
    return get_success_data(api_client.get_vessel(vessel_id, ADMIN))["version"]


def read_contract_version(contract_id: str) -> int:
    return get_success_data(api_client.get_contract(contract_id, ADMIN))["version"]


def reserve_allocation(
    contract_id: str,
    vessel_id: str,
    allocated_gallons: float = 4000,
    start_at: str = "2026-09-01T00:00:00Z",
    end_at: str = "2026-11-01T00:00:00Z",
    expected_vessel_version=None,
    headers=None,
) -> dict:
    payload = {
        "contract_id": contract_id,
        "vessel_id": vessel_id,
        "start_at": start_at,
        "end_at": end_at,
        "allocated_gallons": allocated_gallons,
        "expected_vessel_version": (
            read_vessel_version(vessel_id)
            if expected_vessel_version is None
            else expected_vessel_version
        ),
    }
    return get_success_data(
        api_client.create_vessel_allocation(payload, headers or CELLAR)
    )


def commit_allocation(allocation_id: str, lot_id: str) -> dict:
    return get_success_data(
        api_client.commit_vessel_allocation(allocation_id, {"lot_id": lot_id}, CELLAR)
    )


def release_allocation(allocation_id: str) -> dict:
    return get_success_data(
        api_client.vessel_allocation_transition(
            allocation_id, {"action": "RELEASE"}, CELLAR
        )
    )


def clean_vessel(vessel_id: str) -> dict:
    return get_success_data(
        api_client.vessel_condition(vessel_id, {"action": "CLEAN"}, CELLAR)
    )


def house_lot(
    contract_id: str,
    vessel_id: str,
    lot_id: str,
    allocated_gallons: float = 4000,
    start_at: str = "2026-09-01T00:00:00Z",
    end_at: str = "2026-11-01T00:00:00Z",
) -> dict:
    allocation = reserve_allocation(
        contract_id, vessel_id, allocated_gallons, start_at, end_at
    )
    commit_allocation(allocation["id"], lot_id)
    return allocation


def advance_lot_to_aging(lot_id: str, loss_gallons: float = 0) -> dict:
    get_success_data(
        api_client.lot_transition(lot_id, {"action": "START_FERMENTATION"}, CELLAR)
    )
    get_success_data(
        api_client.lot_transition(
            lot_id, {"action": "PRESS", "loss_gallons": loss_gallons}, CELLAR
        )
    )
    return get_success_data(
        api_client.lot_transition(lot_id, {"action": "START_AGING"}, CELLAR)
    )


# ── Tier 1: an active contract, optionally with fruit and a lot ───────


def setup_active_contract(
    clock: str = "2026-09-01T00:00:00Z", client_overrides=None, **contract_overrides
) -> dict:
    """Clock + one ACTIVE Client + one ACTIVE Contract.  Returns a scenario dict."""
    set_clock(clock)
    client = new_client(**(client_overrides or {}))
    contract = new_contract(client["id"], **contract_overrides)
    contract = activate_contract(contract["id"])
    return {
        "client": client,
        "contract": contract,
        "rep_headers": make_client_rep_headers(client["id"]),
    }


def setup_contract_with_lot(
    clock: str = "2026-09-01T00:00:00Z",
    load=None,
    delivery_ticket: str = "DT-1001",
    lot_code: str = "CS-OAK-26-01",
    **contract_overrides,
) -> dict:
    """ACTIVE contract holding one lot built from a single accepted truckload."""
    scenario = setup_active_contract(clock, **contract_overrides)
    contract_id = scenario["contract"]["id"]
    intake = new_accepted_intake(contract_id, delivery_ticket, load=load)
    lot = new_lot(contract_id, [intake["id"]], lot_code=lot_code)
    scenario["intake"] = intake
    scenario["lot"] = lot
    return scenario


def setup_housed_aging_lot(
    clock: str = "2026-09-01T00:00:00Z",
    load=None,
    delivery_ticket: str = "DT-1001",
    lot_code: str = "CS-OAK-26-01",
    allocated_gallons: float = 4000,
    vessel_overrides=None,
    alloc_start: str = "2026-09-01T00:00:00Z",
    alloc_end: str = "2026-11-01T00:00:00Z",
    press_loss_gallons: float = 0,
    **contract_overrides,
) -> dict:
    """One lot committed into a CLEAN tank and advanced to production AGING."""
    scenario = setup_contract_with_lot(
        clock, load, delivery_ticket, lot_code, **contract_overrides
    )
    vessel = new_vessel(**(vessel_overrides or {}))
    allocation = house_lot(
        scenario["contract"]["id"],
        vessel["id"],
        scenario["lot"]["id"],
        allocated_gallons,
        alloc_start,
        alloc_end,
    )
    lot = advance_lot_to_aging(scenario["lot"]["id"], press_loss_gallons)
    scenario["vessel"] = vessel
    scenario["allocation"] = allocation
    scenario["lot"] = lot
    return scenario


def setup_two_aging_lots(
    clock: str = "2026-09-01T00:00:00Z",
    load_a=None,
    load_b=None,
    ticket_a: str = "DT-1001",
    ticket_b: str = "DT-1002",
    lot_code_a: str = "CS-OAK-26-01",
    lot_code_b: str = "ME-OAK-26-01",
    gallons_a: float = 2000,
    gallons_b: float = 1000,
    **contract_overrides,
) -> dict:
    """Two INTAKE lots on one contract, each housed in its own tank and AGING.

    Defaults produce lot_a = 1565.00 gallons of CABERNET_SAUVIGNON / OAKVILLE
    (alcohol 14.52) and lot_b = 866.25 gallons of MERLOT / OAKVILLE (13.20).
    """
    load_a = load_a or LOAD_10T_CABERNET_OAKVILLE_HIGH_BRIX
    load_b = load_b or LOAD_5_25T_MERLOT_OAKVILLE
    scenario = setup_active_contract(clock, **contract_overrides)
    contract_id = scenario["contract"]["id"]

    vessel_a = new_vessel(vessel_code="T-101")
    vessel_b = new_vessel(vessel_code="T-102")

    intake_a = new_accepted_intake(contract_id, ticket_a, load=load_a)
    lot_a = new_lot(contract_id, [intake_a["id"]], lot_code=lot_code_a)
    intake_b = new_accepted_intake(contract_id, ticket_b, load=load_b)
    lot_b = new_lot(contract_id, [intake_b["id"]], lot_code=lot_code_b)

    allocation_a = house_lot(contract_id, vessel_a["id"], lot_a["id"], gallons_a)
    allocation_b = house_lot(contract_id, vessel_b["id"], lot_b["id"], gallons_b)

    lot_a = advance_lot_to_aging(lot_a["id"])
    lot_b = advance_lot_to_aging(lot_b["id"])

    scenario.update(
        {
            "vessel_a": vessel_a,
            "vessel_b": vessel_b,
            "intake_a": intake_a,
            "intake_b": intake_b,
            "lot_a": lot_a,
            "lot_b": lot_b,
            "allocation_a": allocation_a,
            "allocation_b": allocation_b,
        }
    )
    return scenario


# ── Tier 2: blend-trial lifecycle ─────────────────────────────────────


def new_blend_trial(contract_id: str, rep_headers, components, **overrides) -> dict:
    return get_success_data(
        api_client.create_blend_trial(
            create_blend_trial_payload(contract_id, components, **overrides), rep_headers
        )
    )


def submit_blend_trial(trial_id: str, rep_headers) -> dict:
    return get_success_data(
        api_client.blend_trial_transition(trial_id, {"action": "SUBMIT"}, rep_headers)
    )


def approve_blend_trial(trial_id: str) -> dict:
    return get_success_data(
        api_client.blend_trial_transition(trial_id, {"action": "APPROVE"}, ADMIN)
    )


def execute_blend_trial(trial_id: str, contract_id: str, rep_headers) -> dict:
    version = read_contract_version(contract_id)
    return get_success_data(
        api_client.execute_blend_trial(
            trial_id, {"expected_contract_version": version}, rep_headers
        )
    )


def setup_submitted_blend_trial(
    scenario=None, draw_a: float = 750.00, draw_b: float = 250.00,
    declared_loss_pct: float = 2.00, **kwargs
) -> dict:
    """Two AGING lots plus a SUBMITTED trial drawing from both."""
    scenario = scenario or setup_two_aging_lots(**kwargs)
    trial = new_blend_trial(
        scenario["contract"]["id"],
        scenario["rep_headers"],
        [
            blend_component(scenario["lot_a"]["id"], draw_a),
            blend_component(scenario["lot_b"]["id"], draw_b),
        ],
        declared_loss_pct=declared_loss_pct,
    )
    scenario["trial"] = submit_blend_trial(trial["id"], scenario["rep_headers"])
    return scenario


def setup_approved_blend_trial(**kwargs) -> dict:
    scenario = setup_submitted_blend_trial(**kwargs)
    scenario["trial"] = approve_blend_trial(scenario["trial"]["id"])
    return scenario


def setup_executed_blend_trial(**kwargs) -> dict:
    scenario = setup_approved_blend_trial(**kwargs)
    scenario["trial"] = execute_blend_trial(
        scenario["trial"]["id"], scenario["contract"]["id"], scenario["rep_headers"]
    )
    scenario["blend_lot"] = get_success_data(
        api_client.get_lot(scenario["trial"]["result_lot_id"], ADMIN)
    )
    return scenario


# ── Tier 3: work-order lifecycle ──────────────────────────────────────


def new_work_order(lot_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_work_order(
            create_work_order_payload(lot_id, **overrides), headers or CELLAR
        )
    )


def drive_work_order_to_completed(
    work_order_id: str, actual_labor_hours: float = 2.50, supervisor_headers=None
) -> dict:
    headers = supervisor_headers or CELLAR
    get_success_data(
        api_client.work_order_transition(work_order_id, {"action": "SCHEDULE"}, headers)
    )
    get_success_data(
        api_client.work_order_transition(work_order_id, {"action": "START"}, headers)
    )
    return get_success_data(
        api_client.work_order_transition(
            work_order_id,
            {"action": "COMPLETE", "actual_labor_hours": actual_labor_hours},
            headers,
        )
    )


def bill_work_order(work_order_id: str, contract_id: str, admin_headers=None) -> dict:
    version = read_contract_version(contract_id)
    return get_success_data(
        api_client.bill_work_order(
            work_order_id, {"expected_contract_version": version}, admin_headers or ADMIN
        )
    )


def setup_completed_work_order(
    clock: str = "2026-09-10T00:00:00Z",
    actual_labor_hours: float = 2.50,
    work_order_overrides=None,
    supervisor_headers=None,
    **contract_overrides,
) -> dict:
    """ACTIVE contract carrying one 19-ton crush fee plus one COMPLETED order."""
    scenario = setup_contract_with_lot(clock=clock, **contract_overrides)
    order = new_work_order(
        scenario["lot"]["id"],
        headers=supervisor_headers or CELLAR,
        **(work_order_overrides or {"material_cost_cents": 2000, "rush": False}),
    )
    scenario["work_order"] = drive_work_order_to_completed(
        order["id"], actual_labor_hours, supervisor_headers
    )
    return scenario


def setup_billed_work_order(**kwargs) -> dict:
    scenario = setup_completed_work_order(**kwargs)
    scenario["work_order"] = bill_work_order(
        scenario["work_order"]["id"], scenario["contract"]["id"]
    )
    return scenario


# ── Tier 4: bottling, dry goods and the supply waterfall ──────────────


def setup_dry_goods_shelf(client_id: str, **unit_counts) -> dict:
    """One SKU per required item type, seeded with the supplied unit counts."""
    counts = {
        "BOTTLE": 6000,
        "CORK": 6000,
        "CAPSULE": 6000,
        "LABEL": 12000,
        "CASE_BOX": 500,
    }
    counts.update({k.upper(): v for k, v in unit_counts.items()})
    skus = {
        "BOTTLE": ("BTL-750", 12),
        "CORK": ("CRK-44", 1000),
        "CAPSULE": ("CAP-TIN", 1000),
        "LABEL": ("LBL-EST", 2000),
        "CASE_BOX": ("BOX-12", 25),
    }
    items = {}
    for item_type, units in counts.items():
        sku, units_per_case = skus[item_type]
        items[item_type] = new_dry_goods_item(
            client_id,
            sku=sku,
            item_type=item_type,
            units_per_case=units_per_case,
            initial_units=units,
        )
    return items


def new_bottling_run(lot_id: str, line_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_bottling_run(
            create_bottling_run_payload(lot_id, line_id, **overrides), CELLAR
        )
    )


def reserve_supplies(run_id: str) -> dict:
    return get_success_data(
        api_client.bottling_run_transition(
            run_id, {"action": "RESERVE_SUPPLIES"}, CELLAR
        )
    )


def setup_scheduled_bottling_run(
    clock: str = "2026-10-10T00:00:00Z",
    cases_planned: int = 100,
    bottle_size_ml: int = 750,
    scheduled_start: str = "2026-10-12T09:00:00Z",
    line_overrides=None,
    dry_goods=None,
    housed: bool = False,
    **contract_overrides,
) -> dict:
    """ACTIVE contract, one lot, one AVAILABLE line and one SCHEDULED run."""
    if housed:
        scenario = setup_housed_aging_lot(
            clock=clock,
            alloc_start=clock,
            alloc_end="2026-12-01T00:00:00Z",
            **contract_overrides,
        )
    else:
        scenario = setup_contract_with_lot(clock=clock, **contract_overrides)
    line = new_bottling_line(**(line_overrides or {}))
    if dry_goods is not None:
        scenario["dry_goods"] = setup_dry_goods_shelf(
            scenario["client"]["id"], **dry_goods
        )
    run = new_bottling_run(
        scenario["lot"]["id"],
        line["id"],
        cases_planned=cases_planned,
        bottle_size_ml=bottle_size_ml,
        scheduled_start=scheduled_start,
    )
    scenario["line"] = line
    scenario["run"] = run
    return scenario


def setup_supplies_reserved_run(**kwargs) -> dict:
    kwargs.setdefault("dry_goods", {})
    scenario = setup_scheduled_bottling_run(**kwargs)
    scenario["run"] = reserve_supplies(scenario["run"]["id"])
    return scenario


# ── Tier 5: removal from bond and bonded reporting ────────────────────


def new_release_order(lot_id: str, rep_headers, **overrides) -> dict:
    return get_success_data(
        api_client.create_release_order(
            create_release_order_payload(lot_id, **overrides), rep_headers
        )
    )


def approve_release_order(order_id: str, officer_headers=None) -> dict:
    return get_success_data(
        api_client.release_order_transition(
            order_id, {"action": "APPROVE"}, officer_headers or OFFICER
        )
    )


def execute_release_order(order_id: str, officer_headers=None) -> dict:
    return get_success_data(
        api_client.release_order_transition(
            order_id, {"action": "EXECUTE"}, officer_headers or OFFICER
        )
    )


def setup_requested_release_order(scenario=None, gallons: float = 100.00, **kwargs) -> dict:
    scenario = scenario or setup_housed_aging_lot(**kwargs)
    scenario["release_order"] = new_release_order(
        scenario["lot"]["id"], scenario["rep_headers"], gallons=gallons
    )
    return scenario


def setup_approved_release_order(**kwargs) -> dict:
    scenario = setup_requested_release_order(**kwargs)
    scenario["release_order"] = approve_release_order(scenario["release_order"]["id"])
    return scenario


def setup_executed_release_order(**kwargs) -> dict:
    scenario = setup_approved_release_order(**kwargs)
    scenario["release_order"] = execute_release_order(scenario["release_order"]["id"])
    return scenario


def new_ttb_report(client_id: str, officer_headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_ttb_report(
            create_ttb_report_payload(client_id, **overrides), officer_headers or OFFICER
        )
    )


def prepare_ttb_report(report_id: str, variant=None, officer_headers=None) -> dict:
    payload = {"action": "PREPARE"}
    if variant is not None:
        payload["variant"] = variant
    return get_success_data(
        api_client.ttb_report_transition(report_id, payload, officer_headers or OFFICER)
    )


def recall_ttb_report(report_id: str, officer_headers=None) -> dict:
    return get_success_data(
        api_client.ttb_report_transition(
            report_id, {"action": "RECALL"}, officer_headers or OFFICER
        )
    )


def file_ttb_report(report_id: str, officer_headers=None) -> dict:
    return get_success_data(
        api_client.ttb_report_transition(
            report_id, {"action": "FILE"}, officer_headers or SECOND_OFFICER
        )
    )


def setup_prepared_ttb_report(
    client_id: str, period_start: str, period_end: str, variant=None
) -> dict:
    report = new_ttb_report(
        client_id, period_start=period_start, period_end=period_end
    )
    return prepare_ttb_report(report["id"], variant)
