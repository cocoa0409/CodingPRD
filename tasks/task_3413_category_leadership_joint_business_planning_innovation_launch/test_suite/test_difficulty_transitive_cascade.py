"""Difficulty queue — transitive cascades.

Two multi-hop cascades: a short-paid deduction settlement mutates the fund's
settled ledger (hop 1), recomputes the OPEN review's friction_count (hop 2),
and flips its risk posture across a threshold (hop 3) (PRD §3.6/§3.9); a
DELIST finalization moves the launch to DELISTED (hop 1) and retires the
plan's matching APPROVED price-pack decisions (hop 2) (PRD §3.9/§3.8). Each
test translates one difficulty-design instance and cites the PRD rule it pins.
"""
from test_helpers import (
    assert_deduction,
    assert_fund_invariants,
    assert_innovation_launch,
    assert_performance_review,
    assert_price_pack_decision,
    assert_risk_posture_matches_score,
    assert_trade_fund,
    create_approved_price_pack,
    create_launched_launch,
    create_open_review,
    setup_activated_plan,
    setup_review_scenario,
    validate_success,
)

_LAUNCH_DATE = "2027-01-15T00:00:00Z"


def _short_paid_settle_scenario():
    """OPEN review (risk 24 / HEALTHY at creation) over a plan whose EVENT
    bucket holds exactly 1600 cents, with one RECEIVED EVENT claim of 5000."""
    return setup_review_scenario(
        accruals=(("2027-01", 100000),),
        committed_forecast=("2027-03-01T00:00:00Z", 1000, 1100),
        received_deductions=(("SHORT-1", "EVENT", 5000),),
        review_fields={
            "actual_sales_cents": 750000,
            "sales_target_cents": 1000000,
            "target_distribution_pct": 90,
            "distribution_achieved_pct": 70,
        },
    )


def test_short_paid_settlement_mutates_fund_ledger(api, finance_analyst_headers):
    """PRD §3.6: "`SETTLE` — lawful from either `RECEIVED` or `DISPUTED` — moves the claim to `SETTLED` and pays it against bucket availability: the `settled_amount_cents` becomes the smaller of the claimed `amount_cents` and the fund's availability in the claim's bucket (the event bucket's `event_available_cents` for an `EVENT` claim, the EDLP bucket's `edlp_available_cents` for an `EDLP` claim), `short_paid` flags whether the settled amount fell short of the claim, and the settled sum accumulates into the fund's `edlp_settled_cents` or `event_settled_cents` accordingly."
    PRD §2.11: "the event bucket's `event_available_cents` is what accrued minus what is currently reserved minus what has settled."

    Hop 1 of the cascade: min(5000, 1600) settles 1600, flags short_paid, and
    drains event_available_cents to zero. The review's pre-cascade anchor is
    risk_score 24 / HEALTHY.

    Design: Difficulty/transitive_cascade/deduction_settle_cascade_to_review_posture
    """
    scenario = _short_paid_settle_scenario()
    review = scenario["review"]
    assert review["risk_score"] == 24 and review["risk_posture"] == "HEALTHY", (
        f"pre-cascade anchor must be 24/HEALTHY, got {review['risk_score']}/{review['risk_posture']}"
    )

    deduction = validate_success(
        api.resolve_deduction(
            scenario["deductions"][0]["id"], {"action": "SETTLE"}, finance_analyst_headers
        ),
        200,
    )
    assert_deduction(deduction)
    assert deduction["status"] == "SETTLED"
    assert deduction["settled_amount_cents"] == 1600, (
        f"min(5000, event_available 1600) must settle 1600, got {deduction['settled_amount_cents']}"
    )
    assert deduction["short_paid"] is True

    fund = validate_success(api.get_fund(scenario["fund"]["id"], finance_analyst_headers), 200)
    assert_trade_fund(fund)
    assert fund["event_settled_cents"] == 1600
    assert fund["event_accrued_cents"] == 1600
    assert fund["event_available_cents"] == 0, (
        f"1600 accrued - 0 reserved - 1600 settled must leave 0, got {fund['event_available_cents']}"
    )
    assert_fund_invariants(fund)


