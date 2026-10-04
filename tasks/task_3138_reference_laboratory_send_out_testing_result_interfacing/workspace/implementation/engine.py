"""Workflow engine: state transitions, cascades and clock-driven events.

Everything here traces to PRD section 3 and its structured twin SCAFFOLD
section 1.2. Public entry points are the engine_* functions called by the route
layer; each one performs its validations in the pinned priority order, commits
its side effects, and returns the mutated row.
"""

from datetime import timedelta

import db
import rules
import serializers
import middleware
from db import parse_dt, iso, get, put, touch, all_rows
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_ALREADY_TERMINAL,
    ERR_ORDER_NOT_ACCESSIBLE,
    ERR_EMPTY_REQUISITION,
    ERR_CATALOG_ENTRY_NOT_PUBLISHED,
    ERR_INTERFACE_BUILD_NOT_CERTIFIED,
    ERR_SPECIMEN_TYPE_MISMATCH,
    ERR_INSUFFICIENT_SPECIMEN_VOLUME,
    ERR_TRANSPORT_TEMPERATURE_EXCEEDED,
    ERR_SPECIMEN_STABILITY_EXCEEDED,
    ERR_REFLEX_WINDOW_EXPIRED,
    ERR_INSUFFICIENT_STABILITY_FOR_REFLEX,
    ERR_REFLEX_CONDITION_NOT_MET,
    ERR_SPECIMEN_NOT_ACCEPTABLE,
    ERR_CRITICAL_VALUE_NOT_NOTIFIED,
    ERR_SOD_RESULT_ENTRY_RELEASE,
    ERR_INSTRUMENT_DOUBLE_BOOKED,
    ERR_COURIER_LEG_OVERLAP,
    ERR_UTILIZATION_GUARD_BLOCKED,
    ERR_VOID_AMOUNT_MISMATCH,
    ERR_ALIQUOT_PARENT_MISMATCH,
    ERR_ALIQUOT_OVERDRAW,
    ERR_DUPLICATE_ADD_ON_LINE,
    ERR_DUPLICATE_TEST_CODE,
    ERR_DUPLICATE_ACCESSION_NUMBER,
    ERR_CONTROL_ID_REUSED,
    ERR_UTILIZATION_ADVISORY_NOT_FOUND,
    ERR_CLIENT_NOT_ACTIVE,
    ERR_INVALID_TEMPORAL_WINDOW,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_INTERFACE_RESULT_GATED,
    ERR_RETRY_LIMIT_REACHED,
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
)

ORDER_PLURAL = {
    "client_laboratories": "client_laboratories",
    "order_test_lines": "order_test_lines",
    "send_out_orders": "send_out_orders",
}


# ---------------------------------------------------------------------------
# transition tables (SCAFFOLD section 1.2)
# ---------------------------------------------------------------------------

CLIENT_TRANSITIONS = {
    "activate": {"from": ["PENDING_ONBOARDING"], "to": "ACTIVE"},
    "suspend": {"from": ["ACTIVE", "CREDIT_HOLD"], "to": "SUSPENDED"},
    "reinstate": {"from": ["SUSPENDED"], "to": "ACTIVE"},
    "deactivate": {"from": ["SUSPENDED"], "to": "INACTIVE"},
}

COURIER_TRANSITIONS = {
    "dispatch": {"from": ["PLANNED"], "to": "DISPATCHED"},
    "recall": {"from": ["DISPATCHED"], "to": "PLANNED"},
    "arrive": {"from": ["IN_TRANSIT"], "to": "COMPLETED"},
}

CATALOG_TRANSITIONS = {
    "publish": {"from": ["DRAFT", "DEPRECATED"], "to": "PUBLISHED"},
    "deprecate": {"from": ["PUBLISHED"], "to": "DEPRECATED"},
    "withdraw": {"from": ["PUBLISHED", "DEPRECATED"], "to": "WITHDRAWN"},
}

SPECIMEN_TRANSITIONS = {
    "accession": {"from": ["RECEIVED", "REJECTED"], "to": "ACCESSIONED"},
    "begin-testing": {"from": ["ACCESSIONED"], "to": "IN_TESTING"},
    "reject": {"from": ["RECEIVED", "ACCESSIONED"], "to": "REJECTED"},
}

