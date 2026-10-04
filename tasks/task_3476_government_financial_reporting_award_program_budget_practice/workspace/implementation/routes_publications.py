"""Best-practice publications and member comments (PRD 3.8).

Committee drafting loop: DRAFTING -> MEMBER_COMMENT -> RESOLUTION, with
RESOLUTION -> DRAFTING revise loop and RESOLUTION -> PUBLISHED under the
chair alone (OCC on publication version; segregation of duties bars the chair
from publishing a draft they created).
"""

from clock import clock, parse_iso
from envelope import ok
from errors import api_error
from auth import authenticate, authorize
from listing import list_response
from serialize import member_comment, publication
from store import store, new_id, touch
from validate import (
    RESOLUTIONS,
    get_body,
    opt_str,
    pagination,
    query_filter,
    req_datetime,
    req_int,
    req_str,
    req_str_list,
)


def _now():
    return clock.now_iso()


def create_publication():
    uid, role = authenticate()
    body = get_body()
    committee_name = req_str(body, "committee_name")
    chair_member_id = req_str(body, "chair_member_id")
    member_ids = req_str_list(body, "member_ids")
    title = req_str(body, "title")
    topic_code = req_str(body, "topic_code")
    pinned_standard = opt_str(body, "pinned_standards_reference_id", None)
    authorize(role, ["CommitteeMember"])
    # body FKs (PRD 2.7): chair_member_id together with member_ids, then the
    # pinned standard
    if chair_member_id not in store.members:
        raise api_error("ERR_MEMBER_NOT_FOUND", "chair member not found")
    for mid in member_ids:
        if mid not in store.members:
            raise api_error("ERR_MEMBER_NOT_FOUND", "committee member not found")
    if pinned_standard is not None and pinned_standard not in store.standards_references:
        raise api_error("ERR_STANDARD_NOT_FOUND", "pinned standards reference not found")
    # structural (10): creator and chair must both sit on the committee
    if uid not in member_ids or chair_member_id not in member_ids:
        raise api_error(
            "ERR_CHAIR_NOT_ON_COMMITTEE",
            "creator and chair_member_id must both be elements of member_ids",
        )
    now = _now()
    p = {
        "id": new_id(),
        "committee_name": committee_name,
        "chair_member_id": chair_member_id,
        "member_ids": member_ids,
        "created_by_member_id": uid,
        "title": title,
        "topic_code": topic_code,
        "pinned_standards_reference_id": pinned_standard,
        "comment_window_opens_at": None,
        "comment_window_closes_at": None,
        "draft_number": 1,
        "status": "DRAFTING",
        "published_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.publications[p["id"]] = p
    return ok(publication(p), 201)


def _get_publication(publication_id):
    p = store.publications.get(publication_id)
    if p is None:
        raise api_error("ERR_PUBLICATION_NOT_FOUND", "publication not found")
    return p


def _require_committee(p, uid):
    if uid not in p["member_ids"]:
        raise api_error("ERR_NOT_RESOURCE_OWNER", "caller is not on this publication's committee")


def open_comment_period(publication_id):
    uid, role = authenticate()
    body = get_body()
    # closes_at > now is a request-shape check (PRD 2.6 priority 2)
    closes_at = req_datetime(body, "closes_at")
    if parse_iso(closes_at) <= clock.now():
        raise api_error("ERR_VALIDATION", "closes_at must lie after the current logical time")
    authorize(role, ["CommitteeMember"])
    p = _get_publication(publication_id)
    _require_committee(p, uid)
    if p["status"] != "DRAFTING":
        raise api_error("ERR_PUBLICATION_STATE_INVALID", "open-comment-period requires DRAFTING")
    now = _now()
    p["comment_window_opens_at"] = now
    p["comment_window_closes_at"] = closes_at
    p["status"] = "MEMBER_COMMENT"
    touch(p, now)
    return ok(publication(p))


def close_comment_period(publication_id):
    uid, role = authenticate()
    get_body()
    authorize(role, ["CommitteeMember"])
    p = _get_publication(publication_id)
    _require_committee(p, uid)
    if p["status"] != "MEMBER_COMMENT":
        raise api_error("ERR_PUBLICATION_STATE_INVALID", "close-comment-period requires MEMBER_COMMENT")
    if clock.now() < parse_iso(p["comment_window_closes_at"]):
        raise api_error("ERR_COMMENT_WINDOW_STILL_OPEN", "the comment window has not yet closed")
    now = _now()
    p["status"] = "RESOLUTION"
    touch(p, now)
    return ok(publication(p))


def revise_publication(publication_id):
    uid, role = authenticate()
    get_body()
    authorize(role, ["CommitteeMember"])
    p = _get_publication(publication_id)
    _require_committee(p, uid)
    if p["status"] != "RESOLUTION":
        raise api_error("ERR_PUBLICATION_STATE_INVALID", "revise requires RESOLUTION")
    now = _now()
    p["status"] = "DRAFTING"
    p["draft_number"] += 1
    p["comment_window_opens_at"] = None
    p["comment_window_closes_at"] = None
    touch(p, now)
    return ok(publication(p))


def publish_publication(publication_id):
    uid, role = authenticate()
    body = get_body()
    expected_version = req_int(body, "expected_publication_version")
    authorize(role, ["CommitteeMember"])
    p = _get_publication(publication_id)
    # ownership (5): the chair alone publishes
    if uid != p["chair_member_id"]:
        raise api_error("ERR_NOT_RESOURCE_OWNER", "only the committee chair may publish")
    # state gates (6): RESOLUTION, then OCC on the publication version
    if p["status"] != "RESOLUTION":
        raise api_error("ERR_PUBLICATION_STATE_INVALID", "publish requires RESOLUTION")
    if expected_version != p["version"]:
        raise api_error(
            "ERR_STALE_PUBLICATION_VERSION",
            "expected_publication_version does not match the publication's current version",
        )
    # segregation of duties (7): chair may not publish a draft they created
    if p["chair_member_id"] == p["created_by_member_id"]:
        raise api_error(
            "ERR_SELF_APPROVAL_FORBIDDEN",
            "the chair may not publish a publication they created",
        )
    # pin integrity (8)
    pinned = p["pinned_standards_reference_id"]
    if pinned is not None:
        standard = store.standards_references.get(pinned)
        if standard is not None and standard["status"] == "SUPERSEDED":
            raise api_error(
                "ERR_PINNED_STANDARD_SUPERSEDED",
                "the pinned standards reference has been superseded",
            )
    # structural (10): every comment resolved
    pending = sum(
        1
        for c in store.member_comments.values()
        if c["publication_id"] == p["id"] and c["resolution"] == "PENDING"
    )
    if pending > 0:
        raise api_error("ERR_UNRESOLVED_COMMENTS", "pending comments remain unresolved")
    now = _now()
    p["status"] = "PUBLISHED"
    p["published_at"] = now
    touch(p, now)
    return ok(publication(p))


def create_comment():
    uid, role = authenticate()
    body = get_body()
    publication_id = req_str(body, "publication_id")
    text = req_str(body, "body")
    authorize(role, ["Member"])
    p = store.publications.get(publication_id)
    if p is None:
        raise api_error("ERR_PUBLICATION_NOT_FOUND", "publication not found")
    # state gate (6) before the temporal gate (9)
    if p["status"] != "MEMBER_COMMENT":
        raise api_error("ERR_PUBLICATION_STATE_INVALID", "comments require MEMBER_COMMENT")
    if clock.now() >= parse_iso(p["comment_window_closes_at"]):
        raise api_error("ERR_COMMENT_WINDOW_CLOSED", "the comment window has closed")
    now = _now()
    c = {
        "id": new_id(),
        "publication_id": p["id"],
        "member_id": uid,
        "body": text,
        "resolution": "PENDING",
        "resolution_note": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.member_comments[c["id"]] = c
    touch(p, now)  # pending_comment_count += 1 (derived); publication mutates
    return ok(member_comment(c), 201)


def resolve_comment(comment_id):
    uid, role = authenticate()
    body = get_body()
    resolution = req_str(body, "resolution")
    if resolution not in RESOLUTIONS:
        raise api_error("ERR_VALIDATION", "resolution must be ACCEPTED, REVISED or REJECTED")
    resolution_note = opt_str(body, "resolution_note", None)
    authorize(role, ["CommitteeMember"])
    c = store.member_comments.get(comment_id)
    if c is None:
        raise api_error("ERR_COMMENT_NOT_FOUND", "member comment not found")
    p = store.publications[c["publication_id"]]
    _require_committee(p, uid)
    # state gates (6): publication in RESOLUTION, then comment still PENDING
    if p["status"] != "RESOLUTION":
        raise api_error("ERR_PUBLICATION_STATE_INVALID", "resolve requires the publication in RESOLUTION")
    if c["resolution"] != "PENDING":
        raise api_error("ERR_COMMENT_ALREADY_RESOLVED", "the comment is not PENDING")
    now = _now()
    c["resolution"] = resolution
    c["resolution_note"] = resolution_note
    touch(c, now)
    touch(p, now)  # pending -= 1 / resolved += 1 (derived); publication mutates
    return ok(member_comment(c))


def get_comment(comment_id):
    uid, role = authenticate()
    authorize(role, ["PlatformAdmin", "CommitteeMember", "Member"])
    c = store.member_comments.get(comment_id)
    if c is None:
        raise api_error("ERR_COMMENT_NOT_FOUND", "member comment not found")
    return ok(member_comment(c))


def list_comments():
    uid, role = authenticate()
    authorize(role, ["PlatformAdmin", "CommitteeMember", "Member"])
    limit, offset = pagination()
    rows = list(store.member_comments.values())
    publication_id = query_filter("publication_id")
    if publication_id is not None:
        rows = [c for c in rows if c["publication_id"] == publication_id]
    member_id = query_filter("member_id")
    if member_id is not None:
        rows = [c for c in rows if c["member_id"] == member_id]
    resolution = query_filter("resolution")
    if resolution is not None:
        rows = [c for c in rows if c["resolution"] == resolution]
    return list_response(rows, member_comment, limit, offset)


def register(app):
    app.add_url_rule("/gfoa/publications", "create_publication", create_publication, methods=["POST"])
    app.add_url_rule("/gfoa/publications/<publication_id>/open-comment-period", "open_comment_period", open_comment_period, methods=["POST"])
    app.add_url_rule("/gfoa/publications/<publication_id>/close-comment-period", "close_comment_period", close_comment_period, methods=["POST"])
    app.add_url_rule("/gfoa/publications/<publication_id>/revise", "revise_publication", revise_publication, methods=["POST"])
    app.add_url_rule("/gfoa/publications/<publication_id>/publish", "publish_publication", publish_publication, methods=["POST"])
    app.add_url_rule("/gfoa/member-comments", "create_comment", create_comment, methods=["POST"])
    app.add_url_rule("/gfoa/member-comments/<comment_id>/resolve", "resolve_comment", resolve_comment, methods=["POST"])
    app.add_url_rule("/gfoa/member-comments/<comment_id>", "get_comment", get_comment, methods=["GET"])
    app.add_url_rule("/gfoa/member-comments", "list_comments", list_comments, methods=["GET"])
