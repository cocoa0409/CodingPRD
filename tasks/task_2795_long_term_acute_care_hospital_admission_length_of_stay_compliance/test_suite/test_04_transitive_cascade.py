"""
Chains that one write walks end to end.

Discharge is the deepest: a single call discharges the stay, prices a determination for it,
opens and scores a denial-risk review, and — only when that score lands in the highest band
— auto-issues a documentation query. The depth is data-dependent, so all four levels have
to be read separately from the one request.

Recombination runs the same chain backwards and fans out sideways: one fold voids a `FINAL`
determination, voids the resolved review behind it, subtracts the finalized money from the
period ledger, and decrements the referring hospital's admission count so the referral-mix
share is recomputed — two different aggregates unwound by one write.
"""

from test_helpers import (
    ANALYST_2_HEADERS,
    CLOCK_EPOCH,
    DRG_573,
    NURSE_ID,
    QUERY_RESPONSE_WINDOW_HOURS,
    SYSTEM_ACTOR,
    ClinicalStatus,
    DeterminationStatus,
    DischargeDisposition,
    MonitoringState,
    PaymentReviewStatus,
    PaymentVariant,
    QueryStatus,
    QueryType,
    ReviewOutcome,
    ReviewStatus,
    RiskBand,
    VoidReason,
    assert_cents,
    assert_hospital_posture,
    assert_instant_equals,
    assert_integer_field,
    assert_pct,
    assert_period_ledger,
    assert_stay_dimensions,
    assert_unset,
    factories,
    fixtures,
    shift_hours,
)

# ── The forward cascade ──────────────────────────────
# The stay is backdated eight days before the clock epoch and priced against the shorter
# DRG, whose average length of stay of thirteen days puts the short-stay threshold at ten.
_WOUND_ADMITTED_AT = "2026-07-24T00:00:00.000Z"
_WOUND_ESTIMATED_COST_CENTS = 1500000
_WOUND_CLINICALS = dict(
    factories.WOUND_CLINICALS, prior_acute_discharge_at="2026-07-23T12:00:00Z"
)


def _cascading_discharge(api):
    """A complex-wound stay discharged with nothing in the chart.

    The referral records only one ICU day and ten prior ventilator hours, and no weaning plan
    is ever opened, so the stay prices site-neutral. No interdisciplinary note is filed
    either, which leaves all four mandatory disciplines missing and drives the denial-risk
    score into the highest band — the condition the fourth level of the cascade depends on.
    """
    world = fixtures.build_world(api, drg_rate=dict(DRG_573))
    admission = fixtures.admitted_stay(
        api,
        world,
        clinicals=_WOUND_CLINICALS,
        expected_track="COMPLEX_WOUND",
        admitted_at=_WOUND_ADMITTED_AT,
    )
    admission.stay = fixtures.discharge(
        api,
        admission.stay_id,
        discharge_disposition=DischargeDisposition.HOME,
        estimated_cost_cents=_WOUND_ESTIMATED_COST_CENTS,
    )
    return admission


