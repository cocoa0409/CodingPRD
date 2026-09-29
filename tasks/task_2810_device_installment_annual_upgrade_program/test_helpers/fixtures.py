"""Composite setup helpers.

Every test starts against an empty database whose logical clock reads exactly
2026-08-01T00:00:00Z, so every helper here builds its preconditions from scratch
using only the endpoints the PRD declares. Setup calls go through the lenient
``get_success_data`` validator so a broken precondition surfaces as a setup
failure rather than as a confusing assertion inside the test body.

A `Customer` is entity_backed: after enrolling one, every ownership-gated call in
these chains uses ``make_customer_headers(customer["id"])``. The other five roles
carry opaque operator identifiers.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_ORIGIN, DEFAULT_MIN_DPD, DEFAULT_TERM_MONTHS, DELINQUENT_MIN_DPD,
    FULFILLMENT_WINDOW_DAYS, GRACE_PERIOD_DAYS, UNLOCK_MIN_PAID_INSTALLMENTS,
    UPGRADE_MIN_LOAN_AGE_DAYS, at_midnight, plus_days, plus_months,
)
from .factories import (
    activation_payload, cancellation_payload, clock_payload, completion_payload,
    create_carrier_account_payload, create_credit_application_payload,
    create_customer_payload, create_device_model_payload, create_loan_payload,
    create_target_model_payload, decision_payload, diagnostic_report_payload,
    dispute_payload, next_imei, payment_payload, payoff_quote_payload, regrade_payload,
    reversal_payload, trade_in_declaration_payload, upgrade_request_payload,
)
from .test_users import (
    ADMIN_USER_ID, ASSOCIATE_USER_ID, COLLECTIONS_USER_ID, TECHNICIAN_USER_ID,
    UNDERWRITER_USER_ID, make_admin_headers, make_associate_headers,
    make_collections_headers, make_customer_headers, make_technician_headers,
    make_underwriter_headers,
)


# =========================================================================
# Tier 0 — one-call wrappers around each endpoint used in a setup chain
# =========================================================================
def set_clock(to_iso8601: str, admin_user_id: str = ADMIN_USER_ID) -> Dict[str, Any]:
    """Move the logical clock forward. Returns the endpoint's `current_utc` payload."""
    return get_success_data(api_client.set_clock(
        clock_payload(to_iso8601), make_admin_headers(admin_user_id)))


def reset_clock_to_origin() -> Dict[str, Any]:
    """Re-state the startup default 2026-08-01T00:00:00Z (a no-op forward move)."""
    return set_clock(CLOCK_ORIGIN)


def publish_model(**overrides) -> Dict[str, Any]:
    """Publish the financed catalog model (Handset B by default)."""
    return get_success_data(api_client.create_device_model(
        create_device_model_payload(**overrides), make_admin_headers()))


def publish_target_model(**overrides) -> Dict[str, Any]:
    """Publish the upgrade-target catalog model (Handset A by default)."""
    return get_success_data(api_client.create_device_model(
        create_target_model_payload(**overrides), make_admin_headers()))


def enroll_customer(**overrides) -> Dict[str, Any]:
    """Enrol a program participant. Opens ACTIVE with a zero credit limit."""
    return get_success_data(api_client.create_customer(
        create_customer_payload(**overrides), make_associate_headers()))


def register_carrier_account(customer_id: str, **overrides) -> Dict[str, Any]:
    """Register a carrier account against the owning customer."""
    return get_success_data(api_client.create_carrier_account(
        customer_id, create_carrier_account_payload(**overrides), make_associate_headers()))


def submit_application(customer_id: str, device_model_id: str, **overrides) -> Dict[str, Any]:
    """Submit a point-of-sale credit application."""
    return get_success_data(api_client.create_credit_application(
        create_credit_application_payload(customer_id, device_model_id, **overrides),
        make_associate_headers()))


def decide_application(application_id: str, credit_score_band: str = "PRIME",
                       underwriter_user_id: str = UNDERWRITER_USER_ID) -> Dict[str, Any]:
    """File the underwriting decision. The band is the only writable input."""
    return get_success_data(api_client.decide_credit_application(
        application_id, decision_payload(credit_score_band),
        make_underwriter_headers(underwriter_user_id)))


def originate_loan(application_id: str, down_payment_cents: int = 0,
                   imei: Optional[str] = None,
                   associate_user_id: str = ASSOCIATE_USER_ID) -> Dict[str, Any]:
    """Originate the loan, its full schedule and its handset in one call. The
    acting associate must differ from the application's underwriter_user_id."""
    return get_success_data(api_client.create_loan(
        create_loan_payload(application_id, imei=imei,
                            down_payment_cents=int(down_payment_cents)),
        make_associate_headers(associate_user_id)))


