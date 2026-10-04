"""Manipulation signals, investigations, and enforcement cascades."""

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
    allocate_buyer_group,
    get_investigation,
    get_signal,
    get_title,
    get_week,
    invalidate_computed_weeks,
    new_entity,
    ser_investigation,
    ser_signal,
)

bp = Blueprint("enforcement", __name__)

READ_ROLES = ("PlatformAdmin", "ChartManager", "ChartOps", "Investigator")

STREAMING_KINDS = {"STREAM_ON_DEMAND_PAID", "STREAM_ON_DEMAND_AD", "STREAM_PROGRAMMED"}
BUNDLE_CHANNELS = {"TICKET_BUNDLE", "MERCH_BUNDLE"}


@bp.route("/manipulation-signals", methods=["POST"])
def create_signal():
    require_roles("ChartOps")
    payload = get_json()
    title_id = payload.get("title_product_id")
    week_id = payload.get("chart_week_id")
    title = db.title_products.get(title_id)
    if title is None:
        raise errors.not_found("TitleProduct not found")
    week = db.chart_weeks.get(week_id)
    if week is None:
        raise errors.not_found("ChartWeek not found")

    signal = new_entity()
    signal.update(
        title_product_id=title["id"],
        chart_week_id=week["id"],
        signal_kind=payload.get("signal_kind"),
        evidence=payload.get("evidence"),
        status="OPEN",
    )
    db.manipulation_signals[signal["id"]] = signal
    return envelope_ok(ser_signal(signal), response_type="object", status=201)


@bp.route("/manipulation-signals", methods=["GET"])
def list_signals():
    require_roles(*READ_ROLES)
    limit, offset = pagination_params()
    title_filter = request.args.get("title_product_id")
    week_filter = request.args.get("chart_week_id")
    status_filter = request.args.get("status")
    items = sorted(db.manipulation_signals.values(), key=lambda s: (s["created_at"], s["_seq"]))
    if title_filter:
        items = [s for s in items if s["title_product_id"] == title_filter]
    if week_filter:
        items = [s for s in items if s["chart_week_id"] == week_filter]
    if status_filter:
        items = [s for s in items if s["status"] == status_filter]
    page, page_meta = paginate(items, limit, offset)
    return envelope_ok([ser_signal(s) for s in page], response_type="array", pagination=page_meta)


@bp.route("/manipulation-signals/<sid>", methods=["GET"])
def get_signal_route(sid):
    require_roles(*READ_ROLES)
    s = get_signal(sid)
    return envelope_ok(ser_signal(s), response_type="object")


@bp.route("/manipulation-signals/<sid>/dismiss", methods=["POST"])
def dismiss_signal(sid):
    require_roles("ChartOps")
    s = get_signal(sid)
    if s["status"] != "OPEN":
        raise errors.invalid_state("Signal is not OPEN")
    s["status"] = "DISMISSED"
    touch(s)
    return envelope_ok(ser_signal(s), response_type="object", status=200)


