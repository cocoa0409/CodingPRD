"""Shared domain helpers: lookups, the two ledgers, cascades and scoring."""
from datetime import timedelta
from decimal import Decimal

import calculations as calc
from db import db, days_before, new_id, next_seq, now
from errors import fail

TERMINAL_DEV_STATUS = ("RATIONALIZED", "DISCONTINUED")
LIVE_RUN_STATUSES = ("SCHEDULED", "APPROVED")
LINE_OCCUPYING_STATUSES = ("SCHEDULED", "APPROVED", "HOLD", "COMPLETED")


# --------------------------------------------------------------------------
# row bookkeeping
# --------------------------------------------------------------------------
def new_row(extra=None, versioned=True):
    row = {"id": new_id(), "created_at": now(), "_seq": next_seq()}
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    if extra:
        row.update(extra)
    return row


def touch(row):
    """PRD 2.4 / 2.8: any mutated row gets a fresh updated_at and version + 1."""
    row["updated_at"] = now()
    row["version"] = row["version"] + 1


def apply_changes(row, changes):
    """Write changes, then touch the row only when something actually moved."""
    changed = False
    for key, value in changes.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed:
        touch(row)
    return changed


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------
def _lookup(collection, identifier, error_id):
    row = collection.get(identifier)
    if row is None:
        fail(error_id)
    return row


def get_program(identifier):
    return _lookup(db.programs, identifier, "ERR_PROGRAM_NOT_FOUND")


def get_gap(identifier):
    return _lookup(db.gaps, identifier, "ERR_GAP_NOT_FOUND")


def get_supplier(identifier):
    return _lookup(db.suppliers, identifier, "ERR_SUPPLIER_NOT_FOUND")


def get_plant_line(identifier):
    return _lookup(db.plant_lines, identifier, "ERR_PLANT_LINE_NOT_FOUND")


def get_audit(identifier):
    return _lookup(db.plant_audits, identifier, "ERR_AUDIT_NOT_FOUND")


def get_item(identifier):
    return _lookup(db.items, identifier, "ERR_ITEM_NOT_FOUND")


def get_cost_model(identifier):
    return _lookup(db.cost_models, identifier, "ERR_COST_MODEL_NOT_FOUND")


def get_study(identifier):
    return _lookup(db.studies, identifier, "ERR_STUDY_NOT_FOUND")


def get_artwork_round(identifier):
    return _lookup(db.artwork_rounds, identifier, "ERR_ARTWORK_ROUND_NOT_FOUND")


def get_claim(identifier):
    return _lookup(db.label_claims, identifier, "ERR_CLAIM_NOT_FOUND")


def get_specification(identifier):
    return _lookup(db.specifications, identifier, "ERR_SPECIFICATION_NOT_FOUND")


def get_run(identifier):
    return _lookup(db.production_runs, identifier, "ERR_RUN_NOT_FOUND")


def get_complaint(identifier):
    return _lookup(db.complaints, identifier, "ERR_COMPLAINT_NOT_FOUND")


def get_change_request(identifier):
    return _lookup(db.cost_change_requests, identifier, "ERR_CHANGE_REQUEST_NOT_FOUND")


# --------------------------------------------------------------------------
# program resolution and the two program-level gates
# --------------------------------------------------------------------------
def program_of_gap(gap):
    return db.programs[gap["program_id"]]


def program_of_item(item):
    return program_of_gap(db.gaps[item["gap_id"]])


def program_of_supplier(supplier):
    return db.programs[supplier["program_id"]]


def guard_program_open(program):
    if program["status"] == "CLOSED":
        fail("ERR_PROGRAM_CLOSED")


def guard_not_frozen(program):
    if program["status"] == "RELAUNCH_FREEZE":
        fail("ERR_PROGRAM_RELAUNCH_FROZEN")


# --------------------------------------------------------------------------
# collection scans
# --------------------------------------------------------------------------
def items_of_gap(gap_id):
    return [row for row in db.items.values() if row["gap_id"] == gap_id]


def items_of_program(program_id):
    gap_ids = set(g["id"] for g in db.gaps.values() if g["program_id"] == program_id)
    return [row for row in db.items.values() if row["gap_id"] in gap_ids]


def items_of_supplier(supplier_id):
    return [row for row in db.items.values() if row["supplier_id"] == supplier_id]


def runs_of_item(item_id):
    return [row for row in db.production_runs.values() if row["item_id"] == item_id]


