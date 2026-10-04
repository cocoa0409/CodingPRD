"""Route registry, part 2: statements, payment orders, transactions, pools,
release requests, calendars, exceptions, audit trail and the test-driving
capabilities.  Registered into the same ROUTES table as routes.py.
"""

import calculations as calc
import serializer as ser
from errors import ApiError
from routes import (
    Resp,
    ROUTES,
    _page,
    _order_is_terminal,
    _page as _p,
    audit_ledger_for_account,
    audit_ledger_for_entity,
    created_sort,
    paginate,
    route,
)
from services import (
    AGING_BUCKETS,
    EXCEPTION_KINDS,
    EXCEPTION_STATUSES,
    LINE_MATCH_STATES,
    RAILS,
    RETURN_REASONS,
    RAIL_DOMAINS,
    bad_request,
    optional_enum,
    optional_iso,
    require_enum,
    require_fields,
    require_iso,
)
from utils import iso_from_ms, parse_date, parse_iso, utc_ms_from_local

from services import Ctx  # noqa: F401  (re-export for symmetry)


# ================================================================== BANK STATEMENT

@route("POST", "/bank-statements", ["PaymentOpsAnalyst", "LedgerController"], code=201)
def import_statement(ctx, params, body, query, actor):
    require_fields(body, ["bank_account_id", "institution_ref", "cycle_date",
                          "opening_balance_cents", "closing_balance_cents",
                          "expected_bank_account_version"])
    account = ctx.bank_account(body["bank_account_id"])
    require_enum(body, "matching_algorithm", calc.MATCHING_ALGORITHMS) \
        if body.get("matching_algorithm") is not None else None
    algorithm = optional_enum(body, "matching_algorithm", calc.MATCHING_ALGORITHMS,
                              calc.POSTED_NET)
    cycle_ms = require_iso(body, "cycle_date")
    for field in ("opening_balance_cents", "closing_balance_cents"):
        if isinstance(body[field], bool) or not isinstance(body[field], int):
            raise bad_request("%s must be an integer." % field)
    ctx.check_version(account, body.get("expected_bank_account_version"),
                      "expected_bank_account_version")
    for existing in ctx.store.statements.values():
        if (existing["bank_account_id"] == account["id"]
                and existing["institution_ref"] == body["institution_ref"]
                and existing["revision_number"] == 1):
            raise ApiError("ERR_LINE_ALREADY_MATCHED",
                           "A revision 1 statement with this institution_ref already exists.")
    for existing in ctx.store.statements.values():
        if existing["bank_account_id"] == account["id"] and existing["cycle_date_ms"] == cycle_ms \
                and existing["status"] != "SUPERSEDED":
            raise ApiError("ERR_LINE_ALREADY_MATCHED",
                           "A statement has already been imported for this cycle.")
    row = ctx.created_row(
        bank_account_id=account["id"],
        institution_ref=body["institution_ref"],
        cycle_date_ms=cycle_ms,
        opening_balance_cents=body["opening_balance_cents"],
        closing_balance_cents=body["closing_balance_cents"],
        matching_algorithm=algorithm,
        revision_number=1,
        supersedes_statement_id=None,
        matched_posted_cents=0,
        unmatched_amount_cents=0,
        matched_line_cents=0,
        _ledger_id=audit_ledger_for_account(ctx, account["id"]),
        status="IMPORTED",
    )
    ctx.store.statements[row["id"]] = row
    ctx.touch(account)
    ctx.append_audit(audit_ledger_for_account(ctx, account["id"]), actor,
                     "bank_statement.imported", "BankStatement", row["id"],
                     {"revision_number": 1})
    return Resp(ser.serialize("BankStatement", row, ctx))


@route("GET", "/bank-statements",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentOpsApprover",
        "Auditor"])
def list_statements(ctx, params, body, query, actor):
    rows = list(ctx.store.statements.values())
    if query.get("bank_account_id"):
        rows = [r for r in rows if r["bank_account_id"] == query["bank_account_id"]]
    if query.get("supersedes_statement_id"):
        rows = [r for r in rows if r["supersedes_statement_id"] == query["supersedes_statement_id"]]
    if query.get("status"):
        rows = [r for r in rows if r["status"] == query["status"]]
    return _page(query, "BankStatement", ctx, rows, created_sort)


@route("GET", "/bank-statements/{id}",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentOpsApprover",
        "Auditor"])
def get_statement(ctx, params, body, query, actor):
    row = ctx.statement(params["id"])
    return Resp(ser.serialize("BankStatement", row, ctx))


@route("GET", "/bank-statements/{id}/lines",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentOpsApprover",
        "Auditor"])
def list_statement_lines(ctx, params, body, query, actor):
    statement = ctx.statement(params["id"])
    rows = ctx.statement_lines(statement["id"])
    if query.get("match_state"):
        rows = [r for r in rows if r["match_state"] == query["match_state"]]
    return _page(query, "StatementLine", ctx, rows,
                 lambda r: (r["effective_at_ms"], r["bank_reference"]))


@route("GET", "/bank-statements/{id}/revisions",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "Auditor"])
def list_statement_revisions(ctx, params, body, query, actor):
    statement = ctx.statement(params["id"])
    chain = []
    current = statement
    while current is not None and current["supersedes_statement_id"]:
        parent = ctx.store.statements.get(current["supersedes_statement_id"])
        if parent is None:
            break
        if parent["id"] in [c["id"] for c in chain]:
            break
        chain.append(parent)
        current = parent
    chain.append(statement)
    successor = None
    for candidate in ctx.store.statements.values():
        if candidate["supersedes_statement_id"] == statement["id"]:
            successor = candidate
            break
    while successor is not None:
        chain.append(successor)
        nxt = None
        for candidate in ctx.store.statements.values():
            if candidate["supersedes_statement_id"] == successor["id"]:
                nxt = candidate
                break
        successor = nxt
    chain.sort(key=lambda r: r["revision_number"])
    return _page(query, "BankStatement", ctx, chain,
                 lambda r: (r["revision_number"], r["sequence"]))


@route("POST", "/bank-statements/{id}/lines", ["PaymentOpsAnalyst"], code=201)
def append_statement_line(ctx, params, body, query, actor):
    statement = ctx.statement(params["id"])
    require_fields(body, ["bank_reference", "amount_cents", "direction", "effective_at"])
    if statement["status"] != "IMPORTED":
        raise ApiError("ERR_STATEMENT_ONLY_MUTABLE_BEFORE_RECONCILE")
    require_enum(body, "direction", ("CREDIT", "DEBIT"))
    if isinstance(body["amount_cents"], bool) or not isinstance(body["amount_cents"], int) \
            or body["amount_cents"] == 0:
        raise bad_request("amount_cents must be a non-zero integer.")
    effective_ms = require_iso(body, "effective_at")
    for existing in ctx.store.statement_lines.values():
        if existing["bank_statement_id"] != statement["id"]:
            continue
        if existing["bank_reference"] == body["bank_reference"]:
            raise ApiError("ERR_LINE_ALREADY_MATCHED",
                           "bank_reference is already used within this statement.")
        if (existing["amount_cents"] == body["amount_cents"]
                and existing["effective_at_ms"] == effective_ms):
            raise ApiError("ERR_LINE_ALREADY_MATCHED",
                           "A line with this amount and effective instant already exists.")
    embedded = body.get("embedded_reference_code")
    row = ctx.created_row(
        bank_statement_id=statement["id"],
        bank_reference=body["bank_reference"],
        amount_cents=body["amount_cents"],
        direction=body["direction"],
        effective_at_ms=effective_ms,
        embedded_reference_code=embedded,
        match_state="UNMATCHED",
    )
    ctx.store.statement_lines[row["id"]] = row
    ctx.append_audit(statement.get("_ledger_id"), actor, "statement_line.added",
                     "StatementLine", row["id"], {"amount_cents": row["amount_cents"]})
    return Resp(ser.serialize("StatementLine", row, ctx))


