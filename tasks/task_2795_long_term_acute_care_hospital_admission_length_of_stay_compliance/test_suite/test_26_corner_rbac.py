"""
Role lanes, the role-name whitelist and the segregation of duties.

Four claims are pinned here. Each of the five declared roles must be able to run the
operations the endpoint table grants it, so one admission is carried from reference data
to a finalized payment with every call made by the role that owns it. No role may reach
into another's lane, including on the two read endpoints the nurse is excluded from and
the interruption listing the physician is excluded from. A role name outside the declared
five — or no role header at all — cannot act, on reads or writes. And where a duty is
segregated, holding the role constant and changing only the acting identity is what
decides the request.
"""

import pytest

from test_helpers import (
    ANALYST_2_ID,
    ANALYST_HEADERS,
    ANALYST_ID,
    CLOCK_EPOCH,
    INTAKE_HEADERS,
    NURSE_2_ID,
    NURSE_HEADERS,
    OFFICER_HEADERS,
    OPAQUE_ROLE_HEADERS,
    UNKNOWN_PHYSICIAN_ID,
    UNKNOWN_ROLE,
    ApiErrorId,
    ClinicalStatus,
    DeterminationStatus,
    Discipline,
    PaymentReviewStatus,
    QueryStatus,
    ReferralStatus,
    ReviewOutcome,
    ReviewStatus,
    UserRole,
    assert_instant_equals,
    assert_period_ledger,
    assert_stay_dimensions,
    factories,
    fixtures,
    get_success_data,
    make_attending_physician_headers,
    make_headers,
    validate_error,
    validate_paginated,
)

# The instant every scenario in this module discharges at: two weeks after the epoch.
DISCHARGE_CLOCK = "2026-08-15T00:00:00Z"


def _headers_without_a_role() -> dict:
    """Caller headers carrying an identity but no `X-User-Role` at all."""
    headers = dict(make_headers("clerk-a", UserRole.COMPLIANCE_OFFICER))
    headers.pop("X-User-Role")
    return headers


# The three ways a caller can fail to name one of the five declared roles.
ROLELESS_HEADER_VARIANTS = (
    pytest.param(make_headers("clerk-a", UNKNOWN_ROLE), id="undeclared_role_name"),
    pytest.param(make_headers("clerk-a", ""), id="empty_role_value"),
    pytest.param(_headers_without_a_role(), id="role_header_absent"),
)


def _discharged_stay(api) -> fixtures.Admission:
    """A stay admitted at the epoch, fully documented, and discharged two weeks later.

    All four mandatory disciplines are documented, so the denial-risk score carries no
    missing-discipline points and the cascade leaves the review `OPEN` rather than
    auto-issuing a query.
    """
    admission = fixtures.admitted_stay(api)
    fixtures.file_required_notes(api, admission.stay_id)
    fixtures.advance_clock(api, DISCHARGE_CLOCK)
    admission.stay = fixtures.discharge(api, admission.stay_id)
    return fixtures.collect_cascade(api, admission)


