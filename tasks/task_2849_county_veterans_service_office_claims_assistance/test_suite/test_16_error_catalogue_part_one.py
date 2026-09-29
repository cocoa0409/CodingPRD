"""
The error catalogue, part one: headers, shape, existence and accreditation.

Every refusal here is paired either with the neighbouring request that is
accepted or with a read proving the addressed row was there all along.
"""

import pytest
from test_helpers import (
    CLOCK_START_INSTANT,
    INTAKE_CLERK_HEADERS,
    NON_EXISTENT_UUID,
    NO_HEADERS,
    SYSTEM_ADMIN_HEADERS,
    UNKNOWN_COUNTY_OFFICER_HEADERS,
    accreditation_action,
    assert_exact_whole,
    assert_screen_categories,
    assert_versioned_shape,
    assign_representative_payload,
    benefit_application_payload,
    create_active_representative,
    create_screened_veteran,
    create_state_program,
    create_veteran,
    deactivate_action,
    file_benefit_application,
    headers_with_bad_role,
    hold_outreach_action,
    make_county_officer_headers,
    open_outcome_report,
    outcome_report_payload,
    outreach_event_payload,
    plan_outreach_event,
    read_representative,
    read_state_program,
    read_veteran,
    register_representative,
    representative_payload,
    set_clock,
    set_clock_date,
    state_program_payload,
    submit_discharge_document,
    validate_error,
    validate_paginated,
    validate_success,
    verify_document_action,
)


@pytest.fixture(autouse=True)
def _clock(api):
    """Every test in this module starts at the logical clock's opening instant."""
    set_clock(api, CLOCK_START_INSTANT)


class TestAuthHeaderFaultsAreResolvedBeforeAnyRowLookup:
    """Three header faults, three codes, all on a veteran that exists."""

    @pytest.fixture
    def existing_veteran(self, api):
        """One intake row the faulty requests below all address."""
        return create_veteran(api)

    def test_omitting_both_headers_is_the_missing_header_code(
        self, api, existing_veteran
    ):
        """
        "Both `X-User-Role` and `X-User-ID` are present and non-empty, else `ERR_MISSING_AUTH_HEADERS` (401), on every endpoint."

        Design: Corner/errors/corner_auth_header_faults_are_resolved_before_any_row_lookup
        """
        validate_error(
            api.get_veteran(existing_veteran["id"], NO_HEADERS),
            "ERR_MISSING_AUTH_HEADERS",
            401,
        )
        assert read_veteran(api, existing_veteran["id"])["id"] == existing_veteran["id"]

    def test_a_role_name_outside_the_five_is_the_invalid_role_code(
        self, api, existing_veteran
    ):
        """
        "`X-User-Role` is exactly one of the five role names, else `ERR_INVALID_ROLE` (401), on every endpoint."

        Design: Corner/errors/corner_auth_header_faults_are_resolved_before_any_row_lookup
        """
        validate_error(
            api.get_veteran(existing_veteran["id"], headers_with_bad_role("Auditor")),
            "ERR_INVALID_ROLE",
            401,
        )

    def test_an_officer_identifier_backing_no_row_is_the_unknown_actor_code(
        self, api, existing_veteran
    ):
        """
        "For an entity-backed role, `X-User-ID` resolves to an existing row of its backing entity, else `ERR_UNKNOWN_ACTOR` (403), on every endpoint whose role list includes `CountyOfficer` or `VeteranClient`."

        Design: Corner/errors/corner_auth_header_faults_are_resolved_before_any_row_lookup
        """
        validate_error(
            api.get_veteran(existing_veteran["id"], UNKNOWN_COUNTY_OFFICER_HEADERS),
            "ERR_UNKNOWN_ACTOR",
            403,
        )
        validate_success(
            api.get_veteran(existing_veteran["id"], INTAKE_CLERK_HEADERS), 200
        )


