"""TabletMessage endpoints: create (charged immediately, PENDING_REVIEW),
get/list, and content review (APPROVE delivers; REJECT refunds exactly).

The charge/refund pair nets to zero on the ledger, preserving the
message-charge-refund conservation invariant of PRD section 2.10.
"""

from flask import Blueprint

from calc import (active_contract, active_schedule, can_cover,
                  cap_for_facility)
from core import (ALL_ROLES, CLOCK, DB, append_ledger, auth, body, err,
                  list_response, new_entity, ok_obj, opt_str, pub, req_enum,
                  req_str, touch, apply_filters)

bp = Blueprint("messages", __name__)

MAX_BODY_CHARS = 1000


def message_or_404(message_id):
    message = DB.messages.get(message_id)
    if message is None:
        err("ERR_MESSAGE_NOT_FOUND", 404,
            "TabletMessage %s does not exist" % message_id)
    return message


@bp.post("/comm-services/messages")
def create_message():
    user_id, role = auth(["AccountHolder"])
    data = body()
    account_id = req_str(data, "account_id")
    # Tier 3 ownership: messages are sent by the AccountHolder of record.
    if user_id != account_id:
        err("ERR_NOT_RESOURCE_OWNER", 403,
            "AccountHolder may only message from their own account")
    body_text = req_str(data, "body_text")
    if len(body_text) > MAX_BODY_CHARS:
        err("ERR_MESSAGE_TOO_LONG", 422,
            "Message body exceeds 1000 characters")
    inmate_id = req_str(data, "inmate_id")
    # Tier 5: body FKs in declared input order (account_id, inmate_id, ...).
    account = DB.accounts.get(account_id)
    if account is None:
        err("ERR_ACCOUNT_NOT_FOUND", 404,
            "Account %s does not exist" % account_id)
    inmate = DB.inmates.get(inmate_id)
    if inmate is None:
        err("ERR_INMATE_NOT_FOUND", 404,
            "Inmate %s does not exist" % inmate_id)
    # Tier 6 state gates.
    facility = DB.facilities.get(account["facility_id"])
    if facility is None or facility["status"] != "ACTIVE":
        err("ERR_FACILITY_NOT_ACTIVE", 409,
            "Messages require an ACTIVE facility")
    if account["status"] != "ACTIVE":
        err("ERR_ACCOUNT_NOT_ACTIVE", 409,
            "Messages require an ACTIVE account")
    if inmate["status"] != "IN_CUSTODY":
        err("ERR_INMATE_NOT_IN_CUSTODY", 409,
            "Messages require the inmate to be IN_CUSTODY")
    contract = active_contract(facility["id"])
    schedule = active_schedule(contract["id"]) if contract is not None else None
    if schedule is None:
        err("ERR_NO_ACTIVE_RATE_SCHEDULE", 409,
            "Message creation requires the contract's ACTIVE rate schedule")
    # Tier 10: binding, then fiscal sufficiency.
    if account["inmate_id"] != inmate_id:
        err("ERR_ACCOUNT_INMATE_MISMATCH", 409,
            "account.inmate_id does not match the supplied inmate_id")
    cap = cap_for_facility(facility)
    price = schedule["message_price_cents"]
    if cap is not None:
        # Charge-time minimum at creation time.
        price = min(price, cap["max_ancillary_fee_cents"])
    if not can_cover(account, price):
        err("ERR_INSUFFICIENT_BALANCE", 402,
            "Account cannot cover the message price")
    entity = new_entity()
    entity.update({
        "account_id": account_id,
        "inmate_id": inmate_id,
        "facility_id": account["facility_id"],
        "body_text": body_text,
        "price_cents": price,
        "status": "PENDING_REVIEW",
        "reviewed_by_user_id": None,
        "review_note": None,
        "reviewed_at": None,
    })
    DB.messages[entity["id"]] = entity
    append_ledger(account, "MESSAGE_CHARGE", -price, entity["id"],
                  "Tablet message charge")
    # The charge mutates the account (balance); one version advance.
    touch(account)
    return ok_obj(pub(entity), 201)


@bp.get("/comm-services/messages/<message_id>")
def get_message(message_id):
    auth(ALL_ROLES)
    return ok_obj(pub(message_or_404(message_id)))


@bp.get("/comm-services/messages")
def list_messages():
    auth(ALL_ROLES)
    items = apply_filters(DB.messages.values(),
                          ["account_id", "inmate_id", "facility_id", "status"])
    return list_response(items, pub)


@bp.post("/comm-services/messages/<message_id>/review")
def review_message(message_id):
    user_id, role = auth(["FacilityStaff"])
    data = body()
    decision = req_enum(data, "decision", ("APPROVE", "REJECT"))
    review_note = opt_str(data, "review_note")
    message = message_or_404(message_id)
    if message["status"] != "PENDING_REVIEW":
        err("ERR_INVALID_STATE", 409,
            "Only a PENDING_REVIEW message can be reviewed")
    message["reviewed_by_user_id"] = user_id
    message["review_note"] = review_note
    message["reviewed_at"] = CLOCK.now()
    if decision == "APPROVE":
        message["status"] = "DELIVERED"  # the MESSAGE_CHARGE stands
    else:
        message["status"] = "REJECTED"
        account = DB.accounts.get(message["account_id"])
        if account is not None:
            # Exact reversal of the creation charge.
            append_ledger(account, "MESSAGE_REFUND", message["price_cents"],
                          message["id"], "Message rejection refund")
            # The refund mutates the account (balance); one version advance.
            touch(account)
    touch(message)
    return ok_obj(pub(message))
