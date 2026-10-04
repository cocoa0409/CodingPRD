"""SuspensionCase endpoints: appeal lifecycle with segregation of duties."""
from flask import Blueprint, request

import clock
import domain
import store
from errors import raise_err
from response import envelope, require_roles, body, paginate
from validation import require_fields, get_or_404

bp = Blueprint("cases", __name__)

READ_ROLES_FULL = {"PlatformAdmin", "PolicyAnalyst", "Moderator"}
READ_ROLES_OWNER = {"PlatformAdmin", "PolicyAnalyst", "Moderator", "BusinessOwner"}


@bp.get("/v1/suspension-cases")
def list_cases():
    require_roles(READ_ROLES_FULL)
    items = list(store.cases.values())
    for f in ("listing_id", "status", "violation_type"):
        v = request.args.get(f)
        if v is not None:
            items = [c for c in items if c.get(f) == v]
    page, pg = paginate(items, request.args)
    return envelope([domain.case_view(c) for c in page],
                    response_type="array", pagination=pg)


@bp.get("/v1/suspension-cases/<cid>")
def get_case(cid):
    require_roles(READ_ROLES_OWNER)
    c = get_or_404(store.cases, cid)
    return envelope(domain.case_view(c))


@bp.post("/v1/suspension-cases/<cid>/appeal")
def appeal(cid):
    role, uid = require_roles({"BusinessOwner"})
    case = get_or_404(store.cases, cid)
    data = body()
    l = store.listings.get(case["listing_id"])
    if case["status"] != "OPEN":
        raise_err("ERR_INVALID_STATE", "case not OPEN")
    if l is None or l.get("owner_contributor_id") != uid:
        raise_err("ERR_NOT_LISTING_OWNER", "only the listing owner may appeal")
    now = clock.now()
    if now > clock.parse(case["appeal_deadline"]):
        raise_err("ERR_APPEAL_WINDOW_CLOSED", "appeal window closed")
    text = data.get("appeal_text")
    if not isinstance(text, str) or len(text) < 50:
        raise_err("ERR_INVALID_REQUEST", "appeal_text must be at least 50 characters")
    case["appeal_text"] = text
    case["status"] = "APPEAL_SUBMITTED"
    domain.touch(case)
    return envelope(domain.case_view(case))


@bp.post("/v1/suspension-cases/<cid>/start-appeal-review")
def start_appeal_review(cid):
    role, uid = require_roles({"PolicyAnalyst"})
    case = get_or_404(store.cases, cid)
    if case["status"] != "APPEAL_SUBMITTED":
        raise_err("ERR_INVALID_STATE", "case not APPEAL_SUBMITTED")
    if case.get("suspended_by") == uid:
        raise_err("ERR_SEGREGATION_OF_DUTIES",
                  "suspending analyst cannot review the appeal")
    case["status"] = "UNDER_APPEAL_REVIEW"
    case["decided_by"] = uid
    domain.touch(case)
    return envelope(domain.case_view(case))


@bp.post("/v1/suspension-cases/<cid>/decide")
def decide(cid):
    role, uid = require_roles({"PolicyAnalyst"})
    case = get_or_404(store.cases, cid)
    data = body()
    require_fields(data, ["decision"])
    decision = data["decision"]
    if decision not in ("UPHELD", "OVERTURNED"):
        raise_err("ERR_INVALID_REQUEST", "decision must be UPHELD or OVERTURNED")
    if case["status"] != "UNDER_APPEAL_REVIEW":
        raise_err("ERR_INVALID_STATE", "case not UNDER_APPEAL_REVIEW")
    if case.get("decided_by") != uid:
        raise_err("ERR_NOT_TICKET_OWNER", "only the reviewing analyst may decide")

    l = store.listings.get(case["listing_id"])
    case["status"] = decision
    domain.touch(case)

    if decision == "UPHELD":
        l["status"] = "PERMANENTLY_CLOSED"
        domain.recompute_listing(l)
        domain.touch(l)
        owner = store.contributors.get(l.get("owner_contributor_id"))
        if owner is not None:
            domain.recompute_contributor(owner, demote=True)
    else:  # OVERTURNED
        now = clock.now()
        pre = l.get("_pre_suspension_status", "VERIFIED")
        if pre in ("VERIFIED", "REVERIFY_REQUIRED"):
            if l.get("reverify_due_at") and clock.parse(l["reverify_due_at"]) <= now:
                l["status"] = "REVERIFY_REQUIRED"
            else:
                l["status"] = "VERIFIED"
        else:
            l["status"] = "CLAIM_PENDING"
        if case["violation_type"] == "KEYWORD_STUFFING":
            l["keyword_stuffing_strikes"] = 0
        domain.recompute_listing(l)
        domain.touch(l)
        owner = store.contributors.get(l.get("owner_contributor_id"))
        if owner is not None:
            domain.recompute_contributor(owner, demote=True)
    return envelope(domain.case_view(case))
