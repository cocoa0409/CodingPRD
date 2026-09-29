"""Sale capture: gates, rate selection and dual-variant pricing (PRD 3.9)."""

from decimal import Decimal

from flask import Blueprint

import auth
import calc
import listing
import serialize
import validation as v
from auth import authorize
from envelope import created, ok
from errors import ApiError
from routes_programs import rule_in_effect
from store import db, base_row, touch
from validation import MISSING, as_bool, as_enum, as_int, as_string, field, parse_body, round_cents

bp = Blueprint("transactions", __name__)

CARD_BRANDS = ("VISA", "MASTERCARD", "DISCOVER", "AMEX")
FUNDINGS = ("CREDIT", "DEBIT", "PREPAID")
CAPTURE_TIERS = ("CONSUMER_CREDIT", "COMMERCIAL_CREDIT", "REWARDS_CREDIT", "NOT_APPLICABLE")
OUTCOMES = ("APPROVED_WITH_SURCHARGE", "APPROVED_NO_SURCHARGE", "APPROVED_CASH_DISCOUNT")


def _rank(rule, tier):
    """An exact tier match ranks strictly above a catch-all ALL rule."""
    return 0 if rule["product_tier"] == tier else 1


def _better(candidate, incumbent, tier):
    rank_a, rank_b = _rank(candidate, tier), _rank(incumbent, tier)
    if rank_a != rank_b:
        return rank_a < rank_b
    if candidate["effective_from"] != incumbent["effective_from"]:
        return candidate["effective_from"] > incumbent["effective_from"]
    return (candidate["created_at"], candidate["_seq"]) < (incumbent["created_at"], incumbent["_seq"])


def select_rate_rule(program, card_brand, tier):
    clock = db.now()
    best = None
    for rule in calc.program_rate_rules(program["id"]):
        if rule["brand"] != card_brand:
            continue
        if not rule_in_effect(rule, clock):
            continue
        if rule["product_tier"] != tier and rule["product_tier"] != "ALL":
            continue
        if best is None or _better(rule, best, tier):
            best = rule
    return best


