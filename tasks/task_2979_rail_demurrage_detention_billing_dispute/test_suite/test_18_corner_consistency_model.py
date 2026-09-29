"""Queue B - corner section ``consistency_model``.

Two instances, both asserting that this service is immediately consistent: the
response body of the single call that causes a cascade already carries the
cascade, and reads taken in the very next call agree with it without any
intervening write, poll, retry or delay.

Two adjudications against the design index were needed here, and PRD.md wins
both.  The index expects the fully credited charge line to report a
``DISPUTE_CREDITED`` status, but PRD 3.8 says each line's "status becomes
`ADJUSTED` when the figure is positive or `FINAL` when it is 0", and PRD 3.5
declares no such enum member.  The index also expects an invoice create to
return its summed totals, but PRD 3.7 says "the money totals deliberately stay
at zero until the invoice is issued, because the credit calculation is part of
issuing rather than part of assembling" - so the create carries
``attached_charge_count`` while the rollup arrives at issue, which the second
test asserts in the very next call.

Two rendering conventions apply to the PRD quotations in the docstrings below:
the PRD's em dashes are written as ASCII hyphens and its transition arrows as
``->``.  Nothing else is altered, so every quoted sentence is greppable in
``workspace/PRD.md`` once those two substitutions are made.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_charge_money_invariant,
    assert_invoice_money_invariant,
    assert_pagination_meta,
    assert_subset_equal,
    ids_of,
)
from test_helpers.constants import (
    BILLING_ADJUSTED,
    BILLING_INVOICED,
    CHARGE_ADJUSTED,
    CHARGE_FINAL,
    CLOCK_AFTER_RELEASE,
    CYCLE_A_GROSS_CENTS,
    CYCLE_B_GROSS_CENTS,
    DECISION_ALLOWED,
    DISPUTE_DECIDED,
    INVOICE_ADJUSTED,
    INVOICE_DRAFT,
    INVOICE_ISSUED,
    MOVEMENT_RELEASED,
    TWO_LINE_GROSS_TOTAL,
)
from test_helpers.test_users import ADMIN, make_adjudicator_headers

ADJUDICATOR_ON_THE_CASCADE = "adj-c9m1-a"
RATIONALE_FAULT_ADMITTED = "Railroad fault admitted."


# ===========================================================================
# instance: the_decide_response_itself_already_carries_the_whole_cascade
# ===========================================================================
def test_the_decide_response_itself_already_carries_the_whole_cascade(api):
    """No settlement job: the three downstream reads only confirm the body.

    PRD 3.8: "Deciding cascades outward. Each target cycle's `billing_status`
    moves to `ADJUSTED`, or back to `INVOICED` when its line's credit is 0. The
    invoice's `total_credit_cents`, `total_net_cents` and derived status are
    rewritten and its `version` increments by 1. The consignee's
    `credit_balance_cents` - the sum of `credit_applied_cents` over every charge
    on that consignee's cycles whose status is `FINAL` or `ADJUSTED` - and
    `dispute_posture` are re-derived and its `version` increments by 1. The
    invoice's `total_gross_cents` does not move."

    Design: Corner/consistency_model/the_decide_response_itself_already_carries_the_whole_cascade
    """
    world = fx.reference_world(api)
    cycle = fx.released_cycle_a(api, world)
    invoice = fx.issued_invoice(api, world)
    assert invoice["total_gross_cents"] == CYCLE_A_GROSS_CENTS

    dispute = fx.under_review_dispute(
        api,
        invoice,
        world["customer_id"],
        CYCLE_A_GROSS_CENTS,
        ADJUDICATOR_ON_THE_CASCADE,
    )

    decided = get_success_data(
        api.decide_dispute(
            dispute["id"],
            f.decide_payload(
                DECISION_ALLOWED, 1, decision_rationale=RATIONALE_FAULT_ADMITTED
            ),
            make_adjudicator_headers(ADJUDICATOR_ON_THE_CASCADE),
        )
    )
    # The single response body already reports the whole allowance.
    assert_subset_equal(
        decided,
        {
            "status": DISPUTE_DECIDED,
            "decision": DECISION_ALLOWED,
            "allowance_pct": 1,
            "allowed_credit_cents": CYCLE_A_GROSS_CENTS,
        },
    )

    # Read one: the charge line, immediately, with no write in between.
    charge = fx.charge_of_cycle(api, cycle["id"])
    assert_subset_equal(
        charge,
        {
            "status": CHARGE_ADJUSTED,
            "gross_amount_cents": CYCLE_A_GROSS_CENTS,
            "credit_applied_cents": CYCLE_A_GROSS_CENTS,
            "net_amount_cents": 0,
        },
    )
    assert_charge_money_invariant(charge)

    # Read two: the invoice, whose gross did not move while its credit did.
    adjusted = fx.get_invoice(api, invoice["id"])
    assert_subset_equal(
        adjusted,
        {
            "status": INVOICE_ADJUSTED,
            "total_gross_cents": CYCLE_A_GROSS_CENTS,
            "total_credit_cents": CYCLE_A_GROSS_CENTS,
            "total_net_cents": 0,
        },
    )
    assert_invoice_money_invariant(adjusted)

    # Read three: the consignee's balance, and the cycle's money dimension.
    assert (
        fx.get_customer(api, world["customer_id"])["credit_balance_cents"]
        == CYCLE_A_GROSS_CENTS
    )
    settled_cycle = fx.get_cycle(api, cycle["id"])
    assert_subset_equal(
        settled_cycle,
        {"billing_status": BILLING_ADJUSTED, "movement_status": MOVEMENT_RELEASED},
    )


# ===========================================================================
# instance: the_invoice_create_response_already_holds_its_own_rollup
# ===========================================================================
def test_the_invoice_create_response_already_holds_its_own_attachment(api):
    """Attachment is not a later batch, and the rollup lands on the next call.

    PRD 3.7: "Every charge line whose status is `FINAL`, whose `invoice_id` is
    still null, whose cycle belongs to this consignee, and whose cycle's
    `released_at` falls inside the closed billing period is attached - its
    `invoice_id` is set to the new invoice - and each attached cycle's
    `billing_status` moves `UNBILLED -> INVOICED`. Note that the movement
    dimension is untouched by this: the cycle stays `RELEASED`. The invoice's
    `attached_charge_count` is derived from the attachment, but the money totals
    deliberately stay at zero until the invoice is issued, because the credit
    calculation is part of issuing rather than part of assembling."

    Design: Corner/consistency_model/the_invoice_create_response_already_holds_its_own_rollup
    """
    world = fx.reference_world(api)
    cycle_a, cycle_b = fx.released_pair(api, world)
    fx.set_clock(api, CLOCK_AFTER_RELEASE)

    created = get_success_data(
        api.create_invoice(f.invoice_payload(world["customer_id"]), ADMIN), 201
    )
    # The 201 body already knows both lines are on it - and, per PRD 3.7, still
    # carries zero money.
    assert_subset_equal(
        created,
        {
            "status": INVOICE_DRAFT,
            "attached_charge_count": 2,
            "total_gross_cents": 0,
            "total_credit_cents": 0,
            "total_net_cents": 0,
            "agreement_credit_cents": 0,
            "dispute_count": 0,
            "dispute_deadline_at": None,
        },
    )

    # The very next call already sees the attachment from the charges' side.
    listed = api.list_charges(ADMIN, {"invoice_id": created["id"], "limit": 10, "offset": 0})
    rows = get_success_data(listed)
    assert_pagination_meta(
        listed.json()["meta"], limit=10, offset=0, total_count=2, has_more=False
    )
    assert sorted(row["invoice_id"] for row in rows) == [created["id"]] * 2
    charge_a = fx.charge_of_cycle(api, cycle_a["id"])
    charge_b = fx.charge_of_cycle(api, cycle_b["id"])
    assert sorted(ids_of(rows)) == sorted([charge_a["id"], charge_b["id"]])
    assert charge_a["status"] == CHARGE_FINAL
    assert charge_b["status"] == CHARGE_FINAL

    # And from the cycles' side, with the movement dimension untouched.
    assert_subset_equal(
        fx.get_cycle(api, cycle_a["id"]),
        {"billing_status": BILLING_INVOICED, "movement_status": MOVEMENT_RELEASED},
    )
    assert fx.get_cycle(api, cycle_b["id"])["billing_status"] == BILLING_INVOICED

    # The rollup itself is the issue step, and it too is immediate: no
    # reconciliation or refresh call stands between the create and this body.
    issued = get_success_data(api.issue_invoice(created["id"], ADMIN))
    assert_subset_equal(
        issued,
        {
            "status": INVOICE_ISSUED,
            "attached_charge_count": 2,
            "total_gross_cents": TWO_LINE_GROSS_TOTAL,
            "total_credit_cents": 0,
            "total_net_cents": TWO_LINE_GROSS_TOTAL,
        },
    )
    assert TWO_LINE_GROSS_TOTAL == CYCLE_A_GROSS_CENTS + CYCLE_B_GROSS_CENTS
    assert_invoice_money_invariant(issued)
