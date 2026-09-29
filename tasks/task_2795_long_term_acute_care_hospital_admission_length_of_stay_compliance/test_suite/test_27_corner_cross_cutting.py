"""
The two declared concurrency guards, the small-denominator gate and immediate visibility.

Three claims are pinned here. Both endpoints that declare a version field are made to
refuse a write carried out against a version the intervening write already consumed, and
in each case the refused write is shown to have changed nothing while the retry against
the refreshed version does the destructive thing the guard exists to protect. The
referral-mix gate is shown to hang on the period's denominator rather than on the share, so
one referral source can hold the entire mix and still be compliant until a fourth admission
— made by a different source — releases the gate. And because the model is immediate, the
discharge response body itself must already carry every value its cascade derived, and the
period ledger must never be observed lagging behind a determination it has accepted.
"""

from test_helpers import (
    BASE_REFERRAL_THRESHOLD_PCT,
    DRG_207,
    DRG_207_FULL_STANDARD_CENTS,
    DRG_207_SSO_THRESHOLD_DAYS,
    EXPANDED_REFERRAL_THRESHOLD_PCT,
    INTAKE_HEADERS,
    MIN_ADMISSIONS_FOR_MONITORING,
    NURSE_HEADERS,
    SSO_IPPS_PER_DIEM_FACTOR,
    SYSTEM_ACTOR,
    ApiErrorId,
    ClinicalStatus,
    DeterminationStatus,
    HospitalType,
    MonitoringState,
    PaymentReviewStatus,
    ReferralStatus,
    ReviewOutcome,
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
    assert_stay_dimensions,
    assert_unset,
    clamped_score,
    discharge_payment_pct,
    factories,
    fixtures,
    get_success_data,
    ids_of,
    raw_risk_score,
    risk_band_for,
    round_half_up_int,
    validate_error,
    validate_paginated,
)

# Admission is at the clock epoch and discharge two weeks later, so the covered stay is
# 14 whole days against a short-stay threshold of 25 days for this DRG.
DISCHARGE_CLOCK = "2026-08-15T00:00:00Z"
COVERED_LOS_DAYS = 14

# The short-stay base payment is the lowest of three candidates. The per-diem candidate
# capped at the full amount is 2,800,000 cents and the IPPS comparable full amount is
# 2,400,000 cents, so the IPPS per-diem candidate below is the one that wins.
SSO_BASE_CENTS = round_half_up_int(
    DRG_207["ipps_comparable_per_diem_cents"] * COVERED_LOS_DAYS * SSO_IPPS_PER_DIEM_FACTOR
)
# An estimated cost of 1,000,000 cents is far below base + 3,000,000, so no high-cost
# add-on is earned and the total equals the base.
TOTAL_PAYMENT_CENTS = SSO_BASE_CENTS
DISCHARGE_PCT = discharge_payment_pct(SSO_BASE_CENTS, DRG_207_FULL_STANDARD_CENTS)

# With no interdisciplinary notes filed, no weaning plan opened, the short-stay flag set
# and the standard variant selected, the raw score is 4x8 + 15 + 20 with no length-of-stay
# excess: 67 points, which is the MODERATE band.
UNDOCUMENTED_SCORE = clamped_score(
    raw_risk_score(
        missing_discipline_count=4,
        weaning_gap=1,
        sso_flag=1,
        site_neutral_flag=0,
        los_excess_days=0,
    )
)
UNDOCUMENTED_BAND = risk_band_for(UNDOCUMENTED_SCORE)


def _documented_discharged_stay(api) -> fixtures.Admission:
    """A stay admitted at the epoch, fully documented, and discharged two weeks later."""
    admission = fixtures.admitted_stay(api)
    fixtures.file_required_notes(api, admission.stay_id)
    fixtures.advance_clock(api, DISCHARGE_CLOCK)
    admission.stay = fixtures.discharge(api, admission.stay_id)
    return fixtures.collect_cascade(api, admission)


