"""Formulas whose output depends on how many times, and in what order, the
intermediate figures are rounded, and on which balance the ladder reads.
"""

from test_helpers import (
    INVESTIGATOR,
    assert_points,
    assert_posture,
    assert_rate,
    create_listing,
    evaluate,
    file_snapshot,
    issue_action,
    publish_rule,
    read_action,
    read_listings,
    read_seller,
    register_seller,
    set_clock,
    substantiated_violation,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00.000Z"


def _evaluated_seller(api):
    set_clock(api, CLOCK)
    seller = register_seller(
        api, legal_name="Cedarline Trading LLC", email="ops@cedarline-trading.example",
        tax_id_hash="TAX-CE-0001", payout_bank_token="BANK-CE-0001",
        address_fingerprint="ADDR-CE-0001",
    )
    file_snapshot(
        api, seller["id"], "2026-06-01T00:00:00.000Z", "2026-07-01T00:00:00.000Z",
        order_volume=1500, delivered_or_refunded_volume=1400, defect_claims_pending=5,
        defect_claims_substantiated=16, late_shipments=56, pre_fulfillment_cancellations=22,
        shipments_total=1450, shipments_with_valid_tracking=1300, source="PLATFORM_PIPELINE",
    )
    file_snapshot(
        api, seller["id"], "2026-07-01T00:00:00.000Z", "2026-08-01T00:00:00.000Z",
        order_volume=1600, delivered_or_refunded_volume=1550, defect_claims_pending=18,
        defect_claims_substantiated=22, late_shipments=80, pre_fulfillment_cancellations=45,
        shipments_total=1580, shipments_with_valid_tracking=1371, source="PLATFORM_PIPELINE",
    )
    return seller


def test_health_score_rounds_each_weighted_penalty_before_summing_them(api):
    """PRD §3.4: "Each ratio is then weighted, and **the order of the rounding
    steps is pinned**. Multiply the defect ratio by a weight of 42.50, the late
    ratio by 24.50, the cancellation ratio by 18.50, and the tracking ratio by
    14.50, and round **each** of those four weighted penalties half-up to two
    decimals individually. Then add the four already-rounded penalties together
    and round that sum half-up to two decimals to obtain the penalty total."

    Design: Difficulty/combinatorial_formula/health_score_penalty_rounding_pinned_per_component
    """
    seller = _evaluated_seller(api)

    evaluation = evaluate(api, seller["id"])

    # 12.325 -> 12.33, 2.38875 -> 2.39, 0 -> 0.00, 1.04552... -> 1.05; the four
    # rounded penalties total 15.77.
    assert_points(evaluation["health_score"], "84.23", "health_score")
    # Summing the four unrounded penalties and rounding once gives 84.24.
    assert float(evaluation["health_score"]) != 84.24
    assert_points(read_seller(api, seller["id"])["health_score"], "84.23", "health_score")


def test_the_secondary_rates_all_read_the_same_truncated_input_set(api):
    """PRD §3.4: "The `late_shipment_rate` is the sum of `late_shipments` over the
    set divided by `order_volume_final`, rounded half-up to four decimals; the
    `cancellation_rate` is the sum of `pre_fulfillment_cancellations` over the set
    divided by `order_volume_final`, rounded the same way."

    Design: Difficulty/combinatorial_formula/health_score_penalty_rounding_pinned_per_component
    """
    seller = _evaluated_seller(api)

    evaluation = evaluate(api, seller["id"])

    assert evaluation["order_volume_final"] == 3100
    assert_rate(evaluation["late_shipment_rate"], "0.0439", "late_shipment_rate")   # 136/3100
    assert_rate(evaluation["cancellation_rate"], "0.0216", "cancellation_rate")     # 67/3100
    assert_rate(evaluation["valid_tracking_rate"], "0.8815", "valid_tracking_rate")  # 2671/3030
    # Three metrics breached, so the tier is BREACHING on the count branch rather
    # than on the score branch: 84.23 is well above 60.00.
    assert evaluation["metric_tier"] == "BREACHING"


def _seller_with_two_prior_actions(api):
    """A1 under LISTING_ACCURACY at 2026-01-15 and A2 under REVIEW_MANIPULATION at
    2026-07-01, read at a clock where A1 has just stepped down to a 0.50 factor."""
    set_clock(api, "2026-01-15T00:00:00.000Z")
    rule_la = publish_rule(
        api, code="LA-ACC-1", category="LISTING_ACCURACY", base_severity_weight=2.80,
        removal_scope="LISTING", requires_poa=True,
    )
    rule_rm = publish_rule(
        api, code="RM-FAKE-1", category="REVIEW_MANIPULATION", base_severity_weight=1.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = register_seller(
        api, legal_name="Dovetail Home LLC", email="ops@dovetail-home.example",
        tax_id_hash="TAX-DO-0001", payout_bank_token="BANK-DO-0001",
        address_fingerprint="ADDR-DO-0001",
    )
    listing_one = create_listing(
        api, seller["id"], sku="SKU-DO-1", title="Oak Dining Chair", category_code="HOME"
    )
    listing_two = create_listing(
        api, seller["id"], sku="SKU-DO-2", title="Oak Dining Table", category_code="HOME"
    )
    v1 = substantiated_violation(
        api, seller["id"], rule_la["id"], listing_id=listing_one["id"],
        reporter_type="BUYER", evidence_reference="EV-DO-0001",
        decision_note="Title and compatibility data did not match the shipped item.",
    )
    action_one = issue_action(api, v1["id"])

    set_clock(api, "2026-07-01T00:00:00.000Z")
    v2 = substantiated_violation(
        api, seller["id"], rule_rm["id"], reporter_type="BUYER",
        evidence_reference="EV-DO-0002",
        decision_note="Incentivised review solicitation confirmed in buyer messages.",
    )
    action_two = issue_action(api, v2["id"])

    # A1 is now exactly 180 days old, so its decay factor steps to 0.50 while A2,
    # thirteen days old, keeps 1.00.
    set_clock(api, "2026-07-14T00:00:00.000Z")
    v3 = substantiated_violation(
        api, seller["id"], rule_la["id"], listing_id=listing_two["id"],
        reporter_type="BUYER", evidence_reference="EV-DO-0003",
        decision_note="Dimensions in the listing were wrong by 40 percent.",
    )
    return seller, listing_one, listing_two, action_one, action_two, v3


def test_ladder_rung_is_selected_from_the_post_issuance_balance(api):
    """PRD §3.6: "Fourth, select the rung from that post-issuance balance: a
    balance of 12.00 points or more selects `ACCOUNT_SUSPENSION`; a balance of at
    least 4.00 but below 12.00 selects `LISTING_REMOVAL`; anything below 4.00
    selects `WARNING`."

    Design: Difficulty/combinatorial_formula/ladder_rung_read_from_post_balance_not_prior_balance
    """
    seller, _, _, action_one, action_two, v3 = _seller_with_two_prior_actions(api)

    action_three = validate_success(
        api.create_enforcement_action({"violation_id": v3["id"]}, INVESTIGATOR), 201
    )

    assert_points(read_action(api, action_one["id"])["severity_points_applied"], "2.80")
    assert read_action(api, action_one["id"])["ladder_rung_computed"] == "WARNING"
    assert_points(read_action(api, action_two["id"])["severity_points_applied"], "1.00")
    assert read_action(api, action_two["id"])["ladder_rung_computed"] == "WARNING"
    # 2.80 * (1.00 + 0.25 * min(1, 3)) rounded once.
    assert_points(action_three["severity_points_applied"], "3.50")
    # prior 2.40 (A1 x 0.50 + A2 x 1.00) + 3.50 = 5.90, which selects the middle rung;
    # reading the rung off the prior balance of 2.40 would have said WARNING.
    assert_posture(read_seller(api, seller["id"]), severity_points_balance="5.90")
    assert action_three["ladder_rung_computed"] == "LISTING_REMOVAL"
    assert action_three["action_type"] == "LISTING_REMOVAL"
    assert action_three["override_applied"] is False


def test_the_removal_rung_takes_down_only_the_cited_listing(api):
    """PRD §3.6: "A rung of `LISTING_REMOVAL` moves listings to `REMOVED`
    according to the rule's `removal_scope`: under scope `LISTING` the single item
    cited by the violation's `listing_id` is removed, and under scope `ACCOUNT`
    every listing of the seller currently in `ACTIVE` or `SUPPRESSED` is removed."

    Design: Difficulty/combinatorial_formula/ladder_rung_read_from_post_balance_not_prior_balance
    """
    seller, listing_one, listing_two, _, _, v3 = _seller_with_two_prior_actions(api)

    action_three = validate_success(
        api.create_enforcement_action({"violation_id": v3["id"]}, INVESTIGATOR), 201
    )

    assert action_three["removed_listing_count"] == 1
    listings = {row["id"]: row for row in read_listings(api, seller["id"])}
    assert listings[listing_two["id"]]["state"] == "REMOVED"
    assert listings[listing_two["id"]]["removal_policy_category"] == "LISTING_ACCURACY"
    assert listings[listing_one["id"]]["state"] == "ACTIVE"
    assert_posture(read_seller(api, seller["id"]), enforcement_state="RESTRICTED",
                   disbursement_state="RESERVE_HELD")


def _breaching_seller_with_four_ip_actions(api):
    set_clock(api, CLOCK)
    rule_ip = publish_rule(
        api, code="IP-CTR-1", category="INTELLECTUAL_PROPERTY", base_severity_weight=3.00,
        removal_scope="ACCOUNT", requires_poa=True,
    )
    seller = register_seller(
        api, legal_name="Everglade Imports LLC", email="ops@everglade-imports.example",
        tax_id_hash="TAX-EV-0001", payout_bank_token="BANK-EV-0001",
        address_fingerprint="ADDR-EV-0001",
    )
    file_snapshot(
        api, seller["id"], "2026-07-01T00:00:00.000Z", "2026-08-01T00:00:00.000Z",
        order_volume=2000, delivered_or_refunded_volume=2000, defect_claims_pending=0,
        defect_claims_substantiated=20, late_shipments=80, pre_fulfillment_cancellations=0,
        shipments_total=2000, shipments_with_valid_tracking=2000, source="PLATFORM_PIPELINE",
    )
    evaluation = evaluate(api, seller["id"], INVESTIGATOR)
    assert evaluation["metric_tier"] == "BREACHING"

    actions = []
    for index in range(1, 5):
        violation = substantiated_violation(
            api, seller["id"], rule_ip["id"], reporter_type="RIGHTS_OWNER",
            evidence_reference=f"EV-IP-000{index}",
        )
        actions.append(issue_action(api, violation["id"]))
    fifth = substantiated_violation(
        api, seller["id"], rule_ip["id"], reporter_type="RIGHTS_OWNER",
        evidence_reference="EV-IP-0005",
    )
    return seller, actions, fifth


def test_repeat_factor_is_capped_so_the_fifth_offence_costs_what_the_fourth_did(api):
    """PRD §3.6: "Take the smaller of that count and 3, multiply it by 0.25, and
    add 1.00; that is the repeat factor, so a first offence multiplies by 1.00, a
    second by 1.25, a third by 1.50, a fourth by 1.75, and a fifth or later
    offence also by 1.75 because the count is capped at three."

    Design: Difficulty/combinatorial_formula/severity_points_single_rounding_with_capped_repeat_factor
    """
    seller, actions, fifth_violation = _breaching_seller_with_four_ip_actions(api)

    fifth_action = validate_success(
        api.create_enforcement_action({"violation_id": fifth_violation["id"]}, INVESTIGATOR),
        201,
    )

    # 3.00 x 1.00 x 1.50 x 1.25 = 5.625 and 3.00 x 1.75 x 1.50 x 1.25 = 9.84375.
    assert_points(actions[0]["severity_points_applied"], "5.63")
    assert_points(actions[3]["severity_points_applied"], "9.84")
    assert_points(fifth_action["severity_points_applied"], "9.84")
    # Rounding after each factor gives 9.85; an uncapped repeat factor gives 11.25.
    assert float(fifth_action["severity_points_applied"]) != 9.85
    assert float(fifth_action["severity_points_applied"]) != 11.25
    assert float(fifth_action["severity_points_applied"]) < 12.00
    assert fifth_action["decay_exempt"] is True
    assert fifth_action["policy_category"] == "INTELLECTUAL_PROPERTY"


def test_undecayed_intellectual_property_points_accumulate_into_a_suspension(api):
    """PRD §3.6: "An action whose `decay_exempt` is true keeps a factor of 1.00
    forever — intellectual-property and restricted-product points never fade."

    Design: Difficulty/combinatorial_formula/severity_points_single_rounding_with_capped_repeat_factor
    """
    seller, _, fifth_violation = _breaching_seller_with_four_ip_actions(api)

    fifth_action = validate_success(
        api.create_enforcement_action({"violation_id": fifth_violation["id"]}, INVESTIGATOR),
        201,
    )

    # 5.63 + 7.03 + 8.44 + 9.84 + 9.84, none of it decayed.
    assert_posture(read_seller(api, seller["id"]), severity_points_balance="40.78",
                   enforcement_state="SUSPENDED", disbursement_state="FULL_HOLD")
    assert fifth_action["ladder_rung_computed"] == "ACCOUNT_SUSPENSION"
