"""AdSlot lifecycle: create, fill (two legs), release, mark-unfillable, serve, pods."""
import clock
import util
from db import db
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND,
    ERR_STALE_VERSION, ERR_POD_INFEASIBLE, ERR_FREQUENCY_CAP_EXCEEDED,
)
from services import calc

DURATIONS = {15, 30, 60}
SCOPES = {"NATIONAL", "LOCAL"}
POD_SECONDS = 120


def create_slot(body):
    util.require_fields(body, ["window_id", "break_index", "pod_index",
                               "duration_seconds", "slot_scope"],
                        allowed_extra=["region_code"])
    win = db.windows.get(body["window_id"])
    if win is None:
        raise_err(ERR_NOT_FOUND, "window not found")
    break_index = util.req_int(body["break_index"], "break_index", minimum=1)
    pod_index = util.req_int(body["pod_index"], "pod_index", minimum=1)
    duration = util.req_int(body["duration_seconds"], "duration_seconds", allowed=DURATIONS)
    util.req_enum(body["slot_scope"], "slot_scope", SCOPES)
    region_code = body.get("region_code")
    if body["slot_scope"] == "LOCAL":
        if not isinstance(region_code, str) or not region_code:
            raise_err(ERR_INVALID_REQUEST, "region_code required for LOCAL slot")
    else:
        region_code = None
    now_iso = clock.now_iso()
    slot = {
        "id": util.new_id(),
        "window_id": win["id"],
        "break_index": break_index,
        "pod_index": pod_index,
        "duration_seconds": duration,
        "slot_scope": body["slot_scope"],
        "region_code": region_code,
        "booked_campaign_id": None,
        "status": "OPEN",
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    db.ad_slots[slot["id"]] = slot
    return slot


def fill_slot(slot, body):
    util.require_fields(body, ["campaign_id", "expected_window_version"])
    win = db.windows.get(slot["window_id"])
    camp = db.ad_campaigns.get(body["campaign_id"])
    if camp is None:
        raise_err(ERR_NOT_FOUND, "campaign not found")
    expected = body["expected_window_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(ERR_INVALID_REQUEST, "expected_window_version must be an integer")
    if expected != win["version"]:
        raise_err(ERR_STALE_VERSION, "stale window version")

    if slot["status"] == "OPEN":
        # reservation leg
        if win["status"] not in ("SCHEDULED", "LIVE"):
            raise_err(ERR_INVALID_STATE, "window not SCHEDULED or LIVE")
        if camp["campaign_status"] != "BOOKED":
            raise_err(ERR_INVALID_STATE, "campaign not BOOKED")
        if slot["slot_scope"] == "LOCAL" and slot["region_code"] not in camp["region_target"]:
            raise_err(ERR_POD_INFEASIBLE, "campaign region_target does not include slot region")
        _check_pod_feasibility(slot)
        slot["status"] = "RESERVED"
        slot["booked_campaign_id"] = camp["id"]
        util.touch(slot)
        util.touch(win)
        return slot
    if slot["status"] == "RESERVED":
        # confirmation leg; idempotent on same campaign
        if slot["booked_campaign_id"] != camp["id"]:
            raise_err(ERR_INVALID_STATE, "booked_campaign_id changed")
        slot["status"] = "FILLED"
        util.touch(slot)
        util.touch(win)
        return slot
    raise_err(ERR_INVALID_STATE, "slot not fillable from current state")


def _check_pod_feasibility(slot):
    """If any slot of the break is UNFILLABLE and remaining OPEN slots (minus this one)
    cannot sum to 120 with {15,30,60} pieces, the break is infeasible."""
    siblings = [s for s in db.ad_slots.values()
                if s["window_id"] == slot["window_id"] and s["break_index"] == slot["break_index"]]
    open_durations = sorted(
        (s["duration_seconds"] for s in siblings if s["status"] == "OPEN" and s["id"] != slot["id"]),
        reverse=True,
    )
    has_unfillable = any(s["status"] == "UNFILLABLE" for s in siblings)
    if not has_unfillable:
        return
    filled = sum(s["duration_seconds"] for s in siblings if s["status"] == "FILLED")
    remaining = POD_SECONDS - filled - slot["duration_seconds"]
    if not _subset_sum_possible(open_durations, remaining):
        raise_err(ERR_POD_INFEASIBLE, "break cannot reach 120 seconds")


def _subset_sum_possible(durations, target):
    if target < 0:
        return False
    if target == 0:
        return True
    reachable = {0}
    for d in durations:
        reachable |= {r + d for r in list(reachable) if r + d <= target}
    return target in reachable


def release_slot(slot):
    if slot["status"] != "RESERVED":
        raise_err(ERR_INVALID_STATE, "slot not RESERVED")
    slot["status"] = "OPEN"
    slot["booked_campaign_id"] = None
    util.touch(slot)
    return slot


def mark_unfillable(slot):
    if slot["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "slot not OPEN")
    win = db.windows.get(slot["window_id"])
    if win is None or win["status"] not in ("SCHEDULED", "LIVE"):
        raise_err(ERR_INVALID_STATE, "window not SCHEDULED or LIVE")
    slot["status"] = "UNFILLABLE"
    util.touch(slot)
    return slot


def serve(slot, body):
    util.require_fields(body, ["viewer_id"])
    viewer = db.viewers.get(body["viewer_id"])
    if viewer is None:
        raise_err(ERR_NOT_FOUND, "viewer not found")
    if slot["status"] != "FILLED" or slot["booked_campaign_id"] is None:
        raise_err(ERR_INVALID_STATE, "slot not FILLED")
    camp = db.ad_campaigns.get(slot["booked_campaign_id"])
    if camp is None:
        raise_err(ERR_NOT_FOUND, "campaign not found")
    if not calc.frequency_cap_ok(camp, viewer["id"]):
        raise_err(ERR_FREQUENCY_CAP_EXCEEDED, "frequency cap reached for viewer")
    win = db.windows.get(slot["window_id"])
    now = clock.now()
    imp = {
        "id": util.new_id(),
        "campaign_id": camp["id"],
        "viewer_id": viewer["id"],
        "slot_id": slot["id"],
        "served_at": now,
        "revenue_cents": calc.revenue_cents(camp, slot, win),
        "fill_source": "NATIONAL" if slot["slot_scope"] == "NATIONAL" else "LOCAL_INSERTION",
        "created_at": clock.now_iso(),
    }
    db.impressions[imp["id"]] = imp
    return imp


def pod_summary(win):
    breaks = {}
    for slot in db.ad_slots.values():
        if slot["window_id"] != win["id"]:
            continue
        breaks.setdefault(slot["break_index"], []).append(slot)
    out_breaks = []
    total_open = 0
    total_filled = 0
    for b in sorted(breaks.keys()):
        slots = sorted(breaks[b], key=lambda s: (s["pod_index"], s["created_at"]))
        open_secs = sum(s["duration_seconds"] for s in slots if s["status"] == "OPEN")
        filled_secs = sum(s["duration_seconds"] for s in slots if s["status"] in ("RESERVED", "FILLED"))
        total_open += open_secs
        total_filled += filled_secs
        out_breaks.append({
            "break_index": b,
            "slots": slots,
            "open_seconds": open_secs,
            "filled_seconds": filled_secs,
            "unfillable": any(s["status"] == "UNFILLABLE" for s in slots),
        })
    return {"breaks": out_breaks, "total_open_seconds": total_open,
            "total_filled_seconds": total_filled}
