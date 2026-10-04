"""Project cost estimation: the provisional and reconciled variants diverge
once actual invoices land (PRD §3.4/§3.5)."""

from test_helpers import (
    create_contractor,
    create_work_order,
    drive_work_order_to,
    get_project,
    get_scope_item,
    get_work_order,
    scope_item_payload,
    setup_selected_project,
    trade_scope_item_payload,
)


def _setup_invoiced_trade_project():
    """Selected project with one ELECTRICAL permit item (100000..200000) and
    one volunteer item (200000..400000); the electrical item's work order is
    driven to INVOICED at 210000."""
    ctx = setup_selected_project(
        budget_cents=2_000_000,
        scope_items=[
            trade_scope_item_payload(
                est_low_cents=100_000,
                est_high_cents=200_000,
                requires_permit=True,
                description="rewire panel",
            ),
            scope_item_payload(
                category="SAFETY",
                est_low_cents=200_000,
                est_high_cents=400_000,
                description="build ramp",
            ),
        ],
    )
    contractor = create_contractor(legal_name="SparkPros", trade="ELECTRICAL")
    trade_item = next(
        item for item in ctx["scope_items"] if item["volunteer_performable"] is False
    )
    wo = create_work_order(
        ctx["project"]["id"], contractor["id"], [trade_item["id"]]
    )
    wo = drive_work_order_to(
        wo["id"],
        contractor["id"],
        "INVOICED",
        quote_cents=200_000,
        invoice_cents=210_000,
        permit_number="PERMIT-77",
    )
    return ctx, contractor, wo, trade_item


def test_project_cost_provisional_ignores_invoices():
    """PRD §3.5: "The provisional estimate — the selection and planning basis
    already defined in §3.4 — sums midpoints over `INCLUDED` items and ignores
    actual invoices and material deliveries."
    PRD §3.4: "First comes the provisional estimate itself: the sum of
    `midpoint_cents` over the project's `INCLUDED` scope items, where scope
    estimates are labor-inclusive for licensed-trade items and full-cost for
    volunteer-performable items, and where material orders are tracked
    separately and never enter the figure."

    Midpoints 150000 (electrical) + 300000 (volunteer) pin the provisional
    estimate at 450000 and the envelope at round_half_up(450000 * 1.15) =
    517500; a landed 210000 invoice never moves the provisional figure.

    Design: Difficulty/dual_variant_calc/project_cost_provisional_vs_reconciled_diverge
    """
    ctx, _, _, _ = _setup_invoiced_trade_project()
    assert ctx["project"]["provisional_estimate_cents"] == 450_000
    assert ctx["project"]["envelope_cents"] == 517_500
    after = get_project(ctx["project"]["id"])
    assert after["provisional_estimate_cents"] == 450_000, (
        "the provisional variant never observes invoices"
    )


def test_project_cost_reconciled_replaces_midpoints_with_actuals():
    """PRD §3.5: "The reconciled cost, carried on the project as
    `reconciled_cost_cents`, progressively replaces estimates with actuals as
    the build advances: it sums the `invoice_cents` of the project's work
    orders in `INVOICED` or `PAID`, plus the midpoints of volunteer-performable
    scope items in `INCLUDED` or `COMPLETED` that are not covered by any
    invoiced or paid work order, plus the `total_cents` of material orders in
    `DELIVERED`."

    Once the electrical item's order is INVOICED at 210000, the reconciled
    figure is 210000 plus the surviving volunteer midpoint 300000 = 510000,
    diverging from the still-450000 provisional estimate.

    Design: Difficulty/dual_variant_calc/project_cost_provisional_vs_reconciled_diverge
    """
    ctx, _, work_order, trade_item = _setup_invoiced_trade_project()
    after = get_project(ctx["project"]["id"])
    assert after["reconciled_cost_cents"] == 510_000, (
        "invoice 210000 + volunteer midpoint 300000"
    )
    assert get_scope_item(trade_item["id"])["status"] == "COMPLETED"
    assert get_work_order(work_order["id"])["status"] == "INVOICED"