class TestBothDeclaredConcurrencyGuardsRejectAStaleParent:
    """The two — and only two — endpoints that carry a version field, on both sides."""

    def test_a_referral_create_carrying_a_consumed_patient_version_is_refused(
        self, api, intake
    ):
        """The version a first referral consumed cannot be spent on a second.

        The patient's version is read before any referral exists and one referral is filed
        against it, which advances the patient by exactly one because the create wrote the
        patient's open-referral counter. A second create still offering the original version
        is therefore working from a view the first create invalidated: it is refused, and the
        patient is left holding the single referral that legitimately exists rather than a
        second one the refusal would have superseded.

        PRD 2.6: "If `expected_patient_version` does not equal the patient's current `version`, the create is rejected with `ERR_STALE_PATIENT_VERSION` and HTTP status 412."
        PRD 2.6: "On success the patient's `version` advances by 1, which invalidates every other in-flight referral create for that patient."

        Design: Corner/cross_cutting_complexity_layers/both_declared_occ_guards_reject_a_stale_parent_version
        """
        world = fixtures.build_world(api)
        consumed_version = world.patient_version
        first = fixtures.create_referral(api, world)

        patient = fixtures.read_patient(api, world.patient_id)
        assert_integer_field(patient, "version", consumed_version + 1)
        assert_integer_field(patient, "open_referral_count", 1)

        validate_error(
            api.create_referral(
                factories.referral_payload(
                    world.patient_id, world.hospital_id, world.drg_rate_id, consumed_version
                ),
                headers=intake,
            ),
            ApiErrorId.ERR_STALE_PATIENT_VERSION,
        )

        listed, meta = validate_paginated(
            api.list_referrals(params={"patient_id": world.patient_id}, headers=intake)
        )
        assert ids_of(listed) == [first["id"]]
        assert meta["total_count"] == 1

    def test_the_referral_create_retried_on_the_refreshed_patient_version_supersedes_the_first(
        self, api, intake
    ):
        """Refreshing the version is what licenses the destructive create.

        The guard is not a refusal of the second referral but a demand that its author have
        seen the first. Re-reading the patient and offering the version that read reports
        lets the create through, and the create then does exactly the destructive thing the
        guard protects: the earlier referral is flipped to the terminal superseded status, the
        patient advances one more version, and the open-referral counter settles back at one
        because the decrement and the increment cancel.

        PRD 3.2: "Creation also does something destructive, which is what §2.6's version check protects: any other referral of the same patient whose `status` is `RECEIVED`, `INFO_REQUESTED` or `CRITERIA_MET` is flipped to `SUPERSEDED` (a terminal status), the patient's `version` advances by 1, and the patient's `open_referral_count` settles at 1 — one decrement for the superseded referral, one increment for the new one, so the net stays at 1."
        PRD 2.6: "On success the patient's `version` advances by 1, which invalidates every other in-flight referral create for that patient."

        Design: Corner/cross_cutting_complexity_layers/both_declared_occ_guards_reject_a_stale_parent_version
        """
        world = fixtures.build_world(api)
        first = fixtures.create_referral(api, world)
        refreshed_version = fixtures.read_patient(api, world.patient_id)["version"]

        second = get_success_data(
            api.create_referral(
                factories.referral_payload(
                    world.patient_id, world.hospital_id, world.drg_rate_id, refreshed_version
                ),
                headers=intake,
            ),
            expected_status=201,
        )

        assert (
            fixtures.read_referral(api, first["id"])["status"] == ReferralStatus.SUPERSEDED
        )
        assert fixtures.read_referral(api, second["id"])["status"] == ReferralStatus.RECEIVED
        patient = fixtures.read_patient(api, world.patient_id)
        assert_integer_field(patient, "version", refreshed_version + 1)
        assert_integer_field(patient, "open_referral_count", 1)

    def test_a_reprice_carrying_a_consumed_stay_version_is_refused(
        self, api, analyst, second_analyst
    ):
        """The stay version a first re-price consumed cannot be spent on a second.

        The discharge leaves the stay at one version and holding one draft. The first
        analyst's re-price is accepted against that version and advances the stay, so the
        second analyst — still holding the version the discharge reported — is working from a
        view in which the first analyst's draft does not exist. The refusal must leave that
        draft alive, must add no third determination row, and must not itself move the stay's
        version.

        PRD 2.6: "If `expected_stay_version` does not equal the stay's current `version`, the create is rejected with `ERR_STALE_STAY_VERSION` and HTTP status 412."
        PRD 2.6: "The write supersedes whatever `DRAFT` determination the stay already holds, including one produced by the discharge cascade or by an earlier re-price, so an analyst holding an out-of-date view of the stay would otherwise discard a determination it never observed."

        Design: Corner/cross_cutting_complexity_layers/both_declared_occ_guards_reject_a_stale_parent_version
        """
        admission = _documented_discharged_stay(api)
        consumed_version = admission.stay["version"]
        first_draft = fixtures.reprice(
            api, admission.stay_id, consumed_version, headers=analyst
        )
        refreshed_version = fixtures.read_stay(api, admission.stay_id)["version"]
        assert refreshed_version == consumed_version + 1
        rows_before = fixtures.determinations_of(api, admission.stay_id)
        assert len(rows_before) == 2

        validate_error(
            api.reprice_stay(
                admission.stay_id,
                factories.reprice_payload(consumed_version),
                headers=second_analyst,
            ),
            ApiErrorId.ERR_STALE_STAY_VERSION,
        )

        assert (
            fixtures.read_determination(api, first_draft["id"])["status"]
            == DeterminationStatus.DRAFT
        )
        assert ids_of(fixtures.determinations_of(api, admission.stay_id)) == ids_of(rows_before)
        assert fixtures.read_stay(api, admission.stay_id)["version"] == refreshed_version

    def test_the_reprice_retried_on_the_refreshed_stay_version_voids_the_newer_draft(
        self, api, analyst, second_analyst
    ):
        """Refreshing the stay version is what licenses superseding the newer draft.

        The second analyst re-reads the stay, sees the version the first analyst's write left
        behind, and re-prices against it. That create is accepted and supersedes the draft it
        can now be presumed to have observed, marking it voided for the system's own reason
        rather than an operator's, and leaving the stay with exactly one live determination.

        PRD 3.7: "Before the new row is written, any existing determination on that stay whose `status` is `DRAFT` is flipped to `VOIDED` with `void_reason` set to the literal `SUPERSEDED`."
        PRD 2.6: "On success the stay's `version` advances by 1."

        Design: Corner/cross_cutting_complexity_layers/both_declared_occ_guards_reject_a_stale_parent_version
        """
        admission = _documented_discharged_stay(api)
        first_draft = fixtures.reprice(
            api, admission.stay_id, admission.stay["version"], headers=analyst
        )
        refreshed_version = fixtures.read_stay(api, admission.stay_id)["version"]

        second_draft = fixtures.reprice(
            api, admission.stay_id, refreshed_version, headers=second_analyst
        )

        superseded = fixtures.read_determination(api, first_draft["id"])
        assert superseded["status"] == DeterminationStatus.VOIDED
        assert superseded["void_reason"] == VoidReason.SUPERSEDED
        assert fixtures.sole_determination(api, admission.stay_id)["id"] == second_draft["id"]
        assert fixtures.read_stay(api, admission.stay_id)["version"] == refreshed_version + 1


