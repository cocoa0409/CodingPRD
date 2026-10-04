"""Route registry: every endpoint declared in PRD S4 / SCAFFOLD S1.5.

Handlers receive a request-scoped Ctx, the Flask view kwargs, the parsed JSON
body, the parsed query mapping and the caller's (user_id, role) tuple.  Auth and
role checks are performed by app.py before a handler runs, so the cascade seen
here starts at priority 4 (existence).
"""

import calculations as calc
import errors
import serializer as ser
from errors import ApiError
from services import (
    AGING_BUCKETS,
    COUNTERPARTY_STATUSES,
    CURRENCIES,
    DIRECTIONS,
    ENTITY_TYPES,
    ENTRY_TYPES,
    EXCEPTION_KINDS,
    EXCEPTION_STATUSES,
    LINE_MATCH_STATES,
    RAILS,
    RELATIONSHIP_PURPOSES,
    RAIL_DOMAINS,
    RETURN_REASONS,
    SETTLEMENT_SPEEDS,
    VALID_TZ,
    bad_request,
    require_fields,
    require_enum,
    optional_enum,
    require_iso,
    optional_iso,
    _parse_limit_offset,
)
from utils import parse_date, parse_iso
from utils import local_date_from_ms, utc_ms_from_local
from datetime import time as _dt_time

ROUTES = {}


class Resp(object):
    def __init__(self, data, rtype="object", total=None, limit=None, offset=None):
        self.data = data
        self.rtype = rtype
        self.total = total
        self.limit = limit
        self.offset = offset


def route(method, path, roles, code=200, single_role=False):
    compiled = path
    for token in [p for p in path.split("/") if p.startswith("{")]:
        compiled = compiled.replace(token, "<" + token.strip("{}") + ">")

    def deco(fn):
        ROUTES[(method, compiled)] = {
            "method": method,
            "path": path,
            "roles": list(roles),
            "code": code,
            "single_role": single_role,
            "handler": fn,
        }
        return fn
    return deco


# ------------------------------------------------------------------ helpers

def _end_of_local_day_ms(ctx, ledger, instant_ms):
    """The exclusive upper bound of the local calendar date carrying `instant_ms`.

    PRD S2.11 / S3.9: business-effective instants (value_effective_utc) are
    business dates, while the injected logical clock is an instant.  Comparing a
    posting's business instant with a close *instant* would let a posting dated
    09:00 on the very day the books closed slip past the boundary, which is the
    boundary the closed-period guard exists to stop.  Anchoring the boundary at
    the end of the closing local date keeps the guard strict without ever
    excluding a later date.
    """
    tz = ctx.ledger_timezone(ledger.get("id"))
    local_date = local_date_from_ms(instant_ms, tz)
    nxt = local_date.fromordinal(local_date.toordinal() + 1)
    end_of_day = _dt_time(23, 59, 59)
    return utc_ms_from_local(nxt, end_of_day, tz)


def paginate(query, rows, sort_key):
    rows = sorted(rows, key=sort_key)
    limit, offset = _parse_limit_offset(query)
    total = len(rows)
    page = rows[offset:offset + limit]
    has_more = (offset + limit) < total
    return page, total, limit, offset, has_more


def _page(query, entity_name, ctx, rows, sort_key):
    page, total, limit, offset, _ = paginate(query, rows, sort_key)
    return Resp(ser.serialize_many(entity_name, page, ctx), "array",
                total=total, limit=limit, offset=offset)


def created_sort(row):
    return (row["created_at"], row["sequence"])


def audit_ledger_for_entity(ctx, legal_entity_id):
    entity = ctx.store.legal_entities.get(legal_entity_id)
    if entity is not None:
        return entity.get("home_ledger_id")
    return None


def audit_ledger_for_account(ctx, bank_account_id):
    acct = ctx.store.bank_accounts.get(bank_account_id)
    if acct is not None:
        return audit_ledger_for_entity(ctx, acct["legal_entity_id"])
    return None


def _is_digits(value, count):
    return isinstance(value, str) and len(value) == count and value.isdigit()


def aba_checksum_ok(routing):
    if not _is_digits(routing, 9):
        return False
    d = [int(c) for c in routing]
    total = (3 * (d[0] + d[3] + d[6])
             + 7 * (d[1] + d[4] + d[7])
             + 1 * (d[2] + d[5] + d[8]))
    return total % 10 == 0


def _order_is_terminal(order):
    return order["status"] in ("SETTLED", "RETURNED", "REVERSED", "CANCELLED")


