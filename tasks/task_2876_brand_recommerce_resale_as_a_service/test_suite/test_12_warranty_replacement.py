"""Warranty replacement: the substitute selector, the mass that moves between the
diverted and salvage buckets, and the resolutions a remorse claim may not use.

The units here all come from `IN_STORE` trade-ins because refurbishment needs a
bay in the trade-in's custody store (§3.5), and they share one CLEANING bay
across the windows [09:00, 11:00], [12:00, 14:00] and [15:00, 17:00] — each gap
is a full hour, so none of them conflict. An OUTERWEAR grade B unit from a 50000
MSRP trade-in lists at floor(50000 * 3900 / 10000) = 19500, giving gross 19500, a
900 bp channel fee of 1755 and an order total of 21255.
"""

from test_helpers import (
    MERCH,
    WINDOW_09_11,
    WINDOW_12_14,
    api_client,
    assert_diversion_report,
    assert_instant,
    assert_null,
    assert_unit_dimensions,
    create_report,
    fetch_customer,
    fetch_order,
    fetch_unit,
    fulfill_order,
    order_ledger_entries,
    place_order,
    request_return,
    settle_return,
    settle_return_payload,
    setup_estate,
    setup_listed_unit,
    validate_error,
)

GROSS = 19500
FEE = 1755
TOTAL = 21255
WINDOW_15_17 = ("2026-08-01T15:00:00Z", "2026-08-01T17:00:00Z")
MASS_SOLD = 1400
MASS_SUBSTITUTE = 1300


def _avas_two_units(estate):
    """Two accepted in-store trade-ins by one participant, both listed at 19500.

    The heavier 1400 g unit is the one that gets sold; the 1300 g unit is the only
    substitute the selector can reach.
    """
    first = setup_listed_unit(
        estate,
        loyalty_tier="PLUS",
        item_mass_grams=MASS_SOLD,
        window=WINDOW_09_11,
    )
    second = setup_listed_unit(
        estate,
        customer=first["customer"],
        item_mass_grams=MASS_SUBSTITUTE,
        window=WINDOW_12_14,
    )
    # An in-store PLUS trade-in of a 50000 MSRP item: 10000 base plus 500 loyalty.
    assert first["grant"]["issued_amount_minor"] == 10500
    assert second["grant"]["issued_amount_minor"] == 10500
    assert first["unit"]["list_price_minor"] == GROSS
    assert second["unit"]["list_price_minor"] == GROSS
    return first, second


def _sell_and_claim_defect(scenario, buyer=None):
    """Sell the scenario's unit for cash, hand it over and raise a defect claim."""
    the_buyer = buyer or scenario["customer"]
    order = place_order(the_buyer, scenario["channel"], scenario["unit"], 0)
    assert order["gross_price_minor"] == GROSS
    assert order["channel_fee_minor"] == FEE
    assert order["order_total_minor"] == TOTAL
    assert order["cash_due_minor"] == TOTAL
    fulfilled = fulfill_order(order["id"])
    assert_instant(
        fulfilled["warranty_expires_at"],
        "2026-08-31T00:00:00Z",
        "warranty_expires_at",
    )
    return request_return(order["id"], the_buyer, "WARRANTY_DEFECT")


