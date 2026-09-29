"""
Refusals: unknown references, the logical clock, and the gates in front of the money.

The tests here pin the *identity* of a refusal rather than the mere fact of one. An unknown
reference must answer with the code of the entity it failed to resolve, whether the
reference arrived in the path or in the body; the clock must refuse an instant that is not
strictly later; and the two fiscal gates in front of finalization must each speak in their
declared order, so that the second one is only ever heard once the first is satisfied.
"""

import pytest

from test_helpers import (
    ANALYST_HEADERS,
    ANALYST_ID,
    ApiErrorId,
    DeterminationStatus,
    INTAKE_HEADERS,
    NON_EXISTENT_UUID,
    NOT_FOUND_ERROR_IDS,
    NURSE_HEADERS,
    OFFICER_HEADERS,
    PaymentReviewStatus,
    QueryStatus,
    QueryType,
    ReviewOutcome,
    ReviewStatus,
    assert_cents,
    assert_instant_equals,
    assert_period_ledger,
    factories,
    fixtures,
    get_success_data,
    validate_error,
)

# One endpoint per entity whose id may appear in a request path, each paired with the
# type-specific code the specification names for that entity. Every probe runs against an
# empty store, so the well-formed probe id resolves to nothing.
_PATH_ID_PROBES = (
    (
        "referring_hospital",
        lambda api: api.get_referring_hospital(NON_EXISTENT_UUID, headers=OFFICER_HEADERS),
        ApiErrorId.ERR_HOSPITAL_NOT_FOUND,
    ),
    (
        "patient",
        lambda api: api.get_patient(NON_EXISTENT_UUID, headers=INTAKE_HEADERS),
        ApiErrorId.ERR_PATIENT_NOT_FOUND,
    ),
    (
        "physician",
        lambda api: api.set_credential_status(
            NON_EXISTENT_UUID,
            factories.credential_status_payload("SUSPENDED"),
            headers=OFFICER_HEADERS,
        ),
        ApiErrorId.ERR_PHYSICIAN_NOT_FOUND,
    ),
    (
        "criteria_set",
        lambda api: api.get_criteria_set(NON_EXISTENT_UUID, headers=OFFICER_HEADERS),
        ApiErrorId.ERR_CRITERIA_SET_NOT_FOUND,
    ),
    (
        "cost_reporting_period",
        lambda api: api.get_period(NON_EXISTENT_UUID, headers=OFFICER_HEADERS),
        ApiErrorId.ERR_PERIOD_NOT_FOUND,
    ),
    (
        "referral",
        lambda api: api.get_referral(NON_EXISTENT_UUID, headers=INTAKE_HEADERS),
        ApiErrorId.ERR_REFERRAL_NOT_FOUND,
    ),
    (
        "stay",
        lambda api: api.get_stay(NON_EXISTENT_UUID, headers=NURSE_HEADERS),
        ApiErrorId.ERR_STAY_NOT_FOUND,
    ),
    (
        "weaning_plan",
        lambda api: api.get_weaning_plan(NON_EXISTENT_UUID, headers=NURSE_HEADERS),
        ApiErrorId.ERR_WEANING_PLAN_NOT_FOUND,
    ),
    (
        "interruption",
        lambda api: api.return_interruption(NON_EXISTENT_UUID, headers=NURSE_HEADERS),
        ApiErrorId.ERR_INTERRUPTION_NOT_FOUND,
    ),
    (
        "payment_determination",
        lambda api: api.get_determination(NON_EXISTENT_UUID, headers=ANALYST_HEADERS),
        ApiErrorId.ERR_DETERMINATION_NOT_FOUND,
    ),
    (
        "denial_risk_review",
        lambda api: api.get_review(NON_EXISTENT_UUID, headers=OFFICER_HEADERS),
        ApiErrorId.ERR_REVIEW_NOT_FOUND,
    ),
    (
        "documentation_query",
        lambda api: api.get_query(NON_EXISTENT_UUID, headers=OFFICER_HEADERS),
        ApiErrorId.ERR_QUERY_NOT_FOUND,
    ),
)