ORDER_TRANSITIONS = {
    "accession": {"from": ["SUBMITTED"], "to": "ACCESSIONED"},
    "release-results": {"from": ["IN_TESTING", "INTERIM_REPORTED"], "to": "RESULT_RELEASED"},
    "cancel": {"from": ["SUBMITTED", "ACCESSIONED", "IN_TESTING", "INTERIM_REPORTED"], "to": "CANCELLED"},
    "hold": {"from": ["SUBMITTED", "ACCESSIONED", "IN_TESTING", "INTERIM_REPORTED"], "to": "ON_HOLD"},
    "release-hold": {"from": ["ON_HOLD"], "to": "SUBMITTED"},
    "reflex-cancel": {"from": ["REFLEX_PENDING"], "to": "RESULT_RELEASED"},
    "order-reflex-test": {"from": ["RESULT_RELEASED"], "to": "REFLEX_PENDING"},
    "charge": {"from": ["UNBILLED", "PROVISIONAL", "VOIDED"], "to": "BILLED", "dimension": "billing"},
}

INSTRUMENT_TRANSITIONS = {
    "abort": {"from": ["RESERVED"], "to": "ABORTED"},
    "rebook": {"from": ["ABORTED"], "to": "RESERVED"},
}

BUILD_TRANSITIONS = {
    "start-build": {"from": ["DRAFT", "RETIRED"], "to": "IN_BUILD"},
    "certify": {"from": ["IN_BUILD"], "to": "CERTIFIED"},
    "supersede": {"from": ["CERTIFIED"], "to": "SUPERSEDED"},
    "retire": {"from": ["SUPERSEDED"], "to": "RETIRED"},
}

MESSAGE_TRANSITIONS = {
    "validate": {"from": ["QUEUED", "HELD", "FAILED"], "to": "VALIDATED"},
    "transmit": {"from": ["VALIDATED"], "to": "TRANSMITTED"},
    "fail": {"from": ["VALIDATED"], "to": "FAILED"},
    "hold": {"from": ["QUEUED", "VALIDATED", "TRANSMITTED"], "to": "HELD"},
    "release-hold": {"from": ["HELD"], "to": "VALIDATED"},
    "acknowledge": {"from": ["TRANSMITTED"], "to": "ACKNOWLEDGED"},
}

ADVISORY_TRANSITIONS = {
    "acknowledge": {"from": ["OPEN", "SENT"], "to": "ACKNOWLEDGED"},
    "dismiss": {"from": ["OPEN", "SENT"], "to": "DISMISSED"},
    "escalate": {"from": ["OPEN", "SENT"], "to": "ESCALATED"},
}

# SendOutOrder declares a second, independent dimension: billing_status.
BILLING_STATES = {"UNBILLED", "PROVISIONAL", "BILLED", "VOIDED"}

# Declared state enums per entity (SCAFFOLD section 1.1 field constraints). A
# value outside this set is not a state the resource can be observed in.
STATE_ENUMS = {
    "client_laboratories": {"PENDING_ONBOARDING", "ACTIVE", "CREDIT_HOLD",
                            "SUSPENDED", "INACTIVE"},
    "courier_runs": {"PLANNED", "DISPATCHED", "IN_TRANSIT", "COMPLETED", "ABORTED"},
    "test_catalog_entries": {"DRAFT", "PUBLISHED", "DEPRECATED", "WITHDRAWN"},
    "specimens": {"RECEIVED", "ACCESSIONED", "IN_TESTING", "RESULT_PENDING_REVIEW",
                  "RELEASED", "REJECTED"},
    "send_out_orders": {"SUBMITTED", "ACCESSIONED", "IN_TESTING", "INTERIM_REPORTED",
                        "RESULT_RELEASED", "REFLEX_PENDING", "ON_HOLD", "CLOSED",
                        "CANCELLED"},
    "order_test_lines": {"PENDING", "IN_PROGRESS", "INTERIM", "FINAL",
                         "REPEAT_REQUIRED", "CANCELLED"},
    "instrument_runs": {"RESERVED", "RUNNING", "COMPLETED", "ABORTED"},
    "interface_builds": {"DRAFT", "IN_BUILD", "CERTIFIED", "SUPERSEDED", "RETIRED"},
    "result_interface_messages": {"QUEUED", "VALIDATED", "HELD", "TRANSMITTED",
                                  "FAILED", "ACKNOWLEDGED"},
    "utilization_advisories": {"OPEN", "SENT", "ACKNOWLEDGED", "DISMISSED", "ESCALATED"},
}

