"""TerritoryRule lifecycle."""
from datetime import timedelta

import clock
import util
from db import db
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_RULE_WINDOW_INVALID, ERR_BLACKOUT_OVERLAP, ERR_INVALID_REQUEST,
)

RULE_KINDS = {"BLACKOUT", "OVERFLOW"}


def create_rule(body):
    util.require_fields(body, [
        "window_id", "region_code", "rule_kind",
        "effective_start", "effective_end", "broadcast_obligation_ref",
    ])
    win = db.windows.get(body["window_id"])
    if win is None:
        raise_err(ERR_NOT_FOUND, "window not found")
    util.req_str(body["region_code"], "region_code")
    util.req_enum(body["rule_kind"], "rule_kind", RULE_KINDS)
    start = util.req_dt(body["effective_start"], "effective_start")
    end = util.req_dt(body["effective_end"], "effective_end")
    util.req_str(body["broadcast_obligation_ref"], "broadcast_obligation_ref")

    if not end > start:
        raise_err(ERR_RULE_WINDOW_INVALID, "effective_end must be strictly after effective_start")
    if start < win["scheduled_start"] - timedelta(hours=24):
        raise_err(ERR_RULE_WINDOW_INVALID, "effective_start before window scheduled_start - 24h")

    if body["rule_kind"] == "BLACKOUT":
        for rule in db.territory_rules.values():
            if (rule["window_id"] == win["id"] and rule["region_code"] == body["region_code"]
                    and rule["rule_kind"] == "BLACKOUT" and rule["rule_status"] == "ACTIVE"):
                if start < rule["effective_end"] and rule["effective_start"] < end:
                    raise_err(ERR_BLACKOUT_OVERLAP, "blackout overlaps existing ACTIVE blackout")

    now_iso = clock.now_iso()
    rule = {
        "id": util.new_id(),
        "window_id": win["id"],
        "region_code": body["region_code"],
        "rule_kind": body["rule_kind"],
        "rule_status": "ACTIVE",
        "effective_start": start,
        "effective_end": end,
        "broadcast_obligation_ref": body["broadcast_obligation_ref"],
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    db.territory_rules[rule["id"]] = rule
    return rule


def lift_rule(rule):
    if rule["rule_status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "rule not ACTIVE")
    win = db.windows.get(rule["window_id"])
    if win is None or win["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "window is not SCHEDULED; obligations locked")
    rule["rule_status"] = "LIFTED"
    util.touch(rule)
    return rule
