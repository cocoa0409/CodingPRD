"""Routes: chat, reports, account termination, reverse-reachability lists."""
from datetime import timedelta

from flask import Blueprint

import services as svc
from db import DB
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_ITEM_NOT_FOUND,
    ERR_PARENTAL_CHAT_RESTRICTED,
    ERR_REPORT_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_TERMINATION_NOT_FOUND,
    ERR_UNAUTHORIZED_ROLE,
    ERR_USER_NOT_FOUND,
    ERR_EXPERIENCE_NOT_FOUND,
    ERR_ORDER_NOT_FOUND,
)
from middleware import auth_context, require_role
from response import success
from util import (
    SYSTEM_USER_ID,
    audit,
    body,
    iso_ms,
    list_view,
    new_id,
    now_iso,
    opt_enum,
    paginate,
    req_int,
    req_str,
    stamp_new,
    touch,
)
from routes_core import (
    _tombstone_experience_chats,
    get_experience,
    get_user,
    suspend_user_cascade,
)

bp = Blueprint("safety", __name__)

REASON_CODES = ("HARASSMENT", "SCAM", "INAPPROPRIATE_CONTENT", "PERSONAL_INFO", "OTHER")
TERM_REASONS = ("FRAUD", "SAFETY_VIOLATION", "LEGAL_REQUEST", "PARENT_REQUEST", "SELF_REQUEST")
DISPOSITIONS = ("FORFEIT_TO_PLATFORM", "DONATE_TO_CHARITY", "PAYOUT_TO_VERIFIED_USER")


def _public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def get_message(mid):
    m = DB.chat_messages.get(mid)
    if m is None:
        raise err(ERR_INVALID_REQUEST, "messageId not found")
    return m


def get_report(rid):
    r = DB.reports.get(rid)
    if r is None:
        raise err(ERR_REPORT_NOT_FOUND, "reportId not found")
    return r


def get_termination(tid):
    t = DB.account_terminations.get(tid)
    if t is None:
        raise err(ERR_TERMINATION_NOT_FOUND, "terminationId not found")
    return t


# --- Chat ---------------------------------------------------------------------


@bp.post("/ugc/experiences/<eid>/chat-messages")
def send_chat(eid):
    actor, role = auth_context()
    require_role(role, "Creator")
    exp = get_experience(eid)
    sender = DB.users.get(actor)
    if sender is None:
        raise err(ERR_USER_NOT_FOUND, "acting user not found")
    data = body()
    body_raw = req_str(data, "body_raw")
    svc.recompute_user_temporal(sender)
    pc = svc.get_pc(sender["id"])
    if pc is not None and pc.get("chat_mode") == "RESTRICTED":
        raise err(ERR_PARENTAL_CHAT_RESTRICTED, "Parental controls forbid free-text chat")
    level = sender.get("chat_filter_level", "SAFE")
    msg = {
        "id": new_id(),
        "experience_id": exp["id"],
        "sender_user_id": sender["id"],
        "body_raw": body_raw,
        "body_filtered": svc.apply_chat_filter(body_raw, level),
        "filter_applied": level,
        "was_reported": False,
        "sent_at": iso_ms(DB.current_utc),
    }
    stamp_new(msg)
    DB.chat_messages[msg["id"]] = msg
    audit(actor, "chat.send", "ChatMessage", msg["id"], {})
    return success(_public(msg), 201)


@bp.get("/ugc/chat-messages/<mid>")
def get_message_route(mid):
    auth_context()
    require_role(auth_context()[1], "Creator", "PlatformAdmin", "SafetyAgent", "Moderator")
    return success(_public(get_message(mid)), 200)


@bp.get("/ugc/chat-messages")
def list_messages():
    auth_context()
    require_role(auth_context()[1], "Creator", "PlatformAdmin", "SafetyAgent", "Moderator")
    page, meta = list_view(
        DB.chat_messages,
        [
            ("sender_user_id", "sender_user_id", None),
            ("experience_id", "experience_id", None),
            ("was_reported", "was_reported", "bool"),
        ],
    )
    return success([_public(m) for m in page], 200, meta)


# --- Reports -------------------------------------------------------------------


