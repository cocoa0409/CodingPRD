"""Combinatorial formulas: the three-dimension window conjunction, the per-leg
transport rounding order, and the pinned unwind payout order."""
from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_created_at_ascending,
    assert_ledger_batch_balanced,
    assert_ledger_rows,
    assert_transport_totals,
    assert_unpaginated_meta,
    validate_unpaginated,
)
from test_helpers.constants import (
    FRAME_DAMAGE_POLICY,
    MECHANICAL_POLICY,
    TITLE_MISSING_POLICY,
)
from test_helpers.factories import (
    accept_round,
    complete_inspection,
    create_buyer,
    create_case,
    create_evidence,
    create_inspection,
    create_policy,
    create_sale,
    create_seller,
    create_transport_leg,
    decide_case,
    open_review,
    seller_response,
    set_clock,
)
from test_helpers.test_users import admin_headers

CLOCK_AT_COMPLETION = "2026-08-02T00:00:00.000Z"
CLOCK_AT_ONE_HUNDRED_HOURS = "2026-08-05T04:00:00.000Z"


def _psi_extended_world(api):
    """A COMPLETED PREMIUM inspection naming MECHANICAL, with the clock standing
    exactly 100 hours after hammer time."""
    seller = create_seller(api)
    buyer = create_buyer(api)
    create_policy(api, MECHANICAL_POLICY)
    sale = create_sale(api, seller["id"], buyer["id"])
    inspection = create_inspection(api, sale["id"], buyer["id"], program_tier="PREMIUM")
    set_clock(api, CLOCK_AT_COMPLETION)
    complete_inspection(api, inspection["id"], ["MECHANICAL"])
    set_clock(api, CLOCK_AT_ONE_HUNDRED_HOURS)
    return {"seller": seller, "buyer": buyer, "sale": sale, "inspection": inspection}


def test_inspection_extension_admits_a_claim_the_bare_window_would_have_barred(api):
    """100.0 elapsed hours exceed the 48-hour MECHANICAL window, but a COMPLETED
    inspection naming MECHANICAL adds 96 hours, so the effective window is 144
    and the claim is eligible on all three dimensions at once.

    PRD: "Fourth, `effective_window_hours` is null when the policy's
    `window_hours` is null, and otherwise the policy's `window_hours` plus
    `psi_extension_applied_hours`."

    Design: Difficulty/combinatorial_formula/window_eligibility_three_dimension_conjunction_with_psi_extension
    """
    world = _psi_extended_world(api)

    case = create_case(
        api,
        world["sale"]["id"],
        world["buyer"]["id"],
        defect_class="MECHANICAL",
        claim_amount_cents=60000,
        odometer_at_claim=84200,
        complaint_text="Transmission slips under load",
    )

    assert case["status"] == "SUBMITTED"
    assert case["hours_elapsed_at_claim"] == 100.0
    assert case["miles_driven_at_claim"] == 200
    assert case["psi_extension_applied_hours"] == 96
    assert case["effective_window_hours"] == 144
    assert case["window_eligible"] is True
    assert case["policy_version_at_intake"] == 1


def test_the_extended_window_claim_activates_the_sale_and_bills_the_premium_fee(api):
    """The same filing moves the sale onto the dispute dimension while the
    governing inspection remains a COMPLETED PREMIUM programme at 27500 cents.

    PRD: "The tier selects the fee: `fee_cents` is 12500 for a `STANDARD`
    programme and 27500 for a `PREMIUM` one."

    Design: Difficulty/combinatorial_formula/window_eligibility_three_dimension_conjunction_with_psi_extension
    """
    world = _psi_extended_world(api)
    sale_id = world["sale"]["id"]

    create_case(
        api,
        sale_id,
        world["buyer"]["id"],
        defect_class="MECHANICAL",
        claim_amount_cents=60000,
        odometer_at_claim=84200,
    )

    sale = validate_success(api.get_sale(sale_id, admin_headers()), 200)
    assert sale["arbitration_status"] == "ACTIVE"
    assert sale["open_case_count"] == 1

    inspections, meta = validate_unpaginated(
        api.list_sale_inspections(sale_id, admin_headers())
    )
    assert_unpaginated_meta(meta, 1)
    assert inspections[0]["status"] == "COMPLETED"
    assert inspections[0]["fee_cents"] == 27500


# --- Per-leg rounding order --------------------------------------------------

FRAME_CASE = {
    "defect_class": "FRAME_DAMAGE",
    "claim_amount_cents": 285000,
    "odometer_at_claim": 84120,
    "complaint_text": "Frame rail repair found on the lift",
}


