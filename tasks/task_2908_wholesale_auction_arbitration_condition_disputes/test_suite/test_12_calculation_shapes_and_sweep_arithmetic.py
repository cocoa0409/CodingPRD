"""Arithmetic surfaces: marginal transport bands, the mileage diminution base, the
scorecard's exclusion of denials, half-up hour rounding, the fee ladder's first
rung, and the four-phase sweep counted once."""
from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_instant_equals,
    assert_ledger_batch_balanced,
    assert_ledger_rows,
    assert_sweep_report,
    assert_unpaginated_meta,
    validate_unpaginated,
)
from test_helpers.constants import MECHANICAL_POLICY, leg_cost_cents
from test_helpers.factories import (
    build_arbitrator_review_world,
    build_sale_world,
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
    run_sweep,
    seller_response,
    set_clock,
)
from test_helpers.test_users import admin_headers

MILEAGE_PRESET = {
    "defect_class": "MILEAGE_DISCREPANCY",
    "window_hours": 720,
    "min_claim_amount_cents": 0,
    "requires_third_party_verification": False,
    "max_allowance_bps": 4000,
    "psi_extension_hours": 24,
    "psi_clean_waives_rights": False,
}


def test_a_single_640_mile_leg_is_priced_across_all_three_marginal_bands(api):
    """640 miles pays the dispatch fee plus the full first two bands plus 140 miles
    of the third, which no single average rate can reproduce, and the denial profile
    puts the whole figure on the buyer.

    PRD: "The dispatch fee is 8500 cents on every leg regardless of distance. The
    distance charge is then 185 cents per mile for the leg's first 100 miles, plus
    155 cents per mile for the next 400 miles — that is, for the portion of the
    distance above 100 miles and up to 500 miles — plus 130 cents per mile for every
    mile beyond 500."

    Design: Corner/calculations/transport_bands_price_a_single_640_mile_leg_across_all_three_tiers
    """
    world = build_arbitrator_review_world(api, [MECHANICAL_POLICY])
    expected_cost = leg_cost_cents(640)
    assert expected_cost == 107200

    leg = create_transport_leg(
        api,
        world["case"]["id"],
        expected_case_version=world["case"]["version"],
        miles=640,
        leg_type="RETURN_TO_SELLER",
    )
    assert leg["cost_cents"] == 107200

    decision = decide_case(
        api,
        world["case"]["id"],
        "CLAIM_DENIED",
        fault_party="BUYER",
        rationale="No mechanical defect substantiated",
    )

    assert decision["transport_total_cents"] == 107200
    assert decision["transport_buyer_share_cents"] == 107200
    assert decision["transport_seller_share_cents"] == 0
    assert decision["transport_auction_share_cents"] == 0
    assert decision["outcome"] == "CLAIM_DENIED"
    assert decision["allowance_variant"] == "NONE"
    assert decision["allowance_cents"] == 0

    entries, meta = validate_unpaginated(
        api.list_case_ledger_entries(world["case"]["id"], admin_headers())
    )
    assert_unpaginated_meta(meta, 3)
    assert_ledger_batch_balanced(entries, "the single transport batch")
    assert_ledger_rows(
        entries,
        [
            {"party": "BUYER", "entry_type": "TRANSPORT_ALLOCATION", "amount_signed_cents": -107200},
            {"party": "SELLER", "entry_type": "TRANSPORT_ALLOCATION", "amount_signed_cents": 0},
            {"party": "AUCTION", "entry_type": "TRANSPORT_ALLOCATION", "amount_signed_cents": 107200},
        ],
    )

    case = validate_success(api.get_case(world["case"]["id"], admin_headers()), 200)
    assert case["status"] == "DENIED"


def _mileage_world(api):
    """A mileage claim whose verified odometer reading is 20000 miles above the
    announced figure, alongside an unrelated repair estimate."""
    seller = create_seller(api)
    buyer = create_buyer(api)
    create_policy(api, MILEAGE_PRESET)
    sale = create_sale(
        api,
        seller["id"],
        buyer["id"],
        sale_price_cents=1450000,
        announced_odometer_miles=84000,
        light_channel="GREEN",
    )
    case = create_case(
        api,
        sale["id"],
        buyer["id"],
        defect_class="MILEAGE_DISCREPANCY",
        claim_amount_cents=200000,
        odometer_at_claim=104000,
        complaint_text="Odometer rolled back before the sale",
    )
    create_evidence(
        api,
        case["id"],
        buyer["id"],
        evidence_type="INSPECTION_REPORT",
        repair_estimate_cents=285000,
    )
    create_evidence(
        api,
        case["id"],
        buyer["id"],
        evidence_type="THIRD_PARTY_VERIFICATION",
        odometer_reading=104000,
    )
    open_review(api, case["id"])
    seller_response(
        api, case["id"], seller["id"], "DISPUTE", note="Odometer was as read at the block"
    )
    return {"seller": seller, "buyer": buyer, "sale": sale, "case": case}