@bp.post("/ugc/chat-messages/<mid>/reports")
def file_report(mid):
    actor, role = auth_context()
    require_role(role, "Creator", "SafetyAgent")
    msg = get_message(mid)
    data = body()
    reason_code = opt_enum(data, "reason_code", REASON_CODES)
    if reason_code is None:
        raise err(ERR_INVALID_REQUEST, "reason_code is required")
    report = {
        "id": new_id(),
        "message_id": msg["id"],
        "reporter_user_id": actor,
        "reason_code": reason_code,
        "status": "OPEN",
        "triaged_by_user_id": None,
        "triaged_at": None,
        "action_taken": None,
    }
    stamp_new(report)
    DB.reports[report["id"]] = report
    msg["was_reported"] = True
    touch(msg)
    audit(actor, "report.file", "Report", report["id"], {})
    return success(_public(report), 201)


@bp.get("/ugc/reports/<rid>")
def get_report_route(rid):
    auth_context()
    require_role(auth_context()[1], "SafetyAgent", "PlatformAdmin", "Moderator")
    return success(_public(get_report(rid)), 200)


@bp.get("/ugc/reports")
def list_reports():
    auth_context()
    require_role(auth_context()[1], "SafetyAgent", "PlatformAdmin", "Moderator")
    page, meta = list_view(
        DB.reports,
        [
            ("status", "status", None),
            ("reason_code", "reason_code", None),
            ("message_id", "message_id", None),
            ("reporter_user_id", "reporter_user_id", None),
            ("triaged_by_user_id", "triaged_by_user_id", None),
        ],
    )
    return success([_public(r) for r in page], 200, meta)


@bp.post("/ugc/reports/<rid>/triage")
def triage_report(rid):
    actor, role = auth_context()
    require_role(role, "SafetyAgent")
    report = get_report(rid)
    if report["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Report is not OPEN")
    report["status"] = "TRIAGED"
    report["triaged_at"] = now_iso()
    report["triaged_by_user_id"] = actor
    touch(report)
    audit(actor, "report.triage", "Report", report["id"], {})
    return success(_public(report), 200)


@bp.post("/ugc/reports/<rid>/action")
def action_report(rid):
    actor, role = auth_context()
    require_role(role, "SafetyAgent")
    report = get_report(rid)
    if report["status"] != "TRIAGED":
        raise err(ERR_INVALID_STATE, "Report is not TRIAGED")
    data = body()
    action = data.get("action_taken")
    if action == "NONE":
        raise err(ERR_INVALID_REQUEST, "NONE is not a valid terminal action")
    if action not in ("WARNING", "SUSPEND_SENDER", "TERMINATE_SENDER"):
        raise err(ERR_INVALID_REQUEST, "action_taken must be WARNING, SUSPEND_SENDER, or TERMINATE_SENDER")
    report["action_taken"] = action
    report["status"] = "ACTIONED"
    touch(report)
    msg = DB.chat_messages[report["message_id"]]
    msg["was_reported"] = True
    touch(msg)
    sender = DB.users.get(msg["sender_user_id"])
    if sender is not None:
        if action == "SUSPEND_SENDER" and sender["status"] == "ACTIVE":
            suspend_user_cascade(sender, "chat safety action", actor)
        elif action == "TERMINATE_SENDER":
            create_termination_row(sender["id"], "SAFETY_VIOLATION", "FORFEIT_TO_PLATFORM", actor)
    audit(actor, "report.action", "Report", report["id"], {"action_taken": action})
    return success(_public(report), 200)


@bp.post("/ugc/reports/<rid>/dismiss")
def dismiss_report(rid):
    actor, role = auth_context()
    require_role(role, "SafetyAgent")
    report = get_report(rid)
    if report["status"] != "TRIAGED":
        raise err(ERR_INVALID_STATE, "Report is not TRIAGED")
    report["status"] = "DISMISSED"
    touch(report)
    audit(actor, "report.dismiss", "Report", report["id"], {})
    return success(_public(report), 200)


# --- Account termination ---------------------------------------------------------


def create_termination_row(user_id, reason_code, disposition, actor):
    term = {
        "id": new_id(),
        "user_id": user_id,
        "initiated_by_user_id": actor,
        "reason_code": reason_code,
        "status": "PENDING_DISPOSITION",
        "earnings_disposition": disposition,
        "disposed_robux": None,
        "disposed_usd_cents": None,
        "terminated_at": None,
    }
    stamp_new(term)
    DB.account_terminations[term["id"]] = term
    audit(actor, "account_termination.initiate", "AccountTermination", term["id"], {})
    return term


