"""Business logic: lookups, validation cascade, state machines, calculations.

The store is in-memory and shared by every request in a process; it is created
empty at boot and never seeded.
"""

import calculations as calc
import errors
from errors import ApiError
from utils import (
    VALID_TZ,
    iso_from_ms,
    local_date_from_ms,
    local_time_from_ms,
    parse_date,
    parse_iso,
    utc_ms_from_local,
)

# ------------------------------------------------------------------ constants

RAILS = ("ACH", "WIRE", "RTP", "CHECK")
DIRECTIONS = ("CREDIT", "DEBIT")
ENTRY_TYPES = ("ORIGINATING", "RETURN", "REVERSAL", "FEE", "ADJUSTMENT", "DEPOSIT")
SETTLEMENT_SPEEDS = ("STANDARD", "SAME_DAY")
CURRENCIES = ("USD", "EUR", "GBP")
ENTITY_TYPES = ("PLATFORM", "ORGANISATION")
COUNTERPARTY_STATUSES = ("ACTIVE", "RESTRICTED", "BLOCKED", "CLOSED")
RELATIONSHIP_PURPOSES = ("ACCOUNT_SHARING", "PAYMENT_RAIL_AGREEMENT", "DISPUTE_CHANNEL")
RELATIONSHIP_STATUSES = ("PENDING", "ACTIVE", "SUSPENDED", "TERMINATED")
RAIL_DOMAINS = ("ACH", "WIRE", "RTP", "CHECK", "INTERNAL")
RETURN_REASONS = ("R01", "R02", "R03", "R04", "R05", "R06", "R07", "R08", "R09", "R10",
                  "CHK_RETURNED")
EXCEPTION_KINDS = ("UNMATCHED_DEPOSIT", "RETURN", "REVERSAL", "FAILED_PAYMENT",
                   "STATEMENT_VARIANCE")
EXCEPTION_STATUSES = ("OPEN", "ASSIGNED", "ESCALATED", "RESOLVED", "WAIVED")
AGING_BUCKETS = ("CURRENT", "AGING", "ESCALATED", "CRITICAL")
LINE_MATCH_STATES = ("UNMATCHED", "MATCHED", "IGNORED")

ROLES = (
    "PlatformAdmin", "LedgerController", "PaymentInitiator", "PaymentApprover",
    "PaymentOpsAnalyst", "PaymentOpsApprover", "CounterpartyUser", "Auditor",
)

TERMINAL_ORDER_STATUSES = ("SETTLED", "RETURNED", "REVERSED", "CANCELLED")
DEAD_ORDER_STATUSES = ("SETTLED", "RETURNED", "REVERSED", "CANCELLED")

STATEMENT_STATUSES = ("IMPORTED", "RECONCILING", "RECONCILED", "DISCREPANCY", "REVISED",
                      "SUPERSEDED")