OVERRIDE_REASON = "Sole regional PMV referral source; documented in the compliance plan."


def _mix_world(api) -> dict:
    """Two referral sources of different thresholds and five screened referrals.

    Four of the referrals name the acute-care source, whose ceiling is the base 25.00, and
    one names the critical-access source, whose ceiling is the expanded 50.00. Nothing is
    admitted yet, so the period's denominator is still zero.
    """
    world = fixtures.build_world(api)
    rural = fixtures.add_hospital(
        api, name="Rural Access", hospital_type=HospitalType.CRITICAL_ACCESS
    )
    metro_referrals = [fixtures.qualified_referral(api, world)]
    for _ in range(3):
        patient = fixtures.add_patient(api)
        metro_referrals.append(
            fixtures.qualified_referral(
                api,
                world,
                patient_id=patient["id"],
                patient_version=patient["version"],
            )
        )
    rural_patient = fixtures.add_patient(api)
    rural_referral = fixtures.qualified_referral(
        api,
        world,
        patient_id=rural_patient["id"],
        patient_version=rural_patient["version"],
        hospital_id=rural["id"],
    )
    return {
        "world": world,
        "metro": world.hospital,
        "rural": rural,
        "metro_referrals": metro_referrals,
        "rural_referral": rural_referral,
    }


def _admit_three_from_the_acute_source(api, mix) -> None:
    for referral in mix["metro_referrals"][:3]:
        fixtures.admit(api, referral["id"])


