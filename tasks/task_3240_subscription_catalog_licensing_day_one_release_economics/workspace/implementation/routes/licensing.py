"""LicensingDeal: create, read, list, sign (OCC), renew."""
from datetime import timedelta

from flask import Blueprint, request

from checks import page, query_paging
from db import db
from errors import fail
from request_ctx import (ctx, expect_query, run, want_int, want_instant, want_num,
                         want_str)
from response import ok_array, ok_object
from services import calc
from services.store import refresh_region_capacities

bp = Blueprint("licensing", __name__)

MODELS = ("FIXED", "ENGAGEMENT", "HYBRID")
FEE_FIELDS = ("monthly_fixed_fee_cents", "guaranteed_compensation_cents",
              "engagement_rate_cents_per_hour", "monthly_engagement_cap_cents")


def deal_view(deal, view="LEDGER"):
    out = db.public(deal)
    out["payable_compensation_cents"] = calc.payable_compensation_cents(deal, view)
    return out


def _publisher(pid):
    row = db.publishers.get(pid)
    if row is None:
        fail("ERR_PUBLISHER_NOT_FOUND", "No publisher exists with id %s." % pid)
    return row


def _title(tid, publisher_id=None):
    row = db.titles.get(tid)
    if row is None:
        fail("ERR_TITLE_NOT_FOUND", "No title exists with id %s." % tid)
    if publisher_id is not None and row["publisher_id"] != publisher_id:
        fail("ERR_TITLE_NOT_FOUND",
             "Title %s is not owned by publisher %s." % (tid, publisher_id))
    return row


def _deal(did):
    row = db.deals.get(did)
    if row is None:
        fail("ERR_DEAL_NOT_FOUND", "No licensing deal exists with id %s." % did)
    return row


def refresh_maintenances(deal):
    count = 0
    for window in db.maintenances.values():
        if window["region_code"] not in db.regions:
            continue
        if window["maintenance_start"] < deal["term_end_date"] and \
                deal["term_start_date"] < window["maintenance_end"]:
            count += 1
    deal["maintenances_in_window"] = count


def _setup_deal(deal, commit=True):
    """Recompute every derived field that rides on the deal record."""
    refresh_maintenances(deal)
    deal["compensation_floor_cents"] = calc.compensation_floor_cents(deal)
    if commit:
        deal["payable_compensation_cents"] = calc.payable_compensation_cents(deal)


@bp.route("/catalog/licensing-deals", methods=["POST"])
def create_deal():
    c = ctx(["CatalogAdmin"], full=True)
    run(c, _shape_deal, on_temporal=_deal_windows, on_eligibility=_deal_eligibility)
    publisher = c.extra["publisher"]
    title = c.extra["title"]
    deal = db.new_row()
    deal.update({
        "publisher_id": publisher["id"],
        "title_id": title["id"],
        "compensation_model": c.get("compensation_model"),
        "monthly_fixed_fee_cents": c.int_of("monthly_fixed_fee_cents", 0),
        "guaranteed_compensation_cents": c.int_of("guaranteed_compensation_cents", 0),
        "engagement_rate_cents_per_hour": c.get("engagement_rate_cents_per_hour", 0),
        "monthly_engagement_cap_cents": c.int_of("monthly_engagement_cap_cents", 0),
        "compensation_floor_cents": 0.0,
        "payable_compensation_cents": 0.0,
        "term_start_date": c.get("term_start_date"),
        "term_end_date": c.get("term_end_date"),
        "status": "DRAFT",
        "signed_at": None,
        "add_effective_date": c.get("add_effective_date"),
        "removal_effective_date": None,
        "entry_id": None,
        "maintenances_in_window": 0,
    })
    db.deals[deal["id"]] = deal
    _setup_deal(deal)
    calc.refresh_publisher_rollup(publisher)
    return ok_object(deal_view(deal), 201)


def _shape_deal(c):
    want_str(c, "publisher_id", required=True)
    want_str(c, "title_id", required=True)
    want_str(c, "compensation_model", allowed=MODELS, required=True)
    want_int(c, "monthly_fixed_fee_cents", lo=0)
    want_int(c, "guaranteed_compensation_cents", lo=0)
    want_num(c, "engagement_rate_cents_per_hour", lo=0)
    want_int(c, "monthly_engagement_cap_cents", lo=0)
    want_instant(c, "term_start_date", required=True)
    want_instant(c, "term_end_date", required=True)
    want_instant(c, "add_effective_date", required=True)


def _deal_windows(c):
    if c.get("term_end_date") <= c.get("term_start_date"):
        fail("ERR_TERM_WINDOW_INVALID",
             "term_end_date must be strictly after term_start_date.")
    add = c.get("add_effective_date")
    if not (c.get("term_start_date") <= add < c.get("term_end_date")):
        fail("ERR_ADD_EFFECTIVE_OUTSIDE_TERM",
             "add_effective_date must fall inside the term window.")


def _deal_eligibility(c):
    publisher = _publisher(c.get("publisher_id"))
    c.extra["publisher"] = publisher
    c.extra["title"] = _title(c.get("title_id"), publisher["id"])
    model = c.get("compensation_model")
    fixed = c.int_of("monthly_fixed_fee_cents", 0)
    guaranteed = c.int_of("guaranteed_compensation_cents", 0)
    rate = c.get("engagement_rate_cents_per_hour", 0) or 0
    cap = c.int_of("monthly_engagement_cap_cents", 0)
    ok = False
    if model == "FIXED":
        ok = fixed > 0
    elif model == "ENGAGEMENT":
        ok = rate > 0 and cap > 0
    else:
        ok = guaranteed > 0 and cap > 0
    if not ok:
        fail("ERR_COMPENSATION_MODEL_MISMATCH",
             "The supplied fee fields do not match the %s model." % model)