def runs_of_supplier(supplier_id):
    item_ids = set(row["id"] for row in items_of_supplier(supplier_id))
    return [row for row in db.production_runs.values() if row["item_id"] in item_ids]


def runs_of_program(program_id):
    item_ids = set(row["id"] for row in items_of_program(program_id))
    return [row for row in db.production_runs.values() if row["item_id"] in item_ids]


def complaints_of_item(item_id):
    return [row for row in db.complaints.values() if row["item_id"] == item_id]


def complaints_of_supplier(supplier_id):
    item_ids = set(row["id"] for row in items_of_supplier(supplier_id))
    return [row for row in db.complaints.values() if row["item_id"] in item_ids]


def claims_of_round(round_id):
    return [row for row in db.label_claims.values() if row["artwork_round_id"] == round_id]


def specifications_of_item(item_id):
    return [row for row in db.specifications.values() if row["item_id"] == item_id]


def rounds_of_item(item_id):
    return [row for row in db.artwork_rounds.values() if row["item_id"] == item_id]


def studies_of_item(item_id):
    return [row for row in db.studies.values() if row["item_id"] == item_id]


def cost_models_of_item(item_id):
    return [row for row in db.cost_models.values() if row["item_id"] == item_id]


def cost_models_of_supplier(supplier_id):
    return [row for row in db.cost_models.values() if row["supplier_id"] == supplier_id]


# --------------------------------------------------------------------------
# ledgers (PRD 2.11) - exact integer arithmetic, no rounding anywhere
# --------------------------------------------------------------------------
PROGRAM_COUNTERS = (
    "committed_budget_cents",
    "lifetime_committed_cents",
    "lifetime_released_cents",
    "active_item_count",
    "status",
)
GAP_COUNTERS = ("slots_consumed", "slots_open", "slots_consumed_lifetime", "slots_released_lifetime")


def capture(row, fields):
    return dict((field, row[field]) for field in fields)


def touch_if_moved(row, before):
    for field, value in before.items():
        if row[field] != value:
            touch(row)
            return True
    return False


def _sync_committed(program):
    program["committed_budget_cents"] = (
        program["lifetime_committed_cents"] - program["lifetime_released_cents"]
    )


def commit_money(program, amount):
    program["lifetime_committed_cents"] += amount
    _sync_committed(program)


def release_money(program, amount):
    program["lifetime_released_cents"] += amount
    _sync_committed(program)


def available_budget(program):
    return program["dev_budget_cents"] - program["committed_budget_cents"]


def refresh_active_item_count(program):
    program["active_item_count"] = len(
        [row for row in items_of_program(program["id"]) if row["development_status"] not in TERMINAL_DEV_STATUS]
    )


def refresh_gap_slots(gap):
    gap["slots_consumed"] = len(
        [row for row in items_of_gap(gap["id"]) if row["development_status"] not in TERMINAL_DEV_STATUS]
    )
    gap["slots_open"] = gap["shelf_slots_quota"] - gap["slots_consumed"]


# --------------------------------------------------------------------------
# audits and landed costs
# --------------------------------------------------------------------------
def latest_finalized_audit(supplier_id, window_start=None, window_end=None):
    """Greatest window_end, tie-broken by the greater created_at."""
    candidates = [
        row
        for row in db.plant_audits.values()
        if row["supplier_id"] == supplier_id and row["status"] == "FINALIZED"
    ]
    if window_start is not None:
        candidates = [
            row for row in candidates if window_start <= row["window_end"] <= window_end
        ]
    if not candidates:
        return None
    candidates.sort(key=lambda row: (row["window_end"], row["created_at"], row["_seq"]))
    return candidates[-1]


def refresh_landed_costs(cost_model):
    cost_model["landed_unit_cost_cents_as_quoted"] = calc.landed_unit_cost(
        cost_model["effective_base_cents"],
        cost_model["quoted_yield_pct"],
        0,
        cost_model["freight_cents_per_pallet"],
        cost_model["units_per_pallet"],
    )
    audit = latest_finalized_audit(cost_model["supplier_id"])
    if audit is not None and audit["result"] != "FAIL":
        cost_model["landed_unit_cost_cents_audited"] = calc.landed_unit_cost(
            cost_model["effective_base_cents"],
            audit["audited_yield_pct"],
            calc.SCRAP_BY_RESULT[audit["result"]],
            cost_model["freight_cents_per_pallet"],
            cost_model["units_per_pallet"],
        )