class TestDischargeCascadeFourLevels:
    """The four levels a single discharge call produces, read one at a time."""

    def test_level_one_discharges_the_stay_and_computes_its_length_of_stay_fields(self, api):
        """The discharge itself: both status dimensions and the three length-of-stay fields.

        The stay opened on 2026-07-24 and is discharged at the clock epoch of 2026-08-01,
        eight whole calendar days later, with no interruptions to net out. The short-stay
        threshold is five-sixths of this DRG's thirteen-day average, truncated rather than
        rounded, which is ten days; eight days is at or below that, so the short-stay flag is
        raised. The payment dimension moves independently of the clinical one: the stay is
        `DISCHARGED` and `PRICED` in the same response.

        PRD 3.6: "*Level one* is the discharge itself: `clinical_status` becomes `DISCHARGED`, `discharged_at` is stamped, `discharge_disposition` and `estimated_cost_cents` are stored, the three length-of-stay fields above are computed, and the stay's `version` increases by 1."
        PRD 3.6: "Alongside it, `sso_threshold_days` is computed as five-sixths of the `alos_days` of the DRG in force, rounded **down** to a whole number and never rounded to nearest."
        PRD 3.6: "The stay's `short_stay_outlier_applied` flag is then true exactly when `covered_los_days` is less than or equal to `sso_threshold_days`."

        Design: Difficulty/transitive_cascade/discharge_cascades_four_levels_to_an_auto_issued_documentation_query
        """
        admission = _cascading_discharge(api)

        assert_stay_dimensions(
            admission.stay, ClinicalStatus.DISCHARGED, PaymentReviewStatus.PRICED
        )
        assert_instant_equals(admission.stay["discharged_at"], CLOCK_EPOCH, "discharged_at")
        assert admission.stay["discharge_disposition"] == DischargeDisposition.HOME
        assert_cents(admission.stay, "estimated_cost_cents", _WOUND_ESTIMATED_COST_CENTS)
        assert_integer_field(admission.stay, "covered_los_days", 8)
        assert_integer_field(admission.stay, "sso_threshold_days", 10)
        assert admission.stay["short_stay_outlier_applied"] is True

        reread = fixtures.read_stay(api, admission.stay_id)
        assert_stay_dimensions(reread, ClinicalStatus.DISCHARGED, PaymentReviewStatus.PRICED)
        assert_integer_field(reread, "covered_los_days", 8)
        assert_integer_field(reread, "sso_threshold_days", 10)
        assert reread["short_stay_outlier_applied"] is True

    def test_level_two_prices_a_draft_determination_stamped_to_the_system(self, api):
        """The determination the cascade writes carries SYSTEM as the pricing actor.

        No analyst asked for this pricing, so `priced_by_user_id` is the literal `SYSTEM` and
        `recalculation_reason` is null. Both variants are stored regardless of which is
        selected. The standard base is the smallest of three short-stay candidates: the LTCH
        per-diem component of 3,600,000 / 13 x 8 = 2,215,385 cents after a single half-up
        rounding, 120 percent of the IPPS per diem at 400,000 x 8 x 1.20 = 3,840,000, and the
        IPPS-comparable full amount of 3,400,000. The site-neutral base is the smaller of that
        full amount and the estimated cost, which is 1,500,000. With one ICU day and no
        weaning plan the patient-level criteria fail, so the site-neutral variant is selected;
        the estimated cost sits below both outlier thresholds, so no add-on applies, and the
        percentage is 1,500,000 over the full standard amount of 3,600,000, or 41.67.

        PRD 3.6: "*Level two* follows because the stay became `DISCHARGED`: a `PaymentDetermination` is created for it with `status` `DRAFT` and `priced_by_user_id` set to the literal `SYSTEM` rather than to any human `X-User-ID`."
        PRD 3.7: "When the referral records a prior acute discharge and at least one intensity criterion holds, `payment_variant` is `STANDARD_LTCH_PPS`; in every other case it is `SITE_NEUTRAL`."
        PRD 3.7: "The site-neutral base is the smaller of the DRG's `ipps_comparable_full_cents` and the stay's `estimated_cost_cents`, with a null `estimated_cost_cents` treated as 0."
        PRD 3.7: "`standard_variant_amount_cents` is the standard base plus the add-on computed from the standard base."
        PRD 3.7: "Finally, `discharge_payment_pct` is `base_payment_cents` divided by `full_standard_amount_cents`, multiplied by 100 and rounded half up to two decimal places."

        Design: Difficulty/transitive_cascade/discharge_cascades_four_levels_to_an_auto_issued_documentation_query
        """
        admission = _cascading_discharge(api)

        determination = fixtures.sole_determination(api, admission.stay_id)
        assert determination["status"] == DeterminationStatus.DRAFT
        assert determination["priced_by_user_id"] == SYSTEM_ACTOR
        assert_unset(determination, "recalculation_reason", "finalized_by_user_id", "void_reason")
        assert determination["stay_id"] == admission.stay_id
        assert determination["payment_variant"] == PaymentVariant.SITE_NEUTRAL
        assert determination["drg_code_used"] == "573"
        assert_integer_field(determination, "alos_days_used", 13)
        assert_integer_field(determination, "covered_los_days_used", 8)
        assert determination["short_stay_outlier_applied"] is True
        assert_cents(determination, "full_standard_amount_cents", 3600000)
        assert_cents(determination, "standard_variant_amount_cents", 2215385)
        assert_cents(determination, "site_neutral_variant_amount_cents", 1500000)
        assert_cents(determination, "base_payment_cents", 1500000)
        assert_cents(determination, "outlier_payment_cents", 0)
        assert_cents(determination, "total_payment_cents", 1500000)
        assert_pct(determination, "discharge_payment_pct", 41.67)

        assert_pct(fixtures.read_stay(api, admission.stay_id), "discharge_payment_pct", 41.67)

    def test_level_three_opens_a_scored_review_that_lands_in_the_high_band(self, api):
        """The review the determination causes, and the score that decides the depth.

        Nothing was filed against this stay, so all four mandatory disciplines are missing,
        which is 4 x 8 = 32 points. The stay has no weaning plan at all, so the weaning gap
        contributes 15. The determination raised the short-stay flag, worth 20, and selected
        the site-neutral variant, worth 10. The length-of-stay excess is eight covered days
        less the DRG's thirteen-day average, floored at zero, so it adds nothing. The raw
        total is 77, no query has been answered, so the effective score is the as-documented
        score, and 77 is at or above 70 — the highest band. The review records the nurse whose
        discharge triggered the cascade and is not yet resolved.

        PRD 3.6: "*Level three* follows because a determination now exists: a `DenialRiskReview` is opened for the stay with `status` `OPEN`, `opened_by_user_id` recording the user whose action triggered the cascade (or `SYSTEM` where no human acted), `resolved_by_user_id` and `resolution_note` null, and its `as_documented_score`, `missing_discipline_count`, `answered_query_count`, `effective_score` and `risk_band` computed as set out in §3.8."
        PRD 3.8: "The raw total is then 8 points per missing discipline, plus 15 points if the weaning gap is present, plus 20 points if the short-stay-outlier flag is set, plus 10 points if the site-neutral flag is set, plus half a point per day of length-of-stay excess."
        PRD 3.8: "The review's `effective_score` is the `query_adjusted_score` when `answered_query_count` is greater than 0, and the `as_documented_score` otherwise."
        PRD 3.8: "`risk_band` is `HIGH` when `effective_score` is at least 70, `MODERATE` when `effective_score` is at least 40 but below 70, and `LOW` below 40."

        Design: Difficulty/transitive_cascade/discharge_cascades_four_levels_to_an_auto_issued_documentation_query
        """
        admission = _cascading_discharge(api)

        review = fixtures.sole_review(api, admission.stay_id)
        assert review["stay_id"] == admission.stay_id
        assert_integer_field(review, "missing_discipline_count", 4)
        assert_integer_field(review, "answered_query_count", 0)
        assert_integer_field(review, "as_documented_score", 77)
        assert_integer_field(review, "effective_score", 77)
        assert review["risk_band"] == RiskBand.HIGH
        assert review["opened_by_user_id"] == NURSE_ID
        assert_unset(review, "resolved_by_user_id", "resolution_note")

        reread = fixtures.read_review(api, review["id"])
        assert_integer_field(reread, "as_documented_score", 77)
        assert reread["risk_band"] == RiskBand.HIGH
        assert reread["status"] == ReviewStatus.QUERIES_ISSUED

    def test_level_four_auto_issues_one_idt_participation_query_for_the_high_band(self, api):
        """The fourth level exists only because the third level scored HIGH.

        A band of `HIGH` is the whole condition for this level, so the same discharge that
        produced a `MODERATE` review would have stopped at three levels. Here exactly one
        query is auto-issued against the review, of type `IDT_PARTICIPATION`, with
        `issued_by_user_id` the literal `SYSTEM` rather than the discharging nurse, and the
        review moves out of `OPEN` into `QUERIES_ISSUED`. The query is stamped from the same
        logical instant as the discharge, so `issued_at` reads 2026-08-01T00:00:00.000Z and
        `due_at` is that instant plus seventy-two hours, 2026-08-04T00:00:00.000Z. Nothing has
        answered it yet, so its response fields are all null.

        PRD 3.6: "*Level four* follows only when that review's `risk_band` came out `HIGH`: a `DocumentationQuery` with `query_type` `IDT_PARTICIPATION` is auto-issued against the review with `issued_by_user_id` set to the literal `SYSTEM`, and the review moves `OPEN → QUERIES_ISSUED`."
        PRD 3.8: "The new query carries `denial_risk_review_id` naming the issuing review and `stay_id` copied from that review for direct filtering, enters `status` `ISSUED` with `issued_at` stamped from the logical clock and `due_at` computed as `issued_at` plus 72 hours — three full days — and records the acting nurse's `X-User-ID` as `issued_by_user_id`."

        Design: Difficulty/transitive_cascade/discharge_cascades_four_levels_to_an_auto_issued_documentation_query
        """
        admission = _cascading_discharge(api)
        review = fixtures.sole_review(api, admission.stay_id)
        assert review["risk_band"] == RiskBand.HIGH
        assert review["status"] == ReviewStatus.QUERIES_ISSUED

        queries = fixtures.queries_of(api, denial_risk_review_id=review["id"])
        assert len(queries) == 1, "expected exactly one auto-issued query, got {}".format(
            len(queries)
        )
        query = queries[0]

        assert query["status"] == QueryStatus.ISSUED
        assert query["query_type"] == QueryType.IDT_PARTICIPATION
        assert query["issued_by_user_id"] == SYSTEM_ACTOR
        assert query["denial_risk_review_id"] == review["id"]
        assert query["stay_id"] == admission.stay_id
        assert_instant_equals(query["issued_at"], CLOCK_EPOCH, "issued_at")
        assert_instant_equals(
            query["due_at"], shift_hours(CLOCK_EPOCH, QUERY_RESPONSE_WINDOW_HOURS), "due_at"
        )
        assert_unset(
            query, "response_text", "answered_at", "answered_by_physician_id", "closed_by_user_id"
        )

        reread = fixtures.read_query(api, query["id"])
        assert reread["status"] == QueryStatus.ISSUED
        assert reread["issued_by_user_id"] == SYSTEM_ACTOR

    def test_the_cascade_priced_determination_has_not_reached_the_period_ledger(self, api):
        """Four levels of cascade move no money, because the determination is only a draft.

        The ledger only ever moves on finalization, and nothing in the discharge cascade
        finalizes anything: the determination it wrote is in `DRAFT`. The period therefore
        still reads the zeroes it opened with, even though the stay is priced at 1,500,000
        cents.

        PRD 3.9: "Determinations in `DRAFT` or `VOIDED` contribute nothing to either figure."
        PRD 3.7: "On success `finalized_by_user_id` records the acting `X-User-ID`, the stay's `payment_review_status` moves `PRICED → FINALIZED`, the period's `total_payment_cents` is increased by this determination's `total_payment_cents`, and the period's `final_determination_count` is increased by 1."

        Design: Difficulty/transitive_cascade/discharge_cascades_four_levels_to_an_auto_issued_documentation_query
        """
        admission = _cascading_discharge(api)
        determination = fixtures.sole_determination(api, admission.stay_id)
        assert determination["status"] == DeterminationStatus.DRAFT
        assert_cents(determination, "total_payment_cents", 1500000)

        period = fixtures.read_period(api, admission.world.period_id)
        assert_period_ledger(period, 0, 0)
        assert_integer_field(period, "total_admissions", 1)


