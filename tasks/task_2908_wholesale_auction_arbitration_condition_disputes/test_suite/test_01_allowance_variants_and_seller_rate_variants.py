"""The two dual-variant calculations: the money variants of a repair allowance
and the risk variants of a consignor's arbitration rate."""
from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_instant_equals,
    assert_ledger_batch_balanced,
    assert_ledger_rows,
    assert_policy_action,
    assert_transport_totals,
    assert_unpaginated_meta,
    validate_unpaginated,
)
from test_helpers.constants import CLOCK_DEFAULT, FRAME_DAMAGE_POLICY, TITLE_BRANDED_POLICY
from test_helpers.factories import (
    accept_round,
    build_arbitrator_review_world,
    build_negotiation_world,
    create_buyer,
    create_case,
    create_evidence,
    create_policy,
    create_sale,
    create_seller,
    decide_case,
    open_review,
    seller_response,
)
from test_helpers.test_users import admin_headers

FRAME_CASE = {
    "defect_class": "FRAME_DAMAGE",
    "claim_amount_cents": 285000,
    "odometer_at_claim": 84120,
    "complaint_text": "Frame rail repair found on the lift",
}
RED_SALE = {"light_channel": "RED"}


def _frame_negotiation_world(api, seller_offer_cents=200000):
    return build_negotiation_world(
        api,
        seller_offer_cents=seller_offer_cents,
        policy_presets=[FRAME_DAMAGE_POLICY],
        sale_overrides=dict(RED_SALE),
        case_overrides=dict(FRAME_CASE),
        repair_estimate_cents=285000,
        extra_evidence_types=["THIRD_PARTY_VERIFICATION"],
    )


def _frame_disputed_world(api):
    return build_arbitrator_review_world(
        api,
        policy_presets=[FRAME_DAMAGE_POLICY],
        sale_overrides=dict(RED_SALE),
        case_overrides=dict(FRAME_CASE),
        repair_estimate_cents=285000,
        extra_evidence_types=["THIRD_PARTY_VERIFICATION"],
        response_type="DISPUTE",
    )


def test_negotiated_acceptance_records_the_accepted_offer_and_the_formula_side_by_side(api):
    """A buyer accepting a 200000-cent offer on a RED-light frame claim whose
    verified estimate is 285000 gets allowance_cents 200000 while the decision
    still stores the 171000 the formula would have produced.

    PRD: "Under `NEGOTIATED_ACCEPT`, reached when a buyer accepts a standing
    offer as described in §3.6, `allowance_cents` is the accepted round's
    `seller_offer_cents` and `computed_award_cents` is stored alongside it for
    comparison without constraining it."

    Design: Difficulty/dual_variant_calc/allowance_negotiated_accept_exceeds_arbitrator_formula
    """
    world = _frame_negotiation_world(api)

    decision = accept_round(
        api, world["case"]["id"], world["round"]["id"], world["buyer"]["id"]
    )

    assert decision["allowance_variant"] == "NEGOTIATED_ACCEPT"
    assert decision["allowance_cents"] == 200000
    assert decision["computed_award_cents"] == 171000
    assert decision["allowance_cents"] - decision["computed_award_cents"] == 29000
    assert decision["outcome"] == "REPAIR_ALLOWANCE"
    assert decision["fault_party"] == "SELLER"
    assert_transport_totals(decision, total=0, buyer=0, seller=0, auction=0)


def test_negotiated_acceptance_closes_the_round_and_posts_a_two_row_allowance_pair(api):
    """The accepted round reaches ACCEPTED, the case reaches RESOLVED_ALLOWANCE
    and the ledger carries exactly the balanced REPAIR_ALLOWANCE pair.

    PRD: "**Hop 1.** The round moves `OPEN → ACCEPTED` and the case moves
    `NEGOTIATION → RESOLVED_ALLOWANCE`."

    Design: Difficulty/dual_variant_calc/allowance_negotiated_accept_exceeds_arbitrator_formula
    """
    world = _frame_negotiation_world(api)
    case_id = world["case"]["id"]

    accept_round(api, case_id, world["round"]["id"], world["buyer"]["id"])

    case = validate_success(api.get_case(case_id, admin_headers()), 200)
    assert case["status"] == "RESOLVED_ALLOWANCE"

    rounds, rounds_meta = validate_unpaginated(
        api.list_negotiation_rounds(case_id, admin_headers())
    )
    assert_unpaginated_meta(rounds_meta, 1)
    assert rounds[0]["status"] == "ACCEPTED"

    entries, entries_meta = validate_unpaginated(
        api.list_case_ledger_entries(case_id, admin_headers())
    )
    assert_unpaginated_meta(entries_meta, 2)
    assert_ledger_batch_balanced(entries, "the REPAIR_ALLOWANCE pair")
    assert_ledger_rows(
        entries,
        [
            {
                "party": "BUYER",
                "entry_type": "REPAIR_ALLOWANCE",
                "amount_signed_cents": 200000,
            },
            {
                "party": "SELLER",
                "entry_type": "REPAIR_ALLOWANCE",
                "amount_signed_cents": -200000,
            },
        ],
    )


