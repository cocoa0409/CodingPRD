"""Lease routes: creation, expiration buckets and the pipeline state machine."""
from core import auth, calc, domain
from core.db import (DB, dec, new_common, parse_dt, serialize, touch, utcnow)
from core.errors import ApiError
from core.response import ok

from routes.registry import (body, int_arg, lookup, paginated_ok, req, route,
                             validate, vt)

ALL_ROLES = auth.ROLES
TM_ONLY = ["TransactionManager"]

TERMINAL_PIPELINE = ("EXECUTED", "REJECTED")


def requests_for_lease(lease_id):
    rows = [r for r in DB.rows("transaction_requests") if r.get("lease_id") == lease_id]
    return sorted(rows, key=lambda r: r.get("_seq", 0))


def linked_request(lease_id, required_state=None):
    rows = requests_for_lease(lease_id)
    if required_state is not None:
        for r in rows:
            if r.get("request_state") == required_state:
                return r
        return None
    return rows[-1] if rows else None


@route("POST", "/api/leases", "create_lease", TM_ONLY, 201)
def create_lease():
    data = validate(body(), [req("account_id"), req("property_address"), req("market_code"),
                             req("leased_sqft"), req("base_rent_cents_per_year"),
                             req("lease_start_date"), req("lease_end_date")])
    account = lookup("accounts", data.get("account_id"), "account")
    domain.lifecycle_gate(account, "create_lease")
    sqft = data["leased_sqft"]
    if isinstance(sqft, bool) or not isinstance(sqft, int) or sqft < 1:
        raise ApiError("ERR_INVALID_REQUEST", "leased_sqft must be at least 1.")
    rent = data["base_rent_cents_per_year"]
    if isinstance(rent, bool) or not isinstance(rent, int) or rent < 1:
        raise ApiError("ERR_INVALID_REQUEST",
                       "base_rent_cents_per_year must be at least 1.")
    start = parse_dt(data["lease_start_date"])
    end = parse_dt(data["lease_end_date"])
    if start is None or end is None:
        raise ApiError("ERR_INVALID_REQUEST", "Lease dates must be ISO 8601 instants.")
    if not end > start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "lease_end_date must be strictly after lease_start_date.")
    if domain.lease_premises_conflict(account["id"], data["property_address"], start, end):
        raise ApiError("ERR_LEASE_OVERLAP",
                       "The premises overlap a prior lease or fall inside its 30-day cooldown.")
    obj = new_common()
    obj.update({
        "account_id": account["id"],
        "property_address": data["property_address"],
        "market_code": data["market_code"],
        "leased_sqft": sqft,
        "base_rent_cents_per_year": rent,
        "lease_start_date": start,
        "lease_end_date": end,
        "expiration_bucket": calc.expiration_bucket_for({
            "lease_end_date": end}, DB.clock),
        "pipeline_state": "PIPELINE",
        "revision_count": 0,
    })
    DB.insert("leases", obj)
    account["version"] = account.get("version", 1) + 1
    account["updated_at"] = utcnow()
    return ok(serialize(obj), 201)


@route("GET", "/api/leases", "list_leases", ALL_ROLES)
def list_leases():
    rows = DB.ordered("leases")
    account_id = __import__("flask").request.args.get("account_id")
    if account_id:
        rows = [r for r in rows if r.get("account_id") == account_id]
    return paginated_ok(rows)


@route("GET", "/api/leases/<lease_id>", "get_lease", ALL_ROLES)
def get_lease(lease_id):
    return ok(serialize(lookup("leases", lease_id, "lease")))


def _lease_expired(lease):
    end = lease.get("lease_end_date")
    return end is not None and not end > DB.clock


def _lease_overdue_guard(lease):
    """Priority 18: overdue non-terminal lease while another expired lease exists
    on the same account and market."""
    end = lease.get("lease_end_date")
    if end is None or end > DB.clock:
        return
    if lease.get("pipeline_state") in TERMINAL_PIPELINE:
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


@route("POST", "/api/leases/<lease_id>/submit-for-approval", "lease_submit_for_approval",
       TM_ONLY)
def lease_submit_for_approval(lease_id):
    lease = lookup("leases", lease_id, "lease")
    if lease.get("pipeline_state") != "PIPELINE":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a PIPELINE lease may be submitted for approval.")
    if _lease_expired(lease):
        raise ApiError("ERR_LEASE_EXPIRED",
                       "lease_end_date must be strictly after the account clock.")
    _lease_overdue_guard(lease)
    lease["pipeline_state"] = "APPROVAL_PENDING"
    touch(lease)
    return ok(serialize(lease))


@route("POST", "/api/leases/<lease_id>/approve", "lease_approve", TM_ONLY)
def lease_approve(lease_id):
    lease = lookup("leases", lease_id, "lease")
    if lease.get("pipeline_state") != "APPROVAL_PENDING":
        raise ApiError("ERR_INVALID_STATE",
                       "Only an APPROVAL_PENDING lease may be approved.")
    request = linked_request(lease["id"], "PENDING_APPROVAL")
    if request is None:
        raise ApiError("ERR_INVALID_STATE",
                       "The linked transaction request is not PENDING_APPROVAL.")
    lease["pipeline_state"] = "BROKER_ASSIGNED"
    touch(lease)
    request["request_state"] = "APPROVED"
    touch(request)
    return ok(serialize(lease))


