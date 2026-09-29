"""
Counters that must return to their exact prior value after a reversal, never double-count.

The money ledger is the first: a finalize adds a determination's total to the period, a void
subtracts the same figure, and a re-priced re-finalize has to land the period on the
original number rather than on twice it. The proof is the period close, which re-derives
the ledger from every `FINAL` determination and refuses on any disagreement.

The admission counters are the second: the hospitals' `admissions_in_period` must always sum
to the period's `total_admissions`, and recombination is the one operation that decrements
both. There the proof is the on-demand share recomputation, which rewrites every figure from
the stored denominator and must change nothing at all.
"""

from test_helpers import (
    ANALYST_2_ID,
    ANALYST_ID,
    ApiErrorId,
    ClinicalStatus,
    DeterminationStatus,
    MonitoringState,
    PaymentReviewStatus,
    PaymentVariant,
    PeriodStatus,
    ReviewStatus,
    RiskBand,
    VoidReason,
    assert_cents,
    assert_counters_reconcile,
    assert_hospital_posture,
    assert_instant_equals,
    assert_integer_field,
    assert_pct,
    assert_period_ledger,
    factories,
    fixtures,
    validate_error,
)

DISCHARGE_INSTANT = "2026-08-15T00:00:00Z"
SHORT_STAY_LOS_DAYS = 14
SHORT_STAY_TOTAL_CENTS = 1512000
SHORT_STAY_PCT = 25.20
VOID_REASON = "AUDIT_CORRECTION"


def _priced_short_stay(api):
    """A 14-day stay discharged, priced by the cascade and cleared, ready to finalize.

    No interdisciplinary notes and no weaning plan exist, so the auto-created review scores
    32 for the four missing disciplines plus 15 for the weaning gap plus 20 for the
    short-stay outlier, which lands in the `MODERATE` band and issues no query — leaving the
    review clearable from `OPEN` and the money gate open.
    """
    world = fixtures.build_world(api)
    admission = fixtures.admitted_stay(api, world)
    fixtures.advance_clock(api, DISCHARGE_INSTANT)
    admission = fixtures.discharged_stay(api, admission=admission, file_notes=False)
    fixtures.clear_review_for_finalize(api, admission)
    return world, admission