class TestPaginationBoundsAreRejectedOutsideOneToOneHundred:
    """The window arguments are validated before the collection is read."""

    @pytest.mark.parametrize(
        "params",
        [{"limit": 0}, {"limit": 101}, {"offset": -1}],
        ids=["limit-below-one", "limit-above-one-hundred", "negative-offset"],
    )
    def test_a_window_outside_the_declared_range_is_refused(self, api, params):
        """
        "`limit` is an integer from 1 through 100 and `offset` is an integer of at least 0, else `ERR_INVALID_PAGINATION` (422), on every collection GET endpoint."

        Design: Corner/errors/corner_pagination_bounds_are_rejected_outside_one_to_one_hundred
        """
        validate_error(
            api.list_veterans(INTAKE_CLERK_HEADERS, params=params),
            "ERR_INVALID_PAGINATION",
            422,
        )

    def test_the_widest_legal_window_is_accepted_on_the_empty_collection(self, api):
        """
        "The four pagination fields are `limit` (the effective page size actually applied), `offset` (the effective starting position actually applied), `total_count` (the number of rows matching the filter before the page window is applied) and `has_more` (true when `offset` plus the number of returned rows is strictly less than `total_count`)."

        Design: Corner/errors/corner_pagination_bounds_are_rejected_outside_one_to_one_hundred
        """
        rows, meta = validate_paginated(
            api.list_veterans(INTAKE_CLERK_HEADERS, params={"limit": 100, "offset": 0})
        )
        assert rows == []
        assert_exact_whole(meta["limit"], 100, "limit")
        assert_exact_whole(meta["offset"], 0, "offset")
        assert_exact_whole(meta["total_count"], 0, "total_count")
        assert meta["has_more"] is False


class TestUndeclaredDispatchActionReturnsUnknownAction:
    """A verb the endpoint never declared is a shape fault, not a state fault."""

    def test_suspend_is_not_an_accreditation_action(self, api):
        """
        "The `action` field carries one of the values the addressed dispatch endpoint declares, else `ERR_UNKNOWN_ACTION` (422); this applies to the eleven dispatch endpoints — `POST /cvso/representatives/{id}/accreditation`, `POST /cvso/veterans/{id}/status`, `POST /cvso/discharge-documents/{id}/review`, `POST /cvso/claims/{id}/transitions`, `POST /cvso/evidence-items/{id}/status`, `POST /cvso/exam-appointments/{id}/status`, `POST /cvso/decision-reviews/{id}/status`, `POST /cvso/state-benefit-applications/{id}/determination`, `POST /cvso/state-benefit-applications/{id}/disbursement`, `POST /cvso/outreach-events/{id}/status` and `POST /cvso/outcome-reports/{id}/review`."

        Design: Corner/errors/corner_undeclared_dispatch_action_returns_unknown_action
        """
        representative = register_representative(api)
        validate_error(
            api.representative_accreditation(
                representative["id"],
                accreditation_action("SUSPEND"),
                SYSTEM_ADMIN_HEADERS,
            ),
            "ERR_UNKNOWN_ACTION",
            422,
        )
        stored = read_representative(api, representative["id"])
        assert stored["accreditation_status"] == "PENDING"
        assert_versioned_shape(stored, expected_version=1)


