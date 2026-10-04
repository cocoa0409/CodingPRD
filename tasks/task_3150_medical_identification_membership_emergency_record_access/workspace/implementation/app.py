"""Medical Identification Membership API — Flask implementation.

All state is in-memory (db.py). No seeding at startup.
"""

import os
import re
from datetime import timedelta

from flask import Flask, request

import db
import services as S
import validation as V
from errors import ApiError  # noqa: F401
from errors import (  # noqa: F401
    ERR_MEMBER_NOT_FOUND, ERR_RECORD_ITEM_NOT_FOUND, ERR_ORDER_NOT_FOUND,
    ERR_TICKET_NOT_FOUND, ERR_PRODUCT_NOT_FOUND, ERR_CONTACT_NOT_FOUND,
    ERR_DIRECTIVE_NOT_FOUND, ERR_CASE_NOT_FOUND, ERR_DISPUTE_NOT_FOUND,
    ERR_RESPONDER_NOT_FOUND, ERR_INVALID_STATE, ERR_INVALID_REQUEST,
    ERR_RESPONDER_AUTH_FAILED, ERR_MEMBER_NOT_DISCLOSABLE,
    ERR_WANDERING_NOT_ELIGIBLE, ERR_CONTACT_PRIORITY_CONFLICT,
    ERR_ENGRAVING_OVERFLOW, ERR_RECORD_ITEM_NOT_DISPUTABLE,
    ERR_INSUFFICIENT_FUNDS, ERR_DUPLICATE_EMAIL, ERR_DUPLICATE_CREDENTIAL,
    ERR_DUPLICATE_SKU, ERR_GUARDIAN_LINK_INVALID,
)
from response import success_object, success_list, error_response

app = Flask(__name__)

ZERO_UUID = "00000000-0000-0000-0000-000000000000"

TIERS = ["STANDARD", "PREMIUM", "LIFETIME"]
ITEM_KINDS = ["CONDITION", "MEDICATION", "ALLERGY"]
CONDITION_KINDS = ["GENERAL", "COGNITIVE"]
SEVERITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
DIRECTIVE_TYPES = ["DNR", "POLST", "LIVING_WILL", "HEALTHCARE_PROXY"]
RELEASE_SCOPES = ["EMERGENCY_ONLY", "EMERGENCY_AND_CONTACTS", "FULL"]
ENGRAVE_MODES = ["MANUAL", "SYNC_WITH_RECORD"]
ACCESS_TIERS = ["BASIC", "FULL"]
LOOKUP_METHODS = ["IDENTIFIER", "HOTLINE"]
OPENED_VIAS = ["SELF_REPORT", "HOTLINE_ESCALATION"]
WANDERING_OUTCOMES = ["REUNITED", "OTHER"]
DISPUTE_RESOLUTIONS = ["UPHELD", "CORRECTED"]

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
IDENT_RE = re.compile(r"^MID-\d{6}$")

_identifier_counter = {"n": 0}


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    return error_response("ERR_NOT_FOUND", "Route not found", 404)


@app.errorhandler(405)
def handle_405(err):
    return error_response("ERR_NOT_FOUND", "Method not allowed", 404)


# ---------------------------------------------------------------------------
# Field helpers
# ---------------------------------------------------------------------------

def _valid_date(s):
    if not isinstance(s, str) or not DATE_RE.match(s):
        return False
    try:
        S.parse_date(s)
        return True
    except ValueError:
        return False


def _req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError(ERR_INVALID_REQUEST, f"Missing or invalid field: {field}")
    return v


def _req_int(body, field):
    v = body.get(field)
    if not isinstance(v, int) or isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, f"Missing or invalid field: {field}")
    return v


def _mint_identifier():
    # Format MID-######, unique across members.
    while True:
        S.new_id()  # keep import used
        _identifier_counter["n"] += 1
        code = "MID-" + str(100000 + (_identifier_counter["n"] * 7919) % 900000)
        if all(m["identifier_code"] != code for m in db.members.values()):
            return code


def _list_response(rows):
    rows = sorted(rows, key=lambda r: r["created_at"])
    limit, offset = V.parse_pagination()
    page, total, has_more = V.paginate(rows, limit, offset)
    return success_list(page, limit, offset, total, has_more)


def _member_child_or_404(store, child_id, member_id, error_id):
    obj = store.get(child_id)
    if obj is None or obj["member_id"] != member_id:
        raise ApiError(error_id, "child resource not found for this member")
    return obj


# ---------------------------------------------------------------------------
# Clock & reminders dispatch
# ---------------------------------------------------------------------------

@app.post("/medical-id/_clock/set_current_utc")
def set_clock():
    uid, role = V.actor()
    V.require_roles(role, ["PlatformAdmin"])
    body = V.get_json_body()
    current = body.get("current_utc")
    if not isinstance(current, str):
        raise ApiError(ERR_INVALID_REQUEST, "current_utc must be an ISO 8601 string")
    try:
        S.parse_dt(current)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, "current_utc must be an ISO 8601 string")
    db.set_logical_now(current)
    new_date = S.logical_date()
    # Lapse sweep
    for member in db.members.values():
        if (
            member["status"] == "ACTIVE"
            and member["membership_tier"] != "LIFETIME"
            and member["expires_on"] is not None
            and S.parse_date(member["expires_on"]) <= new_date
        ):
            member["status"] = "SUSPENDED"
            S.bump_member(member)
            S.cancel_pending_reminders(member["id"])
            S.create_reminder(member["id"], "LAPSE_WARNING", member["expires_on"])
            S.append_audit(member["id"], role, uid, "LAPSE",
                           {"member_id": member["id"]})
    return success_object({"current_utc": db.logical_now()})


@app.post("/medical-id/_reminders/dispatch")
def dispatch_reminders():
    uid, role = V.actor()
    V.require_roles(role, ["PlatformAdmin"])
    today = S.logical_date()
    sent = []
    for r in sorted(db.reminders.values(), key=lambda x: x["created_at"]):
        if r["status"] == "PENDING" and S.parse_date(r["due_on"]) <= today:
            r["status"] = "SENT"
            r["sent_on"] = today.isoformat()
            sent.append(r["id"])
    return success_object({"sent_count": len(sent), "sent_reminder_ids": sent})


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------

@app.post("/medical-id/members")
def create_member():
    uid, role = V.actor()
    V.require_roles(role, ["PlatformAdmin"])
    body = V.get_json_body()
    V.require_fields(body, ["full_name", "email", "membership_tier", "date_of_birth"])
    full_name = _req_str(body, "full_name")
    email = _req_str(body, "email")
    tier = V.require_enum(body, "membership_tier", TIERS)
    dob = _req_str(body, "date_of_birth")
    if not _valid_date(dob):
        raise ApiError(ERR_INVALID_REQUEST, "date_of_birth must be YYYY-MM-DD")
    # Uniqueness
    for m in db.members.values():
        if m["email"] == email:
            raise ApiError(ERR_DUPLICATE_EMAIL, "email already registered")

    dob_date = S.parse_date(dob)
    today = S.logical_date()
    member_type = "MINOR" if S.age_on(dob_date, today) < 18 else "ADULT"

    ts = S.now_ts()
    member = {
        "id": S.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "full_name": full_name,
        "email": email,
        "membership_tier": tier,
        "member_type": member_type,
        "date_of_birth": dob,
        "has_cognitive_condition": False,
        "first_lifetime_sync_order_consumed": False,
        "status": "ACTIVE",
        "expires_on": None,
        "identifier_code": _mint_identifier(),
        "balance_cents": 0,
        "wallet_credit_cents": 0,
        "record_revision": 0,
    }
    tm = S.term_months(tier)
    if tm is not None:
        member["expires_on"] = S.add_months(today, tm).isoformat()
    db.members[member["id"]] = member
    fee = S.compute_membership_fee(member)
    member["balance_cents"] += fee
    if tier != "LIFETIME":
        S.create_reminder(
            member["id"],
            "RENEWAL",
            (S.parse_date(member["expires_on"]) - timedelta(days=S.RENEWAL_LEAD_DAYS)).isoformat(),
        )
    S.create_reminder(
        member["id"],
        "RECORD_UPDATE",
        (today + timedelta(days=S.RECORD_UPDATE_CYCLE_DAYS)).isoformat(),
    )
    S.append_audit(member["id"], role, uid, "ENROLL", {"member_id": member["id"]})
    return success_object(member, 201)


