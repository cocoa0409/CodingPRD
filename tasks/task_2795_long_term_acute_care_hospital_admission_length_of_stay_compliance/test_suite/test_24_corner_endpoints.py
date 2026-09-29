"""
Endpoint-surface behaviour: round trips, action endpoints and stored projections.

The tests here pin what a caller observes at the boundary of a single operation — that a
created resource reads back field for field, that an action endpoint with an empty body
still performs every effect the specification attributes to it, that a read is a pure
projection of values earlier writes stored, and that one optional field on the re-pricing
endpoint chooses which rate entry the whole calculation runs against.
"""

import pytest

from test_helpers import (
    CLOCK_EPOCH,
    CRITERIA_SET_A,
    DRG_207,
    DRG_207_SSO_THRESHOLD_DAYS,
    DRG_573,
    ClinicalStatus,
    CriteriaSetStatus,
    DeterminationStatus,
    OPAQUE_ROLE_HEADERS,
    PaymentReviewStatus,
    PeriodStatus,
    QueryStatus,
    QueryType,
    ReviewStatus,
    UserRole,
    VoidReason,
    WeaningPlanStatus,
    assert_cents,
    assert_instant_equals,
    assert_integer_field,
    assert_pct,
    assert_period_ledger,
    assert_stay_dimensions,
    assert_unset,
    factories,
    fixtures,
    get_success_data,
    make_attending_physician_headers,
    validate_paginated,
)


def _stay_discharged_on_day_fourteen(api, world=None, **admission_kwargs):
    """An admitted stay carried to discharge on 2026-08-15, fourteen whole days in.

    No interdisciplinary notes are filed, so the denial-risk review scores all four
    mandatory disciplines as missing and the weaning gap as present.
    """
    admission = fixtures.admitted_stay(api, world, **admission_kwargs)
    fixtures.advance_clock(api, "2026-08-15T00:00:00Z")
    return fixtures.discharged_stay(api, admission=admission, file_notes=False)


class TestCriteriaSetRoundTrip:
    """Publishing a criteria set and reading it back."""

    def test_a_published_criteria_set_reads_back_field_for_field(self, api, intake):
        """Every supplied threshold and the server-set status survive the round trip.

        The publication supplies a label, an effective date and four clinical thresholds
        and supplies no status at all. The read must return the same six values plus the
        status the server chose, and `effective_from` must come back as the plain calendar
        date that was sent rather than widened into an instant, because the field is
        declared as a calendar date from which the set may be pinned.

        PRD 3.1: "Publishing a set names a `label` (1 to 40 characters, unique), an `effective_from` calendar date from which the set may be pinned by screening, and four clinical thresholds: `pmv_min_vent_hours` (from 1 to 1000) and `pmv_min_icu_days` (from 0 to 60) govern the prolonged-mechanical-ventilation track, while `wound_min_stage` (from 1 to 4) and `wound_min_count` (from 1 to 20) govern the complex-wound track."
        PRD 3.1: "On publication, the new set takes `status` `ACTIVE` and every previously `ACTIVE` set flips to `SUPERSEDED` — which is exactly why a referral that pinned an older set can no longer be admitted until it is re-screened."
        PRD 4: "Status codes follow one rule: an operation that brings a new resource into existence returns 201 Created, and every other successful operation — a read, a list, a state transition on an existing resource, a counter recomputation — returns 200 OK."

        Design: Corner/endpoints/criteria_set_create_and_read_round_trip
        """
        created = get_success_data(
            api.create_criteria_set(factories.criteria_set_payload(), headers=OPAQUE_ROLE_HEADERS[UserRole.COMPLIANCE_OFFICER]),
            expected_status=201,
        )
        read = get_success_data(api.get_criteria_set(created["id"], headers=intake), expected_status=200)

        assert read["id"] == created["id"]
        assert read["label"] == created["label"] == CRITERIA_SET_A["label"]
        assert read["effective_from"] == created["effective_from"] == CRITERIA_SET_A["effective_from"]
        assert_integer_field(read, "pmv_min_vent_hours", CRITERIA_SET_A["pmv_min_vent_hours"])
        assert_integer_field(read, "pmv_min_icu_days", CRITERIA_SET_A["pmv_min_icu_days"])
        assert_integer_field(read, "wound_min_stage", CRITERIA_SET_A["wound_min_stage"])
        assert_integer_field(read, "wound_min_count", CRITERIA_SET_A["wound_min_count"])
        assert created["status"] == CriteriaSetStatus.ACTIVE
        assert read["status"] == CriteriaSetStatus.ACTIVE

    @pytest.mark.parametrize("role", list(UserRole.ALL))
    def test_every_role_may_read_a_criteria_set(self, api, role):
        """All five roles see the same criteria set with the same active status.

        The read is not a privileged operation: an intake coordinator screening a referral,
        a nurse documenting a stay, a physician answering a query and an analyst pricing a
        discharge all need to know which thresholds were in force, so every role reaches it.

        PRD 3.1: "Any role may read a criteria set and observe whether a newer publication has superseded it."

        Design: Corner/endpoints/criteria_set_create_and_read_round_trip
        """
        criteria_set = fixtures.publish_criteria_set(api)
        physician = fixtures.add_physician(api)
        headers = (
            make_attending_physician_headers(physician["id"])
            if role == UserRole.ATTENDING_PHYSICIAN
            else OPAQUE_ROLE_HEADERS[role]
        )

        read = get_success_data(api.get_criteria_set(criteria_set["id"], headers=headers), expected_status=200)

        assert read["id"] == criteria_set["id"]
        assert read["status"] == CriteriaSetStatus.ACTIVE
        assert read["label"] == criteria_set["label"]


