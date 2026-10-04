"""Composite setup helpers for multi-step test prerequisites.

The test harness restarts the API server before every individual pytest test, so
each test starts against an empty database. Every helper here therefore builds
its preconditions from scratch using only PRD-declared endpoints, and uses
``get_success_data()`` (the lenient validator) internally so a broken setup
raises a plain "Setup step failed" rather than a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .api_errors import ApiErrorId
from .constants import INITIAL_LOGICAL_CLOCK, TEST_DEFAULTS
from .factories import (
    create_audit_event_payload,
    create_bank_account_payload,
    create_calendar_cell_payload,
    create_counterparty_payload,
    create_ledger_payload,
    create_legal_entity_payload,
    create_manual_transaction_payload,
    create_payment_order_payload,
    create_relationship_payload,
    create_statement_line_payload,
    create_statement_payload,
    create_virtual_account_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
CONTROLLER = TEST_USERS["ledger_controller_headers"]
INITIATOR = TEST_USERS["payment_initiator_headers"]
APPROVER = TEST_USERS["payment_approver_headers"]
ANALYST = TEST_USERS["payment_ops_analyst_headers"]
OPS_APPROVER = TEST_USERS["payment_ops_approver_headers"]
AUDITOR = TEST_USERS["auditor_headers"]

# Aliases for readability at call sites in the test suite.
ADMIN_HEADERS = ADMIN
CONTROLLER_HEADERS = CONTROLLER
INITIATOR_HEADERS = INITIATOR
APPROVER_HEADERS = APPROVER
ANALYST_HEADERS = ANALYST
AUDITOR_HEADERS = AUDITOR

# Default rail cutoff times by rail (local time on the calendar cell).
RAIL_CUTOFF_LOCAL_TIMES = {
    "ACH": "14:00:00",
    "WIRE": "15:00:00",
    "RTP": "16:00:00",
    "CHECK": "11:00:00",
}

# The calendar window used by most scenarios: four open weekdays at the start of
# September 2026, the weekend closed, then open weekdays through the 18th.
DEFAULT_OPEN_DATES = [
    "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04",
    "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11",
    "2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18",
]
DEFAULT_CLOSED_DATES = ["2026-09-05", "2026-09-06", "2026-09-07"]


# ─── Logical clock ────────────────────────────────────

def set_clock(to_iso8601: str = INITIAL_LOGICAL_CLOCK):
    """Pin the injected logical clock.

    Every temporal rule reads this value rather than the host clock. If the
    server already sits at or ahead of the requested instant the API reports
    ERR_CLOCK_NOT_MONOTONIC, which is a no-op for setup purposes.
    """
    res = api_client.set_current_utc(to_iso8601, ADMIN)
    if 200 <= res.status_code < 300:
        return get_success_data(res)
    body = res.json() if res.text else {}
    if body.get("data", {}).get("error_id") == ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value:
        return None
    raise AssertionError(
        f"Setup failed: could not set the logical clock to {to_iso8601}: "
        f"HTTP {res.status_code} {res.text}"
    )


# ─── Tier 1: individual entity creation ───────────────

def create_ledger(name=None, currency="USD", **overrides):
    payload = create_ledger_payload(**{"name": name or TEST_DEFAULTS["LEDGER_NAME"],
                                       "currency": currency, **overrides})
    return get_success_data(api_client.create_ledger(payload, ADMIN))


def create_institution(home_ledger_id, legal_name=None, short_code=None, **overrides):
    payload = create_legal_entity_payload(
        home_ledger_id=home_ledger_id,
        **{**({"legal_name": legal_name} if legal_name else {}),
           **({"short_code": short_code} if short_code else {}),
           **overrides},
    )
    return get_success_data(api_client.create_legal_entity(payload, ADMIN))


def create_counterparty(legal_entity_id, **overrides):
    payload = create_counterparty_payload(legal_entity_id, **overrides)
    return get_success_data(api_client.create_counterparty(payload, INITIATOR))


def create_bank_account(legal_entity_id, **overrides):
    payload = create_bank_account_payload(legal_entity_id, **overrides)
    return get_success_data(api_client.create_bank_account(payload, CONTROLLER))


def create_relationship(legal_entity_id, partner_legal_entity_id, **overrides):
    payload = create_relationship_payload(legal_entity_id, partner_legal_entity_id, **overrides)
    return get_success_data(api_client.create_relationship(payload, APPROVER))


def create_virtual_account(bank_account_id, **overrides):
    payload = create_virtual_account_payload(bank_account_id, **overrides)
    return get_success_data(api_client.create_virtual_account(payload, ANALYST))


def create_manual_entry(ledger_id, **overrides):
    payload = create_manual_transaction_payload(**overrides)
    return get_success_data(api_client.book_transaction(ledger_id, payload, ANALYST))


def post_entry(transaction_id, headers=None):
    return get_success_data(api_client.post_transaction(transaction_id, headers or ANALYST))


def mark_entry_settled(transaction_id, headers=None):
    return get_success_data(
        api_client.mark_transaction_settled(transaction_id, headers or ANALYST))


def void_entry(transaction_id, expected_ledger_version, headers=None):
    return get_success_data(api_client.void_transaction(
        transaction_id, {"expected_ledger_version": expected_ledger_version},
        headers or CONTROLLER))


def ledger_version(ledger_id):
    return get_success_data(api_client.get_ledger(ledger_id, CONTROLLER))["version"]


# ─── Banking calendar ─────────────────────────────────

def publish_calendar_cell(legal_entity_id, calendar_date, **overrides):
    payload = create_calendar_cell_payload(legal_entity_id, calendar_date, **overrides)
    return get_success_data(api_client.publish_calendar_cell(payload, CONTROLLER))


def publish_calendar(legal_entity_id, rails=("ACH", "WIRE", "RTP"),
                     open_dates=None, closed_dates=None, timezone=None):
    """Publish a full working calendar for one institution.

    Open cells name the given rails in both ``cutoffs`` and ``allowed_rails``
    (which must be a non-empty subset of the rails named in ``cutoffs``).
    Closed cells carry the same valid rail configuration but ``is_open: false``,
    which outranks the weekday rule used by the business-day aging calculation.
    """
    rails = list(rails)
    open_dates = DEFAULT_OPEN_DATES if open_dates is None else open_dates
    closed_dates = DEFAULT_CLOSED_DATES if closed_dates is None else closed_dates
    cells = []
    for date in open_dates:
        cells.append(publish_calendar_cell(
            legal_entity_id, date,
            is_open=True,
            cutoffs=[{"rail": r, "cutoff_local_time": RAIL_CUTOFF_LOCAL_TIMES[r]}
                     for r in rails],
            allowed_rails=list(rails),
            **({"timezone": timezone} if timezone else {}),
        ))
    for date in closed_dates:
        cells.append(publish_calendar_cell(
            legal_entity_id, date,
            is_open=False,
            cutoffs=[{"rail": r, "cutoff_local_time": RAIL_CUTOFF_LOCAL_TIMES[r]}
                     for r in rails],
            allowed_rails=list(rails),
            **({"timezone": timezone} if timezone else {}),
        ))
    return cells


# ─── Tier 1/2: scenario building blocks ───────────────

def ledger_scenario(currency="USD", ledger_name=None, entity_name=None,
                    short_code=None, calendar_rails=("ACH", "WIRE", "RTP"),
                    account_overrides=None, counterparty_overrides=None,
                    entity_overrides=None, publish_calendar_cells=True,
                    skip_counterparty=False, skip_account=False,
                    with_partner=False):
    """Ledger + institution + counterparty + bank account, with a working calendar.

    Returns a dict with keys: ledger, ledger_v, entity, entity2 (only when
    ``with_partner``), counterparty, account, account_v (all entity dicts).
    """
    ledger = create_ledger(name=ledger_name, currency=currency)
    entity = create_institution(
        ledger["id"],
        **{**({"legal_name": entity_name} if entity_name else {}),
           **({"short_code": short_code} if short_code else {}),
           **(entity_overrides or {})},
    )
    if publish_calendar_cells:
        publish_calendar(entity["id"], rails=calendar_rails)

    counterparty = None
    if not skip_counterparty:
        counterparty = create_counterparty(entity["id"], **(counterparty_overrides or {}))

    account = None
    if not skip_account:
        acct_over = {"supported_rails": list(calendar_rails)}
        acct_over.update(account_overrides or {})
        account = create_bank_account(entity["id"], **acct_over)

    entity2 = None
    if with_partner:
        entity2 = create_institution(ledger["id"])

    return {
        "ledger": ledger,
        "ledger_v": ledger["version"],
        "entity": entity,
        "entity2": entity2,
        "counterparty": counterparty,
        "account": account,
        "account_v": account["version"] if account else None,
    }


def create_order(scenario, rail="ACH", direction="CREDIT", amount_cents=500_000,
                 idempotency_key=None, **overrides):
    payload = create_payment_order_payload(
        scenario["entity"]["id"],
        scenario["ledger"]["id"],
        scenario["counterparty"]["id"],
        scenario["account"]["id"],
        rail=rail, direction=direction, amount_cents=amount_cents,
        **({"idempotency_key": idempotency_key} if idempotency_key else {}),
        **overrides,
    )
    return get_success_data(api_client.create_payment_order(payload, INITIATOR))


def approve_order(order, headers=None, expected_version=None):
    version = order["version"] if expected_version is None else expected_version
    return get_success_data(api_client.approve_payment_order(
        order["id"], {"expected_payment_order_version": version}, headers or APPROVER))


def _fresh_version(order, headers):
    """Re-read an order's current version before an OCC-guarded call.

    PRD §2.7 makes `expected_payment_order_version` a mandatory OCC field on
    approve/dispatch/return/reverse, and every one of those transitions advances
    the order's `version`.  A helper that carries a captured response dict
    forward without re-reading it therefore sends a version it has already
    consumed — a fixture bug, since the PRD-faithful server must reject it with
    ERR_STALE_VERSION.
    """
    refreshed = get_success_data(api_client.get_payment_order(order["id"], headers))
    return refreshed["version"]


def _version_of(handle, headers):
    """The current version of an order given either its response or its id."""
    if isinstance(handle, dict):
        return _fresh_version(handle, headers)
    refreshed = get_success_data(api_client.get_payment_order(handle, headers))
    return refreshed["version"]


def dispatch_order(order, headers=None, expected_version=None):
    if expected_version is None:
        expected_version = _version_of(order, headers or APPROVER)
    order_id = order["id"] if isinstance(order, dict) else order
    return get_success_data(api_client.dispatch_payment_order(
        order_id, {"expected_payment_order_version": expected_version},
        headers or APPROVER))


def mark_in_flight(order, headers=None):
    order_id = order["id"] if isinstance(order, dict) else order
    return get_success_data(
        api_client.mark_payment_order_in_flight(order_id, headers or ANALYST))


def settle_order(order, headers=None):
    order_id = order["id"] if isinstance(order, dict) else order
    return get_success_data(api_client.settle_payment_order(order_id, headers or ANALYST))


def return_order(order, return_reason="R01", headers=None, expected_version=None):
    if expected_version is None:
        expected_version = _version_of(order, headers or ANALYST)
    order_id = order["id"] if isinstance(order, dict) else order
    return get_success_data(api_client.return_payment_order(
        order_id, {"return_reason": return_reason,
                   "expected_payment_order_version": expected_version},
        headers or ANALYST))


def reverse_order(order, headers=None):
    order_id = order["id"] if isinstance(order, dict) else order
    return get_success_data(api_client.reverse_payment_order(
        order_id, {"expected_payment_order_version": _version_of(order, headers or ANALYST)},
        headers or ANALYST))


def fail_order(order, failure_reason="network failure", headers=None):
    return get_success_data(api_client.fail_payment_order(
        order["id"], {"failure_reason": failure_reason}, headers or ANALYST))


def approved_order_scenario(rail="ACH", direction="CREDIT", amount_cents=500_000,
                            settlement_speed=None, **scenario_overrides):
    """Ledger scenario + an APPROVED order on the given rail."""
    scenario = ledger_scenario(**scenario_overrides)
    overrides = {}
    if settlement_speed is not None:
        overrides["settlement_speed"] = settlement_speed
    order = create_order(scenario, rail=rail, direction=direction,
                         amount_cents=amount_cents, **overrides)
    approved = approve_order(order)
    scenario.update({"order": approved})
    return scenario


def dispatched_order_scenario(rail="ACH", direction="CREDIT", amount_cents=500_000,
                              settlement_speed=None, **scenario_overrides):
    """Ledger scenario + an order approved and dispatched onto its rail."""
    scenario = approved_order_scenario(
        rail=rail, direction=direction, amount_cents=amount_cents,
        settlement_speed=settlement_speed, **scenario_overrides)
    dispatched = dispatch_order(scenario["order"])
    scenario["order"] = dispatched
    return scenario


def returned_order_scenario(rail="ACH", direction="CREDIT", amount_cents=500_000,
                            return_reason="R01", **scenario_overrides):
    """Ledger scenario + an order walked through to RETURNED."""
    scenario = approved_order_scenario(
        rail=rail, direction=direction, amount_cents=amount_cents,
        **scenario_overrides)
    dispatch_order(scenario["order"])
    in_flight = mark_in_flight(scenario["order"])
    returned = return_order(in_flight, return_reason=return_reason)
    scenario["order"] = returned
    return scenario


def settled_order_scenario(rail="ACH", direction="CREDIT", amount_cents=500_000,
                           **scenario_overrides):
    scenario = approved_order_scenario(
        rail=rail, direction=direction, amount_cents=amount_cents,
        **scenario_overrides)
    dispatch_order(scenario["order"])
    in_flight = mark_in_flight(scenario["order"])
    settled = settle_order(in_flight)
    scenario["order"] = settled
    return scenario


# ─── Statements ───────────────────────────────────────

def import_statement(scenario, institution_ref=None, cycle_date=None,
                     expected_account_version=None, **overrides):
    """Import a statement and return the raw response.

    The raw `requests.Response` is returned rather than the unwrapped payload
    because the OCC path under test is a rejection path: the caller needs to
    interrogate the status code of an ERR_STALE_VERSION (PRD §2.7 / §3.7) just
    as much as the payload of a successful 201.
    """
    payload = create_statement_payload(
        scenario["account"]["id"],
        expected_account_version if expected_account_version is not None
        else scenario["account_v"],
        **{**({"institution_ref": institution_ref} if institution_ref else {}),
           **({"cycle_date": cycle_date} if cycle_date else {}),
           **overrides},
    )
    return api_client.import_statement(payload, ANALYST)


def append_line(statement, **overrides):
    payload = create_statement_line_payload(**overrides)
    return get_success_data(
        api_client.append_statement_line(statement["id"], payload, ANALYST))


def reconcile(statement, expected_version=None):
    version = statement["version"] if expected_version is None else expected_version
    return get_success_data(api_client.reconcile_statement(
        statement["id"], {"expected_statement_version": version}, ANALYST))


def statement_scenario(institution_ref="STMT-A", cycle_date="2026-09-01T23:59:59Z",
                       matching_algorithm="POSTED_NET", lines=None, **scenario_overrides):
    """Ledger scenario + an IMPORTED statement, optionally with lines appended."""
    scenario = ledger_scenario(**scenario_overrides)
    statement = get_success_data(
        import_statement(scenario, institution_ref=institution_ref,
                         cycle_date=cycle_date,
                         matching_algorithm=matching_algorithm),
        expected_status=201)
    for line in (lines or []):
        append_line(statement, **line)
    scenario["statement"] = statement
    return scenario


def statement_discrepancy_scenario(amount_cents=750_000, institution_ref="STMT-C",
                                   line_ref="STMT-C-L0", **scenario_overrides):
    """A statement revision 1 with one unmatched line, reconciled to DISCREPANCY."""
    scenario = statement_scenario(
        institution_ref=institution_ref,
        lines=[{"bank_reference": line_ref, "amount_cents": amount_cents,
                "direction": "CREDIT", "effective_at": "2026-09-01T10:00:00Z"}],
        **scenario_overrides)
    scenario["statement"] = reconcile(scenario["statement"])
    return scenario


def revise_statement(statement, institution_ref="STMT-REV",
                     cycle_date="2026-09-01T23:59:59Z",
                     opening_balance_cents=0, closing_balance_cents=0,
                     expected_version=None):
    version = statement["version"] if expected_version is None else expected_version
    return get_success_data(api_client.revise_statement(
        statement["id"],
        {"expected_statement_version": version,
         "institution_ref": institution_ref,
         "cycle_date": cycle_date,
         "opening_balance_cents": opening_balance_cents,
         "closing_balance_cents": closing_balance_cents},
        ANALYST))


def unmatched_deposit_scenario(amount_cents=250_000, reference_code=None,
                               virtual_accounts=None, institution_ref="STMT-B",
                               line_ref="BR-B1", effective_at="2026-09-01T10:00:00Z",
                               **scenario_overrides):
    """A statement whose single line resolves to no destination.

    ``virtual_accounts`` is an optional list of override dicts; each entry is
    passed to ``create_virtual_account``. When omitted, the pooled account has no
    virtual account at all, so both the reference branch and the sole-open
    fallback fail and the line raises an UNMATCHED_DEPOSIT exception.
    """
    scenario = statement_scenario(
        institution_ref=institution_ref,
        lines=[{"bank_reference": line_ref, "amount_cents": amount_cents,
                "direction": "CREDIT", "effective_at": effective_at,
                **({"embedded_reference_code": reference_code} if reference_code else {})}],
        **scenario_overrides)
    for va in (virtual_accounts or []):
        create_virtual_account(scenario["account"]["id"], **va)
    scenario["statement"] = reconcile(scenario["statement"])
    return scenario


# ─── Exception queue helpers ──────────────────────────

def list_transactions(ledger_id, **filters):
    params = {"ledger_id": ledger_id}
    params.update({k: v for k, v in filters.items() if v is not None})
    data = get_success_data(api_client.list_transactions(CONTROLLER, params=params))
    return data if isinstance(data, list) else []


def list_exceptions(ledger_id, **filters):
    params = {"ledger_id": ledger_id}
    params.update({k: v for k, v in filters.items() if v is not None})
    data = get_success_data(api_client.list_exceptions(ANALYST, params=params))
    return data if isinstance(data, list) else []


def list_payment_orders(ledger_id, headers=None, **filters):
    params = {"ledger_id": ledger_id}
    params.update({k: v for k, v in filters.items() if v is not None})
    data = get_success_data(api_client.list_payment_orders(
        headers or APPROVER, params=params))
    return data if isinstance(data, list) else []


def list_counterparties(legal_entity_id, headers=None, **filters):
    params = {"legal_entity_id": legal_entity_id}
    params.update({k: v for k, v in filters.items() if v is not None})
    data = get_success_data(api_client.list_counterparties(
        headers or APPROVER, params=params))
    return data if isinstance(data, list) else []


def first_exception(ledger_id, **filters):
    rows = list_exceptions(ledger_id, **filters)
    assert rows, f"Setup failed: expected at least one exception on ledger {ledger_id}"
    return rows[0]


def assign_exception(exception_id, assignee_user_id=None, headers=None):
    """Assign an exception to an operator.

    PRD §3.8: "the payload's `assignee_user_id` names the operator and the acting
    user owns the work", and resolution is gated on that ownership just below
    ("only when its `assignee_user_id` is set and matches the caller's
    `X-User-ID`").  The default therefore assigns to the acting analyst's own
    identity, so the assignment/resolution pair is internally consistent; a
    literal placeholder that matches no caller would make every subsequent
    resolve fail the ownership test.
    """
    headers = headers or ANALYST
    if assignee_user_id is None:
        assignee_user_id = headers["X-User-ID"]
    return get_success_data(api_client.assign_exception(
        exception_id, {"assignee_user_id": assignee_user_id}, headers))


def reevaluate_exception(exception_id, headers=None):
    return get_success_data(
        api_client.reevaluate_exception_aging(exception_id, headers or ANALYST))


def resolve_exception(exception_id, resolution_note="resolved by operations", headers=None):
    """Resolve an assigned exception.

    PRD §3.8 gates resolution on the item having aged: "may resolve an item only
    when its status is `ASSIGNED`, only when its `assignee_user_id` is set and
    matches the caller's `X-User-ID`, and only once its `age_business_days` is at
    least 1".  At the logical clock's startup default a freshly raised item is
    CURRENT with zero elapsed business days, so the clock is advanced to the next
    business day first — otherwise every resolution would be refused for an age
    the scenario never intended to be in play.  A caller that has already moved
    the clock further is unaffected, because ERR_CLOCK_NOT_MONOTONIC is treated
    as a no-op by set_clock.
    """
    headers = headers or ANALYST
    set_clock("2026-09-02T00:00:00Z")
    return get_success_data(api_client.resolve_exception(
        exception_id, {"resolution_note": resolution_note}, headers))


def close_period(ledger_id, force_resolve=False, expected_version=None, headers=None):
    version = ledger_version(ledger_id) if expected_version is None else expected_version
    return get_success_data(api_client.close_period(
        ledger_id,
        {"expected_ledger_version": version, "force_resolve_exceptions": force_resolve},
        headers or CONTROLLER))


def recompute_ledger(ledger_id, expected_version=None, headers=None):
    version = ledger_version(ledger_id) if expected_version is None else expected_version
    return get_success_data(api_client.recompute_ledger(
        ledger_id, {"expected_ledger_version": version}, headers or CONTROLLER))


def create_order_for(scenario, counterparty, rail="ACH", direction="CREDIT",
                     amount_cents=500_000, **overrides):
    """Create an order addressed to a specific counterparty."""
    payload = create_payment_order_payload(
        scenario["entity"]["id"], scenario["ledger"]["id"], counterparty["id"],
        scenario["account"]["id"], rail=rail, direction=direction,
        amount_cents=amount_cents, **overrides)
    return get_success_data(api_client.create_payment_order(payload, INITIATOR))


def refresh_account(scenario):
    """Re-read the scenario's bank account and refresh the captured version."""
    account = get_success_data(api_client.get_bank_account(scenario["account"]["id"], CONTROLLER))
    scenario["account"] = account
    scenario["account_v"] = account["version"]
    return account


def return_exception_scenario(amount_cents=50_000, return_reason="R01",
                              open_clock=INITIAL_LOGICAL_CLOCK, **scenario_overrides):
    """Ledger scenario + a RETURNED order, returning (scenario, exception)."""
    scenario = returned_order_scenario(
        rail=scenario_overrides.pop("rail", "ACH"),
        amount_cents=amount_cents, return_reason=return_reason,
        **scenario_overrides)
    scenario["exception"] = first_exception(scenario["ledger"]["id"], kind="RETURN")
    return scenario


def build_two_active_return_legs(**scenario_overrides):
    """Two RETURNED orders, so the reverse-rail fee pool stands at 50 cents."""
    scenario = ledger_scenario(**scenario_overrides)
    orders = []
    for amount, reason in ((1_500, "R01"), (2_500, "R02")):
        order = create_order(scenario, rail="ACH", direction="CREDIT", amount_cents=amount)
        approve_order(order)
        dispatch_order(order)
        in_flight = mark_in_flight(order)
        orders.append(return_order(in_flight, return_reason=reason,
                                   expected_version=in_flight["version"]))
    scenario["orders"] = orders
    scenario["exceptions"] = list_exceptions(scenario["ledger"]["id"], kind="RETURN")
    return scenario


def build_three_active_return_legs(rails=("ACH", "ACH", "RTP"),
                                   amounts=(1_500, 2_500, 3_500),
                                   reasons=("R01", "R02", "R03"),
                                   **scenario_overrides):
    """Three RETURNED orders, so the reverse-rail fee pool stands at 75 cents.

    The three legs are created in order, which is the order the allocation
    primitive cycles the remainder in.
    """
    scenario = ledger_scenario(**scenario_overrides)
    orders = []
    for rail, amount, reason in zip(rails, amounts, reasons):
        order = create_order(scenario, rail=rail, direction="CREDIT", amount_cents=amount)
        approve_order(order)
        dispatch_order(order)
        in_flight = mark_in_flight(order)
        orders.append(return_order(in_flight, return_reason=reason,
                                   expected_version=in_flight["version"]))
    scenario["orders"] = orders
    scenario["exceptions"] = list_exceptions(scenario["ledger"]["id"], kind="RETURN")
    return scenario


# ─── Pool / membership helpers ────────────────────────

def create_settlement_pool(ledger_id, member_ids, **overrides):
    payload = {
        "ledger_id": ledger_id,
        "name": overrides.pop("name", "Ops Pool"),
        "member_bank_account_ids": list(member_ids),
        **overrides,
    }
    return get_success_data(api_client.create_settlement_pool(payload, CONTROLLER))


def refresh_pool(pool_id):
    return get_success_data(api_client.refresh_settlement_pool(pool_id, ANALYST))


def ledger_summary(ledger_id, settled=None, headers=None):
    params = {}
    if settled is not None:
        params["settled"] = "true" if settled else "false"
    return get_success_data(api_client.ledger_summary(
        ledger_id, {"settled": bool(settled)} if settled is not None else {},
        headers or CONTROLLER, params=params))


def append_audit_event(ledger_id, **overrides):
    payload = create_audit_event_payload(ledger_id, **overrides)
    return get_success_data(api_client.append_audit_event(payload, ANALYST))


# ─── Allocation primitive ─────────────────────────────

def allocate_shares(total: int, weights):
    """The pinned floor-then-cycle allocation of ``total`` over ordered buckets.

    Each bucket's share is ``total * weight // weight_sum``; the leftover cents
    are then distributed one at a time, cycling through the buckets in order
    until the remainder is exhausted. This is the spec's primitive, expressed in
    the test suite so the expected split can be stated without recomputing it by
    hand.
    """
    weights = list(weights)
    weight_sum = sum(weights)
    shares = [(total * w) // weight_sum for w in weights]
    remainder = total - sum(shares)
    i = 0
    while remainder > 0:
        shares[i % len(shares)] += 1
        remainder -= 1
        i += 1
    return shares


def fee_total_cents(rail: str, direction: str, amount_cents: int,
                    settlement_speed: str = "STANDARD") -> int:
    """The rail fee schedule of PRD §3.3, applied in the declared order."""
    if rail == "ACH":
        base = 500 if settlement_speed == "SAME_DAY" else 25
    elif rail == "RTP":
        base = 75 + (amount_cents // 1_000_000) * 100
    elif rail == "WIRE":
        base = 500 + (amount_cents // 1_000_000) * 250
    elif rail == "CHECK":
        base = 350 if direction == "DEBIT" else 150
    else:
        raise ValueError(f"unknown rail {rail}")

    if direction == "CREDIT" and rail in ("ACH", "RTP"):
        base -= 25

    caps = {"ACH": 400, "WIRE": 2500, "RTP": 250}
    if rail in caps:
        base = min(base, caps[rail])

    return max(base, 10)