# Declared terminal states per entity (SCAFFOLD section 1.2 terminal_states).
TERMINALS = {
    "client_laboratories": {"INACTIVE"},
    "courier_runs": {"COMPLETED", "ABORTED"},
    "test_catalog_entries": {"WITHDRAWN"},
    "specimens": {"RELEASED", "REJECTED"},
    "send_out_orders": {"CLOSED", "CANCELLED"},
    "order_test_lines": {"FINAL", "CANCELLED"},
    "instrument_runs": {"COMPLETED"},
    "interface_builds": {"RETIRED"},
    "result_interface_messages": {"ACKNOWLEDGED"},
    "utilization_advisories": {"DISMISSED", "ESCALATED"},
}

# The state attribute that carries the transitioned dimension on each entity.
STATE_FIELD = {
    "client_laboratories": "status",
    "courier_runs": "status",
    "test_catalog_entries": "status",
    "specimens": "status",
    "send_out_orders": "order_status",
    "order_test_lines": "line_status",
    "instrument_runs": "run_status",
    "interface_builds": "status",
    "result_interface_messages": "status",
    "utilization_advisories": "status",
}

# Transition groups whose redo/rerun legs legitimately leave a terminal state.
TERMINAL_EXEMPT = {
    ("specimens", "accession"),
    ("instrument_runs", "rebook"),
    ("interface_builds", "start-build"),
}


# ---------------------------------------------------------------------------
# generic state guard (PRD section 2.11, validations priority 5 / 5.5)
# ---------------------------------------------------------------------------

def transition_state_field(kind, trigger):
    if kind == "send_out_orders" and trigger == "charge":
        return "billing_status"
    return STATE_FIELD[kind]


def guard_transition(kind, trigger, table, row):
    """Validate priority 5 then 5.5 for an action endpoint.

    PRD 2.11: "State checks come next: a transition attempted from a state that
    is not a declared starting point for that action is refused with
    ERR_INVALID_STATE, and an attempt to move a resource out of a declared
    terminal state is refused with ERR_ALREADY_TERMINAL." Only a state the
    entity actually declares in SCAFFOLD section 1.1 can be terminal for it, so a
    value outside an entity's declared enum (the scheduler's INTERIM_REPORTED
    escape is the concrete case) reports the generic state error instead.
    """
    rule = table.get(trigger)
    if rule is None:
        raise ApiError(ERR_INVALID_STATE, "Undefined transition.")
    field = rule.get("dimension") and "billing_status" or transition_state_field(kind, trigger)
    current = row.get(field)
    declared = STATE_ENUMS.get(kind)
    if field == "billing_status":
        declared = BILLING_STATES
    if current not in declared:
        raise ApiError(
            ERR_INVALID_STATE,
            "State %s is not one this resource declares." % (current,),
        )
    if current in TERMINALS.get(kind, ()) and (kind, trigger) not in TERMINAL_EXEMPT:
        raise ApiError(
            ERR_ALREADY_TERMINAL,
            "Resource sits in terminal state %s." % (current,),
        )
    if current not in rule["from"]:
        raise ApiError(
            ERR_INVALID_STATE,
            "Transition %s is not declared from state %s." % (trigger, current),
        )
    return field


# ---------------------------------------------------------------------------
# OCC helper (PRD section 2.7, validations priority 4.5)
# ---------------------------------------------------------------------------

def check_occ(body, field, parent):
    """The guard is non-optional; mismatch is rejected before every business rule."""
    if field not in body:
        raise ApiError(ERR_INVALID_REQUEST, "Field %s is required." % (field,))
    supplied = body.get(field)
    if isinstance(supplied, str):
        try:
            supplied = int(supplied)
        except ValueError:
            supplied = None
    if supplied is None or int(supplied) != int(parent.get("version", 0)):
        raise ApiError(
            ERR_STALE_VERSION,
            "%s does not match the parent's current version." % (field,),
        )


# ---------------------------------------------------------------------------
# temporal / shape helpers
# ---------------------------------------------------------------------------

def needs_published_requirements(client):
    """PRD section 3.2: a client must have a published requirement note to submit."""
    if client is None:
        return False
    if client.get("status") in ("SUSPENDED", "INACTIVE"):
        return False
    if client.get("requirement_notes_published_at") is None:
        return False
    return True


