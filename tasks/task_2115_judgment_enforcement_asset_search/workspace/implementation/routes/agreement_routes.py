"""Installment agreements: the miss/default/reinstate cycle (PRD 3.7)."""

from flask import request

from auth import check_judgment_ownership
from domain import (
    MAX_MISSES,
    MAX_REINSTATEMENTS,
    by_seq,
    get_agreement,
    guard_judgment_alive,
    invalid_state,
    recompute_balances,
    recount_judgment,
    resume_suspended_actions,
    suspend_served_actions,
)
from errors import ApiError
from store import bump, store
from validators import pagination
from web import endpoint, make_list

from .helpers import apply_filter, scope, serialize

READ_ROLES = ("CaseManager", "ComplianceOfficer", "Creditor", "Debtor")


def register(app):
    # ---- GET /installment-agreements -------------------------------------
    @endpoint(app, "/installment-agreements", "GET", READ_ROLES, 200)
    def list_agreements(ctx):
        limit, offset = pagination(request.args)
        rows = by_seq(list(store.installment_agreements.values()))
        rows = apply_filter(rows, request.args, "judgment_id")
        rows = apply_filter(rows, request.args, "settlement_offer_id")
        rows = apply_filter(rows, request.args, "status")
        rows = scope(ctx, rows, lambda r: store.judgments.get(r["judgment_id"]))
        return make_list(rows, limit, offset, serialize)

    # ---- GET /installment-agreements/{installment_agreement_id} ----------
    @endpoint(app, "/installment-agreements/<installment_agreement_id>", "GET", READ_ROLES, 200)
    def read_agreement(ctx, installment_agreement_id):
        agreement = get_agreement(installment_agreement_id)
        check_judgment_ownership(ctx, store.judgments.get(agreement["judgment_id"]))
        return serialize(agreement)

    # ---- POST /installment-agreements/{id}/record-miss -------------------
    @endpoint(app, "/installment-agreements/<installment_agreement_id>/record-miss", "POST",
              ("CaseManager",), 200)
    def record_miss(ctx, installment_agreement_id):
        agreement = get_agreement(installment_agreement_id)
        if agreement["status"] != "ACTIVE":
            invalid_state("Only an ACTIVE installment agreement may record a missed instalment.")
        judgment = store.judgments.get(agreement["judgment_id"])
        guard_judgment_alive(judgment)

        agreement["missed_count"] += 1
        defaulted = agreement["missed_count"] >= MAX_MISSES
        if defaulted:
            agreement["status"] = "DEFAULTED"
        bump(agreement)

        if defaulted:
            if judgment["enforcement_posture"] == "STAYED":
                judgment["enforcement_posture"] = "ENFORCING"
                resume_suspended_actions(judgment)
            judgment["application_order"] = "STATUTORY_ORDER"
            recompute_balances(judgment)
            recount_judgment(judgment)
            bump(judgment)
        return serialize(agreement)

    # ---- POST /installment-agreements/{id}/reinstate ---------------------
    @endpoint(app, "/installment-agreements/<installment_agreement_id>/reinstate", "POST",
              ("ComplianceOfficer",), 200)
    def reinstate(ctx, installment_agreement_id):
        agreement = get_agreement(installment_agreement_id)
        if agreement["status"] != "DEFAULTED":
            invalid_state("Only a DEFAULTED installment agreement may be reinstated.")
        judgment = store.judgments.get(agreement["judgment_id"])
        guard_judgment_alive(judgment)
        # rung 38 - an agreement may be reinstated once
        if agreement["reinstatement_count"] >= MAX_REINSTATEMENTS:
            raise ApiError("ERR_REINSTATEMENT_LIMIT", "This agreement has no reinstatements left.")

        agreement["missed_count"] = 0
        agreement["reinstatement_count"] += 1
        agreement["status"] = "ACTIVE"
        bump(agreement)

        judgment["application_order"] = agreement["application_order_concession"]
        if judgment["enforcement_posture"] == "ENFORCING":
            judgment["enforcement_posture"] = "STAYED"
            suspend_served_actions(judgment)
        recount_judgment(judgment)
        bump(judgment)
        return serialize(agreement)