def _two_leg_negotiation_world(api):
    """A FRAME_DAMAGE case in NEGOTIATION carrying legs of 137 then 201 miles."""
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
    leg1 = create_transport_leg(api, case["id"], case["version"], 137, "INBOUND_TO_AUCTION")
    leg2 = create_transport_leg(
        api, case["id"], leg1["case_version_after"], 201, "RETURN_TO_SELLER"
    )
    round_row = seller_response(
        api,
        case["id"],
        seller["id"],
        "OFFER_REPAIR_ALLOWANCE",
        seller_offer_cents=200000,
        note="Allowance offered in lieu of unwind",
    )
    return {
        "seller": seller,
        "buyer": buyer,
        "sale": sale,
        "case": case,
        "legs": [leg1, leg2],
        "round": round_row,
    }


def test_leg_cost_uses_marginal_distance_bands_not_an_average_rate(api):
    """A 137-mile leg costs 32735 and a 201-mile leg 42655, and both are listed
    in the ascending created_at order allocation walks them in.

    PRD: "The distance charge is then 185 cents per mile for the leg's first 100
    miles, plus 155 cents per mile for the next 400 miles — that is, for the
    portion of the distance above 100 miles and up to 500 miles — plus 130 cents
    per mile for every mile beyond 500."

    Design: Difficulty/combinatorial_formula/transport_allocation_per_leg_rounding_order_beats_sum_then_round
    """
    world = _two_leg_negotiation_world(api)

    legs, meta = validate_unpaginated(
        api.list_transport_legs(world["case"]["id"], admin_headers())
    )

    assert_unpaginated_meta(meta, 2)
    assert_created_at_ascending(legs, "transport legs")
    assert [leg["cost_cents"] for leg in legs] == [32735, 42655]
    assert [leg["miles"] for leg in legs] == [137, 201]


def test_rounding_each_leg_then_summing_beats_summing_then_rounding_once(api):
    """The 2000/7000 allowance profile over legs of 32735 and 42655 yields seller
    52774 and auction 7538, not the 52773 / 7539 a single closing rounding gives,
    and the eight ledger rows carry the two balanced per-leg batches.

    PRD: "Rounding each leg and then summing is the specified behaviour; summing
    the raw amounts and rounding once at the end produces different figures and
    is a defect."

    Design: Difficulty/combinatorial_formula/transport_allocation_per_leg_rounding_order_beats_sum_then_round
    """
    world = _two_leg_negotiation_world(api)
    case_id = world["case"]["id"]

    decision = accept_round(api, case_id, world["round"]["id"], world["buyer"]["id"])

    assert_transport_totals(decision, total=75390, buyer=15078, seller=52774, auction=7538)
    assert (
        decision["transport_buyer_share_cents"]
        + decision["transport_seller_share_cents"]
        + decision["transport_auction_share_cents"]
        == 75390
    )

    entries, meta = validate_unpaginated(
        api.list_case_ledger_entries(case_id, admin_headers())
    )
    assert_unpaginated_meta(meta, 8)
    assert_ledger_batch_balanced(entries, "the whole case ledger")
    assert_ledger_rows(
        entries,
        [
            {"party": "BUYER", "entry_type": "REPAIR_ALLOWANCE", "amount_signed_cents": 200000},
            {"party": "SELLER", "entry_type": "REPAIR_ALLOWANCE", "amount_signed_cents": -200000},
            {"party": "BUYER", "entry_type": "TRANSPORT_ALLOCATION", "amount_signed_cents": -6547},
            {"party": "SELLER", "entry_type": "TRANSPORT_ALLOCATION", "amount_signed_cents": -22915},
            {"party": "AUCTION", "entry_type": "TRANSPORT_ALLOCATION", "amount_signed_cents": 29462},
            {"party": "BUYER", "entry_type": "TRANSPORT_ALLOCATION", "amount_signed_cents": -8531},
            {"party": "SELLER", "entry_type": "TRANSPORT_ALLOCATION", "amount_signed_cents": -29859},
            {"party": "AUCTION", "entry_type": "TRANSPORT_ALLOCATION", "amount_signed_cents": 38390},
        ],
    )


# --- The pinned unwind payout order ------------------------------------------