class TestTheSmallDenominatorGuardReleasesAtTheFourthAdmission:
    """A referral share that only becomes judgeable once the period holds four admissions."""

    def test_the_two_referral_sources_open_at_the_thresholds_their_own_attributes_dictate(
        self, api
    ):
        """A critical-access source is allowed twice the share an acute-care source is.

        The ceiling is a property of the hospital, fixed the moment it is registered: the
        acute-care source that is not co-located carries the base ceiling, and the
        critical-access source carries the expanded one. Both open with no admissions, a zero
        share and nothing to monitor.

        PRD 3.1: "Two of those inputs determine how much of the LTCH's admission mix this hospital is allowed to supply: a hospital's `threshold_pct` is 50.00 when `is_colocated` is true **or** its `hospital_type` is `CRITICAL_ACCESS`, and 25.00 otherwise."
        PRD 3.3: "A hospital's `share_pct` is its `admissions_in_period` divided by the period's `total_admissions`, multiplied by 100 and rounded half up to two decimal places; when the denominator is zero, `share_pct` is stored as 0.00."

        Design: Corner/cross_cutting_complexity_layers/the_small_denominator_guard_releases_at_the_fourth_admission
        """
        mix = _mix_world(api)

        assert_pct(mix["metro"], "threshold_pct", BASE_REFERRAL_THRESHOLD_PCT)
        assert_hospital_posture(mix["metro"], 0, 0.00, MonitoringState.COMPLIANT)
        assert_pct(mix["rural"], "threshold_pct", EXPANDED_REFERRAL_THRESHOLD_PCT)
        assert_hospital_posture(mix["rural"], 0, 0.00, MonitoringState.COMPLIANT)

    def test_a_source_supplying_the_entire_mix_stays_compliant_below_four_admissions(
        self, api
    ):
        """A 100.00 share is stored and left uncondemned while the denominator is too thin.

        One admission, then three, all from the same acute-care source: the share is the
        whole mix each time and stands far above that source's 25.00 ceiling. The monitoring
        state nevertheless remains compliant, because the gate is on the period's admission
        count and not on the share, and three is still below four. The share is stored all the
        same rather than suppressed.

        PRD 3.3: "If the period's `total_admissions` is fewer than 4, the mix is too thin to judge and `monitoring_state` is `COMPLIANT` regardless of the computed share; note that `share_pct` is still stored in that case, so a hospital may legitimately show a share of 100.00 while sitting at `COMPLIANT`."

        Design: Corner/cross_cutting_complexity_layers/the_small_denominator_guard_releases_at_the_fourth_admission
        """
        mix = _mix_world(api)

        fixtures.admit(api, mix["metro_referrals"][0]["id"])
        assert_hospital_posture(
            fixtures.read_hospital(api, mix["metro"]["id"]),
            1,
            100.00,
            MonitoringState.COMPLIANT,
        )

        for referral in mix["metro_referrals"][1:3]:
            fixtures.admit(api, referral["id"])

        assert_hospital_posture(
            fixtures.read_hospital(api, mix["metro"]["id"]),
            3,
            100.00,
            MonitoringState.COMPLIANT,
        )
        period = fixtures.read_period(api, mix["world"].period_id)
        assert_integer_field(period, "total_admissions", 3)
        assert period["total_admissions"] < MIN_ADMISSIONS_FOR_MONITORING

    def test_the_fourth_admission_made_by_another_source_is_what_breaches_the_first(
        self, api
    ):
        """The admission that condemns the acute-care source is one it did not make.

        The critical-access source's single admission moves the denominator from three to
        four, which releases the gate for every hospital at once. The acute-care source's own
        counter has not changed, yet its share is now judgeable at 75.00 against a ceiling of
        25.00 and it is in breach, while the source that actually made the admission sits at
        25.00 against a ceiling of 50.00 and is neither breached nor within the warning margin
        of it.

        PRD 3.3: "Because the denominator moved, `share_pct`, `threshold_pct` and `monitoring_state` are then recomputed for every referring hospital with a non-zero `admissions_in_period` plus any hospital whose counter just changed."
        PRD 3.3: "A single admission can therefore push a *different* hospital into `WARNING` or out of `BREACHED`."
        PRD 3.3: "Otherwise, if `share_pct` is **strictly greater** than `threshold_pct`, `monitoring_state` becomes `BREACHED` — a share of exactly 25.00 against a threshold of 25.00 is not a breach."

        Design: Corner/cross_cutting_complexity_layers/the_small_denominator_guard_releases_at_the_fourth_admission
        """
        mix = _mix_world(api)
        _admit_three_from_the_acute_source(api, mix)

        fixtures.admit(api, mix["rural_referral"]["id"])

        assert_hospital_posture(
            fixtures.read_hospital(api, mix["metro"]["id"]),
            3,
            75.00,
            MonitoringState.BREACHED,
        )
        assert_hospital_posture(
            fixtures.read_hospital(api, mix["rural"]["id"]),
            1,
            25.00,
            MonitoringState.COMPLIANT,
        )

    def test_the_explicit_recompute_reproduces_the_admission_driven_figures(self, api, officer):
        """The on-demand sweep agrees with the counters the admissions maintained.

        The whole point of offering a full recomputation is that it can be checked against
        the incrementally maintained figures. Running it over the same four admissions must
        leave both hospitals exactly where the admissions put them, and the two hospital
        counters must still sum to the period's own total.

        PRD 3.3: "A `ComplianceOfficer` may also re-run that whole recomputation on demand against an `OPEN` period, an idempotent sweep that rewrites `share_pct`, `threshold_pct` and `monitoring_state` for every referring hospital from the period's stored `total_admissions`."
        PRD 3.3: "The sweep exists precisely so that the incrementally maintained counters can be checked against a full recompute — the two must always agree."

        Design: Corner/cross_cutting_complexity_layers/the_small_denominator_guard_releases_at_the_fourth_admission
        """
        mix = _mix_world(api)
        _admit_three_from_the_acute_source(api, mix)
        fixtures.admit(api, mix["rural_referral"]["id"])

        recomputed = fixtures.recompute_shares(api, mix["world"].period_id, headers=officer)

        assert_integer_field(recomputed, "total_admissions", 4)
        metro = fixtures.read_hospital(api, mix["metro"]["id"])
        rural = fixtures.read_hospital(api, mix["rural"]["id"])
        assert_hospital_posture(metro, 3, 75.00, MonitoringState.BREACHED)
        assert_hospital_posture(rural, 1, 25.00, MonitoringState.COMPLIANT)
        assert_counters_reconcile(recomputed, [metro, rural])

    def test_an_admission_from_a_breached_source_is_refused_without_a_justification(
        self, api
    ):
        """Once the source is in breach its next admission needs a reason in writing.

        The acute-care source was compliant for its first three admissions and is in breach
        only because a fourth admission elsewhere released the gate. Its fifth referral is
        otherwise ready to admit, so the refusal is entirely about the missing justification,
        and the referral is left qualified rather than consumed.

        PRD 3.3: "When the referring hospital of the referral being admitted has `monitoring_state` `BREACHED`, admission is refused with `ERR_REFERRAL_SOURCE_BREACHED` unless the request supplies a non-empty `override_reason`."

        Design: Corner/cross_cutting_complexity_layers/the_small_denominator_guard_releases_at_the_fourth_admission
        """
        mix = _mix_world(api)
        _admit_three_from_the_acute_source(api, mix)
        fixtures.admit(api, mix["rural_referral"]["id"])
        fifth = mix["metro_referrals"][3]

        validate_error(
            api.admit_referral(fifth["id"], factories.admit_payload(), headers=INTAKE_HEADERS),
            ApiErrorId.ERR_REFERRAL_SOURCE_BREACHED,
        )

        assert fixtures.read_referral(api, fifth["id"])["status"] == ReferralStatus.CRITERIA_MET
        assert_integer_field(
            fixtures.read_period(api, mix["world"].period_id), "total_admissions", 4
        )

    def test_an_overridden_admission_is_recorded_and_still_counts_toward_the_share(self, api):
        """The override lets the admission through without exempting it from the mix.

        Supplying the justification admits the patient and stamps both the override flag and
        the text on the resulting stay. The admission is then an ordinary member of the mix:
        the acute-care source moves to four of five, its share rises to 80.00, it stays in
        breach, and the period's own total counts all five.

        PRD 3.3: "Supplying one lets the admission proceed, records `admitted_with_override` as true on the resulting stay and stores the justification in `override_reason`; admissions that did not need an override carry `admitted_with_override` false and `override_reason` null."
        PRD 3.3: "Otherwise, if `share_pct` is **strictly greater** than `threshold_pct`, `monitoring_state` becomes `BREACHED` — a share of exactly 25.00 against a threshold of 25.00 is not a breach."

        Design: Corner/cross_cutting_complexity_layers/the_small_denominator_guard_releases_at_the_fourth_admission
        """
        mix = _mix_world(api)
        _admit_three_from_the_acute_source(api, mix)
        fixtures.admit(api, mix["rural_referral"]["id"])
        fifth = mix["metro_referrals"][3]

        stay = fixtures.admit(api, fifth["id"], override_reason=OVERRIDE_REASON)

        assert stay["admitted_with_override"] is True
        assert stay["override_reason"] == OVERRIDE_REASON
        assert_hospital_posture(
            fixtures.read_hospital(api, mix["metro"]["id"]),
            4,
            80.00,
            MonitoringState.BREACHED,
        )
        assert_integer_field(
            fixtures.read_period(api, mix["world"].period_id), "total_admissions", 5
        )


