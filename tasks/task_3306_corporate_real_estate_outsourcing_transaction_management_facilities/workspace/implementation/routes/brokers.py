"""Commission records, broker engagements and fee accruals."""
from decimal import Decimal

from core import auth, calc, domain
from core.db import DB, dec, new_common, parse_dt, serialize, touch
from core.errors import ApiError
from core.response import ok

from routes.registry import (body, lookup, paginated_ok, req, route, validate)

COMMISSION_SOURCES = ("THIRD_PARTY", "SELF_PERFORM")
BROKER_CLASSES = ("SENIOR", "STANDARD")
FIN_ROLES = ["AccountExecutive", "TransactionManager", "GovernanceManager"]
TM_ONLY = ["TransactionManager"]
EXEC_TM = ["AccountExecutive", "TransactionManager"]
ENG_ROLES = ["AccountExecutive", "TransactionManager", "ApprovalAuthority"]


# ---------------------------------------------------------------------------
# Commission records
# ---------------------------------------------------------------------------

def _gross_fee_base(account):
    sqft = int(account.get("portfolio_sqft") or 0)
    return dec(calc.tier_rate(sqft)) * dec(sqft)


@route("POST", "/api/commission-records", "create_commission_record", EXEC_TM, 201)
def create_commission_record():
    data = validate(body(), [req("account_id"), req("commission_source"),
                             req("base_rent_cents"), req("commission_pct"),
                             req("accrual_date")])
    account = lookup("accounts", data.get("account_id"), "account")
    source = data["commission_source"]
    if source not in COMMISSION_SOURCES:
        raise ApiError("ERR_INVALID_REQUEST",
                       "commission_source must be THIRD_PARTY or SELF_PERFORM.")
    base_rent = data["base_rent_cents"]
    if isinstance(base_rent, bool) or not isinstance(base_rent, (int, float)) or base_rent < 0:
        raise ApiError("ERR_INVALID_REQUEST", "base_rent_cents may not be negative.")
    pct = dec(data["commission_pct"])
    if pct < 0 or pct > dec("0.35"):
        raise ApiError("ERR_INVALID_REQUEST",
                       "commission_pct must lie between 0 and 0.35 inclusive.")
    accrual_date = parse_dt(data["accrual_date"])
    if accrual_date is None:
        raise ApiError("ERR_INVALID_REQUEST", "accrual_date must be an ISO 8601 instant.")
    if dec(base_rent) > _gross_fee_base(account):
        raise ApiError("ERR_COMMISSION_EXCEEDS_FEE",
                       "base_rent_cents exceeds the account's gross fee base.")
    obj = new_common()
    obj.update({
        "account_id": account["id"],
        "commission_source": source,
        "base_rent_cents": int(base_rent),
        "commission_pct": pct,
        "accrual_date": accrual_date,
        "credited": False,
    })
    obj["credit_amount_cents"] = calc.record_due_cents(obj)
    DB.insert("commission_records", obj)
    domain.recompute_fee(account)
    touch(account)
    return ok(serialize(obj), 201)


@route("GET", "/api/commission-records", "list_commission_records", FIN_ROLES)
def list_commission_records():
    rows = DB.ordered("commission_records")
    args = __import__("flask").request.args
    if args.get("account_id"):
        rows = [r for r in rows if r.get("account_id") == args.get("account_id")]
    return paginated_ok(rows)


@route("GET", "/api/commission-records/<record_id>", "get_commission_record", FIN_ROLES)
def get_commission_record(record_id):
    return ok(serialize(lookup("commission_records", record_id, "commission record")))


# ---------------------------------------------------------------------------
# Broker engagements
# ---------------------------------------------------------------------------

