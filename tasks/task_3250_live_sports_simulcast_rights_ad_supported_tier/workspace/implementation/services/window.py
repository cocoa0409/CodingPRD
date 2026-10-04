"""StreamingWindow lifecycle: create/supersede, go-live, complete, cancel."""
from datetime import timedelta

import clock
import util
from db import db
from errors import (
    raise_err, ERR_INVALID_STATE, ERR_INVALID_REQUEST, ERR_NOT_FOUND,
    ERR_STALE_VERSION, ERR_WINDOW_OUTSIDE_TERM, ERR_WINDOW_QUOTA_EXCEEDED,
    ERR_EXCLUSIVE_RATIO_BREACH, ERR_GOLIVE_GATE_FAILED,
)
from services import calc

RIGHTS_MODES = {"SIMULCAST", "EXCLUSIVE"}


def serialize(win):
    from serialize import serialize as _s
    return _s(win)


def _window_weight(win):
    return calc.EXCLUSIVE_WEIGHT if win["rights_mode"] == "EXCLUSIVE" else calc.SIMULCAST_WEIGHT


def consumed_counts(prop_id):
    sim = sum(1 for w in db.windows.values()
              if w["property_id"] == prop_id and w["rights_mode"] == "SIMULCAST"
              and w["status"] not in ("CANCELLED", "REPLACED"))
    exc = sum(1 for w in db.windows.values()
              if w["property_id"] == prop_id and w["rights_mode"] == "EXCLUSIVE"
              and w["status"] not in ("CANCELLED", "REPLACED"))
    return sim, exc


