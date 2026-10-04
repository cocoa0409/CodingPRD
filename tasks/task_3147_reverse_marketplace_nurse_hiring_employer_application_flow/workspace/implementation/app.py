"""Reverse Nurse Marketplace API — Flask application.

Implements the PRD under /marketplace. In-memory store; logical clock
defaults to 2026-09-01T00:00:00Z and is advanced only via
POST /marketplace/_clock/set_current_utc.
"""

import os
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

import db
import errors
from errors import ApiError
from response import success as ok, error as err_resp
from middleware import get_auth, require_roles
from domain import (
    new_id, iso, now_iso, today, parse_datetime, parse_date, touch, ser,
    NURSE_FIELDS, LV_FIELDS, CERT_FIELDS, EMPLOYER_FIELDS, REQ_FIELDS,
    MATCH_FIELDS, APPLICATION_FIELDS, INTERVIEW_FIELDS, OFFER_FIELDS,
    SCREENING_FIELDS, DOC_FIELDS, PLACEMENT_FIELDS, INVOICE_FIELDS,
)

app = Flask(__name__)

SPECIALTIES = {"ICU", "ER", "MED_SURG", "TELEMETRY", "OR", "PEDIATRICS", "LABOR_DELIVERY", "ONCOLOGY"}
SHIFTS = {"DAY", "NIGHT", "ROTATING"}
CERT_CODES = {"BLS", "ACLS", "PALS", "CCRN", "CEN", "RNC", "ONC"}
FEE_MODELS = {"SUBSCRIPTION", "PER_PLACEMENT"}
SUB_TIERS = {"BASIC", "PRO", "ENTERPRISE"}
DOC_TYPES = {"I9", "W4", "DIRECT_DEPOSIT", "HEALTH_RECORD", "SIGNED_CONTRACT"}

