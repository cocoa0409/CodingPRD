"""Inmate endpoints: booking, get/list, and the release cascade.

The release cascade runs in the PRD-pinned order: (1) cancel future
REQUESTED/CONFIRMED video sessions with VIDEO_REFUND for confirmed ones,
(2) reject PENDING_REVIEW messages with MESSAGE_REFUND, (3) only then
auto-close ACTIVE DEBIT accounts with the closure fee waived, so the refunds
from steps 1-2 land inside the closure snapshot.
"""

from flask import Blueprint

from core import (ALL_ROLES, CLOCK, DB, append_ledger, auth, body, err,
                  list_response, new_entity, ok_obj, opt_str, pub, req_str,
                  touch, apply_filters)
from routes_accounts import close_account

bp = Blueprint("inmates", __name__)


def inmate_or_404(inmate_id):
    inmate = DB.inmates.get(inmate_id)
    if inmate is None:
        err("ERR_INMATE_NOT_FOUND", 404,
            "Inmate %s does not exist" % inmate_id)
    return inmate


@bp.post("/comm-services/inmates")
def create_inmate():
    auth(["FacilityStaff"])
    data = body()
    booking_number = req_str(data, "booking_number")
    full_name = req_str(data, "full_name")
    housing_unit = opt_str(data, "housing_unit")
    facility_id = req_str(data, "facility_id")
    if facility_id not in DB.facilities:
        err("ERR_FACILITY_NOT_FOUND", 404,
            "Facility %s does not exist" % facility_id)
    for other in DB.inmates.values():
        if (other["facility_id"] == facility_id
                and other["booking_number"] == booking_number
                and other["status"] == "IN_CUSTODY"):
            err("ERR_DUPLICATE_BOOKING_NUMBER", 409,
                "booking_number %s is in use by an IN_CUSTODY inmate of this "
                "facility" % booking_number)
    entity = new_entity()
    entity.update({
        "facility_id": facility_id,
        "booking_number": booking_number,
        "full_name": full_name,
        "housing_unit": housing_unit,
        "status": "IN_CUSTODY",
        "released_at": None,
    })
    DB.inmates[entity["id"]] = entity
    return ok_obj(pub(entity), 201)


@bp.get("/comm-services/inmates/<inmate_id>")
def get_inmate(inmate_id):
    auth(ALL_ROLES)
    return ok_obj(pub(inmate_or_404(inmate_id)))


@bp.get("/comm-services/inmates")
def list_inmates():
    auth(ALL_ROLES)
    items = apply_filters(DB.inmates.values(), ["facility_id", "status"])
    return list_response(items, pub)


@bp.post("/comm-services/inmates/<inmate_id>/release")
def release_inmate(inmate_id):
    auth(["FacilityStaff"])
    inmate = inmate_or_404(inmate_id)
    if inmate["status"] != "IN_CUSTODY":
        err("ERR_INVALID_STATE", 409, "Only an IN_CUSTODY inmate can be released")
    now = CLOCK.now()
    inmate["status"] = "RELEASED"
    inmate["released_at"] = now
    touch(inmate)

    # CASCADE STEP 1: cancel the inmate's future REQUESTED/CONFIRMED video
    # sessions; confirmed ones are refunded in full. The cascade bypasses the
    # not-yet-started cancel guard (it only fires on future sessions anyway).
    refunded_account_ids = set()
    sessions = sorted(
        (s for s in DB.sessions.values()
         if s["inmate_id"] == inmate["id"]
         and s["status"] in ("REQUESTED", "CONFIRMED")
         and s["scheduled_start"] > now),
        key=lambda s: s["_seq"])
    for session in sessions:
        was_confirmed = session["status"] == "CONFIRMED"
        session["status"] = "CANCELLED"
        session["cancelled_at"] = now
        touch(session)
        if was_confirmed:
            account = DB.accounts.get(session["account_id"])
            if account is not None:
                append_ledger(account, "VIDEO_REFUND", session["charge_cents"],
                              session["id"],
                              "Video session refund (inmate release)")
                refunded_account_ids.add(account["id"])

    # CASCADE STEP 2: reject the inmate's PENDING_REVIEW messages with an
    # exact MESSAGE_REFUND reversal.
    messages = sorted(
        (m for m in DB.messages.values()
         if m["inmate_id"] == inmate["id"] and m["status"] == "PENDING_REVIEW"),
        key=lambda m: m["_seq"])
    for message in messages:
        message["status"] = "REJECTED"
        message["reviewed_by_user_id"] = "system"
        message["review_note"] = None
        message["reviewed_at"] = now
        touch(message)
        account = DB.accounts.get(message["account_id"])
        if account is not None:
            append_ledger(account, "MESSAGE_REFUND", message["price_cents"],
                          message["id"], "Message refund (inmate release)")
            refunded_account_ids.add(account["id"])

    # CASCADE STEP 3 (strictly after steps 1-2): auto-close every ACTIVE
    # DEBIT account of the inmate, closure fee waived, initiated by 'system'.
    # PREPAID and COLLECT accounts are unaffected by a release.
    accounts = sorted(
        (a for a in DB.accounts.values()
         if a["inmate_id"] == inmate["id"]
         and a["funding_model"] == "DEBIT"
         and a["status"] == "ACTIVE"),
        key=lambda a: a["_seq"])
    closed_account_ids = set()
    for account in accounts:
        close_account(account, fee_waived=True,
                      requested_by="system", requested_role="system")
        closed_account_ids.add(account["id"])

    # Each account mutated by the cascade refunds but not auto-closed in
    # step 3 advances its version once for this release request (PRD 2.5);
    # closed accounts already advanced exactly once inside close_account.
    for account_id in refunded_account_ids - closed_account_ids:
        account = DB.accounts.get(account_id)
        if account is not None:
            touch(account)

    return ok_obj(pub(inmate))
