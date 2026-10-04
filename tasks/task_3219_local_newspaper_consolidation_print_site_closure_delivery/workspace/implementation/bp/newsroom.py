"""Newsroom positions and changes, and title closures with archive continuity."""
from flask import Blueprint, request

from core import DB, fail
from helpers import ok_list, ok_object, create, sort_by_created
from guards import body, identity, path_one, require_row
from models import touch, bump
import calcs as C
import recompute as R
import logical_time as T

bp = Blueprint("newsroom", __name__)

READ_NEWS = ["NewsroomOperationsManager", "Auditor", "PlatformAdmin"]
READ_TITLE = ["PrintOperationsDirector", "Auditor", "PlatformAdmin"]


# --------------------------------------------------------------------------
# NewsroomPosition
# --------------------------------------------------------------------------
@bp.post("/regional-news-ops/regions/<region_id>/newsroom-positions")
def create_position(region_id):
    data = body()
    identity(["NewsroomOperationsManager"])
    region = path_one("regions", region_id)
    position = create("newsroom_positions", data,
                      ["role_code", "expertise_code", "monthly_cost_cents"],
                      system={"region_id": region["id"]})
    if int(position.get("monthly_cost_cents") or 0) < 1:
        DB.col("newsroom_positions").pop(position["id"], None)
        fail("ERR_INVALID_REQUEST", "monthly_cost_cents must be at least 1.")
    position["status"] = "open"
    position["allocated_headcount"] = 0
    return ok_object(position, 201)


@bp.get("/regional-news-ops/regions/<region_id>/newsroom-positions")
def list_positions(region_id):
    identity(READ_NEWS)
    region = path_one("regions", region_id)
    rows = [p for p in DB.all("newsroom_positions") if p.get("region_id") == region["id"]]
    return ok_list(sort_by_created(rows), None, None)


@bp.get("/regional-news-ops/newsroom-positions/<position_id>")
def get_position(position_id):
    identity(READ_NEWS)
    return ok_object(path_one("newsroom_positions", position_id))


# --------------------------------------------------------------------------
# NewsroomChange
# --------------------------------------------------------------------------
@bp.post("/regional-news-ops/newsroom-changes")
def create_change():
    data = body()
    role, uid = identity(["NewsroomOperationsManager"])
    position = require_row("newsroom_positions", data.get("newsroom_position_id"))
    to_region = require_row("regions", data.get("to_region_id"))
    from_region = require_row("regions", data.get("from_region_id"))
    hub = DB.get("region_hubs", to_region.get("region_hub_id"))
    if hub is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    if "expected_hub_version" not in data or data["expected_hub_version"] is None:
        fail("ERR_INVALID_REQUEST", "expected_hub_version is required.")
    if int(data["expected_hub_version"]) != int(hub.get("version") or 1):
        fail("ERR_STALE_VERSION")
    if data.get("effective_date") is None:
        fail("ERR_INVALID_REQUEST", "effective_date is required.")
    T.require_future_date(data["effective_date"], "ERR_EFFECTIVE_DATE_NOT_FUTURE")
    if int(data.get("requested_slots") or 0) < 1:
        fail("ERR_INVALID_REQUEST", "requested_slots must be at least 1.")
    change = create("newsroom_changes", data,
                    ["newsroom_position_id", "to_region_id", "from_region_id",
                     "effective_date", "layoff_order_index", "requested_slots"],
                    system={"newsroom_position_id": position["id"],
                            "to_region_id": to_region["id"],
                            "from_region_id": from_region["id"]},
                    extra_allowed=("expected_hub_version",))
    change["created_by"] = uid
    change["status"] = "proposed"
    change["allocated_slots"] = 0
    change["residual_headcount"] = 0
    change["severance_cost_cents"] = 0
    C.residual_pass(hub)
    bump(hub)
    return ok_object(change, 201)


@bp.get("/regional-news-ops/newsroom-changes")
def list_changes():
    identity(READ_NEWS)
    rows = DB.all("newsroom_changes")
    to_region = request.args.get("to_region_id")
    from_region = request.args.get("from_region_id")
    if to_region:
        rows = [c for c in rows if c.get("to_region_id") == to_region]
    if from_region:
        rows = [c for c in rows if c.get("from_region_id") == from_region]
    return ok_list(sort_by_created(rows), request.args.get("limit"),
                   request.args.get("offset"))


@bp.get("/regional-news-ops/newsroom-changes/<change_id>")
def get_change(change_id):
    identity(READ_NEWS)
    return ok_object(path_one("newsroom_changes", change_id))


@bp.get("/regional-news-ops/newsroom-positions/<position_id>/newsroom-changes")
def position_changes(position_id):
    identity(READ_NEWS)
    position = path_one("newsroom_positions", position_id)
    rows = [c for c in DB.all("newsroom_changes")
            if c.get("newsroom_position_id") == position["id"]]
    return ok_list(sort_by_created(rows), None, None)


