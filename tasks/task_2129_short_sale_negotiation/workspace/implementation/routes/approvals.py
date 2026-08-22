"""Approval letters, extensions, expiry and closing (PRD §3.9)."""
from decimal import Decimal

from flask import Blueprint

import constants as K
import services as S
import validation as V
from auth import require
from db import db
from envelope import collection, created, enum_filter, str_filter, success
from errors import fail
from serializers import approval_out, extension_out
from timeutil import add_days

bp = Blueprint("approvals", __name__)

APPROVAL_READ_ROLES = (
    K.ROLE_NEGOTIATOR,
    K.ROLE_LISTING_AGENT,
    K.ROLE_SERVICER_ANALYST,
    K.ROLE_PLATFORM_ADMIN,
)
EXTENSION_READ_ROLES = (K.ROLE_NEGOTIATOR, K.ROLE_SERVICER_ANALYST, K.ROLE_PLATFORM_ADMIN)


@bp.post("/short-sale/cases/<case_id>/approval-letters")
def issue_letter(case_id):
    user_id = require(K.ROLE_SERVICER_ANALYST)
    case = S.need_case(case_id)
    data = V.body()

    # rung 6 — body reference existence
    raw_offer = data.get("offer_id")
    if isinstance(raw_offer, str) and raw_offer.strip():
        candidate = db.get("offers", raw_offer)
        if candidate is None or candidate["case_id"] != case["id"]:
            fail("ERR_OFFER_NOT_FOUND", "The offer_id names no offer on this case.")

    # rung 7 — request shape
    offer_id = V.req_string(data, "offer_id")
    approved_net = V.req_int(data, "approved_net_proceeds_cents", minimum=0)
    commission_cap_pct = V.req_decimal(
        data, "commission_cap_pct", minimum=Decimal(0), exclusive_min=True
    )
    relocation = V.req_int(data, "seller_relocation_incentive_cents", minimum=0)
    deficiency_waiver = V.req_enum(data, "deficiency_waiver", K.DEFICIENCY_WAIVERS)
    conditions = V.opt_string_list(data, "conditions", [])
    expected_case_version = V.req_version(data, "expected_case_version")

    offer = db.get("offers", offer_id)
    if offer is None or offer["case_id"] != case["id"]:
        fail("ERR_OFFER_NOT_FOUND", "The offer_id names no offer on this case.")

    # rung 8 — optimistic concurrency on the parent ShortSaleCase
    if expected_case_version != case["version"]:
        fail("ERR_STALE_CASE_VERSION", "The case has moved since it was read.")

    # rung 9 — state admissibility
    S.require_case_actionable(case)
    if offer["status"] != "SUBMITTED":
        fail("ERR_OFFER_NOT_ACTIONABLE", "The named offer is not SUBMITTED.")

    # rung 15 — deficiency-waiver eligibility
    if deficiency_waiver == "WAIVED" and not case["deficiency_waiver_permitted"]:
        fail(
            "ERR_DEFICIENCY_WAIVER_NOT_PERMITTED",
            "This investor does not permit waiving the deficiency.",
        )

    # rung 17 — controlling valuation present
    if case["minimum_acceptable_net_cents"] is None or case["final_value_cents"] is None:
        fail("ERR_CONTROLLING_VALUATION_MISSING", "The case has no controlling valuation.")

    # rung 18 — hardship accepted
    package = S.case_package(case["id"])
    if package is None or package["status"] != "ACCEPTED":
        fail("ERR_HARDSHIP_NOT_ACCEPTED", "The case's hardship package is not accepted.")

    # rung 19 — current final net sheet
    has_current_final = any(
        s["variant"] == "FINAL" and s["status"] == "CURRENT"
        for s in S.offer_net_sheets(offer["id"])
    )
    if not has_current_final:
        fail("ERR_STALE_NET_SHEET", "The offer has no CURRENT net sheet of the FINAL variant.")

    # rung 20 — junior liens resolved
    for lien in S.case_liens(case["id"]):
        if lien["status"] != "APPROVED":
            fail("ERR_JUNIOR_LIEN_UNRESOLVED", "At least one junior lien is unresolved.")

    # rung 21 — MI decided
    claim = S.case_mi_claim(case["id"])
    if claim is not None and claim["status"] not in ("APPROVED", "NOT_REQUIRED"):
        fail("ERR_MI_APPROVAL_PENDING", "The mortgage insurance claim is not decided.")

    # rung 29 — commission cap
    if commission_cap_pct > K.SERVICER_COMMISSION_CAP_PCT:
        fail("ERR_COMMISSION_CAP_EXCEEDED", "The commission cap exceeds the servicer's cap.")

    # rung 30 — net floor
    if approved_net < case["minimum_acceptable_net_cents"]:
        fail("ERR_NET_BELOW_MINIMUM", "The approved net is below the case's minimum acceptable net.")

    issued_at = db.now()
    letter = {
        "id": db.new_id(),
        "case_id": case["id"],
        "offer_id": offer["id"],
        "supersedes_approval_id": None,
        "approved_net_proceeds_cents": approved_net,
        "commission_cap_pct": commission_cap_pct,
        "seller_relocation_incentive_cents": relocation,
        "deficiency_waiver": deficiency_waiver,
        "conditions": conditions,
        "issued_by_user_id": user_id,
        "issued_at": issued_at,
        "closing_deadline": add_days(issued_at, K.APPROVAL_TERM_DAYS),
        "cumulative_extension_days_used": 0,
        "status": "ACTIVE",
    }
    db.insert("approvals", letter)

    offer["status"] = "ACCEPTED"
    if case["negotiation_status"] == "OFFER_UNDER_REVIEW":
        case["negotiation_status"] = "APPROVAL_ACTIVE"
    db.force_touch("cases", case["id"])

    return created(approval_out(letter))