@app.get("/medical-id/members")
def list_members():
    uid, role = V.actor()
    V.require_roles(role, ["PlatformAdmin", "HotlineOperator"])
    rows = list(db.members.values())
    if "status" in request.args:
        rows = [m for m in rows if m["status"] == request.args["status"]]
    if "membership_tier" in request.args:
        rows = [m for m in rows if m["membership_tier"] == request.args["membership_tier"]]
    if "member_type" in request.args:
        rows = [m for m in rows if m["member_type"] == request.args["member_type"]]
    return _list_response(rows)


@app.get("/medical-id/members/<memberId>")
def get_member(memberId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian", "PlatformAdmin", "HotlineOperator"])
    member = V.get_member_or_404(memberId)
    V.check_member_scope(uid, role, memberId)
    return success_object(member)


@app.post("/medical-id/members/<memberId>/renew")
def renew_member(memberId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian"])
    member = V.get_member_or_404(memberId)
    V.check_member_scope(uid, role, memberId)
    body = V.get_json_body()
    # Tier precondition: LIFETIME cannot renew.
    if member["membership_tier"] == "LIFETIME":
        raise ApiError(ERR_INVALID_STATE, "LIFETIME members cannot renew")
    if member["status"] == "CANCELLED":
        raise ApiError(ERR_INVALID_STATE, "CANCELLED member cannot renew")
    amount = _req_int(body, "amount_paid_cents")
    if amount < 0:
        raise ApiError(ERR_INVALID_REQUEST, "amount_paid_cents must be >= 0")
    fee = S.compute_membership_fee(member)
    if member["wallet_credit_cents"] + amount < fee:
        raise ApiError(ERR_INSUFFICIENT_FUNDS, "insufficient funds for renewal")
    # Apply wallet first
    applied = min(member["wallet_credit_cents"], fee)
    member["wallet_credit_cents"] -= applied
    # The renewal fee is debited to the member's balance (same schedule as §3.1).
    member["balance_cents"] += fee
    today = S.logical_date()
    tm = S.term_months(member["membership_tier"])
    if member["status"] == "SUSPENDED":
        new_exp = S.add_months(today, tm)
        S.cancel_pending_reminders(member["id"], {"LAPSE_WARNING"})
    else:  # ACTIVE early renewal
        new_exp = S.add_months(max(S.parse_date(member["expires_on"]), today), tm)
    member["expires_on"] = new_exp.isoformat()
    member["status"] = "ACTIVE"
    S.bump_member(member)
    S.reanchor_renewal_reminder(member)
    S.append_audit(member["id"], role, uid, "RENEWAL",
                   {"member_id": member["id"], "fee_cents": fee,
                    "wallet_applied_cents": applied, "amount_paid_cents": amount})
    return success_object(member)


@app.post("/medical-id/members/<memberId>/cancel")
def cancel_member(memberId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian", "PlatformAdmin"])
    member = V.get_member_or_404(memberId)
    V.check_member_scope(uid, role, memberId)
    if member["status"] == "CANCELLED":
        raise ApiError(ERR_INVALID_STATE, "member already CANCELLED")
    member["status"] = "CANCELLED"
    S.bump_member(member)
    # Cascade
    for o in db.orders.values():
        if o["member_id"] == memberId and o["status"] == "PENDING":
            o["status"] = "CANCELLED"
            o["version"] += 1
            o["updated_at"] = S.now_ts()
            member["wallet_credit_cents"] += o["price_cents"]
    for d in db.disputes.values():
        if d["member_id"] == memberId and d["status"] in ("OPEN", "UNDER_REVIEW"):
            d["status"] = "DISMISSED"
            d["version"] += 1
            d["updated_at"] = S.now_ts()
    for c in db.wandering_cases.values():
        if c["member_id"] == memberId and c["status"] == "OPEN":
            c["status"] = "RESOLVED"
            c["outcome"] = "OTHER"
            c["resolved_at"] = S.now_ts()
            c["version"] += 1
            c["updated_at"] = S.now_ts()
    S.cancel_pending_reminders(memberId)
    for gl in db.guardian_links.values():
        if gl["status"] == "ACTIVE" and (
            gl["member_id"] == memberId or gl["guardian_member_id"] == memberId
        ):
            gl["status"] = "REVOKED"
            gl["version"] += 1
            gl["updated_at"] = S.now_ts()
    S.append_audit(memberId, role, uid, "CANCEL", {"member_id": memberId})
    return success_object(member)


# ---------------------------------------------------------------------------
# Guardian links
# ---------------------------------------------------------------------------

@app.post("/medical-id/members/<memberId>/guardian-links")
def create_guardian_link(memberId):
    uid, role = V.actor()
    V.require_roles(role, ["PlatformAdmin"])
    dependent = V.get_member_or_404(memberId)
    body = V.get_json_body()
    V.require_fields(body, ["guardian_member_id", "relation_label"])
    guardian_id = _req_str(body, "guardian_member_id")
    relation_label = _req_str(body, "relation_label")
    guardian = db.members.get(guardian_id)
    if (
        guardian_id == memberId
        or guardian is None
        or guardian["status"] != "ACTIVE"
        or guardian["member_type"] != "ADULT"
        or any(
            gl["member_id"] == memberId and gl["status"] == "ACTIVE"
            for gl in db.guardian_links.values()
        )
    ):
        raise ApiError(ERR_GUARDIAN_LINK_INVALID, "guardian link target invalid")
    ts = S.now_ts()
    gl = {
        "id": S.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "member_id": memberId,
        "guardian_member_id": guardian_id,
        "relation_label": relation_label,
        "status": "ACTIVE",
    }
    db.guardian_links[gl["id"]] = gl
    S.append_audit(memberId, role, uid, "GUARDIAN_LINK",
                   {"guardian_link_id": gl["id"], "guardian_member_id": guardian_id})
    return success_object(gl, 201)


@app.get("/medical-id/members/<memberId>/guardian-links")
def list_dependent_links(memberId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian", "PlatformAdmin"])
    V.get_member_or_404(memberId)
    V.check_member_scope(uid, role, memberId)
    rows = [gl for gl in db.guardian_links.values() if gl["member_id"] == memberId]
    if "status" in request.args:
        rows = [gl for gl in rows if gl["status"] == request.args["status"]]
    return _list_response(rows)


@app.get("/medical-id/members/<memberId>/guardianships")
def list_guardianships(memberId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian", "PlatformAdmin"])
    V.get_member_or_404(memberId)
    V.check_member_scope(uid, role, memberId)
    rows = [gl for gl in db.guardian_links.values() if gl["guardian_member_id"] == memberId]
    if "status" in request.args:
        rows = [gl for gl in rows if gl["status"] == request.args["status"]]
    return _list_response(rows)


@app.get("/medical-id/guardian-links")
def list_all_links():
    uid, role = V.actor()
    V.require_roles(role, ["PlatformAdmin"])
    rows = list(db.guardian_links.values())
    if "member_id" in request.args:
        rows = [gl for gl in rows if gl["member_id"] == request.args["member_id"]]
    if "guardian_member_id" in request.args:
        rows = [gl for gl in rows if gl["guardian_member_id"] == request.args["guardian_member_id"]]
    if "status" in request.args:
        rows = [gl for gl in rows if gl["status"] == request.args["status"]]
    return _list_response(rows)


@app.get("/medical-id/guardian-links/<linkId>")
def get_link(linkId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian", "PlatformAdmin"])
    gl = db.guardian_links.get(linkId)
    if gl is None:
        raise ApiError(ERR_MEMBER_NOT_FOUND, "guardian link not found")
    return success_object(gl)


@app.post("/medical-id/guardian-links/<linkId>/revoke")
def revoke_link(linkId):
    uid, role = V.actor()
    V.require_roles(role, ["PlatformAdmin"])
    gl = db.guardian_links.get(linkId)
    if gl is None:
        raise ApiError(ERR_MEMBER_NOT_FOUND, "guardian link not found")
    if gl["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "guardian link not ACTIVE")
    gl["status"] = "REVOKED"
    gl["version"] += 1
    gl["updated_at"] = S.now_ts()
    S.append_audit(gl["member_id"], role, uid, "GUARDIAN_REVOKE",
                   {"guardian_link_id": gl["id"]})
    return success_object(gl)


# ---------------------------------------------------------------------------
# Record items + verification tickets
# ---------------------------------------------------------------------------

def _open_ticket(item, doc_ref, submission_round):
    ts = S.now_ts()
    t = {
        "id": S.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "record_item_id": item["id"],
        "member_id": item["member_id"],
        "provider_document_ref": doc_ref,
        "submission_round": submission_round,
        "decision_note": None,
        "status": "OPEN",
    }
    db.tickets[t["id"]] = t
    return t


@app.post("/medical-id/members/<memberId>/record-items")
def create_record_item(memberId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian"])
    member = V.get_member_or_404(memberId)
    V.check_member_scope(uid, role, memberId)
    V.require_member_active(member)
    body = V.get_json_body()
    V.require_fields(body, ["item_kind", "label", "detail", "severity", "provider_document_ref"])
    item_kind = V.require_enum(body, "item_kind", ITEM_KINDS)
    label = _req_str(body, "label")
    detail = _req_str(body, "detail")
    severity = V.require_enum(body, "severity", SEVERITIES)
    doc_ref = _req_str(body, "provider_document_ref")
    condition_kind = body.get("condition_kind", "GENERAL")
    if condition_kind not in CONDITION_KINDS:
        raise ApiError(ERR_INVALID_REQUEST, "condition_kind invalid")

    S.bump_record_revision(member)
    S.bump_member(member)
    ts = S.now_ts()
    item = {
        "id": S.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "member_id": memberId,
        "item_kind": item_kind,
        "condition_kind": condition_kind,
        "label": label,
        "detail": detail,
        "severity": severity,
        "provider_document_ref": doc_ref,
        "record_revision": member["record_revision"],
        "status": "PENDING_VERIFICATION",
    }
    db.record_items[item["id"]] = item
    _open_ticket(item, doc_ref, 1)
    S.recompute_cognitive(member)
    S.reanchor_record_update_reminder(member)
    S.resync_pending_sync_orders(member)
    S.append_audit(memberId, role, uid, "RECORD_CAPTURE",
                   {"record_item_id": item["id"]})
    return success_object(item, 201)


@app.get("/medical-id/members/<memberId>/record-items")
def list_member_record_items(memberId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian", "RecordVerifier", "PlatformAdmin"])
    V.get_member_or_404(memberId)
    V.check_member_scope(uid, role, memberId)
    rows = [it for it in db.record_items.values() if it["member_id"] == memberId]
    if "status" in request.args:
        rows = [it for it in rows if it["status"] == request.args["status"]]
    if "item_kind" in request.args:
        rows = [it for it in rows if it["item_kind"] == request.args["item_kind"]]
    return _list_response(rows)


@app.get("/medical-id/members/<memberId>/record-items/<itemId>")
def get_member_record_item(memberId, itemId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian", "RecordVerifier", "PlatformAdmin"])
    V.get_member_or_404(memberId)
    item = _member_child_or_404(db.record_items, itemId, memberId, ERR_RECORD_ITEM_NOT_FOUND)
    V.check_member_scope(uid, role, memberId)
    return success_object(item)


@app.post("/medical-id/members/<memberId>/record-items/<itemId>/submit-for-verification")
def resubmit_record_item(memberId, itemId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian"])
    member = V.get_member_or_404(memberId)
    item = _member_child_or_404(db.record_items, itemId, memberId, ERR_RECORD_ITEM_NOT_FOUND)
    V.check_member_scope(uid, role, memberId)
    V.require_member_active(member)
    body = V.get_json_body()
    doc_ref = _req_str(body, "provider_document_ref")
    if item["status"] != "REJECTED":
        raise ApiError(ERR_INVALID_STATE, "item is not REJECTED")
    if any(
        t for t in db.tickets.values()
        if t["record_item_id"] == itemId and t["status"] == "OPEN"
    ):
        raise ApiError(ERR_INVALID_STATE, "an OPEN ticket already exists for this item")
    prev_rounds = [t["submission_round"] for t in db.tickets.values() if t["record_item_id"] == itemId]
    next_round = max(prev_rounds, default=0) + 1
    item["status"] = "PENDING_VERIFICATION"
    item["provider_document_ref"] = doc_ref
    item["version"] += 1
    item["updated_at"] = S.now_ts()
    _open_ticket(item, doc_ref, next_round)
    S.append_audit(memberId, role, uid, "RECORD_RESUBMIT",
                   {"record_item_id": itemId, "submission_round": next_round})
    return success_object(item)


@app.post("/medical-id/members/<memberId>/record-items/<itemId>/supersede")
def supersede_record_item(memberId, itemId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian"])
    member = V.get_member_or_404(memberId)
    item = _member_child_or_404(db.record_items, itemId, memberId, ERR_RECORD_ITEM_NOT_FOUND)
    V.check_member_scope(uid, role, memberId)
    V.require_member_active(member)
    if item["status"] != "VERIFIED":
        raise ApiError(ERR_INVALID_STATE, "item is not VERIFIED")
    body = V.get_json_body()
    V.require_fields(body, ["replacement_label", "replacement_detail",
                            "provider_document_ref", "expected_member_version"])
    replacement_label = _req_str(body, "replacement_label")
    replacement_detail = _req_str(body, "replacement_detail")
    doc_ref = _req_str(body, "provider_document_ref")
    V.require_occ(body, member)
    new_item = _do_supersede(member, item, replacement_label, replacement_detail, doc_ref, role, uid,
                             audit_action="RECORD_SUPERSEDE")
    return success_object(new_item)


def _do_supersede(member, item, replacement_label, replacement_detail, doc_ref,
                  role, uid, audit_action="RECORD_SUPERSEDE"):
    """Shared supersede side-effect set (§3.3 / §3.9 CORRECTED)."""
    item["status"] = "SUPERSEDED"
    item["version"] += 1
    item["updated_at"] = S.now_ts()
    S.bump_record_revision(member)
    S.bump_member(member)
    ts = S.now_ts()
    new_item = {
        "id": S.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "member_id": member["id"],
        "item_kind": item["item_kind"],
        "condition_kind": "GENERAL",
        "label": replacement_label,
        "detail": replacement_detail,
        "severity": item["severity"],
        "provider_document_ref": doc_ref,
        "record_revision": member["record_revision"],
        "status": "PENDING_VERIFICATION",
    }
    db.record_items[new_item["id"]] = new_item
    _open_ticket(new_item, doc_ref, 1)
    S.recompute_cognitive(member)
    S.reanchor_record_update_reminder(member)
    S.resync_pending_sync_orders(member)
    S.append_audit(member["id"], role, uid, audit_action,
                   {"superseded_item_id": item["id"], "replacement_item_id": new_item["id"]})
    return new_item


@app.get("/medical-id/record-items/<itemId>")
def get_record_item(itemId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian", "RecordVerifier", "PlatformAdmin"])
    item = db.record_items.get(itemId)
    if item is None:
        raise ApiError(ERR_RECORD_ITEM_NOT_FOUND, "record item not found")
    return success_object(item)


@app.get("/medical-id/record-items")
def list_record_items():
    uid, role = V.actor()
    V.require_roles(role, ["RecordVerifier", "PlatformAdmin"])
    rows = list(db.record_items.values())
    if "member_id" in request.args:
        rows = [it for it in rows if it["member_id"] == request.args["member_id"]]
    if "status" in request.args:
        rows = [it for it in rows if it["status"] == request.args["status"]]
    if "item_kind" in request.args:
        rows = [it for it in rows if it["item_kind"] == request.args["item_kind"]]
    return _list_response(rows)


@app.get("/medical-id/members/<memberId>/record-items/<itemId>/tickets")
def list_item_tickets(memberId, itemId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian", "RecordVerifier", "PlatformAdmin"])
    V.get_member_or_404(memberId)
    _member_child_or_404(db.record_items, itemId, memberId, ERR_RECORD_ITEM_NOT_FOUND)
    V.check_member_scope(uid, role, memberId)
    rows = [t for t in db.tickets.values() if t["record_item_id"] == itemId]
    if "status" in request.args:
        rows = [t for t in rows if t["status"] == request.args["status"]]
    return _list_response(rows)


@app.get("/medical-id/verification-tickets")
def list_tickets():
    uid, role = V.actor()
    V.require_roles(role, ["RecordVerifier", "PlatformAdmin"])
    rows = list(db.tickets.values())
    if "member_id" in request.args:
        rows = [t for t in rows if t["member_id"] == request.args["member_id"]]
    if "record_item_id" in request.args:
        rows = [t for t in rows if t["record_item_id"] == request.args["record_item_id"]]
    if "status" in request.args:
        rows = [t for t in rows if t["status"] == request.args["status"]]
    return _list_response(rows)


@app.get("/medical-id/verification-tickets/<ticketId>")
def get_ticket(ticketId):
    uid, role = V.actor()
    V.require_roles(role, ["RecordVerifier", "PlatformAdmin"])
    t = db.tickets.get(ticketId)
    if t is None:
        raise ApiError(ERR_TICKET_NOT_FOUND, "ticket not found")
    return success_object(t)


@app.post("/medical-id/verification-tickets/<ticketId>/resolve")
def resolve_ticket(ticketId):
    uid, role = V.actor()
    V.require_roles(role, ["RecordVerifier"])
    t = db.tickets.get(ticketId)
    if t is None:
        raise ApiError(ERR_TICKET_NOT_FOUND, "ticket not found")
    body = V.get_json_body()
    V.require_fields(body, ["decision", "decision_note"])
    decision = V.require_enum(body, "decision", ["APPROVE", "REJECT"])
    decision_note = body["decision_note"]
    if not isinstance(decision_note, str) or decision_note == "":
        raise ApiError(ERR_INVALID_REQUEST, "decision_note must be a non-empty string")
    if t["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, "ticket is not OPEN")
    item = db.record_items[t["record_item_id"]]
    member = db.members[t["member_id"]]
    if decision == "APPROVE":
        t["status"] = "APPROVED"
        t["decision_note"] = decision_note
        t["version"] += 1
        t["updated_at"] = S.now_ts()
        item["status"] = "VERIFIED"
        item["version"] += 1
        item["updated_at"] = S.now_ts()
        S.bump_record_revision(member)
        S.bump_member(member)
        S.recompute_cognitive(member)
        S.reanchor_record_update_reminder(member)
        S.resync_pending_sync_orders(member)
        S.append_audit(member["id"], role, uid, "RECORD_VERIFY",
                       {"record_item_id": item["id"], "ticket_id": t["id"]})
    else:
        t["status"] = "REJECTED"
        t["decision_note"] = decision_note
        t["version"] += 1
        t["updated_at"] = S.now_ts()
        item["status"] = "REJECTED"
        item["version"] += 1
        item["updated_at"] = S.now_ts()
        S.append_audit(member["id"], role, uid, "RECORD_REJECT",
                       {"record_item_id": item["id"], "ticket_id": t["id"]})
    return success_object(t)


# ---------------------------------------------------------------------------
# Emergency contacts
# ---------------------------------------------------------------------------

@app.post("/medical-id/members/<memberId>/contacts")
def create_contact(memberId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian"])
    member = V.get_member_or_404(memberId)
    V.check_member_scope(uid, role, memberId)
    V.require_member_active(member)
    body = V.get_json_body()
    V.require_fields(body, ["contact_name", "phone", "priority_rank"])
    contact_name = _req_str(body, "contact_name")
    phone = _req_str(body, "phone")
    rank = _req_int(body, "priority_rank")
    if rank < 1:
        raise ApiError(ERR_INVALID_REQUEST, "priority_rank must be >= 1")
    if any(
        c for c in db.contacts.values()
        if c["member_id"] == memberId and c["status"] == "ACTIVE"
        and c["priority_rank"] == rank
    ):
        raise ApiError(ERR_CONTACT_PRIORITY_CONFLICT, "priority_rank already in use")
    ts = S.now_ts()
    c = {
        "id": S.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "member_id": memberId,
        "contact_name": contact_name,
        "phone": phone,
        "priority_rank": rank,
        "status": "ACTIVE",
    }
    db.contacts[c["id"]] = c
    S.append_audit(memberId, role, uid, "CONTACT_ADD", {"contact_id": c["id"]})
    return success_object(c, 201)


@app.get("/medical-id/members/<memberId>/contacts")
def list_member_contacts(memberId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian", "PlatformAdmin"])
    V.get_member_or_404(memberId)
    V.check_member_scope(uid, role, memberId)
    rows = [c for c in db.contacts.values() if c["member_id"] == memberId]
    if "status" in request.args:
        rows = [c for c in rows if c["status"] == request.args["status"]]
    return _list_response(rows)


@app.get("/medical-id/contacts/<contactId>")
def get_contact(contactId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian", "PlatformAdmin"])
    c = db.contacts.get(contactId)
    if c is None:
        raise ApiError(ERR_CONTACT_NOT_FOUND, "contact not found")
    return success_object(c)


@app.get("/medical-id/contacts")
def list_contacts():
    uid, role = V.actor()
    V.require_roles(role, ["PlatformAdmin"])
    rows = list(db.contacts.values())
    if "member_id" in request.args:
        rows = [c for c in rows if c["member_id"] == request.args["member_id"]]
    if "status" in request.args:
        rows = [c for c in rows if c["status"] == request.args["status"]]
    return _list_response(rows)


@app.post("/medical-id/members/<memberId>/contacts/<contactId>/remove")
def remove_contact(memberId, contactId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian"])
    member = V.get_member_or_404(memberId)
    c = _member_child_or_404(db.contacts, contactId, memberId, ERR_CONTACT_NOT_FOUND)
    V.check_member_scope(uid, role, memberId)
    V.require_member_active(member)
    if c["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "contact is not ACTIVE")
    c["status"] = "REMOVED"
    c["version"] += 1
    c["updated_at"] = S.now_ts()
    S.append_audit(memberId, role, uid, "CONTACT_REMOVE", {"contact_id": c["id"]})
    return success_object(c)


# ---------------------------------------------------------------------------
# Advance directives
# ---------------------------------------------------------------------------

@app.post("/medical-id/members/<memberId>/directives")
def create_directive(memberId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian"])
    member = V.get_member_or_404(memberId)
    V.check_member_scope(uid, role, memberId)
    V.require_member_active(member)
    body = V.get_json_body()
    V.require_fields(body, ["directive_type", "document_ref", "release_scope"])
    directive_type = V.require_enum(body, "directive_type", DIRECTIVE_TYPES)
    document_ref = _req_str(body, "document_ref")
    release_scope = V.require_enum(body, "release_scope", RELEASE_SCOPES)
    ts = S.now_ts()
    d = {
        "id": S.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "member_id": memberId,
        "directive_type": directive_type,
        "document_ref": document_ref,
        "release_scope": release_scope,
        "status": "STORED",
    }
    db.directives[d["id"]] = d
    S.append_audit(memberId, role, uid, "DIRECTIVE_STORE", {"directive_id": d["id"]})
    return success_object(d, 201)


@app.get("/medical-id/members/<memberId>/directives")
def list_member_directives(memberId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian", "PlatformAdmin"])
    V.get_member_or_404(memberId)
    V.check_member_scope(uid, role, memberId)
    rows = [d for d in db.directives.values() if d["member_id"] == memberId]
    if "status" in request.args:
        rows = [d for d in rows if d["status"] == request.args["status"]]
    return _list_response(rows)


@app.get("/medical-id/directives/<directiveId>")
def get_directive(directiveId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian", "PlatformAdmin"])
    d = db.directives.get(directiveId)
    if d is None:
        raise ApiError(ERR_DIRECTIVE_NOT_FOUND, "directive not found")
    return success_object(d)


@app.get("/medical-id/directives")
def list_directives():
    uid, role = V.actor()
    V.require_roles(role, ["PlatformAdmin"])
    rows = list(db.directives.values())
    if "member_id" in request.args:
        rows = [d for d in rows if d["member_id"] == request.args["member_id"]]
    if "status" in request.args:
        rows = [d for d in rows if d["status"] == request.args["status"]]
    return _list_response(rows)


@app.post("/medical-id/members/<memberId>/directives/<directiveId>/revoke")
def revoke_directive(memberId, directiveId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian"])
    member = V.get_member_or_404(memberId)
    d = _member_child_or_404(db.directives, directiveId, memberId, ERR_DIRECTIVE_NOT_FOUND)
    V.check_member_scope(uid, role, memberId)
    V.require_member_active(member)
    if d["status"] == "REVOKED":
        raise ApiError(ERR_INVALID_STATE, "directive is already REVOKED")
    d["status"] = "REVOKED"
    d["version"] += 1
    d["updated_at"] = S.now_ts()
    S.append_audit(memberId, role, uid, "DIRECTIVE_REVOKE", {"directive_id": d["id"]})
    return success_object(d)


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

@app.post("/medical-id/products")
def create_product():
    uid, role = V.actor()
    V.require_roles(role, ["PlatformAdmin"])
    body = V.get_json_body()
    V.require_fields(body, ["product_sku", "product_name", "base_price_cents", "max_engrave_chars"])
    sku = _req_str(body, "product_sku")
    name = _req_str(body, "product_name")
    price = _req_int(body, "base_price_cents")
    max_chars = _req_int(body, "max_engrave_chars")
    if price < 0:
        raise ApiError(ERR_INVALID_REQUEST, "base_price_cents must be >= 0")
    if max_chars < 1:
        raise ApiError(ERR_INVALID_REQUEST, "max_engrave_chars must be >= 1")
    if any(p["product_sku"] == sku for p in db.products.values()):
        raise ApiError(ERR_DUPLICATE_SKU, "product_sku already registered")
    ts = S.now_ts()
    p = {
        "id": S.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "product_sku": sku,
        "product_name": name,
        "base_price_cents": price,
        "max_engrave_chars": max_chars,
    }
    db.products[p["id"]] = p
    return success_object(p, 201)


@app.get("/medical-id/products")
def list_products():
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian", "FulfillmentAgent", "PlatformAdmin"])
    return _list_response(list(db.products.values()))


@app.get("/medical-id/products/<productId>")
def get_product(productId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian", "FulfillmentAgent", "PlatformAdmin"])
    p = db.products.get(productId)
    if p is None:
        raise ApiError(ERR_PRODUCT_NOT_FOUND, "product not found")
    return success_object(p)


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

@app.post("/medical-id/members/<memberId>/orders")
def create_order(memberId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian"])
    member = V.get_member_or_404(memberId)
    V.check_member_scope(uid, role, memberId)
    V.require_member_active(member)
    body = V.get_json_body()
    V.require_fields(body, ["product_id", "engraving_text"])
    product_id = _req_str(body, "product_id")
    engraving_text = body.get("engraving_text")
    if not isinstance(engraving_text, str):
        raise ApiError(ERR_INVALID_REQUEST, "engraving_text must be a string")
    engrave_mode = body.get("engrave_mode", "MANUAL")
    if engrave_mode not in ENGRAVE_MODES:
        raise ApiError(ERR_INVALID_REQUEST, "engrave_mode invalid")
    product = db.products.get(product_id)
    if product is None:
        raise ApiError(ERR_PRODUCT_NOT_FOUND, "product_id does not exist")
    if engrave_mode == "MANUAL" and len(engraving_text) > product["max_engrave_chars"]:
        raise ApiError(ERR_ENGRAVING_OVERFLOW, "engraving_text exceeds max_engrave_chars")
    synced_revision = 0
    if engrave_mode == "SYNC_WITH_RECORD":
        engraving_text = S.generate_engraving_text(member, product)
        synced_revision = member["record_revision"]
    price = S.compute_order_price(member, product, engrave_mode)
    ts = S.now_ts()
    o = {
        "id": S.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "member_id": memberId,
        "product_id": product_id,
        "engraving_text": engraving_text,
        "engrave_mode": engrave_mode,
        "synced_revision": synced_revision,
        "price_cents": price,
        "status": "PENDING",
    }
    db.orders[o["id"]] = o
    return success_object(o, 201)


@app.get("/medical-id/members/<memberId>/orders")
def list_member_orders(memberId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian", "FulfillmentAgent", "PlatformAdmin"])
    V.get_member_or_404(memberId)
    V.check_member_scope(uid, role, memberId)
    rows = [o for o in db.orders.values() if o["member_id"] == memberId]
    if "status" in request.args:
        rows = [o for o in rows if o["status"] == request.args["status"]]
    return _list_response(rows)


@app.get("/medical-id/orders/<orderId>")
def get_order(orderId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian", "FulfillmentAgent", "PlatformAdmin"])
    o = db.orders.get(orderId)
    if o is None:
        raise ApiError(ERR_ORDER_NOT_FOUND, "order not found")
    return success_object(o)


@app.get("/medical-id/orders")
def list_orders():
    uid, role = V.actor()
    V.require_roles(role, ["FulfillmentAgent", "PlatformAdmin"])
    rows = list(db.orders.values())
    if "member_id" in request.args:
        rows = [o for o in rows if o["member_id"] == request.args["member_id"]]
    if "product_id" in request.args:
        rows = [o for o in rows if o["product_id"] == request.args["product_id"]]
    if "status" in request.args:
        rows = [o for o in rows if o["status"] == request.args["status"]]
    return _list_response(rows)


@app.post("/medical-id/members/<memberId>/orders/<orderId>/confirm")
def confirm_order(memberId, orderId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian"])
    member = V.get_member_or_404(memberId)
    o = _member_child_or_404(db.orders, orderId, memberId, ERR_ORDER_NOT_FOUND)
    V.check_member_scope(uid, role, memberId)
    V.require_member_active(member)
    if o["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, "order is not PENDING")
    body = V.get_json_body()
    V.require_occ(body, member)
    product = db.products[o["product_id"]]
    if o["engrave_mode"] == "SYNC_WITH_RECORD":
        o["engraving_text"] = S.generate_engraving_text(member, product)
        o["synced_revision"] = member["record_revision"]
    else:
        if len(o["engraving_text"]) > product["max_engrave_chars"]:
            raise ApiError(ERR_ENGRAVING_OVERFLOW, "engraving_text exceeds max_engrave_chars")
    o["price_cents"] = S.compute_order_price(member, product, o["engrave_mode"])
    if o["engrave_mode"] == "SYNC_WITH_RECORD" and member["membership_tier"] == "LIFETIME":
        member["first_lifetime_sync_order_consumed"] = True
    member["balance_cents"] += o["price_cents"]
    S.bump_member(member)
    o["status"] = "CONFIRMED"
    o["version"] += 1
    o["updated_at"] = S.now_ts()
    S.append_audit(memberId, role, uid, "ORDER_CONFIRM",
                   {"order_id": o["id"], "price_cents": o["price_cents"]})
    return success_object(o)


@app.post("/medical-id/members/<memberId>/orders/<orderId>/engrave")
def engrave_order(memberId, orderId):
    uid, role = V.actor()
    V.require_roles(role, ["FulfillmentAgent"])
    V.get_member_or_404(memberId)
    o = _member_child_or_404(db.orders, orderId, memberId, ERR_ORDER_NOT_FOUND)
    if o["status"] != "CONFIRMED":
        raise ApiError(ERR_INVALID_STATE, "order is not CONFIRMED")
    o["status"] = "ENGRAVED"
    o["version"] += 1
    o["updated_at"] = S.now_ts()
    S.append_audit(memberId, role, uid, "ORDER_ENGRAVE", {"order_id": o["id"]})
    return success_object(o)


@app.post("/medical-id/members/<memberId>/orders/<orderId>/ship")
def ship_order(memberId, orderId):
    uid, role = V.actor()
    V.require_roles(role, ["FulfillmentAgent"])
    member = V.get_member_or_404(memberId)
    o = _member_child_or_404(db.orders, orderId, memberId, ERR_ORDER_NOT_FOUND)
    if o["status"] != "ENGRAVED":
        raise ApiError(ERR_INVALID_STATE, "order is not ENGRAVED")
    o["status"] = "SHIPPED"
    o["version"] += 1
    o["updated_at"] = S.now_ts()
    member["balance_cents"] -= o["price_cents"]
    S.bump_member(member)
    S.append_audit(memberId, role, uid, "ORDER_SHIP", {"order_id": o["id"]})
    return success_object(o)


@app.post("/medical-id/members/<memberId>/orders/<orderId>/cancel")
def cancel_order(memberId, orderId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian"])
    member = V.get_member_or_404(memberId)
    o = _member_child_or_404(db.orders, orderId, memberId, ERR_ORDER_NOT_FOUND)
    V.check_member_scope(uid, role, memberId)
    V.require_member_active(member)
    if o["status"] not in ("PENDING", "CONFIRMED"):
        raise ApiError(ERR_INVALID_STATE, "order cannot be cancelled from this state")
    if o["status"] == "CONFIRMED":
        member["balance_cents"] -= o["price_cents"]
        member["wallet_credit_cents"] += o["price_cents"]
        S.bump_member(member)
    o["status"] = "CANCELLED"
    o["version"] += 1
    o["updated_at"] = S.now_ts()
    S.append_audit(memberId, role, uid, "ORDER_CANCEL", {"order_id": o["id"]})
    return success_object(o)


# ---------------------------------------------------------------------------
# Responders
# ---------------------------------------------------------------------------

@app.post("/medical-id/responders")
def create_responder():
    uid, role = V.actor()
    V.require_roles(role, ["PlatformAdmin"])
    body = V.get_json_body()
    V.require_fields(body, ["agency_name", "credential_code", "access_tier", "expires_on"])
    agency_name = _req_str(body, "agency_name")
    credential_code = _req_str(body, "credential_code")
    access_tier = V.require_enum(body, "access_tier", ACCESS_TIERS)
    expires_on = _req_str(body, "expires_on")
    if not _valid_date(expires_on):
        raise ApiError(ERR_INVALID_REQUEST, "expires_on must be YYYY-MM-DD")
    if any(r["credential_code"] == credential_code for r in db.responders.values()):
        raise ApiError(ERR_DUPLICATE_CREDENTIAL, "credential_code already registered")
    ts = S.now_ts()
    r = {
        "id": S.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "agency_name": agency_name,
        "credential_code": credential_code,
        "access_tier": access_tier,
        "expires_on": expires_on,
        "status": "ACTIVE",
    }
    db.responders[r["id"]] = r
    return success_object(r, 201)


@app.get("/medical-id/responders")
def list_responders():
    uid, role = V.actor()
    V.require_roles(role, ["PlatformAdmin", "HotlineOperator"])
    rows = list(db.responders.values())
    if "status" in request.args:
        rows = [r for r in rows if r["status"] == request.args["status"]]
    if "access_tier" in request.args:
        rows = [r for r in rows if r["access_tier"] == request.args["access_tier"]]
    return _list_response(rows)


@app.get("/medical-id/responders/<responderId>")
def get_responder(responderId):
    uid, role = V.actor()
    V.require_roles(role, ["PlatformAdmin", "HotlineOperator"])
    r = db.responders.get(responderId)
    if r is None:
        raise ApiError(ERR_RESPONDER_NOT_FOUND, "responder not found")
    return success_object(r)


@app.post("/medical-id/responders/<responderId>/revoke")
def revoke_responder(responderId):
    uid, role = V.actor()
    V.require_roles(role, ["PlatformAdmin"])
    r = db.responders.get(responderId)
    if r is None:
        raise ApiError(ERR_RESPONDER_NOT_FOUND, "responder not found")
    if r["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "responder is not ACTIVE")
    r["status"] = "REVOKED"
    r["version"] += 1
    r["updated_at"] = S.now_ts()
    return success_object(r)


# ---------------------------------------------------------------------------
# Access events (emergency access)
# ---------------------------------------------------------------------------

@app.post("/medical-id/access-events")
def create_access_event():
    uid, role = V.actor()
    V.require_roles(role, ["Responder", "HotlineOperator"])
    body = V.get_json_body()
    V.require_fields(body, ["credential_code", "identifier_code", "lookup_method"])
    credential_code = _req_str(body, "credential_code")
    identifier_code = _req_str(body, "identifier_code")
    lookup_method = V.require_enum(body, "lookup_method", LOOKUP_METHODS)
    operator_id = body.get("operator_id")
    # Resolve the member up front so denied attempts can still record member_id.
    member = None
    for m in db.members.values():
        if m["identifier_code"] == identifier_code:
            member = m
            break
    # HOTLINE requires operator_id; IDENTIFIER must carry none.
    if lookup_method == "HOTLINE":
        if not isinstance(operator_id, str) or operator_id == "":
            return _denied_access(uid, role, member["id"] if member else None, None,
                                  lookup_method, None,
                                  ERR_RESPONDER_AUTH_FAILED,
                                  "HOTLINE lookup missing operator_id", 403)
    else:
        if operator_id is not None:
            raise ApiError(ERR_INVALID_REQUEST,
                           "IDENTIFIER lookup must not carry operator_id")
    cred = None
    for r in db.responders.values():
        if r["credential_code"] == credential_code:
            cred = r
            break
    today = S.logical_date()
    if (
        cred is None
        or cred["status"] != "ACTIVE"
        or S.parse_date(cred["expires_on"]) <= today
    ):
        return _denied_access(uid, role, member["id"] if member else None,
                              cred["id"] if cred else None,
                              lookup_method, operator_id,
                              ERR_RESPONDER_AUTH_FAILED,
                              "responder credential invalid or expired", 403)
    if role == "Responder" and uid != cred["id"]:
        return _denied_access(uid, role, member["id"] if member else None, cred["id"],
                              lookup_method, operator_id,
                              ERR_RESPONDER_AUTH_FAILED,
                              "X-User-ID must equal the credential owner id", 403)
    if member is None or member["status"] == "CANCELLED":
        return _denied_access(uid, role, member["id"] if member else None, cred["id"],
                              lookup_method, operator_id,
                              ERR_MEMBER_NOT_DISCLOSABLE,
                              "member not disclosable", 409)
    # GRANTED: compute disclosure scope
    base_scope = {"CONDITIONS", "MEDICATIONS", "ALLERGIES"}
    if cred["access_tier"] == "FULL":
        base_scope = base_scope | {"CONTACTS", "DIRECTIVES"}
    scope = set(base_scope)
    cognitive = member["has_cognitive_condition"]
    if cognitive:
        scope.add("CONTACTS")
        scope.add("DIRECTIVES")
    # DIRECTIVES only actually disclosed if any directive is in-scope
    disclosed_directives = []
    if "DIRECTIVES" in scope:
        for d in db.directives.values():
            if d["member_id"] != member["id"] or d["status"] != "STORED":
                continue
            in_scope = False
            if cred["access_tier"] == "FULL" and d["release_scope"] in (
                "EMERGENCY_AND_CONTACTS", "FULL",
            ):
                in_scope = True
            if cognitive and d["release_scope"] == "EMERGENCY_ONLY":
                in_scope = True
            if cognitive and d["release_scope"] in ("EMERGENCY_AND_CONTACTS", "FULL"):
                in_scope = True
            if in_scope:
                disclosed_directives.append(d)
        if not disclosed_directives:
            scope.discard("DIRECTIVES")
    # is_escalated: union exceeds credential tier alone
    tier_alone = {"CONDITIONS", "MEDICATIONS", "ALLERGIES"}
    if cred["access_tier"] == "FULL":
        tier_alone = tier_alone | {"CONTACTS", "DIRECTIVES"}
    is_escalated = not scope.issubset(tier_alone)
    if cred["access_tier"] == "BASIC" and cognitive:
        is_escalated = True
    ts = S.now_ts()
    ev = {
        "id": S.new_id(),
        "created_at": ts,
        "member_id": member["id"],
        "responder_id": cred["id"],
        "lookup_method": lookup_method,
        "operator_id": operator_id if lookup_method == "HOTLINE" else None,
        "disclosed_scope": sorted(scope),
        "is_escalated": is_escalated,
        "outcome": "GRANTED",
        "reason_code": None,
    }
    db.access_events[ev["id"]] = ev
    for d in disclosed_directives:
        d["status"] = "RELEASED"
        d["version"] += 1
        d["updated_at"] = S.now_ts()
        S.append_audit(member["id"], role, uid, "DIRECTIVE_RELEASE",
                       {"directive_id": d["id"], "access_event_id": ev["id"]})
    S.append_audit(member["id"], role, uid, "ACCESS_GRANT",
                   {"access_event_id": ev["id"], "responder_id": cred["id"]})
    # Rate flag: count GRANTED events for this responder in trailing 24h inclusive.
    now_dt = S.parse_dt(ts)
    window_start = now_dt - timedelta(hours=24)
    count = 0
    for e in db.access_events.values():
        if e["responder_id"] == cred["id"] and e["outcome"] == "GRANTED":
            et = S.parse_dt(e["created_at"])
            if window_start <= et <= now_dt:
                count += 1
    if count > S.DAILY_ACCESS_SOFT_CAP:
        S.append_audit(member["id"], role, uid, "ACCESS_RATE_FLAG",
                       {"access_event_id": ev["id"], "responder_id": cred["id"],
                        "granted_count_24h": count})
    return success_object(ev, 201)


def _denied_access(uid, role, member_id, responder_id, lookup_method, operator_id,
                   reason_code, message, http_status):
    """Log a DENIED access event, then surface the denial as an error response."""
    ts = S.now_ts()
    ev = {
        "id": S.new_id(),
        "created_at": ts,
        "member_id": member_id,
        "responder_id": responder_id,
        "lookup_method": lookup_method,
        "operator_id": operator_id,
        "disclosed_scope": [],
        "is_escalated": False,
        "outcome": "DENIED",
        "reason_code": reason_code,
    }
    db.access_events[ev["id"]] = ev
    return error_response(reason_code, message, http_status)


@app.get("/medical-id/members/<memberId>/access-events")
def list_member_access_events(memberId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian", "PlatformAdmin"])
    V.get_member_or_404(memberId)
    V.check_member_scope(uid, role, memberId)
    rows = [e for e in db.access_events.values() if e["member_id"] == memberId]
    if "outcome" in request.args:
        rows = [e for e in rows if e["outcome"] == request.args["outcome"]]
    return _list_response(rows)


@app.get("/medical-id/access-events/<eventId>")
def get_access_event(eventId):
    uid, role = V.actor()
    V.require_roles(role, ["PlatformAdmin"])
    e = db.access_events.get(eventId)
    if e is None:
        raise ApiError(ERR_MEMBER_NOT_FOUND, "access event not found")
    return success_object(e)


@app.get("/medical-id/access-events")
def list_access_events():
    uid, role = V.actor()
    V.require_roles(role, ["PlatformAdmin"])
    rows = list(db.access_events.values())
    if "responder_id" in request.args:
        rows = [e for e in rows if e["responder_id"] == request.args["responder_id"]]
    if "member_id" in request.args:
        rows = [e for e in rows if e["member_id"] == request.args["member_id"]]
    if "outcome" in request.args:
        rows = [e for e in rows if e["outcome"] == request.args["outcome"]]
    return _list_response(rows)


# ---------------------------------------------------------------------------
# Wandering cases
# ---------------------------------------------------------------------------

@app.post("/medical-id/members/<memberId>/wandering-cases")
def open_wandering_case(memberId):
    uid, role = V.actor()
    V.require_roles(role, ["Guardian", "HotlineOperator"])
    member = V.get_member_or_404(memberId)
    V.check_member_scope(uid, role, memberId)
    V.require_member_active(member)
    body = V.get_json_body()
    opened_via = V.require_enum(body, "opened_via", OPENED_VIAS)
    if not member["has_cognitive_condition"] or any(
        c for c in db.wandering_cases.values()
        if c["member_id"] == memberId and c["status"] == "OPEN"
    ):
        raise ApiError(ERR_WANDERING_NOT_ELIGIBLE, "wandering case not eligible")
    ts = S.now_ts()
    c = {
        "id": S.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "member_id": memberId,
        "opened_via": opened_via,
        "opened_at": ts,
        "resolved_at": None,
        "outcome": None,
        "status": "OPEN",
    }
    db.wandering_cases[c["id"]] = c
    S.append_audit(memberId, role, uid, "WANDERING_OPEN", {"case_id": c["id"]})
    return success_object(c, 201)


@app.get("/medical-id/members/<memberId>/wandering-cases")
def list_member_cases(memberId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian", "HotlineOperator", "PlatformAdmin"])
    V.get_member_or_404(memberId)
    V.check_member_scope(uid, role, memberId)
    rows = [c for c in db.wandering_cases.values() if c["member_id"] == memberId]
    if "status" in request.args:
        rows = [c for c in rows if c["status"] == request.args["status"]]
    return _list_response(rows)


@app.get("/medical-id/wandering-cases")
def list_cases():
    uid, role = V.actor()
    V.require_roles(role, ["PlatformAdmin", "HotlineOperator"])
    rows = list(db.wandering_cases.values())
    if "member_id" in request.args:
        rows = [c for c in rows if c["member_id"] == request.args["member_id"]]
    if "status" in request.args:
        rows = [c for c in rows if c["status"] == request.args["status"]]
    return _list_response(rows)


@app.get("/medical-id/wandering-cases/<caseId>")
def get_case(caseId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian", "HotlineOperator", "PlatformAdmin"])
    c = db.wandering_cases.get(caseId)
    if c is None:
        raise ApiError(ERR_CASE_NOT_FOUND, "wandering case not found")
    return success_object(c)


@app.post("/medical-id/members/<memberId>/wandering-cases/<caseId>/resolve")
def resolve_case(memberId, caseId):
    uid, role = V.actor()
    V.require_roles(role, ["Guardian", "HotlineOperator"])
    V.get_member_or_404(memberId)
    c = _member_child_or_404(db.wandering_cases, caseId, memberId, ERR_CASE_NOT_FOUND)
    V.check_member_scope(uid, role, memberId)
    body = V.get_json_body()
    outcome = V.require_enum(body, "outcome", WANDERING_OUTCOMES)
    if c["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, "case is not OPEN")
    c["status"] = "RESOLVED"
    c["outcome"] = outcome
    c["resolved_at"] = S.now_ts()
    c["version"] += 1
    c["updated_at"] = S.now_ts()
    S.append_audit(memberId, role, uid, "WANDERING_RESOLVE",
                   {"case_id": c["id"], "outcome": outcome})
    return success_object(c)


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------

@app.get("/medical-id/reminders")
def list_reminders():
    uid, role = V.actor()
    V.require_roles(role, ["PlatformAdmin"])
    rows = list(db.reminders.values())
    if "member_id" in request.args:
        rows = [r for r in rows if r["member_id"] == request.args["member_id"]]
    if "reminder_kind" in request.args:
        rows = [r for r in rows if r["reminder_kind"] == request.args["reminder_kind"]]
    if "status" in request.args:
        rows = [r for r in rows if r["status"] == request.args["status"]]
    return _list_response(rows)


@app.get("/medical-id/reminders/<reminderId>")
def get_reminder(reminderId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian", "PlatformAdmin"])
    r = db.reminders.get(reminderId)
    if r is None:
        raise ApiError(ERR_MEMBER_NOT_FOUND, "reminder not found")
    return success_object(r)


@app.get("/medical-id/members/<memberId>/reminders")
def list_member_reminders(memberId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian", "PlatformAdmin"])
    V.get_member_or_404(memberId)
    V.check_member_scope(uid, role, memberId)
    rows = [r for r in db.reminders.values() if r["member_id"] == memberId]
    if "reminder_kind" in request.args:
        rows = [r for r in rows if r["reminder_kind"] == request.args["reminder_kind"]]
    if "status" in request.args:
        rows = [r for r in rows if r["status"] == request.args["status"]]
    return _list_response(rows)


# ---------------------------------------------------------------------------
# Disputes
# ---------------------------------------------------------------------------

@app.post("/medical-id/members/<memberId>/disputes")
def create_dispute(memberId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian"])
    member = V.get_member_or_404(memberId)
    V.check_member_scope(uid, role, memberId)
    V.require_member_active(member)
    body = V.get_json_body()
    V.require_fields(body, ["record_item_id", "claim_text"])
    record_item_id = _req_str(body, "record_item_id")
    claim_text = _req_str(body, "claim_text")
    item = db.record_items.get(record_item_id)
    if (
        item is None
        or item["member_id"] != memberId
        or item["status"] == "SUPERSEDED"
    ):
        raise ApiError(ERR_RECORD_ITEM_NOT_DISPUTABLE, "record item not disputable")
    ts = S.now_ts()
    d = {
        "id": S.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "member_id": memberId,
        "record_item_id": record_item_id,
        "claim_text": claim_text,
        "resolution_note": None,
        "status": "OPEN",
    }
    db.disputes[d["id"]] = d
    S.append_audit(memberId, role, uid, "DISPUTE_OPEN",
                   {"dispute_id": d["id"], "record_item_id": record_item_id})
    return success_object(d, 201)


@app.get("/medical-id/members/<memberId>/disputes")
def list_member_disputes(memberId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian", "RecordVerifier", "PlatformAdmin"])
    V.get_member_or_404(memberId)
    V.check_member_scope(uid, role, memberId)
    rows = [d for d in db.disputes.values() if d["member_id"] == memberId]
    if "status" in request.args:
        rows = [d for d in rows if d["status"] == request.args["status"]]
    return _list_response(rows)


@app.get("/medical-id/disputes")
def list_disputes():
    uid, role = V.actor()
    V.require_roles(role, ["RecordVerifier", "PlatformAdmin"])
    rows = list(db.disputes.values())
    if "member_id" in request.args:
        rows = [d for d in rows if d["member_id"] == request.args["member_id"]]
    if "record_item_id" in request.args:
        rows = [d for d in rows if d["record_item_id"] == request.args["record_item_id"]]
    if "status" in request.args:
        rows = [d for d in rows if d["status"] == request.args["status"]]
    return _list_response(rows)


@app.get("/medical-id/disputes/<disputeId>")
def get_dispute(disputeId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian", "RecordVerifier", "PlatformAdmin"])
    d = db.disputes.get(disputeId)
    if d is None:
        raise ApiError(ERR_DISPUTE_NOT_FOUND, "dispute not found")
    return success_object(d)


@app.post("/medical-id/disputes/<disputeId>/claim-for-review")
def claim_dispute(disputeId):
    uid, role = V.actor()
    V.require_roles(role, ["RecordVerifier"])
    d = db.disputes.get(disputeId)
    if d is None:
        raise ApiError(ERR_DISPUTE_NOT_FOUND, "dispute not found")
    if d["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, "dispute is not OPEN")
    d["status"] = "UNDER_REVIEW"
    d["version"] += 1
    d["updated_at"] = S.now_ts()
    S.append_audit(d["member_id"], role, uid, "DISPUTE_CLAIM", {"dispute_id": d["id"]})
    return success_object(d)


@app.post("/medical-id/disputes/<disputeId>/return-to-queue")
def return_dispute(disputeId):
    uid, role = V.actor()
    V.require_roles(role, ["RecordVerifier"])
    d = db.disputes.get(disputeId)
    if d is None:
        raise ApiError(ERR_DISPUTE_NOT_FOUND, "dispute not found")
    if d["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "dispute is not UNDER_REVIEW")
    d["status"] = "OPEN"
    d["version"] += 1
    d["updated_at"] = S.now_ts()
    S.append_audit(d["member_id"], role, uid, "DISPUTE_RETURN", {"dispute_id": d["id"]})
    return success_object(d)


@app.post("/medical-id/disputes/<disputeId>/resolve")
def resolve_dispute(disputeId):
    uid, role = V.actor()
    V.require_roles(role, ["RecordVerifier"])
    d = db.disputes.get(disputeId)
    if d is None:
        raise ApiError(ERR_DISPUTE_NOT_FOUND, "dispute not found")
    body = V.get_json_body()
    V.require_fields(body, ["resolution", "resolution_note"])
    resolution = V.require_enum(body, "resolution", DISPUTE_RESOLUTIONS)
    note = body["resolution_note"]
    if not isinstance(note, str) or note == "":
        raise ApiError(ERR_INVALID_REQUEST, "resolution_note must be a non-empty string")
    if d["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "dispute is not UNDER_REVIEW")
    d["resolution_note"] = note
    d["status"] = "RESOLVED_UPHELD" if resolution == "UPHELD" else "RESOLVED_CORRECTED"
    d["version"] += 1
    d["updated_at"] = S.now_ts()
    if resolution == "CORRECTED":
        item = db.record_items[d["record_item_id"]]
        member = db.members[d["member_id"]]
        if item["status"] == "VERIFIED":
            _do_supersede(member, item, item["label"], item["detail"],
                          item["provider_document_ref"], role, uid,
                          audit_action="DISPUTE_RESOLVE")
        else:
            S.append_audit(d["member_id"], role, uid, "DISPUTE_RESOLVE",
                           {"dispute_id": d["id"], "resolution": resolution})
    else:
        S.append_audit(d["member_id"], role, uid, "DISPUTE_RESOLVE",
                       {"dispute_id": d["id"], "resolution": resolution})
    return success_object(d)


@app.post("/medical-id/disputes/<disputeId>/dismiss")
def dismiss_dispute(disputeId):
    uid, role = V.actor()
    V.require_roles(role, ["RecordVerifier"])
    d = db.disputes.get(disputeId)
    if d is None:
        raise ApiError(ERR_DISPUTE_NOT_FOUND, "dispute not found")
    if d["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, "dispute is not OPEN")
    d["status"] = "DISMISSED"
    d["version"] += 1
    d["updated_at"] = S.now_ts()
    S.append_audit(d["member_id"], role, uid, "DISPUTE_DISMISS", {"dispute_id": d["id"]})
    return success_object(d)


# ---------------------------------------------------------------------------
# Audit events
# ---------------------------------------------------------------------------

@app.get("/medical-id/audit-events")
def list_audit_events():
    uid, role = V.actor()
    V.require_roles(role, ["PlatformAdmin"])
    rows = list(db.audit_events.values())
    if "member_id" in request.args:
        rows = [e for e in rows if e["member_id"] == request.args["member_id"]]
    if "action" in request.args:
        rows = [e for e in rows if e["action"] == request.args["action"]]
    return _list_response(rows)


@app.get("/medical-id/audit-events/<eventId>")
def get_audit_event(eventId):
    uid, role = V.actor()
    V.require_roles(role, ["PlatformAdmin"])
    e = db.audit_events.get(eventId)
    if e is None:
        raise ApiError(ERR_MEMBER_NOT_FOUND, "audit event not found")
    return success_object(e)


@app.get("/medical-id/members/<memberId>/audit-events")
def list_member_audit(memberId):
    uid, role = V.actor()
    V.require_roles(role, ["Member", "Guardian", "PlatformAdmin"])
    V.get_member_or_404(memberId)
    V.check_member_scope(uid, role, memberId)
    rows = [e for e in db.audit_events.values() if e["member_id"] == memberId]
    if "action" in request.args:
        rows = [e for e in rows if e["action"] == request.args["action"]]
    return _list_response(rows)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