class TestEveryEntitySpecificNotFoundCodeIsReachable:
    """The same unused identifier answers with a different code per entity."""

    def test_the_six_families_named_by_their_own_resolution_rules(self, api):
        """
        "The first unresolvable reference decides the code, and the code is the entity-specific one wherever the addressed entity has one."

        Design: Corner/errors/corner_every_entity_specific_not_found_code_is_reachable
        """
        validate_error(
            api.get_veteran(NON_EXISTENT_UUID, INTAKE_CLERK_HEADERS),
            "ERR_VETERAN_NOT_FOUND",
            404,
        )
        validate_error(
            api.get_representative(NON_EXISTENT_UUID, SYSTEM_ADMIN_HEADERS),
            "ERR_REPRESENTATIVE_NOT_FOUND",
            404,
        )
        validate_error(
            api.get_claim(NON_EXISTENT_UUID, SYSTEM_ADMIN_HEADERS),
            "ERR_CLAIM_NOT_FOUND",
            404,
        )
        validate_error(
            api.get_power_of_attorney(NON_EXISTENT_UUID, SYSTEM_ADMIN_HEADERS),
            "ERR_POA_NOT_FOUND",
            404,
        )
        validate_error(
            api.get_exam_site(NON_EXISTENT_UUID, SYSTEM_ADMIN_HEADERS),
            "ERR_EXAM_SITE_NOT_FOUND",
            404,
        )
        validate_error(
            api.get_state_program(NON_EXISTENT_UUID, SYSTEM_ADMIN_HEADERS),
            "ERR_STATE_PROGRAM_NOT_FOUND",
            404,
        )

    def test_the_seven_families_whose_code_covers_only_their_own_path_id(self, api):
        """
        "The remaining entity-specific 404 codes cover an unresolvable path id on their own entity: `ERR_DISCHARGE_DOCUMENT_NOT_FOUND` for a discharge document, `ERR_EVIDENCE_ITEM_NOT_FOUND` for an evidence item, `ERR_EXAM_APPOINTMENT_NOT_FOUND` for an examination appointment, `ERR_DECISION_REVIEW_NOT_FOUND` for a decision review, `ERR_BENEFIT_APPLICATION_NOT_FOUND` for a state benefit application, `ERR_OUTREACH_EVENT_NOT_FOUND` for an outreach event and `ERR_OUTCOME_REPORT_NOT_FOUND` for an outcome report — each also HTTP 404."

        Design: Corner/errors/corner_every_entity_specific_not_found_code_is_reachable
        """
        validate_error(
            api.get_discharge_document(NON_EXISTENT_UUID, INTAKE_CLERK_HEADERS),
            "ERR_DISCHARGE_DOCUMENT_NOT_FOUND",
            404,
        )
        validate_error(
            api.get_evidence_item(NON_EXISTENT_UUID, SYSTEM_ADMIN_HEADERS),
            "ERR_EVIDENCE_ITEM_NOT_FOUND",
            404,
        )
        validate_error(
            api.get_exam_appointment(NON_EXISTENT_UUID, SYSTEM_ADMIN_HEADERS),
            "ERR_EXAM_APPOINTMENT_NOT_FOUND",
            404,
        )
        validate_error(
            api.get_decision_review(NON_EXISTENT_UUID, SYSTEM_ADMIN_HEADERS),
            "ERR_DECISION_REVIEW_NOT_FOUND",
            404,
        )
        validate_error(
            api.get_state_benefit_application(NON_EXISTENT_UUID, SYSTEM_ADMIN_HEADERS),
            "ERR_BENEFIT_APPLICATION_NOT_FOUND",
            404,
        )
        validate_error(
            api.get_outreach_event(NON_EXISTENT_UUID, SYSTEM_ADMIN_HEADERS),
            "ERR_OUTREACH_EVENT_NOT_FOUND",
            404,
        )
        validate_error(
            api.get_outcome_report(NON_EXISTENT_UUID, SYSTEM_ADMIN_HEADERS),
            "ERR_OUTCOME_REPORT_NOT_FOUND",
            404,
        )