@bp.get("/short-sale/approval-letters/<letter_id>")
def get_letter(letter_id):
    require(*APPROVAL_READ_ROLES)
    letter = S.need_approval(letter_id)
    return success(approval_out(letter))


@bp.get("/short-sale/approval-letters")
def list_letters():
    require(*APPROVAL_READ_ROLES)
    case_id = str_filter("case_id")
    offer_id = str_filter("offer_id")
    supersedes = str_filter("supersedes_approval_id")
    status = enum_filter("status", K.APPROVAL_STATUSES)
    rows = db.all("approvals")
    if case_id is not None:
        rows = [r for r in rows if r["case_id"] == case_id]
    if offer_id is not None:
        rows = [r for r in rows if r["offer_id"] == offer_id]
    if supersedes is not None:
        rows = [r for r in rows if r["supersedes_approval_id"] == supersedes]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return collection(rows, approval_out, sort_key=lambda r: r["_seq"])


@bp.post("/short-sale/approval-letters/<letter_id>/close")
def close_letter(letter_id):
    require(K.ROLE_NEGOTIATOR)
    letter = S.need_approval(letter_id)
    V.body()

    # rung 9 — state admissibility
    if letter["status"] != "ACTIVE":
        fail("ERR_APPROVAL_NOT_ACTIVE", "Only an ACTIVE letter may be closed.")

    # rung 10 — approval-letter currency (lazy expiry)
    S.expire_letter_if_past_deadline(letter)

    letter["status"] = "CLOSED"
    case = db.get("cases", letter["case_id"])
    if case["negotiation_status"] == "APPROVAL_ACTIVE":
        case["negotiation_status"] = "CLOSED"
    listing = S.controlling_listing(case["id"])
    if listing is not None and listing["marketing_status"] in ("ACTIVE", "UNDER_CONTRACT"):
        listing["marketing_status"] = "WITHDRAWN"
        listing["ended_at"] = db.now()

    return success(approval_out(letter))


# ---------------------------------------------------------------------------
# extension requests
# ---------------------------------------------------------------------------
@bp.post("/short-sale/approval-letters/<letter_id>/extension-requests")
def file_extension(letter_id):
    user_id = require(K.ROLE_NEGOTIATOR)
    letter = S.need_approval(letter_id)
    data = V.body()
    requested_days = V.req_int(data, "requested_days", minimum=1)
    reason = V.req_string(data, "reason")

    # rung 9 — state admissibility
    if letter["status"] != "ACTIVE":
        fail("ERR_APPROVAL_NOT_ACTIVE", "Only an ACTIVE letter accepts extension requests.")

    # rung 10 — approval-letter currency (lazy expiry)
    S.expire_letter_if_past_deadline(letter)

    request_row = {
        "id": db.new_id(),
        "approval_letter_id": letter["id"],
        "requested_days": requested_days,
        "reason": reason,
        "requested_by_user_id": user_id,
        "granted_days": None,
        "decided_by_user_id": None,
        "new_closing_deadline": None,
        "status": "REQUESTED",
    }
    db.insert("extensions", request_row)
    return created(extension_out(request_row))


@bp.get("/short-sale/approval-letters/<letter_id>/extension-requests")
def list_extensions(letter_id):
    require(*EXTENSION_READ_ROLES)
    letter = S.need_approval(letter_id)
    status = enum_filter("status", K.EXTENSION_STATUSES)
    rows = S.approval_extensions(letter["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return collection(rows, extension_out, sort_key=lambda r: r["_seq"])


@bp.post("/short-sale/extension-requests/<request_id>/decision")
def decide_extension(request_id):
    user_id = require(K.ROLE_SERVICER_ANALYST)
    request_row = S.need_extension(request_id)
    letter = db.get("approvals", request_row["approval_letter_id"])

    # rung 4 — segregation of duties
    if user_id == letter["issued_by_user_id"]:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The analyst who issued the letter may not decide its extension requests.",
        )

    data = V.body()
    outcome = V.req_enum(data, "outcome", K.EXTENSION_DECISION_OUTCOMES)

    # rung 9 — state admissibility
    if request_row["status"] != "REQUESTED":
        fail("ERR_EXTENSION_NOT_PENDING", "Only a REQUESTED extension may be decided.")
    if letter["status"] != "ACTIVE":
        fail("ERR_APPROVAL_NOT_ACTIVE", "The approval letter is not ACTIVE.")

    # rung 10 — approval-letter currency (lazy expiry)
    S.expire_letter_if_past_deadline(letter)

    request_row["decided_by_user_id"] = user_id

    if outcome == "DENY":
        request_row["granted_days"] = 0
        request_row["status"] = "DENIED"
        return success(extension_out(request_row))

    # rung 31 — extension budget
    granted_days = request_row["requested_days"]
    if letter["cumulative_extension_days_used"] + granted_days > K.MAX_CUMULATIVE_EXTENSION_DAYS:
        fail("ERR_EXTENSION_BUDGET_EXCEEDED", "The chain's extension budget would be exceeded.")

    # CASCADE-C hop 1
    request_row["granted_days"] = granted_days
    successor = S.mint_successor_letter(letter, granted_days)

    # hop 2, caused by hop 1
    letter["status"] = "SUPERSEDED"

    # hop 3, caused by hop 2
    S.cancel_requested_extensions(letter["id"], except_id=request_row["id"])

    request_row["new_closing_deadline"] = successor["closing_deadline"]
    request_row["status"] = "GRANTED"

    return success(extension_out(request_row))
