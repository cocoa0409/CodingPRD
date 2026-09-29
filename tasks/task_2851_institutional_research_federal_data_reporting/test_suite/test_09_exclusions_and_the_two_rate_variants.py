"""Allowable exclusions and the two fractions they pull apart: federal adjusted against ranking gross."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    assert_cohort_conservation,
    assert_cohort_counts,
    assert_component_status,
    assert_divergence_is_difference_of_published_variants,
    assert_equals_number,
    assert_instant_equals,
    assert_null,
    assert_rate_variants,
    assert_version,
    constants as K,
    factories as f,
    fixtures as fx,
)

MEDICAL_NOTE = "Student withdrew for documented medical reasons in the second year."
DISABILITY_NOTE = "Disability services letter dated 2024-03-11 is on file for this student."
DECEASED_NOTE = "Death certificate received by the registrar on 2024-05-02."
DECEASED_FILED_NOTE = "Death certificate filed with the registrar in the tracking window."
APPROVE_NOTE = "Allowable exclusion confirmed against the federal instructions."
APPROVE_FEDERAL_NOTE = "Allowable exclusion approved under the federal instructions."
REVERSAL_NOTE = "Reversed on review: the documentation belongs to a different student record."


class TestExclusionCodeIsTheClosedFederalList:
    """A plausible institutional reason is not an allowable federal exclusion."""

    def test_a_medical_withdrawal_is_refused_while_permanent_disability_is_accepted(
        self, api, registrar, analyst
    ):
        """The refused claim leaves the member at NONE with neither code nor note stored.

        PRD 3.6: "Filing a claim requires an `exclusion_code` drawn from the closed federal list —
        `DECEASED`, `PERMANENTLY_DISABLED`, `ARMED_FORCES`, `FOREIGN_AID_SERVICE` or
        `CHURCH_MISSION`, anything else reporting `ERR_INVALID_EXCLUSION_CODE` — together with an
        `exclusion_evidence_note` of 10 to 500 characters."

        PRD 3.6: "Both variants store `exclusion_claimed_by_user_id` and increment the member's
        `version`, both require the parent cohort's cycle not to be `ARCHIVED`, and a member in any
        other exclusion state reports `ERR_INVALID_EXCLUSION_STATE`."

        Design: Corner/validations/corner_val_exclusion_code_is_the_closed_federal_list
        """
        cycle = fx.create_cycle(api, registrar)
        cohort = validate_success(
            api.create_cohort(
                cycle["id"],
                f.make_cohort_payload(
                    cohort_type=K.COHORT_GRAD_RATE_150,
                    entry_term="FALL2020",
                    publication_metric_key="GRAD_RATE_150_FALL2020",
                ),
                registrar,
            ),
            201,
        )
        member = validate_success(
            api.add_cohort_member(
                cohort["id"],
                f.make_member_payload("S001", outcome=K.OUTCOME_NO_LONGER_ENROLLED),
                registrar,
            ),
            201,
        )

        refused = api.file_exclusion_claim(
            member["id"],
            f.make_exclusion_claim_payload(
                exclusion_code="MEDICAL_WITHDRAWAL", exclusion_evidence_note=MEDICAL_NOTE
            ),
            registrar,
        )
        validate_error(refused, ApiErrorId.INVALID_EXCLUSION_CODE, 422)

        untouched = validate_success(api.get_cohort_member(member["id"], analyst))
        assert untouched["exclusion_status"] == K.EXCLUSION_NONE
        assert_null(untouched["exclusion_code"], "member.exclusion_code")
        assert_null(untouched["exclusion_evidence_note"], "member.exclusion_evidence_note")
        assert_version(untouched, 1, "member")

        claimed = validate_success(
            api.file_exclusion_claim(
                member["id"],
                f.make_exclusion_claim_payload(
                    exclusion_code=K.EXCLUSION_CODE_PERMANENTLY_DISABLED,
                    exclusion_evidence_note=DISABILITY_NOTE,
                ),
                registrar,
            )
        )
        assert claimed["exclusion_status"] == K.EXCLUSION_CLAIMED
        assert claimed["exclusion_code"] == K.EXCLUSION_CODE_PERMANENTLY_DISABLED
        assert claimed["exclusion_claimed_by_user_id"] == "registrar-1"
        assert_version(claimed, 2, "member")

        priced = validate_success(api.get_cohort(cohort["id"], analyst))
        assert_cohort_counts(priced, initial_count=1, exclusion_count=0, adjusted_count=1)
        assert_cohort_conservation(priced)


class TestDenominatorAndInputSufficiency:
    """One priority band holds three different emptinesses, each with its own code."""

    def test_an_empty_roster_a_metricless_component_and_a_fully_excluded_cohort_all_report_distinctly(
        self, api, registrar, director, analyst
    ):
        """The fully excluded cohort still publishes a ranking rate of 100.0 from its raw roster.

        PRD 3.6: "The last two conditions are distinct failures with distinct errors: a cohort of ten
        students, all of whose exclusions were approved, has a non-zero `initial_count` and a zero
        `adjusted_count`, so it passes the emptiness test and fails the denominator test."

        PRD 3.3: "Four preconditions guard it: the component must be `DRAFT`; the parent cycle's
        posture must be `CENSUS_LOCKED` or `REOPENED`, because the census-date snapshot rule permits
        preparation only from a census-locked extract, and anything else reports
        `ERR_INVALID_CYCLE_STATE`; the referenced extract's `status` must be `ACTIVE` or `LOCKED`, and
        a `SUPERSEDED` extract reports `ERR_FROZEN_FILE_SUPERSEDED`; and at least one component
        metric must exist, failing which the run reports `ERR_NO_METRICS`."

        PRD 3.6: "When `adjusted_count` is 0 the rate is null; otherwise it is the numerator divided
        by the denominator, multiplied by 100, rounded half up to one decimal place."

        Design: Corner/validations/corner_val_denominator_sufficiency_blocks_empty_and_fully_excluded_cohorts
        """
        scenario = fx.component_on_locked_cycle(
            api, metrics=(), checksum="c1d2e3f4a5b60146"
        )
        fx.cohort_on_scenario(
            api,
            scenario,
            cohort_type=K.COHORT_GRAD_RATE_150,
            entry_term="FALL2020",
            publication_metric_key="GRAD_RATE_150_FALL2020",
        )

        empty_lock = api.lock_cohort(scenario.cohort_id, registrar)
        validate_error(empty_lock, ApiErrorId.EMPTY_COHORT, 422)
        still_draft = validate_success(api.get_cohort(scenario.cohort_id, analyst))
        assert still_draft["status"] == K.COHORT_DRAFT
        assert_version(still_draft, 1, "cohort")

        metricless = api.prepare_component(scenario.component_id, analyst)
        validate_error(metricless, ApiErrorId.NO_METRICS, 422)
        held = validate_success(api.get_survey_component(scenario.component_id, analyst))
        assert_component_status(held, prep_status=K.PREP_DRAFT, edit_status=K.EDIT_NOT_RUN)

        member = validate_success(
            api.add_cohort_member(
                scenario.cohort_id,
                f.make_member_payload("S001", outcome=K.OUTCOME_COMPLETED_150),
                registrar,
            ),
            201,
        )
        validate_success(
            api.file_exclusion_claim(
                member["id"],
                f.make_exclusion_claim_payload(
                    exclusion_code=K.EXCLUSION_CODE_DECEASED,
                    exclusion_evidence_note=DECEASED_NOTE,
                ),
                registrar,
            )
        )
        validate_success(
            api.review_exclusion_claim(
                member["id"],
                f.make_exclusion_review_payload(K.DECISION_APPROVE, APPROVE_NOTE),
                director,
            )
        )

        hollow = validate_success(api.get_cohort(scenario.cohort_id, analyst))
        assert_cohort_counts(hollow, initial_count=1, exclusion_count=1, adjusted_count=0)
        assert_null(hollow["federal_rate_pct"], "cohort.federal_rate_pct")
        assert_rate_variants(hollow, ranking_rate_pct=100.0)
        assert_cohort_conservation(hollow)

        no_denominator = api.lock_cohort(scenario.cohort_id, registrar)
        validate_error(no_denominator, ApiErrorId.EMPTY_COHORT_DENOMINATOR, 422)

        validate_success(
            api.review_exclusion_claim(
                member["id"],
                f.make_exclusion_review_payload(K.DECISION_DENY, REVERSAL_NOTE),
                director,
            )
        )
        restored = validate_success(api.get_cohort(scenario.cohort_id, analyst))
        assert_cohort_counts(restored, exclusion_count=0, adjusted_count=1)
        assert_rate_variants(restored, federal_rate_pct=100.0)

        locked = validate_success(api.lock_cohort(scenario.cohort_id, registrar))
        assert locked["status"] == K.COHORT_LOCKED
        assert_instant_equals(locked["locked_at"], K.CLOCK_AFTER_CENSUS_ECHO, "cohort.locked_at")

        summary = validate_success(api.get_cohort_rate_summary(scenario.cohort_id, analyst))
        assert_rate_variants(summary, federal_rate_pct=100.0)
        assert_cohort_counts(summary, adjusted_count=1)


class TestRateSummaryIsAComputedRead:
    """The summary adds the divergence that lives on no entity and agrees on everything else."""

    def test_the_summary_reports_a_divergence_the_cohort_row_does_not_store(
        self, api, registrar, director
    ):
        """Federal 66.7 over the adjusted three, ranking 50.0 over the raw four, gap 16.7.

        PRD 3.6: "The divergence between them, `rate_divergence_pp`, is reported in percentage points
        as the federal rate minus the ranking rate, rounded half up to one decimal place."

        PRD 3.6: "A computed read exposes both variants side by side together with
        `rate_divergence_pp` and the five headcounts they were derived from."

        Design: Corner/endpoints/corner_ep_rate_summary_is_a_computed_read_that_matches_the_stored_variants
        """
        cycle = fx.create_cycle(api, registrar)
        cohort = validate_success(
            api.create_cohort(
                cycle["id"],
                f.make_cohort_payload(
                    cohort_type=K.COHORT_GRAD_RATE_150,
                    entry_term="FALL2020",
                    publication_metric_key="GRAD_RATE_150_FALL2020",
                ),
                registrar,
            ),
            201,
        )
        seated = fx.add_members(
            api,
            cohort["id"],
            fx.roster_of(
                K.OUTCOME_COMPLETED_150,
                K.OUTCOME_COMPLETED_150,
                K.OUTCOME_STILL_ENROLLED,
                K.OUTCOME_NO_LONGER_ENROLLED,
            ),
        )
        fourth = seated[3]

        validate_success(
            api.file_exclusion_claim(
                fourth["id"],
                f.make_exclusion_claim_payload(
                    exclusion_code=K.EXCLUSION_CODE_DECEASED,
                    exclusion_evidence_note=DECEASED_FILED_NOTE,
                ),
                registrar,
            )
        )
        validate_success(
            api.review_exclusion_claim(
                fourth["id"],
                f.make_exclusion_review_payload(K.DECISION_APPROVE, APPROVE_FEDERAL_NOTE),
                director,
            )
        )

        summary = validate_success(api.get_cohort_rate_summary(cohort["id"], director))
        assert_cohort_counts(
            summary,
            initial_count=4,
            exclusion_count=1,
            adjusted_count=3,
            completers_count=2,
            retained_count=3,
        )
        assert_rate_variants(summary, federal_rate_pct=66.7, ranking_rate_pct=50.0)
        assert_equals_number(summary["rate_divergence_pp"], 16.7, "rate_divergence_pp")
        assert_divergence_is_difference_of_published_variants(summary)
        assert_cohort_conservation(summary, "rate summary")

        stored = validate_success(api.get_cohort(cohort["id"], director))
        assert_rate_variants(stored, federal_rate_pct=66.7, ranking_rate_pct=50.0)


DECEASED_2021_NOTE = "Death certificate on file, dated 2021-03-04."
DOCUMENTARY_APPROVAL = "Allowable exclusion approved on documentary evidence."
COMPLETER_APPROVAL = "Allowable exclusion approved although the student completed."
ARMED_FORCES_FILED = "Active-duty orders filed with the registrar on 2026-10-02."
ORDERS_VERIFIED = "Orders verified; allowable exclusion approved."
ORDERS_POSTDATE = "Orders postdate the 150 percent completion window; exclusion withdrawn."
FOREIGN_AID_NOTE = "Peace Corps service dates confirmed by the placement agency."
SECOND_APPROVAL = "Service dates verified on the second filing; exclusion approved."
SECOND_DENIAL = "Second review reverses the approval; the service falls outside the window."


class TestTheTwoVariantsDivergeOnOneApprovedExclusion:
    """One approval moves one denominator and leaves the other, so the two figures split."""

    @staticmethod
    def _five_member_cohort(api, registrar, checksum, claim_on, exclusion_code, evidence_note):
        """Five students — three completers and two still enrolled — with one claim pending."""
        scenario = fx.cohort_with_roster(
            api,
            fx.roster_of(
                K.OUTCOME_COMPLETED_150,
                K.OUTCOME_COMPLETED_150,
                K.OUTCOME_COMPLETED_150,
                K.OUTCOME_STILL_ENROLLED,
                K.OUTCOME_STILL_ENROLLED,
            ),
            record_count=5,
            checksum=checksum,
            cohort_type=K.COHORT_GRAD_RATE_150,
            entry_term="FALL2020",
            publication_metric_key="GRAD_RATE_150_FALL2020",
        )
        target = scenario.member(claim_on)
        claimed = validate_success(
            api.file_exclusion_claim(
                target["id"],
                f.make_exclusion_claim_payload(
                    exclusion_code=exclusion_code, exclusion_evidence_note=evidence_note
                ),
                registrar,
            )
        )
        assert claimed["exclusion_status"] == K.EXCLUSION_CLAIMED
        assert_version(claimed, 2, "member")
        return scenario, target["id"]

    def test_excluding_a_non_completer_lifts_the_federal_variant_fifteen_points_clear(
        self, api, registrar, director, analyst
    ):
        """Federal 3/4 and ranking 3/5 come from one roster, and the cohort never leaves DRAFT.

        PRD 3.6: "Its numerator counts members whose `exclusion_status` is not `APPROVED` and whose
        `outcome` is `COMPLETED_150` for a `GRAD_RATE_150` cohort, or whose `outcome` is
        `COMPLETED_150` or `STILL_ENROLLED` for a `RETENTION_FT` cohort."

        PRD 3.6: "Its numerator is `completers_count` for a `GRAD_RATE_150` cohort and
        `retained_count` for a `RETENTION_FT` cohort — note that these counts include members whose
        exclusion was approved."

        PRD 3.6: "A decision on a `DRAFT` cohort recomputes the counts and rates and stops there —
        nothing is published yet, so nothing needs restating."

        Design: Difficulty/dual_variant_calc/cohort_rate_federal_adjusted_vs_ranking_gross_diverge_15pp
        """
        scenario, member_id = self._five_member_cohort(
            api,
            registrar,
            "a1b2c3d4e5f60001",
            "S005",
            K.EXCLUSION_CODE_DECEASED,
            DECEASED_2021_NOTE,
        )

        approved = validate_success(
            api.review_exclusion_claim(
                member_id,
                f.make_exclusion_review_payload(K.DECISION_APPROVE, DOCUMENTARY_APPROVAL),
                director,
            )
        )
        assert approved["exclusion_status"] == K.EXCLUSION_APPROVED
        assert approved["exclusion_reviewed_by_user_id"] == "director-1"

        stored = validate_success(api.get_cohort(scenario.cohort_id, analyst))
        assert_cohort_counts(
            stored,
            initial_count=5,
            exclusion_count=1,
            adjusted_count=4,
            completers_count=3,
            retained_count=5,
        )
        assert_rate_variants(stored, federal_rate_pct=75.0, ranking_rate_pct=60.0)
        assert stored["status"] == K.COHORT_DRAFT
        assert_cohort_conservation(stored)

        summary = validate_success(api.get_cohort_rate_summary(scenario.cohort_id, analyst))
        assert_rate_variants(summary, federal_rate_pct=75.0, ranking_rate_pct=60.0)
        assert_equals_number(summary["rate_divergence_pp"], 15.0, "rate_divergence_pp")
        assert_cohort_counts(summary, retained_count=5)
        assert_divergence_is_difference_of_published_variants(summary)

    def test_excluding_a_completer_drives_the_federal_variant_below_the_ranking_one(
        self, api, registrar, director, analyst
    ):
        """The same approval on a completer strips the numerator only on the federal side.

        PRD 3.6: "The **federal adjusted rate**, exposed as `federal_rate_pct`, removes approved
        exclusions from *both* sides."

        PRD 3.6: "The **ranking gross rate**, exposed as `ranking_rate_pct`, applies no exclusion
        filter at all, because ranking and consortium surveys forbid exclusion adjustments."

        PRD 3.6: "The divergence between them, `rate_divergence_pp`, is reported in percentage points
        as the federal rate minus the ranking rate, rounded half up to one decimal place."

        Design: Difficulty/dual_variant_calc/cohort_rate_federal_adjusted_vs_ranking_gross_diverge_15pp
        """
        scenario, member_id = self._five_member_cohort(
            api,
            registrar,
            "a1b2c3d4e5f60002",
            "S003",
            K.EXCLUSION_CODE_DECEASED,
            DECEASED_2021_NOTE,
        )

        before = validate_success(api.get_cohort_rate_summary(scenario.cohort_id, analyst))
        assert_rate_variants(before, federal_rate_pct=60.0, ranking_rate_pct=60.0)
        assert_equals_number(before["rate_divergence_pp"], 0.0, "rate_divergence_pp")

        validate_success(
            api.review_exclusion_claim(
                member_id,
                f.make_exclusion_review_payload(K.DECISION_APPROVE, COMPLETER_APPROVAL),
                director,
            )
        )

        stored = validate_success(api.get_cohort(scenario.cohort_id, analyst))
        assert_cohort_counts(
            stored,
            initial_count=5,
            exclusion_count=1,
            adjusted_count=4,
            completers_count=3,
            retained_count=5,
        )
        assert_rate_variants(stored, federal_rate_pct=50.0, ranking_rate_pct=60.0)
        assert_cohort_conservation(stored)

        summary = validate_success(api.get_cohort_rate_summary(scenario.cohort_id, analyst))
        assert_rate_variants(summary, federal_rate_pct=50.0, ranking_rate_pct=60.0)
        assert_equals_number(summary["rate_divergence_pp"], -10.0, "rate_divergence_pp")
        assert_divergence_is_difference_of_published_variants(summary)


class TestDenyingAnApprovalIsACompensatingAction:
    """The recomputation is total, so reversing an approval lands on the pre-approval figures."""

    @staticmethod
    def _claim_pending_on_the_fifth_student(api, registrar, checksum):
        """Three completers, two still enrolled, and an ARMED_FORCES claim on S005."""
        scenario = fx.cohort_with_roster(
            api,
            fx.roster_of(
                K.OUTCOME_COMPLETED_150,
                K.OUTCOME_COMPLETED_150,
                K.OUTCOME_COMPLETED_150,
                K.OUTCOME_STILL_ENROLLED,
                K.OUTCOME_STILL_ENROLLED,
            ),
            record_count=5,
            checksum=checksum,
            cohort_type=K.COHORT_GRAD_RATE_150,
            entry_term="FALL2020",
            publication_metric_key="GRAD_RATE_150_FALL2020",
        )
        opening = validate_success(api.get_cohort_rate_summary(scenario.cohort_id, registrar))
        assert_rate_variants(opening, federal_rate_pct=60.0, ranking_rate_pct=60.0)

        fifth = scenario.member("S005")
        claimed = validate_success(
            api.file_exclusion_claim(
                fifth["id"],
                f.make_exclusion_claim_payload(
                    exclusion_code=K.EXCLUSION_CODE_ARMED_FORCES,
                    exclusion_evidence_note=ARMED_FORCES_FILED,
                ),
                registrar,
            )
        )
        assert_version(claimed, 2, "member")
        return scenario, fifth["id"]

    def test_the_denial_of_an_approval_restores_both_counts_and_both_rates_exactly(
        self, api, registrar, director, analyst
    ):
        """4 + 1 == 5 becomes 5 + 0 == 5 and the federal rate returns to exactly 60.0.

        PRD 3.6: "A conservation identity holds after every membership creation and every exclusion
        decision: `adjusted_count` plus `exclusion_count` always equals `initial_count`."

        PRD 3.6: "`CLAIMED → APPROVED` on an approval, `CLAIMED → DENIED` on a denial, and
        `APPROVED → DENIED` on a denial of an already-approved exclusion, which is the compensating
        action that reverses an approval."

        PRD 3.6: "The three differ in what actually moves: an approval adds the member to
        `exclusion_count` and removes it from `adjusted_count`; a denial of a claim moves neither
        count, because a merely `CLAIMED` member had never entered `exclusion_count`; and a denial of
        an approval decreases `exclusion_count` by one and increases `adjusted_count` by one,
        restoring both rates to their pre-approval values exactly."

        Design: Difficulty/compensating_invariant/exclusion_approve_then_deny_restores_cohort_counts_and_rates
        """
        scenario, member_id = self._claim_pending_on_the_fifth_student(
            api, registrar, "a1b2c3d4e5f60022"
        )

        validate_success(
            api.review_exclusion_claim(
                member_id,
                f.make_exclusion_review_payload(K.DECISION_APPROVE, ORDERS_VERIFIED),
                director,
            )
        )
        adjusted = validate_success(api.get_cohort(scenario.cohort_id, analyst))
        assert_cohort_counts(
            adjusted, initial_count=5, exclusion_count=1, adjusted_count=4, completers_count=3
        )
        assert_rate_variants(adjusted, federal_rate_pct=75.0, ranking_rate_pct=60.0)
        assert_cohort_conservation(adjusted)

        reversed_member = validate_success(
            api.review_exclusion_claim(
                member_id,
                f.make_exclusion_review_payload(K.DECISION_DENY, ORDERS_POSTDATE),
                director,
            )
        )
        assert reversed_member["exclusion_status"] == K.EXCLUSION_DENIED
        assert reversed_member["review_note"] == ORDERS_POSTDATE

        restored = validate_success(api.get_cohort(scenario.cohort_id, analyst))
        assert_cohort_counts(
            restored,
            initial_count=5,
            exclusion_count=0,
            adjusted_count=5,
            completers_count=3,
            retained_count=5,
        )
        assert_rate_variants(restored, federal_rate_pct=60.0, ranking_rate_pct=60.0)
        assert_cohort_conservation(restored)

        summary = validate_success(api.get_cohort_rate_summary(scenario.cohort_id, analyst))
        assert_equals_number(summary["rate_divergence_pp"], 0.0, "rate_divergence_pp")
        assert_cohort_conservation(summary, "rate summary")
        assert_divergence_is_difference_of_published_variants(summary)

    def test_a_refiled_claim_walks_the_same_figures_out_and_back_a_second_time(
        self, api, registrar, director, analyst
    ):
        """A refiling replaces the code and the note yet moves no count until it is approved.

        PRD 3.6: "It drives `NONE → CLAIMED` for a first filing and `DENIED → CLAIMED` for a refiling
        with new evidence, in which case the code and the note are replaced."

        PRD 3.6: "Because the recomputation is total rather than incremental, no drift can accumulate:
        an exclusion that is approved, refiled and then denied restores `adjusted_count`,
        `exclusion_count`, `federal_rate_pct` and `ranking_rate_pct` to the exact values they held
        before the approval."

        Design: Difficulty/compensating_invariant/exclusion_approve_then_deny_restores_cohort_counts_and_rates
        """
        scenario, member_id = self._claim_pending_on_the_fifth_student(
            api, registrar, "a1b2c3d4e5f60023"
        )

        first_approval = validate_success(
            api.review_exclusion_claim(
                member_id,
                f.make_exclusion_review_payload(K.DECISION_APPROVE, ORDERS_VERIFIED),
                director,
            )
        )
        assert_version(first_approval, 3, "member")
        assert_rate_variants(
            validate_success(api.get_cohort(scenario.cohort_id, analyst)),
            federal_rate_pct=75.0,
            ranking_rate_pct=60.0,
        )

        first_denial = validate_success(
            api.review_exclusion_claim(
                member_id,
                f.make_exclusion_review_payload(K.DECISION_DENY, ORDERS_POSTDATE),
                director,
            )
        )
        assert first_denial["exclusion_status"] == K.EXCLUSION_DENIED
        assert_version(first_denial, 4, "member")

        refiled = validate_success(
            api.file_exclusion_claim(
                member_id,
                f.make_exclusion_claim_payload(
                    exclusion_code=K.EXCLUSION_CODE_FOREIGN_AID_SERVICE,
                    exclusion_evidence_note=FOREIGN_AID_NOTE,
                ),
                registrar,
            )
        )
        assert refiled["exclusion_status"] == K.EXCLUSION_CLAIMED
        assert refiled["exclusion_code"] == K.EXCLUSION_CODE_FOREIGN_AID_SERVICE
        assert refiled["exclusion_evidence_note"] == FOREIGN_AID_NOTE
        assert_version(refiled, 5, "member")

        pending = validate_success(api.get_cohort(scenario.cohort_id, analyst))
        assert_cohort_counts(pending, initial_count=5, exclusion_count=0, adjusted_count=5)
        assert_rate_variants(pending, federal_rate_pct=60.0, ranking_rate_pct=60.0)

        second_approval = validate_success(
            api.review_exclusion_claim(
                member_id,
                f.make_exclusion_review_payload(K.DECISION_APPROVE, SECOND_APPROVAL),
                director,
            )
        )
        assert second_approval["exclusion_status"] == K.EXCLUSION_APPROVED
        assert_version(second_approval, 6, "member")
        readjusted = validate_success(api.get_cohort(scenario.cohort_id, analyst))
        assert_cohort_counts(readjusted, exclusion_count=1, adjusted_count=4)
        assert_rate_variants(readjusted, federal_rate_pct=75.0, ranking_rate_pct=60.0)
        assert_cohort_conservation(readjusted)

        second_denial = validate_success(
            api.review_exclusion_claim(
                member_id,
                f.make_exclusion_review_payload(K.DECISION_DENY, SECOND_DENIAL),
                director,
            )
        )
        assert second_denial["exclusion_status"] == K.EXCLUSION_DENIED
        assert_version(second_denial, 7, "member")

        settled = validate_success(api.get_cohort_rate_summary(scenario.cohort_id, analyst))
        assert_cohort_counts(settled, initial_count=5, exclusion_count=0, adjusted_count=5)
        assert_rate_variants(settled, federal_rate_pct=60.0, ranking_rate_pct=60.0)
        assert_equals_number(settled["rate_divergence_pp"], 0.0, "rate_divergence_pp")
        assert_cohort_conservation(settled, "rate summary")
