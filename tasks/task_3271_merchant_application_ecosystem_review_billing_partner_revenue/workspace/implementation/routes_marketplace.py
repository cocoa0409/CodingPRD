"""Routes: merchants, installations, consent, webhooks, performance samples."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import ok_object, ok_list, paginate, ApiError
from middleware import (
    require_role, get_or_404, json_body, require_fields, touch, new_entity,
)
import services as svc

bp = Blueprint("marketplace", __name__)

PLAN_TIERS = {"BASIC", "GROWTH", "ENTERPRISE"}
UNINSTALLING = {"UNINSTALLING", "UNINSTALLED"}


# ---------------------------------------------------------------------------
# Merchants
# ---------------------------------------------------------------------------

@bp.route("/merchants", methods=["POST"])
def create_merchant():
    require_role("PlatformAdmin")
    body = json_body()
    require_fields(body, "shop_domain", "plan_tier")
    if body["plan_tier"] not in PLAN_TIERS:
        raise ApiError("ERR_INVALID_REQUEST", 400, "plan_tier must be BASIC, GROWTH or ENTERPRISE")
    for m in db.merchants.values():
        if m["shop_domain"] == body["shop_domain"]:
            raise ApiError("ERR_DUPLICATE", 409, "shop_domain already registered")
    m = new_entity()
    m.update({"shop_domain": body["shop_domain"], "plan_tier": body["plan_tier"]})
    db.merchants[m["id"]] = m
    return ok_object(svc.serialize_merchant(m), 201)


@bp.route("/merchants/<mid>", methods=["GET"])
def get_merchant(mid):
    uid, role = require_role("PlatformAdmin", "Merchant")
    m = get_or_404(db.merchants, mid, "merchant")
    if role == "Merchant" and uid != m["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "merchant may only read own account")
    return ok_object(svc.serialize_merchant(m))


@bp.route("/merchants/<mid>/invoices", methods=["GET"])
def merchant_invoices(mid):
    uid, role = require_role("PlatformAdmin", "Merchant")
    get_or_404(db.merchants, mid, "merchant")
    if role == "Merchant" and uid != mid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "merchant may only list own invoices")
    items = [svc.serialize_invoice(i) for i in db.invoices.values()
             if i["merchant_id"] == mid]
    if request.args.get("status"):
        items = [i for i in items if i["status"] == request.args["status"]]
    items.sort(key=lambda i: i["created_at"])
    page, limit, offset, total = paginate(items, request.args)
    return ok_list(page, limit, offset, total)


@bp.route("/merchants/<mid>/invoices", methods=["POST"])
def create_invoice(mid):
    require_role("PlatformAdmin")
    get_or_404(db.merchants, mid, "merchant")
    body = json_body()
    require_fields(body, "cycle")
    cycle = body["cycle"]
    import re
    if not isinstance(cycle, str) or not re.fullmatch(r"\d{4}-\d{2}", cycle):
        raise ApiError("ERR_INVALID_REQUEST", 400, "cycle must be YYYY-MM")
    for inv in db.invoices.values():
        if inv["merchant_id"] == mid and inv["cycle"] == cycle:
            raise ApiError("ERR_DUPLICATE", 409, "invoice for this cycle already exists")
    inv = new_entity()
    inv.update({
        "merchant_id": mid,
        "cycle": cycle,
        "status": "OPEN",
        "total_cents": 0,
        "issued_at": None,
    })
    db.invoices[inv["id"]] = inv
    return ok_object(svc.serialize_invoice(inv), 201)


@bp.route("/merchants/<mid>/installations", methods=["GET"])
def merchant_installations(mid):
    uid, role = require_role("PlatformAdmin", "Merchant")
    get_or_404(db.merchants, mid, "merchant")
    if role == "Merchant" and uid != mid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "merchant may only list own installations")
    items = [svc.serialize_installation(i) for i in db.installations.values()
             if i["merchant_id"] == mid]
    if request.args.get("status"):
        items = [i for i in items if i["status"] == request.args["status"]]
    items.sort(key=lambda i: i["created_at"])
    page, limit, offset, total = paginate(items, request.args)
    return ok_list(page, limit, offset, total)


@bp.route("/merchants/<mid>/support-tickets", methods=["GET"])
def merchant_tickets(mid):
    uid, role = require_role("PlatformAdmin", "Merchant")
    get_or_404(db.merchants, mid, "merchant")
    if role == "Merchant" and uid != mid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "merchant may only list own tickets")
    items = [svc.serialize_ticket(t) for t in db.tickets.values()
             if t["merchant_id"] == mid]
    if request.args.get("status"):
        items = [t for t in items if t["status"] == request.args["status"]]
    items.sort(key=lambda t: t["created_at"])
    page, limit, offset, total = paginate(items, request.args)
    return ok_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Installations
# ---------------------------------------------------------------------------

@bp.route("/installations", methods=["POST"])
def create_installation():
    uid, _ = require_role("Merchant")
    body = json_body()
    require_fields(body, "app_id", "merchant_id")
    app = db.apps.get(body["app_id"])
    if app is None:
        raise ApiError("ERR_NOT_FOUND", 404, "app not found")
    merchant = db.merchants.get(body["merchant_id"])
    if merchant is None:
        raise ApiError("ERR_NOT_FOUND", 404, "merchant not found")
    if uid != merchant["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "merchant may only install for self")
    if app["listing_status"] != "LISTED":
        raise ApiError("ERR_APP_NOT_LISTED", 409, "app is not LISTED")
    inst = new_entity()
    inst.update({
        "app_id": app["id"],
        "merchant_id": merchant["id"],
        "status": "PENDING_CONSENT",
        "installed_at": None,
        "uninstalled_at": None,
        "data_deletion_deadline": None,
        "data_deletion_confirmed_at": None,
    })
    db.installations[inst["id"]] = inst
    return ok_object(svc.serialize_installation(inst), 201)


@bp.route("/installations/<iid>", methods=["GET"])
def get_installation(iid):
    uid, role = require_role("PlatformAdmin", "Developer", "Merchant")
    inst = get_or_404(db.installations, iid, "installation")
    if role == "Merchant" and uid != inst["merchant_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not your installation")
    if role == "Developer" and uid != svc.developer_id_of_app(inst["app_id"]):
        raise ApiError("ERR_UNAUTHORIZED", 403, "not your app's installation")
    return ok_object(svc.serialize_installation(inst))


def _published_version(app_id):
    pubs = [v for v in db.versions.values()
            if v["app_id"] == app_id and v["status"] == "PUBLISHED"]
    if not pubs:
        return None
    pubs.sort(key=lambda v: db.parse_dt(v["created_at"]))
    return pubs[-1]


def _grant_consents(inst, scopes):
    now_s = db.fmt_dt(db.clock.now())
    for code in scopes:
        cr = new_entity()
        cr.update({
            "installation_id": inst["id"],
            "scope_code": code,
            "status": "GRANTED",
            "granted_at": now_s,
            "revoked_at": None,
        })
        db.consent_records[cr["id"]] = cr


@bp.route("/installations/<iid>/consent", methods=["POST"])
def consent(iid):
    uid, _ = require_role("Merchant")
    inst = get_or_404(db.installations, iid, "installation")
    if uid != inst["merchant_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "merchant may only consent own installation")
    if inst["status"] not in ("PENDING_CONSENT", "RECONSENT_REQUIRED"):
        if inst["status"] in UNINSTALLING:
            raise ApiError("ERR_UNINSTALL_IN_PROGRESS", 409, "installation is being uninstalled")
        raise ApiError("ERR_INVALID_STATE", 409, "installation not awaiting consent")
    pub = _published_version(inst["app_id"])
    requested = []
    if pub:
        requested = [sr for sr in db.scope_requests.values()
                     if sr["app_version_id"] == pub["id"]]
    if inst["status"] == "PENDING_CONSENT":
        for sr in requested:
            if sr["status"] != "APPROVED":
                raise ApiError("ERR_SCOPE_NOT_APPROVED", 422,
                               "all scopes of the PUBLISHED version must be APPROVED")
        _grant_consents(inst, [sr["scope_code"] for sr in requested])
        inst["status"] = "ACTIVE"
        inst["installed_at"] = db.fmt_dt(db.clock.now())
    else:
        # RECONSENT_REQUIRED: grant delta scopes = approved scopes of the
        # published version lacking an active GRANTED consent record.
        granted = {cr["scope_code"] for cr in db.consent_records.values()
                   if cr["installation_id"] == iid and cr["status"] == "GRANTED"}
        delta = [sr["scope_code"] for sr in requested
                 if sr["status"] == "APPROVED" and sr["scope_code"] not in granted]
        _grant_consents(inst, delta)
        inst["status"] = "ACTIVE"
    touch(inst)
    return ok_object(svc.serialize_installation(inst))


@bp.route("/installations/<iid>/request-reconsent", methods=["POST"])
def request_reconsent(iid):
    require_role("PlatformAdmin")
    inst = get_or_404(db.installations, iid, "installation")
    if inst["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "installation not ACTIVE")
    inst["status"] = "RECONSENT_REQUIRED"
    touch(inst)
    return ok_object(svc.serialize_installation(inst))


@bp.route("/installations/<iid>/uninstall", methods=["POST"])
def uninstall(iid):
    uid, _ = require_role("Merchant")
    inst = get_or_404(db.installations, iid, "installation")
    if uid != inst["merchant_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "merchant may only uninstall own installation")
    if inst["status"] not in ("ACTIVE", "RECONSENT_REQUIRED", "SUSPENDED"):
        if inst["status"] in UNINSTALLING:
            raise ApiError("ERR_UNINSTALL_IN_PROGRESS", 409, "already uninstalling")
        raise ApiError("ERR_INVALID_STATE", 409, "installation cannot be uninstalled from this state")
    now = db.clock.now()
    inst["status"] = "UNINSTALLING"
    inst["uninstalled_at"] = db.fmt_dt(now)
    inst["data_deletion_deadline"] = db.fmt_dt(now + timedelta(days=30))
    for c in db.charges.values():
        if c["installation_id"] == iid and c["status"] == "PENDING":
            c["status"] = "REVERSED"
            touch(c)
    for w in db.webhooks.values():
        if w["installation_id"] == iid and w["status"] == "ACTIVE":
            # app/uninstalled delivery attempt is recorded implicitly; status unchanged
            w["last_delivery_attempt_at"] = db.fmt_dt(now)
    touch(inst)
    return ok_object(svc.serialize_installation(inst))


@bp.route("/installations/<iid>/confirm-data-deletion", methods=["POST"])
def confirm_data_deletion(iid):
    uid, _ = require_role("Developer")
    inst = get_or_404(db.installations, iid, "installation")
    if uid != svc.developer_id_of_app(inst["app_id"]):
        raise ApiError("ERR_UNAUTHORIZED", 403, "developer must own the app")
    now = db.clock.now()
    # PRD §3.9: "Confirmation attempted after the deadline is rejected with
    # ERR_DELETION_OVERDUE". When the deadline-passage cascade has already
    # moved the installation to UNINSTALLED, the state category (§2.7
    # priority 4) masks the deadline category (priority 11) and the request
    # surfaces the state error instead.
    if inst["status"] == "UNINSTALLING" and \
            now > db.parse_dt(inst["data_deletion_deadline"]):
        raise ApiError("ERR_DELETION_OVERDUE", 422, "deletion deadline has passed")
    if inst["status"] != "UNINSTALLING":
        raise ApiError("ERR_INVALID_STATE", 409, "installation not UNINSTALLING")
    inst["status"] = "UNINSTALLED"
    inst["data_deletion_confirmed_at"] = db.fmt_dt(now)
    for w in db.webhooks.values():
        if w["installation_id"] == iid and w["status"] != "DISABLED":
            w["status"] = "DISABLED"
            touch(w)
    touch(inst)
    return ok_object(svc.serialize_installation(inst))


# ---------------------------------------------------------------------------
# Consent records
# ---------------------------------------------------------------------------

@bp.route("/installations/<iid>/consent-records", methods=["GET"])
def list_consent_records(iid):
    uid, role = require_role("PlatformAdmin", "Developer", "Merchant")
    inst = get_or_404(db.installations, iid, "installation")
    if role == "Merchant" and uid != inst["merchant_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not your installation")
    if role == "Developer" and uid != svc.developer_id_of_app(inst["app_id"]):
        raise ApiError("ERR_UNAUTHORIZED", 403, "not your app's installation")
    items = [svc.serialize_consent_record(cr) for cr in db.consent_records.values()
             if cr["installation_id"] == iid]
    if request.args.get("status"):
        items = [c for c in items if c["status"] == request.args["status"]]
    items.sort(key=lambda c: c["created_at"])
    page, limit, offset, total = paginate(items, request.args)
    return ok_list(page, limit, offset, total)


@bp.route("/consent-records/<cid>", methods=["GET"])
def get_consent_record(cid):
    uid, role = require_role("PlatformAdmin", "Developer", "Merchant")
    cr = get_or_404(db.consent_records, cid, "consent record")
    inst = db.installations.get(cr["installation_id"])
    if inst:
        if role == "Merchant" and uid != inst["merchant_id"]:
            raise ApiError("ERR_UNAUTHORIZED", 403, "not your installation")
        if role == "Developer" and uid != svc.developer_id_of_app(inst["app_id"]):
            raise ApiError("ERR_UNAUTHORIZED", 403, "not your app's installation")
    return ok_object(svc.serialize_consent_record(cr))


@bp.route("/installations/<iid>/consent-records/<rid>/revoke", methods=["POST"])
def revoke_consent(iid, rid):
    uid, _ = require_role("Merchant")
    inst = get_or_404(db.installations, iid, "installation")
    cr = db.consent_records.get(rid)
    if cr is None or cr["installation_id"] != iid:
        raise ApiError("ERR_NOT_FOUND", 404, "consent record not found")
    if uid != inst["merchant_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "merchant may only revoke own consents")
    if inst["status"] != "ACTIVE":
        if inst["status"] in UNINSTALLING:
            raise ApiError("ERR_UNINSTALL_IN_PROGRESS", 409, "installation is being uninstalled")
        raise ApiError("ERR_INVALID_STATE", 409, "installation not ACTIVE")
    if cr["status"] != "GRANTED":
        raise ApiError("ERR_INVALID_STATE", 409, "consent record not GRANTED")
    scope = db.scopes.get(cr["scope_code"])
    if scope and scope["risk_level"] == "HIGH":
        pending = [c for c in db.charges.values()
                   if c["installation_id"] == iid and c["status"] == "PENDING"]
        if pending:
            raise ApiError("ERR_REVIEWER_CONFLICT", 422,
                           "HIGH-risk scope revocation blocked by pending charges")
    cr["status"] = "REVOKED"
    cr["revoked_at"] = db.fmt_dt(db.clock.now())
    touch(cr)
    inst["status"] = "RECONSENT_REQUIRED"
    touch(inst)
    return ok_object(svc.serialize_consent_record(cr))


# ---------------------------------------------------------------------------
# Webhook subscriptions
# ---------------------------------------------------------------------------

@bp.route("/installations/<iid>/webhook-subscriptions", methods=["POST"])
def create_webhook(iid):
    uid, _ = require_role("Developer")
    inst = get_or_404(db.installations, iid, "installation")
    if uid != svc.developer_id_of_app(inst["app_id"]):
        raise ApiError("ERR_UNAUTHORIZED", 403, "developer must own the app")
    if inst["status"] in UNINSTALLING:
        raise ApiError("ERR_UNINSTALL_IN_PROGRESS", 409, "installation is being uninstalled")
    body = json_body()
    require_fields(body, "topic", "endpoint_url")
    for w in db.webhooks.values():
        if w["installation_id"] == iid and w["topic"] == body["topic"]:
            raise ApiError("ERR_DUPLICATE", 409, "topic already subscribed for this installation")
    w = new_entity()
    w.update({
        "installation_id": iid,
        "topic": body["topic"],
        "endpoint_url": body["endpoint_url"],
        "status": "ACTIVE",
    })
    db.webhooks[w["id"]] = w
    return ok_object(svc.serialize_webhook(w), 201)


@bp.route("/installations/<iid>/webhook-subscriptions", methods=["GET"])
def list_webhooks(iid):
    uid, role = require_role("PlatformAdmin", "Developer", "Merchant")
    inst = get_or_404(db.installations, iid, "installation")
    if role == "Merchant" and uid != inst["merchant_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not your installation")
    if role == "Developer" and uid != svc.developer_id_of_app(inst["app_id"]):
        raise ApiError("ERR_UNAUTHORIZED", 403, "not your app's installation")
    items = [svc.serialize_webhook(w) for w in db.webhooks.values()
             if w["installation_id"] == iid]
    if request.args.get("status"):
        items = [w for w in items if w["status"] == request.args["status"]]
    items.sort(key=lambda w: w["created_at"])
    page, limit, offset, total = paginate(items, request.args)
    return ok_list(page, limit, offset, total)


@bp.route("/webhook-subscriptions/<wid>", methods=["GET"])
def get_webhook(wid):
    uid, role = require_role("PlatformAdmin", "Developer", "Merchant")
    w = get_or_404(db.webhooks, wid, "webhook subscription")
    inst = db.installations.get(w["installation_id"])
    if inst:
        if role == "Merchant" and uid != inst["merchant_id"]:
            raise ApiError("ERR_UNAUTHORIZED", 403, "not your installation")
        if role == "Developer" and uid != svc.developer_id_of_app(inst["app_id"]):
            raise ApiError("ERR_UNAUTHORIZED", 403, "not your app's installation")
    return ok_object(svc.serialize_webhook(w))


# ---------------------------------------------------------------------------
# Performance samples
# ---------------------------------------------------------------------------

@bp.route("/installations/<iid>/performance-samples", methods=["POST"])
def create_sample(iid):
    uid, role = require_role("Developer", "PlatformAdmin")
    inst = get_or_404(db.installations, iid, "installation")
    if role == "Developer" and uid != svc.developer_id_of_app(inst["app_id"]):
        raise ApiError("ERR_UNAUTHORIZED", 403, "developer must own the app")
    if inst["status"] in UNINSTALLING:
        raise ApiError("ERR_UNINSTALL_IN_PROGRESS", 409, "installation is being uninstalled")
    body = json_body()
    require_fields(body, "storefront_load_ms", "sampled_at")
    load = body["storefront_load_ms"]
    if not isinstance(load, int) or isinstance(load, bool) or load <= 0:
        raise ApiError("ERR_INVALID_AMOUNT", 422, "storefront_load_ms must be a positive integer")
    try:
        sampled_dt = db.parse_dt(body["sampled_at"])
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid sampled_at")
    s = new_entity()
    s.update({
        "installation_id": iid,
        "storefront_load_ms": load,
        "sampled_at": db.fmt_dt(sampled_dt),
    })
    db.samples[s["id"]] = s
    _evaluate_performance(inst, sampled_dt)
    return ok_object(svc.serialize_sample(s), 201)


def _evaluate_performance(inst, sampled_dt):
    app = db.apps.get(inst["app_id"])
    if app is None:
        return
    window_start = sampled_dt - timedelta(days=7)
    window = [x for x in db.samples.values()
              if x["installation_id"] == inst["id"]
              and window_start < db.parse_dt(x["sampled_at"]) <= sampled_dt]
    if not window:
        return
    total = sum(x["storefront_load_ms"] for x in window)
    avg = svc.round_half_up_2dp(total / len(window))
    impact = svc.round_half_up(2 * avg)
    if impact <= 200:
        # PRD §3.7: a compliant window makes the app's performance_state
        # "remain or return to COMPLIANT"; the consecutive-breach tracker
        # resets, since the §3.7 delisting trigger requires three
        # *consecutive* breaching windows.
        if app["performance_state"] != "COMPLIANT":
            app["performance_state"] = "COMPLIANT"
            touch(app)
        app["_breach_days"] = set()
        return
    # Breach
    day_key = sampled_dt.strftime("%Y-%m-%d")
    days = app.setdefault("_breach_days", set())
    if day_key in days:
        # A second breaching sample on an already-counted day does not open
        # another strike: the §3.7 consecutive-window tracker distinguishes
        # windows by distinct sampled_at days, and the performance_state is
        # already past DEGRADED for this day.
        return
    days.add(day_key)
    if len(days) >= 3:
        if app["performance_state"] != "DELISTED_PERFORMANCE":
            app["performance_state"] = "DELISTED_PERFORMANCE"
            app["listing_status"] = "DELISTED"
            if app["status"] == "LISTED":
                app["status"] = "DELISTED"
            svc.open_strike(app["id"], "PERFORMANCE_BREACH")
            touch(app)
    else:
        if app["performance_state"] != "DELISTED_PERFORMANCE":
            app["performance_state"] = "DEGRADED"
            svc.open_strike(app["id"], "PERFORMANCE_BREACH")
            touch(app)


@bp.route("/installations/<iid>/performance-samples", methods=["GET"])
def list_samples(iid):
    uid, role = require_role("PlatformAdmin", "Developer")
    inst = get_or_404(db.installations, iid, "installation")
    if role == "Developer" and uid != svc.developer_id_of_app(inst["app_id"]):
        raise ApiError("ERR_UNAUTHORIZED", 403, "not your app's installation")
    items = [svc.serialize_sample(s) for s in db.samples.values()
             if s["installation_id"] == iid]
    items.sort(key=lambda s: s["created_at"])
    page, limit, offset, total = paginate(items, request.args)
    return ok_list(page, limit, offset, total)


@bp.route("/performance-samples/<sid>", methods=["GET"])
def get_sample(sid):
    require_role("PlatformAdmin", "Developer")
    s = get_or_404(db.samples, sid, "performance sample")
    return ok_object(svc.serialize_sample(s))


# ---------------------------------------------------------------------------
# Strikes
# ---------------------------------------------------------------------------

@bp.route("/strikes/<sid>", methods=["GET"])
def get_strike(sid):
    require_role("PlatformAdmin", "Developer")
    s = get_or_404(db.strikes, sid, "strike")
    return ok_object(svc.serialize_strike(s))
