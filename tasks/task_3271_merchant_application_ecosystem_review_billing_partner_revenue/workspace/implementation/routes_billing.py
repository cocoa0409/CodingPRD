"""Routes: billing charges, invoices, support tickets, logical clock."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import ok_object, ok_list, paginate, ApiError
from middleware import (
    require_role, get_or_404, json_body, require_fields, touch, new_entity,
)
import services as svc

bp = Blueprint("billing", __name__)

CHARGE_TYPES = {"RECURRING", "USAGE", "ONE_TIME"}
SEVERITIES = {"LOW": 72, "MEDIUM": 48, "HIGH": 24}
UNINSTALLING = {"UNINSTALLING", "UNINSTALLED"}


# ---------------------------------------------------------------------------
# Billing charges
# ---------------------------------------------------------------------------

@bp.route("/installations/<iid>/billing-charges", methods=["POST"])
def create_charge(iid):
    uid, _ = require_role("Developer")
    inst = get_or_404(db.installations, iid, "installation")
    if uid != svc.developer_id_of_app(inst["app_id"]):
        raise ApiError("ERR_UNAUTHORIZED", 403, "developer must own the app")
    if inst["status"] in UNINSTALLING:
        raise ApiError("ERR_UNINSTALL_IN_PROGRESS", 409, "installation is being uninstalled")
    body = json_body()
    require_fields(body, "charge_type", "base_amount_cents", "description")
    charge_type = body["charge_type"]
    if charge_type not in CHARGE_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid charge_type")
    discount_code = body.get("discount_code")
    if discount_code and charge_type != "ONE_TIME":
        raise ApiError("ERR_DISCOUNT_NOT_APPLICABLE", 422,
                       "discount_code honored only on ONE_TIME charges")
    base = body["base_amount_cents"]
    if not isinstance(base, int) or isinstance(base, bool) or base <= 0:
        raise ApiError("ERR_INVALID_AMOUNT", 422, "base_amount_cents must be a positive integer")
    now = db.clock.now()
    effective_base = base
    capped_at = None
    if charge_type == "USAGE":
        if inst["installed_at"]:
            installed = db.parse_dt(inst["installed_at"])
            if now < installed + timedelta(days=30):
                days = int((now - installed).total_seconds() // 86400)
                days = min(days, 30)
                capped = svc.round_half_up(base * days / 30)
                effective_base = min(base, capped)
            capped_at = db.fmt_dt(installed + timedelta(days=30))
    if effective_base < 0:
        raise ApiError("ERR_INVALID_AMOUNT", 422, "proration produced a negative amount")
    discount = 0
    if charge_type == "ONE_TIME" and discount_code == "LAUNCH10":
        discount = svc.round_half_up(effective_base * 0.10)
    final = effective_base - discount
    app = db.apps.get(inst["app_id"])
    dev = db.developers.get(app["developer_id"]) if app else None
    tier = svc.tier_for_gross(dev["lifetime_gross_cents"]) if dev else "T0"
    share, net = svc.compute_share(final, tier)
    c = new_entity()
    c.update({
        "installation_id": iid,
        "billing_cycle": db.cycle_of(now),
        "charge_type": charge_type,
        "status": "PENDING",
        "base_amount_cents": effective_base,
        "discount_code": discount_code,
        "discount_amount_cents": discount,
        "final_amount_cents": final,
        "platform_share_cents": share,
        "developer_net_cents": net,
        "description": body["description"],
        "capped_at": capped_at,
    })
    db.charges[c["id"]] = c
    return ok_object(svc.serialize_charge(c), 201)


@bp.route("/installations/<iid>/billing-charges", methods=["GET"])
def list_charges(iid):
    uid, role = require_role("PlatformAdmin", "Developer", "Merchant")
    inst = get_or_404(db.installations, iid, "installation")
    if role == "Merchant" and uid != inst["merchant_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not your installation")
    if role == "Developer" and uid != svc.developer_id_of_app(inst["app_id"]):
        raise ApiError("ERR_UNAUTHORIZED", 403, "not your app's installation")
    items = [svc.serialize_charge(c) for c in db.charges.values()
             if c["installation_id"] == iid]
    if request.args.get("status"):
        items = [c for c in items if c["status"] == request.args["status"]]
    if request.args.get("charge_type"):
        items = [c for c in items if c["charge_type"] == request.args["charge_type"]]
    if request.args.get("billing_cycle"):
        items = [c for c in items if c["billing_cycle"] == request.args["billing_cycle"]]
    items.sort(key=lambda c: c["created_at"])
    page, limit, offset, total = paginate(items, request.args)
    return ok_list(page, limit, offset, total)


@bp.route("/billing-charges/<cid>", methods=["GET"])
def get_charge(cid):
    uid, role = require_role("PlatformAdmin", "Developer", "Merchant")
    c = get_or_404(db.charges, cid, "charge")
    inst = db.installations.get(c["installation_id"])
    if inst:
        if role == "Merchant" and uid != inst["merchant_id"]:
            raise ApiError("ERR_UNAUTHORIZED", 403, "not your installation")
        if role == "Developer" and uid != svc.developer_id_of_app(inst["app_id"]):
            raise ApiError("ERR_UNAUTHORIZED", 403, "not your app's installation")
    return ok_object(svc.serialize_charge(c))


def _charge_and_install(cid):
    c = get_or_404(db.charges, cid, "charge")
    inst = db.installations.get(c["installation_id"])
    return c, inst


@bp.route("/billing-charges/<cid>/approve", methods=["POST"])
def approve_charge(cid):
    uid, _ = require_role("Merchant")
    c, inst = _charge_and_install(cid)
    if inst and uid != inst["merchant_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not your installation")
    if c["status"] != "PENDING":
        raise ApiError("ERR_CHARGE_NOT_PENDING", 409, "charge is not PENDING")
    if inst and inst["status"] not in ("ACTIVE", "RECONSENT_REQUIRED"):
        raise ApiError("ERR_UNINSTALL_IN_PROGRESS", 409,
                       "installation not in an approvable state")
    c["status"] = "APPROVED"
    touch(c)
    return ok_object(svc.serialize_charge(c))


@bp.route("/billing-charges/<cid>/decline", methods=["POST"])
def decline_charge(cid):
    uid, _ = require_role("Merchant")
    c, inst = _charge_and_install(cid)
    if inst and uid != inst["merchant_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not your installation")
    if c["status"] != "PENDING":
        raise ApiError("ERR_CHARGE_NOT_PENDING", 409, "charge is not PENDING")
    c["status"] = "DECLINED"
    touch(c)
    return ok_object(svc.serialize_charge(c))


@bp.route("/billing-charges/<cid>/reverse", methods=["POST"])
def reverse_charge(cid):
    require_role("PlatformAdmin")
    c, inst = _charge_and_install(cid)
    if c["status"] not in ("PENDING", "INVOICED"):
        raise ApiError("ERR_INVALID_STATE", 409, "charge cannot be reversed from this state")
    developer_id = svc.developer_id_of_installation(c["installation_id"])
    if c["status"] == "INVOICED":
        inv = _invoice_for_charge(c, inst)
        if inv and inv["status"] != "ISSUED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "owning invoice is not ISSUED (already paid or void)")
        c["status"] = "REVERSED"
        touch(c)
        if developer_id:
            svc.append_ledger(developer_id, c["id"], "REVERSAL",
                              -c["final_amount_cents"], "FINAL", c["billing_cycle"])
            svc.recompute_lifetime_gross(developer_id)
        if inv:
            svc.recompute_invoice_total(inv)
            touch(inv)
    else:
        c["status"] = "REVERSED"
        touch(c)
    return ok_object(svc.serialize_charge(c))


def _invoice_for_charge(charge, inst):
    for inv in db.invoices.values():
        if inv["merchant_id"] == inst["merchant_id"] and inv["cycle"] == charge["billing_cycle"]:
            return inv
    return None


@bp.route("/billing-charges/<cid>/ledger-entries", methods=["GET"])
def charge_ledger(cid):
    require_role("PlatformAdmin", "Developer")
    get_or_404(db.charges, cid, "charge")
    items = [svc.serialize_ledger_entry(le) for le in db.ledger_entries.values()
             if le["charge_id"] == cid]
    items.sort(key=lambda le: le["created_at"])
    page, limit, offset, total = paginate(items, request.args)
    return ok_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

@bp.route("/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    uid, role = require_role("PlatformAdmin", "Merchant")
    inv = get_or_404(db.invoices, iid, "invoice")
    if role == "Merchant" and uid != inv["merchant_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not your invoice")
    return ok_object(svc.serialize_invoice(inv))


def _charges_for_invoice(inv, statuses=None):
    out = []
    for c in db.charges.values():
        if c["billing_cycle"] != inv["cycle"]:
            continue
        inst = db.installations.get(c["installation_id"])
        if not inst or inst["merchant_id"] != inv["merchant_id"]:
            continue
        if statuses and c["status"] not in statuses:
            continue
        out.append(c)
    # §3.8's transition list ("every matching APPROVED charge transitions
    # ... each such charge's platform_share_cents ... finalized per §3.6
    # using the app's revenue_share_tier in force at invoice time") reads as
    # a sequential per-charge evaluation; process in creation order so the
    # running tier base (§2.12 lifetime gross over INVOICED/SETTLED charges)
    # accumulates deterministically.
    out.sort(key=lambda c: (db.parse_dt(c["created_at"]), c["id"]))
    return out


@bp.route("/invoices/<iid>/issue", methods=["POST"])
def issue_invoice(iid):
    require_role("PlatformAdmin")
    inv = get_or_404(db.invoices, iid, "invoice")
    if inv["status"] != "OPEN":
        raise ApiError("ERR_INVOICE_NOT_ISSUABLE", 409, "invoice is not OPEN")
    body = json_body()
    expected = body.get("expected_invoice_version")
    if expected is not None and expected != inv["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_invoice_version mismatch")
    approved = _charges_for_invoice(inv, {"APPROVED"})
    if not approved:
        raise ApiError("ERR_INVALID_AMOUNT", 422,
                       "no APPROVED charges for this cycle")
    # PRD §2.12 + §3.6: the tier "in force at the moment the charge is
    # invoiced" is derived from lifetime_gross_cents, and lifetime gross is
    # defined over charges whose status is INVOICED or SETTLED. This issue
    # action transitions these charges to INVOICED in the same step, so the
    # tier base must include this batch's final amounts (simulating the
    # all-charges-invoiced state) — finalize each share against the running
    # gross.
    running_gross = {}
    for c in approved:
        developer_id = svc.developer_id_of_installation(c["installation_id"])
        if developer_id:
            running_gross.setdefault(
                developer_id, db.developers[developer_id]["lifetime_gross_cents"])
            # At the moment this charge is invoiced it is itself INVOICED,
            # so its final_amount_cents counts toward the §2.12 gross base
            # (as do the amounts of charges already transitioned by this
            # same issue action).
            running_gross[developer_id] += c["final_amount_cents"]
        svc.finalize_charge_share(
            c, gross_override=running_gross.get(developer_id))
        c["status"] = "INVOICED"
        touch(c)
        if developer_id:
            svc.append_ledger(developer_id, c["id"], "ACCRUAL",
                              c["final_amount_cents"], "PROVISIONAL", c["billing_cycle"])
    inv["status"] = "ISSUED"
    inv["issued_at"] = db.fmt_dt(db.clock.now())
    svc.recompute_invoice_total(inv)
    touch(inv)
    for developer_id in {svc.developer_id_of_installation(c["installation_id"]) for c in approved}:
        if developer_id:
            svc.recompute_lifetime_gross(developer_id)
    return ok_object(svc.serialize_invoice(inv))


@bp.route("/invoices/<iid>/mark-paid", methods=["POST"])
def mark_paid(iid):
    require_role("PlatformAdmin")
    inv = get_or_404(db.invoices, iid, "invoice")
    if inv["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409, "invoice is not ISSUED")
    invoiced = _charges_for_invoice(inv, {"INVOICED"})
    for c in invoiced:
        c["status"] = "SETTLED"
        touch(c)
    developers = set()
    for c in invoiced:
        developer_id = svc.developer_id_of_installation(c["installation_id"])
        if developer_id:
            developers.add(developer_id)
            svc.append_ledger(developer_id, c["id"], "ACCRUAL",
                              c["final_amount_cents"], "FINAL", c["billing_cycle"])
    inv["status"] = "PAID"
    touch(inv)
    for developer_id in developers:
        svc.recompute_lifetime_gross(developer_id)
    return ok_object(svc.serialize_invoice(inv))


@bp.route("/invoices/<iid>/void", methods=["POST"])
def void_invoice(iid):
    require_role("PlatformAdmin")
    inv = get_or_404(db.invoices, iid, "invoice")
    if inv["status"] != "OPEN":
        raise ApiError("ERR_INVOICE_NOT_VOIDABLE", 409, "invoice is not OPEN")
    invoiced = _charges_for_invoice(inv, {"INVOICED"})
    if invoiced:
        raise ApiError("ERR_INVOICE_NOT_VOIDABLE", 409,
                       "invoice has INVOICED charges")
    inv["status"] = "VOID"
    touch(inv)
    return ok_object(svc.serialize_invoice(inv))


# ---------------------------------------------------------------------------
# Support tickets
# ---------------------------------------------------------------------------

@bp.route("/apps/<aid>/support-tickets", methods=["POST"])
def create_ticket(aid):
    uid, _ = require_role("Merchant")
    get_or_404(db.apps, aid, "app")
    body = json_body()
    require_fields(body, "merchant_id", "severity")
    merchant = db.merchants.get(body["merchant_id"])
    if merchant is None:
        raise ApiError("ERR_NOT_FOUND", 404, "merchant not found")
    if uid != merchant["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "merchant may only open own tickets")
    if body["severity"] not in SEVERITIES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "severity must be LOW, MEDIUM or HIGH")
    t = new_entity()
    t.update({
        "app_id": aid,
        "merchant_id": merchant["id"],
        "severity": body["severity"],
        "sla_hours": SEVERITIES[body["severity"]],
        "status": "OPEN",
        "opened_at": db.fmt_dt(db.clock.now()),
        "first_response_at": None,
        "resolved_at": None,
        "sla_breached": False,
    })
    db.tickets[t["id"]] = t
    return ok_object(svc.serialize_ticket(t), 201)


@bp.route("/support-tickets/<tid>", methods=["GET"])
def get_ticket(tid):
    uid, role = require_role("PlatformAdmin", "Developer", "Merchant")
    t = get_or_404(db.tickets, tid, "support ticket")
    if role == "Merchant" and uid != t["merchant_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not your ticket")
    if role == "Developer" and uid != svc.developer_id_of_app(t["app_id"]):
        raise ApiError("ERR_UNAUTHORIZED", 403, "not your app's ticket")
    return ok_object(svc.serialize_ticket(t))


@bp.route("/support-tickets/<tid>/respond", methods=["POST"])
def respond_ticket(tid):
    uid, _ = require_role("Developer")
    t = get_or_404(db.tickets, tid, "support ticket")
    if uid != svc.developer_id_of_app(t["app_id"]):
        raise ApiError("ERR_UNAUTHORIZED", 403, "developer must own the app")
    if t["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "ticket is not OPEN")
    t["status"] = "ANSWERED"
    t["first_response_at"] = db.fmt_dt(db.clock.now())
    touch(t)
    return ok_object(svc.serialize_ticket(t))


@bp.route("/support-tickets/<tid>/escalate", methods=["POST"])
def escalate_ticket(tid):
    uid, _ = require_role("Merchant")
    t = get_or_404(db.tickets, tid, "support ticket")
    if uid != t["merchant_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not your ticket")
    if t["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "ticket is not OPEN")
    t["status"] = "ESCALATED"
    t["sla_breached"] = svc.sla_breached(t)
    touch(t)
    return ok_object(svc.serialize_ticket(t))


@bp.route("/support-tickets/<tid>/resolve", methods=["POST"])
def resolve_ticket(tid):
    uid, _ = require_role("Developer")
    t = get_or_404(db.tickets, tid, "support ticket")
    if uid != svc.developer_id_of_app(t["app_id"]):
        raise ApiError("ERR_UNAUTHORIZED", 403, "developer must own the app")
    if t["status"] not in ("ANSWERED", "ESCALATED", "DISPUTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "ticket cannot be resolved from this state")
    from_state = t["status"]
    t["status"] = "RESOLVED"
    t["resolved_at"] = db.fmt_dt(db.clock.now())
    breached = svc.sla_breached(t)
    newly_breached = breached and not t["sla_breached"]
    t["sla_breached"] = breached
    if from_state == "ESCALATED" and breached:
        svc.open_strike(t["app_id"], "SUPPORT_BREACH")
    touch(t)
    return ok_object(svc.serialize_ticket(t))


@bp.route("/support-tickets/<tid>/dispute", methods=["POST"])
def dispute_ticket(tid):
    uid, _ = require_role("Merchant")
    t = get_or_404(db.tickets, tid, "support ticket")
    if uid != t["merchant_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not your ticket")
    if t["status"] != "RESOLVED":
        raise ApiError("ERR_INVALID_STATE", 409, "ticket is not RESOLVED")
    now = db.clock.now()
    resolved = db.parse_dt(t["resolved_at"]) if t.get("resolved_at") else now
    if (now - resolved) > timedelta(days=14):
        raise ApiError("ERR_INVALID_STATE", 409, "dispute window (14 days) has closed")
    t["status"] = "DISPUTED"
    touch(t)
    return ok_object(svc.serialize_ticket(t))


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_role("PlatformAdmin")
    body = json_body()
    require_fields(body, "to_iso8601")
    try:
        dt = db.parse_dt(body["to_iso8601"])
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid to_iso8601")
    db.clock.set(dt)
    svc.run_time_cascades()
    return ok_object({})
