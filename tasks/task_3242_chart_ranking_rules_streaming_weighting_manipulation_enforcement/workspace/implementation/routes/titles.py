"""Title product, sale batch, and title-centric reverse-reachability routes."""

from flask import Blueprint, request

import errors
from db import db
from helpers import (
    envelope_ok,
    get_json,
    iso3,
    paginate,
    pagination_params,
    parse_dt,
    require_roles,
    touch,
)
from services import (
    allocate_buyer_group,
    get_label,
    get_title,
    get_week,
    new_entity,
    ser_batch,
    ser_dispute,
    ser_entry,
    ser_report,
    ser_signal,
    ser_title,
)

bp = Blueprint("titles", __name__)

ALL_ROLES = ("PlatformAdmin", "ChartManager", "ChartOps", "DataProvider", "LabelRep", "Investigator")
REPORT_READ_ROLES = ("PlatformAdmin", "ChartManager", "ChartOps", "Investigator")


@bp.route("/titles", methods=["POST"])
def create_title():
    user_id, role = require_roles("LabelRep")
    payload = get_json()

    upc = payload.get("upc")
    label_account_id = payload.get("label_account_id")

    # ownership: LabelRep's X-User-ID is the label account id
    if label_account_id != user_id:
        raise errors.unauthorized("LabelRep may only register titles for their own label")

    label = db.label_accounts.get(label_account_id)
    if label is None:
        raise errors.not_found("LabelAccount not found")

    for t in db.title_products.values():
        if t["upc"] == upc:
            raise errors.ApiError("ERR_VALIDATION", "upc must be unique", 422)

    policy = payload.get("availability_policy") or {}
    af = policy.get("available_from")
    au = policy.get("available_until")
    if af is not None and au is not None:
        if not (parse_dt(af) < parse_dt(au)):
            raise errors.ApiError(
                "ERR_VALIDATION", "available_from must be strictly earlier than available_until", 422
            )

    release_date = payload.get("release_date")
    if release_date is not None:
        release_date = iso3(parse_dt(release_date))

    base_price = payload.get("base_price_cents")
    if base_price is not None and base_price < 0:
        raise errors.ApiError("ERR_VALIDATION", "base_price_cents must be >= 0", 422)

    title = new_entity()
    title.update(
        upc=upc,
        title=payload.get("title"),
        artist_name=payload.get("artist_name"),
        product_kind=payload.get("product_kind"),
        genre_tag=payload.get("genre_tag"),
        release_date=release_date,
        base_price_cents=base_price,
        label_account_id=label_account_id,
        availability_policy=policy,
        eligibility_posture="ELIGIBLE",
    )
    db.title_products[title["id"]] = title
    return envelope_ok(ser_title(title), response_type="object", status=201)


@bp.route("/titles", methods=["GET"])
def list_titles():
    require_roles(*ALL_ROLES)
    limit, offset = pagination_params()
    genre_tag = request.args.get("genre_tag")
    product_kind = request.args.get("product_kind")
    label_account_id = request.args.get("label_account_id")
    items = sorted(db.title_products.values(), key=lambda t: (t["created_at"], t["_seq"]))
    if genre_tag is not None:
        items = [t for t in items if t["genre_tag"] == genre_tag]
    if product_kind is not None:
        items = [t for t in items if t["product_kind"] == product_kind]
    if label_account_id is not None:
        items = [t for t in items if t["label_account_id"] == label_account_id]
    page, page_meta = paginate(items, limit, offset)
    return envelope_ok([ser_title(t) for t in page], response_type="array", pagination=page_meta)


@bp.route("/titles/<tid>", methods=["GET"])
def get_title_route(tid):
    require_roles(*ALL_ROLES)
    t = get_title(tid)
    return envelope_ok(ser_title(t), response_type="object")


@bp.route("/titles/<tid>/reinstate", methods=["POST"])
def reinstate_title(tid):
    require_roles("ChartManager")
    t = get_title(tid)
    if t["eligibility_posture"] != "DISQUALIFIED":
        raise errors.invalid_state("Title is not DISQUALIFIED")
    t["eligibility_posture"] = "ELIGIBLE"
    touch(t)
    return envelope_ok(ser_title(t), response_type="object", status=200)


# ---------------------------------------------------------------------------
# Sale batches
# ---------------------------------------------------------------------------

