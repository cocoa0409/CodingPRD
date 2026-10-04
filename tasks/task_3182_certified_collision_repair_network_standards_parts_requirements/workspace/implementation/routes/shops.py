"""Shop, certification cycle, and attestation endpoints."""
import re
from datetime import timedelta

from flask import Blueprint, request

import calc
import sweep
from db import db, serialize
from util import (ApiError, bump, get_json, iso_ms, new_common, now_logical, ok,
                  paginate, parse_dt, sort_by_created)

bp = Blueprint("shops", __name__)

ROLES_READ_SHOPS = {"NetworkAdmin", "NetworkAuditor", "ShopManager", "DealerRep",
                    "InsurerRep"}
ROLES_READ_CYCLES = {"NetworkAdmin", "NetworkAuditor", "ShopManager"}
ROLES_READ_ATTEST = {"NetworkAdmin", "NetworkAuditor", "ShopManager"}
SHOP_STATUSES = {"APPLICANT", "CERTIFIED", "PROBATION", "SUSPENDED", "EXPIRED",
                 "DECERTIFIED"}


def require_roles(*roles):
    role = request.headers.get("X-User-Role")
    if role not in roles:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       f"Role {role} is not permitted for this endpoint")


def get_shop_or_404(shop_id):
    shop = db.shops.get(shop_id)
    if not shop:
        raise ApiError("ERR_NOT_FOUND", 404, "Shop not found")
    return shop


def get_cycle_or_404(cycle_id):
    cycle = db.cycles.get(cycle_id)
    if not cycle:
        raise ApiError("ERR_NOT_FOUND", 404, "Certification cycle not found")
    return cycle


# ---------------------------------------------------------------------------
# Shops
# ---------------------------------------------------------------------------
@bp.post("/network/shops")
def create_shop():
    require_roles("NetworkAdmin")
    body = get_json()
    legal_name = body.get("legal_name")
    state_code = body.get("state_code")
    zip_code = body.get("zip_code")
    latitude = body.get("latitude")
    longitude = body.get("longitude")
    structural = body.get("structural_capability", False)
    if not isinstance(legal_name, str) or not legal_name:
        raise ApiError("ERR_INVALID_REQUEST", 400, "legal_name is required")
    if not isinstance(state_code, str) or not re.fullmatch(r"[A-Z]{2}", state_code):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "state_code must be 2 uppercase letters")
    if not isinstance(zip_code, str) or not re.fullmatch(r"\d{5}", zip_code):
        raise ApiError("ERR_INVALID_REQUEST", 400, "zip_code must be 5 digits")
    if not isinstance(latitude, (int, float)) or isinstance(latitude, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "latitude must be a number")
    if not isinstance(longitude, (int, float)) or isinstance(longitude, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "longitude must be a number")
    if not isinstance(structural, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "structural_capability must be a boolean")
    shop = new_common()
    shop.update({
        "legal_name": legal_name,
        "state_code": state_code,
        "zip_code": zip_code,
        "latitude": latitude,
        "longitude": longitude,
        "certification_status": "APPLICANT",
        "locator_hidden": False,
        "structural_capability": structural,
        "lifetime_repair_count": 0,
        "pending_referral_count": 0,
        "warranty_reserve_cents": 0,
        "live_compliance_score": 0.0,
        "_suspended_at": None,
    })
    db.shops[shop["id"]] = shop
    return ok(serialize(shop), 201)