def bad_request(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def require(condition, error_id, message=""):
    if not condition:
        raise ApiError(error_id, message)


def require_fields(body, names, types=None):
    """ERR_INVALID_REQUEST for a missing required field or a wrong-typed field."""
    if not isinstance(body, dict):
        raise bad_request("Request body must be a JSON object.")
    types = types or {}
    for name in names:
        if name not in body or body[name] is None:
            raise bad_request("Field %r is required." % name)
        expected = types.get(name)
        if expected is not None and not isinstance(body[name], expected):
            raise bad_request("Field %r has the wrong type." % name)


def require_int(body, name, minimum=None):
    value = body.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("Field %r must be an integer." % name)
    if minimum is not None and value < minimum:
        raise bad_request("Field %r must be >= %d." % (name, minimum))
    return value


def require_enum(body, name, allowed):
    value = body.get(name)
    if value not in allowed:
        raise bad_request("Field %r must be one of %s." % (name, ", ".join(allowed)))
    return value


def optional_enum(body, name, allowed, default):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if value not in allowed:
        raise bad_request("Field %r must be one of %s." % (name, ", ".join(allowed)))
    return value


def require_iso(body, name):
    try:
        return parse_iso(body.get(name))
    except (ValueError, TypeError):
        raise bad_request("Field %r must be an ISO 8601 instant." % name)


def optional_iso(body, name):
    if name not in body or body[name] is None:
        return None
    return require_iso(body, name)


def _parse_limit_offset(query):
    def one(name, default):
        raw = query.get(name)
        if raw is None or raw == "":
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise bad_request("Query parameter %r must be an integer." % name)

    limit = one("limit", 10)
    offset = one("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


class Ctx(object):
    """Request-scoped view over the process-wide store."""

    def __init__(self, store):
        self.store = store

    # ---------------------------------------------------------------- clock

    def now_ms(self):
        return self.store.clock_ms

    def next_seq(self):
        return self.store.next_seq()

    def touch(self, row, at_ms=None):
        row["updated_at"] = at_ms if at_ms is not None else self.store.clock_ms
        row["version"] = int(row.get("version", 1)) + 1

    def created_row(self, **fields):
        now = self.store.clock_ms
        row = {
            "id": self.store.new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "sequence": self.next_seq(),
        }
        row.update(fields)
        return row

    # ---------------------------------------------------------------- audit

    def append_audit(self, ledger_id, actor, action, target_entity_type, target_entity_id,
                     details=None, at_ms=None):
        if ledger_id is None:
            return None
        seq = 1 + sum(1 for e in self.store.audit_events.values()
                      if e["ledger_id"] == ledger_id)
        row = {
            "id": self.store.new_id(),
            "created_at": at_ms if at_ms is not None else self.store.clock_ms,
            "ledger_id": ledger_id,
            "actor_user_id": actor[0] if actor else None,
            "actor_role": actor[1] if actor else None,
            "action": action,
            "target_entity_type": target_entity_type,
            "target_entity_id": target_entity_id,
            "sequence_number": seq,
            "details": details if details is not None else {},
        }
        self.store.audit_events[row["id"]] = row
        return row

    # ---------------------------------------------------------------- lookups

    def ledger(self, ledger_id, error_id="ERR_LEDGER_NOT_FOUND"):
        row = self.store.ledgers.get(ledger_id)
        if row is None:
            raise ApiError(error_id)
        return row

    def legal_entity(self, entity_id, error_id="ERR_LEGAL_ENTITY_NOT_FOUND"):
        row = self.store.legal_entities.get(entity_id)
        if row is None:
            raise ApiError(error_id)
        return row

    def counterparty(self, cid, error_id="ERR_COUNTERPARTY_NOT_FOUND"):
        row = self.store.counterparties.get(cid)
        if row is None:
            raise ApiError(error_id)
        return row

    def bank_account(self, aid, error_id="ERR_BANK_ACCOUNT_NOT_FOUND"):
        row = self.store.bank_accounts.get(aid)
        if row is None:
            raise ApiError(error_id)
        return row

    def virtual_account(self, vid, error_id="ERR_VIRTUAL_ACCOUNT_NOT_FOUND"):
        row = self.store.virtual_accounts.get(vid)
        if row is None:
            raise ApiError(error_id)
        return row

    def statement(self, sid, error_id="ERR_BANK_STATEMENT_NOT_FOUND"):
        row = self.store.statements.get(sid)
        if row is None:
            raise ApiError(error_id)
        return row

    def payment_order(self, oid, error_id="ERR_PAYMENT_ORDER_NOT_FOUND"):
        row = self.store.payment_orders.get(oid)
        if row is None:
            raise ApiError(error_id)
        return row

    def transaction(self, tid, error_id="ERR_TRANSACTION_NOT_FOUND"):
        row = self.store.transactions.get(tid)
        if row is None:
            raise ApiError(error_id)
        return row

    def exception(self, eid, error_id="ERR_EXCEPTION_NOT_FOUND"):
        row = self.store.exceptions.get(eid)
        if row is None:
            raise ApiError(error_id)
        return row

    def release_request(self, rid, error_id="ERR_RELEASE_REQUEST_NOT_FOUND"):
        row = self.store.release_requests.get(rid)
        if row is None:
            raise ApiError(error_id)
        return row

    def relationship(self, rid, error_id="ERR_INVALID_REQUEST"):
        row = self.store.relationships.get(rid)
        if row is None:
            raise ApiError(error_id)
        return row

    def pool(self, pid, error_id="ERR_INVALID_REQUEST"):
        row = self.store.settlement_pools.get(pid)
        if row is None:
            raise ApiError(error_id)
        return row

    def membership(self, mid, error_id="ERR_INVALID_REQUEST"):
        row = self.store.pool_memberships.get(mid)
        if row is None:
            raise ApiError(error_id)
        return row

    def calendar_cell(self, cid, error_id="ERR_INVALID_REQUEST"):
        row = self.store.calendar_cells.get(cid)
        if row is None:
            raise ApiError(error_id)
        return row

    # ---------------------------------------------------------------- OCC

    def check_version(self, row, expected, field_name):
        if expected is None:
            return
        if not isinstance(expected, int) or isinstance(expected, bool):
            raise bad_request("Field %r must be an integer." % field_name)
        if int(expected) != int(row["version"]):
            raise ApiError("ERR_STALE_VERSION",
                           "Expected %s %s but the persisted version is %s."
                           % (field_name, expected, row["version"]))

    # ---------------------------------------------------------------- ledger maths

    def ledger_debits_cents(self, ledger_id):
        return sum(r["amount_cents"] for r in self.store.transactions.values()
                   if r["ledger_id"] == ledger_id and r["direction"] == "DEBIT"
                   and r["lifecycle_status"] in ("PENDING", "POSTED"))

    def ledger_credits_cents(self, ledger_id):
        return sum(r["amount_cents"] for r in self.store.transactions.values()
                   if r["ledger_id"] == ledger_id and r["direction"] == "CREDIT"
                   and r["lifecycle_status"] in ("PENDING", "POSTED"))

    def ledger_pending_cents(self, ledger_id):
        return sum(r["net_effect_cents"] for r in self.store.transactions.values()
                   if r["ledger_id"] == ledger_id
                   and r["lifecycle_status"] not in ("VOID", "REJECTED")
                   and r["settlement_status"] in ("UNSETTLED", "IN_SETTLEMENT"))

    def ledger_posted_cents(self, ledger_id):
        return sum(r["net_effect_cents"] for r in self.store.transactions.values()
                   if r["ledger_id"] == ledger_id
                   and r["lifecycle_status"] not in ("VOID", "REJECTED")
                   and r["settlement_status"] == "SETTLED")

    def identity_holds(self, ledger_id):
        return calc.double_entry_identity(
            self.ledger_debits_cents(ledger_id),
            self.ledger_credits_cents(ledger_id),
            self.ledger_posted_cents(ledger_id),
            self.ledger_pending_cents(ledger_id),
        )

    # ---------------------------------------------------------------- aging

    def ledger_timezone(self, ledger_id):
        ledger = self.store.ledgers.get(ledger_id)
        if ledger is None:
            return "America/New_York"
        entity = self.store.legal_entities.get(ledger.get("legal_entity_id"))
        if entity is not None and entity.get("timezone"):
            return entity["timezone"]
        # fall back to the timezone of the calendar of the entity that owns the ledger
        for cell in self.store.calendar_cells.values():
            if cell["legal_entity_id"] == ledger.get("legal_entity_id"):
                return cell["timezone"]
        # otherwise any institution that owns a bank account booked into the ledger
        for txn in self.store.transactions.values():
            if txn["ledger_id"] == ledger_id:
                order = self.store.payment_orders.get(txn.get("payment_order_id"))
                if order is not None:
                    acct = self.store.bank_accounts.get(order.get("source_account_id"))
                    if acct is not None:
                        return self.calendar_timezone_for(acct["legal_entity_id"])
        for acct in self.store.bank_accounts.values():
            if acct["legal_entity_id"] == ledger.get("legal_entity_id"):
                return self.calendar_timezone_for(acct["legal_entity_id"])
        return "America/New_York"

    def calendar_timezone_for(self, legal_entity_id):
        for cell in self.store.calendar_cells.values():
            if cell["legal_entity_id"] == legal_entity_id:
                return cell["timezone"]
        return "America/New_York"

    def closed_dates(self, legal_entity_id):
        return {parse_date(c["calendar_date"]) for c in self.store.calendar_cells.values()
                if c["legal_entity_id"] == legal_entity_id and not c["is_open"]}

    def exception_age_days(self, exc):
        tz = self.ledger_timezone(exc["ledger_id"])
        open_date = local_date_from_ms(exc["opened_utc"], tz)
        target_date = local_date_from_ms(self.now_ms(), tz)
        if target_date <= open_date:
            return 0
        entity_id = self.store.ledgers.get(exc["ledger_id"], {}).get("legal_entity_id")
        closed = self.closed_dates(entity_id)
        count = 0
        day = open_date
        while day < target_date:
            day = day.fromordinal(day.toordinal() + 1)
            if day.weekday() >= 5:
                continue
            if day in closed:
                continue
            count += 1
        return count

    def aging_bucket(self, age_business_days):
        return calc.aging_bucket(age_business_days)

    # ---------------------------------------------------------------- pools

    def pool_forced_status_for_pool(self, pool):
        total = 0
        for aid in pool["member_bank_account_ids"]:
            acct = self.store.bank_accounts.get(aid)
            if acct is not None and acct["status"] == "OPEN":
                total += acct["available_funds_cents"]
        return calc.settlement_pool_status(total)

    def pool_forced_status(self, bank_account_id):
        best = None
        order = {"READY": 3, "DEGRADED": 2, "FAILED": 1}
        for pool in self.store.settlement_pools.values():
            if bank_account_id in pool["member_bank_account_ids"]:
                status = self.pool_forced_status_for_pool(pool)
                if best is None or order[status] < order[best]:
                    best = status
        return best

    # ---------------------------------------------------------------- statements

    def statement_lines(self, statement_id):
        rows = [r for r in self.store.statement_lines.values()
                if r["bank_statement_id"] == statement_id]
        rows.sort(key=lambda r: (r["effective_at_ms"], r["bank_reference"]))
        return rows

    def recompute_statement(self, statement):
        lines = self.statement_lines(statement["id"])
        txn_source = self._statement_transactions(statement)
        matched_ids = []
        excess_cents = 0
        unattributed_cents = 0
        consumed = set()
        cycle_ms = statement["cycle_date_ms"]
        algorithm = statement["matching_algorithm"]

        for line in lines:
            candidates = [t for t in txn_source
                          if t["settlement_status"] == "SETTLED"
                          and t["value_effective_utc"] <= cycle_ms
                          and t["created_at"] <= line["effective_at_ms"]]
            matched = None
            for t in candidates:
                if t["id"] in consumed:
                    continue
                if t["net_effect_cents"] != line["amount_cents"]:
                    continue
                if algorithm == calc.SETTLED_SINGLE and t["value_effective_utc"] != line["effective_at_ms"]:
                    continue
                matched = t
                break
            if matched is not None:
                consumed.add(matched["id"])
                matched_ids.append(matched["id"])
                line["match_state"] = "MATCHED"
            else:
                line["match_state"] = "UNMATCHED"
                same_amount = [t for t in candidates if t["net_effect_cents"] == line["amount_cents"]]
                if same_amount:
                    excess_cents += line["amount_cents"]
                else:
                    unattributed_cents += line["amount_cents"]

        settled_total = sum(t["net_effect_cents"] for t in txn_source
                            if t["settlement_status"] == "SETTLED"
                            and t["value_effective_utc"] <= cycle_ms)
        matched_posted = sum(self.store.transactions[tid]["net_effect_cents"]
                             for tid in matched_ids)
        matched_line_amounts = sum(
            l["amount_cents"] for l in lines if l["match_state"] == "MATCHED")
        # the bank's own line amounts are the matched figure when a net line absorbs
        # several internal legs; the internal figure is published alongside.
        statement["matched_posted_cents"] = matched_posted
        statement["matched_line_cents"] = matched_line_amounts
        unmatched = (settled_total - matched_line_amounts - excess_cents
                     + unattributed_cents)
        statement["unmatched_amount_cents"] = unmatched
        return unmatched

    def _statement_transactions(self, statement):
        account = self.store.bank_accounts.get(statement["bank_account_id"])
        ledger_ids = set()
        if account is not None:
            for ledger in self.store.ledgers.values():
                if ledger.get("legal_entity_id") == account.get("legal_entity_id"):
                    ledger_ids.add(ledger["id"])
        for txn in self.store.transactions.values():
            order = self.store.payment_orders.get(txn.get("payment_order_id"))
            if order is not None and order.get("source_account_id") == statement["bank_account_id"]:
                ledger_ids.add(txn["ledger_id"])
            if order is not None and account is not None and \
                    order.get("legal_entity_id") == account.get("legal_entity_id"):
                ledger_ids.add(txn["ledger_id"])
        return [t for t in self.store.transactions.values() if t["ledger_id"] in ledger_ids]

    # ---------------------------------------------------------------- deposit attribution

    def resolve_destination(self, line):
        """Returns (virtual_account, ledger_id) or (None, None) per the four branches."""
        statement = self.store.statements.get(line["bank_statement_id"])
        if statement is None:
            return None, None
        if line["effective_at_ms"] > statement["cycle_date_ms"]:
            return None, None
        candidates = [v for v in self.store.virtual_accounts.values()
                      if v["bank_account_id"] == statement["bank_account_id"]
                      and v["status"] == "OPEN"]
        chosen = None
        ref = line.get("embedded_reference_code")
        if ref:
            for v in candidates:
                if v["reference_code"] == ref:
                    chosen = v
                    break
        if chosen is None:
            bank_ref = line.get("bank_reference") or ""
            account = self.store.bank_accounts.get(statement["bank_account_id"])
            if account is not None:
                last4 = account["account_number_last4"]
                for v in candidates:
                    num = v["virtual_account_number"]
                    if num == bank_ref or (num.endswith(last4) and last4 in bank_ref
                                           and num[:len(num) - len(last4)] in bank_ref):
                        chosen = v
                        break
            if chosen is None:
                for v in candidates:
                    if v["virtual_account_number"] in bank_ref:
                        chosen = v
                        break
        if chosen is None and len(candidates) == 1:
            chosen = candidates[0]
        if chosen is None:
            return None, None
        return chosen, statement.get("_ledger_id")

    def deposit_fields(self, gross):
        fee, amount = calc.deposit_split(gross)
        return fee, amount

    # ---------------------------------------------------------------- exceptions

    def raise_exception(self, ledger_id, kind, amount_cents, payment_order_id=None,
                        bank_statement_id=None, attributed_fee_cents=0,
                        attributable_amount_cents=0, actor=None):
        ledger = self.store.ledgers.get(ledger_id)
        closing_ms = ledger["period_close_ms"] if ledger is not None else self.now_ms()
        row = self.created_row(
            ledger_id=ledger_id,
            payment_order_id=payment_order_id,
            bank_statement_id=bank_statement_id,
            kind=kind,
            amount_cents=amount_cents,
            attributed_fee_cents=attributed_fee_cents,
            attributable_amount_cents=attributable_amount_cents,
            opened_utc=self.now_ms(),
            closing_period_utc=closing_ms,
            status="OPEN",
            assignee_user_id=None,
            resolution_note=None,
        )
        self.store.exceptions[row["id"]] = row
        return row

    def open_exceptions(self, ledger_id, kind=None):
        rows = [e for e in self.store.exceptions.values()
                if e["ledger_id"] == ledger_id and e["status"] in ("OPEN", "ASSIGNED", "ESCALATED")]
        if kind is not None:
            rows = [e for e in rows if e["kind"] == kind]
        return rows

    def run_aging_pass(self, ledger_id):
        for exc in self.store.exceptions.values():
            if exc["ledger_id"] == ledger_id and exc["status"] in ("OPEN", "ASSIGNED", "ESCALATED"):
                age = self.exception_age_days(exc)
                exc["aging_bucket_cached"] = self.aging_bucket(age)

    def unattributed_deposit_open_on(self, ledger_id):
        return bool(self.open_exceptions(ledger_id, kind="UNMATCHED_DEPOSIT"))

    # ---------------------------------------------------------------- fee pool

    def active_return_legs(self, ledger_id):
        rows = [t for t in self.store.transactions.values()
                if t["ledger_id"] == ledger_id and t["entry_type"] == "RETURN"
                and t["settlement_status"] in ("UNSETTLED", "IN_SETTLEMENT")
                and t["id"] not in self.store.ledgers[ledger_id].get("resolved_return_leg_ids", set())]
        rows.sort(key=lambda t: (t["created_at"], t["sequence"]))
        return rows

    def fee_cover_cents(self, ledger_id, return_leg):
        total = 0
        for t in self.store.transactions.values():
            if t["ledger_id"] != ledger_id:
                continue
            if t["entry_type"] != "FEE" or t["settlement_status"] != "SETTLED":
                continue
            if t["value_effective_utc"] <= return_leg["value_effective_utc"]:
                total += t["net_effect_cents"]
        return abs(total)

    def reverse_fee_shares(self, ledger_id):
        legs = self.active_return_legs(ledger_id)
        total = calc.RETURN_LEG_FEE_CENTS * len(legs)
        shares = calc.allocate_shares(total, [1] * len(legs))
        return list(zip(legs, shares))

    def resolve_return_leg_fee(self, ledger_id, return_leg):
        ledger = self.store.ledgers[ledger_id]
        legs = self.active_return_legs(ledger_id)
        ordered = [l["id"] for l in legs]
        total = calc.RETURN_LEG_FEE_CENTS * len(legs)
        shares = calc.allocate_shares(total, [1] * len(legs))
        share = 0
        for leg, s in zip(legs, shares):
            if leg["id"] == return_leg["id"]:
                share = s
                break
        cover = self.fee_cover_cents(ledger_id, return_leg)
        delivered, undeliverable = calc.reverse_fee_split(cover, share)
        ledger["delivered_fee_transfers_cents"] += delivered
        ledger["undeliverable_cents"] += undeliverable
        ledger.setdefault("resolved_return_leg_ids", set()).add(return_leg["id"])
        return delivered, undeliverable

    # ---------------------------------------------------------------- cutoff resolution

    def resolve_cutoffs(self, order):
        account = self.store.bank_accounts.get(order["source_account_id"])
        if account is None:
            return [], None
        entity_id = account["legal_entity_id"]
        cells = [c for c in self.store.calendar_cells.values()
                 if c["legal_entity_id"] == entity_id]
        if not cells:
            return [], None
        tz = self.calendar_timezone_for(entity_id)
        opened_ms = order["created_at"]
        opened_date = local_date_from_ms(opened_ms, tz)
        opened_time = local_time_from_ms(opened_ms, tz)
        horizon = opened_date.fromordinal(opened_date.toordinal() + calc.LOOKAHEAD_CALENDAR_DAYS)
        by_date = {parse_date(c["calendar_date"]): c for c in cells if c["is_open"]}
        candidates = []
        for cell in cells:
            if not cell["is_open"]:
                continue
            cell_date = parse_date(cell["calendar_date"])
            if not (opened_date <= cell_date <= horizon):
                continue
            if order["rail"] not in cell["allowed_rails"]:
                continue
            for cutoff in cell["cutoffs"]:
                if cutoff.get("rail") != order["rail"]:
                    continue
                cutoff_time = cutoff["_local_time"]
                if opened_time <= cutoff_time:
                    moment_ms = utc_ms_from_local(cell_date, cutoff_time, tz)
                else:
                    nxt = cell_date.fromordinal(cell_date.toordinal() + 1)
                    open_cell = by_date.get(nxt)
                    if open_cell is None:
                        continue
                    moment_ms = utc_ms_from_local(nxt, cutoff_time, tz)
                candidates.append({
                    "rail": order["rail"],
                    "cutoff_utc": moment_ms,
                    "_cutoff_ms": moment_ms,
                    "calendar_code": cell.get("calendar_code",
                                              "%s-%s" % (entity_id[:8], cell["calendar_date"])),
                    "_cell": cell,
                    "_time": cutoff_time,
                })
        if not candidates:
            return [], None
        candidates.sort(key=lambda c: c["_cutoff_ms"])
        snapshot = candidates[0]["_cutoff_ms"]
        return candidates, snapshot

    # ---------------------------------------------------------------- transaction helpers

    def create_transaction(self, ledger_id, entry_type, direction, amount_cents,
                           value_effective_utc, payment_order_id=None,
                           reverses_transaction_id=None, refunds_transaction_id=None,
                           lifecycle_status="PENDING", settlement_status="UNSETTLED",
                           actor=None, action="transaction.created", touch_ledger=True):
        net = -amount_cents if direction == "DEBIT" else amount_cents
        row = self.created_row(
            ledger_id=ledger_id,
            payment_order_id=payment_order_id,
            entry_type=entry_type,
            direction=direction,
            amount_cents=amount_cents,
            net_effect_cents=net,
            value_effective_utc=value_effective_utc,
            reverses_transaction_id=reverses_transaction_id,
            refunds_transaction_id=refunds_transaction_id,
            lifecycle_status=lifecycle_status,
            settlement_status=settlement_status,
        )
        self.store.transactions[row["id"]] = row
        ledger = self.store.ledgers.get(ledger_id)
        if ledger is not None and touch_ledger:
            self.touch(ledger)
        if action:
            self.append_audit(ledger_id, actor, action, "Transaction", row["id"],
                              {"entry_type": entry_type, "direction": direction,
                               "amount_cents": amount_cents})
        return row

    def order_legs(self, order_id):
        rows = [t for t in self.store.transactions.values()
                if t["payment_order_id"] == order_id]
        rows.sort(key=lambda t: (t["created_at"], t["sequence"]))
        return rows

    def order_settled_net_cents(self, order_id):
        return sum(t["net_effect_cents"] for t in self.order_legs(order_id)
                   if t["settlement_status"] == "SETTLED"
                   and t["entry_type"] in ("ORIGINATING", "FEE"))

    # ---------------------------------------------------------------- requests

    def linked_release_requests(self, order_id):
        rows = [r for r in self.store.release_requests.values()
                if r["payment_order_id"] == order_id]
        rows.sort(key=lambda r: (r["created_at"], r["sequence"]))
        return rows


# ------------------------------------------------------------------ module-level helpers

def accepts(roles, role):
    return role in roles


def single_role(roles):
    return len(roles) == 1