"""Taxpayer registry routes: create/read/update (OCC), IP PIN opt-in/out,
nested identity-theft reports and protection pins."""
from datetime import timedelta

from flask import Blueprint

import calc
from auth import forbid_other_taxpayer, require_roles
from domain import (active_pin, create_pin, get_taxpayer, new_record, pub,
                    touch)
from envelope import created, list_response, ok
from errors import err
from store import DB, parse_ts
from validate import (body, is_int, opt_enum, opt_int, page, pagination,
                      req_date, req_field, req_int, req_str, req_tin, invalid)

bp = Blueprint("taxpayers", __name__)

DELIVERY_CHANNELS = ("POSTAL_MAIL", "ONLINE_ACCOUNT")
REPORT_SOURCES = ("TAXPAYER_REPORT", "DUPLICATE_DETECTION")


def _own_taxpayer_path(uid, role, taxpayer_id):
    """Priority 3 ownership on taxpayer-id path params (checked before 404)."""
    forbid_other_taxpayer(uid, role, taxpayer_id)


@bp.post("/identity-protection/taxpayers")
def create_taxpayer():
    require_roles(["SystemAdmin"])
    b = body()
    # Priority 8: duplicate tin (before priority-14 payload shape).
    tin = b.get("tin")
    if isinstance(tin, str):
        for t in DB.taxpayers.values():
            if t["tin"] == tin:
                err("ERR_DUPLICATE_TIN")
    # Priority 14: payload shape.
    tin = req_tin(b, "tin")
    full_name = req_str(b, "full_name")
    dob = req_date(b, "date_of_birth")
    prior = opt_int(b, "prior_year_refund_cents", 0)
    if prior < 0:
        invalid("prior_year_refund_cents must be >= 0")
    channel = opt_enum(b, "pin_delivery_channel", DELIVERY_CHANNELS, "POSTAL_MAIL")
    rec = new_record(DB.taxpayers, {
        "tin": tin,
        "full_name": full_name,
        "date_of_birth": dob,
        "prior_year_refund_cents": prior,
        "pin_delivery_channel": channel,
        "status": "ACTIVE",
        "ip_pin_enrollment": "NOT_ENROLLED",
    })
    return created(pub(rec))


@bp.get("/identity-protection/taxpayers/<string:taxpayer_id>")
def read_taxpayer(taxpayer_id):
    uid, role = require_roles(
        ["SystemAdmin", "FraudAnalyst", "VerificationAgent", "TaxpayerAdvocate", "Taxpayer"])
    _own_taxpayer_path(uid, role, taxpayer_id)
    return ok(pub(get_taxpayer(taxpayer_id)))


@bp.put("/identity-protection/taxpayers/<string:taxpayer_id>")
def update_taxpayer(taxpayer_id):
    uid, role = require_roles(["Taxpayer", "SystemAdmin"])
    _own_taxpayer_path(uid, role, taxpayer_id)
    t = get_taxpayer(taxpayer_id)
    b = body()
    # Priority 5: OCC (expected_taxpayer_version must equal current version).
    expected = b.get("expected_taxpayer_version")
    if expected is not None and expected != t["version"]:
        err("ERR_STALE_VERSION")
    # Priority 14: payload shape (expected_taxpayer_version is non-optional).
    req_field(b, "expected_taxpayer_version")
    if not is_int(b["expected_taxpayer_version"]):
        invalid("expected_taxpayer_version must be an integer")
    if "full_name" in b and b["full_name"] is not None:
        t["full_name"] = req_str(b, "full_name")
    if "date_of_birth" in b and b["date_of_birth"] is not None:
        t["date_of_birth"] = req_date(b, "date_of_birth")
    if "prior_year_refund_cents" in b and b["prior_year_refund_cents"] is not None:
        prior = opt_int(b, "prior_year_refund_cents")
        if prior < 0:
            invalid("prior_year_refund_cents must be >= 0")
        t["prior_year_refund_cents"] = prior
    if "pin_delivery_channel" in b and b["pin_delivery_channel"] is not None:
        t["pin_delivery_channel"] = opt_enum(b, "pin_delivery_channel", DELIVERY_CHANNELS)
    touch(t)  # success increments version by exactly 1
    return ok(pub(t))