class TestPendingAccreditationCannotActAsACountyOfficer:
    """The acting officer's own status is read before the addressed row's."""

    @pytest.fixture
    def waiting_document(self, api):
        """A document in PENDING_VERIFICATION and a representative still PENDING."""
        veteran = create_veteran(api)
        document = submit_discharge_document(api, veteran["id"])
        return {
            "document_id": document["id"],
            "pending_officer_headers": make_county_officer_headers(
                register_representative(api)["id"]
            ),
        }

    def test_a_pending_representative_may_not_adjudicate(self, api, waiting_document):
        """
        "The acting representative's `accreditation_status` is `ACTIVE`, else `ERR_REPRESENTATIVE_NOT_ACCREDITED` (403), on every endpoint whose role list includes `CountyOfficer`."

        Design: Corner/errors/corner_pending_accreditation_cannot_act_as_a_county_officer
        """
        validate_error(
            api.review_discharge_document(
                waiting_document["document_id"],
                verify_document_action(),
                waiting_document["pending_officer_headers"],
            ),
            "ERR_REPRESENTATIVE_NOT_ACCREDITED",
            403,
        )
        stored = validate_success(
            api.get_discharge_document(
                waiting_document["document_id"], INTAKE_CLERK_HEADERS
            ),
            200,
        )
        assert stored["verification_status"] == "PENDING_VERIFICATION"

    def test_an_active_representative_makes_the_identical_call_succeed(
        self, api, waiting_document
    ):
        """
        "Activation, named by the `action` value `ACTIVATE`, is available only from `PENDING`; it sets `accreditation_status` to `ACTIVE` and recomputes `caseload_weight`, which on a freshly activated row is 0 because the representative holds nothing yet."

        Design: Corner/errors/corner_pending_accreditation_cannot_act_as_a_county_officer
        """
        api.review_discharge_document(
            waiting_document["document_id"],
            verify_document_action(),
            waiting_document["pending_officer_headers"],
        )
        officer = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        verified = validate_success(
            api.review_discharge_document(
                waiting_document["document_id"],
                verify_document_action(),
                make_county_officer_headers(officer["id"]),
            ),
            200,
        )
        assert verified["verification_status"] == "VERIFIED"
        assert verified["verified_by_representative_id"] == officer["id"]


class TestExpiredAccreditationIsRefusedEvenWhileStatusReadsActive:
    """Nothing sweeps the status field, so the expiry date is checked on its own."""

    @pytest.fixture
    def stale_officer(self, api):
        """An ACTIVE representative activated before their expiry, read after it."""
        officer = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2026-12-31"
        )
        veteran = create_veteran(api)
        document = submit_discharge_document(api, veteran["id"])
        set_clock_date(api, "2027-01-01")
        return {
            "officer_id": officer["id"],
            "officer_headers": make_county_officer_headers(officer["id"]),
            "document_id": document["id"],
        }

    def test_a_past_expiry_refuses_the_action_while_the_status_still_reads_active(
        self, api, stale_officer
    ):
        """
        "An expiry date that has already passed refuses the action with `ERR_ACCREDITATION_EXPIRED` (HTTP 403) *even when* `accreditation_status` still reads `ACTIVE` — nothing sweeps the status field automatically, so a stale `ACTIVE` row with a past expiry is exactly the case this second check exists to catch."

        Design: Corner/errors/corner_expired_accreditation_is_refused_even_while_status_reads_active
        """
        validate_error(
            api.review_discharge_document(
                stale_officer["document_id"],
                verify_document_action(),
                stale_officer["officer_headers"],
            ),
            "ERR_ACCREDITATION_EXPIRED",
            403,
        )
        stored = read_representative(api, stale_officer["officer_id"])
        assert stored["accreditation_status"] == "ACTIVE"
        assert stored["accreditation_expires_on"] == "2026-12-31"

    def test_an_expiry_falling_on_the_clock_date_is_still_good_for_that_day(
        self, api, stale_officer
    ):
        """
        "The acting representative's `accreditation_expires_on` is not earlier than the logical-clock date, else `ERR_ACCREDITATION_EXPIRED` (403), on every endpoint whose role list includes `CountyOfficer`."

        Design: Corner/errors/corner_expired_accreditation_is_refused_even_while_status_reads_active
        """
        same_day = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2027-01-01"
        )
        verified = validate_success(
            api.review_discharge_document(
                stale_officer["document_id"],
                verify_document_action(),
                make_county_officer_headers(same_day["id"]),
            ),
            200,
        )
        assert verified["verification_status"] == "VERIFIED"
        assert verified["verified_by_representative_id"] == same_day["id"]