def _restrict_counterparty(ctx, counterparty, actor):
    counterparty["status"] = "RESTRICTED"
    ctx.touch(counterparty)
    entity_id = counterparty["legal_entity_id"]
    for rel in ctx.store.relationships.values():
        if (rel["status"] == "ACTIVE" and rel["purpose"] == "ACCOUNT_SHARING"
                and rel["legal_entity_id"] == entity_id):
            rel["status"] = "SUSPENDED"
            ctx.touch(rel)
    ctx.append_audit(audit_ledger_for_entity(ctx, entity_id), actor,
                     "counterparty.restricted", "Counterparty", counterparty["id"],
                     {"to_status": "RESTRICTED"})


def _relationship_sides(ctx, legal_entity_id):
    """The ledgers of the two institutions named through one relationship side."""
    entity = ctx.store.legal_entities.get(legal_entity_id)
    if entity is None:
        return []
    return [entity.get("home_ledger_id")]


# ================================================================== LEDGER

@route("POST", "/ledgers", ["PlatformAdmin", "LedgerController"], code=201)
def create_ledger(ctx, params, body, query, actor):
    require_fields(body, ["name", "currency"])
    require_enum(body, "currency", CURRENCIES)
    row = ctx.created_row(
        name=body["name"],
        currency=body["currency"],
        legal_entity_id=body.get("legal_entity_id"),
        period_index=1,
        period_opened_utc=ctx.now_ms(),
        period_close_ms=ctx.now_ms(),
        period_closed_through_index=0,
        delivered_fee_transfers_cents=0,
        undeliverable_cents=0,
        resolved_return_leg_ids=set(),
        status="OPEN",
    )
    ctx.store.ledgers[row["id"]] = row
    ctx.append_audit(row["id"], actor, "ledger.opened", "Ledger", row["id"],
                     {"currency": row["currency"]})
    return Resp(ser.serialize("Ledger", row, ctx))


@route("GET", "/ledgers", ["PlatformAdmin", "LedgerController", "Auditor", "PaymentOpsAnalyst"])
def list_ledgers(ctx, params, body, query, actor):
    rows = list(ctx.store.ledgers.values())
    if query.get("status"):
        rows = [r for r in rows if r["status"] == query["status"]]
    return _page(query, "Ledger", ctx, rows, created_sort)


@route("GET", "/ledgers/{id}",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentOpsApprover",
        "PaymentApprover", "PaymentInitiator", "Auditor"])
def get_ledger(ctx, params, body, query, actor):
    row = ctx.ledger(params["id"])
    return Resp(ser.serialize("Ledger", row, ctx))


@route("POST", "/ledgers/{id}/close-period", ["LedgerController"], single_role=True)
def close_period(ctx, params, body, query, actor):
    row = ctx.ledger(params["id"])
    ctx.check_version(row, body.get("expected_ledger_version"), "expected_ledger_version")
    ctx.run_aging_pass(row["id"])
    force = bool(body.get("force_resolve_exceptions"))
    if ctx.open_exceptions(row["id"]) and not force:
        raise ApiError("ERR_CLOSE_BLOCKED_BY_EXCEPTION")
    now = ctx.now_ms()
    # PRD S3.9 / S3.6: period close is a day-boundary event, so the close instant
    # of the period being closed is the END of the closing local date rather than
    # the instant the command happened to run.  That is what makes a posting
    # whose value_effective_utc falls anywhere on the closing date -- not merely
    # before the command ran -- fall inside the closed period and draw
    # ERR_PERIOD_CLOSED, while a row whose state gate already refuses the
    # transition still reports ERR_INVALID_TRANSITION first (PRD S2.10: the state
    # gate precedes the business checks).
    row["period_close_ms"] = _end_of_local_day_ms(ctx, row, now)
    closed_index = row["period_index"]
    if closed_index < 12:
        row["period_index"] += 1
        # "`period_opened_utc` is reset to the close instant of the period just ended"
        row["period_opened_utc"] = row["period_close_ms"]
    else:
        row["status"] = "CLOSED"
        row["period_closed_through_index"] = 12
    # PRD S2.4: "`period_closed_through_index` ... is the Highest period_index
    # whose books are closed; 0 = no period closed".  Every close therefore
    # records the index it froze -- the grade-12 close records 12, which is the
    # case S3.9 states explicitly -- so the closed-period boundary of S2.11 /
    # S3.9 is reachable after any close rather than only after the last one.
    if row["status"] != "CLOSED":
        row["period_closed_through_index"] = closed_index
    ctx.touch(row)
    ctx.append_audit(row["id"], actor, "ledger.period_closed", "Ledger", row["id"],
                     {"period_index": row["period_index"], "status": row["status"]})
    return Resp(ser.serialize("Ledger", row, ctx))