def read_loan(loan_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Read one loan — the canonical way to obtain its current `version`."""
    return get_success_data(api_client.get_loan(
        loan_id, headers or make_associate_headers()))


def read_customer(customer_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_customer(
        customer_id, headers or make_associate_headers()))


def read_device_model(model_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_device_model(
        model_id, headers or make_admin_headers()))


def read_device_unit(device_unit_id: str,
                     headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_device_unit(
        device_unit_id, headers or make_associate_headers()))


def read_carrier_accounts(customer_id: str,
                          headers: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    return get_success_data(api_client.list_carrier_accounts(
        customer_id, headers or make_associate_headers()))


def read_upgrade_request(upgrade_request_id: str,
                         headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_upgrade_request(
        upgrade_request_id, headers or make_associate_headers()))


def read_trade_in(trade_in_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_trade_in(
        trade_in_id, headers or make_associate_headers()))


def read_diagnostic_reports(trade_in_id: str,
                            headers: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    return get_success_data(api_client.list_diagnostic_reports(
        trade_in_id, headers or make_technician_headers()))


def read_installments(loan_id: str, headers: Optional[Dict[str, str]] = None,
                      params: Optional[Dict] = None) -> List[Dict[str, Any]]:
    """One loan's installment ladder, ordered by installment_number ascending."""
    query = {"limit": 100}
    if params:
        query.update(params)
    rows = get_success_data(api_client.list_installments(
        loan_id, headers or make_associate_headers(), params=query))
    return sorted(rows, key=lambda row: row["installment_number"])


def read_installment(loan_id: str, installment_number: int,
                     headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    for row in read_installments(loan_id, headers):
        if row["installment_number"] == installment_number:
            return row
    raise AssertionError(
        f"Setup failed: loan {loan_id} has no installment {installment_number}")


def read_delinquency_events(loan_id: str, headers: Optional[Dict[str, str]] = None,
                            params: Optional[Dict] = None) -> List[Dict[str, Any]]:
    query = {"limit": 100}
    if params:
        query.update(params)
    return get_success_data(api_client.list_delinquency_events(
        loan_id, headers or make_collections_headers(), params=query))


def read_payoff_quotes(loan_id: str, headers: Optional[Dict[str, str]] = None,
                       params: Optional[Dict] = None) -> List[Dict[str, Any]]:
    query = {"limit": 100}
    if params:
        query.update(params)
    return get_success_data(api_client.list_loan_payoff_quotes(
        loan_id, headers or make_associate_headers(), params=query))


def read_payoff_quote(loan_id: str, payoff_quote_id: str,
                      headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Re-read one quote through its loan's quote sub-collection."""
    for quote in read_payoff_quotes(loan_id, headers):
        if quote["id"] == payoff_quote_id:
            return quote
    raise AssertionError(
        f"Setup failed: loan {loan_id} has no payoff quote {payoff_quote_id}")


def loan_device_unit(loan_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """The handset origination minted for this loan."""
    rows = get_success_data(api_client.list_device_units(
        headers or make_associate_headers(), params={"loan_id": loan_id}))
    assert rows, f"Setup failed: no handset was minted for loan {loan_id}"
    return rows[0]


def activate_device(device_unit_id: str, carrier_account_id: str,
                    headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Put the handset on a network. Performed by an associate or a technician."""
    return get_success_data(api_client.activate_device_unit(
        device_unit_id, activation_payload(carrier_account_id),
        headers or make_associate_headers()))


def post_payment(loan_id: str, amount_cents: int, customer_id: Optional[str] = None,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Post an ordinary PAYMENT and run the allocation waterfall."""
    if headers is None:
        headers = (make_customer_headers(customer_id) if customer_id
                   else make_collections_headers())
    return get_success_data(api_client.create_payment(
        loan_id, payment_payload(int(amount_cents)), headers))


def post_reversal(loan_id: str, amount_cents: int, reverses_posting_id: str,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Post a REVERSAL undoing an earlier posting, cent for cent."""
    return get_success_data(api_client.create_payment(
        loan_id, reversal_payload(int(amount_cents), reverses_posting_id),
        headers or make_collections_headers()))


def price_quote(loan_id: str, quote_type: str = "EARLY_CANCELLATION",
                customer_id: Optional[str] = None,
                headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Price and issue a payoff quote of one of the two flavours."""
    if headers is None:
        headers = (make_customer_headers(customer_id) if customer_id
                   else make_associate_headers())
    return get_success_data(api_client.create_payoff_quote(
        loan_id, payoff_quote_payload(quote_type), headers))


def cancel_loan(loan_id: str, payoff_quote_id: str, payment_amount_cents: int,
                customer_id: Optional[str] = None,
                headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Settle an EARLY_CANCELLATION quote in full and close the loan."""
    if headers is None:
        headers = (make_customer_headers(customer_id) if customer_id
                   else make_associate_headers())
    return get_success_data(api_client.cancel_loan(
        loan_id, cancellation_payload(payoff_quote_id, int(payment_amount_cents)), headers))


def run_sweep(headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Run the daily servicing sweep at the current logical clock."""
    return get_success_data(api_client.run_daily_servicing(
        headers or make_collections_headers()))


def open_upgrade_request(loan_id: str, target_device_model_id: str,
                         fulfillment_window_start: str, customer_id: Optional[str] = None,
                         expected_loan_version: Optional[int] = None,
                         headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Open an upgrade request. When `expected_loan_version` is omitted the loan is
    re-read first, so the OCC guard sees the caller's freshest observation."""
    if headers is None:
        headers = (make_customer_headers(customer_id) if customer_id
                   else make_associate_headers())
    if expected_loan_version is None:
        expected_loan_version = read_loan(loan_id, make_associate_headers())["version"]
    return get_success_data(api_client.create_upgrade_request(
        upgrade_request_payload(loan_id, target_device_model_id, fulfillment_window_start,
                                int(expected_loan_version)),
        headers))


def declare_trade_in(upgrade_request_id: str, device_unit_id: str,
                     declared_condition: str = "GOOD", customer_id: Optional[str] = None,
                     headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Declare the handset coming back, with the customer's self-assessed condition."""
    if headers is None:
        headers = (make_customer_headers(customer_id) if customer_id
                   else make_associate_headers())
    return get_success_data(api_client.declare_trade_in(
        upgrade_request_id, trade_in_declaration_payload(device_unit_id, declared_condition),
        headers))


def receive_trade_in(trade_in_id: str,
                     technician_user_id: str = TECHNICIAN_USER_ID) -> Dict[str, Any]:
    """Record physical receipt at the store (exclusive to a ServiceTechnician)."""
    return get_success_data(api_client.receive_trade_in(
        trade_in_id, make_technician_headers(technician_user_id)))


def grade_trade_in(trade_in_id: str, technician_user_id: str = TECHNICIAN_USER_ID,
                   **measurements) -> Dict[str, Any]:
    """File the initial bench diagnostic. Returns the DiagnosticReport."""
    return get_success_data(api_client.create_diagnostic_report(
        trade_in_id, diagnostic_report_payload(**measurements),
        make_technician_headers(technician_user_id)))


def dispute_trade_in(trade_in_id: str, customer_id: Optional[str] = None,
                     dispute_reason: str = "Screen was intact at hand-over",
                     headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Dispute the grading, moving the trade-in GRADED -> DISPUTED."""
    if headers is None:
        headers = (make_customer_headers(customer_id) if customer_id
                   else make_associate_headers())
    return get_success_data(api_client.dispute_trade_in(
        trade_in_id, dispute_payload(dispute_reason), headers))


def regrade_trade_in(trade_in_id: str, technician_user_id: str = "u-tech-2",
                     **measurements) -> Dict[str, Any]:
    """File an overriding regrade. The actor must differ from the technician who
    filed the newest report."""
    return get_success_data(api_client.regrade_trade_in(
        trade_in_id, regrade_payload(**measurements),
        make_technician_headers(technician_user_id)))


def complete_upgrade(upgrade_request_id: str, payoff_quote_id: str,
                     target_imei: Optional[str] = None,
                     additional_down_payment_cents: Optional[int] = None,
                     associate_user_id: str = ASSOCIATE_USER_ID) -> Dict[str, Any]:
    """Complete the upgrade. Returns the newly minted successor loan."""
    extra = {}
    if additional_down_payment_cents is not None:
        extra["additional_down_payment_cents"] = int(additional_down_payment_cents)
    return get_success_data(api_client.complete_upgrade(
        upgrade_request_id,
        completion_payload(payoff_quote_id, target_imei=target_imei, **extra),
        make_associate_headers(associate_user_id)))


# =========================================================================
# Tier 1 — the origination chain
# =========================================================================
def setup_active_loan(term_months: int = DEFAULT_TERM_MONTHS,
                      credit_score_band: str = "PRIME",
                      down_payment_cents: int = 0,
                      declared_down_payment_cents: Optional[int] = None,
                      activate: bool = False,
                      with_target_model: bool = True,
                      with_carrier_account: bool = True,
                      model_overrides: Optional[Dict[str, Any]] = None,
                      target_model_overrides: Optional[Dict[str, Any]] = None,
                      customer_overrides: Optional[Dict[str, Any]] = None,
                      carrier_overrides: Optional[Dict[str, Any]] = None,
                      imei: Optional[str] = None,
                      existing_model: Optional[Dict[str, Any]] = None,
                      existing_target_model: Optional[Dict[str, Any]] = None,
                      associate_user_id: str = ASSOCIATE_USER_ID,
                      underwriter_user_id: str = UNDERWRITER_USER_ID) -> Dict[str, Any]:
    """Publish a catalog, enrol a customer and walk application -> decision ->
    origination, leaving an ACTIVE loan with a full installment schedule.

    Pass `existing_model` / `existing_target_model` (whole model records, as returned
    by publish_model / publish_target_model) to reuse an already-published catalog
    instead of publishing a fresh one — that is how two borrowers end up financing
    the same model or contending for one target model's reservation capacity.

    Returns a context dict with keys: model, target_model, customer,
    customer_headers, carrier, application, loan, device, installments.
    """
    model = existing_model if existing_model is not None else publish_model(**(model_overrides or {}))
    if existing_target_model is not None:
        target_model = existing_target_model
    elif with_target_model:
        target_model = publish_target_model(**(target_model_overrides or {}))
    else:
        target_model = None
    customer = enroll_customer(**(customer_overrides or {}))
    customer_id = customer["id"]

    application_payload_extras: Dict[str, Any] = {"requested_term_months": int(term_months)}
    if declared_down_payment_cents is None and down_payment_cents:
        declared_down_payment_cents = int(down_payment_cents)
    if declared_down_payment_cents is not None:
        application_payload_extras["declared_down_payment_cents"] = int(declared_down_payment_cents)

    application = submit_application(customer_id, model["id"], **application_payload_extras)
    application = decide_application(application["id"], credit_score_band,
                                     underwriter_user_id=underwriter_user_id)
    loan = originate_loan(application["id"], down_payment_cents=int(down_payment_cents),
                          imei=imei, associate_user_id=associate_user_id)
    device = loan_device_unit(loan["id"])

    carrier = None
    if with_carrier_account:
        carrier = register_carrier_account(customer_id, **(carrier_overrides or {}))
    if activate:
        assert carrier is not None, "setup_active_loan(activate=True) needs a carrier account"
        device = activate_device(device["id"], carrier["id"])

    return {
        "model": model,
        "target_model": target_model,
        "customer": customer,
        "customer_id": customer_id,
        "customer_headers": make_customer_headers(customer_id),
        "carrier": carrier,
        "application": application,
        "loan": loan,
        "loan_id": loan["id"],
        "device": device,
        "device_id": device["id"],
        "installments": read_installments(loan["id"]),
        "term_months": int(term_months),
    }


def installment_total_cents(installments: List[Dict[str, Any]], count: int) -> int:
    """The exact cash needed to settle the first `count` installments in full."""
    assert count <= len(installments), (
        f"Setup failed: asked for {count} installments of {len(installments)}")
    return sum(int(row["amount_due_cents"]) for row in installments[:count])


def pay_installments(ctx: Dict[str, Any], count: int) -> Dict[str, Any]:
    """Post one payment that settles exactly the first `count` installments.

    The waterfall fills the future-obligation bucket in ascending installment
    order, so a single posting of their summed amount_due lands them all PAID
    with no overpayment residue.
    """
    installments = ctx.get("installments") or read_installments(ctx["loan_id"])
    amount = installment_total_cents(installments, int(count))
    posting = post_payment(ctx["loan_id"], amount, customer_id=ctx["customer_id"])
    ctx["posting"] = posting
    ctx["loan"] = read_loan(ctx["loan_id"])
    ctx["installments"] = read_installments(ctx["loan_id"])
    return posting


def setup_loan_with_paid_installments(count: int, **kwargs) -> Dict[str, Any]:
    """An ACTIVE loan whose first `count` installments are PAID."""
    ctx = setup_active_loan(**kwargs)
    if count:
        pay_installments(ctx, count)
    return ctx


# =========================================================================
# Tier 2 — servicing, delinquency and closure
# =========================================================================
def advance_to_dpd(ctx: Dict[str, Any], days_past_due: int,
                   installment_number: int = 1, sweep: bool = True) -> Dict[str, Any]:
    """Move the clock to `days_past_due` days after one installment's due date and
    (by default) run the sweep so the ageing is actually recorded."""
    due = read_installment(ctx["loan_id"], installment_number)["due_date"]
    set_clock(plus_days(due, int(days_past_due)))
    if sweep:
        ctx["sweep"] = run_sweep()
    ctx["loan"] = read_loan(ctx["loan_id"])
    ctx["installments"] = read_installments(ctx["loan_id"])
    return ctx


def setup_grace_loan(**kwargs) -> Dict[str, Any]:
    """A loan sitting in GRACE — one installment past due inside the 10-day window."""
    ctx = setup_active_loan(**kwargs)
    return advance_to_dpd(ctx, GRACE_PERIOD_DAYS - 5)


def setup_delinquent_loan(days_past_due: int = DELINQUENT_MIN_DPD, **kwargs) -> Dict[str, Any]:
    """A loan aged past the grace window into DELINQUENT."""
    ctx = setup_active_loan(**kwargs)
    return advance_to_dpd(ctx, int(days_past_due))


def setup_defaulted_loan(**kwargs) -> Dict[str, Any]:
    """A loan aged to 90 days past due and swept, firing the default cascade."""
    ctx = setup_active_loan(**kwargs)
    ctx = advance_to_dpd(ctx, DEFAULT_MIN_DPD)
    ctx["customer"] = read_customer(ctx["customer_id"])
    return ctx


def setup_paid_off_loan(**kwargs) -> Dict[str, Any]:
    """A loan closed by settling an EARLY_CANCELLATION quote to the cent."""
    ctx = setup_active_loan(**kwargs)
    quote = price_quote(ctx["loan_id"], "EARLY_CANCELLATION", customer_id=ctx["customer_id"])
    ctx["quote"] = quote
    ctx["cancellation"] = cancel_loan(ctx["loan_id"], quote["id"],
                                      int(quote["total_payoff_cents"]),
                                      customer_id=ctx["customer_id"])
    ctx["loan"] = read_loan(ctx["loan_id"])
    ctx["device"] = read_device_unit(ctx["device_id"])
    return ctx


def setup_unlock_eligible(**kwargs) -> Dict[str, Any]:
    """An activated handset whose loan has the policy number of paid installments and
    whose activation is older than the carrier account's unlock_policy_days."""
    kwargs.setdefault("activate", True)
    ctx = setup_loan_with_paid_installments(UNLOCK_MIN_PAID_INSTALLMENTS, **kwargs)
    policy_days = int(ctx["carrier"]["unlock_policy_days"])
    set_clock(plus_days(ctx["device"]["activated_at"], policy_days))
    ctx["device"] = read_device_unit(ctx["device_id"])
    return ctx


# =========================================================================
# Tier 3 — the upgrade chain
# =========================================================================
def upgrade_window_start_for(loan: Dict[str, Any]) -> str:
    """The first fulfillment-window start the loan's upgrade window admits."""
    return at_midnight(loan["upgrade_window_opens_at"])


def setup_upgrade_ready(paid_count: int = 12, **kwargs) -> Dict[str, Any]:
    """An activated loan that clears every upgrade gate: enough PAID installments,
    the clock standing at the loan's upgrade_window_opens_at, delinquency CURRENT.

    Paying first and moving the clock afterwards keeps the schedule clean — no
    sweep runs, so nothing ages into arrears.
    """
    kwargs.setdefault("activate", True)
    ctx = setup_loan_with_paid_installments(int(paid_count), **kwargs)
    set_clock(at_midnight(ctx["loan"]["upgrade_window_opens_at"]))
    ctx["loan"] = read_loan(ctx["loan_id"])
    ctx["window_start"] = upgrade_window_start_for(ctx["loan"])
    return ctx


def setup_upgrade_request(paid_count: int = 12, window_start: Optional[str] = None,
                          **kwargs) -> Dict[str, Any]:
    """An OPEN upgrade request holding the loan and one reserved target-model slot."""
    ctx = setup_upgrade_ready(paid_count=paid_count, **kwargs)
    start = window_start or ctx["window_start"]
    ctx["upgrade_request"] = open_upgrade_request(
        ctx["loan_id"], ctx["target_model"]["id"], start, customer_id=ctx["customer_id"])
    ctx["upgrade_request_id"] = ctx["upgrade_request"]["id"]
    ctx["window_start"] = start
    ctx["window_end"] = plus_days(start, FULFILLMENT_WINDOW_DAYS)
    ctx["loan"] = read_loan(ctx["loan_id"])
    ctx["target_model"] = read_device_model(ctx["target_model"]["id"])
    return ctx


def setup_trade_in_declared(declared_condition: str = "GOOD", **kwargs) -> Dict[str, Any]:
    """A DECLARED trade-in attached to an open upgrade request."""
    ctx = setup_upgrade_request(**kwargs)
    ctx["trade_in"] = declare_trade_in(ctx["upgrade_request_id"], ctx["device_id"],
                                       declared_condition, customer_id=ctx["customer_id"])
    ctx["trade_in_id"] = ctx["trade_in"]["id"]
    ctx["upgrade_request"] = read_upgrade_request(ctx["upgrade_request_id"])
    return ctx


def setup_trade_in_received(declared_condition: str = "GOOD",
                            technician_user_id: str = TECHNICIAN_USER_ID,
                            **kwargs) -> Dict[str, Any]:
    """A RECEIVED trade-in: the handset is back in store and its line is deactivated."""
    ctx = setup_trade_in_declared(declared_condition, **kwargs)
    ctx["trade_in"] = receive_trade_in(ctx["trade_in_id"], technician_user_id)
    ctx["device"] = read_device_unit(ctx["device_id"])
    return ctx


def setup_trade_in_graded(declared_condition: str = "GOOD",
                          technician_user_id: str = TECHNICIAN_USER_ID,
                          measurements: Optional[Dict[str, Any]] = None,
                          **kwargs) -> Dict[str, Any]:
    """A GRADED trade-in carrying its final credit and its first DiagnosticReport."""
    ctx = setup_trade_in_received(declared_condition,
                                  technician_user_id=technician_user_id, **kwargs)
    ctx["report"] = grade_trade_in(ctx["trade_in_id"], technician_user_id,
                                   **(measurements or {}))
    ctx["trade_in"] = read_trade_in(ctx["trade_in_id"])
    ctx["customer"] = read_customer(ctx["customer_id"])
    return ctx


def setup_trade_in_disputed(**kwargs) -> Dict[str, Any]:
    """A DISPUTED trade-in awaiting a regrade by a different technician."""
    ctx = setup_trade_in_graded(**kwargs)
    ctx["trade_in"] = dispute_trade_in(ctx["trade_in_id"], customer_id=ctx["customer_id"])
    return ctx


def setup_completion_ready(declared_condition: str = "GOOD",
                           measurements: Optional[Dict[str, Any]] = None,
                           **kwargs) -> Dict[str, Any]:
    """A graded trade-in plus a live UPGRADE_ROLLOVER quote — everything the
    completion call demands."""
    ctx = setup_trade_in_graded(declared_condition, measurements=measurements, **kwargs)
    ctx["quote"] = price_quote(ctx["loan_id"], "UPGRADE_ROLLOVER",
                              customer_id=ctx["customer_id"])
    ctx["loan"] = read_loan(ctx["loan_id"])
    return ctx


def setup_completed_upgrade(**kwargs) -> Dict[str, Any]:
    """A COMPLETED upgrade: the old loan is closed and a successor loan exists."""
    ctx = setup_completion_ready(**kwargs)
    ctx["new_loan"] = complete_upgrade(ctx["upgrade_request_id"], ctx["quote"]["id"])
    ctx["upgrade_request"] = read_upgrade_request(ctx["upgrade_request_id"])
    ctx["loan"] = read_loan(ctx["loan_id"])
    ctx["trade_in"] = read_trade_in(ctx["trade_in_id"])
    return ctx


def setup_second_customer(model: Dict[str, Any],
                          target_model: Optional[Dict[str, Any]] = None,
                          term_months: int = DEFAULT_TERM_MONTHS,
                          **kwargs) -> Dict[str, Any]:
    """A second borrower financing an ALREADY-PUBLISHED model — for cross-customer
    ownership screens and shared reservation-capacity scenarios.

    `model` and `target_model` are whole model records (e.g. `ctx["model"]` and
    `ctx["target_model"]` from a first borrower's context), so both borrowers really
    do share one catalog entry.
    """
    return setup_active_loan(term_months=term_months, existing_model=model,
                             existing_target_model=target_model, **kwargs)
