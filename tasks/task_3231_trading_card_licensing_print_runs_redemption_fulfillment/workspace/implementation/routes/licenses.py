"""License resource: CRUD plus activate / suspend / expire transitions."""

from flask import jsonify, request

import db
import requtil
import response
from core import app
from common import (
    recompute_license_counts,
    recompute_sets_per_case,
    record_license_status,
    refresh_print_run_status,
    serialize,
    sets_under_line,
)
from constants import EXCLUSIVITY_SCOPES, LICENSE_STATUSES
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LICENSE_NOT_FOUND,
    ERR_LICENSE_TERM_EXPIRED,
    ERR_LICENSE_TERM_NOT_ENDED,
    ERR_LICENSE_TERM_NOT_STARTED,
    ERR_REFERENCE_NOT_FOUND,
)
from middleware import authenticate, require_role

READ_ROLES = ["LicensingManager", "ProductManager", "PlatformAdmin"]


def _get(license_id):
    rec = db.STORE.get("licenses", license_id)
    if rec is None:
        raise ApiError(ERR_LICENSE_NOT_FOUND, "No License exists with id %s" % license_id)
    return rec


def _serialize(rec):
    return serialize("licenses", rec)


@app.route("/api/licenses", methods=["POST"])
def create_license():
    principal = authenticate(request.headers)
    require_role(principal, ["LicensingManager"])

    data = requtil.body()
    grantor_name = requtil.required_str(data, "grantor_name")
    # PRD 3.1 lists `exclusivity_scope` among the fields a registering caller
    # "declares" but does not mark it required the way it marks the term dates,
    # and `approval_window_days` is the only field it explicitly reports having
    # "a default ... when the caller does not supply it" — so the scope takes a
    # benign default rather than being refused when omitted.
    exclusivity_scope = requtil.optional_enum(
        data, "exclusivity_scope", EXCLUSIVITY_SCOPES, "EXCLUSIVE"
    )
    term_starts_on = requtil.required_dt(data, "term_starts_on")
    term_ends_on = requtil.required_dt(data, "term_ends_on")
    window = requtil.optional_int(data, "approval_window_days", 10)
    if window is None or window < 0:
        raise ApiError(ERR_INVALID_REQUEST, "approval_window_days must be >= 0")

    store = db.STORE
    now = store.now()
    rec = db.record("licenses", {
        "grantor_name": grantor_name,
        "exclusivity_scope": exclusivity_scope,
        "term_starts_on": term_starts_on,
        "term_ends_on": term_ends_on,
        "approval_window_days": window,
        "rights_version": 0,
        "status": "DRAFT",
        "set_count": 0,
        "approved_set_count": 0,
    }, now)
    store.insert("licenses", rec)
    return jsonify(response.ok_object(_serialize(rec))), 201


@app.route("/api/licenses", methods=["GET"])
def list_licenses():
    principal = authenticate(request.headers)
    require_role(principal, ["LicensingManager", "PlatformAdmin"])

    store = db.STORE
    items = list(store.all("licenses"))
    status = requtil.filter_value("status")
    grantor = requtil.filter_value("grantor_name")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if grantor is not None:
        items = [r for r in items if r["grantor_name"] == grantor]
    items.sort(key=lambda r: r["created_at"])
    return jsonify(response.paginate([_serialize(r) for r in items], request.args)), 200


@app.route("/api/licenses/<license_id>", methods=["GET"])
def get_license(license_id):
    principal = authenticate(request.headers)
    require_role(principal, READ_ROLES)
    rec = _get(license_id)
    return jsonify(response.ok_object(_serialize(rec))), 200


@app.route("/api/licenses/<license_id>/activate", methods=["POST"])
def activate_license(license_id):
    principal = authenticate(request.headers)
    require_role(principal, ["LicensingManager"])

    store = db.STORE
    now = store.now()
    rec = _get(license_id)

    # Strict comparisons: refused when the clock has not yet reached
    # term_starts_on (strict) and when it is past term_ends_on (strict).
    if now < rec["term_starts_on"]:
        raise ApiError(ERR_LICENSE_TERM_NOT_STARTED, "License term has not started")
    if now > rec["term_ends_on"]:
        raise ApiError(ERR_LICENSE_TERM_EXPIRED, "License term has already ended")

    if rec["status"] == "DRAFT":
        pass
    elif rec["status"] == "SUSPENDED":
        # Reactivation requires at least one APPROVED card set under this
        # license.
        approved = any(
            s["status"] == "APPROVED"
            for line in store.all("product_lines")
            if line["license_id"] == license_id
            for s in sets_under_line(store, line["id"])
        )
        if not approved:
            raise ApiError(
                ERR_INVALID_STATE,
                "License cannot be reactivated: no APPROVED card set under it",
            )
    else:
        raise ApiError(ERR_INVALID_STATE, "License is not DRAFT or SUSPENDED")

    rec["status"] = "ACTIVE"
    rec["rights_version"] = rec["rights_version"] + 1
    db.bump(rec, now)
    record_license_status(rec, "ACTIVE", now)
    return jsonify(response.ok_object(_serialize(rec))), 200


@app.route("/api/licenses/<license_id>/suspend", methods=["POST"])
def suspend_license(license_id):
    principal = authenticate(request.headers)
    require_role(principal, ["LicensingManager"])

    store = db.STORE
    now = store.now()
    rec = _get(license_id)
    if rec["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Only an ACTIVE license can be suspended")

    rec["status"] = "SUSPENDED"
    rec["rights_version"] = rec["rights_version"] + 1
    db.bump(rec, now)
    record_license_status(rec, "SUSPENDED", now)

    # Downward cascade: every product line under this license returns to
    # PLANNING (each recomputing sets_per_case), and every card set under those
    # lines has its print-run status reset to UNDECIDED.
    for line in store.all("product_lines"):
        if line["license_id"] != license_id:
            continue
        line["status"] = "PLANNING"
        recompute_sets_per_case(store, line, now)
        for card_set in sets_under_line(store, line["id"]):
            card_set["print_run_status"] = "UNDECIDED"
            db.touch(card_set, now)

    return jsonify(response.ok_object(_serialize(rec))), 200


@app.route("/api/licenses/<license_id>/expire", methods=["POST"])
def expire_license(license_id):
    principal = authenticate(request.headers)
    require_role(principal, ["LicensingManager"])

    store = db.STORE
    now = store.now()
    rec = _get(license_id)
    if rec["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Only an ACTIVE license can be expired")
    if not now > rec["term_ends_on"]:
        raise ApiError(ERR_LICENSE_TERM_NOT_ENDED, "License term has not yet ended")

    rec["status"] = "EXPIRED"
    rec["rights_version"] = rec["rights_version"] + 1
    db.bump(rec, now)
    record_license_status(rec, "EXPIRED", now)

    for line in store.all("product_lines"):
        if line["license_id"] != license_id:
            continue
        line["status"] = "PLANNING"
        recompute_sets_per_case(store, line, now)
        for card_set in sets_under_line(store, line["id"]):
            card_set["print_run_status"] = "UNDECIDED"
            db.touch(card_set, now)

    return jsonify(response.ok_object(_serialize(rec))), 200


@app.route("/api/licenses/<license_id>/product-lines", methods=["GET"])
def list_license_product_lines(license_id):
    principal = authenticate(request.headers)
    require_role(principal, READ_ROLES)
    _get(license_id)

    store = db.STORE
    items = [p for p in store.all("product_lines") if p["license_id"] == license_id]
    items.sort(key=lambda r: r["created_at"])
    payload = [serialize("product_lines", p) for p in items]
    return jsonify(response.paginate(payload, request.args)), 200