@route("POST", "/ledgers/{id}/receipts", ["PaymentOpsAnalyst", "Auditor", "LedgerController"])
def ledger_receipts(ctx, params, body, query, actor):
    row = ctx.ledger(params["id"])
    ids = body.get("transaction_ids")
    if ids is None:
        ids = []
    if not isinstance(ids, list):
        raise bad_request("transaction_ids must be an array.")
    out = []
    for tid in ids:
        txn = ctx.transaction(tid)
        payload = ser.serialize("Transaction", txn, ctx)
        payload["receipt_pairs"] = [
            {"direction": "DEBIT", "amount_cents": txn["amount_cents"]},
            {"direction": "CREDIT", "amount_cents": txn["amount_cents"]},
        ]
        out.append(payload)
    return Resp(out, "array", total=len(out), limit=len(out), offset=0)


@route("POST", "/ledgers/{id}/recompute", ["LedgerController", "PlatformAdmin"])
def recompute_ledger(ctx, params, body, query, actor):
    row = ctx.ledger(params["id"])
    ctx.check_version(row, body.get("expected_ledger_version"), "expected_ledger_version")
    if not ctx.identity_holds(row["id"]):
        raise ApiError("ERR_LEDGER_UNBALANCED",
                       "The double-entry identity could not be restored.")
    resolved = len(row.get("resolved_return_leg_ids", set()))
    if row["delivered_fee_transfers_cents"] + row["undeliverable_cents"] != \
            calc.RETURN_LEG_FEE_CENTS * resolved:
        raise ApiError("ERR_LEDGER_UNBALANCED",
                       "The reverse-rail fee invariant could not be restored.")
    ctx.touch(row)
    ctx.append_audit(row["id"], actor, "ledger.recomputed", "Ledger", row["id"], {})
    return Resp(ser.serialize("Ledger", row, ctx))


@route("POST", "/ledgers/{id}/summary",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentOpsApprover", "Auditor"])
def ledger_summary(ctx, params, body, query, actor):
    row = ctx.ledger(params["id"])
    merged = dict(query)
    if isinstance(body, dict):
        merged.update({k: v for k, v in body.items() if k not in merged})
    settled = str(merged.get("settled", "")).lower() == "true"
    pending = ctx.ledger_pending_cents(row["id"])
    posted = ctx.ledger_posted_cents(row["id"])
    data = {
        "ledger_id": row["id"],
        "provisional_pending_cents": pending,
        "posted_balance_cents": posted,
        "opened_exception_count": len(ctx.open_exceptions(row["id"])),
        "period_index": row["period_index"],
        "final_posted_cents": posted,
        "settled_variant": settled,
    }
    return Resp(data)


# ================================================================== LEGAL ENTITY

@route("POST", "/legal-entities", ["PlatformAdmin"], code=201)
def create_legal_entity(ctx, params, body, query, actor):
    require_fields(body, ["legal_name", "short_code"])
    entity_type = optional_enum(body, "entity_type", ENTITY_TYPES, "ORGANISATION")
    home_ledger_id = body.get("home_ledger_id")
    if home_ledger_id is not None:
        ctx.ledger(home_ledger_id)
    if entity_type == "ORGANISATION" and home_ledger_id is None:
        raise bad_request("home_ledger_id is required when entity_type is ORGANISATION.")
    default_limit = body.get("default_velocity_limit_cents")
    if default_limit is None:
        default_limit = calc.PLATFORM_DEFAULT_LIMIT_CENTS
    elif isinstance(default_limit, bool) or not isinstance(default_limit, int):
        raise bad_request("default_velocity_limit_cents must be an integer.")
    for existing in ctx.store.legal_entities.values():
        if existing["short_code"] == body["short_code"]:
            raise ApiError("ERR_DUPLICATE_REFERENCE_CODE",
                           "short_code is already in use.")
    timezone = body.get("timezone")
    if timezone is not None and timezone not in VALID_TZ:
        raise bad_request("timezone is not a supported IANA timezone.")
    row = ctx.created_row(
        legal_name=body["legal_name"],
        short_code=body["short_code"],
        entity_type=entity_type,
        home_ledger_id=home_ledger_id,
        default_velocity_limit_cents=default_limit,
        timezone=timezone,
    )
    ctx.store.legal_entities[row["id"]] = row
    ctx.append_audit(home_ledger_id, actor, "legal_entity.created", "LegalEntity", row["id"],
                     {"short_code": row["short_code"]})
    return Resp(ser.serialize("LegalEntity", row, ctx))


@route("GET", "/legal-entities",
       ["PlatformAdmin", "LedgerController", "Auditor", "PaymentOpsAnalyst"])
def list_legal_entities(ctx, params, body, query, actor):
    rows = list(ctx.store.legal_entities.values())
    if query.get("entity_type"):
        rows = [r for r in rows if r["entity_type"] == query["entity_type"]]
    if query.get("home_ledger_id"):
        rows = [r for r in rows if r["home_ledger_id"] == query["home_ledger_id"]]
    return _page(query, "LegalEntity", ctx, rows, created_sort)


@route("GET", "/legal-entities/{id}",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentOpsApprover",
        "PaymentApprover", "PaymentInitiator", "Auditor"])
