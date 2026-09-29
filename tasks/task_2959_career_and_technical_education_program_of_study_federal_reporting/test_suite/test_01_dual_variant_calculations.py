"""The two dual-variant calculations of the CTE service.

The alignment index is computed once when a district submits a program and again
when the state approves it, and the performance actual is recomputed on every
read of an indicator and once more when the reporting year closes. Both pairs
read the same stored rows and legitimately publish different answers, so each
scenario below builds one body of data and then observes both variants over it.
"""

from test_helpers import (
    Builder,
    CteApiClient,
    assert_cohort_figures,
    assert_alignment_index,
    assert_credit_totals,
    assert_pct,
    f,
    k,
    quantized,
    users,
    validate_unpaginated,
)

# --- Curriculum straddling the two alignment include sets -------------------
ALIGNMENT_CIP = "47.0604"
ALIGNMENT_NARRATIVE_URL = "https://district.example/pos/47-0604/narrative.pdf"
CLNA_MEETING_ONE = "2026-08-04T14:00:00.000Z"
CLNA_MEETING_TWO = "2026-08-05T14:00:00.000Z"
ENDORSEMENT_MEETING = "2026-08-10T15:00:00.000Z"

# --- A four-student cohort, one below the federal minimum -------------------
SMALL_COHORT_CIP = "51.3902"
FIRST_STATE_STUDENT_ID = 100000001
COHORT_SIZE = 4
OFFERED_LEVEL_PCT = 44.44
BASELINE_PCT = 60.0
CLOSE_DATE = "2027-09-30"


def _mixed_status_sequence(build: Builder):
    """Author a program whose four courses straddle both include sets.

    Two secondary courses carry 2.50 ACTIVE and 1.00 DRAFT credit hours, and two
    postsecondary courses carry 3.00 credit hours each with 3.00 articulated —
    the ACTIVE one countersigned, the DRAFT one not. The program reaches a
    certified needs assessment with an endorsing committee seated behind it.
    """
    program = build.create_program(
        ALIGNMENT_CIP,
        title="Automotive Technology",
        cluster=k.CLUSTER_ADVANCED_MANUFACTURING,
        labor_market_data_asof="2026-03-01",
    )
    program_id = program["id"]
    secondary_active = build.add_course(
        program_id,
        f.secondary_course(
            "SEC-A", 1, 2.5, title="Intro to Automotive Systems", status=k.COURSE_ACTIVE
        ),
    )
    build.add_course(
        program_id,
        f.secondary_course(
            "SEC-B",
            2,
            1.0,
            title="Automotive Electrical",
            status=k.COURSE_DRAFT,
            prerequisite_course_id=secondary_active["id"],
        ),
    )
    postsecondary_active = build.add_course(
        program_id,
        f.postsecondary_course(
            "PS-A",
            3,
            3.0,
            3.0,
            True,
            title="Dual-Credit Powertrain",
            status=k.COURSE_ACTIVE,
            prerequisite_course_id=secondary_active["id"],
        ),
    )
    build.add_course(
        program_id,
        f.postsecondary_course(
            "PS-B",
            4,
            3.0,
            3.0,
            False,
            title="Dual-Credit Diagnostics",
            status=k.COURSE_DRAFT,
            prerequisite_course_id=postsecondary_active["id"],
        ),
    )
    build.add_credential(program_id, "ASE-G1", tier=k.TIER_NATIONAL)
    educator = build.add_educator(
        program_id, full_name="Dana Ortiz", claimed_industry_hours=4200
    )
    build.verify_hours(educator["id"], 4200)
    committee_row = build.charter_committee(program_id)
    committee = build.seat_roster(committee_row["id"])
    build.quorate_meeting(committee, k.AGENDA_CLNA_STAKEHOLDER, CLNA_MEETING_ONE)
    build.quorate_meeting(committee, k.AGENDA_CLNA_STAKEHOLDER, CLNA_MEETING_TWO)
    build.certify_clna(program_id)
    return program_id, committee


def _submit_program(api: CteApiClient, program_id: str):
    """Submit the packet as the authoring director and return the program row."""
    return validate_unpaginated(
        api.submit_program(
            program_id,
            f.submit_payload(ALIGNMENT_NARRATIVE_URL),
            users.headers(users.DIRECTOR),
        ),
        200,
    )


def _approve_program(api: CteApiClient, build: Builder, program_id: str, committee):
    """File a passing endorsement, then grant state approval."""
    build.quorate_meeting(committee, k.AGENDA_POS_ENDORSEMENT, ENDORSEMENT_MEETING)
    return validate_unpaginated(
        api.state_approve(
            program_id,
            f.state_approve_payload(approval_note="Aligned sequence verified."),
            users.headers(users.REVIEWER),
        ),
        200,
    )