class TestRescoreExpiresAnOverdueQuery:
    """One rescore call sweeps an overdue query, reopens the review and re-scores it."""

    @staticmethod
    def _review_with_an_overdue_query(api):
        """A discharged stay whose only query has passed its due instant unanswered."""
        admission = _stay_discharged_on_day_fourteen(api)
        review = fixtures.sole_review(api, admission.stay_id)
        query = fixtures.issue_query(api, review["id"], query_type=QueryType.VENT_WEANING_RATIONALE)
        fixtures.advance_clock(api, "2026-08-19T00:00:00Z")
        return admission, review, query

    def test_a_rescore_expires_a_query_whose_due_instant_has_already_passed(self, api, officer):
        """The lazy expiry sweep moves an overdue `ISSUED` query to `EXPIRED`.

        The query is issued at 2026-08-15T00:00:00Z, so its due instant is 72 hours later at
        2026-08-18T00:00:00Z. Advancing the clock a further day changes nothing by itself;
        it is the rescore that reads the deadline and flips the query. Expiry is not a
        close, so neither `answered_at` nor `closed_by_user_id` is written.

        PRD 3.8: "The new query carries `denial_risk_review_id` naming the issuing review and `stay_id` copied from that review for direct filtering, enters `status` `ISSUED` with `issued_at` stamped from the logical clock and `due_at` computed as `issued_at` plus 72 hours — three full days — and records the acting nurse's `X-User-ID` as `issued_by_user_id`."
        PRD 3.8: "Rescoring recomputes both variants, refreshes `effective_score`, `risk_band`, `missing_discipline_count` and `answered_query_count`, and additionally performs a lazy expiry sweep: every `DocumentationQuery` on the review whose `status` is `ISSUED` and whose `due_at` has already passed the current logical instant moves `ISSUED → EXPIRED`."

        Design: Corner/endpoints/rescore_expires_an_overdue_query_and_reopens_the_review
        """
        _admission, review, query = self._review_with_an_overdue_query(api)
        assert query["status"] == QueryStatus.ISSUED
        assert_instant_equals(query["issued_at"], "2026-08-15T00:00:00Z", "issued_at")
        assert_instant_equals(query["due_at"], "2026-08-18T00:00:00Z", "due_at")

        get_success_data(api.rescore_review(review["id"], headers=officer), expected_status=200)

        swept = fixtures.read_query(api, query["id"])
        assert swept["status"] == QueryStatus.EXPIRED
        assert_unset(swept, "answered_at", "answered_by_physician_id", "closed_by_user_id", "response_text")

    def test_the_review_reopens_once_no_issued_query_remains(self, api, officer):
        """Sweeping the last `ISSUED` query returns the review from `QUERIES_ISSUED` to `OPEN`.

        Issuing the query drove the review out of `OPEN`; the rescore that expires that same
        query leaves no outstanding question, so the review comes back to `OPEN` and is
        available for another round of querying.

        PRD 3.8: "A review in `OPEN` moves `OPEN → QUERIES_ISSUED`; a review already in `QUERIES_ISSUED` stays there."
        PRD 3.8: "When the review was in `QUERIES_ISSUED` and no query remains in `ISSUED` after the sweep, the rescore returns the review to `OPEN` — the cycle `OPEN → QUERIES_ISSUED → OPEN` may repeat for as many rounds of querying as the case needs."

        Design: Corner/endpoints/rescore_expires_an_overdue_query_and_reopens_the_review
        """
        _admission, review, _query = self._review_with_an_overdue_query(api)
        assert fixtures.read_review(api, review["id"])["status"] == ReviewStatus.QUERIES_ISSUED

        rescored = get_success_data(api.rescore_review(review["id"], headers=officer), expected_status=200)

        assert rescored["status"] == ReviewStatus.OPEN
        assert fixtures.read_review(api, review["id"])["status"] == ReviewStatus.OPEN
        still_issued = fixtures.queries_of(
            api, denial_risk_review_id=review["id"], status=QueryStatus.ISSUED
        )
        assert still_issued == [], "an expired query must not still be listed as ISSUED"

    def test_an_expired_query_earns_no_answered_query_credit(self, api, officer):
        """With no answer on the chart the effective score is still the as-documented score.

        The chart carries no interdisciplinary note in any of the four mandatory disciplines
        and no weaning plan, and its determination applied the short-stay outlier: 8 points
        for each of four missing disciplines, 15 for the weaning gap and 20 for the
        short-stay flag total 67, which is the `MODERATE` band. The expired query earns no
        credit, so `answered_query_count` stays 0 and the query-adjusted variant is still
        unset.

        PRD 3.8: "The count of answered queries, `answered_query_count`, counts the review's `DocumentationQuery` rows whose `status` is `ANSWERED` or `CLOSED`; queries in `ISSUED`, `EXPIRED` or `VOIDED` earn no credit."
        PRD 3.8: "`query_adjusted_score` is null until a rescore observes a non-zero `answered_query_count`."
        PRD 3.8: "The review's `effective_score` is the `query_adjusted_score` when `answered_query_count` is greater than 0, and the `as_documented_score` otherwise."
        PRD 3.8: "The raw total is then 8 points per missing discipline, plus 15 points if the weaning gap is present, plus 20 points if the short-stay-outlier flag is set, plus 10 points if the site-neutral flag is set, plus half a point per day of length-of-stay excess."

        Design: Corner/endpoints/rescore_expires_an_overdue_query_and_reopens_the_review
        """
        _admission, review, _query = self._review_with_an_overdue_query(api)
        assert_integer_field(review, "as_documented_score", 67)

        rescored = get_success_data(api.rescore_review(review["id"], headers=officer), expected_status=200)

        assert_integer_field(rescored, "answered_query_count", 0)
        assert_integer_field(rescored, "missing_discipline_count", 4)
        assert_integer_field(rescored, "as_documented_score", 67)
        assert_integer_field(rescored, "effective_score", 67)
        assert_unset(rescored, "query_adjusted_score")


