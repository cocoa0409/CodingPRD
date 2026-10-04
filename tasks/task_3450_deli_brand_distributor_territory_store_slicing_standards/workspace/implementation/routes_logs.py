"""OpenedProductLog and TrainingCertification endpoints (PRD SS3.5 / SS3.6)."""
from datetime import timedelta

from flask import Blueprint, request

import store
from domain import (CERT_VALIDITY_DAYS, CLEANING_WINDOW_HOURS,
                    LATE_PULL_SUSPENSION_THRESHOLD, late_pulls_30d, lazy_cert,
                    suspend_account, touch)
from errors import fail
from serializers import ser_cert, ser_log
from store import db
from util import (auth, body, list_response, new_id, ok, opt_dt, req_bool,
                  req_str, sort_std)

bp = Blueprint("logs", __name__)

LOG_READERS = ("BrandAdmin", "DistributorRep", "RetailManager", "SafetyOfficer")
CERT_READERS = ("BrandAdmin", "DistributorRep", "RetailManager")


# ---------------------------------------------------------------------------
# opened product logs
# ---------------------------------------------------------------------------

@bp.post("/api/opened-product-logs")
def create_log():
    _, uid = auth("RetailManager")
    b = body()
    product_id = req_str(b, "product_id")
    slicer_id = req_str(b, "slicer_id")
    opened_at = opt_dt(b, "opened_at")
    if opened_at is None:
        opened_at = store.now()  # omitted: defaults to the logical clock now
    product = db["products"].get(product_id)
    if product is None:
        fail("ERR_NOT_FOUND", 404, "product not found")
    slicer = db["slicers"].get(slicer_id)
    if slicer is None:
        fail("ERR_NOT_FOUND", 404, "slicer not found")
    # allergen separation at opening (SS3.5): slicer must be ACTIVE and belong
    # to the caller's account; dedication / 24h cleaning rules apply
    if slicer["account_id"] != uid or slicer["status"] != "ACTIVE":
        fail("ERR_ALLERGEN_CROSS_CONTACT", 422,
             "slicer is not ACTIVE or does not belong to the caller's account")
    tags = product["allergen_tags"]
    if product["requires_dedicated_slicer"]:
        if slicer["dedicated_allergen"] not in tags:
            fail("ERR_ALLERGEN_CROSS_CONTACT", 422,
                 "product requires a dedicated slicer for one of its allergens")
    elif tags:
        compliant = slicer["dedicated_allergen"] in tags
        if not compliant and slicer["cleaning_verified_at"] is not None:
            compliant = (slicer["cleaning_verified_at"]
                         >= opened_at - timedelta(hours=CLEANING_WINDOW_HOURS))
        if not compliant:
            fail("ERR_ALLERGEN_CROSS_CONTACT", 422,
                 "slicer dedication or verified cleaning does not cover the product's allergens")
    now = store.now()
    log = {
        "id": new_id(), "_seq": store.next_seq(), "account_id": uid,
        "product_id": product_id, "slicer_id": slicer_id,
        "opened_at": opened_at,
        "pull_deadline": opened_at + timedelta(hours=product["shelf_life_opened_hours"]),
        "pulled_at": None, "status": "OPEN",
        "created_at": now, "updated_at": now, "version": 1,
    }
    db["logs"][log["id"]] = log
    return ok(ser_log(log), 201)


