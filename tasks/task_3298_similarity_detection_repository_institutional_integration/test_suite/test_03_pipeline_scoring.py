"""Processing pipeline and similarity scoring (PRD §3.6, §2.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_source,
    create_sources,
    get_assignment_version,
    get_report,
    inject_fragment,
    make_instructor_headers,
    process,
    setup_basic_scenario,
    setup_processed_submission,
    submit,
    validate_error,
    validate_paginated,
    validate_success,
    words,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INST_ADMIN = TEST_USERS["institutional_admin_headers"]


def _setup_scored_submission(api, word_count, fragments, assignment_overrides=None):
    """Scenario + one submission with fragments injected, then processed.

    fragments: list of (matched_word_count, match_category, offset_start).
    Returns (inst, instr, asg, sub, report).
    """
    inst, integ, instr, student, asg = setup_basic_scenario(
        "US", assignment_overrides=assignment_overrides
    )
    sub = submit(asg["id"], student["id"], words(word_count))
    sources = create_sources(inst["id"], max(1, len(fragments)), region="US")
    for i, (wc, cat, off) in enumerate(fragments):
        inject_fragment(sub["id"], sources[i % len(sources)]["id"], wc, cat, off)
    process(sub["id"], instr["id"])
    report = get_report(sub["id"], instr["id"])
    return inst, instr, asg, sub, report


def test_similarity_report_raw_vs_filtered_diverge(api):
    """PRD §3.6: "The **filtered** variant first removes fragments per the
    assignment's exclusion settings — `DIRECT_QUOTE` fragments when
    `exclude_quotes` is on, `BIBLIOGRAPHY_ENTRY` fragments when
    `exclude_bibliography` is on, and fragments whose `matched_word_count` falls
    strictly below `small_match_threshold_words` when `exclude_small_matches` is
    on (a fragment exactly at the threshold is kept) — then runs the identical
    aggregation, and is stored as `filtered_score_bps`."

    Design: Difficulty/dual_variant_calc/similarity_report_raw_vs_filtered_diverge
    """
    inst, instr, asg, sub, report = _setup_scored_submission(
        api,
        1000,
        [
            (120, "DIRECT_QUOTE", 0),
            (100, "PARAPHRASE", 200),
            (80, "BIBLIOGRAPHY_ENTRY", 400),
            (30, "BOILERPLATE", 600),
        ],
        assignment_overrides={
            "exclude_quotes": True,
            "exclude_bibliography": True,
            "exclude_small_matches": True,
            "small_match_threshold_words": 8,
        },
    )
    assert sub["word_count"] == 1000
    # raw: 120*1.0 + round_half_up(100*0.8) + 80*1.0 + round_half_up(30*0.5)
    #    = 120 + 80 + 80 + 15 = 295 -> 10000*295/1000 = 2950
    assert report["raw_score_bps"] == 2950
    assert report["filtered_score_bps"] == 950
    assert report["raw_score_bps"] != report["filtered_score_bps"]
    assert report["exclusion_snapshot"] == {
        "exclude_quotes": True,
        "exclude_bibliography": True,
        "exclude_small_matches": True,
        "small_match_threshold_words": 8,
    }
    assert report["report_state"] == "DRAFT"


def test_similarity_report_exclusion_snapshot_frozen_at_generation(api):
    """PRD §3.6: "the report freezes a copy of the four settings —
    `exclude_quotes`, `exclude_bibliography`, `exclude_small_matches`, and
    `small_match_threshold_words` — into its `exclusion_snapshot` at generation
    time, and a later regeneration refreshes that snapshot from the assignment's
    current values."

    Design: Difficulty/dual_variant_calc/similarity_report_raw_vs_filtered_diverge
    """
    inst, integ, instr, student, asg = setup_basic_scenario(
        "US", assignment_overrides={"exclude_quotes": True}
    )
    sub = submit(asg["id"], student["id"], words(1000))
    src = create_source(inst["id"], uri="https://src.example/snap1")
    inject_fragment(sub["id"], src["id"], 120, "DIRECT_QUOTE", 0)
    process(sub["id"], instr["id"])
    report = get_report(sub["id"], instr["id"])
    assert report["exclusion_snapshot"]["exclude_quotes"] is True
    assert report["exclusion_snapshot"]["exclude_bibliography"] is False
    # raw counts the quote; filtered drops it.
    assert report["raw_score_bps"] == 1200
    assert report["filtered_score_bps"] == 0

    # Flip the setting; the report goes STALE; regeneration refreshes the snapshot.
    asg_v = get_assignment_version(asg["id"], instr["id"])
    validate_success(
        api.patch_assignment(
            asg["id"],
            {"expected_assignment_version": asg_v, "exclude_quotes": False},
            make_instructor_headers(instr["id"]),
        )
    )
    process(sub["id"], instr["id"])
    report2 = get_report(sub["id"], instr["id"])
    assert report2["report_state"] == "DRAFT"
    assert report2["exclusion_snapshot"]["exclude_quotes"] is False
    assert report2["filtered_score_bps"] == 1200


def test_filtered_score_nonlinear_interaction_overlap_dedup(api):
    """PRD §3.6: "Step one, deduplication: fragments whose word intervals —
    each interval starting at `offset_start` and extending `matched_word_count`
    words — overlap transitively are clustered together, and within each cluster
    only the fragment with the largest `weighted_words` survives"

    Design: Difficulty/combinatorial_formula/filtered_score_nonlinear_interaction
    """
    inst, instr, asg, sub, report = _setup_scored_submission(
        api,
        1000,
        [
            (100, "DIRECT_QUOTE", 0),   # interval [0,100), weighted 100
            (60, "PARAPHRASE", 50),     # interval [50,110) overlaps; weighted 48
        ],
    )
    # Overlap dedup keeps only the larger weighted fragment (100 beats 48).
    assert report["raw_score_bps"] == 1000
    # All exclusions OFF: the filtered variant runs the identical aggregation.
    assert report["filtered_score_bps"] == 1000


def test_filtered_score_nonlinear_interaction_branch_flips_result(api):
    """PRD §3.6: "`DIRECT_QUOTE` fragments when `exclude_quotes` is on ... then
    runs the identical aggregation, and is stored as `filtered_score_bps`."

    Design: Difficulty/combinatorial_formula/filtered_score_nonlinear_interaction
    """
    # Same overlapping fragments, but exclude_quotes on: the DIRECT_QUOTE 100w
    # fragment is filtered out, leaving PARAPHRASE weighted 48 -> 480 bps.
    inst, instr, asg, sub, report = _setup_scored_submission(
        api,
        1000,
        [
            (100, "DIRECT_QUOTE", 0),
            (60, "PARAPHRASE", 50),
        ],
        assignment_overrides={"exclude_quotes": True},
    )
    assert report["raw_score_bps"] == 1000
    assert report["filtered_score_bps"] == 480


def test_per_fragment_rounding_order_matters(api):
    """PRD §2.7: "Summing raw matched-word counts first and rounding once at the
    end is a different, forbidden computation — three one-word `PARAPHRASE`
    fragments contribute 3 weighted words under per-fragment rounding (each
    rounds to 1), versus 2 under sum-then-round."

    Design: Difficulty/combinatorial_formula/per_fragment_rounding_order_matters
    """
    inst, integ, instr, student, asg = setup_basic_scenario("US")
    sub = submit(asg["id"], student["id"], words(100))
    src = create_source(inst["id"], source_type="PUBLICATION", uri="https://src.example/r1")
    for off in (0, 10, 20):
        inject_fragment(sub["id"], src["id"], 1, "PARAPHRASE", off)
    process(sub["id"], instr["id"])

    data, meta = validate_paginated(api.list_match_fragments_of_submission(sub["id"], INST_ADMIN))
    assert len(data) == 3
    for frag in data:
        assert frag["weighted_words"] == 1, "round_half_up(1 * 0.8) == 1 per fragment at injection"

    report = get_report(sub["id"], instr["id"])
    assert report["raw_score_bps"] == 300, (
        "10000 * (1+1+1)/100 == 300 under per-fragment rounding; "
        "the sum-then-round order would produce 200 and is forbidden"
    )


def test_score_clamps_at_10000_bps(api):
    """PRD §3.6: "the score is ten thousand times the ratio of the matched total
    to the submission's `word_count`, capped so the ratio never exceeds one, and
    rounded half up to an integer in the 0-to-10000 range."

    Design: Corner/calculations/score_clamps_at_10000_bps
    """
    inst, integ, instr, student, asg = setup_basic_scenario("US")
    sub = submit(asg["id"], student["id"], words(10))
    src = create_source(inst["id"], uri="https://src.example/cl")
    inject_fragment(sub["id"], src["id"], 50, "DIRECT_QUOTE", 0)
    process(sub["id"], instr["id"])
    report = get_report(sub["id"], instr["id"])
    assert sub["word_count"] == 10
    assert report["raw_score_bps"] == 10000, "matched 50 > word_count 10 must clamp to 10000, not 50000"


def test_small_match_threshold_boundary_kept_vs_dropped(api):
    """PRD §3.6: "fragments whose `matched_word_count` falls strictly below
    `small_match_threshold_words` when `exclude_small_matches` is on (a fragment
    exactly at the threshold is kept)"

    Design: Difficulty/boundary_precision_check/small_match_threshold_boundary_kept_vs_dropped
    """
    inst, instr, asg, sub, report = _setup_scored_submission(
        api,
        100,
        [
            (8, "BOILERPLATE", 0),   # exactly at threshold -> KEPT
            (7, "BOILERPLATE", 50),  # strictly below threshold -> DROPPED
        ],
        assignment_overrides={"exclude_small_matches": True, "small_match_threshold_words": 8},
    )
    # raw: round_half_up(8*0.5) + round_half_up(7*0.5) = 4 + 4 = 8 -> 800
    assert report["raw_score_bps"] == 800
    # filtered: only the 8-word fragment survives -> 4 -> 400
    assert report["filtered_score_bps"] == 400


def test_excluded_fragments_never_reenter_scores(api):
    """PRD §3.6: "fragments marked `excluded` never participate." PRD §3.6:
    "A re-run from `REPORT_READY` (for instance after the report went `STALE`)
    regenerates everything: the report returns to `DRAFT` with a refreshed
    `exclusion_snapshot` and recomputed scores"

    Design: Corner/calculations/excluded_fragments_never_reenter_scores
    """
    inst, integ, instr, student, asg = setup_basic_scenario("US")
    sub = submit(asg["id"], student["id"], words(100))
    src1 = create_source(inst["id"], source_type="INTERNET", uri="https://src.example/f1")
    src2 = create_source(inst["id"], source_type="PUBLICATION", uri="https://src.example/f2")
    inject_fragment(sub["id"], src1["id"], 10, "DIRECT_QUOTE", 0)
    inject_fragment(sub["id"], src2["id"], 25, "PARAPHRASE", 50)
    process(sub["id"], instr["id"])
    # 10 + round_half_up(25*0.8)=20 -> 30 -> 3000 bps before retract
    assert get_report(sub["id"], instr["id"])["raw_score_bps"] == 3000

    resp = api.retract_source(src1["id"], INST_ADMIN)
    validate_success(resp)

    process(sub["id"], instr["id"])
    report = get_report(sub["id"], instr["id"])
    # After retract + regen the excluded fragment contributes 0: 20 -> 2000 bps
    assert report["raw_score_bps"] == 2000
    assert report["report_state"] == "DRAFT", "STALE must be cleared by regeneration"


def test_submission_pipeline_cycle_reprocess(api):
    """PRD §3.6: "The submission must be in `RECEIVED`, `FAILED`, or
    `REPORT_READY`; invoking the pipeline against a `SUPERSEDED` submission is
    rejected" PRD §3.6: "Reports and assessments are one-to-one with their
    submission: reading a submission's similarity report or AI assessment
    returns an array of at most one element"

    Design: Difficulty/non_linear_state_machine/submission_pipeline_cycle_reprocess
    """
    inst, integ, instr, student, asg = setup_basic_scenario("US")
    sub = submit(asg["id"], student["id"], "alpha beta gamma")
    first = process(sub["id"], instr["id"])
    assert first["pipeline_state"] == "REPORT_READY"
    assert first["word_count"] == 3

    # Cycle edge: REPORT_READY -> PROCESSING -> REPORT_READY must succeed.
    second = process(sub["id"], instr["id"])
    assert second["pipeline_state"] == "REPORT_READY"

    data, meta = validate_paginated(
        api.list_similarity_reports(sub["id"], make_instructor_headers(instr["id"]))
    )
    assert len(data) == 1, "regeneration upserts; no duplicate report rows"


def test_process_superseded_submission_rejected(api):
    """PRD §3.6: "The submission must be in `RECEIVED`, `FAILED`, or
    `REPORT_READY`; invoking the pipeline against a `SUPERSEDED` submission is
    rejected with `ERR_INVALID_SUBMISSION_STATE` (HTTP 409)."

    Design: Corner/state_machines/process_superseded_submission_rejected
    """
    inst, integ, instr, student, asg = setup_basic_scenario("US")
    sub1 = submit(asg["id"], student["id"], "first version")
    process(sub1["id"], instr["id"])
    submit(asg["id"], student["id"], "second version", supersedes_submission_id=sub1["id"])

    resp = api.process_submission(sub1["id"], make_instructor_headers(instr["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_SUBMISSION_STATE, expected_status=409)
    fetched = validate_success(api.get_submission(sub1["id"], make_instructor_headers(instr["id"])))
    assert fetched["pipeline_state"] == "SUPERSEDED"


def test_weighted_words_computed_at_injection(api):
    """PRD §2.7: "Critically, weighting rounds per fragment before any
    summation: each fragment's `weighted_words` is the half-up-rounded integer
    of its `matched_word_count` times its category multiplier, computed at
    injection time"

    Design: Difficulty/combinatorial_formula/per_fragment_rounding_order_matters
    """
    inst, integ, instr, student, asg = setup_basic_scenario("US")
    sub = submit(asg["id"], student["id"], words(100))
    src = create_source(inst["id"], source_type="PUBLICATION", uri="https://src.example/r2")
    frag = validate_success(
        api.inject_match(
            {
                "submission_id": sub["id"],
                "source_document_id": src["id"],
                "matched_word_count": 1,
                "match_category": "PARAPHRASE",
                "offset_start": 0,
            },
            ADMIN,
        ),
        expected_status=201,
    )
    assert frag["weighted_words"] == 1, "round_half_up(1 * 0.8) == 1 computed at injection time"


def test_pipeline_retry_from_failed_and_rerun_from_report_ready(api):
    """PRD §3.6: "The submission must be in `RECEIVED`, `FAILED`, or
    `REPORT_READY`" PRD §3.6: "A retry from `FAILED` and a re-run from
    `REPORT_READY` both pass through `PROCESSING` the same way, each bumping
    `version` once more."

    Design: Difficulty/non_linear_state_machine/submission_pipeline_cycle_reprocess
    """
    inst, integ, instr, student, asg = setup_basic_scenario("US")
    sub = submit(asg["id"], student["id"], "alpha beta gamma")
    v0 = sub["version"]
    first = process(sub["id"], instr["id"])
    assert first["pipeline_state"] == "REPORT_READY"
    assert first["version"] == v0 + 1
    # Re-run from REPORT_READY passes through PROCESSING, bumping version again.
    second = process(sub["id"], instr["id"])
    assert second["pipeline_state"] == "REPORT_READY"
    assert second["version"] == v0 + 2


def test_small_match_threshold_boundary_all_dropped(api):
    """PRD §3.6: "fragments whose `matched_word_count` falls strictly below
    `small_match_threshold_words` when `exclude_small_matches` is on (a fragment
    exactly at the threshold is kept)"

    Design: Difficulty/boundary_precision_check/small_match_threshold_boundary_kept_vs_dropped
    """
    inst, instr, asg, sub, report = _setup_scored_submission(
        api,
        100,
        [(7, "BOILERPLATE", 0)],  # 7 < 8 -> DROPPED
        assignment_overrides={"exclude_small_matches": True, "small_match_threshold_words": 8},
    )
    # raw: round_half_up(7*0.5) = 4 -> 400
    assert report["raw_score_bps"] == 400
    # filtered: the only fragment is strictly below the threshold -> 0
    assert report["filtered_score_bps"] == 0

