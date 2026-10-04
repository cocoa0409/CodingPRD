"""Investigations: open, list, get, transition; nested CID and ConsentOrder
creation/listing (their transitions live in routes_cids.py / routes_orders.py).
"""
from flask import Blueprint, request

import envelope
import errors
import requtil
import store
from timeutil import parse_iso

bp = Blueprint("investigations", __name__)

INVESTIGATION_STATES = {
    "INTAKE",
    "PRELIMINARY_REVIEW",
    "EVIDENCE_GATHERING",
    "NEGOTIATING",
    "SETTLED",
    "CLOSED_NO_ACTION",
    "CLOSED_ORDER_ENTERED",
}
# Only these targets are directly requestable; SETTLED and CLOSED_ORDER_ENTERED
# are system-only (consent-order drafting / finalization cascades).
INV_TRANSITIONS = {
    "PRELIMINARY_REVIEW": {"INTAKE"},
    "EVIDENCE_GATHERING": {"PRELIMINARY_REVIEW", "NEGOTIATING"},
    "NEGOTIATING": {"EVIDENCE_GATHERING"},
    "CLOSED_NO_ACTION": {"INTAKE", "PRELIMINARY_REVIEW", "EVIDENCE_GATHERING"},
}
ORIGINS = {"COMPLAINT", "REFERRAL", "MARKET_MONITORING"}


