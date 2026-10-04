"""Cross-entity state dependencies: quote acceptance gated on the product's
state, slot commit gated on the line review's state, and launch-plan approval
re-checking dossier compliance (including a lazily lapsed certification).
"""

from test_helpers import (
    CLOCK_PAST_CERT_EXPIRY,
    TEST_USERS,
    ApiErrorId,
    accept_quote,
    advance_line_review_to_decided,
    advance_line_review_to_reviewing,
    commit_slot,
    create_quote,
    evaluate_quote,
    read_cost_quote,
    read_dossier,
    read_launch_plan,
    read_line_review,
    read_planogram_slot,
    read_product,
    set_clock,
    setup_locked_plan,
    setup_open_review_with_slot,
    setup_product_with_approved_formula,
    transition_product,
    validate_error,
)

_SOURCING = TEST_USERS["sourcing_lead_headers"]
_PLANNER = TEST_USERS["retail_planner_headers"]
_PM = TEST_USERS["product_manager_headers"]


def _setup_quote_pending_on_formulation_product():
    ctx = setup_product_with_approved_formula()
    ctx["quote"] = create_quote(ctx["product"]["id"], ctx["manufacturer"]["id"])
    evaluate_quote(ctx["quote"]["id"])
    return ctx


def test_quote_accept_blocked_while_product_in_formulation(api):
    """PRD §3.5: "Acceptance — moving an `UNDER_EVALUATION` quote to
    `ACCEPTED` — is the most heavily gated transition in the platform, and its
    checks are: the product must be in `SOURCING`, else
    `ERR_PRODUCT_NOT_SOURCING`; ..."
    The quote is in a valid from-state and the formula is APPROVED, yet the
    product's FORMULATION state blocks acceptance.

    Design: Difficulty/cross_entity_state_dependency/quote_accept_requires_product_in_sourcing
    """
    ctx = _setup_quote_pending_on_formulation_product()

    response = api.patch_cost_quote(ctx["quote"]["id"], {"status": "ACCEPTED"}, _SOURCING)

    validate_error(response, ApiErrorId.ERR_PRODUCT_NOT_SOURCING.value)
    assert read_product(ctx["product"]["id"])["status"] == "FORMULATION"
    assert read_cost_quote(ctx["quote"]["id"])["status"] == "UNDER_EVALUATION"


def test_quote_accept_succeeds_once_product_reaches_sourcing(api):
    """PRD §3.5: "Acceptance — moving an `UNDER_EVALUATION` quote to
    `ACCEPTED` — is the most heavily gated transition in the platform, and its
    checks are: the product must be in `SOURCING`, else
    `ERR_PRODUCT_NOT_SOURCING`; an approved formula project for the product
    must exist, else `ERR_FORMULA_NOT_APPROVED`; ..."
    Advancing the product to SOURCING opens the gate: the same quote accepts,
    pinning the approved formula's version.

    Design: Difficulty/cross_entity_state_dependency/quote_accept_requires_product_in_sourcing
    """
    ctx = _setup_quote_pending_on_formulation_product()
    transition_product(ctx["product"]["id"], "SOURCING")

    accepted = accept_quote(ctx["quote"]["id"])

    assert accepted["status"] == "ACCEPTED"
    assert accepted["pinned_formula_version"] == 1
    assert accepted["accepted_at"] is not None


def test_slot_commit_blocked_while_review_reviewing(api):
    """PRD §3.7: "A slot starts `PROPOSED`. Once its review has reached
    `DECIDED` — else the commit is rejected with `ERR_INVALID_STATE` — the
    planner may commit it, moving it to `COMMITTED`."
    The review sits in REVIEWING (window ended, not yet decided), so the
    commit is rejected.

    Design: Difficulty/cross_entity_state_dependency/slot_commit_requires_line_review_decided
    """
    ctx = setup_open_review_with_slot()
    ctx["line_review"] = advance_line_review_to_reviewing(ctx["line_review"]["id"])

    response = api.patch_planogram_slot(ctx["slot"]["id"], {"status": "COMMITTED"}, _PLANNER)

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
    assert read_planogram_slot(ctx["slot"]["id"])["status"] == "PROPOSED"
    assert read_line_review(ctx["line_review"]["id"])["status"] == "REVIEWING"


def test_slot_commit_opens_once_review_is_decided(api):
    """PRD §3.7: "A slot starts `PROPOSED`. Once its review has reached
    `DECIDED` — else the commit is rejected with `ERR_INVALID_STATE` — the
    planner may commit it, moving it to `COMMITTED`."
    After the review reaches DECIDED, the same commit succeeds and stamps
    committed_at.

    Design: Difficulty/cross_entity_state_dependency/slot_commit_requires_line_review_decided
    """
    ctx = setup_open_review_with_slot()
    ctx["line_review"] = advance_line_review_to_decided(ctx["line_review"]["id"])

    committed = commit_slot(ctx["slot"]["id"])

    assert committed["status"] == "COMMITTED"
    assert committed["committed_at"] is not None


def test_plan_approve_blocked_by_lazily_lapsed_cert(api):
    """PRD §3.6: "Thereafter the certification lapses lazily: any read or
    write of the dossier once the logical clock has passed `cert_expires_at`
    moves the dimension to `LAPSED`."
    PRD §3.8: "...the product's dossier must be fully compliant with a
    certification that has not lapsed, else `ERR_COMPLIANCE_GATE_FAILED`; ..."
    Certified at 2026-09-01 (expires 2027-09-01); at 2027-09-02 the dossier
    read lapses the cert and the approve is rejected.

    Design: Difficulty/cross_entity_state_dependency/plan_approve_blocked_by_lapsed_cert
    """
    ctx = setup_locked_plan()
    set_clock(CLOCK_PAST_CERT_EXPIRY)

    dossier = read_dossier(ctx["dossier"]["id"])
    assert dossier["cert_status"] == "LAPSED"
    assert dossier["compliant"] is False

    response = api.patch_launch_plan(ctx["plan"]["id"], {"status": "APPROVED"}, _PM)

    validate_error(response, ApiErrorId.ERR_COMPLIANCE_GATE_FAILED.value)
    assert read_launch_plan(ctx["plan"]["id"])["status"] == "QUANTITY_LOCKED"


def test_lapsed_cert_cascade_reverts_launch_ready_product(api):
    """PRD §3.6: "Both denial and lapse fire the product-reversion cascade: if
    the product is in `COMPLIANCE_GATE` or `LAUNCH_READY`, it reverts directly
    to `FORMULATION` — with no intermediate state — and that reversion in turn
    invalidates every accepted quote and reopens every approved formula
    project exactly as the manual reformulation of §3.3 does."
    Discovered after the 2027-09-01 expiry, the lapse reverts the LAUNCH_READY
    product to FORMULATION and invalidates its ACCEPTED quote.

    Design: Difficulty/cross_entity_state_dependency/plan_approve_blocked_by_lapsed_cert
    """
    ctx = setup_locked_plan()
    set_clock(CLOCK_PAST_CERT_EXPIRY)

    dossier = read_dossier(ctx["dossier"]["id"])
    assert dossier["cert_status"] == "LAPSED"
    assert dossier["cert_expires_at"] == "2027-09-01T00:00:00Z"

    assert read_product(ctx["product"]["id"])["status"] == "FORMULATION"
    assert read_cost_quote(ctx["quote"]["id"])["status"] == "INVALIDATED"
