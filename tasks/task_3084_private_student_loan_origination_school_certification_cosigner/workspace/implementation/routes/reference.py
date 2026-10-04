"""Reference-data routes: borrowers, cosigners, schools, loan policies, clock."""

from flask import Blueprint, request

from db import db, parse_iso, iso, DEFAULT_CLOCK
from common import stamp, touch, body_of, query_int, required, enum
from errors import fail
from middleware import guard, require_borrower_owns, require_cosigner_is
from response import object_body, array_body, paginate
import engine
import calc

bp = Blueprint("reference", __name__)
PREFIX = "/private-student-loans"


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------
@bp.route(PREFIX + "/_clock/set_current_utc", methods=["POST"])
@guard("PlatformAdmin", "Servicer")
def set_clock(_user_id=None, _role=None):
    data = body_of(request)
    raw = required(data, "to_iso8601")
    try:
        dt = parse_iso(raw)
    except Exception:
        fail("ERR_INVALID_CLOCK", "to_iso8601 is not a well-formed ISO 8601 instant")
    if dt is None or dt < DEFAULT_CLOCK:
        fail("ERR_INVALID_CLOCK", "to_iso8601 precedes the server start-of-time default")
    db.set_clock(dt)
    engine.sweep()
    return object_body({"current_utc": iso(db.clock)})


# ---------------------------------------------------------------------------
# borrowers
# ---------------------------------------------------------------------------
@bp.route(PREFIX + "/borrowers", methods=["POST"])
@guard("PlatformAdmin")
def create_borrower(_user_id=None, _role=None):
    data = body_of(request)
    full_name = required(data, "full_name")
    email = required(data, "email")
    state_code = required(data, "state_code")
    program_level = required(data, "program_level")
    enum(program_level, engine.PROGRAM_LEVELS)
    record = {
        "full_name": full_name,
        "email": email,
        "state_code": state_code,
        "program_level": program_level,
        "credit_score": data.get("credit_score"),
        "dti_ratio": data.get("dti_ratio"),
        "enrollment_status": data.get("enrollment_status", "IN_SCHOOL"),
        "on_time_payment_run_count": 0,
        "lifetime_on_time_payment_count": 0,
        "status": "ACTIVE",
    }
    stamp(record, new=True)
    db.borrowers[record["id"]] = record
    return object_body(engine.ser_borrower(record), 201)


@bp.route(PREFIX + "/borrowers/<bid>", methods=["GET"])
@guard("PlatformAdmin", "Borrower", "Servicer")
def read_borrower(bid, _user_id=None, _role=None):
    engine.sweep()
    record = engine.get_borrower(bid)
    return object_body(engine.ser_borrower(record))