@bp.post("/ugc/account-terminations")
def initiate_termination():
    actor, role = auth_context()
    require_role(role, "PlatformAdmin", "SafetyAgent")
    data = body()
    user_id = data.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        raise err(ERR_INVALID_REQUEST, "user_id is required")
    user = get_user(user_id)
    reason_code = opt_enum(data, "reason_code", TERM_REASONS)
    if reason_code is None:
        raise err(ERR_INVALID_REQUEST, "reason_code is required")
    disposition = opt_enum(data, "earnings_disposition", DISPOSITIONS)
    if reason_code != "SELF_REQUEST" and disposition is None:
        raise err(ERR_INVALID_REQUEST, "earnings_disposition is required for this reason_code")
    if disposition in ("FORFEIT_TO_PLATFORM", "DONATE_TO_CHARITY") and reason_code not in (
        "FRAUD",
        "SAFETY_VIOLATION",
        "LEGAL_REQUEST",
    ):
        raise err(
            ERR_INVALID_REQUEST,
            "earnings_disposition is not admissible for this reason_code",
        )
    if disposition == "PAYOUT_TO_VERIFIED_USER" and reason_code != "SELF_REQUEST":
        raise err(
            ERR_INVALID_REQUEST,
            "PAYOUT_TO_VERIFIED_USER is admissible only for SELF_REQUEST",
        )
    if actor == user["id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES, "Cannot initiate termination on one's own account")
    term = create_termination_row(user["id"], reason_code, disposition, actor)
    return success(_public(term), 201)


@bp.get("/ugc/account-terminations/<tid>")
def get_termination_route(tid):
    auth_context()
    require_role(auth_context()[1], "PlatformAdmin", "SafetyAgent", "FinanceOfficer")
    return success(_public(get_termination(tid)), 200)


@bp.get("/ugc/account-terminations")
def list_terminations():
    auth_context()
    require_role(auth_context()[1], "PlatformAdmin", "SafetyAgent", "FinanceOfficer")
    page, meta = list_view(
        DB.account_terminations,
        [
            ("user_id", "user_id", None),
            ("initiated_by_user_id", "initiated_by_user_id", None),
            ("status", "status", None),
        ],
    )
    return success([_public(t) for t in page], 200, meta)


def _terminate_children(user):
    """Push child entities to terminal states."""
    for rl in DB.resale_listings.values():
        if rl["seller_user_id"] == user["id"] and rl["status"] == "ACTIVE":
            rl["status"] = "CANCELLED"
            touch(rl)
    for e in DB.experiences.values():
        if e["creator_user_id"] == user["id"] and e["status"] != "ARCHIVED":
            e["status"] = "ARCHIVED"
            e["archived_at"] = now_iso()
            touch(e)
    for d in DB.devex_requests.values():
        if d["user_id"] == user["id"] and d["status"] in ("SUBMITTED", "APPROVED"):
            d["status"] = "CANCELLED"
            touch(d)


def _reverse_recent_sales(user, disposition):
    """COMPLETED -> REVERSED for sales within 30 days when earnings forfeited."""
    if disposition != "FORFEIT_TO_PLATFORM":
        return
    cutoff = DB.current_utc - timedelta(days=30)
    for o in DB.purchase_orders.values():
        if o["status"] != "COMPLETED":
            continue
        c = o.get("_completed_dt")
        if c is None or c < cutoff:
            continue
        seller_id = None
        if o["item_type"] == "MARKETPLACE_ITEM":
            item = DB.marketplace_items.get(o["item_id"])
            seller_id = item["creator_user_id"] if item else None
        elif o["item_type"] == "EXPERIENCE_GAMEPASS":
            exp = DB.experiences.get(o["item_id"])
            seller_id = exp["creator_user_id"] if exp else None
        elif o["item_type"] == "LIMITED_ITEM_RESALE":
            listing = DB.resale_listings.get(o["item_id"])
            seller_id = listing["seller_user_id"] if listing else None
        if seller_id != user["id"]:
            continue
        o["status"] = "REVERSED"
        touch(o)


@bp.post("/ugc/account-terminations/<tid>/dispose-earnings")
def dispose_earnings(tid):
    actor, role = auth_context()
    require_role(role, "PlatformAdmin")
    term = get_termination(tid)
    if term["status"] != "PENDING_DISPOSITION":
        raise err(ERR_INVALID_STATE, "Termination is not PENDING_DISPOSITION")
    user = DB.users.get(term["user_id"])
    if user is None:
        raise err(ERR_USER_NOT_FOUND, "user not found")
    if term["initiated_by_user_id"] == term["user_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES, "Initiator may not equal the termination target")
    disposition = term.get("earnings_disposition")
    if disposition == "PAYOUT_TO_VERIFIED_USER" and not svc.devex_eligible(user):
        from errors import ERR_DEVEX_NOT_ELIGIBLE

        raise err(ERR_DEVEX_NOT_ELIGIBLE, "Target user is not DevEx eligible")
    disposed = user.get("robux_balance", 0)
    term["disposed_robux"] = disposed
    term["disposed_usd_cents"] = svc.devex_ladder_cents(disposed)
    user["robux_balance"] = 0
    touch(user)
    _reverse_recent_sales(user, disposition)
    if disposition == "PAYOUT_TO_VERIFIED_USER":
        synthetic = {
            "id": new_id(),
            "user_id": user["id"],
            "status": "PAID",
            "requested_robux": disposed,
            "locked_robux": disposed,
            "usd_payout_cents": term["disposed_usd_cents"],
            "withholding_tax_cents": 0,
            "net_payout_cents": term["disposed_usd_cents"],
            "submitted_at": iso_ms(DB.current_utc),
            "approved_at": now_iso(),
            "paid_at": now_iso(),
            "expected_user_version": user["version"],
            "_approved_by": SYSTEM_USER_ID,
        }
        stamp_new(synthetic)
        DB.devex_requests[synthetic["id"]] = synthetic
    term["status"] = "EARNINGS_DISPOSED"
    touch(term)
    audit(actor, "account_termination.dispose_earnings", "AccountTermination", term["id"], {"disposed_robux": disposed})
    # system transition: EARNINGS_DISPOSED -> COMPLETE -> User.TERMINATED
    term["status"] = "COMPLETE"
    term["terminated_at"] = now_iso()
    touch(term)
    user["status"] = "TERMINATED"
    user["terminated_at"] = now_iso()
    touch(user)
    _terminate_children(user)
    audit(SYSTEM_USER_ID, "account_termination.complete", "AccountTermination", term["id"], {})
    return success(_public(term), 200)


# --- Reverse-reachability lists ---------------------------------------------------


@bp.get("/ugc/experience-age-ratings/<rid>")
def get_age_rating(rid):
    auth_context()
    require_role(auth_context()[1], "Anonymous", "Creator", "PlatformAdmin", "Moderator", "AppealsReviewer")
    r = DB.age_ratings.get(rid)
    if r is None:
        raise err(ERR_EXPERIENCE_NOT_FOUND, "age rating not found")
    return success(_public(r), 200)


@bp.get("/ugc/experience-age-ratings")
def list_age_ratings():
    auth_context()
    require_role(auth_context()[1], "Anonymous", "Creator", "PlatformAdmin", "Moderator", "AppealsReviewer")
    page, meta = list_view(
        DB.age_ratings,
        [
            ("experience_id", "experience_id", None),
            ("supersedes_id", "supersedes_id", None),
            ("is_current", "is_current", "bool"),
        ],
    )
    return success([_public(r) for r in page], 200, meta)


@bp.get("/ugc/audit-logs/<aid>")
def get_audit(aid):
    auth_context()
    require_role(auth_context()[1], "PlatformAdmin")
    a = DB.audit_logs.get(aid)
    if a is None:
        raise err(ERR_INVALID_REQUEST, "audit log entry not found")
    return success(_public(a), 200)


@bp.get("/ugc/audit-logs")
def list_audit():
    auth_context()
    require_role(auth_context()[1], "PlatformAdmin")
    page, meta = list_view(
        DB.audit_logs,
        [
            ("actor_user_id", "actor_user_id", None),
            ("subject_type", "subject_type", None),
            ("subject_id", "subject_id", None),
        ],
    )
    return success([_public(a) for a in page], 200, meta)
