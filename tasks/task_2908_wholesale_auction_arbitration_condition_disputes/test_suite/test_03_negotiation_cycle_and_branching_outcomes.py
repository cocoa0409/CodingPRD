"""Non-linear state machines: the cyclic negotiation loop, the two independent
sale dimensions, and the asymmetric branches out of ARBITRATOR_REVIEW."""
from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_created_at_ascending,
    assert_instant_equals,
    assert_ledger_batch_balanced,
    assert_ledger_rows,
    assert_transport_totals,
    assert_unpaginated_meta,
    validate_unpaginated,
)
from test_helpers.constants import CLOCK_DEFAULT, FRAME_DAMAGE_POLICY
from test_helpers.factories import (
    counter_round,
    create_buyer,
    create_case,
    create_evidence,
    create_policy,
    create_sale,
    create_seller,
    create_transport_leg,
    decide_case,
    escalate_case,
    open_review,
    seller_response,
    set_clock,
    settle_sale,
)
from test_helpers.test_users import admin_headers

FRAME_CASE = {
    "defect_class": "FRAME_DAMAGE",
    "claim_amount_cents": 285000,
    "odometer_at_claim": 84120,
    "complaint_text": "Frame rail repair found on the lift",
}
SECOND_OFFER_CLOCK = "2026-08-01T03:00:00.000Z"
THIRD_OFFER_CLOCK = "2026-08-01T06:00:00.000Z"
THIRD_COOLDOWN_END = "2026-08-01T08:00:00.000Z"


def _frame_review_world(api):
    """A FRAME_DAMAGE case in UNDER_REVIEW, evidenced and intaked."""
    seller = create_seller(api)
    buyer = create_buyer(api)
    create_policy(api, FRAME_DAMAGE_POLICY)
    sale = create_sale(api, seller["id"], buyer["id"], light_channel="RED")
    case = create_case(api, sale["id"], buyer["id"], **FRAME_CASE)
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
    return {"seller": seller, "buyer": buyer, "sale": sale, "case": case}


def _three_cycle_world(api):
    """Three complete offer/counter cycles over the same pair of states."""
    world = _frame_review_world(api)
    case_id = world["case"]["id"]
    seller_id = world["seller"]["id"]
    buyer_id = world["buyer"]["id"]

    round1 = seller_response(
        api, case_id, seller_id, "OFFER_REPAIR_ALLOWANCE", 100000, "First offer"
    )
    counter_round(api, case_id, round1["id"], buyer_id, 250000, "Estimate is 285000")

    set_clock(api, SECOND_OFFER_CLOCK)
    round2 = seller_response(
        api, case_id, seller_id, "OFFER_REPAIR_ALLOWANCE", 150000, "Second offer"
    )
    counter_round(api, case_id, round2["id"], buyer_id, 240000, "Still short")

    set_clock(api, THIRD_OFFER_CLOCK)
    round3 = seller_response(
        api, case_id, seller_id, "OFFER_REPAIR_ALLOWANCE", 180000, "Final offer"
    )
    counter_round(api, case_id, round3["id"], buyer_id, 230000, "Impasse")

    world["rounds"] = [round1, round2, round3]
    return world


def test_escalation_unlocks_once_the_round_counter_reaches_three(api):
    """After three offer/counter cycles the case is still in COUNTERED, but the
    round counter has reached 3 and escalation is finally admitted.

    PRD: "Escalation is gated on exhaustion: the case's `current_round_index`
    must have reached 3 rounds or more, **or** its `seller_response_timed_out`
    flag must be true."

    Design: Difficulty/non_linear_state_machine/negotiation_cycle_three_rounds_then_escalation_unlocks
    """
    world = _three_cycle_world(api)

    case = escalate_case(
        api, world["case"]["id"], note="Three rounds exhausted, impasse"
    )

    assert case["status"] == "ARBITRATOR_REVIEW"
    assert case["current_round_index"] == 3


