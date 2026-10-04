"""Routes: developers, apps, versions, scope requests, review windows,
permission scopes, ledger entries."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import ok_object, ok_list, paginate
from middleware import (
    actor, require_role, get_or_404, json_body, require_fields, touch, new_entity,
)
from errors import ApiError
import services as svc

bp = Blueprint("core", __name__)

PAYOUT_CURRENCIES = {"USD", "EUR", "GBP"}
APP_CATEGORIES = {"PRODUCTIVITY", "MARKETING", "FULFILLMENT", "ANALYTICS", "FINANCE"}
RISK_LEVELS = {"LOW", "MEDIUM", "HIGH"}


# ---------------------------------------------------------------------------
# Developers
# ---------------------------------------------------------------------------

@bp.route("/developers", methods=["POST"])
def create_developer():
    require_role("PlatformAdmin")
    body = json_body()
    require_fields(body, "company_name", "contact_email", "payout_currency")
    if body["payout_currency"] not in PAYOUT_CURRENCIES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "payout_currency must be USD, EUR or GBP")
    for d in db.developers.values():
        if d["contact_email"] == body["contact_email"]:
            raise ApiError("ERR_DUPLICATE", 409, "contact_email already registered")
    dev = new_entity()
    dev.update({
        "company_name": body["company_name"],
        "contact_email": body["contact_email"],
        "payout_currency": body["payout_currency"],
        "status": "ACTIVE",
        "lifetime_gross_cents": 0,
    })
    db.developers[dev["id"]] = dev
    return ok_object(svc.serialize_developer(dev), 201)


@bp.route("/developers/<did>", methods=["GET"])
def get_developer(did):
    uid, role = require_role("PlatformAdmin", "Developer")
    dev = get_or_404(db.developers, did, "developer")
    if role == "Developer" and uid != dev["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "developer may only read own account")
    return ok_object(svc.serialize_developer(dev))


@bp.route("/developers/<did>/ledger-entries", methods=["GET"])
def developer_ledger(did):
    uid, role = require_role("PlatformAdmin", "Developer")
    dev = get_or_404(db.developers, did, "developer")
    if role == "Developer" and uid != dev["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "developer may only read own ledger")
    items = [svc.serialize_ledger_entry(le) for le in db.ledger_entries.values()
             if le["developer_id"] == did]
    items.sort(key=lambda x: x["created_at"])
    page, limit, offset, total = paginate(items, request.args)
    return ok_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Apps
# ---------------------------------------------------------------------------

@bp.route("/apps", methods=["POST"])
def create_app():
    uid, _ = require_role("Developer")
    body = json_body()
    require_fields(body, "developer_id", "name", "category")
    dev = db.developers.get(body["developer_id"])
    if dev is None:
        raise ApiError("ERR_NOT_FOUND", 404, "developer not found")
    if uid != dev["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "developer may only create own apps")
    if body["category"] not in APP_CATEGORIES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid category")
    for a in db.apps.values():
        if a["developer_id"] == dev["id"] and a["name"] == body["name"]:
            raise ApiError("ERR_DUPLICATE", 409, "app name already used by this developer")
    app = new_entity()
    app.update({
        "developer_id": dev["id"],
        "name": body["name"],
        "status": "DRAFT",
        "listing_status": "UNLISTED",
        "category": body["category"],
        "submitted_at": None,
        "performance_state": "COMPLIANT",
    })
    db.apps[app["id"]] = app
    return ok_object(svc.serialize_app(app), 201)


@bp.route("/apps", methods=["GET"])
def list_apps():
    require_role("PlatformAdmin", "Developer", "Reviewer", "Merchant")
    args = request.args
    items = list(db.apps.values())
    if args.get("developer_id"):
        items = [a for a in items if a["developer_id"] == args["developer_id"]]
    if args.get("category"):
        items = [a for a in items if a["category"] == args["category"]]
    if args.get("listing_status"):
        items = [a for a in items if a["listing_status"] == args["listing_status"]]
    if args.get("search"):
        items = [a for a in items if a["listing_status"] == "LISTED"]
        scored = [(svc.search_score(a), a) for a in items]
        scored.sort(key=lambda t: (-t[0], db.parse_dt(t[1]["created_at"])))
        items = [a for _, a in scored]
    else:
        items.sort(key=lambda a: db.parse_dt(a["created_at"]))
    out = [svc.serialize_app(a) for a in items]
    page, limit, offset, total = paginate(out, args)
    return ok_list(page, limit, offset, total)


@bp.route("/apps/<aid>", methods=["GET"])
def get_app(aid):
    require_role("PlatformAdmin", "Developer", "Reviewer", "Merchant")
    app = get_or_404(db.apps, aid, "app")
    return ok_object(svc.serialize_app(app))


@bp.route("/apps/<aid>", methods=["PATCH"])
def update_app(aid):
    uid, _ = require_role("Developer")
    app = get_or_404(db.apps, aid, "app")
    if uid != app["developer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "developer may only update own apps")
    if app["status"] in ("DELISTED",):
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "app is terminal")
    body = json_body()
    expected = body.get("expected_app_version")
    if expected is not None and expected != app["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_app_version mismatch")
    name = body.get("name")
    category = body.get("category")
    if category is not None and category not in APP_CATEGORIES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid category")
    if name is not None:
        for a in db.apps.values():
            if a["id"] != aid and a["developer_id"] == app["developer_id"] and a["name"] == name:
                raise ApiError("ERR_DUPLICATE", 409, "app name already used by this developer")
        app["name"] = name
    if category is not None:
        app["category"] = category
    touch(app)
    return ok_object(svc.serialize_app(app))


@bp.route("/apps/<aid>/submit", methods=["POST"])
def submit_app(aid):
    uid, _ = require_role("Developer")
    app = get_or_404(db.apps, aid, "app")
    if uid != app["developer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "developer may only submit own apps")
    if app["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "app not in a submittable state")
    dev = db.developers.get(app["developer_id"])
    if not dev or dev["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "developer account not ACTIVE")
    if app["status"] == "DRAFT":
        candidates = [v for v in db.versions.values()
                      if v["app_id"] == aid and v["status"] == "SUBMITTED"]
        if not candidates:
            raise ApiError("ERR_INVALID_STATE", 409, "no SUBMITTED version to submit")
        ver = sorted(candidates, key=lambda v: db.parse_dt(v["created_at"]))[-1]
        ver["status"] = "IN_REVIEW"
        touch(ver)
    else:
        candidates = [v for v in db.versions.values()
                      if v["app_id"] == aid and v["status"] == "CHANGES_REQUESTED"]
        if not candidates:
            raise ApiError("ERR_INVALID_STATE", 409, "no CHANGES_REQUESTED version to resubmit")
        ver = sorted(candidates, key=lambda v: db.parse_dt(v["created_at"]))[-1]
        ver["review_round"] += 1
        ver["status"] = "IN_REVIEW"
        touch(ver)
    app["status"] = "IN_REVIEW"
    app["submitted_at"] = db.fmt_dt(db.clock.now())
    touch(app)
    return ok_object(svc.serialize_app(app))


@bp.route("/apps/<aid>/publish", methods=["POST"])
def publish_app(aid):
    uid, _ = require_role("Developer")
    app = get_or_404(db.apps, aid, "app")
    if uid != app["developer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "developer may only publish own apps")
    if app["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "app not APPROVED")
    approved = [v for v in db.versions.values()
                if v["app_id"] == aid and v["status"] == "APPROVED"]
    if len(approved) != 1:
        raise ApiError("ERR_INVALID_STATE", 409, "requires exactly one APPROVED version")
    target = approved[0]
    for v in db.versions.values():
        if v["app_id"] == aid and v["status"] == "PUBLISHED":
            v["status"] = "SUPERSEDED"
            touch(v)
    target["status"] = "PUBLISHED"
    target["published_at"] = db.fmt_dt(db.clock.now())
    touch(target)
    app["status"] = "LISTED"
    app["listing_status"] = "LISTED"
    touch(app)
    return ok_object(svc.serialize_app(app))


@bp.route("/apps/<aid>/suspend", methods=["POST"])
def suspend_app(aid):
    require_role("PlatformAdmin")
    app = get_or_404(db.apps, aid, "app")
    if app["status"] != "LISTED":
        raise ApiError("ERR_INVALID_STATE", 409, "app not LISTED")
    app["status"] = "SUSPENDED"
    app["listing_status"] = "DELISTED"
    for inst in db.installations.values():
        if inst["app_id"] == aid and inst["status"] == "ACTIVE":
            inst["status"] = "SUSPENDED"
            touch(inst)
    touch(app)
    return ok_object(svc.serialize_app(app))


@bp.route("/apps/<aid>/reinstate", methods=["POST"])
def reinstate_app(aid):
    require_role("PlatformAdmin")
    app = get_or_404(db.apps, aid, "app")
    if app["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "app not SUSPENDED")
    blockers = svc.active_unexpired_strikes(
        aid, reasons={"DATA_DELETION_OVERDUE", "WEBHOOK_NONCOMPLIANCE"})
    if blockers:
        raise ApiError("ERR_STRIKE_THRESHOLD", 422, "active compliance strikes block reinstatement")
    app["status"] = "LISTED"
    app["listing_status"] = "LISTED"
    for inst in db.installations.values():
        if inst["app_id"] == aid and inst["status"] == "SUSPENDED":
            inst["status"] = "ACTIVE"
            touch(inst)
    touch(app)
    return ok_object(svc.serialize_app(app))


@bp.route("/apps/<aid>/delist", methods=["POST"])
def delist_app(aid):
    require_role("PlatformAdmin")
    app = get_or_404(db.apps, aid, "app")
    if app["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "app not SUSPENDED")
    active = svc.active_unexpired_strikes(aid)
    if len(active) < 5:
        raise ApiError("ERR_STRIKE_THRESHOLD", 422, "fewer than 5 active unexpired strikes")
    now = db.clock.now()
    app["status"] = "DELISTED"
    app["listing_status"] = "DELISTED"
    for inst in db.installations.values():
        if inst["app_id"] == aid and inst["status"] in ("ACTIVE", "SUSPENDED", "RECONSENT_REQUIRED"):
            inst["status"] = "UNINSTALLING"
            inst["uninstalled_at"] = db.fmt_dt(now)
            inst["data_deletion_deadline"] = db.fmt_dt(now + timedelta(days=30))
            touch(inst)
            for c in db.charges.values():
                if c["installation_id"] == inst["id"] and c["status"] == "PENDING":
                    c["status"] = "REVERSED"
                    touch(c)
    touch(app)
    return ok_object(svc.serialize_app(app))


@bp.route("/apps/<aid>/strikes", methods=["GET"])
def app_strikes(aid):
    require_role("PlatformAdmin", "Developer")
    get_or_404(db.apps, aid, "app")
    items = [svc.serialize_strike(s) for s in db.strikes.values() if s["app_id"] == aid]
    if request.args.get("status"):
        items = [s for s in items if s["status"] == request.args["status"]]
    items.sort(key=lambda s: s["created_at"])
    page, limit, offset, total = paginate(items, request.args)
    return ok_list(page, limit, offset, total)


@bp.route("/apps/<aid>/versions", methods=["GET"])
def app_versions(aid):
    require_role("PlatformAdmin", "Developer", "Reviewer")
    get_or_404(db.apps, aid, "app")
    items = [svc.serialize_version(v) for v in db.versions.values() if v["app_id"] == aid]
    items.sort(key=lambda v: v["created_at"])
    page, limit, offset, total = paginate(items, request.args)
    return ok_list(page, limit, offset, total)


@bp.route("/apps/<aid>/versions", methods=["POST"])
def create_version(aid):
    uid, _ = require_role("Developer")
    app = get_or_404(db.apps, aid, "app")
    if uid != app["developer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "developer may only version own apps")
    if app["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "app not in DRAFT or CHANGES_REQUESTED")
    body = json_body()
    require_fields(body, "semver")
    for v in db.versions.values():
        if v["app_id"] == aid and v["semver"] == body["semver"]:
            raise ApiError("ERR_INVALID_REQUEST", 400, "semver already used within this app")
    v = new_entity()
    v.update({
        "app_id": aid,
        "semver": body["semver"],
        "status": "SUBMITTED",
        "review_round": 0,
        "published_at": None,
    })
    db.versions[v["id"]] = v
    return ok_object(svc.serialize_version(v), 201)


@bp.route("/apps/<aid>/installations", methods=["GET"])
def app_installations(aid):
    uid, role = require_role("PlatformAdmin", "Developer")
    app = get_or_404(db.apps, aid, "app")
    if role == "Developer" and uid != app["developer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "developer may only list own apps' installations")
    items = [svc.serialize_installation(i) for i in db.installations.values()
             if i["app_id"] == aid]
    if request.args.get("status"):
        items = [i for i in items if i["status"] == request.args["status"]]
    items.sort(key=lambda i: i["created_at"])
    page, limit, offset, total = paginate(items, request.args)
    return ok_list(page, limit, offset, total)


@bp.route("/apps/<aid>/support-tickets", methods=["GET"])
def app_tickets(aid):
    require_role("PlatformAdmin", "Developer", "Merchant")
    get_or_404(db.apps, aid, "app")
    items = [svc.serialize_ticket(t) for t in db.tickets.values() if t["app_id"] == aid]
    if request.args.get("status"):
        items = [t for t in items if t["status"] == request.args["status"]]
    if request.args.get("merchant_id"):
        items = [t for t in items if t["merchant_id"] == request.args["merchant_id"]]
    items.sort(key=lambda t: t["created_at"])
    page, limit, offset, total = paginate(items, request.args)
    return ok_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# App versions (top-level)
# ---------------------------------------------------------------------------

@bp.route("/app-versions/<vid>", methods=["GET"])
def get_version(vid):
    require_role("PlatformAdmin", "Developer", "Reviewer")
    v = get_or_404(db.versions, vid, "app version")
    return ok_object(svc.serialize_version(v))


@bp.route("/app-versions", methods=["GET"])
def list_versions():
    require_role("PlatformAdmin", "Developer", "Reviewer")
    items = list(db.versions.values())
    if request.args.get("app_id"):
        items = [v for v in items if v["app_id"] == request.args["app_id"]]
    if request.args.get("status"):
        items = [v for v in items if v["status"] == request.args["status"]]
    items.sort(key=lambda v: db.parse_dt(v["created_at"]))
    out = [svc.serialize_version(v) for v in items]
    page, limit, offset, total = paginate(out, request.args)
    return ok_list(page, limit, offset, total)


def _check_reviewer_not_developer(version):
    body = json_body()
    require_fields(body, "reviewer_id")
    app = db.apps.get(version["app_id"])
    if app and body["reviewer_id"] == app["developer_id"]:
        raise ApiError("ERR_REVIEWER_CONFLICT", 422,
                       "reviewer must not be the owning developer")
    return body


@bp.route("/app-versions/<vid>/approve", methods=["POST"])
def approve_version(vid):
    require_role("Reviewer")
    v = get_or_404(db.versions, vid, "app version")
    app = db.apps.get(v["app_id"])
    if v["status"] != "IN_REVIEW" or (app and app["status"] != "IN_REVIEW"):
        raise ApiError("ERR_VERSION_NOT_REVIEWABLE", 409, "version not IN_REVIEW")
    _check_reviewer_not_developer(v)
    pending = [sr for sr in db.scope_requests.values()
               if sr["app_version_id"] == vid and sr["status"] == "PENDING"]
    if pending:
        raise ApiError("ERR_INVALID_STATE", 409, "scope requests still PENDING")
    v["status"] = "APPROVED"
    touch(v)
    if app:
        app["status"] = "APPROVED"
        touch(app)
    return ok_object(svc.serialize_version(v))


@bp.route("/app-versions/<vid>/request-changes", methods=["POST"])
def request_changes(vid):
    require_role("Reviewer")
    v = get_or_404(db.versions, vid, "app version")
    app = db.apps.get(v["app_id"])
    if v["status"] != "IN_REVIEW" or (app and app["status"] != "IN_REVIEW"):
        raise ApiError("ERR_VERSION_NOT_REVIEWABLE", 409, "version not IN_REVIEW")
    _check_reviewer_not_developer(v)
    v["status"] = "CHANGES_REQUESTED"
    touch(v)
    if app:
        app["status"] = "CHANGES_REQUESTED"
        touch(app)
    return ok_object(svc.serialize_version(v))


@bp.route("/app-versions/<vid>/reject", methods=["POST"])
def reject_version(vid):
    require_role("Reviewer")
    v = get_or_404(db.versions, vid, "app version")
    app = db.apps.get(v["app_id"])
    if v["status"] != "IN_REVIEW" or (app and app["status"] != "IN_REVIEW"):
        raise ApiError("ERR_VERSION_NOT_REVIEWABLE", 409, "version not IN_REVIEW")
    body = _check_reviewer_not_developer(v)
    require_fields(body, "reason")
    v["status"] = "REJECTED"
    touch(v)
    for sr in db.scope_requests.values():
        if sr["app_version_id"] == vid and sr["status"] == "PENDING":
            sr["status"] = "DENIED"
            sr["denied_reason"] = "VERSION_REJECTED"
            touch(sr)
    if app:
        app["status"] = "DRAFT"
        touch(app)
    return ok_object(svc.serialize_version(v))


# ---------------------------------------------------------------------------
# Scope requests
# ---------------------------------------------------------------------------

@bp.route("/app-versions/<vid>/scope-requests", methods=["POST"])
def create_scope_request(vid):
    uid, _ = require_role("Developer")
    v = get_or_404(db.versions, vid, "app version")
    app = db.apps.get(v["app_id"])
    if app and uid != app["developer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "developer may only request scopes on own versions")
    body = json_body()
    require_fields(body, "scope_code")
    scope = db.scopes.get(body["scope_code"])
    if scope is None:
        raise ApiError("ERR_NOT_FOUND", 404, "permission scope not found")
    justification = body.get("justification")
    if scope["risk_level"] == "HIGH":
        if not justification or len(justification) < 20:
            raise ApiError("ERR_SCOPE_JUSTIFICATION_REQUIRED", 422,
                           "HIGH-risk scope requires justification >= 20 chars")
    sr = new_entity()
    sr.update({
        "app_version_id": vid,
        "scope_code": body["scope_code"],
        "justification": justification,
        "status": "PENDING",
        "denied_reason": None,
    })
    db.scope_requests[sr["id"]] = sr
    return ok_object(svc.serialize_scope_request(sr), 201)


@bp.route("/app-versions/<vid>/scope-requests", methods=["GET"])
def list_scope_requests(vid):
    require_role("PlatformAdmin", "Developer", "Reviewer")
    get_or_404(db.versions, vid, "app version")
    items = [svc.serialize_scope_request(sr) for sr in db.scope_requests.values()
             if sr["app_version_id"] == vid]
    if request.args.get("status"):
        items = [s for s in items if s["status"] == request.args["status"]]
    items.sort(key=lambda s: s["created_at"])
    page, limit, offset, total = paginate(items, request.args)
    return ok_list(page, limit, offset, total)


@bp.route("/scope-requests/<sid>", methods=["GET"])
def get_scope_request(sid):
    require_role("PlatformAdmin", "Developer", "Reviewer")
    sr = get_or_404(db.scope_requests, sid, "scope request")
    return ok_object(svc.serialize_scope_request(sr))


@bp.route("/scope-requests/<sid>/decide", methods=["POST"])
def decide_scope_request(sid):
    require_role("Reviewer")
    sr = get_or_404(db.scope_requests, sid, "scope request")
    if sr["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "scope request not PENDING")
    body = json_body()
    require_fields(body, "decision")
    decision = body["decision"]
    if decision == "APPROVED":
        sr["status"] = "APPROVED"
        sr["denied_reason"] = None
    elif decision == "DENIED":
        reason = body.get("denied_reason")
        if not reason:
            raise ApiError("ERR_INVALID_REQUEST", 400, "denied_reason required for denial")
        sr["status"] = "DENIED"
        sr["denied_reason"] = reason
    else:
        raise ApiError("ERR_INVALID_REQUEST", 400, "decision must be APPROVED or DENIED")
    touch(sr)
    return ok_object(svc.serialize_scope_request(sr))


# ---------------------------------------------------------------------------
# Review windows
# ---------------------------------------------------------------------------

@bp.route("/app-versions/<vid>/review-windows", methods=["POST"])
def create_review_window(vid):
    require_role("Reviewer")
    v = get_or_404(db.versions, vid, "app version")
    body = json_body()
    require_fields(body, "reviewer_id", "starts_at", "ends_at")
    app = db.apps.get(v["app_id"])
    if app and body["reviewer_id"] == app["developer_id"]:
        raise ApiError("ERR_REVIEWER_CONFLICT", 422,
                       "reviewer must not be the owning developer")
    try:
        starts = db.parse_dt(body["starts_at"])
        ends = db.parse_dt(body["ends_at"])
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid starts_at/ends_at")
    if ends <= starts:
        raise ApiError("ERR_INVALID_REQUEST", 400, "ends_at must be strictly after starts_at")
    for w in db.review_windows.values():
        if w["app_version_id"] != vid or w["status"] != "SCHEDULED":
            continue
        s2 = db.parse_dt(w["starts_at"])
        e2 = db.parse_dt(w["ends_at"])
        if starts < e2 and s2 < ends:
            raise ApiError("ERR_REVIEW_WINDOW_OVERLAP", 409,
                           "review window overlaps an existing SCHEDULED window")
    w = new_entity()
    w.update({
        "app_version_id": vid,
        "reviewer_id": body["reviewer_id"],
        "starts_at": db.fmt_dt(starts),
        "ends_at": db.fmt_dt(ends),
        "status": "SCHEDULED",
    })
    db.review_windows[w["id"]] = w
    return ok_object(svc.serialize_review_window(w), 201)


@bp.route("/app-versions/<vid>/review-windows", methods=["GET"])
def list_review_windows(vid):
    require_role("PlatformAdmin", "Developer", "Reviewer")
    get_or_404(db.versions, vid, "app version")
    items = [svc.serialize_review_window(w) for w in db.review_windows.values()
             if w["app_version_id"] == vid]
    if request.args.get("status"):
        items = [w for w in items if w["status"] == request.args["status"]]
    items.sort(key=lambda w: w["created_at"])
    page, limit, offset, total = paginate(items, request.args)
    return ok_list(page, limit, offset, total)


@bp.route("/review-windows/<wid>", methods=["GET"])
def get_review_window(wid):
    require_role("PlatformAdmin", "Developer", "Reviewer")
    w = get_or_404(db.review_windows, wid, "review window")
    return ok_object(svc.serialize_review_window(w))


# ---------------------------------------------------------------------------
# Permission scopes catalog
# ---------------------------------------------------------------------------

@bp.route("/permission-scopes", methods=["GET"])
def list_scopes():
    require_role("PlatformAdmin", "Developer", "Reviewer", "Merchant")
    items = [svc.serialize_scope(s) for s in db.scopes.values()]
    if request.args.get("risk_level"):
        items = [s for s in items if s["risk_level"] == request.args["risk_level"]]
    items.sort(key=lambda s: s["created_at"])
    page, limit, offset, total = paginate(items, request.args)
    return ok_list(page, limit, offset, total)


@bp.route("/permission-scopes", methods=["POST"])
def create_scope():
    require_role("PlatformAdmin")
    body = json_body()
    require_fields(body, "code", "risk_level")
    if body["risk_level"] not in RISK_LEVELS:
        raise ApiError("ERR_INVALID_REQUEST", 400, "risk_level must be LOW, MEDIUM or HIGH")
    if body["code"] in db.scopes:
        raise ApiError("ERR_DUPLICATE", 409, "scope code already registered")
    s = {"id": db.new_uuid(), "created_at": db.fmt_dt(db.clock.now())}
    s.update({"code": body["code"], "risk_level": body["risk_level"]})
    db.scopes[s["code"]] = s
    return ok_object(svc.serialize_scope(s), 201)


# ---------------------------------------------------------------------------
# Ledger entries (top-level)
# ---------------------------------------------------------------------------

@bp.route("/ledger-entries", methods=["GET"])
def list_ledger_entries():
    require_role("PlatformAdmin", "Developer")
    items = list(db.ledger_entries.values())
    if request.args.get("developer_id"):
        items = [le for le in items if le["developer_id"] == request.args["developer_id"]]
    if request.args.get("charge_id"):
        items = [le for le in items if le["charge_id"] == request.args["charge_id"]]
    if request.args.get("entry_variant"):
        items = [le for le in items if le["entry_variant"] == request.args["entry_variant"]]
    if request.args.get("cycle"):
        items = [le for le in items if le["cycle"] == request.args["cycle"]]
    items.sort(key=lambda le: db.parse_dt(le["created_at"]))
    out = [svc.serialize_ledger_entry(le) for le in items]
    page, limit, offset, total = paginate(out, request.args)
    return ok_list(page, limit, offset, total)
