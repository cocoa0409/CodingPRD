"""License agreements and licensed stores."""
from flask import Blueprint, request

import errors as E
import middleware as mw
from db import db
from response import success_list, success_object
from services import calculations as calc
from services import cascades

bp = Blueprint("agreements", __name__)

ROYALTY_BASES = ("ACCRUAL", "CASH")
LIVE_AGREEMENT_STATES = ("PENDING_ACCEPTANCE", "ACTIVE", "SUSPENDED")


def pub_agreement(a):
    return {
        "id": a["id"], "licensee_id": a["licensee_id"], "venue_id": a["venue_id"],
        "royalty_tiers": [dict(t) for t in a["royalty_tiers"]],
        "royalty_basis": a["royalty_basis"],
        "term_start_date": a["term_start_date"], "term_end_date": a["term_end_date"],
        "status": a["status"], "breach_strikes": a["breach_strikes"],
        "created_at": a["created_at"], "updated_at": a["updated_at"], "version": a["version"],
    }


def pub_store(s):
    return {
        "id": s["id"], "agreement_id": s["agreement_id"], "store_code": s["store_code"],
        "equipment_footprint_units": s["equipment_footprint_units"],
        "operating_status": s["operating_status"],
        "compliance_posture": s["compliance_posture"],
        "created_at": s["created_at"], "updated_at": s["updated_at"], "version": s["version"],
    }


def _get_agreement(aid):
    a = db.license_agreements.get(aid)
    if a is None:
        raise E.err_not_found("license agreement not found")
    return a


def get_store(sid):
    s = db.stores.get(sid)
    if s is None:
        raise E.err_not_found("store not found")
    return s


def _agreement_view_scope(uid, role, agreement):
    if role == "LicenseeManager" and uid != agreement["licensee_id"]:
        raise E.err_forbidden()
    if role == "HostVenueManager" and uid != agreement["venue_id"]:
        raise E.err_forbidden()


# ---------------------------------------------------------------------------
# Agreements
# ---------------------------------------------------------------------------

@bp.post("/licensing/license-agreements")
def create_agreement():
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin",))
    b = mw.body()
    licensee_id = mw.req_str(b, "licensee_id")
    venue_id = mw.req_str(b, "venue_id")
    tiers = b.get("royalty_tiers")
    basis = mw.req_enum(b, "royalty_basis", ROYALTY_BASES)
    term_start = mw.req_date(b, "term_start_date")
    term_end = mw.req_date(b, "term_end_date")
    if licensee_id not in db.licensees:
        raise E.err_not_found("licensee not found")
    if venue_id not in db.host_venues:
        raise E.err_not_found("host venue not found")
    calc.validate_royalty_tiers(tiers)
    if term_end <= term_start:
        raise E.err_invalid_request("term_end_date must be strictly after term_start_date")
    rec = mw.make_resource({
        "licensee_id": licensee_id, "venue_id": venue_id,
        "royalty_tiers": [{"threshold_cents": t["threshold_cents"], "rate_bps": t["rate_bps"]} for t in tiers],
        "royalty_basis": basis,
        "term_start_date": term_start.isoformat(), "term_end_date": term_end.isoformat(),
        "status": "DRAFT", "breach_strikes": 0,
    })
    db.license_agreements[rec["id"]] = rec
    return success_object(pub_agreement(rec), 201)


@bp.get("/licensing/license-agreements/<aid>")
def get_agreement(aid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "LicenseeManager", "HostVenueManager"))
    a = _get_agreement(aid)
    _agreement_view_scope(uid, role, a)
    return success_object(pub_agreement(a))


@bp.get("/licensing/license-agreements")
def list_agreements():
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "LicenseeManager"))
    items = list(db.license_agreements.values())
    if role == "LicenseeManager":
        items = [a for a in items if a["licensee_id"] == uid]
    lic = request.args.get("licensee_id")
    if lic is not None:
        items = [a for a in items if a["licensee_id"] == lic]
    ven = request.args.get("venue_id")
    if ven is not None:
        items = [a for a in items if a["venue_id"] == ven]
    st = request.args.get("status")
    if st is not None:
        items = [a for a in items if a["status"] == st]
    page, limit, offset, total = mw.paginate(items)
    return success_list([pub_agreement(x) for x in page], limit, offset, total)


