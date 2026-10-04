"""Routes: clock, users, parental controls, identity, tax, experiences, engagement."""
from datetime import datetime, timedelta, timezone

from flask import Blueprint, request

import services as svc
from db import DB
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_USER_NOT_FOUND,
    ERR_EXPERIENCE_NOT_FOUND,
    ERR_UNAUTHORIZED_ROLE,
    ERR_STALE_VERSION,
)
from middleware import auth_context, require_role
from response import success
from util import (
    audit,
    body,
    iso_ms,
    list_view,
    new_id,
    now_iso,
    opt_enum,
    opt_int,
    opt_str,
    paginate,
    parse_iso_date,
    parse_iso_dt,
    req_int,
    req_str,
    stamp_new,
    touch,
)

bp = Blueprint("core", __name__)

AGE_RATINGS = ("ALL", "NINE_PLUS", "THIRTEEN_PLUS", "SEVENTEEN_PLUS")


def get_user(uid):
    u = DB.users.get(uid)
    if u is None:
        raise err(ERR_USER_NOT_FOUND, "userId not found")
    return u


def get_experience(eid):
    e = DB.experiences.get(eid)
    if e is None:
        raise err(ERR_EXPERIENCE_NOT_FOUND, "experienceId not found")
    return e


def viewer_user(role, uid):
    if role == "Creator":
        return DB.users.get(uid)
    return None


# --- Clock -----------------------------------------------------------------


@bp.post("/ugc/_clock/set_current_utc")
def set_clock():
    actor, role = auth_context()
    require_role(role, "PlatformAdmin")
    data = body()
    dt = parse_iso_dt(data.get("to_iso8601"), "to_iso8601")
    DB.current_utc = dt
    for u in DB.users.values():
        svc.recompute_user_temporal(u)
        svc.check_iv_expiry(u["id"])
    audit(actor, "clock.set_current_utc", "Clock", "platform", {"to": iso_ms(dt)})
    return success({"current_utc": iso_ms(dt)}, 200)


# --- Users -----------------------------------------------------------------


@bp.post("/ugc/users")
def register_user():
    actor, role = auth_context()
    require_role(role, "Anonymous")
    data = body()
    username = req_str(data, "username", min_len=3, max_len=20, pattern=r"[A-Za-z0-9_]+")
    email = req_str(data, "email")
    dob = parse_iso_date(data.get("date_of_birth"), "date_of_birth")
    parent_id = data.get("parent_user_id")
    parent = None
    if parent_id is not None:
        if not isinstance(parent_id, str):
            raise err(ERR_INVALID_REQUEST, "parent_user_id must be a string or null")
        parent = DB.users.get(parent_id)
        if parent is None:
            raise err(ERR_USER_NOT_FOUND, "parent_user_id not found")
        svc.recompute_user_temporal(parent)
        if parent.get("age_band") != "ADULT" or parent.get("parent_user_id"):
            raise err(
                ERR_INVALID_REQUEST,
                "parent_user_id must reference an ADULT user with no parent of their own",
            )
    for u in DB.users.values():
        if u.get("username") == username:
            raise err(ERR_INVALID_REQUEST, "username already taken")
    user = {
        "id": new_id(),
        "username": username,
        "email": email,
        "date_of_birth": dob.isoformat(),
        "parent_user_id": parent_id,
        "status": "ACTIVE",
        "robux_balance": 0,
        "earned_robux_lifetime": 0,
        "suspension_reason": None,
        "terminated_at": None,
        "_dob": dob,
        "_created_dt": DB.current_utc,
    }
    stamp_new(user)
    svc.recompute_user_temporal(user)  # sets account_age_days, age_band, chat_filter_level
    DB.users[user["id"]] = user
    audit(actor, "user.register", "User", user["id"], {"username": username})
    return success(svc.view_user(user), 201)