def require_intake_admissible(client):
    """Validation priority 21: client posture and published requirement note."""
    if client is None:
        return
    if not needs_published_requirements(client):
        raise ApiError(
            ERR_CLIENT_NOT_ACTIVE,
            "Client is SUSPENDED or INACTIVE, or its requirement note is not published.",
        )


def within_credit_ceiling(client, amount_cents):
    """Validation priority 24: a charge may not push a CLIENT-routed balance over."""
    if client is None:
        return
    if (client.get("billing_arrangement") or "CLIENT") != "CLIENT":
        return
    current = rules.dec(client.get("outstanding_balance_cents"))
    projected = current + rules.dec(amount_cents)
    if projected > rules.dec(client.get("credit_limit_cents")):
        raise ApiError(
            ERR_CREDIT_LIMIT_EXCEEDED,
            "Charge would push the routed balance above the client's credit limit.",
        )


# ---------------------------------------------------------------------------
# cascades
# ---------------------------------------------------------------------------

def _ledger_for(client_id):
    for ledger in all_rows("billing_ledgers"):
        if ledger.get("client_laboratory_id") == client_id:
            return ledger
    return None


def post_charge_to_ledger(client, amount_cents):
    ledger = _ledger_for(client["id"])
    if ledger is not None:
        ledger["billed_cents"] = rules.num(
            rules.round_half_up(rules.dec(ledger.get("billed_cents")) + rules.dec(amount_cents), 2)
        )
        ledger["charge_entry_count"] = int(ledger.get("charge_entry_count") or 0) + 1
        rules.recompute_ledger(ledger)
        touch(ledger)
    refresh_client_posture(client)
    return ledger


def void_charge_on_ledger(client, amount_cents):
    ledger = _ledger_for(client["id"])
    if ledger is not None:
        ledger["voided_cents"] = rules.num(
            rules.round_half_up(rules.dec(ledger.get("voided_cents")) + rules.dec(amount_cents), 2)
        )
        rules.recompute_ledger(ledger)
        touch(ledger)
    refresh_client_posture(client)
    return ledger


def refresh_client_posture(client):
    """Recompute derived counters and flip ACTIVE -> CREDIT_HOLD when over limit."""
    balance = rules.recompute_outstanding_balance(client)
    rules.recompute_billable_line_count(client)
    rules.recompute_utilization(client)
    rules.recompute_interface_status(client)
    if client.get("status") == "ACTIVE" and balance > rules.dec(client.get("credit_limit_cents")):
        client["status"] = "CREDIT_HOLD"
        for order in orders_of_client_all(client["id"]):
            if order.get("order_status") == "SUBMITTED":
                order["order_status"] = "ON_HOLD"
                touch(order)
        client["_posture_flip"] = True
    touch(client)
    return client


def orders_of_client_all(client_id):
    return [o for o in all_rows("send_out_orders") if o.get("client_laboratory_id") == client_id]


def lines_for_catalog_entry(entry_id):
    return [l for l in all_rows("order_test_lines") if l.get("test_catalog_entry_id") == entry_id]


# ---------------------------------------------------------------------------
# clock-driven system transitions (PRD section 2.4)
# ---------------------------------------------------------------------------

def fire_clock_events():
    """Advance every scheduled resource whose instant the clock has reached."""
    now = db.now()
    for run in all_rows("courier_runs"):
        if run.get("status") == "DISPATCHED":
            departure = parse_dt(run.get("scheduled_departure_at"))
            # A leg dispatched once its departure instant had already arrived is not
            # swept to IN_TRANSIT until the clock moves again, so the declared
            # DISPATCHED -> PLANNED recall leg stays reachable while the vehicle has
            # not physically left.
            dispatched_at = parse_dt(run.get("_dispatch_clock_at"))
            already_moved = dispatched_at is not None and now <= dispatched_at
            if departure is not None and departure <= now and not already_moved:
                run["status"] = "IN_TRANSIT"
                touch(run)
        if run.get("status") == "IN_TRANSIT":
            delivery = parse_dt(run.get("scheduled_delivery_at"))
            if delivery is not None and delivery <= now:
                run["status"] = "COMPLETED"
                run["specimen_count"] = sum(
                    1 for s in all_rows("specimens") if s.get("courier_run_id") == run["id"]
                )
                touch(run)
    for run in all_rows("instrument_runs"):
        if run.get("run_status") == "RESERVED":
            start = parse_dt(run.get("reserved_start_at"))
            if start is not None and start <= now:
                run["run_status"] = "RUNNING"
                touch(run)
        if run.get("run_status") == "RUNNING":
            end = parse_dt(run.get("reserved_end_at"))
            if end is not None and end <= now:
                run["run_status"] = "COMPLETED"
                run["occupied_until_at"] = iso(
                    end + timedelta(minutes=int(run.get("decontamination_buffer_minutes") or 0))
                )
                touch(run)