def get_legal_entity(ctx, params, body, query, actor):
    row = ctx.legal_entity(params["id"])
    return Resp(ser.serialize("LegalEntity", row, ctx))


@route("GET", "/legal-entities/{id}/counterparties",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentApprover", "Auditor"])
def list_entity_counterparties(ctx, params, body, query, actor):
    entity = ctx.legal_entity(params["id"])
    rows = [r for r in ctx.store.counterparties.values()
            if r["legal_entity_id"] == entity["id"]]
    if query.get("status"):
        rows = [r for r in rows if r["status"] == query["status"]]
    return _page(query, "Counterparty", ctx, rows, created_sort)


@route("GET", "/legal-entities/{id}/bank-accounts",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentApprover", "Auditor"])
def list_entity_bank_accounts(ctx, params, body, query, actor):
    entity = ctx.legal_entity(params["id"])
    rows = [r for r in ctx.store.bank_accounts.values()
            if r["legal_entity_id"] == entity["id"]]
    if query.get("status"):
        rows = [r for r in rows if r["status"] == query["status"]]
    return _page(query, "BankAccount", ctx, rows, created_sort)


@route("GET", "/legal-entities/{id}/institution-calendar",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentApprover",
        "PaymentInitiator", "Auditor"])
def list_entity_calendar(ctx, params, body, query, actor):
    entity = ctx.legal_entity(params["id"])
    rows = [r for r in ctx.store.calendar_cells.values()
            if r["legal_entity_id"] == entity["id"]]
    rows = _filter_calendar(query, rows)
    return _page(query, "BankingCalendar", ctx, rows,
                 lambda r: (r["calendar_date"], r["sequence"]))


@route("GET", "/legal-entities/{id}/payment-orders",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentApprover",
        "PaymentInitiator", "Auditor"])
def list_entity_payment_orders(ctx, params, body, query, actor):
    entity = ctx.legal_entity(params["id"])
    rows = [r for r in ctx.store.payment_orders.values()
            if r["legal_entity_id"] == entity["id"]]
    if query.get("status"):
        rows = [r for r in rows if r["status"] == query["status"]]
    if query.get("rail"):
        rows = [r for r in rows if r["rail"] == query["rail"]]
    return _page(query, "PaymentOrder", ctx, rows, created_sort)


def _filter_calendar(query, rows):
    if query.get("from_date"):
        try:
            start = parse_date(query["from_date"]).isoformat()
        except ValueError:
            raise bad_request("from_date must be YYYY-MM-DD.")
        rows = [r for r in rows if r["calendar_date"] >= start]
    if query.get("to_date"):
        try:
            end = parse_date(query["to_date"]).isoformat()
        except ValueError:
            raise bad_request("to_date must be YYYY-MM-DD.")
        rows = [r for r in rows if r["calendar_date"] <= end]
    if query.get("is_open") is not None and query["is_open"] != "":
        want = str(query["is_open"]).lower() == "true"
        rows = [r for r in rows if bool(r["is_open"]) == want]
    return rows


# ================================================================== COUNTERPARTY

@route("POST", "/counterparties", ["PaymentInitiator", "PaymentApprover", "PlatformAdmin"],
       code=201)
