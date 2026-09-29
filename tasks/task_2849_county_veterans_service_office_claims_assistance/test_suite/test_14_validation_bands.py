"""
Validation rules at their exact boundaries, and the rows they refuse to write.

Each family here pairs the refusal with the neighbouring request that passes, so
the rule is observed as a boundary rather than as a blanket rejection.
"""

import pytest
from test_helpers import (
    CLOCK_START_INSTANT,
    INTAKE_CLERK_HEADERS,
    assert_application_filing_defaults,
    assert_cents,
    assert_exact_whole,
    assert_pct_2dp,
    benefit_application_payload,
    claim_payload,
    conditions,
    create_active_representative,
    create_represented_veteran,
    create_screened_veteran,
    create_claim_in_evidence_development,
    create_state_program,
    create_verified_veteran,
    file_benefit_application,
    make_county_officer_headers,
    read_claim,
    read_state_program,
    read_veteran,
    receive_evidence,
    request_evidence,
    set_clock,
    submit_for_peer_review,
    submit_for_review_action,
    validate_error,
    validate_paginated,
    validate_success,
    veteran_payload,
)


@pytest.fixture(autouse=True)
def _clock(api):
    """Every test in this module starts at the logical clock's opening instant."""
    set_clock(api, CLOCK_START_INSTANT)


class TestServiceSpanBoundary:
    """The span rule refuses an inverted tour and admits a single-day one."""

    def test_an_inverted_span_is_its_own_error_code(self, api):
        """
        "A service span does not end before it starts — `service_end_date` is not earlier than `service_start_date` on a veteran, and `claimed_service_end` is not earlier than `claimed_service_start` on a discharge document — else `ERR_INVALID_SERVICE_DATES` (422), on `POST /cvso/veterans`, `PATCH /cvso/veterans/{id}`, `POST /cvso/veterans/{id}/discharge-documents` and `POST /cvso/discharge-documents/{id}/resubmit`."

        Design: Corner/validations/corner_service_end_before_service_start_returns_invalid_service_dates
        """
        error = validate_error(
            api.create_veteran(
                veteran_payload(
                    full_name="Alex Rivera",
                    date_of_birth="1979-03-04",
                    service_start_date="2001-09-11",
                    service_end_date="2001-09-10",
                    household_income_cents=1500000,
                    net_worth_cents=2000000,
                    dependent_count=2,
                    homeless_status="NOT_HOMELESS",
                    referral_source="WALK_IN",
                ),
                INTAKE_CLERK_HEADERS,
            ),
            "ERR_INVALID_SERVICE_DATES",
            422,
        )
        assert error["error_id"] != "ERR_VALIDATION"
        _rows, meta = validate_paginated(api.list_veterans(INTAKE_CLERK_HEADERS))
        assert_exact_whole(meta["total_count"], 0, "total_count")

    def test_a_single_day_span_is_accepted_and_counts_one_wartime_day(self, api):
        """
        "If that later start is not after that earlier end, the overlap contributes the number of days from the start to the end plus one — the plus one making both ends inclusive — and otherwise contributes nothing."

        Design: Corner/validations/corner_single_day_service_span_is_accepted
        """
        officer = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        officer_headers = make_county_officer_headers(officer["id"])
        built = create_verified_veteran(
            api,
            officer_headers,
            document_kwargs={
                "claimed_service_start": "2001-09-11",
                "claimed_service_end": "2001-09-11",
            },
            date_of_birth="1979-03-04",
            service_start_date="2001-09-11",
            service_end_date="2001-09-11",
            household_income_cents=1500000,
            net_worth_cents=2000000,
            dependent_count=2,
            homeless_status="NOT_HOMELESS",
            referral_source="WALK_IN",
        )
        stored = read_veteran(api, built["veteran"]["id"])
        assert stored["discharge_doc_status"] == "VERIFIED"
        assert_exact_whole(stored["wartime_service_days"], 1, "wartime_service_days")

    def test_the_document_side_of_the_same_rule_refuses_an_inverted_copy(self, api):
        """
        "A submission declares its `document_type` (`DD214`, `NGB22`, `DD215` or `STATEMENT_OF_SERVICE`), its `source` — the provenance of the copy, one of `VETERAN_PROVIDED`, `NPRC_RESPONSE` or `STATE_ARCHIVE` — and the three facts printed on the paper: `claimed_service_start`, `claimed_service_end` and `claimed_character_of_service`, the last being one of `HONORABLE`, `GENERAL`, `OTHER_THAN_HONORABLE`, `BAD_CONDUCT`, `DISHONORABLE` or `UNCHARACTERIZED`."

        Design: Corner/validations/corner_service_end_before_service_start_returns_invalid_service_dates
        """
        veteran = validate_success(
            api.create_veteran(
                veteran_payload(
                    full_name="Alex Rivera",
                    date_of_birth="1979-03-04",
                    dependent_count=2,
                    homeless_status="NOT_HOMELESS",
                    referral_source="WALK_IN",
                ),
                INTAKE_CLERK_HEADERS,
            ),
            201,
        )
        validate_error(
            api.create_discharge_document(
                veteran["id"],
                {
                    "document_type": "DD214",
                    "source": "VETERAN_PROVIDED",
                    "claimed_service_start": "2001-09-11",
                    "claimed_service_end": "2001-09-10",
                    "claimed_character_of_service": "HONORABLE",
                },
                INTAKE_CLERK_HEADERS,
            ),
            "ERR_INVALID_SERVICE_DATES",
            422,
        )
        assert read_veteran(api, veteran["id"])["discharge_doc_status"] == "NOT_SUBMITTED"