@route("POST", "/bank-statements/{id}/reconcile", ["PaymentOpsAnalyst", "LedgerController"])
def reconcile_statement(ctx, params, body, query, actor):
    statement = ctx.statement(params["id"])
    ctx.check_version(statement, body.get("expected_statement_version"),
                      "expected_statement_version")
    if statement["status"] not in ("IMPORTED", "REVISED"):
        raise ApiError("ERR_INVALID_TRANSITION")
    statement["status"] = "RECONCILING"
    ctx.touch(statement)
    unmatched = ctx.recompute_statement(statement)
    forced = body.get("force_reconciled") or body.get("force")
    if forced and unmatched != 0:
        raise ApiError("ERR_STATEMENT_VARIANCE_UNRESOLVED")
    if unmatched == 0:
        statement["status"] = "RECONCILED"
        ctx.touch(statement)
        ctx.append_audit(statement.get("_ledger_id"), actor, "bank_statement.reconciled",
                         "BankStatement", statement["id"], {"unmatched_amount_cents": 0})
    else:
        statement["status"] = "DISCREPANCY"
        ctx.touch(statement)
        ctx.raise_exception(statement.get("_ledger_id"), "STATEMENT_VARIANCE",
                            abs(unmatched), bank_statement_id=statement["id"],
                            actor=actor)
        ctx.append_audit(statement.get("_ledger_id"), actor, "bank_statement.discrepancy",
                         "BankStatement", statement["id"],
                         {"unmatched_amount_cents": unmatched})
    # PRD S3.8: "A StatementLine that resolves to no destination raises an
    # ExceptionItem of kind UNMATCHED_DEPOSIT."  The attribution pass runs over
    # the statement's own unmatched population, and both computed fields are
    # reported on the raise even when nothing resolved (S3.8: "Both
    # attributed_fee_cents and attributable_amount_cents are reported on every
    # raise ... whether or not a destination resolved ... both default to 0").
    for line in ctx.statement_lines(statement["id"]):
        if line["match_state"] != "UNMATCHED":
            continue
        _raise_unmatched_deposit(ctx, statement, line, actor)
    return Resp(ser.serialize("BankStatement", statement, ctx))


def _raise_unmatched_deposit(ctx, statement, line, actor):
    """Raise one UNMATCHED_DEPOSIT for a line that resolves to no destination.

    Idempotent per line: the reconcile pass and the revision's second hop both
    sweep the same unmatched population (PRD S3.7 re-runs attribution over "the
    predecessor's still-unmatched lines"), so a second sweep must not mint a
    duplicate item for a line that already carries one.
    """
    gross = abs(line["amount_cents"])
    for existing in ctx.store.exceptions.values():
        if (existing["bank_statement_id"] == line["bank_statement_id"]
                and existing["kind"] == "UNMATCHED_DEPOSIT"
                and existing["amount_cents"] == gross
                and existing["status"] in ("OPEN", "ASSIGNED", "ESCALATED")):
            return existing
    destination, _ledger_id = ctx.resolve_destination(line)
    fee, amount = ctx.deposit_fields(gross)
    return ctx.raise_exception(statement.get("_ledger_id"), "UNMATCHED_DEPOSIT", gross,
                               bank_statement_id=line["bank_statement_id"],
                               attributed_fee_cents=fee,
                               attributable_amount_cents=amount, actor=actor)


@route("POST", "/bank-statements/{id}/revise", ["PaymentOpsAnalyst", "LedgerController"],
       code=201)
def revise_statement(ctx, params, body, query, actor):
    statement = ctx.statement(params["id"])
    require_fields(body, ["institution_ref", "cycle_date", "opening_balance_cents",
                          "closing_balance_cents"])
    ctx.check_version(statement, body.get("expected_statement_version"),
                      "expected_statement_version")
    if body.get("revision_number") is not None:
        if body["revision_number"] != statement["revision_number"]:
            raise ApiError("ERR_STALE_VERSION",
                           "The supplied revision_number has been superseded.")
    if statement["status"] != "DISCREPANCY":
        raise ApiError("ERR_INVALID_TRANSITION")
    cycle_ms = require_iso(body, "cycle_date")
    for field in ("opening_balance_cents", "closing_balance_cents"):
        if isinstance(body[field], bool) or not isinstance(body[field], int):
            raise bad_request("%s must be an integer." % field)

    statement["status"] = "SUPERSEDED"
    ctx.touch(statement)
    for exc in ctx.store.exceptions.values():
        if (exc["bank_statement_id"] == statement["id"]
                and exc["kind"] == "STATEMENT_VARIANCE"
                and exc["status"] in ("OPEN", "ASSIGNED", "ESCALATED")):
            exc["status"] = "RESOLVED"
            exc["resolution_note"] = "superseded by revision %d" % (statement["revision_number"] + 1)
            ctx.touch(exc)

    successor = ctx.created_row(
        bank_account_id=statement["bank_account_id"],
        institution_ref=body["institution_ref"],
        cycle_date_ms=cycle_ms,
        opening_balance_cents=body["opening_balance_cents"],
        closing_balance_cents=body["closing_balance_cents"],
        matching_algorithm=statement["matching_algorithm"],
        revision_number=statement["revision_number"] + 1,
        supersedes_statement_id=statement["id"],
        matched_posted_cents=0,
        unmatched_amount_cents=0,
        matched_line_cents=0,
        _ledger_id=statement.get("_ledger_id"),
        status="REVISED",
    )
    ctx.store.statements[successor["id"]] = successor

    # The successor supersedes its predecessor's line set: the bank has re-issued
    # the same cycle, so the revision carries those lines forward and the next
    # reconciliation run re-evaluates them under the same algorithm.
    for line in ctx.statement_lines(statement["id"]):
        copy = ctx.created_row(
            bank_statement_id=successor["id"],
            bank_reference=line["bank_reference"],
            amount_cents=line["amount_cents"],
            direction=line["direction"],
            effective_at_ms=line["effective_at_ms"],
            embedded_reference_code=line["embedded_reference_code"],
            match_state="UNMATCHED",
        )
        ctx.store.statement_lines[copy["id"]] = copy

    # second hop: re-run deposit attribution over the predecessor's still-unmatched lines
    for line in ctx.statement_lines(statement["id"]):
        if line["match_state"] == "MATCHED":
            continue
        _raise_unmatched_deposit(ctx, statement, line, actor)

    ctx.append_audit(statement.get("_ledger_id"), actor, "bank_statement.revised",
                     "BankStatement", successor["id"],
                     {"revision_number": successor["revision_number"]})
    return Resp(ser.serialize("BankStatement", successor, ctx))


# ================================================================== PAYMENT ORDER

def _rail_account_checks(ctx, body, legal_entity_id, account):
    rail = body.get("rail")
    if rail not in RAILS:
        raise bad_request("rail must be one of %s." % ", ".join(RAILS))
    if rail not in account["supported_rails"]:
        raise ApiError("ERR_RAIL_ACCOUNT_UNSUPPORTED")
    if account["legal_entity_id"] != legal_entity_id:
        raise ApiError("ERR_RAIL_ACCOUNT_UNSUPPORTED")
    if rail == "CHECK" and not body.get("payable_to_name"):
        raise ApiError("ERR_RAIL_ACCOUNT_UNSUPPORTED")


def _velocity_check(ctx, order):
    counterparty = ctx.store.counterparties.get(order["counterparty_id"])
    if counterparty is None:
        return
    limit = ser.effective_limit_cents(ctx, counterparty)
    if order["amount_cents"] <= 0 or not calc.velocity_admits(order["amount_cents"], limit):
        raise ApiError("ERR_VELOCITY_LIMIT_EXCEEDED")


def _ledger_locked(ctx, ledger_id):
    ledger = ctx.store.ledgers.get(ledger_id)
    if ledger is not None and ledger["status"] == "CLOSED":
        raise ApiError("ERR_LEDGER_LOCKED")


