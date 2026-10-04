"""Arbitration award math: abandonment override variant and the pinned nested
rounding order (score rounded to 2dp before tier selection)."""
from test_helpers import (
    validate_success, get_success_data,
    make_member_headers, make_panelist_headers, TEST_USERS, api_client,
    setup_arbitration_case_scheduled, create_listing, activate_listing,
    change_status, current_clock_iso,
)

STAFF = TEST_USERS["staff_headers"]

BASE_FACTORS = {
    "F1_FIRST_CONTACT": 7,
    "F2_CONTINUOUS_EFFORT": 6,
    "F3_AGENCY_DISCLOSURE": 5,
    "F4_CONTRACT_ROLE": 5,
    "F5_ABANDONMENT": 5,
}


def _run_case(api, ctx, factors, claim_amount_cents):
    """File -> decline mediation -> convene -> hold with factors -> UPHOLD.
    Returns the ruled case."""
    resp = api.create_arbitration_case(
        ctx["assoc"]["id"],
        {"respondent_member_id": ctx["respondent"]["id"],
         "listing_id": ctx["listing"]["id"],
         "claim_amount_cents": claim_amount_cents},
        make_member_headers(ctx["complainant"]["id"]))
    case = get_success_data(resp)
    get_success_data(api.record_mediation_outcome(
        ctx["assoc"]["id"], case["id"], "DECLINED", STAFF))
    panel = get_success_data(api.convene_hearing_panel(
        ctx["assoc"]["id"], "ARBITRATION", case["id"], STAFF))
    get_success_data(api.hold_hearing(
        ctx["assoc"]["id"], panel["id"],
        make_panelist_headers(panel["selected_member_ids"][0]),
        factor_scores=factors))
    get_success_data(api.rule_panel(
        ctx["assoc"]["id"], panel["id"],
        "UPHOLD", make_panelist_headers(panel["selected_member_ids"][1])))
    return get_success_data(
        api.get_arbitration_case(ctx["assoc"]["id"], case["id"], STAFF))


def _second_sold_listing(api, ctx):
    listing = create_listing(ctx["assoc"]["id"], ctx["office"]["id"],
                             ctx["complainant"]["id"])
    listing = activate_listing(ctx["assoc"]["id"], ctx["office"]["id"], listing)
    cur = current_clock_iso()
    change_status(ctx["assoc"]["id"], ctx["office"]["id"], listing, "PENDING", cur)
    return change_status(ctx["assoc"]["id"], ctx["office"]["id"], listing, "SOLD", cur)


def test_arbitration_award_abandonment_override_vs_weighted(api):
    """PRD §3.7: "One override runs after the score rounding and before tier
    selection: when `F5_ABANDONMENT` is 8 or higher — the respondent abandoned
    the transaction — the percentage is forced to zero regardless of the
    weighted score."
    PRD §3.7: "a score of at least 7.00 awards the full claim (the 7.00
    boundary is inclusive); at least 5.00 awards 60 percent; at least 3.00
    awards 30 percent; below 3.00 awards nothing."

    Design: Difficulty/dual_variant_calc/arbitration_award_abandonment_override_vs_weighted
    """
    ctx = setup_arbitration_case_scheduled(claim_amount_cents=1000000)
    # Case A: F5 = 7 -> no override; score 6.05 -> 60% tier.
    case_a = _run_case(api, ctx, dict(BASE_FACTORS, F5_ABANDONMENT=7), 1000000)
    assert case_a["status"] == "AWARDED"
    assert case_a["award_amount_cents"] == 600000, \
        f"score 6.05 -> pct 0.60 -> 600000; got {case_a['award_amount_cents']}"

    # Case B on a second SOLD listing: identical inputs but F5 = 8 -> override to 0.
    ctx["listing"] = _second_sold_listing(api, ctx)
    case_b = _run_case(api, ctx, dict(BASE_FACTORS, F5_ABANDONMENT=8), 1000000)
    assert case_b["award_amount_cents"] == 0, \
        f"F5 >= 8 forces pct 0.00 despite score 6.15; got {case_b['award_amount_cents']}"
    assert case_a["award_amount_cents"] != case_b["award_amount_cents"]