class TestWeaningCloseLinksTheClosingPhysician:
    """The close writes the acting physician onto the plan, and the listing finds it there."""

    @staticmethod
    def _plan_ready_for_a_vent_dependent_close(api):
        """A regressed plan with three failed trials, plus a second uninvolved pulmonologist."""
        admission = fixtures.admitted_stay(api)
        other_physician = fixtures.add_physician(api, full_name="Dr Pat Pulmo")
        plan = fixtures.open_weaning_plan(api, admission.stay_id, vent_hours_total=100)
        for _ in range(3):
            plan = fixtures.failed_sbt(api, plan["id"])
        return admission, plan, other_physician

    def test_the_close_stamps_the_acting_physician_and_the_logical_clock(self, api):
        """`closed_by_physician_id` comes from the request header, not from any body field.

        The close body carries only an outcome, so the only place the plan's physician
        foreign key can come from is the acting identity. The plan opened with both
        `closed_at` and `closed_by_physician_id` null and, after three failed trials, sits in
        `REGRESSED` with an attempt count of exactly 3 — the minimum a ventilator-dependent
        close demands. The clock has not been advanced, so the stamp is the starting instant.

        PRD 3.4: "A new plan carries `stay_id`, enters `status` `SBT_TRIAL` with `current_step` 0, `sbt_attempt_count` 0, `consecutive_failed_sbt` 0, `max_tolerated_sbt_hours` 0, `liberation_eligible` false, and `last_progression_at`, `closed_at` and `closed_by_physician_id` all null."
        PRD 3.4: "Both closes stamp `closed_at` from the logical clock and write the acting physician's `X-User-ID` into `closed_by_physician_id`, and both require the acting physician to have `specialty` `PULMONOLOGY` and `credential_status` `ACTIVE`."
        PRD 3.4: "A `VENT_DEPENDENT` close is reachable from `SBT_TRIAL`, from `PROGRESSING` and from `REGRESSED`, and requires `sbt_attempt_count` of at least 3; a plan with fewer attempts is refused with `ERR_INSUFFICIENT_SBT_ATTEMPTS`."
        PRD 2.1: "When `X-User-Role` is `AttendingPhysician`, `X-User-ID` is the `id` of the acting `Physician` row; ownership and credential checks on any resource that references a `Physician` compare the resource's physician foreign-key field to `X-User-ID`, and it is this value that gets stamped as `closed_by_physician_id` when a weaning plan is closed and as `answered_by_physician_id` when a query is answered."

        Design: Corner/endpoints/weaning_close_links_the_plan_to_the_closing_physician
        """
        _admission, plan, other_physician = self._plan_ready_for_a_vent_dependent_close(api)
        assert plan["status"] == WeaningPlanStatus.REGRESSED
        assert_integer_field(plan, "sbt_attempt_count", 3)
        assert_unset(plan, "closed_at", "closed_by_physician_id")

        closed = fixtures.close_plan(
            api,
            plan["id"],
            WeaningPlanStatus.VENT_DEPENDENT,
            make_attending_physician_headers(other_physician["id"]),
        )

        assert closed["status"] == WeaningPlanStatus.VENT_DEPENDENT
        assert closed["closed_by_physician_id"] == other_physician["id"]
        assert_instant_equals(closed["closed_at"], CLOCK_EPOCH, "closed_at")

    def test_the_listing_finds_the_plan_by_its_closing_physician_and_not_by_another(self, api):
        """Filtering on `closed_by_physician_id` returns the closer's plan and nobody else's.

        Two credentialed pulmonologists exist and only one of them closed the plan. The
        filter on the closing physician must return exactly that one plan, carrying its own
        `stay_id`; the same filter for the physician who never touched the plan must come
        back empty. Filtering instead on the terminal status reaches the same single plan.

        PRD 3.4: "Weaning plans are readable individually and listable with optional filters on `stay_id`, `closed_by_physician_id` and `status`, alongside `limit` and `offset`."

        Design: Corner/endpoints/weaning_close_links_the_plan_to_the_closing_physician
        """
        admission, plan, other_physician = self._plan_ready_for_a_vent_dependent_close(api)
        fixtures.close_plan(
            api,
            plan["id"],
            WeaningPlanStatus.VENT_DEPENDENT,
            make_attending_physician_headers(other_physician["id"]),
        )

        by_closer, _meta = validate_paginated(
            api.list_weaning_plans(
                params={"closed_by_physician_id": other_physician["id"]},
                headers=OPAQUE_ROLE_HEADERS[UserRole.COMPLIANCE_OFFICER],
            )
        )
        by_bystander, _meta = validate_paginated(
            api.list_weaning_plans(
                params={"closed_by_physician_id": admission.world.physician_id},
                headers=OPAQUE_ROLE_HEADERS[UserRole.COMPLIANCE_OFFICER],
            )
        )
        by_status, _meta = validate_paginated(
            api.list_weaning_plans(
                params={"status": WeaningPlanStatus.VENT_DEPENDENT},
                headers=OPAQUE_ROLE_HEADERS[UserRole.COMPLIANCE_OFFICER],
            )
        )

        assert len(by_closer) == 1
        assert by_closer[0]["id"] == plan["id"]
        assert by_closer[0]["stay_id"] == admission.stay_id
        assert by_bystander == [], "a physician who never closed this plan matches nothing"
        assert [item["id"] for item in by_status] == [plan["id"]]


