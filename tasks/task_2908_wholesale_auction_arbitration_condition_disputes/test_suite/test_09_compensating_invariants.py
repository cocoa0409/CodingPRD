"""Compensating invariants probed armed and disarmed in the same run: the sale
ledger's reversal pair, and the open-claim counters released by two paths."""
from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_created_at_ascending,
    assert_ledger_batch_balanced,
    assert_ledger_rows,
    assert_party_net_zero,
    assert_sweep_report,
    assert_transport_totals,
    assert_unpaginated_meta,
    validate_unpaginated,
)
from test_helpers.constants import FRAME_DAMAGE_POLICY, MECHANICAL_POLICY
from test_helpers.factories import (
    create_buyer,
    create_case,
    create_evidence,
    create_policy,
    create_sale,
    create_seller,
    decide_case,
    open_review,
    run_sweep,
    seller_response,
    set_clock,
    settle_sale,
    withdraw_case,
)
from test_helpers.test_users import admin_headers

SETTLED_CASE = {
    "defect_class": "FRAME_DAMAGE",
    "claim_amount_cents": 285000,
    "odometer_at_claim": 84120,
    "complaint_text": "Frame rail repair found on the lift",
}
UNSETTLED_CASE = {
    "defect_class": "FRAME_DAMAGE",
    "claim_amount_cents": 190000,
    "odometer_at_claim": 61080,
    "complaint_text": "Unibody kink behind the strut tower",
}


def _disputed_frame_case(api, sale, seller_id, buyer_id, overrides, estimate):
    case = create_case(api, sale["id"], buyer_id, **overrides)
    create_evidence(
        api,
        case["id"],
        buyer_id,
        evidence_type="INSPECTION_REPORT",
        repair_estimate_cents=estimate,
    )
    create_evidence(api, case["id"], buyer_id, evidence_type="THIRD_PARTY_VERIFICATION")
    open_review(api, case["id"])
    seller_response(
        api, case["id"], seller_id, "DISPUTE", note="Damage predates consignment"
    )
    return case


def _armed_and_disarmed_world(api):
    """Two disputed frame claims: one on a sale whose proceeds were released and
    one on a sale that was never settled."""
    seller = create_seller(api)
    buyer = create_buyer(api)
    create_policy(api, FRAME_DAMAGE_POLICY)
    sale1 = create_sale(api, seller["id"], buyer["id"], light_channel="RED")
    sale2 = create_sale(
        api,
        seller["id"],
        buyer["id"],
        sale_price_cents=900000,
        announced_odometer_miles=61000,
        light_channel="RED",
    )
    case1 = _disputed_frame_case(
        api, sale1, seller["id"], buyer["id"], SETTLED_CASE, 285000
    )
    settle_sale(api, sale1["id"])
    case2 = _disputed_frame_case(
        api, sale2, seller["id"], buyer["id"], UNSETTLED_CASE, 190000
    )
    return {
        "seller": seller,
        "buyer": buyer,
        "sale1": sale1,
        "sale2": sale2,
        "case1": case1,
        "case2": case2,
    }


