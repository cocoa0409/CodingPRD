"""Junior liens and the mortgage-insurance claim (PRD §3.7)."""
from decimal import Decimal

from flask import Blueprint

import constants as K
import services as S
import validation as V
from auth import require
from db import db
from envelope import collection, created, enum_filter, success
from errors import fail
from serializers import lien_out, mi_claim_out

bp = Blueprint("liens_mi", __name__)

LIEN_READ_ROLES = (
    K.ROLE_NEGOTIATOR,
    K.ROLE_SERVICER_ANALYST,
    K.ROLE_JUNIOR_LIEN_HOLDER,
    K.ROLE_PLATFORM_ADMIN,
)
MI_READ_ROLES = (
    K.ROLE_NEGOTIATOR,
    K.ROLE_SERVICER_ANALYST,
    K.ROLE_MI_UNDERWRITER,
    K.ROLE_PLATFORM_ADMIN,
)

# outcome -> the lien statuses it is declared from
LIEN_TRANSITIONS = {
    "NEGOTIATE": ("DEMAND_SENT",),
    "APPROVE": ("DEMAND_SENT", "NEGOTIATING"),
    "REFUSE": ("DEMAND_SENT", "NEGOTIATING"),
    "WITHDRAW_APPROVAL": ("APPROVED",),
}


# ---------------------------------------------------------------------------
# junior liens
# ---------------------------------------------------------------------------
@bp.post("/short-sale/cases/<case_id>/junior-liens")
def create_lien(case_id):
    require(K.ROLE_NEGOTIATOR)
    case = S.need_case(case_id)
    data = V.body()
    lien = {
        "id": db.new_id(),
        "case_id": case["id"],
        "lien_position": V.req_int(data, "lien_position", minimum=2),
        "holder_name": V.req_string(data, "holder_name"),
        "holder_user_id": V.req_string(data, "holder_user_id"),
        "balance_cents": V.req_int(data, "balance_cents", minimum=1),
        "demand_cents": None,
        "approved_contribution_cents": 0,
        "status": "IDENTIFIED",
    }

    # rung 9 — state admissibility
    S.require_case_actionable(case)

    # rung 11 — uniqueness
    for existing in S.case_liens(case["id"]):
        if existing["lien_position"] == lien["lien_position"]:
            fail(
                "ERR_DUPLICATE_RESOURCE",
                "This case already carries a lien at that recording position.",
            )

    db.insert("liens", lien)
    S.recompute_junior_ledger(case)
    return created(lien_out(lien))