def create_counterparty(ctx, params, body, query, actor):
    require_fields(body, ["legal_entity_id", "display_name", "external_ref"])
    entity = ctx.legal_entity(body["legal_entity_id"])
    for existing in ctx.store.counterparties.values():
        if (existing["legal_entity_id"] == entity["id"]
                and existing["external_ref"] == body["external_ref"]):
            raise ApiError("ERR_DUPLICATE_REFERENCE_CODE",
                           "external_ref is already used within this institution.")
    limit = body.get("velocity_limit_cents")
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int)):
        raise bad_request("velocity_limit_cents must be an integer.")
    row = ctx.created_row(
        legal_entity_id=entity["id"],
        display_name=body["display_name"],
        external_ref=body["external_ref"],
        velocity_limit_cents=limit,
        status="ACTIVE",
    )
    ctx.store.counterparties[row["id"]] = row
    ctx.append_audit(entity.get("home_ledger_id"), actor, "counterparty.created",
                     "Counterparty", row["id"], {})
    return Resp(ser.serialize("Counterparty", row, ctx))


@route("GET", "/counterparties",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentApprover", "Auditor"])
def list_counterparties(ctx, params, body, query, actor):
    rows = list(ctx.store.counterparties.values())
    if query.get("legal_entity_id"):
        rows = [r for r in rows if r["legal_entity_id"] == query["legal_entity_id"]]
    if query.get("status"):
        rows = [r for r in rows if r["status"] == query["status"]]
    return _page(query, "Counterparty", ctx, rows, created_sort)


@route("GET", "/counterparties/{id}",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentOpsApprover",
        "PaymentApprover", "PaymentInitiator", "CounterpartyUser", "Auditor"])
def get_counterparty(ctx, params, body, query, actor):
    row = ctx.counterparty(params["id"])
    if actor[1] == "CounterpartyUser" and actor[0] != row["id"]:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE",
                       "A CounterpartyUser may only read its own counterparty record.")
    return Resp(ser.serialize("Counterparty", row, ctx))


@route("GET", "/counterparties/{id}/payment-orders",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentApprover",
        "PaymentInitiator", "Auditor"])
def list_counterparty_orders(ctx, params, body, query, actor):
    counterparty = ctx.counterparty(params["id"])
    rows = [r for r in ctx.store.payment_orders.values()
            if r["counterparty_id"] == counterparty["id"]]
    if query.get("status"):
        rows = [r for r in rows if r["status"] == query["status"]]
    return _page(query, "PaymentOrder", ctx, rows, created_sort)


@route("POST", "/counterparties/{id}/restrict", ["PaymentApprover"], single_role=True)
def restrict_counterparty(ctx, params, body, query, actor):
    row = ctx.counterparty(params["id"])
    if row["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_TRANSITION")
    _restrict_counterparty(ctx, row, actor)
    return Resp(ser.serialize("Counterparty", row, ctx))


@route("POST", "/counterparties/{id}/block", ["PaymentApprover"], single_role=True)
def block_counterparty(ctx, params, body, query, actor):
    row = ctx.counterparty(params["id"])
    if row["status"] not in ("ACTIVE", "RESTRICTED"):
        raise ApiError("ERR_INVALID_TRANSITION")
    row["status"] = "BLOCKED"
    ctx.touch(row)
    ctx.append_audit(audit_ledger_for_entity(ctx, row["legal_entity_id"]), actor,
                     "counterparty.blocked", "Counterparty", row["id"],
                     {"to_status": "BLOCKED"})
    return Resp(ser.serialize("Counterparty", row, ctx))


@route("POST", "/counterparties/{id}/unblock", ["PaymentApprover"], single_role=True)
def unblock_counterparty(ctx, params, body, query, actor):
    row = ctx.counterparty(params["id"])
    if row["status"] != "BLOCKED":
        raise ApiError("ERR_INVALID_TRANSITION")
    row["status"] = "RESTRICTED"
    ctx.touch(row)
    ctx.append_audit(audit_ledger_for_entity(ctx, row["legal_entity_id"]), actor,
                     "counterparty.unblocked", "Counterparty", row["id"],
                     {"to_status": "RESTRICTED"})
    return Resp(ser.serialize("Counterparty", row, ctx))


@route("POST", "/counterparties/{id}/restore", ["PaymentApprover"], single_role=True)
def restore_counterparty(ctx, params, body, query, actor):
    row = ctx.counterparty(params["id"])
    if row["status"] != "RESTRICTED":
        raise ApiError("ERR_INVALID_TRANSITION")
    row["status"] = "ACTIVE"
    ctx.touch(row)
    ctx.append_audit(audit_ledger_for_entity(ctx, row["legal_entity_id"]), actor,
                     "counterparty.restored", "Counterparty", row["id"],
                     {"to_status": "ACTIVE"})
    return Resp(ser.serialize("Counterparty", row, ctx))


