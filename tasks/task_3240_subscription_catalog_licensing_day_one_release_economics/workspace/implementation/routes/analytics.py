"""AvailabilityProjection: the day-one release economics."""
from flask import Blueprint, request

from checks import page, query_paging
from db import db
from errors import fail
from request_ctx import (ctx, expect_query, run, want_int, want_str)
from response import ok_array, ok_object
from services import calc

bp = Blueprint("analytics", __name__)

RELEASE_CLASSES = ("DAY_ONE", "BACK_CATALOG", "CATALOG_ADD")
PROJECTION_STATUSES = ("DRAFT", "FINALIZED")


def _title(tid):
    row = db.titles.get(tid)
    if row is None:
        fail("ERR_TITLE_NOT_FOUND", "No title exists with id %s." % tid)
    return row


def _region(code):
    row = db.regions.get(code)
    if row is None:
        fail("ERR_REGION_NOT_FOUND", "No region exists with code %s." % code)
    return row


def _projection(pid):
    row = db.projections.get(pid)
    if row is None:
        fail("ERR_PROJECTION_NOT_FOUND",
             "No availability projection exists with id %s." % pid)
    return row


def live_deal(title_id):
    rows = [r for r in db.deals.values()
            if r["title_id"] == title_id and r["status"] == "LIVE"]
    if not rows:
        return None
    rows.sort(key=lambda r: (r["term_start_date"], r["_seq"]))
    return rows[0]


def _nothing(_c):
    return None


def _shape_projection(c):
    want_str(c, "title_id", required=True)
    want_str(c, "region_code", required=True)
    want_int(c, "launch_subscriber_count", lo=0, required=True)
    want_int(c, "tier_step_count", lo=0, required=True)
    want_int(c, "projected_unit_sales_units", lo=0, required=True)
    want_str(c, "release_class", allowed=RELEASE_CLASSES, required=True)


def _resolve_projection_refs(c):
    c.extra["title"] = _title(c.get("title_id"))
    c.extra["region"] = _region(c.get("region_code"))


def _binding(c):
    title = c.extra["title"]
    deal = live_deal(title["id"])
    if deal is None:
        fail("ERR_NO_BINDING_DEAL",
             "Title %s has no licensing deal in LIVE status." % title["id"])
    return deal


def _projection_eligibility(c):
    deal = _binding(c)
    c.extra["deal"] = deal
    if c.get("release_class") == "DAY_ONE":
        for row in db.projections.values():
            if (row["title_id"] == c.get("title_id")
                    and row["region_code"] == c.get("region_code")
                    and row["release_class"] == "DAY_ONE"
                    and row["status"] == "FINALIZED"):
                fail("ERR_DUPLICATE_DAY_ONE_PROJECTION",
                     "A finalized DAY_ONE projection already exists for this "
                     "title and region.")


def derive(projection, deal=None):
    """Recompute every derived figure on a projection."""
    title = db.titles[projection["title_id"]]
    region = db.regions[projection["region_code"]]
    if deal is None:
        deal = live_deal(title["id"])
        if deal is None:
            deal = _any_deal(title["id"])
    value, _capped = calc.subscription_value_cents(deal, title, projection)
    cannibalized = calc.provisional_cannibalized_cents(
        title, region, projection["projected_unit_sales_units"])
    projection["projected_subscription_value_cents"] = value
    projection["projected_cannibalized_unit_sales_cents"] = float(cannibalized)
    net = value - float(cannibalized)
    projection["projected_net_value_cents"] = net
    projection["decision"] = calc.decision_ladder(net, title, projection["release_class"])
    return projection


def _any_deal(title_id):
    rows = [r for r in db.deals.values() if r["title_id"] == title_id]
    if not rows:
        return None
    rows.sort(key=lambda r: (r["term_start_date"], r["_seq"]))
    return rows[0]