class TestEveryRoleRunsItsOwnOperations:
    """The five declared roles, each exercising the operations that belong to it."""

    def test_one_admission_runs_end_to_end_with_every_call_made_by_its_owning_role(
        self, api, officer, intake, nurse, second_nurse, analyst, second_analyst
    ):
        """A single stay reaches a finalized payment with each step taken by its own role.

        The officer seeds the reference data and the fiscal envelope, the intake coordinator
        registers the patient and carries the referral through to admission, the nurse
        documents and discharges, the analyst prices, the physician answers the query the
        nurse issued, the officer rescores and clears the review, and a second analyst
        accepts the price. Every one of those calls is made by the role the endpoint admits,
        so not one of them may be refused: the whole chain is the positive half of the
        authorization rule.

        PRD 2.1: "The `ComplianceOfficer` owns reference data and the fiscal envelope: referring hospitals, physicians and their credentials, MS-LTC-DRG rate entries, admission criteria sets, and cost reporting periods including their recomputation and close."
        PRD 2.1: "An `IntakeCoordinator` receives referrals, screens them, supplies late data, withdraws them and admits qualifying patients — and does nothing else."
        PRD 2.1: "A `UtilizationReviewNurse` documents the stay: interdisciplinary notes, interruptions and returns, the ventilator weaning plan and its trial records, discharge, and the issuing and closing of documentation queries; a nurse may not answer a query, because only a physician may."
        PRD 2.1: "An `AttendingPhysician` closes weaning plans and answers documentation queries."
        PRD 2.1: "A `RevenueIntegrityAnalyst` prices and re-prices discharged stays and moves determinations through the period ledger."

        Design: Corner/rbac/every_role_can_run_its_own_exclusive_operations
        """
        # The compliance officer's lane: reference data and the fiscal envelope.
        get_success_data(
            api.create_period(factories.period_payload(), headers=officer), expected_status=201
        )
        hospital = get_success_data(
            api.create_referring_hospital(factories.referring_hospital_payload(), headers=officer),
            expected_status=201,
        )
        get_success_data(
            api.create_criteria_set(factories.criteria_set_payload(), headers=officer),
            expected_status=201,
        )
        drg_rate = get_success_data(
            api.create_drg_rate(factories.drg_rate_payload(), headers=officer), expected_status=201
        )
        physician = get_success_data(
            api.create_physician(factories.physician_payload(), headers=officer),
            expected_status=201,
        )
        physician_headers = make_attending_physician_headers(physician["id"])

        # The intake coordinator's lane: the patient, the referral, screening and admission.
        patient = get_success_data(
            api.create_patient(factories.patient_payload(), headers=intake), expected_status=201
        )
        referral = get_success_data(
            api.create_referral(
                factories.referral_payload(
                    patient["id"], hospital["id"], drg_rate["id"], patient["version"]
                ),
                headers=intake,
            ),
            expected_status=201,
        )
        screened = get_success_data(
            api.screen_referral(referral["id"], headers=intake), expected_status=200
        )
        assert screened["status"] == ReferralStatus.CRITERIA_MET
        stay = get_success_data(
            api.admit_referral(referral["id"], factories.admit_payload(), headers=intake),
            expected_status=201,
        )

        # The nurse's lane, shared with the physician for interdisciplinary notes.
        for discipline in (
            Discipline.NURSING,
            Discipline.RESPIRATORY_THERAPY,
            Discipline.CASE_MANAGEMENT,
        ):
            get_success_data(
                api.create_idt_note(
                    stay["id"], factories.idt_note_payload(discipline=discipline), headers=nurse
                ),
                expected_status=201,
            )
        get_success_data(
            api.create_idt_note(
                stay["id"],
                factories.idt_note_payload(discipline=Discipline.PHYSICIAN),
                headers=physician_headers,
            ),
            expected_status=201,
        )
        get_success_data(api.set_clock(DISCHARGE_CLOCK, headers=nurse), expected_status=200)
        discharged = get_success_data(
            api.discharge_stay(stay["id"], factories.discharge_payload(), headers=nurse),
            expected_status=200,
        )
        assert discharged["clinical_status"] == ClinicalStatus.DISCHARGED

        # The analyst's lane: re-pricing the discharged stay.
        priced = get_success_data(
            api.reprice_stay(
                stay["id"],
                factories.reprice_payload(discharged["version"]),
                headers=analyst,
            ),
            expected_status=201,
        )
        assert priced["priced_by_user_id"] == ANALYST_ID
        assert priced["status"] == DeterminationStatus.DRAFT

        # The officer reads the review; the nurse issues the query on it.
        reviews, _meta = validate_paginated(api.list_stay_reviews(stay["id"], headers=officer))
        review = reviews[0]
        issued = get_success_data(
            api.issue_query(review["id"], factories.issue_query_payload(), headers=nurse),
            expected_status=201,
        )
        assert issued["status"] == QueryStatus.ISSUED

        # The physician's lane: answering the query, which no nurse may do.
        answered = get_success_data(
            api.answer_query(
                issued["id"], factories.answer_query_payload(), headers=physician_headers
            ),
            expected_status=200,
        )
        assert answered["status"] == QueryStatus.ANSWERED

        # Back to the nurse's lane to close it, then the officer rescores and clears.
        closed = get_success_data(api.close_query(issued["id"], headers=second_nurse))
        assert closed["status"] == QueryStatus.CLOSED
        rescored = get_success_data(api.rescore_review(review["id"], headers=officer))
        assert rescored["status"] == ReviewStatus.OPEN
        resolved = get_success_data(
            api.resolve_review(review["id"], factories.resolve_review_payload(), headers=officer)
        )
        assert resolved["status"] == ReviewStatus.CLEARED

        # The second analyst accepts what the first priced.
        finalized = get_success_data(
            api.finalize_determination(priced["id"], headers=second_analyst)
        )
        assert finalized["status"] == DeterminationStatus.FINAL
        assert finalized["finalized_by_user_id"] == ANALYST_2_ID

    @pytest.mark.parametrize("role", UserRole.ALL)
    def test_the_logical_clock_is_the_one_operation_every_role_may_invoke(
        self, api, officer, role
    ):
        """Each of the five declared roles can advance the logical clock.

        Setting the clock is deliberately not owned by any single lane, so the same call is
        made once per role. The physician's identity has to name a real physician row, which
        is why one is registered first; the other four roles are opaque operator identities.
        Each call must be accepted and must report the instant it replaced.

        PRD 2.4: "An operator in any of the five roles may advance the clock by supplying a `current_utc` instant; the response reports the new `current_utc` alongside the `previous_utc` it replaced."

        Design: Corner/rbac/every_role_can_run_its_own_exclusive_operations
        """
        physician = fixtures.add_physician(api, headers=officer)
        headers = (
            make_attending_physician_headers(physician["id"])
            if role == UserRole.ATTENDING_PHYSICIAN
            else OPAQUE_ROLE_HEADERS[role]
        )

        clock = get_success_data(api.set_clock(DISCHARGE_CLOCK, headers=headers))

        assert_instant_equals(clock["current_utc"], DISCHARGE_CLOCK, field="current_utc")
        assert_instant_equals(clock["previous_utc"], CLOCK_EPOCH, field="previous_utc")

    @pytest.mark.parametrize("filed_by", ["nurse", "physician"])
    def test_a_note_may_be_filed_by_either_the_nurse_or_the_attending_physician(
        self, api, filed_by
    ):
        """Interdisciplinary documentation is the one clinical write two roles share.

        The nurse owns stay documentation and the physician owns the clinical record, and
        the note endpoint admits both. Filing the same physician-discipline note once as
        each role must be accepted both times, and the stay must end up carrying the note
        either way.

        PRD 3.4: "Either a `UtilizationReviewNurse` or an `AttendingPhysician` may file a note against a stay."

        Design: Corner/rbac/every_role_can_run_its_own_exclusive_operations
        """
        admission = fixtures.admitted_stay(api)
        headers = (
            NURSE_HEADERS if filed_by == "nurse" else admission.world.physician_headers
        )

        note = get_success_data(
            api.create_idt_note(
                admission.stay_id,
                factories.idt_note_payload(discipline=Discipline.PHYSICIAN),
                headers=headers,
            ),
            expected_status=201,
        )

        assert note["discipline"] == Discipline.PHYSICIAN
        filed = fixtures.notes_of(api, admission.stay_id)
        assert [n["id"] for n in filed] == [note["id"]]


