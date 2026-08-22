"""Payments: booking, the chronological replay and reversal (PRD 3.8)."""

from flask import request

from auth import check_judgment_ownership
from domain import (
    by_seq,
    get_action,
    get_agreement,
    get_judgment,
    get_payment,
    guard_judgment_alive,
    invalid_state,
    recompute_balances,
    recompute_collections,
    recount_judgment,
    replay,
    satisfy_judgment,
    step_back_posture,
    to_date,
)
from errors import ApiError
from store import bump, new_row, store
from validators import (
    ENUM_PAYMENT_SOURCE,
    check_enum,
    json_body,
    pagination,
    positive,
    present,
    require_date,
    require_int,
    require_string,
)
from web import endpoint, make_list

from .helpers import apply_filter, scope, serialize

READ_ROLES = ("CaseManager", "ComplianceOfficer", "Creditor", "Debtor")


def register(app):
    # ---- POST /payments ---------------------------------------------------
    @endpoint(app, "/payments", "POST", ("CaseManager", "Debtor"), 201)
    def create_payment(ctx):
        body = json_body()
        judgment = None
        if present(body, "judgment_id"):
            judgment = get_judgment(body.get("judgment_id"))
            check_judgment_ownership(ctx, judgment)
        action = get_action(body.get("enforcement_action_id")) if present(body, "enforcement_action_id") else None
        agreement = get_agreement(body.get("installment_agreement_id")) if present(body, "installment_agreement_id") else None

        judgment_id = require_string(body, "judgment_id")
        amount_cents = require_int(body, "amount_cents")
        received_on = require_date(body, "received_on")
        require_string(body, "source")
        if present(body, "installment_agreement_id"):
            require_string(body, "installment_agreement_id")
        if present(body, "enforcement_action_id"):
            require_string(body, "enforcement_action_id")
        source = check_enum(body, "source", ENUM_PAYMENT_SOURCE)
        positive(amount_cents, "amount_cents")

        guard_judgment_alive(judgment)

        # rung 20 - no money is booked against an action with a live claim
        if action is not None:
            for claim in store.exemption_claims.values():
                if claim["enforcement_action_id"] == action["id"] and claim["status"] in ("FILED", "OPPOSED"):
                    raise ApiError("ERR_EXEMPTION_PENDING",
                                   "An exemption claim on this enforcement action is still live.")

        # rung 26 - received_on lies inside the judgment's life
        entered_on = to_date(judgment["entered_on"])
        clock_date = store.clock_date()
        if received_on < entered_on or received_on > clock_date:
            raise ApiError("ERR_PAYMENT_DATE_INVALID",
                           "received_on must fall between entered_on and the current clock date.")

        # rung 42 - a point-in-time test against the payoff as of received_on
        point_in_time = replay(judgment, received_on, judgment["application_order"])["total"]
        if amount_cents > point_in_time:
            raise ApiError("ERR_PAYMENT_EXCEEDS_PAYOFF",
                           "The payment exceeds the judgment's payoff as of received_on.")

        row = new_row({
            "judgment_id": judgment_id,
            "installment_agreement_id": agreement["id"] if agreement is not None else None,
            "enforcement_action_id": action["id"] if action is not None else None,
            "amount_cents": amount_cents,
            "received_on": received_on.isoformat(),
            "source": source,
            "status": "APPLIED",
            "applied_to_costs_cents": 0,
            "applied_to_interest_cents": 0,
            "applied_to_principal_cents": 0,
            "contingency_fee_cents": 0,
            "reversal_reason": None,
            "reversed_on": None,
        })
        store.payments[row["id"]] = row

        recompute_balances(judgment)
        recompute_collections(judgment)

        if action is not None:
            action["collected_cents"] += amount_cents
            collects = (source == "GARNISHMENT") or (
                action["action_type"] == "BANK_LEVY"
                and action["collected_cents"] >= action["levy_hold_cents"]
            )
            if collects and action["status"] == "SERVED":
                if action["action_type"] == "BANK_LEVY":
                    hold = action["levy_hold_cents"]
                    finding = store.asset_findings.get(action["asset_finding_id"])
                    if hold and finding is not None:
                        finding["frozen_cents"] -= hold
                        finding["swept_cents"] += hold
                        bump(finding)
                action["levy_hold_cents"] = 0
                action["status"] = "COLLECTED"
                bump(action)
                step_back_posture(judgment)
            else:
                bump(action)

        if agreement is not None:
            agreement["paid_to_date_cents"] += amount_cents
            completes = (agreement["status"] == "ACTIVE"
                         and agreement["paid_to_date_cents"] >= agreement["total_cents"])
            if completes:
                agreement["status"] = "COMPLETED"
            bump(agreement)
            if completes:
                judgment["forgiven_cents"] = judgment["total_payoff_cents"]
                if judgment["status"] == "ACTIVE":
                    satisfy_judgment(judgment)

        if judgment["status"] == "ACTIVE" and judgment["total_payoff_cents"] == 0:
            satisfy_judgment(judgment)

        recount_judgment(judgment)
        bump(judgment)
        return serialize(row)

    # ---- GET /payments ----------------------------------------------------
    @endpoint(app, "/payments", "GET", READ_ROLES, 200)
    def list_payments(ctx):
        limit, offset = pagination(request.args)
        rows = by_seq(list(store.payments.values()))
        rows = apply_filter(rows, request.args, "judgment_id")
        rows = apply_filter(rows, request.args, "installment_agreement_id")
        rows = apply_filter(rows, request.args, "enforcement_action_id")
        rows = apply_filter(rows, request.args, "status")
        rows = scope(ctx, rows, lambda r: store.judgments.get(r["judgment_id"]))
        return make_list(rows, limit, offset, serialize)

    # ---- GET /payments/{payment_id} --------------------------------------
    @endpoint(app, "/payments/<payment_id>", "GET", READ_ROLES, 200)
    def read_payment(ctx, payment_id):
        payment = get_payment(payment_id)
        check_judgment_ownership(ctx, store.judgments.get(payment["judgment_id"]))
        return serialize(payment)

    # ---- POST /payments/{payment_id}/reverse -----------------------------
    @endpoint(app, "/payments/<payment_id>/reverse", "POST", ("ComplianceOfficer",), 200)
    def reverse_payment(ctx, payment_id):
        payment = get_payment(payment_id)
        body = json_body()
        reason = require_string(body, "reason")
        if payment["status"] != "APPLIED":
            invalid_state("Only an APPLIED payment may be reversed.")
        judgment = store.judgments.get(payment["judgment_id"])
        guard_judgment_alive(judgment)

        payment["status"] = "REVERSED"
        payment["reversal_reason"] = reason
        payment["reversed_on"] = store.clock_date().isoformat()
        bump(payment)

        recompute_balances(judgment)
        recompute_collections(judgment)

        action = store.enforcement_actions.get(payment["enforcement_action_id"]) \
            if payment["enforcement_action_id"] else None
        if action is not None:
            action["collected_cents"] -= payment["amount_cents"]
            if action["status"] == "COLLECTED":
                action["status"] = "SERVED"
            bump(action)

        agreement = store.installment_agreements.get(payment["installment_agreement_id"]) \
            if payment["installment_agreement_id"] else None
        if agreement is not None:
            agreement["paid_to_date_cents"] -= payment["amount_cents"]
            bump(agreement)

        if judgment["status"] == "ACTIVE" and judgment["total_payoff_cents"] == 0:
            satisfy_judgment(judgment)

        recount_judgment(judgment)
        bump(judgment)
        return serialize(payment)