TIER_FEES = {"BASIC": 2500000, "PRO": 2000000, "ENTERPRISE": 1500000}
HOURS_PER_YEAR = 2080
INITIAL_DEADLINE_HOURS = 72
COUNTER_EXTENSION_HOURS = 48
MAX_REVISIONS = 2
OFFER_EXPIRY_HOURS = 48
BUFFER_MINUTES = 30
MIN_DURATION_MINUTES = 30
MAX_DURATION_MINUTES = 240
MAX_UNIT_INTERVIEWS_PER_DAY = 6
RAPID_OFFER_TARGET_HOURS = 120


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def handle_api_error(e):
    return err_resp(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return err_resp(errors.ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return err_resp(errors.ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(Exception)
def handle_exc(e):
    if isinstance(e, ApiError):
        return err_resp(e.error_id, e.message, e.http_status)
    return err_resp(errors.ERR_VALIDATION, f"Unexpected error: {e}", 400)


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.validation("Request body must be a JSON object")
    return data


def req_field(data, name):
    if name not in data or data[name] is None:
        raise errors.validation(f"Missing required field: {name}")
    return data[name]


def req_str(data, name):
    v = req_field(data, name)
    if not isinstance(v, str):
        raise errors.validation(f"Field {name} must be a string")
    return v


def req_int(data, name):
    v = req_field(data, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.validation(f"Field {name} must be an integer")
    return v


def pagination_params():
    try:
        limit = int(request.args.get("limit", "10"))
    except ValueError:
        raise errors.validation("limit must be an integer")
    try:
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        raise errors.validation("offset must be an integer")
    if limit < 1 or limit > 100:
        raise errors.validation("limit must be between 1 and 100")
    if offset < 0:
        raise errors.validation("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_nurse_or_404(nid):
    n = db.nurses.get(nid)
    if n is None:
        raise errors.not_found("Nurse not found")
    return n


def get_employer_or_404(eid):
    e = db.employers.get(eid)
    if e is None:
        raise errors.not_found("Employer not found")
    return e


def get_requisition_or_404(rid):
    r = db.requisitions.get(rid)
    if r is None:
        raise errors.not_found("Requisition not found")
    return r


def get_application_or_404(aid):
    a = db.applications.get(aid)
    if a is None:
        raise errors.not_found("Application not found")
    return a


def get_interview_or_404(iid):
    i = db.interviews.get(iid)
    if i is None:
        raise errors.not_found("Interview not found")
    return i


def get_offer_or_404(oid):
    o = db.offers.get(oid)
    if o is None:
        raise errors.not_found("Offer not found")
    return o


def get_screening_or_404(sid):
    s = db.screenings.get(sid)
    if s is None:
        raise errors.not_found("Screening not found")
    return s


def get_doc_or_404(did):
    d = db.onboarding_documents.get(did)
    if d is None:
        raise errors.not_found("OnboardingDocument not found")
    return d


def get_placement_or_404(pid):
    p = db.placements.get(pid)
    if p is None:
        raise errors.not_found("Placement not found")
    return p


def get_invoice_or_404(iid):
    i = db.invoices.get(iid)
    if i is None:
        raise errors.not_found("Invoice not found")
    return i


def get_lv_or_404(vid):
    v = db.license_verifications.get(vid)
    if v is None:
        raise errors.not_found("LicenseVerification not found")
    return v


def get_cert_or_404(cid):
    c = db.certifications.get(cid)
    if c is None:
        raise errors.not_found("Certification not found")
    return c


# ---------------------------------------------------------------------------
# Computed helpers
# ---------------------------------------------------------------------------

def nurse_license_verified(nurse):
    """license_verified: exactly one VERIFIED LV with state==home_state and
    expiry_date strictly after clock current date."""
    now_d = today()
    candidates = [
        v for v in db.license_verifications.values()
        if v["nurse_id"] == nurse["id"]
        and v["status"] == "VERIFIED"
        and v["license_state"] == nurse["home_state"]
        and parse_date(v["expiry_date"]) is not None
        and parse_date(v["expiry_date"]) > now_d
    ]
    return len(candidates) == 1


def recompute_nurse_license_verified(nurse):
    nurse["license_verified"] = nurse_license_verified(nurse)


def nurse_active_application_count(nurse):
    return sum(
        1 for a in db.applications.values()
        if a["nurse_id"] == nurse["id"] and a["status"] in ("SUBMITTED", "UNDER_REVIEW")
    )


def nurse_has_live_applications(nurse):
    return any(
        a["nurse_id"] == nurse["id"]
        and a["status"] in ("SUBMITTED", "UNDER_REVIEW", "INTERVIEWING", "OFFER_EXTENDED")
        for a in db.applications.values()
    )


def requisition_openings_filled(req):
    return sum(
        1 for p in db.placements.values()
        if p["requisition_id"] == req["id"]
        and p["status"] in ("PENDING_START", "GUARANTEE_ACTIVE", "COMPLETED")
    )


def screening_overall(cred, back):
    if cred in ("FAILED",) or back in ("FLAGGED",):
        return "BLOCKED"
    if cred == "VERIFIED" and back == "CLEARED":
        return "COMPLETE"
    return "IN_PROGRESS"


def nurse_holds_required_certs(nurse, required):
    """True iff the nurse holds each required cert unexpired (expires_on > today)."""
    if not required:
        return True
    now_d = today()
    held = set()
    for c in db.certifications.values():
        if c["nurse_id"] != nurse["id"]:
            continue
        exp = parse_date(c["expires_on"])
        if exp is not None and exp > now_d:
            held.add(c["cert_code"])
    return all(code in held for code in required)


def find_employer_by_legal_name(name):
    for e in db.employers.values():
        if e["legal_name"] == name:
            return e
    return None


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def cascade_nurse_activation(nurse):
    """On PENDING_VERIFICATION -> ACTIVE: auto-add current employer to exclusions."""
    if nurse.get("current_employer_name"):
        emp = find_employer_by_legal_name(nurse["current_employer_name"])
        if emp is not None and emp["id"] not in nurse["confidentiality_exclusions"]:
            nurse["confidentiality_exclusions"].append(emp["id"])


def cascade_withdraw_application(app, actor_system=True):
    """Move an application to WITHDRAWN (system cascade). Cancels SCHEDULED interviews."""
    for iv in db.interviews.values():
        if iv["application_id"] == app["id"] and iv["status"] == "SCHEDULED":
            iv["status"] = "CANCELLED"
            touch(iv)
    app["status"] = "WITHDRAWN"
    touch(app)
    nurse = db.nurses.get(app["nurse_id"])
    if nurse is not None:
        nurse["active_application_count"] = nurse_active_application_count(nurse)


def cascade_expire_application(app):
    for iv in db.interviews.values():
        if iv["application_id"] == app["id"] and iv["status"] == "SCHEDULED":
            iv["status"] = "CANCELLED"
            touch(iv)
    app["status"] = "EXPIRED"
    touch(app)
    nurse = db.nurses.get(app["nurse_id"])
    if nurse is not None:
        nurse["active_application_count"] = nurse_active_application_count(nurse)


def cascade_rescind_offer(offer):
    """Offer -> RESCINDED; application OFFER_EXTENDED -> WITHDRAWN (system cascade)."""
    offer["status"] = "RESCINDED"
    touch(offer)
    app = db.applications.get(offer["application_id"])
    if app is not None and app["status"] == "OFFER_EXTENDED":
        app["status"] = "WITHDRAWN"
        touch(app)
        nurse = db.nurses.get(app["nurse_id"])
        if nurse is not None:
            nurse["active_application_count"] = nurse_active_application_count(nurse)


def requisition_fill_cascade(req):
    """Requisition OPEN -> FILLED: withdraw siblings, rescind sibling offers."""
    req["status"] = "FILLED"
    touch(req)
    for app_row in db.applications.values():
        if app_row["requisition_id"] != req["id"]:
            continue
        if app_row["status"] in ("SUBMITTED", "UNDER_REVIEW", "INTERVIEWING"):
            cascade_withdraw_application(app_row)
        elif app_row["status"] == "OFFER_EXTENDED":
            # cascade the attached offer to RESCINDED (which withdraws the app)
            for o in db.offers.values():
                if o["application_id"] == app_row["id"] and o["status"] == "ISSUED":
                    cascade_rescind_offer(o)


def nurse_hired_cascade(nurse, accepted_app_id):
    """Nurse ACTIVE -> HIRED: withdraw all other live applications."""
    nurse["status"] = "HIRED"
    touch(nurse)
    for app_row in db.applications.values():
        if app_row["nurse_id"] != nurse["id"] or app_row["id"] == accepted_app_id:
            continue
        if app_row["status"] in ("SUBMITTED", "UNDER_REVIEW", "INTERVIEWING"):
            cascade_withdraw_application(app_row)
        elif app_row["status"] == "OFFER_EXTENDED":
            for o in db.offers.values():
                if o["application_id"] == app_row["id"] and o["status"] == "ISSUED":
                    cascade_rescind_offer(o)
    nurse["active_application_count"] = nurse_active_application_count(nurse)


def compute_provisional_fee(employer, annualized_salary_cents):
    if employer["fee_model"] == "PER_PLACEMENT":
        raw = Decimal(annualized_salary_cents) * Decimal(employer["placement_fee_bps"]) / Decimal(10000)
        return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return TIER_FEES[employer["subscription_tier"]]


# ---------------------------------------------------------------------------
# Clock-driven system transitions
# ---------------------------------------------------------------------------

def fire_due_transitions():
    """Fire due system transitions in deterministic order:
    1. license expirations
    2. application deadline expirations
    3. offer expirations
    4. placement start/guarantee transitions
    Returns count fired.
    """
    fired = 0
    now = db.clock_now
    now_d = now.date()

    # 1. License expirations: VERIFIED -> EXPIRED when now >= expiry_date
    for v in sorted(db.license_verifications.values(), key=lambda x: x["created_at"]):
        if v["status"] == "VERIFIED":
            exp = parse_date(v["expiry_date"])
            if exp is not None and now_d >= exp:
                v["status"] = "EXPIRED"
                touch(v)
                fired += 1
                nurse = db.nurses.get(v["nurse_id"])
                if nurse is not None:
                    was = nurse["license_verified"]
                    recompute_nurse_license_verified(nurse)
                    if was and not nurse["license_verified"] and nurse["status"] == "ACTIVE":
                        nurse["status"] = "INACTIVE"
                        touch(nurse)

    # 2. Application deadline expirations
    for a in sorted(db.applications.values(), key=lambda x: x["created_at"]):
        if a["status"] in ("SUBMITTED", "UNDER_REVIEW", "INTERVIEWING"):
            dl = parse_datetime(a["response_deadline_at"])
            if dl is not None and now >= dl:
                cascade_expire_application(a)
                fired += 1

    # 3. Offer expirations
    for o in sorted(db.offers.values(), key=lambda x: x["created_at"]):
        if o["status"] == "ISSUED":
            exp = parse_datetime(o["offer_expires_at"])
            if exp is not None and now >= exp:
                o["status"] = "EXPIRED"
                touch(o)
                fired += 1
                a = db.applications.get(o["application_id"])
                if a is not None and a["status"] == "OFFER_EXTENDED":
                    a["status"] = "EXPIRED"
                    touch(a)
                    nurse = db.nurses.get(a["nurse_id"])
                    if nurse is not None:
                        nurse["active_application_count"] = nurse_active_application_count(nurse)

    # 4. Placement transitions
    for p in sorted(db.placements.values(), key=lambda x: x["created_at"]):
        if p["status"] == "PENDING_START":
            sd = parse_date(p["start_date"])
            if sd is not None and now_d >= sd:
                p["status"] = "GUARANTEE_ACTIVE"
                touch(p)
                fired += 1
        if p["status"] == "GUARANTEE_ACTIVE":
            ge = parse_date(p["guarantee_ends_on"])
            if ge is not None and now_d > ge:
                p["status"] = "COMPLETED"
                touch(p)
                fired += 1
                # settle linked PLACEMENT_FEE invoice
                for inv in db.invoices.values():
                    if inv.get("placement_id") == p["id"] and inv["invoice_kind"] == "PLACEMENT_FEE" \
                            and inv["status"] in ("ISSUED", "PARTIALLY_CREDITED"):
                        inv["status"] = "SETTLED"
                        touch(inv)

    return fired


# ---------------------------------------------------------------------------
# Clock endpoint
# ---------------------------------------------------------------------------

@app.route("/marketplace/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("PlatformAdmin")
    data = body()
    raw = req_str(data, "current_utc")
    dt = parse_datetime(raw)
    if dt is None:
        raise errors.validation("current_utc must be an ISO 8601 UTC datetime")
    db.clock_now = dt
    fired = fire_due_transitions()
    # Echo the supplied instant exactly as provided ("the response echoes
    # `current_utc`"); internal fields keep the canonical millisecond format.
    return ok({"current_utc": raw, "fired_transitions": fired}, "object", 200)


# ---------------------------------------------------------------------------
# Nurses
# ---------------------------------------------------------------------------

@app.route("/marketplace/nurses", methods=["POST"])
def create_nurse():
    role, uid = require_roles("Candidate")
    data = body()
    full_name = req_str(data, "full_name")
    email = req_str(data, "email")
    home_state = req_str(data, "home_state")
    primary_specialty = req_str(data, "primary_specialty")
    years_experience = req_int(data, "years_experience")
    desired_shift = req_str(data, "desired_shift")
    desired_rate = req_int(data, "desired_hourly_rate_cents")
    max_commute = req_int(data, "max_commute_miles")
    current_employer_name = req_str(data, "current_employer_name")
    exclusions = data.get("confidentiality_exclusions", [])
    if not isinstance(exclusions, list):
        raise errors.validation("confidentiality_exclusions must be an array")

    if primary_specialty not in SPECIALTIES:
        raise errors.validation("primary_specialty out of range")
    if desired_shift not in SHIFTS:
        raise errors.validation("desired_shift out of range")
    if not (0 <= years_experience <= 60):
        raise errors.validation("years_experience out of range")
    if desired_rate < 2000:
        raise errors.validation("desired_hourly_rate_cents must be >= 2000")
    if not (1 <= max_commute <= 500):
        raise errors.validation("max_commute_miles out of range")

    for n in db.nurses.values():
        if n["email"] == email:
            raise errors.duplicate_resource("Nurse email already exists")

    nid = new_id()
    ts = now_iso()
    nurse = {
        "id": nid,
        "full_name": full_name,
        "email": email,
        "home_state": home_state,
        "primary_specialty": primary_specialty,
        "years_experience": years_experience,
        "desired_shift": desired_shift,
        "desired_hourly_rate_cents": desired_rate,
        "max_commute_miles": max_commute,
        "current_employer_name": current_employer_name,
        "confidentiality_exclusions": list(exclusions),
        "status": "DRAFT",
        "license_verified": False,
        "active_application_count": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.nurses[nid] = nurse
    return ok(ser(nurse, NURSE_FIELDS), "object", 201)


def _check_nurse_read(role, uid, nurse):
    """Employer reading a nurse who excludes them or is DRAFT/WITHDRAWN -> 404."""
    if role == "Employer":
        if nurse["status"] in ("DRAFT", "WITHDRAWN"):
            raise errors.not_found("Nurse not found")
        if uid in nurse["confidentiality_exclusions"]:
            raise errors.not_found("Nurse not found")


@app.route("/marketplace/nurses/<nid>", methods=["GET"])
def get_nurse(nid):
    role, uid = require_roles("Candidate", "Employer", "PlatformAdmin")
    nurse = db.nurses.get(nid)
    if nurse is None:
        raise errors.not_found("Nurse not found")
    _check_nurse_read(role, uid, nurse)
    return ok(ser(nurse, NURSE_FIELDS), "object", 200)


@app.route("/marketplace/nurses", methods=["GET"])
def list_nurses():
    role, uid = require_roles("Employer", "PlatformAdmin")
    limit, offset = pagination_params()
    items = list(db.nurses.values())
    if role == "Employer":
        items = [
            n for n in items
            if n["status"] == "ACTIVE" and uid not in n["confidentiality_exclusions"]
        ]
    status_f = request.args.get("status")
    if status_f:
        items = [n for n in items if n["status"] == status_f]
    spec_f = request.args.get("primary_specialty")
    if spec_f:
        items = [n for n in items if n["primary_specialty"] == spec_f]
    items.sort(key=lambda n: n["created_at"])
    page, meta = paginate([ser(n, NURSE_FIELDS) for n in items], limit, offset)
    return ok(page, "array", 200, pagination=meta)


def _candidate_owns_nurse(uid, nurse):
    if uid != nurse["id"]:
        raise errors.forbidden("Candidate may only act on their own profile")


@app.route("/marketplace/nurses/<nid>/submit", methods=["POST"])
def submit_nurse(nid):
    role, uid = require_roles("Candidate")
    nurse = get_nurse_or_404(nid)
    _candidate_owns_nurse(uid, nurse)
    if nurse["status"] != "DRAFT":
        raise errors.invalid_state("Nurse is not DRAFT")
    has_pending_or_verified = any(
        v["nurse_id"] == nid and v["status"] in ("PENDING", "VERIFIED")
        for v in db.license_verifications.values()
    )
    if not has_pending_or_verified:
        raise errors.invalid_state("No LicenseVerification in PENDING or VERIFIED")
    nurse["status"] = "PENDING_VERIFICATION"
    touch(nurse)
    return ok(ser(nurse, NURSE_FIELDS), "object", 200)


@app.route("/marketplace/nurses/<nid>/deactivate", methods=["POST"])
def deactivate_nurse(nid):
    role, uid = require_roles("Candidate")
    nurse = get_nurse_or_404(nid)
    _candidate_owns_nurse(uid, nurse)
    if nurse["status"] != "ACTIVE":
        raise errors.invalid_state("Nurse is not ACTIVE")
    if nurse_has_live_applications(nurse):
        raise errors.nurse_has_live_applications("Nurse has live applications")
    nurse["status"] = "INACTIVE"
    touch(nurse)
    return ok(ser(nurse, NURSE_FIELDS), "object", 200)


@app.route("/marketplace/nurses/<nid>/reactivate", methods=["POST"])
def reactivate_nurse(nid):
    role, uid = require_roles("Candidate")
    nurse = get_nurse_or_404(nid)
    _candidate_owns_nurse(uid, nurse)
    if nurse["status"] != "INACTIVE":
        raise errors.invalid_state("Nurse is not INACTIVE")
    recompute_nurse_license_verified(nurse)
    if not nurse["license_verified"]:
        raise errors.credentials_incomplete("License is not verified")
    nurse["status"] = "ACTIVE"
    touch(nurse)
    return ok(ser(nurse, NURSE_FIELDS), "object", 200)


@app.route("/marketplace/nurses/<nid>/withdraw", methods=["POST"])
def withdraw_nurse(nid):
    role, uid = require_roles("Candidate")
    nurse = get_nurse_or_404(nid)
    _candidate_owns_nurse(uid, nurse)
    if nurse["status"] not in ("ACTIVE", "INACTIVE"):
        raise errors.invalid_state("Nurse cannot withdraw from this state")
    blocking = any(
        p["nurse_id"] == nid and p["status"] in ("PENDING_START", "GUARANTEE_ACTIVE")
        for p in db.placements.values()
    )
    if blocking:
        raise errors.invalid_state("Nurse has a live placement")
    # cascade applications
    for a in list(db.applications.values()):
        if a["nurse_id"] != nid:
            continue
        if a["status"] in ("SUBMITTED", "UNDER_REVIEW", "INTERVIEWING"):
            cascade_withdraw_application(a)
        elif a["status"] == "OFFER_EXTENDED":
            for o in list(db.offers.values()):
                if o["application_id"] == a["id"] and o["status"] == "ISSUED":
                    cascade_rescind_offer(o)
    nurse["status"] = "WITHDRAWN"
    touch(nurse)
    nurse["active_application_count"] = nurse_active_application_count(nurse)
    return ok(ser(nurse, NURSE_FIELDS), "object", 200)


@app.route("/marketplace/nurses/<nid>/license-verifications", methods=["GET"])
def list_nurse_lvs(nid):
    role, uid = require_roles("Candidate", "PlatformAdmin")
    nurse = get_nurse_or_404(nid)
    if role == "Candidate" and uid != nurse["id"]:
        raise errors.forbidden("Candidate may only read their own verifications")
    limit, offset = pagination_params()
    items = [v for v in db.license_verifications.values() if v["nurse_id"] == nid]
    items.sort(key=lambda v: v["created_at"])
    page, meta = paginate([ser(v, LV_FIELDS) for v in items], limit, offset)
    return ok(page, "array", 200, pagination=meta)


@app.route("/marketplace/nurses/<nid>/certifications", methods=["GET"])
def list_nurse_certs(nid):
    role, uid = require_roles("Candidate", "Employer", "PlatformAdmin")
    nurse = get_nurse_or_404(nid)
    if role == "Candidate" and uid != nurse["id"]:
        raise errors.forbidden("Candidate may only read their own certifications")
    if role == "Employer" and uid in nurse["confidentiality_exclusions"]:
        raise errors.not_found("Nurse not found")
    limit, offset = pagination_params()
    items = [c for c in db.certifications.values() if c["nurse_id"] == nid]
    items.sort(key=lambda c: c["created_at"])
    page, meta = paginate([ser(c, CERT_FIELDS) for c in items], limit, offset)
    return ok(page, "array", 200, pagination=meta)


@app.route("/marketplace/nurses/<nid>/applications", methods=["GET"])
def list_nurse_applications(nid):
    role, uid = require_roles("Candidate", "PlatformAdmin")
    nurse = get_nurse_or_404(nid)
    if role == "Candidate" and uid != nurse["id"]:
        raise errors.forbidden("Candidate may only read their own applications")
    limit, offset = pagination_params()
    items = [a for a in db.applications.values() if a["nurse_id"] == nid]
    status_f = request.args.get("status")
    if status_f:
        items = [a for a in items if a["status"] == status_f]
    items.sort(key=lambda a: a["created_at"])
    page, meta = paginate([ser(a, APPLICATION_FIELDS) for a in items], limit, offset)
    return ok(page, "array", 200, pagination=meta)


@app.route("/marketplace/nurses/<nid>/matches", methods=["GET"])
def list_nurse_matches(nid):
    role, uid = require_roles("Candidate", "PlatformAdmin")
    nurse = get_nurse_or_404(nid)
    if role == "Candidate" and uid != nurse["id"]:
        raise errors.forbidden("Candidate may only read their own matches")
    limit, offset = pagination_params()
    items = [m for m in db.matches.values() if m["nurse_id"] == nid]
    items.sort(key=lambda m: m["created_at"])
    page, meta = paginate([ser(m, MATCH_FIELDS) for m in items], limit, offset)
    return ok(page, "array", 200, pagination=meta)


# ---------------------------------------------------------------------------
# License verifications
# ---------------------------------------------------------------------------

@app.route("/marketplace/license-verifications", methods=["POST"])
def create_lv():
    role, uid = require_roles("Candidate")
    data = body()
    nurse_id = req_str(data, "nurse_id")
    license_number = req_str(data, "license_number")
    license_state = req_str(data, "license_state")
    expiry_date = req_str(data, "expiry_date")
    nurse = get_nurse_or_404(nurse_id)
    if uid != nurse["id"]:
        raise errors.forbidden("Candidate may only submit verifications for themselves")
    if parse_date(expiry_date) is None:
        raise errors.validation("expiry_date must be an ISO date")
    for v in db.license_verifications.values():
        if v["license_state"] == license_state and v["license_number"] == license_number:
            raise errors.duplicate_resource("license_number already exists in this license_state")
    vid = new_id()
    ts = now_iso()
    lv = {
        "id": vid,
        "nurse_id": nurse_id,
        "license_number": license_number,
        "license_state": license_state,
        "expiry_date": expiry_date,
        "status": "PENDING",
        "rejection_reason": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.license_verifications[vid] = lv
    return ok(ser(lv, LV_FIELDS), "object", 201)


@app.route("/marketplace/license-verifications/<vid>", methods=["GET"])
def get_lv(vid):
    role, uid = require_roles("Candidate", "PlatformAdmin")
    lv = get_lv_or_404(vid)
    if role == "Candidate" and uid != lv["nurse_id"]:
        raise errors.forbidden("Candidate may only read their own verifications")
    return ok(ser(lv, LV_FIELDS), "object", 200)


@app.route("/marketplace/license-verifications/<vid>/verify", methods=["POST"])
def verify_lv(vid):
    require_roles("PlatformAdmin")
    lv = get_lv_or_404(vid)
    if lv["status"] != "PENDING":
        raise errors.invalid_state("Verification is not PENDING")
    exp = parse_date(lv["expiry_date"])
    if exp is None or exp <= today():
        raise errors.license_expired("License expiry is not strictly after current date")
    lv["status"] = "VERIFIED"
    touch(lv)
    nurse = db.nurses.get(lv["nurse_id"])
    if nurse is not None:
        was = nurse["license_verified"]
        recompute_nurse_license_verified(nurse)
        if nurse["license_verified"] and not was and nurse["status"] == "PENDING_VERIFICATION":
            nurse["status"] = "ACTIVE"
            cascade_nurse_activation(nurse)
            touch(nurse)
    return ok(ser(lv, LV_FIELDS), "object", 200)


@app.route("/marketplace/license-verifications/<vid>/reject", methods=["POST"])
def reject_lv(vid):
    require_roles("PlatformAdmin")
    lv = get_lv_or_404(vid)
    if lv["status"] != "PENDING":
        raise errors.invalid_state("Verification is not PENDING")
    data = body()
    reason = data.get("rejection_reason")
    if not reason:
        raise errors.review_note_required("rejection_reason is required")
    lv["status"] = "REJECTED"
    lv["rejection_reason"] = reason
    touch(lv)
    nurse = db.nurses.get(lv["nurse_id"])
    if nurse is not None and nurse["status"] == "PENDING_VERIFICATION":
        still_open = any(
            v["nurse_id"] == nurse["id"] and v["status"] in ("PENDING", "VERIFIED")
            for v in db.license_verifications.values()
        )
        if not still_open:
            nurse["status"] = "DRAFT"
            touch(nurse)
    return ok(ser(lv, LV_FIELDS), "object", 200)


# ---------------------------------------------------------------------------
# Certifications
# ---------------------------------------------------------------------------

@app.route("/marketplace/certifications", methods=["POST"])
def create_cert():
    role, uid = require_roles("Candidate")
    data = body()
    nurse_id = req_str(data, "nurse_id")
    cert_code = req_str(data, "cert_code")
    expires_on = req_str(data, "expires_on")
    nurse = get_nurse_or_404(nurse_id)
    if uid != nurse["id"]:
        raise errors.forbidden("Candidate may only certify themselves")
    if cert_code not in CERT_CODES:
        raise errors.validation("cert_code out of range")
    exp = parse_date(expires_on)
    if exp is None:
        raise errors.validation("expires_on must be an ISO date")
    if exp <= today():
        raise errors.license_expired("expires_on must be strictly after current date")
    cid = new_id()
    cert = {
        "id": cid,
        "nurse_id": nurse_id,
        "cert_code": cert_code,
        "expires_on": expires_on,
        "created_at": now_iso(),
    }
    db.certifications[cid] = cert
    return ok(ser(cert, CERT_FIELDS), "object", 201)


@app.route("/marketplace/certifications/<cid>", methods=["GET"])
def get_cert(cid):
    role, uid = require_roles("Candidate", "Employer", "PlatformAdmin")
    cert = get_cert_or_404(cid)
    if role == "Candidate" and uid != cert["nurse_id"]:
        raise errors.forbidden("Candidate may only read their own certifications")
    if role == "Employer":
        nurse = db.nurses.get(cert["nurse_id"])
        if nurse is not None and uid in nurse["confidentiality_exclusions"]:
            raise errors.not_found("Certification not found")
    return ok(ser(cert, CERT_FIELDS), "object", 200)


# ---------------------------------------------------------------------------
# Employers
# ---------------------------------------------------------------------------

@app.route("/marketplace/employers", methods=["POST"])
def create_employer():
    require_roles("PlatformAdmin")
    data = body()
    legal_name = req_str(data, "legal_name")
    facility_state = req_str(data, "facility_state")
    fee_model = req_str(data, "fee_model")
    subscription_tier = data.get("subscription_tier")
    sla_response_hours = req_int(data, "sla_response_hours")
    guarantee_days = req_int(data, "guarantee_days")
    placement_fee_bps = req_int(data, "placement_fee_bps")
    if fee_model not in FEE_MODELS:
        raise errors.validation("fee_model out of range")
    if subscription_tier is not None and subscription_tier not in SUB_TIERS:
        raise errors.validation("subscription_tier out of range")
    if fee_model == "SUBSCRIPTION" and subscription_tier is None:
        raise errors.validation("subscription_tier required for SUBSCRIPTION fee_model")
    if not (24 <= sla_response_hours <= 168):
        raise errors.validation("sla_response_hours out of range")
    if not (30 <= guarantee_days <= 120):
        raise errors.validation("guarantee_days out of range")
    if not (500 <= placement_fee_bps <= 3000):
        raise errors.validation("placement_fee_bps out of range")
    eid = new_id()
    ts = now_iso()
    emp = {
        "id": eid,
        "legal_name": legal_name,
        "facility_state": facility_state,
        "fee_model": fee_model,
        "subscription_tier": subscription_tier,
        "sla_response_hours": sla_response_hours,
        "guarantee_days": guarantee_days,
        "placement_fee_bps": placement_fee_bps,
        "credit_balance_cents": 0,
        "status": "ACTIVE",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.employers[eid] = emp
    return ok(ser(emp, EMPLOYER_FIELDS), "object", 201)


@app.route("/marketplace/employers/<eid>", methods=["GET"])
def get_employer(eid):
    role, uid = require_roles("Employer", "PlatformAdmin")
    emp = get_employer_or_404(eid)
    if role == "Employer" and uid != emp["id"]:
        raise errors.forbidden("Employer may only read itself")
    return ok(ser(emp, EMPLOYER_FIELDS), "object", 200)


@app.route("/marketplace/employers/<eid>/requisitions", methods=["GET"])
def list_employer_requisitions(eid):
    role, uid = require_roles("Employer", "PlatformAdmin")
    emp = get_employer_or_404(eid)
    if role == "Employer" and uid != emp["id"]:
        raise errors.forbidden("Employer may only read its own requisitions")
    limit, offset = pagination_params()
    items = [r for r in db.requisitions.values() if r["employer_id"] == eid]
    status_f = request.args.get("status")
    if status_f:
        items = [r for r in items if r["status"] == status_f]
    items.sort(key=lambda r: r["created_at"])
    page, meta = paginate([ser(r, REQ_FIELDS) for r in items], limit, offset)
    return ok(page, "array", 200, pagination=meta)


@app.route("/marketplace/employers/<eid>/invoices", methods=["GET"])
def list_employer_invoices(eid):
    role, uid = require_roles("Employer", "PlatformAdmin")
    emp = get_employer_or_404(eid)
    if role == "Employer" and uid != emp["id"]:
        raise errors.forbidden("Employer may only read its own invoices")
    limit, offset = pagination_params()
    items = [i for i in db.invoices.values() if i["employer_id"] == eid]
    status_f = request.args.get("status")
    if status_f:
        items = [i for i in items if i["status"] == status_f]
    items.sort(key=lambda i: i["created_at"])
    page, meta = paginate([ser(i, INVOICE_FIELDS) for i in items], limit, offset)
    return ok(page, "array", 200, pagination=meta)


@app.route("/marketplace/employers/<eid>/suspend", methods=["POST"])
def suspend_employer(eid):
    require_roles("PlatformAdmin")
    emp = get_employer_or_404(eid)
    if emp["status"] != "ACTIVE":
        raise errors.invalid_state("Employer is not ACTIVE")
    emp["status"] = "SUSPENDED"
    touch(emp)
    return ok(ser(emp, EMPLOYER_FIELDS), "object", 200)


@app.route("/marketplace/employers/<eid>/reinstate", methods=["POST"])
def reinstate_employer(eid):
    require_roles("PlatformAdmin")
    emp = get_employer_or_404(eid)
    if emp["status"] != "SUSPENDED":
        raise errors.invalid_state("Employer is not SUSPENDED")
    emp["status"] = "ACTIVE"
    touch(emp)
    return ok(ser(emp, EMPLOYER_FIELDS), "object", 200)


# ---------------------------------------------------------------------------
# Requisitions
# ---------------------------------------------------------------------------

@app.route("/marketplace/requisitions", methods=["POST"])
def create_requisition():
    role, uid = require_roles("Employer")
    data = body()
    employer_id = req_str(data, "employer_id")
    employer = get_employer_or_404(employer_id)
    if uid != employer["id"]:
        raise errors.forbidden("Employer may only create requisitions for itself")
    specialty = req_str(data, "specialty")
    unit_name = req_str(data, "unit_name")
    required_certs = data.get("required_certs", [])
    if not isinstance(required_certs, list):
        raise errors.validation("required_certs must be an array")
    for c in required_certs:
        if c not in CERT_CODES:
            raise errors.validation("required_certs contains unknown cert code")
    facility_state = req_str(data, "facility_state")
    distance = req_int(data, "distance_from_facility_miles")
    shift = req_str(data, "shift")
    offered_rate = req_int(data, "offered_hourly_rate_cents")
    openings_total = req_int(data, "openings_total")
    if specialty not in SPECIALTIES:
        raise errors.validation("specialty out of range")
    if shift not in SHIFTS:
        raise errors.validation("shift out of range")
    if not (0 <= distance <= 500):
        raise errors.validation("distance_from_facility_miles out of range")
    if offered_rate < 2000:
        raise errors.validation("offered_hourly_rate_cents must be >= 2000")
    if not (1 <= openings_total <= 20):
        raise errors.validation("openings_total out of range")
    rid = new_id()
    ts = now_iso()
    req = {
        "id": rid,
        "employer_id": employer_id,
        "specialty": specialty,
        "unit_name": unit_name,
        "required_certs": list(required_certs),
        "facility_state": facility_state,
        "distance_from_facility_miles": distance,
        "shift": shift,
        "offered_hourly_rate_cents": offered_rate,
        "openings_total": openings_total,
        "openings_filled": 0,
        "status": "OPEN",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.requisitions[rid] = req
    return ok(ser(req, REQ_FIELDS), "object", 201)


@app.route("/marketplace/requisitions/<rid>", methods=["GET"])
def get_requisition(rid):
    require_roles("Candidate", "Employer", "PlatformAdmin")
    req = get_requisition_or_404(rid)
    return ok(ser(req, REQ_FIELDS), "object", 200)


def _employer_owns_req(uid, req):
    if uid != req["employer_id"]:
        raise errors.forbidden("Employer does not own this requisition")


@app.route("/marketplace/requisitions/<rid>/pause", methods=["POST"])
def pause_requisition(rid):
    role, uid = require_roles("Employer")
    req = get_requisition_or_404(rid)
    _employer_owns_req(uid, req)
    if req["status"] != "OPEN":
        raise errors.invalid_state("Requisition is not OPEN")
    req["status"] = "PAUSED"
    touch(req)
    return ok(ser(req, REQ_FIELDS), "object", 200)


@app.route("/marketplace/requisitions/<rid>/resume", methods=["POST"])
def resume_requisition(rid):
    role, uid = require_roles("Employer")
    req = get_requisition_or_404(rid)
    _employer_owns_req(uid, req)
    if req["status"] != "PAUSED":
        raise errors.invalid_state("Requisition is not PAUSED")
    if req["openings_filled"] >= req["openings_total"]:
        raise errors.invalid_state("Requisition is already filled")
    req["status"] = "OPEN"
    touch(req)
    return ok(ser(req, REQ_FIELDS), "object", 200)


@app.route("/marketplace/requisitions/<rid>/close", methods=["POST"])
def close_requisition(rid):
    role, uid = require_roles("Employer")
    req = get_requisition_or_404(rid)
    _employer_owns_req(uid, req)
    if req["status"] not in ("OPEN", "PAUSED", "FILLED"):
        raise errors.invalid_state("Requisition cannot be closed from this state")
    any_offer_extended = any(
        a["requisition_id"] == rid and a["status"] == "OFFER_EXTENDED"
        for a in db.applications.values()
    )
    if any_offer_extended:
        raise errors.invalid_state("An application is OFFER_EXTENDED")
    for a in list(db.applications.values()):
        if a["requisition_id"] == rid and a["status"] in ("SUBMITTED", "UNDER_REVIEW", "INTERVIEWING"):
            cascade_withdraw_application(a)
    req["status"] = "CLOSED"
    touch(req)
    return ok(ser(req, REQ_FIELDS), "object", 200)


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def compute_match_score(nurse, req):
    score = Decimal(0)
    if nurse["home_state"] == req["facility_state"]:
        score += 40
    score += Decimal(25) * Decimal(min(nurse["years_experience"], 10)) / Decimal(10)
    if nurse["desired_shift"] == req["shift"]:
        score += 20
    elif nurse["desired_shift"] == "ROTATING" or req["shift"] == "ROTATING":
        score += 10
    if nurse["max_commute_miles"] >= req["distance_from_facility_miles"]:
        score += 15
    if req["required_certs"] and not nurse_holds_required_certs(nurse, req["required_certs"]):
        score -= 20
    if score < 0:
        score = Decimal(0)
    if score > 100:
        score = Decimal(100)
    return int(score.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@app.route("/marketplace/requisitions/<rid>/generate-matches", methods=["POST"])
def generate_matches(rid):
    role, uid = require_roles("Employer", "PlatformAdmin")
    req = get_requisition_or_404(rid)
    if role == "Employer":
        _employer_owns_req(uid, req)
    # idempotent per requisition: replace prior non-suppressed Match rows
    for mid in [m["id"] for m in db.matches.values()
                if m["requisition_id"] == rid and not m["suppressed"]]:
        del db.matches[mid]
    pool = []
    for n in db.nurses.values():
        if n["status"] != "ACTIVE":
            continue
        recompute_nurse_license_verified(n)
        if not n["license_verified"]:
            continue
        if n["primary_specialty"] != req["specialty"]:
            continue
        pool.append(n)
    new_matches = []
    for n in pool:
        suppressed = req["employer_id"] in n["confidentiality_exclusions"]
        mid = new_id()
        score = compute_match_score(n, req)
        ts = now_iso()
        m = {
            "id": mid,
            "nurse_id": n["id"],
            "requisition_id": rid,
            "match_score": score,
            "suppressed": suppressed,
            "generated_at": ts,
            "created_at": ts,
            "_nurse_created_at": n["created_at"],
        }
        db.matches[mid] = m
        new_matches.append(m)
    new_matches.sort(key=lambda m: (-m["match_score"], m["_nurse_created_at"]))
    return ok([ser(m, MATCH_FIELDS) for m in new_matches], "array", 200)


@app.route("/marketplace/requisitions/<rid>/matches", methods=["GET"])
def list_req_matches(rid):
    role, uid = require_roles("Employer", "PlatformAdmin")
    req = get_requisition_or_404(rid)
    if role == "Employer":
        _employer_owns_req(uid, req)
    limit, offset = pagination_params()
    include_suppressed = request.args.get("include_suppressed", "false").lower() == "true"
    items = []
    for m in db.matches.values():
        if m["requisition_id"] != rid:
            continue
        if m["suppressed"]:
            if role == "Employer":
                continue
            if not include_suppressed:
                continue
        nurse = db.nurses.get(m["nurse_id"])
        m["_nurse_created_at"] = nurse["created_at"] if nurse else ""
        items.append(m)
    items.sort(key=lambda m: (-m["match_score"], m["_nurse_created_at"]))
    page, meta = paginate([ser(m, MATCH_FIELDS) for m in items], limit, offset)
    return ok(page, "array", 200, pagination=meta)


@app.route("/marketplace/requisitions/<rid>/sla-report", methods=["GET"])
def sla_report(rid):
    role, uid = require_roles("Employer", "PlatformAdmin")
    req = get_requisition_or_404(rid)
    if role == "Employer":
        _employer_owns_req(uid, req)
    employer = db.employers.get(req["employer_id"])
    sla_hours = employer["sla_response_hours"] if employer else 0

    breach_count = 0
    evaluated_count = 0
    rapid_offer_target_met = False

    for a in db.applications.values():
        if a["requisition_id"] != rid:
            continue
        if a["status"] == "SUBMITTED":
            continue
        evaluated_count += 1
        created = parse_datetime(a["created_at"])
        events = []
        # first interview scheduled
        ivs = [i for i in db.interviews.values() if i["application_id"] == a["id"]]
        if ivs:
            first_iv = min(ivs, key=lambda i: parse_datetime(i["scheduled_by_employer_at"]))
            events.append(parse_datetime(first_iv["scheduled_by_employer_at"]))
        # first counter (we track counter times)
        for t in a.get("_counter_times", []):
            events.append(parse_datetime(t))
        # offer issued_at
        ofs = [o for o in db.offers.values() if o["application_id"] == a["id"]]
        if ofs:
            first_of = min(ofs, key=lambda o: parse_datetime(o["issued_at"]))
            events.append(parse_datetime(first_of["issued_at"]))
        # employer withdraw time
        if a.get("_employer_withdrawn_at"):
            events.append(parse_datetime(a["_employer_withdrawn_at"]))
        if events:
            first_action = min(events)
            delta_h = (first_action - created).total_seconds() / 3600.0
            whole_hours = int(delta_h)  # truncate toward zero (floor for positive)
            if delta_h < 0:
                whole_hours = 0
            if whole_hours > sla_hours:
                breach_count += 1

    # rapid offer target: accepted application's time-to-offer <= 120h
    for a in db.applications.values():
        if a["requisition_id"] != rid or a["status"] != "ACCEPTED":
            continue
        ofs = [o for o in db.offers.values() if o["application_id"] == a["id"]]
        if ofs:
            first_of = min(ofs, key=lambda o: parse_datetime(o["issued_at"]))
            created = parse_datetime(a["created_at"])
            delta_h = (parse_datetime(first_of["issued_at"]) - created).total_seconds() / 3600.0
            whole = int(delta_h)
            if delta_h < 0:
                whole = 0
            if whole <= RAPID_OFFER_TARGET_HOURS:
                rapid_offer_target_met = True

    return ok({
        "breach_count": breach_count,
        "evaluated_count": evaluated_count,
        "rapid_offer_target_met": rapid_offer_target_met,
    }, "object", 200)


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

@app.route("/marketplace/applications", methods=["POST"])
def create_application():
    role, uid = require_roles("Employer")
    data = body()
    requisition_id = req_str(data, "requisition_id")
    nurse_id = req_str(data, "nurse_id")
    proposed_rate = req_int(data, "proposed_hourly_rate_cents")
    proposed_shift = req_str(data, "proposed_shift")
    if "expected_nurse_version" not in data or data["expected_nurse_version"] is None:
        raise errors.validation("expected_nurse_version is required")
    expected_nv = data["expected_nurse_version"]
    if isinstance(expected_nv, bool) or not isinstance(expected_nv, int):
        raise errors.validation("expected_nurse_version must be an integer")

    # existence left-to-right: requisition then nurse
    req = get_requisition_or_404(requisition_id)
    nurse = get_nurse_or_404(nurse_id)

    # OCC check on nurse version
    if nurse["version"] != expected_nv:
        raise errors.stale_nurse_version("Nurse version mismatch")

    # employer identity = requisition.employer_id; acting employer must own req
    employer = db.employers.get(req["employer_id"])
    if uid != req["employer_id"]:
        raise errors.forbidden("Employer does not own this requisition")

    # confidentiality
    if req["employer_id"] in nurse["confidentiality_exclusions"]:
        raise errors.candidate_confidential()

    # credential gates: nurse ACTIVE + license_verified
    recompute_nurse_license_verified(nurse)
    if nurse["status"] != "ACTIVE" or not nurse["license_verified"]:
        raise errors.credentials_incomplete("Nurse is not ACTIVE and license-verified")

    # terms
    if proposed_shift not in SHIFTS:
        raise errors.validation("proposed_shift out of range")
    if proposed_shift != req["shift"]:
        raise errors.terms_mismatch("proposed_shift must equal requisition shift")
    if proposed_rate < 2000:
        raise errors.validation("proposed_hourly_rate_cents must be >= 2000")
    if proposed_rate < req["offered_hourly_rate_cents"]:
        raise errors.terms_mismatch("proposed rate below requisition floor")

    # employer suspension -> ERR_NO_OPENINGS
    if employer is not None and employer["status"] != "ACTIVE":
        raise errors.no_openings("Employer is suspended")

    aid = new_id()
    ts = now_iso()
    deadline = db.clock_now + timedelta(hours=INITIAL_DEADLINE_HOURS)
    app_row = {
        "id": aid,
        "requisition_id": requisition_id,
        "nurse_id": nurse_id,
        "employer_id": req["employer_id"],
        "proposed_hourly_rate_cents": proposed_rate,
        "proposed_shift": proposed_shift,
        "status": "SUBMITTED",
        "response_deadline_at": iso(deadline),
        "revision_count": 0,
        "deadline_extended": False,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_counter_times": [],
        "_employer_withdrawn_at": None,
    }
    db.applications[aid] = app_row
    touch(nurse)
    nurse["active_application_count"] = nurse_active_application_count(nurse)
    return ok(ser(app_row, APPLICATION_FIELDS), "object", 201)


@app.route("/marketplace/applications/<aid>", methods=["GET"])
def get_application(aid):
    role, uid = require_roles("Candidate", "Employer", "PlatformAdmin")
    a = get_application_or_404(aid)
    if role == "Candidate" and uid != a["nurse_id"]:
        raise errors.forbidden("Candidate may only read their own applications")
    if role == "Employer" and uid != a["employer_id"]:
        raise errors.forbidden("Employer may only read its own applications")
    return ok(ser(a, APPLICATION_FIELDS), "object", 200)


@app.route("/marketplace/applications", methods=["GET"])
def list_applications():
    role, uid = require_roles("Candidate", "Employer", "PlatformAdmin")
    limit, offset = pagination_params()
    items = list(db.applications.values())
    if role == "Candidate":
        items = [a for a in items if a["nurse_id"] == uid]
    elif role == "Employer":
        items = [a for a in items if a["employer_id"] == uid]
    for key in ("nurse_id", "employer_id", "requisition_id", "status"):
        v = request.args.get(key)
        if v:
            items = [a for a in items if a.get(key) == v]
    items.sort(key=lambda a: a["created_at"])
    page, meta = paginate([ser(a, APPLICATION_FIELDS) for a in items], limit, offset)
    return ok(page, "array", 200, pagination=meta)


@app.route("/marketplace/applications/<aid>/review", methods=["POST"])
def review_application(aid):
    role, uid = require_roles("Candidate")
    a = get_application_or_404(aid)
    if uid != a["nurse_id"]:
        raise errors.forbidden("Candidate may only review their own applications")
    if a["status"] != "SUBMITTED":
        raise errors.invalid_state("Application is not SUBMITTED")
    dl = parse_datetime(a["response_deadline_at"])
    if db.clock_now >= dl:
        raise errors.deadline_passed("Response deadline has passed")
    a["status"] = "UNDER_REVIEW"
    touch(a)
    nurse = db.nurses.get(a["nurse_id"])
    if nurse is not None:
        nurse["active_application_count"] = nurse_active_application_count(nurse)
    return ok(ser(a, APPLICATION_FIELDS), "object", 200)


@app.route("/marketplace/applications/<aid>/counter", methods=["POST"])
def counter_application(aid):
    role, uid = require_roles("Employer")
    a = get_application_or_404(aid)
    if uid != a["employer_id"]:
        raise errors.forbidden("Employer does not own this application")
    if a["status"] != "UNDER_REVIEW":
        raise errors.invalid_state("Application is not UNDER_REVIEW")
    dl = parse_datetime(a["response_deadline_at"])
    if db.clock_now >= dl:
        raise errors.deadline_passed("Response deadline has passed")
    data = body()
    new_rate = req_int(data, "proposed_hourly_rate_cents")
    new_shift = data.get("proposed_shift", a["proposed_shift"])
    req = db.requisitions.get(a["requisition_id"])
    if a["revision_count"] >= MAX_REVISIONS:
        raise errors.terms_mismatch("Revision cap exceeded")
    if new_shift not in SHIFTS:
        raise errors.validation("proposed_shift out of range")
    if req is not None:
        if new_shift != req["shift"]:
            raise errors.terms_mismatch("proposed_shift must equal requisition shift")
        if new_rate < req["offered_hourly_rate_cents"]:
            raise errors.terms_mismatch("proposed rate below requisition floor")
    if new_rate < 2000:
        raise errors.validation("proposed_hourly_rate_cents must be >= 2000")

    a["proposed_hourly_rate_cents"] = new_rate
    a["proposed_shift"] = new_shift
    a["revision_count"] += 1
    a.setdefault("_counter_times", []).append(now_iso())
    if not a["deadline_extended"]:
        dl2 = parse_datetime(a["response_deadline_at"]) + timedelta(hours=COUNTER_EXTENSION_HOURS)
        a["response_deadline_at"] = iso(dl2)
        a["deadline_extended"] = True
    touch(a)
    return ok(ser(a, APPLICATION_FIELDS), "object", 200)


@app.route("/marketplace/applications/<aid>/decline", methods=["POST"])
def decline_application(aid):
    role, uid = require_roles("Candidate")
    a = get_application_or_404(aid)
    if uid != a["nurse_id"]:
        raise errors.forbidden("Candidate may only decline their own applications")
    if a["status"] not in ("SUBMITTED", "UNDER_REVIEW", "INTERVIEWING"):
        raise errors.invalid_state("Application cannot be declined from this state")
    a["status"] = "DECLINED"
    touch(a)
    nurse = db.nurses.get(a["nurse_id"])
    if nurse is not None:
        nurse["active_application_count"] = nurse_active_application_count(nurse)
    return ok(ser(a, APPLICATION_FIELDS), "object", 200)


@app.route("/marketplace/applications/<aid>/withdraw", methods=["POST"])
def withdraw_application(aid):
    role, uid = require_roles("Employer")
    a = get_application_or_404(aid)
    if uid != a["employer_id"]:
        raise errors.forbidden("Employer does not own this application")
    if a["status"] not in ("SUBMITTED", "UNDER_REVIEW", "INTERVIEWING"):
        raise errors.invalid_state("Application cannot be withdrawn from this state")
    for iv in db.interviews.values():
        if iv["application_id"] == aid and iv["status"] == "SCHEDULED":
            iv["status"] = "CANCELLED"
            touch(iv)
    a["status"] = "WITHDRAWN"
    a["_employer_withdrawn_at"] = now_iso()
    touch(a)
    nurse = db.nurses.get(a["nurse_id"])
    if nurse is not None:
        nurse["active_application_count"] = nurse_active_application_count(nurse)
    return ok(ser(a, APPLICATION_FIELDS), "object", 200)


@app.route("/marketplace/applications/<aid>/interviews", methods=["GET"])
def list_app_interviews(aid):
    role, uid = require_roles("Candidate", "Employer", "PlatformAdmin")
    a = get_application_or_404(aid)
    if role == "Candidate" and uid != a["nurse_id"]:
        raise errors.forbidden()
    if role == "Employer" and uid != a["employer_id"]:
        raise errors.forbidden()
    limit, offset = pagination_params()
    items = [i for i in db.interviews.values() if i["application_id"] == aid]
    items.sort(key=lambda i: i["created_at"])
    page, meta = paginate([ser(i, INTERVIEW_FIELDS) for i in items], limit, offset)
    return ok(page, "array", 200, pagination=meta)


@app.route("/marketplace/applications/<aid>/offers", methods=["GET"])
def list_app_offers(aid):
    role, uid = require_roles("Candidate", "Employer", "PlatformAdmin")
    a = get_application_or_404(aid)
    if role == "Candidate" and uid != a["nurse_id"]:
        raise errors.forbidden()
    if role == "Employer" and uid != a["employer_id"]:
        raise errors.forbidden()
    limit, offset = pagination_params()
    items = [o for o in db.offers.values() if o["application_id"] == aid]
    items.sort(key=lambda o: o["created_at"])
    page, meta = paginate([ser(o, OFFER_FIELDS) for o in items], limit, offset)
    return ok(page, "array", 200, pagination=meta)


@app.route("/marketplace/applications/<aid>/screenings", methods=["GET"])
def list_app_screenings(aid):
    role, uid = require_roles("Employer", "PlatformAdmin")
    a = get_application_or_404(aid)
    if role == "Employer" and uid != a["employer_id"]:
        raise errors.forbidden()
    limit, offset = pagination_params()
    items = [s for s in db.screenings.values() if s["application_id"] == aid]
    items.sort(key=lambda s: s["created_at"])
    page, meta = paginate([ser(s, SCREENING_FIELDS) for s in items], limit, offset)
    return ok(page, "array", 200, pagination=meta)


@app.route("/marketplace/applications/<aid>/onboarding-documents", methods=["GET"])
def list_app_docs(aid):
    role, uid = require_roles("Candidate", "Employer", "PlatformAdmin")
    a = get_application_or_404(aid)
    if role == "Candidate" and uid != a["nurse_id"]:
        raise errors.forbidden()
    if role == "Employer" and uid != a["employer_id"]:
        raise errors.forbidden()
    limit, offset = pagination_params()
    items = [d for d in db.onboarding_documents.values() if d["application_id"] == aid]
    items.sort(key=lambda d: d["created_at"])
    page, meta = paginate([ser(d, DOC_FIELDS) for d in items], limit, offset)
    return ok(page, "array", 200, pagination=meta)


# ---------------------------------------------------------------------------
# Interviews
# ---------------------------------------------------------------------------

@app.route("/marketplace/applications/<aid>/interviews", methods=["POST"])
def schedule_interview(aid):
    role, uid = require_roles("Employer")
    a = get_application_or_404(aid)
    if uid != a["employer_id"]:
        raise errors.forbidden("Employer does not own this application")
    if a["status"] not in ("UNDER_REVIEW", "INTERVIEWING"):
        raise errors.invalid_state("Application must be UNDER_REVIEW or INTERVIEWING")
    dl = parse_datetime(a["response_deadline_at"])
    if db.clock_now >= dl:
        raise errors.deadline_passed("Response deadline has passed")

    data = body()
    starts_raw = req_str(data, "starts_at")
    ends_raw = req_str(data, "ends_at")
    starts = parse_datetime(starts_raw)
    ends = parse_datetime(ends_raw)
    if starts is None or ends is None:
        raise errors.validation("starts_at and ends_at must be ISO 8601 datetimes")
    if starts <= db.clock_now:
        raise errors.terms_mismatch("starts_at must be strictly after clock now")
    if ends <= starts:
        raise errors.terms_mismatch("ends_at must be strictly after starts_at")
    duration_min = (ends - starts).total_seconds() / 60.0
    if duration_min < MIN_DURATION_MINUTES or duration_min > MAX_DURATION_MINUTES:
        raise errors.terms_mismatch("Interview duration must be 30-240 minutes")

    nurse_id = a["nurse_id"]
    buf = timedelta(minutes=BUFFER_MINUTES)
    for iv in db.interviews.values():
        if iv["status"] != "SCHEDULED":
            continue
        iv_app = db.applications.get(iv["application_id"])
        if iv_app is None or iv_app["nurse_id"] != nurse_id:
            continue
        s = parse_datetime(iv["starts_at"])
        e = parse_datetime(iv["ends_at"])
        # overlap iff starts < e + buf AND s - buf < ends
        if starts < e + buf and s - buf < ends:
            raise errors.interview_conflict()

    # unit day capacity
    req = db.requisitions.get(a["requisition_id"])
    if req is not None:
        unit_key = (req["facility_state"], req["unit_name"])
        target_day = starts.date()
        count = 0
        for iv in db.interviews.values():
            if iv["status"] not in ("SCHEDULED", "COMPLETED"):
                continue
            iv_app = db.applications.get(iv["application_id"])
            if iv_app is None:
                continue
            iv_req = db.requisitions.get(iv_app["requisition_id"])
            if iv_req is None:
                continue
            if (iv_req["facility_state"], iv_req["unit_name"]) != unit_key:
                continue
            if parse_datetime(iv["starts_at"]).date() == target_day:
                count += 1
        if count >= MAX_UNIT_INTERVIEWS_PER_DAY:
            raise errors.unit_day_capacity()

    iid = new_id()
    ts = now_iso()
    iv = {
        "id": iid,
        "application_id": aid,
        "starts_at": iso(starts),
        "ends_at": iso(ends),
        "status": "SCHEDULED",
        "scheduled_by_employer_at": ts,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.interviews[iid] = iv
    if a["status"] == "UNDER_REVIEW":
        a["status"] = "INTERVIEWING"
        touch(a)
    return ok(ser(iv, INTERVIEW_FIELDS), "object", 201)


@app.route("/marketplace/interviews/<iid>", methods=["GET"])
def get_interview(iid):
    role, uid = require_roles("Candidate", "Employer", "PlatformAdmin")
    iv = get_interview_or_404(iid)
    a = db.applications.get(iv["application_id"])
    if a is not None:
        if role == "Candidate" and uid != a["nurse_id"]:
            raise errors.forbidden()
        if role == "Employer" and uid != a["employer_id"]:
            raise errors.forbidden()
    return ok(ser(iv, INTERVIEW_FIELDS), "object", 200)


def _interview_employer_check(uid, iv):
    a = db.applications.get(iv["application_id"])
    if a is None or uid != a["employer_id"]:
        raise errors.forbidden("Employer does not own this interview")
    return a


@app.route("/marketplace/interviews/<iid>/complete", methods=["POST"])
def complete_interview(iid):
    role, uid = require_roles("Employer")
    iv = get_interview_or_404(iid)
    _interview_employer_check(uid, iv)
    if iv["status"] != "SCHEDULED":
        raise errors.invalid_state("Interview is not SCHEDULED")
    ends = parse_datetime(iv["ends_at"])
    if db.clock_now < ends:
        raise errors.deadline_passed("Interview window has not passed")
    iv["status"] = "COMPLETED"
    touch(iv)
    return ok(ser(iv, INTERVIEW_FIELDS), "object", 200)


@app.route("/marketplace/interviews/<iid>/cancel", methods=["POST"])
def cancel_interview(iid):
    role, uid = require_roles("Employer")
    iv = get_interview_or_404(iid)
    _interview_employer_check(uid, iv)
    if iv["status"] != "SCHEDULED":
        raise errors.invalid_state("Interview is not SCHEDULED")
    iv["status"] = "CANCELLED"
    touch(iv)
    return ok(ser(iv, INTERVIEW_FIELDS), "object", 200)


@app.route("/marketplace/interviews/<iid>/no-show", methods=["POST"])
def noshow_interview(iid):
    role, uid = require_roles("Employer")
    iv = get_interview_or_404(iid)
    _interview_employer_check(uid, iv)
    if iv["status"] != "SCHEDULED":
        raise errors.invalid_state("Interview is not SCHEDULED")
    ends = parse_datetime(iv["ends_at"])
    if db.clock_now <= ends:
        raise errors.deadline_passed("Interview window has not passed")
    iv["status"] = "NO_SHOW"
    touch(iv)
    return ok(ser(iv, INTERVIEW_FIELDS), "object", 200)


# ---------------------------------------------------------------------------
# Offers
# ---------------------------------------------------------------------------

@app.route("/marketplace/applications/<aid>/offers", methods=["POST"])
def issue_offer(aid):
    role, uid = require_roles("Employer")
    a = get_application_or_404(aid)
    if uid != a["employer_id"]:
        raise errors.forbidden("Employer does not own this application")
    data = body()
    offered_rate = req_int(data, "offered_hourly_rate_cents")
    start_date_raw = req_str(data, "start_date")
    if "expected_requisition_version" not in data or data["expected_requisition_version"] is None:
        raise errors.validation("expected_requisition_version is required")
    expected_rv = data["expected_requisition_version"]
    if isinstance(expected_rv, bool) or not isinstance(expected_rv, int):
        raise errors.validation("expected_requisition_version must be an integer")

    req = get_requisition_or_404(a["requisition_id"])

    # OCC
    if req["version"] != expected_rv:
        raise errors.stale_requisition_version("Requisition version mismatch")

    if a["status"] != "INTERVIEWING":
        raise errors.invalid_state("Application is not INTERVIEWING")

    dl = parse_datetime(a["response_deadline_at"])
    if db.clock_now >= dl:
        raise errors.deadline_passed("Response deadline has passed")

    # at least one COMPLETED interview
    any_completed = any(
        i["application_id"] == aid and i["status"] == "COMPLETED"
        for i in db.interviews.values()
    )
    if not any_completed:
        raise errors.invalid_state("No completed interview for this application")

    # terms
    if offered_rate != a["proposed_hourly_rate_cents"]:
        raise errors.terms_mismatch("Offer rate must equal current proposed rate")
    sd = parse_date(start_date_raw)
    if sd is None:
        raise errors.validation("start_date must be an ISO date")
    delta = (sd - today()).days
    if delta < 14 or delta > 90:
        raise errors.terms_mismatch("start_date must be 14-90 days after current date")

    # quota / suspension
    employer = db.employers.get(a["employer_id"])
    if employer is not None and employer["status"] != "ACTIVE":
        raise errors.no_openings("Employer is suspended")
    if req["status"] != "OPEN" or req["openings_filled"] >= req["openings_total"]:
        raise errors.no_openings("Requisition has no openings remaining")

    # duplicate: one non-terminal offer per application
    for o in db.offers.values():
        if o["application_id"] == aid and o["status"] in ("ISSUED",):
            raise errors.duplicate_resource("A non-terminal offer already exists")

    oid = new_id()
    ts = now_iso()
    offer = {
        "id": oid,
        "application_id": aid,
        "offered_hourly_rate_cents": offered_rate,
        "start_date": start_date_raw,
        "status": "ISSUED",
        "offer_expires_at": iso(db.clock_now + timedelta(hours=OFFER_EXPIRY_HOURS)),
        "issued_at": ts,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.offers[oid] = offer
    a["status"] = "OFFER_EXTENDED"
    touch(a)
    touch(req)
    nurse = db.nurses.get(a["nurse_id"])
    if nurse is not None:
        nurse["active_application_count"] = nurse_active_application_count(nurse)
    return ok(ser(offer, OFFER_FIELDS), "object", 201)


@app.route("/marketplace/offers/<oid>", methods=["GET"])
def get_offer(oid):
    role, uid = require_roles("Candidate", "Employer", "PlatformAdmin")
    o = get_offer_or_404(oid)
    a = db.applications.get(o["application_id"])
    if a is not None:
        if role == "Candidate" and uid != a["nurse_id"]:
            raise errors.forbidden()
        if role == "Employer" and uid != a["employer_id"]:
            raise errors.forbidden()
    return ok(ser(o, OFFER_FIELDS), "object", 200)


@app.route("/marketplace/offers/<oid>/accept", methods=["POST"])
def accept_offer(oid):
    role, uid = require_roles("Candidate")
    o = get_offer_or_404(oid)
    a = db.applications.get(o["application_id"])
    if a is None:
        raise errors.not_found("Application not found")
    if uid != a["nurse_id"]:
        raise errors.forbidden("Candidate does not own this offer")

    if o["status"] != "ISSUED":
        raise errors.invalid_state("Offer is not ISSUED")
    exp = parse_datetime(o["offer_expires_at"])
    if db.clock_now >= exp:
        raise errors.deadline_passed("Offer has expired")
    if a["status"] != "OFFER_EXTENDED":
        raise errors.invalid_state("Application is not OFFER_EXTENDED")

    # screening gate
    scr = None
    for s in db.screenings.values():
        if s["application_id"] == a["id"]:
            scr = s
            break
    if scr is None or scr["overall_status"] != "COMPLETE":
        raise errors.credentials_incomplete("Screening is not COMPLETE")

    # signed contract gate
    contract_ok = any(
        d["application_id"] == a["id"] and d["doc_type"] == "SIGNED_CONTRACT" and d["status"] == "APPROVED"
        for d in db.onboarding_documents.values()
    )
    if not contract_ok:
        raise errors.credentials_incomplete("No APPROVED SIGNED_CONTRACT document")

    # quota
    req = db.requisitions.get(a["requisition_id"])
    if req is None:
        raise errors.not_found("Requisition not found")
    if req["openings_filled"] >= req["openings_total"]:
        raise errors.no_openings("No openings remaining")

    employer = db.employers.get(a["employer_id"])
    nurse = db.nurses.get(a["nurse_id"])

    # --- atomic placement cascade ---
    # 1. Placement
    pid = new_id()
    ts = now_iso()
    annualized = o["offered_hourly_rate_cents"] * HOURS_PER_YEAR
    sd = parse_date(o["start_date"])
    guarantee_days = employer["guarantee_days"] if employer else 0
    guarantee_ends = sd + timedelta(days=guarantee_days)
    placement = {
        "id": pid,
        "application_id": a["id"],
        "requisition_id": a["requisition_id"],
        "nurse_id": a["nurse_id"],
        "employer_id": a["employer_id"],
        "hourly_rate_cents": o["offered_hourly_rate_cents"],
        "annualized_salary_cents": annualized,
        "start_date": o["start_date"],
        "guarantee_ends_on": guarantee_ends.isoformat(),
        "status": "PENDING_START",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.placements[pid] = placement

    # 2. requisition openings_filled += 1; maybe FILLED
    req["openings_filled"] += 1
    touch(req)
    if req["openings_filled"] >= req["openings_total"] and req["status"] == "OPEN":
        requisition_fill_cascade(req)

    # 3. nurse HIRED cascade
    if nurse is not None and nurse["status"] == "ACTIVE":
        nurse_hired_cascade(nurse, a["id"])

    # 4. application ACCEPTED
    a["status"] = "ACCEPTED"
    touch(a)

    # 5. offer ACCEPTED
    o["status"] = "ACCEPTED"
    touch(o)

    # 6. Invoice
    iid = new_id()
    fee = compute_provisional_fee(employer, annualized) if employer else 0
    invoice = {
        "id": iid,
        "employer_id": a["employer_id"],
        "placement_id": pid,
        "invoice_kind": "PLACEMENT_FEE",
        "amount_due_cents": fee,
        "amount_credited_cents": 0,
        "status": "ISSUED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.invoices[iid] = invoice

    if nurse is not None:
        nurse["active_application_count"] = nurse_active_application_count(nurse)

    return ok(ser(placement, PLACEMENT_FIELDS), "object", 200)


@app.route("/marketplace/offers/<oid>/decline", methods=["POST"])
def decline_offer(oid):
    role, uid = require_roles("Candidate")
    o = get_offer_or_404(oid)
    a = db.applications.get(o["application_id"])
    if a is None:
        raise errors.not_found("Application not found")
    if uid != a["nurse_id"]:
        raise errors.forbidden("Candidate does not own this offer")
    if o["status"] != "ISSUED":
        raise errors.invalid_state("Offer is not ISSUED")
    o["status"] = "DECLINED"
    touch(o)
    if a["status"] == "OFFER_EXTENDED":
        a["status"] = "DECLINED"
        touch(a)
        nurse = db.nurses.get(a["nurse_id"])
        if nurse is not None:
            nurse["active_application_count"] = nurse_active_application_count(nurse)
    return ok(ser(o, OFFER_FIELDS), "object", 200)


@app.route("/marketplace/offers/<oid>/rescind", methods=["POST"])
def rescind_offer(oid):
    role, uid = require_roles("Employer")
    o = get_offer_or_404(oid)
    a = db.applications.get(o["application_id"])
    if a is None:
        raise errors.not_found("Application not found")
    if uid != a["employer_id"]:
        raise errors.forbidden("Employer does not own this offer")
    if o["status"] != "ISSUED":
        raise errors.invalid_state("Offer is not ISSUED")
    o["status"] = "RESCINDED"
    touch(o)
    if a["status"] == "OFFER_EXTENDED":
        a["status"] = "WITHDRAWN"
        touch(a)
        nurse = db.nurses.get(a["nurse_id"])
        if nurse is not None:
            nurse["active_application_count"] = nurse_active_application_count(nurse)
    return ok(ser(o, OFFER_FIELDS), "object", 200)


# ---------------------------------------------------------------------------
# Screenings
# ---------------------------------------------------------------------------

@app.route("/marketplace/screenings", methods=["POST"])
def create_screening():
    role, uid = require_roles("Employer")
    data = body()
    application_id = req_str(data, "application_id")
    a = get_application_or_404(application_id)
    if uid != a["employer_id"]:
        raise errors.forbidden("Employer does not own this application")
    for s in db.screenings.values():
        if s["application_id"] == application_id:
            raise errors.duplicate_resource("Screening already exists for this application")
    sid = new_id()
    ts = now_iso()
    scr = {
        "id": sid,
        "application_id": application_id,
        "credential_status": "PENDING",
        "background_status": "PENDING",
        "overall_status": "IN_PROGRESS",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.screenings[sid] = scr
    return ok(ser(scr, SCREENING_FIELDS), "object", 201)


@app.route("/marketplace/screenings/<sid>", methods=["GET"])
def get_screening(sid):
    role, uid = require_roles("Employer", "PlatformAdmin")
    s = get_screening_or_404(sid)
    if role == "Employer":
        a = db.applications.get(s["application_id"])
        if a is None or uid != a["employer_id"]:
            raise errors.forbidden()
    return ok(ser(s, SCREENING_FIELDS), "object", 200)


def _rescind_issued_offer_cascade(app):
    for o in db.offers.values():
        if o["application_id"] == app["id"] and o["status"] == "ISSUED":
            o["status"] = "RESCINDED"
            touch(o)
            if app["status"] == "OFFER_EXTENDED":
                app["status"] = "WITHDRAWN"
                touch(app)
                nurse = db.nurses.get(app["nurse_id"])
                if nurse is not None:
                    nurse["active_application_count"] = nurse_active_application_count(nurse)


@app.route("/marketplace/screenings/<sid>/verify-credentials", methods=["POST"])
def verify_credentials(sid):
    require_roles("PlatformAdmin")
    s = get_screening_or_404(sid)
    if s["credential_status"] != "PENDING":
        raise errors.invalid_state("credential_status is not PENDING")
    a = db.applications.get(s["application_id"])
    req = db.requisitions.get(a["requisition_id"]) if a else None
    nurse = db.nurses.get(a["nurse_id"]) if a else None
    if req is not None and nurse is not None:
        if not nurse_holds_required_certs(nurse, req["required_certs"]):
            raise errors.credentials_incomplete("Nurse lacks required certifications")
    s["credential_status"] = "VERIFIED"
    s["overall_status"] = screening_overall(s["credential_status"], s["background_status"])
    touch(s)
    return ok(ser(s, SCREENING_FIELDS), "object", 200)


@app.route("/marketplace/screenings/<sid>/fail-credentials", methods=["POST"])
def fail_credentials(sid):
    require_roles("PlatformAdmin")
    s = get_screening_or_404(sid)
    if s["credential_status"] != "PENDING":
        raise errors.invalid_state("credential_status is not PENDING")
    s["credential_status"] = "FAILED"
    s["overall_status"] = screening_overall(s["credential_status"], s["background_status"])
    touch(s)
    a = db.applications.get(s["application_id"])
    if a is not None:
        _rescind_issued_offer_cascade(a)
    return ok(ser(s, SCREENING_FIELDS), "object", 200)


@app.route("/marketplace/screenings/<sid>/clear-background", methods=["POST"])
def clear_background(sid):
    require_roles("PlatformAdmin")
    s = get_screening_or_404(sid)
    if s["background_status"] != "PENDING":
        raise errors.invalid_state("background_status is not PENDING")
    s["background_status"] = "CLEARED"
    s["overall_status"] = screening_overall(s["credential_status"], s["background_status"])
    touch(s)
    return ok(ser(s, SCREENING_FIELDS), "object", 200)


@app.route("/marketplace/screenings/<sid>/flag-background", methods=["POST"])
def flag_background(sid):
    require_roles("PlatformAdmin")
    s = get_screening_or_404(sid)
    if s["background_status"] != "PENDING":
        raise errors.invalid_state("background_status is not PENDING")
    s["background_status"] = "FLAGGED"
    s["overall_status"] = screening_overall(s["credential_status"], s["background_status"])
    touch(s)
    a = db.applications.get(s["application_id"])
    if a is not None:
        _rescind_issued_offer_cascade(a)
    return ok(ser(s, SCREENING_FIELDS), "object", 200)


# ---------------------------------------------------------------------------
# Onboarding documents
# ---------------------------------------------------------------------------

@app.route("/marketplace/onboarding-documents", methods=["POST"])
def create_doc():
    role, uid = require_roles("Candidate")
    data = body()
    application_id = req_str(data, "application_id")
    doc_type = req_str(data, "doc_type")
    a = get_application_or_404(application_id)
    if uid != a["nurse_id"]:
        raise errors.forbidden("Candidate may only upload documents for their own applications")
    if doc_type not in DOC_TYPES:
        raise errors.validation("doc_type out of range")
    did = new_id()
    ts = now_iso()
    d = {
        "id": did,
        "application_id": application_id,
        "doc_type": doc_type,
        "status": "RECEIVED",
        "review_note": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.onboarding_documents[did] = d
    return ok(ser(d, DOC_FIELDS), "object", 201)


@app.route("/marketplace/onboarding-documents/<did>", methods=["GET"])
def get_doc(did):
    role, uid = require_roles("Candidate", "Employer", "PlatformAdmin")
    d = get_doc_or_404(did)
    a = db.applications.get(d["application_id"])
    if a is not None:
        if role == "Candidate" and uid != a["nurse_id"]:
            raise errors.forbidden()
        if role == "Employer" and uid != a["employer_id"]:
            raise errors.forbidden()
    return ok(ser(d, DOC_FIELDS), "object", 200)


def _doc_employer_check(uid, d):
    a = db.applications.get(d["application_id"])
    if a is None or uid != a["employer_id"]:
        raise errors.forbidden("Employer does not own this document")
    return a


@app.route("/marketplace/onboarding-documents/<did>/approve", methods=["POST"])
def approve_doc(did):
    role, uid = require_roles("Employer")
    d = get_doc_or_404(did)
    _doc_employer_check(uid, d)
    if d["status"] != "RECEIVED":
        raise errors.invalid_state("Document is not RECEIVED")
    d["status"] = "APPROVED"
    touch(d)
    return ok(ser(d, DOC_FIELDS), "object", 200)


@app.route("/marketplace/onboarding-documents/<did>/reject", methods=["POST"])
def reject_doc(did):
    role, uid = require_roles("Employer")
    d = get_doc_or_404(did)
    _doc_employer_check(uid, d)
    if d["status"] != "RECEIVED":
        raise errors.invalid_state("Document is not RECEIVED")
    data = body()
    note = data.get("review_note")
    if not note:
        raise errors.review_note_required("review_note is required")
    d["status"] = "REJECTED"
    d["review_note"] = note
    touch(d)
    return ok(ser(d, DOC_FIELDS), "object", 200)


# ---------------------------------------------------------------------------
# Placements
# ---------------------------------------------------------------------------

@app.route("/marketplace/placements/<pid>", methods=["GET"])
def get_placement(pid):
    role, uid = require_roles("Candidate", "Employer", "PlatformAdmin")
    p = get_placement_or_404(pid)
    if role == "Candidate" and uid != p["nurse_id"]:
        raise errors.forbidden()
    if role == "Employer" and uid != p["employer_id"]:
        raise errors.forbidden()
    return ok(ser(p, PLACEMENT_FIELDS), "object", 200)


@app.route("/marketplace/placements", methods=["GET"])
def list_placements():
    role, uid = require_roles("Candidate", "Employer", "PlatformAdmin")
    limit, offset = pagination_params()
    items = list(db.placements.values())
    if role == "Candidate":
        items = [p for p in items if p["nurse_id"] == uid]
    elif role == "Employer":
        items = [p for p in items if p["employer_id"] == uid]
    for key in ("nurse_id", "employer_id", "requisition_id", "application_id", "status"):
        v = request.args.get(key)
        if v:
            items = [p for p in items if p.get(key) == v]
    items.sort(key=lambda p: p["created_at"])
    page, meta = paginate([ser(p, PLACEMENT_FIELDS) for p in items], limit, offset)
    return ok(page, "array", 200, pagination=meta)


@app.route("/marketplace/placements/<pid>/terminate", methods=["POST"])
def terminate_placement(pid):
    role, uid = require_roles("Employer")
    p = get_placement_or_404(pid)
    if uid != p["employer_id"]:
        raise errors.forbidden("Employer does not own this placement")
    ge = parse_date(p["guarantee_ends_on"])
    if today() > ge:
        raise errors.placement_guarantee_expired("Guarantee window has closed")
    if p["status"] not in ("PENDING_START", "GUARANTEE_ACTIVE"):
        raise errors.invalid_state("Placement cannot be terminated from this state")

    was_pending_start = p["status"] == "PENDING_START"
    employer = db.employers.get(p["employer_id"])
    nurse = db.nurses.get(p["nurse_id"])
    req = db.requisitions.get(p["requisition_id"])

    p["status"] = "TERMINATED_IN_GUARANTEE"
    touch(p)

    # requisition reopening
    if req is not None:
        req["openings_filled"] = max(0, req["openings_filled"] - 1)
        if req["status"] == "FILLED":
            req["status"] = "OPEN"
        touch(req)

    # nurse back to ACTIVE
    if nurse is not None and nurse["status"] == "HIRED":
        nurse["status"] = "ACTIVE"
        touch(nurse)
        nurse["active_application_count"] = nurse_active_application_count(nurse)

    # invoice refund
    inv = None
    for i in db.invoices.values():
        if i.get("placement_id") == p["id"] and i["invoice_kind"] == "PLACEMENT_FEE":
            inv = i
            break
    if inv is not None and employer is not None:
        sd = parse_date(p["start_date"])
        now_d = today()
        days_served = max(0, (now_d - sd).days)
        gd = employer["guarantee_days"]
        if was_pending_start:
            numerator = gd
        else:
            numerator = max(0, gd - days_served)
        raw = Decimal(inv["amount_due_cents"]) * Decimal(numerator) / Decimal(gd)
        refund = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        inv["amount_credited_cents"] += refund
        if refund == inv["amount_due_cents"]:
            inv["status"] = "VOID"
        else:
            inv["status"] = "PARTIALLY_CREDITED"
        touch(inv)
        employer["credit_balance_cents"] += refund
        touch(employer)

    return ok(ser(p, PLACEMENT_FIELDS), "object", 200)


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

@app.route("/marketplace/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    role, uid = require_roles("Employer", "PlatformAdmin")
    inv = get_invoice_or_404(iid)
    if role == "Employer" and uid != inv["employer_id"]:
        raise errors.forbidden()
    return ok(ser(inv, INVOICE_FIELDS), "object", 200)


@app.route("/marketplace/invoices", methods=["GET"])
def list_invoices():
    role, uid = require_roles("Employer", "PlatformAdmin")
    limit, offset = pagination_params()
    items = list(db.invoices.values())
    if role == "Employer":
        items = [i for i in items if i["employer_id"] == uid]
    for key in ("employer_id", "placement_id", "status"):
        v = request.args.get(key)
        if v:
            items = [i for i in items if i.get(key) == v]
    items.sort(key=lambda i: i["created_at"])
    page, meta = paginate([ser(i, INVOICE_FIELDS) for i in items], limit, offset)
    return ok(page, "array", 200, pagination=meta)


@app.route("/marketplace/invoices/<iid>/settle", methods=["POST"])
def settle_invoice(iid):
    role, uid = require_roles("Employer")
    inv = get_invoice_or_404(iid)
    if uid != inv["employer_id"]:
        raise errors.forbidden("Employer does not own this invoice")
    if inv["status"] not in ("ISSUED", "PARTIALLY_CREDITED"):
        raise errors.invalid_state("Invoice cannot be settled from this state")
    employer = db.employers.get(inv["employer_id"])
    if employer is not None:
        outstanding = inv["amount_due_cents"] - inv["amount_credited_cents"]
        applied = min(employer["credit_balance_cents"], outstanding)
        if applied > 0:
            employer["credit_balance_cents"] -= applied
            inv["amount_credited_cents"] += applied
            touch(employer)
    inv["status"] = "SETTLED"
    touch(inv)
    return ok(ser(inv, INVOICE_FIELDS), "object", 200)


# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
