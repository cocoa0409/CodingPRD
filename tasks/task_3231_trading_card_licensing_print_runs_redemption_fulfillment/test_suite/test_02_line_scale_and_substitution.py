"""Line-scale arithmetic: per-set tier snapping and the substitution tier.

Both rules pin an evaluation order that changes the answer: each card set is
snapped against its own tier quantum before the line total is summed, and a
redemption's tier is selected from its scratch value before the ratio is
applied.
"""

from test_helpers import (
    ApiErrorId,
    approve_artwork_for_set,
    approve_card_set,
    assert_product_line,
    assert_redemption,
    build_redemption_near_deadline,
    create_active_license,
    create_card_set_raw,
    create_line_ready,
    create_redemption_payload,
    get_success_data,
    PROJECTION_MULTIPLE_OF,
    submit_card_set_for_review,
    SUBSTITUTION_DEADLINE_DAYS_HIGH,
    SUBSTITUTION_DEADLINE_DAYS_LOW,
    SUBSTITUTION_DIVERGENCE_CENTS,
    TEST_USERS,
    validate_error,
    validate_success,
)

PM = TEST_USERS["product_manager_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
ANALYST = TEST_USERS["redemption_analyst_headers"]


def _base_set_line(api, quantity, name):
    """Create a BASE card set of `quantity` inside its own READY line."""
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(
        api, line["id"], set_name=name, set_tier="BASE", print_run_quantity=quantity
    )
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    card_set = submit_card_set_for_review(api, card_set["id"])
    card_set = get_success_data(approve_card_set(api, card_set["id"], card_set["version"]))
    return license_obj, line, card_set


def _three_base_sets_of_1234(api):
    """One line carrying three approved BASE sets of 1234 cards each."""
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    sets = []
    for name in ("Flagship Base", "Flagship Inserts", "Flagship Parallels"):
        card_set = create_card_set_raw(
            api, line["id"], set_name=name, set_tier="BASE", print_run_quantity=1234
        )
        approve_artwork_for_set(api, card_set["id"], license_obj["id"])
        card_set = submit_card_set_for_review(api, card_set["id"])
        sets.append(
            get_success_data(approve_card_set(api, card_set["id"], card_set["version"]))
        )
    return license_obj, line, sets


def test_line_allocated_cards_snaps_every_set_before_summing(api):
    """PRD §3.8: "for a line carrying three `BASE` sets of 1234 cards each, the
    correct per-set-then-sum result is 1500 plus 1500 plus 1500, which is 4500,
    whereas snapping the summed 3702 once against the `BASE` quantum of 500
    yields 4000."

    Design: Difficulty/combinatorial_formula/tier_snap_aggregate_pins_per_set_before_sum
    """
    _, line, sets = _three_base_sets_of_1234(api)
    assert len(sets) == 3
    quantum = PROJECTION_MULTIPLE_OF["BASE"]
    assert quantum == 500

    read = validate_success(api.get_product_line(line["id"], PLANNER))
    assert_product_line(read)
    assert read["allocated_cards"] == 4500, (
        "per-set ceiling (1500 + 1500 + 1500), not the 4000 a single ceiling "
        "over the summed 3702 would give"
    )


def test_line_allocated_cards_is_not_the_snap_of_the_summed_quantity(api):
    """PRD §2.11: "Each card set's own quantity is first snapped to that set's own
    tier quantum — rounded up to the next multiple of that tier's quantum,
    where the quantum is a different number for each of the three tiers — and
    only then are the snapped per-set quantities added together into the line
    total."

    PRD §3.8: "Snapping the summed total once, against a single quantum,
    produces a lower and incorrect number for the same inputs."

    Design: Difficulty/combinatorial_formula/tier_snap_aggregate_pins_per_set_before_sum
    """
    _, line, _ = _three_base_sets_of_1234(api)
    quantum = PROJECTION_MULTIPLE_OF["BASE"]
    single_snap_of_sum = -(-(1234 * 3) // quantum) * quantum
    assert single_snap_of_sum == 4000, "the counter-example the PRD names"

    read = validate_success(api.get_product_line(line["id"], PLANNER))
    assert read["allocated_cards"] != single_snap_of_sum, (
        "the implementation must not snap the summed total against one quantum"
    )
    assert read["allocated_cards"] == 4500


def test_line_sets_per_case_is_the_product_of_the_physical_factors(api):
    """PRD §3.2: "That derived value is the product of the three physical
    factors — boxes per case, multiplied by packs per box, multiplied by cards
    per pack".

    PRD §3.8: "for a line carrying three `BASE` sets of 1234 cards each, the
    correct per-set-then-sum result is 1500 plus 1500 plus 1500, which is
    4500".

    Design: Difficulty/combinatorial_formula/tier_snap_aggregate_pins_per_set_before_sum
    """
    _, line, _ = _three_base_sets_of_1234(api)
    read = validate_success(api.get_product_line(line["id"], PLANNER))
    assert read["sets_per_case"] == (
        read["boxes_per_case"] * read["packs_per_box"] * read["cards_per_pack"]
    )
    assert read["sets_per_case"] == 2000


def test_a_zero_quantity_set_contributes_zero_to_the_line_total(api):
    """PRD §3.8: "Every card set under the line participates in this total
    regardless of its status, because the line's producible total is what each
    set *will* run; a set whose quantity is 0 contributes 0."

    Design: Difficulty/combinatorial_formula/tier_snap_aggregate_pins_per_set_before_sum
    """
    _, line, _ = _three_base_sets_of_1234(api)
    blank = create_card_set_raw(
        api, line["id"], set_name="Flagship Blank", set_tier="BASE", print_run_quantity=0
    )
    assert blank["status"] == "DRAFT"

    read = validate_success(api.get_product_line(line["id"], PLANNER))
    assert read["allocated_cards"] == 4500, "an unapproved zero-quantity set adds nothing"


def test_redemption_deadline_days_follow_the_scratch_value_tier(api):
    """PRD §3.5: "A redemption whose `estimated_value_cents` is at least that
    threshold is granted `SUBSTITUTION_DEADLINE_DAYS_HIGH`, 730 days; one below
    it is granted `SUBSTITUTION_DEADLINE_DAYS_LOW`, 365 days."

    Design: Difficulty/combinatorial_formula/substition_ratio_and_allowance_follow_the_value_tier
    """
    _, low = build_redemption_near_deadline(api, estimated_value_cents=150000)
    low = validate_success(api.get_redemption(low["id"], ANALYST))
    assert_redemption(low)
    assert low["deadline_days"] == SUBSTITUTION_DEADLINE_DAYS_LOW == 365
    assert low["estimated_value_cents"] == 150000


def test_a_scratch_value_at_the_divergence_takes_the_high_tier_window(api):
    """PRD §3.5: "The boundary is inclusive on the high side, so a scratch
    value of exactly 250000 already takes the longer window."

    Design: Difficulty/combinatorial_formula/substition_ratio_and_allowance_follow_the_value_tier
    """
    _, high = build_redemption_near_deadline(
        api, estimated_value_cents=SUBSTITUTION_DIVERGENCE_CENTS,
        redemption_code="RDM-5001",
    )
    read = validate_success(api.get_redemption(high["id"], ANALYST))
    assert read["deadline_days"] == SUBSTITUTION_DEADLINE_DAYS_HIGH == 730
    assert read["estimated_value_cents"] == 250000, (
        "the scratch value is unchanged by the deadline derivation"
    )

    _, low = build_redemption_near_deadline(
        api, estimated_value_cents=249999, redemption_code="RDM-5002"
    )
    read_low = validate_success(api.get_redemption(low["id"], ANALYST))
    assert read_low["deadline_days"] == 365, "one cent below the boundary stays low"


def test_a_high_tier_redemption_keeps_its_scratch_value_until_cancellation(api):
    """PRD §3.5: "The fulfilment deadline is not a configured constant but a
    function of the promised value, and it is fixed at issuance."

    PRD §3.5: "Cancellation sets the status to `CANCELLED` and sets
    `estimated_value_cents` to 0, reflecting that the promised autograph is no
    longer the consideration".

    Design: Difficulty/combinatorial_formula/substition_ratio_and_allowance_follow_the_value_tier
    """
    _, redemption = build_redemption_near_deadline(api, estimated_value_cents=400000)
    read = validate_success(api.get_redemption(redemption["id"], ANALYST))
    assert read["estimated_value_cents"] == 400000
    assert read["deadline_days"] == 730

    get_success_data(
        api.set_clock("2029-01-01T00:00:00Z", TEST_USERS["platform_admin_headers"])
    )
    cancelled = validate_success(api.cancel_redemption(redemption["id"], ANALYST))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["estimated_value_cents"] == 0
    assert cancelled["deadline_days"] == 730, "the issuance-time window never moves"


def test_cancelling_inside_the_window_is_refused(api):
    """PRD §3.5: "requires the clock to have moved strictly past `opened_on`
    plus `deadline_days` — a cancellation at or before the deadline is refused
    with `ERR_REDEMPTION_DEADLINE_NOT_EXCEEDED`".

    Design: Difficulty/combinatorial_formula/substition_ratio_and_allowance_follow_the_value_tier
    """
    _, redemption = build_redemption_near_deadline(api, estimated_value_cents=150000)
    resp = api.cancel_redemption(redemption["id"], ANALYST)
    validate_error(resp, ApiErrorId.ERR_REDEMPTION_DEADLINE_NOT_EXCEEDED)
    after = validate_success(api.get_redemption(redemption["id"], ANALYST))
    assert after["status"] == "ISSUED"
    assert after["estimated_value_cents"] == 150000