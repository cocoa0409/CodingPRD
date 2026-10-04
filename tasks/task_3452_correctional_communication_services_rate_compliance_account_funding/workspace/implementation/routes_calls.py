"""CallRecord endpoints: connect (pinning charge-time-minimum applied rates
and the recording exemption) and end (billing with affordability cutoff).

Validation follows the PRD section 2.8 tier order: shape -> existence (body
FKs in declared input order) -> state gates -> recipient consent/protection
-> account-inmate binding -> fiscal sufficiency. ERR_NUMBER_BLOCKED therefore
outranks ERR_INSUFFICIENT_BALANCE when both apply.
"""

from flask import Blueprint

from calc import (active_contract, active_schedule, can_cover,
                  cap_for_facility, end_call_charges)
from core import (ALL_ROLES, CLOCK, DB, append_ledger, auth, balance_of, body,
                  err, list_response, new_entity, ok_obj, pub, req_enum,
                  req_int, req_str, touch, apply_filters)

bp = Blueprint("calls", __name__)

CALL_TYPES = ("LOCAL", "INTRASTATE", "INTERSTATE", "INTERNATIONAL")

_RATE_FIELD = {
    "LOCAL": "local_per_minute_cents",
    "INTRASTATE": "intrastate_per_minute_cents",
    "INTERSTATE": "interstate_per_minute_cents",
    "INTERNATIONAL": "international_per_minute_cents",
}


def call_or_404(call_id):
    call = DB.calls.get(call_id)
    if call is None:
        err("ERR_CALL_NOT_FOUND", 404, "CallRecord %s does not exist" % call_id)
    return call


@bp.post("/comm-services/calls")
def connect_call():
    auth(["FacilityStaff"])
    data = body()
    call_type = req_enum(data, "call_type", CALL_TYPES)
    account_id = req_str(data, "account_id")
    inmate_id = req_str(data, "inmate_id")
    recipient_number_id = req_str(data, "recipient_number_id")
    # Tier 5: body foreign keys resolve in the endpoint's declared input order.
    account = DB.accounts.get(account_id)
    if account is None:
        err("ERR_ACCOUNT_NOT_FOUND", 404,
            "Account %s does not exist" % account_id)
    inmate = DB.inmates.get(inmate_id)
    if inmate is None:
        err("ERR_INMATE_NOT_FOUND", 404,
            "Inmate %s does not exist" % inmate_id)
    recipient = DB.recipients.get(recipient_number_id)
    if recipient is None:
        err("ERR_RECIPIENT_NUMBER_NOT_FOUND", 404,
            "RecipientNumber %s does not exist" % recipient_number_id)
    # Tier 6: state gates.
    facility = DB.facilities.get(account["facility_id"])
    if facility is None or facility["status"] != "ACTIVE":
        err("ERR_FACILITY_NOT_ACTIVE", 409,
            "Calls require an ACTIVE facility")
    if account["status"] != "ACTIVE":
        err("ERR_ACCOUNT_NOT_ACTIVE", 409, "Calls require an ACTIVE account")
    if inmate["status"] != "IN_CUSTODY":
        err("ERR_INMATE_NOT_IN_CUSTODY", 409,
            "Calls require the inmate to be IN_CUSTODY")
    contract = active_contract(facility["id"])
    schedule = active_schedule(contract["id"]) if contract is not None else None
    if schedule is None:
        err("ERR_NO_ACTIVE_RATE_SCHEDULE", 409,
            "Call connect requires the contract's ACTIVE rate schedule")
    # Tier 7: recipient consent and protection (outranks fiscal failures).
    if recipient["verification_status"] != "VERIFIED":
        err("ERR_NUMBER_NOT_VERIFIED", 409,
            "Recipient number is not VERIFIED")
    if recipient["block_status"] == "BLOCKED":
        err("ERR_NUMBER_BLOCKED", 409, "Recipient number is BLOCKED")
    # Tier 10: account-inmate binding, then fiscal sufficiency.
    if account["inmate_id"] != inmate_id:
        err("ERR_ACCOUNT_INMATE_MISMATCH", 409,
            "account.inmate_id does not match the supplied inmate_id")
    cap = cap_for_facility(facility)
    max_rate = cap["max_per_minute_cents"] if cap is not None else None
    max_conn = cap["max_connection_fee_cents"] if cap is not None else None
    applied_rate = schedule[_RATE_FIELD[call_type]]
    if max_rate is not None:
        applied_rate = min(applied_rate, max_rate)
    applied_conn = schedule["connection_fee_cents"]
    if max_conn is not None:
        applied_conn = min(applied_conn, max_conn)
    # Connect requires covering at least the connection fee plus one minute.
    if not can_cover(account, applied_conn + applied_rate):
        err("ERR_INSUFFICIENT_BALANCE", 402,
            "Account cannot cover the connection fee plus one minute")
    entity = new_entity()
    entity.update({
        "account_id": account_id,
        "inmate_id": inmate_id,
        "facility_id": account["facility_id"],
        "recipient_number_id": recipient_number_id,
        "rate_schedule_id": schedule["id"],
        "call_type": call_type,
        "status": "CONNECTED",
        "applied_per_minute_cents": applied_rate,
        "applied_connection_fee_cents": applied_conn,
        "connected_at": CLOCK.now(),
        "ended_at": None,
        "duration_seconds": None,
        "billable_minutes": None,
        "total_charge_cents": None,
        "cutoff_reason": "NONE",
        # Attorney-privilege recording exemption resolved at connect time.
        "recording_status": ("EXEMPT_PRIVILEGED"
                             if recipient["privilege_status"] == "PRIVILEGED"
                             else "RECORDED"),
        # Internal: affordability at end is judged against this snapshot.
        "_balance_at_connect": balance_of(account_id),
    })
    DB.calls[entity["id"]] = entity
    return ok_obj(pub(entity), 201)


@bp.get("/comm-services/calls/<call_id>")
def get_call(call_id):
    auth(ALL_ROLES)
    return ok_obj(pub(call_or_404(call_id)))


@bp.get("/comm-services/calls")
def list_calls():
    auth(ALL_ROLES)
    items = apply_filters(DB.calls.values(),
                          ["account_id", "inmate_id", "facility_id",
                           "recipient_number_id", "rate_schedule_id", "status"])
    return list_response(items, pub)


@bp.post("/comm-services/calls/<call_id>/end")
def end_call(call_id):
    auth(["FacilityStaff"])
    data = body()
    duration = req_int(data, "duration_seconds", minimum=0)
    call = call_or_404(call_id)
    if call["status"] != "CONNECTED":
        err("ERR_INVALID_STATE", 409, "Only a CONNECTED call can be ended")
    account = DB.accounts.get(call["account_id"])
    status, billable, total, cutoff = end_call_charges(call, account, duration)
    call["status"] = status
    call["ended_at"] = CLOCK.now()
    call["duration_seconds"] = duration
    call["billable_minutes"] = billable
    call["total_charge_cents"] = total
    call["cutoff_reason"] = cutoff
    touch(call)
    if status == "COMPLETED" and total > 0:
        # A zero duration routes to NOT_CONNECTED and appends no ledger entry.
        append_ledger(account, "CALL_CHARGE", -total, call["id"],
                      "Call charge (%d billable minutes)" % billable)
        # The charge mutates the account (balance); one version advance.
        touch(account)
    return ok_obj(pub(call))