class TestAllFourUniquenessConstraintsAreEnforced:
    """Four scoped keys, four distinct duplicate codes."""

    def test_the_registry_number_is_unique_across_the_whole_roster(self, api):
        """
        "`accreditation_number` is not already held by another representative, else `ERR_DUPLICATE_ACCREDITATION_NUMBER` (409), on `POST /cvso/representatives` and `PATCH /cvso/representatives/{id}`."

        Design: Corner/errors/corner_all_four_uniqueness_constraints_are_enforced
        """
        held = register_representative(api, accreditation_number="ACC-2849-770")
        validate_error(
            api.create_representative(
                representative_payload(accreditation_number="ACC-2849-770"),
                SYSTEM_ADMIN_HEADERS,
            ),
            "ERR_DUPLICATE_ACCREDITATION_NUMBER",
            409,
        )
        other = register_representative(api, accreditation_number="ACC-2849-771")
        validate_error(
            api.update_representative(
                other["id"],
                {"accreditation_number": "ACC-2849-770"},
                SYSTEM_ADMIN_HEADERS,
            ),
            "ERR_DUPLICATE_ACCREDITATION_NUMBER",
            409,
        )
        assert read_representative(api, held["id"])["accreditation_number"] == (
            "ACC-2849-770"
        )
        assert read_representative(api, other["id"])["accreditation_number"] == (
            "ACC-2849-771"
        )

    def test_the_program_code_is_unique_across_all_programs(self, api):
        """
        "`program_code` is not already held by another program, else `ERR_DUPLICATE_PROGRAM_CODE` (409), on `POST /cvso/state-programs` and `PATCH /cvso/state-programs/{id}`."

        Design: Corner/errors/corner_all_four_uniqueness_constraints_are_enforced
        """
        first = create_state_program(api, program_code="PRG-2849-A", fiscal_year=2026)
        validate_error(
            api.create_state_program(
                state_program_payload(program_code="PRG-2849-A", fiscal_year=2027),
                SYSTEM_ADMIN_HEADERS,
            ),
            "ERR_DUPLICATE_PROGRAM_CODE",
            409,
        )
        stored = read_state_program(api, first["id"])
        assert stored["program_code"] == "PRG-2849-A"
        assert_versioned_shape(stored, expected_version=1)

    def test_the_quarter_label_is_unique_across_all_reports(self, api):
        """
        "`fiscal_quarter` is not already held by another outcome report, else `ERR_DUPLICATE_FISCAL_QUARTER` (409), on `POST /cvso/outcome-reports`."

        Design: Corner/errors/corner_all_four_uniqueness_constraints_are_enforced
        """
        officer = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        officer_headers = make_county_officer_headers(officer["id"])
        open_outcome_report(api, officer_headers, "2026Q2")
        validate_error(
            api.create_outcome_report(outcome_report_payload("2026Q2"), officer_headers),
            "ERR_DUPLICATE_FISCAL_QUARTER",
            409,
        )
        _rows, meta = validate_paginated(api.list_outcome_reports(officer_headers))
        assert_exact_whole(meta["total_count"], 1, "total_count")

    def test_the_open_application_triple_may_not_be_filed_twice(self, api):
        """
        "No other state benefit application exists with the same `veteran_id`, `program_id` and `fiscal_year` whose `determination_status` is `SUBMITTED` or `APPROVED`, else `ERR_DUPLICATE_BENEFIT_APPLICATION` (409), on `POST /cvso/state-benefit-applications`."

        Design: Corner/errors/corner_all_four_uniqueness_constraints_are_enforced
        """
        officer = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        built = create_screened_veteran(api, make_county_officer_headers(officer["id"]))
        program = create_state_program(
            api, program_type="PROPERTY_TAX_EXEMPTION", fiscal_year=2026
        )
        filed = file_benefit_application(
            api,
            built["veteran"]["id"],
            program,
            assessed_property_value_cents=8500000,
        )
        assert filed["determination_status"] == "SUBMITTED"
        validate_error(
            api.create_state_benefit_application(
                benefit_application_payload(
                    built["veteran"]["id"],
                    program["id"],
                    2026,
                    read_state_program(api, program["id"])["version"],
                    assessed_property_value_cents=8500000,
                ),
                INTAKE_CLERK_HEADERS,
            ),
            "ERR_DUPLICATE_BENEFIT_APPLICATION",
            409,
        )
        _rows, meta = validate_paginated(
            api.list_state_benefit_applications(INTAKE_CLERK_HEADERS)
        )
        assert_exact_whole(meta["total_count"], 1, "total_count")


