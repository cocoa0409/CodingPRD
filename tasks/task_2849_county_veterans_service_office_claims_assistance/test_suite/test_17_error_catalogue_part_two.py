"""
The error catalogue, part two: referential agreement, state and safety gates.

Each refusal is observed next to the write that clears the same gate, so the
code is pinned to its own condition rather than to a broken request.
"""

import pytest
from test_helpers import (
    CLOCK_START_DATE,
    CLOCK_START_INSTANT,
    INTAKE_CLERK_HEADERS,
    STATE_AUDITOR_HEADERS,
    SYSTEM_ADMIN_HEADERS,
    accept_designation,
    accept_poa_payload,
    approve_application_action,
    assert_cents,
    assert_exact_whole,
    assert_pct_2dp,
    assign_representative_payload,
    benefit_application_payload,
    claim_payload,
    complete_appointment_action,
    complete_prep_action,
    conditions,
    create_active_designation,
    create_active_representative,
    create_claim_in_evidence_development,
    create_claim_with_appointment,
    create_draft_claim,
    create_filed_claim,
    create_screened_veteran,
    create_state_program,
    create_veteran,
    discharge_document_payload,
    evidence_item_payload,
    file_benefit_application,
    fill_designation_ceiling,
    make_county_officer_headers,
    make_veteran_client_headers,
    offer_designation,
    open_evidence_development,
    poa_payload,
    read_application,
    read_claim,
    read_claim_evidence,
    read_exam_site,
    read_representative,
    read_state_program,
    read_veteran,
    record_death_action,
    record_decision_payload,
    set_clock,
    submit_for_review_action,
    validate_error,
    validate_paginated,
    validate_success,
    veteran_version,
)


@pytest.fixture(autouse=True)
def _clock(api):
    """Every test in this module starts at the logical clock's opening instant."""
    set_clock(api, CLOCK_START_INSTANT)


def _officer(api):
    """One ACTIVE county officer who may do claim and evidence work."""
    return create_active_representative(
        api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
    )


class TestClaimCreationRequiresAnAcceptedDesignation:
    """An offer on the table is not representation yet."""

    @pytest.fixture
    def offered_only(self, api):
        """A screened veteran with a designation still sitting in OFFERED."""
        officer = _officer(api)
        officer_headers = make_county_officer_headers(officer["id"])
        built = create_screened_veteran(api, officer_headers)
        poa = offer_designation(api, built["veteran"]["id"], officer["id"])
        return {
            "veteran_id": built["veteran"]["id"],
            "officer_headers": officer_headers,
            "poa": poa,
        }

    def test_a_claim_against_an_offered_designation_is_refused(self, api, offered_only):
        """
        "The designation named by `poa_id` has `status` `ACTIVE`, else `ERR_POA_NOT_ACTIVE` (409), on `POST /cvso/claims` and `POST /cvso/claims/{id}/transitions`."
        "The row starts in `status` `OFFERED` with `accepted_at` and `revoked_reason` unset."

        Design: Corner/errors/corner_claim_creation_requires_an_accepted_designation
        """
        assert offered_only["poa"]["status"] == "OFFERED"
        assert offered_only["poa"]["accepted_at"] is None
        validate_error(
            api.create_claim(
                claim_payload(
                    offered_only["veteran_id"],
                    offered_only["poa"]["id"],
                    claimed_conditions=conditions("tinnitus"),
                ),
                offered_only["officer_headers"],
            ),
            "ERR_POA_NOT_ACTIVE",
            409,
        )
        _rows, meta = validate_paginated(
            api.list_claims(offered_only["officer_headers"])
        )
        assert_exact_whole(meta["total_count"], 0, "total_count")

    def test_once_the_veteran_accepts_the_same_claim_opens(self, api, offered_only):
        """
        "Acceptance then sets `status` to `ACTIVE`, stamps `accepted_at` with the logical-clock instant, increments the designated representative's `active_poa_count` by 1, and increments the veteran's `version` by 1 — which is exactly why a client holding a stale version number loses the race."

        Design: Corner/errors/corner_claim_creation_requires_an_accepted_designation
        """
        api.create_claim(
            claim_payload(
                offered_only["veteran_id"],
                offered_only["poa"]["id"],
                claimed_conditions=conditions("tinnitus"),
            ),
            offered_only["officer_headers"],
        )
        accepted = accept_designation(
            api, offered_only["poa"]["id"], offered_only["veteran_id"]
        )
        assert accepted["status"] == "ACTIVE"
        assert accepted["accepted_at"] == CLOCK_START_INSTANT
        created = validate_success(
            api.create_claim(
                claim_payload(
                    offered_only["veteran_id"],
                    offered_only["poa"]["id"],
                    claimed_conditions=conditions("tinnitus"),
                ),
                offered_only["officer_headers"],
            ),
            201,
        )
        assert created["status"] == "DRAFT"
        assert created["poa_id"] == offered_only["poa"]["id"]