class TestIntentToFileWindow:
    """The anchor date is bounded by the separation below and the clock above."""

    @pytest.fixture
    def represented_veteran(self, api):
        """A veteran separated on 10 September 2005 with an ACTIVE designation."""
        rep = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        return create_represented_veteran(api, designee=rep)

    def _claim_body(self, base, intent_to_file_date):
        return claim_payload(
            base["veteran"]["id"],
            base["poa"]["id"],
            claimed_conditions=conditions("tinnitus"),
            intent_to_file_date=intent_to_file_date,
        )

    def test_an_anchor_after_the_clock_date_is_refused(self, api, represented_veteran):
        """
        "`intent_to_file_date` is not later than the logical-clock date and not earlier than the veteran's `service_end_date`, else `ERR_INTENT_TO_FILE_DATE_INVALID` (409), on `POST /cvso/claims` and `PATCH /cvso/claims/{id}`."

        Design: Corner/validations/corner_intent_to_file_date_must_sit_between_separation_and_today
        """
        validate_error(
            api.create_claim(
                self._claim_body(represented_veteran, "2026-09-01"),
                represented_veteran["officer_headers"],
            ),
            "ERR_INTENT_TO_FILE_DATE_INVALID",
            409,
        )
        _rows, meta = validate_paginated(
            api.list_claims(represented_veteran["officer_headers"])
        )
        assert_exact_whole(meta["total_count"], 0, "total_count")

    def test_an_anchor_before_the_separation_is_refused_with_the_same_code(
        self, api, represented_veteran
    ):
        """
        "When `intent_to_file_date` is supplied it must be no later than the logical-clock date and no earlier than the veteran's `service_end_date`, else `ERR_INTENT_TO_FILE_DATE_INVALID`."

        Design: Corner/validations/corner_intent_to_file_date_must_sit_between_separation_and_today
        """
        assert represented_veteran["veteran"]["service_end_date"] == "2005-09-10"
        validate_error(
            api.create_claim(
                self._claim_body(represented_veteran, "2005-09-09"),
                represented_veteran["officer_headers"],
            ),
            "ERR_INTENT_TO_FILE_DATE_INVALID",
            409,
        )
        _rows, meta = validate_paginated(
            api.list_claims(represented_veteran["officer_headers"])
        )
        assert_exact_whole(meta["total_count"], 0, "total_count")

    def test_an_anchor_between_the_two_bounds_creates_the_claim(
        self, api, represented_veteran
    ):
        """
        "The server sets `status` to `DRAFT`, `prepared_by_representative_id` to the acting officer's `X-User-ID`, `rework_count` and `reopen_count` to 0, and `evidence_completeness_pct` to 0.00."

        Design: Corner/validations/corner_intent_to_file_date_must_sit_between_separation_and_today
        """
        api.create_claim(
            self._claim_body(represented_veteran, "2026-09-01"),
            represented_veteran["officer_headers"],
        )
        api.create_claim(
            self._claim_body(represented_veteran, "2005-09-09"),
            represented_veteran["officer_headers"],
        )
        created = validate_success(
            api.create_claim(
                self._claim_body(represented_veteran, "2025-09-15"),
                represented_veteran["officer_headers"],
            ),
            201,
        )
        assert created["intent_to_file_date"] == "2025-09-15"
        assert created["status"] == "DRAFT"
        assert_pct_2dp(created["evidence_completeness_pct"], 0.00)
        _rows, meta = validate_paginated(
            api.list_claims(represented_veteran["officer_headers"])
        )
        assert_exact_whole(meta["total_count"], 1, "total_count")