@route("POST", "/counterparties/{id}/close", ["PaymentApprover"], single_role=True)
def close_counterparty(ctx, params, body, query, actor):
    row = ctx.counterparty(params["id"])
    if row["status"] == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    for order in ctx.store.payment_orders.values():
        if order["counterparty_id"] == row["id"] and order["status"] not in (
                "SETTLED", "RETURNED", "REVERSED", "CANCELLED"):
            raise ApiError("ERR_COUNTERPARTY_NOT_SETTLED")
    row["status"] = "CLOSED"
    ctx.touch(row)
    ctx.append_audit(audit_ledger_for_entity(ctx, row["legal_entity_id"]), actor,
                     "counterparty.closed", "Counterparty", row["id"],
                     {"to_status": "CLOSED"})
    return Resp(ser.serialize("Counterparty", row, ctx))


# ================================================================== RELATIONSHIP

@route("POST", "/counterparty-relationships",
       ["PaymentApprover", "PaymentInitiator", "PlatformAdmin"], code=201)
def create_relationship(ctx, params, body, query, actor):
    require_fields(body, ["legal_entity_id", "partner_legal_entity_id", "purpose"])
    left = ctx.legal_entity(body["legal_entity_id"])
    right = ctx.legal_entity(body["partner_legal_entity_id"])
    if left["id"] == right["id"]:
        raise bad_request("legal_entity_id and partner_legal_entity_id must differ.")
    require_enum(body, "purpose", RELATIONSHIP_PURPOSES)
    sharing = body.get("account_data_sharing", False)
    if not isinstance(sharing, bool):
        raise bad_request("account_data_sharing must be a boolean.")
    for rel in ctx.store.relationships.values():
        pair = {rel["legal_entity_id"], rel["partner_legal_entity_id"]}
        if pair == {left["id"], right["id"]} and rel["status"] == "ACTIVE":
            raise ApiError("ERR_RELATIONSHIP_ALREADY_ACTIVE")
    row = ctx.created_row(
        legal_entity_id=left["id"],
        partner_legal_entity_id=right["id"],
        purpose=body["purpose"],
        account_data_sharing=sharing,
        status="PENDING",
    )
    ctx.store.relationships[row["id"]] = row
    ctx.append_audit(left.get("home_ledger_id"), actor, "counterparty_relationship.created",
                     "CounterpartyRelationship", row["id"], {})
    return Resp(ser.serialize("CounterpartyRelationship", row, ctx))


@route("GET", "/counterparty-relationships",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentApprover", "Auditor"])
def list_relationships(ctx, params, body, query, actor):
    rows = list(ctx.store.relationships.values())
    if query.get("legal_entity_id"):
        rows = [r for r in rows if r["legal_entity_id"] == query["legal_entity_id"]]
    if query.get("partner_legal_entity_id"):
        rows = [r for r in rows if r["partner_legal_entity_id"] == query["partner_legal_entity_id"]]
    if query.get("status"):
        rows = [r for r in rows if r["status"] == query["status"]]
    return _page(query, "CounterpartyRelationship", ctx, rows, created_sort)


@route("GET", "/counterparty-relationships/{id}",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentApprover",
        "PaymentInitiator", "Auditor"])
def get_relationship(ctx, params, body, query, actor):
    row = ctx.relationship(params["id"])
    return Resp(ser.serialize("CounterpartyRelationship", row, ctx))


def _activation_gate(ctx, row):
    for side in (row["legal_entity_id"], row["partner_legal_entity_id"]):
        entity = ctx.store.legal_entities.get(side)
        if entity is None:
            continue
        ledger_id = entity.get("home_ledger_id")
        if ledger_id and ctx.unattributed_deposit_open_on(ledger_id):
            raise ApiError("ERR_LEDGER_UNBALANCED",
                           "An unattributed deposit is still open on one side of "
                           "this relationship.")


@route("POST", "/counterparty-relationships/{id}/activate", ["PaymentApprover"],
       single_role=True)
