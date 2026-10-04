"""Transitive cascades: the four-entity discontinuation cascade and the
certification-denial cascade that reverts the product through the
reformulation path.
"""

from test_helpers import (
    CLOCK_MARKDOWN_WEEK9,
    approve_discontinuation,
    assert_footprint_conservation,
    assert_launch_inventory_conserved,
    open_dossier,
    propose_discontinuation,
    read_cost_quote,
    read_discontinuation_review,
    read_dossier,
    read_formula_project,
    read_launch_plan,
    read_partner,
    read_planogram_slot,
    read_product,
    set_clock,
    setup_compliance_gate_product,
    setup_executed_plan,
    submit_dossier_review,
)


def _propose_and_approve(ctx):
    review = propose_discontinuation(ctx["product"]["id"], reason="TREND_DECAY")
    approve_discontinuation(review["id"])
    return review


def test_discontinuation_cascade_reaches_product_and_slot(api):
    """PRD §3.9: "Approval fires the discontinuation cascade, atomically and
    four entities deep: the product moves from `LAUNCHED` to `DISCONTINUED`
    with its `successor_product_id` set from the review — which may be null;
    every `COMMITTED` or `ACTIVE` planogram slot for the product moves to
    `VACATED`, freeing its facings; each vacancy forces recomputation of the
    partner's `committed_facings` and `available_facings`; and the product's
    `EXECUTED` launch plan moves to `RECONCILED` with `markdown_units` set to
    `retail_units_available` and `markdown_exposure_cents` computed from the
    depth tiers of §3.8."

    Design: Difficulty/transitive_cascade/discontinuation_cascade_depth3
    """
    ctx = setup_executed_plan()
    set_clock(CLOCK_MARKDOWN_WEEK9)  # 65 days after launch -> 9 whole weeks

    review = _propose_and_approve(ctx)

    product = read_product(ctx["product"]["id"])
    assert product["status"] == "DISCONTINUED"
    assert product["successor_product_id"] is None
    assert read_planogram_slot(ctx["slot"]["id"])["status"] == "VACATED"
    partner = read_partner(ctx["partner"]["id"])
    assert partner["committed_facings"]["EYES"] == 0
    assert partner["available_facings"]["EYES"] == 10
    assert_footprint_conservation(partner)
    assert read_discontinuation_review(review["id"])["status"] == "APPROVED"


def test_discontinuation_cascade_reconciles_plan_with_markdown_depth(api):
    """PRD §3.8: "The depth depends on whole weeks since `launched_at`: zero
    percent when four weeks or fewer have elapsed, thirty percent through
    eight weeks, fifty percent through twelve weeks, and seventy percent
    beyond that; the exposure is `markdown_units` times `landed_locked_cents`
    times the depth, in integer cents."
    Launched 2026-11-01, reconciled at 2027-01-05 -> 9 whole weeks -> depth
    0.50; markdown_units == 800 (all retail units) so exposure ==
    800 * 237 * 0.50 == 94800.

    Design: Difficulty/transitive_cascade/discontinuation_cascade_depth3
    """
    ctx = setup_executed_plan()
    set_clock(CLOCK_MARKDOWN_WEEK9)

    _propose_and_approve(ctx)

    plan = read_launch_plan(ctx["plan"]["id"])
    assert plan["status"] == "RECONCILED"
    assert plan["markdown_units"] == 800
    assert plan["markdown_exposure_cents"] == 94800
    assert_launch_inventory_conserved(plan)


def test_cert_denial_reverts_product_from_compliance_gate(api):
    """PRD §3.6: "Both denial and lapse fire the product-reversion cascade: if
    the product is in `COMPLIANCE_GATE` or `LAUNCH_READY`, it reverts directly
    to `FORMULATION` — with no intermediate state — and that reversion in turn
    invalidates every accepted quote and reopens every approved formula
    project exactly as the manual reformulation of §3.3 does."

    Design: Difficulty/transitive_cascade/cert_denial_cascade_depth2
    """
    ctx = setup_compliance_gate_product()
    dossier = open_dossier(ctx["product"]["id"])
    submit_dossier_review(dossier["id"], "INGREDIENT", "CLEARED")
    submit_dossier_review(dossier["id"], "CLAIM", "SUBSTANTIATED")
    submit_dossier_review(dossier["id"], "CERTIFICATION", "APPLIED")
    submit_dossier_review(dossier["id"], "CERTIFICATION", "AUDITING")

    denied = submit_dossier_review(dossier["id"], "CERTIFICATION", "DENIED")

    assert denied["cert_status"] == "DENIED"
    assert denied["compliant"] is False
    assert read_product(ctx["product"]["id"])["status"] == "FORMULATION"


def test_cert_denial_invalidates_quote_and_reopens_formula(api):
    """PRD §3.6: "Both denial and lapse fire the product-reversion cascade: if
    the product is in `COMPLIANCE_GATE` or `LAUNCH_READY`, it reverts directly
    to `FORMULATION` — with no intermediate state — and that reversion in turn
    invalidates every accepted quote and reopens every approved formula
    project exactly as the manual reformulation of §3.3 does."
    The second cascade link lands on the quote (INVALIDATED) and the formula
    project (IN_DEVELOPMENT at round 2).

    Design: Difficulty/transitive_cascade/cert_denial_cascade_depth2
    """
    ctx = setup_compliance_gate_product()
    dossier = open_dossier(ctx["product"]["id"])
    submit_dossier_review(dossier["id"], "INGREDIENT", "CLEARED")
    submit_dossier_review(dossier["id"], "CLAIM", "SUBSTANTIATED")
    submit_dossier_review(dossier["id"], "CERTIFICATION", "APPLIED")
    submit_dossier_review(dossier["id"], "CERTIFICATION", "AUDITING")
    submit_dossier_review(dossier["id"], "CERTIFICATION", "DENIED")

    assert read_cost_quote(ctx["quote"]["id"])["status"] == "INVALIDATED"
    formula = read_formula_project(ctx["formula_project"]["id"])
    assert formula["status"] == "IN_DEVELOPMENT"
    assert formula["round_count"] == 2
    assert read_dossier(dossier["id"])["cert_status"] == "DENIED"
