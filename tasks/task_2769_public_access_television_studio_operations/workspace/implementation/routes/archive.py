"""Archive retention, on-demand distribution and community impact (PRD 3.9)."""

from flask import Blueprint

import calc
import constants as C
import db
import middleware
import support
import validation
from errors import ApiError, invalid_transition

bp = Blueprint("archive", __name__)

READ_ROLES = (
    C.ROLE_CENTER_ADMIN,
    C.ROLE_SCHEDULING_COORDINATOR,
    C.ROLE_CONTENT_REVIEWER,
    C.ROLE_PRODUCER,
)


@bp.get("/archive-assets/<asset_id>")
def read_asset(asset_id):
    middleware.authorize(*READ_ROLES)
    row = support.must_exist("archive_assets", asset_id)
    return support.single("archive_assets", row)


@bp.get("/archive-assets")
def list_assets():
    middleware.authorize(*READ_ROLES)
    program_id = validation.query_string("program_id")
    source_slot_id = validation.query_string("source_slot_id")
    on_demand_status = validation.query_enum("on_demand_status", C.ARCHIVE_STATUSES)
    retention_class = validation.query_enum("retention_class", C.RETENTION_CLASSES)
    validation.pagination()
    rows = support.filter_rows(
        "archive_assets",
        [
            ("program_id", program_id),
            ("source_slot_id", source_slot_id),
            ("on_demand_status", on_demand_status),
            ("retention_class", retention_class),
        ],
    )
    return support.collection_response("archive_assets", rows)


def _final_index(row):
    return calc.community_impact_index(
        row["measured_households"], row["on_demand_views"], row["volunteer_hours_tenths"], "FINAL"
    )


@bp.post("/archive-assets/<asset_id>/publish")
def publish_asset(asset_id):
    middleware.authorize(C.ROLE_CENTER_ADMIN)
    body = validation.body()
    retention_class = validation.req_enum(body, "retention_class", C.RETENTION_CLASSES)
    row = support.must_exist("archive_assets", asset_id)
    program = db.get("programs", row["program_id"])
    slot = db.get("playback_slots", row["source_slot_id"])
    # priority 9: all three preconditions are transition legality on this operation
    if row["on_demand_status"] != "PENDING":
        raise invalid_transition("Only a pending archive asset may be published")
    if program is None or program["review_status"] != "APPROVED":
        raise invalid_transition("The archived program is not approved")
    if slot is None or slot["status"] != "AIRED":
        raise invalid_transition("The source slot has not aired")
    instant = db.now()
    row["retention_class"] = retention_class
    row["published_at"] = instant
    row["retain_until"] = calc.retain_until(instant, retention_class)
    row["on_demand_status"] = "PUBLISHED"
    row["impact_variant"] = "FINAL"
    row["community_impact_index"] = _final_index(row)
    db.bump(row)
    return support.single("archive_assets", row)


@bp.post("/archive-assets/<asset_id>/record-views")
def record_views(asset_id):
    middleware.authorize(C.ROLE_CENTER_ADMIN)
    body = validation.body()
    on_demand_views = validation.req_int(body, "on_demand_views", minimum=0)
    row = support.must_exist("archive_assets", asset_id)
    # priority 9
    if row["on_demand_status"] != "PUBLISHED":
        raise invalid_transition("Only a published archive asset accepts view records")
    row["on_demand_views"] = on_demand_views
    row["impact_variant"] = "FINAL"
    row["community_impact_index"] = _final_index(row)
    db.bump(row)
    return support.single("archive_assets", row)


@bp.post("/archive-assets/<asset_id>/purge")
def purge_asset(asset_id):
    middleware.authorize(C.ROLE_CENTER_ADMIN)
    validation.body()
    row = support.must_exist("archive_assets", asset_id)
    # priority 9
    if row["on_demand_status"] not in ("PUBLISHED", "WITHDRAWN"):
        raise invalid_transition("Only a published or withdrawn archive asset may be purged")
    # priority 32
    if row["retention_class"] == "PERMANENT":
        raise ApiError("ERR_PERMANENT_RETENTION", "A permanently retained asset can never be purged")
    if row["retain_until"] is None or db.now() < row["retain_until"]:
        raise ApiError("ERR_RETENTION_NOT_ELAPSED", "The retention window has not elapsed")
    row["on_demand_status"] = "PURGED"
    row["purged_at"] = db.now()
    db.bump(row)
    return support.single("archive_assets", row)