def test_unwinding_a_settled_sale_posts_the_equal_and_opposite_reversal_pair(api):
    """With the compensation armed the sale ledger carries four rows summing to
    zero, and each party's own rows net to zero as well.

    PRD: "settle a sale and then unwind it, and the per-party net across the
    `SALE_PROCEEDS` and `SALE_PROCEEDS_REVERSAL` entry types is exactly zero for
    the buyer *and* exactly zero for the seller — not merely zero when the two
    parties are added together."

    Design: Difficulty/compensating_invariant/sale_ledger_conservation_reverses_a_settled_sale_and_posts_nothing_for_an_unsettled_one
    """
    world = _armed_and_disarmed_world(api)
    sale1_id = world["sale1"]["id"]

    decision = decide_case(
        api,
        world["case1"]["id"],
        "UNWIND",
        fault_party="SELLER",
        rationale="Undisclosed frame damage on a settled sale",
    )
    assert decision["sale_price_refund_cents"] == 1450000
    assert decision["fee_offset_applied_cents"] == 0
    assert decision["total_buyer_payout_cents"] == 1450000
    assert_transport_totals(decision, total=0, buyer=0, seller=0, auction=0)

    entries, meta = validate_unpaginated(
        api.list_sale_ledger_entries(sale1_id, admin_headers())
    )
    assert_unpaginated_meta(meta, 4)
    assert_created_at_ascending(entries, "sale 1 ledger entries")
    assert_ledger_batch_balanced(entries, "sale 1's whole ledger")
    assert_ledger_rows(
        entries,
        [
            {"party": "SELLER", "entry_type": "SALE_PROCEEDS", "amount_signed_cents": 1450000},
            {"party": "BUYER", "entry_type": "SALE_PROCEEDS", "amount_signed_cents": -1450000},
            {
                "party": "BUYER",
                "entry_type": "SALE_PROCEEDS_REVERSAL",
                "amount_signed_cents": 1450000,
            },
            {
                "party": "SELLER",
                "entry_type": "SALE_PROCEEDS_REVERSAL",
                "amount_signed_cents": -1450000,
            },
        ],
    )
    reversal_pair = ["SALE_PROCEEDS", "SALE_PROCEEDS_REVERSAL"]
    assert_party_net_zero(entries, "SELLER", reversal_pair)
    assert_party_net_zero(entries, "BUYER", reversal_pair)

    sale1 = validate_success(api.get_sale(sale1_id, admin_headers()), 200)
    assert sale1["settlement_status"] == "REVERSED"
    assert sale1["arbitration_status"] == "RESOLVED"


def test_unwinding_a_never_settled_sale_posts_nothing_yet_pays_the_same_shape(api):
    """With the compensation disarmed the second sale's ledger stays empty, while
    the payout figure keeps exactly the same shape as the armed case.

    PRD: "when the sale was still `UNSETTLED` no reversal rows are posted at all,
    because no proceeds were ever released and inventing a pair would break the
    ledger's zero-sum invariant."

    Design: Difficulty/compensating_invariant/sale_ledger_conservation_reverses_a_settled_sale_and_posts_nothing_for_an_unsettled_one
    """
    world = _armed_and_disarmed_world(api)
    sale2_id = world["sale2"]["id"]

    decision = decide_case(
        api,
        world["case2"]["id"],
        "UNWIND",
        fault_party="SELLER",
        rationale="Undisclosed unibody damage on an unsettled sale",
    )

    assert decision["sale_price_refund_cents"] == 900000
    assert decision["fee_offset_applied_cents"] == 0
    assert decision["total_buyer_payout_cents"] == 900000

    entries, meta = validate_unpaginated(
        api.list_sale_ledger_entries(sale2_id, admin_headers())
    )
    assert_unpaginated_meta(meta, 0)
    assert entries == []

    sale2 = validate_success(api.get_sale(sale2_id, admin_headers()), 200)
    assert sale2["settlement_status"] == "REVERSED"
    assert sale2["arbitration_status"] == "RESOLVED"

    case2 = validate_success(api.get_case(world["case2"]["id"], admin_headers()), 200)
    assert case2["status"] == "UNWOUND"

    decisions, decisions_meta = validate_unpaginated(
        api.list_decision(world["case2"]["id"], admin_headers())
    )
    assert_unpaginated_meta(decisions_meta, 1)
    assert decisions[0]["outcome"] == "UNWIND"