def _cross_lane_world(api) -> dict:
    """A discharged, priced stay with an issued query, plus a referral awaiting admission.

    Everything a cross-lane attempt could need is in place and legal for the role that
    owns it, so the only thing wrong with each refused call below is who is making it.
    """
    admission = _discharged_stay(api)
    query = fixtures.issue_query(api, admission.review_id)
    waiting_patient = fixtures.add_patient(api)
    waiting_referral = fixtures.qualified_referral(
        api,
        admission.world,
        patient_id=waiting_patient["id"],
        patient_version=waiting_patient["version"],
    )
    stay = fixtures.read_stay(api, admission.stay_id)
    return {
        "admission": admission,
        "referral_id": waiting_referral["id"],
        "stay_id": admission.stay_id,
        "stay_version": stay["version"],
        "review_id": admission.review_id,
        "determination_id": admission.determination_id,
        "query_id": query["id"],
        "period_id": admission.world.period_id,
        "physician_headers": admission.world.physician_headers,
    }


def _admit_as_the_nurse(api, ctx):
    return api.admit_referral(ctx["referral_id"], factories.admit_payload(), headers=NURSE_HEADERS)


def _discharge_as_the_intake_coordinator(api, ctx):
    return api.discharge_stay(
        ctx["stay_id"], factories.discharge_payload(), headers=INTAKE_HEADERS
    )