class TestEveryPathIdNotFoundCodeIsTriggerable:
    """Each of the twelve path-existence codes is reachable and distinct."""

    @pytest.mark.parametrize(
        "probe, expected_error_id",
        [pytest.param(probe, error_id, id=name) for name, probe, error_id in _PATH_ID_PROBES],
    )
    def test_an_unknown_path_id_answers_with_the_code_of_its_own_entity_type(
        self, api, probe, expected_error_id
    ):
        """A well-formed id that belongs to nothing yields that entity's own 404.

        Nothing has been created, so the probe id resolves to no row of any type. The
        response must name the entity the server failed to resolve rather than a generic
        validation failure, and the status must be 404 with an explanatory message.

        PRD 2.8: "Every entity `id` appearing in the request path resolves to an existing row, returning the type-specific 404: `ERR_REFERRAL_NOT_FOUND`, `ERR_STAY_NOT_FOUND`, `ERR_WEANING_PLAN_NOT_FOUND`, `ERR_INTERRUPTION_NOT_FOUND`, `ERR_DETERMINATION_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_QUERY_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`, `ERR_HOSPITAL_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_CRITERIA_SET_NOT_FOUND` or `ERR_PHYSICIAN_NOT_FOUND`."

        Design: Corner/errors/every_path_id_not_found_code_is_triggerable
        """
        validate_error(probe(api), expected_error_id)

    def test_no_endpoint_borrows_another_entitys_not_found_code(self, api):
        """The twelve path-existence codes come back distinct, one per entity type.

        Sweeping every endpoint that carries a path id collects twelve refusals, and they
        must be twelve different codes: a server that answered a missing weaning plan with
        the stay's code would leave a caller unable to tell which reference it got wrong.
        Together they account for every declared not-found code except the DRG rate's, which
        no path exposes because a rate entry is only ever named in a body.

        PRD 2.8: "Every entity `id` appearing in the request path resolves to an existing row, returning the type-specific 404: `ERR_REFERRAL_NOT_FOUND`, `ERR_STAY_NOT_FOUND`, `ERR_WEANING_PLAN_NOT_FOUND`, `ERR_INTERRUPTION_NOT_FOUND`, `ERR_DETERMINATION_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_QUERY_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`, `ERR_HOSPITAL_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_CRITERIA_SET_NOT_FOUND` or `ERR_PHYSICIAN_NOT_FOUND`."

        Design: Corner/errors/every_path_id_not_found_code_is_triggerable
        """
        observed = []
        for _name, probe, expected_error_id in _PATH_ID_PROBES:
            observed.append(validate_error(probe(api), expected_error_id)["error_id"])

        assert len(observed) == 12
        assert len(set(observed)) == 12, "two endpoints answered with the same code: {}".format(
            observed
        )
        assert set(observed) == set(NOT_FOUND_ERROR_IDS) - {ApiErrorId.ERR_DRG_RATE_NOT_FOUND}