def test_a_replacement_moves_mass_between_the_buckets_and_conserves_the_total():
    """1400 g leaves the diverted bucket, 1300 g takes over, 2700 g is still tracked.

    PRD §3.8: "The defective unit moves from `SOLD` to `SALVAGED`, has its
    `listed_channel_id` cleared to null, and has its `accounting_state` driven to
    `EXPENSED` — from `CAPITALIZED` or from `WRITTEN_DOWN`, whichever it held."
    PRD §3.8: "The substitute unit moves from `LISTED` to `SOLD` and records
    `replacement_for_unit_id` as the defective unit's identifier, which is the
    lineage link a later audit follows."
    PRD §3.8: "The buyer's `diverted_grams_total` is recomputed, dropping by the
    salvaged unit's mass while the substitute's mass stays where it was, and the
    customer's version is incremented."
    PRD §3.1: "`diverted_grams_total` is recomputed the same way: as the sum of
    `mass_grams` over the resale units whose originating trade-in belongs to this
    customer with status `ACCEPTED` and whose lifecycle state is anything other than
    `SALVAGED`."
    PRD §3.8: "Deliberately, **no ledger entry of any kind is appended**: a
    replacement moves goods, not money, and the conserved brand-currency quantity is
    untouched."
    PRD §3.8: "When a substitute is found, the order moves to `REPLACED` with
    `refund_cash_minor`, `refund_credit_minor` and `restock_fee_minor` all set to 0,
    and its version incremented."

    Design: Difficulty/compensating_invariant/warranty_replacement_preserves_tracked_mass_conservation_exactly
    """
    estate = setup_estate()
    sold_scenario, substitute_scenario = _avas_two_units(estate)
    owner = sold_scenario["customer"]
    defective = sold_scenario["unit"]
    substitute = substitute_scenario["unit"]

    before = fetch_customer(owner["id"])
    assert before["diverted_grams_total"] == 2700
    assert before["credit_balance_minor"] == 21000

    order = _sell_and_claim_defect(sold_scenario)
    settled = settle_return(order["id"], "REPLACE")
    assert settled["status"] == "REPLACED"
    assert settled["restock_fee_minor"] == 0
    assert settled["refund_cash_minor"] == 0
    assert settled["refund_credit_minor"] == 0
    assert settled["version"] > order["version"]

    salvaged = fetch_unit(defective["id"])
    assert_unit_dimensions(salvaged, "SALVAGED", "EXPENSED")
    assert_null(salvaged["listed_channel_id"], "listed_channel_id")
    # mass_grams is a record of what came in and is never rewritten.
    assert salvaged["mass_grams"] == MASS_SOLD

    shipped = fetch_unit(substitute["id"])
    assert shipped["lifecycle_state"] == "SOLD"
    assert shipped["replacement_for_unit_id"] == defective["id"]
    # A replacement never expenses the substitute.
    assert shipped["accounting_state"] == "CAPITALIZED"
    assert shipped["mass_grams"] == MASS_SUBSTITUTE
    assert shipped["version"] > substitute["version"]

    # Total tracked mass across both rows is exactly what it was.
    assert salvaged["mass_grams"] + shipped["mass_grams"] == 2700

    after = fetch_customer(owner["id"])
    # Dropped by exactly the salvaged unit's mass.
    assert after["diverted_grams_total"] == MASS_SUBSTITUTE
    assert after["version"] > before["version"]
    # Not one minor unit of brand currency moved.
    assert after["credit_balance_minor"] == 21000
    assert order_ledger_entries(order["id"]) == []


def test_the_diversion_report_reflects_the_post_replacement_split():
    """The published split is 1300 diverted against 1400 salvaged, and the rate follows.

    PRD §3.9: "`units_diverted_count` is the number of those units whose
    `lifecycle_state` is anything other than `SALVAGED`."
    PRD §3.9: "`diverted_grams` is the summed `mass_grams` of those same non-salvaged
    units."
    PRD §3.9: "`salvage_grams` is the summed `mass_grams` of the units in the
    population whose `lifecycle_state` is `SALVAGED`."
    PRD §3.9: "`landfill_diversion_rate_bp` is the diverted share of the total
    in-period accepted mass: when `diverted_grams` and `salvage_grams` are both zero
    it is 0, and otherwise it is `diverted_grams` multiplied by ten thousand, divided
    by the sum of `diverted_grams` and `salvage_grams`, rounded down to whole basis
    points."
    PRD §3.9: "`credit_liability_minor` is the unredeemed brand currency issued
    inside the period — the summed `remaining_minor` over grants whose `status` is
    `ISSUED` or `PARTIALLY_REDEEMED` and whose `issued_at` is at or after
    `period_start_at` and strictly before `period_end_at`."
    PRD §3.9: "A generated report is created in `DRAFT`, with `published_at` null."

    Design: Difficulty/compensating_invariant/warranty_replacement_preserves_tracked_mass_conservation_exactly
    """
    estate = setup_estate()
    sold_scenario, substitute_scenario = _avas_two_units(estate)

    order = _sell_and_claim_defect(sold_scenario)
    assert settle_return(order["id"], "REPLACE")["status"] == "REPLACED"
    assert fetch_unit(sold_scenario["unit"]["id"])["lifecycle_state"] == "SALVAGED"
    assert fetch_unit(substitute_scenario["unit"]["id"])["lifecycle_state"] == "SOLD"

    report = create_report()
    assert_diversion_report(report)
    assert report["status"] == "DRAFT"
    assert_null(report["published_at"], "published_at")
    # Only the substitute is still counted as diverted.
    assert report["units_diverted_count"] == 1
    assert report["diverted_grams"] == MASS_SUBSTITUTE
    assert report["salvage_grams"] == MASS_SOLD
    # floor(1300 * 10000 / 2700).
    assert report["landfill_diversion_rate_bp"] == 4814
    # Both grants are still ISSUED and untouched by the replacement.
    assert report["credit_liability_minor"] == 21000
    # The population's mass is the mass that came in, however it is split.
    assert report["diverted_grams"] + report["salvage_grams"] == 2700