def _small_cohort_indicator(build: Builder):
    """Enroll four concentrators, one of them credentialed, behind an indicator.

    Every student earns exactly 2.00 credit hours in the program's ACTIVE
    secondary course, and exactly one of them holds a verified attainment of the
    program's NATIONAL credential.
    """
    program = build.create_program(
        SMALL_COHORT_CIP,
        title="Practical Nursing",
        cluster=k.CLUSTER_HEALTH_SCIENCE,
        labor_market_data_asof="2026-03-01",
    )
    program_id = program["id"]
    course = build.add_course(
        program_id,
        f.secondary_course(
            "NUR-1", 1, 2.5, title="Nursing Fundamentals", status=k.COURSE_ACTIVE
        ),
    )
    credential = build.add_credential(
        program_id, "CNA-ST", tier=k.TIER_NATIONAL, exam_required=False
    )
    students = []
    for offset in range(COHORT_SIZE):
        student = build.enroll(
            program_id, str(FIRST_STATE_STUDENT_ID + offset), cohort_year=2026
        )
        build.post_credit(student["id"], course["id"], 2.0, posted_on="2026-07-15")
        students.append(student)
    build.attain(
        students[0]["id"],
        credential["id"],
        attained_on="2026-07-20",
        verification_status=k.VERIFICATION_VERIFIED,
        exam_score=f.UNSET,
    )
    indicator = build.agreed_indicator(
        program_id,
        k.INDICATOR_4S1_CREDENTIAL,
        OFFERED_LEVEL_PCT,
        reporting_year=2027,
        baseline_pct=BASELINE_PCT,
        cohort_year=2026,
    )
    return program_id, indicator