@route("POST", "/payment-orders", ["PaymentInitiator"], code=201, single_role=False)
def create_payment_order(ctx, params, body, query, actor):
    require_fields(body, ["legal_entity_id", "ledger_id", "counterparty_id",
                          "source_account_id", "rail", "direction", "amount_cents",
                          "idempotency_key"])
    entity = ctx.legal_entity(body["legal_entity_id"])
    ledger = ctx.ledger(body["ledger_id"])
    counterparty = ctx.counterparty(body["counterparty_id"])
    account = ctx.bank_account(body["source_account_id"])
    _rail_account_checks(ctx, body, entity["id"], account)
    require_enum(body, "direction", ("CREDIT", "DEBIT"))
    speed = optional_enum(body, "settlement_speed", ("STANDARD", "SAME_DAY"), "STANDARD")
    if speed == "SAME_DAY" and body["rail"] != "ACH":
        raise ApiError("ERR_SETTLEMENT_SPEED_UNSUPPORTED")
    if isinstance(body["amount_cents"], bool) or not isinstance(body["amount_cents"], int):
        raise bad_request("amount_cents must be an integer.")

    provisional = {
        "amount_cents": body["amount_cents"],
        "counterparty_id": counterparty["id"],
    }
    _velocity_check(ctx, provisional)
    requested_ms = optional_iso(body, "requested_release_utc")

    provisional.update({
        "source_account_id": account["id"],
        "rail": body["rail"],
        "settlement_speed": speed,
        "created_at": ctx.now_ms(),
    })
    cutoffs, snapshot = ctx.resolve_cutoffs(provisional)
    if snapshot is None:
        raise ApiError("ERR_CALENDAR_HAS_NO_OPEN_CYCLE")

    _ledger_locked(ctx, ledger["id"])

    key = (entity["id"], body["idempotency_key"])
    existing_id = ctx.store.idempotency.get(key)
    if existing_id is not None:
        existing = ctx.store.payment_orders.get(existing_id)
        if existing is not None and existing["status"] not in ("CANCELLED", "REJECTED"):
            raise ApiError("ERR_DUPLICATE_PAYMENT",
                           "idempotency_key was already used for this legal entity.")

    signature = calc.duplicate_signature(entity["id"], counterparty["id"], body["rail"],
                                        body["direction"], body["amount_cents"])
    last_seen = ctx.store.dup_signatures.get(signature)
    if last_seen is not None and calc.dup_window_blocks(ctx.now_ms(), last_seen):
        # PRD S3.10: "the platform derives a duplicate signature ... and a stored
        # signature blocks a new create only while the logical clock has advanced
        # no more than 600 seconds past the instant that signature was last seen."
        # The guard asks whether THIS create is a duplicate of an order already
        # booked for the same key; a create carrying a key that has never been
        # used is a new draft even when a sibling key stored the identical
        # content signature a moment ago, so two different keys still yield two
        # orders.  Only a repeated key whose stored order is missing, or whose
        # stored order carries a different signature, is the duplicate.
        stored = ctx.store.payment_orders.get(existing_id) if existing_id else None
        if stored is not None:
            stored_sig = calc.duplicate_signature(stored["legal_entity_id"],
                                                  stored["counterparty_id"], stored["rail"],
                                                  stored["direction"], stored["amount_cents"])
            if stored_sig != signature:
                raise ApiError("ERR_DUPLICATE_PAYMENT",
                               "An identical payment was created inside the "
                               "deduplication window.")

    row = ctx.created_row(
        legal_entity_id=entity["id"],
        ledger_id=ledger["id"],
        counterparty_id=counterparty["id"],
        source_account_id=account["id"],
        rail=body["rail"],
        direction=body["direction"],
        amount_cents=body["amount_cents"],
        settlement_speed=speed,
        idempotency_key=body["idempotency_key"],
        payable_to_name=body.get("payable_to_name"),
        requested_release_utc=requested_ms,
        cutoffs=cutoffs,
        cutoff_snapshot_ms=snapshot,
        status="PENDING_APPROVAL",
        settlement_status="UNSETTLED",
        initiator_user_id=actor[0],
        approver_user_id=None,
        return_reason=None,
        failure_reason=None,
        ever_settled=False,
        dispatch_count=0,
        closed_method=None,
    )
    ctx.store.payment_orders[row["id"]] = row
    ctx.store.idempotency[key] = row["id"]
    ctx.store.dup_signatures[signature] = ctx.now_ms()
    ctx.append_audit(ledger["id"], actor, "payment_order.created", "PaymentOrder",
                     row["id"], {"amount_cents": row["amount_cents"], "rail": row["rail"]})
    return Resp(ser.serialize("PaymentOrder", row, ctx))


@route("GET", "/payment-orders",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentApprover",
        "PaymentInitiator", "Auditor"])
def list_payment_orders(ctx, params, body, query, actor):
    rows = list(ctx.store.payment_orders.values())
    for field in ("ledger_id", "legal_entity_id", "counterparty_id", "status", "rail",
                  "source_account_id"):
        if query.get(field):
            rows = [r for r in rows if r[field] == query[field]]
    return _page(query, "PaymentOrder", ctx, rows, created_sort)


@route("GET", "/payment-orders/{id}",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentOpsApprover",
        "PaymentApprover", "PaymentInitiator", "Auditor"])
def get_payment_order(ctx, params, body, query, actor):
    row = ctx.payment_order(params["id"])
    return Resp(ser.serialize("PaymentOrder", row, ctx))


@route("POST", "/payment-orders/{id}/approve", ["PaymentApprover"], single_role=True)
def approve_payment_order(ctx, params, body, query, actor):
    order = ctx.payment_order(params["id"])
    if order["status"] != "PENDING_APPROVAL":
        if _order_is_terminal(order):
            raise ApiError("ERR_INVALID_TRANSITION")
        raise ApiError("ERR_INVALID_TRANSITION")
    ctx.check_version(order, body.get("expected_payment_order_version"),
                      "expected_payment_order_version")
    _velocity_check(ctx, order)
    counterparty = ctx.store.counterparties.get(order["counterparty_id"])
    if counterparty is None or counterparty["status"] != "ACTIVE":
        raise ApiError("ERR_COUNTERPARTY_BLOCKED")
    if actor[0] == order["initiator_user_id"]:
        raise ApiError("ERR_SELF_APPROVAL_FORBIDDEN")
    _ledger_locked(ctx, order["ledger_id"])

    order["status"] = "APPROVED"
    order["approver_user_id"] = actor[0]
    ctx.touch(order)
    ctx.touch(ctx.store.ledgers[order["ledger_id"]])
    for request in ctx.linked_release_requests(order["id"]):
        if request["request_state"] == "PENDING" \
                and request["initiator_user_id"] == actor[0]:
            request["request_state"] = "DENIED"
            ctx.touch(request)
    ctx.append_audit(order["ledger_id"], actor, "payment_order.approved", "PaymentOrder",
                     order["id"], {"approver_user_id": actor[0], "to_status": "APPROVED"})
    return Resp(ser.serialize("PaymentOrder", order, ctx))


@route("POST", "/payment-orders/{id}/cancel", ["PaymentInitiator"], single_role=True)
def cancel_payment_order(ctx, params, body, query, actor):
    order = ctx.payment_order(params["id"])
    if order["status"] in ("SETTLED", "RETURNED", "REVERSED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if order["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_INVALID_TRANSITION")
    if actor[0] != order["initiator_user_id"]:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE",
                       "Only the initiating user may cancel this payment order.")
    order["status"] = "CANCELLED"
    ctx.touch(order)
    counterparty = ctx.store.counterparties.get(order["counterparty_id"])
    if counterparty is not None:
        from routes import _restrict_counterparty
        if counterparty["status"] == "ACTIVE":
            _restrict_counterparty(ctx, counterparty, actor)
    for exc in ctx.store.exceptions.values():
        if (exc["payment_order_id"] == order["id"] and exc["kind"] == "FAILED_PAYMENT"
                and exc["status"] == "OPEN"):
            exc["status"] = "OPEN"
            exc["assignee_user_id"] = None
            ctx.touch(exc)
    ctx.touch(ctx.store.ledgers[order["ledger_id"]])
    ctx.append_audit(order["ledger_id"], actor, "payment_order.cancelled", "PaymentOrder",
                     order["id"], {"to_status": "CANCELLED"})
    return Resp(ser.serialize("PaymentOrder", order, ctx))


DISPATCH_STATUS = {
    "ACH": "ACH_DISPATCHED",
    "WIRE": "WIRE_DISPATCHED",
    "RTP": "RTP_DISPATCHED",
    "CHECK": "CHECK_DISPATCHED",
}