def _undocumented_discharge(api) -> tuple:
    """An admission with no documentation at all, discharged two weeks in.

    No interdisciplinary note is filed and no weaning plan is opened, so all four mandatory
    disciplines are missing and the weaning gap counts: the score lands in the middle band
    and the cascade therefore stops at level three.
    """
    admission = fixtures.admitted_stay(api)
    fixtures.advance_clock(api, DISCHARGE_CLOCK)
    discharge_response = api.discharge_stay(
        admission.stay_id, factories.discharge_payload(), headers=NURSE_HEADERS
    )
    return admission, get_success_data(discharge_response, expected_status=200)


class TestEveryCascadeEffectIsVisibleInTheSameRequestCycle:
    """The discharge response, the reads that follow it, and the ledger, all without delay."""

    def test_none_of_the_discharge_figures_are_precomputed_at_admission(self, api):
        """The stay opens with the discharge-time fields unset rather than guessed at.

        Nothing about the length of stay, the short-stay comparison or the payment percentage
        can be known while the patient is still in the bed, so the admission response carries
        them as null and the payment dimension as pending. Only the carried-day counter, which
        genuinely starts at zero, holds a number.

        PRD 3.3: "Its `carried_los_days` starts at 0, its `interruption_days_total` at 0, its `interruption_count` at 0, and its `interrupted_parent_stay_id`, `resumed_at`, `discharged_at`, `covered_los_days`, `sso_threshold_days`, `short_stay_outlier_applied` and `discharge_payment_pct` all start null."
        PRD 3.6: "Before discharge all three of `covered_los_days`, `sso_threshold_days` and `short_stay_outlier_applied` are null."

        Design: Corner/consistency_model/every_cascade_effect_is_visible_in_the_same_request_cycle
        """
        admission = fixtures.admitted_stay(api)

        assert_stay_dimensions(
            admission.stay, ClinicalStatus.ADMITTED, PaymentReviewStatus.PENDING
        )
        assert_unset(
            admission.stay,
            "discharged_at",
            "covered_los_days",
            "sso_threshold_days",
            "short_stay_outlier_applied",
            "discharge_payment_pct",
        )
        assert_integer_field(admission.stay, "carried_los_days", 0)

    def test_the_discharge_response_body_already_carries_every_derived_value(self, api):
        """One call returns the whole of level one and the percentage level two mirrored back.

        The response to the discharge is the only thing the client is given, so it must
        already hold the fourteen covered days, the twenty-five-day short-stay threshold that
        those days fall under, the flag that comparison sets, the payment percentage the
        determination mirrored onto the stay, and the advanced payment dimension. A client
        that had to read the stay again to see any of them would be observing a delay the
        contract does not allow.

        PRD 2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
        PRD 3.6: "*Level one* is the discharge itself: `clinical_status` becomes `DISCHARGED`, `discharged_at` is stamped, `discharge_disposition` and `estimated_cost_cents` are stored, the three length-of-stay fields above are computed, and the stay's `version` increases by 1."
        PRD 3.6: "That determination is priced by the full dual-variant calculation of §3.7, its `recalculation_reason` is null because no analyst asked for it, and its `discharge_payment_pct` is mirrored onto the stay's own `discharge_payment_pct` field."

        Design: Corner/consistency_model/every_cascade_effect_is_visible_in_the_same_request_cycle
        """
        _admission, discharged = _undocumented_discharge(api)

        assert_stay_dimensions(
            discharged, ClinicalStatus.DISCHARGED, PaymentReviewStatus.PRICED
        )
        assert_integer_field(discharged, "covered_los_days", COVERED_LOS_DAYS)
        assert_integer_field(discharged, "sso_threshold_days", DRG_207_SSO_THRESHOLD_DAYS)
        assert discharged["short_stay_outlier_applied"] is True
        assert_pct(discharged, "discharge_payment_pct", DISCHARGE_PCT)
        assert_instant_equals(
            discharged["discharged_at"], DISCHARGE_CLOCK, field="discharged_at"
        )

    def test_the_read_that_immediately_follows_the_discharge_agrees_field_for_field(self, api):
        """The stored stay and the response the discharge returned are the same record.

        The read is issued with nothing in between, and it must agree on every derived field
        rather than converging on it. Reading a second time must return the same values again,
        which is what rules out a figure that settles only after the first observation.

        PRD 2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
        PRD 3.6: "The stay's `short_stay_outlier_applied` flag is then true exactly when `covered_los_days` is less than or equal to `sso_threshold_days`."

        Design: Corner/consistency_model/every_cascade_effect_is_visible_in_the_same_request_cycle
        """
        admission, discharged = _undocumented_discharge(api)
        compared_fields = (
            "clinical_status",
            "payment_review_status",
            "covered_los_days",
            "sso_threshold_days",
            "short_stay_outlier_applied",
            "discharge_payment_pct",
            "version",
        )

        first_read = fixtures.read_stay(api, admission.stay_id)
        second_read = fixtures.read_stay(api, admission.stay_id)

        for field in compared_fields:
            assert first_read[field] == discharged[field], field
            assert second_read[field] == first_read[field], field
        assert_instant_equals(first_read["discharged_at"], discharged["discharged_at"])

    def test_the_child_rows_the_cascade_created_are_listed_on_the_very_next_call(
        self, api, officer
    ):
        """Levels two and three are readable immediately, and level four correctly absent.

        The determination the discharge priced is already listed against the stay, in draft,
        totalling the short-stay amount and attributed to the system rather than to the nurse
        who discharged. The review is listed too, scored at sixty-seven, which is the middle
        band — so no query was auto-issued and the query listing for this stay is genuinely
        empty rather than pending.

        PRD 3.6: "*Level two* follows because the stay became `DISCHARGED`: a `PaymentDetermination` is created for it with `status` `DRAFT` and `priced_by_user_id` set to the literal `SYSTEM` rather than to any human `X-User-ID`."
        PRD 3.6: "*Level three* follows because a determination now exists: a `DenialRiskReview` is opened for the stay with `status` `OPEN`, `opened_by_user_id` recording the user whose action triggered the cascade (or `SYSTEM` where no human acted), `resolved_by_user_id` and `resolution_note` null, and its `as_documented_score`, `missing_discipline_count`, `answered_query_count`, `effective_score` and `risk_band` computed as set out in §3.8."
        PRD 3.6: "When the band is `MODERATE` or `LOW`, no query is issued and the review stays `OPEN`."

        Design: Corner/consistency_model/every_cascade_effect_is_visible_in_the_same_request_cycle
        """
        admission, _discharged = _undocumented_discharge(api)

        determinations, _det_meta = validate_paginated(
            api.list_stay_determinations(admission.stay_id, headers=officer)
        )
        assert len(determinations) == 1
        determination = determinations[0]
        assert determination["status"] == DeterminationStatus.DRAFT
        assert determination["priced_by_user_id"] == SYSTEM_ACTOR
        assert_cents(determination, "total_payment_cents", TOTAL_PAYMENT_CENTS)

        reviews, _rev_meta = validate_paginated(
            api.list_stay_reviews(admission.stay_id, headers=officer)
        )
        assert len(reviews) == 1
        review = reviews[0]
        assert review["status"] == ReviewStatus.OPEN
        assert_integer_field(review, "effective_score", UNDOCUMENTED_SCORE)
        assert review["risk_band"] == UNDOCUMENTED_BAND
        assert UNDOCUMENTED_BAND == RiskBand.MODERATE

        queries, query_meta = validate_paginated(
            api.list_queries(params={"stay_id": admission.stay_id}, headers=officer)
        )
        assert queries == []
        assert query_meta["total_count"] == 0

    def test_the_period_ledger_is_never_observed_lagging_a_final_determination(
        self, api, officer, second_analyst
    ):
        """The finalize response and the period read that follows it agree to the cent.

        The period opens empty. The review is cleared, and the resolve response itself already
        reports the cleared status. The finalize response then reports the determination final
        with its total, and the period read issued straight afterwards already carries that
        same total and a count of one: there is no window in which the determination is final
        while the ledger still says zero. The admission counter the admit incremented is
        likewise already there.

        PRD 2.7: "A newly opened period begins with `total_admissions` 0, `total_payment_cents` 0 and `final_determination_count` 0."
        PRD 3.7: "On success `finalized_by_user_id` records the acting `X-User-ID`, the stay's `payment_review_status` moves `PRICED → FINALIZED`, the period's `total_payment_cents` is increased by this determination's `total_payment_cents`, and the period's `final_determination_count` is increased by 1."

        Design: Corner/consistency_model/every_cascade_effect_is_visible_in_the_same_request_cycle
        """
        admission, _discharged = _undocumented_discharge(api)
        period_at_open = admission.world.period
        assert_period_ledger(
            period_at_open, total_payment_cents=0, final_determination_count=0
        )
        review = fixtures.sole_review(api, admission.stay_id)
        determination = fixtures.sole_determination(api, admission.stay_id)

        resolved = get_success_data(
            api.resolve_review(
                review["id"],
                factories.resolve_review_payload(outcome=ReviewOutcome.CLEARED),
                headers=officer,
            )
        )
        assert resolved["status"] == ReviewStatus.CLEARED

        finalized = get_success_data(
            api.finalize_determination(determination["id"], headers=second_analyst)
        )

        assert finalized["status"] == DeterminationStatus.FINAL
        assert_cents(finalized, "total_payment_cents", TOTAL_PAYMENT_CENTS)
        period = fixtures.read_period(api, admission.world.period_id)
        assert_period_ledger(
            period,
            total_payment_cents=TOTAL_PAYMENT_CENTS,
            final_determination_count=1,
        )
        assert_integer_field(period, "total_admissions", 1)

    def test_the_stay_listing_reflects_both_writes_with_no_reindex_delay(
        self, api, officer, second_analyst
    ):
        """A filtered collection read sees the discharge and the finalize at once.

        The stay is listed by its clinical status immediately after the discharge, and listed
        again by the same filter after the finalize, where it must already report the finalized
        payment dimension. A collection that lagged either write would hand an auditor a view
        the single-record reads contradict.

        PRD 3.6: "This second dimension is genuinely independent: `payment_review_status` moves while `clinical_status` stays at `DISCHARGED`."
        PRD 3.7: "On success `finalized_by_user_id` records the acting `X-User-ID`, the stay's `payment_review_status` moves `PRICED → FINALIZED`, the period's `total_payment_cents` is increased by this determination's `total_payment_cents`, and the period's `final_determination_count` is increased by 1."

        Design: Corner/consistency_model/every_cascade_effect_is_visible_in_the_same_request_cycle
        """
        admission, _discharged = _undocumented_discharge(api)

        listed, meta = validate_paginated(
            api.list_stays(
                params={"clinical_status": ClinicalStatus.DISCHARGED}, headers=officer
            )
        )
        assert ids_of(listed) == [admission.stay_id]
        assert meta["total_count"] == 1
        assert listed[0]["payment_review_status"] == PaymentReviewStatus.PRICED

        fixtures.resolve_review(
            api, fixtures.sole_review(api, admission.stay_id)["id"]
        )
        fixtures.finalize(
            api,
            fixtures.sole_determination(api, admission.stay_id)["id"],
            headers=second_analyst,
        )

        relisted, _relisted_meta = validate_paginated(
            api.list_stays(
                params={"clinical_status": ClinicalStatus.DISCHARGED}, headers=officer
            )
        )
        assert ids_of(relisted) == [admission.stay_id]
        assert relisted[0]["payment_review_status"] == PaymentReviewStatus.FINALIZED
