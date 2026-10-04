"""Mailing waves: scheduling, manifest, reconciliation; mailing items."""

from flask import Blueprint, request

import db
import domain
from errors import ApiError
from response import ok, created, listing
from validation import (
    require_roles, ALL_ROLES, body, check_allowed, req_month, pagination,
)

bp = Blueprint("waves", __name__, url_prefix="/library")


def get_wave_or_404(wid):
    w = db.waves.get(wid)
    if w is None:
        raise ApiError(404, "ERR_WAVE_NOT_FOUND",
                       "Referenced mailing wave id does not exist")
    return w


def get_item_or_404(iid):
    it = db.items.get(iid)
    if it is None:
        raise ApiError(404, "ERR_ITEM_NOT_FOUND",
                       "Referenced mailing item id does not exist")
    return it


@bp.post("/waves")
def create_wave():
    require_roles("MailOps")
    data = body()
    check_allowed(data, {"mailing_month"})
    month = req_month(data, "mailing_month")
    if month < db.logical_month():
        raise ApiError(422, "ERR_WAVE_MONTH_PAST",
                       "Wave mailing_month is before the current logical month")
    for w in db.waves.values():
        if w["mailing_month"] == month:
            raise ApiError(409, "ERR_WAVE_MONTH_DUPLICATE",
                           "A wave already exists for this mailing_month")
    rec = db.base_record()
    rec.update({
        "mailing_month": month,
        "status": "SCHEDULED",
        "manifested_item_count": 0,
        "returned_item_count": 0,
    })
    db.waves[rec["id"]] = rec
    return created(domain.ser_wave(rec))


def _eligible_children(month):
    """manifest_eligibility_set: status, earlier registration month, age <= 59,
    affiliate operative for the wave month, no prior item for (child, month)."""
    out = []
    for c in db.children.values():
        if c["enrollment_status"] not in domain.ACTIVE_CHILD_STATES:
            continue
        if not (c["registered_month"] < month):
            continue
        band = domain.band_for_age(domain.age_months(c["_birth"], month))
        if band is None:
            continue
        if not domain.operative_for_month(c["affiliate_id"], month):
            continue
        dup = False
        for it in db.items.values():
            if it["child_id"] == c["id"] and it["mailing_month"] == month:
                dup = True
                break
        if dup:
            continue
        out.append((c, band))
    return out


@bp.post("/waves/<wid>/manifest")
def manifest_wave(wid):
    require_roles("MailOps")
    wave = get_wave_or_404(wid)
    if wave["status"] != "SCHEDULED":
        raise ApiError(409, "ERR_INVALID_STATE",
                       "Only a SCHEDULED wave can be manifested")
    month = wave["mailing_month"]
    locked = {}
    for band in domain.BANDS:
        found = None
        for s in db.selections.values():
            if (s["mailing_month"] == month and s["age_band"] == band
                    and s["status"] == "LOCKED"):
                found = s
                break
        if found is None:
            raise ApiError(409, "ERR_MANIFEST_SELECTIONS_INCOMPLETE",
                           "Manifest requires LOCKED selections for all five age bands")
        locked[band] = found
    eligible = _eligible_children(month)
    demand = {}
    for c, band in eligible:
        demand[band] = demand.get(band, 0) + 1
    # Aggregate demand per title so stock can never go negative.
    title_demand = {}
    for band, n in demand.items():
        tid = locked[band]["title_id"]
        title_demand[tid] = title_demand.get(tid, 0) + n
    for tid, n in title_demand.items():
        if domain.stock_on_hand(tid) < n:
            raise ApiError(409, "ERR_INVENTORY_SHORTFALL",
                           "A band's selected title has stock_on_hand below manifest demand")
    count = 0
    for c, band in eligible:
        rec = db.base_record()
        rec.update({
            "wave_id": wid,
            "mailing_month": month,
            "child_id": c["id"],
            "affiliate_id": c["affiliate_id"],
            "selection_id": locked[band]["id"],
            "age_band": band,
            "status": "MAILED",
        })
        db.items[rec["id"]] = rec
        count += 1
    wave["manifested_item_count"] = count
    wave["status"] = "MANIFESTED"
    db.touch(wave)
    return ok(domain.ser_wave(wave))