def _price_as_the_compliance_officer(api, ctx):
    return api.reprice_stay(
        ctx["stay_id"], factories.reprice_payload(ctx["stay_version"]), headers=OFFICER_HEADERS
    )


def _resolve_the_review_as_the_analyst(api, ctx):
    return api.resolve_review(
        ctx["review_id"], factories.resolve_review_payload(), headers=ANALYST_HEADERS
    )


def _answer_the_query_as_the_nurse(api, ctx):
    return api.answer_query(
        ctx["query_id"], factories.answer_query_payload(), headers=NURSE_HEADERS
    )


def _close_the_query_as_the_physician(api, ctx):
    return api.close_query(ctx["query_id"], headers=ctx["physician_headers"])


CROSS_LANE_WRITES = (
    pytest.param(_admit_as_the_nurse, id="nurse_admits"),
    pytest.param(_discharge_as_the_intake_coordinator, id="intake_discharges"),
    pytest.param(_price_as_the_compliance_officer, id="officer_prices"),
    pytest.param(_resolve_the_review_as_the_analyst, id="analyst_resolves"),
    pytest.param(_answer_the_query_as_the_nurse, id="nurse_answers"),
    pytest.param(_close_the_query_as_the_physician, id="physician_closes"),
)


class TestNoRoleReachesIntoAnotherLane:
    """A declared role calling an endpoint that does not admit it."""

    @pytest.mark.parametrize("attempt", CROSS_LANE_WRITES)
    def test_a_write_owned_by_another_role_is_refused_as_unauthorized(self, api, attempt):
        """Six writes, each attempted by a declared role the endpoint does not admit.

        Admission belongs to the intake coordinator, discharge and query closure to the
        nurse, pricing to the analyst, review resolution to the officer, and answering a
        query to the physician alone. Each request below is otherwise perfectly formed —
        the referral qualifies, the stay is discharged, the version supplied is current and
        the query is issued — so the only defect is the role in the header. Because
        authorization is decided before path existence, foreign keys and every business
        rule, the answer must be the authorization refusal and not the state or concurrency
        error the same call would earn from its rightful owner.

        PRD 2.1: "If `X-User-Role` is absent, holds a value that is not one of these five spellings, or names a role that the requested endpoint does not admit, the request is refused with `ERR_UNAUTHORIZED` and HTTP status 403."
        PRD 2.8: "The server evaluates its checks in a fixed order and the **first** violated rule determines the response; no later check is evaluated once one has fired."

        Design: Corner/rbac/one_role_cannot_run_another_roles_exclusive_operation
        """
        ctx = _cross_lane_world(api)

        validate_error(attempt(api, ctx), ApiErrorId.ERR_UNAUTHORIZED)

    def test_the_nurse_may_not_browse_referrals_or_read_the_fiscal_envelope(self, api, nurse):
        """Two reads outside the nurse's documentation lane are refused.

        The nurse documents a stay; the referral queue belongs to intake and the cost
        reporting period to the officer and the analyst. Neither endpoint admits the nurse,
        so both reads are refused on the header alone even though both target existing,
        readable records.

        PRD 2.1: "If `X-User-Role` is absent, holds a value that is not one of these five spellings, or names a role that the requested endpoint does not admit, the request is refused with `ERR_UNAUTHORIZED` and HTTP status 403."
        PRD 2.1: "A `UtilizationReviewNurse` documents the stay: interdisciplinary notes, interruptions and returns, the ventilator weaning plan and its trial records, discharge, and the issuing and closing of documentation queries; a nurse may not answer a query, because only a physician may."

        Design: Corner/rbac/one_role_cannot_run_another_roles_exclusive_operation
        """
        world = fixtures.build_world(api)
        fixtures.qualified_referral(api, world)

        validate_error(api.list_referrals(headers=nurse), ApiErrorId.ERR_UNAUTHORIZED)
        validate_error(
            api.get_period(world.period_id, headers=nurse), ApiErrorId.ERR_UNAUTHORIZED
        )

    @pytest.mark.parametrize("identity", ["a_registered_physician", "an_unregistered_identity"])
    def test_the_physician_may_not_browse_a_stays_interruption_history(self, api, identity):
        """The interruption listing does not admit the physician, whoever the physician is.

        Interruptions are the nurse's ledger, read by the officer, the analyst and intake as
        well, but not by the physician. The refusal must be the same whether the acting
        `X-User-ID` names a physician the officer registered or an identity no physician row
        matches, because authorization reads the role header and never looks a caller up.

        PRD 2.1: "If `X-User-Role` is absent, holds a value that is not one of these five spellings, or names a role that the requested endpoint does not admit, the request is refused with `ERR_UNAUTHORIZED` and HTTP status 403."
        PRD 2.1: "Authorization is decided from the header alone; the API does not consult a user directory."

        Design: Corner/rbac/one_role_cannot_run_another_roles_exclusive_operation
        """
        admission = fixtures.admitted_stay(api)
        headers = (
            admission.world.physician_headers
            if identity == "a_registered_physician"
            else make_attending_physician_headers(UNKNOWN_PHYSICIAN_ID)
        )

        validate_error(
            api.list_interruptions(admission.stay_id, headers=headers),
            ApiErrorId.ERR_UNAUTHORIZED,
        )

    def test_a_refused_cross_lane_call_leaves_every_record_where_it_was(self, api, officer):
        """Refusing a call for its role header writes nothing.

        Every cross-lane write is attempted in turn against one prepared stay. Afterwards the
        stay must still be discharged and priced rather than re-priced or re-discharged, the
        issued query must still be waiting for its answer, and the referral must still be
        qualified rather than admitted — the refusals cost the store nothing.

        PRD 2.1: "If `X-User-Role` is absent, holds a value that is not one of these five spellings, or names a role that the requested endpoint does not admit, the request is refused with `ERR_UNAUTHORIZED` and HTTP status 403."
        PRD 2.8: "The server evaluates its checks in a fixed order and the **first** violated rule determines the response; no later check is evaluated once one has fired."

        Design: Corner/rbac/one_role_cannot_run_another_roles_exclusive_operation
        """
        ctx = _cross_lane_world(api)
        determinations_before = fixtures.determinations_of(api, ctx["stay_id"])

        for attempt in (
            _admit_as_the_nurse,
            _discharge_as_the_intake_coordinator,
            _price_as_the_compliance_officer,
            _resolve_the_review_as_the_analyst,
            _answer_the_query_as_the_nurse,
            _close_the_query_as_the_physician,
        ):
            validate_error(attempt(api, ctx), ApiErrorId.ERR_UNAUTHORIZED)

        stay = fixtures.read_stay(api, ctx["stay_id"])
        assert_stay_dimensions(stay, ClinicalStatus.DISCHARGED, PaymentReviewStatus.PRICED)
        assert stay["version"] == ctx["stay_version"]
        assert fixtures.read_query(api, ctx["query_id"])["status"] == QueryStatus.ISSUED
        assert (
            fixtures.read_review(api, ctx["review_id"])["status"] == ReviewStatus.QUERIES_ISSUED
        )
        assert (
            fixtures.read_referral(api, ctx["referral_id"])["status"]
            == ReferralStatus.CRITERIA_MET
        )
        assert fixtures.determinations_of(api, ctx["stay_id"]) == determinations_before


