"""Promotional campaign versioning (PRD 3.7)."""
from flask import Blueprint

import auth
import constants as C
import derive
import logical_clock as clockmod
import response
import serialize
import shapes
from db import DB, append_audit, new_row, ordered
from errors import fail
from routes.common import fk, listing, path_row

bp = Blueprint("campaigns", __name__)

VERBS = ("SCHEDULE", "WITHDRAW")


@bp.post("/campaign-versions")
def draft_version():
    auth.enter(["ContentManager"])
    data = shapes.body()
    cluster_id = fk(data, "cluster_id", "clusters")
    code = shapes.req_str(data, "campaign_code", 1, 24)
    version_no = shapes.req_int(data, "version_no", 1, None)
    if cluster_id is None:
        shapes.req_str(data, "cluster_id", 1, None)
    kind = shapes.req_enum(data, "discount_kind", C.DISCOUNT_KINDS)
    value = shapes.req_int(data, "discount_value", 1, 10000 if kind == "PERCENT_OFF" else None)
    start = shapes.req_instant(data, "window_start_utc")
    end = shapes.req_instant(data, "window_end_utc")
    group = shapes.req_str(data, "stacking_group", 1, 24)
    rank = shapes.req_int(data, "priority_rank", 1, 999)
    for row in DB.campaigns.values():
        if row.get("campaign_code") == code and row.get("version_no") == version_no:
            fail("ERR_DUPLICATE_NATURAL_KEY", "this version_no already exists for the campaign")
    if end <= start:
        fail("ERR_CAMPAIGN_WINDOW_EXPIRED", "window_end_utc must be after window_start_utc")
    if end <= clockmod.now():
        fail("ERR_CAMPAIGN_WINDOW_EXPIRED", "window_end_utc is at or before the clock")
    row = new_row({
        "campaign_code": code,
        "version_no": version_no,
        "cluster_id": cluster_id,
        "discount_kind": kind,
        "discount_value": value,
        "window_start_utc": clockmod.iso(start),
        "window_end_utc": clockmod.iso(end),
        "stacking_group": group,
        "priority_rank": rank,
        "state": "DRAFT",
        "pinned_bundle_version": None,
    })
    DB.campaigns[row["id"]] = row
    return response.created(serialize.dump("campaign", row))


@bp.get("/campaign-versions")
def list_versions():
    auth.enter(auth.ALL_READ_ROLES)
    return listing("campaigns", "campaign")


@bp.get("/campaign-versions/<version_id>")
def get_version(version_id):
    auth.enter(auth.ALL_READ_ROLES)
    row = path_row("campaigns", version_id)
    derive.advance_campaign(row)
    return response.ok(serialize.dump("campaign", row))


def _windows_intersect(start_a, end_a, start_b, end_b):
    """Both windows are closed on both ends."""
    return start_a <= end_b and start_b <= end_a


@bp.post("/campaign-versions/<version_id>/actions")
def drive_version(version_id):
    ctx = auth.enter(["ContentManager", "PlatformAdmin"])
    row = path_row("campaigns", version_id)
    data = shapes.body()
    action = shapes.req_enum(data, "action", VERBS)
    if row["state"] in C.CAMPAIGN_TERMINAL:
        fail("ERR_ALREADY_TERMINAL", "the campaign version is already terminal")
    cluster = DB.clusters.get(row.get("cluster_id"))

    if action == "SCHEDULE":
        if row["state"] != "DRAFT":
            fail("ERR_INVALID_STATE_TRANSITION", "SCHEDULE is not declared out of %s" % row["state"])
        if cluster is None or int(cluster.get("published_bundle_version") or 0) < 1:
            fail("ERR_INVALID_STATE_TRANSITION", "the cluster has published no content")
        start = clockmod.parse_instant(row["window_start_utc"])
        end = clockmod.parse_instant(row["window_end_utc"])
        for other in ordered(list(DB.campaigns.values())):
            if other["id"] == row["id"]:
                continue
            if other.get("cluster_id") != row.get("cluster_id"):
                continue
            if other.get("stacking_group") != row.get("stacking_group"):
                continue
            if other.get("state") not in ("SCHEDULED", "ACTIVE"):
                continue
            other_start = clockmod.parse_instant(other["window_start_utc"])
            other_end = clockmod.parse_instant(other["window_end_utc"])
            if _windows_intersect(start, end, other_start, other_end):
                fail("ERR_CAMPAIGN_WINDOW_CONFLICT",
                     "another live version of this stacking group occupies this window")
        if end < clockmod.now():
            fail("ERR_CAMPAIGN_WINDOW_EXPIRED", "window_end_utc is before the clock")
        derive.apply_changes(row, {
            "state": "SCHEDULED",
            "pinned_bundle_version": int(cluster.get("published_bundle_version") or 0),
        })
        append_audit("CAMPAIGN_VERSION", row["id"], "CAMPAIGN_SCHEDULED", ctx["role"],
                     ctx["user_id"], detail="WINDOW_SCHEDULED")
        for other in ordered(list(DB.campaigns.values())):
            if other["id"] == row["id"] or other.get("campaign_code") != row.get("campaign_code"):
                continue
            if int(other.get("version_no")) >= int(row.get("version_no")):
                continue
            if other.get("state") not in ("SCHEDULED", "ACTIVE"):
                continue
            derive.apply_changes(other, {"state": "SUPERSEDED"})
            append_audit("CAMPAIGN_VERSION", other["id"], "CAMPAIGN_SUPERSEDED",
                         derive.SYSTEM_ROLE, None, detail="HIGHER_VERSION_SCHEDULED")
        derive.advance_campaign(row)

    else:  # WITHDRAW
        if row["state"] not in ("DRAFT", "SCHEDULED", "ACTIVE"):
            fail("ERR_INVALID_STATE_TRANSITION", "WITHDRAW is not declared out of %s" % row["state"])
        derive.apply_changes(row, {"state": "WITHDRAWN"})
        append_audit("CAMPAIGN_VERSION", row["id"], "CAMPAIGN_WITHDRAWN", ctx["role"],
                     ctx["user_id"], detail="VERSION_WITHDRAWN")

    return response.ok(serialize.dump("campaign", row))
