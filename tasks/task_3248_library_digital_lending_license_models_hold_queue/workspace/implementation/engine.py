"""Core entity helpers, serializers, event writer, and availability/wait calculations."""
import uuid
from datetime import timedelta
from flask import request
from db import stores, _event_seq
from timeutil import CLOCK, fmt_ts, parse_iso, round_half_up
from errors import err, ERR_INVALID_REQUEST


# ---------------------------------------------------------------- utilities

def new_id():
    return str(uuid.uuid4())


def now():
    return CLOCK.now()


def touch_common(rec, created=False):
    ts = fmt_ts(now())
    if created:
        rec["created_at"] = ts
        rec["updated_at"] = ts
        rec["version"] = 1
    else:
        rec["updated_at"] = ts
        rec["version"] = rec.get("version", 1) + 1


def require_body():
    if not request.is_json:
        raise err(ERR_INVALID_REQUEST, "request body must be JSON")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


def req_field(body, name, types, enums=None, allow_null=False):
    if name not in body:
        raise err(ERR_INVALID_REQUEST, f"missing required field: {name}")
    v = body[name]
    if v is None:
        if allow_null:
            return None
        raise err(ERR_INVALID_REQUEST, f"field {name} may not be null")
    if not isinstance(v, types) or (isinstance(v, bool) and bool not in types):
        raise err(ERR_INVALID_REQUEST, f"field {name} has wrong type")
    if enums is not None and v not in enums:
        raise err(ERR_INVALID_REQUEST, f"field {name} has unknown enum member")
    return v


def opt_field(body, name, types, enums=None, default=None, allow_null=True):
    if name not in body:
        return default
    v = body[name]
    if v is None:
        if allow_null:
            return None
        raise err(ERR_INVALID_REQUEST, f"field {name} may not be null")
    if not isinstance(v, types) or (isinstance(v, bool) and bool not in types):
        raise err(ERR_INVALID_REQUEST, f"field {name} has wrong type")
    if enums is not None and v not in enums:
        raise err(ERR_INVALID_REQUEST, f"field {name} has unknown enum member")
    return v


def req_datetime(body, name):
    v = req_field(body, name, (str,))
    try:
        return parse_iso(v)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, f"field {name} must be ISO-8601 datetime")


# ---------------------------------------------------------------- lookups

def get_consortium(cid, spec):
    c = stores["consortiums"].get(cid)
    if c is None:
        raise err(spec, "consortium not found")
    return c


def get_library(lid, spec):
    l = stores["libraries"].get(lid)
    if l is None:
        raise err(spec, "library not found")
    return l


def get_patron(pid, spec):
    p = stores["patrons"].get(pid)
    if p is None:
        raise err(spec, "patron not found")
    return p


def get_title(tid, spec):
    t = stores["titles"].get(tid)
    if t is None:
        raise err(spec, "title not found")
    return t


def get_license(lid, spec):
    lic = stores["licenses"].get(lid)
    if lic is None:
        raise err(spec, "license not found")
    return lic


def get_hold(hid, spec):
    h = stores["holds"].get(hid)
    if h is None:
        raise err(spec, "hold not found")
    return h


def get_loan(lid, spec):
    ln = stores["loans"].get(lid)
    if ln is None:
        raise err(spec, "loan not found")
    return ln


def get_order(oid, spec):
    o = stores["orders"].get(oid)
    if o is None:
        raise err(spec, "order not found")
    return o


def get_fund(fid, spec):
    f = stores["funds"].get(fid)
    if f is None:
        raise err(spec, "fund not found")
    return f


ERR_FUND_NOT_FOUND_SPEC = ("ERR_FUND_NOT_FOUND", 404)


def get_invoice(iid, spec):
    i = stores["invoices"].get(iid)
    if i is None:
        raise err(spec, "invoice not found")
    return i


def get_snapshot(sid, spec):
    s = stores["snapshots"].get(sid)
    if s is None:
        raise err(spec, "snapshot not found")
    return s


# ---------------------------------------------------------------- events

