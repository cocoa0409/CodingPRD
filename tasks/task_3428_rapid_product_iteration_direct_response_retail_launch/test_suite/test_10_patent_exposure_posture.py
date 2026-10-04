"""Patent cases: provisional vs final reserve, exposure banding, season
contagion (guard/freeze/recover), close preconditions, and the adverse
judgment cascade (PRD §2.9, §3.5, §3.8, §3.9).
"""
import pytest

from test_helpers import (
    ADMIN,
    LC_JANE,
    LC_JOHN,
    MEDIA,
    ApiErrorId,
    api_client,
    air_media_test_payload,
    assert_reserve_reconciliation,
    create_category,
    create_media_test,
    create_season,
    file_case,
    get_category,
    get_season,
    record_judgment,
    run_review,
    settle_case,
    setup_season_with_category,
    setup_severe_guarded_season,
    setup_substantiated_study,
    setup_tooled_variant,
    validate_error,
    validate_ok,
)


def test_exposure_elevated_band_from_single_med_case(api):
    """PRD §3.8: "The `exposure_level` bands from the index with inclusive
    lower bounds: an index of 20 or more is `SEVERE`, an index of 8 or more
    (but under 20) is `ELEVATED`, and anything lower is `CLEAR`."

    Design: Corner/calculations/exposure_elevated_band_from_single_med_case
    """
    base = setup_season_with_category()
    file_case(base["category"]["id"], "PT-7001", 400_000, "MED",
              filer_headers=LC_JANE)
    category = get_category(base["category"]["id"])
    assert category["exposure_index"] == 11  # crowding_base 6 + MED weight 5
    assert category["exposure_level"] == "ELEVATED"
    assert get_season(base["season"]["id"])["posture"] == "SEASON_OPEN"


def test_case_filed_activates_at_first_review(api):
    """PRD §3.9: "Step 1 activates pending litigation: every PatentCase in
    `FILED` status in a category linked to the season becomes `ACTIVE`."

    Design: Corner/state_machines/case_filed_activates_at_first_review
    """
    base = setup_season_with_category()
    case = file_case(base["category"]["id"], "PT-5001", 1_000_000, "MED",
                     filer_headers=LC_JANE)
    assert case["status"] == "FILED"
    run_review(base["season"]["id"])
    cases = validate_ok(
        api_client.list_category_patent_cases(base["category"]["id"], LC_JANE)
    )
    assert cases[0]["status"] == "ACTIVE"


def test_litigation_reserve_provisional_then_final_on_settle(api):
    """PRD §3.8: "a provisional reserve is booked at once:
    `provisional_reserve_cents` is the claim amount multiplied by the 0.30
    prior-adverse probability, rounded half-up to whole cents" and "Settlement
    records the supplied `settlement_cents` as `final_amount_cents`, moves the
    case to `SETTLED`, and recomputes both derived ledgers: the provisional
    reserve is replaced by the settlement amount inside
    `active_reserve_cents`".

    Design: Difficulty/dual_variant_calc/litigation_reserve_provisional_vs_final
    """
    base = setup_season_with_category()
    case = file_case(base["category"]["id"], "PT-1001", 1_000_000, "MED",
                     filer_headers=LC_JANE)
    assert case["provisional_reserve_cents"] == 300000
    assert case["final_amount_cents"] is None
    assert get_category(base["category"]["id"])["active_reserve_cents"] == 300000
    settled = settle_case(case["id"], 450_000, settler_headers=LC_JOHN)
    assert settled["status"] == "SETTLED"
    assert settled["final_amount_cents"] == 450000
    assert get_category(base["category"]["id"])["active_reserve_cents"] == 450000


def test_litigation_reserve_variants_diverge_and_ledger_reconciles(api):
    """PRD §2.9: "the category's `active_reserve_cents` equals the sum of
    `provisional_reserve_cents` over its PatentCases in `FILED` or `ACTIVE`
    status, plus the sum of `final_amount_cents` over its PatentCases in
    `SETTLED` or `JUDGED_ADVERSE` status; a case judged favorable contributes
    zero."

    Design: Difficulty/dual_variant_calc/litigation_reserve_provisional_vs_final
    """
    base = setup_season_with_category()
    case = file_case(base["category"]["id"], "PT-1001", 1_000_000, "MED",
                     filer_headers=LC_JANE)
    reserve_before = get_category(base["category"]["id"])["active_reserve_cents"]
    settled = settle_case(case["id"], 450_000, settler_headers=LC_JOHN)
    reserve_after = get_category(base["category"]["id"])["active_reserve_cents"]
    assert case["provisional_reserve_cents"] != settled["final_amount_cents"]
    assert reserve_before == 300000
    assert reserve_after == 450000
    assert reserve_after - reserve_before == 150000
    assert_reserve_reconciliation(
        get_category(base["category"]["id"]), [settled]
    )


