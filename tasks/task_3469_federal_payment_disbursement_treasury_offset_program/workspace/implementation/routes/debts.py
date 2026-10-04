"""Debt endpoints (PRD §3.3): referral, retrieval, listing, notice, activation.

CreditorAnalyst scoping (PRD §2.1, §2.8 tier 2): the analyst's X-User-ID must
equal the creditor_agency_id the debt is referred under (creation) or the
owning creditor of the debt being transitioned (notice/activate). On
transition endpoints the ownership check runs as soon as the debt is
loadable — before schema validation when the debt exists — matching the
tier-2 position; a missing debt still surfaces tier-4 schema errors first and
then ERR_NOT_FOUND.
"""
from datetime import timedelta

from flask import Blueprint, request

from constants import (
    DEBT_TYPES,
    NOTICE_WINDOW_DAYS,
    PRIORITY_RANK_BY_DEBT_TYPE,
    ROLE_CREDITOR_ANALYST,
)
from db import STORE, clock_now, new_entity, touch
from errors import (
    err_agreement_not_active,
    err_creditor_not_found,
    err_due_process_not_completed,
    err_forbidden,
    err_invalid_state,
    err_not_found,
    err_notice_window_not_elapsed,
)
from middleware import (
    authenticate,
    get_body,
    list_page,
    require_roles,
    spec_field,
    validate_body,
)
from response import ok, ok_list
from serializers import serialize_debt
from services.matching import agreement_covers
from util import gen_id

bp = Blueprint("debts", __name__)


def _forbid_foreign_creditor(ctx, creditor_agency_id):
    if creditor_agency_id != ctx.user_id:
        raise err_forbidden("CreditorAnalyst may only act on its own creditor's debts")


@bp.post("/debts")
def create_debt():
    ctx = authenticate()
    require_roles(ctx, ROLE_CREDITOR_ANALYST)
    body = get_body()
    # Tier 2 ownership: a present creditor_agency_id that differs from the
    # analyst's X-User-ID is forbidden before any further validation.
    referred_creditor = body.get("creditor_agency_id")
    if isinstance(referred_creditor, str):
        _forbid_foreign_creditor(ctx, referred_creditor)
    data = validate_body(body, [
        spec_field("creditor_agency_id", "str", required=True),
        spec_field("debtor_tin", "str", required=True),
        spec_field("debtor_name", "str", required=True),
        spec_field("debt_type", "enum", required=True, enum=DEBT_TYPES),
        spec_field("original_amount_cents", "int", required=True, gt=0),
        spec_field("delinquent_since", "dt", required=True),
        spec_field("notice_sent_at", "dt", required=False),
        spec_field("due_process_completed", "bool", required=False),
    ])
    creditor = STORE["creditors"].get(data["creditor_agency_id"])
    if creditor is None:
        raise err_creditor_not_found()

    ent = new_entity()
    ent["id"] = gen_id()
    ent.update({
        "creditor_agency_id": data["creditor_agency_id"],
        "debtor_tin": data["debtor_tin"],
        "debtor_name": data["debtor_name"],
        "debt_type": data["debt_type"],
        "original_amount_cents": data["original_amount_cents"],
        "current_balance_cents": data["original_amount_cents"],
        "priority_rank": PRIORITY_RANK_BY_DEBT_TYPE[data["debt_type"]],
        "delinquent_since": data["delinquent_since"],
        "notice_sent_at": data["notice_sent_at"],
        "due_process_completed": data["due_process_completed"]
            if data["due_process_completed"] is not None else False,
        "returned_count": 0,
        # Creation shortcut: referred with notice_sent_at -> NOTICED,
        # otherwise REFERRED (PRD §3.3).
        "status": "NOTICED" if data["notice_sent_at"] is not None else "REFERRED",
    })
    STORE["debts"][ent["id"]] = ent
    return ok(serialize_debt(ent), 201)


@bp.get("/debts/<string:debtId>")
def get_debt(debtId):
    authenticate()
    debt = STORE["debts"].get(debtId)
    if debt is None:
        raise err_not_found("Debt not found")
    return ok(serialize_debt(debt))


@bp.get("/debts")
def list_debts():
    authenticate()
    items = list(STORE["debts"].values())
    creditor_agency_id = request.args.get("creditor_agency_id")
    debtor_tin = request.args.get("debtor_tin")
    status = request.args.get("status")
    if creditor_agency_id is not None:
        items = [d for d in items if d["creditor_agency_id"] == creditor_agency_id]
    if debtor_tin is not None:
        items = [d for d in items if d["debtor_tin"] == debtor_tin]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    page, limit, offset, total = list_page(items)
    return ok_list([serialize_debt(d) for d in page], limit, offset, total)


@bp.post("/debts/<string:debtId>/notice")
def record_notice(debtId):
    """REFERRED or RETURNED -> NOTICED; re-referral always writes fresh values
    from the request and starts a fresh notice window (PRD §3.3)."""
    ctx = authenticate()
    require_roles(ctx, ROLE_CREDITOR_ANALYST)
    debt = STORE["debts"].get(debtId)
    if debt is not None:
        _forbid_foreign_creditor(ctx, debt["creditor_agency_id"])
    data = validate_body(get_body(), [
        spec_field("notice_sent_at", "dt", required=True),
        spec_field("due_process_completed", "bool", required=True),
    ])
    if debt is None:
        raise err_not_found("Debt not found")
    if debt["status"] not in ("REFERRED", "RETURNED"):
        raise err_invalid_state("Only a REFERRED or RETURNED debt can record a notice")
    debt["notice_sent_at"] = data["notice_sent_at"]
    debt["due_process_completed"] = data["due_process_completed"]
    debt["status"] = "NOTICED"
    touch(debt)
    return ok(serialize_debt(debt))


@bp.post("/debts/<string:debtId>/activate")
def activate_debt(debtId):
    """NOTICED -> ACTIVE through the due-process, notice-window, and (for state
    creditors) reciprocal-agreement gates (PRD §3.3)."""
    ctx = authenticate()
    require_roles(ctx, ROLE_CREDITOR_ANALYST)
    debt = STORE["debts"].get(debtId)
    if debt is not None:
        _forbid_foreign_creditor(ctx, debt["creditor_agency_id"])
    validate_body(get_body(), [])
    if debt is None:
        raise err_not_found("Debt not found")
    if debt["status"] != "NOTICED":
        raise err_invalid_state("Only a NOTICED debt can be activated")
    # Compliance gates (tier 8).
    if not debt["due_process_completed"]:
        raise err_due_process_not_completed()
    if clock_now() < debt["notice_sent_at"] + timedelta(days=NOTICE_WINDOW_DAYS):
        raise err_notice_window_not_elapsed()
    # Referential gate (tier 10): state creditors need covering agreement.
    creditor = STORE["creditors"].get(debt["creditor_agency_id"])
    if creditor is not None and creditor["creditor_type"] == "STATE":
        if not agreement_covers(creditor["state_code"], ("FED_TO_STATE", "BIDIRECTIONAL")):
            raise err_agreement_not_active()
    debt["status"] = "ACTIVE"
    touch(debt)
    return ok(serialize_debt(debt))
