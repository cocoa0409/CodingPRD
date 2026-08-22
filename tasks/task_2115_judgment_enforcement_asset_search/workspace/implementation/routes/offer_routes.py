"""Settlement offers, counters and acceptance (PRD 3.7)."""

from flask import request

from auth import check_judgment_ownership
from domain import (
    INSTALLMENT_FIRST_DUE_DAYS,
    MAX_NEGOTIATION_ROUNDS,
    MIN_SETTLEMENT_PCT_BPS,
    add_days,
    by_seq,
    children,
    clock_instant_string,
    get_judgment,
    get_offer,
    guard_judgment_alive,
    invalid_state,
    payoff_now,
    recount_judgment,
    suspend_served_actions,
)
from errors import ApiError
from store import bump, new_row, store, touch
from validators import (
    ENUM_APPLICATION_ORDER,
    ENUM_OFFER_KIND,
    ENUM_OFFERED_BY,
    check_enum,
    json_body,
    pagination,
    positive,
    present,
    require_instant,
    require_int,
    require_string,
)
from web import endpoint, make_list

from .helpers import apply_filter, scope, serialize

WRITE_ROLES = ("CaseManager", "Creditor", "Debtor")
DECIDE_ROLES = ("CaseManager", "ComplianceOfficer", "Creditor", "Debtor")
READ_ROLES = ("CaseManager", "ComplianceOfficer", "Creditor", "Debtor")
CREDITOR_SIDE_ROLES = ("CaseManager", "ComplianceOfficer", "Creditor")