def test_the_selector_takes_the_cheapest_listed_candidate():
    """Three candidates on one channel, and the 15600 one wins over the 19500 one.

    PRD §3.8: "A candidate qualifies only if its `lifecycle_state` is `LISTED`, its
    `listed_channel_id` equals the order's `channel_id`, its `product_category`
    matches the defective unit's, its `condition_grade` matches the defective unit's,
    and it is not the defective unit itself."
    PRD §3.8: "Candidates are ranked by ascending `current_price_minor` — the
    cheapest suitable substitute wins, since the brand is making the buyer whole
    rather than upgrading them — with ties broken by ascending `listed_at` and then
    by ascending `created_at`, never by identifier."
    PRD §3.8: "The substitute unit moves from `LISTED` to `SOLD` and records
    `replacement_for_unit_id` as the defective unit's identifier, which is the
    lineage link a later audit follows."
    PRD §3.8: "The defective unit moves from `SOLD` to `SALVAGED`, has its
    `listed_channel_id` cleared to null, and has its `accounting_state` driven to
    `EXPENSED` — from `CAPITALIZED` or from `WRITTEN_DOWN`, whichever it held."
    PRD §3.6: "The **baseline resale value** is the unit's `reference_msrp_minor`
    multiplied by the tier's `resale_price_pct_bp`, divided by ten thousand and
    rounded down."

    Design: Corner/calculations/replacement_selector_takes_the_cheapest_listed_candidate
    """
    estate = setup_estate()
    # The unit that will be sold and then found defective.
    sold_scenario = setup_listed_unit(
        estate, loyalty_tier="PLUS", item_mass_grams=MASS_SOLD, window=WINDOW_09_11
    )
    # An equally priced candidate from a second participant's trade-in.
    dearer = setup_listed_unit(
        estate,
        email="ben@example.com",
        full_name="Ben Ortiz",
        item_mass_grams=MASS_SUBSTITUTE,
        window=WINDOW_12_14,
    )
    # A cheaper candidate: floor(40000 * 3900 / 10000) = 15600.
    cheaper = setup_listed_unit(
        estate,
        email="cleo@example.com",
        full_name="Cleo Nakamura",
        msrp_minor=40000,
        item_mass_grams=MASS_SUBSTITUTE,
        window=WINDOW_15_17,
    )
    assert sold_scenario["unit"]["current_price_minor"] == GROSS
    assert dearer["unit"]["current_price_minor"] == GROSS
    assert cheaper["unit"]["current_price_minor"] == 15600
    # All three sit on the one channel with the same category and grade.
    for candidate in (sold_scenario, dearer, cheaper):
        assert candidate["unit"]["listed_channel_id"] == estate["channel"]["id"]
        assert candidate["unit"]["product_category"] == "OUTERWEAR"
        assert candidate["unit"]["condition_grade"] == "B"
    dearer_version = dearer["unit"]["version"]

    order = _sell_and_claim_defect(sold_scenario)
    settled = settle_return(order["id"], "REPLACE")
    assert settled["status"] == "REPLACED"

    # Ascending current_price_minor picks 15600 even though a 19500 candidate was
    # listed earlier.
    substitute = fetch_unit(cheaper["unit"]["id"])
    assert substitute["lifecycle_state"] == "SOLD"
    assert substitute["replacement_for_unit_id"] == sold_scenario["unit"]["id"]
    assert substitute["accounting_state"] == "CAPITALIZED"
    assert substitute["current_price_minor"] == 15600
    assert substitute["version"] > cheaper["unit"]["version"]

    # The dearer candidate was never selected, so it was never written to.
    loser = fetch_unit(dearer["unit"]["id"])
    assert loser["lifecycle_state"] == "LISTED"
    assert loser["current_price_minor"] == GROSS
    assert loser["listed_channel_id"] == estate["channel"]["id"]
    assert_null(loser["replacement_for_unit_id"], "replacement_for_unit_id")
    assert loser["version"] == dearer_version

    defective = fetch_unit(sold_scenario["unit"]["id"])
    assert_unit_dimensions(defective, "SALVAGED", "EXPENSED")
    assert_null(defective["listed_channel_id"], "listed_channel_id")
    assert_null(defective["replacement_for_unit_id"], "replacement_for_unit_id")