class TestNexusStrengthMustAgreeWithTheEvidenceType:
    """The opinion strength belongs to exactly one evidence type."""

    @pytest.fixture
    def developing_claim(self, api):
        """A claim in EVIDENCE_DEVELOPMENT with no evidence on file yet."""
        ctx = create_claim_in_evidence_development(
            api, claimed_conditions=conditions("tinnitus")
        )
        return {
            "claim_id": ctx["claim"]["id"],
            "officer_headers": ctx["officer_headers"],
        }

    def test_both_directions_of_the_disagreement_carry_the_same_code(
        self, api, developing_claim
    ):
        """
        "That last field must agree with the type: a `NEXUS_LETTER` item must carry a strength other than `NONE`, and every other evidence type must carry `NONE` or omit the field entirely; a disagreement is refused with `ERR_NEXUS_STRENGTH_MISMATCH` at HTTP 422."

        Design: Corner/errors/corner_nexus_strength_must_agree_with_the_evidence_type
        """
        validate_error(
            api.create_evidence_item(
                developing_claim["claim_id"],
                evidence_item_payload(
                    evidence_type="NEXUS_LETTER", nexus_opinion_strength="NONE"
                ),
                developing_claim["officer_headers"],
            ),
            "ERR_NEXUS_STRENGTH_MISMATCH",
            422,
        )
        validate_error(
            api.create_evidence_item(
                developing_claim["claim_id"],
                evidence_item_payload(
                    evidence_type="SERVICE_TREATMENT_RECORD",
                    nexus_opinion_strength="HIGHLY_PROBABLE",
                ),
                developing_claim["officer_headers"],
            ),
            "ERR_NEXUS_STRENGTH_MISMATCH",
            422,
        )
        assert (
            read_claim_evidence(
                api, developing_claim["claim_id"], developing_claim["officer_headers"]
            )
            == []
        )

    def test_the_two_agreeing_shapes_are_both_written(self, api, developing_claim):
        """
        "The row starts in `status` `REQUESTED` with `requested_on` set to the logical-clock date, `weight_points` at 0.00 and `auto_generated` false, and creating it recomputes the claim's `evidence_completeness_pct` and increments the claim's `version` by 1."

        Design: Corner/errors/corner_nexus_strength_must_agree_with_the_evidence_type
        """
        letter = validate_success(
            api.create_evidence_item(
                developing_claim["claim_id"],
                evidence_item_payload(
                    evidence_type="NEXUS_LETTER",
                    nexus_opinion_strength="AT_LEAST_AS_LIKELY_AS_NOT",
                ),
                developing_claim["officer_headers"],
            ),
            201,
        )
        assert letter["status"] == "REQUESTED"
        assert letter["requested_on"] == CLOCK_START_DATE
        assert letter["auto_generated"] is False
        assert_pct_2dp(letter["weight_points"], 0.00)
        record = validate_success(
            api.create_evidence_item(
                developing_claim["claim_id"],
                evidence_item_payload(evidence_type="SERVICE_TREATMENT_RECORD"),
                developing_claim["officer_headers"],
            ),
            201,
        )
        assert record["status"] == "REQUESTED"
        assert_pct_2dp(
            read_claim(api, developing_claim["claim_id"])["evidence_completeness_pct"],
            0.00,
        )


