"""Consortium invoice generation (waterfall allocation) and lifecycle."""
from flask import Blueprint, request
from db import stores
from middleware import require_roles
from response import success, paginate
from timeutil import parse_iso, round_half_up
from engine import (
    new_id, touch_common, require_body, req_datetime,
    get_consortium, get_invoice, serialize,
)
from errors import (
    err, ERR_NOT_FOUND, ERR_INVOICE_NOT_FOUND, ERR_FORBIDDEN,
    ERR_INVOICE_INVALID_STATE,
)

bp = Blueprint("invoices", __name__)


def _compute_lines(consortium_id, period_start, period_end):
    consortium = stores["consortiums"][consortium_id]
    lines = {}

    def add(lib_id, cents):
        if cents:
            lines[lib_id] = lines.get(lib_id, 0) + cents

    # shared-title allocation
    for order in stores["orders"].values():
        if order["status"] != "FULFILLED":
            continue
        title = stores["titles"].get(order["title_id"])
        if title is None or title["consortium_id"] != consortium_id:
            continue
        if title["sharing_scope"] != "CONSORTIUM":
            continue
        if not (period_start <= parse_iso(order["updated_at"]) < period_end):
            continue
        T = order["invoiced_cost_cents"] or 0
        host = order["library_id"]
        counts = {}
        for ev in stores["events"].values():
            if ev["event_type"] != "CHECKOUT" or ev["title_id"] != title["id"]:
                continue
            if period_start <= parse_iso(ev["occurred_at"]) < period_end:
                counts[ev["library_id"]] = counts.get(ev["library_id"], 0) + 1
        total_counts = sum(counts.values())
        floor = round_half_up(T * consortium["host_share_floor_pct"])
        host_prop = round_half_up(T * counts.get(host, 0) / max(total_counts, 1))
        host_share = max(host_prop, floor)
        add(host, host_share)
        remainder = T - host_share
        non_host = [(lid, c) for lid, c in counts.items() if lid != host and c > 0]
        non_host.sort(key=lambda t: (-t[1], stores["libraries"][t[0]]["created_at"],
                                     stores["libraries"][t[0]]["_seq"]))
        if not non_host:
            # No non-host usage: the host absorbs the full T — the floor does
            # not shrink the host's share below the invoiced cost.
            lines[host] = lines.get(host, 0) - host_share + T
        else:
            denom = sum(c for _, c in non_host)
            shares = []
            for lid, c in non_host:
                shares.append([lid, round_half_up(remainder * c / denom)])
            residual = remainder - sum(s for _, s in shares)
            if residual != 0:
                shares[0][1] += residual
            for lid, s in shares:
                add(lid, s)

    # CPC pass-through: charge follows the patron's home library
    for ev in stores["events"].values():
        if ev["event_type"] != "CHECKOUT" or not ev.get("charge_cents"):
            continue
        loan = stores["loans"].get(ev["loan_id"])
        lic = stores["licenses"].get(loan["license_id"]) if loan else None
        if lic is None or lic["model"] != "COST_PER_CIRC":
            continue
        if period_start <= parse_iso(ev["occurred_at"]) < period_end:
            add(ev["library_id"], ev["charge_cents"])

    out = [{"library_id": lid, "share_cents": cents} for lid, cents in lines.items() if cents != 0]
    out.sort(key=lambda l: (stores["libraries"][l["library_id"]]["created_at"],
                            stores["libraries"][l["library_id"]]["_seq"]))
    return out


@bp.post("/lending/consortiums/<cid>/invoices/generate")
def generate_invoice(cid):
    body = require_body()
    period_start = req_datetime(body, "period_start")
    period_end = req_datetime(body, "period_end")
    require_roles({"ConsortiumAdmin"})
    get_consortium(cid, ERR_NOT_FOUND)
    lines = _compute_lines(cid, period_start, period_end)
    inv = {
        "id": new_id(),
        "consortium_id": cid,
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "lines": lines,
        "total_cents": sum(l["share_cents"] for l in lines),
        "status": "DRAFT",
    }
    touch_common(inv, created=True)
    inv["_seq"] = len(stores["invoices"])
    inv["_period_start"] = period_start
    inv["_period_end"] = period_end
    stores["invoices"][inv["id"]] = inv
    return success(serialize(inv), 201)


@bp.get("/lending/consortiums/<cid>/invoices")
def list_invoices(cid):
    require_roles({"ConsortiumAdmin", "LibraryAdmin", "SystemAnalyst"})
    get_consortium(cid, ERR_NOT_FOUND)
    status = request.args.get("status")
    items = [i for i in stores["invoices"].values() if i["consortium_id"] == cid]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    items.sort(key=lambda i: (i["created_at"], i["_seq"]))
    page, meta = paginate([serialize(i) for i in items], request.args)
    return success(page, 200, meta)


@bp.get("/lending/consortium-invoices/<iid>")
def read_invoice(iid):
    require_roles({"ConsortiumAdmin", "LibraryAdmin", "SystemAnalyst"})
    inv = get_invoice(iid, ERR_INVOICE_NOT_FOUND)
    return success(serialize(inv))


@bp.post("/lending/consortium-invoices/<iid>/issue")
def issue_invoice(iid):
    require_roles({"ConsortiumAdmin"})
    inv = get_invoice(iid, ERR_INVOICE_NOT_FOUND)
    if inv["status"] not in ("DRAFT", "DISPUTED"):
        raise err(ERR_INVOICE_INVALID_STATE, "invoice is not DRAFT or DISPUTED")
    if inv["status"] == "DISPUTED":
        inv["lines"] = _compute_lines(inv["consortium_id"], inv["_period_start"], inv["_period_end"])
        inv["total_cents"] = sum(l["share_cents"] for l in inv["lines"])
    inv["status"] = "ISSUED"
    touch_common(inv)
    return success(serialize(inv))


@bp.post("/lending/consortium-invoices/<iid>/dispute")
def dispute_invoice(iid):
    if request.is_json:
        request.get_json(silent=True)
    role, uid = require_roles({"LibraryAdmin"})
    inv = get_invoice(iid, ERR_INVOICE_NOT_FOUND)
    is_member = any(l["consortium_id"] == inv["consortium_id"] and l["id"] == uid
                    for l in stores["libraries"].values())
    if not is_member:
        raise err(ERR_FORBIDDEN, "only a billed member library may dispute")
    if inv["status"] != "ISSUED":
        raise err(ERR_INVOICE_INVALID_STATE, "invoice is not ISSUED")
    inv["status"] = "DISPUTED"
    touch_common(inv)
    return success(serialize(inv))


@bp.post("/lending/consortium-invoices/<iid>/settle")
def settle_invoice(iid):
    require_roles({"ConsortiumAdmin"})
    inv = get_invoice(iid, ERR_INVOICE_NOT_FOUND)
    if inv["status"] != "ISSUED":
        raise err(ERR_INVOICE_INVALID_STATE, "invoice is not ISSUED")
    inv["status"] = "SETTLED"
    touch_common(inv)
    return success(serialize(inv))
