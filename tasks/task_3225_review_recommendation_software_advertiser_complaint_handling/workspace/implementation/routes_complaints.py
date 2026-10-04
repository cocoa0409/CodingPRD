"""Routes: complaints (file, start-review, escalate, resolve, reject)."""
from flask import Blueprint, request

from db import store
from errors import not_found, err
from middleware import require_roles
from response import ok, ok_list, paginate
from services import (
    stamp_common, touch, get_body, req_str, req_enum, clamp,
    recompute_page_aggregates, set_review_state, pub,
    REMOVAL_TRUST_PENALTY,
)
from routes_pages import get_page

bp = Blueprint("complaints", __name__)

COMPLAINT_ROLES = ("PlatformOps", "ContentModerator", "SupportAdmin", "BusinessOwner")
COMPLAINT_KINDS = ("FILTERED_DISPUTE", "NEGATIVE_DISPUTE", "SOLICITATION_REPORT")
OPEN_STATES = ("OPEN", "UNDER_REVIEW", "ESCALATED")
DECIDABLE = ("UNDER_REVIEW", "ESCALATED")


def get_complaint(complaint_id):
    c = store.complaints.get(complaint_id)
    if c is None:
        raise not_found("complaint not found")
    return c


@bp.post("/platform/business-pages/<pageId>/complaints")
@require_roles("BusinessOwner")
def create_complaint(pageId, _actor_id, _actor_role):
    page = get_page(pageId)
    body = get_body()
    review_id = req_str(body, "review_id")
    kind = req_enum(body, "kind", COMPLAINT_KINDS)
    text = req_str(body, "body", min_len=10)
    review = store.reviews.get(review_id)
    if review is None:
        raise not_found("review not found")
    if page["claimed_by_user_id"] != _actor_id:
        raise err("ERR_COMPLAINT_CONFLICT",
                  "only the page's claimed owner may file a complaint")
    if review["page_id"] != pageId:
        raise err("ERR_COMPLAINT_CONFLICT", "review is not on this page")
    if kind == "FILTERED_DISPUTE" and review["recommendation_state"] != "FILTERED":
        raise err("ERR_COMPLAINT_CONFLICT",
                  "FILTERED_DISPUTE requires a FILTERED review")
    for c in store.complaints.values():
        if c["review_id"] == review_id and c["status"] in OPEN_STATES:
            raise err("ERR_COMPLAINT_CONFLICT",
                      "an open complaint already exists on this review")
    comp = stamp_common({
        "page_id": pageId,
        "review_id": review_id,
        "filer_user_id": _actor_id,
        "kind": kind,
        "body": text,
        "escalated": False,
        "decided_by_admin_id": None,
        "status": "OPEN",
    })
    store.complaints[comp["id"]] = comp
    return ok(pub(comp), status=201)


@bp.get("/platform/complaints")
@require_roles(*COMPLAINT_ROLES)
def list_complaints(_actor_id, _actor_role):
    items = list(store.complaints.values())
    for f in ("page_id", "review_id", "filer_user_id"):
        v = request.args.get(f)
        if v is not None:
            items = [c for c in items if c.get(f) == v]
    items, limit, offset, total = paginate([pub(c) for c in items], request.args)
    return ok_list(items, limit, offset, total)


@bp.get("/platform/complaints/<complaintId>")
@require_roles(*COMPLAINT_ROLES)
def get_one_complaint(complaintId, _actor_id, _actor_role):
    return ok(pub(get_complaint(complaintId)))


@bp.post("/platform/complaints/<complaintId>/start-review")
@require_roles("ContentModerator")
def start_review(complaintId, _actor_id, _actor_role):
    comp = get_complaint(complaintId)
    if comp["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "complaint is not OPEN")
    if comp["filer_user_id"] == _actor_id:
        raise err("ERR_SELF_ACTION",
                  "moderator may not review a complaint they filed")
    comp["status"] = "UNDER_REVIEW"
    touch(comp)
    return ok(pub(comp))


@bp.post("/platform/complaints/<complaintId>/escalate")
@require_roles("ContentModerator")
def escalate(complaintId, _actor_id, _actor_role):
    comp = get_complaint(complaintId)
    if comp["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "complaint is not UNDER_REVIEW")
    comp["status"] = "ESCALATED"
    comp["escalated"] = True
    touch(comp)
    return ok(pub(comp))


@bp.post("/platform/complaints/<complaintId>/resolve")
@require_roles("ContentModerator")
def resolve(complaintId, _actor_id, _actor_role):
    comp = get_complaint(complaintId)
    body = get_body()
    action = req_enum(body, "action",
                      ("UPHOLD_FILTER", "RESTORE_REVIEW", "REMOVE_REVIEW"))
    if comp["status"] not in DECIDABLE:
        raise err("ERR_INVALID_STATE",
                  "complaint is not in a decidable state")
    review = store.reviews.get(comp["review_id"])
    page = store.pages.get(comp["page_id"])
    if action == "UPHOLD_FILTER":
        if (comp["kind"] == "FILTERED_DISPUTE"
                and review["recommendation_state"] != "FILTERED"):
            raise err("ERR_REVIEW_STATE_CHANGED",
                      "review is no longer FILTERED")
        comp["status"] = "RESOLVED_UPHELD"
    elif action == "RESTORE_REVIEW":
        # PRD §3.3: "Any transition that would place an evidence-confirmed
        # review into DISPLAYED — whether via re-evaluation or via complaint
        # resolution — is rejected with ERR_REVIEW_EVIDENCE_LOCKED (HTTP 409)."
        # Since the only pathway that sets evidence_confirmed also moves the
        # review to REMOVED, the evidence check must precede the FILTERED
        # state check or the PRD's "via complaint resolution" clause would be
        # unreachable.
        if review["evidence_confirmed"]:
            raise err("ERR_REVIEW_EVIDENCE_LOCKED",
                      "evidence-confirmed review cannot be restored")
        if review["recommendation_state"] != "FILTERED":
            raise err("ERR_INVALID_STATE", "review is not FILTERED")
        set_review_state(review, "DISPLAYED")
        comp["status"] = "RESOLVED_ACTIONED"
    else:  # REMOVE_REVIEW
        if review["recommendation_state"] == "REMOVED":
            raise err("ERR_INVALID_STATE", "review is already REMOVED")
        set_review_state(review, "REMOVED")
        author = store.users.get(review["author_user_id"])
        if author is not None:
            author["trust_score"] = clamp(
                author["trust_score"] - REMOVAL_TRUST_PENALTY, 0, 100)
            touch(author)
        comp["status"] = "RESOLVED_ACTIONED"
    comp["decided_by_admin_id"] = _actor_id
    touch(comp)
    return ok(pub(comp))


@bp.post("/platform/complaints/<complaintId>/reject")
@require_roles("ContentModerator")
def reject_complaint(complaintId, _actor_id, _actor_role):
    comp = get_complaint(complaintId)
    if comp["status"] not in DECIDABLE:
        raise err("ERR_INVALID_STATE",
                  "complaint is not in a decidable state")
    comp["status"] = "REJECTED"
    comp["decided_by_admin_id"] = _actor_id
    touch(comp)
    return ok(pub(comp))
