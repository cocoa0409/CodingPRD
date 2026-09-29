"""Non-linear state machines and multi-hop cascades.

Covers the bounded review cycle of PRD §3.4, the two parallel contract
dimensions of PRD §3.8 and §3.9, and the two places where a single request has
to propagate through fleet, contract, invoice and account in one shot: the
mobilization cascade of PRD §3.6 and the finalization cascade of PRD §3.7.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers import test_users as U
from test_helpers.api_errors import (
    ERR_ACCOUNT_CREDIT_HOLD,
    ERR_PERMIT_REVISION_LIMIT,
)
from test_helpers.assertions import (
    assert_cents,
    assert_credit_hold,
    assert_fleet_counts,
    assert_fresh_invoice,
    assert_instant,
    assert_integer,
    assert_invoice_rollup,
    assert_labor_hours,
    assert_line_types,
    line_by_type,
)


# ---------------------------------------------------------------------------
# non_linear_state_machine
# ---------------------------------------------------------------------------


def test_the_review_cycle_is_traversable_twice_and_refused_the_third_time(api):
    """PRD §3.4: "With the default allowance of 2, an application may be
    resubmitted while its `revision_round` reads 1 and while it reads 2, and is
    refused once it reads 3."

    Design: Difficulty/non_linear_state_machine/permit_revision_cycle_bounded_at_third_round
    """
    world = FX.seed_world(
        api,
        jobsite={
            "site_label": "Quay Street Tower",
            "address_line": "11 Quay Street",
            "site_condition": C.CONDITION_CONCRETE,
            "requires_sidewalk_closure": True,
        },
    )
    permit = FX.seed_permit(api, world["jobsite"]["id"])
    assert permit["status"] == C.PERMIT_DRAFT
    assert_integer(permit["revision_round"], 0, "revision_round")
    assert permit["required_change_summary"] is None

    summaries = [
        "narrow the closure to one lane",
        "add pedestrian canopy detail",
        "restate the traffic-control plan",
    ]
    for round_number, summary in enumerate(summaries, start=1):
        submitted = FX.submit_permit(api, permit["id"])
        assert submitted["status"] == C.PERMIT_SUBMITTED
        assert submitted["required_change_summary"] is None
        assert_instant(submitted["submitted_at_utc"], C.CLOCK_AUG_01, "submitted_at_utc")

        revision = FX.decide_permit(
            api,
            permit["id"],
            C.DECISION_REQUEST_REVISION,
            required_change_summary=summary,
        )
        assert revision["status"] == C.PERMIT_REVISION_REQUESTED
        assert_integer(revision["revision_round"], round_number, "revision_round")
        assert revision["required_change_summary"] == summary

    before = FX.read_permit(api, permit["id"])
    assert_integer(before["revision_round"], 3, "revision_round")

    validate_error(
        api.submit_permit(permit["id"], U.MUNICIPAL_LIAISON, F.submit_payload()),
        ERR_PERMIT_REVISION_LIMIT,
        409,
    )

    after = FX.read_permit(api, permit["id"])
    assert after["status"] == C.PERMIT_REVISION_REQUESTED
    assert_integer(after["revision_round"], 3, "revision_round")
    assert after["required_change_summary"] == summaries[-1]
    assert_instant(
        after["submitted_at_utc"], before["submitted_at_utc"], "submitted_at_utc"
    )

    # A REVISION_REQUESTED application no longer contends for the corridor.
    municipality = FX.read_municipality(api, world["municipality"]["id"])
    assert_integer(
        municipality["committed_closure_linear_feet"],
        0,
        "committed_closure_linear_feet",
    )


def test_lifecycle_and_billing_dimensions_advance_on_disjoint_triggers(api):
    """PRD §3.8: "The contract's money dimension, `billing_status`, evolves
    independently of its `lifecycle_status`; the two are parallel dimensions on
    the same row, and a contract may perfectly well be `ACTIVE` and `PAST_DUE`, or
    `DEMOBILIZING` and `CURRENT`." Closure of PRD §3.9 is the one edge that reads
    both dimensions at once.

    Design: Difficulty/non_linear_state_machine/contract_parallel_dimensions_advance_independently
    """
    world = FX.seed_world(api)
    fresh = FX.seed_contract(
        api, world["jobsite"]["id"], world["account"]["id"], linear_feet=500
    )[0]
    assert fresh["lifecycle_status"] == C.LIFECYCLE_PENDING_MOBILIZATION
    assert fresh["billing_status"] == C.BILLING_NOT_BILLED

    install = FX.plan_work_order(api, fresh["id"], C.WO_DELIVERY_INSTALL, 500)
    FX.set_clock(api, C.CLOCK_AUG_20)
    FX.dispatch(api, install["id"], world["crew"]["id"], "2026-08-20T08:00:00Z")
    FX.complete(api, install["id"], 500)

    mobilized = FX.read_contract(api, fresh["id"])
    assert mobilized["lifecycle_status"] == C.LIFECYCLE_ACTIVE
    assert mobilized["billing_status"] == C.BILLING_CURRENT

    mobilization = FX.invoices_for(api, fresh["id"])[0]
    assert_cents(mobilization["total_cents"], 85487, "total_cents")
    assert_instant(mobilization["due_at_utc"], "2026-09-19T00:00:00Z", "due_at_utc")

    # One day past the mobilization invoice's due date, the billing run itself
    # re-evaluates the money dimension before it prices the period.
    FX.set_clock(api, C.CLOCK_SEP_20)
    periodic = validate_success(
        api.create_billing_run(
            fresh["id"],
            F.billing_run_payload(C.CLOCK_AUG_20, C.CLOCK_SEP_17),
            U.ACCOUNT_MANAGER,
        ),
        expected_status=201,
    )
    assert_integer(periodic["billable_days"], 28, "billable_days")
    assert_line_types(periodic, [C.LINE_RENTAL])
    assert_cents(line_by_type(periodic, C.LINE_RENTAL)["amount_cents"], 27000, "RENTAL")
    assert_invoice_rollup(
        periodic, subtotal=27000, tax=2403, late_fee=1282, total=30685
    )

    overdue = FX.read_contract(api, fresh["id"])
    assert overdue["lifecycle_status"] == C.LIFECYCLE_ACTIVE
    assert overdue["billing_status"] == C.BILLING_PAST_DUE

    removal = FX.plan_work_order(api, fresh["id"], C.WO_REMOVAL, 500)
    FX.dispatch(api, removal["id"], world["crew"]["id"], "2026-09-20T08:00:00Z")
    FX.complete(api, removal["id"], 500)

    demobilizing = FX.read_contract(api, fresh["id"])
    assert demobilizing["lifecycle_status"] == C.LIFECYCLE_DEMOBILIZING
    assert demobilizing["billing_status"] == C.BILLING_PAST_DUE

    reconciliation = api.list_reconciliations(
        U.YARD_AUDITOR, params={"contract_id": fresh["id"], "limit": C.MAX_LIMIT}
    ).json()["data"][0]
    finalized = FX.finalize_reconciliation(
        api, reconciliation["id"], [F.unit_return(C.PANEL_CODE, returned=50)]
    )
    assert finalized["status"] == C.REC_FINALIZED
    assert_cents(finalized["loss_charge_cents"], 0, "loss_charge_cents")
    assert_cents(finalized["damage_charge_cents"], 0, "damage_charge_cents")

    # A finalized reconciliation alone does not close the contract: the ledger is
    # still owed, so the money dimension holds the closure back.
    unsettled = FX.read_contract(api, fresh["id"])
    assert unsettled["lifecycle_status"] == C.LIFECYCLE_DEMOBILIZING
    assert unsettled["billing_status"] == C.BILLING_PAST_DUE

    account = FX.pay_account(api, world["account"]["id"], 116172)
    assert_cents(account["open_balance_cents"], 0, "open_balance_cents")
    assert account["credit_hold_flag"] is False

    closed = FX.read_contract(api, fresh["id"])
    assert closed["lifecycle_status"] == C.LIFECYCLE_CLOSED
    assert closed["billing_status"] == C.BILLING_SETTLED

    invoices = FX.invoices_for(api, fresh["id"])
    assert len(invoices) == 2, invoices
    assert {inv["invoice_kind"] for inv in invoices} == {
        C.KIND_MOBILIZATION,
        C.KIND_PERIODIC,
    }
    assert all(inv["status"] == C.INVOICE_PAID for inv in invoices), invoices


# ---------------------------------------------------------------------------
# transitive_cascade
# ---------------------------------------------------------------------------


def test_completing_the_install_propagates_through_fleet_contract_invoice_and_account(
    api,
):
    """PRD §3.6: "A delivery-and-install visit reported complete is the trigger
    for the mobilization cascade, four hops deep ... All four hops complete inside
    the single request that reported the visit." The account's raised
    `credit_hold_flag` is then visible only through PRD §3.5's last dispatch gate.

    Design: Difficulty/transitive_cascade/install_completion_five_hop_cascade
    """
    world = FX.seed_world(
        api,
        crews=(C.CREW_A, C.CREW_B),
        account={"credit_limit_cents": 85486},
        jobsite={"phase_count": 4},
    )
    contract, _quote = FX.seed_contract(
        api, world["jobsite"]["id"], world["account"]["id"], linear_feet=500
    )
    install = FX.plan_work_order(api, contract["id"], C.WO_DELIVERY_INSTALL, 500)
    relocation = FX.plan_work_order(api, contract["id"], C.WO_RELOCATION, 500)

    FX.set_clock(api, C.CLOCK_AUG_20)
    scheduled = FX.dispatch(
        api, install["id"], world["crews"][C.CREW_A]["id"], "2026-08-20T08:00:00Z"
    )
    assert_labor_hours(scheduled["estimated_labor_hours"], 4.25)
    assert_fleet_counts(
        FX.read_product(api, world["panel"]["id"]),
        available=350,
        reserved=50,
        deployed=0,
    )

    completed = FX.complete(api, install["id"], 500)
    assert completed["status"] == C.WO_COMPLETED
    assert completed["completed_by_user_id"] == U.DISPATCH_COORDINATOR_ID

    # Hop one: the reservation becomes a deployment.
    assert_fleet_counts(
        FX.read_product(api, world["panel"]["id"]),
        available=350,
        reserved=0,
        deployed=50,
        damaged=0,
        lost=0,
    )

    # Hop two: the contract advances on both dimensions and anchors its billing.
    active = FX.read_contract(api, contract["id"])
    assert active["lifecycle_status"] == C.LIFECYCLE_ACTIVE
    assert active["billing_status"] == C.BILLING_CURRENT
    assert_instant(active["billing_anchor_utc"], C.CLOCK_AUG_20, "billing_anchor_utc")
    assert_integer(active["deployed_linear_feet"], 500, "deployed_linear_feet")

    # Hop three: the mobilization invoice, with the three lines of PRD §3.8.
    invoices = FX.invoices_for(api, contract["id"])
    assert len(invoices) == 1, invoices
    invoice = invoices[0]
    assert invoice["invoice_kind"] == C.KIND_MOBILIZATION
    assert_line_types(
        invoice, [C.LINE_INSTALL_LABOR, C.LINE_DELIVERY, C.LINE_PERMIT_HANDLING]
    )
    assert_cents(
        line_by_type(invoice, C.LINE_INSTALL_LABOR)["amount_cents"], 47500, "INSTALL_LABOR"
    )
    assert_cents(line_by_type(invoice, C.LINE_DELIVERY)["amount_cents"], 18500, "DELIVERY")
    assert_cents(
        line_by_type(invoice, C.LINE_PERMIT_HANDLING)["amount_cents"],
        12500,
        "PERMIT_HANDLING",
    )
    assert_invoice_rollup(invoice, subtotal=78500, tax=6987, late_fee=0, total=85487)
    assert_fresh_invoice(
        invoice, issued_by=U.DISPATCH_COORDINATOR_ID, issued_at=C.CLOCK_AUG_20
    )
    assert_instant(invoice["due_at_utc"], "2026-09-19T00:00:00Z", "due_at_utc")

    # Hop four: the account's exposure, one cent past its limit.
    account = FX.read_account(api, world["account"]["id"])
    assert_cents(account["open_balance_cents"], 85487, "open_balance_cents")
    assert account["credit_hold_flag"] is True
    assert_credit_hold(account)

    # Hop five is observable only through the last dispatch gate of PRD §3.5.
    validate_error(
        api.dispatch_work_order(
            relocation["id"],
            F.dispatch_payload(
                world["crews"][C.CREW_B]["id"], "2026-08-22T08:00:00Z"
            ),
            U.DISPATCH_COORDINATOR,
        ),
        ERR_ACCOUNT_CREDIT_HOLD,
        402,
    )
    unmoved = FX.read_work_order(api, relocation["id"])
    assert unmoved["status"] == C.WO_PLANNED
    assert unmoved["crew_id"] is None


def test_finalizing_the_reconciliation_propagates_through_fleet_invoice_and_account(api):
    """PRD §3.7: "Finalization then runs its own three-hop cascade." with hop
    three lifting "the account's `open_balance_cents` by that invoice's
    `total_cents`" and re-evaluating "its `credit_hold_flag`", while PRD §3.9
    holds the contract in `DEMOBILIZING` until the ledger settles.

    Design: Difficulty/transitive_cascade/reconciliation_finalize_four_hop_cascade
    """
    world = FX.seed_world(api, account={"credit_limit_cents": 234461})
    state = FX.seed_demobilizing_contract(api, world, linear_feet=500)

    assert state["reconciliation"] is not None, "removal must open a reconciliation"
    assert state["reconciliation"]["status"] == C.REC_OPEN

    before = FX.read_account(api, world["account"]["id"])
    assert_cents(before["open_balance_cents"], 85487, "open_balance_cents")
    assert before["credit_hold_flag"] is False

    finalized = FX.finalize_reconciliation(
        api,
        state["reconciliation"]["id"],
        [F.unit_return(C.PANEL_CODE, returned=43, damaged=2, missing=5)],
        auditor_note="five panels stolen overnight, no report filed",
    )

    assert finalized["status"] == C.REC_FINALIZED
    assert finalized["finalized_by_user_id"] == U.YARD_AUDITOR_ID
    assert finalized["assessment_variant"] == C.VARIANT_REPLACEMENT_COST
    assert_cents(finalized["loss_charge_cents"], 120000, "loss_charge_cents")
    assert_cents(finalized["damage_charge_cents"], 16800, "damage_charge_cents")

    # Hop one: the fifty deployed panels split three ways.
    assert_fleet_counts(
        FX.read_product(api, world["panel"]["id"]),
        available=393,
        reserved=0,
        deployed=0,
        damaged=2,
        lost=5,
    )

    # Hop two: the FINAL invoice, carrying both money lines.
    finals = FX.invoices_for(api, state["contract"]["id"], invoice_kind=C.KIND_FINAL)
    assert len(finals) == 1, finals
    final = finals[0]
    assert_line_types(final, [C.LINE_LOSS, C.LINE_DAMAGE])
    assert_cents(line_by_type(final, C.LINE_LOSS)["amount_cents"], 120000, "LOSS")
    assert_cents(line_by_type(final, C.LINE_DAMAGE)["amount_cents"], 16800, "DAMAGE")
    assert_invoice_rollup(final, subtotal=136800, tax=12175, late_fee=0, total=148975)
    assert_fresh_invoice(
        final, issued_by=U.YARD_AUDITOR_ID, issued_at=C.CLOCK_AUG_25
    )

    # Hop three: the account's exposure, one cent past its limit.
    after = FX.read_account(api, world["account"]["id"])
    assert_cents(after["open_balance_cents"], 234462, "open_balance_cents")
    assert after["credit_hold_flag"] is True
    assert_credit_hold(after)

    contract = FX.read_contract(api, state["contract"]["id"])
    assert contract["lifecycle_status"] == C.LIFECYCLE_DEMOBILIZING
    assert contract["billing_status"] == C.BILLING_CURRENT