def test_two_upheld_claims_on_two_sales_leave_the_tier_alone_at_ten_thousand_bps(api):
    """Both unwinds are upheld, so the rolling rate reads a perfect 10000 bps, and
    the consignor still never moves because two sales are below the sample floor.

    PRD: "Otherwise, if `rolling_window_sales_count` is below 4 the tier is
    `GOOD_STANDING`, because a rate computed from a handful of sales says nothing"

    Design: Difficulty/compensating_invariant/sale_ledger_conservation_reverses_a_settled_sale_and_posts_nothing_for_an_unsettled_one
    """
    world = _armed_and_disarmed_world(api)
    seller_id = world["seller"]["id"]

    decide_case(api, world["case1"]["id"], "UNWIND", fault_party="SELLER")
    decide_case(api, world["case2"]["id"], "UNWIND", fault_party="SELLER")

    scorecard = validate_success(api.get_seller_scorecard(seller_id, admin_headers()), 200)
    assert scorecard["rolling_window_sales_count"] == 2
    assert scorecard["rolling_window_upheld_count"] == 2
    assert scorecard["rolling_arbitration_rate_bps"] == 10000
    assert scorecard["policy_tier"] == "GOOD_STANDING"

    actions, actions_meta = validate_unpaginated(
        api.list_seller_policy_actions(seller_id, admin_headers())
    )
    assert_unpaginated_meta(actions_meta, 0)
    assert actions == []

    case1 = validate_success(api.get_case(world["case1"]["id"], admin_headers()), 200)
    assert case1["status"] == "UNWOUND"


# --- Open-claim counters released by two different paths ----------------------

PAST_INTAKE_GRACE = "2026-08-03T00:00:01.000Z"


def _two_open_claim_world(api):
    """Two claims left in SUBMITTED — one to be withdrawn explicitly, one to be
    expired by the sweep."""
    seller = create_seller(api)
    buyer = create_buyer(api)
    create_policy(api, MECHANICAL_POLICY)
    sale1 = create_sale(api, seller["id"], buyer["id"], light_channel="YELLOW")
    sale2 = create_sale(
        api,
        seller["id"],
        buyer["id"],
        sale_price_cents=900000,
        announced_odometer_miles=61000,
        light_channel="YELLOW",
    )
    case_withdraw = create_case(
        api,
        sale1["id"],
        buyer["id"],
        defect_class="MECHANICAL",
        claim_amount_cents=100000,
        odometer_at_claim=84100,
        complaint_text="Transmission slips in third",
    )
    case_expire = create_case(
        api,
        sale2["id"],
        buyer["id"],
        defect_class="MECHANICAL",
        claim_amount_cents=100000,
        odometer_at_claim=61100,
        complaint_text="Engine misfire under load",
    )
    return {
        "seller": seller,
        "buyer": buyer,
        "sale1": sale1,
        "sale2": sale2,
        "case_withdraw": case_withdraw,
        "case_expire": case_expire,
    }


def test_an_explicit_withdrawal_releases_the_claim_it_owns_and_no_other(api):
    """The withdrawal returns sale 1 to NONE while the sibling claim keeps its own
    counters, so the release is scoped to one case.

    PRD: "the sale's `open_case_count`, the buyer's `open_claim_count` and the
    consignor's `open_claim_count` each fall by 1; and when the sale's
    `open_case_count` reaches 0 and no `ArbitrationDecision` exists on any of that
    sale's cases, the sale's `arbitration_status` reverts `ACTIVE → NONE`."

    Design: Difficulty/compensating_invariant/open_claim_counters_restored_by_withdraw_and_by_sweep_expiry
    """
    world = _two_open_claim_world(api)

    buyer_before = validate_success(api.get_buyer(world["buyer"]["id"], admin_headers()), 200)
    assert buyer_before["open_claim_count"] == 2
    assert buyer_before["lifetime_claim_count"] == 2
    seller_before = validate_success(
        api.get_seller(world["seller"]["id"], admin_headers()), 200
    )
    assert seller_before["open_claim_count"] == 2

    withdrawn = withdraw_case(
        api,
        world["case_withdraw"]["id"],
        world["buyer"]["id"],
        reason="Shop found the fault was pre-existing wear the buyer accepted",
    )
    assert withdrawn["status"] == "WITHDRAWN"

    sale1 = validate_success(api.get_sale(world["sale1"]["id"], admin_headers()), 200)
    assert sale1["open_case_count"] == 0
    assert sale1["arbitration_status"] == "NONE"

    sale2 = validate_success(api.get_sale(world["sale2"]["id"], admin_headers()), 200)
    assert sale2["open_case_count"] == 1
    assert sale2["arbitration_status"] == "ACTIVE"

    buyer = validate_success(api.get_buyer(world["buyer"]["id"], admin_headers()), 200)
    assert buyer["open_claim_count"] == 1
    assert buyer["lifetime_claim_count"] == 2