class TestBenefitApplicationReferentialGatesAreDistinctCodes:
    """Three filing gates, three codes, two of them at different statuses."""

    @pytest.fixture
    def screened_and_funded(self, api):
        """A screened veteran and a 2026 property-tax programme at version 1."""
        officer = _officer(api)
        built = create_screened_veteran(api, make_county_officer_headers(officer["id"]))
        program = create_state_program(
            api, program_type="PROPERTY_TAX_EXEMPTION", fiscal_year=2026
        )
        return {"veteran_id": built["veteran"]["id"], "program": program}

    def test_a_retuned_programme_invalidates_the_captured_version(
        self, api, screened_and_funded
    ):
        """
        "`expected_program_version` equals the referenced program's current `version`, else `ERR_STALE_PROGRAM_VERSION` (412), on `POST /cvso/state-benefit-applications`."
        "Retuning may change `program_name`, `annual_pool_cents`, `min_rating_pct`, `requires_wartime` or `max_award_cents`; already-approved applications are never re-adjudicated, but the write increments the program's `version` by 1, which invalidates any `expected_program_version` a client captured earlier."

        Design: Corner/errors/corner_benefit_application_referential_gates_are_distinct_codes
        """
        program = screened_and_funded["program"]
        retuned = validate_success(
            api.update_state_program(
                program["id"], {"annual_pool_cents": 200000000}, SYSTEM_ADMIN_HEADERS
            ),
            200,
        )
        assert_exact_whole(retuned["version"], 2, "version")
        validate_error(
            api.create_state_benefit_application(
                benefit_application_payload(
                    screened_and_funded["veteran_id"],
                    program["id"],
                    2026,
                    1,
                    assessed_property_value_cents=8500000,
                ),
                INTAKE_CLERK_HEADERS,
            ),
            "ERR_STALE_PROGRAM_VERSION",
            412,
        )
        filed = validate_success(
            api.create_state_benefit_application(
                benefit_application_payload(
                    screened_and_funded["veteran_id"],
                    program["id"],
                    2026,
                    2,
                    assessed_property_value_cents=8500000,
                ),
                INTAKE_CLERK_HEADERS,
            ),
            201,
        )
        assert filed["determination_status"] == "SUBMITTED"

    def test_a_year_the_programme_does_not_fund_is_its_own_code(
        self, api, screened_and_funded
    ):
        """
        "The application's `fiscal_year` equals the referenced program's `fiscal_year`, else `ERR_FISCAL_YEAR_MISMATCH` (409), on `POST /cvso/state-benefit-applications`."

        Design: Corner/errors/corner_benefit_application_referential_gates_are_distinct_codes
        """
        program = screened_and_funded["program"]
        assert_exact_whole(program["fiscal_year"], 2026, "fiscal_year")
        validate_error(
            api.create_state_benefit_application(
                benefit_application_payload(
                    screened_and_funded["veteran_id"],
                    program["id"],
                    2027,
                    read_state_program(api, program["id"])["version"],
                    assessed_property_value_cents=8500000,
                ),
                INTAKE_CLERK_HEADERS,
            ),
            "ERR_FISCAL_YEAR_MISMATCH",
            409,
        )
        _rows, meta = validate_paginated(
            api.list_state_benefit_applications(INTAKE_CLERK_HEADERS)
        )
        assert_exact_whole(meta["total_count"], 0, "total_count")

    def test_the_case_state_the_programme_type_demands_is_its_own_code(
        self, api, screened_and_funded
    ):
        """
        "The veteran's `intake_status` matches the program type applied for — `SCREENED` or `ACTIVE` for a `PROPERTY_TAX_EXEMPTION` or `TUITION_WAIVER` application, and `DECEASED` for a `BURIAL_BENEFIT` application — else `ERR_VETERAN_STATUS_INELIGIBLE` (409), on `POST /cvso/state-benefit-applications`."

        Design: Corner/errors/corner_benefit_application_referential_gates_are_distinct_codes
        """
        program = screened_and_funded["program"]
        untouched = create_veteran(api)
        validate_error(
            api.create_state_benefit_application(
                benefit_application_payload(
                    untouched["id"],
                    program["id"],
                    2026,
                    read_state_program(api, program["id"])["version"],
                    assessed_property_value_cents=8500000,
                ),
                INTAKE_CLERK_HEADERS,
            ),
            "ERR_VETERAN_STATUS_INELIGIBLE",
            409,
        )
        burial = create_state_program(
            api, program_type="BURIAL_BENEFIT", fiscal_year=2026
        )
        validate_error(
            api.create_state_benefit_application(
                benefit_application_payload(
                    screened_and_funded["veteran_id"],
                    burial["id"],
                    2026,
                    read_state_program(api, burial["id"])["version"],
                ),
                INTAKE_CLERK_HEADERS,
            ),
            "ERR_VETERAN_STATUS_INELIGIBLE",
            409,
        )
        assert read_veteran(api, untouched["id"])["intake_status"] == "INTAKE_STARTED"