def test_short_paid_settlement_flips_review_posture(api, finance_analyst_headers, manufacturer_planner_headers):
    """PRD §3.6: "At hop two the server recomputes `friction_count` on every `OPEN` performance review whose launch belongs to the fund's plan: that count covers the fund's deductions created within the review's window whose status is `DISPUTED` or `WRITTEN_OFF`, plus those `SETTLED` with `short_paid` true, so a dispute adds friction and a rejection of a disputed claim removes it again."
    PRD §3.6: "At hop three those reviews recompute their `risk_score` and `risk_posture`, which can flip a review's posture across the risk thresholds (§3.9) while the review is still open."
    PRD §3.9: "The `risk_posture` reads straight off the score: at least 75 is `DELIST_RECOMMENDED`, at least 50 is `AT_RISK`, at least 25 is `WATCH`, and anything below is `HEALTHY`."

    Hops 2-3: the short-paid settlement lifts friction_count 0 -> 1 and the
    score 24 -> 26 (0.1*min(1,5)*20), flipping HEALTHY -> WATCH while the
    review stays OPEN.

    Design: Difficulty/transitive_cascade/deduction_settle_cascade_to_review_posture
    """
    scenario = _short_paid_settle_scenario()
    review = scenario["review"]
    assert review["friction_count"] == 0, "a RECEIVED claim must not count as friction"
    assert review["risk_score"] == 24 and review["risk_posture"] == "HEALTHY"

    validate_success(
        api.resolve_deduction(
            scenario["deductions"][0]["id"], {"action": "SETTLE"}, finance_analyst_headers
        ),
        200,
    )

    reviews = validate_success(
        api.list_performance_reviews(scenario["launch"]["id"], manufacturer_planner_headers), 200
    )
    assert len(reviews) == 1
    refreshed = reviews[0]
    assert_performance_review(refreshed)
    assert refreshed["status"] == "OPEN"
    assert refreshed["friction_count"] == 1, (
        f"a short-paid SETTLED claim must count, got {refreshed['friction_count']}"
    )
    assert refreshed["risk_score"] == 26, (
        f"24 + 0.1*min(1,5)*20 must recompute to 26, got {refreshed['risk_score']}"
    )
    assert refreshed["risk_posture"] == "WATCH", (
        f"26 >= 25 must flip the posture to WATCH, got {refreshed['risk_posture']}"
    )
    assert_risk_posture_matches_score(refreshed)


def _delist_scenario():
    """ACTIVATED plan with an APPROVED 'tabs' price-pack (ppu 100) and a
    LAUNCHED 'tabs' launch carrying one OPEN review."""
    scenario = setup_activated_plan()
    plan_id = scenario["plan"]["id"]
    ppd = create_approved_price_pack(plan_id, scenario["retailer"]["id"], list_price_cents=599)
    launch, _phases = create_launched_launch(plan_id, launch_date=_LAUNCH_DATE)
    review = create_open_review(
        launch["id"],
        _LAUNCH_DATE,
        actual_sales_cents=900000,
        sales_target_cents=1000000,
        target_distribution_pct=90,
        distribution_achieved_pct=90,
    )
    return scenario, ppd, launch, review


def test_delist_finalize_moves_launch_to_delisted(api, manufacturer_planner_headers):
    """PRD §3.9: "The `RetailerBuyer` of the plan that owns the review's launch closes an `OPEN` review with a `decision` of `CONTINUE` or `DELIST`; the payload value is recorded on the review, the review moves `OPEN → FINALIZED`, and its `version` increments."
    PRD §3.9: "`DELIST` moves the launch `LAUNCHED → DELISTED` with its `version` incremented and then fires the pack-family cascade of §3.8: every `APPROVED` price-pack decision of the same plan sharing the launch's `pack_family` transitions to `RETIRED`, each incrementing its own `version`."

    Hop 1: the review lands FINALIZED with decision DELIST and the launch moves
    LAUNCHED -> DELISTED.

    Design: Difficulty/transitive_cascade/delist_finalize_cascade_retires_price_packs
    """
    scenario, _ppd, launch, review = _delist_scenario()

    finalized = validate_success(
        api.finalize_performance_review(review["id"], {"decision": "DELIST"}, scenario["buyer_headers"]),
        200,
    )
    assert_performance_review(finalized)
    assert finalized["status"] == "FINALIZED"
    assert finalized["decision"] == "DELIST"

    refreshed_launch = validate_success(api.get_launch(launch["id"], manufacturer_planner_headers), 200)
    assert_innovation_launch(refreshed_launch)
    assert refreshed_launch["status"] == "DELISTED", (
        f"hop 1 must move the launch to DELISTED, got {refreshed_launch['status']}"
    )


def test_delist_finalize_retires_matching_price_packs(api, manufacturer_planner_headers):
    """PRD §3.9: "`DELIST` moves the launch `LAUNCHED → DELISTED` with its `version` incremented and then fires the pack-family cascade of §3.8: every `APPROVED` price-pack decision of the same plan sharing the launch's `pack_family` transitions to `RETIRED`, each incrementing its own `version`."
    PRD §3.8: "Every decision carries a computed `price_per_unit_cents`, its `list_price_cents` divided by `unit_count` rounded UP to the next whole cent — never banker's, never nearest — so per-unit comparisons across channels always use whole-cent figures."

    Hop 2: the plan's APPROVED 'tabs' decision lands RETIRED; its
    price_per_unit_cents stays ceil(599/6) = 100 — retirement mutates only the
    lifecycle state.

    Design: Difficulty/transitive_cascade/delist_finalize_cascade_retires_price_packs
    """
    scenario, ppd, _launch, review = _delist_scenario()

    validate_success(
        api.finalize_performance_review(review["id"], {"decision": "DELIST"}, scenario["buyer_headers"]),
        200,
    )

    decisions = validate_success(
        api.list_price_pack_decisions(
            scenario["plan"]["id"], manufacturer_planner_headers, params={"pack_family": "tabs"}
        ),
        200,
    )
    assert len(decisions) == 1
    retired = decisions[0]
    assert retired["id"] == ppd["id"]
    assert_price_pack_decision(retired)
    assert retired["status"] == "RETIRED", (
        f"hop 2 must retire the matching APPROVED decision, got {retired['status']}"
    )
    assert retired["price_per_unit_cents"] == 100, (
        f"ceil(599/6)=100 must be unchanged by retirement, got {retired['price_per_unit_cents']}"
    )