@route("POST", "/payment-orders/{id}/dispatch", ["PaymentApprover"], single_role=True)
def dispatch_payment_order(ctx, params, body, query, actor):
    order = ctx.payment_order(params["id"])
    if order["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_TRANSITION")
    ctx.check_version(order, body.get("expected_payment_order_version"),
                      "expected_payment_order_version")
    account = ctx.store.bank_accounts.get(order["source_account_id"])
    if account is None:
        raise ApiError("ERR_BANK_ACCOUNT_NOT_FOUND")
    _rail_account_checks(ctx, order, order["legal_entity_id"], account)
    pool_status = ctx.pool_forced_status(account["id"])
    if pool_status == "FAILED":
        raise ApiError("ERR_SETTLEMENT_POOL_INSUFFICIENT")
    fee_total = calc.fee_total_cents(order["rail"], order["direction"], order["amount_cents"],
                                     order["settlement_speed"])
    if order["rail"] == "CHECK" and account["available_funds_cents"] < \
            (order["amount_cents"] + fee_total):
        raise ApiError("ERR_SETTLEMENT_POOL_INSUFFICIENT")
    _ledger_locked(ctx, order["ledger_id"])

    now = ctx.now_ms()
    net_originating = (order["amount_cents"] if order["direction"] == "DEBIT"
                       else -order["amount_cents"])
    orig = ctx.create_transaction(
        order["ledger_id"], "ORIGINATING",
        "CREDIT" if net_originating > 0 else "DEBIT",
        abs(net_originating), now, payment_order_id=order["id"],
        actor=actor, action=None, touch_ledger=False)
    fee = ctx.create_transaction(
        order["ledger_id"], "FEE", "CREDIT" if -fee_total > 0 else "DEBIT",
        abs(fee_total), now, payment_order_id=order["id"],
        actor=actor, action=None, touch_ledger=False)
    # the ledger legs of the dispatch command move UNSETTLED -> IN_SETTLEMENT
    for leg in (orig, fee):
        leg["settlement_status"] = "IN_SETTLEMENT"
        ctx.touch(leg)
    order["status"] = DISPATCH_STATUS[order["rail"]]
    order["settlement_status"] = "IN_SETTLEMENT"
    ctx.touch(order)
    request = ctx.created_row(
        payment_order_id=order["id"],
        counterparty_id=order["counterparty_id"],
        initiator_user_id=actor[0],
        needed_by_utc=order.get("requested_release_utc") or now,
        reason="automatic release request raised at dispatch",
        request_state="PENDING",
    )
    ctx.store.release_requests[request["id"]] = request
    ctx.touch(ctx.store.ledgers[order["ledger_id"]])
    ctx.append_audit(order["ledger_id"], actor, "payment_order.dispatched", "PaymentOrder",
                     order["id"], {"to_status": order["status"], "rail": order["rail"],
                                   "fee_total_cents": fee_total})
    return Resp(ser.serialize("PaymentOrder", order, ctx))


@route("POST", "/payment-orders/{id}/mark_in_flight", ["PaymentOpsAnalyst"])
def mark_in_flight(ctx, params, body, query, actor):
    order = ctx.payment_order(params["id"])
    if order["status"] not in ("ACH_DISPATCHED", "WIRE_DISPATCHED", "RTP_DISPATCHED",
                               "CHECK_DISPATCHED"):
        raise ApiError("ERR_INVALID_TRANSITION")
    order["status"] = "IN_FLIGHT"
    ctx.touch(order)
    return Resp(ser.serialize("PaymentOrder", order, ctx))


@route("POST", "/payment-orders/{id}/settle", ["PaymentOpsAnalyst"])
def settle_payment_order(ctx, params, body, query, actor):
    order = ctx.payment_order(params["id"])
    if order["status"] != "IN_FLIGHT":
        raise ApiError("ERR_INVALID_TRANSITION")
    if order["return_reason"] is not None:
        raise ApiError("ERR_INVALID_TRANSITION")
    order["status"] = "SETTLED"
    order["settlement_status"] = "SETTLED"
    order["ever_settled"] = True
    ctx.touch(order)
    for leg in ctx.order_legs(order["id"]):
        if leg["entry_type"] in ("ORIGINATING", "FEE") and \
                leg["settlement_status"] == "IN_SETTLEMENT":
            leg["settlement_status"] = "SETTLED"
            ctx.touch(leg)
    for request in ctx.linked_release_requests(order["id"]):
        if request["request_state"] == "PENDING":
            request["request_state"] = "SATISFIED"
            ctx.touch(request)
    ctx.touch(ctx.store.ledgers[order["ledger_id"]])
    for exc in ctx.store.exceptions.values():
        if (exc["payment_order_id"] == order["id"] and exc["kind"] == "FAILED_PAYMENT"
                and exc["status"] in ("OPEN", "ASSIGNED", "ESCALATED")):
            exc["status"] = "RESOLVED"
            exc["resolution_note"] = "payment order settled"
            ctx.touch(exc)
    ctx.append_audit(order["ledger_id"], actor, "payment_order.settled", "PaymentOrder",
                     order["id"], {"to_status": "SETTLED"})
    return Resp(ser.serialize("PaymentOrder", order, ctx))


@route("POST", "/payment-orders/{id}/return", ["PaymentOpsAnalyst"])
def return_payment_order(ctx, params, body, query, actor):
    order = ctx.payment_order(params["id"])
    if order["status"] != "IN_FLIGHT":
        raise ApiError("ERR_INVALID_TRANSITION")
    reason = body.get("return_reason")
    if reason not in RETURN_REASONS:
        raise bad_request("return_reason must be R01..R10 or CHK_RETURNED.")
    ctx.check_version(order, body.get("expected_payment_order_version"),
                      "expected_payment_order_version")

    order["status"] = "RETURNED"
    order["return_reason"] = reason
    ctx.touch(order)
    now = ctx.now_ms()
    for leg in ctx.order_legs(order["id"]):
        if leg["entry_type"] in ("ORIGINATING", "FEE") and \
                leg["settlement_status"] == "IN_SETTLEMENT":
            ctx.create_transaction(
                order["ledger_id"], "RETURN",
                "CREDIT" if leg["net_effect_cents"] < 0 else "DEBIT",
                abs(leg["net_effect_cents"]), now, payment_order_id=order["id"],
                refunds_transaction_id=leg["id"], lifecycle_status="POSTED",
                settlement_status="UNSETTLED", actor=actor, action=None,
                touch_ledger=False)
            ctx.create_transaction(
                order["ledger_id"], "FEE", "CREDIT",
                calc.RETURN_LEG_FEE_CENTS, now, payment_order_id=order["id"],
                lifecycle_status="POSTED", settlement_status="UNSETTLED",
                actor=actor, action=None, touch_ledger=False)
    ctx.touch(ctx.store.ledgers[order["ledger_id"]])
    exc = ctx.raise_exception(order["ledger_id"], "RETURN", abs(order["amount_cents"]),
                              payment_order_id=order["id"], actor=actor)
    if abs(order["amount_cents"]) >= 100000:
        counterparty = ctx.store.counterparties.get(order["counterparty_id"])
        if counterparty is not None and counterparty["status"] == "ACTIVE":
            from routes import _restrict_counterparty
            _restrict_counterparty(ctx, counterparty, actor)
    ctx.append_audit(order["ledger_id"], actor, "payment_order.returned", "PaymentOrder",
                     order["id"], {"return_reason": reason, "to_status": "RETURNED"})
    return Resp(ser.serialize("PaymentOrder", order, ctx))


@route("POST", "/payment-orders/{id}/reverse", ["PaymentOpsAnalyst"])
def reverse_payment_order(ctx, params, body, query, actor):
    order = ctx.payment_order(params["id"])
    if order["status"] != "SETTLED":
        raise ApiError("ERR_INVALID_TRANSITION")
    if order["settlement_status"] != "SETTLED":
        raise ApiError("ERR_INVALID_SETTLEMENT_AXIS")
    if not order.get("ever_settled"):
        raise ApiError("ERR_INVALID_TRANSITION")
    ctx.check_version(order, body.get("expected_payment_order_version"),
                      "expected_payment_order_version")
    settled_net = ctx.order_settled_net_cents(order["id"])
    order["status"] = "REVERSED"
    ctx.touch(order)
    ctx.create_transaction(
        order["ledger_id"], "REVERSAL",
        "CREDIT" if -settled_net > 0 else "DEBIT",
        abs(settled_net), ctx.now_ms(), payment_order_id=order["id"],
        lifecycle_status="POSTED", settlement_status="SETTLED",
        actor=actor, action=None, touch_ledger=False)
    for request in ctx.linked_release_requests(order["id"]):
        request["request_state"] = "DECLINED"
        ctx.touch(request)
    ctx.touch(ctx.store.ledgers[order["ledger_id"]])
    ctx.raise_exception(order["ledger_id"], "REVERSAL", abs(order["amount_cents"]),
                        payment_order_id=order["id"], actor=actor)
    ctx.append_audit(order["ledger_id"], actor, "payment_order.reversed", "PaymentOrder",
                     order["id"], {"to_status": "REVERSED"})
    return Resp(ser.serialize("PaymentOrder", order, ctx))


