"""
The hold-and-resubmit loop on separation paperwork.

One family corrects a peacetime interval into a wartime one and re-screens the
veteran; the other shows a held document closing the door on claim intake.
"""

import pytest
from test_helpers import (
    CLOCK_START_INSTANT,
    assert_exact_whole,
    claim_payload,
    conditions,
    create_active_representative,
    create_represented_veteran,
    create_veteran,
    hold_discharge_document,
    make_county_officer_headers,
    read_screens,
    read_veteran,
    resubmit_document_payload,
    screen_veteran,
    set_clock,
    submit_discharge_document,
    validate_error,
    validate_success,
    verify_discharge_document,
)

MEANS_TESTED_PROFILE = {
    "date_of_birth": "1965-05-20",
    "household_income_cents": 1500000,
    "net_worth_cents": 2000000,
    "dependent_count": 2,
    "homeless_status": "NOT_HOMELESS",
    "referral_source": "WALK_IN",
}


@pytest.fixture
def corrected_service_interval(api):
    """
    A document whose peacetime interval was held, corrected to a ninety-day
    wartime interval, verified, and then screened.
    """
    set_clock(api, CLOCK_START_INSTANT)
    officer = create_active_representative(
        api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
    )
    officer_headers = make_county_officer_headers(officer["id"])
    veteran = create_veteran(
        api,
        service_start_date="1985-01-01",
        service_end_date="1989-12-31",
        **MEANS_TESTED_PROFILE,
    )
    document = submit_discharge_document(
        api,
        veteran["id"],
        claimed_service_start="1985-01-01",
        claimed_service_end="1989-12-31",
        claimed_character_of_service="HONORABLE",
    )
    hold_discharge_document(
        api, document["id"], officer_headers, reason="Service dates disagree with the file"
    )
    resubmitted = validate_success(
        api.resubmit_discharge_document(
            document["id"],
            resubmit_document_payload(
                claimed_service_start="2001-09-11", claimed_service_end="2001-12-09"
            ),
            officer_headers,
        )
    )
    verified = verify_discharge_document(api, document["id"], officer_headers)
    screen = screen_veteran(api, veteran["id"], officer_headers)
    return {
        "veteran_id": veteran["id"],
        "document": verified,
        "resubmitted": resubmitted,
        "screen": screen,
        "officer_headers": officer_headers,
    }


@pytest.fixture
def claim_blocked_by_hold(api):
    """
    A represented veteran whose newest document is sitting in DISCREPANCY_HELD,
    with the claim body the officer wants to post.
    """
    set_clock(api, CLOCK_START_INSTANT)
    preparer = create_active_representative(
        api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
    )
    base = create_represented_veteran(api, designee=preparer, **MEANS_TESTED_PROFILE)
    officer_headers = base["officer_headers"]
    replacement = submit_discharge_document(
        api,
        base["veteran"]["id"],
        claimed_service_start="2001-09-11",
        claimed_service_end="2004-09-10",
        claimed_character_of_service="HONORABLE",
    )
    hold_discharge_document(
        api, replacement["id"], officer_headers, reason="Separation date is illegible"
    )
    payload = claim_payload(
        base["veteran"]["id"],
        base["poa"]["id"],
        claimed_conditions=conditions("tinnitus"),
    )
    return {
        "base": base,
        "document_id": replacement["id"],
        "officer_headers": officer_headers,
        "preparer": preparer,
        "payload": payload,
    }