class TestRequestShapeErrorsHaveTheirOwnCodes:
    """Three shape faults that are not the generic validation code."""

    @pytest.fixture
    def officer_headers(self, api):
        """One ACTIVE county officer, since two of these three are officer work."""
        officer = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        return make_county_officer_headers(officer["id"])

    def test_a_zero_length_outreach_block_is_the_interval_code(
        self, api, officer_headers
    ):
        """
        "`ends_at` is strictly greater than `starts_at`, else `ERR_INVALID_INTERVAL` (422), on `POST /cvso/exam-appointments` and `POST /cvso/outreach-events`."

        Design: Corner/errors/corner_request_shape_errors_have_their_own_codes
        """
        officer = create_active_representative(
            api, accreditation_type="VSO_ORG", accreditation_expires_on="2029-12-31"
        )
        validate_error(
            api.create_outreach_event(
                outreach_event_payload(
                    officer["id"],
                    "2026-08-05T09:00:00.000Z",
                    "2026-08-05T09:00:00.000Z",
                ),
                officer_headers,
            ),
            "ERR_INVALID_INTERVAL",
            422,
        )
        _rows, meta = validate_paginated(api.list_outreach_events(officer_headers))
        assert_exact_whole(meta["total_count"], 0, "total_count")

    def test_a_fifth_quarter_is_the_fiscal_quarter_code(self, api, officer_headers):
        """
        "`fiscal_quarter` is four digits followed by the letter Q followed by a single digit from 1 through 4, else `ERR_INVALID_FISCAL_QUARTER` (422), on `POST /cvso/outcome-reports`."

        Design: Corner/errors/corner_request_shape_errors_have_their_own_codes
        """
        validate_error(
            api.create_outcome_report(outcome_report_payload("2026Q5"), officer_headers),
            "ERR_INVALID_FISCAL_QUARTER",
            422,
        )
        opened = open_outcome_report(api, officer_headers, "2026Q4")
        assert opened["fiscal_quarter"] == "2026Q4"
        assert opened["status"] == "OPEN"

    def test_more_enrolments_than_contacts_is_the_headcount_code(
        self, api, officer_headers
    ):
        """
        "`veterans_enrolled` is less than or equal to `veterans_contacted`, else `ERR_ENROLLED_EXCEEDS_CONTACTED` (422), on an outreach `HOLD`."

        Design: Corner/errors/corner_request_shape_errors_have_their_own_codes
        """
        assignee = create_active_representative(
            api, accreditation_type="VSO_ORG", accreditation_expires_on="2029-12-31"
        )
        event = plan_outreach_event(
            api,
            assignee["id"],
            "2026-08-05T09:00:00.000Z",
            "2026-08-05T11:00:00.000Z",
        )
        set_clock_date(api, "2026-08-05", "12:00:00")
        validate_error(
            api.outreach_event_status(
                event["id"],
                hold_outreach_action(veterans_contacted=10, veterans_enrolled=12),
                officer_headers,
            ),
            "ERR_ENROLLED_EXCEEDS_CONTACTED",
            422,
        )
        held = validate_success(
            api.outreach_event_status(
                event["id"],
                hold_outreach_action(veterans_contacted=10, veterans_enrolled=10),
                officer_headers,
            ),
            200,
        )
        assert held["status"] == "HELD"
        assert_exact_whole(held["veterans_enrolled"], 10, "veterans_enrolled")


