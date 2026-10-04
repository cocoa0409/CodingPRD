"""Non-linear state machines: the tender retender loop and the claim dispute loop."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    CUSTOMER_SERVICE_HEADERS,
    PROCUREMENT_LEAD_HEADERS,
    QA_LEAD_HEADERS,
    fixtures,
)


def test_retender_reverts_bids_and_panels_then_second_cycle_awards(api):
    """Retender loops EVALUATING -> OPEN, resetting bids to SUBMITTED and panels to SCORED.

    PRD §3.4: "When evaluation leaves fewer than `min_sources` distinct suppliers holding `ELIGIBLE` bids, the tender cannot be awarded but it is not dead: a retender loops it `EVALUATING → OPEN`. Every bid of the tender reverts to `SUBMITTED` with its `award_score` reset to null — including bids that had been `DISQUALIFIED`, which return to `SUBMITTED` the same way — and every panel reverts `LOCKED → SCORED`. The cycle `OPEN → CLOSED → EVALUATING → OPEN` may repeat as often as procurement needs."

    Design: Difficulty/non_linear_state_machine/tender_retender_cycle_restores_open
    """
    category = fixtures.create_category(api)
    sup_a = fixtures.create_supplier(api, name="Sup A")
    sup_b = fixtures.create_supplier(api, name="Sup B")
    sup_c = fixtures.create_supplier(api, name="Sup C")
    product = fixtures.create_product(api, category["id"], unit_cost_cents=200)

    tender = fixtures.create_open_tender(api, product["id"], bid_ceiling_cents=1000)
    bid_a = fixtures.submit_bid(api, tender["id"], sup_a, 700)
    bid_b = fixtures.submit_bid(api, tender["id"], sup_b, 800)
    panel_a = fixtures.score_bid_panel(api, bid_a, 80, sample_code="BLIND-A1")
    fixtures.score_bid_panel(api, bid_b, 50, sample_code="BLIND-B1")
    validate_success(api.close_tender(tender["id"], PROCUREMENT_LEAD_HEADERS))
    validate_success(api.evaluate_tender(tender["id"], PROCUREMENT_LEAD_HEADERS))

    # Only supplier A is ELIGIBLE (B's panel scored 50 < 60): retender.
    reopened = validate_success(api.retender(tender["id"], PROCUREMENT_LEAD_HEADERS))
    assert reopened["status"] == "OPEN", (
        f"retender must loop EVALUATING -> OPEN, got {reopened['status']}"
    )

    read_bid_a = validate_success(api.get_bid(bid_a["id"], PROCUREMENT_LEAD_HEADERS))
    read_bid_b = validate_success(api.get_bid(bid_b["id"], PROCUREMENT_LEAD_HEADERS))
    read_panel_a = validate_success(api.get_panel(panel_a["id"], QA_LEAD_HEADERS))
    assert read_bid_a["status"] == "SUBMITTED" and read_bid_a["award_score"] is None
    assert read_bid_b["status"] == "SUBMITTED" and read_bid_b["award_score"] is None, (
        "a previously DISQUALIFIED bid returns to SUBMITTED the same way"
    )
    assert read_panel_a["status"] == "SCORED", "panels revert LOCKED -> SCORED on retender"

    # Second cycle: a third supplier joins, panels are re-scored, award succeeds.
    bid_c = fixtures.submit_bid(api, tender["id"], sup_c, 750)
    fixtures.score_bid_panel(api, bid_c, 75, sample_code="BLIND-C1")
    validate_success(api.close_tender(tender["id"], PROCUREMENT_LEAD_HEADERS))
    validate_success(api.evaluate_tender(tender["id"], PROCUREMENT_LEAD_HEADERS))
    awarded = validate_success(
        api.award_tender(
            tender["id"],
            {"primary_bid_id": bid_a["id"], "secondary_bid_id": bid_c["id"]},
            PROCUREMENT_LEAD_HEADERS,
        )
    )
    assert awarded["status"] == "AWARDED"

    read_bid_c = validate_success(api.get_bid(bid_c["id"], PROCUREMENT_LEAD_HEADERS))
    assert read_bid_c["award_score"] == 61.0, (
        f"0.5*75 + 0.3*25 + 0.2*80 = 61.0, got {read_bid_c['award_score']}"
    )


def test_retendered_tender_accepts_a_rebid_from_a_returned_supplier(api):
    """After retender, a supplier whose bid reverted may participate again.

    PRD §3.4: "Every bid of the tender reverts to `SUBMITTED` with its `award_score` reset to null — including bids that had been `DISQUALIFIED`, which return to `SUBMITTED` the same way — and every panel reverts `LOCKED → SCORED`. The cycle `OPEN → CLOSED → EVALUATING → OPEN` may repeat as often as procurement needs."

    Design: Difficulty/non_linear_state_machine/tender_retender_cycle_restores_open
    """
    category = fixtures.create_category(api)
    sup_a = fixtures.create_supplier(api, name="Sup A")
    sup_b = fixtures.create_supplier(api, name="Sup B")
    sup_c = fixtures.create_supplier(api, name="Sup C")
    product = fixtures.create_product(api, category["id"])

    tender = fixtures.create_open_tender(api, product["id"], bid_ceiling_cents=1000)
    bid_a = fixtures.submit_bid(api, tender["id"], sup_a, 700)
    bid_b = fixtures.submit_bid(api, tender["id"], sup_b, 800)
    fixtures.score_bid_panel(api, bid_a, 80, sample_code="BLIND-A1")
    fixtures.score_bid_panel(api, bid_b, 40, sample_code="BLIND-B1")
    validate_success(api.close_tender(tender["id"], PROCUREMENT_LEAD_HEADERS))
    validate_success(api.evaluate_tender(tender["id"], PROCUREMENT_LEAD_HEADERS))

    reopened = validate_success(api.retender(tender["id"], PROCUREMENT_LEAD_HEADERS))
    assert reopened["status"] == "OPEN"

    # The reopened tender admits a fresh bid from a supplier that never bid.
    bid_c = fixtures.submit_bid(api, tender["id"], sup_c, 600)
    fixtures.score_bid_panel(api, bid_c, 90, sample_code="BLIND-C1")
    validate_success(api.close_tender(tender["id"], PROCUREMENT_LEAD_HEADERS))
    validate_success(api.evaluate_tender(tender["id"], PROCUREMENT_LEAD_HEADERS))

    read_bid_c = validate_success(api.get_bid(bid_c["id"], PROCUREMENT_LEAD_HEADERS))
    # 0.5*90 + 0.3*40 + 0.2*80 = 45 + 12 + 16 = 73.0
    assert read_bid_c["award_score"] == 73.0, (
        f"rejoined supplier: 0.5*90 + 0.3*40 + 0.2*80 = 73.0, got {read_bid_c['award_score']}"
    )
    assert read_bid_c["status"] == "ELIGIBLE"


def test_claim_dispute_review_cycle_then_approval(api):
    """The UNDER_REVIEW -> DISPUTED -> UNDER_REVIEW loop closes and later approves.

    PRD §3.9: "Review moves a claim `FILED → UNDER_REVIEW`, and the same action re-opens a `DISPUTED` claim — the cycle `UNDER_REVIEW → DISPUTED → UNDER_REVIEW` may repeat."
    PRD §3.9: "Approval moves it `UNDER_REVIEW → APPROVED` and prices the refund: for a `QUALITY_DEFECT` claim the `refund_amount_cents` is the `unit_price_cents` multiplied by the `quantity` and doubled, rounded half-up to whole cents; for `DAMAGED` or `OTHER` the same inputs are refunded at face value, identically rounded."

    Design: Difficulty/non_linear_state_machine/claim_dispute_review_cycle
    """
    world = fixtures.claims_world(api)
    claim = fixtures.file_claim(
        api, world["product"]["id"], world["store"]["id"],
        quantity=1, unit_price_cents=349, reason="QUALITY_DEFECT",
    )

    validate_success(api.review_claim(claim["id"], CUSTOMER_SERVICE_HEADERS))
    disputed = validate_success(api.dispute_claim(claim["id"], CUSTOMER_SERVICE_HEADERS))
    assert disputed["status"] == "DISPUTED"

    back = validate_success(api.review_claim(claim["id"], CUSTOMER_SERVICE_HEADERS))
    assert back["status"] == "UNDER_REVIEW", "review re-opens a DISPUTED claim"

    approved = validate_success(api.approve_claim(claim["id"], CUSTOMER_SERVICE_HEADERS))
    assert approved["status"] == "APPROVED"
    assert approved["refund_amount_cents"] == 698, (
        f"349*1 doubled = 698, got {approved['refund_amount_cents']}"
    )
    assert approved["version"] == 5, (
        f"create(1) + review + dispute + review + approve = version 5, got {approved['version']}"
    )


def test_claim_dispute_loop_may_repeat(api):
    """The dispute loop may run more than once before resolution.

    PRD §3.9: "Review moves a claim `FILED → UNDER_REVIEW`, and the same action re-opens a `DISPUTED` claim — the cycle `UNDER_REVIEW → DISPUTED → UNDER_REVIEW` may repeat."

    Design: Difficulty/non_linear_state_machine/claim_dispute_review_cycle
    """
    world = fixtures.claims_world(api)
    claim = fixtures.file_claim(
        api, world["product"]["id"], world["store"]["id"], reason="OTHER",
    )

    validate_success(api.review_claim(claim["id"], CUSTOMER_SERVICE_HEADERS))
    for _ in range(2):
        d = validate_success(api.dispute_claim(claim["id"], CUSTOMER_SERVICE_HEADERS))
        assert d["status"] == "DISPUTED"
        r = validate_success(api.review_claim(claim["id"], CUSTOMER_SERVICE_HEADERS))
        assert r["status"] == "UNDER_REVIEW"

    rejected = validate_success(api.reject_claim(claim["id"], CUSTOMER_SERVICE_HEADERS))
    assert rejected["status"] == "REJECTED"
