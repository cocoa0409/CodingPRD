"""Cyclic state machines: the product reformulation loop (with its cross-entity
compensation on quotes and formula projects) and the compliance dossier's four
independently-evolving dimensions.
"""

from test_helpers import (
    approve_formula,
    assert_dossier_compliance_verdict,
    open_dossier,
    read_concept,
    read_cost_quote,
    read_dossier,
    read_formula_project,
    setup_compliance_gate_product,
    setup_compliant_gate_product,
    submit_dossier_review,
    submit_formula_sample,
    transition_product,
)


def test_reformulation_reverts_quote_and_reopens_formula(api):
    """PRD §3.3: "A manager may return a product from `SOURCING` or
    `COMPLIANCE_GATE` to `FORMULATION` at any time, and the compliance cascades
    of §3.6 can force the same reversion. Either way, the reversion has two
    side effects executed atomically with it: every `ACCEPTED` quote for the
    product transitions to `INVALIDATED`, which releases the quarterly
    production slot that quote was consuming, and every `APPROVED` formula
    project for the product reopens to `IN_DEVELOPMENT` with its `round_count`
    incremented by one."

    Design: Difficulty/non_linear_state_machine/product_reformulation_cycle_reverts_quote_and_formula
    """
    ctx = setup_compliance_gate_product()

    product = transition_product(ctx["product"]["id"], "FORMULATION")

    assert product["status"] == "FORMULATION"
    assert read_cost_quote(ctx["quote"]["id"])["status"] == "INVALIDATED"
    formula = read_formula_project(ctx["formula_project"]["id"])
    assert formula["status"] == "IN_DEVELOPMENT"
    assert formula["round_count"] == 2
    assert read_concept(ctx["concept"]["id"])["status"] == "IN_DEVELOPMENT"


def test_reformulation_loop_is_reenterable(api):
    """PRD §3.3: "Moving a product from `FORMULATION` to `SOURCING` requires
    that at least one formula project for the product is in `APPROVED` status,
    else the advance is rejected with `ERR_FORMULA_NOT_APPROVED`."
    After the COMPLIANCE_GATE -> FORMULATION loop reopens the approved project
    at round 2, re-approving it lets the product advance to SOURCING again —
    the cycle is legal and re-enterable.

    Design: Difficulty/non_linear_state_machine/product_reformulation_cycle_reverts_quote_and_formula
    """
    ctx = setup_compliance_gate_product()
    transition_product(ctx["product"]["id"], "FORMULATION")

    submit_formula_sample(ctx["formula_project"]["id"], ctx["manufacturer"]["id"])
    reapproved = approve_formula(ctx["formula_project"]["id"])
    assert reapproved["status"] == "APPROVED"
    assert reapproved["round_count"] == 2
    assert reapproved["formula_version"] == 2

    product = transition_product(ctx["product"]["id"], "SOURCING")
    assert product["status"] == "SOURCING"


def test_certification_advances_while_other_dimensions_are_pending(api):
    """PRD §3.6: "`compliant` is true exactly when `ingredient_status` is
    `CLEARED`, `claim_status` is `SUBSTANTIATED`, `cert_status` is `CERTIFIED`
    and has not lazily lapsed, and `registration_status` is `REGISTERED`."
    Certification reaches CERTIFIED while the other dimensions lag; with
    ingredient still PENDING the verdict is false. PRD §3.6: "Certification
    stamps `cert_expires_at` at exactly three hundred and sixty-five days
    after the review instant." — certified at 2026-09-01, so
    cert_expires_at == 2027-09-01T00:00:00Z.

    Design: Difficulty/non_linear_state_machine/dossier_parallel_dimensions_evolve_independently
    """
    ctx = setup_compliance_gate_product()
    dossier = open_dossier(ctx["product"]["id"])

    submit_dossier_review(dossier["id"], "CERTIFICATION", "APPLIED")
    submit_dossier_review(dossier["id"], "CERTIFICATION", "AUDITING")
    certified = submit_dossier_review(dossier["id"], "CERTIFICATION", "CERTIFIED")
    submit_dossier_review(dossier["id"], "REGISTRATION", "FILED")
    submit_dossier_review(dossier["id"], "REGISTRATION", "REGISTERED")
    submit_dossier_review(dossier["id"], "CLAIM", "SUBSTANTIATED")

    assert certified["cert_status"] == "CERTIFIED"
    assert certified["cert_expires_at"] == "2027-09-01T00:00:00Z"
    mid = read_dossier(dossier["id"])
    assert mid["ingredient_status"] == "PENDING"
    assert mid["compliant"] is False
    assert_dossier_compliance_verdict(mid)


def test_compliant_flips_true_only_when_all_four_dimensions_are_green(api):
    """PRD §3.6: "Compliance is a derived verdict: `compliant` is true exactly
    when `ingredient_status` is `CLEARED`, `claim_status` is `SUBSTANTIATED`,
    `cert_status` is `CERTIFIED` and has not lazily lapsed, and
    `registration_status` is `REGISTERED`."
    After the final INGREDIENT CLEARED review, all four dimensions are green
    and the verdict flips true.

    Design: Difficulty/non_linear_state_machine/dossier_parallel_dimensions_evolve_independently
    """
    ctx = setup_compliant_gate_product()
    dossier = read_dossier(ctx["dossier"]["id"])

    assert dossier["ingredient_status"] == "CLEARED"
    assert dossier["claim_status"] == "SUBSTANTIATED"
    assert dossier["cert_status"] == "CERTIFIED"
    assert dossier["registration_status"] == "REGISTERED"
    assert dossier["compliant"] is True
    assert_dossier_compliance_verdict(dossier)
