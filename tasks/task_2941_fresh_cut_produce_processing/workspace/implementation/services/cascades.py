"""The three containment cascades. None of them is ever self-reversing."""

import datetime

import db
from services import chemistry, holds, lots, posture

ENV_CLOSED_RUN_LOOKBACK_HOURS = 24
REWORK_MAX_DEPTH = 5


def _run_order(run):
    return (db.dt_of(run, "planned_start_at"), db.dt_of(run, "created_at"), run["_seq"])


def _receipt_order(receipt):
    return (
        db.dt_of(receipt, "received_at"),
        db.dt_of(receipt, "created_at"),
        receipt["_seq"],
    )


def runs_of_line(line_id):
    return [r for r in db.rows("process_runs") if r["line_id"] == line_id]


def open_corrective_action(line, source_type, source_ref_id, severity, now):
    action = db.new_row(
        "corrective_actions",
        {
            "line_id": line["id"],
            "source_type": source_type,
            "source_ref_id": source_ref_id,
            "severity": severity,
            "status": "OPEN",
            "action_taken": None,
            "implemented_by_user_id": None,
            "verified_by_user_id": None,
            "reopen_count": 0,
            "verified_at": None,
            "_dt_verified_at": None,
        },
    )
    db.stamp(action, "opened_at", now)
    return action


def _hold_runs(run_rows, reason, now):
    """Hold each run in planned_start_at order and depress the lots it consumed."""
    held = []
    for run in sorted(run_rows, key=_run_order):
        if run["disposition_status"] == "REJECTED":
            continue
        holds.open_hold(run, reason, now)
        held.append(run)
    for run in held:
        for lot in lots.lots_consumed_by_run(run["id"]):
            lots.recompute_trailing(lot)
    return held


def _cancel_setup_runs(run_rows):
    for run in sorted(run_rows, key=_run_order):
        if run["run_status"] == "SETUP":
            run["run_status"] = "CANCELLED"
            db.touch(run)


# --------------------------------------------------------------------------
# environmental confirmation
# --------------------------------------------------------------------------


def environmental_confirmation(swab, line, now):
    severity = "CRITICAL" if swab["zone"] == "ZONE_1" else "MAJOR"
    open_corrective_action(line, "ENV_SWAB", swab["id"], severity, now)
    new_posture = posture.recompute(line)
    if new_posture != "FROZEN":
        return
    line_runs = runs_of_line(line["id"])
    _cancel_setup_runs([r for r in line_runs if r["run_status"] == "SETUP"])
    collected = db.dt_of(swab, "collected_at")
    cutoff = None
    if collected is not None:
        cutoff = collected - datetime.timedelta(hours=ENV_CLOSED_RUN_LOOKBACK_HOURS)
    targets = []
    for run in line_runs:
        if run["disposition_status"] == "REJECTED":
            continue
        if run["run_status"] == "RUNNING":
            targets.append(run)
        elif run["run_status"] == "CLOSED":
            closed = db.dt_of(run, "closed_at")
            if cutoff is not None and closed is not None and closed >= cutoff:
                targets.append(run)
    _hold_runs(targets, "ENVIRONMENTAL_POSITIVE", now)


# --------------------------------------------------------------------------
# sanitation validation failure
# --------------------------------------------------------------------------


def sanitation_failure(event, line, now):
    open_corrective_action(line, "SANITATION_FAILURE", event["id"], "MAJOR", now)
    posture.recompute(line)
    system_ids = []
    for run in runs_of_line(line["id"]):
        if run["run_status"] not in ("SETUP", "RUNNING"):
            continue
        if run["wash_system_id"] not in system_ids:
            system_ids.append(run["wash_system_id"])
    systems = [s for s in db.rows("wash_systems") if s["id"] in system_ids]
    systems.sort(key=lambda s: (db.dt_of(s, "created_at"), s["_seq"]))
    marked = []
    for system in systems:
        chemistry.force_dump_required(system)
        marked.append(system["id"])
    plant_runs = [
        r
        for r in db.rows("process_runs")
        if r["run_status"] == "SETUP" and r["wash_system_id"] in marked
    ]
    _cancel_setup_runs(plant_runs)


# --------------------------------------------------------------------------
# grower lot recall
# --------------------------------------------------------------------------


def _runs_consuming_receipt(receipt_id):
    out = []
    for c in db.rows("lot_consumptions"):
        if c["status"] != "ACTIVE" or c["raw_receipt_id"] != receipt_id:
            continue
        run = db.find("process_runs", c["process_run_id"])
        if run is not None and run not in out:
            out.append(run)
    return out


def _rework_descendants(roots):
    """Walk rework_source_run_id edges downward, at most REWORK_MAX_DEPTH hops."""
    frontier = list(roots)
    seen = set(r["id"] for r in roots)
    reached = []
    depth = 0
    while frontier and depth < REWORK_MAX_DEPTH:
        children = []
        for run in db.rows("process_runs"):
            parent_id = run.get("rework_source_run_id")
            if parent_id is None or run["id"] in seen:
                continue
            if any(parent_id == f["id"] for f in frontier):
                children.append(run)
                seen.add(run["id"])
        reached.extend(children)
        frontier = children
        depth += 1
    return reached


def recall(lot, now):
    lot["status"] = "RECALLED"
    db.stamp(lot, "recalled_at", now)
    db.touch(lot)

    receipts = [
        r
        for r in db.rows("raw_receipts")
        if r["grower_lot_id"] == lot["id"]
        and r["status"] in ("PENDING_INSPECTION", "ACCEPTED")
    ]
    quarantined = []
    for receipt in sorted(receipts, key=_receipt_order):
        receipt["status"] = "QUARANTINED"
        db.touch(receipt)
        quarantined.append(receipt)

    roots = []
    for receipt in quarantined:
        for run in _runs_consuming_receipt(receipt["id"]):
            if run not in roots:
                roots.append(run)

    held = _hold_runs(roots, "RECALL", now)
    descendants = _rework_descendants(roots)
    held = held + _hold_runs(descendants, "RECALL", now)
    for run in held:
        for consumed_lot in lots.lots_consumed_by_run(run["id"]):
            lots.recompute_trailing(consumed_lot)
    return lot