class TestStayAndPeriodReadsReturnStoredValues:
    """Both reads are projections of what earlier writes stored, and change nothing."""

    def test_the_stay_read_returns_the_length_of_stay_figures_the_discharge_computed(self, api, officer):
        """Covered days, the short-stay threshold and the payment percentage read back as stored.

        The patient is admitted on 2026-08-01 and discharged on 2026-08-15, so the whole-day
        count between the two calendar dates is 14, and with no interruption on the stay
        `carried_los_days` and `interruption_days_total` are both 0, leaving
        `covered_los_days` at 14. The DRG in force averages 30 days, so the short-stay
        threshold is five-sixths of 30 floored, which is 25, and 14 days is at or under it, so
        the outlier applies. The short-stay standard base is the smallest of 2,800,000,
        1,512,000 and 2,400,000, which is 1,512,000 against a full standard amount of
        6,000,000, giving a discharge payment percentage of 25.20.

        PRD 2.5: "The day count between two instants is the difference between their UTC *calendar dates*, expressed in whole days; the later day is not itself counted."
        PRD 3.6: "The stay's `covered_los_days` is then `carried_los_days` plus that segment length, minus `interruption_days_total`."
        PRD 3.6: "Alongside it, `sso_threshold_days` is computed as five-sixths of the `alos_days` of the DRG in force, rounded **down** to a whole number and never rounded to nearest."
        PRD 3.6: "The stay's `short_stay_outlier_applied` flag is then true exactly when `covered_los_days` is less than or equal to `sso_threshold_days`."
        PRD 3.7: "The percentage is mirrored onto the stay's `discharge_payment_pct`, which is null until a determination exists."
        PRD 3.6: "The stay's second status dimension advances `PENDING → PRICED`."

        Design: Corner/endpoints/stay_and_period_reads_return_stored_derived_values
        """
        admission = _stay_discharged_on_day_fourteen(api)

        read = get_success_data(api.get_stay(admission.stay_id, headers=officer), expected_status=200)

        assert_integer_field(read, "covered_los_days", 14)
        assert_integer_field(read, "sso_threshold_days", DRG_207_SSO_THRESHOLD_DAYS)
        assert read["short_stay_outlier_applied"] is True
        assert_pct(read, "discharge_payment_pct", 25.20)
        assert_integer_field(read, "carried_los_days", 0)
        assert_integer_field(read, "interruption_days_total", 0)
        assert_integer_field(read, "interruption_count", 0)
        assert_stay_dimensions(read, ClinicalStatus.DISCHARGED, PaymentReviewStatus.PRICED)

    def test_repeated_reads_by_different_roles_agree_and_leave_the_version_alone(self, api, officer):
        """A read is not a mutation, so the stay's `version` is identical across both reads.

        The compliance officer and the attending physician ask the same question of the same
        stay. Because `version` only moves on a mutation, both answers carry the version the
        discharge left behind, and the derived figures are identical for both callers: the
        read projects stored state rather than recomputing it per caller.

        PRD 2.4: "Most resources additionally carry `updated_at`, refreshed on every mutation, and `version`, an integer that begins at 1 on creation and increments by exactly 1 on every mutation of that row."

        Design: Corner/endpoints/stay_and_period_reads_return_stored_derived_values
        """
        admission = _stay_discharged_on_day_fourteen(api)
        version_after_discharge = admission.stay["version"]

        as_officer = get_success_data(api.get_stay(admission.stay_id, headers=officer), expected_status=200)
        as_physician = get_success_data(
            api.get_stay(admission.stay_id, headers=admission.world.physician_headers),
            expected_status=200,
        )

        assert as_officer["version"] == version_after_discharge
        assert as_physician["version"] == version_after_discharge
        assert as_physician["covered_los_days"] == as_officer["covered_los_days"]
        assert_pct(as_physician, "discharge_payment_pct", 25.20)
        assert as_physician["payment_review_status"] == as_officer["payment_review_status"]

    def test_the_period_ledger_ignores_a_determination_that_is_still_a_draft(self, api, analyst):
        """The period counts the admission but not the money, because nothing is `FINAL` yet.

        The cascade priced the stay, but only finalization moves money into the period. So
        the period read shows one admission and an untouched ledger — the figures a newly
        opened period starts from — while its status is still `OPEN`.

        PRD 2.7: "A newly opened period begins with `total_admissions` 0, `total_payment_cents` 0 and `final_determination_count` 0."
        PRD 3.3: "The admission also does four things beyond the stay itself: the referral's `status` becomes `ADMITTED`, `Patient.open_referral_count` is recomputed to 0, the period's `total_admissions` is increased by 1, and the referring hospital's `admissions_in_period` is increased by 1."
        PRD 3.7: "On success `finalized_by_user_id` records the acting `X-User-ID`, the stay's `payment_review_status` moves `PRICED → FINALIZED`, the period's `total_payment_cents` is increased by this determination's `total_payment_cents`, and the period's `final_determination_count` is increased by 1."

        Design: Corner/endpoints/stay_and_period_reads_return_stored_derived_values
        """
        admission = _stay_discharged_on_day_fourteen(api)
        assert admission.determination["status"] == DeterminationStatus.DRAFT

        period = get_success_data(
            api.get_period(admission.world.period_id, headers=analyst), expected_status=200
        )

        assert_integer_field(period, "total_admissions", 1)
        assert_period_ledger(period, total_payment_cents=0, final_determination_count=0)
        assert period["status"] == PeriodStatus.OPEN