@bp.post("/licensing/license-agreements/<aid>/submit")
def submit_agreement(aid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin",))
    a = _get_agreement(aid)
    if a["status"] != "DRAFT":
        raise E.err_invalid_agreement_state()
    a["status"] = "PENDING_ACCEPTANCE"
    mw.touch(a)
    return success_object(pub_agreement(a))


@bp.post("/licensing/license-agreements/<aid>/accept")
def accept_agreement(aid):
    uid, role = mw.auth()
    mw.require_role(role, ("HostVenueManager",))
    a = _get_agreement(aid)
    if uid != a["venue_id"]:
        raise E.err_forbidden("HostVenueManager identity must equal the agreement's venue_id")
    if a["status"] != "PENDING_ACCEPTANCE":
        raise E.err_invalid_agreement_state()
    for other in db.license_agreements.values():
        if other["id"] == a["id"]:
            continue
        if other["venue_id"] == a["venue_id"] and other["status"] in LIVE_AGREEMENT_STATES:
            raise E.err_uniqueness("another live agreement exists for this venue")
    a["status"] = "ACTIVE"
    mw.touch(a)
    return success_object(pub_agreement(a))


@bp.post("/licensing/license-agreements/<aid>/suspend")
def suspend_agreement(aid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin",))
    a = _get_agreement(aid)
    if a["status"] != "ACTIVE":
        raise E.err_invalid_agreement_state()
    cascades.suspend_agreement(a)
    return success_object(pub_agreement(a))


@bp.post("/licensing/license-agreements/<aid>/reinstate")
def reinstate_agreement(aid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin",))
    a = _get_agreement(aid)
    if a["status"] != "SUSPENDED":
        raise E.err_invalid_agreement_state()
    a["status"] = "ACTIVE"
    a["breach_strikes"] = 0
    mw.touch(a)
    return success_object(pub_agreement(a))


@bp.post("/licensing/license-agreements/<aid>/terminate")
def terminate_agreement(aid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin",))
    a = _get_agreement(aid)
    if a["status"] not in ("ACTIVE", "SUSPENDED"):
        raise E.err_invalid_agreement_state()
    cascades.terminate_or_expire_agreement(a, "TERMINATED")
    return success_object(pub_agreement(a))


@bp.post("/licensing/license-agreements/<aid>/sweep-expiry")
def sweep_expiry_agreement(aid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin",))
    a = _get_agreement(aid)
    if a["status"] not in ("ACTIVE", "SUSPENDED"):
        raise E.err_invalid_agreement_state()
    from datetime import date as _date
    term_end = _date.fromisoformat(a["term_end_date"])
    if db.clock.date() <= term_end:
        raise E.err_invalid_request("logical clock date is not strictly after term_end_date")
    cascades.terminate_or_expire_agreement(a, "EXPIRED")
    return success_object(pub_agreement(a))


@bp.patch("/licensing/license-agreements/<aid>")
def amend_agreement(aid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin",))
    a = _get_agreement(aid)
    b = mw.body()
    new_tiers = a["royalty_tiers"]
    if "royalty_tiers" in b:
        calc.validate_royalty_tiers(b["royalty_tiers"])
        new_tiers = [{"threshold_cents": t["threshold_cents"], "rate_bps": t["rate_bps"]}
                     for t in b["royalty_tiers"]]
    new_basis = a["royalty_basis"]
    if "royalty_basis" in b:
        v = b["royalty_basis"]
        if v not in ROYALTY_BASES:
            raise E.err_invalid_request("royalty_basis must be one of CASH, ACCRUAL")
        new_basis = v
    new_term_end = a["term_end_date"]
    if "term_end_date" in b:
        te = mw.opt_date(b, "term_end_date")
        from datetime import date as _date
        if te <= _date.fromisoformat(a["term_start_date"]):
            raise E.err_invalid_request("term_end_date must be strictly after term_start_date")
        new_term_end = te.isoformat()
    expected = b.get("expected_agreement_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise E.err_invalid_request("expected_agreement_version is required and must be an integer")
    if expected != a["version"]:
        raise E.err_stale_version()
    a["royalty_tiers"] = new_tiers
    a["royalty_basis"] = new_basis
    a["term_end_date"] = new_term_end
    mw.touch(a)
    return success_object(pub_agreement(a))


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------

@bp.post("/licensing/license-agreements/<aid>/stores")
def create_store(aid):
    uid, role = mw.auth()
    mw.require_role(role, ("LicenseeManager", "BrandProgramAdmin"))
    a = _get_agreement(aid)
    if role == "LicenseeManager" and uid != a["licensee_id"]:
        raise E.err_forbidden()
    if a["status"] != "ACTIVE":
        raise E.err_agreement_not_active("store creation requires an ACTIVE agreement")
    b = mw.body()
    store_code = mw.req_str(b, "store_code")
    footprint = mw.req_int(b, "equipment_footprint_units", minimum=1)
    for s in db.stores.values():
        if s["agreement_id"] == aid and s["store_code"] == store_code:
            raise E.err_uniqueness("store_code already exists within this agreement")
    rec = mw.make_resource({
        "agreement_id": aid, "store_code": store_code,
        "equipment_footprint_units": footprint,
        "operating_status": "PROVISIONING", "compliance_posture": "GOOD_STANDING",
    })
    db.stores[rec["id"]] = rec
    return success_object(pub_store(rec), 201)


@bp.get("/licensing/stores/<sid>")
def fetch_store(sid):
    uid, role = mw.auth()
    mw.require_role(role, (
        "BrandProgramAdmin", "LicenseeManager", "HostVenueManager", "BrandInspector",
        "DistributorAgent",
    ))
    s = get_store(sid)
    if role == "LicenseeManager" and uid != mw.licensee_of_store(s):
        raise E.err_forbidden()
    return success_object(pub_store(s))


@bp.get("/licensing/license-agreements/<aid>/stores")
def list_stores(aid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "LicenseeManager", "HostVenueManager"))
    a = _get_agreement(aid)
    _agreement_view_scope(uid, role, a)
    items = [s for s in db.stores.values() if s["agreement_id"] == aid]
    page, limit, offset, total = mw.paginate(items)
    return success_list([pub_store(x) for x in page], limit, offset, total)


@bp.post("/licensing/stores/<sid>/request-certification")
def request_certification(sid):
    uid, role = mw.auth()
    mw.require_role(role, ("LicenseeManager",))
    s = get_store(sid)
    if uid != mw.licensee_of_store(s):
        raise E.err_forbidden()
    if s["operating_status"] != "PROVISIONING":
        raise E.err_invalid_store_state()
    s["operating_status"] = "CERT_PENDING"
    mw.touch(s)
    return success_object(pub_store(s))


@bp.post("/licensing/stores/<sid>/begin-operations")
def begin_operations(sid):
    uid, role = mw.auth()
    mw.require_role(role, ("LicenseeManager",))
    s = get_store(sid)
    if uid != mw.licensee_of_store(s):
        raise E.err_forbidden()
    if s["operating_status"] != "CERT_PENDING":
        raise E.err_invalid_store_state()
    a = db.license_agreements[s["agreement_id"]]
    if a["status"] != "ACTIVE":
        raise E.err_agreement_not_active("begin-operations requires an ACTIVE agreement")
    if calc.certified_active_baristas(a["licensee_id"]) < calc.MIN_CERTIFIED_BARISTAS:
        raise E.err_insufficient_staff()
    venue = db.host_venues[a["venue_id"]]
    if calc.venue_footprint_usage(venue["id"]) > venue["max_equipment_footprint_units"]:
        raise E.err_footprint()
    s["operating_status"] = "OPERATING"
    mw.touch(s)
    calc.recompute_posture(s)
    return success_object(pub_store(s))


@bp.post("/licensing/stores/<sid>/suspend")
def suspend_store(sid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin",))
    s = get_store(sid)
    if s["operating_status"] != "OPERATING":
        raise E.err_invalid_store_state()
    cascades.suspend_store(s)
    return success_object(pub_store(s))


@bp.post("/licensing/stores/<sid>/resume")
def resume_store(sid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin",))
    s = get_store(sid)
    if s["operating_status"] != "SUSPENDED":
        raise E.err_invalid_store_state()
    a = db.license_agreements[s["agreement_id"]]
    if a["status"] != "ACTIVE":
        raise E.err_agreement_not_active("resume requires an ACTIVE parent agreement")
    s["operating_status"] = "OPERATING"
    mw.touch(s)
    calc.recompute_posture(s)
    return success_object(pub_store(s))


@bp.post("/licensing/stores/<sid>/delicense")
def delicense_store(sid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin",))
    s = get_store(sid)
    if s["operating_status"] == "DELICENSED":
        raise E.err_invalid_store_state()
    cascades.delicense_store(s)
    return success_object(pub_store(s))
