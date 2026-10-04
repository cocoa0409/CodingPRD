# Capacity pool routes (PRD 3.5): creation, OCC-guarded investment, fetch.
from flask import Blueprint

from auth import require_roles
from envelope import success
from errors import ApiError, ERR_POOL_CAPACITY_EXCEEDED, ERR_POOL_PERIOD_OVERLAP, ERR_STALE_VERSION
from lookups import get_capacity_pool
from serialize import capacity_pool_public
from store import store
from validate import (
    as_datetime,
    as_int,
    as_int_at_least,
    as_str,
    check_unknown_fields,
    get_body,
    require_fields,
)

bp = Blueprint("capacity", __name__)

_CREATE_ALLOWED = {"site_name", "process_technology", "period_start", "period_end", "total_units"}
_PATCH_ALLOWED = {"total_units", "expected_capacity_pool_version"}


@bp.post("/capacity-pools")
def create_capacity_pool():
    require_roles("SupplyPlanner")
    body = get_body(required=True)
    require_fields(body, ["site_name", "process_technology", "period_start", "period_end", "total_units"])
    check_unknown_fields(body, _CREATE_ALLOWED)
    site_name = as_str(body["site_name"], "site_name")
    process_technology = as_str(body["process_technology"], "process_technology")
    period_start = as_datetime(body["period_start"], "period_start")
    period_end = as_datetime(body["period_end"], "period_end")
    total_units = as_int_at_least(body["total_units"], "total_units", 1)
    # Row 7: half-open window overlap for the same site + technology;
    # adjacency (existing.period_end == new.period_start) is allowed.
    for existing in store.capacity_pools.values():
        if existing["site_name"] != site_name or existing["process_technology"] != process_technology:
            continue
        if period_start < existing["period_end"] and existing["period_start"] < period_end:
            raise ApiError(
                ERR_POOL_PERIOD_OVERLAP, 409,
                "Window overlaps an existing pool for site %s / %s" % (site_name, process_technology),
            )
    pool = {
        "site_name": site_name,
        "process_technology": process_technology,
        "period_start": period_start,
        "period_end": period_end,
        "total_units": total_units,
        "allocated_units": 0,
    }
    pool.update(store.stamp())
    store.capacity_pools[pool["id"]] = pool
    return success(capacity_pool_public(pool), 201)


@bp.patch("/capacity-pools/<pool_id>")
def invest_capacity_pool(pool_id):
    require_roles("SupplyPlanner")
    pool = get_capacity_pool(pool_id)
    body = get_body(required=True)
    require_fields(body, ["total_units", "expected_capacity_pool_version"])
    check_unknown_fields(body, _PATCH_ALLOWED)
    total_units = as_int_at_least(body["total_units"], "total_units", 1)
    expected_version = as_int(body["expected_capacity_pool_version"], "expected_capacity_pool_version")
    # OCC (PRD 2.7): stale view of the pool rejects the investment.
    if expected_version != pool["version"]:
        raise ApiError(
            ERR_STALE_VERSION, 412,
            "expected_capacity_pool_version %s does not match the pool's current version %s"
            % (expected_version, pool["version"]),
        )
    # Row 10: total_units may never be set below allocated_units.
    if total_units < pool["allocated_units"]:
        raise ApiError(ERR_POOL_CAPACITY_EXCEEDED, 422, "total_units may not be set below allocated_units")
    pool["total_units"] = total_units
    store.touch(pool)
    return success(capacity_pool_public(pool))


@bp.get("/capacity-pools/<pool_id>")
def fetch_capacity_pool(pool_id):
    require_roles("PlatformAdmin", "SupplyPlanner", "ChannelManager")
    return success(capacity_pool_public(get_capacity_pool(pool_id)))