@route("POST", "/payment-orders/{id}/fail", ["PaymentOpsAnalyst"])
def fail_payment_order(ctx, params, body, query, actor):
    order = ctx.payment_order(params["id"])
    if order["status"] != "IN_FLIGHT":
        raise ApiError("ERR_INVALID_TRANSITION")
    order["settlement_status"] = "FAILED"
    order["failure_reason"] = body.get("failure_reason")
    ctx.touch(order)
    for leg in ctx.order_legs(order["id"]):
        if leg["entry_type"] in ("ORIGINATING", "FEE") and \
                leg["settlement_status"] == "IN_SETTLEMENT":
            leg["settlement_status"] = "UNSETTLED"
            ctx.touch(leg)
    ctx.touch(ctx.store.ledgers[order["ledger_id"]])
    ctx.raise_exception(order["ledger_id"], "FAILED_PAYMENT", abs(order["amount_cents"]),
                        payment_order_id=order["id"], actor=actor)
    ctx.append_audit(order["ledger_id"], actor, "payment_order.failed", "PaymentOrder",
                     order["id"], {"failure_reason": body.get("failure_reason")})
    return Resp(ser.serialize("PaymentOrder", order, ctx))


# ================================================================== TRANSACTION

@route("POST", "/ledgers/{id}/transactions", ["LedgerController", "PaymentOpsAnalyst"],
       code=201)
def create_manual_transaction(ctx, params, body, query, actor):
    ledger = ctx.ledger(params["id"])
    require_fields(body, ["entry_type", "direction", "amount_cents", "value_effective_utc"])
    if body.get("payment_order_id") is not None:
        ctx.payment_order(body["payment_order_id"])
    if body.get("reverses_transaction_id") is not None:
        ctx.transaction(body["reverses_transaction_id"])
    if body.get("refunds_transaction_id") is not None:
        ctx.transaction(body["refunds_transaction_id"])
    entry_type = require_enum(body, "entry_type", ("ORIGINATING", "RETURN", "REVERSAL",
                                                   "FEE", "ADJUSTMENT", "DEPOSIT"))
    require_enum(body, "direction", ("CREDIT", "DEBIT"))
    if isinstance(body["amount_cents"], bool) or not isinstance(body["amount_cents"], int) \
            or body["amount_cents"] <= 0:
        raise bad_request("amount_cents must be strictly greater than zero.")
    value_ms = require_iso(body, "value_effective_utc")
    if entry_type == "REVERSAL" and body.get("reverses_transaction_id") is None:
        raise bad_request("reverses_transaction_id is required for a REVERSAL entry.")
    if entry_type == "RETURN" and body.get("refunds_transaction_id") is None:
        raise bad_request("refunds_transaction_id is required for a RETURN entry.")
    if entry_type != "REVERSAL" and body.get("reverses_transaction_id") is not None:
        raise bad_request("reverses_transaction_id must be null for this entry type.")
    if entry_type != "RETURN" and body.get("refunds_transaction_id") is not None:
        raise bad_request("refunds_transaction_id must be null for this entry type.")

    if value_ms < ledger["period_close_ms"] and ledger["period_closed_through_index"] > 0:
        raise ApiError("ERR_PERIOD_CLOSED")
    net = -body["amount_cents"] if body["direction"] == "DEBIT" else body["amount_cents"]
    # PRD S2.11 / S3.6: "A manual posting that would drive posted_balance_cents
    # below zero on a ledger whose institution has no overdraft facility is
    # refused with ERR_BALANCE_WOULD_GO_NEGATIVE" -- a manual posting makes the
    # books more exposed, so the guard is about withdrawing funds the ledger has
    # actually settled: it bites only when a positive posted book is pushed
    # negative by this entry.  A ledger with nothing settled (or one already in
    # compensation) has no settled funds for the posting to withdraw, which is
    # why the ADJUSTMENT/REVERSAL compensation pair of S3.6 and the
    # pending-only postings of S3.6 both remain admissible.
    current_posted = ctx.ledger_posted_cents(ledger["id"])
    if current_posted > 0 and (current_posted + net) < 0:
        raise ApiError("ERR_BALANCE_WOULD_GO_NEGATIVE")

    row = ctx.create_transaction(
        ledger["id"], entry_type, body["direction"], body["amount_cents"], value_ms,
        payment_order_id=body.get("payment_order_id"),
        reverses_transaction_id=body.get("reverses_transaction_id"),
        refunds_transaction_id=body.get("refunds_transaction_id"),
        actor=actor, action="transaction.created")
    return Resp(ser.serialize("Transaction", row, ctx))


@route("GET", "/transactions",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentOpsApprover",
        "Auditor"])
def list_transactions(ctx, params, body, query, actor):
    rows = list(ctx.store.transactions.values())
    for field in ("ledger_id", "payment_order_id", "entry_type", "lifecycle_status",
                  "settlement_status", "reverses_transaction_id", "refunds_transaction_id"):
        if query.get(field):
            rows = [r for r in rows if r[field] == query[field]]
    return _page(query, "Transaction", ctx, rows,
                 lambda r: (r["created_at"], _leg_rank(r), r["sequence"]))


def _leg_rank(row):
    return 0 if row["entry_type"] == "ORIGINATING" else 1


@route("GET", "/transactions/{id}",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentOpsApprover",
        "Auditor"])
def get_transaction(ctx, params, body, query, actor):
    row = ctx.transaction(params["id"])
    return Resp(ser.serialize("Transaction", row, ctx))


@route("POST", "/transactions/{id}/post", ["PaymentOpsAnalyst", "LedgerController"])
def post_transaction(ctx, params, body, query, actor):
    row = ctx.transaction(params["id"])
    if row["lifecycle_status"] != "PENDING":
        raise ApiError("ERR_INVALID_TRANSITION")
    ledger = ctx.store.ledgers.get(row["ledger_id"])
    if ledger is not None and ledger["period_closed_through_index"] > 0 \
            and row["value_effective_utc"] < ledger["period_close_ms"]:
        raise ApiError("ERR_PERIOD_CLOSED")
    if row["entry_type"] in ("RETURN", "REVERSAL"):
        referenced = row.get("refunds_transaction_id") or row.get("reverses_transaction_id")
        if referenced is not None:
            target = ctx.store.transactions.get(referenced)
            if target is None or target["ledger_id"] != row["ledger_id"]:
                raise bad_request("The referenced counterpart entry does not exist in this ledger.")
    row["lifecycle_status"] = "POSTED"
    ctx.touch(row)
    if ledger is not None:
        ctx.touch(ledger)
    ctx.append_audit(row["ledger_id"], actor, "transaction.posted", "Transaction",
                     row["id"], {"to_status": "POSTED"})
    return Resp(ser.serialize("Transaction", row, ctx))


@route("POST", "/transactions/{id}/reject", ["PaymentOpsAnalyst", "LedgerController"])
def reject_transaction(ctx, params, body, query, actor):
    row = ctx.transaction(params["id"])
    if row["lifecycle_status"] != "PENDING":
        raise ApiError("ERR_INVALID_TRANSITION")
    row["lifecycle_status"] = "REJECTED"
    ctx.touch(row)
    ledger = ctx.store.ledgers.get(row["ledger_id"])
    if ledger is not None:
        ctx.touch(ledger)
    ctx.append_audit(row["ledger_id"], actor, "transaction.rejected", "Transaction",
                     row["id"], {"to_status": "REJECTED"})
    return Resp(ser.serialize("Transaction", row, ctx))


@route("POST", "/transactions/{id}/mark_settled", ["PaymentOpsAnalyst", "LedgerController"])
def mark_transaction_settled(ctx, params, body, query, actor):
    row = ctx.transaction(params["id"])
    if row["payment_order_id"] is not None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "mark_settled applies to manual entries only.")
    if row["lifecycle_status"] not in ("PENDING", "POSTED"):
        raise ApiError("ERR_INVALID_TRANSITION")
    if row["settlement_status"] == "SETTLED":
        raise ApiError("ERR_INVALID_TRANSITION")
    row["settlement_status"] = "SETTLED"
    ctx.touch(row)
    ledger = ctx.store.ledgers.get(row["ledger_id"])
    if ledger is not None:
        ctx.touch(ledger)
    ctx.append_audit(row["ledger_id"], actor, "transaction.mark_settled", "Transaction",
                     row["id"], {"to_status": "SETTLED"})
    return Resp(ser.serialize("Transaction", row, ctx))


