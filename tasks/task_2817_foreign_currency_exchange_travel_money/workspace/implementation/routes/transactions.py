"""The counter: quoting, authorising, settling, voiding, reversing and compliance decisions."""
from datetime import timedelta

from flask import Blueprint

import calc
from core import (
    DUAL_CONTROL_THRESHOLD_CENTS,
    ID_REQUIRED_CENTS,
    QUOTE_TTL_MINUTES,
    REPORT_THRESHOLD_CENTS,
    REVERSAL_WINDOW_HOURS,
    D,
    actor,
    all_rows,
    body,
    clock,
    endpoint,
    fail,
    fmt_dt,
    listing,
    need,
    need_currency,
    new_row,
    now_str,
    ok,
    opt_str,
    parse_note_lines,
    public,
    req_enum,
    req_list,
    req_str,
    require_branch_active,
    require_not_frozen,
    require_not_restricted,
    require_standard_denominations,
    S,
    store,
    touch,
)
from routes.inventory import branch_sells_exotic

bp = Blueprint("transactions", __name__)

READERS = ("PlatformAdmin", "TreasuryOfficer", "BranchManager", "BranchTeller", "ComplianceOfficer")
DIRECTIONS = ("SELL_FX_TO_CUSTOMER", "BUY_FX_FROM_CUSTOMER")


# ==========================================================================
# Quoting
# ==========================================================================
@bp.post("/exchange-transactions")
@endpoint(["BranchTeller", "BranchManager"])
def quote_transaction():
    b = body()
    branch = need("Branch", req_str(b, "branch_id"))
    customer = need("Customer", req_str(b, "customer_id"))
    card = need("RateCard", req_str(b, "rate_card_id"))
    currency_code = req_str(b, "currency_code")
    profile = need_currency(currency_code)
    direction = req_enum(b, "direction", DIRECTIONS)
    lines = parse_note_lines(
        req_list(b, "requested_denominations"), "requested_denominations", min_count=1
    )
    require_standard_denominations(lines, profile, "requested_denominations")
    if card["branch_id"] != branch["id"] or card["currency_code"] != currency_code:
        fail(
            "ERR_INVALID_REQUEST",
            "The cited rate card belongs to another branch or currency.",
        )
    require_branch_active(branch)
    if card["status"] != "PUBLISHED":
        fail("ERR_RATE_CARD_NOT_PUBLISHED")
    if not calc.card_covers(card, clock()):
        fail("ERR_RATE_CARD_NOT_EFFECTIVE")

    applied_rate = (
        card["sell_rate_micros"] if direction == "SELL_FX_TO_CUSTOMER" else card["buy_rate_micros"]
    )
    fx_gross = calc.fx_gross(lines)
    gross = calc.usd_conversion(lines, applied_rate)
    commission, total = calc.commission_and_total(
        gross, gross, card["commission_schedule_code"], direction
    )

    row = new_row("ExchangeTransaction")
    row["branch_id"] = branch["id"]
    row["customer_id"] = customer["id"]
    row["rate_card_id"] = card["id"]
    row["buyback_contract_id"] = None
    row["currency_code"] = currency_code
    row["direction"] = direction
    row["requested_denominations"] = lines
    row["fx_gross_minor_units"] = fx_gross
    row["applied_rate_micros"] = applied_rate
    row["quoted_usd_gross_cents"] = gross
    row["quoted_commission_cents"] = commission
    row["quoted_total_charge_cents"] = total
    row["quote_expires_at"] = fmt_dt(clock() + timedelta(minutes=QUOTE_TTL_MINUTES))
    row["settled_usd_gross_cents"] = None
    row["settled_commission_cents"] = None
    row["settled_total_charge_cents"] = None
    row["price_adjustment_cents"] = None
    row["settlement_status"] = "QUOTED"
    row["compliance_status"] = "PENDING"
    row["quoted_by_user_id"] = actor()
    row["authorized_by_user_id"] = None
    row["settled_by_user_id"] = None
    row["authorized_at"] = None
    row["settled_at"] = None
    row["reversed_at"] = None
    store(row)
    return ok(public(row), 201)