@bp.route("/manipulation-signals/<sid>/escalate", methods=["POST"])
def escalate_signal(sid):
    user_id, role = require_roles("ChartOps")
    s = get_signal(sid)
    payload = get_json()

    if s["status"] != "OPEN":
        raise errors.invalid_state("Signal is not OPEN")

    title = get_title(s["title_product_id"])
    label = db.label_accounts.get(title["label_account_id"])
    if label is None:
        raise errors.not_found("LabelAccount not found")
    if label["account_status"] != "ACTIVE":
        raise errors.account_suspended("Label account is SUSPENDED")

    # single-investigation uniqueness
    existing = [i for i in db.investigations.values() if i["signal_id"] == s["id"]]
    if existing:
        raise errors.signal_already_escalated()

    assigned_to = payload.get("assigned_to")
    if assigned_to == user_id:
        raise errors.duty_segregation_violation("assigned_to must differ from the escalating user")

    # kind-specific quarantine cascade
    if s["signal_kind"] == "ARTIFICIAL_STREAMING":
        for r in db.consumption_reports.values():
            if (
                r["title_product_id"] == s["title_product_id"]
                and r["chart_week_id"] == s["chart_week_id"]
                and r["component_kind"] in STREAMING_KINDS
                and r["status"] == "ACCEPTED"
            ):
                r["status"] = "QUARANTINED"
                touch(r)
    elif s["signal_kind"] == "BULK_PURCHASE":
        for b in db.sale_batches.values():
            if (
                b["title_product_id"] == s["title_product_id"]
                and b["chart_week_id"] == s["chart_week_id"]
                and b["review_status"] == "CLEARED"
            ):
                b["review_status"] = "UNDER_REVIEW"
                b["countable_units"] = 0
                touch(b)
    elif s["signal_kind"] == "TICKET_BUNDLE_ABUSE":
        for b in db.sale_batches.values():
            if (
                b["title_product_id"] == s["title_product_id"]
                and b["chart_week_id"] == s["chart_week_id"]
                and b["channel"] in BUNDLE_CHANNELS
                and b["review_status"] == "CLEARED"
            ):
                b["review_status"] = "UNDER_REVIEW"
                b["countable_units"] = 0
                touch(b)

    inv = new_entity()
    inv.update(
        signal_id=s["id"],
        assigned_to=assigned_to,
        finding=None,
        notes=None,
        status="OPEN",
    )
    db.investigations[inv["id"]] = inv

    s["status"] = "ESCALATED"
    touch(s)
    return envelope_ok(ser_investigation(inv), response_type="object", status=201)


@bp.route("/investigations", methods=["GET"])
def list_investigations():
    require_roles(*READ_ROLES)
    limit, offset = pagination_params()
    status_filter = request.args.get("status")
    signal_filter = request.args.get("signal_id")
    items = sorted(db.investigations.values(), key=lambda i: (i["created_at"], i["_seq"]))
    if status_filter:
        items = [i for i in items if i["status"] == status_filter]
    if signal_filter:
        items = [i for i in items if i["signal_id"] == signal_filter]
    page, page_meta = paginate(items, limit, offset)
    return envelope_ok([ser_investigation(i) for i in page], response_type="array", pagination=page_meta)


@bp.route("/investigations/<iid>", methods=["GET"])
def get_investigation_route(iid):
    require_roles(*READ_ROLES)
    i = get_investigation(iid)
    return envelope_ok(ser_investigation(i), response_type="object")


@bp.route("/manipulation-signals/<sid>/investigations", methods=["GET"])
def list_signal_investigations(sid):
    require_roles(*READ_ROLES)
    s = get_signal(sid)
    items = sorted(
        [i for i in db.investigations.values() if i["signal_id"] == s["id"]],
        key=lambda i: (i["created_at"], i["_seq"]),
    )
    return envelope_ok([ser_investigation(i) for i in items], response_type="array")


