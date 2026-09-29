"""The two conserved quantities of PRD §2.10.

Every reservation has a matching compensating release, and every issuance has a
matching compensating void; these tests walk long sequences and check the closing
identity rather than a single hop.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers import test_users as U
from test_helpers.assertions import (
    assert_cents,
    assert_fleet_counts,
    assert_instant,
    assert_integer,
    assert_invoice_rollup,
    assert_line_types,
)


# ---------------------------------------------------------------------------
# compensating_invariant — the fleet
# ---------------------------------------------------------------------------


def _contract_awaiting_mobilization(api):
    """A 500-foot construction contract over a fleet of 400 ten-foot panels.

    Each install attempt therefore commits 50 panels, and the crew's 12.0-hour
    daily capacity plus a fresh UTC date per attempt keep every dispatch gate
    other than the one under test silent.
    """
    world = FX.seed_world(api)
    contract, _quote = FX.seed_contract(
        api, world["jobsite"]["id"], world["account"]["id"], linear_feet=500
    )
    FX.set_clock(api, C.CLOCK_AUG_20)
    return world, contract


def test_cancelling_a_dispatched_install_returns_every_reserved_panel(api):
    """PRD §3.6: "Cancellation is the exact compensating action for dispatch: a
    dispatch followed by a cancellation must leave the panel product's
    `available_count` precisely where it started."

    Design: Difficulty/compensating_invariant/fleet_conservation_across_dispatch_cancel_and_abort
    """
    world, contract = _contract_awaiting_mobilization(api)
    panel_id = world["panel"]["id"]

    assert_fleet_counts(
        FX.read_product(api, panel_id),
        available=400,
        reserved=0,
        deployed=0,
        damaged=0,
        lost=0,
    )

    visit = FX.plan_work_order(api, contract["id"], C.WO_DELIVERY_INSTALL, 500)
    FX.dispatch(api, visit["id"], world["crew"]["id"], "2026-08-20T08:00:00Z")
    assert_fleet_counts(
        FX.read_product(api, panel_id), available=350, reserved=50, deployed=0
    )

    cancelled = validate_success(
        api.cancel_work_order(
            visit["id"],
            F.cancel_payload("CUSTOMER_RESCHEDULE"),
            U.DISPATCH_COORDINATOR,
        )
    )
    assert cancelled["status"] == C.WO_CANCELLED
    assert cancelled["reserved_unit_counts"] == []
    assert cancelled["crew_id"] is None

    assert_fleet_counts(
        FX.read_product(api, panel_id),
        available=400,
        reserved=0,
        deployed=0,
        damaged=0,
        lost=0,
    )
    assert FX.invoices_for(api, contract["id"]) == []
    reread = FX.read_contract(api, contract["id"])
    assert reread["lifecycle_status"] == C.LIFECYCLE_PENDING_MOBILIZATION
    assert reread["billing_status"] == C.BILLING_NOT_BILLED


def test_abort_then_install_then_finalize_closes_the_fleet_identity(api):
    """PRD §2.10: "Units move between buckets; they are never created or
    destroyed." and PRD §3.6: "Aborting releases every entry of
    `reserved_unit_counts` from `reserved_count` back to `available_count` and
    empties `reserved_unit_counts`".

    Design: Difficulty/compensating_invariant/fleet_conservation_across_dispatch_cancel_and_abort
    """
    world, contract = _contract_awaiting_mobilization(api)
    panel_id = world["panel"]["id"]
    crew_id = world["crew"]["id"]

    FX.set_clock(api, C.CLOCK_AUG_21)
    aborted_visit = FX.plan_work_order(
        api, contract["id"], C.WO_DELIVERY_INSTALL, 500
    )
    FX.dispatch(api, aborted_visit["id"], crew_id, "2026-08-21T08:00:00Z")
    aborted = validate_success(
        api.abort_work_order(
            aborted_visit["id"],
            F.abort_payload("SITE_NOT_READY"),
            U.DISPATCH_COORDINATOR,
        )
    )
    assert aborted["status"] == C.WO_ABORTED
    assert aborted["reserved_unit_counts"] == []
    assert aborted["crew_id"] is None
    assert_fleet_counts(
        FX.read_product(api, panel_id),
        available=400,
        reserved=0,
        deployed=0,
        damaged=0,
        lost=0,
    )
    assert FX.invoices_for(api, contract["id"]) == []
    assert (
        FX.read_contract(api, contract["id"])["lifecycle_status"]
        == C.LIFECYCLE_PENDING_MOBILIZATION
    )

    FX.set_clock(api, C.CLOCK_AUG_22)
    install = FX.plan_work_order(api, contract["id"], C.WO_DELIVERY_INSTALL, 500)
    FX.dispatch(api, install["id"], crew_id, "2026-08-22T08:00:00Z")
    completed = FX.complete(api, install["id"], 500)
    assert completed["status"] == C.WO_COMPLETED
    assert_fleet_counts(
        FX.read_product(api, panel_id),
        available=350,
        reserved=0,
        deployed=50,
        damaged=0,
        lost=0,
    )

    invoices = FX.invoices_for(api, contract["id"])
    assert len(invoices) == 1, invoices
    assert invoices[0]["invoice_kind"] == C.KIND_MOBILIZATION
    assert_cents(invoices[0]["total_cents"], 85487, "total_cents")

    FX.set_clock(api, C.CLOCK_AUG_25)
    removal = FX.plan_work_order(api, contract["id"], C.WO_REMOVAL, 500)
    FX.dispatch(api, removal["id"], crew_id, "2026-08-25T08:00:00Z")
    FX.complete(api, removal["id"], 500)
    assert_fleet_counts(
        FX.read_product(api, panel_id), available=350, reserved=0, deployed=50
    )

    reconciliation = api.list_reconciliations(
        U.YARD_AUDITOR, params={"contract_id": contract["id"], "limit": C.MAX_LIMIT}
    ).json()["data"][0]
    finalized = FX.finalize_reconciliation(
        api,
        reconciliation["id"],
        [F.unit_return(C.PANEL_CODE, returned=50)],
    )
    assert_cents(finalized["loss_charge_cents"], 0, "loss_charge_cents")
    assert_cents(finalized["damage_charge_cents"], 0, "damage_charge_cents")

    assert_fleet_counts(
        FX.read_product(api, panel_id),
        available=400,
        reserved=0,
        deployed=0,
        damaged=0,
        lost=0,
    )
    assert len(FX.invoices_for(api, contract["id"])) == 1
    final_contract = FX.read_contract(api, contract["id"])
    assert final_contract["lifecycle_status"] == C.LIFECYCLE_DEMOBILIZING
    # PRD §3.6 defines deployed_linear_feet as, at all times, the sum of
    # completed_linear_feet over the DELIVERY_INSTALL visits in COMPLETED or
    # PARTIAL — the single completed install of 500 feet.
    assert_integer(final_contract["deployed_linear_feet"], 500, "deployed_linear_feet")


# ---------------------------------------------------------------------------
# compensating_invariant — the ledger
# ---------------------------------------------------------------------------


def _mobilized_contract(api):
    """An ACTIVE contract whose 85487-cent mobilization invoice was raised by dc-001.

    The install is reported by the dispatch coordinator, so `issued_by_user_id`
    on the cascaded invoice is dc-001 and a void by am-001 clears the four-eyes
    rule of PRD §2.9.
    """
    world = FX.seed_world(api)
    state = FX.seed_installed_contract(api, world, linear_feet=500)
    invoice = state["mobilization_invoice"]
    assert invoice is not None, "the mobilization cascade must issue an invoice"
    assert_cents(invoice["total_cents"], 85487, "total_cents")
    assert invoice["issued_by_user_id"] == U.DISPATCH_COORDINATOR_ID
    state["world"] = world
    state["invoice"] = invoice
    return state


def test_voiding_a_partially_paid_invoice_writes_off_only_the_open_amount(api):
    """PRD §3.8: "The void reduces the account's `open_balance_cents` by exactly
    the invoice's `total_cents` less its `amount_paid_cents` as measured at the
    moment of the void, and raises the account's `lifetime_credited_cents` by
    that same amount. Cash already collected is not refunded, so the void never
    moves `amount_paid_cents`".

    Design: Difficulty/compensating_invariant/open_balance_conservation_across_issue_and_void
    """
    state = _mobilized_contract(api)
    account_id = state["world"]["account"]["id"]
    invoice_id = state["invoice"]["id"]

    paid = FX.pay_account(api, account_id, 40000)
    assert_cents(paid["open_balance_cents"], 45487, "open_balance_cents")
    assert_cents(paid["lifetime_credited_cents"], 0, "lifetime_credited_cents")
    part_paid = FX.read_invoice(api, invoice_id)
    assert part_paid["status"] == C.INVOICE_PARTIALLY_PAID
    assert_cents(part_paid["amount_paid_cents"], 40000, "amount_paid_cents")

    voided = validate_success(
        api.void_invoice(
            invoice_id, F.void_payload("BILLED_IN_ERROR"), U.ACCOUNT_MANAGER
        )
    )
    assert voided["status"] == C.INVOICE_VOID
    assert_cents(voided["amount_paid_cents"], 40000, "amount_paid_cents")
    assert voided["void_reason_code"] == "BILLED_IN_ERROR"

    account = FX.read_account(api, account_id)
    assert_cents(account["open_balance_cents"], 0, "open_balance_cents")
    assert_cents(account["lifetime_credited_cents"], 45487, "lifetime_credited_cents")
    assert account["credit_hold_flag"] is False

    contract = FX.read_contract(api, state["contract"]["id"])
    assert contract["lifecycle_status"] == C.LIFECYCLE_ACTIVE
    assert contract["billing_status"] == C.BILLING_SETTLED


def test_periodic_run_after_a_void_reopens_the_balance_and_leaves_credits_alone(api):
    """PRD §3.8: "`SETTLED` is **not** terminal in the money dimension: when a
    new invoice is issued for a contract whose ledger had been fully settled or
    written off, and whose `lifecycle_status` is not `CLOSED`, the money dimension
    moves `SETTLED → CURRENT` and the account's `open_balance_cents` rises by the
    new invoice's `total_cents`."

    Design: Difficulty/compensating_invariant/open_balance_conservation_across_issue_and_void
    """
    state = _mobilized_contract(api)
    account_id = state["world"]["account"]["id"]
    contract_id = state["contract"]["id"]

    FX.pay_account(api, account_id, 40000)
    validate_success(
        api.void_invoice(
            state["invoice"]["id"],
            F.void_payload("BILLED_IN_ERROR"),
            U.ACCOUNT_MANAGER,
        )
    )

    FX.set_clock(api, C.CLOCK_SEP_17)
    periodic = validate_success(
        api.create_billing_run(
            contract_id,
            F.billing_run_payload("2026-08-20T00:00:00Z", "2026-09-17T00:00:00Z"),
            U.ACCOUNT_MANAGER,
        ),
        expected_status=201,
    )

    assert periodic["invoice_kind"] == C.KIND_PERIODIC
    assert_integer(periodic["billable_days"], 28, "billable_days")
    assert_line_types(periodic, [C.LINE_RENTAL])
    assert_cents(periodic["lines"][0]["amount_cents"], 27000, "RENTAL")
    assert_integer(periodic["lines"][0]["quantity"], 28, "quantity")
    assert_invoice_rollup(periodic, subtotal=27000, tax=2403, late_fee=0, total=29403)
    assert_instant(periodic["period_end_utc"], "2026-09-17T00:00:00Z", "period_end_utc")

    account = FX.read_account(api, account_id)
    assert_cents(account["open_balance_cents"], 29403, "open_balance_cents")
    assert_cents(account["lifetime_credited_cents"], 45487, "lifetime_credited_cents")
    assert account["credit_hold_flag"] is False

    contract = FX.read_contract(api, contract_id)
    assert contract["lifecycle_status"] == C.LIFECYCLE_ACTIVE
    assert contract["billing_status"] == C.BILLING_CURRENT