def activate_relationship(ctx, params, body, query, actor):
    row = ctx.relationship(params["id"])
    ctx.check_version(row, body.get("expected_relationship_version"),
                      "expected_relationship_version")
    if row["status"] not in ("PENDING", "SUSPENDED"):
        if row["status"] == "TERMINATED":
            raise ApiError("ERR_ALREADY_TERMINAL")
        raise ApiError("ERR_INVALID_TRANSITION")
    _activation_gate(ctx, row)
    row["status"] = "ACTIVE"
    ctx.touch(row)
    ctx.append_audit(audit_ledger_for_entity(ctx, row["legal_entity_id"]), actor,
                     "counterparty_relationship.activated", "CounterpartyRelationship",
                     row["id"], {"to_status": "ACTIVE"})
    return Resp(ser.serialize("CounterpartyRelationship", row, ctx))


@route("POST", "/counterparty-relationships/{id}/suspend", ["PaymentApprover"],
       single_role=True)
def suspend_relationship(ctx, params, body, query, actor):
    row = ctx.relationship(params["id"])
    if row["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_TRANSITION")
    row["status"] = "SUSPENDED"
    ctx.touch(row)
    return Resp(ser.serialize("CounterpartyRelationship", row, ctx))


@route("POST", "/counterparty-relationships/{id}/terminate", ["PaymentApprover"],
       single_role=True)
def terminate_relationship(ctx, params, body, query, actor):
    row = ctx.relationship(params["id"])
    if row["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_TRANSITION")
    row["status"] = "TERMINATED"
    ctx.touch(row)
    return Resp(ser.serialize("CounterpartyRelationship", row, ctx))


# ================================================================== BANK ACCOUNT

@route("POST", "/bank-accounts", ["PaymentApprover", "LedgerController", "PlatformAdmin"],
       code=201)
def create_bank_account(ctx, params, body, query, actor):
    require_fields(body, ["legal_entity_id", "institution_name", "routing_number",
                          "account_number_last4", "supported_rails"])
    entity = ctx.legal_entity(body["legal_entity_id"])
    if not aba_checksum_ok(body["routing_number"]):
        raise bad_request("routing_number must be nine digits with a valid ABA checksum.")
    if not _is_digits(body["account_number_last4"], 4):
        raise bad_request("account_number_last4 must be exactly four digits.")
    rails = body["supported_rails"]
    if not isinstance(rails, list) or not rails:
        raise bad_request("supported_rails must be a non-empty array.")
    for rail in rails:
        if rail not in RAILS:
            raise bad_request("supported_rails contains an unknown rail.")
    funds = body.get("available_funds_cents", 0)
    if isinstance(funds, bool) or not isinstance(funds, int):
        raise bad_request("available_funds_cents must be an integer.")
    row = ctx.created_row(
        legal_entity_id=entity["id"],
        institution_name=body["institution_name"],
        routing_number=body["routing_number"],
        account_number_last4=body["account_number_last4"],
        supported_rails=list(rails),
        available_funds_cents=funds,
        status="OPEN",
    )
    ctx.store.bank_accounts[row["id"]] = row
    ctx.append_audit(entity.get("home_ledger_id"), actor, "bank_account.created",
                     "BankAccount", row["id"], {})
    return Resp(ser.serialize("BankAccount", row, ctx))


@route("GET", "/bank-accounts",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentApprover", "Auditor"])
def list_bank_accounts(ctx, params, body, query, actor):
    rows = list(ctx.store.bank_accounts.values())
    if query.get("legal_entity_id"):
        rows = [r for r in rows if r["legal_entity_id"] == query["legal_entity_id"]]
    if query.get("status"):
        rows = [r for r in rows if r["status"] == query["status"]]
    return _page(query, "BankAccount", ctx, rows, created_sort)


@route("GET", "/bank-accounts/{id}",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentOpsApprover",
        "PaymentApprover", "PaymentInitiator", "Auditor"])
def get_bank_account(ctx, params, body, query, actor):
    row = ctx.bank_account(params["id"])
    return Resp(ser.serialize("BankAccount", row, ctx))


@route("GET", "/bank-accounts/{id}/virtual-accounts",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentApprover", "Auditor"])
def list_account_virtual_accounts(ctx, params, body, query, actor):
    account = ctx.bank_account(params["id"])
    rows = [r for r in ctx.store.virtual_accounts.values()
            if r["bank_account_id"] == account["id"]]
    if query.get("status"):
        rows = [r for r in rows if r["status"] == query["status"]]
    return _page(query, "VirtualAccount", ctx, rows, created_sort)


@route("GET", "/bank-accounts/{id}/statements",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentOpsApprover",
        "Auditor"])
