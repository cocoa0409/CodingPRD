"""Corner queue — validation probes on the execution workflows: the
price-pack channel-conflict pair (pairwise gap inclusivity, e-commerce
undercut floor, club-pack minimum), forecast week alignment, launch fiscal-year
fit, review timing, and deduction claim uniqueness.

Each test translates one non-stub corner-design `validations` instance and
cites the PRD sentence that pins the asserted rule.
"""
from test_helpers import (
    ApiErrorId,
    assert_forecast,
    assert_performance_review,
    assert_price_pack_decision,
    create_approved_price_pack,
    create_deduction_payload,
    create_forecast_payload,
    create_launch_payload,
    create_launch_with_phases,
    create_ppd_payload,
    create_price_pack,
    create_review_payload,
    execute_launch,
    file_deduction,
    gate_all_phases,
    set_clock,
    setup_activated_plan,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_channel_price_gap_at_exactly_max_approved(api, manufacturer_planner_headers):
    """PRD §3.8: "The pairwise price-gap rule runs first: for every other approved decision of the plan, the gap between the candidate's `price_per_unit_cents` and the sibling's is taken as the absolute difference divided by the smaller of the two per-unit prices and expressed as a percent, and every such gap must be at most 15 percent — a gap of exactly 15 percent passes."
    PRD §3.8: "Every decision carries a computed `price_per_unit_cents`, its `list_price_cents` divided by `unit_count` rounded UP to the next whole cent — never banker's, never nearest — so per-unit comparisons across channels always use whole-cent figures."
    PRD §3.8: "A candidate that clears both gates moves `PROPOSED → APPROVED` with its `version` incremented."

    MASS sibling at 600/6 = 100 cents per unit; GROCERY candidate at 575/5 =
    115. The gap is |115 - 100| / 100 = 15.0 percent — exactly the inclusive
    ceiling, so the approval succeeds.

    Design: Corner/validations/channel_gap_at_exactly_max_approved
    """
    scenario = setup_activated_plan(retailer_overrides={"channels": ["MASS", "GROCERY"]})
    plan_id = scenario["plan"]["id"]
    buyer = scenario["buyer_headers"]

    create_approved_price_pack(
        plan_id,
        scenario["retailer"]["id"],
        channel="MASS",
        pack_code="TB-6",
        unit_count=6,
        list_price_cents=600,
    )
    candidate = create_price_pack(
        plan_id, channel="GROCERY", pack_code="TB-5", unit_count=5, list_price_cents=575
    )
    assert candidate["price_per_unit_cents"] == 115, (
        f"ceil(575/5) must be 115, got {candidate['price_per_unit_cents']}"
    )

    decided = validate_success(
        api.decide_price_pack_decision(candidate["id"], {"decision": "APPROVE"}, buyer),
        200,
    )
    assert_price_pack_decision(decided)
    assert decided["status"] == "APPROVED", (
        f"a gap of exactly 15 percent passes, got {decided['status']}"
    )


def test_channel_price_gap_above_max_rejected(api, manufacturer_planner_headers):
    """PRD §3.8: "The pairwise price-gap rule runs first: for every other approved decision of the plan, the gap between the candidate's `price_per_unit_cents` and the sibling's is taken as the absolute difference divided by the smaller of the two per-unit prices and expressed as a percent, and every such gap must be at most 15 percent — a gap of exactly 15 percent passes."
    PRD §3.8: "Any breach rejects the approval with `ERR_CHANNEL_CONFLICT` (HTTP 422)."
    PRD §3.8: "A candidate that clears both gates moves `PROPOSED → APPROVED` with its `version` incremented."

    CONVENIENCE candidate at 351/3 = 117 against the approved MASS 100: the gap
    is 17/100 = 17 percent, one step past the ceiling, so the approval is
    rejected and the candidate stays PROPOSED.

    Design: Corner/validations/channel_gap_above_max_rejected
    """
    scenario = setup_activated_plan(retailer_overrides={"channels": ["MASS", "CONVENIENCE"]})
    plan_id = scenario["plan"]["id"]
    buyer = scenario["buyer_headers"]

    create_approved_price_pack(
        plan_id,
        scenario["retailer"]["id"],
        channel="MASS",
        pack_code="TB-6",
        unit_count=6,
        list_price_cents=600,
    )
    candidate = create_price_pack(
        plan_id, channel="CONVENIENCE", pack_code="TB-3", unit_count=3, list_price_cents=351
    )
    assert candidate["price_per_unit_cents"] == 117, (
        f"ceil(351/3) must be 117, got {candidate['price_per_unit_cents']}"
    )

    validate_error(
        api.decide_price_pack_decision(candidate["id"], {"decision": "APPROVE"}, buyer),
        ApiErrorId.ERR_CHANNEL_CONFLICT,
    )

    ppds, _ = validate_paginated(
        api.list_price_pack_decisions(plan_id, manufacturer_planner_headers)
    )
    reloaded = {p["id"]: p for p in ppds}[candidate["id"]]
    assert reloaded["status"] == "PROPOSED", (
        f"a rejected approval must not move the candidate, got {reloaded['status']}"
    )


def test_ecommerce_undercut_floor_boundary(api, manufacturer_planner_headers):
    """PRD §3.8: "Only after the pairwise rule passes does the e-commerce undercut rule run, and only when the candidate's `channel` is `ECOMMERCE`: the candidate's per-unit price must be at least the lowest per-unit price among the plan's approved non-e-commerce decisions, reduced by 10 percent and rounded up to the next whole cent; falling below that floor rejects the approval with `ERR_ECOMMERCE_UNDERCUT` (HTTP 422)."
    PRD §3.8: "Every decision carries a computed `price_per_unit_cents`, its `list_price_cents` divided by `unit_count` rounded UP to the next whole cent — never banker's, never nearest — so per-unit comparisons across channels always use whole-cent figures."

    The floor off the approved MASS 100 is ceil(100 × 0.9) = 90. The 450/5 = 90
    candidate sits exactly on the floor and is approved (its pairwise gap
    10/90 ≈ 11.11 also passes); the 445/5 = 89 candidate falls one cent below
    and fails `ERR_ECOMMERCE_UNDERCUT` even though its pairwise gap
    (11/89 ≈ 12.36) would pass.

    Design: Corner/validations/ecommerce_undercut_boundary
    """
    scenario = setup_activated_plan(retailer_overrides={"channels": ["MASS", "ECOMMERCE"]})
    plan_id = scenario["plan"]["id"]
    buyer = scenario["buyer_headers"]

    create_approved_price_pack(
        plan_id,
        scenario["retailer"]["id"],
        channel="MASS",
        pack_code="TB-6",
        unit_count=6,
        list_price_cents=600,
    )
    at_floor = create_price_pack(
        plan_id, channel="ECOMMERCE", pack_code="TB-E5", unit_count=5, list_price_cents=450
    )
    below_floor = create_price_pack(
        plan_id, channel="ECOMMERCE", pack_code="TB-E5B", unit_count=5, list_price_cents=445
    )
    assert at_floor["price_per_unit_cents"] == 90
    assert below_floor["price_per_unit_cents"] == 89

    approved = validate_success(
        api.decide_price_pack_decision(at_floor["id"], {"decision": "APPROVE"}, buyer),
        200,
    )
    assert approved["status"] == "APPROVED", (
        f"a per-unit price exactly at the undercut floor passes, got {approved['status']}"
    )

    validate_error(
        api.decide_price_pack_decision(below_floor["id"], {"decision": "APPROVE"}, buyer),
        ApiErrorId.ERR_ECOMMERCE_UNDERCUT,
    )


def test_club_pack_min_units_boundary(api, manufacturer_planner_headers):
    """PRD §3.8: "Club economics demand scale: a `CLUB`-channel pack whose `unit_count` falls below 12 is rejected with `ERR_CLUB_PACK_TOO_SMALL` (HTTP 422)."
    PRD §3.8: "Every decision carries a computed `price_per_unit_cents`, its `list_price_cents` divided by `unit_count` rounded UP to the next whole cent — never banker's, never nearest — so per-unit comparisons across channels always use whole-cent figures."

    `unit_count` 11 falls below the 12-unit club minimum and is rejected; 12 is
    exactly at the minimum and succeeds, with the per-unit price rounded up:
    ceil(1199/12) = 100.

    Design: Corner/validations/club_pack_min_units_boundary
    """
    scenario = setup_activated_plan(retailer_overrides={"channels": ["CLUB"]})
    plan_id = scenario["plan"]["id"]

    validate_error(
        api.create_price_pack_decision(
            plan_id,
            create_ppd_payload(
                channel="CLUB", pack_code="TB-C11", unit_count=11, list_price_cents=1099
            ),
            manufacturer_planner_headers,
        ),
        ApiErrorId.ERR_CLUB_PACK_TOO_SMALL,
    )

    created = validate_success(
        api.create_price_pack_decision(
            plan_id,
            create_ppd_payload(
                channel="CLUB", pack_code="TB-C12", unit_count=12, list_price_cents=1199
            ),
            manufacturer_planner_headers,
        ),
        201,
    )
    assert_price_pack_decision(created)
    assert created["price_per_unit_cents"] == 100, (
        f"ceil(1199/12) must round up to 100, got {created['price_per_unit_cents']}"
    )


def test_forecast_week_must_start_on_monday(api, supply_chain_planner_headers):
    """PRD §3.7: "The `week_start` must fall on a Monday at midnight UTC and anchors the half-open week that runs seven days forward from it; any other alignment is rejected with `ERR_WEEK_NOT_ALIGNED` (HTTP 422)."
    PRD §3.7: "A forecast carries two independent state axes. Its publication axis, `pub_status`, begins at `PUBLISHED` and can end at `SUPERSEDED`; its commitment axis, `commit_status`, begins at `UNCOMMITTED` — with `committed_cases` and `committed_at` both null — and can reach `COMMITTED`."

    2027-03-02 is a Tuesday, so it fails alignment; the Monday before it
    (2027-03-01) succeeds and is born PUBLISHED.

    Design: Corner/validations/week_not_aligned_returns_422
    """
    scenario = setup_activated_plan()
    plan_id = scenario["plan"]["id"]

    validate_error(
        api.create_forecast(
            plan_id,
            create_forecast_payload(week_start="2027-03-02T00:00:00Z"),
            supply_chain_planner_headers,
        ),
        ApiErrorId.ERR_WEEK_NOT_ALIGNED,
    )

    created = validate_success(
        api.create_forecast(
            plan_id,
            create_forecast_payload(week_start="2027-03-01T00:00:00Z"),
            supply_chain_planner_headers,
        ),
        201,
    )
    assert_forecast(created)
    assert created["pub_status"] == "PUBLISHED", (
        f"a forecast is born PUBLISHED, got {created['pub_status']}"
    )


def test_launch_date_outside_plan_fiscal_year_rejected(api, manufacturer_planner_headers):
    """PRD §3.5: "The `launch_date`'s UTC calendar year must equal the plan's `fiscal_year`; a date outside it is rejected with `ERR_LAUNCH_OUTSIDE_FISCAL_YEAR` (HTTP 422)."

    A 2028-01-10 launch date against a fiscal_year-2027 plan fails the
    fiscal-year fit.

    Design: Corner/validations/launch_outside_fiscal_year_returns_422
    """
    scenario = setup_activated_plan()  # fiscal_year 2027
    validate_error(
        api.create_launch(
            scenario["plan"]["id"],
            create_launch_payload(launch_date="2028-01-10T00:00:00Z"),
            manufacturer_planner_headers,
        ),
        ApiErrorId.ERR_LAUNCH_OUTSIDE_FISCAL_YEAR,
    )


def test_review_before_min_days_rejected_then_allowed_at_boundary(
    api, manufacturer_planner_headers
):
    """PRD §3.9: "Timing: the logical clock must have reached the launch's `launch_date` plus 84 days — exactly at that boundary the review is allowed, and any earlier attempt fails with `ERR_REVIEW_TOO_EARLY` (HTTP 422)."
    PRD §3.9: "The review is born `OPEN` with its `decision` still null — and while it stays open, the deduction cascade of §3.6 keeps recomputing its friction, score, and posture as claims move."

    Against a launch dated 2027-01-15: at launch + 83 days (2027-04-08) the
    review create fails `ERR_REVIEW_TOO_EARLY`; at exactly launch + 84 days
    (2027-04-09) it succeeds and lands OPEN.

    Design: Corner/validations/review_too_early_returns_422
    """
    scenario = setup_activated_plan()
    launch, phases = create_launch_with_phases(
        scenario["plan"]["id"], launch_date="2027-01-15T00:00:00Z"
    )
    gate_all_phases(launch["id"], phases)
    execute_launch(launch["id"], "2027-01-15T00:00:00Z")

    set_clock("2027-04-08T00:00:00Z")  # launch_date + 83 days
    validate_error(
        api.create_performance_review(
            launch["id"], create_review_payload(), manufacturer_planner_headers
        ),
        ApiErrorId.ERR_REVIEW_TOO_EARLY,
    )

    set_clock("2027-04-09T00:00:00Z")  # launch_date + 84 days exactly
    created = validate_success(
        api.create_performance_review(
            launch["id"], create_review_payload(), manufacturer_planner_headers
        ),
        201,
    )
    assert_performance_review(created)
    assert created["status"] == "OPEN", f"a review is born OPEN, got {created['status']}"


def test_duplicate_claim_reference_within_fund_rejected(api):
    """PRD §3.6: "A `RetailerBuyer` files a **Deduction** against a fund — the new claim's `fund_id` ties it to that fund — with a `claim_reference` — the retailer-side claim number, unique within the fund, with duplicates rejected `ERR_DUPLICATE_CLAIM` (HTTP 409) — a `bucket` of `EDLP` or `EVENT`, and a strictly positive `amount_cents`."

    Uniqueness is per fund with no bucket qualifier: the repeat claim rides the
    other bucket and still fails.

    Design: Corner/validations/duplicate_claim_reference_returns_409
    """
    scenario = setup_activated_plan()
    fund_id = scenario["fund"]["id"]
    retailer_id = scenario["retailer"]["id"]

    file_deduction(fund_id, retailer_id, "CL-1", bucket="EDLP", amount_cents=100)

    validate_error(
        api.create_deduction(
            fund_id,
            create_deduction_payload("CL-1", bucket="EVENT", amount_cents=200),
            scenario["buyer_headers"],
        ),
        ApiErrorId.ERR_DUPLICATE_CLAIM,
    )
