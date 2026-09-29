"""The published formulas read on their own terms: which rows enter a severity
input set and which quietly leave it, how age discounts a point total while
leaving the stored figure alone, where an overshoot ratio is capped and a score
floored, which registration signals count and which are disregarded, and which
tier percentage prices a rolling reserve.
"""

from test_helpers import (
    INVESTIGATOR,
    OFFICER,
    REVIEWER,
    ApiErrorId,
    appeal_decision_payload,
    assert_cents,
    assert_funds,
    assert_instant_equals,
    assert_meta,
    assert_points,
    assert_posture,
    assert_rate,
    credit,
    evaluate,
    file_appeal,
    file_snapshot,
    file_violation,
    hold_payload,
    issue_action,
    notices_for,
    open_investigation,
    publish_rule,
    read_action,
    read_notices,
    read_seller,
    register_seller,
    set_clock,
    start_review,
    substantiated_violation,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00.000Z"
JANUARY = "2026-01-01T00:00:00.000Z"
JULY = "2026-07-01T00:00:00.000Z"
NEXT_JANUARY = "2027-01-01T00:00:00.000Z"

OUTAGE_GROUNDS = (
    "The late shipments were caused by a carrier outage that the platform itself "
    "published a notice about."
)
OUTAGE_RATIONALE = (
    "Carrier outage was outside the seller's control and is documented by the "
    "platform."
)


# --------------------------------------------------------------------------
# The severity input set is filtered on state, not on the stored number
# --------------------------------------------------------------------------
def _seller_with_two_actions_in_two_categories(api):
    """The clock frozen at CLOCK, a 2.00-point listing-accuracy rule and a
    3.00-point shipping-performance rule, a seller with no listings so no removal
    has anything to take down, and an appeal against the second action already
    under review. The pre-grant balance is 2.00 + 3.00 = 5.00."""
    set_clock(api, CLOCK)
    rule_la = publish_rule(
        api, code="LA-SET-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    rule_sp = publish_rule(
        api, code="SP-SET-1", category="SHIPPING_PERFORMANCE", base_severity_weight=3.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = register_seller(
        api, legal_name="Harborline Tools LLC", email="ops@harborline-tools.example",
        tax_id_hash="TAX-HL-0001", payout_bank_token="BANK-HL-0001",
        address_fingerprint="ADDR-HL-0001",
    )
    first = substantiated_violation(
        api, seller["id"], rule_la["id"], reporter_type="BUYER",
        evidence_reference="EV-SET-0001",
    )
    a1 = issue_action(api, first["id"])
    second = substantiated_violation(
        api, seller["id"], rule_sp["id"], reporter_type="PLATFORM_AUTOMATION",
        evidence_reference="EV-SET-0002",
    )
    a2 = issue_action(api, second["id"])
    appeal = file_appeal(api, a2["id"], seller["id"], grounds=OUTAGE_GROUNDS)
    start_review(api, appeal["id"], REVIEWER)
    return seller, a1, a2, appeal


def test_the_vacated_action_leaves_the_input_set_without_losing_its_own_points(api):
    """PRD §3.6: "`severity_points_balance` on the seller is never incremented in
    place; it is recomputed from scratch over the seller's actions in `ISSUED`,
    `ACKNOWLEDGED`, or `UPHELD`, and a vacated action simply leaves that set, which
    is what makes reinstatement genuinely compensating."

    PRD §3.8: "`reinstatement_granted` becomes true exactly when the appealed
    action's `action_type` was `ACCOUNT_SUSPENSION` — for a vacated warning or
    listing removal it stays false."

    Design: Corner/calculations/calc_vacated_actions_leave_the_severity_input_set
    """
    seller, a1, a2, appeal = _seller_with_two_actions_in_two_categories(api)
    # A different category means no repetition, so 3.00 is the bare base weight.
    assert_points(a2["severity_points_applied"], "3.00", "severity_points_applied")
    assert a2["action_type"] == "LISTING_REMOVAL"
    assert a2["removed_listing_count"] == 0
    before = read_seller(api, seller["id"])
    assert_posture(before, enforcement_state="RESTRICTED",
                   disbursement_state="RESERVE_HELD", severity_points_balance="5.00")

    decided = validate_success(
        api.decide_appeal(
            appeal["id"], appeal_decision_payload("GRANTED", rationale=OUTAGE_RATIONALE),
            REVIEWER,
        ),
        200,
    )

    assert decided["state"] == "GRANTED"
    # The vacated rung was a listing removal, so no reinstatement was granted.
    assert decided["reinstatement_granted"] is False

    vacated = read_action(api, a2["id"])
    assert vacated["state"] == "VACATED"
    assert vacated["resolution_reason"] == "APPEAL_GRANTED"
    # The stored figure is not zeroed; it simply stops being summed.
    assert_points(vacated["severity_points_applied"], "3.00", "severity_points_applied")
    assert read_action(api, a1["id"])["state"] == "ISSUED"

    after = read_seller(api, seller["id"])
    # Exactly a1's points: not the old 5.00 and not 0.00.
    assert_posture(after, enforcement_state="WATCHLIST",
                   disbursement_state="RESERVE_HELD", severity_points_balance="2.00")
    assert after["reinstated_count"] == 0


# --------------------------------------------------------------------------
# The step decay: exemption, the half-weight band, and the zero-weight band
# --------------------------------------------------------------------------
def _two_actions_of_identical_age_one_exempt(api):
    """Both actions are issued at JANUARY, one under a listing-accuracy rule worth
    2.00 and one under an intellectual-property rule worth 3.00 reported by a
    rights owner, which lifts it to 3.00 x 1.50 = 4.50. The clock then moves to
    JULY, 181 days later, and a third listing-accuracy violation is carried to
    SUBSTANTIATED so that issuing it forces the balance to be recomputed."""
    set_clock(api, JANUARY)
    rule_la = publish_rule(
        api, code="LA-DECAY-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    rule_ip = publish_rule(
        api, code="IP-DECAY-1", category="INTELLECTUAL_PROPERTY",
        base_severity_weight=3.00, removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = register_seller(
        api, legal_name="Harborline Tools LLC", email="ops@harborline-tools.example",
        tax_id_hash="TAX-HL-0001", payout_bank_token="BANK-HL-0001",
        address_fingerprint="ADDR-HL-0001",
    )
    first = substantiated_violation(
        api, seller["id"], rule_la["id"], reporter_type="BUYER",
        evidence_reference="EV-DECAY-0001",
    )
    a1 = issue_action(api, first["id"])
    second = substantiated_violation(
        api, seller["id"], rule_ip["id"], reporter_type="RIGHTS_OWNER",
        evidence_reference="EV-DECAY-0002",
    )
    a2 = issue_action(api, second["id"])
    set_clock(api, JULY)
    third = substantiated_violation(
        api, seller["id"], rule_la["id"], reporter_type="BUYER",
        evidence_reference="EV-DECAY-0003",
    )
    return seller, a1, a2, third


def test_the_decay_exempt_action_keeps_full_weight_while_its_peer_halves(api):
    """PRD §3.6: "An action whose `decay_exempt` is true keeps a factor of 1.00
    forever — intellectual-property and restricted-product points never fade."

    PRD §3.2: "The server derives `decay_exempt` itself: it is true exactly when
    `category` is `INTELLECTUAL_PROPERTY` or `RESTRICTED_PRODUCT`, and false for the
    other three categories."

    Design: Corner/calculations/calc_decay_exempt_action_holds_full_weight_while_its_peer_halves
    """
    seller, a1, a2, pending = _two_actions_of_identical_age_one_exempt(api)
    assert_points(a1["severity_points_applied"], "2.00", "severity_points_applied")
    assert a1["decay_exempt"] is False
    assert_points(a2["severity_points_applied"], "4.50", "severity_points_applied")
    assert a2["decay_exempt"] is True

    a3 = issue_action(api, pending["id"])

    # Decay shrinks the balance, never the repeat count: one prior listing-accuracy
    # action still multiplies the 2.00 base by 1.25.
    assert_points(a3["severity_points_applied"], "2.50", "severity_points_applied")
    assert a3["ladder_rung_computed"] == "LISTING_REMOVAL"
    assert a3["override_applied"] is False

    after = read_seller(api, seller["id"])
    # 2.00 x 0.50 + 4.50 x 1.00 + 2.50 = 8.00; decaying the exempt row too gives
    # 5.75 and skipping decay altogether gives 9.00.
    assert_posture(after, enforcement_state="RESTRICTED",
                   disbursement_state="RESERVE_HELD", severity_points_balance="8.00")
    # The stored points never change; only their weight in the balance does.
    assert_points(read_action(api, a1["id"])["severity_points_applied"], "2.00",
                  "severity_points_applied")


def test_an_action_a_full_year_old_contributes_nothing_to_the_balance(api):
    """PRD §3.6: "Otherwise, an action younger than 180 days takes a factor of 1.00,
    an action at least 180 days old but younger than 365 days takes a factor of
    0.50, and an action 365 days old or older takes a factor of 0.00 and thereby
    contributes nothing."

    Design: Corner/calculations/calc_decay_tier_three_zeroes_an_action_at_365_days
    """
    set_clock(api, JANUARY)
    rule_la = publish_rule(
        api, code="LA-AGE-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    rule_sp = publish_rule(
        api, code="SP-AGE-1", category="SHIPPING_PERFORMANCE", base_severity_weight=3.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = register_seller(
        api, legal_name="Harborline Tools LLC", email="ops@harborline-tools.example",
        tax_id_hash="TAX-HL-0001", payout_bank_token="BANK-HL-0001",
        address_fingerprint="ADDR-HL-0001",
    )
    first = substantiated_violation(
        api, seller["id"], rule_la["id"], reporter_type="BUYER",
        evidence_reference="EV-AGE-0001",
    )
    a1 = issue_action(api, first["id"])
    assert_posture(read_seller(api, seller["id"]), enforcement_state="WATCHLIST",
                   severity_points_balance="2.00")
    # Exactly 365 days later, which falls through the `age_days < 365` band.
    set_clock(api, NEXT_JANUARY)
    second = substantiated_violation(
        api, seller["id"], rule_sp["id"], reporter_type="PLATFORM_AUTOMATION",
        evidence_reference="EV-AGE-0002",
    )

    a2 = issue_action(api, second["id"])

    # No prior shipping-performance action exists, so the repeat factor is 1.00.
    assert_points(a2["severity_points_applied"], "3.00", "severity_points_applied")
    assert a2["ladder_rung_computed"] == "WARNING"
    assert_instant_equals(a2["issued_at"], NEXT_JANUARY, "issued_at")

    after = read_seller(api, seller["id"])
    # a1 contributes 2.00 x 0.00; the half-weight reading would give 4.00 and
    # wrongly restrict the account.
    assert_posture(after, enforcement_state="WATCHLIST",
                   disbursement_state="RESERVE_HELD", severity_points_balance="3.00")
    fully_decayed = read_action(api, a1["id"])
    assert fully_decayed["state"] == "ISSUED"
    assert_points(fully_decayed["severity_points_applied"], "2.00",
                  "severity_points_applied")


# --------------------------------------------------------------------------
# The health score: capped ratios, a floored score, and the tier ladder
# --------------------------------------------------------------------------
def _catastrophic_seller_with_no_shipping_rule_on_file(api):
    """One window in which every metric fails as badly as it can: 100 substantiated
    claims against 1000 settled orders, 200 late shipments, 100 cancellations and
    not one shipment with valid tracking. The policy catalogue is deliberately
    empty, so the breaching tier has no shipping-performance account-scoped rule to
    cite."""
    set_clock(api, CLOCK)
    seller = register_seller(
        api, legal_name="Harborline Tools LLC", email="ops@harborline-tools.example",
        tax_id_hash="TAX-HL-0001", payout_bank_token="BANK-HL-0001",
        address_fingerprint="ADDR-HL-0001",
    )
    file_snapshot(
        api, seller["id"], JULY, CLOCK,
        order_volume=1000, delivered_or_refunded_volume=1000, defect_claims_pending=0,
        defect_claims_substantiated=100, late_shipments=200,
        pre_fulfillment_cancellations=100, shipments_total=1000,
        shipments_with_valid_tracking=0,
    )
    return seller


def test_every_overshoot_ratio_is_capped_and_the_score_is_floored_at_zero(api):
    """PRD §3.4: "For each of the three "lower is better" metrics the overshoot
    ratio is computed by subtracting the metric's threshold from the metric's rate,
    replacing a negative difference with zero, dividing the result by that same
    threshold, and capping the quotient at 2.0000."

    PRD §3.4: "Finally, subtract the penalty total from 100.00, round half-up to two
    decimals, and take the greater of that figure and 0.00; the result is
    `health_score`."

    Design: Corner/calculations/calc_health_score_ratios_cap_and_floor_the_score_at_zero
    """
    seller = _catastrophic_seller_with_no_shipping_rule_on_file(api)

    evaluation = validate_success(
        api.create_health_evaluation(seller["id"], INVESTIGATOR), 201
    )

    assert evaluation["order_volume_final"] == 1000
    assert_rate(evaluation["odr_final"], "0.1000", "odr_final")
    assert_rate(evaluation["odr_provisional"], "0.1000", "odr_provisional")
    assert_rate(evaluation["odr_variant_delta"], "0.0000", "odr_variant_delta")
    assert_rate(evaluation["late_shipment_rate"], "0.2000", "late_shipment_rate")
    assert_rate(evaluation["cancellation_rate"], "0.1000", "cancellation_rate")
    assert_rate(evaluation["valid_tracking_rate"], "0.0000", "valid_tracking_rate")
    # The defect ratio overshoots nine-fold, the late ratio four-fold and the
    # cancellation ratio three-fold, yet each is clamped to 2.0000 before it is
    # weighted: 85.00 + 49.00 + 37.00 + 14.50 = 185.50.
    assert_points(evaluation["health_score"], "0.00", "health_score")
    assert evaluation["metric_tier"] == "BREACHING"
    assert evaluation["breached_metrics"] == [
        "ORDER_DEFECT_RATE", "LATE_SHIPMENT_RATE", "CANCELLATION_RATE",
        "VALID_TRACKING_RATE",
    ]

    after = read_seller(api, seller["id"])
    assert_points(after["health_score"], "0.00", "health_score")
    assert after["metric_tier"] == "BREACHING"
    # A metric tier never moves the enforcement dimension.
    assert_posture(after, enforcement_state="ACTIVE", disbursement_state="NORMAL",
                   severity_points_balance="0.00")


def test_a_breaching_tier_with_no_citable_rule_mints_nothing_and_still_files(api):
    """PRD §3.4: "Should the candidate pool be empty — no rule in the catalogue is
    both a shipping-performance rule and account-scoped — no violation is created,
    `auto_violation_id` stays null, and the evaluation is nonetheless filed and
    returned with a 201 status."

    Design: Corner/calculations/calc_health_score_ratios_cap_and_floor_the_score_at_zero
    """
    seller = _catastrophic_seller_with_no_shipping_rule_on_file(api)

    evaluation = validate_success(
        api.create_health_evaluation(seller["id"], INVESTIGATOR), 201
    )

    assert evaluation["metric_tier"] == "BREACHING"
    assert evaluation["auto_violation_id"] is None
    rows, meta = validate_paginated(
        api.list_violations(INVESTIGATOR, {"seller_id": seller["id"]})
    )
    assert rows == [], f"the empty candidate pool minted a violation anyway: {rows}"
    assert_meta(meta, total_count=0, has_more=False)
    # Nothing was minted, so nothing gates the funds dimension.
    assert_posture(read_seller(api, seller["id"]), disbursement_state="NORMAL")


def test_a_zero_volume_seller_is_exempt_rather_than_perfectly_healthy(api):
    """PRD §3.4: "If `order_volume_final` is zero the tier is `EXEMPT`, because a
    seller with no orders in the window cannot meaningfully be graded."

    PRD §3.4: "The `valid_tracking_rate` is the sum of
    `shipments_with_valid_tracking` over the set divided by the sum of
    `shipments_total` over the set, rounded half-up to four decimals — except that
    when the summed `shipments_total` is zero the rate is exactly `1.0000`, because
    a seller who shipped nothing has not failed to provide tracking."

    Design: Corner/calculations/calc_zero_volume_seller_is_exempt_not_healthy
    """
    set_clock(api, CLOCK)
    seller = register_seller(
        api, legal_name="Harborline Tools LLC", email="ops@harborline-tools.example",
        tax_id_hash="TAX-HL-0001", payout_bank_token="BANK-HL-0001",
        address_fingerprint="ADDR-HL-0001",
    )
    file_snapshot(
        api, seller["id"], JULY, CLOCK,
        order_volume=0, delivered_or_refunded_volume=0, defect_claims_pending=0,
        defect_claims_substantiated=0, late_shipments=0,
        pre_fulfillment_cancellations=0, shipments_total=0,
        shipments_with_valid_tracking=0,
    )

    evaluation = validate_success(
        api.create_health_evaluation(seller["id"], OFFICER), 201
    )

    # EXEMPT is the first condition of the ladder, so it wins over HEALTHY even
    # though the score is a perfect hundred and nothing breached.
    assert evaluation["metric_tier"] == "EXEMPT"
    assert_points(evaluation["health_score"], "100.00", "health_score")
    assert evaluation["order_volume_final"] == 0
    assert evaluation["input_snapshot_count"] == 1
    assert_rate(evaluation["odr_provisional"], "0.0000", "odr_provisional")
    assert_rate(evaluation["odr_final"], "0.0000", "odr_final")
    assert_rate(evaluation["late_shipment_rate"], "0.0000", "late_shipment_rate")
    assert_rate(evaluation["cancellation_rate"], "0.0000", "cancellation_rate")
    # The two zero-denominator guards fire in opposite directions: 1.0000 here,
    # which is why the 0.9500 floor is not breached.
    assert_rate(evaluation["valid_tracking_rate"], "1.0000", "valid_tracking_rate")
    assert evaluation["breached_metrics"] == []

    assert read_seller(api, seller["id"])["metric_tier"] == "EXEMPT"


def test_the_input_set_is_lookback_bounded_before_it_is_truncated(api):
    """PRD §3.4: "A candidate snapshot must belong to the subject seller, must have a
    `window_end` no later than the current logical clock reading, and must have a
    `window_end` strictly later than ninety days before that reading — the
    trailing-quarter lookback."

    PRD §3.4: "Otherwise the row records `input_snapshot_count` as the number of
    snapshots in the set, which is therefore either 1 or 2; `input_window_start` as
    the `window_start` of the earliest snapshot in the set; and `input_window_end`
    as the `window_end` of the latest."

    Design: Corner/calculations/calc_evaluation_input_set_is_lookback_bounded_then_truncated
    """
    set_clock(api, CLOCK)
    seller = register_seller(
        api, legal_name="Harborline Tools LLC", email="ops@harborline-tools.example",
        tax_id_hash="TAX-HL-0001", payout_bank_token="BANK-HL-0001",
        address_fingerprint="ADDR-HL-0001",
    )
    # Ninety days before 2026-08-01 is 2026-05-03, so this window is out of reach
    # however many claims it carries.
    file_snapshot(
        api, seller["id"], "2026-03-01T00:00:00.000Z", "2026-04-01T00:00:00.000Z",
        order_volume=1000, delivered_or_refunded_volume=1000, defect_claims_pending=0,
        defect_claims_substantiated=500, late_shipments=0,
        pre_fulfillment_cancellations=0, shipments_total=1000,
        shipments_with_valid_tracking=1000,
    )
    file_snapshot(
        api, seller["id"], "2026-05-10T00:00:00.000Z", "2026-06-10T00:00:00.000Z",
        order_volume=1000, delivered_or_refunded_volume=1000, defect_claims_pending=0,
        defect_claims_substantiated=5, late_shipments=0,
        pre_fulfillment_cancellations=0, shipments_total=1000,
        shipments_with_valid_tracking=1000,
    )
    file_snapshot(
        api, seller["id"], "2026-06-20T00:00:00.000Z", "2026-07-20T00:00:00.000Z",
        order_volume=1000, delivered_or_refunded_volume=1000, defect_claims_pending=0,
        defect_claims_substantiated=5, late_shipments=0,
        pre_fulfillment_cancellations=0, shipments_total=1000,
        shipments_with_valid_tracking=1000,
    )

    evaluation = validate_success(
        api.create_health_evaluation(seller["id"], INVESTIGATOR), 201
    )

    assert evaluation["input_snapshot_count"] == 2
    # 10 / 2000; readmitting the excluded window would give 0.1700 and a breach.
    assert_rate(evaluation["odr_final"], "0.0050", "odr_final")
    assert_rate(evaluation["odr_provisional"], "0.0050", "odr_provisional")
    assert_rate(evaluation["odr_variant_delta"], "0.0000", "odr_variant_delta")
    assert evaluation["order_volume_final"] == 2000
    # The surviving set's own bounds, not the whole snapshot history's.
    assert_instant_equals(evaluation["input_window_start"], "2026-05-10T00:00:00.000Z",
                          "input_window_start")
    assert_instant_equals(evaluation["input_window_end"], "2026-07-20T00:00:00.000Z",
                          "input_window_end")
    assert_points(evaluation["health_score"], "100.00", "health_score")
    assert evaluation["metric_tier"] == "HEALTHY"
    assert evaluation["breached_metrics"] == []

    # Exclusion from the input set is not deletion: all three rows are on file.
    _, meta = validate_paginated(api.list_seller_snapshots(seller["id"], OFFICER))
    assert_meta(meta, total_count=3, has_more=False)


# --------------------------------------------------------------------------
# Registration signal weights: the cap, the fixed order, and the two gates
# --------------------------------------------------------------------------
def test_all_five_matching_signals_cap_the_confidence_score_at_one(api):
    """PRD §3.1: "The summed weight is capped at 1.00 and then rounded half-up to two
    decimals to become the pair's `confidence_score`; because the five weights total
    1.25, the cap is genuinely reachable."

    PRD §3.1: "The link records `candidate_seller_id` for the newly registered seller
    and `matched_seller_id` for the incumbent, lists the signals that matched in
    `matched_signals` using the fixed order `TAX_ID`, `BANK_TOKEN`, `ADDRESS`,
    `EMAIL_DOMAIN`, `DEVICE`, and freezes the incumbent's posture at that moment into
    `matched_seller_state_at_detection` so that a later change to the incumbent's
    account cannot rewrite the evidence."

    PRD §3.1: "If — and only if — that top link scores 0.60 or higher *and* its
    `matched_seller_state_at_detection` is `BANNED` or `SUSPENDED`, the new account's
    `registration_risk_flag` becomes true."

    Design: Corner/calculations/calc_related_account_score_caps_at_one_with_signals_in_fixed_order
    """
    set_clock(api, CLOCK)
    incumbent = register_seller(
        api, legal_name="Harborline Tools LLC", email="ops@harborline-tools.example",
        tax_id_hash="TAX-SHARED", payout_bank_token="BANK-SHARED",
        address_fingerprint="ADDR-SHARED", device_fingerprint="DEV-SHARED",
    )

    candidate = register_seller(
        api, legal_name="Harborline Tools Outlet LLC",
        email="outlet@harborline-tools.example", tax_id_hash="TAX-SHARED",
        payout_bank_token="BANK-SHARED", address_fingerprint="ADDR-SHARED",
        device_fingerprint="DEV-SHARED",
    )

    links, meta = validate_paginated(
        api.list_related_account_links(OFFICER, {"candidate_seller_id": candidate["id"]})
    )
    assert_meta(meta, total_count=1, has_more=False)
    link = links[0]
    # 0.35 + 0.45 + 0.15 + 0.10 + 0.20 = 1.25, stored as the capped 1.00.
    assert_points(link["confidence_score"], "1.00", "confidence_score")
    assert link["matched_signals"] == [
        "TAX_ID", "BANK_TOKEN", "ADDRESS", "EMAIL_DOMAIN", "DEVICE",
    ]
    assert link["candidate_seller_id"] == candidate["id"]
    assert link["matched_seller_id"] == incumbent["id"]
    assert link["matched_seller_state_at_detection"] == "ACTIVE"
    assert link["state"] == "DETECTED"
    assert_instant_equals(link["detected_at"], CLOCK, "detected_at")

    fresh = read_seller(api, candidate["id"])
    # root_seller_id comes from the top link's existence, not from the risk flag.
    assert fresh["root_seller_id"] == incumbent["id"]
    assert fresh["registration_risk_flag"] is False
    assert_posture(fresh, enforcement_state="ACTIVE", disbursement_state="NORMAL",
                   severity_points_balance="0.00")
    assert notices_for(read_notices(api, candidate["id"]), "REGISTRATION_FLAGGED") == []

    # Scoring a candidate never writes to the incumbent it was scored against.
    unchanged = read_seller(api, incumbent["id"])
    assert unchanged["version"] == 1
    assert_posture(unchanged, enforcement_state="ACTIVE", disbursement_state="NORMAL")


def test_a_public_mailbox_domain_is_no_signal_and_a_low_score_mints_no_link(api):
    """PRD §3.1: "That derived domain participates in matching only when it is not one
    of the four public mailbox providers the marketplace disregards — `gmail.com`,
    `yahoo.com`, `outlook.com`, and `hotmail.com` — because thousands of unrelated
    sellers share those."

    PRD §3.1: "Where no incumbent reaches 0.35, no link is minted at all."

    Design: Corner/calculations/calc_public_email_domain_is_not_a_signal_and_min_score_gates_the_link
    """
    set_clock(api, CLOCK)
    incumbent = register_seller(
        api, legal_name="Harborline Tools LLC", email="a.harbor@gmail.com",
        tax_id_hash="TAX-PUB", payout_bank_token="BANK-A",
        address_fingerprint="ADDR-PUB",
    )

    shares_tax_id = register_seller(
        api, legal_name="Beacon Hardware LLC", email="b.harbor@gmail.com",
        tax_id_hash="TAX-PUB", payout_bank_token="BANK-B",
        address_fingerprint="ADDR-B",
    )
    shares_address_only = register_seller(
        api, legal_name="Cedar Fasteners LLC", email="ops@cedar-fasteners.example",
        tax_id_hash="TAX-C", payout_bank_token="BANK-C",
        address_fingerprint="ADDR-PUB",
    )

    linked, linked_meta = validate_paginated(
        api.list_related_account_links(
            OFFICER, {"candidate_seller_id": shares_tax_id["id"]}
        )
    )
    assert_meta(linked_meta, total_count=1, has_more=False)
    # The shared gmail.com domain is disregarded, so the score is 0.35 and not 0.45.
    assert_points(linked[0]["confidence_score"], "0.35", "confidence_score")
    assert linked[0]["matched_signals"] == ["TAX_ID"]
    assert linked[0]["matched_seller_id"] == incumbent["id"]

    # A bare address match is worth 0.15, which is below the 0.35 gate, and the
    # gate governs row creation rather than merely the risk flag.
    unlinked, unlinked_meta = validate_paginated(
        api.list_related_account_links(
            OFFICER, {"candidate_seller_id": shares_address_only["id"]}
        )
    )
    assert unlinked == [], f"a 0.15 match minted a link anyway: {unlinked}"
    assert_meta(unlinked_meta, total_count=0, has_more=False)

    scored = read_seller(api, shares_tax_id["id"])
    assert scored["root_seller_id"] == incumbent["id"]
    assert scored["registration_risk_flag"] is False
    assert_posture(scored, enforcement_state="ACTIVE", disbursement_state="NORMAL")
    ignored = read_seller(api, shares_address_only["id"])
    assert ignored["root_seller_id"] is None
    assert ignored["registration_risk_flag"] is False
    assert_posture(ignored, enforcement_state="ACTIVE", disbursement_state="NORMAL")


# --------------------------------------------------------------------------
# The reserve percentage is selected by the snapshotted risk tier
# --------------------------------------------------------------------------
def test_a_rolling_reserve_is_priced_at_the_tier_two_percentage(api):
    """PRD §3.9: "Failing that, the tier is `TIER_2` when `severity_points_balance` is
    4.00 or more, or `metric_tier` is `AT_RISK`, or `registration_risk_flag` is true."

    PRD §3.9: "Under `ROLLING`, the reserve is a share of the balance actually sitting
    on the account: multiply `available_balance_cents` by the tier's rolling
    percentage — 10 percent at `TIER_1`, 20 percent at `TIER_2`, and 30 percent at
    `TIER_3` — and round the product half-up to a whole number of cents."

    Design: Corner/calculations/calc_rolling_reserve_uses_the_tier_two_percentage
    """
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="LA-RES-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = register_seller(
        api, legal_name="Harborline Tools LLC", email="ops@harborline-tools.example",
        tax_id_hash="TAX-HL-0001", payout_bank_token="BANK-HL-0001",
        address_fingerprint="ADDR-HL-0001",
    )
    credit(api, seller["id"], 200000, "PAYOUT-CYCLE-2026-07-K")
    file_snapshot(
        api, seller["id"], "2026-05-01T00:00:00.000Z", "2026-06-01T00:00:00.000Z",
        order_volume=1000, delivered_or_refunded_volume=1000, defect_claims_pending=0,
        defect_claims_substantiated=0, late_shipments=0,
        pre_fulfillment_cancellations=0, shipments_total=1000,
        shipments_with_valid_tracking=1000,
    )
    file_snapshot(
        api, seller["id"], JULY, CLOCK,
        order_volume=1000, delivered_or_refunded_volume=1000, defect_claims_pending=0,
        defect_claims_substantiated=30, late_shipments=0,
        pre_fulfillment_cancellations=0, shipments_total=1000,
        shipments_with_valid_tracking=1000,
    )
    # 30 / 2000 = 0.0150, an overshoot of half the threshold: 21.25 off a hundred.
    evaluation = evaluate(api, seller["id"], INVESTIGATOR)
    assert_rate(evaluation["odr_final"], "0.0150", "odr_final")
    assert_points(evaluation["health_score"], "78.75", "health_score")
    assert evaluation["metric_tier"] == "AT_RISK"
    violation = file_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER",
        evidence_reference="EV-RES-0001",
    )
    open_investigation(api, violation["id"])
    version = read_seller(api, seller["id"], INVESTIGATOR)["version"]

    hold = validate_success(
        api.create_hold(
            hold_payload(
                seller["id"], CLOCK, "2026-08-20T00:00:00.000Z", version,
                hold_type="RESERVE", reserve_basis="ROLLING",
            ),
            INVESTIGATOR,
        ),
        201,
    )

    # The metric dimension alone carries the tier: the point balance is still 0.00.
    assert hold["risk_tier"] == "TIER_2"
    assert_cents(hold["held_amount_cents"], 40000, "held_amount_cents")
    assert hold["hold_type"] == "RESERVE"
    assert hold["reserve_basis"] == "ROLLING"
    assert hold["auto_created"] is False
    assert hold["state"] == "ACTIVE"
    assert hold["enforcement_action_id"] is None

    after = read_seller(api, seller["id"])
    # 20 percent of 200000; TIER_1 would have held 20000 and TIER_3 60000.
    assert_funds(after, available=160000, held=40000, credited=200000, debited=0)
    assert_posture(after, enforcement_state="ACTIVE",
                   disbursement_state="RESERVE_HELD", severity_points_balance="0.00")
    held_notices = notices_for(read_notices(api, seller["id"]), "FUNDS_HELD")
    assert len(held_notices) == 1, f"expected one FUNDS_HELD notice, got {held_notices}"
    assert_cents(held_notices[0]["amount_cents"], 40000, "amount_cents")


# --------------------------------------------------------------------------
# An empty input set is a refusal, not a zero-valued evaluation
# --------------------------------------------------------------------------
def test_an_evaluation_with_no_snapshot_inside_the_lookback_is_refused(api):
    """PRD §3.4: "Where the input set comes out empty — the seller has no snapshot
    inside the trailing ninety days — the whole request fails with
    `ERR_NO_SNAPSHOTS_IN_WINDOW` and no evaluation row is filed at all."

    Design: Corner/calculations/calc_evaluation_with_an_empty_input_set_is_rejected
    """
    set_clock(api, CLOCK)
    seller = register_seller(
        api, legal_name="Harborline Tools LLC", email="ops@harborline-tools.example",
        tax_id_hash="TAX-HL-0001", payout_bank_token="BANK-HL-0001",
        address_fingerprint="ADDR-HL-0001",
    )
    # The seller has evidence on file, just none of it inside the lookback.
    file_snapshot(
        api, seller["id"], "2026-03-01T00:00:00.000Z", "2026-04-01T00:00:00.000Z",
        order_volume=500, delivered_or_refunded_volume=500, defect_claims_pending=1,
        defect_claims_substantiated=1, late_shipments=2,
        pre_fulfillment_cancellations=1, shipments_total=500,
        shipments_with_valid_tracking=500,
    )

    response = api.create_health_evaluation(seller["id"], INVESTIGATOR)

    validate_error(response, ApiErrorId.NO_SNAPSHOTS_IN_WINDOW.value, 422)
    _, meta = validate_paginated(
        api.list_health_evaluations(INVESTIGATOR, {"seller_id": seller["id"]})
    )
    assert_meta(meta, total_count=0, has_more=False)

    after = read_seller(api, seller["id"])
    # The refused request leaves the grade unset rather than resetting it to a
    # perfect one, and it does not count as a mutation.
    assert after["health_score"] is None
    assert after["metric_tier"] is None
    assert after["open_defect_claim_units"] == 1
    assert after["version"] == 2