@bp.post("/waves/<wid>/reconcile")
def reconcile_wave(wid):
    require_roles("MailOps")
    wave = get_wave_or_404(wid)
    if wave["status"] != "MANIFESTED":
        raise ApiError(409, "ERR_INVALID_STATE",
                       "Only a MANIFESTED wave can be reconciled")
    for it in db.items.values():
        if it["wave_id"] == wid and it["status"] == "MAILED":
            it["status"] = "DELIVERED"
            db.touch(it)
    # One DRAFT invoice per affiliate with at least one billable item.
    groups = {}
    order = []
    for it in db.items.values():
        if it["wave_id"] != wid:
            continue
        if it["status"] not in ("MAILED", "DELIVERED"):
            continue
        if it["affiliate_id"] not in groups:
            groups[it["affiliate_id"]] = []
            order.append(it["affiliate_id"])
        groups[it["affiliate_id"]].append(it)
    for aff_id in order:
        aff = db.affiliates.get(aff_id)
        prog = db.state_programs.get(aff["state_program_id"]) if aff else None
        cap = prog["max_state_share_per_book_cents"] if prog else 0
        share_bp = prog["funding_share_bp"] if prog else 0
        gross = 0
        state_total = 0
        for it in groups[aff_id]:
            po = domain.confirmed_order_for_selection(it["selection_id"])
            effective_unit = po["total_cents"] // po["quantity"]
            item_cost = effective_unit + domain.HANDLING_CENTS_PER_BOOK
            gross += item_cost
            capped = min(item_cost, cap)
            state_total += domain.round_half_up_ratio(capped * share_bp, 10000)
        rec = db.base_record()
        rec.update({
            "affiliate_id": aff_id,
            "wave_id": wid,
            "billing_month": wave["mailing_month"],
            "status": "DRAFT",
            "item_count": len(groups[aff_id]),
            "gross_cents": gross,
            "state_share_cents": state_total,
            "local_share_cents": gross - state_total,
            "credit_memo_cents": 0,
            "pricing_variant": "PER_LINE",
        })
        db.invoices[rec["id"]] = rec
    wave["status"] = "RECONCILED"
    db.touch(wave)
    return ok(domain.ser_wave(wave))


@bp.get("/items/<iid>")
def get_item(iid):
    require_roles(*ALL_ROLES)
    return ok(domain.ser_item(get_item_or_404(iid)))


@bp.get("/items")
def list_items():
    require_roles(*ALL_ROLES)
    limit, offset = pagination()
    f_wave = request.args.get("wave_id")
    f_child = request.args.get("child_id")
    f_sel = request.args.get("selection_id")
    f_aff = request.args.get("affiliate_id")
    f_status = request.args.get("status")
    rows = [it for it in db.items.values()
            if (f_wave is None or it["wave_id"] == f_wave)
            and (f_child is None or it["child_id"] == f_child)
            and (f_sel is None or it["selection_id"] == f_sel)
            and (f_aff is None or it["affiliate_id"] == f_aff)
            and (f_status is None or it["status"] == f_status)]
    rows.sort(key=lambda r: r["_seq"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return listing([domain.ser_item(it) for it in page], limit, offset, total)


@bp.post("/items/<iid>/mark-returned")
def mark_returned(iid):
    require_roles("MailOps")
    data = body()
    check_allowed(data, set())
    it = get_item_or_404(iid)
    if it["status"] != "MAILED":
        raise ApiError(409, "ERR_INVALID_STATE",
                       "Only a MAILED item can be marked returned")
    wave = db.waves[it["wave_id"]]
    if wave["status"] != "MANIFESTED":
        raise ApiError(409, "ERR_INVALID_STATE",
                       "Returns are only accepted while the wave is MANIFESTED")
    it["status"] = "RETURNED_UNDELIVERABLE"
    db.touch(it)
    wave["returned_item_count"] += 1
    db.touch(wave)
    child = db.children[it["child_id"]]
    child["consecutive_returns"] += 1
    if child["enrollment_status"] in domain.ACTIVE_CHILD_STATES:
        if child["consecutive_returns"] >= domain.RETURN_AUTO_UNENROLL_THRESHOLD:
            child["enrollment_status"] = "UNENROLLED"
            child["unenroll_reason"] = "UNDELIVERABLE"
        else:
            child["enrollment_status"] = "UNDELIVERABLE_HOLD"
    db.touch(child)
    return ok(domain.ser_item(it))