@route("POST", "/api/broker-engagements", "create_broker_engagement", TM_ONLY, 201)
def create_broker_engagement():
    data = validate(body(), [req("account_id"), req("transaction_request_id"),
                             req("market_code"), req("broker_name"),
                             req("licensed_in_market"), req("broker_class")])
    account = lookup("accounts", data.get("account_id"), "account")
    treq = lookup("transaction_requests", data.get("transaction_request_id"),
                  "transaction request")
    domain.lifecycle_gate(account, "create_broker_engagement")
    if treq.get("account_id") != account["id"]:
        raise ApiError("ERR_RESOURCE_NOT_FOUND",
                       "The transaction request does not belong to this account.")
    broker_class = data["broker_class"]
    if broker_class not in BROKER_CLASSES:
        raise ApiError("ERR_INVALID_REQUEST",
                       "broker_class must be SENIOR or STANDARD.")
    if not isinstance(data["licensed_in_market"], bool):
        raise ApiError("ERR_INVALID_REQUEST", "licensed_in_market must be a boolean.")
    lease = DB.get("leases", treq.get("lease_id"))
    if lease is not None and lease.get("market_code") != data["market_code"]:
        raise ApiError("ERR_MARKET_MISMATCH",
                       "The engagement market does not match the lease market.")
    obj = new_common()
    obj.update({
        "account_id": account["id"],
        "transaction_request_id": treq["id"],
        "market_code": data["market_code"],
        "broker_name": data["broker_name"],
        "licensed_in_market": data["licensed_in_market"],
        "broker_class": broker_class,
        "engagement_state": "PENDING",
        "deal_commission_cents": 0,
        "broker_share_cents": 0,
        "account_share_cents": 0,
    })
    DB.insert("broker_engagements", obj)
    return ok(serialize(obj), 201)


@route("GET", "/api/broker-engagements", "list_broker_engagements", ENG_ROLES)
def list_broker_engagements():
    rows = DB.ordered("broker_engagements")
    args = __import__("flask").request.args
    if args.get("account_id"):
        rows = [r for r in rows if r.get("account_id") == args.get("account_id")]
    if args.get("transaction_request_id"):
        rows = [r for r in rows
                if r.get("transaction_request_id") == args.get("transaction_request_id")]
    return paginated_ok(rows)


@route("GET", "/api/broker-engagements/<engagement_id>", "get_broker_engagement", ENG_ROLES)
def get_broker_engagement(engagement_id):
    return ok(serialize(lookup("broker_engagements", engagement_id, "broker engagement")))


@route("POST", "/api/broker-engagements/<engagement_id>/assign",
       "assign_broker_engagement", TM_ONLY)
def assign_broker_engagement(engagement_id):
    obj = lookup("broker_engagements", engagement_id, "broker engagement")
    if obj.get("engagement_state") != "PENDING":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a PENDING engagement may be assigned.")
    if obj.get("licensed_in_market") is not True:
        raise ApiError("ERR_BROKER_NOT_LICENSED",
                       "The broker is not licensed in the target market.")
    obj["engagement_state"] = "ASSIGNED"
    touch(obj)
    return ok(serialize(obj))


@route("POST", "/api/broker-engagements/<engagement_id>/execute",
       "execute_broker_engagement", TM_ONLY)
def execute_broker_engagement(engagement_id):
    obj = lookup("broker_engagements", engagement_id, "broker engagement")
    treq = lookup("transaction_requests", obj.get("transaction_request_id"),
                  "transaction request")
    if obj.get("engagement_state") != "ASSIGNED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only an ASSIGNED engagement may be executed.")
    if treq.get("request_state") == "EXECUTED":
        raise ApiError("ERR_INVALID_STATE",
                       "The transaction request has already been executed.")
    if treq.get("request_state") != "APPROVED":
        raise ApiError("ERR_INVALID_STATE",
                       "Execution requires an APPROVED transaction request.")
    account = lookup("accounts", obj.get("account_id"), "account")
    split = calc.broker_commission_split(obj, treq)
    obj.update(split)
    obj["engagement_state"] = "EXECUTED"
    touch(obj)
    treq["request_state"] = "EXECUTED"
    treq["savings_final_cents"] = calc.savings_realization_score(treq, "final")
    touch(treq)
    domain.recompute_fee(account)
    touch(account)
    return ok(serialize(obj))


@route("POST", "/api/broker-engagements/<engagement_id>/terminate",
       "terminate_broker_engagement", TM_ONLY)
def terminate_broker_engagement(engagement_id):
    obj = lookup("broker_engagements", engagement_id, "broker engagement")
    state = obj.get("engagement_state")
    if state not in ("PENDING", "ASSIGNED", "EXECUTED"):
        raise ApiError("ERR_INVALID_STATE",
                       "A TERMINATED engagement cannot be terminated again.")
    account = DB.get("accounts", obj.get("account_id"))
    if state == "EXECUTED":
        obj["broker_share_cents"] = 0
        obj["account_share_cents"] = 0
    obj["engagement_state"] = "TERMINATED"
    touch(obj)
    if account is not None:
        domain.recompute_fee(account)
        touch(account)
    return ok(serialize(obj))