@route("POST", "/api/leases/<lease_id>/reject", "lease_reject", TM_ONLY)
def lease_reject(lease_id):
    lease = lookup("leases", lease_id, "lease")
    if lease.get("pipeline_state") != "APPROVAL_PENDING":
        raise ApiError("ERR_INVALID_STATE",
                       "Only an APPROVAL_PENDING lease may be rejected.")
    lease["pipeline_state"] = "REJECTED"
    touch(lease)
    request = linked_request(lease["id"])
    if request is not None:
        request["request_state"] = "REJECTED"
        touch(request)
    return ok(serialize(lease))


@route("POST", "/api/leases/<lease_id>/revise", "lease_revise", TM_ONLY)
def lease_revise(lease_id):
    lease = lookup("leases", lease_id, "lease")
    account = lookup("accounts", lease.get("account_id"), "account")
    if lease.get("pipeline_state") != "REJECTED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a REJECTED lease may be revised.")
    if int(lease.get("revision_count") or 0) >= 3:
        raise ApiError("ERR_REVISION_LIMIT_REACHED",
                       "The lease has already entered three revision rounds.")
    data = body()
    expected = data.get("expected_account_version")
    if expected is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "expected_account_version is required on this operation.")
    if int(expected) != int(account.get("version") or 1):
        raise ApiError("ERR_STALE_VERSION",
                       "expected_account_version does not match the account version.")
    lease["pipeline_state"] = "APPROVAL_PENDING"
    lease["revision_count"] = int(lease.get("revision_count") or 0) + 1
    touch(lease)
    touch(account)
    return ok(serialize(lease))


@route("POST", "/api/leases/<lease_id>/launch-marketing", "lease_launch_marketing", TM_ONLY)
def lease_launch_marketing(lease_id):
    lease = lookup("leases", lease_id, "lease")
    # PRD §3.2 / §2.8: the cross-entity precondition that a BrokerEngagement on
    # the lease already exist in state ASSIGNED "is rejected before any business
    # check with ERR_INVALID_STATE" — i.e. it is evaluated (priority 8) ahead of
    # the lease's own state check (priority 9, ERR_NOT_TRANSITIONING).
    engagements = [e for e in DB.children("broker_engagements", lease.get("account_id"))
                   if e.get("transaction_request_id") in
                   {r["id"] for r in requests_for_lease(lease["id"])}]
    assigned = [e for e in engagements if e.get("engagement_state") == "ASSIGNED"]
    if lease.get("pipeline_state") != "BROKER_ASSIGNED":
        if not assigned:
            raise ApiError("ERR_INVALID_STATE",
                           "A broker engagement on this lease must be ASSIGNED first.")
        raise ApiError("ERR_NOT_TRANSITIONING",
                       "Only a BROKER_ASSIGNED lease may be launched into market.")
    if not assigned:
        raise ApiError("ERR_INVALID_STATE",
                       "A broker engagement on this lease must be ASSIGNED first.")
    lease["pipeline_state"] = "IN_MARKET"
    touch(lease)
    return ok(serialize(lease))


@route("POST", "/api/leases/<lease_id>/open-negotiation", "lease_open_negotiation", TM_ONLY)
def lease_open_negotiation(lease_id):
    lease = lookup("leases", lease_id, "lease")
    if lease.get("pipeline_state") != "IN_MARKET":
        raise ApiError("ERR_INVALID_STATE",
                       "Only an IN_MARKET lease may open negotiation.")
    request = linked_request(lease["id"])
    licensed = []
    if request is not None:
        licensed = [e for e in DB.children("broker_engagements", lease.get("account_id"))
                    if e.get("transaction_request_id") == request["id"]
                    and e.get("licensed_in_market") is True]
    if len(licensed) != 1:
        raise ApiError("ERR_INVALID_STATE",
                       "The linked transaction request must carry exactly one licensed broker.")
    lease["pipeline_state"] = "NEGOTIATING"
    touch(lease)
    return ok(serialize(lease))


def post_commission_record(account, request, now=None):
    prior = dec(request.get("prior_rent_cents_per_year") or 0)
    commission = dec(request.get("third_party_commission_cents") or 0)
    pct = (commission / prior) if prior > 0 else dec(0)
    record = new_common()
    record.update({
        "account_id": account["id"],
        "commission_source": "THIRD_PARTY",
        "base_rent_cents": int(prior),
        "commission_pct": pct,
        "accrual_date": now or DB.clock,
        "credited": False,
    })
    record["credit_amount_cents"] = calc.record_due_cents(record)
    DB.insert("commission_records", record)
    return record


@route("POST", "/api/leases/<lease_id>/execute", "lease_execute", TM_ONLY)
def lease_execute(lease_id):
    lease = lookup("leases", lease_id, "lease")
    if lease.get("pipeline_state") != "NEGOTIATING":
        raise ApiError("ERR_INVALID_STATE", "Only a NEGOTIATING lease may be executed.")
    account = lookup("accounts", lease.get("account_id"), "account")
    request = linked_request(lease["id"], "APPROVED")
    lease["pipeline_state"] = "EXECUTED"
    touch(lease)
    if request is not None:
        request["request_state"] = "EXECUTED"
        request["savings_final_cents"] = calc.savings_realization_score(request, "final")
        touch(request)
        post_commission_record(account, request)
    domain.recompute_fee(account)
    touch(account)
    return ok(serialize(lease))


@route("POST", "/api/leases/<lease_id>/expire", "lease_expire",
       ["TransactionManager", "AccountExecutive"])
def lease_expire(lease_id):
    lease = lookup("leases", lease_id, "lease")
    if lease.get("pipeline_state") in TERMINAL_PIPELINE:
        raise ApiError("ERR_INVALID_STATE",
                       "A terminal lease cannot be expired again.")
    lease["pipeline_state"] = "REJECTED"
    touch(lease)
    return ok(serialize(lease))