class TestProgramInputMatchesTheProgramType:
    """A tuition credit count means nothing to a property-tax exemption."""

    @pytest.fixture
    def property_tax_program(self, api):
        """A screened veteran and a property-tax exemption program at version 1."""
        officer = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        officer_headers = make_county_officer_headers(officer["id"])
        built = create_screened_veteran(api, officer_headers)
        program = create_state_program(
            api, program_type="PROPERTY_TAX_EXEMPTION", fiscal_year=2026
        )
        return {
            "veteran_id": built["veteran"]["id"],
            "program": program,
            "program_version": read_state_program(api, program["id"])["version"],
        }

    def test_the_wrong_money_bearing_input_is_refused(self, api, property_tax_program):
        """
        "The money-bearing input matches the program type, else `ERR_PROGRAM_INPUT_MISMATCH` (422), on `POST /cvso/state-benefit-applications`."

        Design: Corner/validations/corner_program_input_must_match_the_program_type
        """
        validate_error(
            api.create_state_benefit_application(
                benefit_application_payload(
                    property_tax_program["veteran_id"],
                    property_tax_program["program"]["id"],
                    2026,
                    property_tax_program["program_version"],
                    tuition_credits_requested=12,
                ),
                INTAKE_CLERK_HEADERS,
            ),
            "ERR_PROGRAM_INPUT_MISMATCH",
            422,
        )
        _rows, meta = validate_paginated(
            api.list_state_benefit_applications(INTAKE_CLERK_HEADERS)
        )
        assert_exact_whole(meta["total_count"], 0, "total_count")

    def test_the_matching_input_files_the_application_without_committing_money(
        self, api, property_tax_program
    ):
        """
        "The money-bearing input must match the program type — a `PROPERTY_TAX_EXEMPTION` application carries `assessed_property_value_cents` greater than 0, a `TUITION_WAIVER` application carries `tuition_credits_requested` greater than 0, and a `BURIAL_BENEFIT` application carries neither — and a mismatch is `ERR_PROGRAM_INPUT_MISMATCH` at HTTP 422."
        "A successful filing sets `determination_status` to `SUBMITTED`, `disbursement_status` to `NOT_APPLICABLE`, and `gross_award_cents`, `admin_fee_cents` and `benefit_amount_cents` all to 0, and it does **not** move the program's `allocated_cents`: money is committed only at approval."

        Design: Corner/validations/corner_program_input_must_match_the_program_type
        """
        api.create_state_benefit_application(
            benefit_application_payload(
                property_tax_program["veteran_id"],
                property_tax_program["program"]["id"],
                2026,
                property_tax_program["program_version"],
                tuition_credits_requested=12,
            ),
            INTAKE_CLERK_HEADERS,
        )
        application = file_benefit_application(
            api,
            property_tax_program["veteran_id"],
            property_tax_program["program"],
            assessed_property_value_cents=8500000,
        )
        assert_application_filing_defaults(application)
        assert_cents(application["assessed_property_value_cents"], 8500000)
        _rows, meta = validate_paginated(
            api.list_state_benefit_applications(INTAKE_CLERK_HEADERS)
        )
        assert_exact_whole(meta["total_count"], 1, "total_count")
        assert_cents(
            read_state_program(api, property_tax_program["program"]["id"])[
                "allocated_cents"
            ],
            0,
        )