@bp.post("/identity-protection/taxpayers/<string:taxpayer_id>/ip-pin-opt-in")
def opt_in(taxpayer_id):
    uid, role = require_roles(["Taxpayer", "SystemAdmin"])
    _own_taxpayer_path(uid, role, taxpayer_id)
    t = get_taxpayer(taxpayer_id)
    b = body()
    # Priority 6: permitted from NOT_ENROLLED and OPTED_OUT only.
    if t["ip_pin_enrollment"] not in ("NOT_ENROLLED", "OPTED_OUT"):
        err("ERR_INVALID_STATE", "Already ENROLLED in the IP PIN program.")
    # Priority 14: payload shape.
    tax_year = req_int(b, "tax_year")
    channel = opt_enum(b, "delivery_channel", DELIVERY_CHANNELS)
    t["ip_pin_enrollment"] = "ENROLLED"
    touch(t)
    create_pin(t, tax_year, channel or t["pin_delivery_channel"])
    return ok(pub(t))


@bp.post("/identity-protection/taxpayers/<string:taxpayer_id>/ip-pin-opt-out")
def opt_out(taxpayer_id):
    uid, role = require_roles(["Taxpayer", "SystemAdmin"])
    _own_taxpayer_path(uid, role, taxpayer_id)
    t = get_taxpayer(taxpayer_id)
    # Priority 11: opt-out requires ENROLLED.
    if t["ip_pin_enrollment"] != "ENROLLED":
        err("ERR_NOT_ENROLLED")
    t["ip_pin_enrollment"] = "OPTED_OUT"
    touch(t)
    for p in DB.pins.values():
        if p["taxpayer_id"] == t["id"] and p["status"] == "ACTIVE":
            p["status"] = "REVOKED"
            touch(p)
    return ok(pub(t))


@bp.post("/identity-protection/taxpayers/<string:taxpayer_id>/identity-theft-reports")
def file_report(taxpayer_id):
    uid, role = require_roles(["Taxpayer", "FraudAnalyst"])
    _own_taxpayer_path(uid, role, taxpayer_id)
    t = get_taxpayer(taxpayer_id)
    # Priority 9: review-window exclusivity (closed 60-day window).
    now = DB.now()
    for r in DB.reports.values():
        if r["taxpayer_id"] != t["id"] or r["status"] != "SUBMITTED":
            continue
        start = parse_ts(r["created_at"])
        if start <= now <= start + timedelta(days=calc.REPORT_WINDOW_DAYS):
            err("ERR_ACTIVE_REPORT_WINDOW")
    # Priority 14: payload shape. DUPLICATE_DETECTION is system-reserved.
    b = body()
    source = req_field(b, "source")
    if source not in REPORT_SOURCES or source == "DUPLICATE_DETECTION":
        invalid("source must be TAXPAYER_REPORT")
    description = b.get("description", "")
    if not isinstance(description, str):
        invalid("description must be a string")
    rec = new_record(DB.reports, {
        "taxpayer_id": t["id"],
        "source": source,
        "description": description,
        "created_by_user_id": uid,
        "confirmed_tax_year": None,
        "status": "SUBMITTED",
    })
    return created(pub(rec))


@bp.get("/identity-protection/taxpayers/<string:taxpayer_id>/identity-theft-reports")
def list_reports(taxpayer_id):
    uid, role = require_roles(["Taxpayer", "FraudAnalyst", "TaxpayerAdvocate", "SystemAdmin"])
    _own_taxpayer_path(uid, role, taxpayer_id)
    t = get_taxpayer(taxpayer_id)
    limit, offset = pagination()
    rows = [r for r in DB.reports.values() if r["taxpayer_id"] == t["id"]]
    items, total = page(rows, limit, offset)
    return list_response([pub(r) for r in items], total, limit, offset)


@bp.get("/identity-protection/taxpayers/<string:taxpayer_id>/protection-pins")
def list_pins(taxpayer_id):
    uid, role = require_roles(["Taxpayer", "SystemAdmin", "FraudAnalyst", "TaxpayerAdvocate"])
    _own_taxpayer_path(uid, role, taxpayer_id)
    t = get_taxpayer(taxpayer_id)
    limit, offset = pagination()
    rows = [p for p in DB.pins.values() if p["taxpayer_id"] == t["id"]]
    items, total = page(rows, limit, offset)
    return list_response([pub(p) for p in items], total, limit, offset)
