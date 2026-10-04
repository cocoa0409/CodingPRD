"""Routes: solicitation cases with the three-hop confirm cascade."""
from datetime import timedelta
from flask import Blueprint, request

from db import store, fmt_ts
from errors import not_found, err
from middleware import require_roles
from response import ok, ok_list, paginate
from services import (
    stamp_common, touch, get_body, req_str, clamp,
    recompute_page_aggregates, set_review_state, pub,
    STRIKE_TRUST_PENALTY, STRIKE_ESCALATION, ALERT_COOLDOWN_D,
)
from routes_pages import get_page

bp = Blueprint("cases", __name__)

CASE_ROLES = ("PlatformOps", "TrustInvestigator", "SupportAdmin")


def get_case(case_id):
    c = store.cases.get(case_id)
    if c is None:
        raise not_found("solicitation case not found")
    return c


@bp.post("/platform/business-pages/<pageId>/solicitation-cases")
@require_roles("Reporter")
def create_case(pageId, _actor_id, _actor_role):
    page = get_page(pageId)
    body = get_body()
    targets = body.get("target_review_ids")
    if not isinstance(targets, list) or not targets or len(targets) > 10:
        raise err("ERR_CASE_TARGETS_INVALID",
                  "target_review_ids must contain 1..10 entries")
    if any(not isinstance(t, str) for t in targets):
        raise err("ERR_CASE_TARGETS_INVALID", "targets must be review ids")
    if len(set(targets)) != len(targets):
        raise err("ERR_CASE_TARGETS_INVALID", "targets must be distinct")
    evidence_text = req_str(body, "evidence_text", min_len=20)
    for rid in targets:
        r = store.reviews.get(rid)
        if r is None:
            raise not_found("target review not found")
        if r["page_id"] != pageId or r["recommendation_state"] == "REMOVED":
            raise err("ERR_CASE_TARGETS_INVALID",
                      "targets must be non-REMOVED reviews on this page")
    case = stamp_common({
        "page_id": pageId,
        "reporter_user_id": _actor_id,
        "target_review_ids": list(targets),
        "evidence_text": evidence_text,
        "confirmed_review_count": 0,
        "status": "OPEN",
    })
    store.cases[case["id"]] = case
    return ok(pub(case), status=201)


@bp.get("/platform/solicitation-cases")
@require_roles(*CASE_ROLES)
def list_cases(_actor_id, _actor_role):
    items = list(store.cases.values())
    for f in ("page_id", "reporter_user_id"):
        v = request.args.get(f)
        if v is not None:
            items = [c for c in items if c.get(f) == v]
    items, limit, offset, total = paginate([pub(c) for c in items], request.args)
    return ok_list(items, limit, offset, total)


@bp.get("/platform/solicitation-cases/<caseId>")
@require_roles(*CASE_ROLES)
def get_one_case(caseId, _actor_id, _actor_role):
    return ok(pub(get_case(caseId)))


@bp.post("/platform/solicitation-cases/<caseId>/investigate")
@require_roles("TrustInvestigator")
def investigate(caseId, _actor_id, _actor_role):
    case = get_case(caseId)
    if case["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "case is not OPEN")
    case["status"] = "INVESTIGATING"
    touch(case)
    return ok(pub(case))


@bp.post("/platform/solicitation-cases/<caseId>/confirm")
@require_roles("TrustInvestigator")
def confirm(caseId, _actor_id, _actor_role):
    case = get_case(caseId)
    if case["status"] != "INVESTIGATING":
        raise err("ERR_INVALID_STATE", "case is not INVESTIGATING")
    if case["reporter_user_id"] == _actor_id:
        raise err("ERR_SELF_ACTION",
                  "investigator may not confirm a case they reported")
    # hop 1: mark + remove targets
    affected_pages = set()
    authors = []
    for rid in case["target_review_ids"]:
        r = store.reviews.get(rid)
        if r is None:
            continue
        r["evidence_confirmed"] = True
        set_review_state(r, "REMOVED")
        affected_pages.add(r["page_id"])
        if r["author_user_id"] not in authors:
            authors.append(r["author_user_id"])
    case["confirmed_review_count"] = len(case["target_review_ids"])
    case["status"] = "CONFIRMED"
    touch(case)
    # hop 2: strikes + trust penalty + force-flag cascade
    for aid in authors:
        author = store.users.get(aid)
        if author is None:
            continue
        author["strike_count"] += 1
        author["trust_score"] = clamp(
            author["trust_score"] - STRIKE_TRUST_PENALTY, 0, 100)
        touch(author)
        if author["strike_count"] >= STRIKE_ESCALATION:
            for r in store.reviews.values():
                if (r["author_user_id"] == aid
                        and r["recommendation_state"] != "REMOVED"
                        and r["recommendation_state"] != "FILTERED"):
                    set_review_state(r, "FILTERED")
                    affected_pages.add(r["page_id"])
    for pid in affected_pages:
        page = store.pages.get(pid)
        if page is not None:
            recompute_page_aggregates(page)
            touch(page)
    # hop 3: auto-place consumer alert unless one already active
    page = store.pages[case["page_id"]]
    exists = any(a["page_id"] == page["id"] and a["status"] == "ACTIVE"
                 and a["kind"] == "SOLICITATION_EVIDENCE"
                 for a in store.alerts.values())
    if not exists:
        cooldown = store.now + timedelta(days=ALERT_COOLDOWN_D)
        alert = stamp_common({
            "page_id": page["id"],
            "kind": "SOLICITATION_EVIDENCE",
            "case_id": case["id"],
            "evidence_text": "Auto-placed: solicitation evidence confirmed",
            "review_cooldown_until": fmt_ts(cooldown),
            "lifted_by_admin_id": None,
            "status": "ACTIVE",
            "_cooldown_dt": cooldown,
        })
        store.alerts[alert["id"]] = alert
    return ok(pub(case))


@bp.post("/platform/solicitation-cases/<caseId>/dismiss")
@require_roles("TrustInvestigator")
def dismiss(caseId, _actor_id, _actor_role):
    case = get_case(caseId)
    if case["status"] != "INVESTIGATING":
        raise err("ERR_INVALID_STATE", "case is not INVESTIGATING")
    case["status"] = "DISMISSED"
    touch(case)
    return ok(pub(case))