def test_a_remorse_claim_cannot_be_settled_with_a_substitute():
    """REPLACE is refused on a change of mind, and the refund it forces charges the fee.

    PRD §3.8: "The order's `reason_type` must be `WARRANTY_DEFECT`; a buyer-remorse
    claim cannot be settled with a substitute unit and the attempt is refused at the
    state gate with `ERR_ORDER_RETURN_NOT_SETTLEABLE`."
    PRD §3.8: "For a `BUYER_REMORSE` claim, `restock_fee_minor` is the order's
    `gross_price_minor` multiplied by that tier's `restock_fee_pct_bp`, divided by ten
    thousand and rounded **up**; the non-refundable amount is that restocking fee plus
    the order's `channel_fee_minor`, because the brand does not eat the channel fee on
    a change of mind."
    PRD §3.8: "`refund_cash_minor` is the order's `cash_due_minor` less the
    non-refundable amount, floored at zero so it can never go negative."
    PRD §3.8: "The **first link** writes `restock_fee_minor`, `refund_cash_minor` and
    `refund_credit_minor` onto the order, moves the order to `RETURNED`, increments
    its version, and moves the unit from `SOLD` to `RETURNED` with
    `listed_channel_id` cleared to null and its own version incremented."
    PRD §3.8: "The unit's `current_price_minor` and `list_price_minor` are retained
    until it is re-listed, and its `accounting_state` is left exactly as it was — a
    `CAPITALIZED` unit stays `CAPITALIZED`, and a `WRITTEN_DOWN` unit stays
    `WRITTEN_DOWN`."

    Design: Corner/state_machines/replace_resolution_is_refused_for_a_buyer_remorse_reason
    """
    estate = setup_estate()
    sold_scenario = setup_listed_unit(
        estate, loyalty_tier="PLUS", item_mass_grams=MASS_SOLD, window=WINDOW_09_11
    )
    # A perfectly good substitute exists, so only the reason can be the refusal.
    candidate = setup_listed_unit(
        estate,
        email="ben@example.com",
        full_name="Ben Ortiz",
        item_mass_grams=MASS_SUBSTITUTE,
        window=WINDOW_12_14,
    )
    candidate_version = candidate["unit"]["version"]

    buyer = sold_scenario["customer"]
    order = place_order(buyer, sold_scenario["channel"], sold_scenario["unit"], 0)
    assert order["cash_due_minor"] == TOTAL
    assert order["credit_applied_minor"] == 0
    assert fulfill_order(order["id"])["status"] == "FULFILLED"
    claimed = request_return(order["id"], buyer, "BUYER_REMORSE")
    assert claimed["status"] == "RETURN_REQUESTED"
    assert claimed["reason_type"] == "BUYER_REMORSE"

    validate_error(
        api_client.settle_resale_order_return(
            order["id"], settle_return_payload("REPLACE"), MERCH
        ),
        "ERR_ORDER_RETURN_NOT_SETTLEABLE",
        409,
    )

    # The refused attempt claimed nothing: the candidate is untouched.
    untouched = fetch_unit(candidate["unit"]["id"])
    assert untouched["lifecycle_state"] == "LISTED"
    assert_null(untouched["replacement_for_unit_id"], "replacement_for_unit_id")
    assert untouched["version"] == candidate_version
    # The claim is still live and still a remorse claim.
    still_claimed = fetch_order(order["id"])
    assert still_claimed["status"] == "RETURN_REQUESTED"
    assert still_claimed["reason_type"] == "BUYER_REMORSE"
    assert still_claimed["version"] == claimed["version"]

    # A refund is the resolution that is open, and it keeps the fees.
    refunded = settle_return(order["id"], "REFUND")
    assert refunded["status"] == "RETURNED"
    # ceil(19500 * 1200 / 10000).
    assert refunded["restock_fee_minor"] == 2340
    # 21255 - (2340 + 1755).
    assert refunded["refund_cash_minor"] == 17160
    assert refunded["refund_credit_minor"] == 0

    returned_unit = fetch_unit(sold_scenario["unit"]["id"])
    assert returned_unit["lifecycle_state"] == "RETURNED"
    assert_null(returned_unit["listed_channel_id"], "listed_channel_id")
    assert returned_unit["accounting_state"] == "CAPITALIZED"
    assert returned_unit["current_price_minor"] == GROSS
    assert returned_unit["list_price_minor"] == GROSS
