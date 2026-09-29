"""Three boundaries, on three different endpoints, each probed from both sides:
the order-defect breach threshold on the rounded rate, the suspension threshold
on the post-issuance balance, and the coverage separation on a hold interval.
"""

from test_helpers import (
    INVESTIGATOR,
    ApiErrorId,
    assert_cents,
    assert_funds,
    assert_points,
    assert_posture,
    assert_rate,
    credit,
    evaluate,
    file_snapshot,
    file_violation,
    hold_payload,
    issue_action,
    open_investigation,
    open_hold,
    publish_rule,
    read_holds,
    read_seller,
    register_seller,
    set_clock,
    substantiated_violation,
    validate_error,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00.000Z"
WINDOW_START = "2026-07-01T00:00:00.000Z"
WINDOW_END = "2026-08-01T00:00:00.000Z"


# --------------------------------------------------------------------------
# The order-defect breach threshold
# --------------------------------------------------------------------------
def _three_sellers_straddling_the_defect_threshold(api):
    """No SHIPPING_PERFORMANCE / ACCOUNT rule is published, so a BREACHING tier
    mints no automatic violation and every posture stays undisturbed."""
    set_clock(api, CLOCK)
    at_threshold = register_seller(
        api, legal_name="Quarrystone Fixtures LLC", email="ops@quarrystone-fixtures.example",
        tax_id_hash="TAX-QU-0001", payout_bank_token="BANK-QU-0001",
        address_fingerprint="ADDR-QU-0001",
    )
    rounds_up = register_seller(
        api, legal_name="Riverbend Linens LLC", email="ops@riverbend-linens.example",
        tax_id_hash="TAX-RI-0002", payout_bank_token="BANK-RI-0002",
        address_fingerprint="ADDR-RI-0002",
    )
    rounds_down = register_seller(
        api, legal_name="Stonebriar Cookware LLC", email="ops@stonebriar-cookware.example",
        tax_id_hash="TAX-ST-0003", payout_bank_token="BANK-ST-0003",
        address_fingerprint="ADDR-ST-0003",
    )
    file_snapshot(
        api, at_threshold["id"], WINDOW_START, WINDOW_END,
        order_volume=2000, delivered_or_refunded_volume=2000, defect_claims_pending=0,
        defect_claims_substantiated=20, late_shipments=80, pre_fulfillment_cancellations=0,
        shipments_total=2000, shipments_with_valid_tracking=1900, source="PLATFORM_PIPELINE",
    )
    file_snapshot(
        api, rounds_up["id"], WINDOW_START, WINDOW_END,
        order_volume=2100, delivered_or_refunded_volume=2010, defect_claims_pending=0,
        defect_claims_substantiated=20, late_shipments=84, pre_fulfillment_cancellations=0,
        shipments_total=2100, shipments_with_valid_tracking=1995, source="PLATFORM_PIPELINE",
    )
    file_snapshot(
        api, rounds_down["id"], WINDOW_START, WINDOW_END,
        order_volume=2100, delivered_or_refunded_volume=2020, defect_claims_pending=0,
        defect_claims_substantiated=20, late_shipments=84, pre_fulfillment_cancellations=0,
        shipments_total=2100, shipments_with_valid_tracking=1995, source="PLATFORM_PIPELINE",
    )
    return at_threshold, rounds_up, rounds_down


def test_the_defect_rate_is_rounded_before_it_is_compared_to_the_threshold(api):
    """PRD §3.4: "The three "lower is better" metrics breach when their rate is
    greater than **or equal to** their threshold, so `odr_final` of exactly
    `0.0100` is a breach."

    Design: Difficulty/boundary_precision_check/odr_exactly_at_breach_threshold_breaches_and_one_unit_below_does_not
    """
    at_threshold, rounds_up, rounds_down = _three_sellers_straddling_the_defect_threshold(api)

    # 20/2000 sits exactly on the threshold.
    exact = evaluate(api, at_threshold["id"], INVESTIGATOR)
    assert_rate(exact["odr_final"], "0.0100", "odr_final")
    assert exact["metric_tier"] == "BREACHING"
    assert exact["breached_metrics"] == ["ORDER_DEFECT_RATE", "LATE_SHIPMENT_RATE"]

    # 20/2010 is 0.0099502, which rounds up to the threshold before comparison.
    up = evaluate(api, rounds_up["id"], INVESTIGATOR)
    assert_rate(up["odr_final"], "0.0100", "odr_final")
    assert up["metric_tier"] == "BREACHING"
    assert_rate(up["odr_provisional"], "0.0095", "odr_provisional")
    assert_rate(up["odr_variant_delta"], "-0.0005", "odr_variant_delta")

    # 20/2020 is 0.0099010, which rounds to just below the threshold.
    down = evaluate(api, rounds_down["id"], INVESTIGATOR)
    assert_rate(down["odr_final"], "0.0099", "odr_final")
    assert down["metric_tier"] == "AT_RISK"
    assert down["breached_metrics"] == ["LATE_SHIPMENT_RATE"]


def test_a_metric_sitting_on_its_threshold_costs_nothing_yet_still_counts(api):
    """PRD §3.4: "Note the design intent: a metric sitting exactly on its threshold
    contributes no penalty at all yet still counts as breached, because the score
    measures overage while the tier measures crossing."

    Design: Difficulty/boundary_precision_check/odr_exactly_at_breach_threshold_breaches_and_one_unit_below_does_not
    """
    at_threshold, rounds_up, rounds_down = _three_sellers_straddling_the_defect_threshold(api)

    exact = evaluate(api, at_threshold["id"], INVESTIGATOR)
    up = evaluate(api, rounds_up["id"], INVESTIGATOR)
    down = evaluate(api, rounds_down["id"], INVESTIGATOR)

    # The asymmetry: 0.0400 breaches upwards, 0.9500 does not breach downwards.
    assert_rate(exact["late_shipment_rate"], "0.0400", "late_shipment_rate")
    assert "LATE_SHIPMENT_RATE" in exact["breached_metrics"]
    assert_rate(exact["valid_tracking_rate"], "0.9500", "valid_tracking_rate")
    assert "VALID_TRACKING_RATE" not in exact["breached_metrics"]

    for evaluation in (exact, up, down):
        assert_points(evaluation["health_score"], "100.00", "health_score")

    # An empty candidate pool means the breach mints nothing and moves nothing.
    assert exact["auto_violation_id"] is None
    assert_posture(read_seller(api, at_threshold["id"]), enforcement_state="ACTIVE",
                   disbursement_state="NORMAL")
    assert read_seller(api, at_threshold["id"])["metric_tier"] == "BREACHING"
    assert read_seller(api, rounds_down["id"])["metric_tier"] == "AT_RISK"


# --------------------------------------------------------------------------
# The suspension threshold on the post-issuance balance
# --------------------------------------------------------------------------
def _two_sellers_one_cent_apart(api):
    """Both sellers already carry an 8.00-point action; the second violation is
    worth 4.00 for the first seller and 3.99 for the second, and neither seller
    has a listing, a snapshot or a credit to blur the comparison."""
    set_clock(api, CLOCK)
    heavy = publish_rule(
        api, code="LA-800", category="LISTING_ACCURACY", base_severity_weight=8.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    exactly_four = publish_rule(
        api, code="RM-400", category="REVIEW_MANIPULATION", base_severity_weight=4.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    one_cent_short = publish_rule(
        api, code="RM-399", category="REVIEW_MANIPULATION", base_severity_weight=3.99,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    reaches_twelve = register_seller(
        api, legal_name="Thistlewood Decor LLC", email="ops@thistlewood-decor.example",
        tax_id_hash="TAX-TH-0001", payout_bank_token="BANK-TH-0001",
        address_fingerprint="ADDR-TH-0001",
    )
    stops_below = register_seller(
        api, legal_name="Umberfield Audio LLC", email="ops@umberfield-audio.example",
        tax_id_hash="TAX-UM-0002", payout_bank_token="BANK-UM-0002",
        address_fingerprint="ADDR-UM-0002",
    )
    first_for_a = substantiated_violation(
        api, reaches_twelve["id"], heavy["id"], reporter_type="BUYER",
        evidence_reference="EV-TH-0001",
    )
    action_a1 = issue_action(api, first_for_a["id"])
    second_for_a = substantiated_violation(
        api, reaches_twelve["id"], exactly_four["id"], reporter_type="BUYER",
        evidence_reference="EV-TH-0002",
    )
    first_for_b = substantiated_violation(
        api, stops_below["id"], heavy["id"], reporter_type="BUYER",
        evidence_reference="EV-UM-0001",
    )
    action_b1 = issue_action(api, first_for_b["id"])
    second_for_b = substantiated_violation(
        api, stops_below["id"], one_cent_short["id"], reporter_type="BUYER",
        evidence_reference="EV-UM-0002",
    )
    return (reaches_twelve, action_a1, second_for_a,
            stops_below, action_b1, second_for_b)


def test_a_post_issuance_balance_of_exactly_twelve_points_suspends(api):
    """PRD §3.6: "Because the comparisons are inclusive, a post-issuance balance of
    exactly 12.00 suspends."

    Design: Difficulty/boundary_precision_check/post_balance_exactly_at_suspend_threshold_suspends
    """
    seller, first_action, pending_violation, _, _, _ = _two_sellers_one_cent_apart(api)
    assert_points(first_action["severity_points_applied"], "8.00",
                  "severity_points_applied")

    second_action = issue_action(api, pending_violation["id"])

    assert_points(second_action["severity_points_applied"], "4.00",
                  "severity_points_applied")
    assert second_action["ladder_rung_computed"] == "ACCOUNT_SUSPENSION"
    assert second_action["action_type"] == "ACCOUNT_SUSPENSION"
    assert second_action["override_applied"] is False
    assert second_action["removed_listing_count"] == 0

    after = read_seller(api, seller["id"])
    assert_posture(after, enforcement_state="SUSPENDED", disbursement_state="FULL_HOLD",
                   severity_points_balance="12.00")
    # The sweeping row swept a zero balance; the posture still changed.
    assert_funds(after, available=0, held=0, credited=0, debited=0)


def test_one_cent_short_of_twelve_stops_at_a_listing_removal(api):
    """PRD §3.6: "Fourth, select the rung from that post-issuance balance: a balance
    of 12.00 points or more selects `ACCOUNT_SUSPENSION`; a balance of at least
    4.00 but below 12.00 selects `LISTING_REMOVAL`; anything below 4.00 selects
    `WARNING`."

    Design: Difficulty/boundary_precision_check/post_balance_exactly_at_suspend_threshold_suspends
    """
    _, _, _, seller, first_action, pending_violation = _two_sellers_one_cent_apart(api)
    assert_points(first_action["severity_points_applied"], "8.00",
                  "severity_points_applied")

    second_action = issue_action(api, pending_violation["id"])

    assert_points(second_action["severity_points_applied"], "3.99",
                  "severity_points_applied")
    assert second_action["ladder_rung_computed"] == "LISTING_REMOVAL"
    assert second_action["removed_listing_count"] == 0

    after = read_seller(api, seller["id"])
    assert_posture(after, enforcement_state="RESTRICTED", disbursement_state="RESERVE_HELD",
                   severity_points_balance="11.99")


# --------------------------------------------------------------------------
# The coverage separation between two active holds
# --------------------------------------------------------------------------
def _seller_with_one_reserve_hold(api):
    """A TIER_1 seller under investigation, credited 300000 cents, whose first
    ROLLING reserve already covers the closed interval to 2026-08-10."""
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="LA-BUF-1", category="LISTING_ACCURACY", base_severity_weight=1.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = register_seller(
        api, legal_name="Vantage Pet Supply LLC", email="ops@vantage-petsupply.example",
        tax_id_hash="TAX-VA-0001", payout_bank_token="BANK-VA-0001",
        address_fingerprint="ADDR-VA-0001",
    )
    credit(api, seller["id"], 300000, "PAYOUT-CYCLE-2026-07-E")
    violation = file_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER", evidence_reference="EV-VA-0001"
    )
    open_investigation(api, violation["id"])
    first = open_hold(
        api, seller["id"], CLOCK, "2026-08-10T00:00:00.000Z", reserve_basis="ROLLING"
    )
    return seller, first


def _rolling_attempt(api, seller_id, coverage_start, coverage_end):
    version = read_seller(api, seller_id, INVESTIGATOR)["version"]
    return api.create_hold(
        hold_payload(
            seller_id, coverage_start, coverage_end, version,
            hold_type="RESERVE", reserve_basis="ROLLING",
        ),
        INVESTIGATOR,
    )


def test_a_gap_of_exactly_twenty_four_hours_is_refused(api):
    """PRD §3.9: "Unlike measurement windows, coverage intervals may not merely
    avoid overlapping: a new interval must be separated from the interval of every
    other `ACTIVE` hold of the same seller by strictly more than twenty-four
    hours, and a new interval that touches, overlaps, or sits within a full day of
    an existing active one is refused with `ERR_HOLD_COVERAGE_OVERLAP`."

    Design: Difficulty/boundary_precision_check/hold_coverage_gap_exactly_buffer_hours_is_rejected
    """
    seller, first = _seller_with_one_reserve_hold(api)
    assert_cents(first["held_amount_cents"], 30000, "held_amount_cents")
    before = read_seller(api, seller["id"], INVESTIGATOR)

    response = _rolling_attempt(
        api, seller["id"], "2026-08-11T00:00:00.000Z", "2026-08-20T00:00:00.000Z"
    )

    validate_error(response, ApiErrorId.HOLD_COVERAGE_OVERLAP.value, 422)
    after = read_seller(api, seller["id"], INVESTIGATOR)
    assert_funds(after, available=270000, held=30000, credited=300000, debited=0)
    assert after["version"] == before["version"]
    assert [row["id"] for row in read_holds(api, params={"seller_id": seller["id"]})] == \
        [first["id"]]


def test_one_second_more_separation_is_accepted_and_re_reads_the_reduced_balance(api):
    """PRD §3.9: "Under `ROLLING`, the reserve is a share of the balance actually
    sitting on the account: multiply `available_balance_cents` by the tier's
    rolling percentage — 10 percent at `TIER_1`, 20 percent at `TIER_2`, and 30
    percent at `TIER_3` — and round the product half-up to a whole number of
    cents."

    Design: Difficulty/boundary_precision_check/hold_coverage_gap_exactly_buffer_hours_is_rejected
    """
    seller, first = _seller_with_one_reserve_hold(api)
    validate_error(
        _rolling_attempt(
            api, seller["id"], "2026-08-11T00:00:00.000Z", "2026-08-20T00:00:00.000Z"
        ),
        ApiErrorId.HOLD_COVERAGE_OVERLAP.value, 422,
    )
    before = read_seller(api, seller["id"], INVESTIGATOR)

    second = validate_success(
        _rolling_attempt(
            api, seller["id"], "2026-08-11T00:00:01.000Z", "2026-08-20T00:00:00.000Z"
        ),
        201,
    )

    # Ten percent of the already reduced 270000, not of the original 300000.
    assert_cents(second["held_amount_cents"], 27000, "held_amount_cents")
    assert second["risk_tier"] == "TIER_1"
    assert second["reserve_basis"] == "ROLLING"

    after = read_seller(api, seller["id"], INVESTIGATOR)
    assert_funds(after, available=243000, held=57000, credited=300000, debited=0)
    assert after["version"] == before["version"] + 1
    rows = read_holds(api, params={"seller_id": seller["id"]})
    assert sorted(row["id"] for row in rows) == sorted([first["id"], second["id"]])
    assert all(row["state"] == "ACTIVE" for row in rows)
