"""Scorecard composite/rating boundaries, dispute cycle, overlap guard,
CRITICAL cascade, weekly forecast variants, and revenue-share split."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_active_operator, setup_active_operator_with_statement,
    setup_restaurant_available, setup_closed_week, set_clock,
    create_scorecard_payload, create_week_payload,
    make_operator_headers,
)

ADMIN = TEST_USERS["system_admin_headers"]
FC = TEST_USERS["field_consultant_headers"]
SC = TEST_USERS["selection_committee_headers"]
FIN = TEST_USERS["finance_admin_headers"]


# ---------------------------------------------------------------------------
# Weekly forecast: PROVISIONAL vs TRAILING variants
# ---------------------------------------------------------------------------

def test_weekly_forecast_provisional_from_baseline(api):
    """PRD §3.7: "While the restaurant has no `CLOSED` week on file, the
    provisional variant derives the forecast from the site's seven-day baseline
    adjusted for the six-day calendar: `baseline_weekly_revenue_cents`
    multiplied by six, divided by seven, rounded half-up to a whole cent."
    PRD §3.7: "In both variants the `planned_labor_hours` are the forecast
    divided by a labor rate of 15,000 cents per planned hour (that is, 150
    dollars of forecast revenue per labor hour), rounded up to the next whole
    hour."

    Design: Difficulty/dual_variant_calc/weekly_forecast_provisional_vs_trailing_on_operating_week
    """
    set_clock()
    restaurant = setup_restaurant_available(site_code="GA-ATL-001",
                                            baseline_weekly_revenue_cents=700000)
    resp = api.create_week(restaurant["id"],
                           create_week_payload(week_start_on="2026-09-07T00:00:00Z"), FC)
    week = validate_success(resp, expected_status=201)
    # PROVISIONAL: round_half_up(700000 * 6 / 7) = 600000; ceil(600000/15000) = 40
    assert week["forecast_revenue_cents"] == 600000
    assert week["planned_labor_hours"] == 40


def test_weekly_forecast_trailing_after_first_closed_week(api):
    """PRD §3.7: "Once the restaurant has at least one `CLOSED` week, the
    trailing variant ignores the baseline entirely and forecasts from actuals:
    the arithmetic mean of `actual_revenue_cents` across the restaurant's four
    most recent `CLOSED` operating weeks, taken most-recent-first by
    `week_start_on` — averaging however many closed weeks exist when fewer than
    four are on file — rounded half-up to a whole cent."

    Design: Difficulty/dual_variant_calc/weekly_forecast_provisional_vs_trailing_on_operating_week
    """
    set_clock()
    ctx = setup_active_operator(restaurant=setup_restaurant_available(
        site_code="GA-ATL-001", baseline_weekly_revenue_cents=700000))
    first = get_success_data(api.create_week(
        ctx["restaurant"]["id"], create_week_payload(week_start_on="2026-09-07T00:00:00Z"), FC))
    assert first["forecast_revenue_cents"] == 600000
    assert first["planned_labor_hours"] == 40
    set_clock("2026-09-14T00:00:00Z")
    # The clock advance opens the week (PLANNED -> OPEN), which mutates the
    # resource and bumps its version; re-read before closing so the OCC
    # expected_week_version matches.
    first = get_success_data(api.get_week(first["id"], FC))
    validate_success(api.close_week(
        ctx["restaurant"]["id"], first["id"],
        {"actual_revenue_cents": 650000, "expected_week_version": first["version"]}, FC))
    # TRAILING: mean of the single CLOSED week's actuals = 650000;
    # ceil(650000 / 15000) = 44.
    resp = api.create_week(ctx["restaurant"]["id"],
                           create_week_payload(week_start_on="2026-09-14T00:00:00Z"), FC)
    second = validate_success(resp, expected_status=201)
    assert second["forecast_revenue_cents"] == 650000
    assert second["planned_labor_hours"] == -(-650000 // 15000)  # ceil = 44


# ---------------------------------------------------------------------------
# Revenue share split: tiering and nested rounding
# ---------------------------------------------------------------------------

def test_revenue_share_tiered_split_mode_a(api):
    """PRD §3.8: "The first 50,000,000 cents (five hundred thousand dollars) of
    the shareable base earns the agreement's `base_share_bps`; any remainder
    above that threshold earns `base_share_bps` reduced by 500 basis points,
    floored at zero so the tier-two rate never goes negative."

    Design: Difficulty/combinatorial_formula/revenue_share_tiered_split_mode_a
    """
    set_clock()
    ctx = setup_active_operator_with_statement(actual_revenue_cents=70_000_000)
    statement = ctx["statement"]
    # gross 70,000,000 -> brand fee 10,500,000; net 59,500,000;
    # occupancy 4,760,000; shareable 54,740,000;
    # tier1 50,000,000 @ 5000bps = 25,000,000; tier2 4,740,000 @ 4500bps = 2,133,000.
    assert statement["gross_revenue_cents"] == 70_000_000
    assert statement["brand_fee_cents"] == 10_500_000
    assert statement["occupancy_charge_cents"] == 4_760_000
    assert statement["operator_share_cents"] == 27_133_000


def test_revenue_share_tier2_discount_applied_not_flat_rate(api):
    """PRD §3.8: "Each tier's share is computed as the tier's cents multiplied
    by the tier's basis-point rate divided by ten thousand and rounded half-up
    independently, and the `operator_share_cents` is the sum of the two
    independently rounded tier amounts."

    Design: Difficulty/combinatorial_formula/revenue_share_tiered_split_mode_a
    """
    set_clock()
    ctx = setup_active_operator_with_statement(actual_revenue_cents=70_000_000)
    statement = ctx["statement"]
    flat_half = 54_740_000 // 2  # what a single-rate 50% share would give
    assert statement["operator_share_cents"] == 27_133_000
    assert statement["operator_share_cents"] != flat_half


def test_revenue_share_nested_rounding_mode_b(api):
    """PRD §3.8: "The `brand_fee_cents` is the gross multiplied by 1,500 basis
    points (15 percent), divided by ten thousand, rounded half-up to a whole
    cent. Subtracting the brand fee from the gross leaves the net-after-fee
    amount; the `occupancy_charge_cents` — the franchisor's charge for the site
    and equipment it owns — is that net amount multiplied by 800 basis points
    (8 percent), divided by ten thousand, rounded half-up."

    Design: Difficulty/combinatorial_formula/revenue_share_nested_rounding_mode_b
    """
    set_clock()
    ctx = setup_active_operator_with_statement(actual_revenue_cents=10_000_001)
    statement = ctx["statement"]
    # brand fee: round_half_up(10,000,001 * 0.15) = round_half_up(1,500,000.15) = 1,500,000
    # net: 8,500,001; occupancy: round_half_up(680,000.08) = 680,000
    assert statement["brand_fee_cents"] == 1_500_000
    assert statement["occupancy_charge_cents"] == 680_000


def test_revenue_share_nested_rounding_share_rounds_half_up(api):
    """PRD §3.8: "Each tier's share is computed as the tier's cents multiplied
    by the tier's basis-point rate divided by ten thousand and rounded half-up
    independently, and the `operator_share_cents` is the sum of the two
    independently rounded tier amounts."

    Design: Difficulty/combinatorial_formula/revenue_share_nested_rounding_mode_b
    """
    set_clock()
    ctx = setup_active_operator_with_statement(actual_revenue_cents=10_000_001)
    statement = ctx["statement"]
    # shareable: 8,500,001 - 680,000 = 7,820,001 (all within tier 1);
    # share: round_half_up(7,820,001 * 0.5) = round_half_up(3,910,000.5) = 3,910,001
    assert statement["operator_share_cents"] == 3_910_001


# ---------------------------------------------------------------------------
# PROVISIONAL vs FINAL statement lifecycle
# ---------------------------------------------------------------------------

def test_provisional_statement_voids_successfully(api):
    """PRD §3.8: "A `FinanceAdmin` may instead void an `ISSUED` statement, but
    only while its kind is `PROVISIONAL`; `FINAL` statements are never voidable,
    and the attempt is refused with `ERR_STATEMENT_NOT_VOIDABLE`."
    PRD §3.8: "Voiding moves the statement to its terminal `VOID` status without
    touching the operator's lifetime total."

    Design: Difficulty/dual_variant_calc/revenue_share_provisional_vs_final_kind_divergence_on_statement
    """
    set_clock()
    ctx = setup_active_operator_with_statement(actual_revenue_cents=10_000_000)
    statement = ctx["statement"]
    assert statement["statement_kind"] == "PROVISIONAL"
    assert statement["operator_share_cents"] == 3_910_000
    resp = api.void_statement(statement["id"], FIN)
    voided = validate_success(resp)
    assert voided["statement_status"] == "VOID"
    assert voided["statement_kind"] == "PROVISIONAL"


def test_void_provisional_statement_leaves_lifetime_total_untouched(api):
    """PRD §3.8: "Voiding moves the statement to its terminal `VOID` status
    without touching the operator's lifetime total."
    PRD §3.6: "The operator is created with ... `lifetime_revenue_share_cents`
    at zero"

    Design: Difficulty/dual_variant_calc/revenue_share_provisional_vs_final_kind_divergence_on_statement
    """
    set_clock()
    ctx = setup_active_operator_with_statement(actual_revenue_cents=10_000_000)
    statement = ctx["statement"]
    validate_success(api.void_statement(statement["id"], FIN))
    operator = get_success_data(api.get_operator(ctx["operator"]["id"], ADMIN))
    assert operator["lifetime_revenue_share_cents"] == 0
    current = get_success_data(api.get_statement(statement["id"], FIN))
    assert current["statement_status"] == "VOID"


# ---------------------------------------------------------------------------
# Week close -> statement -> settle cascade onto the operator
# ---------------------------------------------------------------------------

def test_week_close_issues_provisional_statement_for_operator(api):
    """PRD §3.7: "A successful close moves the week to its terminal `CLOSED`
    status, increments its `version` by one, and automatically issues a revenue
    share statement for the restaurant's current operator."
    PRD §3.8: "The statement issued automatically at week close is `PROVISIONAL`"

    Design: Difficulty/transitive_cascade/week_close_issues_statement_and_settle_bumps_operator_lifetime
    """
    set_clock()
    ctx = setup_active_operator_with_statement(actual_revenue_cents=10_000_000)
    assert ctx["week"]["week_status"] == "CLOSED"
    statement = ctx["statement"]
    assert statement["statement_kind"] == "PROVISIONAL"
    assert statement["statement_status"] == "ISSUED"
    assert statement["operator_id"] == ctx["operator"]["id"]
    assert statement["operating_week_id"] == ctx["week"]["id"]


def test_settle_bumps_operator_lifetime_revenue_share(api):
    """PRD §3.8: "A `FinanceAdmin` settles an `ISSUED` statement, moving it to
    `SETTLED` and adding its `operator_share_cents` to the operator's
    `lifetime_revenue_share_cents` cumulative total."

    Design: Difficulty/transitive_cascade/week_close_issues_statement_and_settle_bumps_operator_lifetime
    """
    set_clock()
    ctx = setup_active_operator_with_statement(actual_revenue_cents=10_000_000)
    operator_id = ctx["operator"]["id"]
    before = get_success_data(api.get_operator(operator_id, ADMIN))
    assert before["lifetime_revenue_share_cents"] == 0
    resp = api.settle_statement(ctx["statement"]["id"], FIN)
    settled = validate_success(resp)
    assert settled["statement_status"] == "SETTLED"
    after = get_success_data(api.get_operator(operator_id, ADMIN))
    assert after["lifetime_revenue_share_cents"] == 3_910_000


# ---------------------------------------------------------------------------
# Scorecard composite boundaries
# ---------------------------------------------------------------------------

def test_scorecard_rating_boundary_composite_70_is_meets(api):
    """PRD §3.9: "On publish, the system computes the `composite_score`: the
    food safety score weighted at one half, the service speed score weighted at
    three tenths, and the community engagement score weighted at one fifth,
    summed and floored to a whole integer. The `rating` bands off the composite:
    a composite of at least 90 earns `EXCEEDS`; at least 70 earns `MEETS`; at
    least 50 earns `BELOW`; anything lower is `CRITICAL`."

    Design: Difficulty/boundary_precision_check/scorecard_rating_boundary_meets_at_70_below_at_69
    """
    set_clock()
    ctx = setup_active_operator()
    operator_id = ctx["operator"]["id"]
    resp = api.create_scorecard(operator_id, create_scorecard_payload(
        food_safety_score=70, service_speed_score=70, community_engagement_score=70), FC)
    scorecard = get_success_data(resp)
    published = validate_success(api.publish_scorecard(operator_id, scorecard["id"], FC))
    # floor(70*0.5 + 70*0.3 + 70*0.2) = 70 -> at least 70 earns MEETS
    assert published["composite_score"] == 70
    assert published["rating"] == "MEETS"


def test_scorecard_rating_boundary_composite_69_is_below(api):
    """PRD §3.9: "The `rating` bands off the composite: a composite of at least
    90 earns `EXCEEDS`; at least 70 earns `MEETS`; at least 50 earns `BELOW`;
    anything lower is `CRITICAL`."

    Design: Difficulty/boundary_precision_check/scorecard_rating_boundary_meets_at_70_below_at_69
    """
    set_clock()
    ctx = setup_active_operator()
    operator_id = ctx["operator"]["id"]
    resp = api.create_scorecard(operator_id, create_scorecard_payload(
        period_start_on="2026-09-14T00:00:00Z", period_end_on="2026-09-20T00:00:00Z",
        food_safety_score=68, service_speed_score=70, community_engagement_score=70), FC)
    scorecard = get_success_data(resp)
    published = validate_success(api.publish_scorecard(operator_id, scorecard["id"], FC))
    # floor(68*0.5 + 70*0.3 + 70*0.2) = floor(34 + 21 + 14) = 69 -> BELOW
    assert published["composite_score"] == 69
    assert published["rating"] == "BELOW"


# ---------------------------------------------------------------------------
# Scorecard dispute/republish revision loop
# ---------------------------------------------------------------------------

def test_scorecard_dispute_moves_published_to_disputed(api):
    """PRD §3.9: "The scored operator may dispute a `PUBLISHED` scorecard under
    their own identity, moving it to `DISPUTED`."

    Design: Difficulty/non_linear_state_machine/scorecard_dispute_republish_cycle
    """
    set_clock()
    ctx = setup_active_operator()
    operator_id = ctx["operator"]["id"]
    scorecard = get_success_data(api.create_scorecard(
        operator_id, create_scorecard_payload(
            food_safety_score=90, service_speed_score=80, community_engagement_score=70), FC))
    validate_success(api.publish_scorecard(operator_id, scorecard["id"], FC))
    resp = api.dispute_scorecard(operator_id, scorecard["id"], make_operator_headers(operator_id))
    disputed = validate_success(resp)
    assert disputed["scorecard_status"] == "DISPUTED"


def test_scorecard_republish_recomputes_composite_and_returns_published(api):
    """PRD §3.9: "After review, a `FieldConsultant` republishes it, moving it
    back to `PUBLISHED` and recomputing `composite_score` and `rating` from the
    component scores under the same weights and bands."

    Design: Difficulty/non_linear_state_machine/scorecard_dispute_republish_cycle
    """
    set_clock()
    ctx = setup_active_operator()
    operator_id = ctx["operator"]["id"]
    scorecard = get_success_data(api.create_scorecard(
        operator_id, create_scorecard_payload(
            food_safety_score=90, service_speed_score=80, community_engagement_score=70), FC))
    validate_success(api.publish_scorecard(operator_id, scorecard["id"], FC))
    validate_success(api.dispute_scorecard(operator_id, scorecard["id"],
                                           make_operator_headers(operator_id)))
    republished = validate_success(api.republish_scorecard(operator_id, scorecard["id"], FC))
    assert republished["scorecard_status"] == "PUBLISHED"
    # floor(90*0.5 + 80*0.3 + 70*0.2) = floor(45 + 24 + 14) = 83 -> MEETS
    assert republished["composite_score"] == 83
    assert republished["rating"] == "MEETS"


# ---------------------------------------------------------------------------
# CRITICAL cascade: publish -> operator suspended -> agreement suspended
# ---------------------------------------------------------------------------

def test_critical_scorecard_publish_computes_critical_rating(api):
    """PRD §3.9: "On publish, the system computes the `composite_score`: the
    food safety score weighted at one half, the service speed score weighted at
    three tenths, and the community engagement score weighted at one fifth,
    summed and floored to a whole integer."
    PRD §3.9: "anything lower is `CRITICAL`"

    Design: Difficulty/transitive_cascade/scorecard_critical_cascades_operator_suspend_agreement_suspend
    """
    set_clock()
    ctx = setup_active_operator()
    operator_id = ctx["operator"]["id"]
    scorecard = get_success_data(api.create_scorecard(
        operator_id, create_scorecard_payload(
            food_safety_score=40, service_speed_score=50, community_engagement_score=60), FC))
    published = validate_success(api.publish_scorecard(operator_id, scorecard["id"], FC))
    # floor(40*0.5 + 50*0.3 + 60*0.2) = floor(20 + 15 + 12) = 47 -> CRITICAL
    assert published["composite_score"] == 47
    assert published["rating"] == "CRITICAL"


def test_critical_scorecard_cascades_operator_and_agreement_suspend(api):
    """PRD §3.9: "Food safety comes first in this program: when a published
    scorecard lands `CRITICAL` and the operator is `ACTIVE`, the operator is
    immediately cascaded from `ACTIVE` to `SUSPENDED` (with the agreement
    cascade of §3.6 following from that suspension)."
    PRD §3.6: "Suspending an `ACTIVE` operator moves them to `SUSPENDED` and
    cascades the agreement from `EXECUTED` to `SUSPENDED`."

    Design: Difficulty/transitive_cascade/scorecard_critical_cascades_operator_suspend_agreement_suspend
    """
    set_clock()
    ctx = setup_active_operator()
    operator_id = ctx["operator"]["id"]
    scorecard = get_success_data(api.create_scorecard(
        operator_id, create_scorecard_payload(
            food_safety_score=40, service_speed_score=50, community_engagement_score=60), FC))
    validate_success(api.publish_scorecard(operator_id, scorecard["id"], FC))
    operator = get_success_data(api.get_operator(operator_id, ADMIN))
    assert operator["operator_status"] == "SUSPENDED"
    agreement = get_success_data(api.get_operator_agreement(operator_id, SC))[0]
    assert agreement["agreement_status"] == "SUSPENDED"


# ---------------------------------------------------------------------------
# Scorecard overlap guard
# ---------------------------------------------------------------------------

def test_scorecard_period_overlap_rejected_on_intersection(api):
    """PRD §3.9: "The new scorecard's period must not overlap the period window
    of any existing `PUBLISHED`, `DISPUTED`, or `FINAL` scorecard for the same
    operator; an overlap is refused with `ERR_SCORECARD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/scorecard_period_overlap_rejected_on_intersection
    """
    set_clock()
    ctx = setup_active_operator()
    operator_id = ctx["operator"]["id"]
    sc_a = get_success_data(api.create_scorecard(operator_id, create_scorecard_payload(
        period_start_on="2026-09-07T00:00:00Z", period_end_on="2026-09-13T00:00:00Z",
        food_safety_score=90, service_speed_score=80, community_engagement_score=70), FC))
    validate_success(api.publish_scorecard(operator_id, sc_a["id"], FC))
    sc_b = get_success_data(api.create_scorecard(operator_id, create_scorecard_payload(
        period_start_on="2026-09-10T00:00:00Z", period_end_on="2026-09-16T00:00:00Z",
        food_safety_score=80, service_speed_score=80, community_engagement_score=80), FC))
    resp = api.publish_scorecard(operator_id, sc_b["id"], FC)
    validate_error(resp, ApiErrorId.ERR_SCORECARD_OVERLAP)


def test_scorecard_overlap_rejection_leaves_second_card_draft(api):
    """PRD §3.9: "an overlap is refused with `ERR_SCORECARD_OVERLAP`."
    PRD §3.9: "A new scorecard's `scorecard_status` begins at `DRAFT`."

    Design: Difficulty/resource_temporal_overlap/scorecard_period_overlap_rejected_on_intersection
    """
    set_clock()
    ctx = setup_active_operator()
    operator_id = ctx["operator"]["id"]
    sc_a = get_success_data(api.create_scorecard(operator_id, create_scorecard_payload(
        period_start_on="2026-09-07T00:00:00Z", period_end_on="2026-09-13T00:00:00Z"), FC))
    validate_success(api.publish_scorecard(operator_id, sc_a["id"], FC))
    sc_b = get_success_data(api.create_scorecard(operator_id, create_scorecard_payload(
        period_start_on="2026-09-10T00:00:00Z", period_end_on="2026-09-16T00:00:00Z"), FC))
    validate_error(api.publish_scorecard(operator_id, sc_b["id"], FC),
                   ApiErrorId.ERR_SCORECARD_OVERLAP)
    current = get_success_data(api.get_scorecard(sc_b["id"], FC))
    assert current["scorecard_status"] == "DRAFT"