def test_arbitrator_award_is_clipped_to_the_formula_below_the_requested_figure(api):
    """On identical case data an officer asking for 250000 receives
    min(250000, 171000) = 171000, so the award variant is bounded where the
    negotiated variant was not.

    PRD: "Under `ARBITRATOR_AWARD`, reached when an officer rules a repair
    allowance, `allowance_cents` is the smaller of the
    `requested_allowance_cents` figure and `computed_award_cents` — the officer
    can never award more than the formula supports and never more than was asked
    for."

    Design: Difficulty/dual_variant_calc/allowance_arbitrator_award_clipped_by_severity_formula
    """
    world = _frame_disputed_world(api)

    decision = decide_case(
        api,
        world["case"]["id"],
        "REPAIR_ALLOWANCE",
        fault_party="SELLER",
        requested_allowance_cents=250000,
        rationale="Frame repair substantiated; award set by the severity formula",
    )

    assert decision["allowance_variant"] == "ARBITRATOR_AWARD"
    assert decision["computed_award_cents"] == 171000
    assert decision["allowance_cents"] == 171000
    assert decision["allowance_cents"] != 250000
    assert decision["allowance_cents"] != 200000
    assert decision["requested_allowance_cents"] == 250000


def test_arbitrator_allowance_leaves_the_settlement_dimension_untouched(api):
    """The awarded case reaches RESOLVED_ALLOWANCE while its sale stays
    UNSETTLED and the ledger carries the balanced pair at the awarded figure.

    PRD: "The sale's `settlement_status` is left completely untouched — the
    allowance branch never reverses proceeds."

    Design: Difficulty/dual_variant_calc/allowance_arbitrator_award_clipped_by_severity_formula
    """
    world = _frame_disputed_world(api)
    case_id = world["case"]["id"]

    decide_case(
        api,
        case_id,
        "REPAIR_ALLOWANCE",
        fault_party="SELLER",
        requested_allowance_cents=250000,
    )

    case = validate_success(api.get_case(case_id, admin_headers()), 200)
    assert case["status"] == "RESOLVED_ALLOWANCE"

    sale = validate_success(api.get_sale(world["sale"]["id"], admin_headers()), 200)
    assert sale["settlement_status"] == "UNSETTLED"

    entries, entries_meta = validate_unpaginated(
        api.list_case_ledger_entries(case_id, admin_headers())
    )
    assert_unpaginated_meta(entries_meta, 2)
    assert_ledger_batch_balanced(entries, "the awarded REPAIR_ALLOWANCE pair")
    buyer_rows = [row for row in entries if row["party"] == "BUYER"]
    assert len(buyer_rows) == 1
    assert buyer_rows[0]["amount_signed_cents"] == 171000


# --- The risk-domain dual variant --------------------------------------------

IN_WINDOW_HAMMER = "2026-07-01T00:00:00.000Z"
OUT_OF_WINDOW_HAMMER = "2026-03-01T00:00:00.000Z"


