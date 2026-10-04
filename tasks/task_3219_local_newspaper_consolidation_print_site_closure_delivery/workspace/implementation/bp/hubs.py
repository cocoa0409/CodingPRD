"""Region hub and region endpoints."""
from flask import Blueprint, request

from core import DB, fail
from helpers import ok_list, ok_object, create, sort_by_created
from guards import body, identity, path_one, query_pagination
import calcs as C
import recompute as R

bp = Blueprint("hubs", __name__)

READ_HUB = ["PrintOperationsDirector", "NewsroomOperationsManager",
            "DeliveryNetworkManager", "CustomerService", "Auditor", "PlatformAdmin"]
READ_REGION = ["PrintOperationsDirector", "NewsroomOperationsManager", "Auditor",
               "PlatformAdmin"]


def region_payload(region):
    return region


@bp.post("/regional-news-ops/region-hubs")
def create_hub():
    data = body()
    identity(["PlatformAdmin"])
    hub = create("region_hubs", data,
                 ["name", "total_newsroom_headcount", "max_print_tonnage_budget_cents",
                  "transfer_cost_ceiling_cents"])
    if int(hub["total_newsroom_headcount"]) < 1:
        fail("ERR_INVALID_REQUEST", "total_newsroom_headcount must be at least 1.")
    if int(hub["max_print_tonnage_budget_cents"]) < 1:
        fail("ERR_INVALID_REQUEST", "max_print_tonnage_budget_cents must be at least 1.")
    if int(hub["transfer_cost_ceiling_cents"]) < 1:
        fail("ERR_INVALID_REQUEST", "transfer_cost_ceiling_cents must be at least 1.")
    if not (1 <= int(hub["min_on_time_ratio_pct"]) <= 100):
        fail("ERR_INVALID_REQUEST", "min_on_time_ratio_pct must be between 1 and 100.")
    hub["press_posture"] = "OPEN"
    hub["legal_notice_block"] = False
    hub["unassigned_headcount"] = hub["total_newsroom_headcount"]
    return ok_object(hub, 201)


@bp.get("/regional-news-ops/region-hubs")
def list_hubs():
    identity(READ_HUB)
    limit, offset = query_pagination()
    return ok_list(sort_by_created(DB.all("region_hubs")), limit, offset)


@bp.get("/regional-news-ops/region-hubs/<hub_id>")
def get_hub(hub_id):
    identity(READ_HUB)
    hub = path_one("region_hubs", hub_id)
    C.refresh_legal_notice_block(hub)
    C.recompute_press_posture(hub)
    return ok_object(hub)


@bp.get("/regional-news-ops/region-hubs/<hub_id>/compliance")
def hub_compliance(hub_id):
    identity(["PrintOperationsDirector", "Auditor", "PlatformAdmin"])
    hub = path_one("region_hubs", hub_id)
    C.refresh_legal_notice_block(hub)
    compliant, on_time, counted = C.legal_notice_verdict(hub)
    return ok_object({
        "is_legal_notice_ratio_compliant": compliant,
        "on_time_market_count": on_time,
        "counted_market_count": counted,
        "min_on_time_ratio_pct": int(hub.get("min_on_time_ratio_pct") or 90),
        "legal_notice_block": bool(hub.get("legal_notice_block")),
        "press_posture": hub.get("press_posture"),
    })


@bp.post("/regional-news-ops/region-hubs/<hub_id>/regions")
def create_region(hub_id):
    data = body()
    identity(["PrintOperationsDirector"])
    hub = path_one("region_hubs", hub_id)
    region = create("regions", data,
                    ["name", "daily_headcount_floor", "daily_headcount_cap",
                     "allocation_priority"], system={"region_hub_id": hub["id"]})
    if int(region["daily_headcount_floor"]) < 0:
        fail("ERR_INVALID_REQUEST", "daily_headcount_floor must be at least 0.")
    if int(region["daily_headcount_cap"]) < int(region["daily_headcount_floor"]):
        fail("ERR_INVALID_REQUEST",
             "daily_headcount_cap must be at least daily_headcount_floor.")
    if DB.duplicate("regions", region["id"], region_hub_id=hub["id"], name=region["name"]):
        DB.col("regions").pop(region["id"], None)
        fail("ERR_DUPLICATE_HUB_CODE")
    region["status"] = "active"
    region["guaranteed_headcount"] = 0
    region["allocated_newsroom_headcount"] = 0
    region["member_market_count"] = 0
    R.recompute_region(region, hub, bump_row=False)
    return ok_object(region, 201)


@bp.get("/regional-news-ops/region-hubs/<hub_id>/regions")
def list_regions(hub_id):
    identity(READ_REGION)
    hub = path_one("region_hubs", hub_id)
    rows = [r for r in DB.all("regions") if r.get("region_hub_id") == hub["id"]]
    rows.sort(key=lambda r: (int(r.get("allocation_priority") or 0),
                             str(r.get("name") or "")))
    return ok_list(rows, None, None)


@bp.get("/regional-news-ops/regions/<region_id>")
def get_region(region_id):
    identity(READ_REGION)
    return ok_object(path_one("regions", region_id))