@bp.route("/investigations/<iid>/resolve", methods=["POST"])
def resolve_investigation(iid):
    user_id, role = require_roles("Investigator")
    inv = get_investigation(iid)
    payload = get_json()

    if inv["status"] != "OPEN":
        raise errors.invalid_state("Investigation is not OPEN")

    finding = payload.get("finding")
    notes = payload.get("notes")
    if finding not in ("DISMISSED", "QUARANTINE_REPORTS", "DISQUALIFY"):
        raise errors.ApiError("ERR_VALIDATION", "finding must be DISMISSED, QUARANTINE_REPORTS, or DISQUALIFY", 422)

    # segregation of duties: resolver must be the assigned investigator
    if inv["assigned_to"] != user_id:
        raise errors.duty_segregation_violation("Resolver must be the assigned investigator")

    signal = get_signal(inv["signal_id"])
    title = get_title(signal["title_product_id"])
    week = get_week(signal["chart_week_id"])
    chart_id = week["chart_id"]

    inv["finding"] = finding
    inv["notes"] = notes
    inv["status"] = "CLOSED"
    touch(inv)

    if finding == "DISMISSED":
        # restore quarantined reports to ACCEPTED
        for r in db.consumption_reports.values():
            if (
                r["title_product_id"] == title["id"]
                and r["chart_week_id"] == week["id"]
                and r["status"] == "QUARANTINED"
            ):
                r["status"] = "ACCEPTED"
                touch(r)
        # restore under-review batches to CLEARED and recompute caps
        affected_groups = set()
        for b in db.sale_batches.values():
            if (
                b["title_product_id"] == title["id"]
                and b["chart_week_id"] == week["id"]
                and b["review_status"] == "UNDER_REVIEW"
            ):
                b["review_status"] = "CLEARED"
                touch(b)
                affected_groups.add((b["buyer_key"], b["title_product_id"], b["chart_week_id"]))
        for buyer_key, tid, wid in affected_groups:
            allocate_buyer_group(buyer_key, tid, wid)

    elif finding == "QUARANTINE_REPORTS":
        # ACCEPTED/QUARANTINED reports -> EXCLUDED; UNDER_REVIEW batches -> REJECTED
        for r in db.consumption_reports.values():
            if (
                r["title_product_id"] == title["id"]
                and r["chart_week_id"] == week["id"]
                and r["status"] in ("ACCEPTED", "QUARANTINED")
            ):
                r["status"] = "EXCLUDED"
                touch(r)
        for b in db.sale_batches.values():
            if (
                b["title_product_id"] == title["id"]
                and b["chart_week_id"] == week["id"]
                and b["review_status"] == "UNDER_REVIEW"
            ):
                b["review_status"] = "REJECTED"
                b["countable_units"] = 0
                touch(b)
        invalidate_computed_weeks(chart_id)

    elif finding == "DISQUALIFY":
        # title -> DISQUALIFIED
        title["eligibility_posture"] = "DISQUALIFIED"
        touch(title)
        # all chart entries of the title on the signal's week -> RECURRENT_REMOVED
        for e in db.chart_entries.values():
            if e["chart_week_id"] == week["id"] and e["title_product_id"] == title["id"]:
                e["entry_status"] = "RECURRENT_REMOVED"
                touch(e)
        # ACCEPTED/QUARANTINED reports -> EXCLUDED
        for r in db.consumption_reports.values():
            if (
                r["title_product_id"] == title["id"]
                and r["chart_week_id"] == week["id"]
                and r["status"] in ("ACCEPTED", "QUARANTINED")
            ):
                r["status"] = "EXCLUDED"
                touch(r)
        # UNDER_REVIEW batches -> REJECTED
        for b in db.sale_batches.values():
            if (
                b["title_product_id"] == title["id"]
                and b["chart_week_id"] == week["id"]
                and b["review_status"] == "UNDER_REVIEW"
            ):
                b["review_status"] = "REJECTED"
                b["countable_units"] = 0
                touch(b)
        # label strike
        label = db.label_accounts.get(title["label_account_id"])
        if label is not None:
            label["strike_count"] = label.get("strike_count", 0) + 1
            if label["strike_count"] >= 3 and label["account_status"] == "ACTIVE":
                label["account_status"] = "SUSPENDED"
            touch(label)
        invalidate_computed_weeks(chart_id)

    return envelope_ok(ser_investigation(inv), response_type="object", status=200)


# ---------------------------------------------------------------------------
# Reverse reachability: week-scoped signals
# ---------------------------------------------------------------------------

@bp.route("/chart-weeks/<wid>/signals", methods=["GET"])
def list_week_signals(wid):
    require_roles(*READ_ROLES)
    week = get_week(wid)
    limit, offset = pagination_params()
    items = sorted(
        [s for s in db.manipulation_signals.values() if s["chart_week_id"] == week["id"]],
        key=lambda s: (s["created_at"], s["_seq"]),
    )
    page, page_meta = paginate(items, limit, offset)
    return envelope_ok([ser_signal(s) for s in page], response_type="array", pagination=page_meta)


@bp.route("/chart-weeks/<wid>/sale-batches", methods=["GET"])
def list_week_sale_batches(wid):
    require_roles(*READ_ROLES)
    week = get_week(wid)
    limit, offset = pagination_params()
    review_filter = request.args.get("review_status")
    from services import ser_batch
    items = sorted(
        [b for b in db.sale_batches.values() if b["chart_week_id"] == week["id"]],
        key=lambda b: (b["created_at"], b["_seq"]),
    )
    if review_filter:
        items = [b for b in items if b["review_status"] == review_filter]
    page, page_meta = paginate(items, limit, offset)
    return envelope_ok([ser_batch(b) for b in page], response_type="array", pagination=page_meta)