class TestAlignmentIndexVariants:
    """One curriculum, two include sets, two published bridge scores."""

    def test_submission_publishes_the_provisional_local_bridge_score(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.4: "An accepted submission increments `approval_round` by 1 — the counter is the district's audit trail of how many times the packet has gone up — writes the supplied `narrative_url` onto the program, clears `open_finding_codes` back to an empty list, and recomputes the alignment index under the `PROVISIONAL_LOCAL` variant, writing `alignment_index`, setting `alignment_index_variant` to `PROVISIONAL_LOCAL`, and refreshing `secondary_credit_total`, `postsecondary_credit_total` and `articulated_credit_total`."

        PRD §3.1: "Under the `PROVISIONAL_LOCAL` variant the include set is courses whose `status` is `DRAFT` or `ACTIVE`, and the articulated sum ignores `articulation_verified` entirely, counting every qualifying postsecondary course's `articulated_credit_hours`."

        PRD §3.1: "The **depth factor** is the smaller of 1.0 and the secondary credit subtotal divided by the four credit hours of secondary coursework a full pathway is expected to carry. The **bridge factor** is the smaller of 1.0 and the articulated subtotal divided by the larger of 1.0 and the postsecondary credit subtotal — the denominator floor of 1.0 keeps the factor finite when the postsecondary side is empty. The **breadth bonus** is 0.10 when the secondary credit subtotal is greater than zero, the postsecondary credit subtotal is greater than zero, and the articulated subtotal is at least the three articulated credit hours that mark a genuine dual-credit bridge; otherwise the bonus is 0.0. The weighted combination is then formed by multiplying the depth factor by 0.60, multiplying the bridge factor by 0.30, and adding the breadth bonus. That sum is clamped to at most 1.0, and the clamped value is rounded half-up to four decimal places exactly once."

        Design: Difficulty/dual_variant_calc/alignment_index_provisional_local_vs_federal_certified
        """
        program_id, _committee = _mixed_status_sequence(build)

        submitted = _submit_program(api, program_id)

        assert submitted["alignment_index_variant"] == k.ALIGNMENT_VARIANT_PROVISIONAL_LOCAL
        assert_alignment_index(submitted["alignment_index"], 0.9250)

    def test_submission_stores_the_draft_inclusive_credit_subtotals(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.1: "Given the variant's include set, the evaluation proceeds in a fixed order. Three sums are taken first: the secondary credit subtotal is the sum of `credit_hours` over the program's courses whose `segment` is `SECONDARY` and whose `status` is in the include set; the postsecondary credit subtotal is the same sum over courses whose `segment` is `POSTSECONDARY` and whose `status` is in the include set; and the articulated subtotal is the sum of `articulated_credit_hours` over courses whose `segment` is `POSTSECONDARY`, whose `status` is in the include set, and which satisfy the variant's articulation restriction. Those three sums are what get stored as `secondary_credit_total`, `postsecondary_credit_total` and `articulated_credit_total`."

        PRD §3.1: "Under the `PROVISIONAL_LOCAL` variant the include set is courses whose `status` is `DRAFT` or `ACTIVE`, and the articulated sum ignores `articulation_verified` entirely, counting every qualifying postsecondary course's `articulated_credit_hours`."

        Design: Difficulty/dual_variant_calc/alignment_index_provisional_local_vs_federal_certified
        """
        program_id, _committee = _mixed_status_sequence(build)

        submitted = _submit_program(api, program_id)

        assert_credit_totals(submitted, 3.50, 6.00, 6.00)

    def test_state_approval_republishes_the_federal_certified_bridge_score(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.1: "Under the `FEDERAL_CERTIFIED` variant the include set is courses whose `status` is `ACTIVE` only, and the articulated sum counts a postsecondary course's `articulated_credit_hours` solely when that course's `articulation_verified` is true."

        PRD §3.4: "State approval then does four things. It overwrites `alignment_index` with the `FEDERAL_CERTIFIED` result, sets `alignment_index_variant` to `FEDERAL_CERTIFIED`, and overwrites all three credit subtotals with that variant's sums. It sets `federal_reporting_eligible` to true — this flag is true exactly while `approval_status` is `STATE_APPROVED`, and it is what determines whether the program appears in the federal Perkins submission."

        Design: Difficulty/dual_variant_calc/alignment_index_provisional_local_vs_federal_certified
        """
        program_id, committee = _mixed_status_sequence(build)
        _submit_program(api, program_id)

        approved = _approve_program(api, build, program_id, committee)

        assert approved["approval_status"] == k.APPROVAL_STATE_APPROVED
        assert approved["federal_reporting_eligible"] is True
        assert approved["alignment_index_variant"] == k.ALIGNMENT_VARIANT_FEDERAL_CERTIFIED
        assert_alignment_index(approved["alignment_index"], 0.7750)
        assert_credit_totals(approved, 2.50, 3.00, 3.00)

    def test_federal_certified_score_sits_exactly_below_the_provisional_one(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.1: "Identical curriculum data therefore yields a `FEDERAL_CERTIFIED` index that is lower than or equal to the `PROVISIONAL_LOCAL` index, never higher."

        PRD §2.12: "It is expected and correct for a program's provisional index to exceed its federal-certified index, and for an indicator's `preliminary_status_projection` to read `NOT_MET` while the final scoring records `NOT_SCORED`."

        PRD §3.4: "And the alignment index recomputed under the `FEDERAL_CERTIFIED` variant must reach the federal floor of 0.7500, inclusive — an index of exactly 0.7500 passes, anything strictly below it fails with `ERR_ALIGNMENT_INDEX_BELOW_FLOOR`."

        Design: Difficulty/dual_variant_calc/alignment_index_provisional_local_vs_federal_certified
        """
        program_id, committee = _mixed_status_sequence(build)
        submitted = _submit_program(api, program_id)

        approved = _approve_program(api, build, program_id, committee)

        provisional = quantized(submitted["alignment_index"], 4)
        federal = quantized(approved["alignment_index"], 4)
        assert provisional - federal == quantized(0.1500, 4), (
            f"Expected the provisional index {provisional} to exceed the "
            f"federal-certified index {federal} by exactly 0.1500"
        )
        assert federal >= quantized(k.FEDERAL_ALIGNMENT_FLOOR, 4), (
            f"The federal-certified index {federal} must reach the federal floor"
        )


class TestSmallCohortIndicatorVariants:
    """One four-student cohort, one raw percentage, two different scorings."""

    def test_agreed_indicator_carries_the_four_student_cohort_and_its_threshold(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.8: "`denominator_count` is the number of students whose program matches the indicator's program, whose `cohort_year` matches the indicator's `cohort_year`, and whose `concentrator_status` is `CONCENTRATOR` or `COMPLETER`; a `PARTICIPANT` counts in neither the numerator nor the denominator. `numerator_count` is the number of those same students whose `verified_qualifying_attainment_count` is at least 1. `small_cohort_flag` is true exactly when `denominator_count` is below the federal minimum cohort size of 5."

        PRD §3.8: "Acceptance copies `last_offer_pct` into `negotiated_level_pct` and sets `met_threshold_pct` to that level multiplied by the federal tolerance of 0.90, rounded half-up to two decimal places."

        Design: Difficulty/dual_variant_calc/indicator_actual_preliminary_unadjusted_vs_final_small_cohort_adjusted
        """
        _program_id, indicator = _small_cohort_indicator(build)

        observed = validate_unpaginated(
            api.get_indicator(indicator["id"], users.headers(users.REVIEWER)), 200
        )

        assert observed["status"] == k.PI_AGREED
        assert_cohort_figures(observed, denominator=4, numerator=1, small_cohort=True)
        assert_pct(observed["negotiated_level_pct"], 44.44, "negotiated_level_pct")
        assert_pct(observed["met_threshold_pct"], 40.00, "met_threshold_pct")

    def test_preliminary_variant_projects_a_missed_target_on_the_raw_percentage(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.8: "The raw percentage is null when `denominator_count` is zero; otherwise it is 100 multiplied by `numerator_count`, divided by `denominator_count`, rounded half-up to two decimal places."

        PRD §3.8: "The `PRELIMINARY_UNADJUSTED` variant ignores `small_cohort_flag` completely: it publishes the raw percentage as `preliminary_actual_pct` and sets `preliminary_status_projection` to `MET` when the raw percentage is at least `met_threshold_pct`, to `NOT_MET` when it is strictly below, and to `UNDEFINED` whenever either the raw percentage or `met_threshold_pct` is null."

        Design: Difficulty/dual_variant_calc/indicator_actual_preliminary_unadjusted_vs_final_small_cohort_adjusted
        """
        _program_id, indicator = _small_cohort_indicator(build)

        observed = validate_unpaginated(
            api.get_indicator(indicator["id"], users.headers(users.REVIEWER)), 200
        )

        assert_pct(observed["preliminary_actual_pct"], 25.00, "preliminary_actual_pct")
        assert observed["preliminary_status_projection"] == k.PROJECTION_NOT_MET

    def test_closing_the_year_suppresses_the_score_of_a_small_cohort(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.8: "The `FINAL_SMALL_COHORT_ADJUSTED` variant is the only one that may persist `actual_pct` or move the indicator's `status`, and it applies the suppression: when `small_cohort_flag` is true, the indicator is scored `NOT_SCORED` and `consecutive_miss_count` is left untouched regardless of how the raw percentage compares to `met_threshold_pct`."

        PRD §3.8: "When `denominator_count` is below 5 — including the case where it is zero — the indicator is scored `NOT_SCORED`. `actual_pct` still takes the final variant's output, which is null when `denominator_count` is zero and otherwise the unsuppressed percentage, and `consecutive_miss_count` is left exactly as it was."

        Design: Difficulty/dual_variant_calc/indicator_actual_preliminary_unadjusted_vs_final_small_cohort_adjusted
        """
        _program_id, indicator = _small_cohort_indicator(build)

        closed = validate_unpaginated(
            api.close_reporting_year(
                indicator["id"],
                f.close_year_payload(CLOSE_DATE),
                users.headers(users.REVIEWER),
            ),
            200,
        )

        assert closed["status"] == k.PI_NOT_SCORED
        assert_pct(closed["actual_pct"], 25.00, "actual_pct")

    def test_suppressed_score_leaves_the_miss_counter_untouched(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.8: "The `FINAL_SMALL_COHORT_ADJUSTED` variant is the only one that may persist `actual_pct` or move the indicator's `status`, and it applies the suppression: when `small_cohort_flag` is true, the indicator is scored `NOT_SCORED` and `consecutive_miss_count` is left untouched regardless of how the raw percentage compares to `met_threshold_pct`. Identical student data can therefore show `preliminary_status_projection` of `NOT_MET` while the closed year records `NOT_SCORED`."

        PRD §3.8: "The increment of `consecutive_miss_count` is cascade link 1, and it is that increment reaching the miss tolerance of 2 — not the close itself — that fires link 2: the indicator escalates `NOT_MET → IMPROVEMENT_REQUIRED`."

        Design: Difficulty/dual_variant_calc/indicator_actual_preliminary_unadjusted_vs_final_small_cohort_adjusted
        """
        _program_id, indicator = _small_cohort_indicator(build)

        closed = validate_unpaginated(
            api.close_reporting_year(
                indicator["id"],
                f.close_year_payload(CLOSE_DATE),
                users.headers(users.REVIEWER),
            ),
            200,
        )

        assert closed["consecutive_miss_count"] == 0, (
            "A suppressed small-cohort score must leave consecutive_miss_count at 0, "
            f"got {closed['consecutive_miss_count']}"
        )
        reread = validate_unpaginated(
            api.get_indicator(indicator["id"], users.headers(users.REVIEWER)), 200
        )
        assert reread["status"] == k.PI_NOT_SCORED
        assert reread["preliminary_status_projection"] == k.PROJECTION_NOT_MET
