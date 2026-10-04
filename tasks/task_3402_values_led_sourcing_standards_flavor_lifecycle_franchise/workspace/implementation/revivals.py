"""Fan-driven flavor revival requests (PRD section 3.6).

Create gates run in order: flavor must be RETIRED, then the current logical
time must be no later than retired_at + 730 days (window inclusive). Signing
enforces one signature per email per request; reaching exactly 500 total
signatures qualifies the request (threshold inclusive). Adoption is reserved
to the independent board and moves the flavor RETIRED -> REVIVED.
"""
from datetime import timedelta

from flask import Blueprint, request

from auth import authenticate, authorize
from db import LOGICAL_CLOCK, STORE, new_resource, public, sorted_items, touch
from envelope import ok, ok_list, pagination_args
from errors import fail
from flavors import get_flavor
from timeutil import fmt_dt, parse_iso
from validate import get_body, opt_int, req_str

bp = Blueprint("revivals", __name__)

REVIVAL_SIGNATURE_THRESHOLD = 500
REVIVAL_WINDOW_DAYS = 730


def get_revival(rid):
    r = STORE["revival_requests"].get(rid)
    if r is None:
        fail("ERR_REVIVAL_REQUEST_NOT_FOUND",
             "RevivalRequest id does not exist")
    return r


@bp.post("/flavors/<fid>/revival-requests")
def create_revival(fid):
    _, role = authenticate()
    authorize(role, ("Fan",))
    flavor = get_flavor(fid)
    body = get_body()
    fan_email = req_str(body, "fan_email")
    title = req_str(body, "title")
    if flavor["status"] != "RETIRED":
        fail("ERR_FLAVOR_NOT_RETIRED",
             "Revival requests require a RETIRED flavor")
    retired_at = parse_iso(flavor["retired_at"])
    if LOGICAL_CLOCK["now"] > retired_at + timedelta(days=REVIVAL_WINDOW_DAYS):
        fail("ERR_REVIVAL_WINDOW_EXPIRED",
             "The revival window (730 days from retirement) has passed")
    r = new_resource()
    r.update({
        "flavor_id": fid,
        "fan_email": fan_email,
        "title": title,
        "signature_count": 0,
        "signer_emails": [],
        "status": "OPEN",
        "qualified_at": None,
    })
    STORE["revival_requests"][r["id"]] = r
    return ok(public(r), 201)


@bp.get("/flavors/<fid>/revival-requests")
def list_revivals(fid):
    _, role = authenticate()
    authorize(role, ("Fan", "FlavorManager", "IndependentBoardMember"))
    get_flavor(fid)
    status = request.args.get("status")
    items = [r for r in STORE["revival_requests"].values()
             if r["flavor_id"] == fid]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = [public(r) for r in sorted_items(items)]
    limit, offset = pagination_args()
    return ok_list(items, limit, offset)


@bp.post("/revival-requests/<rid>/sign")
def sign_revival(rid):
    _, role = authenticate()
    authorize(role, ("Fan",))
    r = get_revival(rid)
    body = get_body()
    fan_email = req_str(body, "fan_email")
    count = opt_int(body, "count", 1, 1)
    if r["status"] != "OPEN":
        fail("ERR_INVALID_STATE",
             "Only an OPEN revival request can be signed")
    if fan_email in r["signer_emails"]:
        fail("ERR_DUPLICATE_SIGNATURE",
             "This email has already signed the revival request")
    r["signer_emails"].append(fan_email)
    r["signature_count"] += count
    if r["signature_count"] >= REVIVAL_SIGNATURE_THRESHOLD:
        r["status"] = "QUALIFIED"
        r["qualified_at"] = fmt_dt(LOGICAL_CLOCK["now"])
    touch(r)
    return ok(public(r))


@bp.post("/revival-requests/<rid>/adopt")
def adopt_revival(rid):
    _, role = authenticate()
    authorize(role, ("IndependentBoardMember",))
    r = get_revival(rid)
    if r["status"] != "QUALIFIED":
        fail("ERR_INVALID_STATE",
             "Only a QUALIFIED revival request can be adopted")
    r["status"] = "ADOPTED"
    touch(r)
    flavor = STORE["flavors"].get(r["flavor_id"])
    if flavor is not None and flavor["status"] == "RETIRED":
        flavor["status"] = "REVIVED"
        touch(flavor)
    return ok(public(r))


@bp.post("/revival-requests/<rid>/decline")
def decline_revival(rid):
    _, role = authenticate()
    authorize(role, ("IndependentBoardMember",))
    r = get_revival(rid)
    if r["status"] not in ("OPEN", "QUALIFIED"):
        fail("ERR_INVALID_STATE",
             "Only an OPEN or QUALIFIED revival request can be declined")
    r["status"] = "DECLINED"
    touch(r)
    return ok(public(r))