def set_clock(value):
    parsed = parse_dt(value)
    if parsed is None:
        raise ApiError(ERR_INVALID_REQUEST, "current_utc must be an ISO 8601 instant.")
    db.set_now(parsed)
    fire_clock_events()
    return parsed


# ---------------------------------------------------------------------------
# ClientLaboratory workflows
# ---------------------------------------------------------------------------

def engine_client_publish_requirements(client):
    client["requirement_notes_published_at"] = iso(db.now())
    if client.get("onboarding_status") == "DOCUMENTS_PENDING":
        client["onboarding_status"] = "REQUIREMENTS_PUBLISHED"
    if _courier_run_count(client["id"]) >= 1:
        client["onboarding_status"] = "COMPLETE"
    for advisory in all_rows("utilization_advisories"):
        if advisory.get("client_laboratory_id") == client["id"] and advisory.get("status") == "OPEN":
            if client.get("onboarding_status") == "COMPLETE":
                advisory["status"] = "SENT"
                advisory["send_count"] = int(advisory.get("send_count") or 0) + 1
                touch(advisory)
    rules.recompute_interface_status(client)
    rules.recompute_outstanding_balance(client)
    rules.recompute_billable_line_count(client)
    rules.recompute_utilization(client)
    touch(client)
    return client


def _courier_run_count(client_id):
    return sum(1 for r in all_rows("courier_runs") if r.get("client_laboratory_id") == client_id)


def engine_client_activate(client):
    guard_transition("client_laboratories", "activate", CLIENT_TRANSITIONS, client)
    if client.get("onboarding_status") != "COMPLETE":
        raise ApiError(ERR_INVALID_STATE, "onboarding_status must be COMPLETE before activation.")
    rules.recompute_interface_status(client)
    if client.get("interface_status") != "CERTIFIED":
        raise ApiError(ERR_INVALID_STATE, "A certified interface build is required for activation.")
    if _courier_run_count(client["id"]) < 1:
        raise ApiError(ERR_INVALID_STATE, "At least one courier run is required for activation.")
    rules.recompute_outstanding_balance(client)
    if rules.dec(client.get("outstanding_balance_cents")) > rules.dec(client.get("credit_limit_cents")):
        raise ApiError(ERR_INVALID_STATE, "Outstanding balance exceeds the credit limit.")
    client["status"] = "ACTIVE"
    rules.recompute_interface_status(client)
    rules.recompute_outstanding_balance(client)
    rules.recompute_billable_line_count(client)
    rules.recompute_utilization(client)
    touch(client)
    return client


def engine_client_suspend(client):
    guard_transition("client_laboratories", "suspend", CLIENT_TRANSITIONS, client)
    client["status"] = "SUSPENDED"
    for run in all_rows("courier_runs"):
        if run.get("client_laboratory_id") == client["id"] and run.get("status") == "PLANNED":
            run["status"] = "ABORTED"
            touch(run)
    touch(client)
    return client


def engine_client_reinstate(client):
    guard_transition("client_laboratories", "reinstate", CLIENT_TRANSITIONS, client)
    rules.recompute_interface_status(client)
    if client.get("interface_status") != "CERTIFIED":
        raise ApiError(ERR_INVALID_STATE, "A certified interface build is required for reinstatement.")
    rules.recompute_outstanding_balance(client)
    if rules.dec(client.get("outstanding_balance_cents")) > rules.dec(client.get("credit_limit_cents")):
        raise ApiError(ERR_INVALID_STATE, "Outstanding balance exceeds the credit limit.")
    client["status"] = "ACTIVE"
    touch(client)
    return client