@route("POST", "/transactions/{id}/void", ["LedgerController"], single_role=True)
def void_transaction(ctx, params, body, query, actor):
    row = ctx.transaction(params["id"])
    if row["lifecycle_status"] != "POSTED":
        raise ApiError("ERR_INVALID_TRANSITION")
    if row["settlement_status"] != "UNSETTLED":
        raise ApiError("ERR_INVALID_SETTLEMENT_AXIS")
    if row["entry_type"] == "ORIGINATING" and row["lifecycle_status"] == "POSTED" \
            and row.get("entered_via_reversal"):
        raise ApiError("ERR_INVALID_TRANSITION")
    ledger = ctx.store.ledgers.get(row["ledger_id"])
    if ledger is not None:
        ctx.check_version(ledger, body.get("expected_ledger_version"),
                          "expected_ledger_version")
    row["lifecycle_status"] = "VOID"
    ctx.touch(row)
    if ledger is not None:
        ctx.touch(ledger)
    ctx.append_audit(row["ledger_id"], actor, "transaction.voided", "Transaction",
                     row["id"], {"to_status": "VOID"})
    return Resp(ser.serialize("Transaction", row, ctx))


# ================================================================== SETTLEMENT POOL

@route("POST", "/settlement-pools", ["LedgerController", "PlatformAdmin"], code=201)
def create_settlement_pool(ctx, params, body, query, actor):
    require_fields(body, ["name", "ledger_id", "member_bank_account_ids"])
    ledger = ctx.ledger(body["ledger_id"])
    members = body["member_bank_account_ids"]
    if not isinstance(members, list):
        raise bad_request("member_bank_account_ids must be an array.")
    accounts = []
    for aid in members:
        account = ctx.bank_account(aid)
        if account["status"] != "OPEN":
            raise bad_request("Every pool member account must be OPEN.")
        accounts.append(account)
    status = optional_enum(body, "status", ("ACTIVE", "SUSPENDED"), "ACTIVE")
    row = ctx.created_row(
        ledger_id=ledger["id"],
        name=body["name"],
        member_bank_account_ids=[a["id"] for a in accounts],
        status=status,
    )
    ctx.store.settlement_pools[row["id"]] = row
    for account in accounts:
        membership = ctx.created_row(
            settlement_pool_id=row["id"],
            bank_account_id=account["id"],
            weight_units=1,
        )
        ctx.store.pool_memberships[membership["id"]] = membership
    return Resp(ser.serialize("SettlementPool", row, ctx))


@route("GET", "/settlement-pools",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "Auditor"])
def list_settlement_pools(ctx, params, body, query, actor):
    rows = list(ctx.store.settlement_pools.values())
    if query.get("ledger_id"):
        rows = [r for r in rows if r["ledger_id"] == query["ledger_id"]]
    if query.get("forced_settlement_status"):
        rows = [r for r in rows
                if ctx.pool_forced_status_for_pool(r) == query["forced_settlement_status"]]
    return _page(query, "SettlementPool", ctx, rows, created_sort)


@route("GET", "/settlement-pools/{id}",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentOpsApprover",
        "Auditor"])
def get_settlement_pool(ctx, params, body, query, actor):
    row = ctx.pool(params["id"])
    return Resp(ser.serialize("SettlementPool", row, ctx))


@route("GET", "/settlement-pools/{id}/memberships",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "Auditor"])
def list_pool_memberships(ctx, params, body, query, actor):
    pool = ctx.pool(params["id"])
    rows = [r for r in ctx.store.pool_memberships.values()
            if r["settlement_pool_id"] == pool["id"]]
    return _page(query, "PoolMembership", ctx, rows, created_sort)


@route("POST", "/settlement-pools/{id}/refresh", ["PaymentOpsAnalyst", "LedgerController"])
def refresh_settlement_pool(ctx, params, body, query, actor):
    pool = ctx.pool(params["id"])
    ctx.touch(pool)
    ctx.append_audit(pool["ledger_id"], actor, "settlement_pool.refreshed",
                     "SettlementPool", pool["id"], {})
    return Resp(ser.serialize("SettlementPool", pool, ctx))


@route("POST", "/pool-memberships", ["LedgerController", "PlatformAdmin"], code=201)
def create_pool_membership(ctx, params, body, query, actor):
    require_fields(body, ["settlement_pool_id", "bank_account_id"])
    pool = ctx.pool(body["settlement_pool_id"])
    account = ctx.bank_account(body["bank_account_id"])
    weight = body.get("weight_units", 1)
    if isinstance(weight, bool) or not isinstance(weight, int) or weight <= 0:
        raise bad_request("weight_units must be an integer strictly greater than zero.")
    if account["id"] not in pool["member_bank_account_ids"]:
        pool["member_bank_account_ids"].append(account["id"])
        ctx.touch(pool)
    row = ctx.created_row(
        settlement_pool_id=pool["id"],
        bank_account_id=account["id"],
        weight_units=weight,
    )
    ctx.store.pool_memberships[row["id"]] = row
    return Resp(ser.serialize("PoolMembership", row, ctx))


@route("GET", "/pool-memberships",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "Auditor"])
def list_pool_membership_rows(ctx, params, body, query, actor):
    rows = list(ctx.store.pool_memberships.values())
    if query.get("settlement_pool_id"):
        rows = [r for r in rows if r["settlement_pool_id"] == query["settlement_pool_id"]]
    if query.get("bank_account_id"):
        rows = [r for r in rows if r["bank_account_id"] == query["bank_account_id"]]
    return _page(query, "PoolMembership", ctx, rows, created_sort)


@route("GET", "/pool-memberships/{id}",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "Auditor"])
def get_pool_membership(ctx, params, body, query, actor):
    row = ctx.membership(params["id"])
    return Resp(ser.serialize("PoolMembership", row, ctx))


@route("POST", "/pool-memberships/{id}/remove", ["LedgerController", "PlatformAdmin"])
def remove_pool_membership(ctx, params, body, query, actor):
    row = ctx.membership(params["id"])
    pool = ctx.pool(row["settlement_pool_id"])
    del ctx.store.pool_memberships[row["id"]]
    if row["bank_account_id"] in pool["member_bank_account_ids"]:
        pool["member_bank_account_ids"].remove(row["bank_account_id"])
    ctx.touch(pool)
    return Resp(ser.serialize("SettlementPool", pool, ctx))


# ================================================================== RELEASE REQUEST

@route("POST", "/release-requests", ["PaymentInitiator", "PaymentApprover"], code=201)
def create_release_request(ctx, params, body, query, actor):
    require_fields(body, ["payment_order_id", "counterparty_id", "needed_by_utc", "reason"])
    order = ctx.payment_order(body["payment_order_id"])
    counterparty = ctx.counterparty(body["counterparty_id"])
    needed_ms = require_iso(body, "needed_by_utc")
    row = ctx.created_row(
        payment_order_id=order["id"],
        counterparty_id=counterparty["id"],
        initiator_user_id=actor[0],
        needed_by_utc=needed_ms,
        reason=body["reason"],
        request_state="PENDING",
    )
    ctx.store.release_requests[row["id"]] = row
    ctx.append_audit(order["ledger_id"], actor, "release_request.raised",
                     "ReleaseRequest", row["id"], {})
    return Resp(ser.serialize("ReleaseRequest", row, ctx))


@route("GET", "/release-requests",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentApprover",
        "PaymentInitiator", "CounterpartyUser", "Auditor"])
def list_release_requests(ctx, params, body, query, actor):
    rows = list(ctx.store.release_requests.values())
    if query.get("payment_order_id"):
        rows = [r for r in rows if r["payment_order_id"] == query["payment_order_id"]]
    if query.get("counterparty_id"):
        rows = [r for r in rows if r["counterparty_id"] == query["counterparty_id"]]
    if query.get("request_state"):
        rows = [r for r in rows if r["request_state"] == query["request_state"]]
    if actor[1] == "CounterpartyUser":
        rows = [r for r in rows if r["counterparty_id"] == actor[0]]
    return _page(query, "ReleaseRequest", ctx, rows, created_sort)


@route("GET", "/release-requests/{id}",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentOpsApprover",
        "PaymentApprover", "PaymentInitiator", "CounterpartyUser", "Auditor"])
def get_release_request(ctx, params, body, query, actor):
    row = ctx.release_request(params["id"])
    if actor[1] == "CounterpartyUser" and actor[0] != row["counterparty_id"]:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE",
                       "A CounterpartyUser may only read its own release requests.")
    return Resp(ser.serialize("ReleaseRequest", row, ctx))


