"""Penalty pipeline, abatement deadlines, and finalization (PRD §3.4, §2.7):
points factor tables, tiered dollar conversion, half-up rounding, statutory
floors, the good-faith discount, extensions, and the finalize window.

Clock note: all readings are >= the startup reading 2026-09-01T00:00:00Z
(PRD §2.4). Rebased literals: issuance at 2026-09-10T09:00:00Z gives a
NO_INJURY (30-day) deadline of 2026-10-10T09:00:00Z and a contest/finalize
window ending 2026-10-10T09:00:00Z; a SERIOUS (5-day) citation's deadline is
2026-09-15T09:00:00Z and its single extension (+ceil(5/2)=3 days) moves it to
2026-09-18T09:00:00Z. Penalty cent amounts are date-independent.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    abate_citation_flow,
    decide_contest_flow,
    docket_contest_flow,
    extend_citation_flow,
    file_contest_flow,
    finalize_assessment_flow,
    get_assessment_for_citation,
    in_progress_inspection,
    issue_citation,
    issue_n_citations,
    make_operator_rep_headers,
    refresh_citation,
    set_clock,
    setup_inspector,
    setup_registry,
    validate_error,
    verify_citation_flow,
    withdraw_contest_flow,
)

_ADMIN = TEST_USERS["admin_headers"]

# The 15-point repeat-violation citation used by several tests:
# NONE(0) + REASONABLY_LIKELY(15) + NO_INJURY(0) + 1 person(0) + non-S&S(0)
# + history(0) + size(0 for 1000 tons) = 15 points; gross 15 x 11250 = 168750c;
# x1.15 = 194062.50 -> round half-up 194063 (PRD §3.4, §2.7).
REPEAT_15PT_FACTORS = {
    "negligence": "NONE",
    "gravity_likelihood": "REASONABLY_LIKELY",
    "gravity_severity": "NO_INJURY",
    "persons_affected": 1,
    "significant_and_substantial": False,
    "repeat_violation": True,
}


def test_penalty_proposed_vs_final_good_faith_divergence(api):
    """PRD §3.4: "The proposed variant, computed at issuance, runs steps one,
    two, and four only — no good-faith discount can exist before the outcome of
    abatement is known."
    PRD §3.4: "Third — only in the final variant — the good-faith discount
    subtracts 10 percent of the multiplied amount, the discount itself rounded
    half-up to whole cents, and this discount applies only when the citation's
    abatement axis stands at `VERIFIED` with `verified_at` on or before the
    `abatement_deadline`."

    Design: Difficulty/dual_variant_calc/penalty_proposed_vs_final_good_faith_divergence
    """
    set_clock("2026-09-10T08:00:00Z")
    operator, mine, i1 = setup_registry(tonnage=1000)
    verifier = setup_inspector()
    inspection = in_progress_inspection(mine, i1, kind="SPOT")

    set_clock("2026-09-10T09:00:00Z")
    citation = issue_citation(inspection, mine, i1, **REPEAT_15PT_FACTORS)
    assessment = get_assessment_for_citation(citation["id"])
    assert assessment["points_total"] == 15
    assert assessment["proposed_penalty_cents"] == 194063
    assert assessment["status"] == "PROPOSED"
    assert assessment["good_faith_applied"] is False

    # On-time abatement + verification (deadline 2026-10-10T09:00:00Z).
    set_clock("2026-09-11T09:00:00Z")
    citation = abate_citation_flow(citation, operator)
    set_clock("2026-09-12T09:00:00Z")
    citation = verify_citation_flow(citation, verifier)

    # Finalize strictly past issued_at + 30 days (2026-10-10T09:00:00Z).
    set_clock("2026-10-11T09:00:01Z")
    finalized = finalize_assessment_flow(assessment)
    assert finalized["status"] == "FINAL"
    assert finalized["proposed_penalty_cents"] == 194063, (
        "the proposed variant never runs the good-faith step"
    )
    # discount = round_half_up(194063 x 0.10) = 19406; 194063 - 19406 = 174657
    assert finalized["final_penalty_cents"] == 174657
    assert finalized["good_faith_applied"] is True
    assert finalized["statutory_floor_applied"] is False
    assert finalized["proposed_penalty_cents"] - finalized["final_penalty_cents"] == 19406, (
        "the two pipeline variants diverge by exactly the final-only discount step"
    )


def test_penalty_points_tiered_multi_input_total(api):
    """PRD §3.4: "Negligence contributes 0 points for `NONE`, 10 for `LOW`,
    25 for `MODERATE`, 40 for `HIGH`, and 50 for `RECKLESS_DISREGARD`.
    Likelihood contributes 5 for `UNLIKELY`, 15 for `REASONABLY_LIKELY`, and 25
    for `HIGHLY_LIKELY`. Severity contributes 0 for `NO_INJURY`, 10 for
    `MINOR`, 20 for `SERIOUS`, and 30 for `FATAL_POTENTIAL`. Exposure
    contributes 0 points when exactly one person is affected, 5 for two through
    five persons, 10 for six through twenty, and 20 for twenty-one or more. A
    significant-and-substantial citation adds a 15-point surcharge."
    PRD §3.4: "First, the point total converts to gross cents marginally across
    four tiers: the first twenty points at 11,250 cents each, the next forty
    points (points 21 through 60) at 22,500 cents each, the following forty
    (points 61 through 100) at 37,500 cents each, and every point beyond 100 at
    52,500 cents each."

    Design: Difficulty/combinatorial_formula/penalty_points_tiered_multi_input_total
    """
    set_clock("2026-09-10T08:00:00Z")
    _operator, mine, i1 = setup_registry(mine_type="SURFACE", tonnage=120000)
    inspection = in_progress_inspection(mine, i1, kind="SPOT")
    set_clock("2026-09-10T09:00:00Z")
    citation = issue_citation(
        inspection, mine, i1,
        negligence="MODERATE", gravity_likelihood="REASONABLY_LIKELY",
        gravity_severity="SERIOUS", persons_affected=3,
        significant_and_substantial=True, repeat_violation=False,
    )
    # MODERATE 25 + REASONABLY_LIKELY 15 + SERIOUS 20 + persons(3) 5
    # + S&S 15 + history 0 + size(120000 tons) 5 = 85 points.
    assert citation["abatement_base_days"] == 5
    assert citation["abatement_deadline"] == "2026-09-15T09:00:00Z"

    assessment = get_assessment_for_citation(citation["id"])
    assert assessment["points_total"] == 85
    # 20*11250 + 40*22500 + 25*37500 = 225000 + 900000 + 937500
    assert assessment["proposed_penalty_cents"] == 2062500
    assert assessment["statutory_floor_applied"] is False


def test_repeat_multiplier_half_up_rounding_step(api):
    """PRD §3.4: "Second, when `repeat_violation` is true, the gross amount is
    multiplied by 1.15 and rounded half-up to whole cents; a non-repeat
    citation skips the multiplier untouched."
    PRD §2.7: "Within the penalty pipeline, rounding happens at exactly two
    places and nowhere else: once after the repeat-violation multiplier is
    applied, and once after the good-faith discount is computed, each time
    rounding half-up to whole cents; intermediate values are exact decimals."

    Design: Difficulty/combinatorial_formula/repeat_multiplier_half_up_rounding_step
    """
    set_clock("2026-09-10T08:00:00Z")
    _operator, mine, i1 = setup_registry(tonnage=1000)
    inspection = in_progress_inspection(mine, i1, kind="SPOT")
    set_clock("2026-09-10T09:00:00Z")
    citation = issue_citation(inspection, mine, i1, **REPEAT_15PT_FACTORS)

    assessment = get_assessment_for_citation(citation["id"])
    assert assessment["points_total"] == 15
    # 168750 x 1.15 = 194062.50 exactly; half-up yields 194063, NOT 194062.
    assert assessment["proposed_penalty_cents"] == 194063


def test_finalize_blocked_while_contest_pending(api):
    """PRD §3.4: "Finalization also requires the citation's `contest_status` to
    be `UNCONTESTED` — a citation under contest blocks finalization with
    `ERR_INVALID_STATE`, and the assessment must still be `PROPOSED` —
    whereupon `final_penalty_cents` is computed by the final variant of the
    pipeline, good-faith discount included when verification was on time."
    PRD §3.6: "Withdrawal is a compensating action that restores the
    pre-contest posture: the citation's contest axis returns from `CONTESTED`
    to `UNCONTESTED` with a version increment, and the assessment returns from
    `CONTESTED` to `PROPOSED`, from which an administrator may later finalize
    it once the contest window has lapsed, exactly as in §3.4."

    Design: Difficulty/cross_entity_state_dependency/finalize_blocked_while_contest_pending
    """
    set_clock("2026-09-10T08:00:00Z")
    operator, mine, i1 = setup_registry(tonnage=1000)
    inspection = in_progress_inspection(mine, i1, kind="SPOT")
    set_clock("2026-09-10T09:00:00Z")
    citation = issue_citation(inspection, mine, i1, **REPEAT_15PT_FACTORS)
    assessment = get_assessment_for_citation(citation["id"])

    set_clock("2026-09-12T10:00:00Z")
    contest = file_contest_flow(citation, operator, grounds="amount disputed")
    assert get_assessment_for_citation(citation["id"])["status"] == "CONTESTED"

    # Window fully lapsed (issued 2026-09-10T09:00:00Z + 30 days), yet the
    # pending contest still blocks finalization.
    set_clock("2026-10-13T10:00:00Z")
    resp = api.finalize_penalty_assessment(assessment["id"], _ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    # Withdrawal restores PROPOSED; the identical finalize now succeeds.
    withdrawn = withdraw_contest_flow(contest, operator)
    assert withdrawn["status"] == "WITHDRAWN"
    assert refresh_citation(citation["id"])["contest_status"] == "UNCONTESTED"
    assert get_assessment_for_citation(citation["id"])["status"] == "PROPOSED"

    finalized = finalize_assessment_flow(assessment)
    assert finalized["status"] == "FINAL"
    assert finalized["final_penalty_cents"] == 194063, (
        "never abated: the final variant runs no good-faith discount"
    )
    assert finalized["good_faith_applied"] is False


def test_issue_vacate_pair_conserves_mine_penalty_exposure(api):
    """PRD §3.6: "`VACATED` moves the axis to `VACATED` and finalizes the
    assessment at zero cents; from `decided_at` onward the vacated citation is
    excluded both from pattern-of-violations windows and from the 730-day
    history counts of future citations."
    PRD §3.4: "Fourth and last, the statutory floor applies: 150,000 cents for
    an `ORDER`, 120,000 cents for a significant-and-substantial `CITATION`, and
    60,000 cents for a `CITATION` without the S&S designation; the stored
    amount is the greater of the computed net and the floor."

    Exposure metric (test-side): sum over the mine's citations with
    contest_status != VACATED of (final_penalty_cents if FINAL else
    proposed_penalty_cents).

    Design: Difficulty/compensating_invariant/issue_vacate_pair_conserves_mine_penalty_exposure
    """
    set_clock("2026-09-10T08:00:00Z")
    operator, mine, i1 = setup_registry(mine_type="SURFACE", tonnage=120000)
    inspection = in_progress_inspection(mine, i1, kind="SPOT")
    set_clock("2026-09-10T09:00:00Z")

    # Citation 1: 20 points (likelihood 15 + size 5), repeat -> 225000 x 1.15.
    cit1 = issue_citation(inspection, mine, i1, **REPEAT_15PT_FACTORS)
    asm1 = get_assessment_for_citation(cit1["id"])
    assert asm1["points_total"] == 20
    assert asm1["proposed_penalty_cents"] == 258750
    exposure_before = asm1["proposed_penalty_cents"]

    # Citation 2: 25+15+10+5+15+0(history: 1 prior)+5(size) = 75 points.
    cit2 = issue_citation(
        inspection, mine, i1,
        standard_code="30 CFR 56.14100",
        negligence="MODERATE", gravity_likelihood="REASONABLY_LIKELY",
        gravity_severity="MINOR", persons_affected=2,
        significant_and_substantial=True, repeat_violation=False,
    )
    asm2 = get_assessment_for_citation(cit2["id"])
    assert asm2["points_total"] == 75
    # 20*11250 + 40*22500 + 15*37500 = 1687500
    assert asm2["proposed_penalty_cents"] == 1687500
    assert exposure_before + asm2["proposed_penalty_cents"] == 1946250

    set_clock("2026-09-12T10:00:00Z")
    contest = file_contest_flow(cit2, operator, grounds="severity overstated")
    docket_contest_flow(contest)
    set_clock("2026-09-20T10:00:00Z")
    decide_contest_flow(contest, "VACATED")

    cit2_after = refresh_citation(cit2["id"])
    asm2_after = get_assessment_for_citation(cit2["id"])
    assert cit2_after["contest_status"] == "VACATED"
    assert asm2_after["status"] == "FINAL"
    assert asm2_after["final_penalty_cents"] == 0

    # The forward/compensating pair conserves the mine's penalty exposure.
    asm1_after = get_assessment_for_citation(cit1["id"])
    assert asm1_after["status"] == "PROPOSED"
    assert asm1_after["proposed_penalty_cents"] == 258750
    exposure_after = asm1_after["proposed_penalty_cents"]
    assert exposure_after == exposure_before == 258750


def test_statutory_floor_raises_small_penalty(api):
    """PRD §3.4: "Fourth and last, the statutory floor applies: 150,000 cents
    for an `ORDER`, 120,000 cents for a significant-and-substantial `CITATION`,
    and 60,000 cents for a `CITATION` without the S&S designation; the stored
    amount is the greater of the computed net and the floor."
    PRD §3.4: "`statutory_floor_applied` records whether the floor raised the
    stored amount above the computed figure."

    Design: Corner/calculations/statutory_floor_raises_small_penalty
    """
    set_clock("2026-09-10T08:00:00Z")
    _operator, mine, i1 = setup_registry(tonnage=1000)
    inspection = in_progress_inspection(mine, i1, kind="SPOT")
    set_clock("2026-09-10T09:00:00Z")
    citation = issue_citation(
        inspection, mine, i1,
        standard_code="30 CFR 75.1100",
        negligence="NONE", gravity_likelihood="UNLIKELY",
        gravity_severity="NO_INJURY", persons_affected=1,
        significant_and_substantial=False, repeat_violation=False,
    )
    assessment = get_assessment_for_citation(citation["id"])
    assert assessment["points_total"] == 5
    # 5 x 11250 = 56250 computed; the 60000c non-S&S CITATION floor raises it.
    assert assessment["proposed_penalty_cents"] == 60000
    assert assessment["statutory_floor_applied"] is True


def test_history_window_tier_counts_six_priors(api):
    """PRD §3.4: "History contributes according to the count of the mine's
    other citations — excluding the new citation itself — whose `issued_at`
    falls in the trailing 730-day window that excludes the window's opening
    instant and includes the new citation's own `issued_at`, counting only
    citations whose `contest_status` is not `VACATED`: 0 points for up to five
    such citations, 5 for six through fifteen, 10 for sixteen through thirty,
    and 20 for thirty-one or more."

    Design: Corner/calculations/history_window_tier_counts_six_priors
    """
    set_clock("2026-09-10T08:00:00Z")
    _operator, mine, i1 = setup_registry(tonnage=1000)
    inspection = in_progress_inspection(mine, i1, kind="SPOT")
    set_clock("2026-09-10T09:00:00Z")
    # Six minimal priors (UNLIKELY-only factor weight), each 5 points floored.
    issue_n_citations(
        inspection, mine, i1, 6,
        factor_overrides={"negligence": "NONE"},
        standard_code_prefix="30 CFR 75.20",
    )
    seventh = issue_citation(
        inspection, mine, i1,
        standard_code="30 CFR 75.206",
        negligence="NONE", gravity_likelihood="UNLIKELY",
        gravity_severity="NO_INJURY", persons_affected=1,
        significant_and_substantial=False, repeat_violation=False,
    )
    assessment = get_assessment_for_citation(seventh["id"])
    # 5 (likelihood) + 5 (history: exactly 6 priors lands in the 6..15 tier)
    assert assessment["points_total"] == 10
    assert assessment["proposed_penalty_cents"] == 112500  # 10 x 11250; floor unreached
    assert assessment["statutory_floor_applied"] is False


def test_verification_at_exact_deadline_keeps_good_faith(api):
    """PRD §3.4: "Verification exactly at the deadline counts as on time."
    PRD §3.4: "Third — only in the final variant — the good-faith discount
    subtracts 10 percent of the multiplied amount, the discount itself rounded
    half-up to whole cents, and this discount applies only when the citation's
    abatement axis stands at `VERIFIED` with `verified_at` on or before the
    `abatement_deadline`."

    Design: Corner/calculations/verification_at_exact_deadline_keeps_good_faith
    """
    set_clock("2026-09-10T08:00:00Z")
    operator, mine, i1 = setup_registry(tonnage=1000)
    verifier = setup_inspector()
    inspection = in_progress_inspection(mine, i1, kind="SPOT")
    set_clock("2026-09-10T09:00:00Z")
    citation = issue_citation(inspection, mine, i1, **REPEAT_15PT_FACTORS)
    assessment = get_assessment_for_citation(citation["id"])

    set_clock("2026-09-11T09:00:00Z")
    citation = abate_citation_flow(citation, operator)

    # verified_at == abatement_deadline exactly (2026-10-10T09:00:00Z): on time.
    set_clock("2026-10-10T09:00:00Z")
    citation = verify_citation_flow(citation, verifier)
    assert citation["verified_at"] == "2026-10-10T09:00:00Z"
    assert citation["abatement_deadline"] == "2026-10-10T09:00:00Z"

    set_clock("2026-10-11T00:00:00Z")
    finalized = finalize_assessment_flow(assessment)
    assert finalized["final_penalty_cents"] == 174657
    assert finalized["good_faith_applied"] is True


def test_abatement_extension_adds_half_base_days_once(api):
    """PRD §3.4: "Once per citation, and only while the axis is `OPEN` and the
    clock reads strictly before the current `abatement_deadline`, the operator
    may request an extension with a `justification`: the deadline advances by
    half the base days rounded up (15 days on a 30-day base, 8 on a 15-day
    base, 3 on a 5-day base, 1 on a 1-day base) and `abatement_extended`
    becomes true."

    Design: Corner/calculations/abatement_extension_adds_half_base_days_once
    """
    set_clock("2026-09-10T08:00:00Z")
    operator, mine, i1 = setup_registry(tonnage=1000)
    inspection = in_progress_inspection(mine, i1, kind="SPOT")
    set_clock("2026-09-10T09:00:00Z")
    citation = issue_citation(
        inspection, mine, i1,
        standard_code="30 CFR 75.500",
        negligence="MODERATE", gravity_likelihood="REASONABLY_LIKELY",
        gravity_severity="SERIOUS", persons_affected=2,
        significant_and_substantial=False, repeat_violation=False,
    )
    assert citation["abatement_base_days"] == 5
    assert citation["abatement_deadline"] == "2026-09-15T09:00:00Z"

    set_clock("2026-09-12T09:00:00Z")
    extended = extend_citation_flow(citation, operator)
    # ceil(5/2) = 3 days: 2026-09-15T09:00:00Z -> 2026-09-18T09:00:00Z
    assert extended["abatement_deadline"] == "2026-09-18T09:00:00Z"
    assert extended["abatement_extended"] is True


def test_extension_exhausted_outranks_window_passed(api):
    """PRD §2.5: "a double-extension attempted after the abatement deadline
    reports `ERR_ABATEMENT_EXTENSION_EXHAUSTED` rather than
    `ERR_ABATEMENT_WINDOW_PASSED` (tier 10 outranks tier 11)."
    PRD §3.4: "A second extension request, or any extension on a citation no
    longer `OPEN`, fails with `ERR_ABATEMENT_EXTENSION_EXHAUSTED`; an extension
    requested at or after the current deadline fails with
    `ERR_ABATEMENT_WINDOW_PASSED`"

    Design: Corner/validations/extension_exhausted_outranks_window_passed
    """
    set_clock("2026-09-10T08:00:00Z")
    operator, mine, i1 = setup_registry(tonnage=1000)
    inspection = in_progress_inspection(mine, i1, kind="SPOT")
    set_clock("2026-09-10T09:00:00Z")
    citation = issue_citation(
        inspection, mine, i1,
        standard_code="30 CFR 75.500",
        negligence="MODERATE", gravity_likelihood="REASONABLY_LIKELY",
        gravity_severity="SERIOUS", persons_affected=2,
        significant_and_substantial=False, repeat_violation=False,
    )
    set_clock("2026-09-12T09:00:00Z")
    citation = extend_citation_flow(citation, operator)
    assert citation["abatement_deadline"] == "2026-09-18T09:00:00Z"

    # Past the extended deadline AND the extension budget spent: the
    # single-extension constraint (earlier tier) is the reported error.
    set_clock("2026-09-19T10:00:00Z")
    resp = api.extend_citation_abatement(
        citation["id"],
        {"justification": "second extension attempt past the extended deadline"},
        make_operator_rep_headers(operator["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ABATEMENT_EXTENSION_EXHAUSTED)
    after = refresh_citation(citation["id"])
    assert after["abatement_deadline"] == "2026-09-18T09:00:00Z"
    assert after["abatement_extended"] is True


def test_err_finalize_window_active(api):
    """PRD §3.4: "An uncontested assessment matures to `FINAL` when an
    `MSHAAdmin` finalizes it after the contest window has fully lapsed: the
    logical clock must read strictly later than 30 days after the citation's
    `issued_at`, and finalizing at or before that instant fails with
    `ERR_FINALIZE_WINDOW_ACTIVE`."

    Design: Corner/errors/err_finalize_window_active
    """
    set_clock("2026-09-10T08:00:00Z")
    _operator, mine, i1 = setup_registry(tonnage=1000)
    inspection = in_progress_inspection(mine, i1, kind="SPOT")
    set_clock("2026-09-10T09:00:00Z")
    citation = issue_citation(inspection, mine, i1)
    assessment = get_assessment_for_citation(citation["id"])

    # issued_at + 15 days: the 30-day contest window is still open.
    set_clock("2026-09-25T09:00:00Z")
    resp = api.finalize_penalty_assessment(assessment["id"], _ADMIN)
    validate_error(resp, ApiErrorId.ERR_FINALIZE_WINDOW_ACTIVE)
    assert get_assessment_for_citation(citation["id"])["status"] == "PROPOSED"


def test_extend_abatement_after_deadline_rejected(api):
    """PRD §3.4: "an extension requested at or after the current deadline fails
    with `ERR_ABATEMENT_WINDOW_PASSED`"

    Design: Corner/errors/extend_abatement_after_deadline_rejected
    """
    set_clock("2026-09-10T08:00:00Z")
    operator, mine, i1 = setup_registry(tonnage=1000)
    inspection = in_progress_inspection(mine, i1, kind="SPOT")
    set_clock("2026-09-10T09:00:00Z")
    citation = issue_citation(
        inspection, mine, i1,
        standard_code="30 CFR 75.500",
        negligence="MODERATE", gravity_likelihood="REASONABLY_LIKELY",
        gravity_severity="SERIOUS", persons_affected=2,
        significant_and_substantial=False, repeat_violation=False,
    )
    assert citation["abatement_deadline"] == "2026-09-15T09:00:00Z"

    # One second past the (never-extended) deadline; the extension budget is
    # intact, so the temporal rule is the one that fires.
    set_clock("2026-09-15T09:00:01Z")
    resp = api.extend_citation_abatement(
        citation["id"],
        {"justification": "one second too late"},
        make_operator_rep_headers(operator["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ABATEMENT_WINDOW_PASSED)
    after = refresh_citation(citation["id"])
    assert after["abatement_deadline"] == "2026-09-15T09:00:00Z"
    assert after["abatement_extended"] is False