class TestBodyForeignKeysReportTheirOwnNotFoundCodes:
    """A reference carried in the body is resolved exactly like one carried in the path."""

    @pytest.mark.parametrize(
        "field, expected_error_id",
        [
            pytest.param("patient_id", ApiErrorId.ERR_PATIENT_NOT_FOUND, id="patient_id"),
            pytest.param(
                "referring_hospital_id", ApiErrorId.ERR_HOSPITAL_NOT_FOUND, id="referring_hospital_id"
            ),
            pytest.param("drg_rate_id", ApiErrorId.ERR_DRG_RATE_NOT_FOUND, id="drg_rate_id"),
        ],
    )
    def test_a_referral_naming_an_unknown_reference_reports_that_references_code(
        self, api, field, expected_error_id
    ):
        """Each of the referral's three body foreign keys answers with its own 404.

        The referral create carries three references at once. Replacing exactly one of them
        with a well-formed id that belongs to nothing must produce the code of that
        reference's entity type, so a coordinator learns which of the three it got wrong.

        PRD 2.8: "Every foreign key supplied in the body resolves to an existing row — `patient_id`, `referring_hospital_id`, `drg_rate_id`, `physician_id`, `cost_reporting_period_id`, `interrupted_parent_stay_id`, `referral_id`, `stay_id` and `review_id` — returning `ERR_PATIENT_NOT_FOUND`, `ERR_HOSPITAL_NOT_FOUND`, `ERR_DRG_RATE_NOT_FOUND`, `ERR_PHYSICIAN_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`, `ERR_STAY_NOT_FOUND` or `ERR_REFERRAL_NOT_FOUND` as appropriate."

        Design: Corner/errors/body_foreign_keys_report_their_own_not_found_codes
        """
        world = fixtures.build_world(api)
        payload = factories.referral_payload(
            world.patient_id,
            world.hospital_id,
            world.drg_rate_id,
            fixtures.read_patient(api, world.patient_id)["version"],
        )
        payload[field] = NON_EXISTENT_UUID

        validate_error(api.create_referral(payload, headers=INTAKE_HEADERS), expected_error_id)

    def test_the_body_reference_is_resolved_before_the_version_is_compared(self, api):
        """An unknown patient wins over a stale `expected_patient_version`.

        The request is doubly wrong: it names a patient that does not exist and it carries a
        version that matches no patient either. Because existence is checked one rule earlier
        than optimistic concurrency, the caller is told the patient is missing rather than
        that its view is stale — a stale-version answer about a non-existent row would be
        nonsense.

        PRD 2.8: "Requests frequently violate more than one rule."
        PRD 2.8: "The server evaluates its checks in a fixed order and the **first** violated rule determines the response; no later check is evaluated once one has fired."
        PRD 2.8: "Where the endpoint declares a version field, the supplied `expected_stay_version` or `expected_patient_version` equals the parent's current `version`, else `ERR_STALE_STAY_VERSION` or `ERR_STALE_PATIENT_VERSION` (412)."

        Design: Corner/errors/body_foreign_keys_report_their_own_not_found_codes
        """
        world = fixtures.build_world(api)
        current_version = fixtures.read_patient(api, world.patient_id)["version"]
        payload = factories.referral_payload(
            NON_EXISTENT_UUID,
            world.hospital_id,
            world.drg_rate_id,
            current_version + 99,
        )

        validate_error(
            api.create_referral(payload, headers=INTAKE_HEADERS), ApiErrorId.ERR_PATIENT_NOT_FOUND
        )

    def test_an_unknown_override_rate_reports_the_drg_rate_code(self, api, analyst):
        """The optional `override_drg_rate_id` on a re-price is resolved the same way.

        The stay is discharged and priced, and the analyst supplies a current stay version, so
        the only thing wrong with the re-price is the rate entry it names. The refusal is the
        DRG rate's own code — the code no path id can produce, because a rate entry is only
        ever referenced from a body.

        PRD 3.7: "An `override_drg_rate_id` that resolves to no rate entry yields `ERR_DRG_RATE_NOT_FOUND`."

        Design: Corner/errors/body_foreign_keys_report_their_own_not_found_codes
        """
        admission = fixtures.admitted_stay(api)
        fixtures.advance_clock(api, "2026-08-15T00:00:00Z")
        admission = fixtures.discharged_stay(api, admission=admission, file_notes=False)
        payload = factories.reprice_payload(
            fixtures.read_stay(api, admission.stay_id)["version"],
            recalculation_reason="Coding audit.",
            override_drg_rate_id=NON_EXISTENT_UUID,
        )

        validate_error(
            api.reprice_stay(admission.stay_id, payload, headers=analyst),
            ApiErrorId.ERR_DRG_RATE_NOT_FOUND,
        )

    def test_a_refused_reference_leaves_the_store_exactly_as_it_was(self, api, analyst):
        """Neither refusal writes anything: no version moves and no determination is displaced.

        A referral create that is refused must not advance the patient's version, because
        that advance is the very thing that supersedes other in-flight referrals. A re-price
        that is refused must not have voided the draft it would have superseded, because the
        supersession happens only on the way to writing a replacement row.

        PRD 2.6: "On success the patient's `version` advances by 1, which invalidates every other in-flight referral create for that patient."
        PRD 3.7: "Before the new row is written, any existing determination on that stay whose `status` is `DRAFT` is flipped to `VOIDED` with `void_reason` set to the literal `SUPERSEDED`."

        Design: Corner/errors/body_foreign_keys_report_their_own_not_found_codes
        """
        admission = fixtures.admitted_stay(api)
        fixtures.advance_clock(api, "2026-08-15T00:00:00Z")
        admission = fixtures.discharged_stay(api, admission=admission, file_notes=False)
        world = admission.world
        patient_version = fixtures.read_patient(api, world.patient_id)["version"]
        stay_version = fixtures.read_stay(api, admission.stay_id)["version"]
        draft_before = admission.determination

        validate_error(
            api.create_referral(
                factories.referral_payload(
                    NON_EXISTENT_UUID, world.hospital_id, world.drg_rate_id, patient_version
                ),
                headers=INTAKE_HEADERS,
            ),
            ApiErrorId.ERR_PATIENT_NOT_FOUND,
        )
        validate_error(
            api.reprice_stay(
                admission.stay_id,
                factories.reprice_payload(
                    stay_version,
                    recalculation_reason="Coding audit.",
                    override_drg_rate_id=NON_EXISTENT_UUID,
                ),
                headers=analyst,
            ),
            ApiErrorId.ERR_DRG_RATE_NOT_FOUND,
        )

        assert fixtures.read_patient(api, world.patient_id)["version"] == patient_version
        assert fixtures.read_stay(api, admission.stay_id)["version"] == stay_version
        drafts = fixtures.determinations_of(
            api, admission.stay_id, status=DeterminationStatus.DRAFT
        )
        assert [item["id"] for item in drafts] == [draft_before["id"]]