def _fee_hold_unwind_world(api):
    """A buyer carrying a 75000-cent balance from two frivolous denials, plus a
    100000-cent unsettled sale whose TITLE_MISSING case is in ARBITRATOR_REVIEW
    with legs of 137 then 201 miles."""
    seller = create_seller(api)
    buyer = create_buyer(api)
    create_policy(api, MECHANICAL_POLICY)
    create_policy(api, TITLE_MISSING_POLICY)
    frivolous_sales = [
        create_sale(
            api,
            seller["id"],
            buyer["id"],
            sale_price_cents=900000,
            announced_odometer_miles=70000 + index * 1000,
        )
        for index in range(2)
    ]
    for index, sale in enumerate(frivolous_sales):
        case = create_case(
            api,
            sale["id"],
            buyer["id"],
            defect_class="MECHANICAL",
            claim_amount_cents=60000,
            odometer_at_claim=70050 + index * 1000,
            complaint_text="Noise at idle",
        )
        create_evidence(
            api,
            case["id"],
            buyer["id"],
            evidence_type="INSPECTION_REPORT",
            repair_estimate_cents=10000,
        )
        open_review(api, case["id"])
        seller_response(api, case["id"], seller["id"], "DISPUTE", note="Nothing found")
        decide_case(
            api,
            case["id"],
            "FRIVOLOUS_DENIED",
            fault_party="BUYER",
            rationale="No defect substantiated",
        )
    unwind_sale = create_sale(
        api, seller["id"], buyer["id"], sale_price_cents=100000
    )
    case = create_case(
        api,
        unwind_sale["id"],
        buyer["id"],
        defect_class="TITLE_MISSING",
        claim_amount_cents=0,
        odometer_at_claim=84100,
        complaint_text="Title never arrived",
    )
    create_evidence(api, case["id"], buyer["id"], evidence_type="TITLE_DOCUMENT")
    case = open_review(api, case["id"])
    leg1 = create_transport_leg(api, case["id"], case["version"], 137, "INBOUND_TO_AUCTION")
    create_transport_leg(
        api, case["id"], leg1["case_version_after"], 201, "RETURN_TO_SELLER"
    )
    seller_response(api, case["id"], seller["id"], "DISPUTE", note="Title was mailed")
    return {"seller": seller, "buyer": buyer, "sale": unwind_sale, "case": case}


def test_unwind_fee_offset_is_measured_against_the_gross_refund(api):
    """A 75000-cent balance against a 100000-cent gross refund offsets the whole
    75000 and drives the payout to -12696, where measuring against the 62304
    remaining after transport would have offset only 62304 and paid 0.

    PRD: "Step three: `fee_offset_applied_cents` is the smaller of the buyer's
    outstanding `frivolous_fee_balance_cents` and the **gross** refund from step
    one — deliberately measured against the gross figure, not against what is
    left after the buyer's transport share."

    Design: Difficulty/combinatorial_formula/unwind_payout_fee_offset_measured_against_gross_refund
    """
    world = _fee_hold_unwind_world(api)

    decision = decide_case(
        api,
        world["case"]["id"],
        "UNWIND",
        fault_party="NONE",
        rationale="Title never produced; neither party at fault for the transport",
    )

    assert decision["outcome"] == "UNWIND"
    assert decision["sale_price_refund_cents"] == 100000
    assert decision["fee_offset_applied_cents"] == 75000
    assert decision["total_buyer_payout_cents"] == -12696

    buyer = validate_success(api.get_buyer(world["buyer"]["id"], admin_headers()), 200)
    assert buyer["frivolous_fee_balance_cents"] == 0
    assert buyer["frivolous_claim_count"] == 2
    assert buyer["claim_privilege_status"] == "ACTIVE"


def test_unwinding_an_unsettled_sale_splits_transport_evenly_and_posts_no_reversal(api):
    """With fault_party NONE the two parties split each leg 5000 bps and the
    auction absorbs a negative residual of -2, while an UNSETTLED sale receives
    no SALE_PROCEEDS_REVERSAL rows at all.

    PRD: "a `SALE_PROCEEDS_REVERSAL` pair crediting the buyer `sale_price_cents`
    and debiting the consignor the same is posted **only** when the sale's
    `settlement_status` was `SETTLED`; when the sale was still `UNSETTLED` no
    reversal rows are posted at all, because no proceeds were ever released and
    inventing a pair would break the ledger's zero-sum invariant."

    Design: Difficulty/combinatorial_formula/unwind_payout_fee_offset_measured_against_gross_refund
    """
    world = _fee_hold_unwind_world(api)
    sale_id = world["sale"]["id"]

    decision = decide_case(api, world["case"]["id"], "UNWIND", fault_party="NONE")

    assert_transport_totals(
        decision, total=75390, buyer=37696, seller=37696, auction=-2
    )

    sale = validate_success(api.get_sale(sale_id, admin_headers()), 200)
    assert sale["settlement_status"] == "REVERSED"
    assert sale["arbitration_status"] == "RESOLVED"

    entries, _ = validate_unpaginated(
        api.list_sale_ledger_entries(sale_id, admin_headers())
    )
    assert all(
        row["entry_type"] != "SALE_PROCEEDS_REVERSAL" for row in entries
    ), "an unsettled sale must receive no SALE_PROCEEDS_REVERSAL rows"
    assert_ledger_batch_balanced(entries, "the unwound sale's ledger")
