"""Derived aggregates: plant roll-ups, tank balances, track commitments."""
from decimal import Decimal

import calc
from store import db
from util import D, rhu, at_second, plus_minutes

ZERO2 = D("0.00")
ZERO3 = D("0.000")

BATCH_CONSUMING_STATES = ("CHARGED", "FERMENTING", "HEALTH_WATCH", "DISTILLING",
                          "COMPLETED", "DUMPED")
TRACK_COMMITTED_STATES = ("SCHEDULED", "BLOCKED", "LOADED")

DEFAULT_BASE_GRIND_CAP = 120000
DEFAULT_COVERAGE_FLOOR = D("200000")
DEFAULT_BASELINE_CI = D("60.0")


# --------------------------------------------------------------- contracts
def contract_bushels_delivered(contract_id):
    total = D(0)
    for delivery in db.deliveries.values():
        if delivery["contract_id"] == contract_id and delivery["grading_status"] == "SETTLED":
            total += D(delivery["net_dry_bushels"])
    return rhu(total, 2)


def contract_remainder(contract):
    delivered = contract_bushels_delivered(contract["id"])
    return rhu(D(contract["bushels_contracted"]) - delivered, 2)


# ------------------------------------------------------------------- tanks
def tank_current_gallons(tank):
    total = D(tank["opening_gallons"])
    for batch in db.batches.values():
        if batch["destination_tank_id"] == tank["id"] and batch["status"] == "COMPLETED":
            total += D(batch["ethanol_gallons_produced"] or 0)
    for blend in db.blends.values():
        if blend["status"] != "EXECUTED":
            continue
        if blend["destination_tank_id"] == tank["id"]:
            total += D(blend["output_gallons"] or 0)
        if blend["neat_source_tank_id"] == tank["id"]:
            total -= D(blend["neat_gallons"])
        if blend["denaturant_source_tank_id"] == tank["id"]:
            total -= D(blend["denaturant_gallons"])
    for shipment in db.shipments.values():
        if (shipment["source_tank_id"] == tank["id"]
                and shipment["loading_status"] == "LOADED"):
            total -= D(shipment["loaded_gallons"] or 0)
    return rhu(total, 2)


def tank_available_gallons(tank):
    current = tank_current_gallons(tank)
    available = rhu(D(tank["capacity_gallons"]) - current, 2)
    if available < 0:
        available = ZERO2
    return available


def blend_occupancy_end(blend, tank=None):
    tank = tank or db.tanks.get(blend["destination_tank_id"])
    minutes = tank["settling_buffer_minutes"] if tank else 0
    return plus_minutes(blend["window_end"], minutes)


# ------------------------------------------------------------------ tracks
def track_committed_railcars(track_id, window_start=None, window_end=None,
                             exclude_id=None):
    total = 0
    for shipment in db.shipments.values():
        if shipment["track_id"] != track_id:
            continue
        if shipment["loading_status"] not in TRACK_COMMITTED_STATES:
            continue
        if exclude_id is not None and shipment["id"] == exclude_id:
            continue
        if window_start is not None:
            if not calc.windows_overlap_half_open(
                    at_second(shipment["window_start"]), at_second(shipment["window_end"]),
                    at_second(window_start), at_second(window_end)):
                continue
        total += int(shipment["railcar_count"])
    return total


# ------------------------------------------------------------------ plant
def plant_corn_inventory():
    total = D(0)
    for delivery in db.deliveries.values():
        if delivery["grading_status"] == "SETTLED":
            total += D(delivery["net_dry_bushels"])
    for batch in db.batches.values():
        if batch["status"] in BATCH_CONSUMING_STATES:
            total -= D(batch["corn_bushels_charged"])
    return rhu(total, 2)


def plant_ddgs_inventory():
    total = D(0)
    for batch in db.batches.values():
        if batch["status"] == "COMPLETED":
            total += D(batch["ddgs_tons_produced"] or 0)
    for sale in db.sales.values():
        if sale["status"] == "SHIPPED" and sale["product"] in ("DDGS_DRY", "DDGS_WET"):
            total -= D(sale["quantity"])
    return rhu(total, 3)


def plant_corn_oil_inventory():
    total = D(0)
    for batch in db.batches.values():
        if batch["status"] == "COMPLETED":
            total += D(batch["corn_oil_lbs_produced"] or 0)
    for sale in db.sales.values():
        if sale["status"] == "SHIPPED" and sale["product"] == "CORN_OIL":
            total -= D(sale["quantity"])
    return rhu(total, 2)