class TestThePeriodLedgerAcrossAVoidAndRePrice:
    """Finalize adds, void subtracts the same figure, and the round trip nets to zero."""

    def test_the_ledger_reads_zero_before_the_finalize_and_the_determination_total_after(
        self, api, second_analyst
    ):
        """The first reading of the three: an accepted price is what enters the ledger.

        The 14-day stay is a short-stay outlier against a threshold of 25 days, so its
        standard base is the smallest of the 2,800,000-cent LTCH per-diem component, the
        1,512,000-cent 120-percent IPPS blend and the 2,400,000-cent IPPS full amount — and
        the estimated cost of 1,000,000 cents is far below the outlier threshold, so nothing
        is added on top. While the determination is still `DRAFT` the period's ledger reads
        nothing at all; the finalize is the moment the 1,512,000 cents and the count of one
        appear.

        PRD 3.7: "On success `finalized_by_user_id` records the acting `X-User-ID`, the stay's `payment_review_status` moves `PRICED → FINALIZED`, the period's `total_payment_cents` is increased by this determination's `total_payment_cents`, and the period's `final_determination_count` is increased by 1."
        PRD 3.7: "The standard base is the minimum of those three."
        PRD 3.9: "Determinations in `DRAFT` or `VOIDED` contribute nothing to either figure."

        Design: Difficulty/compensating_invariant/void_reprice_refinalize_leaves_the_period_ledger_undrifted
        """
        world, admission = _priced_short_stay(api)

        assert_integer_field(admission.stay, "covered_los_days", SHORT_STAY_LOS_DAYS)
        draft = fixtures.read_determination(api, admission.determination_id)
        assert draft["status"] == DeterminationStatus.DRAFT
        assert draft["payment_variant"] == PaymentVariant.STANDARD_LTCH_PPS
        assert_cents(draft, "total_payment_cents", SHORT_STAY_TOTAL_CENTS)
        assert fixtures.read_review(api, admission.review_id)["risk_band"] == (
            RiskBand.MODERATE
        )

        before = fixtures.read_period(api, world.period_id)
        assert_period_ledger(before, total_payment_cents=0, final_determination_count=0)

        finalized = fixtures.finalize(
            api, admission.determination_id, headers=second_analyst
        )
        assert finalized["status"] == DeterminationStatus.FINAL
        assert finalized["finalized_by_user_id"] == ANALYST_2_ID
        assert_cents(finalized, "total_payment_cents", SHORT_STAY_TOTAL_CENTS)

        after = fixtures.read_period(api, world.period_id)
        assert_period_ledger(
            after,
            total_payment_cents=SHORT_STAY_TOTAL_CENTS,
            final_determination_count=1,
        )

        stay = fixtures.read_stay(api, admission.stay_id)
        assert stay["payment_review_status"] == PaymentReviewStatus.FINALIZED
        assert_pct(stay, "discharge_payment_pct", SHORT_STAY_PCT)

    def test_voiding_the_final_determination_subtracts_exactly_what_the_finalize_added(
        self, api, second_analyst, third_analyst
    ):
        """The second reading: both figures return to their pre-finalization values.

        A third analyst voids what the second accepted, which is the only reversal the
        specification offers for money already in the ledger. The subtraction is not an
        approximation of the addition but the same integer, so the period returns to zero
        cents and zero finalized determinations. The stay's money story unwinds with it —
        back to `PENDING` with no discharge percentage — while the review, which the void
        does not touch, stays resolved.

        PRD 3.7: "Voiding a `FINAL` determination is `FINAL → VOIDED`, requires that the acting `X-User-ID` differ from the determination's `finalized_by_user_id`, sets the stay's `payment_review_status` back to `PENDING` and clears `discharge_payment_pct`, and unwinds the ledger exactly: the period's `total_payment_cents` is decreased by this determination's `total_payment_cents` and its `final_determination_count` is decreased by 1, returning both to their pre-finalization values."
        PRD 2.9: "Second, a compensating reversal must restore the ledger exactly: voiding a determination that was `FINAL` decrements the period's `total_payment_cents` by that determination's `total_payment_cents` and decrements `final_determination_count` by 1, returning both to their pre-finalization values, because integer cent addition is exact and the per-determination rounding already happened."

        Design: Difficulty/compensating_invariant/void_reprice_refinalize_leaves_the_period_ledger_undrifted
        """
        world, admission = _priced_short_stay(api)
        fixtures.finalize(api, admission.determination_id, headers=second_analyst)
        assert_period_ledger(
            fixtures.read_period(api, world.period_id),
            total_payment_cents=SHORT_STAY_TOTAL_CENTS,
            final_determination_count=1,
        )

        voided = fixtures.void(
            api,
            admission.determination_id,
            void_reason=VOID_REASON,
            headers=third_analyst,
        )
        assert voided["status"] == DeterminationStatus.VOIDED
        assert voided["void_reason"] == VOID_REASON

        after_void = fixtures.read_period(api, world.period_id)
        assert_period_ledger(
            after_void, total_payment_cents=0, final_determination_count=0
        )

        stay = fixtures.read_stay(api, admission.stay_id)
        assert stay["payment_review_status"] == PaymentReviewStatus.PENDING
        assert stay["discharge_payment_pct"] is None
        assert (
            fixtures.read_review(api, admission.review_id)["status"]
            == ReviewStatus.CLEARED
        )

    def test_a_void_attempted_by_the_finalizing_analyst_leaves_the_ledger_untouched(
        self, api, second_analyst
    ):
        """A refused reversal must not half-apply: no subtraction without a void.

        The analyst who accepted the determination is the one person forbidden to reverse
        it, and the refusal is a segregation-of-duties failure rather than a state error —
        the determination really is `FINAL` and really is voidable, just not by this
        identity. Because the request never took effect the determination is still `FINAL`
        with a null `void_reason`, and the period still carries the 1,512,000 cents and the
        count of one.

        PRD 2.1: "The `X-User-ID` voiding a determination that is currently `FINAL` must differ from that determination's `finalized_by_user_id`."
        PRD 3.7: "The `void_reason` field holds the analyst's supplied reason for a human void, the literal `SUPERSEDED` for a draft displaced by a re-price, and the literal `RECOMBINED` for one unwound by a recombination; it is null on a determination that was never voided."

        Design: Difficulty/compensating_invariant/void_reprice_refinalize_leaves_the_period_ledger_undrifted
        """
        world, admission = _priced_short_stay(api)
        fixtures.finalize(api, admission.determination_id, headers=second_analyst)

        refused = api.void_determination(
            admission.determination_id,
            factories.void_payload(VOID_REASON),
            headers=second_analyst,
        )
        validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        determination = fixtures.read_determination(api, admission.determination_id)
        assert determination["status"] == DeterminationStatus.FINAL
        assert determination["void_reason"] is None

        assert_period_ledger(
            fixtures.read_period(api, world.period_id),
            total_payment_cents=SHORT_STAY_TOTAL_CENTS,
            final_determination_count=1,
        )

    def test_the_re_priced_re_finalized_period_lands_on_the_original_figure_and_closes(
        self, api, analyst, second_analyst, third_analyst
    ):
        """The third reading: 1,512,000 and one, not 3,024,000 and two.

        The round trip is finalize, void, re-price, finalize again, and the ledger is read
        at every stage: zero before, the determination total after the first finalize, zero
        again after the void, and after the second finalize exactly the same total as
        before rather than the sum of both determinations. The re-price is a new row priced
        by a different analyst from the same frozen inputs, so it reproduces the identical
        figure. The close is what proves the arithmetic: it re-derives the ledger from every
        `FINAL` determination in the period and refuses on any disagreement, so reaching
        `CLOSED` means the incrementally maintained figures survived the reversal intact.

        PRD 3.9: "Second, the incrementally maintained ledger must equal a full recomputation: the period's `total_payment_cents` must equal the sum of the `total_payment_cents` of every determination whose `status` is `FINAL` and whose stay belongs to this period, and its `final_determination_count` must equal the count of those same determinations."
        PRD 3.7: "The new determination is written with `status` `DRAFT`, `priced_by_user_id` set to the acting analyst's `X-User-ID`, its `stay_id` copied from the path, the stay's `payment_review_status` set to `PRICED`, and the stay's `version` increased by 1."
        PRD 3.9: "On a successful close the period moves `OPEN → CLOSED`, `closed_at` is stamped from the logical clock, and `share_pct`, `threshold_pct` and `monitoring_state` are recomputed one final time for every referring hospital so that the closed period's admission mix is frozen at its audited values."

        Design: Difficulty/compensating_invariant/void_reprice_refinalize_leaves_the_period_ledger_undrifted
        """
        world, admission = _priced_short_stay(api)
        first_determination_id = admission.determination_id

        assert_period_ledger(
            fixtures.read_period(api, world.period_id),
            total_payment_cents=0,
            final_determination_count=0,
        )

        fixtures.finalize(api, first_determination_id, headers=second_analyst)
        assert_period_ledger(
            fixtures.read_period(api, world.period_id),
            total_payment_cents=SHORT_STAY_TOTAL_CENTS,
            final_determination_count=1,
        )

        fixtures.void(
            api,
            first_determination_id,
            void_reason=VOID_REASON,
            headers=third_analyst,
        )
        assert_period_ledger(
            fixtures.read_period(api, world.period_id),
            total_payment_cents=0,
            final_determination_count=0,
        )

        stay = fixtures.read_stay(api, admission.stay_id)
        second = fixtures.reprice(
            api, admission.stay_id, stay["version"], headers=analyst
        )
        assert second["id"] != first_determination_id
        assert second["priced_by_user_id"] == ANALYST_ID
        assert_cents(second, "total_payment_cents", SHORT_STAY_TOTAL_CENTS)

        fixtures.finalize(api, second["id"], headers=second_analyst)
        assert_period_ledger(
            fixtures.read_period(api, world.period_id),
            total_payment_cents=SHORT_STAY_TOTAL_CENTS,
            final_determination_count=1,
        )

        closed = fixtures.close_period(api, world.period_id)
        assert closed["status"] == PeriodStatus.CLOSED
        assert_instant_equals(closed["closed_at"], DISCHARGE_INSTANT, "closed_at")
        assert_period_ledger(
            closed,
            total_payment_cents=SHORT_STAY_TOTAL_CENTS,
            final_determination_count=1,
        )