# ==========================================================================
# Authorising
# ==========================================================================
@bp.post("/exchange-transactions/<transaction_id>/authorize")
@endpoint(["BranchTeller", "BranchManager"])
def authorize_transaction(transaction_id):
    transaction = need("ExchangeTransaction", transaction_id)
    if transaction["settlement_status"] != "QUOTED":
        fail("ERR_TRANSACTION_NOT_QUOTED")
    branch = need("Branch", transaction["branch_id"])
    customer = need("Customer", transaction["customer_id"])
    profile = need_currency(transaction["currency_code"])
    # rank 7
    require_branch_active(branch)
    require_not_frozen(branch)
    if transaction["direction"] == "BUY_FX_FROM_CUSTOMER":
        require_not_restricted(branch)
    # rank 8
    if customer["compliance_hold_active"]:
        fail("ERR_CUSTOMER_COMPLIANCE_HOLD")
    if transaction["quoted_usd_gross_cents"] >= ID_REQUIRED_CENTS and (
        customer["id_document_type"] is None
        or customer["id_document_number"] is None
        or customer["id_document_expiry"] is None
    ):
        fail("ERR_CUSTOMER_ID_REQUIRED")
    if customer["id_document_expiry"] is not None and D(
        customer["id_document_expiry"]
    ) <= clock():
        fail("ERR_CUSTOMER_ID_EXPIRED")
    selling = transaction["direction"] == "SELL_FX_TO_CUSTOMER"
    if (
        selling
        and profile["currency_class"] == "RESTRICTED"
        and customer["travel_document_reference"] is None
    ):
        fail("ERR_RESTRICTED_CURRENCY_DOC_REQUIRED")
    # rank 10
    if clock() > D(transaction["quote_expires_at"]):
        fail("ERR_QUOTE_EXPIRED")
    # rank 11
    if (
        selling
        and profile["currency_class"] == "RESTRICTED"
        and transaction["fx_gross_minor_units"] > profile["export_limit_minor_units"]
    ):
        fail("ERR_EXPORT_LIMIT_EXCEEDED")
    if (
        selling
        and profile["currency_class"] == "EXOTIC"
        and not branch_sells_exotic(branch["id"], transaction["currency_code"])
    ):
        fail("ERR_EXOTIC_PLAN_REQUIRED")

    transaction["settlement_status"] = "AUTHORIZED"
    transaction["authorized_at"] = now_str()
    transaction["authorized_by_user_id"] = actor()
    if customer["structuring_risk_tier"] == "HIGH" and transaction["compliance_status"] == "PENDING":
        transaction["compliance_status"] = "FLAGGED"
    touch(transaction)
    return ok(public(transaction))


# ==========================================================================
# Settling
# ==========================================================================
@bp.post("/exchange-transactions/<transaction_id>/settle")
@endpoint(["BranchTeller", "BranchManager"])
def settle_transaction(transaction_id):
    transaction = need("ExchangeTransaction", transaction_id)
    if transaction["settlement_status"] != "AUTHORIZED":
        fail("ERR_TRANSACTION_NOT_AUTHORIZED")
    branch = need("Branch", transaction["branch_id"])
    customer = need("Customer", transaction["customer_id"])
    currency_code = transaction["currency_code"]
    lines = transaction["requested_denominations"]
    selling = transaction["direction"] == "SELL_FX_TO_CUSTOMER"
    # rank 7
    require_not_frozen(branch)
    # rank 8
    if transaction["compliance_status"] == "BLOCKED":
        fail("ERR_TRANSACTION_COMPLIANCE_BLOCKED")
    # the settlement card is re-read at authorized_at, not at the settle instant
    card = calc.effective_published_card(
        branch["id"], currency_code, D(transaction["authorized_at"])
    )
    # rank 9 - dual control needs the settled gross, hence the card
    if card is not None:
        applied_rate = card["sell_rate_micros"] if selling else card["buy_rate_micros"]
        gross = calc.usd_conversion(lines, applied_rate)
        if gross >= DUAL_CONTROL_THRESHOLD_CENTS and actor() == transaction["authorized_by_user_id"]:
            fail("ERR_DUAL_CONTROL_REQUIRED")
    # rank 12
    if card is None:
        fail("ERR_RATE_CARD_NOT_EFFECTIVE")
    # rank 13 - fiscal capacity
    position = calc.branch_position(branch["id"], currency_code)
    if position is None:
        fail("ERR_DENOMINATION_NOT_STOCKED")
    for line in lines:
        entry = calc.mix_entry(position, line["denomination_minor_units"])
        if entry is None:
            fail("ERR_DENOMINATION_NOT_STOCKED")
        if selling and entry["available_note_count"] < line["note_count"]:
            fail("ERR_INSUFFICIENT_INVENTORY")
    if not selling:
        projected = calc.projected_vault_after(
            branch, position, transaction["fx_gross_minor_units"]
        )
        if projected > branch["vault_limit_usd_cents"]:
            fail("ERR_VAULT_LIMIT_WOULD_EXCEED")

    # settlement pricing (applied_rate_micros stays the quote-time rate on the row)
    transaction["settled_usd_gross_cents"] = gross
    transaction["settlement_status"] = "SETTLED"
    transaction["settled_at"] = now_str()
    transaction["settled_by_user_id"] = actor()
    basis = calc.same_day_settled_basis(transaction, gross)
    commission, total = calc.commission_and_total(
        gross, basis, card["commission_schedule_code"], transaction["direction"]
    )
    transaction["settled_commission_cents"] = commission
    transaction["settled_total_charge_cents"] = total
    transaction["price_adjustment_cents"] = total - transaction["quoted_total_charge_cents"]
    touch(transaction)

    # inventory cascade (hops 1-5)
    for line in lines:
        entry = calc.mix_entry(position, line["denomination_minor_units"])
        if selling:
            entry["available_note_count"] -= line["note_count"]
        else:
            entry["available_note_count"] += line["note_count"]
    calc.inventory_cascade(position, branch)
    touch(branch)

    # surveillance cascade
    old_tier, new_tier = calc.recompute_customer_surveillance(customer)
    if new_tier == "HIGH" and old_tier != "HIGH":
        calc.raise_structuring_report(customer, branch["id"], transaction["id"])
    touch(customer)

    # threshold report, independent of both cascades
    if gross >= REPORT_THRESHOLD_CENTS:
        calc.create_report(
            customer["id"],
            branch["id"],
            "THRESHOLD_REPORT",
            transaction["settled_at"],
            transaction["settled_at"],
            gross,
            1,
            triggering_transaction_id=transaction["id"],
        )
    return ok(public(transaction))


