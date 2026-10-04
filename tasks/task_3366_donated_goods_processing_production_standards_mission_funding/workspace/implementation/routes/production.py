"""Production standards (OCC-guarded, superseding) and processing runs."""
from flask import Blueprint, request

import errors
from db import store
from envelope import success
from serializers import ser_run, ser_standard
from services import D, new_entity, org_of_site, rhu, rhu2, touch
from validate import (
    _is_int,
    auth,
    field,
    get_body,
    paginate,
    require_role,
    sort_created,
)

bp = Blueprint("production", __name__)

CATEGORIES = {"TEXTILES", "HOUSEWARES", "MEDIA", "FURNITURE", "EWASTE"}


def _get_org(oid):
    org = store.member_orgs.get(oid)
    if org is None:
        errors.not_found("MemberOrg not found")
    return org


@bp.post("/donated-goods/production-standards")
def create_standard():
    body = get_body()
    member_org_id = field(body, "member_org_id", "str", required=True)
    category = field(body, "category", "str", required=True, enum=CATEGORIES)
    target = field(body, "target_items_per_hour", "int", required=True, minval=1)
    hourly_cost = field(body, "hourly_cost_cents", "int", required=True)
    grade_price_map = field(body, "grade_price_map", "dict", required=True)
    for grade in ("A", "B", "C"):
        if grade not in grade_price_map or not _is_int(grade_price_map[grade]):
            errors.invalid_request(
                "grade_price_map must carry integer cents for A, B and C")
    price_floor = field(body, "price_floor_cents", "int", required=True)
    price_ceiling = field(body, "price_ceiling_cents", "int", required=True)
    expected_version = field(body, "expected_member_org_version", "int",
                             required=True)
    uid, role = auth()
    require_role(role, {"MemberAdmin"})
    if uid != member_org_id:
        errors.ownership_mismatch()
    org = _get_org(member_org_id)
    # OCC (priority 6) precedes the suspension gate (priority 7).
    if expected_version != org["version"]:
        errors.stale_version()
    if org["brand_license_status"] != "ACTIVE":
        errors.org_suspended()
    with store.lock:
        prior = None
        for s in store.production_standards.values():
            if (s["member_org_id"] == member_org_id
                    and s["category"] == category and s["status"] == "ACTIVE"):
                prior = s
                break
        if prior is not None:
            # Shallow supersession: pinned items/runs are never re-evaluated.
            prior["status"] = "SUPERSEDED"
            touch(prior)
        std = new_entity()
        std.update({
            "member_org_id": member_org_id,
            "category": category,
            "target_items_per_hour": target,
            "hourly_cost_cents": hourly_cost,
            "grade_price_map": {g: int(grade_price_map[g]) for g in ("A", "B", "C")},
            "price_floor_cents": price_floor,
            "price_ceiling_cents": price_ceiling,
            "status": "ACTIVE",
        })
        store.production_standards[std["id"]] = std
        touch(org)
    return success(ser_standard(std), 201)


@bp.get("/donated-goods/member-orgs/<oid>/production-standards")
def list_standards(oid):
    auth()
    _get_org(oid)
    items = [s for s in store.production_standards.values()
             if s["member_org_id"] == oid]
    category = request.args.get("category")
    status = request.args.get("status")
    if category is not None:
        items = [s for s in items if s["category"] == category]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = sort_created(items)
    page, meta = paginate(items)
    return success([ser_standard(s) for s in page], 200,
                   response_type="array", pagination=meta)


# ---------------------------------------------------------------------------
# Processing runs
# ---------------------------------------------------------------------------

@bp.post("/donated-goods/processing-runs")
def create_run():
    body = get_body()
    site_id = field(body, "site_id", "str", required=True)
    standard_id = field(body, "production_standard_id", "str", required=True)
    _uid, role = auth()
    require_role(role, {"ProductionLead"})
    site = store.donation_sites.get(site_id)
    if site is None:
        errors.not_found("DonationSite not found")
    std = store.production_standards.get(standard_id)
    if std is None:
        errors.not_found("ProductionStandard not found")
    org = org_of_site(site)
    if org["brand_license_status"] != "ACTIVE":
        errors.org_suspended()
    if std["status"] != "ACTIVE" or std["member_org_id"] != site["member_org_id"]:
        errors.no_eligible_standard()
    with store.lock:
        run = new_entity()
        run.update({
            "site_id": site_id,
            "production_standard_id": standard_id,  # pinned for the run's life
            "category": std["category"],
            "status": "OPEN",
            "item_count_processed": None,
            "unsalable_count": None,
            "labor_minutes": None,
            "labor_cost_cents": None,
            "gross_rate_iph": None,
            "net_rate_iph": None,
            "variance_bps": None,
            "performance_flag": None,
        })
        store.processing_runs[run["id"]] = run
    return success(ser_run(run), 201)


@bp.get("/donated-goods/processing-runs")
def list_runs():
    auth()
    items = list(store.processing_runs.values())
    for param in ("site_id", "status", "production_standard_id"):
        val = request.args.get(param)
        if val is not None:
            items = [r for r in items if r[param] == val]
    items = sort_created(items)
    page, meta = paginate(items)
    return success([ser_run(r) for r in page], 200,
                   response_type="array", pagination=meta)


def _get_run(rid):
    run = store.processing_runs.get(rid)
    if run is None:
        errors.not_found("ProcessingRun not found")
    return run


@bp.get("/donated-goods/processing-runs/<rid>")
def get_run(rid):
    auth()
    return success(ser_run(_get_run(rid)), 200)


@bp.post("/donated-goods/processing-runs/<rid>/close")
def close_run(rid):
    body = get_body()
    processed = field(body, "item_count_processed", "int", required=True)
    unsalable = field(body, "unsalable_count", "int", required=True)
    labor_minutes = field(body, "labor_minutes", "int", required=True, minval=1)
    labor_cost = field(body, "labor_cost_cents", "int", required=True)
    _uid, role = auth()
    require_role(role, {"ProductionLead"})
    run = _get_run(rid)
    org = org_of_site(store.donation_sites[run["site_id"]])
    if org["brand_license_status"] != "ACTIVE":
        errors.org_suspended()
    if run["status"] != "OPEN":
        errors.invalid_state("Only an OPEN run can be closed")
    with store.lock:
        std = store.production_standards[run["production_standard_id"]]
        target = std["target_items_per_hour"]  # pinned; supersede-safe
        gross = rhu2(D(processed) * 60 / D(labor_minutes))
        net = rhu2(D(processed - unsalable) * 60 / D(labor_minutes))
        variance = rhu((net - D(target)) * 10000 / D(target))
        run["item_count_processed"] = processed
        run["unsalable_count"] = unsalable
        run["labor_minutes"] = labor_minutes
        run["labor_cost_cents"] = labor_cost
        run["gross_rate_iph"] = float(gross)
        run["net_rate_iph"] = float(net)
        run["variance_bps"] = variance
        run["performance_flag"] = "MET" if net >= D(target) else "MISSED"
        run["status"] = "CLOSED"
        touch(run)
    return success(ser_run(run), 200)