@bp.route("/titles/<tid>/sale-batches", methods=["POST"])
def create_sale_batch(tid):
    user_id, role = require_roles("ChartOps", "LabelRep")
    t = get_title(tid)
    payload = get_json()

    # LabelRep ownership: X-User-ID must be the owning label account id
    if role == "LabelRep" and t["label_account_id"] != user_id:
        raise errors.unauthorized("LabelRep may only record batches for their own titles")

    week_id = payload.get("chart_week_id")
    week = db.chart_weeks.get(week_id)
    if week is None:
        raise errors.not_found("ChartWeek not found")

    if t["product_kind"] != "ALBUM":
        raise errors.bundle_channel_invalid()

    channel = payload.get("channel")
    quantity = payload.get("quantity")
    buyer_key = payload.get("buyer_key")

    batch = new_entity()
    batch.update(
        title_product_id=t["id"],
        channel=channel,
        quantity=quantity,
        buyer_key=buyer_key,
        chart_week_id=week["id"],
        countable_units=0,
        review_status="CLEARED",
    )
    db.sale_batches[batch["id"]] = batch

    # allocate countable units for the group
    allocate_buyer_group(buyer_key, t["id"], week["id"])

    return envelope_ok(ser_batch(batch), response_type="object", status=201)


@bp.route("/titles/<tid>/sale-batches", methods=["GET"])
def list_sale_batches(tid):
    require_roles("PlatformAdmin", "ChartManager", "ChartOps", "LabelRep", "Investigator")
    t = get_title(tid)
    limit, offset = pagination_params()
    week_filter = request.args.get("chart_week_id")
    items = sorted(
        [b for b in db.sale_batches.values() if b["title_product_id"] == t["id"]],
        key=lambda b: (b["created_at"], b["_seq"]),
    )
    if week_filter:
        items = [b for b in items if b["chart_week_id"] == week_filter]
    page, page_meta = paginate(items, limit, offset)
    return envelope_ok([ser_batch(b) for b in page], response_type="array", pagination=page_meta)


# ---------------------------------------------------------------------------
# Reverse reachability
# ---------------------------------------------------------------------------

@bp.route("/titles/<tid>/reports", methods=["GET"])
def list_title_reports(tid):
    require_roles(*REPORT_READ_ROLES)
    t = get_title(tid)
    limit, offset = pagination_params()
    week_filter = request.args.get("chart_week_id")
    items = sorted(
        [r for r in db.consumption_reports.values() if r["title_product_id"] == t["id"]],
        key=lambda r: (r["created_at"], r["_seq"]),
    )
    if week_filter:
        items = [r for r in items if r["chart_week_id"] == week_filter]
    page, page_meta = paginate(items, limit, offset)
    return envelope_ok([ser_report(r) for r in page], response_type="array", pagination=page_meta)


@bp.route("/titles/<tid>/entries", methods=["GET"])
def list_title_entries(tid):
    require_roles(*ALL_ROLES)
    t = get_title(tid)
    limit, offset = pagination_params()
    items = sorted(
        [e for e in db.chart_entries.values() if e["title_product_id"] == t["id"]],
        key=lambda e: (e["created_at"], e["_seq"]),
    )
    page, page_meta = paginate(items, limit, offset)
    return envelope_ok([ser_entry(e) for e in page], response_type="array", pagination=page_meta)


@bp.route("/titles/<tid>/signals", methods=["GET"])
def list_title_signals(tid):
    require_roles(*REPORT_READ_ROLES)
    t = get_title(tid)
    limit, offset = pagination_params()
    status_filter = request.args.get("status")
    items = sorted(
        [s for s in db.manipulation_signals.values() if s["title_product_id"] == t["id"]],
        key=lambda s: (s["created_at"], s["_seq"]),
    )
    if status_filter:
        items = [s for s in items if s["status"] == status_filter]
    page, page_meta = paginate(items, limit, offset)
    return envelope_ok([ser_signal(s) for s in page], response_type="array", pagination=page_meta)


@bp.route("/titles/<tid>/disputes", methods=["GET"])
def list_title_disputes(tid):
    require_roles("PlatformAdmin", "ChartManager", "ChartOps", "LabelRep", "Investigator")
    t = get_title(tid)
    limit, offset = pagination_params()
    items = sorted(
        [d for d in db.genre_disputes.values() if d["title_product_id"] == t["id"]],
        key=lambda d: (d["created_at"], d["_seq"]),
    )
    page, page_meta = paginate(items, limit, offset)
    return envelope_ok([ser_dispute(d) for d in page], response_type="array", pagination=page_meta)
