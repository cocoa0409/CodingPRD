"""Derived / computed field helpers.

Every conserved quantity is recomputed from scratch from the surviving rows so
that no incremental drift is possible.
"""

from consts import (
    ELEVATED_OOS_LANE_THRESHOLD,
    MAX_CONSECUTIVE_ON_POSITION_MINUTES,
    REQUIRED_EQUIPMENT_BY_LANE_TYPE,
    SURGE_OPEN_ESCALATION_THRESHOLD,
)
from util import whole_minutes
import store

_STATE_RANK = {"SERVICEABLE": 0, "DEGRADED": 1, "OUT_OF_SERVICE": 2}
_RANK_STATE = {0: "SERVICEABLE", 1: "DEGRADED", 2: "OUT_OF_SERVICE"}


def lane_units(lane_id):
    return [u for u in store.rows("equipment_units") if u["lane_id"] == lane_id]


def lane_equipment_state(lane):
    required = REQUIRED_EQUIPMENT_BY_LANE_TYPE[lane["lane_type"]]
    units = lane_units(lane["id"])
    worst = 0
    for kind in required:
        matching = [u for u in units if u["equipment_type"] == kind]
        if not matching:
            return "OUT_OF_SERVICE"
        best = min(_STATE_RANK[u["state"]] for u in matching)
        if best > worst:
            worst = best
    return _RANK_STATE[worst]


def required_units(lane):
    """The units that satisfy the lane's required equipment types."""
    required = REQUIRED_EQUIPMENT_BY_LANE_TYPE[lane["lane_type"]]
    return [u for u in lane_units(lane["id"]) if u["equipment_type"] in required]


def lane_has_advanced_imaging(lane):
    return any(u["equipment_type"] == "ADVANCED_IMAGING" for u in lane_units(lane["id"]))


def checkpoint_lanes(checkpoint_id):
    return [l for l in store.rows("lanes") if l["checkpoint_id"] == checkpoint_id]


def open_lane_count(checkpoint_id):
    return len([l for l in checkpoint_lanes(checkpoint_id) if l["lane_state"] == "OPEN"])


def available_lane_positions(cp):
    used = sum(
        l["required_officer_count"]
        for l in checkpoint_lanes(cp["id"])
        if l["lane_state"] == "OPEN"
    )
    return cp["total_lane_positions"] - used


def open_escalation_count(checkpoint_id):
    return len(
        [
            t
            for t in store.rows("escalation_tickets")
            if t["checkpoint_id"] == checkpoint_id and t["state"] in ("RAISED", "ACKNOWLEDGED")
        ]
    )


def oos_lane_count(checkpoint_id):
    n = 0
    for lane in checkpoint_lanes(checkpoint_id):
        if lane["lane_state"] == "DECOMMISSIONED":
            continue
        if lane_equipment_state(lane) == "OUT_OF_SERVICE":
            n += 1
    return n


def checkpoint_referrals(checkpoint_id):
    lane_ids = {l["id"] for l in checkpoint_lanes(checkpoint_id)}
    return [r for r in store.rows("screening_referrals") if r["lane_id"] in lane_ids]


def secondary_slots_in_use(checkpoint_id):
    return len(
        [
            r
            for r in checkpoint_referrals(checkpoint_id)
            if r["state"] in ("RAISED", "IN_PROGRESS")
        ]
    )


def posture(cp):
    if cp["suspended"]:
        return "SUSPENDED"
    escalations = open_escalation_count(cp["id"])
    if escalations >= SURGE_OPEN_ESCALATION_THRESHOLD:
        return "SURGE"
    if escalations == 1 or oos_lane_count(cp["id"]) >= ELEVATED_OOS_LANE_THRESHOLD:
        return "ELEVATED"
    return "NORMAL"


def refresh_checkpoint(cp):
    cp["available_lane_positions"] = available_lane_positions(cp)
    cp["open_lane_count"] = open_lane_count(cp["id"])
    cp["secondary_slots_in_use"] = secondary_slots_in_use(cp["id"])
    cp["posture"] = posture(cp)
    return cp


def officer_assignments(officer_id):
    return [a for a in store.rows("lane_assignments") if a["officer_id"] == officer_id]


def officer_details(officer_id):
    return [d for d in store.rows("surge_details") if d["officer_id"] == officer_id]


def approved_detail_minutes(officer_id):
    return sum(
        d["detail_minutes"] for d in officer_details(officer_id) if d["state"] == "APPROVED"
    )


def committed_duty_minutes(officer_id):
    total = sum(
        a["planned_minutes"]
        for a in officer_assignments(officer_id)
        if a["assignment_state"] in ("SCHEDULED", "CHECKED_IN", "REASSIGN_PENDING")
    )
    return total + approved_detail_minutes(officer_id)


def refresh_officer(officer):
    officer["approved_detail_minutes"] = approved_detail_minutes(officer["id"])
    officer["committed_duty_minutes"] = committed_duty_minutes(officer["id"])
    return officer


def refresh_officer_by_id(officer_id):
    officer = store.get("officers", officer_id)
    if officer is not None:
        refresh_officer(officer)
    return officer


def actual_minutes(assignment):
    if assignment["assignment_state"] in ("SCHEDULED", "CANCELLED"):
        return None
    if assignment["checked_in_at_utc"] is None:
        return None
    end = assignment["released_at_utc"] or store.now()
    elapsed = whole_minutes(assignment["checked_in_at_utc"], end)
    return max(0, elapsed) - assignment["break_minutes_taken"]


def evaluate_break_due(assignment):
    """System rule NOT_DUE/COMPLETED -> DUE.  Never bumps version."""
    if assignment["assignment_state"] not in ("CHECKED_IN", "REASSIGN_PENDING"):
        return
    if assignment["break_state"] not in ("NOT_DUE", "COMPLETED"):
        return
    baseline = assignment["break_baseline_utc"]
    if baseline is None:
        return
    if whole_minutes(baseline, store.now()) >= MAX_CONSECUTIVE_ON_POSITION_MINUTES:
        assignment["break_state"] = "DUE"


def evaluate_all_breaks():
    for assignment in store.rows("lane_assignments"):
        evaluate_break_due(assignment)