def test_the_sweep_releases_the_stale_claim_and_repeating_it_changes_nothing(api):
    """The second path is implicit: the sweep expires the untouched claim, both
    open counters land back at zero, the lifetime counter is not reversed, and a
    repeat sweep is idle.

    PRD: "Every `ArbitrationCase` still in `SUBMITTED` for which the clock has
    passed `claimed_at_utc` plus a 48-hour intake grace period moves `SUBMITTED →
    EXPIRED`, releasing counters exactly as a withdrawal does"

    Design: Difficulty/compensating_invariant/open_claim_counters_restored_by_withdraw_and_by_sweep_expiry
    """
    world = _two_open_claim_world(api)
    buyer_id = world["buyer"]["id"]
    seller_id = world["seller"]["id"]

    withdraw_case(api, world["case_withdraw"]["id"], buyer_id)
    set_clock(api, PAST_INTAKE_GRACE)

    report = run_sweep(api)
    assert_sweep_report(report, cases_expired=1)

    expired = validate_success(
        api.get_case(world["case_expire"]["id"], admin_headers()), 200
    )
    assert expired["status"] == "EXPIRED"

    sale2 = validate_success(api.get_sale(world["sale2"]["id"], admin_headers()), 200)
    assert sale2["open_case_count"] == 0
    assert sale2["arbitration_status"] == "NONE"

    buyer = validate_success(api.get_buyer(buyer_id, admin_headers()), 200)
    assert buyer["open_claim_count"] == 0
    assert buyer["lifetime_claim_count"] == 2
    seller = validate_success(api.get_seller(seller_id, admin_headers()), 200)
    assert seller["open_claim_count"] == 0

    assert_sweep_report(run_sweep(api))
    buyer_after = validate_success(api.get_buyer(buyer_id, admin_headers()), 200)
    assert buyer_after["open_claim_count"] == 0
    assert buyer_after["lifetime_claim_count"] == 2
    seller_after = validate_success(api.get_seller(seller_id, admin_headers()), 200)
    assert seller_after["open_claim_count"] == 0


def test_neither_release_path_moves_money_or_touches_the_consignor(api):
    """Releasing a claim is a counter operation only: no ledger rows, no holds and
    no scorecard movement on either sale.

    PRD: "This is the compensating half of the counter conservation of §2.9:
    filing and then withdrawing must leave all four aggregate conditions exactly
    where they started."

    Design: Difficulty/compensating_invariant/open_claim_counters_restored_by_withdraw_and_by_sweep_expiry
    """
    world = _two_open_claim_world(api)

    withdraw_case(api, world["case_withdraw"]["id"], world["buyer"]["id"])
    set_clock(api, PAST_INTAKE_GRACE)
    run_sweep(api)

    for sale in (world["sale1"], world["sale2"]):
        row = validate_success(api.get_sale(sale["id"], admin_headers()), 200)
        assert row["settlement_status"] == "UNSETTLED"
        assert row["settlement_hold"] is False
        entries, meta = validate_unpaginated(
            api.list_sale_ledger_entries(sale["id"], admin_headers())
        )
        assert_unpaginated_meta(meta, 0)
        assert entries == []

    scorecard = validate_success(
        api.get_seller_scorecard(world["seller"]["id"], admin_headers()), 200
    )
    assert scorecard["rolling_window_upheld_count"] == 0
    assert scorecard["rolling_arbitration_rate_bps"] == 0
    assert scorecard["policy_tier"] == "GOOD_STANDING"
