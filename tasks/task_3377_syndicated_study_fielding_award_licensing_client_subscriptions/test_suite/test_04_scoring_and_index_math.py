"""Index mathematics: dual provisional/final variants, pinned rounding order,
eligibility and tie boundaries, significance grouping (PRD §3.3, §3.4, §3.5)."""
from test_helpers import (
    ApiErrorId,
    close_fielding,
    determine_awards,
    get_brand_result_for,
    get_study,
    list_awards_for,
    list_brand_results_for,
    list_frame_responses,
    setup_fielding_study,
    setup_scored_study,
    study_goto,
    validate_error,
    compute_scores,
    api_client,
    TEST_USERS,
)

AO = TEST_USERS["awards_officer_headers"]


def _dedupe_ctx():
    """rt-1 answers twice (10/10 earlier, 2/2 later); rt-2 once (6/6)."""
    return setup_fielding_study(
        min_sample=3,
        brands=[{
            "name": "BrandA", "target": 5,
            "responses": [
                {"token": "rt-1", "qual": 10, "feat": 10, "clock": "2026-09-02T00:00:00Z"},
                {"token": "rt-1", "qual": 2, "feat": 2, "clock": "2026-09-03T00:00:00Z"},
                {"token": "rt-2", "qual": 6, "feat": 6},
            ],
        }],
    )


def test_provisional_and_final_index_diverge_after_dedupe(api):
    """PRD §3.3: "the sweep upserts exactly one `BrandResult` row per brand that
    has a frame, recording `provisional_accepted_n` as the count of `ACCEPTED`
    responses the brand had at the moment of close *before* the sweep ran,
    `provisional_index` as the index score computed over that pre-sweep accepted
    set (null when the pre-sweep accepted set is empty), and `accepted_n` as the
    post-sweep accepted count."
    PRD §3.3: "Both index variants use the same pinned mathematics of §3.4; they
    differ only in input set — provisional over the pre-sweep set, final over the
    post-sweep set."

    Design: Difficulty/dual_variant_calc/index_score_provisional_vs_final_after_dedupe
    """
    ctx = _dedupe_ctx()
    sid = ctx["study"]["id"]
    close_fielding(sid)
    study_goto(sid, "SCORING")
    compute_scores(sid)
    br = get_brand_result_for(sid, ctx["brands"]["BrandA"]["id"])
    assert br["provisional_accepted_n"] == 3, f"pre-sweep count, got {br['provisional_accepted_n']}"
    assert br["accepted_n"] == 2, f"post-sweep count, got {br['accepted_n']}"
    assert br["provisional_index"] == 600, f"pre-sweep index over (10/10, 2/2, 6/6), got {br['provisional_index']}"
    assert br["final_index"] == 800, f"post-sweep index over (10/10, 6/6), got {br['final_index']}"


def test_duplicate_sweep_rejects_later_submission(api):
    """PRD §3.3: "among the `ACCEPTED` responses in the brand that share a
    `respondent_token`, the sweep keeps the one with the earliest `submitted_at`;
    if two candidates tie on `submitted_at`, the one arriving through a `PANEL`
    frame is preferred over `CUSTOMER_LIST`; a further tie is broken by the
    earliest `created_at`. Every other response in such a sharing group flips from
    `ACCEPTED` to `REJECTED` with `reject_reason` set to `DUPLICATE` — and
    `REJECTED` is terminal for a response; nothing resurrects it."

    Design: Difficulty/dual_variant_calc/index_score_provisional_vs_final_after_dedupe
    """
    ctx = _dedupe_ctx()
    sid = ctx["study"]["id"]
    r_keep, r_lost = ctx["responses"][0]["id"], ctx["responses"][1]["id"]
    close_fielding(sid)

    rejected = list_frame_responses(ctx["frames"]["BrandA"]["id"], quality_status="REJECTED")
    assert [r["id"] for r in rejected] == [r_lost], "the later rt-1 response is swept"
    assert rejected[0]["reject_reason"] == "DUPLICATE"
    accepted = list_frame_responses(ctx["frames"]["BrandA"]["id"], quality_status="ACCEPTED")
    accepted_ids = {r["id"] for r in accepted}
    assert accepted_ids == {r_keep, ctx["responses"][2]["id"]}, (
        f"earlier submitted_at is kept, got {accepted_ids}"
    )


