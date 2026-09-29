"""Difficulty tests: dual-variant calculations, combinatorial formulas and the
non-linear case state machine.

Every test in this module translates exactly one instance of
`SCAFFOLD_DIFFICULTY_DESIGN.yaml` (rules `dual_variant_calc`,
`combinatorial_formula` and `non_linear_state_machine`) and carries the
instance's `Design:` tag as the last line of its docstring.

The harness restarts the API server before every individual test, so the store
is empty and the logical clock reads `2026-08-01T00:00:00Z` on entry; each test
rebuilds its whole precondition chain through the PRD's public endpoints.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions, constants, factories, fixtures
from test_helpers.api_errors import ApiErrorId


def test_formal_and_informal_ladder_bands_are_disjoint(api, officer):
    """One case, two ladder variants, two non-overlapping permitted bands.

    A legacy prior in another course gives 4 cross-course points and one prior,
    so the formal variant reaches 56.00 for rank 5 with band [4, 6] while the
    informal variant, which may read neither input, stays at 44.00 for rank 3
    with band [1, 3].

    PRD §3.4: "Add 4 cross-course points and the formal index becomes 56.00 for
    a recommended rank of 5 and a band from 4 to 6, against an unchanged
    informal band from 1 to 3: the two bands are disjoint, so no single
    proposed rank is legal under both."

    Design: Difficulty/dual_variant_calc/ladder_placement_formal_and_informal_variants_yield_disjoint_bands
    """
    world = fixtures.seed_actors(client=api)
    fixtures.seed_legacy_prior_case(
        world,
        decided_at="2025-04-01T00:00:00Z",
        completed_at="2025-05-01T00:00:00Z",
        imposed_ladder_rank=3,
        course_code="HIST-110",
        client=api,
    )
    fixtures.seed_draft_report(world, client=api)
    fixtures.seed_submitted_report(world, client=api)
    fixtures.seed_accepted_report(world, client=api)
    fixtures.seed_case(world, client=api)

    formal = validate_success(
        api.get_severity_assessment(
            world["case"]["id"], officer, params={"pathway_basis": "FORMAL"}
        )
    )
    assert formal["pathway_basis"] == "FORMAL"
    assertions.assert_pct_equals(
        formal["evidence_strength_score"], 60.00, "formal evidence_strength_score"
    )
    assert formal["base_points"] == 20
    assertions.assert_pct_equals(
        formal["evidence_contribution"], 24.00, "evidence_contribution"
    )
    assert formal["distinct_other_course_codes"] == 1
    assert formal["cross_course_pattern_points"] == 4
    assert formal["prior_upheld_count_at_assessment"] == 1
    assertions.assert_pct_equals(
        formal["provisional_severity_index"], 48.00, "provisional_severity_index"
    )
    assert formal["prior_escalation_points"] == 8
    assertions.assert_pct_equals(formal["severity_index"], 56.00, "severity_index")
    assert formal["tier_rank"] == 5
    assert formal["recommended_ladder_rank"] == 5
    assert formal["recommended_kind"] == "DISCIPLINARY_PROBATION"
    assert formal["permitted_band_min"] == 4
    assert formal["permitted_band_max"] == 6
    assert formal["required_panel_size"] == 3
    assert formal["informal_pathway_permitted"] is False

    informal = validate_success(
        api.get_severity_assessment(
            world["case"]["id"], officer, params={"pathway_basis": "INFORMAL"}
        )
    )
    assert informal["pathway_basis"] == "INFORMAL"
    assertions.assert_pct_equals(
        informal["severity_index"], 44.00, "informal severity_index"
    )
    assert informal["cross_course_pattern_points"] == 0
    assert informal["prior_escalation_points"] == 0
    assert informal["recommended_ladder_rank"] == 3
    assert informal["recommended_kind"] == "GRADE_PENALTY_COURSE"
    assert informal["permitted_band_min"] == 1
    assert informal["permitted_band_max"] == 3

    assert formal["permitted_band_min"] > informal["permitted_band_max"], (
        "the office band [4, 6] and the informal band [1, 3] must be disjoint"
    )


def test_case_row_carries_both_variant_ranks_and_bars_the_informal_pathway(
    api, officer
):
    """The case row stores both variants' answers side by side.

    The same intake writes rank 5 under the formal algorithm and rank 3 under
    the informal one, and because the formal rank exceeds 3 the office may not
    route the case down the informal pathway at all.

    PRD §3.4: "`informal_recommended_ladder_rank` is the tier rank of that
    informal index, capped at 3."
    PRD §3.4: "Choosing `INFORMAL` for a case whose `recommended_ladder_rank`
    exceeds 3 is rejected with `ERR_INFORMAL_PATHWAY_NOT_PERMITTED`."

    Design: Difficulty/dual_variant_calc/ladder_placement_formal_and_informal_variants_yield_disjoint_bands
    """
    world = fixtures.seed_actors(client=api)
    fixtures.seed_legacy_prior_case(
        world,
        decided_at="2025-04-01T00:00:00Z",
        completed_at="2025-05-01T00:00:00Z",
        imposed_ladder_rank=3,
        course_code="HIST-110",
        client=api,
    )
    fixtures.seed_draft_report(world, client=api)
    fixtures.seed_submitted_report(world, client=api)
    fixtures.seed_accepted_report(world, client=api)
    fixtures.seed_case(world, client=api)

    case = validate_success(api.get_case(world["case"]["id"], officer))
    assertions.assert_pct_equals(
        case["evidence_strength_score"], 60.00, "case evidence_strength_score"
    )
    assert case["cross_course_pattern_points"] == 4
    assert case["prior_upheld_count_at_assessment"] == 1
    assertions.assert_pct_equals(
        case["provisional_severity_index"], 48.00, "provisional_severity_index"
    )
    assert case["prior_escalation_points"] == 8
    assertions.assert_pct_equals(case["severity_index"], 56.00, "severity_index")
    assert case["recommended_ladder_rank"] == 5
    assertions.assert_pct_equals(
        case["informal_severity_index"], 44.00, "informal_severity_index"
    )
    assert case["informal_recommended_ladder_rank"] == 3
    assert case["pathway"] == "UNASSIGNED"

    validate_error(
        api.set_case_pathway(
            case["id"], factories.pathway_payload("INFORMAL"), officer
        ),
        ApiErrorId.ERR_INFORMAL_PATHWAY_NOT_PERMITTED,
        409,
    )
    unchanged = validate_success(api.get_case(case["id"], officer))
    assert unchanged["pathway"] == "UNASSIGNED"
    assert unchanged["version"] == case["version"]


def test_reporting_rate_diverges_between_the_submitted_and_adjudicated_bases(
    api, officer
):
    """The two reporting bases count different entities over the same window.

    ENGL has 2000 enrolled students, three submitted reports inside the
    365-day window and exactly one upheld case decided inside it, so the
    submitted basis reports 1.50 per 1000 and the adjudicated basis 0.50 — a
    delta of exactly 1.00 over identical stored data.

    PRD §3.1: "A department of 2000 enrolled students with three submitted
    reports of which one reached an upheld finding therefore reports 1.50 on
    the submitted basis and 0.50 on the adjudicated basis"

    Design: Difficulty/dual_variant_calc/department_reporting_rate_submitted_basis_versus_adjudicated_basis
    """
    world = fixtures.seed_actors(client=api)
    for digest in (constants.SHA256_A, constants.SHA256_B, constants.SHA256_C):
        report = fixtures.create_report(
            world["offering"]["id"], world["student"]["id"], world["reporter_h"], api
        )
        fixtures.attach_similarity_evidence(
            report["id"], world["reporter_h"], api, sha256=digest
        )
        fixtures.submit_report(report["id"], world["reporter_h"], api)
    # One upheld finding for the same department, decided inside the window.
    fixtures.seed_legacy_prior_case(
        world,
        decided_at="2026-06-01T00:00:00Z",
        completed_at="2026-06-20T00:00:00Z",
        imposed_ladder_rank=3,
        course_code="ENGL-105",
        client=api,
    )

    submitted = validate_success(
        api.get_department_reporting_metrics(
            world["dept"]["id"],
            officer,
            params={"basis": "SUBMITTED", "as_of": "2026-08-01T00:00:00Z"},
        )
    )
    assert submitted["basis"] == "SUBMITTED"
    assert submitted["window_days"] == 365
    assert submitted["enrolled_student_count"] == 2000
    assert submitted["numerator"] == 3
    assertions.assert_pct_equals(
        submitted["reporting_rate_per_1k"], 1.50, "submitted reporting_rate_per_1k"
    )

    adjudicated = validate_success(
        api.get_department_reporting_metrics(
            world["dept"]["id"],
            officer,
            params={"basis": "ADJUDICATED", "as_of": "2026-08-01T00:00:00Z"},
        )
    )
    assert adjudicated["basis"] == "ADJUDICATED"
    assert adjudicated["window_days"] == 365
    assert adjudicated["enrolled_student_count"] == 2000
    assert adjudicated["numerator"] == 1
    assertions.assert_pct_equals(
        adjudicated["reporting_rate_per_1k"], 0.50, "adjudicated reporting_rate_per_1k"
    )

    delta = round(
        float(submitted["reporting_rate_per_1k"])
        - float(adjudicated["reporting_rate_per_1k"]),
        2,
    )
    assert delta == 1.00, f"expected a basis delta of exactly 1.00, got {delta}"


def test_adjudicated_basis_read_persists_nothing_on_the_department(api, officer):
    """Only the submitted basis writes back onto the department row.

    The persisted `reporting_rate_per_1k_submitted` always carries the
    submitted basis, so an adjudicated-basis read that returns 0.50 must leave
    the stored 1.50 exactly where it was.

    PRD §3.1: "with `basis` set to `ADJUDICATED` it persists nothing at all"

    Design: Difficulty/dual_variant_calc/department_reporting_rate_submitted_basis_versus_adjudicated_basis
    """
    world = fixtures.seed_actors(client=api)
    for digest in (constants.SHA256_A, constants.SHA256_B, constants.SHA256_C):
        report = fixtures.create_report(
            world["offering"]["id"], world["student"]["id"], world["reporter_h"], api
        )
        fixtures.attach_similarity_evidence(
            report["id"], world["reporter_h"], api, sha256=digest
        )
        fixtures.submit_report(report["id"], world["reporter_h"], api)
    fixtures.seed_legacy_prior_case(
        world,
        decided_at="2026-06-01T00:00:00Z",
        completed_at="2026-06-20T00:00:00Z",
        imposed_ladder_rank=3,
        course_code="ENGL-105",
        client=api,
    )

    # Submitting a report already recomputes and persists the submitted rate.
    before = validate_success(api.get_department(world["dept"]["id"], officer))
    assertions.assert_pct_equals(
        before["reporting_rate_per_1k_submitted"],
        1.50,
        "persisted reporting_rate_per_1k_submitted",
    )

    adjudicated = validate_success(
        api.get_department_reporting_metrics(
            world["dept"]["id"], officer, params={"basis": "ADJUDICATED"}
        )
    )
    assertions.assert_pct_equals(
        adjudicated["reporting_rate_per_1k"], 0.50, "adjudicated reporting_rate_per_1k"
    )

    after = validate_success(api.get_department(world["dept"]["id"], officer))
    assertions.assert_pct_equals(
        after["reporting_rate_per_1k_submitted"],
        1.50,
        "persisted rate after an adjudicated-basis read",
    )
    assert after["monitoring_flag"] == before["monitoring_flag"]

    # The submitted-basis read is the one with the write-back side effect.
    resubmitted_basis = validate_success(
        api.get_department_reporting_metrics(
            world["dept"]["id"], officer, params={"basis": "SUBMITTED"}
        )
    )
    assertions.assert_pct_equals(
        resubmitted_basis["reporting_rate_per_1k"],
        1.50,
        "submitted reporting_rate_per_1k",
    )
    final = validate_success(api.get_department(world["dept"]["id"], officer))
    assertions.assert_pct_equals(
        final["reporting_rate_per_1k_submitted"],
        1.50,
        "persisted rate after a submitted-basis read",
    )


def test_evidence_chain_reaches_81_50_after_a_one_page_proctor_log(api, officer):
    """The six-step evidence chain composes, it does not add band-scaled parts.

    A 45.00 / 4-page similarity report alone scores 60.00; adding a one-page
    proctor log re-runs the whole chain — the page total and the kind-diversity
    sum both change and the corroboration bonus switches on — for 81.50, not
    the 87.50 that band-scaling the diversity points would give.

    PRD §3.3: "Adding a one-page proctor log to the 45.00 case gives 48.00
    similarity points, 2.50 page points, 16.00 diversity points and a 15.00
    corroboration bonus, for 81.50"

    Design: Difficulty/combinatorial_formula/evidence_strength_score_seven_step_dependency_chain_mode_a
    """
    world = fixtures.seed_draft_report(client=api)

    before = validate_success(api.get_report(world["report"]["id"], officer))
    assertions.assert_pct_equals(
        before["evidence_strength_score"], 60.00, "SEED-A evidence_strength_score"
    )
    assert before["evidence_complete"] is True
    assert before["status"] == "DRAFT"

    item = validate_success(
        api.create_evidence_item(
            factories.proctor_log_payload(world["report"]["id"]), world["reporter_h"]
        ),
        201,
    )
    assertions.assert_absent(item, "updated_at", "version")

    after = validate_success(api.get_report(world["report"]["id"], officer))
    assertions.assert_pct_equals(
        after["evidence_strength_score"], 81.50, "SEED-B evidence_strength_score"
    )
    assert after["evidence_complete"] is True
    assert after["status"] == "DRAFT"
    moved = round(
        float(after["evidence_strength_score"])
        - float(before["evidence_strength_score"]),
        2,
    )
    assert moved == 21.50, f"expected the score to move by 21.50, got {moved}"


def test_band_multiplier_reads_the_allowance_adjusted_similarity(api, officer):
    """The band is chosen after the excluded-quote allowance, not before.

    At 44.99 the adjusted value is 39.99, which falls to the 1.00 band, so the
    single item scores 51.99 instead of 60.00 and the pair with a one-page
    proctor log scores 73.49 instead of 81.50.

    PRD §3.3: "The same item at 44.99 adjusts to 39.99, falls to the 1.00 band
    for 39.99 similarity points, and scores 51.99."
    PRD §3.3: "the same pair at 44.99 scores 73.49"

    Design: Difficulty/combinatorial_formula/evidence_strength_score_seven_step_dependency_chain_mode_a
    """
    world = fixtures.seed_actors(client=api)
    report = fixtures.create_report(
        world["offering"]["id"], world["student"]["id"], world["reporter_h"], api
    )
    fixtures.attach_similarity_evidence(
        report["id"], world["reporter_h"], api, similarity_pct=44.99
    )

    single = validate_success(api.get_report(report["id"], officer))
    assertions.assert_pct_equals(
        single["evidence_strength_score"], 51.99, "44.99 single-item score"
    )
    assert single["evidence_complete"] is True

    fixtures.attach_proctor_log(report["id"], world["reporter_h"], api)
    pair = validate_success(api.get_report(report["id"], officer))
    assertions.assert_pct_equals(
        pair["evidence_strength_score"], 73.49, "44.99 two-item score"
    )


def test_informal_grade_penalty_rounds_components_before_weighting(api, officer):
    """Zeroing the essay rounds each component first, then weights.

    The four-component gradebook gives a baseline of 79.06; re-running the same
    three steps with the essay forced to 0 gives 47.86 and a delta of 31.20.
    Weighting the unrounded percentages would give 47.87.

    PRD §3.8: "Zeroing the first component gives 0.0000 plus 29.1420 plus
    12.4440 plus 6.2780, which is 47.8640 and rounds to 47.86, for a delta of
    31.20."

    Design: Difficulty/combinatorial_formula/adjusted_course_grade_pct_round_components_first_mode_b
    """
    world = fixtures.seed_informal_case(client=api)
    fixtures.propose_informal_resolution(
        world,
        2,
        effective_from="2026-08-05T00:00:00Z",
        client=api,
        grade_component_code="ESSAY",
    )
    fixtures.respond_informal(world, "ACCEPT", client=api)

    accepted = validate_success(api.get_case(world["case"]["id"], officer))
    assert accepted["adjudication_status"] == "INFORMAL_ACCEPTED"
    assert accepted["responsibility_finding"] == "RESPONSIBLE"
    assert accepted["finding_basis"] == "ADMISSION"

    fixtures.impose_sanction(world, client=api)

    sanction = validate_success(api.get_sanction(world["sanction"]["id"], officer))
    assert sanction["status"] == "IMPOSED"
    assert sanction["origin"] == "INFORMAL_PROPOSAL"
    assert sanction["kind"] == "GRADE_PENALTY_ASSIGNMENT"
    assert sanction["ladder_rank"] == 2
    assert sanction["grade_component_code"] == "ESSAY"
    assertions.assert_pct_equals(
        sanction["baseline_course_grade_pct"], 79.06, "baseline_course_grade_pct"
    )
    assertions.assert_pct_equals(
        sanction["adjusted_course_grade_pct"], 47.86, "adjusted_course_grade_pct"
    )
    assertions.assert_pct_equals(
        sanction["grade_penalty_delta_pct"], 31.20, "grade_penalty_delta_pct"
    )

    case = validate_success(api.get_case(world["case"]["id"], officer))
    assert case["adjudication_status"] == "SANCTION_IMPOSED"
    assert case["notation_status"] == "NOT_APPLICABLE"
    assertions.assert_pct_equals(
        case["baseline_course_grade_pct"], 79.06, "case baseline_course_grade_pct"
    )

    student = validate_success(api.get_student(world["student"]["id"], officer))
    assert student["active_sanction_points"] == 2
    assert student["standing"] == "GOOD_STANDING"
    assert student["transcript_notation"] == "NONE"


def test_zeroing_the_midterm_component_yields_its_own_rounded_delta(api, officer):
    """The same gradebook, a different zeroed component, a different answer.

    Forcing the midterm to 0 leaves the other three rounded percentages
    untouched, so the adjusted grade is 49.92 and the delta 29.14 — the delta is
    the rounded difference, not a re-derivation from unrounded parts.

    PRD §3.8: "Zeroing the second component instead gives 31.2000 plus 0.0000
    plus 12.4440 plus 6.2780, which is 49.9220 and rounds to 49.92, for a delta
    of 29.14."

    Design: Difficulty/combinatorial_formula/adjusted_course_grade_pct_round_components_first_mode_b
    """
    world = fixtures.seed_informal_case(client=api)
    fixtures.propose_informal_resolution(
        world,
        2,
        effective_from="2026-08-05T00:00:00Z",
        client=api,
        grade_component_code="MIDTERM",
    )
    fixtures.respond_informal(world, "ACCEPT", client=api)
    fixtures.impose_sanction(world, client=api)

    sanction = validate_success(api.get_sanction(world["sanction"]["id"], officer))
    assert sanction["status"] == "IMPOSED"
    assert sanction["grade_component_code"] == "MIDTERM"
    assertions.assert_pct_equals(
        sanction["baseline_course_grade_pct"], 79.06, "baseline_course_grade_pct"
    )
    assertions.assert_pct_equals(
        sanction["adjusted_course_grade_pct"], 49.92, "adjusted_course_grade_pct"
    )
    assertions.assert_pct_equals(
        sanction["grade_penalty_delta_pct"], 29.14, "grade_penalty_delta_pct"
    )


def test_escalation_band_is_keyed_on_the_provisional_index_not_the_final_one(
    api, officer
):
    """A same-course prior escalates without inflating the band it selects.

    The prior sits in this case's own `course_code`, so the pattern detector
    contributes 0 and the provisional index is 44.00. One prior below the 50.00
    pivot takes 8 points, for 52.00. Selecting the band from the final index
    would take 14 and land at 58.00, which is a different tier.

    PRD §3.4: "A plagiarism case with an evidence score of 60.00, no cross-course
    points and one prior contributes 24.00, reaches a provisional index of 44.00,
    takes 8 escalation points because 44.00 is below the pivot, and lands at
    52.00; keying the band on the final value would give 14 points and 58.00."

    Design: Difficulty/combinatorial_formula/case_severity_index_escalation_band_read_from_provisional_mode_c
    """
    world = fixtures.seed_actors(client=api)
    prior_offering = fixtures.create_offering(
        world["dept"]["id"],
        world["reporter"]["id"],
        world["officer"],
        api,
        unique=True,
        course_code="ENGL-201",
        term_code="2025SP",
    )
    prior_report = fixtures.create_report(
        prior_offering["id"], world["student"]["id"], world["reporter_h"], api
    )
    validate_success(
        api.legacy_import_case(
            factories.legacy_import_payload(
                prior_report["id"],
                decided_at="2025-09-01T00:00:00Z",
                responsibility_finding="RESPONSIBLE",
                imposed_ladder_rank=3,
                completed_at="2025-12-01T00:00:00Z",
            ),
            world["officer"],
        ),
        201,
    )
    student = validate_success(api.get_student(world["student"]["id"], officer))
    assert student["prior_upheld_count"] == 1

    fixtures.seed_draft_report(world, client=api)
    fixtures.seed_submitted_report(world, client=api)
    fixtures.seed_accepted_report(world, client=api)
    fixtures.seed_case(world, client=api)

    case = validate_success(api.get_case(world["case"]["id"], officer))
    assertions.assert_pct_equals(
        case["evidence_strength_score"], 60.00, "evidence_strength_score"
    )
    assert case["cross_course_pattern_points"] == 0
    assert case["prior_upheld_count_at_assessment"] == 1
    assertions.assert_pct_equals(
        case["provisional_severity_index"], 44.00, "provisional_severity_index"
    )
    assert case["prior_escalation_points"] == 8
    assertions.assert_pct_equals(case["severity_index"], 52.00, "severity_index")
    assert case["recommended_ladder_rank"] == 3
    assertions.assert_pct_equals(
        case["informal_severity_index"], 44.00, "informal_severity_index"
    )
    assert case["informal_recommended_ladder_rank"] == 3


def test_severity_assessment_read_reselects_the_band_after_a_second_prior(
    api, officer
):
    """The read re-runs the whole chain, so a second prior moves the band.

    With one prior the read shows 8 escalation points, 52.00 and tier 3 with a
    band from 2 to 4. A second same-course prior leaves the provisional index at
    44.00 but moves the band selection to the two-or-more row, giving 18 points,
    62.00, tier 5 and a band from 4 to 6.

    PRD §3.4: "18 with two or more priors and a provisional index below 50.00"
    PRD §3.4: "The read re-runs the assessment, so a case whose sibling history
    has changed reports fresh numbers."

    Design: Difficulty/combinatorial_formula/case_severity_index_escalation_band_read_from_provisional_mode_c
    """
    world = fixtures.seed_actors(client=api)
    first_offering = fixtures.create_offering(
        world["dept"]["id"],
        world["reporter"]["id"],
        world["officer"],
        api,
        unique=True,
        course_code="ENGL-201",
        term_code="2025SP",
    )
    first_report = fixtures.create_report(
        first_offering["id"], world["student"]["id"], world["reporter_h"], api
    )
    validate_success(
        api.legacy_import_case(
            factories.legacy_import_payload(
                first_report["id"],
                decided_at="2025-09-01T00:00:00Z",
                responsibility_finding="RESPONSIBLE",
                imposed_ladder_rank=3,
                completed_at="2025-12-01T00:00:00Z",
            ),
            world["officer"],
        ),
        201,
    )
    fixtures.seed_draft_report(world, client=api)
    fixtures.seed_submitted_report(world, client=api)
    fixtures.seed_accepted_report(world, client=api)
    fixtures.seed_case(world, client=api)

    one_prior = validate_success(
        api.get_severity_assessment(world["case"]["id"], officer)
    )
    assert one_prior["pathway_basis"] == "FORMAL"
    assert one_prior["base_points"] == 20
    assertions.assert_pct_equals(
        one_prior["evidence_contribution"], 24.00, "evidence_contribution"
    )
    assert one_prior["distinct_other_course_codes"] == 0
    assert one_prior["cross_course_pattern_points"] == 0
    assert one_prior["prior_upheld_count_at_assessment"] == 1
    assertions.assert_pct_equals(
        one_prior["provisional_severity_index"], 44.00, "provisional_severity_index"
    )
    assert one_prior["prior_escalation_points"] == 8
    assertions.assert_pct_equals(one_prior["severity_index"], 52.00, "severity_index")
    assert one_prior["tier_rank"] == 3
    assert one_prior["panel_severity_recommendation"] is None
    assert one_prior["recommended_ladder_rank"] == 3
    assert one_prior["permitted_band_min"] == 2
    assert one_prior["permitted_band_max"] == 4
    assert one_prior["required_panel_size"] == 3
    assert one_prior["informal_pathway_permitted"] is True

    second_offering = fixtures.create_offering(
        world["dept"]["id"],
        world["reporter"]["id"],
        world["officer"],
        api,
        unique=True,
        course_code="ENGL-201",
        term_code="2024FA",
    )
    second_report = fixtures.create_report(
        second_offering["id"], world["student"]["id"], world["reporter_h"], api
    )
    validate_success(
        api.legacy_import_case(
            factories.legacy_import_payload(
                second_report["id"],
                decided_at="2025-01-15T00:00:00Z",
                responsibility_finding="RESPONSIBLE",
                imposed_ladder_rank=3,
                completed_at="2025-03-01T00:00:00Z",
            ),
            world["officer"],
        ),
        201,
    )

    two_priors = validate_success(
        api.get_severity_assessment(world["case"]["id"], officer)
    )
    assert two_priors["distinct_other_course_codes"] == 0
    assert two_priors["cross_course_pattern_points"] == 0
    assert two_priors["prior_upheld_count_at_assessment"] == 2
    assertions.assert_pct_equals(
        two_priors["provisional_severity_index"],
        44.00,
        "provisional_severity_index with two priors",
    )
    assert two_priors["prior_escalation_points"] == 18
    assertions.assert_pct_equals(
        two_priors["severity_index"], 62.00, "severity_index with two priors"
    )
    assert two_priors["tier_rank"] == 5
    assert two_priors["recommended_ladder_rank"] == 5
    assert two_priors["permitted_band_min"] == 4
    assert two_priors["permitted_band_max"] == 6
    assert two_priors["required_panel_size"] == 3
    assert two_priors["informal_pathway_permitted"] is False


def test_imposition_moves_both_state_dimensions_with_one_version_advance(
    api, officer
):
    """Adjudication and notation are parallel dimensions of the same case.

    A panel recommendation of 4 floors the rank-3 tier at 4, which is the only
    route to `TRANSCRIPT_NOTATION_ONLY`. Imposing it drives the adjudication
    dimension from `DECIDED` to `SANCTION_IMPOSED` and the notation dimension
    from `NOT_APPLICABLE` to `PENDING_POSTING` in one request, and `version`
    advances exactly once for both.

    PRD §3.8: "`notation_status` becomes `PENDING_POSTING` when the sanction's
    `ladder_rank` is 4 or greater, leaving `expungement_eligible_at` null until
    the sanction is completed. `version` advances once."

    Design: Difficulty/non_linear_state_machine/case_parallel_dimensions_advance_independently_of_each_other
    """
    world = fixtures.seed_convened_session(client=api)
    fixtures.cast_vote(world, 0, "RESPONSIBLE", 6, api)
    fixtures.cast_vote(world, 1, "RESPONSIBLE", 4, api)
    fixtures.cast_vote(world, 2, "NOT_RESPONSIBLE", None, api)
    fixtures.decide_hearing(world, client=api)

    decided = validate_success(api.get_case(world["case"]["id"], officer))
    assert decided["adjudication_status"] == "DECIDED"
    assert decided["notation_status"] == "NOT_APPLICABLE"
    assert decided["responsibility_finding"] == "RESPONSIBLE"
    assert decided["finding_basis"] == "PANEL"
    assert decided["panel_severity_recommendation"] == 4
    assert decided["recommended_ladder_rank"] == 4

    fixtures.propose_sanction(world, 4, client=api)
    proposed_case = validate_success(api.get_case(world["case"]["id"], officer))
    assert proposed_case["adjudication_status"] == "DECIDED"
    assert proposed_case["notation_status"] == "NOT_APPLICABLE"

    fixtures.impose_sanction(world, client=api)

    sanction = validate_success(api.get_sanction(world["sanction"]["id"], officer))
    assert sanction["status"] == "IMPOSED"
    assert sanction["kind"] == "TRANSCRIPT_NOTATION_ONLY"
    assert sanction["ladder_rank"] == 4
    assertions.assert_instant_equals(
        sanction["imposed_at"], "2026-08-20T10:00:00Z", "imposed_at"
    )
    assertions.assert_pct_equals(
        sanction["adjusted_course_grade_pct"],
        0.00,
        "adjusted_course_grade_pct on a non-grade kind",
    )
    assertions.assert_pct_equals(
        sanction["grade_penalty_delta_pct"],
        0.00,
        "grade_penalty_delta_pct on a non-grade kind",
    )

    imposed = validate_success(api.get_case(world["case"]["id"], officer))
    assert imposed["adjudication_status"] == "SANCTION_IMPOSED"
    assert imposed["notation_status"] == "PENDING_POSTING"
    assert imposed["expungement_eligible_at"] is None
    assert imposed["version"] == proposed_case["version"] + 1, (
        "one request touching both dimensions must advance version exactly once"
    )

    student = validate_success(api.get_student(world["student"]["id"], officer))
    assert student["active_sanction_points"] == 4
    assert student["standing"] == "GOOD_STANDING"
    assert student["transcript_notation"] == "NONE"


def test_notation_dimension_advances_while_adjudication_stands_still(
    api, officer, registrar
):
    """The registrar moves the notation dimension and nothing else.

    Posting the pending notation takes `notation_status` to `POSTED` and the
    student's `transcript_notation` with it, while `adjudication_status` stays at
    `SANCTION_IMPOSED`; `expungement_eligible_at` stays null because the
    governing sanction has not been completed.

    PRD §2.10: "Neither dimension constrains the other except where a rule in §3
    explicitly names the other field."
    PRD §3.10: "`expungement_eligible_at` is computed — or left null when the
    governing sanction is not yet `COMPLETED`"

    Design: Difficulty/non_linear_state_machine/case_parallel_dimensions_advance_independently_of_each_other
    """
    world = fixtures.seed_convened_session(client=api)
    fixtures.cast_vote(world, 0, "RESPONSIBLE", 6, api)
    fixtures.cast_vote(world, 1, "RESPONSIBLE", 4, api)
    fixtures.cast_vote(world, 2, "NOT_RESPONSIBLE", None, api)
    fixtures.decide_hearing(world, client=api)
    fixtures.propose_sanction(world, 4, client=api)
    fixtures.impose_sanction(world, client=api)

    before = validate_success(api.get_case(world["case"]["id"], officer))
    assert before["adjudication_status"] == "SANCTION_IMPOSED"
    assert before["notation_status"] == "PENDING_POSTING"

    posted = validate_success(api.post_notation(world["case"]["id"], registrar))
    assert posted["notation_status"] == "POSTED"
    assert posted["adjudication_status"] == "SANCTION_IMPOSED"
    assert posted["expungement_eligible_at"] is None
    assert posted["version"] == before["version"] + 1

    reread = validate_success(api.get_case(world["case"]["id"], officer))
    assert reread["notation_status"] == "POSTED"
    assert reread["adjudication_status"] == "SANCTION_IMPOSED"
    assert reread["responsibility_finding"] == "RESPONSIBLE"

    student = validate_success(api.get_student(world["student"]["id"], officer))
    assert student["transcript_notation"] == "POSTED"
    assert student["active_sanction_points"] == 4
    assert student["standing"] == "GOOD_STANDING"

    sanction = validate_success(api.get_sanction(world["sanction"]["id"], officer))
    assert sanction["status"] == "IMPOSED"
    assert sanction["completed_at"] is None


def test_returned_report_cannot_be_resubmitted_without_fresh_evidence(api, officer):
    """The return-for-info loop demands evidence newer than `returned_at`.

    The report still satisfies the DRAFT-side rule — it has a similarity item and
    `evidence_complete` is true — but nothing was added after the return, so the
    resubmission is refused and neither the status nor the resubmission counter
    moves.

    PRD §3.3: "From `RETURNED_FOR_INFO` the requirement is different: at least
    one evidence item must have been added since the report's `returned_at`,
    otherwise `ERR_EVIDENCE_INCOMPLETE`"

    The clock is advanced to 2026-08-03 before the return, so the seeded evidence
    sits strictly before `returned_at` rather than sharing its instant.  PRD §2.4
    makes every window "inclusive at both ends unless the text says strictly", so
    an item created at exactly `returned_at` would count as added since it; only
    an item created before it is unambiguously stale.

    Design: Difficulty/non_linear_state_machine/integrity_report_returned_for_info_cycle_requires_fresh_evidence
    """
    world = fixtures.seed_submitted_report(client=api)
    fixtures.set_clock("2026-08-03T00:00:00Z", world["officer"], api)
    fixtures.triage_report(
        world["report"]["id"],
        "RETURN_FOR_INFO",
        "More context needed on the source overlap.",
        world["officer"],
        api,
    )

    returned = validate_success(api.get_report(world["report"]["id"], officer))
    assert returned["status"] == "RETURNED_FOR_INFO"
    assert returned["evidence_complete"] is True
    assertions.assert_pct_equals(
        returned["evidence_strength_score"], 60.00, "evidence_strength_score"
    )
    assert returned["resubmission_count"] == 0
    assert returned["triaged_at"] is None
    assertions.assert_instant_equals(
        returned["returned_at"], "2026-08-03T00:00:00Z", "returned_at"
    )

    fixtures.set_clock("2026-08-05T00:00:00Z", world["officer"], api)
    validate_error(
        api.submit_report(world["report"]["id"], world["reporter_h"]),
        ApiErrorId.ERR_EVIDENCE_INCOMPLETE,
        409,
    )

    unchanged = validate_success(api.get_report(world["report"]["id"], officer))
    assert unchanged["status"] == "RETURNED_FOR_INFO"
    assert unchanged["resubmission_count"] == 0
    assert unchanged["version"] == returned["version"]
    assertions.assert_instant_equals(
        unchanged["submitted_at"], "2026-08-01T00:00:00Z", "submitted_at"
    )

    reporter = validate_success(api.get_faculty_member(world["reporter"]["id"], officer))
    assert reporter["reports_submitted_count"] == 1


def test_fresh_evidence_reopens_the_submit_path_and_preserves_submitted_at(
    api, officer
):
    """A resubmission counts the cycle without rewriting the first submission.

    A witness statement added after `returned_at` unblocks the resubmission: the
    status returns to `SUBMITTED`, `resubmission_count` reaches 1, the score is
    recomputed over the enlarged set to 80.00, and `submitted_at` still records
    the first submission four days earlier.

    PRD §3.3: "On a resubmission `status` becomes `SUBMITTED` again,
    `submitted_at` is left untouched so that it always records the first
    submission, `resubmission_count` increases by one"

    Design: Difficulty/non_linear_state_machine/integrity_report_returned_for_info_cycle_requires_fresh_evidence
    """
    world = fixtures.seed_submitted_report(client=api)
    fixtures.triage_report(
        world["report"]["id"],
        "RETURN_FOR_INFO",
        "More context needed on the source overlap.",
        world["officer"],
        api,
    )

    fixtures.set_clock("2026-08-05T00:00:00Z", world["officer"], api)
    item = validate_success(
        api.create_evidence_item(
            factories.witness_statement_payload(world["report"]["id"]),
            world["reporter_h"],
        ),
        201,
    )
    assertions.assert_absent(item, "updated_at", "version")

    resubmitted = validate_success(
        api.submit_report(world["report"]["id"], world["reporter_h"])
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["resubmission_count"] == 1
    assertions.assert_pct_equals(
        resubmitted["evidence_strength_score"],
        80.00,
        "evidence_strength_score over the enlarged set",
    )
    assertions.assert_instant_equals(
        resubmitted["submitted_at"], "2026-08-01T00:00:00Z", "submitted_at"
    )

    reread = validate_success(api.get_report(world["report"]["id"], officer))
    assert reread["status"] == "SUBMITTED"
    assert reread["resubmission_count"] == 1
    assertions.assert_instant_equals(
        reread["submitted_at"], "2026-08-01T00:00:00Z", "persisted submitted_at"
    )
    assertions.assert_pct_equals(
        reread["evidence_strength_score"], 80.00, "persisted evidence_strength_score"
    )

    reporter = validate_success(api.get_faculty_member(world["reporter"]["id"], officer))
    assert reporter["reports_submitted_count"] == 1


def test_remand_unwinds_the_decision_and_reopens_the_hearing_loop(api, officer):
    """A remand pushes a decided case backwards into a second hearing round.

    The finding, the basis, the panel recommendation and `decided_at` are all
    unwound, the rank falls back to the plain tier rank, a `REHEARING_NOTICE`
    restarts the ten-day clock, and the case becomes schedulable again — the
    second session opens round 2 and charges the room a second time.

    PRD §3.9: "`responsibility_finding` returns to `UNDETERMINED`,
    `finding_basis` to `NONE`, `panel_severity_recommendation` to null and
    `decided_at` to null"
    PRD §3.7: "`round_number` set to the case's `hearing_round` plus one"

    Design: Difficulty/non_linear_state_machine/appeal_remand_reopens_the_hearing_loop_once_then_hits_the_round_limit
    """
    world = fixtures.seed_decided_case(client=api)
    first_session_id = world["session"]["id"]
    room_id = world["room"]["id"]

    fixtures.file_appeal(world, "PROCEDURE", client=api)
    assert world["appeal"]["status"] == "SUBMITTED"
    assert world["appeal"]["hearing_round_at_filing"] == 1
    assert world["appeal"]["decided_at"] is None

    fixtures.screen_appeal(world, "ACCEPT_FOR_REVIEW", client=api)
    assert world["appeal"]["status"] == "UNDER_REVIEW"
    screened_case = validate_success(api.get_case(world["case"]["id"], officer))
    assert screened_case["adjudication_status"] == "APPEAL_UNDER_REVIEW"
    # PRD §3.9 puts `pre_appeal_adjudication_status` on the Case, not the Appeal.
    assert screened_case["pre_appeal_adjudication_status"] == "DECIDED"

    fixtures.decide_appeal(world, "REMANDED", client=api)
    appeal = validate_success(api.get_appeal(world["appeal"]["id"], officer))
    assert appeal["status"] == "REMANDED"
    assertions.assert_instant_equals(
        appeal["decided_at"], "2026-08-20T10:00:00Z", "appeal decided_at"
    )

    remanded = validate_success(api.get_case(world["case"]["id"], officer))
    assert remanded["adjudication_status"] == "FORMAL_REFERRED"
    assert remanded["responsibility_finding"] == "UNDETERMINED"
    assert remanded["finding_basis"] == "NONE"
    assert remanded["panel_severity_recommendation"] is None
    assert remanded["decided_at"] is None
    assert remanded["pre_appeal_adjudication_status"] is None
    assert remanded["notation_status"] == "NOT_APPLICABLE"
    assert remanded["pathway"] == "FORMAL"
    assert remanded["hearing_round"] == 1
    assertions.assert_pct_equals(remanded["severity_index"], 44.00, "severity_index")
    assert remanded["recommended_ladder_rank"] == 3

    # PRD §4 declares the `kind` filter on the global notification list
    # ("List notifications, filterable by case and kind"), not on the
    # case sub-resource listing, which is a plain "listing of a case's notices".
    notices, _meta = assertions.validate_list(
        api.list_notifications(
            officer,
            params={
                "case_id": world["case"]["id"],
                "kind": "REHEARING_NOTICE",
                "limit": 100,
            },
        )
    )
    assert len(notices) == 1
    assertions.assert_instant_equals(
        notices[0]["sent_at"], "2026-08-20T10:00:00Z", "rehearing notice sent_at"
    )

    first_session = validate_success(api.get_hearing_session(first_session_id, officer))
    assert first_session["status"] == "DECIDED"
    assert first_session["round_number"] == 1

    fixtures.schedule_hearing(
        world,
        start_at="2026-09-05T10:00:00Z",
        end_at="2026-09-05T11:30:00Z",
        client=api,
    )
    second_session = validate_success(
        api.get_hearing_session(world["session"]["id"], officer)
    )
    assert second_session["id"] != first_session_id
    assert second_session["status"] == "SCHEDULED"
    assert second_session["round_number"] == 2
    assert second_session["quorum_required"] == 2
    assert second_session["panel_finding"] is None
    assert second_session["effective_vote_count"] == 0

    rescheduled = validate_success(api.get_case(world["case"]["id"], officer))
    assert rescheduled["adjudication_status"] == "HEARING_SCHEDULED"
    assert rescheduled["hearing_round"] == 2

    room = validate_success(api.get_hearing_room(room_id, officer))
    assert room["booked_minutes_total"] == 300


def test_second_remand_is_refused_after_the_case_has_opened_two_rounds(api, officer):
    """The loop closes: a case may be remanded once, never twice.

    The second hearing round decides the case again and the student's second and
    final appeal reaches review, but `hearing_round` now stands at 2, so the
    remand is refused and the appeal stays `UNDER_REVIEW` with no decision
    recorded.

    PRD §3.9: "its `hearing_round` must be no greater than 1, otherwise
    `ERR_REMAND_LIMIT_REACHED` — a case may be remanded once, never twice."

    Design: Difficulty/non_linear_state_machine/appeal_remand_reopens_the_hearing_loop_once_then_hits_the_round_limit
    """
    world = fixtures.seed_decided_case(client=api)
    fixtures.file_appeal(world, "PROCEDURE", client=api)
    fixtures.screen_appeal(world, "ACCEPT_FOR_REVIEW", client=api)
    fixtures.decide_appeal(world, "REMANDED", client=api)
    fixtures.schedule_hearing(
        world,
        start_at="2026-09-05T10:00:00Z",
        end_at="2026-09-05T11:30:00Z",
        client=api,
    )
    fixtures.convene_hearing(world, "2026-09-05T10:00:00Z", api)
    fixtures.cast_responsible_majority(world, 4, api)
    fixtures.decide_hearing(world, client=api)

    redecided = validate_success(api.get_case(world["case"]["id"], officer))
    assert redecided["adjudication_status"] == "DECIDED"
    assert redecided["responsibility_finding"] == "RESPONSIBLE"
    assert redecided["finding_basis"] == "PANEL"
    assert redecided["panel_severity_recommendation"] == 4
    assert redecided["recommended_ladder_rank"] == 4
    assert redecided["hearing_round"] == 2
    assertions.assert_instant_equals(
        redecided["decided_at"], "2026-09-05T10:00:00Z", "second decided_at"
    )

    fixtures.file_appeal(world, "EVIDENCE", client=api)
    assert world["appeal"]["hearing_round_at_filing"] == 2
    fixtures.screen_appeal(world, "ACCEPT_FOR_REVIEW", client=api)
    assert world["appeal"]["status"] == "UNDER_REVIEW"

    validate_error(
        api.decide_appeal(
            world["appeal"]["id"],
            factories.appeal_decision_payload("REMANDED"),
            world["dean"],
        ),
        ApiErrorId.ERR_REMAND_LIMIT_REACHED,
        409,
    )

    appeal = validate_success(api.get_appeal(world["appeal"]["id"], officer))
    assert appeal["status"] == "UNDER_REVIEW"
    assert appeal["decided_at"] is None
    assert appeal["hearing_round_at_filing"] == 2

    case = validate_success(api.get_case(world["case"]["id"], officer))
    assert case["adjudication_status"] == "APPEAL_UNDER_REVIEW"
    assert case["responsibility_finding"] == "RESPONSIBLE"
    assert case["hearing_round"] == 2
    assertions.assert_instant_equals(
        case["decided_at"], "2026-09-05T10:00:00Z", "decided_at after the refusal"
    )