def _five_sale_seller_world(api):
    """Four sales inside the 90-day window and one outside it, then one upheld
    TITLE_BRANDED claim on the first in-window sale."""
    seller = create_seller(api)
    buyer = create_buyer(api)
    create_policy(api, TITLE_BRANDED_POLICY)
    sales = [
        create_sale(
            api,
            seller["id"],
            buyer["id"],
            hammer_time_utc=IN_WINDOW_HAMMER,
            title_status="BRANDED_SALVAGE",
        )
    ]
    for _ in range(3):
        sales.append(
            create_sale(
                api, seller["id"], buyer["id"], hammer_time_utc=IN_WINDOW_HAMMER
            )
        )
    sales.append(
        create_sale(
            api, seller["id"], buyer["id"], hammer_time_utc=OUT_OF_WINDOW_HAMMER
        )
    )
    case = create_case(
        api,
        sales[0]["id"],
        buyer["id"],
        defect_class="TITLE_BRANDED",
        claim_amount_cents=100000,
        odometer_at_claim=84300,
        complaint_text="Title came back branded salvage, announced as clean",
    )
    create_evidence(api, case["id"], buyer["id"], evidence_type="TITLE_DOCUMENT")
    create_evidence(
        api, case["id"], buyer["id"], evidence_type="THIRD_PARTY_VERIFICATION"
    )
    open_review(api, case["id"])
    seller_response(api, case["id"], seller["id"], "DISPUTE", note="Branding postdates the sale")
    return {"seller": seller, "buyer": buyer, "sales": sales, "case": case}


def test_rolling_rate_diverges_from_the_lifetime_rate_across_the_ninety_day_boundary(api):
    """One upheld claim over five lifetime sales, four of which hammered inside
    the window, reads 2500 bps rolling against 2000 bps lifetime.

    PRD: "Each variant's rate is then 0 when its sales count is 0, and otherwise
    10000 multiplied by the upheld count, divided by the sales count, rounded
    half up to a whole number of basis points — stored as
    `rolling_arbitration_rate_bps` and `lifetime_arbitration_rate_bps`
    respectively."

    Design: Difficulty/dual_variant_calc/seller_rate_rolling_diverges_from_lifetime_and_only_rolling_tiers
    """
    world = _five_sale_seller_world(api)

    decide_case(
        api,
        world["case"]["id"],
        "UNWIND",
        fault_party="SELLER",
        rationale="Branded title, unlimited window, sale unwound",
    )
    scorecard = validate_success(
        api.get_seller_scorecard(world["seller"]["id"], admin_headers()), 200
    )

    assert scorecard["rolling_window_sales_count"] == 4
    assert scorecard["lifetime_sales_count"] == 5
    assert scorecard["rolling_window_upheld_count"] == 1
    assert scorecard["lifetime_upheld_count"] == 1
    assert scorecard["rolling_arbitration_rate_bps"] == 2500
    assert scorecard["lifetime_arbitration_rate_bps"] == 2000
    assert (
        scorecard["rolling_arbitration_rate_bps"]
        - scorecard["lifetime_arbitration_rate_bps"]
        == 500
    )


def test_only_the_rolling_variant_moves_the_tier_and_blocks_the_consignor(api):
    """2500 bps rolling blocks the consignor outright; the 2000 bps lifetime
    figure would have stopped at PROBATION and never gets a vote.

    PRD: "**Only the rolling variant moves the tier.** The lifetime figures are
    reported for context and never drive a consequence, so a consignor with a
    dreadful lifetime record and a clean recent quarter stays in
    `GOOD_STANDING`."

    Design: Difficulty/dual_variant_calc/seller_rate_rolling_diverges_from_lifetime_and_only_rolling_tiers
    """
    world = _five_sale_seller_world(api)
    seller_id = world["seller"]["id"]

    decide_case(api, world["case"]["id"], "UNWIND", fault_party="SELLER")

    scorecard = validate_success(api.get_seller_scorecard(seller_id, admin_headers()), 200)
    assert scorecard["policy_tier"] == "BLOCKED"

    seller = validate_success(api.get_seller(seller_id, admin_headers()), 200)
    assert seller["policy_tier"] == "BLOCKED"
    assert_instant_equals(seller["blocked_at_utc"], CLOCK_DEFAULT, "blocked_at_utc")

    actions, actions_meta = validate_unpaginated(
        api.list_seller_policy_actions(seller_id, admin_headers())
    )
    assert_unpaginated_meta(actions_meta, 1)
    assert_policy_action(
        actions[0],
        action_type="BLOCK",
        from_tier="GOOD_STANDING",
        to_tier="BLOCKED",
        rolling_rate_bps=2500,
        triggered_by_case_id=world["case"]["id"],
    )
