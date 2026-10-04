"""Account endpoints: open/get/list, deposits, suspend/resume, close,
escheat notice/remit/claim, and the append-only ledger listing.

Also hosts the shared close_account() service used by the inmate-release
cascade (fee waived, requested_by 'system').
"""

from flask import Blueprint, request

from calc import active_contract, cap_for_facility, refund_payout
from core import (ALL_ROLES, CLOCK, DB, append_ledger, auth, balance_of, body,
                  err, ledger_of, list_response, new_entity, new_group,
                  ok_obj, pub, req_enum, req_int, req_str, settled_totals,
                  touch, apply_filters)

bp = Blueprint("accounts", __name__)

FUNDING_MODELS = ("PREPAID", "COLLECT", "DEBIT")


def account_or_404(account_id):
    account = DB.accounts.get(account_id)
    if account is None:
        err("ERR_ACCOUNT_NOT_FOUND", 404,
            "Account %s does not exist" % account_id)
    return account


def account_pub(account):
    """Serialize with the computed ledger fields (PRD sections 2.5, 3.3).

    retained_fees_cents is derived so the closure-balance partition invariant
    holds at every point: B == refunded + escheated + retained + frozen,
    where the frozen remainder is the ledger balance minus the unclaimed
    bucket (unclaimed money is still physically on the ledger).
    """
    data = pub(account)
    entries = ledger_of(account["id"])
    balance = sum(e["amount_cents"] for e in entries)
    refunded = sum(-e["amount_cents"] for e in entries
                   if e["type"] == "REFUND_PAYOUT")
    escheated = sum(-e["amount_cents"] for e in entries
                    if e["type"] == "ESCHEAT_REMITTANCE")
    data["balance_cents"] = balance
    data["refunded_total_cents"] = refunded
    data["escheated_total_cents"] = escheated
    if account["status"] == "CLOSED" and account["balance_at_closure_cents"] is not None:
        data["retained_fees_cents"] = (account["balance_at_closure_cents"]
                                       - refunded - escheated - balance)
    else:
        data["retained_fees_cents"] = 0
    return data


def close_account(account, fee_waived, requested_by, requested_role):
    """Account CLOSED transition with snapshot and refundable computation.

    Creates a RefundRequest iff refundable > 0; otherwise a single
    CLOSURE_FEE debit of the entire snapshot zeroes the balance.
    """
    now = CLOCK.now()
    closure_balance = balance_of(account["id"])
    facility = DB.facilities.get(account["facility_id"])
    cap = cap_for_facility(facility)
    contract = active_contract(account["facility_id"])
    if fee_waived:
        fee = 0
    elif contract is not None and cap is not None:
        # Charge-time minimum resolved at close time.
        fee = min(contract["closure_fee_cents"], cap["max_ancillary_fee_cents"])
    elif contract is not None:
        fee = contract["closure_fee_cents"]
    else:
        fee = 0
    method = cap["refund_method"] if cap is not None else "SIMPLE_BALANCE"
    payout = refund_payout(method, ledger_of(account["id"]),
                           closure_balance, fee)
    account["status"] = "CLOSED"
    account["closed_at"] = now
    account["balance_at_closure_cents"] = closure_balance
    account["refundable_computed_cents"] = payout
    # Internal: close-time inputs pinned so refund adjudication recomputes
    # with the same formula and inputs even after later cap amendments.
    account["_closure_fee_cents"] = fee
    account["_refund_method"] = method
    if payout > 0:
        request_entity = new_entity()
        request_entity.update({
            "account_id": account["id"],
            "source": "CLOSURE",
            "status": "REQUESTED",
            "requested_amount_cents": closure_balance,
            "computed_payout_cents": None,
            "refund_method_applied": None,
            "requested_by_user_id": requested_by,
            "requested_by_role": requested_role,
            "decided_by_user_id": None,
            "denial_reason": None,
            "paid_by_user_id": None,
            "paid_at": None,
        })
        DB.refunds[request_entity["id"]] = request_entity
        account["latest_refund_request_id"] = request_entity["id"]
    else:
        # Nothing to adjudicate: the whole snapshot is retained.
        append_ledger(account, "CLOSURE_FEE", -closure_balance, None,
                      "Closure fee and retained balance")
    touch(account)
    return account