def test_escalating_supersedes_every_round_the_loop_produced(api):
    """All three rounds end SUPERSEDED with their offers and demands intact, and
    the loop never touched either of the sale's own dimensions.

    PRD: "Escalating marks every round on the case still in `OPEN` or `COUNTERED`
    as `SUPERSEDED` — `OPEN → SUPERSEDED` or `COUNTERED → SUPERSEDED` —
    processed in ascending `created_at` order, and increments the case's
    `version` by 1."

    Design: Difficulty/non_linear_state_machine/negotiation_cycle_three_rounds_then_escalation_unlocks
    """
    world = _three_cycle_world(api)
    case_id = world["case"]["id"]

    escalate_case(api, case_id)

    rounds, meta = validate_unpaginated(
        api.list_negotiation_rounds(case_id, admin_headers())
    )
    assert_unpaginated_meta(meta, 3)
    assert_created_at_ascending(rounds, "negotiation rounds")
    assert [row["round_index"] for row in rounds] == [1, 2, 3]
    assert [row["seller_offer_cents"] for row in rounds] == [100000, 150000, 180000]
    assert [row["status"] for row in rounds] == ["SUPERSEDED"] * 3
    assert rounds[0]["buyer_demand_cents"] == 250000
    assert rounds[2]["buyer_demand_cents"] == 230000
    assert_instant_equals(rounds[2]["countered_at_utc"], THIRD_OFFER_CLOCK, "countered_at_utc")
    assert_instant_equals(
        rounds[2]["cooldown_until_utc"], THIRD_COOLDOWN_END, "cooldown_until_utc"
    )

    sale = validate_success(api.get_sale(world["sale"]["id"], admin_headers()), 200)
    assert sale["arbitration_status"] == "ACTIVE"
    assert sale["open_case_count"] == 1


# --- The two independent sale dimensions --------------------------------------


def _disputed_sale_world(api):
    world = _frame_review_world(api)
    seller_response(
        api,
        world["case"]["id"],
        world["seller"]["id"],
        "DISPUTE",
        note="Damage predates consignment",
    )
    return world


def test_proceeds_release_while_a_claim_is_open_yields_settled_times_active(api):
    """Settling a sale that already carries an open claim succeeds and produces
    the combination SETTLED x ACTIVE on one row.

    PRD: "Crucially, settlement is *not* blocked by an open dispute: a sale whose
    `arbitration_status` is `ACTIVE` may still be settled, because the two
    dimensions are orthogonal and the department would otherwise be able to hold
    a seller's money hostage merely by receiving a claim."

    Design: Difficulty/non_linear_state_machine/sale_settlement_and_arbitration_dimensions_move_independently
    """
    world = _disputed_sale_world(api)
    sale_id = world["sale"]["id"]

    settled = settle_sale(api, sale_id)

    assert settled["settlement_status"] == "SETTLED"
    assert settled["arbitration_status"] == "ACTIVE"
    assert_instant_equals(settled["settled_at_utc"], CLOCK_DEFAULT, "settled_at_utc")

    observed = validate_success(api.get_sale(sale_id, admin_headers()), 200)
    assert observed["settlement_status"] == "SETTLED"
    assert observed["arbitration_status"] == "ACTIVE"


def test_unwinding_a_settled_sale_reverses_the_money_dimension_and_resolves_the_other(api):
    """The unwind drives the settled sale to REVERSED x RESOLVED and posts the
    four-row proceeds-and-reversal history.

    PRD: "The sale's `settlement_status` becomes `REVERSED` no matter what it was
    before — `SETTLED → REVERSED` or `UNSETTLED → REVERSED`"

    Design: Difficulty/non_linear_state_machine/sale_settlement_and_arbitration_dimensions_move_independently
    """
    world = _disputed_sale_world(api)
    sale_id = world["sale"]["id"]
    settle_sale(api, sale_id)

    decision = decide_case(
        api,
        world["case"]["id"],
        "UNWIND",
        fault_party="SELLER",
        rationale="Undisclosed frame damage confirmed",
    )

    assert decision["sale_price_refund_cents"] == 1450000
    assert decision["fee_offset_applied_cents"] == 0
    assert decision["total_buyer_payout_cents"] == 1450000

    sale = validate_success(api.get_sale(sale_id, admin_headers()), 200)
    assert sale["settlement_status"] == "REVERSED"
    assert sale["arbitration_status"] == "RESOLVED"
    assert sale["open_case_count"] == 0

    entries, meta = validate_unpaginated(
        api.list_sale_ledger_entries(sale_id, admin_headers())
    )
    assert_unpaginated_meta(meta, 4)
    assert_created_at_ascending(entries, "sale ledger entries")
    assert_ledger_batch_balanced(entries, "the proceeds and reversal history")
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