class TestARoleNameOutsideTheDeclaredFiveCannotAct:
    """An undeclared role name, an empty one and a missing header, on a read and a write."""

    @pytest.mark.parametrize("headers", ROLELESS_HEADER_VARIANTS)
    def test_a_read_from_a_caller_naming_no_declared_role_is_refused(self, api, headers):
        """A read is refused when the role header is undeclared, empty or absent.

        The period exists and is readable by three of the five roles, so nothing about the
        target is wrong. What is wrong is the caller: `WardClerk` is not one of the five
        spellings, an empty value names no role at all, and an omitted header names none
        either. All three land on the same refusal, and none of them may be answered with
        the record.

        PRD 2.1: "There are exactly five roles, spelled exactly as follows: `ComplianceOfficer`, `IntakeCoordinator`, `UtilizationReviewNurse`, `AttendingPhysician`, and `RevenueIntegrityAnalyst`."
        PRD 2.1: "If `X-User-Role` is absent, holds a value that is not one of these five spellings, or names a role that the requested endpoint does not admit, the request is refused with `ERR_UNAUTHORIZED` and HTTP status 403."

        Design: Corner/rbac/an_unknown_or_absent_role_header_cannot_act
        """
        period = fixtures.open_period(api)

        validate_error(
            api.get_period(period["id"], headers=headers), ApiErrorId.ERR_UNAUTHORIZED
        )

    @pytest.mark.parametrize("headers", ROLELESS_HEADER_VARIANTS)
    def test_a_write_from_a_caller_naming_no_declared_role_is_refused(self, api, headers):
        """A write is refused on the same three header defects, payload notwithstanding.

        The patient payload is complete and valid, so an authorized officer or intake
        coordinator would have it accepted. Presented by a caller whose role header names
        nothing declared, it is refused instead, and the refusal is the authorization one
        rather than anything about the body.

        PRD 2.8: "**Authorization.** `X-User-Role` names a declared role and that role is permitted to invoke this endpoint."
        PRD 2.1: "If `X-User-Role` is absent, holds a value that is not one of these five spellings, or names a role that the requested endpoint does not admit, the request is refused with `ERR_UNAUTHORIZED` and HTTP status 403."

        Design: Corner/rbac/an_unknown_or_absent_role_header_cannot_act
        """
        validate_error(
            api.create_patient(factories.patient_payload(), headers=headers),
            ApiErrorId.ERR_UNAUTHORIZED,
        )

    def test_a_write_refused_for_its_role_header_leaves_the_record_uncreated(self, api, officer):
        """The refused registration writes no patient row at all.

        A medical record number is unique across patients, so re-offering the identical
        payload under an officer's headers is a direct probe of whether the refused attempt
        wrote anything: had the row landed, the second call would collide. It is accepted
        instead, which proves the store was untouched.

        PRD 2.8: "`DrgRateEntry.drg_code`, `ReferringHospital.npi`, `Physician.npi`, `Patient.mrn`, `AdmissionCriteriaSet.label` and `CostReportingPeriod.period_label` are each unique; a new criteria set's `effective_from` must be strictly after the `effective_from` of every `ACTIVE` set; a new period's `start_date` through `end_date` range must not overlap an existing period and only one period may be `OPEN` at a time."
        PRD 2.1: "If `X-User-Role` is absent, holds a value that is not one of these five spellings, or names a role that the requested endpoint does not admit, the request is refused with `ERR_UNAUTHORIZED` and HTTP status 403."

        Design: Corner/rbac/an_unknown_or_absent_role_header_cannot_act
        """
        payload = factories.patient_payload()

        validate_error(
            api.create_patient(payload, headers=make_headers("clerk-a", UNKNOWN_ROLE)),
            ApiErrorId.ERR_UNAUTHORIZED,
        )

        created = get_success_data(
            api.create_patient(payload, headers=officer), expected_status=201
        )
        assert created["mrn"] == payload["mrn"]