@bp.post("/comm-services/accounts")
def create_account():
    auth(["PlatformAdmin", "FacilityStaff"])
    data = body()
    model = req_enum(data, "funding_model", FUNDING_MODELS)
    owner_name = req_str(data, "owner_name")
    owner_contact = req_str(data, "owner_contact")
    credit = data.get("collect_credit_limit_cents")
    if model == "COLLECT":
        if credit is None or isinstance(credit, bool) or not isinstance(credit, int):
            err("ERR_INVALID_REQUEST", 400,
                "collect_credit_limit_cents is required for COLLECT accounts")
        credit_limit = credit
    else:
        credit_limit = None  # ignored for PREPAID/DEBIT
    facility_id = req_str(data, "facility_id")
    inmate_id = req_str(data, "inmate_id")
    if facility_id not in DB.facilities:
        err("ERR_FACILITY_NOT_FOUND", 404,
            "Facility %s does not exist" % facility_id)
    if inmate_id not in DB.inmates:
        err("ERR_INMATE_NOT_FOUND", 404,
            "Inmate %s does not exist" % inmate_id)
    entity = new_entity()
    entity.update({
        "facility_id": facility_id,
        "inmate_id": inmate_id,
        "funding_model": model,
        "owner_name": owner_name,
        "owner_contact": owner_contact,
        "collect_credit_limit_cents": credit_limit,
        "status": "ACTIVE",
        "closed_at": None,
        "balance_at_closure_cents": None,
        "refundable_computed_cents": None,
        "latest_refund_request_id": None,
        "unclaimed_balance_cents": 0,
        "unclaimed_since": None,
        "escheat_status": "NONE",
        "escheat_notice_sent_at": None,
    })
    DB.accounts[entity["id"]] = entity
    return ok_obj(account_pub(entity), 201)


@bp.get("/comm-services/accounts/<account_id>")
def get_account(account_id):
    auth(ALL_ROLES)
    return ok_obj(account_pub(account_or_404(account_id)))


@bp.get("/comm-services/accounts")
def list_accounts():
    auth(ALL_ROLES)
    items = apply_filters(DB.accounts.values(),
                          ["facility_id", "inmate_id", "funding_model",
                           "status", "escheat_status"])
    return list_response(items, account_pub)


@bp.post("/comm-services/accounts/<account_id>/deposits")
def create_deposit(account_id):
    user_id, role = auth(["AccountHolder", "FacilityStaff"])
    # Tier 3 ownership: an AccountHolder's X-User-ID is the account id.
    if role == "AccountHolder" and user_id != account_id:
        err("ERR_NOT_RESOURCE_OWNER", 403,
            "AccountHolder may only deposit to their own account")
    data = body()
    amount = req_int(data, "amount_cents", minimum=1)
    account = account_or_404(account_id)
    facility = DB.facilities.get(account["facility_id"])
    if facility is None or facility["status"] != "ACTIVE":
        err("ERR_FACILITY_NOT_ACTIVE", 409,
            "Deposits require an ACTIVE facility")
    if account["status"] != "ACTIVE":
        err("ERR_ACCOUNT_NOT_ACTIVE", 409,
            "Deposits require an ACTIVE account")
    contract = active_contract(facility["id"])
    if contract is None:
        err("ERR_NO_ACTIVE_CONTRACT", 409,
            "Deposits require an ACTIVE contract for the facility")
    cap = cap_for_facility(facility)
    if cap is None:
        fee = contract["deposit_fee_cents"]
    else:
        # Charge-time minimum at deposit time.
        fee = min(contract["deposit_fee_cents"], cap["max_deposit_fee_cents"])
    if amount <= fee:
        # Boundary: amount == fee + 1 is allowed, netting a single cent.
        err("ERR_DEPOSIT_TOO_SMALL", 422,
            "Deposit amount_cents must strictly exceed the deposit fee")
    group = new_group()
    append_ledger(account, "DEPOSIT", amount, None, "Deposit", group)
    append_ledger(account, "DEPOSIT_FEE", -fee, None, "Deposit fee", group)
    # One mutation per request: the account version advances by exactly one
    # regardless of how many ledger rows the deposit appends (PRD 2.5/2.7).
    touch(account)
    return ok_obj(account_pub(account), 201)


@bp.post("/comm-services/accounts/<account_id>/suspend")
def suspend_account(account_id):
    auth(["FacilityStaff"])
    account = account_or_404(account_id)
    if account["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Only an ACTIVE account can be suspended")
    account["status"] = "SUSPENDED"
    touch(account)
    return ok_obj(account_pub(account))


@bp.post("/comm-services/accounts/<account_id>/resume")
def resume_account(account_id):
    auth(["FacilityStaff"])
    account = account_or_404(account_id)
    if account["status"] != "SUSPENDED":
        err("ERR_INVALID_STATE", 409, "Only a SUSPENDED account can be resumed")
    account["status"] = "ACTIVE"
    touch(account)
    return ok_obj(account_pub(account))