@bp.route(PREFIX + "/borrowers", methods=["GET"])
@guard("PlatformAdmin", "Servicer")
def list_borrowers(_user_id=None, _role=None):
    limit = query_int(request, "limit", 10, 1, 100)
    offset = query_int(request, "offset", 0, 0)
    engine.sweep()
    records = engine.sort_by_created(db.borrowers.values())
    page, limit, offset, total = paginate(records, limit, offset)
    return array_body([engine.ser_borrower(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# cosigners
# ---------------------------------------------------------------------------
@bp.route(PREFIX + "/borrowers/<bid>/cosigners", methods=["POST"])
@guard("Borrower", "PlatformAdmin")
def create_cosigner(bid, _user_id=None, _role=None):
    borrower = engine.get_borrower(bid)
    if _role == "Borrower":
        require_borrower_owns(_user_id, bid)
    data = body_of(request)
    relationship = required(data, "relationship")
    enum(relationship, engine.RELATIONSHIPS)
    record = {
        "borrower_id": borrower["id"],
        "full_name": required(data, "full_name"),
        "email": required(data, "email"),
        "state_code": required(data, "state_code"),
        "relationship": relationship,
        "credit_score": data.get("credit_score"),
        "credit_history_months": data.get("credit_history_months"),
        "dti_ratio": data.get("dti_ratio"),
        "underwriting_status": "INVITED",
    }
    stamp(record, new=True)
    db.cosigners[record["id"]] = record
    return object_body(engine.ser_cosigner(record), 201)


@bp.route(PREFIX + "/cosigners/<cid>", methods=["GET"])
@guard("Borrower", "Cosigner", "Underwriter", "Servicer")
def read_cosigner(cid, _user_id=None, _role=None):
    record = engine.get_cosigner(cid, allow_released=True)
    return object_body(engine.ser_cosigner(record))


@bp.route(PREFIX + "/cosigners", methods=["GET"])
@guard("PlatformAdmin", "Servicer")
def list_cosigners(_user_id=None, _role=None):
    limit = query_int(request, "limit", 10, 1, 100)
    offset = query_int(request, "offset", 0, 0)
    records = engine.sort_by_created(db.cosigners.values())
    filter_borrower = request.args.get("borrower_id")
    if filter_borrower:
        records = [r for r in records if r.get("borrower_id") == filter_borrower]
    page, limit, offset, total = paginate(records, limit, offset)
    return array_body([engine.ser_cosigner(r) for r in page], limit, offset, total)


def _cosigner_eligibility(cosigner, policy):
    min_score = policy.get("cosigner_release_min_credit_score",
                           engine.POLICY_DEFAULTS["cosigner_release_min_credit_score"])
    max_dti = policy.get("cosigner_release_max_dti_ratio",
                         engine.POLICY_DEFAULTS["cosigner_release_max_dti_ratio"])
    score = cosigner.get("credit_score")
    dti = cosigner.get("dti_ratio")
    if score is None or dti is None:
        return False
    return int(score) >= int(min_score) - 60 and float(dti) <= float(max_dti)


def _policy_for_cosigner(cosigner):
    borrower = db.borrowers.get(cosigner.get("borrower_id"))
    if borrower is None:
        return {}
    apps = [a for a in db.applications.values() if a["borrower_id"] == borrower["id"]]
    for app in engine.sort_by_created(apps):
        pol = db.policies.get(app.get("policy_id"))
        if pol:
            return pol
    return {}


@bp.route(PREFIX + "/cosigners/<cid>/reunderwrite", methods=["POST"])
@guard("Cosigner")
def reunderwrite(cid, _user_id=None, _role=None):
    cosigner = engine.get_cosigner(cid)
    require_cosigner_is(_user_id, cid)
    engine.get_borrower(cosigner["borrower_id"])
    status = cosigner.get("underwriting_status")
    if status not in ("INVITED", "INELIGIBLE"):
        fail("ERR_INVALID_STATE", "cosigner %s cannot be re-underwritten from %s" % (cid, status))
    data = body_of(request)
    if "credit_score" in data:
        cosigner["credit_score"] = data["credit_score"]
    if "dti_ratio" in data:
        cosigner["dti_ratio"] = data["dti_ratio"]
    policy = _policy_for_cosigner(cosigner)
    cosigner["underwriting_status"] = (
        "ELIGIBLE" if _cosigner_eligibility(cosigner, policy) else "INELIGIBLE"
    )
    touch(cosigner)
    for app in db.applications.values():
        if app.get("cosigner_id") == cid:
            _reprice(app, "provisional")
    return object_body(engine.ser_cosigner(cosigner))


def _reprice(app, variant):
    borrower = db.borrowers.get(app["borrower_id"])
    cosigner = db.cosigners.get(app.get("cosigner_id")) if app.get("cosigner_id") else None
    score, tier, margin = calc.price_application(borrower, cosigner, variant)
    app["combined_credit_score"] = score
    app["tier"] = tier
    app["margin_rate_pct"] = float(margin) if margin is not None else None
    touch(app)


# ---------------------------------------------------------------------------
# cosigner-loan / release listings
# ---------------------------------------------------------------------------
@bp.route(PREFIX + "/cosigners/<cid>/loans", methods=["GET"])
@guard("Cosigner", "Servicer", "Underwriter")
def cosigner_loans(cid, _user_id=None, _role=None):
    engine.get_cosigner(cid, allow_released=True)
    engine.sweep()
    records = [l for l in engine.sort_by_created(db.loans.values())
               if l.get("cosigner_id") == cid]
    return array_body([engine.ser_loan(r) for r in records], 10, 0, len(records))


@bp.route(PREFIX + "/cosigners/<cid>/loan-applications", methods=["GET"])
@guard("Cosigner", "Underwriter", "Servicer")
def cosigner_applications(cid, _user_id=None, _role=None):
    engine.get_cosigner(cid, allow_released=True)
    records = [a for a in engine.sort_by_created(db.applications.values())
               if a.get("cosigner_id") == cid]
    return array_body([engine.ser_application(r) for r in records], 10, 0, len(records))


@bp.route(PREFIX + "/cosigners/<cid>/release-applications", methods=["GET"])
@guard("Cosigner", "Underwriter", "Servicer")
def cosigner_releases(cid, _user_id=None, _role=None):
    engine.get_cosigner(cid, allow_released=True)
    records = [r for r in engine.sort_by_created(db.release_applications.values())
               if r.get("cosigner_id") == cid]
    return array_body([engine.ser_release(r) for r in records], 10, 0, len(records))


# ---------------------------------------------------------------------------
# schools
# ---------------------------------------------------------------------------
@bp.route(PREFIX + "/schools", methods=["POST"])
@guard("PlatformAdmin")
def create_school(_user_id=None, _role=None):
    data = body_of(request)
    record = {
        "name": required(data, "name"),
        "school_code": required(data, "school_code"),
        "state_code": required(data, "state_code"),
        "certification_capacity_per_period_cents": required(
            data, "certification_capacity_per_period_cents"),
        "active": bool(data.get("active", True)),
    }
    stamp(record, new=True)
    db.schools[record["id"]] = record
    return object_body(engine.ser_school(record), 201)


@bp.route(PREFIX + "/schools/<sid>", methods=["GET"])
@guard("PlatformAdmin", "School", "Servicer", "Underwriter")
def read_school(sid, _user_id=None, _role=None):
    record = engine.get_school(sid)
    return object_body(engine.ser_school(record))


@bp.route(PREFIX + "/schools", methods=["GET"])
@guard("PlatformAdmin", "Servicer")
def list_schools(_user_id=None, _role=None):
    limit = query_int(request, "limit", 10, 1, 100)
    offset = query_int(request, "offset", 0, 0)
    records = engine.sort_by_created(db.schools.values())
    page, limit, offset, total = paginate(records, limit, offset)
    return array_body([engine.ser_school(r) for r in page], limit, offset, total)


@bp.route(PREFIX + "/schools/<sid>/certifications", methods=["GET"])
@guard("School", "Servicer", "PlatformAdmin")
def school_certifications(sid, _user_id=None, _role=None):
    engine.get_school(sid)
    records = [c for c in engine.sort_by_created(db.certifications.values())
               if c["school_id"] == sid]
    return array_body([engine.ser_certification(r) for r in records], 10, 0, len(records))


@bp.route(PREFIX + "/schools/<sid>/loan-applications", methods=["GET"])
@guard("School", "Underwriter", "Servicer")
def school_applications(sid, _user_id=None, _role=None):
    engine.get_school(sid)
    records = [a for a in engine.sort_by_created(db.applications.values())
               if a["school_id"] == sid]
    return array_body([engine.ser_application(r) for r in records], 10, 0, len(records))


# ---------------------------------------------------------------------------
# loan policies
# ---------------------------------------------------------------------------
@bp.route(PREFIX + "/loan-policies", methods=["POST"])
@guard("PlatformAdmin")
def create_policy(_user_id=None, _role=None):
    data = body_of(request)
    program_level = required(data, "program_level")
    enum(program_level, engine.PROGRAM_LEVELS)
    record = {
        "product_code": required(data, "product_code"),
        "program_level": program_level,
    }
    for key, default in engine.POLICY_DEFAULTS.items():
        record[key] = data[key] if key in data and data[key] is not None else default
    stamp(record, new=True)
    db.policies[record["id"]] = record
    return object_body(engine.ser_policy(record), 201)


@bp.route(PREFIX + "/loan-policies/<pid>", methods=["GET"])
@guard("PlatformAdmin", "Underwriter", "Servicer", "Borrower")
def read_policy(pid, _user_id=None, _role=None):
    record = engine.get_policy(pid)
    return object_body(engine.ser_policy(record))


@bp.route(PREFIX + "/loan-policies", methods=["GET"])
@guard("PlatformAdmin", "Servicer")
def list_policies(_user_id=None, _role=None):
    limit = query_int(request, "limit", 10, 1, 100)
    offset = query_int(request, "offset", 0, 0)
    records = engine.sort_by_created(db.policies.values())
    page, limit, offset, total = paginate(records, limit, offset)
    return array_body([engine.ser_policy(r) for r in page], limit, offset, total)


@bp.route(PREFIX + "/loan-policies/<pid>/loans", methods=["GET"])
@guard("Servicer", "PlatformAdmin")
def policy_loans(pid, _user_id=None, _role=None):
    engine.get_policy(pid)
    records = [l for l in engine.sort_by_created(db.loans.values())
               if l.get("policy_id") == pid]
    return array_body([engine.ser_loan(r) for r in records], 10, 0, len(records))


@bp.route(PREFIX + "/loan-policies/<pid>/loan-applications", methods=["GET"])
@guard("Underwriter", "Servicer", "PlatformAdmin")
def policy_applications(pid, _user_id=None, _role=None):
    engine.get_policy(pid)
    records = [a for a in engine.sort_by_created(db.applications.values())
               if a.get("policy_id") == pid]
    return array_body([engine.ser_application(r) for r in records], 10, 0, len(records))