def list_account_statements(ctx, params, body, query, actor):
    account = ctx.bank_account(params["id"])
    rows = [r for r in ctx.store.statements.values()
            if r["bank_account_id"] == account["id"]]
    if query.get("status"):
        rows = [r for r in rows if r["status"] == query["status"]]
    return _page(query, "BankStatement", ctx, rows,
                 lambda r: (-r["revision_number"], r["sequence"]))


@route("GET", "/bank-accounts/{id}/settlement-pools",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentOpsApprover",
        "Auditor"])
def list_account_pools(ctx, params, body, query, actor):
    account = ctx.bank_account(params["id"])
    rows = [r for r in ctx.store.settlement_pools.values()
            if account["id"] in r["member_bank_account_ids"]]
    return _page(query, "SettlementPool", ctx, rows, created_sort)


@route("POST", "/bank-accounts/{id}/close", ["LedgerController", "PlatformAdmin"])
def close_bank_account(ctx, params, body, query, actor):
    row = ctx.bank_account(params["id"])
    if row["status"] == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    row["status"] = "CLOSED"
    ctx.touch(row)
    ctx.append_audit(audit_ledger_for_entity(ctx, row["legal_entity_id"]), actor,
                     "bank_account.closed", "BankAccount", row["id"],
                     {"to_status": "CLOSED"})
    return Resp(ser.serialize("BankAccount", row, ctx))


# ================================================================== VIRTUAL ACCOUNT

@route("POST", "/virtual-accounts",
       ["PaymentOpsAnalyst", "PaymentApprover", "PlatformAdmin"], code=201)
def create_virtual_account(ctx, params, body, query, actor):
    require_fields(body, ["bank_account_id", "virtual_account_number", "reference_code"])
    account = ctx.bank_account(body["bank_account_id"])
    number = body["virtual_account_number"]
    if not isinstance(number, str) or not number.isdigit() or not (10 <= len(number) <= 16):
        raise bad_request("virtual_account_number must be 10 to 16 digits.")
    code = body["reference_code"]
    if (not isinstance(code, str) or not (6 <= len(code) <= 12)
            or not code.isalnum() or code != code.upper()):
        raise bad_request("reference_code must be 6 to 12 uppercase alphanumeric characters.")
    for existing in ctx.store.virtual_accounts.values():
        if existing["virtual_account_number"] == number:
            raise ApiError("ERR_DUPLICATE_REFERENCE_CODE",
                           "virtual_account_number is already in use.")
        if existing["reference_code"] == code:
            raise ApiError("ERR_DUPLICATE_REFERENCE_CODE",
                           "reference_code is already in use.")
    row = ctx.created_row(
        bank_account_id=account["id"],
        virtual_account_number=number,
        reference_code=code,
        status="OPEN",
    )
    ctx.store.virtual_accounts[row["id"]] = row
    ctx.append_audit(audit_ledger_for_account(ctx, account["id"]), actor,
                     "virtual_account.created", "VirtualAccount", row["id"], {})
    return Resp(ser.serialize("VirtualAccount", row, ctx))


@route("GET", "/virtual-accounts",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentApprover", "Auditor"])
def list_virtual_accounts(ctx, params, body, query, actor):
    rows = list(ctx.store.virtual_accounts.values())
    if query.get("bank_account_id"):
        rows = [r for r in rows if r["bank_account_id"] == query["bank_account_id"]]
    if query.get("status"):
        rows = [r for r in rows if r["status"] == query["status"]]
    return _page(query, "VirtualAccount", ctx, rows, created_sort)


@route("GET", "/virtual-accounts/{id}",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentOpsApprover",
        "PaymentApprover", "Auditor"])
def get_virtual_account(ctx, params, body, query, actor):
    row = ctx.virtual_account(params["id"])
    return Resp(ser.serialize("VirtualAccount", row, ctx))


@route("POST", "/virtual-accounts/{id}/close", ["PaymentOpsAnalyst", "PlatformAdmin"])
def close_virtual_account(ctx, params, body, query, actor):
    row = ctx.virtual_account(params["id"])
    if row["status"] == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    row["status"] = "CLOSED"
    ctx.touch(row)
    ctx.append_audit(audit_ledger_for_account(ctx, row["bank_account_id"]), actor,
                     "virtual_account.closed", "VirtualAccount", row["id"],
                     {"to_status": "CLOSED"})
    return Resp(ser.serialize("VirtualAccount", row, ctx))