@bp.get("/api/opened-product-logs")
def list_logs():
    auth(*LOG_READERS)
    items = sort_std(db["logs"].values())
    account_id = request.args.get("account_id")
    product_id = request.args.get("product_id")
    slicer_id = request.args.get("slicer_id")
    status = request.args.get("status")
    if account_id is not None:
        items = [l for l in items if l["account_id"] == account_id]
    if product_id is not None:
        items = [l for l in items if l["product_id"] == product_id]
    if slicer_id is not None:
        items = [l for l in items if l["slicer_id"] == slicer_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    return list_response([ser_log(l) for l in items])


@bp.get("/api/opened-product-logs/<lid>")
def get_log(lid):
    auth(*LOG_READERS)
    l = db["logs"].get(lid)
    if l is None:
        fail("ERR_NOT_FOUND", 404, "opened product log not found")
    return ok(ser_log(l))


@bp.post("/api/opened-product-logs/<lid>/pull")
def pull_log(lid):
    _, uid = auth("RetailManager")
    l = db["logs"].get(lid)
    if l is None:
        fail("ERR_NOT_FOUND", 404, "opened product log not found")
    if l["account_id"] != uid:
        fail("ERR_FORBIDDEN", 403, "X-User-ID must equal the log's account_id")
    if l["status"] != "OPEN":
        fail("ERR_ALREADY_TERMINAL", 409, "opened product log is " + l["status"])
    now = store.now()
    # boundary: a pull at exactly the deadline is ON TIME (<=)
    if now <= l["pull_deadline"]:
        l["status"] = "PULLED_ON_TIME"
    else:
        l["status"] = "PULLED_LATE"
    l["pulled_at"] = now
    touch(l)
    if l["status"] == "PULLED_LATE":
        # freshness discipline collapse: auto-suspend at the threshold
        if late_pulls_30d(l["account_id"]) >= LATE_PULL_SUSPENSION_THRESHOLD:
            account = db["accounts"].get(l["account_id"])
            if account is not None and account["approval_status"] == "APPROVED":
                suspend_account(account)
    return ok(ser_log(l))


# ---------------------------------------------------------------------------
# training certifications
# ---------------------------------------------------------------------------

@bp.post("/api/training-certifications")
def create_cert():
    _, uid = auth("DistributorRep")
    b = body()
    account_id = req_str(b, "account_id")
    associate_name = req_str(b, "associate_name")
    slicing_module_passed = req_bool(b, "slicing_module_passed")
    allergen_module_passed = req_bool(b, "allergen_module_passed")
    if db["accounts"].get(account_id) is None:
        fail("ERR_NOT_FOUND", 404, "account not found")
    # standing gate: the acting distributor must be ACTIVE
    dist = db["distributors"].get(uid)
    if dist is None:
        fail("ERR_NOT_FOUND", 404, "distributor not found")
    if dist["status"] != "ACTIVE":
        fail("ERR_DISTRIBUTOR_NOT_ACTIVE", 409, "distributor is not ACTIVE")
    now = store.now()
    c = {
        "id": new_id(), "_seq": store.next_seq(), "account_id": account_id,
        "associate_name": associate_name,
        "slicing_module_passed": slicing_module_passed,
        "allergen_module_passed": allergen_module_passed,
        "certified_at": now,
        "expires_at": now + timedelta(days=CERT_VALIDITY_DAYS),
        "status": "ACTIVE", "created_at": now,
    }
    db["certs"][c["id"]] = c
    return ok(ser_cert(c), 201)


@bp.get("/api/training-certifications")
def list_certs():
    auth(*CERT_READERS)
    items = sort_std(db["certs"].values())
    for c in items:
        lazy_cert(c)
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    if account_id is not None:
        items = [c for c in items if c["account_id"] == account_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response([ser_cert(c) for c in items])


@bp.get("/api/training-certifications/<cid>")
def get_cert(cid):
    auth(*CERT_READERS)
    c = db["certs"].get(cid)
    if c is None:
        fail("ERR_NOT_FOUND", 404, "training certification not found")
    return ok(ser_cert(c))


@bp.post("/api/training-certifications/<cid>/revoke")
def revoke_cert(cid):
    auth("BrandAdmin")
    c = db["certs"].get(cid)
    if c is None:
        fail("ERR_NOT_FOUND", 404, "training certification not found")
    lazy_cert(c)  # a stale ACTIVE cert reads as EXPIRED first
    if c["status"] in ("EXPIRED", "REVOKED"):
        fail("ERR_ALREADY_TERMINAL", 409, "training certification is " + c["status"])
    c["status"] = "REVOKED"
    return ok(ser_cert(c))