# ── The reverse cascade ──────────────────────────────
# The parent is admitted fourteen days before the clock epoch and discharged at the epoch,
# then the same patient is readmitted two days later — inside the three-day fold window —
# and the readmission is folded back into the parent.
_PARENT_ADMITTED_AT = "2026-07-18T00:00:00.000Z"
_CHILD_ADMITTED_AT = "2026-08-03T00:00:00.000Z"
_PARENT_ESTIMATED_COST_CENTS = 1000000
_FINALIZED_CENTS = 1512000


def _finalized_parent_stay(api):
    """A fourteen-day stay discharged, cleared and finalized, so real money is on the books.

    Nothing is filed in the chart, so the review scores 32 for the four missing disciplines
    plus 15 for the absent weaning plan plus 20 for the short-stay flag, which is 67 — the
    middle band, so no query is auto-issued and the review can be resolved straight from
    `OPEN`. The referral carries a prior acute discharge and clears both intensity criteria,
    so pricing selects the standard variant and the finalized amount is 1,512,000 cents.
    """
    admission = fixtures.admitted_stay(api, admitted_at=_PARENT_ADMITTED_AT)
    fixtures.discharged_stay(
        api,
        admission=admission,
        discharge_disposition=DischargeDisposition.ACUTE_TRANSFER,
        estimated_cost_cents=_PARENT_ESTIMATED_COST_CENTS,
        file_notes=False,
    )
    review = fixtures.sole_review(api, admission.stay_id)
    fixtures.resolve_review(
        api,
        review["id"],
        outcome=ReviewOutcome.CLEARED,
        resolution_note="Acute transfer documented; the moderate band is accepted.",
    )
    determination = fixtures.sole_determination(api, admission.stay_id)
    fixtures.finalize(api, determination["id"], headers=ANALYST_2_HEADERS)
    return admission, determination["id"], review["id"]