class TestWartimeRequirementIsCheckedAtApprovalTime:
    """Filing never reads the wartime clock; approval does."""

    def _funded_application(self, api, service_start, service_end):
        """A submitted application against a programme that requires wartime service."""
        officer = _officer(api)
        built = create_screened_veteran(
            api,
            make_county_officer_headers(officer["id"]),
            document_kwargs={
                "claimed_service_start": service_start,
                "claimed_service_end": service_end,
            },
            service_start_date=service_start,
            service_end_date=service_end,
        )
        program = create_state_program(
            api,
            program_type="PROPERTY_TAX_EXEMPTION",
            fiscal_year=2026,
            requires_wartime=True,
            min_rating_pct=0,
        )
        application = file_benefit_application(
            api,
            built["veteran"]["id"],
            program,
            assessed_property_value_cents=8500000,
        )
        return {
            "veteran": read_veteran(api, built["veteran"]["id"]),
            "program": program,
            "application": application,
        }

    def test_peacetime_service_files_but_cannot_be_approved(self, api):
        """
        "When the program's `requires_wartime` is true, the veteran's `wartime_service_days` meets the wartime minimum, else `ERR_PROGRAM_WARTIME_REQUIRED` (409), on a state benefit application `APPROVE`."
        "The count is taken against three fixed statutory wartime windows, evaluated in this order: 28 February 1961 through 7 May 1975, 2 August 1990 through 11 April 1991, and 11 September 2001 through 30 August 2021."

        Design: Corner/errors/corner_wartime_requirement_is_checked_at_approval_time
        """
        built = self._funded_application(api, "1980-01-01", "1984-01-01")
        assert_exact_whole(
            built["veteran"]["wartime_service_days"], 0, "wartime_service_days"
        )
        assert built["application"]["determination_status"] == "SUBMITTED"
        validate_error(
            api.application_determination(
                built["application"]["id"],
                approve_application_action(),
                STATE_AUDITOR_HEADERS,
            ),
            "ERR_PROGRAM_WARTIME_REQUIRED",
            409,
        )
        still_submitted = read_application(api, built["application"]["id"])
        assert still_submitted["determination_status"] == "SUBMITTED"
        assert still_submitted["disbursement_status"] == "NOT_APPLICABLE"
        assert_cents(read_state_program(api, built["program"]["id"])["allocated_cents"], 0)

    def test_wartime_service_clears_the_same_gate(self, api):
        """
        "Approval sets `determination_status` to `APPROVED`, freezes `rating_at_approval_pct` at the veteran's `combined_rating_pct` as of that instant, moves the disbursement dimension from `NOT_APPLICABLE` to `PENDING` as a coupled initialisation, and increases the program's `allocated_cents` by `benefit_amount_cents`."
        "If that later start is not after that earlier end, the overlap contributes the number of days from the start to the end plus one — the plus one making both ends inclusive — and otherwise contributes nothing."

        Design: Corner/errors/corner_wartime_requirement_is_checked_at_approval_time
        """
        built = self._funded_application(api, "2001-09-11", "2005-09-10")
        assert_exact_whole(
            built["veteran"]["wartime_service_days"], 1461, "wartime_service_days"
        )
        approved = validate_success(
            api.application_determination(
                built["application"]["id"],
                approve_application_action(),
                STATE_AUDITOR_HEADERS,
            ),
            200,
        )
        assert approved["determination_status"] == "APPROVED"
        assert approved["disbursement_status"] == "PENDING"
        assert_exact_whole(
            approved["rating_at_approval_pct"], 0, "rating_at_approval_pct"
        )
        assert_cents(
            read_state_program(api, built["program"]["id"])["allocated_cents"],
            approved["benefit_amount_cents"],
        )


