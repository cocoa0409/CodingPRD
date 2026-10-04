"""Routes: merge requests with the three-hop merge cascade."""
from flask import Blueprint, request

from db import store
from errors import not_found, err
from middleware import require_roles
from response import ok, ok_list, paginate
from services import (
    stamp_common, touch, get_body, req_str,
    recompute_page_aggregates, pub,
)

bp = Blueprint("merges", __name__)

MERGE_ROLES = ("PlatformOps", "SupportAdmin")


def get_merge(mr_id):
    m = store.merge_requests.get(mr_id)
    if m is None:
        raise not_found("merge request not found")
    return m


def _pending_conflict(dup_id, surv_id, exclude_id=None):
    for m in store.merge_requests.values():
        if m["status"] == "PENDING" and m["id"] != exclude_id:
            if dup_id in (m["duplicate_page_id"], m["survivor_page_id"]) \
                    or surv_id in (m["duplicate_page_id"], m["survivor_page_id"]):
                return True
    return False


@bp.post("/platform/merge-requests")
@require_roles("SupportAdmin")
def create_merge(_actor_id, _actor_role):
    body = get_body()
    dup_id = req_str(body, "duplicate_page_id")
    surv_id = req_str(body, "survivor_page_id")
    reason = req_str(body, "reason", min_len=10)
    dup = store.pages.get(dup_id)
    surv = store.pages.get(surv_id)
    if dup is None or surv is None:
        raise not_found("page not found")
    if dup_id == surv_id:
        raise err("ERR_MERGE_CONFLICT", "duplicate and survivor must differ")
    if dup["status"] != "ACTIVE" or surv["status"] != "ACTIVE":
        raise err("ERR_MERGE_CONFLICT", "both pages must be ACTIVE")
    if _pending_conflict(dup_id, surv_id):
        raise err("ERR_MERGE_CONFLICT",
                  "a PENDING merge already references one of these pages")
    mr = stamp_common({
        "duplicate_page_id": dup_id,
        "survivor_page_id": surv_id,
        "reason": reason,
        "decided_by_admin_id": None,
        "status": "PENDING",
    })
    store.merge_requests[mr["id"]] = mr
    return ok(pub(mr), status=201)


@bp.get("/platform/merge-requests")
@require_roles(*MERGE_ROLES)
def list_merges(_actor_id, _actor_role):
    items = list(store.merge_requests.values())
    for f in ("duplicate_page_id", "survivor_page_id"):
        v = request.args.get(f)
        if v is not None:
            items = [m for m in items if m.get(f) == v]
    items, limit, offset, total = paginate([pub(m) for m in items], request.args)
    return ok_list(items, limit, offset, total)


@bp.get("/platform/merge-requests/<mergeRequestId>")
@require_roles(*MERGE_ROLES)
def get_one_merge(mergeRequestId, _actor_id, _actor_role):
    return ok(pub(get_merge(mergeRequestId)))


@bp.post("/platform/merge-requests/<mergeRequestId>/execute")
@require_roles("SupportAdmin")
def execute_merge(mergeRequestId, _actor_id, _actor_role):
    mr = get_merge(mergeRequestId)
    body = get_body()
    epv = body.get("expected_duplicate_page_version")
    if not isinstance(epv, int) or isinstance(epv, bool):
        raise err("ERR_INVALID_REQUEST",
                  "expected_duplicate_page_version is required")
    if mr["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "merge request is not PENDING")
    dup = store.pages[mr["duplicate_page_id"]]
    surv = store.pages[mr["survivor_page_id"]]
    if epv != dup["version"]:
        raise err("ERR_STALE_VERSION",
                  "expected_duplicate_page_version does not match")
    if mr["duplicate_page_id"] == mr["survivor_page_id"]:
        raise err("ERR_MERGE_CONFLICT", "duplicate and survivor must differ")
    if dup["status"] != "ACTIVE" or surv["status"] != "ACTIVE":
        raise err("ERR_MERGE_CONFLICT", "both pages must be ACTIVE")
    if _pending_conflict(dup["id"], surv["id"], exclude_id=mr["id"]):
        raise err("ERR_MERGE_CONFLICT",
                  "another PENDING merge references one of these pages")
    mr["status"] = "EXECUTED"
    mr["decided_by_admin_id"] = _actor_id
    touch(mr)
    # BusinessPage ACTIVE -> MERGED
    dup["status"] = "MERGED"
    dup["merged_into_id"] = surv["id"]
    touch(dup)
    # hop 1: re-point reviews; recompute aggregates
    for r in store.reviews.values():
        if r["page_id"] == dup["id"]:
            r["page_id"] = surv["id"]
            touch(r)
    dup["displayed_review_count"] = 0
    dup["displayed_rating_avg_x100"] = 0
    recompute_page_aggregates(surv)
    touch(surv)
    # hop 2: close duplicate's ad account + cancel its campaigns
    if dup.get("ad_account_id"):
        acct = store.ad_accounts.get(dup["ad_account_id"])
        if acct is not None and acct["status"] != "CLOSED":
            acct["status"] = "CLOSED"
            touch(acct)
            for camp in store.campaigns.values():
                if (camp["ad_account_id"] == acct["id"]
                        and camp["status"] in ("DRAFT", "ACTIVE", "PAUSED")):
                    camp["status"] = "CANCELLED"
                    touch(camp)
    # hop 3: lift alerts, expire claims, reject other pending merges
    for a in store.alerts.values():
        if a["page_id"] == dup["id"] and a["status"] == "ACTIVE":
            a["status"] = "LIFTED"
            touch(a)
    for c in store.claims.values():
        if c["page_id"] == dup["id"] and c["status"] in ("SUBMITTED", "VERIFIED"):
            c["status"] = "EXPIRED"
            touch(c)
    for m in store.merge_requests.values():
        if m["id"] == mr["id"] or m["status"] != "PENDING":
            continue
        if dup["id"] in (m["duplicate_page_id"], m["survivor_page_id"]) \
                or surv["id"] in (m["duplicate_page_id"], m["survivor_page_id"]):
            m["status"] = "REJECTED"
            touch(m)
    return ok(pub(mr))


@bp.post("/platform/merge-requests/<mergeRequestId>/reject")
@require_roles("SupportAdmin")
def reject_merge(mergeRequestId, _actor_id, _actor_role):
    mr = get_merge(mergeRequestId)
    if mr["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "merge request is not PENDING")
    mr["status"] = "REJECTED"
    mr["decided_by_admin_id"] = _actor_id
    touch(mr)
    return ok(pub(mr))