def _ceil_div(numerator, denominator):
    return -(-numerator // denominator)


def register(app):
    # ---- POST /settlement-offers -----------------------------------------
    @endpoint(app, "/settlement-offers", "POST", WRITE_ROLES, 201)
    def create_offer(ctx):
        body = json_body()
        judgment = None
        if present(body, "judgment_id"):
            judgment = get_judgment(body.get("judgment_id"))
            check_judgment_ownership(ctx, judgment)
        parent = get_offer(body.get("responds_to_offer_id")) if present(body, "responds_to_offer_id") else None

        judgment_id = require_string(body, "judgment_id")
        require_string(body, "offered_by")
        require_string(body, "kind")
        amount_cents = require_int(body, "amount_cents")
        expires_at = require_instant(body, "expires_at")
        expected_version = require_int(body, "expected_judgment_version")
        installment_count = require_int(body, "installment_count", optional=True, default=1)
        if installment_count is not None and installment_count > 60:
            raise ApiError("ERR_INVALID_REQUEST", "installment_count may not exceed 60.")
        if present(body, "application_order_concession"):
            require_string(body, "application_order_concession")
        if present(body, "responds_to_offer_id"):
            require_string(body, "responds_to_offer_id")

        offered_by = check_enum(body, "offered_by", ENUM_OFFERED_BY)
        kind = check_enum(body, "kind", ENUM_OFFER_KIND)
        concession = check_enum(body, "application_order_concession",
                                ENUM_APPLICATION_ORDER, optional=True) or "STATUTORY_ORDER"

        positive(amount_cents, "amount_cents")
        positive(installment_count, "installment_count")

        # rung 12 - optimistic concurrency against the judgment row
        if expected_version != judgment["version"]:
            raise ApiError("ERR_STALE_JUDGMENT_VERSION",
                           "expected_judgment_version does not match the judgment's current version.")
        if parent is not None and parent["status"] != "OPEN":
            invalid_state("The offer being countered is no longer OPEN.")
        guard_judgment_alive(judgment)

        round_number = 1
        if parent is not None:
            # rung 31 - sides must alternate
            if parent["offered_by"] == offered_by:
                raise ApiError("ERR_SAME_PARTY_COUNTER",
                               "A counter-offer must come from the opposite side.")
            round_number = parent["round_number"] + 1
            # rung 35 - four rounds is the whole negotiation
            if round_number > MAX_NEGOTIATION_ROUNDS:
                raise ApiError("ERR_NEGOTIATION_ROUNDS_EXHAUSTED",
                               "The negotiation has no rounds left.")

        if kind == "LUMP_SUM":
            installment_count = 1

        payoff = payoff_now(judgment)
        row = new_row({
            "judgment_id": judgment_id,
            "responds_to_offer_id": parent["id"] if parent is not None else None,
            "offered_by": offered_by,
            "kind": kind,
            "amount_cents": amount_cents,
            "installment_count": installment_count,
            "application_order_concession": concession,
            "expires_at": body["expires_at"],
            "round_number": round_number,
            "monthly_cents": _ceil_div(amount_cents, installment_count),
            "min_acceptable_cents": (payoff * MIN_SETTLEMENT_PCT_BPS) // 10000,
            "status": "OPEN",
            "decided_at": None,
            "_expires_at": expires_at,
        })
        store.settlement_offers[row["id"]] = row

        if parent is not None:
            parent["status"] = "COUNTERED"
            parent["decided_at"] = clock_instant_string()
            bump(parent)

        recount_judgment(judgment)
        bump(judgment)
        return serialize(row)

    # ---- GET /settlement-offers ------------------------------------------
    @endpoint(app, "/settlement-offers", "GET", READ_ROLES, 200)
    def list_offers(ctx):
        limit, offset = pagination(request.args)
        rows = by_seq(list(store.settlement_offers.values()))
        rows = apply_filter(rows, request.args, "judgment_id")
        rows = apply_filter(rows, request.args, "responds_to_offer_id")
        rows = apply_filter(rows, request.args, "status")
        rows = scope(ctx, rows, lambda r: store.judgments.get(r["judgment_id"]))
        return make_list(rows, limit, offset, serialize)

    # ---- GET /settlement-offers/{settlement_offer_id} --------------------
    @endpoint(app, "/settlement-offers/<settlement_offer_id>", "GET", READ_ROLES, 200)
    def read_offer(ctx, settlement_offer_id):
        offer = get_offer(settlement_offer_id)
        check_judgment_ownership(ctx, store.judgments.get(offer["judgment_id"]))
        return serialize(offer)

    # ---- POST /settlement-offers/{id}/accept -----------------------------
    @endpoint(app, "/settlement-offers/<settlement_offer_id>/accept", "POST", DECIDE_ROLES, 200)
    def accept_offer(ctx, settlement_offer_id):
        offer = get_offer(settlement_offer_id)
        judgment = store.judgments.get(offer["judgment_id"])
        check_judgment_ownership(ctx, judgment)
        if offer["status"] != "OPEN":
            invalid_state("Only an OPEN offer may be accepted.")
        # acceptance is cross-party: side is fixed by role
        if offer["offered_by"] == "CREDITOR" and ctx.role != "Debtor":
            invalid_state("An offer tendered by the creditor side may only be accepted by the debtor.")
        if offer["offered_by"] == "DEBTOR" and ctx.role not in CREDITOR_SIDE_ROLES:
            invalid_state("An offer tendered by the debtor may only be accepted by the creditor side.")
        guard_judgment_alive(judgment)
        # rung 39 - the settlement floor, waived for a ComplianceOfficer
        if offer["amount_cents"] < offer["min_acceptable_cents"] and ctx.role != "ComplianceOfficer":
            raise ApiError("ERR_SETTLEMENT_BELOW_FLOOR",
                           "The offer falls below its snapshotted settlement floor.")

        offer["status"] = "ACCEPTED"
        offer["decided_at"] = clock_instant_string()
        bump(offer)

        total = offer["amount_cents"]
        count = offer["installment_count"]
        monthly = _ceil_div(total, count)
        agreement = new_row({
            "judgment_id": judgment["id"],
            "settlement_offer_id": offer["id"],
            "total_cents": total,
            "installment_count": count,
            "monthly_cents": monthly,
            "final_installment_cents": total - monthly * (count - 1),
            "first_due_on": add_days(store.clock_date(), INSTALLMENT_FIRST_DUE_DAYS).isoformat(),
            "paid_to_date_cents": 0,
            "missed_count": 0,
            "reinstatement_count": 0,
            "application_order_concession": offer["application_order_concession"],
            "status": "ACTIVE",
        })
        store.installment_agreements[agreement["id"]] = agreement

        judgment["application_order"] = agreement["application_order_concession"]
        if judgment["enforcement_posture"] == "ENFORCING":
            judgment["enforcement_posture"] = "STAYED"
            suspend_served_actions(judgment)

        for sibling in children(store.settlement_offers, "judgment_id", judgment["id"]):
            if sibling["id"] != offer["id"] and sibling["status"] == "OPEN":
                sibling["status"] = "REJECTED"
                sibling["decided_at"] = clock_instant_string()
                bump(sibling)

        recount_judgment(judgment)
        bump(judgment)
        return serialize(offer)

    # ---- POST /settlement-offers/{id}/reject -----------------------------
    @endpoint(app, "/settlement-offers/<settlement_offer_id>/reject", "POST", DECIDE_ROLES, 200)
    def reject_offer(ctx, settlement_offer_id):
        offer = get_offer(settlement_offer_id)
        judgment = store.judgments.get(offer["judgment_id"])
        check_judgment_ownership(ctx, judgment)
        if offer["status"] != "OPEN":
            invalid_state("Only an OPEN offer may be rejected.")
        guard_judgment_alive(judgment)
        offer["status"] = "REJECTED"
        offer["decided_at"] = clock_instant_string()
        bump(offer)
        recount_judgment(judgment)
        touch(judgment)
        return serialize(offer)
