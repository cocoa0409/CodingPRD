"""Transitive cascades: one buyer click reaching sibling sales, and a third
frivolous denial reaching an inspection on a sale no decision mentions."""
from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_created_at_ascending,
    assert_instant_equals,
    assert_ledger_batch_balanced,
    assert_ledger_rows,
    assert_policy_action,
    assert_unpaginated_meta,
    validate_unpaginated,
)
from test_helpers.constants import CLOCK_DEFAULT, FRAME_DAMAGE_POLICY, MECHANICAL_POLICY
from test_helpers.factories import (
    accept_round,
    create_buyer,
    create_case,
    create_evidence,
    create_inspection,
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
SIBLING_SALES = [
    {"sale_price_cents": 900000, "announced_odometer_miles": 61000, "light_channel": "GREEN"},
    {"sale_price_cents": 1100000, "announced_odometer_miles": 52000, "light_channel": "GREEN"},
    {"sale_price_cents": 780000, "announced_odometer_miles": 99000, "light_channel": "YELLOW"},
]


def _four_sale_accept_world(api):
    """Four in-window sales for one consignor, with a single OPEN 200000-cent
    offer standing on the first of them."""
    seller = create_seller(api)
    buyer = create_buyer(api)
    create_policy(api, FRAME_DAMAGE_POLICY)
    sale1 = create_sale(api, seller["id"], buyer["id"], light_channel="RED")
    siblings = [
        create_sale(api, seller["id"], buyer["id"], **overrides)
        for overrides in SIBLING_SALES
    ]
    case = create_case(api, sale1["id"], buyer["id"], **FRAME_CASE)
    create_evidence(
        api,
        case["id"],
        buyer["id"],
        evidence_type="INSPECTION_REPORT",
        repair_estimate_cents=285000,
    )
    create_evidence(
        api, case["id"], buyer["id"], evidence_type="THIRD_PARTY_VERIFICATION"
    )
    case = open_review(api, case["id"])
    round_row = seller_response(
        api,
        case["id"],
        seller["id"],
        "OFFER_REPAIR_ALLOWANCE",
        200000,
        "Goodwill allowance offered",
    )
    return {
        "seller": seller,
        "buyer": buyer,
        "sale1": sale1,
        "siblings": siblings,
        "case": case,
        "round": round_row,
    }


def test_one_acceptance_walks_five_hops_from_the_round_to_the_consignor_tier(api):
    """Accepting the offer resolves the round and the case, recomputes the
    scorecard to 1 upheld over 4 in-window sales, and blocks the consignor with a
    single BLOCK policy action attributed to the triggering case.

    PRD: "**Hop 4.** Because the recomputed rolling rate may have crossed a tier
    threshold, the consignor's `policy_tier` advances and a `SellerPolicyAction`
    row is appended recording the move."

    Design: Difficulty/transitive_cascade/upheld_accept_cascades_five_hops_to_sibling_sale_settlement_holds
    """
    world = _four_sale_accept_world(api)
    case_id = world["case"]["id"]
    seller_id = world["seller"]["id"]

    decision = accept_round(api, case_id, world["round"]["id"], world["buyer"]["id"])
    assert decision["allowance_variant"] == "NEGOTIATED_ACCEPT"
    assert decision["allowance_cents"] == 200000

    case = validate_success(api.get_case(case_id, admin_headers()), 200)
    assert case["status"] == "RESOLVED_ALLOWANCE"

    sale1 = validate_success(api.get_sale(world["sale1"]["id"], admin_headers()), 200)
    assert sale1["arbitration_status"] == "RESOLVED"
    assert sale1["open_case_count"] == 0

    scorecard = validate_success(api.get_seller_scorecard(seller_id, admin_headers()), 200)
    assert scorecard["rolling_window_sales_count"] == 4
    assert scorecard["rolling_window_upheld_count"] == 1
    assert scorecard["rolling_arbitration_rate_bps"] == 2500
    assert scorecard["lifetime_sales_count"] == 4
    assert scorecard["lifetime_upheld_count"] == 1
    assert scorecard["lifetime_arbitration_rate_bps"] == 2500

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
        triggered_by_case_id=case_id,
    )

    case_actions, case_actions_meta = validate_unpaginated(
        api.list_case_policy_actions(case_id, admin_headers())
    )
    assert_unpaginated_meta(case_actions_meta, 1)
    assert case_actions[0]["id"] == actions[0]["id"]