class TestClockMustMoveStrictlyForward:
    """The logical clock accepts only an instant strictly later than the one it holds."""

    @pytest.mark.parametrize(
        "candidate, headers",
        [
            pytest.param("2026-08-15T00:00:00Z", OFFICER_HEADERS, id="identical_instant"),
            pytest.param("2026-08-10T00:00:00Z", ANALYST_HEADERS, id="earlier_instant"),
        ],
    )
    def test_an_instant_that_is_not_strictly_later_is_refused(self, api, candidate, headers):
        """Re-sending the held instant is refused exactly as a backwards jump is.

        The clock has been moved to 2026-08-15T00:00:00Z. Both a repeat of that same instant
        and a jump back to an earlier one fail the monotonicity test, because the requirement
        is *strictly* after and not merely no earlier. Two different roles make the two
        attempts and both are told the same thing, so the refusal is about the instant rather
        than about who asked.

        PRD 2.4: "The clock is strictly monotonic: a `current_utc` that is not strictly after the current logical instant is refused with `ERR_CLOCK_NOT_MONOTONIC`."
        PRD 2.8: "The requested `current_utc` must be strictly after the current logical instant, else `ERR_CLOCK_NOT_MONOTONIC` (422)."

        Design: Corner/errors/clock_must_move_strictly_forward
        """
        fixtures.advance_clock(api, "2026-08-15T00:00:00Z")

        validate_error(
            api.set_clock(candidate, headers=headers), ApiErrorId.ERR_CLOCK_NOT_MONOTONIC
        )

    def test_a_one_second_advance_is_accepted_and_names_the_instant_it_replaced(self, api, nurse):
        """A single second past the refused instant is enough, and the refusals left no trace.

        Both refused attempts are followed by an advance of exactly one second, which
        succeeds. Its `previous_utc` is the instant the clock held all along — proof that
        neither refusal moved it — and its `current_utc` is the new instant.

        PRD 2.4: "An operator in any of the five roles may advance the clock by supplying a `current_utc` instant; the response reports the new `current_utc` alongside the `previous_utc` it replaced."
        PRD 2.4: "The clock is strictly monotonic: a `current_utc` that is not strictly after the current logical instant is refused with `ERR_CLOCK_NOT_MONOTONIC`."

        Design: Corner/errors/clock_must_move_strictly_forward
        """
        fixtures.advance_clock(api, "2026-08-15T00:00:00Z")
        validate_error(
            api.set_clock("2026-08-15T00:00:00Z", headers=OFFICER_HEADERS),
            ApiErrorId.ERR_CLOCK_NOT_MONOTONIC,
        )
        validate_error(
            api.set_clock("2026-08-10T00:00:00Z", headers=ANALYST_HEADERS),
            ApiErrorId.ERR_CLOCK_NOT_MONOTONIC,
        )

        accepted = get_success_data(
            api.set_clock("2026-08-15T00:00:01Z", headers=nurse), expected_status=200
        )

        assert_instant_equals(accepted["current_utc"], "2026-08-15T00:00:01Z", "current_utc")
        assert_instant_equals(accepted["previous_utc"], "2026-08-15T00:00:00Z", "previous_utc")