def write_event(library_id, title_id, patron_id, loan_id, hold_id, license_id,
                event_type, charge_cents=0, occurred_at=None):
    ts = occurred_at if occurred_at is not None else now()
    ev = {
        "id": new_id(),
        "library_id": library_id,
        "title_id": title_id,
        "patron_id": patron_id,
        "loan_id": loan_id,
        "hold_id": hold_id,
        "license_id": license_id,
        "event_type": event_type,
        "occurred_at": fmt_ts(ts),
        "charge_cents": charge_cents,
        "created_at": fmt_ts(ts),
        "_seq": next(_event_seq),
    }
    stores["events"][ev["id"]] = ev
    return ev


def serialize_event(ev):
    return {k: v for k, v in ev.items() if not k.startswith("_")}


# ---------------------------------------------------------------- serializers

def serialize(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------- licenses / availability

def consortium_of_title(title):
    return stores["consortiums"].get(title["consortium_id"])


def discounted_cpc_charge(title):
    """Per-event discounted charge, pinned by PRD §2.7:
    round_half_up(cpc_price_per_circ_cents * (1 - cpc_discount_pct)).

    The discount fraction is a decimal input, so the product is computed in
    exact decimal arithmetic from the inputs' canonical decimal forms before
    the half-up rounding — the result never depends on binary float noise.
    """
    from decimal import Decimal
    consortium = consortium_of_title(title)
    pct = consortium["cpc_discount_pct"] if consortium else 0.0
    product = Decimal(str(title["cpc_price_per_circ_cents"])) * (1 - Decimal(str(pct)))
    return round_half_up(product)


def license_visible_to(license_rec, library_id, title):
    if license_rec["library_id"] == library_id:
        return True
    return title["sharing_scope"] == "CONSORTIUM"


def license_has_capacity(license_rec):
    if license_rec["status"] != "ACTIVE":
        return False
    model = license_rec["model"]
    if model == "OCOU":
        return license_rec["copies_on_loan"] + license_rec["_reserved"] < license_rec["copies_total"]
    if model == "METERED_CIRC":
        return license_rec["circs_consumed"] < license_rec["circs_total"]
    if model in ("METERED_TIME", "SIMULTANEOUS_USE"):
        exp = license_rec.get("expires_at_dt")
        return exp is not None and exp > now()
    if model == "COST_PER_CIRC":
        return True  # depletion checked at charge step / epoch
    return False


MODEL_ORDER = {"OCOU": 0, "METERED_TIME": 1, "METERED_CIRC": 2,
               "COST_PER_CIRC": 3, "SIMULTANEOUS_USE": 4}


def select_license(title, library_id, require_capacity=True):
    """Pinned selector: model order, then expires_at ASC nulls-last, then created_at ASC."""
    candidates = []
    for lic in stores["licenses"].values():
        if lic["title_id"] != title["id"] or lic["status"] != "ACTIVE":
            continue
        if not license_visible_to(lic, library_id, title):
            continue
        if require_capacity and not license_has_capacity(lic):
            continue
        exp = lic.get("expires_at_dt")
        exp_key = (1, "") if exp is None else (0, fmt_ts(exp))
        candidates.append((MODEL_ORDER[lic["model"]], exp_key, lic["created_at"], lic["_seq"], lic))
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t[0], t[1], t[2], t[3]))
    return candidates[0][4]


def effective_copies(title, library_id):
    """C per wait_estimate: OCOU copies_total + eligible METERED_CIRC + eligible METERED_TIME."""
    total = 0
    for lic in stores["licenses"].values():
        if lic["title_id"] != title["id"] or lic["status"] != "ACTIVE":
            continue
        if not license_visible_to(lic, library_id, title):
            continue
        if lic["model"] == "OCOU":
            total += lic["copies_total"]
        elif lic["model"] == "METERED_CIRC":
            if lic["circs_consumed"] < lic["circs_total"]:
                total += 1
        elif lic["model"] == "METERED_TIME":
            exp = lic.get("expires_at_dt")
            if exp is not None and exp > now():
                total += 1
    return total