def test_the_hold_cascade_skips_the_claimed_sale_and_holds_the_other_three(api):
    """The block places settlement holds on the three undisputed sales only; the
    sale the claim was filed on is excluded because its arbitration dimension is
    no longer NONE, and no money is posted against any of the three.

    PRD: "every sale of that consignor whose `settlement_status` is `UNSETTLED`
    **and** whose `arbitration_status` is `NONE` has `settlement_hold` set to
    true, processed in ascending `created_at` order, each sale's `version` rising
    by 1."

    Design: Difficulty/transitive_cascade/upheld_accept_cascades_five_hops_to_sibling_sale_settlement_holds
    """
    world = _four_sale_accept_world(api)

    accept_round(api, world["case"]["id"], world["round"]["id"], world["buyer"]["id"])

    for sibling in world["siblings"]:
        sale = validate_success(api.get_sale(sibling["id"], admin_headers()), 200)
        assert sale["settlement_hold"] is True
        assert sale["settlement_status"] == "UNSETTLED"
        entries, entries_meta = validate_unpaginated(
            api.list_sale_ledger_entries(sibling["id"], admin_headers())
        )
        assert_unpaginated_meta(entries_meta, 0)
        assert entries == []

    sale1 = validate_success(api.get_sale(world["sale1"]["id"], admin_headers()), 200)
    assert sale1["settlement_hold"] is False

    case_entries, case_meta = validate_unpaginated(
        api.list_case_ledger_entries(world["case"]["id"], admin_headers())
    )
    assert_unpaginated_meta(case_meta, 2)
    assert_ledger_rows(
        case_entries,
        [
            {"party": "BUYER", "entry_type": "REPAIR_ALLOWANCE", "amount_signed_cents": 200000},
            {"party": "SELLER", "entry_type": "REPAIR_ALLOWANCE", "amount_signed_cents": -200000},
        ],
    )
    assert_ledger_batch_balanced(case_entries, "the accepted allowance pair")


# --- The frivolous-denial chain ----------------------------------------------

FRIVOLOUS_SALES = [
    {"sale_price_cents": 1450000, "announced_odometer_miles": 84000},
    {"sale_price_cents": 900000, "announced_odometer_miles": 61000},
    {"sale_price_cents": 1100000, "announced_odometer_miles": 52000},
    {"sale_price_cents": 780000, "announced_odometer_miles": 99000},
]
FRIVOLOUS_COMPLAINTS = [
    "Transmission slips in third",
    "Engine misfire under load",
    "Rear differential whine",
]


def _frivolous_chain_world(api, denials: int):
    """Four sales, an outstanding STANDARD inspection on sale 4, and `denials`
    already-decided FRIVOLOUS_DENIED cases; the next case sits ready in
    ARBITRATOR_REVIEW."""
    seller = create_seller(api)
    buyer = create_buyer(api)
    create_policy(api, MECHANICAL_POLICY)
    sales = [
        create_sale(
            api, seller["id"], buyer["id"], light_channel="YELLOW", **overrides
        )
        for overrides in FRIVOLOUS_SALES
    ]
    inspection = create_inspection(
        api, sales[3]["id"], buyer["id"], program_tier="STANDARD"
    )
    cases = []
    for index in range(denials + 1):
        case = create_case(
            api,
            sales[index]["id"],
            buyer["id"],
            defect_class="MECHANICAL",
            claim_amount_cents=100000,
            odometer_at_claim=FRIVOLOUS_SALES[index]["announced_odometer_miles"] + 100,
            complaint_text=FRIVOLOUS_COMPLAINTS[index],
        )
        create_evidence(
            api,
            case["id"],
            buyer["id"],
            evidence_type="INSPECTION_REPORT",
            repair_estimate_cents=100000,
        )
        open_review(api, case["id"])
        seller_response(
            api,
            case["id"],
            seller["id"],
            "DISPUTE",
            note="Unit was announced as-is on a yellow light",
        )
        if index < denials:
            decide_case(
                api,
                case["id"],
                "FRIVOLOUS_DENIED",
                fault_party="BUYER",
                rationale="No mechanical defect found in the submitted file",
            )
        cases.append(case)
    return {
        "seller": seller,
        "buyer": buyer,
        "sales": sales,
        "inspection": inspection,
        "cases": cases,
    }