def open_contract_coverage():
    total = D(0)
    for contract in db.contracts.values():
        if contract["status"] in ("OPEN", "PARTIALLY_FILLED"):
            total += contract_remainder(contract)
    return rhu(total, 2)


def procurement_posture():
    plant = db.plant
    floor = D(plant["coverage_floor_bushels"]) if plant else DEFAULT_COVERAGE_FLOOR
    return "ADEQUATE" if open_contract_coverage() >= floor else "SHORT"


def compliance_posture():
    rank = 0
    for condition in db.conditions.values():
        if condition["status"] == "EXCEEDANCE":
            rank = max(rank, calc.SEVERITY_RANK[condition["severity"]])
    for tank in db.tanks.values():
        if tank["service_status"] == "ON_HOLD" and tank["hold_reason"] == "OFF_SPEC":
            rank = max(rank, 1)
    return calc.POSTURE_BY_RANK[rank]


def daily_grind_cap():
    plant = db.plant
    base = plant["base_grind_cap_bushels"] if plant else DEFAULT_BASE_GRIND_CAP
    return calc.grind_cap(base, compliance_posture(), procurement_posture())


def rolling_yield():
    bushels = D(0)
    gallons = D(0)
    for batch in db.batches.values():
        if batch["status"] == "COMPLETED":
            bushels += D(batch["corn_bushels_charged"])
            gallons += D(batch["ethanol_gallons_produced"] or 0)
    if bushels <= 0:
        return calc.BASE_YIELD
    return rhu(gallons / bushels, 3)


def certified_projects_in_order():
    projects = [p for p in db.projects.values() if p["verification_status"] == "CERTIFIED"]
    return sorted(projects, key=lambda p: (p["certified_at"], p["created_at"], p["_seq"]))


def ci_state():
    certified = certified_projects_in_order()
    credited, total = calc.ci_waterfall(certified)
    plant = db.plant
    baseline = D(plant["baseline_ci_g_per_mj"]) if plant else DEFAULT_BASELINE_CI
    score = calc.ci_score(baseline, total)
    # PRD 3.1: "lcfs_credit_tonnes_per_million_gal starts at 0.000"; PRD 3.8:
    # both carbon figures are "re-derived on every certification", so the credit
    # figure stays at its seeded zero until a project has actually been certified.
    lcfs = calc.lcfs_credit(score) if certified else D("0.000")
    return credited, total, score, lcfs


def recompute_credited(skip_bump_id=None):
    """Re-run the waterfall across every certified project. Each rewritten row
    takes a fresh version and updated_at (the row that triggered the run is
    bumped by its own transition, so it is skipped here)."""
    from store import touch
    credited, _total = calc.ci_waterfall(certified_projects_in_order())
    for project_id, value in credited.items():
        project = db.projects[project_id]
        project["credited_reduction_g_per_mj"] = value
        if project_id != skip_bump_id:
            touch(project)


def position_mark(commodity):
    plant = db.plant
    if plant is None:
        return None
    return {
        "CORN": plant["mark_corn_cents_per_bushel"],
        "ETHANOL": plant["mark_ethanol_cents_per_gallon"],
        "NATGAS": plant["mark_natgas_cents_per_mmbtu"],
    }[commodity]


def reprice_position(position):
    """Re-derive unrealized_pnl_cents against the commodity's current mark.
    PRD 3.9: a position opens with unrealized_pnl_cents at 0; the figure is
    re-derived when marks are posted and when contracts are closed."""
    contracts_open = int(position["contracts"]) - int(position["contracts_closed"])
    position["unrealized_pnl_cents"] = calc.hedge_unrealized(
        position["direction"], position["commodity"], position["entry_price"],
        position_mark(position["commodity"]), contracts_open)


def rin_counts():
    """Widening tallies of rin_count: generated over all live statuses,
    separated over SEPARATED and RETIRED, retired over RETIRED alone."""
    generated = separated = retired = 0
    for rin in db.rins.values():
        count = int(rin["rin_count"])
        if rin["status"] in ("GENERATED", "SEPARATED", "RETIRED"):
            generated += count
        if rin["status"] in ("SEPARATED", "RETIRED"):
            separated += count
        if rin["status"] == "RETIRED":
            retired += count
    return generated, separated, retired