def test_the_mileage_base_ignores_the_repair_estimate_and_is_clipped_by_the_cap(api):
    """The base is priced per overage mile rather than from the 285000 estimate on
    file, and the 900000 result is clipped to the policy cap before the arbitrator's
    smaller request wins.

    PRD: "For a `MILEAGE_DISCREPANCY` claim the base is the true mileage overage
    priced per mile: take the case's `verified_true_mileage`, subtract the sale's
    `announced_odometer_miles`, treat any negative difference as 0, and multiply the
    result by 45 cents per mile."

    Design: Corner/calculations/mileage_diminution_base_replaces_the_repair_estimate_and_is_clipped_by_the_cap
    """
    world = _mileage_world(api)

    decision = decide_case(
        api,
        world["case"]["id"],
        "REPAIR_ALLOWANCE",
        fault_party="SELLER",
        requested_allowance_cents=500000,
        rationale="Undisclosed 20000-mile discrepancy",
    )

    assert decision["computed_award_cents"] == 580000
    assert decision["allowance_cents"] == 500000
    assert decision["allowance_variant"] == "ARBITRATOR_AWARD"
    assert decision["transport_total_cents"] == 0
    assert decision["transport_buyer_share_cents"] == 0
    assert decision["transport_seller_share_cents"] == 0
    assert decision["transport_auction_share_cents"] == 0

    case = validate_success(api.get_case(world["case"]["id"], admin_headers()), 200)
    assert case["status"] == "RESOLVED_ALLOWANCE"
    assert case["verified_true_mileage"] == 104000

    entries, meta = validate_unpaginated(
        api.list_case_ledger_entries(world["case"]["id"], admin_headers())
    )
    assert_unpaginated_meta(meta, 2)
    assert_ledger_rows(
        entries,
        [
            {"party": "BUYER", "entry_type": "REPAIR_ALLOWANCE", "amount_signed_cents": 500000},
            {"party": "SELLER", "entry_type": "REPAIR_ALLOWANCE", "amount_signed_cents": -500000},
        ],
    )

    sale = validate_success(api.get_sale(world["sale"]["id"], admin_headers()), 200)
    assert sale["settlement_status"] == "UNSETTLED"


def test_a_denied_decision_never_reaches_either_upheld_count(api):
    """Four in-window sales clear the sample floor, yet the one closed case was
    denied, so both variants report zero upheld and a zero rate.

    PRD: "Decisions with `outcome` `CLAIM_DENIED` or `FRIVOLOUS_DENIED` are excluded
    from the arithmetic entirely."

    Design: Corner/calculations/scorecard_excludes_denied_decisions_from_both_variants
    """
    world = build_arbitrator_review_world(api, [MECHANICAL_POLICY])
    seller_id = world["seller"]["id"]
    for index in range(3):
        create_sale(
            api,
            seller_id,
            world["buyer"]["id"],
            sale_price_cents=900000 + index * 10000,
            announced_odometer_miles=60000 + index * 1000,
        )
    decide_case(
        api,
        world["case"]["id"],
        "CLAIM_DENIED",
        fault_party="BUYER",
        rationale="Condition consistent with the light disclosure",
    )

    scorecard = validate_success(api.get_seller_scorecard(seller_id, admin_headers()), 200)

    assert scorecard["rolling_window_sales_count"] == 4
    assert scorecard["rolling_window_upheld_count"] == 0
    assert scorecard["rolling_arbitration_rate_bps"] == 0
    assert scorecard["policy_tier"] == "GOOD_STANDING"
    assert scorecard["lifetime_sales_count"] == 4
    assert scorecard["lifetime_upheld_count"] == 0
    assert scorecard["lifetime_arbitration_rate_bps"] == 0

    actions, meta = validate_unpaginated(
        api.list_seller_policy_actions(seller_id, admin_headers())
    )
    assert_unpaginated_meta(meta, 0)
    assert actions == []

    seller = validate_success(api.get_seller(seller_id, admin_headers()), 200)
    assert seller["open_claim_count"] == 0
    assert seller["policy_tier"] == "GOOD_STANDING"