def engine_client_deactivate(client):
    guard_transition("client_laboratories", "deactivate", CLIENT_TRANSITIONS, client)
    live = {"SUBMITTED", "ACCESSIONED", "IN_TESTING", "INTERIM_REPORTED", "REFLEX_PENDING", "ON_HOLD"}
    for order in orders_of_client_all(client["id"]):
        if order.get("order_status") in live:
            raise ApiError(ERR_INVALID_STATE, "Client has live orders and cannot be deactivated.")
    client["status"] = "INACTIVE"
    touch(client)
    return client


def engine_client_settle_balance(client, amount_cents):
    # The settlement grows the ledger's voided total (the declared side effect) and
    # is netted against the client's routed balance so the posture can revert.
    client["_settlement_credit_cents"] = rules.num(
        rules.round_half_up(
            rules.dec(client.get("_settlement_credit_cents") or 0) + rules.dec(amount_cents), 2
        )
    )
    ledger = _ledger_for(client["id"])
    if ledger is not None:
        ledger["voided_cents"] = rules.num(
            rules.round_half_up(
                rules.dec(ledger.get("voided_cents")) + rules.dec(amount_cents), 2
            )
        )
        rules.recompute_ledger(ledger)
        touch(ledger)
    balance = rules.recompute_outstanding_balance(client)
    rules.recompute_billable_line_count(client)
    rules.recompute_utilization(client)
    rules.recompute_interface_status(client)
    if client.get("status") == "CREDIT_HOLD" and balance <= rules.dec(client.get("credit_limit_cents")):
        client["status"] = "ACTIVE"
    touch(client)
    return client


# ---------------------------------------------------------------------------
# CourierRun workflows
# ---------------------------------------------------------------------------

def engine_courier_dispatch(run):
    guard_transition("courier_runs", "dispatch", COURIER_TRANSITIONS, run)
    departure = parse_dt(run.get("scheduled_departure_at"))
    if departure is None or departure > db.now():
        raise ApiError(ERR_INVALID_STATE, "scheduled_departure_at has not been reached.")
    client = get("client_laboratories", run.get("client_laboratory_id"))
    if (client or {}).get("status") not in ("ACTIVE", "CREDIT_HOLD"):
        raise ApiError(ERR_INVALID_STATE, "Owning client is not ACTIVE or CREDIT_HOLD.")
    run["status"] = "DISPATCHED"
    run["_dispatch_clock_at"] = iso(db.now())
    touch(run)
    return run


def engine_courier_recall(run):
    guard_transition("courier_runs", "recall", COURIER_TRANSITIONS, run)
    pickup = parse_dt(run.get("scheduled_pickup_at"))
    if pickup is None or pickup <= db.now():
        raise ApiError(ERR_INVALID_STATE, "The vehicle has already left; recall is not possible.")
    run["status"] = "PLANNED"
    touch(run)
    return run


def engine_courier_arrive(run):
    guard_transition("courier_runs", "arrive", COURIER_TRANSITIONS, run)
    delivery = parse_dt(run.get("scheduled_delivery_at"))
    if delivery is None or delivery > db.now():
        raise ApiError(ERR_INVALID_STATE, "scheduled_delivery_at has not been reached.")
    run["status"] = "COMPLETED"
    run["specimen_count"] = sum(1 for s in all_rows("specimens") if s.get("courier_run_id") == run["id"])
    touch(run)
    return run


# ---------------------------------------------------------------------------
# TestCatalogEntry workflows
# ---------------------------------------------------------------------------

def engine_catalog_publish(entry):
    guard_transition("test_catalog_entries", "publish", CATALOG_TRANSITIONS, entry)
    for other in all_rows("test_catalog_entries"):
        if other["id"] == entry["id"]:
            continue
        if other.get("test_code") == entry.get("test_code") and other.get("status") != "WITHDRAWN":
            raise ApiError(ERR_DUPLICATE_TEST_CODE, "test_code is already carried by a live entry.")
    if entry.get("reflex_condition") not in (None, "NONE"):
        target = _find_entry_by_code(entry.get("reflex_test_code"))
        if target is None or target.get("status") != "PUBLISHED":
            raise ApiError(ERR_INVALID_STATE, "reflex_test_code must name a PUBLISHED entry.")
    entry["status"] = "PUBLISHED"
    entry["updated_at"] = iso(db.now())
    entry["version"] = int(entry.get("version", 1)) + 1
    return entry