class TestExaminationCannotBeCompletedBeforeThePrepSession:
    """The coaching session must be logged before the examination closes."""

    @pytest.fixture
    def booked(self, api):
        """A claim with one SCHEDULED examination whose prep flag is still false."""
        ctx = create_claim_with_appointment(
            api, claimed_conditions=conditions("tinnitus")
        )
        return {
            "claim_id": ctx["claim"]["id"],
            "appointment_id": ctx["appointment"]["id"],
            "site_id": ctx["site"]["id"],
            "officer_headers": ctx["officer_headers"],
        }

    def test_completion_without_the_prep_session_is_refused(self, api, booked):
        """
        "**Completing** the appointment (`COMPLETE`) is available only from `SCHEDULED`, requires `prep_session_completed` to already be true — otherwise the attempt is refused with `ERR_EXAM_PREP_INCOMPLETE` at HTTP 409 — and requires a `completed_on` date no later than the logical-clock date."

        Design: Corner/errors/corner_examination_cannot_be_completed_before_the_prep_session
        """
        validate_error(
            api.exam_appointment_status(
                booked["appointment_id"],
                complete_appointment_action(),
                booked["officer_headers"],
            ),
            "ERR_EXAM_PREP_INCOMPLETE",
            409,
        )
        stored = validate_success(
            api.get_exam_appointment(
                booked["appointment_id"], booked["officer_headers"]
            ),
            200,
        )
        assert stored["status"] == "SCHEDULED"
        assert stored["prep_session_completed"] is False
        assert_exact_whole(
            read_exam_site(api, booked["site_id"])["booked_slot_count"],
            1,
            "booked_slot_count",
        )

    def test_logging_the_prep_session_first_closes_the_examination_out(
        self, api, booked
    ):
        """
        "Completion sets `status` to `COMPLETED` and `completed_on`, decrements the site's `booked_slot_count` by 1, and **synthesizes a new evidence item on the linked claim**: `evidence_type` `DBQ`, `status` `RECEIVED`, `received_on` equal to the appointment's `completed_on`, `nexus_opinion_strength` `NONE`, and `auto_generated` true."

        Design: Corner/errors/corner_examination_cannot_be_completed_before_the_prep_session
        """
        api.exam_appointment_status(
            booked["appointment_id"],
            complete_appointment_action(),
            booked["officer_headers"],
        )
        prepped = validate_success(
            api.exam_appointment_status(
                booked["appointment_id"],
                complete_prep_action(),
                booked["officer_headers"],
            ),
            200,
        )
        assert prepped["status"] == "SCHEDULED"
        assert prepped["prep_session_completed"] is True
        completed = validate_success(
            api.exam_appointment_status(
                booked["appointment_id"],
                complete_appointment_action(CLOCK_START_DATE),
                booked["officer_headers"],
            ),
            200,
        )
        assert completed["status"] == "COMPLETED"
        assert completed["completed_on"] == CLOCK_START_DATE
        assert_exact_whole(
            read_exam_site(api, booked["site_id"])["booked_slot_count"],
            0,
            "booked_slot_count",
        )
        items = read_claim_evidence(
            api, booked["claim_id"], booked["officer_headers"]
        )
        synthesized = [row for row in items if row["auto_generated"] is True]
        assert len(synthesized) == 1
        assert synthesized[0]["evidence_type"] == "DBQ"
        assert synthesized[0]["status"] == "RECEIVED"


class TestDecisionDateMustNotPrecedeTheFilingDate:
    """Both bounds of the decision date carry the same code."""

    @pytest.fixture
    def filed(self, api):
        """A claim filed on the clock's opening date and awaiting adjudication."""
        ctx = create_filed_claim(api, claimed_conditions=conditions("tinnitus"))
        return {
            "claim_id": ctx["claim"]["id"],
            "officer_headers": ctx["officer_headers"],
        }

    def test_a_decision_dated_before_the_filing_is_refused(self, api, filed):
        """
        "`decided_on` is not earlier than the claim's `filed_on` and not later than the logical-clock date, else `ERR_DECISION_DATE_INVALID` (409), on `POST /cvso/claims/{id}/record-decision`."

        Design: Corner/errors/corner_decision_date_must_not_precede_the_filing_date
        """
        assert read_claim(api, filed["claim_id"])["filed_on"] == CLOCK_START_DATE
        validate_error(
            api.record_decision(
                filed["claim_id"],
                record_decision_payload(
                    decision_outcome="GRANTED",
                    awarded_rating_pct=30,
                    decided_on="2026-07-31",
                ),
                filed["officer_headers"],
            ),
            "ERR_DECISION_DATE_INVALID",
            409,
        )
        stored = read_claim(api, filed["claim_id"])
        assert stored["status"] == "FILED"
        assert stored["decision_outcome"] is None

    def test_a_decision_dated_after_the_clock_is_refused_and_the_same_day_is_not(
        self, api, filed
    ):
        """
        "The `decided_on` date must be no earlier than the claim's `filed_on` and no later than the logical-clock date; a violation of either bound is `ERR_DECISION_DATE_INVALID` at HTTP 409."

        Design: Corner/errors/corner_decision_date_must_not_precede_the_filing_date
        """
        validate_error(
            api.record_decision(
                filed["claim_id"],
                record_decision_payload(
                    decision_outcome="GRANTED",
                    awarded_rating_pct=30,
                    decided_on="2026-08-02",
                ),
                filed["officer_headers"],
            ),
            "ERR_DECISION_DATE_INVALID",
            409,
        )
        decided = validate_success(
            api.record_decision(
                filed["claim_id"],
                record_decision_payload(
                    decision_outcome="GRANTED",
                    awarded_rating_pct=30,
                    decided_on=CLOCK_START_DATE,
                ),
                filed["officer_headers"],
            ),
            200,
        )
        assert decided["status"] == "DECIDED"
        assert decided["decided_on"] == CLOCK_START_DATE