@bp.get("/short-sale/cases/<case_id>/junior-liens")
def list_liens(case_id):
    require(*LIEN_READ_ROLES)
    case = S.need_case(case_id)
    status = enum_filter("status", K.LIEN_STATUSES)
    rows = S.case_liens(case["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return collection(rows, lien_out, sort_key=lambda r: r["_seq"])


@bp.post("/short-sale/junior-liens/<lien_id>/demand")
def send_demand(lien_id):
    require(K.ROLE_NEGOTIATOR)
    lien = S.need_lien(lien_id)
    data = V.body()
    demand_cents = V.req_int(data, "demand_cents", minimum=0)

    # rung 9 — state admissibility
    if lien["status"] != "IDENTIFIED":
        fail("ERR_LIEN_NOT_ACTIONABLE", "A demand may only be sent from IDENTIFIED.")

    # rung 28 — lien contribution cap
    if demand_cents > lien["balance_cents"]:
        fail(
            "ERR_LIEN_CONTRIBUTION_EXCEEDS_CAP",
            "The demanded payoff exceeds the lien's outstanding balance.",
        )

    lien["demand_cents"] = demand_cents
    lien["status"] = "DEMAND_SENT"
    S.stale_case_sheets(lien["case_id"], "PRELIMINARY")
    return success(lien_out(lien))


@bp.post("/short-sale/junior-liens/<lien_id>/response")
def lien_response(lien_id):
    user_id = require(K.ROLE_JUNIOR_LIEN_HOLDER)
    lien = S.need_lien(lien_id)

    # rung 3 — ownership binding
    if user_id != lien["holder_user_id"]:
        fail("ERR_ACTOR_NOT_OWNER", "Only the recorded holder may respond to this lien.")

    data = V.body()
    outcome = V.req_enum(data, "outcome", K.LIEN_RESPONSE_OUTCOMES)
    contribution_cents = None
    if outcome == "APPROVE":
        contribution_cents = V.req_int(data, "contribution_cents", minimum=0)

    # rung 9 — state admissibility
    if lien["status"] not in LIEN_TRANSITIONS[outcome]:
        fail(
            "ERR_LIEN_NOT_ACTIONABLE",
            "%s is not declared from a lien in %s." % (outcome, lien["status"]),
        )

    # rung 28 — lien contribution cap
    if outcome == "APPROVE" and contribution_cents > lien["balance_cents"]:
        fail(
            "ERR_LIEN_CONTRIBUTION_EXCEEDS_CAP",
            "The approved contribution exceeds the lien's outstanding balance.",
        )

    case = db.get("cases", lien["case_id"])

    if outcome == "NEGOTIATE":
        lien["status"] = "NEGOTIATING"
    elif outcome == "APPROVE":
        lien["approved_contribution_cents"] = contribution_cents
        lien["status"] = "APPROVED"
        S.recompute_junior_ledger(case)
        S.stale_case_sheets(case["id"], "FINAL")
    elif outcome == "REFUSE":
        lien["approved_contribution_cents"] = 0
        lien["status"] = "REFUSED"
        S.recompute_junior_ledger(case)
    else:  # WITHDRAW_APPROVAL — the compensating action for APPROVE
        lien["approved_contribution_cents"] = 0
        lien["status"] = "NEGOTIATING"
        S.recompute_junior_ledger(case)
        S.stale_case_sheets(case["id"], "FINAL")

    return success(lien_out(lien))


# ---------------------------------------------------------------------------
# mortgage insurance
# ---------------------------------------------------------------------------
@bp.post("/short-sale/cases/<case_id>/mi-claims")
def create_mi_claim(case_id):
    require(K.ROLE_NEGOTIATOR)
    case = S.need_case(case_id)
    data = V.body()
    claim = {
        "id": db.new_id(),
        "case_id": case["id"],
        "mi_provider": V.req_string(data, "mi_provider"),
        "coverage_pct": V.req_decimal(
            data, "coverage_pct", minimum=Decimal(0), maximum=Decimal(1)
        ),
        "claim_reference": V.req_string(data, "claim_reference"),
        "required_contribution_cents": 0,
        "contribution_form": "NONE",
        "decided_by_user_id": None,
        "status": "PENDING",
    }

    # rung 9 — state admissibility
    S.require_case_actionable(case)

    # rung 11 — uniqueness
    if S.case_mi_claim(case["id"]) is not None:
        fail("ERR_DUPLICATE_RESOURCE", "This case already carries a mortgage insurance claim.")

    db.insert("mi_claims", claim)
    return created(mi_claim_out(claim))


@bp.get("/short-sale/cases/<case_id>/mi-claims")
def list_mi_claims(case_id):
    require(*MI_READ_ROLES)
    case = S.need_case(case_id)
    return collection(S.case_mi_claims(case["id"]), mi_claim_out, sort_key=lambda r: r["_seq"])


@bp.post("/short-sale/mi-claims/<claim_id>/decision")
def decide_mi_claim(claim_id):
    user_id = require(K.ROLE_MI_UNDERWRITER)
    claim = S.need_mi_claim(claim_id)
    data = V.body()
    outcome = V.req_enum(data, "outcome", K.MI_DECISION_OUTCOMES)
    required_contribution = None
    contribution_form = None
    if outcome == "APPROVE":
        required_contribution = V.req_int(data, "required_contribution_cents", minimum=0)
        contribution_form = V.req_enum(
            data, "contribution_form", K.MI_APPROVE_CONTRIBUTION_FORMS
        )

    # rung 9 — state admissibility
    if claim["status"] != "PENDING":
        fail("ERR_MI_CLAIM_NOT_DECIDABLE", "Only a PENDING claim may be decided.")

    case = db.get("cases", claim["case_id"])
    claim["decided_by_user_id"] = user_id

    if outcome == "APPROVE":
        claim["required_contribution_cents"] = required_contribution
        claim["contribution_form"] = contribution_form
        claim["status"] = "APPROVED"
        S.recompute_case_value(case)
        S.stale_case_sheets(case["id"], "FINAL")
    elif outcome == "DECLINE":
        claim["required_contribution_cents"] = 0
        claim["status"] = "DECLINED"
        S.recompute_case_value(case)
    else:  # NOT_REQUIRED
        claim["required_contribution_cents"] = 0
        claim["contribution_form"] = "NONE"
        claim["status"] = "NOT_REQUIRED"
        S.recompute_case_value(case)

    return success(mi_claim_out(claim))