class TestOverrideDrgRateConditionallyReprices:
    """One optional field decides which rate entry the whole re-pricing runs against."""

    @staticmethod
    def _priced_stay_with_a_second_rate_on_file(api):
        """A stay priced against DRG 207 by the cascade, with DRG 573 also loaded."""
        world = fixtures.build_world(api)
        other_rate = fixtures.add_drg_rate(api, **DRG_573)
        admission = _stay_discharged_on_day_fourteen(api, world)
        return admission, other_rate

    def test_the_override_rate_is_the_one_snapshotted_onto_the_new_determination(self, api, analyst):
        """Supplying `override_drg_rate_id` makes that entry the DRG in force for the re-price.

        The referral pinned DRG 207 and the cascade priced against it. The analyst then
        re-prices naming DRG 573, so every snapshot field on the new determination is copied
        from DRG 573 rather than from the referral's rate, while `covered_los_days_used` is
        still the 14 days the stay actually delivered. The supplied reason is echoed back,
        because on this path an analyst did ask for the pricing.

        PRD 3.6: "The \"DRG in force\" means the `DrgRateEntry` identified by the pricing request's `override_drg_rate_id` when one was supplied, and otherwise the `DrgRateEntry` named by the admitting referral's `drg_rate_id`."
        PRD 3.7: "The snapshot fields are `drg_code_used`, `relative_weight_used`, `alos_days_used`, `ipps_per_diem_used_cents`, `ipps_full_used_cents` — copied from the DRG in force — and `covered_los_days_used`, copied from the stay's `covered_los_days` at pricing time."
        PRD 3.7: "The request carries `expected_stay_version` as described in §2.6, a required `recalculation_reason` explaining why the stay is being re-priced, and an optional `override_drg_rate_id` naming a different `DrgRateEntry` to price against — useful when a coding review changed the DRG."

        Design: Corner/endpoints/override_drg_rate_id_conditionally_reprices_the_stay
        """
        admission, other_rate = self._priced_stay_with_a_second_rate_on_file(api)
        assert admission.determination["drg_code_used"] == DRG_207["drg_code"]
        assert_cents(admission.determination, "total_payment_cents", 1512000)

        repriced = fixtures.reprice(
            api,
            admission.stay_id,
            expected_stay_version=admission.stay["version"],
            recalculation_reason="Coding audit reassigned the stay to DRG 573.",
            override_drg_rate_id=other_rate["id"],
            headers=analyst,
        )

        assert repriced["status"] == DeterminationStatus.DRAFT
        assert repriced["drg_code_used"] == DRG_573["drg_code"]
        assert repriced["relative_weight_used"] == DRG_573["relative_weight"]
        assert_integer_field(repriced, "alos_days_used", DRG_573["alos_days"])
        assert_cents(repriced, "ipps_per_diem_used_cents", DRG_573["ipps_comparable_per_diem_cents"])
        assert_cents(repriced, "ipps_full_used_cents", DRG_573["ipps_comparable_full_cents"])
        assert_integer_field(repriced, "covered_los_days_used", 14)
        assert repriced["recalculation_reason"] == "Coding audit reassigned the stay to DRG 573."

    def test_the_displaced_draft_is_voided_as_superseded_and_the_stay_tracks_the_newest(self, api, analyst):
        """The re-price leaves exactly one live determination and the stay follows it.

        The cascade's draft is flipped to `VOIDED` with the reserved reason `SUPERSEDED`
        before the replacement row is written, so at no point does the stay hold two live
        determinations. The stay's own `version` advances by one — which is why a second
        re-price needs a freshly read version — and the stay's `discharge_payment_pct` now
        mirrors the new determination's percentage rather than the voided one's.

        PRD 3.7: "Before the new row is written, any existing determination on that stay whose `status` is `DRAFT` is flipped to `VOIDED` with `void_reason` set to the literal `SUPERSEDED`."
        PRD 3.7: "The new determination is written with `status` `DRAFT`, `priced_by_user_id` set to the acting analyst's `X-User-ID`, its `stay_id` copied from the path, the stay's `payment_review_status` set to `PRICED`, and the stay's `version` increased by 1."
        PRD 3.7: "The percentage is mirrored onto the stay's `discharge_payment_pct`, which is null until a determination exists."

        Design: Corner/endpoints/override_drg_rate_id_conditionally_reprices_the_stay
        """
        admission, other_rate = self._priced_stay_with_a_second_rate_on_file(api)
        cascade_determination = admission.determination
        version_before = admission.stay["version"]

        repriced = fixtures.reprice(
            api,
            admission.stay_id,
            expected_stay_version=version_before,
            recalculation_reason="Coding audit reassigned the stay to DRG 573.",
            override_drg_rate_id=other_rate["id"],
            headers=analyst,
        )

        displaced = fixtures.read_determination(api, cascade_determination["id"])
        assert displaced["status"] == DeterminationStatus.VOIDED
        assert displaced["void_reason"] == VoidReason.SUPERSEDED
        assert fixtures.sole_determination(api, admission.stay_id)["id"] == repriced["id"]
        stay = fixtures.read_stay(api, admission.stay_id)
        assert stay["version"] == version_before + 1
        assert stay["payment_review_status"] == PaymentReviewStatus.PRICED
        assert stay["discharge_payment_pct"] == repriced["discharge_payment_pct"]

    def test_omitting_the_override_falls_back_to_the_referral_rate(self, api, analyst):
        """A re-price with no override prices against the admitting referral's DRG again.

        After the override re-price, the analyst re-prices once more and this time supplies no
        override, so the DRG in force is the referral's DRG 207 once more. Fourteen covered
        days sit at or under that DRG's 25-day short-stay threshold, so the outlier applies
        and the base is the smallest of the three short-stay candidates — 1,512,000 against a
        full standard amount of 6,000,000, which is 25.20 percent. The override determination
        is itself superseded in turn, leaving exactly one live determination as before.

        PRD 3.6: "The \"DRG in force\" means the `DrgRateEntry` identified by the pricing request's `override_drg_rate_id` when one was supplied, and otherwise the `DrgRateEntry` named by the admitting referral's `drg_rate_id`."
        PRD 3.7: "When it is true, the base is reduced to the **smallest of three candidates**."
        PRD 3.7: "Finally, `discharge_payment_pct` is `base_payment_cents` divided by `full_standard_amount_cents`, multiplied by 100 and rounded half up to two decimal places."

        Design: Corner/endpoints/override_drg_rate_id_conditionally_reprices_the_stay
        """
        admission, other_rate = self._priced_stay_with_a_second_rate_on_file(api)
        overridden = fixtures.reprice(
            api,
            admission.stay_id,
            expected_stay_version=admission.stay["version"],
            recalculation_reason="Coding audit reassigned the stay to DRG 573.",
            override_drg_rate_id=other_rate["id"],
            headers=analyst,
        )
        current_version = fixtures.read_stay(api, admission.stay_id)["version"]

        restored = fixtures.reprice(
            api,
            admission.stay_id,
            expected_stay_version=current_version,
            recalculation_reason="Audit reversed; restore the referral DRG.",
            headers=analyst,
        )

        assert restored["drg_code_used"] == DRG_207["drg_code"]
        assert restored["short_stay_outlier_applied"] is True
        assert_cents(restored, "base_payment_cents", 1512000)
        assert_cents(restored, "total_payment_cents", 1512000)
        assert_pct(restored, "discharge_payment_pct", 25.20)
        superseded = fixtures.read_determination(api, overridden["id"])
        assert superseded["status"] == DeterminationStatus.VOIDED
        assert superseded["void_reason"] == VoidReason.SUPERSEDED
        drafts = fixtures.determinations_of(api, admission.stay_id, status=DeterminationStatus.DRAFT)
        assert [item["id"] for item in drafts] == [restored["id"]]