class TestWritesAgainstADeceasedVeteranAreRefused:
    """A terminal case accepts no further paperwork of any kind."""

    @pytest.fixture
    def deceased_case(self, api):
        """An ACTIVE case taken to DECEASED, with one offer left on the table."""
        officer = _officer(api)
        built = create_screened_veteran(api, make_county_officer_headers(officer["id"]))
        veteran_id = built["veteran"]["id"]
        validate_success(
            api.assign_representative(
                veteran_id,
                assign_representative_payload(officer["id"]),
                INTAKE_CLERK_HEADERS,
            ),
            200,
        )
        pending_offer = offer_designation(api, veteran_id, officer["id"])
        dead = validate_success(
            api.veteran_status(
                veteran_id, record_death_action("2026-07-20"), INTAKE_CLERK_HEADERS
            ),
            200,
        )
        assert dead["intake_status"] == "DECEASED"
        return {
            "veteran_id": veteran_id,
            "officer_id": officer["id"],
            "offer_id": pending_offer["id"],
        }

    def test_three_of_the_listed_endpoints_refuse_the_write(self, api, deceased_case):
        """
        "The veteran the write hangs off is not in `intake_status` `DECEASED`, else `ERR_VETERAN_DECEASED` (409), on `POST /cvso/veterans/{id}/discharge-documents`, `POST /cvso/powers-of-attorney`, `POST /cvso/powers-of-attorney/{id}/accept`, `POST /cvso/claims`, `POST /cvso/claims/{id}/transitions` and `POST /cvso/veterans/{id}/assign-representative`."

        Design: Corner/errors/corner_writes_against_a_deceased_veteran_are_refused
        """
        validate_error(
            api.create_discharge_document(
                deceased_case["veteran_id"],
                discharge_document_payload(),
                INTAKE_CLERK_HEADERS,
            ),
            "ERR_VETERAN_DECEASED",
            409,
        )
        successor = create_active_representative(
            api, accreditation_type="VSO_ORG", accreditation_expires_on="2029-12-31"
        )
        validate_error(
            api.create_power_of_attorney(
                poa_payload(deceased_case["veteran_id"], successor["id"]),
                INTAKE_CLERK_HEADERS,
            ),
            "ERR_VETERAN_DECEASED",
            409,
        )
        validate_error(
            api.assign_representative(
                deceased_case["veteran_id"],
                assign_representative_payload(successor["id"]),
                INTAKE_CLERK_HEADERS,
            ),
            "ERR_VETERAN_DECEASED",
            409,
        )

    def test_an_offer_made_before_the_death_can_no_longer_be_accepted(
        self, api, deceased_case
    ):
        """
        "**Recording a death** (`RECORD_DEATH`) is available from either `ACTIVE` or `INACTIVE`, requires a `date_of_death` that is not later than the logical-clock date, and takes the case to `DECEASED`, which is terminal."

        Design: Corner/errors/corner_writes_against_a_deceased_veteran_are_refused
        """
        validate_error(
            api.accept_power_of_attorney(
                deceased_case["offer_id"],
                accept_poa_payload(veteran_version(api, deceased_case["veteran_id"])),
                make_veteran_client_headers(deceased_case["veteran_id"]),
            ),
            "ERR_VETERAN_DECEASED",
            409,
        )
        stored = validate_success(
            api.get_power_of_attorney(deceased_case["offer_id"], INTAKE_CLERK_HEADERS),
            200,
        )
        assert stored["status"] == "OFFERED"
        assert stored["accepted_at"] is None
        living = create_veteran(api)
        offered = offer_designation(api, living["id"], deceased_case["officer_id"])
        accepted = accept_designation(api, offered["id"], living["id"])
        assert accepted["status"] == "ACTIVE"