def create_window(body):
    util.require_fields(body, [
        "property_id", "event_code", "rights_mode", "scheduled_start",
        "scheduled_end", "territory_scope", "regional_block",
        "capacity_required_units", "replay_hours", "expected_property_version",
    ], allowed_extra=["is_marquee", "supersedes_id"])
    prop = db.properties.get(body["property_id"])
    if prop is None:
        raise_err(ERR_NOT_FOUND, "property not found")
    util.req_str(body["event_code"], "event_code")
    util.req_enum(body["rights_mode"], "rights_mode", RIGHTS_MODES)
    scheduled_start = util.req_dt(body["scheduled_start"], "scheduled_start")
    scheduled_end = util.req_dt(body["scheduled_end"], "scheduled_end")
    if not scheduled_end > scheduled_start:
        raise_err(ERR_INVALID_REQUEST, "scheduled_end must be strictly after scheduled_start")
    territory_scope = util.req_str_list(body["territory_scope"], "territory_scope")
    regional_block = util.req_bool(body["regional_block"], "regional_block")
    capacity_required = util.req_int(body["capacity_required_units"], "capacity_required_units", minimum=1)
    replay_hours = util.req_int(body["replay_hours"], "replay_hours")
    is_marquee = body.get("is_marquee", False)
    if not isinstance(is_marquee, bool):
        raise_err(ERR_INVALID_REQUEST, "is_marquee must be a boolean")
    expected_version = body["expected_property_version"]
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise_err(ERR_INVALID_REQUEST, "expected_property_version must be an integer")
    supersedes_id = body.get("supersedes_id")
    old = None
    if supersedes_id is not None:
        old = db.windows.get(supersedes_id)
        if old is None:
            raise_err(ERR_NOT_FOUND, "supersedes_id window not found")

    # OCC check (priority 5)
    if expected_version != prop["version"]:
        raise_err(ERR_STALE_VERSION, "stale property version")

    # Supersede state check
    if old is not None and old["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "superseded window must be SCHEDULED")

    # Window term / replay hours check (priority 7)
    if replay_hours < 0:
        raise_err(ERR_WINDOW_OUTSIDE_TERM, "replay_hours must be >= 0")
    if not (prop["term_start"] <= scheduled_start and scheduled_end <= prop["term_end"]):
        raise_err(ERR_WINDOW_OUTSIDE_TERM, "window schedule outside property term")

    # event_code uniqueness within property
    for w in db.windows.values():
        if w["property_id"] == prop["id"] and w["event_code"] == body["event_code"] \
                and w["status"] not in ("CANCELLED", "REPLACED"):
            raise_err(ERR_INVALID_REQUEST, "event_code already used within property")

    # Quota check (priority 10)
    sim, exc = consumed_counts(prop["id"])
    if body["rights_mode"] == "SIMULCAST" and sim >= prop["simulcast_windows_count"]:
        raise_err(ERR_WINDOW_QUOTA_EXCEEDED, "simulcast window quota exhausted")
    if body["rights_mode"] == "EXCLUSIVE" and exc >= prop["exclusive_windows_count"]:
        raise_err(ERR_WINDOW_QUOTA_EXCEEDED, "exclusive window quota exhausted")

    # Exclusive-ratio gate (priority 11), SIMULCAST only
    if body["rights_mode"] == "SIMULCAST":
        new_sim = sim + 1
        total = new_sim + exc
        ratio = (100 * exc) // max(total, 1)
        if ratio < prop["minimum_exclusive_ratio_pct"]:
            raise_err(ERR_EXCLUSIVE_RATIO_BREACH, "exclusive ratio would fall below minimum")

    now_iso = clock.now_iso()
    win = {
        "id": util.new_id(),
        "property_id": prop["id"],
        "event_code": body["event_code"],
        "rights_mode": body["rights_mode"],
        "status": "SCHEDULED",
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "live_start": None,
        "territory_scope": territory_scope,
        "regional_block": regional_block,
        "is_marquee": is_marquee,
        "capacity_required_units": capacity_required,
        "replay_hours": replay_hours,
        "replaced_by_id": None,
        "supersedes_id": supersedes_id,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    db.windows[win["id"]] = win
    if old is not None:
        old["replaced_by_id"] = win["id"]
        _cancel_internals(old, to_status="REPLACED")
    util.touch(prop)
    return win


def _cancel_internals(win, to_status="CANCELLED"):
    """Shared cascade for cancel/supersede: slots cancelled, reservations released."""
    for slot in db.ad_slots.values():
        if slot["window_id"] == win["id"] and slot["status"] in ("OPEN", "RESERVED"):
            slot["status"] = "CANCELLED"
            slot["booked_campaign_id"] = None
            util.touch(slot)
    for res in db.capacity_reservations.values():
        if res["window_id"] == win["id"] and res["status"] in ("HELD", "CONFIRMED"):
            res["status"] = "RELEASED"
            util.touch(res)
            pool = db.capacity_pools.get(res["pool_id"])
            if pool is not None:
                pool["committed_units"] = pool.get("committed_units", 0) - res["units"]
                util.touch(pool)
    win["status"] = to_status
    util.touch(win)


def cancel_window(win):
    _cancel_internals(win, to_status="CANCELLED")
    return win


def cancel_window_endpoint(win):
    if win["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "window not SCHEDULED")
    return cancel_window(win)


def go_live(win):
    if win["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "window not SCHEDULED")
    prop = db.properties.get(win["property_id"])
    if prop is None or prop["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "owning property not ACTIVE")
    now = clock.now()
    confirmed = sum(
        r["units"] for r in db.capacity_reservations.values()
        if r["window_id"] == win["id"] and r["status"] == "CONFIRMED"
    )
    if confirmed < win["capacity_required_units"]:
        raise_err(ERR_GOLIVE_GATE_FAILED, "capacity gate failed")
    local_filled = sum(
        1 for s in db.ad_slots.values()
        if s["window_id"] == win["id"] and s["slot_scope"] == "LOCAL" and s["status"] == "FILLED"
    )
    if local_filled < prop["required_local_breaks_per_event"]:
        raise_err(ERR_GOLIVE_GATE_FAILED, "local break gate failed")
    if not win["regional_block"]:
        for rule in db.territory_rules.values():
            if (rule["window_id"] == win["id"] and rule["rule_status"] == "ACTIVE"
                    and rule["rule_kind"] == "BLACKOUT"
                    and rule["region_code"] in win["territory_scope"]
                    and rule["effective_start"] <= now < rule["effective_end"]):
                raise_err(ERR_GOLIVE_GATE_FAILED, "active blackout in territory scope")
    # Sweep expired HELD reservations for this window
    for res in db.capacity_reservations.values():
        if res["window_id"] == win["id"] and res["status"] == "HELD" and now >= res["hold_expires_at"]:
            res["status"] = "EXPIRED"
            util.touch(res)
            pool = db.capacity_pools.get(res["pool_id"])
            if pool is not None:
                pool["committed_units"] = pool.get("committed_units", 0) - res["units"]
                util.touch(pool)
    win["status"] = "LIVE"
    win["live_start"] = now
    util.touch(win)
    return win


def complete_window(win):
    if win["status"] != "LIVE":
        raise_err(ERR_INVALID_STATE, "window not LIVE")
    now = clock.now()
    win["status"] = "COMPLETE"
    util.touch(win)
    # Create ReplayAsset
    now_iso = clock.now_iso()
    asset = {
        "id": util.new_id(),
        "window_id": win["id"],
        "status": "AVAILABLE",
        "available_from": now,
        "expires_at": now + timedelta(hours=win["replay_hours"]),
        "replay_views": 0,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    db.replay_assets[asset["id"]] = asset
    # Release CONFIRMED reservations
    for res in db.capacity_reservations.values():
        if res["window_id"] == win["id"] and res["status"] == "CONFIRMED":
            res["status"] = "RELEASED"
            util.touch(res)
            pool = db.capacity_pools.get(res["pool_id"])
            if pool is not None:
                pool["committed_units"] = pool.get("committed_units", 0) - res["units"]
                util.touch(pool)
    prop = db.properties.get(win["property_id"])
    if prop is not None:
        calc.recompute_amortization(prop)
    return win