def _readmit_same_patient(api, admission):
    """A second admission of the same patient two days after the first discharge."""
    fixtures.advance_clock(api, _CHILD_ADMITTED_AT)
    patient = fixtures.read_patient(api, admission.world.patient_id)
    referral = fixtures.qualified_referral(
        api, admission.world, patient_version=patient["version"]
    )
    return fixtures.admit(api, referral["id"])


class TestRecombinationUnwindsThreeAggregatesAtOnce:
    """One fold reaches the period ledger, the resolved review and the referral mix."""

    def test_the_fold_voids_the_finalized_determination_and_backs_its_money_out(self, api):
        """The money the parent had already banked leaves the period ledger.

        Before the fold the period carries the finalized 1,512,000 cents and a count of one.
        Reopening the parent reverts its payment dimension to `PENDING`, and that reversion is
        what unwinds the ledger: the `FINAL` determination becomes `VOIDED` with the system's
        own `RECOMBINED` reason, the period's money falls back to 0 and its finalized count
        falls back to 0.

        PRD 3.5: "Reverting to `PENDING` unwinds the money: every `PaymentDetermination` on the parent whose `status` is `DRAFT` or `FINAL` becomes `VOIDED` with `void_reason` set to the literal `RECOMBINED`, and for each one that was `FINAL`, the period's `total_payment_cents` is decreased by that determination's `total_payment_cents` and its `final_determination_count` is decreased by 1."

        Design: Difficulty/transitive_cascade/recombination_unwinds_ledger_review_and_referral_share_together
        """
        admission, determination_id, _ = _finalized_parent_stay(api)
        child = _readmit_same_patient(api, admission)

        before = fixtures.read_period(api, admission.world.period_id)
        assert_period_ledger(before, _FINALIZED_CENTS, 1)
        assert_integer_field(before, "total_admissions", 2)

        fixtures.recombine(api, child["id"], admission.stay_id)

        determination = fixtures.read_determination(api, determination_id)
        assert determination["status"] == DeterminationStatus.VOIDED
        assert determination["void_reason"] == VoidReason.RECOMBINED
        assert_cents(determination, "total_payment_cents", _FINALIZED_CENTS)

        after = fixtures.read_period(api, admission.world.period_id)
        assert_period_ledger(after, 0, 0)

    def test_the_fold_voids_the_review_that_had_already_been_cleared(self, api):
        """A resolved review is not immune: `CLEARED` moves on to `VOIDED`.

        Finalization required this review to be resolved, so by the time the fold arrives the
        review sits in `CLEARED`. Voiding the determination voids the compliance work built on
        it regardless, which makes `CLEARED → VOIDED` a real transition rather than an
        impossible one.

        PRD 3.5: "Voiding the determinations in turn voids the compliance work built on them: the parent's `DenialRiskReview` becomes `VOIDED`, and every `DocumentationQuery` on that review whose `status` is `ISSUED` or `ANSWERED` becomes `VOIDED` as well."
        PRD 3.5: "Because finalization requires a resolved review, every `FINAL` determination that recombination has to unwind necessarily hangs off a resolved review — so `CLEARED → VOIDED` and `ESCALATED → VOIDED` are real transitions, and `VOIDED` is the only genuinely terminal state of the review lifecycle."

        Design: Difficulty/transitive_cascade/recombination_unwinds_ledger_review_and_referral_share_together
        """
        admission, _, review_id = _finalized_parent_stay(api)
        child = _readmit_same_patient(api, admission)

        before = fixtures.read_review(api, review_id)
        assert before["status"] == ReviewStatus.CLEARED

        fixtures.recombine(api, child["id"], admission.stay_id)

        after = fixtures.read_review(api, review_id)
        assert after["status"] == ReviewStatus.VOIDED
        assert after["risk_band"] == RiskBand.MODERATE

    def test_the_fold_decrements_the_admission_count_and_recomputes_the_referral_share(
        self, api
    ):
        """The same write also moves the referral-mix denominator and the source's share.

        Both stays came from the one registered hospital, so before the fold the period counts
        two admissions and the hospital owns both. The child stops counting, which drops the
        hospital to one admission and the period to one, and the share is recomputed from the
        new denominator to 100.00. A total of one admission is fewer than four, so the mix is
        too thin to judge and the state stays `COMPLIANT` despite the full share.

        PRD 3.5: "Because the child stopped counting as an admission, the child's referring hospital has its `admissions_in_period` decreased by 1 and the period's `total_admissions` is decreased by 1; and because the denominator moved, `share_pct`, `threshold_pct` and `monitoring_state` are recomputed for every referring hospital exactly as at admission."
        PRD 3.3: "If the period's `total_admissions` is fewer than 4, the mix is too thin to judge and `monitoring_state` is `COMPLIANT` regardless of the computed share; note that `share_pct` is still stored in that case, so a hospital may legitimately show a share of 100.00 while sitting at `COMPLIANT`."

        Design: Difficulty/transitive_cascade/recombination_unwinds_ledger_review_and_referral_share_together
        """
        admission, _, _ = _finalized_parent_stay(api)
        child = _readmit_same_patient(api, admission)

        before = fixtures.read_hospital(api, admission.world.hospital_id)
        assert_hospital_posture(before, 2, 100.00, MonitoringState.COMPLIANT)

        fixtures.recombine(api, child["id"], admission.stay_id)

        hospital = fixtures.read_hospital(api, admission.world.hospital_id)
        assert_hospital_posture(hospital, 1, 100.00, MonitoringState.COMPLIANT)
        assert_integer_field(
            fixtures.read_period(api, admission.world.period_id), "total_admissions", 1
        )

    def test_the_fold_terminates_the_child_and_reopens_the_parent_with_its_banked_days(
        self, api
    ):
        """The two halves of the fold, read on the two stays it touched.

        The child reaches `RECOMBINED`, which is terminal, and stops counting toward the
        admission threshold. The parent comes back to `ADMITTED` with its payment dimension
        reverted to `PENDING`, and the fourteen days it had already run from 2026-07-18 to
        2026-08-01 are frozen into `carried_los_days`; its `resumed_at` is the child's
        `admitted_at` and its discharge fields are cleared.

        PRD 3.5: "The fold has two halves. The **child** moves `ADMITTED → RECOMBINED`, which is terminal — no further clinical transition is possible on it — records the parent's id in `interrupted_parent_stay_id`, and sets `counts_toward_admission_threshold` to false."
        PRD 3.5: "Its `carried_los_days` is frozen at the whole-day count from its `admitted_at` to its `discharged_at` — the covered days already banked from the pre-recombination segment — its `resumed_at` is stamped with the child's `admitted_at`, and both its `discharged_at` and its `discharge_disposition` are cleared to null."

        Design: Difficulty/transitive_cascade/recombination_unwinds_ledger_review_and_referral_share_together
        """
        admission, _, _ = _finalized_parent_stay(api)
        child = _readmit_same_patient(api, admission)

        fixtures.recombine(api, child["id"], admission.stay_id)

        folded_child = fixtures.read_stay(api, child["id"])
        assert folded_child["clinical_status"] == ClinicalStatus.RECOMBINED
        assert folded_child["counts_toward_admission_threshold"] is False
        assert folded_child["interrupted_parent_stay_id"] == admission.stay_id

        parent = fixtures.read_stay(api, admission.stay_id)
        assert_stay_dimensions(parent, ClinicalStatus.ADMITTED, PaymentReviewStatus.PENDING)
        assert_integer_field(parent, "carried_los_days", 14)
        assert_instant_equals(parent["resumed_at"], _CHILD_ADMITTED_AT, "resumed_at")
        assert_unset(parent, "discharged_at", "discharge_disposition")