def test_two_denials_stop_the_chain_at_fee_hold_with_the_inspection_outstanding(api):
    """After the first two denials the buyer is in FEE_HOLD carrying 75000 cents,
    and the outstanding inspection on the fourth sale is untouched.

    PRD: "**Hop 3.** Because the balance is now greater than 0, the buyer's
    `claim_privilege_status` moves `ACTIVE → FEE_HOLD` — unless the incremented
    `frivolous_claim_count` has reached 3, in which case the buyer goes
    `FEE_HOLD → SUSPENDED` instead, arriving at the suspension in the same
    request."

    Design: Difficulty/transitive_cascade/third_frivolous_denial_cascades_four_hops_to_inspection_expiry
    """
    world = _frivolous_chain_world(api, denials=2)

    buyer = validate_success(api.get_buyer(world["buyer"]["id"], admin_headers()), 200)
    assert buyer["claim_privilege_status"] == "FEE_HOLD"
    assert buyer["frivolous_claim_count"] == 2
    assert buyer["frivolous_fee_balance_cents"] == 75000

    inspections, meta = validate_unpaginated(
        api.list_sale_inspections(world["sales"][3]["id"], admin_headers())
    )
    assert_unpaginated_meta(meta, 1)
    assert inspections[0]["status"] == "REQUESTED"


def test_the_third_denial_clips_the_fee_at_the_cap_and_suspends_the_buyer(api):
    """The third assessment reads prior_frivolous_count 2 and a fee of 60000,
    clipped from the uncapped 75000, and drives the buyer to SUSPENDED.

    PRD: "The ladder is therefore 25000 cents for a buyer's first frivolous
    claim, 50000 for the second, and 60000 for the third, since 75000 is clipped
    by the cap."

    Design: Difficulty/transitive_cascade/third_frivolous_denial_cascades_four_hops_to_inspection_expiry
    """
    world = _frivolous_chain_world(api, denials=2)
    case3_id = world["cases"][2]["id"]
    buyer_id = world["buyer"]["id"]

    decision = decide_case(
        api,
        case3_id,
        "FRIVOLOUS_DENIED",
        fault_party="BUYER",
        rationale="Third unsupported mechanical claim; pattern of frivolous arbitration",
    )
    assert decision["outcome"] == "FRIVOLOUS_DENIED"
    assert decision["allowance_cents"] == 0
    assert decision["frivolous_fee_cents"] == 60000

    case = validate_success(api.get_case(case3_id, admin_headers()), 200)
    assert case["status"] == "DENIED"

    case_fees, case_fees_meta = validate_unpaginated(
        api.list_case_frivolous_fees(case3_id, admin_headers())
    )
    assert_unpaginated_meta(case_fees_meta, 1)
    assert case_fees[0]["prior_frivolous_count"] == 2
    assert case_fees[0]["fee_cents"] == 60000

    buyer_fees, buyer_fees_meta = validate_unpaginated(
        api.list_buyer_frivolous_fees(buyer_id, admin_headers())
    )
    assert_unpaginated_meta(buyer_fees_meta, 3)
    assert_created_at_ascending(buyer_fees, "buyer frivolous fees")
    assert [
        (row["prior_frivolous_count"], row["fee_cents"]) for row in buyer_fees
    ] == [(0, 25000), (1, 50000), (2, 60000)]

    buyer = validate_success(api.get_buyer(buyer_id, admin_headers()), 200)
    assert buyer["frivolous_claim_count"] == 3
    assert buyer["frivolous_fee_balance_cents"] == 135000
    assert buyer["claim_privilege_status"] == "SUSPENDED"
    assert buyer["open_claim_count"] == 0
    assert buyer["lifetime_claim_count"] == 3