def _change_hub(change):
    position = DB.get("newsroom_positions", change.get("newsroom_position_id"))
    region = DB.get("regions", position.get("region_id")) if position else None
    return DB.get("region_hubs", region.get("region_hub_id")) if region else None


@bp.post("/regional-news-ops/newsroom-changes/<change_id>/approve")
def approve_change(change_id):
    data = body()
    role, uid = identity(["NewsroomOperationsManager"])
    if data:
        fail("ERR_INVALID_REQUEST", "This operation takes no body fields.")
    change = path_one("newsroom_changes", change_id)
    if change.get("status") != "proposed":
        fail("ERR_INVALID_STATE")
    if change.get("created_by") is not None and change.get("created_by") == uid:
        fail("ERR_SEGREGATION_OF_DUTIES")
    T.require_future_date(change.get("effective_date"), "ERR_EFFECTIVE_DATE_NOT_FUTURE")
    change["status"] = "approved"
    touch(change)
    return ok_object(change)


@bp.post("/regional-news-ops/newsroom-changes/<change_id>/apply")
def apply_change(change_id):
    data = body()
    identity(["NewsroomOperationsManager"])
    if data:
        fail("ERR_INVALID_REQUEST", "This operation takes no body fields.")
    change = path_one("newsroom_changes", change_id)
    if change.get("status") != "approved":
        fail("ERR_INVALID_STATE")
    effective = T.date_from_iso(change.get("effective_date"))
    if effective is None or T.today() < effective:
        fail("ERR_INVALID_STATE", "The effective date has not arrived.")
    hub = _change_hub(change)
    if hub is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    applied_positions = {c.get("newsroom_position_id") for c in DB.all("newsroom_changes")
                         if c.get("status") == "applied"}
    C.residual_pass(hub)
    position = DB.get("newsroom_positions", change.get("newsroom_position_id"))
    change["severance_cost_cents"] = C.severance_cost(change, position)
    for pid in applied_positions | {change.get("newsroom_position_id")}:
        R.recompute_position(DB.get("newsroom_positions", pid))
    for region in C.regions_of_hub(hub["id"]):
        C.recompute_region_allocated(region, hub)
    C.recompute_hub_allocation(hub)
    change["status"] = "applied"
    touch(change)
    return ok_object(change)


@bp.post("/regional-news-ops/newsroom-changes/<change_id>/reject")
def reject_change(change_id):
    data = body()
    identity(["NewsroomOperationsManager"])
    if data:
        fail("ERR_INVALID_REQUEST", "This operation takes no body fields.")
    change = path_one("newsroom_changes", change_id)
    if change.get("status") != "proposed":
        fail("ERR_INVALID_STATE")
    change["status"] = "rejected"
    touch(change)
    return ok_object(change)


@bp.post("/regional-news-ops/newsroom-changes/<change_id>/reopen")
def reopen_change(change_id):
    data = body()
    identity(["NewsroomOperationsManager"])
    if data:
        fail("ERR_INVALID_REQUEST", "This operation takes no body fields.")
    change = path_one("newsroom_changes", change_id)
    if change.get("status") != "approved":
        fail("ERR_INVALID_STATE")
    hub = _change_hub(change)
    C.residual_pass(hub)
    position = DB.get("newsroom_positions", change.get("newsroom_position_id"))
    change["severance_cost_cents"] = C.severance_cost(change, position)
    change["status"] = "proposed"
    touch(change)
    if hub is not None:
        bump(hub)
    return ok_object(change)


# --------------------------------------------------------------------------
# TitleClosure
# --------------------------------------------------------------------------
@bp.post("/regional-news-ops/region-hubs/<hub_id>/title-closures")
def create_title(hub_id):
    data = body()
    identity(["PrintOperationsDirector"])
    hub = path_one("region_hubs", hub_id)
    title = create("title_closures", data,
                   ["title_code", "archive_retention_years", "digital_replacement_url"],
                   system={"title_hub_id": hub["id"]})
    if int(title.get("archive_retention_years") or 0) < 1:
        DB.col("title_closures").pop(title["id"], None)
        fail("ERR_INVALID_REQUEST", "archive_retention_years must be at least 1.")
    if DB.duplicate("title_closures", title["id"], title_hub_id=hub["id"],
                 title_code=title["title_code"]):
        DB.col("title_closures").pop(title["id"], None)
        fail("ERR_DUPLICATE_HUB_CODE")
    title["status"] = "announced"
    return ok_object(title, 201)


@bp.get("/regional-news-ops/region-hubs/<hub_id>/title-closures")
def list_titles(hub_id):
    identity(READ_TITLE)
    hub = path_one("region_hubs", hub_id)
    rows = [t for t in DB.all("title_closures") if t.get("title_hub_id") == hub["id"]]
    return ok_list(sort_by_created(rows), None, None)


