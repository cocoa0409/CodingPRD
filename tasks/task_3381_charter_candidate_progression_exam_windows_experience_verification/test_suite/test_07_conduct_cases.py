"""Professional-conduct statements and misconduct cases: statement uniqueness,
the disclosure auto-open cascade, incident-origin forcing, one-live-case per
appointment, role and segregation-of-duties rules, the appeal window, and OCC
on adjudication."""
from test_helpers import (
    ApiErrorId,
    adjudicate_case,
    adjudicate_case_payload,
    appeal_case,
    appeal_case_payload,
    book_appointment,
    conduct_statement_payload,
    create_candidate,
    create_misconduct_case_payload,
    file_conduct_statement,
    get_appointment,
    get_candidate,
    get_misconduct_case,
    list_misconduct_cases,
    make_candidate_headers,
    make_conduct_adjudicator_headers,
    make_conduct_investigator_headers,
    make_proctor_headers,
    open_external_case,
    set_logical_clock,
    setup_bookable_context,
    validate_error,
    validate_success,
)

CLOCK = "2027-01-05T00:00:00Z"


class TestConductStatements:
    def test_duplicate_conduct_statement_rejected(self, api):
        """PRD §3.7: "Filing appends an entry — `disclosure_year`,
        `has_disclosures`, an optional `disclosure_text`, and the filing
        timestamp — to the candidate's `conduct_statements` collection, and the
        pair of candidate and `disclosure_year` must be unique, else
        `ERR_DUPLICATE_CONDUCT_STATEMENT`."

        Design: Corner/errors/c_duplicate_conduct_statement_rejected
        """
        set_logical_clock(CLOCK)
        candidate = create_candidate()
        file_conduct_statement(candidate, disclosure_year=2027, has_disclosures=False)
        resp = api.file_conduct_statement(
            candidate["id"],
            conduct_statement_payload(
                2027, has_disclosures=True, disclosure_text="Late disclosure"
            ),
            make_candidate_headers(candidate["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CONDUCT_STATEMENT)
        assert resp.status_code == 409
        after = get_candidate(candidate["id"])
        assert len(after["conduct_statements"]) == 1

    def test_pcs_disclosure_auto_opens_case(self, api):
        """PRD §3.7: "A statement whose `has_disclosures` is true automatically
        opens a misconduct case against the candidate: the case is born `OPENED`
        with `origin` `CONDUCT_STATEMENT` and a `null` `investigator_user_id`,
        there being no human investigator."

        Design: Corner/cross_cutting_layers/c_pcs_disclosure_auto_opens_case
        """
        set_logical_clock(CLOCK)
        candidate = create_candidate()
        file_conduct_statement(candidate, disclosure_year=2026, has_disclosures=False)
        file_conduct_statement(
            candidate,
            disclosure_year=2027,
            has_disclosures=True,
            disclosure_text="Regulatory inquiry disclosed",
        )
        cases = list_misconduct_cases(params={"candidate_id": candidate["id"]})
        assert len(cases) == 1
        assert cases[0]["origin"] == "CONDUCT_STATEMENT"
        assert cases[0]["status"] == "OPENED"
        assert cases[0]["investigator_user_id"] is None


class TestCaseCreation:
    def test_case_create_with_appointment_forces_incident_origin(self, api):
        """PRD §3.7: "When an `appointment_id` is present the case reports an
        exam-day incident: its `origin` becomes `EXAM_INCIDENT` and the flagged
        appointment's `compliance_status` moves from `CLEAR` to
        `POLICY_FLAGGED`; a manual case without an appointment defaults its
        `origin` to `EXTERNAL_REPORT`."
        PRD §3.7: "The acting operator's identifier is recorded as
        `investigator_user_id`."

        Design: Corner/endpoints/c_case_create_with_appointment_forces_incident_origin
        """
        context = setup_bookable_context()
        appointment = book_appointment(context, pay_fee=False)
        incident_resp = api.create_misconduct_case(
            create_misconduct_case_payload(
                context["candidate"]["id"],
                allegation="Prohibited notes in the testing room",
                appointment_id=appointment["id"],
                origin="EXTERNAL_REPORT",
            ),
            make_proctor_headers("prt-7"),
        )
        incident = validate_success(incident_resp, 201)
        assert incident["origin"] == "EXAM_INCIDENT"
        assert incident["investigator_user_id"] == "prt-7"
        assert (
            get_appointment(appointment["id"])["compliance_status"]
            == "POLICY_FLAGGED"
        )
        manual_resp = api.create_misconduct_case(
            create_misconduct_case_payload(
                context["candidate"]["id"], allegation="Employer complaint"
            ),
            make_conduct_investigator_headers("inv-1"),
        )
        manual = validate_success(manual_resp, 201)
        assert manual["origin"] == "EXTERNAL_REPORT"
        rows = list_misconduct_cases(params={"appointment_id": appointment["id"]})
        assert len(rows) == 1

    def test_second_case_on_flagged_appointment_rejected(self, api):
        """PRD §3.7: "An appointment may carry only one case in `OPENED`,
        `SANCTIONED` or `APPEALED` state at a time — a second is rejected with
        `ERR_CASE_ALREADY_OPEN_FOR_APPOINTMENT`."

        Design: Corner/errors/c_second_case_on_flagged_appointment_rejected
        """
        context = setup_bookable_context()
        appointment = book_appointment(context, pay_fee=False)
        first = api.create_misconduct_case(
            create_misconduct_case_payload(
                context["candidate"]["id"],
                allegation="Notes incident",
                appointment_id=appointment["id"],
            ),
            make_proctor_headers("prt-7"),
        )
        validate_success(first, 201)
        second = api.create_misconduct_case(
            create_misconduct_case_payload(
                context["candidate"]["id"],
                allegation="Second report",
                appointment_id=appointment["id"],
            ),
            make_conduct_investigator_headers("inv-1"),
        )
        validate_error(second, ApiErrorId.ERR_CASE_ALREADY_OPEN_FOR_APPOINTMENT)
        assert second.status_code == 409
        rows = list_misconduct_cases(params={"appointment_id": appointment["id"]})
        assert len(rows) == 1

    def test_candidate_cannot_open_cases(self, api):
        """PRD §2.1: "A request whose role is not listed among the roles
        authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."

        Design: Corner/rbac/c_candidate_cannot_open_cases
        """
        set_logical_clock(CLOCK)
        candidate = create_candidate()
        resp = api.create_misconduct_case(
            create_misconduct_case_payload(candidate["id"], allegation="Self report"),
            make_candidate_headers(candidate["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert resp.status_code == 403
        assert list_misconduct_cases(params={"candidate_id": candidate["id"]}) == []


class TestAdjudication:
    def test_segregation_of_duties_blocks_investigator_adjudicating(self, api):
        """PRD §3.7: "the adjudicator's `X-User-ID` must differ from the case's
        `investigator_user_id` whenever that field is non-null, else
        `ERR_SEGREGATION_OF_DUTIES`; auto-opened statement cases, whose
        investigator is `null`, carry no such bar."

        Design: Corner/rbac/c_segregation_of_duties_blocks_investigator_adjudicating
        """
        set_logical_clock(CLOCK)
        candidate = create_candidate()
        case = open_external_case(candidate["id"], investigator_user_id="inv-1")
        blocked = api.adjudicate_misconduct_case(
            case["id"],
            adjudicate_case_payload(
                expected_case_version=case["version"],
                outcome="SANCTIONED",
                sanction_type="WARNING",
            ),
            make_conduct_adjudicator_headers("inv-1"),
        )
        validate_error(blocked, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert blocked.status_code == 403
        untouched = get_misconduct_case(case["id"])
        assert untouched["status"] == "OPENED"
        assert untouched["version"] == case["version"]
        sanctioned = adjudicate_case(
            case,
            outcome="SANCTIONED",
            sanction_type="WARNING",
            adjudicator_user_id="adj-2",
        )
        assert sanctioned["status"] == "SANCTIONED"

    def test_appeal_after_30_days_expired(self, api):
        """PRD §3.7: "The sanctioned candidate — and only the candidate whose
        case it is — may appeal, moving the case from `SANCTIONED` to
        `APPEALED` (from anything else, `ERR_INVALID_CASE_STATE`), provided the
        logical clock is no later than thirty days after `sanctioned_at`, else
        `ERR_APPEAL_WINDOW_EXPIRED`."

        Design: Corner/errors/c_appeal_after_30_days_expired
        """
        set_logical_clock(CLOCK)
        candidate = create_candidate()
        case = open_external_case(candidate["id"], investigator_user_id="inv-1")
        set_logical_clock("2027-03-20T00:00:00Z")
        adjudicate_case(
            case,
            outcome="SANCTIONED",
            sanction_type="WARNING",
            adjudicator_user_id="adj-1",
        )
        set_logical_clock("2027-04-20T00:00:00Z")
        late = api.appeal_misconduct_case(
            case["id"],
            appeal_case_payload("Too late"),
            make_candidate_headers(candidate["id"]),
        )
        validate_error(late, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED)
        assert late.status_code == 422
        set_logical_clock("2027-04-19T00:00:00Z")
        in_time = appeal_case(case, candidate, appeal_reason="Just in time")
        assert in_time["status"] == "APPEALED"

    def test_occ_adjudicate_stale_version_returns_412(self, api):
        """PRD §2.7: "Adjudicating a misconduct case requires
        `expected_case_version`, carrying the caller's last observed `version`
        of that case; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP
        412), since an appeal or a prior adjudication has advanced the case
        beyond the caller's observation."

        Design: Corner/cross_cutting_layers/c_occ_adjudicate_stale_version_returns_412
        """
        set_logical_clock(CLOCK)
        candidate = create_candidate()
        case = open_external_case(candidate["id"], investigator_user_id="inv-1")
        adjudicate_case(
            case,
            outcome="SANCTIONED",
            sanction_type="WARNING",
            adjudicator_user_id="adj-1",
        )
        appealed = appeal_case(case, candidate, appeal_reason="Disproportionate")
        assert appealed["version"] == case["version"] + 2
        stale = api.adjudicate_misconduct_case(
            case["id"],
            adjudicate_case_payload(
                expected_case_version=case["version"], outcome="DISMISSED"
            ),
            make_conduct_adjudicator_headers("adj-1"),
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        assert stale.status_code == 412
        current = get_misconduct_case(case["id"])
        assert current["status"] == "APPEALED"
        assert current["version"] == appealed["version"]