@bp.get("/ugc/users/<uid>")
def get_user_route(uid):
    auth_context()
    require_role(
        auth_context()[1],
        "Anonymous",
        "Creator",
        "PlatformAdmin",
        "SafetyAgent",
        "Moderator",
        "AppealsReviewer",
        "FinanceOfficer",
    )
    return success(svc.view_user(get_user(uid)), 200)


@bp.get("/ugc/users")
def list_users():
    auth_context()
    require_role(
        auth_context()[1],
        "PlatformAdmin",
        "SafetyAgent",
        "Moderator",
        "AppealsReviewer",
        "FinanceOfficer",
    )
    for u in DB.users.values():
        svc.recompute_user_temporal(u)
    page, meta = list_view(
        DB.users,
        [("status", "status", None), ("age_band", "age_band", None), ("parent_user_id", "parent_user_id", None)],
    )
    return success([svc.view_user(u) for u in page], 200, meta)


def _tombstone_experience_chats(exp):
    for m in DB.chat_messages.values():
        if m["experience_id"] == exp["id"]:
            m["body_filtered"] = "[removed]"
            touch(m)


def suspend_user_cascade(user, reason, actor):
    user["status"] = "SUSPENDED"
    user["suspension_reason"] = reason
    touch(user)
    for rl in DB.resale_listings.values():
        if rl["seller_user_id"] == user["id"] and rl["status"] == "ACTIVE":
            rl["status"] = "CANCELLED"
            touch(rl)
    for e in DB.experiences.values():
        if e["creator_user_id"] == user["id"] and e["status"] == "PUBLISHED":
            e["status"] = "SUSPENDED"
            e["suspended_reason"] = reason
            touch(e)
            _tombstone_experience_chats(e)
    for d in DB.devex_requests.values():
        if d["user_id"] == user["id"] and d["status"] == "SUBMITTED":
            d["status"] = "CANCELLED"
            touch(d)
    audit(actor, "user.suspend", "User", user["id"], {"reason": reason})