def effective_landed_cost(cost_model):
    if cost_model["landed_unit_cost_cents_audited"] is not None:
        return cost_model["landed_unit_cost_cents_audited"]
    return cost_model["landed_unit_cost_cents_as_quoted"]


# --------------------------------------------------------------------------
# complaint trend, supplier counters and the posture cascade
# --------------------------------------------------------------------------
def weighted_complaint_points(complaint_rows, window_start):
    if window_start is None:
        return 0
    right = now()
    total = 0
    for row in complaint_rows:
        if window_start <= row["received_at"] <= right:
            total += calc.SEVERITY_WEIGHTS[row["severity"]]
    return total


def recompute_item_trend(item):
    """Refreshes complaint_ppm_90d and, outside SUSPENDED, the posture."""
    points = weighted_complaint_points(complaints_of_item(item["id"]), days_before(90))
    ppm = calc.complaint_ppm(points, item["trailing_90d_units"])
    changes = {"complaint_ppm_90d": ppm}
    if item["quality_posture"] != "SUSPENDED" and item["development_status"] not in TERMINAL_DEV_STATUS:
        changes["quality_posture"] = calc.posture_for_ppm(ppm)
    return apply_changes(item, changes)


def refresh_supplier_counters(supplier):
    supplier_id = supplier["id"]
    supplier["weighted_complaint_points"] = weighted_complaint_points(
        complaints_of_supplier(supplier_id), days_before(365)
    )
    supplier["probation_item_count"] = len(
        [row for row in items_of_supplier(supplier_id) if row["quality_posture"] == "PROBATION"]
    )


def hold_runs_for_supplier(supplier, reason):
    for run in runs_of_supplier(supplier["id"]):
        if run["status"] in LIVE_RUN_STATUSES:
            run["status"] = "HOLD"
            run["hold_reason"] = reason
            touch(run)


def release_held_runs_for_supplier(supplier):
    for run in runs_of_supplier(supplier["id"]):
        if run["status"] == "HOLD":
            run["status"] = "SCHEDULED"
            touch(run)


def suspend_supplier_items(supplier):
    for item in items_of_supplier(supplier["id"]):
        if item["development_status"] not in TERMINAL_DEV_STATUS:
            apply_changes(item, {"quality_posture": "SUSPENDED"})


def reinstate_supplier_items(supplier):
    for item in items_of_supplier(supplier["id"]):
        if item["quality_posture"] == "SUSPENDED":
            points = weighted_complaint_points(complaints_of_item(item["id"]), days_before(90))
            ppm = calc.complaint_ppm(points, item["trailing_90d_units"])
            apply_changes(item, {"complaint_ppm_90d": ppm, "quality_posture": calc.posture_for_ppm(ppm)})


def maybe_auto_conditional(supplier):
    """PRD 3.8: a second PROBATION item drops a QUALIFIED supplier to CONDITIONAL."""
    if supplier["qualification_status"] == "QUALIFIED" and supplier["probation_item_count"] >= 2:
        supplier["qualification_status"] = "CONDITIONAL"
        hold_runs_for_supplier(supplier, "SUPPLIER_CONDITIONAL")
        return True
    return False


# --------------------------------------------------------------------------
# supplier composite score (PRD 3.8)
# --------------------------------------------------------------------------
def composite_for_window(supplier, window_start):
    supplier_id = supplier["id"]
    right = now()
    if window_start is None:
        audit = None
        points = 0
        completed = []
    else:
        audit = latest_finalized_audit(supplier_id, window_start, right)
        points = weighted_complaint_points(complaints_of_supplier(supplier_id), window_start)
        completed = [
            row
            for row in runs_of_supplier(supplier_id)
            if row["status"] == "COMPLETED"
            and row["completed_at"] is not None
            and window_start <= row["completed_at"] <= right
        ]
    audit_part = calc.audit_component(audit)
    complaint_part = calc.complaint_component(points)
    on_time = len([row for row in completed if row["completed_on_time"]])
    delivery_part = calc.delivery_component(on_time, len(completed))
    return {
        "composite": calc.composite_score(audit_part, complaint_part, delivery_part),
        "audit_component": audit_part,
        "complaint_component": complaint_part,
        "delivery_component": delivery_part,
        "window_start": window_start,
    }


def rolling_window_start():
    return days_before(365)


def rolling_composite(supplier):
    return composite_for_window(supplier, rolling_window_start())


def refresh_cached_composite(supplier):
    supplier["composite_score_cached"] = rolling_composite(supplier)["composite"]