def holds_queue(title_id):
    """PLACED/SUSPENDED holds on the title, ranked placed_at ASC, created_at ASC."""
    hs = [h for h in stores["holds"].values()
          if h["title_id"] == title_id and h["status"] in ("PLACED", "SUSPENDED")]
    hs.sort(key=lambda h: (h["placed_at"], h["created_at"], h["_seq"]))
    return hs


def compute_waits(hold, library, title):
    """(optimistic, pessimistic) integer day counts for a subject hold.

    H is the subject hold's 1-based queue position: the number of
    PLACED/SUSPENDED holds on the title at the subject's position or earlier
    (placed_at ASC, created_at ASC tie-break). A hold with no one ahead still
    waits one full cycle for a copy to free up, so ceil(H/C) never collapses
    to zero for a queued hold.
    """
    H = 0
    for h in holds_queue(hold["title_id"]):
        H += 1
        if h["id"] == hold["id"]:
            break
    C = max(effective_copies(title, hold["library_id"]), 1)
    cycles = -(-H // C)  # ceil
    opt = cycles * library["loan_period_days"]
    pess = cycles * (library["loan_period_days"] + library["max_renewals"] * library["renewal_period_days"])
    return opt, pess


def recompute_waits_for_title(title_id):
    title = stores["titles"].get(title_id)
    if title is None:
        return
    for h in holds_queue(title_id):
        lib = stores["libraries"].get(h["library_id"])
        if lib is None:
            continue
        opt, pess = compute_waits(h, lib, title)
        if h.get("optimistic_wait_days") != opt or h.get("pessimistic_wait_days") != pess:
            h["optimistic_wait_days"] = opt
            h["pessimistic_wait_days"] = pess


# ---------------------------------------------------------------- fund ledger

def recompute_fund(fund):
    committed = 0
    spent = 0
    for o in stores["orders"].values():
        if o["budget_fund_id"] != fund["id"]:
            continue
        if o["status"] == "APPROVED":
            committed += o["estimated_cost_cents"]
        elif o["status"] == "FULFILLED":
            spent += o["invoiced_cost_cents"] or 0
    accrued = 0
    for ev in stores["events"].values():
        if ev["event_type"] != "CHECKOUT" or ev["library_id"] != fund["library_id"]:
            continue
        if not ev.get("charge_cents"):
            continue
        loan = stores["loans"].get(ev["loan_id"])
        lic = stores["licenses"].get(loan["license_id"]) if loan else None
        if lic is None or lic["model"] != "COST_PER_CIRC":
            continue
        ts = parse_iso(ev["occurred_at"])
        if fund["_period_start"] <= ts < fund["_period_end"]:
            accrued += ev["charge_cents"]
    fund["committed_cents"] = committed
    fund["spent_cents"] = spent
    fund["cpc_accrued_cents"] = accrued
    fund["available_committed_cents"] = fund["budget_cents"] - committed - spent - accrued
    fund["available_actual_cents"] = fund["budget_cents"] - spent - accrued


def now_dt():
    return CLOCK.now()


def fund_covering(library_id, ts):
    """The library's OPEN fund whose half-open period contains ts; None if missing."""
    for f in stores["funds"].values():
        if f["library_id"] != library_id or f["status"] != "OPEN":
            continue
        if f["_period_start"] <= ts < f["_period_end"]:
            return f
    return None


def active_loan_count(patron_id):
    return sum(1 for ln in stores["loans"].values()
               if ln["patron_id"] == patron_id and ln["status"] == "ACTIVE")


def active_hold_count(patron_id):
    return sum(1 for h in stores["holds"].values()
               if h["patron_id"] == patron_id and h["status"] in ("PLACED", "READY", "SUSPENDED"))


def sync_patron_counters(patron_id):
    p = stores["patrons"].get(patron_id)
    if p is not None:
        p["active_loan_count"] = active_loan_count(patron_id)
        p["active_hold_count"] = active_hold_count(patron_id)