def test_elapsed_hours_are_reported_half_up_to_three_decimals(api):
    """1000 seconds is 0.2777... hours, which the third-decimal half-up rule reports
    as 0.278 rather than truncating to 0.277.

    PRD: "`hours_elapsed_at_claim` is the difference between `claimed_at_utc` — the
    logical-clock instant the claim is filed — and the sale's `hammer_time_utc`, taken
    in seconds, divided by 3600, and rounded half up to three decimal places."

    Design: Corner/calculations/hours_elapsed_at_claim_rounds_half_up_to_three_decimals
    """
    world = build_sale_world(api, [MECHANICAL_POLICY], light_channel="YELLOW")
    thousand_seconds_later = "2026-08-01T00:16:40.000Z"
    set_clock(api, thousand_seconds_later)

    case = create_case(
        api,
        world["sale"]["id"],
        world["buyer"]["id"],
        defect_class="MECHANICAL",
        claim_amount_cents=90000,
        odometer_at_claim=84100,
        complaint_text="Rough shift detected on the drive home",
    )

    assert case["hours_elapsed_at_claim"] == 0.278
    assert_instant_equals(case["claimed_at_utc"], thousand_seconds_later, "claimed_at_utc")
    assert case["miles_driven_at_claim"] == 100
    assert case["psi_extension_applied_hours"] == 0
    assert case["effective_window_hours"] == 48
    assert case["window_eligible"] is True
    assert case["status"] == "SUBMITTED"


def test_the_first_frivolous_denial_charges_the_base_fee_and_holds_the_bidder(api):
    """With no prior denials the ladder's multiplier is 1, so the fee is the 25000
    base, and the bidder's standing flips to a fee hold in the same request.

    PRD: "The ladder is therefore 25000 cents for a buyer's first frivolous claim,
    50000 for the second, and 60000 for the third, since 75000 is clipped by the cap."

    Design: Corner/calculations/first_frivolous_denial_charges_the_base_fee_and_sets_fee_hold
    """
    world = build_arbitrator_review_world(api, [MECHANICAL_POLICY])
    rationale = "No defect existed; the claim was filed to reprice the unit"

    decision = decide_case(
        api,
        world["case"]["id"],
        "FRIVOLOUS_DENIED",
        fault_party="BUYER",
        rationale=rationale,
    )

    assert decision["frivolous_fee_cents"] == 25000
    assert decision["allowance_cents"] == 0
    assert decision["allowance_variant"] == "NONE"

    fees, fees_meta = validate_unpaginated(
        api.list_case_frivolous_fees(world["case"]["id"], admin_headers())
    )
    assert_unpaginated_meta(fees_meta, 1)
    assert fees[0]["fee_cents"] == 25000
    assert fees[0]["prior_frivolous_count"] == 0
    assert fees[0]["reason"] == rationale
    assert fees[0]["buyer_id"] == world["buyer"]["id"]

    buyer = validate_success(api.get_buyer(world["buyer"]["id"], admin_headers()), 200)
    assert buyer["frivolous_claim_count"] == 1
    assert buyer["frivolous_fee_balance_cents"] == 25000
    assert buyer["claim_privilege_status"] == "FEE_HOLD"

    entries, entries_meta = validate_unpaginated(
        api.list_case_ledger_entries(world["case"]["id"], admin_headers())
    )
    assert_unpaginated_meta(entries_meta, 2)
    assert_ledger_batch_balanced(entries, "the frivolous fee batch")
    assert_ledger_rows(
        entries,
        [
            {
                "party": "BUYER",
                "entry_type": "FRIVOLOUS_FEE_ASSESSED",
                "amount_signed_cents": -25000,
            },
            {
                "party": "AUCTION",
                "entry_type": "FRIVOLOUS_FEE_ASSESSED",
                "amount_signed_cents": 25000,
            },
        ],
    )

    seller = validate_success(api.get_seller(world["seller"]["id"], admin_headers()), 200)
    assert seller["lifetime_upheld_count"] == 0
    assert seller["open_claim_count"] == 0


