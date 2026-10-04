"""TransactionRequest routes: draft, submission, approval chain and terminal escapes."""
from datetime import timedelta

from core import auth, calc, domain
from core.db import DB, new_common, serialize, touch, utcnow
from core.errors import ApiError
from core.response import ok

from routes.registry import (body, lookup, paginated_ok, req, route, validate)

REQUEST_TYPES = ("RENEWAL", "NEW_LEASE", "RESTRUCTURE", "DISPOSITION")
FINANCE_ROLES = ["AccountExecutive", "TransactionManager", "ApprovalAuthority",
                 "GovernanceManager"]
TM_ONLY = ["TransactionManager"]

APPROVE_TOKENS = ("APPROVE", "APPROVED", "YES", "ACCEPT", "ACCEPTED")
REJECT_TOKENS = ("REJECT", "REJECTED", "NO", "DECLINE", "DECLINED")


@route("POST", "/api/transaction-requests", "create_transaction_request", TM_ONLY, 201)
def create_transaction_request():
    data = validate(body(), [req("account_id"), req("lease_id"), req("request_type"),
                             req("prior_rent_cents_per_year"),
                             req("proposed_rent_cents_per_year"),
                             req("requested_term_months"),
                             req("third_party_commission_cents")])
    account = lookup("accounts", data.get("account_id"), "account")
    lease = lookup("leases", data.get("lease_id"), "lease")
    domain.lifecycle_gate(account, "create_transaction_request")
    request_type = data["request_type"]
    if request_type not in REQUEST_TYPES:
        raise ApiError("ERR_INVALID_REQUEST",
                       "request_type must be one of %s." % ", ".join(REQUEST_TYPES))
    prior = data["prior_rent_cents_per_year"]
    proposed = data["proposed_rent_cents_per_year"]
    for field, value in (("prior_rent_cents_per_year", prior),
                         ("proposed_rent_cents_per_year", proposed)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ApiError("ERR_INVALID_REQUEST", "%s must be at least 1." % field)
    term = data["requested_term_months"]
    if isinstance(term, bool) or not isinstance(term, int):
        raise ApiError("ERR_INVALID_REQUEST", "requested_term_months must be an integer.")
    commission = data["third_party_commission_cents"]
    if isinstance(commission, bool) or not isinstance(commission, int) or commission < 0:
        raise ApiError("ERR_INVALID_REQUEST",
                       "third_party_commission_cents may not be negative.")
    credit = data.get("has_commission_credit", False)
    if credit is None:
        credit = False
    if not isinstance(credit, bool):
        raise ApiError("ERR_INVALID_REQUEST", "has_commission_credit must be a boolean.")
    obj = new_common()
    obj.update({
        "account_id": account["id"],
        "lease_id": lease["id"],
        "request_type": request_type,
        "request_state": "DRAFT",
        "required_approval_level": None,
        "prior_rent_cents_per_year": prior,
        "proposed_rent_cents_per_year": proposed,
        "requested_term_months": term,
        "third_party_commission_cents": commission,
        "has_commission_credit": credit,
        "savings_provisional_cents": 0,
        "savings_final_cents": 0,
    })
    DB.insert("transaction_requests", obj)
    return ok(serialize(obj), 201)


@route("GET", "/api/transaction-requests", "list_transaction_requests", FINANCE_ROLES)
def list_transaction_requests():
    rows = DB.ordered("transaction_requests")
    args = __import__("flask").request.args
    if args.get("account_id"):
        rows = [r for r in rows if r.get("account_id") == args.get("account_id")]
    if args.get("lease_id"):
        rows = [r for r in rows if r.get("lease_id") == args.get("lease_id")]
    return paginated_ok(rows)


@route("GET", "/api/transaction-requests/<request_id>", "get_transaction_request",
       FINANCE_ROLES)
def get_transaction_request(request_id):
    return ok(serialize(lookup("transaction_requests", request_id, "transaction request")))


def _lease_overdue_guard(lease):
    if lease is None:
        return
    end = lease.get("lease_end_date")
    if end is None or end > DB.clock:
        return
    if lease.get("pipeline_state") in ("EXECUTED", "REJECTED"):
        return
    for other in DB.children("leases", lease.get("account_id")):
        if other["id"] == lease["id"]:
            continue
        if other.get("market_code") != lease.get("market_code"):
            continue
        o_end = other.get("lease_end_date")
        if o_end is not None and o_end <= DB.clock:
            raise ApiError("ERR_LEASE_OVERDUE",
                           "The lease is overdue while an expired lease exists on the market.")


@route("POST", "/api/transaction-requests/<request_id>/submit",
       "submit_transaction_request", TM_ONLY)
def submit_transaction_request(request_id):
    obj = lookup("transaction_requests", request_id, "transaction request")
    account = lookup("accounts", obj.get("account_id"), "account")
    if obj.get("request_state") != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT request may be submitted.")
    if account.get("lifecycle_state") != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE",
                       "Submission requires an ACTIVE account.")
    lease = DB.get("leases", obj.get("lease_id"))
    _lease_overdue_guard(lease)
    if lease is not None:
        end = lease.get("lease_end_date")
        if end is not None and not end > DB.clock:
            raise ApiError("ERR_LEASE_EXPIRED",
                           "The lease's lease_end_date is not after the account clock.")
    obj["request_state"] = "PENDING_APPROVAL"
    obj["required_approval_level"] = calc.approval_level_band(obj.get("prior_rent_cents_per_year"))
    obj["savings_provisional_cents"] = calc.savings_realization_score(obj, "provisional")
    touch(obj)
    return ok(serialize(obj))