def test_arbitration_award_overturn_sets_zero(api):
    """PRD §3.7: "When the panel rules, an overturning decision sets
    `award_amount_cents` to 0."
    PRD §3.7: "The case transitions `HEARD` → `AWARDED`."

    Design: Difficulty/dual_variant_calc/arbitration_award_abandonment_override_vs_weighted
    """
    ctx = setup_arbitration_case_scheduled(claim_amount_cents=1000000)
    case = ctx["case"]
    panel = ctx["panel"]
    get_success_data(api.hold_hearing(
        ctx["assoc"]["id"], panel["id"],
        make_panelist_headers(ctx["holder_id"]),
        factor_scores=dict(BASE_FACTORS)))
    get_success_data(api.rule_panel(
        ctx["assoc"]["id"], panel["id"],
        "OVERTURN", make_panelist_headers(ctx["ruler_id"])))
    ruled = get_success_data(
        api.get_arbitration_case(ctx["assoc"]["id"], case["id"], STAFF))
    assert ruled["status"] == "AWARDED"
    assert ruled["award_amount_cents"] == 0


def test_procuring_cause_round_score_then_tier_then_round_award(api):
    """PRD §3.7: "The score is rounded half-up to two decimal places first, and
    only then is the award percentage selected: a score of at least 7.00 awards
    the full claim (the 7.00 boundary is inclusive)".
    PRD §2.5: "Arbitration procuring-cause scores are rounded half-up to two
    decimal places before tier selection, and the resulting award in cents is
    rounded half-up to an integer; rounding the claim times the percentage per
    factor and then summing is forbidden."

    Design: Difficulty/combinatorial_formula/procuring_cause_round_score_then_tier_then_round_award
    """
    ctx = setup_arbitration_case_scheduled(claim_amount_cents=1000001)
    factors = {
        "F1_FIRST_CONTACT": 10,
        "F2_CONTINUOUS_EFFORT": 7,
        "F3_AGENCY_DISCLOSURE": 6,
        "F4_CONTRACT_ROLE": 7,
        "F5_ABANDONMENT": 0,
    }
    # Raw score 6.995 -> rounds to 7.00 BEFORE tiering -> FULL tier (1.00).
    case = _run_case(api, ctx, factors, 1000001)
    assert case["status"] == "AWARDED"
    assert case["award_amount_cents"] == 1000001, (
        f"6.995 rounds to 7.00 -> full award round_half_up(1000001 * 1.00) == 1000001; "
        f"got {case['award_amount_cents']} (600001 would mean tiering used unrounded 6.995)")


def test_procuring_cause_mid_tier_award(api):
    """PRD §3.7: "at least 5.00 awards 60 percent; at least 3.00 awards 30 percent; below 3.00 awards nothing."
    PRD §3.7: "Finally the award in cents is the claim amount times the selected percentage, rounded half-up to an integer; the claim is always between 0 and the claim amount inclusive."

    Design: Difficulty/combinatorial_formula/procuring_cause_round_score_then_tier_then_round_award
    """
    ctx = setup_arbitration_case_scheduled(claim_amount_cents=1000000)
    # score = 0.30*5 + 0.25*5 + 0.15*5 + 0.20*5 + 0.10*5 = 5.00 -> 60% tier.
    factors = {k: 5 for k in (
        "F1_FIRST_CONTACT", "F2_CONTINUOUS_EFFORT", "F3_AGENCY_DISCLOSURE",
        "F4_CONTRACT_ROLE", "F5_ABANDONMENT")}
    case = _run_case(api, ctx, factors, 1000000)
    assert case["award_amount_cents"] == 600000