def _four_phase_world(api):
    """One consignor and one bidder across four sales, each staged so that exactly
    one sweep phase has work to do: a lapsing inspection, a lapsing offer, a silent
    consignor, and an untouched claim."""
    seller = create_seller(api)
    buyer = create_buyer(api)
    create_policy(api, MECHANICAL_POLICY)
    sales = [
        create_sale(
            api,
            seller["id"],
            buyer["id"],
            sale_price_cents=1450000 - index * 10000,
            announced_odometer_miles=84000 + index * 1000,
            light_channel="YELLOW",
        )
        for index in range(4)
    ]

    inspection = create_inspection(api, sales[0]["id"], buyer["id"], program_tier="PREMIUM")

    def _claim(sale, odometer, text):
        return create_case(
            api,
            sale["id"],
            buyer["id"],
            defect_class="MECHANICAL",
            claim_amount_cents=120000,
            odometer_at_claim=odometer,
            complaint_text=text,
        )

    negotiating = _claim(sales[1], 85100, "Transfer case whine under load")
    create_evidence(
        api,
        negotiating["id"],
        buyer["id"],
        evidence_type="INSPECTION_REPORT",
        repair_estimate_cents=285000,
    )
    open_review(api, negotiating["id"])
    open_round = seller_response(
        api,
        negotiating["id"],
        seller["id"],
        "OFFER_REPAIR_ALLOWANCE",
        100000,
        "Offer to settle the whine",
    )

    silent = _claim(sales[2], 86100, "Coolant loss from the water pump")
    create_evidence(
        api,
        silent["id"],
        buyer["id"],
        evidence_type="INSPECTION_REPORT",
        repair_estimate_cents=190000,
    )
    open_review(api, silent["id"])

    untouched = _claim(sales[3], 87100, "Intermittent no-start condition")

    return {
        "seller": seller,
        "buyer": buyer,
        "sales": sales,
        "inspection": inspection,
        "negotiating": negotiating,
        "open_round": open_round,
        "silent": silent,
        "untouched": untouched,
    }


def test_all_four_sweep_phases_fire_once_and_the_replay_reports_zeros(api):
    """A single clock jump makes all four phases due at the same moment; the first
    sweep reports one of each and the immediate replay reports nothing, leaving every
    row exactly where the first pass put it.

    PRD: "The sweep is idempotent: called a second time without advancing the clock,
    it moves nothing and reports 0 for all four counters."

    Design: Corner/calculations/sweep_fires_all_four_phases_once_then_is_idempotent_on_replay
    """
    world = _four_phase_world(api)
    set_clock(api, "2026-08-05T00:00:00.000Z")

    first = run_sweep(api)
    assert_sweep_report(
        first,
        inspections_expired=1,
        rounds_expired=1,
        seller_response_timeouts=1,
        cases_expired=1,
    )

    second = run_sweep(api)
    assert_sweep_report(second)

    inspections, inspections_meta = validate_unpaginated(
        api.list_sale_inspections(world["sales"][0]["id"], admin_headers())
    )
    assert_unpaginated_meta(inspections_meta, 1)
    assert inspections[0]["status"] == "EXPIRED"

    negotiating = validate_success(
        api.get_case(world["negotiating"]["id"], admin_headers()), 200
    )
    assert negotiating["status"] == "ARBITRATOR_REVIEW"
    assert negotiating["fault_party"] == "BUYER"
    rounds, rounds_meta = validate_unpaginated(
        api.list_negotiation_rounds(world["negotiating"]["id"], admin_headers())
    )
    assert_unpaginated_meta(rounds_meta, 1)
    assert rounds[0]["id"] == world["open_round"]["id"]
    assert rounds[0]["status"] == "EXPIRED"

    silent = validate_success(api.get_case(world["silent"]["id"], admin_headers()), 200)
    assert silent["status"] == "ARBITRATOR_REVIEW"
    assert silent["fault_party"] == "SELLER"
    assert silent["seller_response_timed_out"] is True
    silent_rounds, silent_meta = validate_unpaginated(
        api.list_negotiation_rounds(world["silent"]["id"], admin_headers())
    )
    assert_unpaginated_meta(silent_meta, 1)
    assert silent_rounds[0]["response_type"] == "TIMEOUT"
    assert silent_rounds[0]["seller_offer_cents"] == 0
    assert silent_rounds[0]["status"] == "CLOSED"

    untouched = validate_success(
        api.get_case(world["untouched"]["id"], admin_headers()), 200
    )
    assert untouched["status"] == "EXPIRED"
    expired_sale = validate_success(
        api.get_sale(world["sales"][3]["id"], admin_headers()), 200
    )
    assert expired_sale["open_case_count"] == 0
    assert expired_sale["arbitration_status"] == "NONE"

    buyer = validate_success(api.get_buyer(world["buyer"]["id"], admin_headers()), 200)
    assert buyer["open_claim_count"] == 2
    assert buyer["lifetime_claim_count"] == 3