class TestResubmissionRecomputesWartimeService:
    """Corrected dates are what the wartime count is taken against."""

    def test_the_loop_counts_one_completed_pass(self, api, corrected_service_interval):
        """
        Resubmission "overwrites whichever of `claimed_service_start`, `claimed_service_end` and `claimed_character_of_service` the caller supplies, clears `discrepancy_reason`, increments `resubmission_count` by 1, returns the document to `PENDING_VERIFICATION`".

        Design: Difficulty/non_linear_state_machine/discharge_document_resubmission_cycle_recomputes_wartime_days_from_corrected_dates
        """
        resubmitted = corrected_service_interval["resubmitted"]
        assert resubmitted["verification_status"] == "PENDING_VERIFICATION"
        assert_exact_whole(resubmitted["resubmission_count"], 1, "resubmission_count")
        assert resubmitted["claimed_service_start"] == "2001-09-11"
        assert resubmitted["claimed_service_end"] == "2001-12-09"
        assert corrected_service_interval["document"]["verification_status"] == "VERIFIED"

    def test_verification_counts_the_corrected_wartime_interval(
        self, api, corrected_service_interval
    ):
        """
        Verifying "recomputes the veteran's `wartime_service_days` from the document's claimed service interval",
        and the overlap "contributes the number of days from the start to the end plus one — the plus one making both ends inclusive".

        Design: Difficulty/non_linear_state_machine/discharge_document_resubmission_cycle_recomputes_wartime_days_from_corrected_dates
        """
        veteran = read_veteran(api, corrected_service_interval["veteran_id"])
        assert_exact_whole(veteran["wartime_service_days"], 90, "wartime_service_days")
        assert veteran["discharge_doc_status"] == "VERIFIED"
        assert veteran["character_of_service"] == "HONORABLE"

    def test_the_first_screen_reads_the_recomputed_wartime_total(
        self, api, corrected_service_interval
    ):
        """
        The screen freezes the count, and
        "`PENSION` is eligible when basic eligibility holds **and** the veteran's `wartime_service_days` is at least 90 days"
        alongside the income and net-worth ceilings.

        Design: Difficulty/non_linear_state_machine/discharge_document_resubmission_cycle_recomputes_wartime_days_from_corrected_dates
        """
        screen = corrected_service_interval["screen"]
        assert_exact_whole(screen["screen_sequence"], 1, "screen_sequence")
        assert screen["basic_eligibility"] is True
        assert_exact_whole(
            screen["wartime_service_days_at_screen"], 90, "wartime_service_days_at_screen"
        )
        assert screen["category_results"]["PENSION"]["eligible"] is True

    def test_the_screen_bands_the_veteran_and_counts_three_categories(
        self, api, corrected_service_interval
    ):
        """
        With no rating on file, "`STATE_PROPERTY_TAX_EXEMPTION` is eligible when basic eligibility holds **and** the veteran's `combined_rating_pct` is at least 30"
        fails, and "`eligible_category_count` is simply how many of the six keys came out true, a value from 0 through 6".

        Design: Difficulty/non_linear_state_machine/discharge_document_resubmission_cycle_recomputes_wartime_days_from_corrected_dates
        """
        screen = corrected_service_interval["screen"]
        assert screen["category_results"]["STATE_PROPERTY_TAX_EXEMPTION"]["eligible"] is (
            False
        )
        assert_exact_whole(screen["eligible_category_count"], 3, "eligible_category_count")
        assert screen["priority_group_assigned"] == "P3"
        veteran = read_veteran(api, corrected_service_interval["veteran_id"])
        assert veteran["intake_status"] == "SCREENED"
        assert len(read_screens(api, corrected_service_interval["veteran_id"])) == 1


class TestClaimIntakeGatedOnVerification:
    """A held document blocks claim creation until it is corrected and verified."""

    def test_a_held_document_refuses_claim_creation(self, api, claim_blocked_by_hold):
        """
        The mirror "always reflects the `verification_status` of the veteran's document with the greatest `created_at`",
        and the gate is that "The veteran's `discharge_doc_status` is `VERIFIED`, else `ERR_DISCHARGE_NOT_VERIFIED` (409)".

        Design: Difficulty/cross_entity_state_dependency/claim_creation_blocked_while_discharge_document_is_discrepancy_held_and_allowed_after_verification
        """
        veteran = read_veteran(api, claim_blocked_by_hold["base"]["veteran"]["id"])
        assert veteran["discharge_doc_status"] == "DISCREPANCY_HELD"
        response = api.create_claim(
            claim_blocked_by_hold["payload"], claim_blocked_by_hold["officer_headers"]
        )
        validate_error(response, "ERR_DISCHARGE_NOT_VERIFIED", 409)

    def test_the_identical_body_is_accepted_once_the_document_is_verified(
        self, api, claim_blocked_by_hold
    ):
        """
        Only the document moved between the two attempts:
        "Holding a discrepancy" "moves the document to `DISCREPANCY_HELD`, mirrors that onto the veteran's `discharge_doc_status`, and bumps both versions".

        Design: Difficulty/cross_entity_state_dependency/claim_creation_blocked_while_discharge_document_is_discrepancy_held_and_allowed_after_verification
        """
        officer_headers = claim_blocked_by_hold["officer_headers"]
        validate_error(
            api.create_claim(claim_blocked_by_hold["payload"], officer_headers),
            "ERR_DISCHARGE_NOT_VERIFIED",
            409,
        )
        validate_success(
            api.resubmit_discharge_document(
                claim_blocked_by_hold["document_id"],
                resubmit_document_payload(claimed_service_end="2005-09-10"),
                officer_headers,
            )
        )
        verify_discharge_document(
            api, claim_blocked_by_hold["document_id"], officer_headers
        )
        claim = validate_success(
            api.create_claim(claim_blocked_by_hold["payload"], officer_headers), 201
        )
        assert claim["status"] == "DRAFT"
        assert claim["prepared_by_representative_id"] == (
            claim_blocked_by_hold["preparer"]["id"]
        )

    def test_verification_restores_the_veteran_mirror_field(
        self, api, claim_blocked_by_hold
    ):
        """
        Verifying "sets the veteran's `discharge_doc_status` to `VERIFIED`, recomputes the veteran's `wartime_service_days` from the document's claimed service interval",
        which is what re-opens claim intake.

        Design: Difficulty/cross_entity_state_dependency/claim_creation_blocked_while_discharge_document_is_discrepancy_held_and_allowed_after_verification
        """
        officer_headers = claim_blocked_by_hold["officer_headers"]
        validate_success(
            api.resubmit_discharge_document(
                claim_blocked_by_hold["document_id"],
                resubmit_document_payload(claimed_service_end="2005-09-10"),
                officer_headers,
            )
        )
        verify_discharge_document(
            api, claim_blocked_by_hold["document_id"], officer_headers
        )
        veteran = read_veteran(api, claim_blocked_by_hold["base"]["veteran"]["id"])
        assert veteran["discharge_doc_status"] == "VERIFIED"