class TestPeerReviewRequiresEveryEvidenceItemClosedOut:
    """One request still outstanding blocks the whole submission."""

    @pytest.fixture
    def half_answered_claim(self, api):
        """A claim with a received nexus letter and a still-outstanding record request."""
        preparer = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        reviewer = create_active_representative(
            api, accreditation_type="VSO_ORG", accreditation_expires_on="2029-12-31"
        )
        ctx = create_claim_in_evidence_development(
            api,
            create_represented_veteran(api, designee=preparer),
            claimed_conditions=conditions("tinnitus"),
        )
        nexus = request_evidence(
            api,
            ctx["claim"]["id"],
            ctx["officer_headers"],
            evidence_type="NEXUS_LETTER",
            provider_name="Dr. Salazar",
            nexus_opinion_strength="AT_LEAST_AS_LIKELY_AS_NOT",
        )
        received_nexus = receive_evidence(api, nexus["id"], ctx["officer_headers"])
        outstanding = request_evidence(
            api,
            ctx["claim"]["id"],
            ctx["officer_headers"],
            evidence_type="SERVICE_TREATMENT_RECORD",
            provider_name="National Personnel Records Center",
        )
        return {
            "claim_id": ctx["claim"]["id"],
            "officer_headers": ctx["officer_headers"],
            "reviewer_id": reviewer["id"],
            "received_nexus": received_nexus,
            "outstanding": outstanding,
        }

    def test_the_outstanding_request_refuses_the_submission(
        self, api, half_answered_claim
    ):
        """
        "No evidence item of the claim is left in an open status — none in `REQUESTED` when the claim is submitted for peer review, and none in `INSUFFICIENT` when the claim is filed — else `ERR_EVIDENCE_ITEM_OUTSTANDING` (409), on a claim `SUBMIT_FOR_REVIEW` and on a claim `FILE`."

        Design: Corner/validations/corner_peer_review_requires_every_evidence_item_closed_out_first
        """
        assert half_answered_claim["outstanding"]["status"] == "REQUESTED"
        validate_error(
            api.claim_transition(
                half_answered_claim["claim_id"],
                submit_for_review_action(half_answered_claim["reviewer_id"]),
                half_answered_claim["officer_headers"],
            ),
            "ERR_EVIDENCE_ITEM_OUTSTANDING",
            409,
        )
        claim = read_claim(api, half_answered_claim["claim_id"])
        assert claim["status"] == "EVIDENCE_DEVELOPMENT"
        assert claim["peer_reviewed_by_representative_id"] is None

    def test_receiving_the_last_item_lets_the_same_submission_through(
        self, api, half_answered_claim
    ):
        """
        "The step sets `status` to `PEER_REVIEW` and `peer_reviewed_by_representative_id` to the nominated reviewer, recomputes `evidence_completeness_pct` and the preparer's `caseload_weight`, and increments the claim's `version` by 1."

        Design: Corner/validations/corner_peer_review_requires_every_evidence_item_closed_out_first
        """
        api.claim_transition(
            half_answered_claim["claim_id"],
            submit_for_review_action(half_answered_claim["reviewer_id"]),
            half_answered_claim["officer_headers"],
        )
        receive_evidence(
            api,
            half_answered_claim["outstanding"]["id"],
            half_answered_claim["officer_headers"],
        )
        submitted = submit_for_peer_review(
            api,
            half_answered_claim["claim_id"],
            half_answered_claim["reviewer_id"],
            half_answered_claim["officer_headers"],
        )
        assert submitted["status"] == "PEER_REVIEW"
        assert (
            submitted["peer_reviewed_by_representative_id"]
            == half_answered_claim["reviewer_id"]
        )

    def test_the_two_closed_out_items_score_the_claim_to_two_decimal_places(
        self, api, half_answered_claim
    ):
        """
        "A claim's `evidence_completeness_pct` is carried to exactly 2 decimal places, rounded half up, and the rounding is applied **twice** — once to each contributing evidence item's `weight_points`, and once to the resulting percentage."
        A nexus letter at 22.5 points times 1.15 rounds to 25.88, a service treatment
        record contributes 20.00, and the denominator is 40 plus 15 for the single
        claimed condition, so the claim scores 45.88 of 55 points.

        Design: Corner/validations/corner_peer_review_requires_every_evidence_item_closed_out_first
        """
        assert_pct_2dp(half_answered_claim["received_nexus"]["weight_points"], 25.88)
        received_record = receive_evidence(
            api,
            half_answered_claim["outstanding"]["id"],
            half_answered_claim["officer_headers"],
        )
        assert_pct_2dp(received_record["weight_points"], 20.00)
        submitted = submit_for_peer_review(
            api,
            half_answered_claim["claim_id"],
            half_answered_claim["reviewer_id"],
            half_answered_claim["officer_headers"],
        )
        assert_pct_2dp(submitted["evidence_completeness_pct"], 83.42)