def test_the_suspension_expires_an_outstanding_inspection_on_an_unrelated_sale(api):
    """The fourth hop reaches a REQUESTED inspection on a sale no decision in the
    chain refers to, with the clock never advancing past its window end.

    PRD: "**Hop 4.** Because the buyer has reached `SUSPENDED`, every post-sale
    inspection still in `REQUESTED` on any sale whose buyer is this buyer is
    moved to `EXPIRED`, processed in ascending `created_at` order, each such
    inspection's `version` rising by 1."

    Design: Difficulty/transitive_cascade/third_frivolous_denial_cascades_four_hops_to_inspection_expiry
    """
    world = _frivolous_chain_world(api, denials=2)
    window_end = world["inspection"]["window_end_utc"]

    decide_case(api, world["cases"][2]["id"], "FRIVOLOUS_DENIED", fault_party="BUYER")

    inspections, meta = validate_unpaginated(
        api.list_sale_inspections(world["sales"][3]["id"], admin_headers())
    )
    assert_unpaginated_meta(meta, 1)
    assert inspections[0]["status"] == "EXPIRED"
    assert_instant_equals(inspections[0]["window_end_utc"], window_end, "window_end_utc")
    assert inspections[0]["completed_at_utc"] is None


def test_a_frivolous_denial_carries_no_seller_consequence_and_posts_no_sale_money(api):
    """Denials are excluded from the scorecard arithmetic, so the consignor's
    rate stays 0 with no policy action, and the three denied sales carry no sale
    money at all — only the balanced frivolous-fee pair each denial assessed.

    PRD: "Decisions with `outcome` `CLAIM_DENIED` or `FRIVOLOUS_DENIED` are
    excluded from the arithmetic entirely."

    PRD: "Each row names the sale it belongs to through `sale_id`" and "A
    `FRIVOLOUS_FEE_ASSESSED` pair is posted, debiting the buyer the fee and
    crediting the auction house the same."

    Design: Difficulty/transitive_cascade/third_frivolous_denial_cascades_four_hops_to_inspection_expiry
    """
    world = _frivolous_chain_world(api, denials=2)
    seller_id = world["seller"]["id"]

    decide_case(api, world["cases"][2]["id"], "FRIVOLOUS_DENIED", fault_party="BUYER")

    scorecard = validate_success(api.get_seller_scorecard(seller_id, admin_headers()), 200)
    assert scorecard["rolling_window_sales_count"] == 4
    assert scorecard["rolling_window_upheld_count"] == 0
    assert scorecard["rolling_arbitration_rate_bps"] == 0
    assert scorecard["policy_tier"] == "GOOD_STANDING"

    actions, actions_meta = validate_unpaginated(
        api.list_seller_policy_actions(seller_id, admin_headers())
    )
    assert_unpaginated_meta(actions_meta, 0)
    assert actions == []

    # The fee ladder walks 25000, 50000, 60000 across the three denials, and every
    # ledger row names the sale it belongs to, so each denied sale carries exactly
    # its own balanced FRIVOLOUS_FEE_ASSESSED pair and no sale money whatever.
    for sale, fee_cents in zip(world["sales"][:3], [25000, 50000, 60000]):
        row = validate_success(api.get_sale(sale["id"], admin_headers()), 200)
        assert row["arbitration_status"] == "RESOLVED"
        assert row["settlement_status"] == "UNSETTLED"
        entries, entries_meta = validate_unpaginated(
            api.list_sale_ledger_entries(sale["id"], admin_headers())
        )
        assert_unpaginated_meta(entries_meta, 2)
        assert_ledger_batch_balanced(entries, "the frivolous fee pair")
        assert_ledger_rows(
            entries,
            [
                {
                    "party": "BUYER",
                    "entry_type": "FRIVOLOUS_FEE_ASSESSED",
                    "amount_signed_cents": -fee_cents,
                },
                {
                    "party": "AUCTION",
                    "entry_type": "FRIVOLOUS_FEE_ASSESSED",
                    "amount_signed_cents": fee_cents,
                },
            ],
        )