def _sorted_page(items, limit, offset):
    items.sort(key=lambda e: (parse_iso(e["created_at"]), e["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return [store.public(e) for e in page], total


@bp.route("/enforcement/investigations", methods=["POST"])
def open_investigation():
    user_id, role = requtil.context()
    requtil.require_role(role, ["StaffAttorney"])
    body = requtil.json_body()
    subject_company_id = requtil.need_str(body, "subject_company_id")
    origin = requtil.need_enum(body, "origin", ORIGINS)
    summary = requtil.need_str(body, "summary")
    company = requtil.get_or_404(
        store.db.subject_companies,
        subject_company_id,
        "ERR_SUBJECT_COMPANY_NOT_FOUND",
        "SubjectCompany",
    )
    # Tier 14 (intake threshold grouped with the fiscal tier, checked last):
    if origin == "MARKET_MONITORING" and company["risk_tier"] not in (
        "ELEVATED",
        "CRITICAL",
    ):
        errors.fail(
            "ERR_MONITORING_THRESHOLD_NOT_MET",
            "MARKET_MONITORING origin requires risk_tier ELEVATED or CRITICAL",
        )
    with store.db.lock:
        inv = store.stamp_new(
            {
                "subject_company_id": subject_company_id,
                "origin": origin,
                "summary": summary,
                "opened_by_user_id": user_id,
                "status": "INTAKE",
            }
        )
        store.db.investigations[inv["id"]] = inv
    return envelope.success(store.public(inv), 201)


@bp.route("/enforcement/investigations", methods=["GET"])
def list_investigations():
    _user_id, role = requtil.context()
    requtil.require_role(role, requtil.ALL_ROLES)
    limit, offset = requtil.page_params()
    items = list(store.db.investigations.values())
    company_filter = request.args.get("subject_company_id")
    if company_filter is not None:
        items = [i for i in items if i["subject_company_id"] == company_filter]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [i for i in items if i["status"] == status_filter]
    page, total = _sorted_page(items, limit, offset)
    return envelope.success_list(page, limit, offset, total)


@bp.route("/enforcement/investigations/<investigationId>", methods=["GET"])
def get_investigation(investigationId):
    _user_id, role = requtil.context()
    requtil.require_role(role, requtil.ALL_ROLES)
    inv = requtil.get_or_404(
        store.db.investigations,
        investigationId,
        "ERR_INVESTIGATION_NOT_FOUND",
        "Investigation",
    )
    return envelope.success(store.public(inv), 200)


@bp.route("/enforcement/investigations/<investigationId>/transition", methods=["POST"])
def transition_investigation(investigationId):
    _user_id, role = requtil.context()
    requtil.require_role(role, ["StaffAttorney"])
    inv = requtil.get_or_404(
        store.db.investigations,
        investigationId,
        "ERR_INVESTIGATION_NOT_FOUND",
        "Investigation",
    )
    body = requtil.json_body()
    target = requtil.need_enum(body, "target_state", INVESTIGATION_STATES)
    if target not in INV_TRANSITIONS or inv["status"] not in INV_TRANSITIONS[target]:
        errors.fail(
            "ERR_INVALID_STATE_TRANSITION",
            "Investigation cannot transition from {} to {}".format(
                inv["status"], target
            ),
        )
    with store.db.lock:
        inv["status"] = target
        store.touch(inv)
    return envelope.success(store.public(inv), 200)


@bp.route("/enforcement/investigations/<investigationId>/cids", methods=["POST"])
def draft_cid(investigationId):
    _user_id, role = requtil.context()
    requtil.require_role(role, ["StaffAttorney"])
    inv = requtil.get_or_404(
        store.db.investigations,
        investigationId,
        "ERR_INVESTIGATION_NOT_FOUND",
        "Investigation",
    )
    body = requtil.json_body()
    subject_matter = requtil.need_str(body, "subject_matter")
    response_due_date = requtil.need_datetime(body, "response_due_date")
    with store.db.lock:
        cid = store.stamp_new(
            {
                "investigation_id": inv["id"],
                "subject_matter": subject_matter,
                "response_due_date": response_due_date,
                "response_document_ref": None,
                "responded_at": None,
                "status": "DRAFT",
            }
        )
        store.db.cids[cid["id"]] = cid
    return envelope.success(store.public(cid), 201)


@bp.route("/enforcement/investigations/<investigationId>/cids", methods=["GET"])
def list_cids(investigationId):
    _user_id, role = requtil.context()
    requtil.require_role(role, requtil.ALL_ROLES)
    inv = requtil.get_or_404(
        store.db.investigations,
        investigationId,
        "ERR_INVESTIGATION_NOT_FOUND",
        "Investigation",
    )
    limit, offset = requtil.page_params()
    items = [c for c in store.db.cids.values() if c["investigation_id"] == inv["id"]]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [c for c in items if c["status"] == status_filter]
    page, total = _sorted_page(items, limit, offset)
    return envelope.success_list(page, limit, offset, total)


@bp.route("/enforcement/investigations/<investigationId>/consent-orders", methods=["POST"])
def draft_consent_order(investigationId):
    user_id, role = requtil.context()
    requtil.require_role(role, ["StaffAttorney"])
    inv = requtil.get_or_404(
        store.db.investigations,
        investigationId,
        "ERR_INVESTIGATION_NOT_FOUND",
        "Investigation",
    )
    body = requtil.json_body()
    monetary_relief_cents = requtil.need_int(body, "monetary_relief_cents", minimum=1)
    max_penalty_cents = requtil.need_int(body, "max_penalty_cents", minimum=1)
    reporting_frequency_months = requtil.need_int(
        body, "reporting_frequency_months", choices={3, 6, 12}
    )
    monitoring_term_years = requtil.need_int(
        body, "monitoring_term_years", minimum=1, maximum=20
    )
    conduct_prohibitions = requtil.need_str_list(body, "conduct_prohibitions")
    if inv["status"] != "NEGOTIATING":
        errors.fail(
            "ERR_INVALID_STATE_TRANSITION",
            "A consent order may be drafted only while the investigation is NEGOTIATING",
        )
    with store.db.lock:
        order = store.stamp_new(
            {
                "investigation_id": inv["id"],
                "subject_company_id": inv["subject_company_id"],
                "negotiating_attorney_user_id": user_id,
                "monetary_relief_cents": monetary_relief_cents,
                "max_penalty_cents": max_penalty_cents,
                "reporting_frequency_months": reporting_frequency_months,
                "monitoring_term_years": monitoring_term_years,
                "conduct_prohibitions": conduct_prohibitions,
                "proposal_round": 1,
                "monitoring_started_at": None,
                "monitoring_ends_at": None,
                "finalized_at": None,
                "finalized_by_user_id": None,
                "status": "DRAFT",
            }
        )
        store.db.consent_orders[order["id"]] = order
        # Drafting is the settlement event: NEGOTIATING -> SETTLED.
        inv["status"] = "SETTLED"
        store.touch(inv)
    return envelope.success(store.public(order), 201)


@bp.route("/enforcement/investigations/<investigationId>/consent-orders", methods=["GET"])
def list_consent_orders(investigationId):
    _user_id, role = requtil.context()
    requtil.require_role(role, requtil.ALL_ROLES)
    inv = requtil.get_or_404(
        store.db.investigations,
        investigationId,
        "ERR_INVESTIGATION_NOT_FOUND",
        "Investigation",
    )
    limit, offset = requtil.page_params()
    items = [
        o for o in store.db.consent_orders.values()
        if o["investigation_id"] == inv["id"]
    ]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [o for o in items if o["status"] == status_filter]
    page, total = _sorted_page(items, limit, offset)
    return envelope.success_list(page, limit, offset, total)