@bp.post("/comm-services/accounts/<account_id>/close")
def close_account_route(account_id):
    user_id, role = auth(["AccountHolder", "FacilityStaff"])
    if role == "AccountHolder" and user_id != account_id:
        err("ERR_NOT_RESOURCE_OWNER", 403,
            "AccountHolder may only close their own account")
    account = account_or_404(account_id)
    if account["status"] not in ("ACTIVE", "SUSPENDED"):
        err("ERR_INVALID_STATE", 409,
            "Only an ACTIVE or SUSPENDED account can be closed")
    for call in DB.calls.values():
        if call["account_id"] == account["id"] and call["status"] == "CONNECTED":
            err("ERR_ACCOUNT_HAS_ACTIVE_CALLS", 409,
                "Close blocked: a call is still CONNECTED")
    now = CLOCK.now()
    for session in DB.sessions.values():
        if (session["account_id"] == account["id"]
                and session["status"] == "CONFIRMED"
                and session["scheduled_end"] > now):
            err("ERR_ACCOUNT_HAS_ACTIVE_SESSIONS", 409,
                "Close blocked: a CONFIRMED video session has not ended")
    for message in DB.messages.values():
        if (message["account_id"] == account["id"]
                and message["status"] == "PENDING_REVIEW"):
            err("ERR_ACCOUNT_HAS_PENDING_MESSAGES", 409,
                "Close blocked: a message is still PENDING_REVIEW")
    close_account(account, fee_waived=False,
                  requested_by=user_id, requested_role=role)
    return ok_obj(account_pub(account))


@bp.post("/comm-services/accounts/<account_id>/send-escheat-notice")
def send_escheat_notice(account_id):
    auth(["ComplianceOfficer"])
    account = account_or_404(account_id)
    if account["escheat_status"] != "DORMANT":
        err("ERR_INVALID_STATE", 409,
            "Escheat notice requires escheat_status DORMANT")
    account["escheat_status"] = "NOTICE_SENT"
    account["escheat_notice_sent_at"] = CLOCK.now()
    touch(account)
    return ok_obj(account_pub(account))


@bp.post("/comm-services/accounts/<account_id>/remit-escheat")
def remit_escheat(account_id):
    from datetime import timedelta

    auth(["ComplianceOfficer"])
    account = account_or_404(account_id)
    if account["escheat_status"] != "NOTICE_SENT":
        err("ERR_INVALID_STATE", 409,
            "Escheat remittance requires escheat_status NOTICE_SENT")
    facility = DB.facilities.get(account["facility_id"])
    cap = cap_for_facility(facility)
    window_days = cap["claim_window_days"] if cap is not None else 0
    now = CLOCK.now()
    if now < account["escheat_notice_sent_at"] + timedelta(days=window_days):
        # Boundary: a clock exactly at notice + claim_window_days allows remit.
        err("ERR_CLAIM_WINDOW_OPEN", 409,
            "The claim window is still open for this unclaimed balance")
    unclaimed = account["unclaimed_balance_cents"]
    closure_balance = account["balance_at_closure_cents"] or 0
    refunded_prior, escheated_prior = settled_totals(account["id"])
    append_ledger(account, "ESCHEAT_REMITTANCE", -unclaimed, None,
                  "Escheat remittance to the state")
    settling = -(closure_balance - refunded_prior - escheated_prior - unclaimed)
    append_ledger(account, "CLOSURE_FEE", settling, None,
                  "Settling closure fee on escheat remittance")
    account["unclaimed_balance_cents"] = 0
    account["unclaimed_since"] = None
    account["escheat_status"] = "REMITTED"
    touch(account)
    return ok_obj(account_pub(account))


@bp.post("/comm-services/accounts/<account_id>/claim-unclaimed")
def claim_unclaimed(account_id):
    user_id, role = auth(["AccountHolder"])
    if user_id != account_id:
        err("ERR_NOT_RESOURCE_OWNER", 403,
            "AccountHolder may only claim their own unclaimed balance")
    account = account_or_404(account_id)
    if account["escheat_status"] not in ("DORMANT", "NOTICE_SENT"):
        err("ERR_ESCHEAT_NOT_CLAIMABLE", 409,
            "Unclaimed balance is claimable only from DORMANT or NOTICE_SENT")
    unclaimed = account["unclaimed_balance_cents"]
    # ESCHEAT_CLAIM requests skip adjudication: created already APPROVED.
    request_entity = new_entity()
    request_entity.update({
        "account_id": account["id"],
        "source": "ESCHEAT_CLAIM",
        "status": "APPROVED",
        "requested_amount_cents": unclaimed,
        "computed_payout_cents": unclaimed,
        "refund_method_applied": None,
        "requested_by_user_id": user_id,
        "requested_by_role": role,
        "decided_by_user_id": "system",
        "denial_reason": None,
        "paid_by_user_id": None,
        "paid_at": None,
    })
    DB.refunds[request_entity["id"]] = request_entity
    account["latest_refund_request_id"] = request_entity["id"]
    account["escheat_status"] = "CLAIMED"
    touch(account)
    return ok_obj(account_pub(account))


@bp.get("/comm-services/accounts/<account_id>/ledger")
def get_ledger(account_id):
    auth(ALL_ROLES)
    account_or_404(account_id)
    entries = list(ledger_of(account_id))
    type_filter = request.args.get("type")
    if type_filter is not None:
        entries = [e for e in entries if e["type"] == type_filter]
    # Chronological by created_at ascending (append order breaks ties).
    return list_response(entries, pub)