def test_final_index_uses_per_factor_rounding_first(api):
    """PRD §3.4: "Per-factor rounding first yields 400 and 429; the pinned weighted
    sum is then 411.6, which rounds half up to 412. A naive implementation that
    sums unrounded factor means gets 411.43 and reports 411 — off by a point, and
    visibly wrong against this document."

    Design: Difficulty/combinatorial_formula/index_score_per_factor_rounding_order
    """
    ctx = setup_scored_study(
        min_sample=3,
        brands=[{
            "name": "BrandA", "target": 7,
            "responses": [
                {"token": f"rt-{i}", "qual": 4, "feat": (5 if i <= 2 else 4), "distinct": 3}
                for i in range(1, 8)
            ],
        }],
    )
    br = get_brand_result_for(ctx["study"]["id"], ctx["brands"]["BrandA"]["id"])
    assert br["final_index"] == 412, (
        f"pinned order: 0.6*400 + 0.4*429 = 411.6 -> 412, got {br['final_index']}"
    )


def test_provisional_index_uses_per_factor_rounding_first(api):
    """PRD §2.7: "Every rounding step the calculations call for rounds half up to
    zero decimal places, and the rounding order is pinned exactly as the
    calculations in §3.4 describe: each per-factor score is rounded to an integer
    first, and the weighted sum is rounded once at the end."
    PRD §3.4: "Rounding earlier, later, or with a different rule produces
    observably different index values and is non-compliant."

    Design: Difficulty/combinatorial_formula/index_score_per_factor_rounding_order
    """
    ctx = setup_fielding_study(
        min_sample=3,
        brands=[{
            "name": "BrandA", "target": 7,
            "responses": [
                {"token": f"rt-{i}", "qual": 4, "feat": (5 if i <= 2 else 4), "distinct": 3}
                for i in range(1, 8)
            ],
        }],
    )
    close_fielding(ctx["study"]["id"])
    br = get_brand_result_for(ctx["study"]["id"], ctx["brands"]["BrandA"]["id"])
    assert br["provisional_index"] == 412, (
        f"provisional variant applies the identical pinned order, got {br['provisional_index']}"
    )
    assert br["provisional_index"] != 411, "411 is the observably wrong sum-then-round result"


def _min_sample_boundary_ctx():
    return setup_scored_study(
        min_sample=3,
        brands=[
            {"name": "BrandA", "source_type": "PANEL", "target": 4,
             "responses": [{"token": f"ra-{i}", "qual": 9, "feat": 7} for i in range(1, 4)]},
            {"name": "BrandB", "source_type": "CUSTOMER_LIST", "target": 4,
             "responses": [{"token": f"rb-{i}", "qual": 8, "feat": 6} for i in range(1, 3)]},
        ],
    )


def test_brand_at_exact_min_sample_is_eligible(api):
    """PRD §3.4: "For every `BrandResult` of the study, compute recomputes
    `accepted_n` from the post-sweep accepted set, derives `final_index` over that
    set (null when `accepted_n` is 0), and sets `eligible` to true exactly when
    `accepted_n` is at least the study's `min_sample_per_brand`; the row's `status`
    moves from `PROVISIONAL` to `FINAL`."

    Design: Difficulty/boundary_precision_check/min_sample_exact_boundary
    """
    ctx = _min_sample_boundary_ctx()
    sid = ctx["study"]["id"]
    assert ctx["compute"]["eligible_count"] == 1, f"only BrandA reaches 3, got {ctx['compute']}"
    bra = get_brand_result_for(sid, ctx["brands"]["BrandA"]["id"])
    assert bra["accepted_n"] == 3 and bra["eligible"] is True
    assert bra["final_index"] == 820, f"0.6*900 + 0.4*700, got {bra['final_index']}"
    assert bra["rank_position"] == 1 and bra["significance_group"] == 1
    assert bra["status"] == "FINAL"


def test_brand_one_below_min_sample_is_ineligible(api):
    """PRD §3.4: "Significance groups and ranks are then assigned over the eligible
    set only — ineligible brands keep both `significance_group` and `rank_position`
    null."
    PRD §3.4: "sets `eligible` to true exactly when `accepted_n` is at least the
    study's `min_sample_per_brand`"

    Design: Difficulty/boundary_precision_check/min_sample_exact_boundary
    """
    ctx = _min_sample_boundary_ctx()
    sid = ctx["study"]["id"]
    brb = get_brand_result_for(sid, ctx["brands"]["BrandB"]["id"])
    assert brb["accepted_n"] == 2, f"min_sample - 1, got {brb['accepted_n']}"
    assert brb["eligible"] is False
    assert brb["final_index"] == 720, f"0.6*800 + 0.4*600, got {brb['final_index']}"
    assert brb["rank_position"] is None and brb["significance_group"] is None