AUGUST_PERIOD = {
    "period_label": "AUG2026",
    "start_date": "2026-08-01",
    "end_date": "2026-08-31",
}
PARENT_DISCHARGE_AT = "2026-08-10T00:00:00Z"
CHILD_ADMITTED_AT = "2026-08-12T00:00:00Z"
PARENT_LOS_DAYS = 9
PARENT_TOTAL_CENTS = 972000
PARENT_RISK_SCORE = 67
ONE_OF_THREE_PCT = 33.33
TWO_OF_THREE_PCT = 66.67
TWO_OF_FOUR_PCT = 50.00
ACUTE_CARE_THRESHOLD_PCT = 25.00


def _two_sources_and_three_admissions(api):
    """Metro General with one admission and Suburban Health with two, in one open period.

    Three admissions is one short of the four the monitoring rule needs before it will
    judge a share, so both hospitals sit at `COMPLIANT` even though Suburban already holds
    two thirds of the mix.
    """
    world = fixtures.build_world(api, period=AUGUST_PERIOD)
    suburban = fixtures.add_hospital(api, name="Suburban Health")
    metro_admission = fixtures.admitted_stay(api, world)
    for _ in range(2):
        patient = fixtures.add_patient(api)
        fixtures.admitted_stay(
            api,
            world,
            patient_id=patient["id"],
            patient_version=patient["version"],
            hospital_id=suburban["id"],
        )
    return world, suburban, metro_admission