def engine_catalog_deprecate(entry):
    guard_transition("test_catalog_entries", "deprecate", CATALOG_TRANSITIONS, entry)
    entry["status"] = "DEPRECATED"
    touch(entry)
    return entry


def engine_catalog_withdraw(entry):
    guard_transition("test_catalog_entries", "withdraw", CATALOG_TRANSITIONS, entry)
    for line in lines_for_catalog_entry(entry["id"]):
        if line.get("line_status") in ("PENDING", "IN_PROGRESS", "INTERIM"):
            raise ApiError(
                ERR_INVALID_STATE,
                "A test line for this entry is still PENDING, IN_PROGRESS or INTERIM.",
            )
    entry["status"] = "WITHDRAWN"
    touch(entry)
    _catalog_withdrawal_cascade(entry)
    return entry


def _catalog_withdrawal_cascade(entry):
    affected_specimens = set()
    for line in lines_for_catalog_entry(entry["id"]):
        order = get("send_out_orders", line.get("send_out_order_id"))
        if order is None:
            continue
        specimen = get("specimens", order.get("specimen_id"))
        if specimen is None:
            continue
        if specimen.get("status") in ("RECEIVED", "ACCESSIONED", "IN_TESTING"):
            # HOP 1: reject the specimen, leaving its condition untouched
            specimen["status"] = "REJECTED"
            specimen["rejection_reason_code"] = "TEST_WITHDRAWN"
            touch(specimen)
            affected_specimens.add(specimen["id"])

    affected_clients = set()
    for specimen_id in affected_specimens:
        # A specimen may carry more than one order, and hop 2 sweeps up every
        # order riding a rejected specimen, not merely the earliest one.
        for order in rules.orders_of_specimen(specimen_id):
            if order.get("order_status") not in (
                "SUBMITTED", "ACCESSIONED", "IN_TESTING", "INTERIM_REPORTED"
            ):
                continue
            _withdraw_cancel_order(order, affected_clients)
    # HOP 5: recompute client balances; a void only lowers the routed balance, so
    # the client never enters CREDIT_HOLD from this chain.
    for client_id in affected_clients:
        client = get("client_laboratories", client_id)
        if client is None:
            continue
        rules.recompute_outstanding_balance(client)
        rules.recompute_billable_line_count(client)
        rules.recompute_utilization(client)
        touch(client)


def _withdraw_cancel_order(order, affected_clients):
    """Hops 2-4 for one order caught by the catalog-withdrawal cascade."""
    # HOP 2: cancel the order
    order["order_status"] = "CANCELLED"
    cancelled_lines_with_charge = []
    for line in all_rows("order_test_lines"):
        if line.get("send_out_order_id") != order["id"]:
            continue
        if line.get("line_status") != "CANCELLED":
            # HOP 3: cancel the line, preserving any existing charge
            line["line_status"] = "CANCELLED"
            touch(line)
        if rules.dec(line.get("billed_cents")) > 0:
            cancelled_lines_with_charge.append(line)
    if cancelled_lines_with_charge:
        # HOP 4: void the order and grow the ledger's voided total
        order["billing_status"] = "VOIDED"
        amount = sum(
            (rules.dec(l.get("billed_cents")) for l in cancelled_lines_with_charge),
            rules.Decimal("0"),
        )
        client = get("client_laboratories", order.get("client_laboratory_id"))
        if client is not None:
            ledger = _ledger_for(client["id"])
            if ledger is not None:
                ledger["voided_cents"] = rules.num(
                    rules.round_half_up(rules.dec(ledger.get("voided_cents")) + amount, 2)
                )
                rules.recompute_ledger(ledger)
                touch(ledger)
            affected_clients.add(client["id"])
    touch(order)
    if order.get("client_laboratory_id"):
        affected_clients.add(order["client_laboratory_id"])


def _order_for_specimen(specimen_id):
    rows = [o for o in all_rows("send_out_orders") if o.get("specimen_id") == specimen_id]
    if not rows:
        return None
    rows.sort(key=lambda o: (o.get("created_at") or "", o["id"]))
    return rows[0]


def _find_entry_by_code(code):
    if code is None:
        return None
    for entry in all_rows("test_catalog_entries"):
        if entry.get("test_code") == code:
            return entry
    return None