class TestAFinalDeterminationBlocksANewOne:
    """`ERR_DETERMINATION_EXISTS` is reachable only past a determination in `FINAL`."""

    @staticmethod
    def _discharged_and_priced(api):
        """A stay discharged on 2026-08-15 with the cascade's draft determination on it."""
        admission = fixtures.admitted_stay(api)
        fixtures.advance_clock(api, "2026-08-15T00:00:00Z")
        return fixtures.discharged_stay(api, admission=admission, file_notes=False)

    def _finalized(self, api, analyst_headers):
        """The same stay with its review cleared and its determination accepted."""
        admission = self._discharged_and_priced(api)
        review = fixtures.sole_review(api, admission.stay_id)
        fixtures.resolve_review(api, review["id"], outcome=ReviewOutcome.CLEARED)
        admission.determination = fixtures.finalize(
            api, admission.determination["id"], headers=analyst_headers
        )
        return admission

    def test_while_the_outstanding_determination_is_a_draft_the_same_reprice_succeeds(self, api, analyst):
        """A draft is superseded silently, so the code is not a duplicate-request guard.

        Before finalization the stay holds one determination in `DRAFT`. Asking to price the
        stay again is not an error at all: the outstanding row is voided as superseded and a
        replacement draft is written. This is the same call that will be refused once the
        determination reaches `FINAL`.

        PRD 3.7: "Before the new row is written, any existing determination on that stay whose `status` is `DRAFT` is flipped to `VOIDED` with `void_reason` set to the literal `SUPERSEDED`."
        PRD 2.8: "A stay may hold at most one `PaymentDetermination` whose `status` is `DRAFT` or `FINAL`; an attempt to add another while a `FINAL` one exists returns `ERR_DETERMINATION_EXISTS` (409)."

        Design: Corner/errors/a_final_determination_blocks_a_new_one
        """
        admission = self._discharged_and_priced(api)
        assert admission.determination["status"] == DeterminationStatus.DRAFT

        repriced = fixtures.reprice(
            api,
            admission.stay_id,
            expected_stay_version=fixtures.read_stay(api, admission.stay_id)["version"],
            recalculation_reason="First audit pass; DRAFT superseded cleanly.",
            headers=analyst,
        )

        assert repriced["status"] == DeterminationStatus.DRAFT
        assert fixtures.sole_determination(api, admission.stay_id)["id"] == repriced["id"]

    def test_a_reprice_past_a_final_determination_is_refused(self, api, analyst, second_analyst):
        """Once the determination is `FINAL` the same request is refused, and not for staleness.

        The review is cleared and the determination accepted, so the stay now holds one
        determination in `FINAL`. The re-price supplies the stay's current version, so the
        optimistic-concurrency check passes and the refusal can only be the one-live-
        determination rule.

        PRD 2.8: "A stay may hold at most one `PaymentDetermination` whose `status` is `DRAFT` or `FINAL`; an attempt to add another while a `FINAL` one exists returns `ERR_DETERMINATION_EXISTS` (409)."
        PRD 3.7: "If the stay already holds a determination whose `status` is `FINAL`, the re-price is refused with `ERR_DETERMINATION_EXISTS`, because a stay may hold at most one determination in `DRAFT` or `FINAL` at a time."

        Design: Corner/errors/a_final_determination_blocks_a_new_one
        """
        admission = self._finalized(api, second_analyst)
        assert admission.determination["status"] == DeterminationStatus.FINAL
        stay = fixtures.read_stay(api, admission.stay_id)
        assert stay["payment_review_status"] == PaymentReviewStatus.FINALIZED

        refused = api.reprice_stay(
            admission.stay_id,
            factories.reprice_payload(
                stay["version"],
                recalculation_reason="Second audit pass attempted after finalization.",
            ),
            headers=analyst,
        )

        validate_error(refused, ApiErrorId.ERR_DETERMINATION_EXISTS)

    def test_the_refused_reprice_leaves_the_final_determination_and_the_ledger_intact(
        self, api, analyst, second_analyst
    ):
        """Nothing is voided and no money moves, because the refusal fired before any write.

        After the refusal the stay still holds exactly one determination and it is still the
        `FINAL` one; no draft was created alongside it. The period's ledger still carries the
        single finalized amount of 1,512,000 cents against a count of one.

        PRD 3.7: "On success `finalized_by_user_id` records the acting `X-User-ID`, the stay's `payment_review_status` moves `PRICED → FINALIZED`, the period's `total_payment_cents` is increased by this determination's `total_payment_cents`, and the period's `final_determination_count` is increased by 1."

        Design: Corner/errors/a_final_determination_blocks_a_new_one
        """
        admission = self._finalized(api, second_analyst)
        assert_cents(admission.determination, "total_payment_cents", 1512000)
        stay = fixtures.read_stay(api, admission.stay_id)

        validate_error(
            api.reprice_stay(
                admission.stay_id,
                factories.reprice_payload(
                    stay["version"],
                    recalculation_reason="Second audit pass attempted after finalization.",
                ),
                headers=analyst,
            ),
            ApiErrorId.ERR_DETERMINATION_EXISTS,
        )

        finals = fixtures.determinations_of(
            api, admission.stay_id, status=DeterminationStatus.FINAL
        )
        drafts = fixtures.determinations_of(
            api, admission.stay_id, status=DeterminationStatus.DRAFT
        )
        assert [item["id"] for item in finals] == [admission.determination["id"]]
        assert drafts == []
        period = fixtures.read_period(api, admission.world.period_id)
        assert_period_ledger(period, total_payment_cents=1512000, final_determination_count=1)