@bp.get("/network/shops")
def list_shops():
    require_roles(*ROLES_READ_SHOPS)
    state_code = request.args.get("state_code")
    status = request.args.get("certification_status")
    items = list(db.shops.values())
    if state_code is not None:
        items = [s for s in items if s["state_code"] == state_code]
    if status is not None:
        items = [s for s in items if s["certification_status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok([serialize(s) for s in page], 200, meta)


@bp.get("/network/shops/<shop_id>")
def get_shop(shop_id):
    require_roles(*ROLES_READ_SHOPS)
    return ok(serialize(get_shop_or_404(shop_id)))


@bp.post("/network/shops/<shop_id>/decertify")
def decertify_shop(shop_id):
    require_roles("NetworkAdmin")
    shop = get_shop_or_404(shop_id)
    if shop["certification_status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a SUSPENDED shop can be decertified")
    open_statuses = {"ESTIMATE", "APPROVED", "IN_REPAIR", "QC", "REWORK", "CALIBRATION"}
    has_open = any(o["shop_id"] == shop["id"] and o["status"] in open_statuses
                   for o in db.repair_orders.values())
    grace_ok = False
    if shop.get("_suspended_at"):
        grace_ok = (now_logical() - shop["_suspended_at"]).days >= calc.DECERTIFY_GRACE_DAYS
    if not grace_ok or has_open:
        raise ApiError("ERR_DECERTIFY_BLOCKED", 422,
                       "Shop must be SUSPENDED for at least 90 days with no open repair orders")
    sweep.set_shop_posture(shop, "DECERTIFIED")
    return ok(serialize(shop))


# ---------------------------------------------------------------------------
# Certification cycles
# ---------------------------------------------------------------------------
@bp.post("/network/shops/<shop_id>/certification-cycles")
def create_cycle(shop_id):
    require_roles("NetworkAdmin")
    shop = get_shop_or_404(shop_id)
    body = get_json()
    ws = parse_dt(body.get("window_start"), "window_start")
    we = parse_dt(body.get("window_end"), "window_end")
    expected_end = ws + timedelta(days=365) - timedelta(seconds=1)
    if we != expected_end:
        raise ApiError("ERR_CYCLE_WINDOW", 422,
                       "window_end must equal window_start + 365 days - 1 second")
    prev_cycles = sort_by_created([c for c in db.cycles.values()
                                   if c["shop_id"] == shop["id"]])
    if prev_cycles:
        prev_end = parse_dt(prev_cycles[-1]["window_end"], "window_end")
        if ws != prev_end + timedelta(seconds=1):
            raise ApiError("ERR_CYCLE_WINDOW", 422,
                           "window_start must equal previous window_end + 1 second")
    cycle = new_common()
    cycle.update({
        "shop_id": shop["id"],
        "cycle_index": len(prev_cycles) + 1,
        "window_start": iso_ms(ws),
        "window_end": iso_ms(we),
        "status": "OPEN",
        "audit_snapshot_score": None,
    })
    db.cycles[cycle["id"]] = cycle
    return ok(serialize(cycle), 201)


@bp.get("/network/shops/<shop_id>/certification-cycles")
def list_cycles(shop_id):
    require_roles(*ROLES_READ_CYCLES)
    get_shop_or_404(shop_id)
    items = sort_by_created([c for c in db.cycles.values()
                             if c["shop_id"] == shop_id])
    page, meta = paginate(items)
    return ok([serialize(c) for c in page], 200, meta)


@bp.get("/network/certification-cycles/<cycle_id>")
def get_cycle(cycle_id):
    require_roles(*ROLES_READ_CYCLES)
    return ok(serialize(get_cycle_or_404(cycle_id)))


def _shop_audits(shop_id):
    return [a for a in db.audits.values()
            if db.cycles.get(a["cycle_id"], {}).get("shop_id") == shop_id]


def _latest_audit_for_cycle(cycle_id):
    audits = sort_by_created([a for a in db.audits.values()
                              if a["cycle_id"] == cycle_id])
    return audits[-1] if audits else None


@bp.post("/network/certification-cycles/<cycle_id>/close")
def close_cycle(cycle_id):
    require_roles("NetworkAuditor")
    cycle = get_cycle_or_404(cycle_id)
    body = get_json()
    if "expected_cycle_version" not in body or not isinstance(
            body.get("expected_cycle_version"), int):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "expected_cycle_version is required")
    result = body.get("result")
    if result not in ("PASS", "FAIL"):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "result must be PASS or FAIL")
    if cycle["status"] not in ("UNDER_AUDIT", "CORRECTIVE_ACTION"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Cycle is not in a closable state")
    if body["expected_cycle_version"] != cycle["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_cycle_version does not match current cycle version")

    shop = get_shop_or_404(cycle["shop_id"])
    audit = _latest_audit_for_cycle(cycle["id"])
    if not audit:
        raise ApiError("ERR_INVALID_STATE", 409, "Cycle has no audit")

    if result == "FAIL":
        audit["status"] = "FAILED"
        if audit.get("grade") is None:
            grade, sp, _ = calc.grade_for_audit(audit)
            audit["grade"] = grade
            audit["severity_points"] = sp
        bump(audit)
        cycle["status"] = "CLOSED_FAIL"
        cycle["audit_snapshot_score"] = calc.compute_compliance_score(shop)
        bump(cycle)
        if shop["certification_status"] in ("CERTIFIED", "PROBATION"):
            sweep.set_shop_posture(shop, "SUSPENDED")
        return ok(serialize(cycle))

    # result == PASS
    if cycle["status"] == "CORRECTIVE_ACTION":
        for a in db.corrective_actions.values():
            if a["audit_id"] == audit["id"] \
                    and a["status"] not in ("VERIFIED", "REJECTED"):
                raise ApiError("ERR_INVALID_STATE", 409,
                               "All corrective actions must be VERIFIED before close")
    if audit["status"] not in ("PASSED",):
        if not (cycle["status"] == "CORRECTIVE_ACTION"
                and audit["status"] == "PASSED"):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Audit has not passed; cannot close with PASS")

    grade, sp, _ = calc.grade_for_audit(audit)
    audit["grade"] = grade
    audit["severity_points"] = sp
    bump(audit)

    shop_status = shop["certification_status"]
    if shop_status == "PROBATION" and grade in ("A", "B"):
        for a in db.corrective_actions.values():
            aud = db.audits.get(a["audit_id"])
            cyc = db.cycles.get(aud["cycle_id"]) if aud else None
            if cyc and cyc["shop_id"] == shop["id"] \
                    and a["status"] in ("OPEN", "SUBMITTED") \
                    and parse_dt(a["due_at"], "due_at") < now_logical():
                raise ApiError("ERR_INVALID_STATE", 409,
                               "Past-due corrective actions block restoration")
    if shop_status == "SUSPENDED" and grade in ("A", "B"):
        for a in db.corrective_actions.values():
            if a["audit_id"] == audit["id"] and a["status"] != "VERIFIED":
                raise ApiError("ERR_INVALID_STATE", 409,
                               "All corrective actions of the current cycle must be VERIFIED")

    cycle["status"] = "CLOSED_PASS"
    cycle["audit_snapshot_score"] = calc.compute_compliance_score(shop)
    bump(cycle)
    sweep.apply_pass_posture(shop, cycle, grade)
    return ok(serialize(cycle))


# ---------------------------------------------------------------------------
# Attestations
# ---------------------------------------------------------------------------
@bp.post("/network/shops/<shop_id>/attestations")
def create_attestation(shop_id):
    require_roles("ShopManager")
    if request.headers.get("X-User-ID") != shop_id:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "ShopManager may only attest for their own shop")
    shop = get_shop_or_404(shop_id)
    body = get_json()
    requirement_id = body.get("requirement_id")
    evidence_uri = body.get("evidence_uri")
    expected = body.get("expected_shop_version")
    if requirement_id is None or requirement_id not in db.requirements:
        raise ApiError("ERR_NOT_FOUND", 404, "Requirement not found")
    req = db.requirements[requirement_id]
    if shop["certification_status"] not in ("CERTIFIED", "PROBATION", "APPLICANT"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Shop posture forbids attestation")
    if not isinstance(expected, int) or expected != shop["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_shop_version does not match current shop version")
    if req["status"] != "PUBLISHED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Requirement is not PUBLISHED")
    if not isinstance(evidence_uri, str) or not evidence_uri:
        raise ApiError("ERR_INVALID_REQUEST", 400, "evidence_uri is required")

    # Supersede the older ACTIVE attestation for the same requirement row.
    for a in db.attestations.values():
        if a["shop_id"] == shop["id"] and a["requirement_id"] == req["id"] \
                and a["status"] == "ACTIVE":
            a["status"] = "SUPERSEDED"
            bump(a)

    att = new_common()
    att.update({
        "shop_id": shop["id"],
        "requirement_id": req["id"],
        "evidence_uri": evidence_uri,
        "attested_at": iso_ms(now_logical()),
        "status": "ACTIVE",
        "lapse_reason": None,
    })
    db.attestations[att["id"]] = att
    calc.recompute_shop_score(shop)
    bump(shop)
    return ok(serialize(att), 201)


@bp.get("/network/shops/<shop_id>/attestations")
def list_shop_attestations(shop_id):
    require_roles(*ROLES_READ_ATTEST)
    get_shop_or_404(shop_id)
    status = request.args.get("status")
    items = [a for a in db.attestations.values() if a["shop_id"] == shop_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok([serialize(a) for a in page], 200, meta)


@bp.get("/network/attestations")
def list_attestations():
    require_roles("NetworkAdmin", "NetworkAuditor")
    requirement_id = request.args.get("requirement_id")
    shop_id = request.args.get("shop_id")
    status = request.args.get("status")
    items = list(db.attestations.values())
    if requirement_id is not None:
        items = [a for a in items if a["requirement_id"] == requirement_id]
    if shop_id is not None:
        items = [a for a in items if a["shop_id"] == shop_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok([serialize(a) for a in page], 200, meta)


@bp.get("/network/attestations/<att_id>")
def get_attestation(att_id):
    require_roles(*ROLES_READ_ATTEST)
    att = db.attestations.get(att_id)
    if not att:
        raise ApiError("ERR_NOT_FOUND", 404, "Attestation not found")
    return ok(serialize(att))