# ==========================================================================
# Voiding
# ==========================================================================
@bp.post("/exchange-transactions/<transaction_id>/void")
@endpoint(["BranchTeller", "BranchManager"])
def void_transaction(transaction_id):
    transaction = need("ExchangeTransaction", transaction_id)
    b = body()
    opt_str(b, "void_reason")
    if transaction["settlement_status"] not in ("QUOTED", "AUTHORIZED"):
        fail("ERR_TRANSACTION_NOT_VOIDABLE")
    transaction["settlement_status"] = "VOIDED"
    touch(transaction)
    return ok(public(transaction))


# ==========================================================================
# Reversing
# ==========================================================================
@bp.post("/exchange-transactions/<transaction_id>/reverse")
@endpoint(["BranchManager"])
def reverse_transaction(transaction_id):
    transaction = need("ExchangeTransaction", transaction_id)
    b = body()
    opt_str(b, "reversal_reason")
    if transaction["settlement_status"] != "SETTLED":
        fail("ERR_TRANSACTION_NOT_SETTLED")
    branch = need("Branch", transaction["branch_id"])
    customer = need("Customer", transaction["customer_id"])
    if transaction["compliance_status"] == "BLOCKED":
        fail("ERR_TRANSACTION_COMPLIANCE_BLOCKED")
    if clock() > D(transaction["settled_at"]) + timedelta(hours=REVERSAL_WINDOW_HOURS):
        fail("ERR_REVERSAL_WINDOW_CLOSED")
    if transaction["buyback_contract_id"] is not None:
        fail("ERR_BUYBACK_BLOCKS_REVERSAL")

    transaction["settlement_status"] = "REVERSED"
    transaction["reversed_at"] = now_str()
    touch(transaction)

    selling = transaction["direction"] == "SELL_FX_TO_CUSTOMER"
    position = calc.branch_position(branch["id"], transaction["currency_code"])
    if position is not None:
        for line in transaction["requested_denominations"]:
            entry = calc.ensure_mix_entry(position, line["denomination_minor_units"])
            if selling:
                entry["available_note_count"] += line["note_count"]
            else:
                entry["available_note_count"] -= line["note_count"]
        calc.inventory_cascade(position, branch)
    touch(branch)

    calc.recompute_customer_surveillance(customer)
    touch(customer)

    for report in list(all_rows("ComplianceReport")):
        if (
            report["report_type"] == "THRESHOLD_REPORT"
            and report["triggering_transaction_id"] == transaction["id"]
            and report["status"] == "DRAFT"
        ):
            del S["ComplianceReport"][report["id"]]
    return ok(public(transaction))


# ==========================================================================
# Compliance decisions (axis B)
# ==========================================================================
@bp.post("/exchange-transactions/<transaction_id>/compliance-decision")
@endpoint(["ComplianceOfficer"])
def compliance_decision(transaction_id):
    transaction = need("ExchangeTransaction", transaction_id)
    b = body()
    decision = req_enum(b, "decision", ("CLEAR", "FLAG", "BLOCK"))
    opt_str(b, "decision_note")
    current = transaction["compliance_status"]
    if decision == "FLAG":
        if current != "PENDING":
            fail("ERR_COMPLIANCE_DECISION_FINAL")
        transaction["compliance_status"] = "FLAGGED"
    else:
        if current not in ("PENDING", "FLAGGED"):
            fail("ERR_COMPLIANCE_DECISION_FINAL")
        transaction["compliance_status"] = "CLEARED" if decision == "CLEAR" else "BLOCKED"
    touch(transaction)
    return ok(public(transaction))


# ==========================================================================
# Reads
# ==========================================================================
@bp.get("/exchange-transactions/<transaction_id>")
@endpoint(READERS)
def read_transaction(transaction_id):
    return ok(public(need("ExchangeTransaction", transaction_id)))


@bp.get("/exchange-transactions")
@endpoint(READERS)
def list_transactions():
    return listing(
        "ExchangeTransaction",
        {
            "branch_id": "branch_id",
            "customer_id": "customer_id",
            "rate_card_id": "rate_card_id",
            "buyback_contract_id": "buyback_contract_id",
            "settlement_status": "settlement_status",
            "compliance_status": "compliance_status",
            "direction": "direction",
        },
    )