def _authority_for(account_id, user_id):
    for a in DB.children("account_assignments", account_id):
        if a.get("assignment_role") != "APPROVAL_AUTHORITY":
            continue
        if user_id is not None and a.get("id") == user_id:
            return a
        if user_id is not None and a.get("assignee_name") == user_id:
            return a
    return None


@route("POST", "/api/transaction-requests/<request_id>/decide",
       "decide_transaction_request", ["ApprovalAuthority"])
def decide_transaction_request(request_id):
    obj = lookup("transaction_requests", request_id, "transaction request")
    account = lookup("accounts", obj.get("account_id"), "account")
    data = body()
    decision = data.get("decision")
    if not isinstance(decision, str):
        raise ApiError("ERR_INVALID_REQUEST", "decision is required.")
    token = decision.strip().upper()
    if token not in APPROVE_TOKENS and token not in REJECT_TOKENS:
        raise ApiError("ERR_INVALID_REQUEST",
                       "decision must be an approval or a rejection.")
    if obj.get("request_state") != "PENDING_APPROVAL":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a PENDING_APPROVAL request may be decided.")
    domain.cooling_off_gate(account["id"])
    user_id = __import__("flask").request.headers.get("X-User-ID")
    assignment = _authority_for(account["id"], user_id)
    if token in APPROVE_TOKENS and assignment is None:
        raise ApiError("ERR_UNAUTHORIZED",
                       "No APPROVAL_AUTHORITY assignment on this account matches X-User-ID.")
    required = obj.get("required_approval_level") or calc.approval_level_band(
        obj.get("prior_rent_cents_per_year"))
    supplied_level = data.get("level")
    if supplied_level is not None:
        if supplied_level not in calc.LEVEL_ORDER:
            raise ApiError("ERR_INVALID_REQUEST",
                           "level must be MANAGER, DIRECTOR or ACCOUNT_EXECUTIVE.")
        if calc.LEVEL_ORDER[supplied_level] < calc.LEVEL_ORDER.get(required, 0):
            raise ApiError("ERR_APPROVAL_LEVEL_INSUFFICIENT",
                           "The acting level is below the required approval level.")
    if token in APPROVE_TOKENS and assignment is not None:
        actor_level = assignment.get("approval_level") or "MANAGER"
        if calc.LEVEL_ORDER.get(actor_level, 0) < calc.LEVEL_ORDER.get(required, 0):
            raise ApiError("ERR_APPROVAL_LEVEL_INSUFFICIENT",
                           "The acting level is below the required approval level.")
    lease = DB.get("leases", obj.get("lease_id"))
    if token in APPROVE_TOKENS:
        obj["request_state"] = "APPROVED"
        if lease is not None and lease.get("pipeline_state") == "APPROVAL_PENDING":
            lease["pipeline_state"] = "BROKER_ASSIGNED"
            touch(lease)
    else:
        obj["request_state"] = "REJECTED"
        if lease is not None and lease.get("pipeline_state") == "APPROVAL_PENDING":
            lease["pipeline_state"] = "REJECTED"
            touch(lease)
    touch(obj)
    touch(account)
    return ok(serialize(obj))


@route("POST", "/api/transaction-requests/<request_id>/withdraw",
       "withdraw_transaction_request", TM_ONLY)
def withdraw_transaction_request(request_id):
    obj = lookup("transaction_requests", request_id, "transaction request")
    if obj.get("request_state") != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT request may be withdrawn.")
    obj["request_state"] = "WITHDRAWN"
    touch(obj)
    return ok(serialize(obj))


@route("POST", "/api/transaction-requests/<request_id>/cancel",
       "cancel_transaction_request", TM_ONLY)
def cancel_transaction_request(request_id):
    obj = lookup("transaction_requests", request_id, "transaction request")
    account = lookup("accounts", obj.get("account_id"), "account")
    if obj.get("request_state") != "PENDING_APPROVAL":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a PENDING_APPROVAL request may be cancelled.")
    if account.get("lifecycle_state") != "OFFBOARDING":
        raise ApiError("ERR_INVALID_STATE",
                       "Cancellation is only available while the account is OFFBOARDING.")
    obj["request_state"] = "CANCELLED"
    touch(obj)
    return ok(serialize(obj))