@bp.route("/catalog/licensing-deals/<deal_id>", methods=["GET"])
def read_deal(deal_id):
    c = ctx(["CatalogAdmin", "CatalogAnalyst"])
    expect_query(c, ("compensation_view",))
    view = request.args.get("compensation_view", "LEDGER")
    if view not in ("LEDGER", "STATEMENT"):
        fail("ERR_INVALID_REQUEST", "compensation_view must be LEDGER or STATEMENT.")
    run(c, _nothing, on_resolve=lambda cc: cc.extra.update({"deal": _deal(deal_id)}))
    deal = c.extra["deal"]
    _setup_deal(deal)
    return ok_object(deal_view(deal, view))


@bp.route("/catalog/licensing-deals", methods=["GET"])
def list_deals():
    c = ctx(["CatalogAdmin", "CatalogAnalyst"])
    expect_query(c, ("publisher_id", "title_id", "status", "limit", "offset"))
    limit, offset = query_paging()
    rows = db.sorted_rows(db.deals)
    for key in ("publisher_id", "title_id"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    status = request.args.get("status")
    if status is not None:
        if status not in ("DRAFT", "SIGNED", "LIVE", "EXPIRING", "COMPLETED"):
            fail("ERR_INVALID_REQUEST", "Unknown deal status %s." % status)
        rows = [r for r in rows if r["status"] == status]
    window, total = page(rows, limit, offset)
    for row in window:
        _setup_deal(row, commit=False)
    return ok_array([deal_view(r) for r in window], limit, offset, total)


def _nothing(_c):
    return None


def _deal_state(c):
    deal = c.extra["deal"]
    if deal["status"] != "DRAFT":
        fail("ERR_DEAL_ALREADY_SIGNED", "Deal %s is no longer DRAFT." % deal["id"])


def _deal_eligibility_for_sign(c):
    deal = c.extra["deal"]
    publisher = db.publishers.get(deal["publisher_id"])
    if publisher is None or publisher["status"] != "ACTIVE":
        fail("ERR_PUBLISHER_SUSPENDED",
             "Publisher %s is suspended." % deal["publisher_id"])


@bp.route("/catalog/licensing-deals/<deal_id>/sign", methods=["POST"])
def sign_deal(deal_id):
    c = ctx(["CatalogAdmin"], full=True)
    run(c, _shape_sign, on_resolve=lambda cc: cc.extra.update({"deal": _deal(deal_id)}),
        on_state=_deal_state, on_temporal=_sign_window,
        on_eligibility=_deal_eligibility_for_sign, on_fiscal=_sign_stale_then_commit)
    return ok_object(deal_view(c.extra["deal"]))


def _shape_sign(c):
    want_int(c, "expected_title_version", lo=0, required=True)


def _sign_window(c):
    deal = c.extra["deal"]
    if deal["term_end_date"] <= deal["term_start_date"]:
        fail("ERR_TERM_WINDOW_INVALID",
             "term_end_date must be strictly after term_start_date.")


def _sign_stale_then_commit(c):
    """The concurrency check is the last layer before the write commits."""
    deal = c.extra["deal"]
    title = db.titles[deal["title_id"]]
    if c.get("expected_title_version") != title["version"]:
        fail("ERR_STALE_VERSION",
             "expected_title_version %s does not match the title's version %s."
             % (c.get("expected_title_version"), title["version"]))
    publisher = db.publishers[deal["publisher_id"]]
    if publisher["status"] != "ACTIVE":
        fail("ERR_PUBLISHER_SUSPENDED",
             "Publisher %s is suspended." % publisher["id"])
    deal["status"] = "SIGNED"
    deal["signed_at"] = db.clock
    db.touch(deal)
    _setup_deal(deal)
    calc.refresh_publisher_rollup(publisher)
    # Signing increments the licensing title's version by exactly one.
    db.touch(title)


def _renew_state(c):
    deal = c.extra["deal"]
    if deal["status"] != "EXPIRING":
        fail("ERR_DEAL_ALREADY_SIGNED",
             "Deal %s is in status %s, not EXPIRING." % (deal["id"], deal["status"]))


@bp.route("/catalog/licensing-deals/<deal_id>/renew", methods=["POST"])
def renew_deal(deal_id):
    c = ctx(["CatalogAdmin"], full=True)
    run(c, _shape_renew, on_resolve=lambda cc: cc.extra.update({"deal": _deal(deal_id)}),
        on_state=_renew_state, on_temporal=_renew_window, on_eligibility=_renew_commit)
    return ok_object(deal_view(c.extra["deal"]))


def _shape_renew(c):
    want_instant(c, "renew_term_end_date", required=True)


def _renew_window(c):
    deal = c.extra["deal"]
    new_end = c.get("renew_term_end_date")
    if new_end is None:
        return
    if new_end <= deal["term_end_date"]:
        fail("ERR_TERM_WINDOW_INVALID",
             "renew_term_end_date must be later than the current term_end_date.")
    if not db.clock < deal["term_end_date"]:
        fail("ERR_TERM_WINDOW_INVALID",
             "The logical clock has already reached the current term_end_date.")


def _renew_commit(c):
    deal = c.extra["deal"]
    deal["term_end_date"] = c.get("renew_term_end_date")
    deal["removal_effective_date"] = deal["term_end_date"] - timedelta(days=2)
    deal["status"] = "LIVE"
    db.touch(deal)
    for row in db.entries.values():
        if row["deal_id"] == deal["id"] and row["status"] == "REMOVING":
            row["status"] = "ADDED"
            db.touch(row)
    _setup_deal(deal)
    publisher = db.publishers.get(deal["publisher_id"])
    if publisher is not None:
        calc.refresh_publisher_rollup(publisher)
    refresh_region_capacities()