def _tie_epsilon_ctx():
    return setup_scored_study(
        min_sample=3,
        tie_epsilon=5,
        brands=[
            {"name": "BrandA", "target": 4, "responses": [
                {"token": "ra-1", "qual": 10, "feat": 8}, {"token": "ra-2", "qual": 9, "feat": 8},
                {"token": "ra-3", "qual": 9, "feat": 9}, {"token": "ra-4", "qual": 10, "feat": 7}]},
            {"name": "BrandB", "target": 4, "responses": [
                {"token": "rb-1", "qual": 10, "feat": 7}, {"token": "rb-2", "qual": 10, "feat": 8},
                {"token": "rb-3", "qual": 10, "feat": 7}, {"token": "rb-4", "qual": 9, "feat": 8}]},
            {"name": "BrandC", "target": 4, "responses": [
                {"token": "rc-1", "qual": 9, "feat": 9, "distinct": 3},
                {"token": "rc-2", "qual": 9, "feat": 8, "distinct": 3},
                {"token": "rc-3", "qual": 9, "feat": 9, "distinct": 3},
                {"token": "rc-4", "qual": 9, "feat": 8, "distinct": 3}]},
        ],
    )


def test_brand_at_exactly_tie_epsilon_shares_rank_one(api):
    """PRD §3.4: "A brand's `rank_position` is 1 plus the count of eligible brands
    whose `final_index` exceeds its own by strictly more than `tie_epsilon` index
    points. Brands within `tie_epsilon` of each other therefore share a rank —
    ties share rank 1 at the top — and ranks skip accordingly under competition
    semantics: two brands tied at the top are both rank 1 and the next brand is
    rank 2."

    Design: Difficulty/boundary_precision_check/tie_epsilon_exact_boundary
    """
    ctx = _tie_epsilon_ctx()
    sid = ctx["study"]["id"]
    bra = get_brand_result_for(sid, ctx["brands"]["BrandA"]["id"])
    brb = get_brand_result_for(sid, ctx["brands"]["BrandB"]["id"])
    brc = get_brand_result_for(sid, ctx["brands"]["BrandC"]["id"])
    assert (bra["final_index"], brb["final_index"], brc["final_index"]) == (890, 885, 880), (
        f"got {bra['final_index']}/{brb['final_index']}/{brc['final_index']}"
    )
    assert bra["rank_position"] == 1
    assert brb["rank_position"] == 1, "890 - 885 == tie_epsilon exactly: strictly-more fails, rank shared"
    assert brc["rank_position"] == 2, "only A's 890 exceeds 880 + 5"
    # All three gaps (5, 10) sit under the critical difference 83.156 -> one group.
    assert bra["significance_group"] == 1
    assert brb["significance_group"] == 1
    assert brc["significance_group"] == 1


def test_tied_brands_each_receive_award(api):
    """PRD §3.5: "The winners are exactly the brands whose `BrandResult` is
    eligible with `rank_position` 1 *and* `significance_group` 1. Both conditions
    bind."
    PRD §3.5: "Ties at the top, sharing rank 1 within group 1, each produce their
    own award."

    Design: Difficulty/boundary_precision_check/tie_epsilon_exact_boundary
    """
    ctx = _tie_epsilon_ctx()
    sid = ctx["study"]["id"]
    result = determine_awards(sid)
    assert result["award_count"] == 2, f"A and B share rank 1 in group 1, got {result['award_count']}"
    awarded_brands = {a["brand_id"] for a in list_awards_for(sid)}
    assert awarded_brands == {ctx["brands"]["BrandA"]["id"], ctx["brands"]["BrandB"]["id"]}
    brc = get_brand_result_for(sid, ctx["brands"]["BrandC"]["id"])
    assert brc["rank_position"] == 2 and brc["significance_group"] == 1
    assert brc["status"] == "FINAL", "rank 2 despite group 1 receives no award and stays FINAL"


def test_index_weights_applied_correctly_70_30(api):
    """PRD §3.4: "the index is the sum over all factors of the factor's integer
    score weighted by its `weight_bp` share of the 10000 basis points, with that
    weighted sum rounded half up to an integer exactly once, at the end."

    Design: Corner/calculations/index_weights_applied_correctly_70_30
    """
    ctx = setup_scored_study(
        min_sample=1,
        weights=[("QUAL", "Quality & Reliability", 7000), ("FEAT", "Features & Controls", 3000)],
        brands=[{"name": "BrandA", "responses": [{"token": "rt-1", "qual": 9, "feat": 6}]}],
    )
    br = get_brand_result_for(ctx["study"]["id"], ctx["brands"]["BrandA"]["id"])
    assert br["final_index"] == 810, f"0.7*900 + 0.3*600, got {br['final_index']}"
    assert br["eligible"] is True and br["rank_position"] == 1


