"""Clock, member orgs, territories, and markdown events."""
from datetime import datetime, timezone

from flask import Blueprint

import errors
from clock import set_now, week_index
from db import store
from envelope import success
from serializers import ser_org, ser_territory
from services import (
    MARKDOWN_PCT,
    ROTATION_WEEKS,
    D,
    new_entity,
    new_light_entity,
    org_of_item,
    rhu,
    touch,
)
from validate import auth, field, get_body, paginate, require_role, sort_created

bp = Blueprint("orgs", __name__)


@bp.post("/donated-goods/_clock/set_current_utc")
def set_clock():
    body = get_body()
    to = field(body, "to_iso8601", "datetime", required=True)
    _uid, role = auth()
    require_role(role, {"PlatformAdmin"})
    with store.lock:
        set_now(to)
    return success({}, 200)


@bp.post("/donated-goods/member-orgs")
def create_org():
    body = get_body()
    name = field(body, "name", "str", required=True)
    costing = field(body, "costing_method", "str", required=False,
                    enum={"STANDARD", "ACTUAL"})
    reserve_floor = field(body, "reserve_floor_cents", "int", required=True)
    diversion_floor = field(body, "diversion_floor_bps", "int", required=True)
    _uid, role = auth()
    require_role(role, {"PlatformAdmin"})
    with store.lock:
        org = new_entity()
        org.update({
            "name": name,
            "brand_license_status": "ACTIVE",
            "costing_method": costing or "STANDARD",
            "reserve_floor_cents": reserve_floor,
            "diversion_floor_bps": diversion_floor,
            "retail_margin_pool_cents": 0,
            "reserved_cents": 0,
            "margin_health": "HEALTHY",
            "contract_revenue_cents": 0,
            "total_diverted_lbs": D(0),
            "total_disposed_lbs": D(0),
            "diversion_rate_bps": 10000,
            "diversion_compliant": True,
            "last_markdown_week": None,
        })
        store.member_orgs[org["id"]] = org
    return success(ser_org(org), 201)


def _get_org(oid):
    org = store.member_orgs.get(oid)
    if org is None:
        errors.not_found("MemberOrg not found")
    return org


@bp.get("/donated-goods/member-orgs/<oid>")
def get_org(oid):
    auth()
    return success(ser_org(_get_org(oid)), 200)


@bp.post("/donated-goods/member-orgs/<oid>/suspend")
def suspend_org(oid):
    get_body()
    _uid, role = auth()
    require_role(role, {"BrandRegulator"})
    org = _get_org(oid)
    if org["brand_license_status"] != "ACTIVE":
        errors.invalid_state("Only an ACTIVE org can be suspended")
    with store.lock:
        org["brand_license_status"] = "SUSPENDED"
        prog_ids = {
            p["id"] for p in store.mission_programs.values()
            if p["member_org_id"] == oid
        }
        for a in store.funding_allocations.values():
            if a["mission_program_id"] in prog_ids and a["status"] == "PENDING":
                a["status"] = "CANCELLED"
                touch(a)
        touch(org)
    return success(ser_org(org), 200)


@bp.post("/donated-goods/member-orgs/<oid>/reinstate")
def reinstate_org(oid):
    get_body()
    _uid, role = auth()
    require_role(role, {"BrandRegulator"})
    org = _get_org(oid)
    if org["brand_license_status"] != "SUSPENDED":
        errors.invalid_state("Only a SUSPENDED org can be reinstated")
    with store.lock:
        org["brand_license_status"] = "ACTIVE"
        touch(org)
    return success(ser_org(org), 200)


# ---------------------------------------------------------------------------
# Territories
# ---------------------------------------------------------------------------

_INF = datetime.max.replace(tzinfo=timezone.utc)


def _half_open_intersect(f1, t1, f2, t2):
    """[f1, t1) vs [f2, t2); null end is open-ended; adjacency allowed."""
    t1 = t1 if t1 is not None else _INF
    t2 = t2 if t2 is not None else _INF
    return f1 < t2 and f2 < t1


@bp.post("/donated-goods/territories")
def create_territory():
    body = get_body()
    member_org_id = field(body, "member_org_id", "str", required=True)
    region_code = field(body, "region_code", "str", required=True)
    eff_from = field(body, "effective_from", "datetime", required=True)
    eff_to = field(body, "effective_to", "datetime", required=False)
    _uid, role = auth()
    require_role(role, {"BrandRegulator"})
    _get_org(member_org_id)
    with store.lock:
        for t in store.territories.values():
            if t["region_code"] != region_code:
                continue
            if t["member_org_id"] == member_org_id:
                continue
            if _half_open_intersect(eff_from, eff_to,
                                    t["effective_from"], t["effective_to"]):
                errors.territory_overlap()
        terr = new_light_entity()
        terr.update({
            "member_org_id": member_org_id,
            "region_code": region_code,
            "effective_from": eff_from,
            "effective_to": eff_to,
        })
        store.territories[terr["id"]] = terr
    return success(ser_territory(terr), 201)


@bp.get("/donated-goods/member-orgs/<oid>/territories")
def list_territories(oid):
    auth()
    _get_org(oid)
    items = sort_created(
        [t for t in store.territories.values() if t["member_org_id"] == oid]
    )
    page, meta = paginate(items)
    return success([ser_territory(t) for t in page], 200,
                   response_type="array", pagination=meta)


# ---------------------------------------------------------------------------
# Markdown events (weekly ops checkpoint)
# ---------------------------------------------------------------------------

@bp.post("/donated-goods/member-orgs/<oid>/markdown-events")
def markdown_event(oid):
    get_body()
    uid, role = auth()
    require_role(role, {"MemberAdmin"})
    if uid != oid:
        errors.ownership_mismatch()
    org = _get_org(oid)
    if org["brand_license_status"] != "ACTIVE":
        errors.org_suspended()
    w = week_index()
    if org["last_markdown_week"] == w:
        errors.markdown_already_run()
    with store.lock:
        items = [
            it for it in store.donated_items.values()
            if it["status"] == "ON_FLOOR" and org_of_item(it)["id"] == oid
        ]
        items.sort(key=lambda it: (it["floor_week"], it["_seq"]))
        marked = 0
        pulled = 0
        for it in items:
            age = w - it["floor_week"]
            if age >= ROTATION_WEEKS:
                # Rotation pull: leaves the floor; step and price frozen.
                it["status"] = "SALVAGED"
                touch(it)
                pulled += 1
            elif age >= 1:
                # At most ONE step per item per event, even after skipped weeks.
                it["markdown_step"] = min(it["markdown_step"] + 1, 3)
                it["current_selling_price_cents"] = rhu(
                    D(it["price_cents"])
                    * (100 - MARKDOWN_PCT[it["markdown_step"]]) / 100
                )
                touch(it)
                marked += 1
        org["last_markdown_week"] = w
        touch(org)
    return success(
        {"applied_week": w, "marked_down_count": marked, "pulled_count": pulled},
        200,
    )