def test_case_accrue_then_favorable_judgment_conserves_reserve_ledger(api):
    """PRD §3.8: "A favorable judgment records `final_amount_cents` 0, moves
    the case to `JUDGED_FAVORABLE`, releases the reserve for that case
    entirely, and removes it from the index." PRD §2.9: "The accrue-and-release
    pairs — filing a case and later settling it, or filing a case and later
    recording a favorable judgment — must return the ledger to its prior value
    exactly."

    Design: Difficulty/compensating_invariant/case_accrue_then_favorable_judgment_conserves_reserve_ledger
    """
    base = setup_season_with_category()
    reserve_base = get_category(base["category"]["id"])["active_reserve_cents"]
    assert reserve_base == 0
    case = file_case(base["category"]["id"], "PT-4001", 1_000_000, "MED",
                     filer_headers=LC_JANE)
    assert get_category(base["category"]["id"])["active_reserve_cents"] == 300000
    run_review(base["season"]["id"])  # FILED -> ACTIVE
    judged = record_judgment(case["id"], "FAVORABLE")
    assert judged["status"] == "JUDGED_FAVORABLE"
    assert judged["final_amount_cents"] == 0
    category = get_category(base["category"]["id"])
    assert category["active_reserve_cents"] == reserve_base
    assert category["exposure_index"] == 6
    assert category["exposure_level"] == "CLEAR"


def test_favorable_judgment_never_disturbs_open_posture(api):
    """PRD §3.8: "The contagion rule fires whenever such a recomputation lands
    on `SEVERE` while the linked season is `SEASON_OPEN`: the season flips to
    `SEASON_GUARDED` and records the current `review_index` in
    `guarded_since_review_index`." An ELEVATED-then-CLEAR path never lands on
    SEVERE, so the season stays OPEN throughout.

    Design: Difficulty/compensating_invariant/case_accrue_then_favorable_judgment_conserves_reserve_ledger
    """
    base = setup_season_with_category()
    case = file_case(base["category"]["id"], "PT-4001", 1_000_000, "MED",
                     filer_headers=LC_JANE)
    assert get_season(base["season"]["id"])["posture"] == "SEASON_OPEN"
    run_review(base["season"]["id"])
    judged = record_judgment(case["id"], "FAVORABLE")
    assert_reserve_reconciliation(get_category(base["category"]["id"]), [judged])
    season = get_season(base["season"]["id"])
    assert season["posture"] == "SEASON_OPEN"
    assert season["guarded_since_review_index"] is None


def test_adverse_judgment_cascades_case_to_category_to_season_posture(api):
    """PRD §3.8: "it records the award as `final_amount_cents`, moves the case
    to `JUDGED_ADVERSE`, recomputes the reserve, and recomputes the exposure
    index with the tripled adverse weight — which may itself push the category
    to `SEVERE` and thereby guard the season."

    exposure: 6 + 3 x 9 = 33 (SEVERE); the season guards at review_index 1.

    Design: Difficulty/transitive_cascade/adverse_judgment_cascades_case_to_category_to_season_posture
    """
    base = setup_season_with_category()
    bundle = setup_tooled_variant(base["category"]["id"])
    setup_substantiated_study(bundle["variant"]["id"])
    create_media_test(bundle["variant"]["id"], "Infomercial A", 1000)
    case = file_case(base["category"]["id"], "PT-2001", 2_000_000, "HIGH",
                     filer_headers=LC_JANE)
    season = run_review(base["season"]["id"])  # activates the case; index 1
    category = get_category(base["category"]["id"])
    assert category["exposure_index"] == 15  # 6 + HIGH 9 while ACTIVE
    assert category["exposure_level"] == "ELEVATED"
    judged = record_judgment(case["id"], "ADVERSE", 800_000)
    assert judged["status"] == "JUDGED_ADVERSE"
    assert judged["final_amount_cents"] == 800000
    category = get_category(base["category"]["id"])
    assert category["exposure_index"] == 33  # 6 + 9 * ADVERSE_WEIGHT_MULTIPLIER 3
    assert category["exposure_level"] == "SEVERE"
    assert category["active_reserve_cents"] == 800000
    season = get_season(base["season"]["id"])
    assert season["posture"] == "SEASON_GUARDED"
    assert season["guarded_since_review_index"] == 1


