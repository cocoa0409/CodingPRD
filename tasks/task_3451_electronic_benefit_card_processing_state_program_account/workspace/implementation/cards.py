"""Card lifecycle: issuance, activation, PIN, replacement with fee waterfall."""
from flask import Blueprint

from errors import ApiError
from state import DB, new_id
from domain import (
    new_entity, touch, post_entry, ser_card, case_purse_by_type,
    spendable_balance, replacements_in_window,
)
from util import authed, body, req_str, ok_object, cardholder_owns

bp = Blueprint("cards", __name__, url_prefix="/ebt")


def get_card(cid):
    c = DB.cards.get(cid)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", "card not found")
    return c


def _mint_pan():
    return "pan_" + new_id()


@bp.post("/cards")
def issue_card():
    authed(["CardholderServices"])
    b = body()
    case_id = req_str(b, "case_account_id")
    case = DB.cases.get(case_id)
    if case is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "case_account_id does not exist")
    if case["account_status"] != "OPEN":
        raise ApiError("ERR_CASE_NOT_OPEN", "card issuance requires the case OPEN")
    card = new_entity()
    card.update({
        "case_account_id": case_id,
        "pan_token": _mint_pan(),
        "card_status": "ISSUED",
        "pin_secret": None,
        "pin_fail_count": 0,
        "replacement_of_card_id": None,
        "fee_charged_cents": None,
        "fee_waived": False,
        "mailed_at": None,
        "activated_at": None,
    })
    DB.cards[card["id"]] = card
    return ok_object(ser_card(card), 201)


@bp.get("/cards/<cid>")
def read_card(cid):
    role, uid = authed(["StateAdmin", "CardholderServices", "Cardholder"])
    card = get_card(cid)
    cardholder_owns(role, uid, card["case_account_id"])
    return ok_object(ser_card(card))


@bp.post("/cards/<cid>/activate")
def activate_card(cid):
    role, uid = authed(["Cardholder", "CardholderServices"])
    card = get_card(cid)
    cardholder_owns(role, uid, card["case_account_id"])
    b = body()
    if card["card_status"] not in ("ISSUED", "MAILED"):
        raise ApiError("ERR_INVALID_STATE",
                       f"cannot activate a card in {card['card_status']}")
    case = DB.cases[card["case_account_id"]]
    if case["account_status"] != "OPEN":
        raise ApiError("ERR_CASE_NOT_OPEN", "card activation requires the case OPEN")
    if card["card_status"] != "MAILED":
        raise ApiError("ERR_CARD_NOT_MAILED", "card is not yet MAILED")
    pin = req_str(b, "pin")
    import util
    card["card_status"] = "ACTIVE"
    card["pin_secret"] = pin
    card["pin_fail_count"] = 0
    card["activated_at"] = util.now_dt()
    touch(card)
    return ok_object(ser_card(card))


@bp.post("/cards/<cid>/replace")
def replace_card(cid):
    role, uid = authed(["Cardholder", "CardholderServices"])
    card = get_card(cid)
    cardholder_owns(role, uid, card["case_account_id"])
    case = DB.cases[card["case_account_id"]]
    if case["account_status"] != "OPEN":
        raise ApiError("ERR_CASE_NOT_OPEN", "card replacement requires the case OPEN")
    if card["card_status"] not in ("ACTIVE", "PIN_LOCKED"):
        raise ApiError("ERR_REPLACEMENT_NOT_ALLOWED",
                       "only ACTIVE or PIN_LOCKED cards may be replaced")
    contract = DB.contracts[case["contract_id"]]
    # Free allowance is evaluated against replacements BEFORE this new card.
    prior_replacements = replacements_in_window(case["id"])
    card["card_status"] = "REPLACED"
    touch(card)
    new_card = new_entity()
    new_card.update({
        "case_account_id": case["id"],
        "pan_token": _mint_pan(),
        "card_status": "ISSUED",
        "pin_secret": None,
        "pin_fail_count": 0,
        "replacement_of_card_id": card["id"],
        "fee_charged_cents": None,
        "fee_waived": False,
        "mailed_at": None,
        "activated_at": None,
    })
    DB.cards[new_card["id"]] = new_card
    # replacement_fee_assessment, pinned order
    if prior_replacements < contract["free_replacements_per_365d"]:
        new_card["fee_charged_cents"] = 0
        new_card["fee_waived"] = False
        return ok_object(ser_card(new_card), 201)
    absorbed = False
    for ptype in ("CASH", "FOOD"):
        purse = case_purse_by_type(case["id"], ptype)
        if purse is None:
            continue
        prog = DB.programs[purse["program_id"]]
        fee = prog["replacement_fee_cents"] if prog["replacement_fee_cents"] is not None \
            else contract["default_replacement_fee_cents"]
        if purse["purse_status"] == "FROZEN":
            continue  # a FROZEN purse cannot absorb the fee; move on
        if spendable_balance(purse["id"]) >= fee:
            if fee > 0:
                post_entry(purse["id"], "FEE_DEBIT", fee,
                           reference_id=new_card["id"], memo="replacement fee")
            new_card["fee_charged_cents"] = fee
            new_card["fee_waived"] = False
            absorbed = True
            break
    if not absorbed:
        new_card["fee_charged_cents"] = 0
        new_card["fee_waived"] = True
    return ok_object(ser_card(new_card), 201)


@bp.post("/cards/<cid>/pin-reset")
def pin_reset(cid):
    role, uid = authed(["Cardholder", "CardholderServices"])
    card = get_card(cid)
    cardholder_owns(role, uid, card["case_account_id"])
    if card["card_status"] not in ("ACTIVE", "PIN_LOCKED"):
        raise ApiError("ERR_REPLACEMENT_NOT_ALLOWED",
                       "PIN reset allowed only on ACTIVE or PIN_LOCKED cards")
    b = body()
    new_pin = req_str(b, "new_pin")
    if role == "Cardholder":
        current_pin = req_str(b, "current_pin")
        if card["pin_secret"] is None or current_pin != card["pin_secret"]:
            _register_pin_failure(card)
            raise ApiError("ERR_PIN_MISMATCH", "current_pin does not match")
    card["pin_secret"] = new_pin
    card["pin_fail_count"] = 0
    if card["card_status"] == "PIN_LOCKED":
        card["card_status"] = "ACTIVE"
    touch(card)
    return ok_object(ser_card(card))


def _register_pin_failure(card):
    card["pin_fail_count"] += 1
    case = DB.cases[card["case_account_id"]]
    contract = DB.contracts[case["contract_id"]]
    if card["pin_fail_count"] >= contract["pin_max_failures"] \
            and card["card_status"] == "ACTIVE":
        card["card_status"] = "PIN_LOCKED"
    touch(card)