def _discharge_and_readmit(api, world, metro_admission):
    """Discharge Metro's patient on 2026-08-10 and readmit her through Metro on 2026-08-12.

    The readmission is a fourth admission, which is what takes the period over the
    monitoring floor, and it falls two whole days after the discharge — inside the
    three-day recombination window.
    """
    fixtures.advance_clock(api, PARENT_DISCHARGE_AT)
    parent = fixtures.discharged_stay(api, admission=metro_admission, file_notes=False)
    fixtures.advance_clock(api, CHILD_ADMITTED_AT)
    patient = fixtures.read_patient(api, world.patient_id)
    referral = fixtures.qualified_referral(
        api,
        world,
        patient_version=patient["version"],
        prior_acute_discharge_at=PARENT_DISCHARGE_AT,
    )
    return parent, fixtures.admit(api, referral["id"])


def _readmission_pending_recombination(api):
    """The four-admission state, with the readmission not yet folded into its parent."""
    world, suburban, metro_admission = _two_sources_and_three_admissions(api)
    parent, child = _discharge_and_readmit(api, world, metro_admission)
    return world, suburban, parent, child


class TestTheAdmissionCountAndShareInvariantAcrossARecombination:
    """The hospital counters always sum to the period's total, before and after the fold."""

    def test_three_admissions_sit_below_the_monitoring_floor_and_the_fourth_breaches(
        self, api
    ):
        """The readmission moves the denominator from 3 to 4 and un-guards the mix.

        At three admissions Metro holds one and Suburban two, so the shares read 33.33 and
        66.67 and their counts sum to the period's 3 — but the mix is too thin to judge and
        both hospitals are `COMPLIANT` regardless. The readmission gives Metro a second
        admission out of four: 50.00 percent against an acute-care threshold of 25.00,
        strictly greater, so Metro becomes `BREACHED`, and Suburban's unchanged two of four
        breaches with it. The sum of the two counters still equals the period's total.

        PRD 3.3: "A hospital's `share_pct` is its `admissions_in_period` divided by the period's `total_admissions`, multiplied by 100 and rounded half up to two decimal places; when the denominator is zero, `share_pct` is stored as 0.00."
        PRD 3.3: "If the period's `total_admissions` is fewer than 4, the mix is too thin to judge and `monitoring_state` is `COMPLIANT` regardless of the computed share; note that `share_pct` is still stored in that case, so a hospital may legitimately show a share of 100.00 while sitting at `COMPLIANT`."
        PRD 3.3: "Otherwise, if `share_pct` is **strictly greater** than `threshold_pct`, `monitoring_state` becomes `BREACHED` — a share of exactly 25.00 against a threshold of 25.00 is not a breach."

        Design: Difficulty/compensating_invariant/recombination_restores_the_admission_count_and_referral_share_invariant
        """
        world, suburban, metro_admission = _two_sources_and_three_admissions(api)

        at_three = fixtures.read_period(api, world.period_id)
        assert_integer_field(at_three, "total_admissions", 3)
        metro = fixtures.read_hospital(api, world.hospital_id)
        assert_hospital_posture(
            metro,
            admissions_in_period=1,
            share_pct=ONE_OF_THREE_PCT,
            monitoring_state=MonitoringState.COMPLIANT,
        )
        assert_pct(metro, "threshold_pct", ACUTE_CARE_THRESHOLD_PCT)
        sub = fixtures.read_hospital(api, suburban["id"])
        assert_hospital_posture(
            sub,
            admissions_in_period=2,
            share_pct=TWO_OF_THREE_PCT,
            monitoring_state=MonitoringState.COMPLIANT,
        )
        assert_counters_reconcile(at_three, [metro, sub])

        _parent, child = _discharge_and_readmit(api, world, metro_admission)
        assert child["clinical_status"] == ClinicalStatus.ADMITTED

        at_four = fixtures.read_period(api, world.period_id)
        assert_integer_field(at_four, "total_admissions", 4)
        metro_breached = fixtures.read_hospital(api, world.hospital_id)
        assert_hospital_posture(
            metro_breached,
            admissions_in_period=2,
            share_pct=TWO_OF_FOUR_PCT,
            monitoring_state=MonitoringState.BREACHED,
        )
        sub_breached = fixtures.read_hospital(api, suburban["id"])
        assert_hospital_posture(
            sub_breached,
            admissions_in_period=2,
            share_pct=TWO_OF_FOUR_PCT,
            monitoring_state=MonitoringState.BREACHED,
        )
        assert_counters_reconcile(at_four, [metro_breached, sub_breached])

    def test_the_recombination_returns_both_counters_to_their_pre_readmission_values(
        self, api, officer
    ):
        """Folding the readmission away restores 3, 1 and 2 exactly, and un-latches the breach.

        Recombination is the only operation that decrements these counters, and it has to
        decrement both sides together: the child stops counting, so Metro drops to one
        admission and the period to three, and the two hospital counters still sum to the
        period's total. Because the denominator fell back below four the monitoring rule
        stops judging again, so Metro's `BREACHED` state is recomputed away rather than
        latched, and the shares return to the 33.33 and 66.67 they read before the
        readmission ever happened.

        PRD 3.5: "Because the child stopped counting as an admission, the child's referring hospital has its `admissions_in_period` decreased by 1 and the period's `total_admissions` is decreased by 1; and because the denominator moved, `share_pct`, `threshold_pct` and `monitoring_state` are recomputed for every referring hospital exactly as at admission."
        PRD 3.5: "A recombination can therefore lift a hospital *out* of `BREACHED`."
        PRD 3.3: "The numerator for each hospital is its `admissions_in_period`, which counts the stays in the open period whose referral pointed at that hospital and whose `counts_toward_admission_threshold` is true."

        Design: Difficulty/compensating_invariant/recombination_restores_the_admission_count_and_referral_share_invariant
        """
        world, suburban, parent, child = _readmission_pending_recombination(api)

        fixtures.recombine(api, child["id"], parent.stay_id, headers=officer)

        period = fixtures.read_period(api, world.period_id)
        assert_integer_field(period, "total_admissions", 3)
        metro = fixtures.read_hospital(api, world.hospital_id)
        assert_hospital_posture(
            metro,
            admissions_in_period=1,
            share_pct=ONE_OF_THREE_PCT,
            monitoring_state=MonitoringState.COMPLIANT,
        )
        sub = fixtures.read_hospital(api, suburban["id"])
        assert_hospital_posture(
            sub,
            admissions_in_period=2,
            share_pct=TWO_OF_THREE_PCT,
            monitoring_state=MonitoringState.COMPLIANT,
        )
        assert_counters_reconcile(period, [metro, sub])

    def test_the_on_demand_recompute_agrees_with_the_decremented_counters(self, api):
        """The full recompute changes nothing, which is what proves the decrement was right.

        Immediately after the fold, every figure is captured and the officer re-runs the
        whole share recomputation against the same open period. The sweep rewrites
        `share_pct`, `threshold_pct` and `monitoring_state` for every hospital from the
        stored denominator, so if the incremental decrement had left either counter drifted
        the recomputed shares would move. They do not: one of three and two of three, 33.33
        and 66.67, both `COMPLIANT`, identical before and after.

        PRD 3.3: "A `ComplianceOfficer` may also re-run that whole recomputation on demand against an `OPEN` period, an idempotent sweep that rewrites `share_pct`, `threshold_pct` and `monitoring_state` for every referring hospital from the period's stored `total_admissions`."
        PRD 3.3: "The sweep exists precisely so that the incrementally maintained counters can be checked against a full recompute — the two must always agree."

        Design: Difficulty/compensating_invariant/recombination_restores_the_admission_count_and_referral_share_invariant
        """
        world, suburban, parent, child = _readmission_pending_recombination(api)
        fixtures.recombine(api, child["id"], parent.stay_id)

        metro_before = fixtures.read_hospital(api, world.hospital_id)
        sub_before = fixtures.read_hospital(api, suburban["id"])

        fixtures.recompute_shares(api, world.period_id)

        metro_after = fixtures.read_hospital(api, world.hospital_id)
        sub_after = fixtures.read_hospital(api, suburban["id"])

        for before, after, admissions, share in (
            (metro_before, metro_after, 1, ONE_OF_THREE_PCT),
            (sub_before, sub_after, 2, TWO_OF_THREE_PCT),
        ):
            assert_hospital_posture(
                after,
                admissions_in_period=admissions,
                share_pct=share,
                monitoring_state=MonitoringState.COMPLIANT,
            )
            assert after["admissions_in_period"] == before["admissions_in_period"]
            assert after["share_pct"] == before["share_pct"]
            assert after["threshold_pct"] == before["threshold_pct"]
            assert after["monitoring_state"] == before["monitoring_state"]

        period = fixtures.read_period(api, world.period_id)
        assert_integer_field(period, "total_admissions", 3)
        assert_counters_reconcile(period, [metro_after, sub_after])

    def test_the_recombination_unwinds_the_parents_money_and_reopens_it_with_banked_days(
        self, api
    ):
        """The parent's draft price and its review are voided, and the ledger never moved.

        Before the fold the parent is a discharged 9-day stay priced at 972,000 cents —
        the smallest of the 1,800,000-cent per-diem component, the 972,000-cent IPPS blend
        and the 2,400,000-cent full amount — with a review scoring 67. The fold voids that
        determination with the system's own `RECOMBINED` reason and voids the review built on
        it, while the period's money ledger stays at zero throughout, because a `DRAFT`
        determination was never in it. The parent reopens with its nine covered days frozen
        into `carried_los_days` and `resumed_at` set to the child's admission instant, and
        the child ends in `RECOMBINED` no longer counting toward the admission threshold.

        PRD 3.5: "Reverting to `PENDING` unwinds the money: every `PaymentDetermination` on the parent whose `status` is `DRAFT` or `FINAL` becomes `VOIDED` with `void_reason` set to the literal `RECOMBINED`, and for each one that was `FINAL`, the period's `total_payment_cents` is decreased by that determination's `total_payment_cents` and its `final_determination_count` is decreased by 1."
        PRD 3.5: "Voiding the determinations in turn voids the compliance work built on them: the parent's `DenialRiskReview` becomes `VOIDED`, and every `DocumentationQuery` on that review whose `status` is `ISSUED` or `ANSWERED` becomes `VOIDED` as well."
        PRD 3.5: "Its `carried_los_days` is frozen at the whole-day count from its `admitted_at` to its `discharged_at` — the covered days already banked from the pre-recombination segment — its `resumed_at` is stamped with the child's `admitted_at`, and both its `discharged_at` and its `discharge_disposition` are cleared to null."
        PRD 3.5: "The **child** moves `ADMITTED → RECOMBINED`, which is terminal — no further clinical transition is possible on it — records the parent's id in `interrupted_parent_stay_id`, and sets `counts_toward_admission_threshold` to false."

        Design: Difficulty/compensating_invariant/recombination_restores_the_admission_count_and_referral_share_invariant
        """
        world, _suburban, parent, child = _readmission_pending_recombination(api)

        assert_integer_field(parent.stay, "covered_los_days", PARENT_LOS_DAYS)
        assert_cents(parent.determination, "total_payment_cents", PARENT_TOTAL_CENTS)
        assert_integer_field(parent.review, "effective_score", PARENT_RISK_SCORE)
        assert_period_ledger(
            fixtures.read_period(api, world.period_id),
            total_payment_cents=0,
            final_determination_count=0,
        )

        fixtures.recombine(api, child["id"], parent.stay_id)

        determination = fixtures.read_determination(api, parent.determination_id)
        assert determination["status"] == DeterminationStatus.VOIDED
        assert determination["void_reason"] == VoidReason.RECOMBINED
        assert (
            fixtures.read_review(api, parent.review_id)["status"] == ReviewStatus.VOIDED
        )
        assert_period_ledger(
            fixtures.read_period(api, world.period_id),
            total_payment_cents=0,
            final_determination_count=0,
        )

        reopened = fixtures.read_stay(api, parent.stay_id)
        assert reopened["clinical_status"] == ClinicalStatus.ADMITTED
        assert reopened["payment_review_status"] == PaymentReviewStatus.PENDING
        assert reopened["discharged_at"] is None
        assert reopened["discharge_disposition"] is None
        assert_integer_field(reopened, "carried_los_days", PARENT_LOS_DAYS)
        assert_instant_equals(reopened["resumed_at"], CHILD_ADMITTED_AT, "resumed_at")

        folded = fixtures.read_stay(api, child["id"])
        assert folded["clinical_status"] == ClinicalStatus.RECOMBINED
        assert folded["counts_toward_admission_threshold"] is False
        assert folded["interrupted_parent_stay_id"] == parent.stay_id