def test_adverse_judgment_cascade_blocks_media_air_with_guarded(api):
    """PRD §3.5: "the owning season must not be `SEASON_GUARDED`, else
    `ERR_SEASON_GUARDED` — the single operation a guarded season throttles."

    Design: Difficulty/transitive_cascade/adverse_judgment_cascades_case_to_category_to_season_posture
    """
    base = setup_season_with_category()
    bundle = setup_tooled_variant(base["category"]["id"])
    setup_substantiated_study(bundle["variant"]["id"])
    media = create_media_test(bundle["variant"]["id"], "Infomercial A", 1000)
    case = file_case(base["category"]["id"], "PT-2001", 2_000_000, "HIGH",
                     filer_headers=LC_JANE)
    run_review(base["season"]["id"])
    record_judgment(case["id"], "ADVERSE", 800_000)
    assert get_season(base["season"]["id"])["posture"] == "SEASON_GUARDED"
    resp = api_client.air_media_test(media["id"], air_media_test_payload(2000), MEDIA)
    validate_error(resp, ApiErrorId.ERR_SEASON_GUARDED)


def test_guarded_season_recovers_to_open_after_cases_settle(api):
    """PRD §3.9: "Step 11 reconciles exposure and posture: every linked
    category's `exposure_index` and `exposure_level` recompute per §3.8; if
    the season is `SEASON_GUARDED` and no linked category is `SEVERE`, the
    season relaxes to `SEASON_OPEN` and `guarded_since_review_index` clears to
    null".

    Design: Corner/state_machines/guarded_season_recovers_to_open_after_cases_settle
    """
    bundle = setup_severe_guarded_season()
    assert bundle["season"]["posture"] == "SEASON_GUARDED"
    settle_case(bundle["case_high"]["id"], 100_000, settler_headers=LC_JOHN)
    settle_case(bundle["case_med"]["id"], 50_000, settler_headers=LC_JOHN)
    category = get_category(bundle["category"]["id"])
    assert category["exposure_index"] == 6
    assert category["exposure_level"] == "CLEAR"
    # Settlement alone does not relax the posture; recovery is checkpointed.
    assert get_season(bundle["season"]["id"])["posture"] == "SEASON_GUARDED"
    season = run_review(bundle["season"]["id"])
    assert season["posture"] == "SEASON_OPEN"
    assert season["guarded_since_review_index"] is None


def test_guarded_season_freezes_after_grace_reviews(api):
    """PRD §3.9: "if the season is `SEASON_GUARDED`, at least one linked
    category is still `SEVERE`, and the difference between the current
    `review_index` and `guarded_since_review_index` is 2 or more at the moment
    the review runs, the season freezes to `SEASON_FROZEN`, recording
    `frozen_at_review_index`."

    Design: Corner/state_machines/guarded_season_freezes_after_grace_reviews
    """
    bundle = setup_severe_guarded_season()  # GUARDED since review_index 0
    season = run_review(bundle["season"]["id"])
    assert season["review_index"] == 1
    assert season["posture"] == "SEASON_GUARDED"  # delta 1 < 2
    season = run_review(bundle["season"]["id"])
    assert season["review_index"] == 2
    assert season["posture"] == "SEASON_FROZEN"  # delta 2 >= 2, still SEVERE
    assert season["frozen_at_review_index"] == 2
    resp = api_client.unfreeze_season(bundle["season"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_close_blocked_until_pipeline_drains(api):
    """PRD §3.9: "only when three aggregate conditions all hold: no
    ModelVariant whose concept chain resolves to this season is in `DRAFT`,
    `TOOLED`, `DR_TESTING`, `RETAIL_LIVE`, or `REFRESH_CANDIDATE`; no
    LaunchCommitment or ReplenishmentOrder on such variants is `OPEN`; and no
    PatentCase in a linked category is `FILED` or `ACTIVE`. Any violation is
    rejected with `ERR_CLOSE_PRECONDITIONS_UNMET`."

    Design: Corner/state_machines/close_blocked_until_pipeline_drains
    """
    base = setup_season_with_category()  # season FW26 stays empty
    season2 = create_season("SS27")
    category2 = create_category(season2["id"], "Air Fryers", 2)
    file_case(category2["id"], "PT-6001", 100_000, "LOW", filer_headers=LC_JANE)
    resp = api_client.close_season(season2["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_CLOSE_PRECONDITIONS_UNMET)
    closed = validate_ok(api_client.close_season(base["season"]["id"], ADMIN))
    assert closed["posture"] == "SEASON_CLOSED"