# --- The asymmetric branches out of ARBITRATOR_REVIEW ------------------------


def _one_leg_disputed_world(api):
    world = _frame_review_world(api)
    create_transport_leg(
        api, world["case"]["id"], world["case"]["version"], 137, "INBOUND_TO_AUCTION"
    )
    seller_response(
        api,
        world["case"]["id"],
        world["seller"]["id"],
        "DISPUTE",
        note="Damage predates consignment",
    )
    return world


def test_claim_denied_puts_the_whole_transport_bill_on_the_buyer(api):
    """A denial awards nothing and allocates the entire 32735-cent leg to the
    buyer, leaving the consignor and the auction house at zero.

    PRD: "For a `CLAIM_DENIED` and equally for a `FRIVOLOUS_DENIED`, the buyer
    bears the whole bill: 10000 basis points to the buyer, nothing to the
    consignor, nothing to the auction house, again regardless of `fault_party`."

    Design: Difficulty/non_linear_state_machine/arbitrator_review_branches_diverge_in_seller_consequence
    """
    world = _one_leg_disputed_world(api)
    case_id = world["case"]["id"]

    decision = decide_case(
        api,
        case_id,
        "CLAIM_DENIED",
        fault_party="BUYER",
        rationale="Damage was disclosed on the condition report the buyer signed",
    )

    assert decision["outcome"] == "CLAIM_DENIED"
    assert decision["allowance_variant"] == "NONE"
    assert decision["allowance_cents"] == 0
    assert_transport_totals(decision, total=32735, buyer=32735, seller=0, auction=0)

    case = validate_success(api.get_case(case_id, admin_headers()), 200)
    assert case["status"] == "DENIED"

    entries, meta = validate_unpaginated(
        api.list_case_ledger_entries(case_id, admin_headers())
    )
    assert_unpaginated_meta(meta, 3)
    assert_ledger_batch_balanced(entries, "the denial's transport batch")
    assert_ledger_rows(
        entries,
        [
            {"party": "BUYER", "entry_type": "TRANSPORT_ALLOCATION", "amount_signed_cents": -32735},
            {"party": "SELLER", "entry_type": "TRANSPORT_ALLOCATION", "amount_signed_cents": 0},
            {"party": "AUCTION", "entry_type": "TRANSPORT_ALLOCATION", "amount_signed_cents": 32735},
        ],
    )


def test_claim_denied_leaves_the_consignor_and_the_settlement_dimension_untouched(api):
    """The denial branch produces no scorecard movement, no policy action, no
    settlement hold and no frivolous fee.

    PRD: "There is no seller consequence of any kind on this branch — no tier
    movement, no policy action, no settlement hold."

    Design: Difficulty/non_linear_state_machine/arbitrator_review_branches_diverge_in_seller_consequence
    """
    world = _one_leg_disputed_world(api)
    case_id = world["case"]["id"]
    seller_id = world["seller"]["id"]

    decide_case(api, case_id, "CLAIM_DENIED", fault_party="BUYER")

    seller = validate_success(api.get_seller(seller_id, admin_headers()), 200)
    assert seller["lifetime_upheld_count"] == 0
    assert seller["rolling_arbitration_rate_bps"] == 0
    assert seller["policy_tier"] == "GOOD_STANDING"

    actions, actions_meta = validate_unpaginated(
        api.list_seller_policy_actions(seller_id, admin_headers())
    )
    assert_unpaginated_meta(actions_meta, 0)
    assert actions == []

    sale = validate_success(api.get_sale(world["sale"]["id"], admin_headers()), 200)
    assert sale["settlement_status"] == "UNSETTLED"
    assert sale["arbitration_status"] == "RESOLVED"
    assert sale["settlement_hold"] is False

    fees, fees_meta = validate_unpaginated(
        api.list_case_frivolous_fees(case_id, admin_headers())
    )
    assert_unpaginated_meta(fees_meta, 0)
    assert fees == []

    buyer = validate_success(api.get_buyer(world["buyer"]["id"], admin_headers()), 200)
    assert buyer["frivolous_claim_count"] == 0