class TestFinalizeReportsTheReviewGateBeforeTheQueryGate:
    """The review gate is heard first; the query gate only speaks once the review is resolved."""

    @staticmethod
    def _awaiting_finalization(api):
        """A discharged stay whose draft determination is ready but whose review is `OPEN`."""
        admission = fixtures.admitted_stay(api)
        fixtures.advance_clock(api, "2026-08-15T00:00:00Z")
        admission = fixtures.discharged_stay(api, admission=admission, file_notes=False)
        admission.review = fixtures.sole_review(api, admission.stay_id)
        return admission

    def test_an_unresolved_review_blocks_the_money(self, api, analyst):
        """Finalizing against a review still `OPEN` is refused by the review gate.

        The cascade opened the review and nobody has resolved it, so the first fiscal gate is
        the one that fires. Nothing else about the request is wrong: the determination is in
        `DRAFT`, the period is open, and the cascade priced the stay as `SYSTEM` so no
        segregation-of-duties conflict exists.

        PRD 2.8: "Finalization requires the stay's `DenialRiskReview` to be resolved, meaning its `status` is `CLEARED` or `ESCALATED`; a review still `OPEN` or `QUERIES_ISSUED` returns `ERR_REVIEW_NOT_RESOLVED` (422)."

        Design: Corner/errors/finalize_reports_the_review_gate_before_the_query_gate
        """
        admission = self._awaiting_finalization(api)
        assert admission.review["status"] == ReviewStatus.OPEN

        refused = api.finalize_determination(admission.determination["id"], headers=analyst)

        validate_error(refused, ApiErrorId.ERR_REVIEW_NOT_RESOLVED)

    def test_a_review_in_queries_issued_is_still_an_unresolved_review(self, api, analyst, nurse):
        """Issuing a query does not change which gate answers: the review is still unresolved.

        The nurse issues a documentation query, which drives the review from `OPEN` to
        `QUERIES_ISSUED`. Both of those statuses count as unresolved, so the same refusal
        comes back and the outstanding query is not yet the reason.

        PRD 3.8: "A review in `OPEN` moves `OPEN → QUERIES_ISSUED`; a review already in `QUERIES_ISSUED` stays there."
        PRD 2.8: "Finalization requires the stay's `DenialRiskReview` to be resolved, meaning its `status` is `CLEARED` or `ESCALATED`; a review still `OPEN` or `QUERIES_ISSUED` returns `ERR_REVIEW_NOT_RESOLVED` (422)."

        Design: Corner/errors/finalize_reports_the_review_gate_before_the_query_gate
        """
        admission = self._awaiting_finalization(api)
        fixtures.issue_query(
            api, admission.review["id"], query_type=QueryType.IDT_PARTICIPATION, headers=nurse
        )
        assert (
            fixtures.read_review(api, admission.review["id"])["status"]
            == ReviewStatus.QUERIES_ISSUED
        )

        refused = api.finalize_determination(admission.determination["id"], headers=analyst)

        validate_error(refused, ApiErrorId.ERR_REVIEW_NOT_RESOLVED)

    def test_only_an_escalated_resolution_makes_the_query_gate_audible(self, api, analyst, nurse, officer):
        """With the review escalated and a query still `ISSUED`, the query gate finally fires.

        An escalation is the one resolution permitted from `QUERIES_ISSUED`, and unlike a
        clearance it carries no requirement that every query already be dealt with. That is
        what leaves the review resolved while a query is still outstanding — the only state in
        which the second gate can be reached.

        PRD 3.8: "A `CLEARED` resolution is permitted only from `OPEN`, only when `risk_band` is not `HIGH`, and only when no query on the review is still in `ISSUED`; a high-risk chart cannot simply be waved through."
        PRD 3.8: "An `ESCALATED` resolution is permitted from either `OPEN` or `QUERIES_ISSUED` and carries no band restriction — escalation is the honest exit for a chart that cannot be cleared."
        PRD 2.8: "Finalization requires zero `DocumentationQuery` rows in `status` `ISSUED` on the stay's review, else `ERR_OPEN_QUERIES_BLOCK_FINALIZE` (422)."

        Design: Corner/errors/finalize_reports_the_review_gate_before_the_query_gate
        """
        admission = self._awaiting_finalization(api)
        fixtures.issue_query(
            api, admission.review["id"], query_type=QueryType.IDT_PARTICIPATION, headers=nurse
        )
        resolved = fixtures.resolve_review(
            api,
            admission.review["id"],
            outcome=ReviewOutcome.ESCALATED,
            resolution_note="Escalated to the physician advisor with the query still outstanding.",
            headers=officer,
        )
        assert resolved["status"] == ReviewStatus.ESCALATED

        refused = api.finalize_determination(admission.determination["id"], headers=analyst)

        validate_error(refused, ApiErrorId.ERR_OPEN_QUERIES_BLOCK_FINALIZE)

    def test_an_answered_query_no_longer_blocks_the_money(self, api, analyst, nurse, officer):
        """Once the query is answered the finalize goes through and the ledger takes the amount.

        The gate counts only queries still in `ISSUED`, so a query the physician has answered
        stops blocking. The finalize then succeeds, records the acting analyst and moves the
        determination's amount into the period's ledger.

        PRD 3.8: "On success the query moves `ISSUED → ANSWERED`, `answered_at` is stamped from the logical clock, `answered_by_physician_id` records the acting physician's `X-User-ID`, the review's `answered_query_count` increases by 1, and the denial-risk score is recomputed, so the `risk_band` may fall."
        PRD 2.8: "Finalization requires zero `DocumentationQuery` rows in `status` `ISSUED` on the stay's review, else `ERR_OPEN_QUERIES_BLOCK_FINALIZE` (422)."
        PRD 3.7: "On success `finalized_by_user_id` records the acting `X-User-ID`, the stay's `payment_review_status` moves `PRICED → FINALIZED`, the period's `total_payment_cents` is increased by this determination's `total_payment_cents`, and the period's `final_determination_count` is increased by 1."

        Design: Corner/errors/finalize_reports_the_review_gate_before_the_query_gate
        """
        admission = self._awaiting_finalization(api)
        query = fixtures.issue_query(
            api, admission.review["id"], query_type=QueryType.IDT_PARTICIPATION, headers=nurse
        )
        fixtures.resolve_review(
            api,
            admission.review["id"],
            outcome=ReviewOutcome.ESCALATED,
            resolution_note="Escalated to the physician advisor with the query still outstanding.",
            headers=officer,
        )
        answered = fixtures.answer_query(
            api,
            query["id"],
            admission.world.physician_headers,
            response_text="Prolonged mechanical ventilation of 240 hours documented at referral.",
        )
        assert answered["status"] == QueryStatus.ANSWERED

        finalized = get_success_data(
            api.finalize_determination(admission.determination["id"], headers=analyst),
            expected_status=200,
        )

        assert finalized["status"] == DeterminationStatus.FINAL
        assert finalized["finalized_by_user_id"] == ANALYST_ID
        period = fixtures.read_period(api, admission.world.period_id)
        assert_period_ledger(period, total_payment_cents=1512000, final_determination_count=1)