class TestShelteredHomelessVeteranCannotBeDeactivated:
    """The case stays open while the housing question is unresolved."""

    @pytest.fixture
    def sheltered_case(self, api):
        """An ACTIVE case whose veteran is living in shelter accommodation."""
        officer = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        built = create_screened_veteran(
            api, make_county_officer_headers(officer["id"]), homeless_status="SHELTERED"
        )
        assigned = validate_success(
            api.assign_representative(
                built["veteran"]["id"],
                assign_representative_payload(officer["id"]),
                INTAKE_CLERK_HEADERS,
            ),
            200,
        )
        assert assigned["intake_status"] == "ACTIVE"
        return {"veteran_id": built["veteran"]["id"]}

    def test_the_protected_case_refuses_deactivation(self, api, sheltered_case):
        """
        "A veteran whose `homeless_status` is `SHELTERED` or `UNSHELTERED` may not be deactivated, else `ERR_HOMELESS_VETERAN_PROTECTED` (409), on a veteran `DEACTIVATE`."

        Design: Corner/errors/corner_sheltered_homeless_veteran_cannot_be_deactivated
        """
        validate_error(
            api.veteran_status(
                sheltered_case["veteran_id"], deactivate_action(), INTAKE_CLERK_HEADERS
            ),
            "ERR_HOMELESS_VETERAN_PROTECTED",
            409,
        )
        stored = read_veteran(api, sheltered_case["veteran_id"])
        assert stored["intake_status"] == "ACTIVE"
        assert stored["homeless_status"] == "SHELTERED"

    def test_once_housed_the_same_case_deactivates(self, api, sheltered_case):
        """
        "**Deactivation** (`DEACTIVATE`) takes an `ACTIVE` case to `INACTIVE`."

        Design: Corner/errors/corner_sheltered_homeless_veteran_cannot_be_deactivated
        """
        api.veteran_status(
            sheltered_case["veteran_id"], deactivate_action(), INTAKE_CLERK_HEADERS
        )
        validate_success(
            api.update_veteran(
                sheltered_case["veteran_id"],
                {"homeless_status": "NOT_HOMELESS"},
                INTAKE_CLERK_HEADERS,
            ),
            200,
        )
        deactivated = validate_success(
            api.veteran_status(
                sheltered_case["veteran_id"], deactivate_action(), INTAKE_CLERK_HEADERS
            ),
            200,
        )
        assert deactivated["intake_status"] == "INACTIVE"


class TestIneligibleCharacterOfServiceBlocksRepresentativeAssignment:
    """A dishonourable discharge fails basic eligibility, so nobody is assigned."""

    @pytest.fixture
    def dishonourable_case(self, api):
        """A screened veteran whose verified paperwork reads DISHONORABLE."""
        officer = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        built = create_screened_veteran(
            api,
            make_county_officer_headers(officer["id"]),
            document_kwargs={"claimed_character_of_service": "DISHONORABLE"},
        )
        return {
            "veteran_id": built["veteran"]["id"],
            "screen": built["screen"],
            "officer_id": officer["id"],
        }

    def test_the_screen_fails_basic_eligibility_and_every_category_with_it(
        self, api, dishonourable_case
    ):
        """
        "`basic_eligibility` is true exactly when the veteran's `character_of_service` is `HONORABLE` or `GENERAL`, and false for any other value."
        "Basic eligibility short-circuits the whole screen: when `basic_eligibility` is false, every one of the six categories is false."

        Design: Corner/errors/corner_ineligible_character_of_service_blocks_representative_assignment
        """
        screen = dishonourable_case["screen"]
        assert screen["basic_eligibility"] is False
        assert_screen_categories(screen)
        outcomes = screen["category_results"]
        assert [entry["eligible"] for entry in outcomes.values()] == [False] * 6
        assert read_veteran(api, dishonourable_case["veteran_id"])[
            "character_of_service"
        ] == "DISHONORABLE"

    def test_assignment_is_refused_as_though_the_veteran_were_never_screened(
        self, api, dishonourable_case
    ):
        """
        "The veteran has at least one eligibility screen whose `basic_eligibility` is true, else `ERR_NOT_SCREENED` (409), on `POST /cvso/veterans/{id}/assign-representative`."

        Design: Corner/errors/corner_ineligible_character_of_service_blocks_representative_assignment
        """
        validate_error(
            api.assign_representative(
                dishonourable_case["veteran_id"],
                assign_representative_payload(dishonourable_case["officer_id"]),
                INTAKE_CLERK_HEADERS,
            ),
            "ERR_NOT_SCREENED",
            409,
        )
        stored = read_veteran(api, dishonourable_case["veteran_id"])
        assert stored["assigned_representative_id"] is None
        assert stored["intake_status"] == "SCREENED"