# ---------------------------------------------------------------------------
# Fee accruals and credit application
# ---------------------------------------------------------------------------

@route("POST", "/api/fee-accruals", "create_fee_accrual", ["AccountExecutive"], 201)
def create_fee_accrual():
    data = validate(body(), [req("account_id"), req("period"), req("base_fee_cents")])
    account = lookup("accounts", data.get("account_id"), "account")
    base_fee = data["base_fee_cents"]
    if isinstance(base_fee, bool) or not isinstance(base_fee, int) or base_fee < 0:
        raise ApiError("ERR_INVALID_REQUEST", "base_fee_cents may not be negative.")
    period = str(data["period"])
    for row in DB.children("fee_accruals", account["id"]):
        if row.get("period") == period:
            raise ApiError("ERR_INVALID_REQUEST",
                           "The period label is unique per account.")
    obj = new_common()
    obj.update({
        "account_id": account["id"],
        "period": period,
        "base_fee_cents": base_fee,
        "applied_credit_cents": 0,
        "credit_application_state": "OPEN",
        "settled_at": None,
    })
    DB.insert("fee_accruals", obj)
    return ok(serialize(obj), 201)


@route("GET", "/api/fee-accruals", "list_fee_accruals",
       ["AccountExecutive", "GovernanceManager", "TransactionManager"])
def list_fee_accruals():
    rows = DB.ordered("fee_accruals")
    args = __import__("flask").request.args
    if args.get("account_id"):
        rows = [r for r in rows if r.get("account_id") == args.get("account_id")]
    if args.get("period"):
        rows = [r for r in rows if r.get("period") == args.get("period")]
    return paginated_ok(rows)


@route("GET", "/api/fee-accruals/<accrual_id>", "get_fee_accrual",
       ["AccountExecutive", "GovernanceManager", "TransactionManager"])
def get_fee_accrual(accrual_id):
    return ok(serialize(lookup("fee_accruals", accrual_id, "fee accrual")))


@route("POST", "/api/fee-accruals/<accrual_id>/settle", "settle_fee_accrual",
       ["AccountExecutive"])
def settle_fee_accrual(accrual_id):
    obj = lookup("fee_accruals", accrual_id, "fee accrual")
    if obj.get("credit_application_state") != "CREDITED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a CREDITED accrual may be settled.")
    obj["credit_application_state"] = "SETTLED"
    obj["settled_at"] = DB.clock
    touch(obj)
    return ok(serialize(obj))


def _account_for_execution(execution_id):
    lease = DB.get("leases", execution_id)
    if lease is not None:
        return lease.get("account_id")
    account = DB.get("accounts", execution_id)
    if account is not None:
        return account["id"]
    request = DB.get("transaction_requests", execution_id)
    if request is not None:
        return request.get("account_id")
    accrual = DB.get("fee_accruals", execution_id)
    if accrual is not None:
        return accrual.get("account_id")
    return None


@route("POST", "/api/lease-executions/<execution_id>/apply", "apply_lease_execution",
       TM_ONLY)
def apply_lease_execution(execution_id):
    account_id = _account_for_execution(execution_id)
    if account_id is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND",
                       "No lease execution matches the supplied identifier.")
    account = lookup("accounts", account_id, "account")
    accruals = DB.children("fee_accruals", account_id)
    if not accruals:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "The account has no fee accrual to credit.")
    accruals = sorted(accruals, key=lambda a: a.get("_seq", 0))
    target = None
    for accrual in accruals:
        if accrual.get("credit_application_state") == "OPEN":
            target = accrual
            break
    if target is None:
        raise ApiError("ERR_FEE_ACCRUAL_LOCKED",
                       "The account's fee accrual is not OPEN for a credit application.")
    uncredited = [r for r in calc.ordered_records(account_id) if not r.get("credited")]
    if not uncredited:
        raise ApiError("ERR_INVALID_STATE",
                       "No uncredited commission record is available to apply.")
    total = Decimal(0)
    for record in uncredited:
        total += calc.record_due_cents(record)
    target["applied_credit_cents"] = total
    target["credit_application_state"] = "CREDITED"
    touch(target)
    for record in uncredited:
        record["credited"] = True
        touch(record)
    domain.recompute_fee(account)
    touch(account)
    return ok(serialize(target))