@bp.route("/catalog/availability-projections", methods=["POST"])
def create_projection():
    c = ctx(["CatalogAnalyst", "CatalogAdmin"], full=True)
    run(c, _shape_projection, on_resolve=_resolve_projection_refs,
        on_eligibility=_projection_eligibility)
    row = db.new_row()
    row.update({
        "title_id": c.extra["title"]["id"],
        "region_code": c.extra["region"]["region_code"],
        "release_class": c.get("release_class"),
        "launch_subscriber_count": c.int_of("launch_subscriber_count", 0),
        "tier_step_count": c.int_of("tier_step_count", 0),
        "projected_unit_sales_units": c.int_of("projected_unit_sales_units", 0),
        "projected_subscription_value_cents": 0.0,
        "projected_cannibalized_unit_sales_cents": 0.0,
        "projected_net_value_cents": 0.0,
        "decision": "REJECT_DAY_ONE",
        "status": "DRAFT",
    })
    db.projections[row["id"]] = row
    derive(row, c.extra["deal"])
    return ok_object(db.public(row), 201)


@bp.route("/catalog/availability-projections/<projection_id>", methods=["GET"])
def read_projection(projection_id):
    c = ctx(["CatalogAdmin", "CatalogAnalyst"])
    expect_query(c, ())
    run(c, _nothing, on_resolve=lambda cc: cc.extra.update(
        {"projection": _projection(projection_id)}))
    return ok_object(db.public(c.extra["projection"]))


@bp.route("/catalog/availability-projections", methods=["GET"])
def list_projections():
    c = ctx(["CatalogAdmin", "CatalogAnalyst"])
    expect_query(c, ("title_id", "region_code", "status", "limit", "offset"))
    limit, offset = query_paging()
    rows = db.sorted_rows(db.projections)
    for key in ("title_id", "region_code"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    status = request.args.get("status")
    if status is not None:
        if status not in PROJECTION_STATUSES:
            fail("ERR_INVALID_REQUEST", "Unknown projection status %s." % status)
        rows = [r for r in rows if r["status"] == status]
    window, total = page(rows, limit, offset)
    return ok_array([db.public(r) for r in window], limit, offset, total)


def _finalize_state(c):
    row = c.extra["projection"]
    if row["status"] == "FINALIZED":
        fail("ERR_PROJECTION_ALREADY_FINALIZED",
             "Projection %s is already finalized." % row["id"])


def _finalize_eligibility(c):
    row = c.extra["projection"]
    if row["release_class"] != "DAY_ONE":
        return
    for other in db.projections.values():
        if other["id"] == row["id"]:
            continue
        if (other["title_id"] == row["title_id"]
                and other["region_code"] == row["region_code"]
                and other["release_class"] == "DAY_ONE"
                and other["status"] == "FINALIZED"):
            fail("ERR_DUPLICATE_DAY_ONE_PROJECTION",
                 "A finalized DAY_ONE projection already exists for this "
                 "title and region.")


@bp.route("/catalog/availability-projections/<projection_id>/finalize", methods=["POST"])
def finalize_projection(projection_id):
    c = ctx(["CatalogAnalyst", "CatalogAdmin"], full=True)
    run(c, _nothing, on_resolve=lambda cc: cc.extra.update(
        {"projection": _projection(projection_id)}),
        on_state=_finalize_state, on_eligibility=_finalize_eligibility)
    row = c.extra["projection"]
    provisional = float(row["projected_cannibalized_unit_sales_cents"])
    final_cannibalized = float(calc.chronological_cannibalized_cents(
        row["title_id"], row["region_code"]))
    title = db.titles[row["title_id"]]
    row["projected_cannibalized_unit_sales_cents"] = final_cannibalized
    net = float(row["projected_subscription_value_cents"]) - final_cannibalized
    row["projected_net_value_cents"] = net
    row["decision"] = calc.decision_ladder(net, title, row["release_class"])
    row["status"] = "FINALIZED"
    db.touch(row)
    view = db.public(row)
    delta = round(final_cannibalized - provisional, 2)
    view["provisional_to_final_delta_cents"] = delta
    view["cannibalization_delta_cents"] = delta
    return ok_object(view)
