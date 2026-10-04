"""Genre dispute routes and chart-scoped dispute listing."""

from flask import Blueprint, request

import errors
from db import db
from helpers import (
    envelope_ok,
    get_json,
    paginate,
    pagination_params,
    require_roles,
    touch,
)
from services import (
    get_chart,
    get_dispute,
    get_title,
    new_entity,
    ser_dispute,
    ser_entry,
)

bp = Blueprint("misc", __name__)

READ_ROLES = ("PlatformAdmin", "ChartManager", "ChartOps", "LabelRep", "Investigator")


@bp.route("/genre-disputes", methods=["POST"])
def create_dispute():
    user_id, role = require_roles("LabelRep")
    payload = get_json()

    title_id = payload.get("title_product_id")
    chart_id = payload.get("chart_id")
    filed_by_label_id = payload.get("filed_by_label_id")
    claimed_genre = payload.get("claimed_genre")

    title = db.title_products.get(title_id)
    if title is None:
        raise errors.not_found("TitleProduct not found")
    chart = db.charts.get(chart_id)
    if chart is None:
        raise errors.not_found("Chart not found")
    label = db.label_accounts.get(filed_by_label_id)
    if label is None:
        raise errors.not_found("LabelAccount not found")

    # ownership: filed_by_label_id must equal title's owning label AND the caller's id
    if filed_by_label_id != title["label_account_id"] or filed_by_label_id != user_id:
        raise errors.unauthorized("Filing label must own the title and match the caller")

    # business constraint: GENRE chart, claimed_genre != title.genre_tag
    if chart["chart_scope"] != "GENRE":
        raise errors.dispute_invalid("Disputes may only be filed against GENRE charts")
    if claimed_genre == title["genre_tag"]:
        raise errors.dispute_invalid("claimed_genre must differ from the title's current genre_tag")

    dispute = new_entity()
    dispute.update(
        title_product_id=title["id"],
        chart_id=chart["id"],
        filed_by_label_id=filed_by_label_id,
        claimed_genre=claimed_genre,
        resolution=None,
        status="FILED",
        reentries_processed=False,
    )
    db.genre_disputes[dispute["id"]] = dispute
    return envelope_ok(ser_dispute(dispute), response_type="object", status=201)


@bp.route("/genre-disputes", methods=["GET"])
def list_disputes():
    require_roles(*READ_ROLES)
    limit, offset = pagination_params()
    title_filter = request.args.get("title_product_id")
    chart_filter = request.args.get("chart_id")
    status_filter = request.args.get("status")
    items = sorted(db.genre_disputes.values(), key=lambda d: (d["created_at"], d["_seq"]))
    if title_filter:
        items = [d for d in items if d["title_product_id"] == title_filter]
    if chart_filter:
        items = [d for d in items if d["chart_id"] == chart_filter]
    if status_filter:
        items = [d for d in items if d["status"] == status_filter]
    page, page_meta = paginate(items, limit, offset)
    return envelope_ok([ser_dispute(d) for d in page], response_type="array", pagination=page_meta)


@bp.route("/genre-disputes/<did>", methods=["GET"])
def get_dispute_route(did):
    require_roles(*READ_ROLES)
    d = get_dispute(did)
    return envelope_ok(ser_dispute(d), response_type="object")


@bp.route("/genre-disputes/<did>/review", methods=["POST"])
def review_dispute(did):
    require_roles("ChartOps")
    d = get_dispute(did)
    if d["status"] != "FILED":
        raise errors.invalid_state("Dispute is not FILED")
    d["status"] = "UNDER_REVIEW"
    touch(d)
    return envelope_ok(ser_dispute(d), response_type="object", status=200)


@bp.route("/genre-disputes/<did>/resolve", methods=["POST"])
def resolve_dispute(did):
    require_roles("ChartManager")
    d = get_dispute(did)
    payload = get_json()
    resolution = payload.get("resolution")

    if d["status"] != "UNDER_REVIEW":
        raise errors.invalid_state("Dispute is not UNDER_REVIEW")

    if resolution not in ("UPHOLD", "RECLASSIFY"):
        raise errors.ApiError("ERR_VALIDATION", "resolution must be UPHOLD or RECLASSIFY", 422)

    chart = get_chart(d["chart_id"])
    title = get_title(d["title_product_id"])

    if resolution == "UPHOLD":
        d["resolution"] = "UPHOLD"
        d["status"] = "RESOLVED_UPHELD"
        touch(d)
        return envelope_ok(ser_dispute(d), response_type="object", status=200)

    # RECLASSIFY
    new_genre_tag = payload.get("new_genre_tag")
    if new_genre_tag != chart["genre_tag"]:
        raise errors.reclassification_target_mismatch()

    title["genre_tag"] = new_genre_tag
    touch(title)

    d["resolution"] = "RECLASSIFY"
    d["status"] = "RESOLVED_RECLASSIFIED"
    d["reentries_processed"] = True

    # re-entry evaluation cascade: re-evaluate RECURRENT_REMOVED entries on this chart
    from services import get_rule, title_eligible_for
    rule = get_rule(chart["recurrent_rule_id"])
    for e in db.chart_entries.values():
        if e["entry_status"] != "RECURRENT_REMOVED":
            continue
        week = db.chart_weeks.get(e["chart_week_id"])
        if week is None or week["chart_id"] != chart["id"]:
            continue
        entry_title = db.title_products.get(e["title_product_id"])
        if entry_title is None:
            continue
        # title must now be eligible on this chart/week
        first_entry = False  # it already had an entry
        if not title_eligible_for(chart, entry_title, week, first_entry):
            continue
        if e["rank"] is not None and e["rank"] <= rule["reentry_min_rank"]:
            e["entry_status"] = "RE_ENTERED"
            touch(e)

    touch(d)
    return envelope_ok(ser_dispute(d), response_type="object", status=200)


@bp.route("/charts/<cid>/disputes", methods=["GET"])
def list_chart_disputes(cid):
    require_roles(*READ_ROLES)
    chart = get_chart(cid)
    limit, offset = pagination_params()
    items = sorted(
        [d for d in db.genre_disputes.values() if d["chart_id"] == chart["id"]],
        key=lambda d: (d["created_at"], d["_seq"]),
    )
    page, page_meta = paginate(items, limit, offset)
    return envelope_ok([ser_dispute(d) for d in page], response_type="array", pagination=page_meta)