@bp.get("/regional-news-ops/title-closures/<title_id>")
def get_title(title_id):
    identity(READ_TITLE)
    return ok_object(path_one("title_closures", title_id))


@bp.post("/regional-news-ops/title-closures/<title_id>/publish-notice")
def publish_notice(title_id):
    data = body()
    identity(["PrintOperationsDirector"])
    if data:
        fail("ERR_INVALID_REQUEST", "This operation takes no body fields.")
    title = path_one("title_closures", title_id)
    hub = DB.get("region_hubs", title.get("title_hub_id"))
    if hub is not None and hub.get("legal_notice_block"):
        fail("ERR_LEGAL_NOTICE_HOLD")
    if title.get("status") != "announced":
        fail("ERR_INVALID_STATE")
    if int(title.get("archive_retention_years") or 0) < 1:
        fail("ERR_INVALID_STATE")
    if hub is not None:
        compliant, _, _ = C.legal_notice_verdict(hub)
        if not compliant:
            fail("ERR_LEGAL_NOTICE_HOLD")
    title["status"] = "notice_published"
    touch(title)
    return ok_object(title)


@bp.post("/regional-news-ops/title-closures/<title_id>/suspend")
def suspend_title(title_id):
    data = body()
    identity(["PrintOperationsDirector"])
    if data:
        fail("ERR_INVALID_REQUEST", "This operation takes no body fields.")
    title = path_one("title_closures", title_id)
    hub = DB.get("region_hubs", title.get("title_hub_id"))
    if title.get("status") != "notice_published":
        fail("ERR_INVALID_STATE")
    if hub is None or not hub.get("legal_notice_block"):
        fail("ERR_INVALID_STATE", "The hub is not under a legal-notice hold.")
    title["status"] = "suspended"
    touch(title)
    return ok_object(title)


@bp.post("/regional-news-ops/title-closures/<title_id>/resume")
def resume_title(title_id):
    data = body()
    identity(["PrintOperationsDirector"])
    if data:
        fail("ERR_INVALID_REQUEST", "This operation takes no body fields.")
    title = path_one("title_closures", title_id)
    hub = DB.get("region_hubs", title.get("title_hub_id"))
    if title.get("status") != "suspended":
        fail("ERR_INVALID_STATE")
    if hub is not None and hub.get("legal_notice_block"):
        fail("ERR_INVALID_STATE", "The hub is still under a legal-notice hold.")
    title["status"] = "notice_published"
    touch(title)
    return ok_object(title)


@bp.post("/regional-news-ops/title-closures/<title_id>/merge")
def merge_title(title_id):
    data = body()
    identity(["PrintOperationsDirector"])
    title = path_one("title_closures", title_id)
    if title.get("status") not in ("notice_published", "suspended"):
        fail("ERR_INVALID_STATE")
    if not str(title.get("digital_replacement_url") or ""):
        fail("ERR_INVALID_STATE")
    survivor = require_row("title_closures", data.get("survivor_title_id"))
    if survivor.get("title_hub_id") != title.get("title_hub_id"):
        fail("ERR_RESOURCE_NOT_FOUND")
    title["status"] = "merged"
    touch(title)
    if survivor.get("status") == "merged" and \
            survivor.get("digital_replacement_url") == title.get("digital_replacement_url"):
        survivor["archive_retention_years"] = max(
            int(survivor.get("archive_retention_years") or 0),
            int(title.get("archive_retention_years") or 0))
        touch(survivor)
    return ok_object(title)


@bp.post("/regional-news-ops/title-closures/<title_id>/archive")
def archive_title(title_id):
    data = body()
    identity(["PrintOperationsDirector"])
    if data:
        fail("ERR_INVALID_REQUEST", "This operation takes no body fields.")
    title = path_one("title_closures", title_id)
    if title.get("status") != "merged":
        fail("ERR_INVALID_STATE")
    survivor = None
    for other in DB.all("title_closures"):
        if other["id"] == title["id"]:
            continue
        if other.get("title_hub_id") == title.get("title_hub_id") and \
                other.get("status") == "merged" and \
                other.get("digital_replacement_url") == title.get("digital_replacement_url"):
            survivor = other
            break
    if survivor is None:
        for other in DB.all("title_closures"):
            if other["id"] != title["id"] and \
                    other.get("digital_replacement_url") == title.get(
                        "digital_replacement_url"):
                survivor = other
                break
    title["status"] = "archived"
    title["archive_handoff_checksum"] = survivor.get("archive_handoff_checksum") \
        if survivor else title.get("archive_handoff_checksum") or "checksum-" + title["id"][:8]
    touch(title)
    return ok_object(title)