def test_significance_grouping_excludes_close_runner_up(api):
    """PRD §3.4: "If the leader's `final_index` minus the candidate's `final_index`
    is strictly greater than that critical difference, the candidate opens a new
    significance group — numbered one past the previous group — and becomes its
    leader; otherwise it joins the current group."
    PRD §3.5: "A brand sitting in significance group 1 whose `rank_position` is 2 —
    within the critical difference of the leader but strictly more than
    `tie_epsilon` index points below it — is statistically indistinguishable from
    the winner yet receives no award."

    Design: Corner/calculations/significance_grouping_excludes_close_runner_up
    """
    ctx = setup_scored_study(
        min_sample=3,
        brands=[
            {"name": "BrandA", "target": 4, "responses": [
                {"token": "ra-1", "qual": 10, "feat": 8}, {"token": "ra-2", "qual": 10, "feat": 7},
                {"token": "ra-3", "qual": 10, "feat": 8}, {"token": "ra-4", "qual": 10, "feat": 7}]},
            {"name": "BrandB", "target": 4, "responses": [
                {"token": "rb-1", "qual": 10, "feat": 7}, {"token": "rb-2", "qual": 9, "feat": 7},
                {"token": "rb-3", "qual": 10, "feat": 7}, {"token": "rb-4", "qual": 9, "feat": 7}]},
            {"name": "BrandC", "target": 8, "responses": [
                {"token": "rc-1", "qual": 9, "feat": 7}, {"token": "rc-2", "qual": 9, "feat": 6},
                {"token": "rc-3", "qual": 9, "feat": 7}, {"token": "rc-4", "qual": 9, "feat": 6},
                {"token": "rc-5", "qual": 9, "feat": 6}, {"token": "rc-6", "qual": 9, "feat": 7},
                {"token": "rc-7", "qual": 9, "feat": 6}, {"token": "rc-8", "qual": 9, "feat": 6}]},
        ],
    )
    sid = ctx["study"]["id"]
    bra = get_brand_result_for(sid, ctx["brands"]["BrandA"]["id"])
    brb = get_brand_result_for(sid, ctx["brands"]["BrandB"]["id"])
    brc = get_brand_result_for(sid, ctx["brands"]["BrandC"]["id"])
    assert (bra["final_index"], brb["final_index"], brc["final_index"]) == (900, 850, 795), (
        f"got {bra['final_index']}/{brb['final_index']}/{brc['final_index']}"
    )
    # Gap 50 <= CD(4,4)=83.156 keeps B in group 1; gap 105 > CD(4,8)=72.016 opens group 2.
    assert (bra["significance_group"], brb["significance_group"], brc["significance_group"]) == (1, 1, 2)
    assert (bra["rank_position"], brb["rank_position"], brc["rank_position"]) == (1, 2, 3)

    result = determine_awards(sid)
    assert result["award_count"] == 1, (
        f"B shares group 1 yet rank 2 excludes it, got {result['award_count']}"
    )
    assert list_awards_for(sid)[0]["brand_id"] == ctx["brands"]["BrandA"]["id"]


def test_compute_without_accepted_responses_returns_409(api, awards_officer_headers):
    """PRD §3.4: "Compute requires at least one `ACCEPTED` response anywhere in the
    study and otherwise fails with `ERR_NO_RESPONSES`."
    PRD §3.3: "recording `provisional_accepted_n` as the count of `ACCEPTED`
    responses the brand had at the moment of close *before* the sweep ran,
    `provisional_index` as the index score computed over that pre-sweep accepted
    set (null when the pre-sweep accepted set is empty), and `accepted_n` as the
    post-sweep accepted count."

    Design: Corner/errors/compute_without_accepted_responses_returns_409
    """
    ctx = setup_fielding_study(min_sample=1, brands=[{"name": "BrandA", "responses": []}])
    sid = ctx["study"]["id"]
    close_fielding(sid)
    study_goto(sid, "SCORING")
    resp = api.compute_scoring(sid, awards_officer_headers)
    validate_error(resp, ApiErrorId.ERR_NO_RESPONSES)
    assert get_study(sid)["status"] == "SCORING"
    br = get_brand_result_for(sid, ctx["brands"]["BrandA"]["id"])
    assert br["provisional_accepted_n"] == 0
    assert br["provisional_index"] is None
    assert br["status"] == "PROVISIONAL"