@bp.post("/ugc/users/<uid>/suspend")
def suspend_user(uid):
    actor, role = auth_context()
    require_role(role, "PlatformAdmin", "SafetyAgent")
    user = get_user(uid)
    if user["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "User is not ACTIVE")
    data = body()
    reason = opt_str(data, "reason")
    suspend_user_cascade(user, reason, actor)
    return success(svc.view_user(user), 200)


@bp.post("/ugc/users/<uid>/reinstate")
def reinstate_user(uid):
    actor, role = auth_context()
    require_role(role, "PlatformAdmin")
    user = get_user(uid)
    if user["status"] != "SUSPENDED":
        raise err(ERR_INVALID_STATE, "User is not SUSPENDED")
    user["status"] = "ACTIVE"
    user["suspension_reason"] = None
    touch(user)
    audit(actor, "user.reinstate", "User", user["id"], {})
    return success(svc.view_user(user), 200)


# --- Parental controls ------------------------------------------------------


@bp.post("/ugc/users/<uid>/parental-controls")
def set_parental_controls(uid):
    actor, role = auth_context()
    require_role(role, "Creator")
    parent = get_user(uid)
    if actor != parent["id"]:
        raise err(ERR_UNAUTHORIZED_ROLE, "Only the linked parent may manage these controls")
    data = body()
    child_id = data.get("child_user_id")
    if not isinstance(child_id, str) or not child_id:
        raise err(ERR_INVALID_REQUEST, "child_user_id is required")
    child = DB.users.get(child_id)
    if child is None:
        raise err(ERR_USER_NOT_FOUND, "child_user_id not found")
    if child.get("parent_user_id") != parent["id"]:
        raise err(ERR_UNAUTHORIZED_ROLE, "child_user_id is not linked to this parent")
    pin_hash = req_str(data, "pin_hash")
    spend = opt_int(data, "monthly_spend_limit_robux", minimum=0)
    chat_mode = opt_enum(data, "chat_mode", ("RESTRICTED", "FILTERED", "OPEN"))
    allowed = data.get("allowed_age_ratings")
    if allowed is None:
        allowed = []
    if not isinstance(allowed, list) or any(a not in AGE_RATINGS for a in allowed):
        raise err(ERR_INVALID_REQUEST, "allowed_age_ratings must be a subset of rating levels")
    if "expected_user_version" not in data:
        raise err(ERR_INVALID_REQUEST, "expected_user_version is required")
    expected = data.get("expected_user_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err(ERR_INVALID_REQUEST, "expected_user_version must be an integer")
    if expected != parent["version"]:
        raise err(ERR_STALE_VERSION, "expected_user_version does not match current user version")
    existing = svc.get_pc(child_id)
    ts = now_iso()
    if existing is None:
        pc = {
            "id": new_id(),
            "child_user_id": child_id,
            "monthly_spend_limit_robux": spend,
            "chat_mode": chat_mode or "FILTERED",
            "allowed_age_ratings": allowed,
            "pin_hash": pin_hash,
            "last_changed_at": ts,
        }
        stamp_new(pc)
        DB.parental_controls[pc["id"]] = pc
    else:
        pc = existing
        pc["monthly_spend_limit_robux"] = spend
        pc["chat_mode"] = chat_mode or "FILTERED"
        pc["allowed_age_ratings"] = allowed
        pc["pin_hash"] = pin_hash
        pc["last_changed_at"] = ts
        touch(pc)
    touch(parent)
    svc.recompute_chat_filter(child)
    touch(child)
    audit(actor, "parental_controls.set", "ParentalControls", pc["id"], {"child_user_id": child_id})
    return success({k: v for k, v in pc.items() if not k.startswith("_")}, 200)


@bp.get("/ugc/users/<uid>/parental-controls")
def get_parental_controls(uid):
    actor, role = auth_context()
    require_role(role, "Creator", "PlatformAdmin")
    parent = get_user(uid)
    if role == "Creator" and actor != parent["id"]:
        raise err(ERR_UNAUTHORIZED_ROLE, "Only the linked parent may read these controls")
    child_id = request.args.get("child_user_id")
    if not child_id:
        raise err(ERR_INVALID_REQUEST, "child_user_id query parameter is required")
    rows = [pc for pc in DB.parental_controls.values() if pc["child_user_id"] == child_id]
    rows.sort(key=lambda r: (r.get("created_at", ""), r["id"]))
    page, meta = paginate(rows)
    return success([{k: v for k, v in pc.items() if not k.startswith("_")} for pc in page], 200, meta)


# --- Identity verifications --------------------------------------------------


@bp.post("/ugc/users/<uid>/identity-verifications")
def submit_iv(uid):
    actor, role = auth_context()
    require_role(role, "Creator")
    user = get_user(uid)
    if actor != user["id"]:
        raise err(ERR_UNAUTHORIZED_ROLE, "Cannot submit identity verification for another user")
    data = body()
    doc_type = opt_enum(data, "document_type", ("PASSPORT", "DRIVERS_LICENSE", "NATIONAL_ID"))
    if doc_type is None:
        raise err(ERR_INVALID_REQUEST, "document_type is required")
    doc_country = req_str(data, "document_country")
    expiry_raw = data.get("expiry_date")
    if expiry_raw is None:
        raise err(ERR_INVALID_REQUEST, "expiry_date is required")
    expiry_dt = parse_iso_dt(expiry_raw, "expiry_date")
    iv = {
        "id": new_id(),
        "user_id": user["id"],
        "status": "PENDING",
        "document_type": doc_type,
        "document_country": doc_country,
        "submitted_at": iso_ms(DB.current_utc),
        "reviewed_at": None,
        "rejection_reason": None,
        "expiry_date": expiry_raw,
        "_expiry_dt": expiry_dt,
    }
    stamp_new(iv)
    DB.identity_verifications[iv["id"]] = iv
    audit(actor, "identity_verification.submit", "IdentityVerification", iv["id"], {})
    return success({k: v for k, v in iv.items() if not k.startswith("_")}, 201)


@bp.get("/ugc/users/<uid>/identity-verifications")
def list_iv(uid):
    actor, role = auth_context()
    require_role(role, "Creator", "PlatformAdmin")
    user = get_user(uid)
    svc.check_iv_expiry(user["id"])
    rows = [v for v in DB.identity_verifications.values() if v["user_id"] == user["id"]]
    rows.sort(key=lambda r: (r.get("created_at", ""), r["id"]))
    page, meta = paginate(rows)
    return success([{k: v for k, v in r.items() if not k.startswith("_")} for r in page], 200, meta)


def _get_iv(iv_id):
    iv = DB.identity_verifications.get(iv_id)
    if iv is None:
        raise err(ERR_USER_NOT_FOUND, "identity verification not found")
    return iv


@bp.post("/ugc/identity-verifications/<iv_id>/verify")
def verify_iv(iv_id):
    actor, role = auth_context()
    require_role(role, "PlatformAdmin")
    iv = _get_iv(iv_id)
    if iv["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Identity verification is not PENDING")
    iv["status"] = "VERIFIED"
    iv["reviewed_at"] = now_iso()
    touch(iv)
    audit(actor, "identity_verification.verify", "IdentityVerification", iv["id"], {})
    return success({k: v for k, v in iv.items() if not k.startswith("_")}, 200)


@bp.post("/ugc/identity-verifications/<iv_id>/reject")
def reject_iv(iv_id):
    actor, role = auth_context()
    require_role(role, "PlatformAdmin")
    iv = _get_iv(iv_id)
    if iv["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Identity verification is not PENDING")
    data = body()
    reason = opt_str(data, "rejection_reason")
    if not reason:
        raise err(ERR_INVALID_REQUEST, "rejection_reason is required")
    iv["status"] = "REJECTED"
    iv["rejection_reason"] = reason
    iv["reviewed_at"] = now_iso()
    touch(iv)
    audit(actor, "identity_verification.reject", "IdentityVerification", iv["id"], {})
    return success({k: v for k, v in iv.items() if not k.startswith("_")}, 200)


# --- Tax documents -----------------------------------------------------------


@bp.post("/ugc/users/<uid>/tax-documents")
def submit_tax(uid):
    actor, role = auth_context()
    require_role(role, "Creator")
    user = get_user(uid)
    if actor != user["id"]:
        raise err(ERR_UNAUTHORIZED_ROLE, "Cannot submit tax document for another user")
    data = body()
    form_type = opt_enum(data, "form_type", ("W9", "W8BEN", "W8BENE"))
    if form_type is None:
        raise err(ERR_INVALID_REQUEST, "form_type is required")
    tin_last4 = req_str(data, "tin_last4")
    legal_name = req_str(data, "legal_name")
    country = req_str(data, "country_of_residence")
    td = {
        "id": new_id(),
        "user_id": user["id"],
        "status": "UNDER_REVIEW",  # SUBMITTED then auto -> UNDER_REVIEW
        "form_type": form_type,
        "tin_last4": tin_last4,
        "legal_name": legal_name,
        "country_of_residence": country,
        "submitted_at": iso_ms(DB.current_utc),
        "reviewed_at": None,
        "rejection_reason": None,
    }
    stamp_new(td)
    DB.tax_documents[td["id"]] = td
    audit(actor, "tax_document.submit", "TaxDocument", td["id"], {})
    return success({k: v for k, v in td.items() if not k.startswith("_")}, 201)


@bp.get("/ugc/users/<uid>/tax-documents")
def list_tax(uid):
    actor, role = auth_context()
    require_role(role, "Creator", "PlatformAdmin", "FinanceOfficer")
    user = get_user(uid)
    rows = [t for t in DB.tax_documents.values() if t["user_id"] == user["id"]]
    rows.sort(key=lambda r: (r.get("created_at", ""), r["id"]))
    page, meta = paginate(rows)
    return success([{k: v for k, v in r.items() if not k.startswith("_")} for r in page], 200, meta)


def _get_td(td_id):
    td = DB.tax_documents.get(td_id)
    if td is None:
        raise err(ERR_USER_NOT_FOUND, "tax document not found")
    return td


@bp.post("/ugc/tax-documents/<td_id>/accept")
def accept_tax(td_id):
    actor, role = auth_context()
    require_role(role, "PlatformAdmin")
    td = _get_td(td_id)
    if td["status"] != "UNDER_REVIEW":
        raise err(ERR_INVALID_STATE, "Tax document is not UNDER_REVIEW")
    td["status"] = "ACCEPTED"
    td["reviewed_at"] = now_iso()
    touch(td)
    audit(actor, "tax_document.accept", "TaxDocument", td["id"], {})
    return success({k: v for k, v in td.items() if not k.startswith("_")}, 200)


@bp.post("/ugc/tax-documents/<td_id>/reject")
def reject_tax(td_id):
    actor, role = auth_context()
    require_role(role, "PlatformAdmin")
    td = _get_td(td_id)
    if td["status"] != "UNDER_REVIEW":
        raise err(ERR_INVALID_STATE, "Tax document is not UNDER_REVIEW")
    data = body()
    reason = opt_str(data, "rejection_reason")
    if not reason:
        raise err(ERR_INVALID_REQUEST, "rejection_reason is required")
    td["status"] = "REJECTED"
    td["rejection_reason"] = reason
    td["reviewed_at"] = now_iso()
    touch(td)
    audit(actor, "tax_document.reject", "TaxDocument", td["id"], {})
    return success({k: v for k, v in td.items() if not k.startswith("_")}, 200)


# --- Experiences -------------------------------------------------------------


def view_exp_for(exp, role, uid):
    return svc.view_experience(exp, viewer_user(role, uid))


@bp.post("/ugc/experiences")
def create_experience():
    actor, role = auth_context()
    require_role(role, "Creator")
    creator = DB.users.get(actor)
    if creator is None:
        raise err(ERR_USER_NOT_FOUND, "acting user not found")
    data = body()
    title = req_str(data, "title", min_len=3, max_len=60)
    description = data.get("description")
    if description is None:
        description = ""
    if not isinstance(description, str):
        raise err(ERR_INVALID_REQUEST, "description must be a string")
    exp = {
        "id": new_id(),
        "creator_user_id": creator["id"],
        "title": title,
        "description": description,
        "status": "DRAFT",
        "age_rating": None,
        "content_descriptors": [],
        "visit_count_lifetime": 0,
        "engagement_minutes_30d": 0,
        "engagement_payout_pending_robux": 0,
        "suspended_reason": None,
        "archived_at": None,
    }
    stamp_new(exp)
    DB.experiences[exp["id"]] = exp
    audit(actor, "experience.create", "Experience", exp["id"], {})
    return success(view_exp_for(exp, role, actor), 201)


@bp.get("/ugc/experiences/<eid>")
def get_experience_route(eid):
    actor, role = auth_context()
    require_role(
        role,
        "Anonymous",
        "Creator",
        "PlatformAdmin",
        "Moderator",
        "SafetyAgent",
        "AppealsReviewer",
        "FinanceOfficer",
    )
    return success(view_exp_for(get_experience(eid), role, actor), 200)


@bp.get("/ugc/experiences")
def list_experiences():
    actor, role = auth_context()
    require_role(
        role,
        "Anonymous",
        "Creator",
        "PlatformAdmin",
        "Moderator",
        "SafetyAgent",
        "AppealsReviewer",
        "FinanceOfficer",
    )
    page, meta = list_view(
        DB.experiences,
        [
            ("creator_user_id", "creator_user_id", None),
            ("status", "status", None),
            ("age_rating", "age_rating", None),
        ],
    )
    return success([view_exp_for(e, role, actor) for e in page], 200, meta)


@bp.post("/ugc/experiences/<eid>/submit-for-review")
def submit_experience(eid):
    actor, role = auth_context()
    require_role(role, "Creator")
    exp = get_experience(eid)
    if exp["creator_user_id"] != actor:
        raise err(ERR_UNAUTHORIZED_ROLE, "Only the owning creator may submit for review")
    if exp["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Experience is not DRAFT")
    creator = DB.users.get(exp["creator_user_id"])
    if creator is None or creator["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Creator is not ACTIVE")
    exp["status"] = "PENDING_REVIEW"
    touch(exp)
    from routes_money import create_submission

    sub = create_submission("EXPERIENCE", exp["id"], actor)
    audit(actor, "experience.submit_for_review", "Experience", exp["id"], {"submission_id": sub["id"]})
    return success(view_exp_for(exp, role, actor), 200)


@bp.post("/ugc/experiences/<eid>/suspend")
def suspend_experience(eid):
    actor, role = auth_context()
    require_role(role, "PlatformAdmin", "SafetyAgent")
    exp = get_experience(eid)
    if exp["status"] != "PUBLISHED":
        raise err(ERR_INVALID_STATE, "Experience is not PUBLISHED")
    data = body()
    exp["status"] = "SUSPENDED"
    exp["suspended_reason"] = opt_str(data, "reason")
    touch(exp)
    _tombstone_experience_chats(exp)
    audit(actor, "experience.suspend", "Experience", exp["id"], {})
    return success(view_exp_for(exp, role, actor), 200)


@bp.post("/ugc/experiences/<eid>/republish")
def republish_experience(eid):
    actor, role = auth_context()
    require_role(role, "Creator")
    exp = get_experience(eid)
    if exp["creator_user_id"] != actor:
        raise err(ERR_UNAUTHORIZED_ROLE, "Only the owning creator may republish")
    if exp["status"] != "SUSPENDED":
        raise err(ERR_INVALID_STATE, "Experience is not SUSPENDED")
    creator = DB.users.get(exp["creator_user_id"])
    if creator is None or creator["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Creator is not ACTIVE")
    exp["status"] = "PUBLISHED"
    exp["suspended_reason"] = None
    touch(exp)
    audit(actor, "experience.republish", "Experience", exp["id"], {})
    return success(view_exp_for(exp, role, actor), 200)


def settle_experience_payout(exp):
    pending = exp.get("engagement_payout_pending_robux", 0)
    if pending:
        creator = DB.users.get(exp["creator_user_id"])
        if creator is not None:
            creator["earned_robux_lifetime"] = creator.get("earned_robux_lifetime", 0) + pending
            touch(creator)
        exp["engagement_payout_pending_robux"] = 0
    return pending


@bp.post("/ugc/experiences/<eid>/archive")
def archive_experience(eid):
    actor, role = auth_context()
    require_role(role, "Creator")
    exp = get_experience(eid)
    if exp["creator_user_id"] != actor:
        raise err(ERR_UNAUTHORIZED_ROLE, "Only the owning creator may archive")
    if exp["status"] not in ("DRAFT", "PUBLISHED", "SUSPENDED"):
        raise err(ERR_INVALID_STATE, "Experience cannot be archived from its current state")
    settle_experience_payout(exp)
    exp["status"] = "ARCHIVED"
    exp["archived_at"] = now_iso()
    touch(exp)
    audit(actor, "experience.archive", "Experience", exp["id"], {})
    return success(view_exp_for(exp, role, actor), 200)


@bp.get("/ugc/experiences/<eid>/age-ratings")
def list_exp_age_ratings(eid):
    auth_context()
    require_role(auth_context()[1], "Anonymous", "Creator", "PlatformAdmin", "Moderator", "AppealsReviewer")
    exp = get_experience(eid)
    rows = [r for r in DB.age_ratings.values() if r["experience_id"] == exp["id"]]
    rows.sort(key=lambda r: (r.get("created_at", ""), r["id"]))
    page, meta = paginate(rows)
    return success([{k: v for k, v in r.items() if not k.startswith("_")} for r in page], 200, meta)


@bp.get("/ugc/experiences/<eid>/chat-messages")
def list_exp_chat(eid):
    auth_context()
    require_role(auth_context()[1], "Creator", "PlatformAdmin", "SafetyAgent", "Moderator")
    exp = get_experience(eid)
    rows = [m for m in DB.chat_messages.values() if m["experience_id"] == exp["id"]]
    sender = request.args.get("sender_user_id")
    if sender is not None:
        rows = [m for m in rows if m["sender_user_id"] == sender]
    rows.sort(key=lambda r: (r.get("created_at", ""), r["id"]))
    page, meta = paginate(rows)
    return success([{k: v for k, v in m.items() if not k.startswith("_")} for m in page], 200, meta)


# --- Engagement --------------------------------------------------------------


@bp.post("/ugc/experiences/<eid>/engagement-snapshots")
def post_snapshot(eid):
    actor, role = auth_context()
    require_role(role, "PlatformAdmin")
    exp = get_experience(eid)
    if exp["status"] == "ARCHIVED":
        raise err(ERR_INVALID_STATE, "Experience is ARCHIVED; snapshots no longer accumulate")
    data = body()
    snapshot_date = data.get("snapshot_date")
    if snapshot_date is None:
        snapshot_date = DB.current_utc.date().isoformat()
    else:
        parse_iso_date(snapshot_date, "snapshot_date")
    minutes = req_int(data, "minutes_engaged", minimum=0)
    payout = svc.engagement_payout_robux(minutes, exp.get("age_rating"))
    snap = {
        "id": new_id(),
        "experience_id": exp["id"],
        "snapshot_date": snapshot_date,
        "minutes_engaged": minutes,
        "payout_robux": payout,
    }
    snap["created_at"] = now_iso()
    DB.engagement_snapshots[snap["id"]] = snap
    exp["engagement_payout_pending_robux"] = exp.get("engagement_payout_pending_robux", 0) + payout
    # recompute rolling 30-day window against the logical clock
    window_start = DB.current_utc.date() - timedelta(days=29)
    total = 0
    for s in DB.engagement_snapshots.values():
        if s["experience_id"] != exp["id"]:
            continue
        try:
            d = datetime.strptime(s["snapshot_date"], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        if window_start <= d <= DB.current_utc.date():
            total += s["minutes_engaged"]
    exp["engagement_minutes_30d"] = total
    touch(exp)
    audit(actor, "engagement.snapshot", "EngagementSnapshot", snap["id"], {"payout_robux": payout})
    return success({k: v for k, v in snap.items() if not k.startswith("_")}, 201)


@bp.get("/ugc/experiences/<eid>/engagement-snapshots")
def list_snapshots(eid):
    auth_context()
    require_role(auth_context()[1], "Creator", "PlatformAdmin", "FinanceOfficer")
    exp = get_experience(eid)
    rows = [s for s in DB.engagement_snapshots.values() if s["experience_id"] == exp["id"]]
    rows.sort(key=lambda r: (r.get("created_at", ""), r["id"]))
    page, meta = paginate(rows)
    return success([{k: v for k, v in s.items() if not k.startswith("_")} for s in page], 200, meta)


@bp.post("/ugc/_engagement/settle_monthly")
def settle_monthly():
    actor, role = auth_context()
    require_role(role, "PlatformAdmin")
    settled = 0
    total = 0
    for exp in DB.experiences.values():
        if exp["status"] != "PUBLISHED":
            continue
        total += settle_experience_payout(exp)
        touch(exp)
        settled += 1
    audit(actor, "engagement.settle_monthly", "Experience", "*", {"settled_count": settled, "total": total})
    return success({"settled_count": settled, "total_robux_credited": total}, 200)