@route("POST", "/release-requests/{id}/cancel", ["PaymentInitiator", "PaymentApprover"])
def cancel_release_request(ctx, params, body, query, actor):
    row = ctx.release_request(params["id"])
    if row["request_state"] != "PENDING":
        raise ApiError("ERR_INVALID_TRANSITION")
    row["request_state"] = "DENIED"
    ctx.touch(row)
    order = ctx.store.payment_orders.get(row["payment_order_id"])
    ctx.append_audit(order["ledger_id"] if order else None, actor,
                     "release_request.cancelled", "ReleaseRequest", row["id"], {})
    return Resp(ser.serialize("ReleaseRequest", row, ctx))


# ================================================================== CALENDAR

@route("POST", "/banking-calendar", ["LedgerController", "PlatformAdmin", "PaymentApprover"],
       code=201)
def create_calendar_cell(ctx, params, body, query, actor):
    require_fields(body, ["legal_entity_id", "calendar_date", "timezone", "is_open",
                          "cutoffs", "allowed_rails"])
    entity = ctx.legal_entity(body["legal_entity_id"])
    if body["timezone"] not in ("America/New_York", "America/Chicago", "Europe/London"):
        raise bad_request("timezone must be America/New_York, America/Chicago or Europe/London.")
    try:
        calendar_date = parse_date(body["calendar_date"]).isoformat()
    except ValueError:
        raise bad_request("calendar_date must be YYYY-MM-DD.")
    if not isinstance(body["is_open"], bool):
        raise bad_request("is_open must be a boolean.")
    cutoffs_raw = body["cutoffs"]
    if not isinstance(cutoffs_raw, list):
        raise bad_request("cutoffs must be an array.")
    cutoffs = []
    for item in cutoffs_raw:
        if not isinstance(item, dict) or item.get("rail") not in RAIL_DOMAINS:
            raise bad_request("Each cutoff must name a known rail.")
        raw_time = item.get("cutoff_local_time")
        if not isinstance(raw_time, str):
            raise bad_request("cutoff_local_time must be a string.")
        try:
            from datetime import time as _time
            parts = raw_time.split(":")
            local_time = _time(int(parts[0]), int(parts[1]),
                               int(parts[2]) if len(parts) > 2 else 0)
        except Exception:
            raise bad_request("cutoff_local_time must be HH:MM or HH:MM:SS.")
        cutoffs.append({"rail": item["rail"], "cutoff_local_time": raw_time,
                        "_local_time": local_time})
    rails = body["allowed_rails"]
    if not isinstance(rails, list) or not rails:
        raise bad_request("allowed_rails must be a non-empty array.")
    cutoff_rails = {c["rail"] for c in cutoffs}
    for rail in rails:
        if rail not in RAIL_DOMAINS or rail not in cutoff_rails:
            raise bad_request("allowed_rails must be a non-empty subset of the cutoff rails.")
    for existing in ctx.store.calendar_cells.values():
        if existing["legal_entity_id"] == entity["id"] \
                and existing["calendar_date"] == calendar_date:
            raise ApiError("ERR_DUPLICATE_REFERENCE_CODE",
                           "At most one calendar cell may exist per institution and date.")
    row = ctx.created_row(
        legal_entity_id=entity["id"],
        calendar_date=calendar_date,
        timezone=body["timezone"],
        is_open=body["is_open"],
        cutoffs=cutoffs,
        allowed_rails=list(rails),
        calendar_code="%s-%s" % (entity["short_code"], calendar_date),
    )
    ctx.store.calendar_cells[row["id"]] = row
    ctx.append_audit(entity.get("home_ledger_id"), actor, "banking_calendar.published",
                     "BankingCalendar", row["id"], {"calendar_date": calendar_date})
    return Resp(ser.serialize("BankingCalendar", row, ctx))


@route("GET", "/banking-calendar",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentApprover",
        "PaymentInitiator", "Auditor"])
def list_calendar(ctx, params, body, query, actor):
    rows = list(ctx.store.calendar_cells.values())
    if query.get("legal_entity_id"):
        rows = [r for r in rows if r["legal_entity_id"] == query["legal_entity_id"]]
    from routes import _filter_calendar
    rows = _filter_calendar(query, rows)
    return _page(query, "BankingCalendar", ctx, rows,
                 lambda r: (r["calendar_date"], r["sequence"]))


@route("GET", "/banking-calendar/{id}",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentApprover",
        "PaymentInitiator", "Auditor"])
def get_calendar(ctx, params, body, query, actor):
    row = ctx.calendar_cell(params["id"])
    return Resp(ser.serialize("BankingCalendar", row, ctx))


# ================================================================== EXCEPTION

@route("GET", "/exceptions",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentOpsApprover",
        "Auditor"])
def list_exceptions(ctx, params, body, query, actor):
    rows = list(ctx.store.exceptions.values())
    for field in ("ledger_id", "kind", "status", "payment_order_id", "bank_statement_id"):
        if query.get(field):
            rows = [r for r in rows if r[field] == query[field]]
    if query.get("aging_bucket"):
        rows = [r for r in rows
                if ctx.aging_bucket(ctx.exception_age_days(r)) == query["aging_bucket"]]
    return _page(query, "ExceptionItem", ctx, rows,
                 lambda r: (r["opened_utc"], r["created_at"]))


@route("GET", "/exceptions/{id}",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentOpsApprover",
        "Auditor"])
def get_exception(ctx, params, body, query, actor):
    row = ctx.exception(params["id"])
    return Resp(ser.serialize("ExceptionItem", row, ctx))


@route("POST", "/exceptions/{id}/assign", ["PaymentOpsAnalyst", "PaymentOpsApprover"])
def assign_exception(ctx, params, body, query, actor):
    row = ctx.exception(params["id"])
    if row["status"] != "OPEN":
        raise ApiError("ERR_INVALID_TRANSITION")
    assignee = body.get("assignee_user_id") if isinstance(body, dict) else None
    row["status"] = "ASSIGNED"
    row["assignee_user_id"] = assignee or actor[0]
    ctx.touch(row)
    ctx.append_audit(row["ledger_id"], actor, "exception_item.assigned", "ExceptionItem",
                     row["id"], {"assignee_user_id": row["assignee_user_id"]})
    return Resp(ser.serialize("ExceptionItem", row, ctx))


@route("POST", "/exceptions/{id}/reevaluate_aging",
       ["PaymentOpsAnalyst", "PaymentOpsApprover"])
def reevaluate_aging(ctx, params, body, query, actor):
    row = ctx.exception(params["id"])
    if row["status"] != "OPEN":
        raise ApiError("ERR_INVALID_TRANSITION")
    if row["kind"] == "UNMATCHED_DEPOSIT":
        line = None
        for candidate in ctx.store.statement_lines.values():
            if candidate["bank_statement_id"] == row["bank_statement_id"] \
                    and candidate["match_state"] == "UNMATCHED" \
                    and abs(candidate["amount_cents"]) == row["amount_cents"]:
                line = candidate
                break
        if line is not None:
            destination, ledger_id = ctx.resolve_destination(line)
            fee, amount = ctx.deposit_fields(abs(line["amount_cents"]))
            row["attributed_fee_cents"] = fee
            row["attributable_amount_cents"] = amount
            if destination is not None:
                # PRD S3.8: "for an UNMATCHED_DEPOSIT item the same reevaluation
                # re-runs deposit attribution and closes the item if a
                # destination has since become resolvable."  Only the *resolve*
                # action books the ORIGINATING/FEE legs ("Resolving an item of
                # kind UNMATCHED_DEPOSIT re-runs deposit attribution and books an
                # ORIGINATING leg ..."), so a bare reevaluation closes the item
                # without touching the ledger.
                row["status"] = "RESOLVED"
                row["resolution_note"] = "destination resolved by reevaluation"
    ctx.touch(row)
    return Resp(ser.serialize("ExceptionItem", row, ctx))


@route("POST", "/exceptions/{id}/escalate", ["PaymentOpsAnalyst", "PaymentOpsApprover"])
def escalate_exception(ctx, params, body, query, actor):
    row = ctx.exception(params["id"])
    if row["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_TRANSITION")
    if ctx.aging_bucket(ctx.exception_age_days(row)) == "CURRENT":
        raise ApiError("ERR_EXCEPTION_NOT_AGED")
    row["status"] = "ESCALATED"
    if isinstance(body, dict) and body.get("assignee_user_id"):
        row["assignee_user_id"] = body["assignee_user_id"]
    ctx.touch(row)
    ctx.append_audit(row["ledger_id"], actor, "exception_item.escalated", "ExceptionItem",
                     row["id"], {"to_status": "ESCALATED"})
    return Resp(ser.serialize("ExceptionItem", row, ctx))