@bp.post("/transactions")
def capture_sale():
    actor = authorize(["TerminalAgent"])
    body, malformed = parse_body()

    # Step 6: terminal identity, before the request-shape step.
    raw_terminal_id = None if malformed else field(body, "terminal_id")
    if isinstance(raw_terminal_id, str) and raw_terminal_id != actor.user_id:
        raise ApiError("ERR_TERMINAL_IDENTITY_MISMATCH")

    if malformed:
        raise v.bad("The request body must be a JSON object.")
    v.require_present(body, ["terminal_id", "program_id", "card_brand", "card_funding",
                            "product_tier", "base_amount_cents", "requested_surcharge_cents",
                            "receipt_line_present"])
    terminal_id = as_string(body["terminal_id"], "terminal_id", 1)
    program_id = as_string(body["program_id"], "program_id", 1)
    card_brand = as_enum(body["card_brand"], "card_brand", CARD_BRANDS)
    card_funding = as_enum(body["card_funding"], "card_funding", FUNDINGS)
    product_tier = as_enum(body["product_tier"], "product_tier", CAPTURE_TIERS)
    base_amount_cents = as_int(body["base_amount_cents"], "base_amount_cents", 1, 100000000)
    requested_surcharge_cents = as_int(body["requested_surcharge_cents"],
                                      "requested_surcharge_cents", 0, 100000000)
    receipt_line_present = as_bool(body["receipt_line_present"], "receipt_line_present")

    if card_funding == "CREDIT":
        if product_tier == "NOT_APPLICABLE":
            raise v.bad("product_tier must name a credit tier when card_funding is CREDIT.")
    else:
        if product_tier != "NOT_APPLICABLE":
            raise v.bad("product_tier must be NOT_APPLICABLE when card_funding is not CREDIT.")

    term = auth.get_terminal(terminal_id)
    program = auth.get_program(program_id)

    # Step 14
    if term["state"] != "ENFORCING":
        raise ApiError("ERR_INVALID_TERMINAL_STATE",
                       "Only an ENFORCING terminal may book a sale.")

    jur = db.jurisdictions.get(program["jurisdiction_id"])

    # Step 16
    if program["program_type"] == "SURCHARGE" and not (jur and jur["surcharge_permitted"]):
        raise ApiError("ERR_SURCHARGE_PROHIBITED_JURISDICTION",
                       "Credit-card surcharging is not permitted in this jurisdiction.")

    # Step 18
    if card_funding in ("DEBIT", "PREPAID") and requested_surcharge_cents > 0:
        raise ApiError("ERR_DEBIT_SURCHARGE_FORBIDDEN",
                       "A debit or prepaid sale may never carry a requested surcharge.")

    # Step 20
    if program["status"] in ("DISABLED", "WITHDRAWN"):
        raise ApiError("ERR_PROGRAM_DISABLED_BY_PROHIBITION",
                       "The program is disabled or withdrawn and can book no sales.")

    # Step 21
    if term.get("program_id") != program["id"]:
        raise ApiError("ERR_TERMINAL_PROGRAM_MISMATCH",
                       "The terminal is not configured for the named program.")

    # Step 34: rate selection, with the credit-only guard on a surcharge program.
    applied_rate_pct = Decimal(0)
    if program["program_type"] == "SURCHARGE" and card_funding != "CREDIT":
        applied_rate_pct = Decimal(0)
    else:
        rule = select_rate_rule(program, card_brand, product_tier)
        if rule is None:
            raise ApiError("ERR_NO_RATE_RULE_IN_EFFECT",
                           "No rate rule of this program covers the presented card at the clock.")
        applied_rate_pct = Decimal(rule["rate_pct"])

    # Pricing
    if program["program_type"] == "SURCHARGE" and card_funding == "CREDIT":
        surcharge_amount_cents = round_cents(
            Decimal(base_amount_cents) * applied_rate_pct / Decimal(100))
        cash_discount_amount_cents = 0
        cash_price_cents = base_amount_cents
        total_amount_cents = base_amount_cents + surcharge_amount_cents
        outcome = "APPROVED_WITH_SURCHARGE"
    elif program["program_type"] == "SURCHARGE":
        surcharge_amount_cents = 0
        cash_discount_amount_cents = 0
        cash_price_cents = base_amount_cents
        total_amount_cents = base_amount_cents
        outcome = "APPROVED_NO_SURCHARGE"
    else:
        surcharge_amount_cents = 0
        cash_discount_amount_cents = round_cents(
            Decimal(base_amount_cents) * applied_rate_pct / Decimal(100))
        cash_price_cents = base_amount_cents - cash_discount_amount_cents
        total_amount_cents = base_amount_cents
        outcome = "APPROVED_CASH_DISCOUNT"

    # Step 35
    if jur is not None and jur["receipt_line_item_required"] and surcharge_amount_cents > 0:
        if not receipt_line_present:
            raise ApiError("ERR_RECEIPT_LINE_ITEM_REQUIRED",
                           "A surcharged sale must print the surcharge as its own receipt line.")

    # Step 37
    if requested_surcharge_cents != surcharge_amount_cents:
        raise ApiError("ERR_SURCHARGE_AMOUNT_MISMATCH",
                       "requested_surcharge_cents %d disagrees with the server's %d."
                       % (requested_surcharge_cents, surcharge_amount_cents))

    row = base_row(kind_common=False)
    row.update({
        "terminal_id": term["id"],
        "program_id": program["id"],
        "card_brand": card_brand,
        "card_funding": card_funding,
        "product_tier": product_tier,
        "base_amount_cents": base_amount_cents,
        "requested_surcharge_cents": requested_surcharge_cents,
        "receipt_line_present": receipt_line_present,
        "applied_rate_pct": applied_rate_pct,
        "surcharge_amount_cents": surcharge_amount_cents,
        "cash_discount_amount_cents": cash_discount_amount_cents,
        "cash_price_cents": cash_price_cents,
        "total_amount_cents": total_amount_cents,
        "outcome": outcome,
        "occurred_at": db.now(),
    })
    db.transactions[row["id"]] = row

    merchant = db.merchants.get(term["merchant_id"])
    if merchant is not None:
        touch(merchant)

    return created(serialize.transaction(row))


@bp.get("/transactions/<transaction_id>")
def read_transaction(transaction_id):
    authorize(auth.READ_ROLES)
    return ok(serialize.transaction(auth.get_transaction(transaction_id)))


@bp.get("/transactions")
def list_transactions():
    authorize(auth.READ_ROLES)
    rows = listing.filtered(list(db.transactions.values()), [
        (listing.arg("terminal_id"), "terminal_id"),
        (listing.arg("program_id"), "program_id"),
        (listing.enum_arg("outcome", OUTCOMES), "outcome"),
    ])
    return listing.list_response(rows, serialize.transaction)