class TestASegregatedDutyNeedsTwoIdentities:
    """Three operations where the role is right and only the acting identity is wrong."""

    def test_the_nurse_who_issued_a_query_may_not_close_it(self, api, nurse, second_nurse):
        """Closing an answered query requires a nurse other than the one who issued it.

        Both callers hold the nurse role and the endpoint admits them both, so nothing here
        turns on authorization: the issuing nurse is refused solely because the query records
        her as its issuer, and a second nurse — identical in every way but identity — closes
        the same query. The recorded closer is the one who actually closed it.

        PRD 2.1: "Segregation of duties is enforced on three operations and produces `ERR_SEGREGATION_OF_DUTIES` with HTTP status 403."
        PRD 2.1: "And the `X-User-ID` closing a documentation query must differ from that query's `issued_by_user_id`."
        PRD 3.8: "The transition is `ANSWERED → CLOSED`, `closed_by_user_id` records the acting nurse's `X-User-ID`, and the query keeps its answered-query credit in the score."

        Design: Corner/rbac/the_same_user_cannot_price_and_finalize_or_issue_and_close
        """
        admission = _discharged_stay(api)
        query = fixtures.issue_query(api, admission.review_id, headers=nurse)
        fixtures.answer_query(api, query["id"], admission.world.physician_headers)

        validate_error(
            api.close_query(query["id"], headers=nurse), ApiErrorId.ERR_SEGREGATION_OF_DUTIES
        )

        closed = get_success_data(api.close_query(query["id"], headers=second_nurse))
        assert closed["status"] == QueryStatus.CLOSED
        assert closed["closed_by_user_id"] == NURSE_2_ID

    def test_the_analyst_who_priced_a_determination_may_not_finalize_it(
        self, api, analyst, second_analyst
    ):
        """Accepting a price requires an analyst other than the one who set it.

        The stay is re-priced by the first analyst, which stamps that analyst on the draft as
        the one who priced it, and the review is cleared so that nothing but the identity
        check stands between the draft and `FINAL`. The pricing analyst is refused; the second
        analyst succeeds and is recorded as the one who finalized.

        PRD 2.1: "The `X-User-ID` finalizing a determination must differ from that determination's `priced_by_user_id`."
        PRD 2.1: "In all three cases both actors necessarily hold the same role, so only the identity distinguishes them."
        PRD 3.7: "On success `finalized_by_user_id` records the acting `X-User-ID`, the stay's `payment_review_status` moves `PRICED → FINALIZED`, the period's `total_payment_cents` is increased by this determination's `total_payment_cents`, and the period's `final_determination_count` is increased by 1."

        Design: Corner/rbac/the_same_user_cannot_price_and_finalize_or_issue_and_close
        """
        admission = _discharged_stay(api)
        priced = fixtures.reprice(
            api, admission.stay_id, admission.stay["version"], headers=analyst
        )
        assert priced["priced_by_user_id"] == ANALYST_ID
        fixtures.resolve_review(api, admission.review_id, outcome=ReviewOutcome.CLEARED)

        validate_error(
            api.finalize_determination(priced["id"], headers=analyst),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        )

        finalized = get_success_data(
            api.finalize_determination(priced["id"], headers=second_analyst)
        )
        assert finalized["status"] == DeterminationStatus.FINAL
        assert finalized["finalized_by_user_id"] == ANALYST_2_ID

    def test_the_analyst_who_finalized_a_determination_may_not_void_it(
        self, api, analyst, second_analyst, third_analyst
    ):
        """Reversing a final determination requires an analyst other than the one who accepted it.

        Three analysts take the three steps the ledger separates: the first prices, the second
        accepts, and only a third may reverse. The second analyst's void is refused on identity
        alone, and the third analyst's void unwinds the period ledger to exactly where it stood
        before the acceptance.

        PRD 2.1: "The `X-User-ID` voiding a determination that is currently `FINAL` must differ from that determination's `finalized_by_user_id`."
        PRD 3.7: "Voiding a `FINAL` determination is `FINAL → VOIDED`, requires that the acting `X-User-ID` differ from the determination's `finalized_by_user_id`, sets the stay's `payment_review_status` back to `PENDING` and clears `discharge_payment_pct`, and unwinds the ledger exactly: the period's `total_payment_cents` is decreased by this determination's `total_payment_cents` and its `final_determination_count` is decreased by 1, returning both to their pre-finalization values."

        Design: Corner/rbac/the_same_user_cannot_price_and_finalize_or_issue_and_close
        """
        admission = _discharged_stay(api)
        priced = fixtures.reprice(
            api, admission.stay_id, admission.stay["version"], headers=analyst
        )
        fixtures.resolve_review(api, admission.review_id, outcome=ReviewOutcome.CLEARED)
        fixtures.finalize(api, priced["id"], headers=second_analyst)

        validate_error(
            api.void_determination(priced["id"], factories.void_payload(), headers=second_analyst),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        )

        voided = get_success_data(
            api.void_determination(priced["id"], factories.void_payload(), headers=third_analyst)
        )
        assert voided["status"] == DeterminationStatus.VOIDED
        assert_period_ledger(
            fixtures.read_period(api, admission.world.period_id),
            total_payment_cents=0,
            final_determination_count=0,
        )