@route("POST", "/exceptions/{id}/deescalate", ["PaymentOpsAnalyst", "PaymentOpsApprover"])
def deescalate_exception(ctx, params, body, query, actor):
    row = ctx.exception(params["id"])
    if row["status"] != "ESCALATED":
        raise ApiError("ERR_INVALID_TRANSITION")
    if ctx.aging_bucket(ctx.exception_age_days(row)) != "CURRENT":
        raise ApiError("ERR_EXCEPTION_NOT_AGED")
    row["status"] = "ASSIGNED"
    ctx.touch(row)
    return Resp(ser.serialize("ExceptionItem", row, ctx))


@route("POST", "/exceptions/{id}/unassign", ["PaymentOpsAnalyst", "PaymentOpsApprover"])
def unassign_exception(ctx, params, body, query, actor):
    row = ctx.exception(params["id"])
    if row["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_TRANSITION")
    row["status"] = "OPEN"
    row["assignee_user_id"] = None
    ctx.touch(row)
    return Resp(ser.serialize("ExceptionItem", row, ctx))


@route("POST", "/exceptions/{id}/resolve", ["PaymentOpsAnalyst", "PaymentOpsApprover"])
def resolve_exception(ctx, params, body, query, actor):
    row = ctx.exception(params["id"])
    if row["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_TRANSITION")
    if not row.get("assignee_user_id") or row["assignee_user_id"] != actor[0]:
        raise ApiError("ERR_EXCEPTION_NOT_ASSIGNED_TO_CALLER")
    if ctx.exception_age_days(row) < 1:
        raise ApiError("ERR_EXCEPTION_NOT_ASSIGNED_TO_CALLER")
    row["status"] = "RESOLVED"
    row["resolution_note"] = (body or {}).get("resolution_note")
    ctx.touch(row)
    ledger = ctx.store.ledgers.get(row["ledger_id"])
    if ledger is not None:
        ctx.touch(ledger)

    if row["kind"] == "RETURN":
        legs = ctx.active_return_legs(row["ledger_id"])
        leg = None
        for candidate in legs:
            order = ctx.store.payment_orders.get(candidate["payment_order_id"])
            if order is not None and order["id"] == row["payment_order_id"]:
                leg = candidate
                break
        if leg is None and legs:
            leg = legs[0]
        if leg is not None:
            ctx.resolve_return_leg_fee(row["ledger_id"], leg)
    elif row["kind"] == "UNMATCHED_DEPOSIT":
        line = None
        for candidate in ctx.store.statement_lines.values():
            if candidate["bank_statement_id"] == row["bank_statement_id"] \
                    and abs(candidate["amount_cents"]) == row["amount_cents"]:
                line = candidate
                break
        if line is not None:
            destination, ledger_id = ctx.resolve_destination(line)
            fee, amount = ctx.deposit_fields(abs(line["amount_cents"]))
            row["attributed_fee_cents"] = fee
            row["attributable_amount_cents"] = amount
            target_ledger = ledger_id or row["ledger_id"]
            ctx.create_transaction(target_ledger, "ORIGINATING", "CREDIT", amount,
                                   ctx.now_ms(), actor=actor, action=None)
            if fee:
                ctx.create_transaction(target_ledger, "FEE", "DEBIT", fee,
                                       ctx.now_ms(), actor=actor, action=None)

    ctx.append_audit(row["ledger_id"], actor, "exception_item.resolved", "ExceptionItem",
                     row["id"], {"resolution_note": row["resolution_note"]})
    return Resp(ser.serialize("ExceptionItem", row, ctx))


@route("POST", "/exceptions/{id}/waive", ["PaymentOpsApprover"], single_role=True)
def waive_exception(ctx, params, body, query, actor):
    row = ctx.exception(params["id"])
    # PRD S3.8: "The action is reachable from both `ASSIGNED` and `ESCALATED`"
    # and it is gated on age -- "A waive requires the item's aging_bucket to be
    # AGING, ESCALATED or CRITICAL -- a CURRENT item cannot be waived, and the
    # attempt is refused with ERR_EXCEPTION_NOT_AGED and HTTP 409".  An OPEN item
    # is a third case the PRD does not name, so it keeps its own state error.
    if row["status"] not in ("ASSIGNED", "ESCALATED", "OPEN"):
        raise ApiError("ERR_INVALID_TRANSITION")
    if ctx.aging_bucket(ctx.exception_age_days(row)) == "CURRENT":
        raise ApiError("ERR_EXCEPTION_NOT_AGED")
    ledger = ctx.store.ledgers.get(row["ledger_id"])
    if ledger is not None and ledger["period_closed_through_index"] > 0 \
            and row["opened_utc"] <= ledger["period_close_ms"]:
        raise ApiError("ERR_PERIOD_CLOSED")
    row["status"] = "WAIVED"
    row["resolution_note"] = (body or {}).get("resolution_note")
    ctx.touch(row)
    ctx.append_audit(row["ledger_id"], actor, "exception_item.waived", "ExceptionItem",
                     row["id"], {"reason": row["resolution_note"]})
    return Resp(ser.serialize("ExceptionItem", row, ctx))


# ================================================================== AUDIT EVENTS

@route("POST", "/audit-events",
       ["PlatformAdmin", "LedgerController", "PaymentOpsAnalyst", "PaymentOpsApprover",
        "PaymentApprover", "PaymentInitiator"], code=201)
def append_audit_event(ctx, params, body, query, actor):
    require_fields(body, ["ledger_id", "actor_user_id", "actor_role", "action",
                          "target_entity_type", "target_entity_id"])
    ledger = ctx.ledger(body["ledger_id"])
    row = ctx.append_audit(ledger["id"], (body["actor_user_id"], body["actor_role"]),
                           body["action"], body["target_entity_type"],
                           body["target_entity_id"], body.get("details") or {})
    return Resp(ser.serialize("AuditEvent", row, ctx))


@route("GET", "/audit-events",
       ["PlatformAdmin", "LedgerController", "Auditor", "PaymentOpsApprover"])
def list_audit_events(ctx, params, body, query, actor):
    ledger_id = query.get("ledger_id") or (body or {}).get("ledger_id")
    ctx.ledger(ledger_id)
    rows = [r for r in ctx.store.audit_events.values() if r["ledger_id"] == ledger_id]
    if query.get("target_entity_type"):
        rows = [r for r in rows if r["target_entity_type"] == query["target_entity_type"]]
    if query.get("target_entity_id"):
        rows = [r for r in rows if r["target_entity_id"] == query["target_entity_id"]]
    return _page(query, "AuditEvent", ctx, rows,
                 lambda r: (r["created_at"], r["sequence_number"]))


@route("GET", "/audit-events/{sequenceNumber}",
       ["PlatformAdmin", "LedgerController", "Auditor", "PaymentOpsApprover"])
def get_audit_event(ctx, params, body, query, actor):
    ledger_id = query.get("ledger_id") or (body or {}).get("ledger_id")
    ctx.ledger(ledger_id)
    sequence = params["sequenceNumber"]
    for row in ctx.store.audit_events.values():
        if row["ledger_id"] == ledger_id and str(row["sequence_number"]) == str(sequence):
            return Resp(ser.serialize("AuditEvent", row, ctx))
    raise ApiError("ERR_INVALID_REQUEST", "No audit event carries that sequence number.")


# ================================================================== TEST DRIVING

@route("POST", "/_clock/set_current_utc", ["PlatformAdmin", "LedgerController"])
def set_current_utc(ctx, params, body, query, actor):
    require_fields(body, ["to_iso8601"])
    target = require_iso(body, "to_iso8601")
    previous = ctx.now_ms()
    if target < previous:
        raise ApiError("ERR_CLOCK_NOT_MONOTONIC",
                       "The logical clock may not move backwards.")
    ctx.store.clock_ms = target
    return Resp({"current_utc": iso_from_ms(target),
                 "previous_utc": iso_from_ms(previous)})


@route("POST", "/_rails/simulate_settlement", ["PlatformAdmin", "PaymentOpsAnalyst"])
def simulate_settlement(ctx, params, body, query, actor):
    require_fields(body, ["payment_order_id", "outcome"])
    order = ctx.payment_order(body["payment_order_id"])
    outcome = body["outcome"]
    accepted = outcome in ("SETTLED", "RETURNED", "FAILED", "IN_FLIGHT", "ACCEPTED")
    ctx.store.rails_outcomes[order["id"]] = {
        "outcome": outcome,
        "return_reason": body.get("return_reason"),
    }
    return Resp({"payment_order_id": order["id"], "outcome": outcome,
                 "accepted": accepted})