class TestAutomaticAssignmentWithAnEmptyCandidateSetIsRefused:
    """An attorney on the roster is never an automatic candidate."""

    @pytest.fixture
    def attorney_only_roster(self, api):
        """A screened veteran and a roster holding one ACTIVE attorney."""
        attorney = create_active_representative(
            api, accreditation_type="ATTORNEY", accreditation_expires_on="2029-12-31"
        )
        built = create_screened_veteran(
            api, make_county_officer_headers(attorney["id"])
        )
        return {"veteran_id": built["veteran"]["id"], "attorney_id": attorney["id"]}

    def test_the_empty_candidate_set_refuses_the_assignment(
        self, api, attorney_only_roster
    ):
        """
        "If the candidate set is empty the request is refused with `ERR_NO_ELIGIBLE_REPRESENTATIVE` at HTTP 409 and no assignment is made."

        Design: Corner/errors/corner_automatic_assignment_with_an_empty_candidate_set_is_refused
        """
        validate_error(
            api.assign_representative(
                attorney_only_roster["veteran_id"],
                assign_representative_payload(),
                INTAKE_CLERK_HEADERS,
            ),
            "ERR_NO_ELIGIBLE_REPRESENTATIVE",
            409,
        )
        stored = read_veteran(api, attorney_only_roster["veteran_id"])
        assert stored["assigned_representative_id"] is None
        assert stored["intake_status"] == "SCREENED"

    def test_one_county_officer_on_the_roster_makes_the_selector_succeed(
        self, api, attorney_only_roster
    ):
        """
        "When `representative_id` is omitted, the automatic selector finds at least one candidate, else `ERR_NO_ELIGIBLE_REPRESENTATIVE` (409), on `POST /cvso/veterans/{id}/assign-representative`."

        Design: Corner/errors/corner_automatic_assignment_with_an_empty_candidate_set_is_refused
        """
        api.assign_representative(
            attorney_only_roster["veteran_id"],
            assign_representative_payload(),
            INTAKE_CLERK_HEADERS,
        )
        eligible = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        assigned = validate_success(
            api.assign_representative(
                attorney_only_roster["veteran_id"],
                assign_representative_payload(),
                INTAKE_CLERK_HEADERS,
            ),
            200,
        )
        assert assigned["assigned_representative_id"] == eligible["id"]
        assert assigned["intake_status"] == "ACTIVE"


class TestDesignationAcceptanceIsRefusedWhenTheCaseloadCeilingIsReached:
    """The ceiling is enforced on acceptance and on assignment alike."""

    @pytest.fixture
    def full_representative(self, api):
        """One representative holding the maximum number of active designations."""
        rep = _officer(api)
        fill_designation_ceiling(api, rep["id"], 40)
        stored = read_representative(api, rep["id"])
        assert_exact_whole(stored["active_poa_count"], 40, "active_poa_count")
        return {"rep_id": rep["id"]}

    def test_the_forty_first_acceptance_is_refused(self, api, full_representative):
        """
        "The designated representative's `accreditation_status` must read `ACTIVE`, and their `active_poa_count` must be strictly less than the 40-designation ceiling."

        Design: Corner/errors/corner_designation_acceptance_is_refused_when_the_caseload_ceiling_is_reached
        """
        veteran = create_veteran(api)
        offered = offer_designation(api, veteran["id"], full_representative["rep_id"])
        validate_error(
            api.accept_power_of_attorney(
                offered["id"],
                accept_poa_payload(veteran_version(api, veteran["id"])),
                make_veteran_client_headers(veteran["id"]),
            ),
            "ERR_REPRESENTATIVE_CASELOAD_FULL",
            409,
        )
        stored = validate_success(
            api.get_power_of_attorney(offered["id"], INTAKE_CLERK_HEADERS), 200
        )
        assert stored["status"] == "OFFERED"
        assert_exact_whole(
            read_representative(api, full_representative["rep_id"])["active_poa_count"],
            40,
            "active_poa_count",
        )

    def test_the_same_ceiling_refuses_a_direct_assignment(
        self, api, full_representative
    ):
        """
        "The representative's `active_poa_count` is strictly less than the per-representative designation ceiling, else `ERR_REPRESENTATIVE_CASELOAD_FULL` (409), on `POST /cvso/powers-of-attorney/{id}/accept` and `POST /cvso/veterans/{id}/assign-representative`."
        "The 40-designation ceiling is enforced on assignment as well as on acceptance, and breaching it is `ERR_REPRESENTATIVE_CASELOAD_FULL`."

        Design: Corner/errors/corner_designation_acceptance_is_refused_when_the_caseload_ceiling_is_reached
        """
        built = create_screened_veteran(
            api, make_county_officer_headers(full_representative["rep_id"])
        )
        validate_error(
            api.assign_representative(
                built["veteran"]["id"],
                assign_representative_payload(full_representative["rep_id"]),
                INTAKE_CLERK_HEADERS,
            ),
            "ERR_REPRESENTATIVE_CASELOAD_FULL",
            409,
        )
        spare = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        assigned = validate_success(
            api.assign_representative(
                built["veteran"]["id"],
                assign_representative_payload(spare["id"]),
                INTAKE_CLERK_HEADERS,
            ),
            200,
        )
        assert assigned["assigned_representative_id"] == spare["id"]


class TestDesigneeCannotSupplyTheIndependentPeerReview:
    """Two different reviewers, two different refusals, one clean third party."""

    @pytest.fixture
    def prepared_by_a_non_designee(self, api):
        """A claim prepared by one officer against another officer's designation."""
        preparer = _officer(api)
        designee = _officer(api)
        preparer_headers = make_county_officer_headers(preparer["id"])
        built = create_screened_veteran(api, preparer_headers)
        veteran_id = built["veteran"]["id"]
        poa = create_active_designation(api, veteran_id, designee["id"])
        claim = create_draft_claim(
            api,
            veteran_id,
            poa["id"],
            preparer_headers,
            claimed_conditions=conditions("tinnitus"),
        )
        developing = open_evidence_development(api, claim["id"], preparer_headers)
        return {
            "claim_id": developing["id"],
            "preparer_id": preparer["id"],
            "designee_id": designee["id"],
            "preparer_headers": preparer_headers,
        }

    def test_naming_the_designee_as_reviewer_is_its_own_code(
        self, api, prepared_by_a_non_designee
    ):
        """
        "The reviewer must also **not** be the representative designated on the claim's power of attorney, because the designee holds a representational interest and cannot supply an independent review; that attempt is refused with the distinct code `ERR_REVIEWER_IS_DESIGNATED_REPRESENTATIVE`, also at HTTP 409."

        Design: Corner/errors/corner_designee_cannot_supply_the_independent_peer_review
        """
        validate_error(
            api.claim_transition(
                prepared_by_a_non_designee["claim_id"],
                submit_for_review_action(prepared_by_a_non_designee["designee_id"]),
                prepared_by_a_non_designee["preparer_headers"],
            ),
            "ERR_REVIEWER_IS_DESIGNATED_REPRESENTATIVE",
            409,
        )
        stored = read_claim(api, prepared_by_a_non_designee["claim_id"])
        assert stored["status"] == "EVIDENCE_DEVELOPMENT"
        assert stored["peer_reviewed_by_representative_id"] is None

    def test_the_preparer_is_refused_under_the_other_code_and_a_third_party_passes(
        self, api, prepared_by_a_non_designee
    ):
        """
        "`reviewer_representative_id` differs from the claim's `prepared_by_representative_id`, else `ERR_SEGREGATION_OF_DUTIES` (409), on a claim `SUBMIT_FOR_REVIEW`."
        "The step sets `status` to `PEER_REVIEW` and `peer_reviewed_by_representative_id` to the nominated reviewer, recomputes `evidence_completeness_pct` and the preparer's `caseload_weight`, and increments the claim's `version` by 1."

        Design: Corner/errors/corner_designee_cannot_supply_the_independent_peer_review
        """
        validate_error(
            api.claim_transition(
                prepared_by_a_non_designee["claim_id"],
                submit_for_review_action(prepared_by_a_non_designee["preparer_id"]),
                prepared_by_a_non_designee["preparer_headers"],
            ),
            "ERR_SEGREGATION_OF_DUTIES",
            409,
        )
        independent = create_active_representative(
            api, accreditation_type="VSO_ORG", accreditation_expires_on="2029-12-31"
        )
        submitted = validate_success(
            api.claim_transition(
                prepared_by_a_non_designee["claim_id"],
                submit_for_review_action(independent["id"]),
                prepared_by_a_non_designee["preparer_headers"],
            ),
            200,
        )
        assert submitted["status"] == "PEER_REVIEW"
        assert submitted["peer_reviewed_by_representative_id"] == independent["id"]
