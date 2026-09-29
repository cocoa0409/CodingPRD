"""
The two long cascades: revoking accreditation and revising a decision.

Each fixture builds the whole chain the cascade is supposed to walk, then fires
one request and lets the tests read every hop.
"""

import pytest
from test_helpers import (
    CLOCK_START_INSTANT,
    INTAKE_CLERK_HEADERS,
    STATE_AUDITOR_HEADERS,
    approve_application_action,
    assert_caseload_weight,
    assert_cents,
    assert_combined_rating,
    assert_exact_whole,
    assign_representative_payload,
    book_appointment,
    conditions,
    create_active_representative,
    create_claim_in_evidence_development,
    create_claim_in_peer_review,
    create_exam_site,
    create_represented_veteran,
    create_state_program,
    decision_review_payload,
    elect_review_action,
    file_benefit_application,
    file_claim,
    file_review_action,
    instant,
    mark_claim_ready,
    read_application,
    read_claim,
    read_exam_site,
    read_representative,
    read_state_program,
    read_veteran,
    record_decision,
    revoke_accreditation_action,
    set_clock,
    set_clock_date,
    validate_success,
    SYSTEM_ADMIN_HEADERS,
)

DEPENDENT_PROFILE = {
    "date_of_birth": "1979-03-04",
    "service_start_date": "2001-09-11",
    "service_end_date": "2005-09-10",
    "household_income_cents": 1500000,
    "net_worth_cents": 2000000,
    "dependent_count": 2,
    "homeless_status": "NOT_HOMELESS",
    "referral_source": "WALK_IN",
}


@pytest.fixture
def revoked_accreditation(api):
    """
    A representative holding one designation, one open claim with a scheduled
    examination and one assigned veteran, whose accreditation is then revoked.
    """
    set_clock(api, CLOCK_START_INSTANT)
    rep = create_active_representative(
        api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
    )
    base = create_represented_veteran(api, designee=rep)
    validate_success(
        api.assign_representative(
            base["veteran"]["id"],
            assign_representative_payload(rep["id"]),
            INTAKE_CLERK_HEADERS,
        )
    )
    ctx = create_claim_in_evidence_development(
        api, base, claimed_conditions=conditions("tinnitus")
    )
    site = create_exam_site(api, concurrent_capacity=2, buffer_minutes=15)
    appointment = book_appointment(
        api,
        ctx["claim"]["id"],
        site["id"],
        instant("2026-09-01", "09:00:00"),
        instant("2026-09-01", "10:00:00"),
        ctx["officer_headers"],
    )
    before = read_representative(api, rep["id"])
    revoked = validate_success(
        api.representative_accreditation(
            rep["id"],
            revoke_accreditation_action("Board sanction"),
            SYSTEM_ADMIN_HEADERS,
        )
    )
    return {
        "rep": rep,
        "before": before,
        "revoked": revoked,
        "veteran_id": base["veteran"]["id"],
        "poa_id": base["poa"]["id"],
        "claim_id": ctx["claim"]["id"],
        "appointment_id": appointment["id"],
        "site_id": site["id"],
        "officer_headers": ctx["officer_headers"],
    }


@pytest.fixture
def revised_decision(api):
    """
    A seventy-percent grant that funded a state award, appealed, reopened and
    then re-decided as a thirty-percent partial grant.
    """
    set_clock(api, CLOCK_START_INSTANT)
    preparer = create_active_representative(
        api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
    )
    reviewer = create_active_representative(
        api, accreditation_type="VSO_ORG", accreditation_expires_on="2029-12-31"
    )
    base = create_represented_veteran(api, designee=preparer, **DEPENDENT_PROFILE)
    ctx = create_claim_in_peer_review(
        api,
        base,
        reviewer=reviewer,
        intent_to_file_date="2025-09-15",
        claimed_conditions=conditions("tinnitus"),
    )
    mark_claim_ready(api, ctx["claim"]["id"], ctx["reviewer_headers"])
    set_clock_date(api, "2026-08-10", "09:00:00")
    file_claim(api, ctx["claim"]["id"], ctx["officer_headers"], "2026-08-10")
    set_clock_date(api, "2026-12-20", "09:00:00")
    record_decision(
        api,
        ctx["claim"]["id"],
        ctx["officer_headers"],
        decision_outcome="GRANTED",
        awarded_rating_pct=70,
        decided_on="2026-12-20",
    )

    program = create_state_program(
        api,
        program_type="TUITION_WAIVER",
        fiscal_year=2026,
        annual_pool_cents=990000,
        min_rating_pct=50,
        max_award_cents=100000000,
    )
    application = file_benefit_application(
        api, base["veteran"]["id"], program, tuition_credits_requested=12
    )
    application = validate_success(
        api.application_determination(
            application["id"], approve_application_action(), STATE_AUDITOR_HEADERS
        )
    )

    set_clock_date(api, "2027-01-10", "09:00:00")
    review = validate_success(
        api.create_decision_review(
            decision_review_payload(ctx["claim"]["id"], "HIGHER_LEVEL_REVIEW"),
            ctx["officer_headers"],
        ),
        201,
    )
    validate_success(
        api.decision_review_status(
            review["id"], elect_review_action("2027-01-10"), ctx["officer_headers"]
        )
    )
    review = validate_success(
        api.decision_review_status(
            review["id"], file_review_action("2027-01-10"), ctx["officer_headers"]
        )
    )

    set_clock_date(api, "2027-02-15", "09:00:00")
    revised = record_decision(
        api,
        ctx["claim"]["id"],
        ctx["officer_headers"],
        decision_outcome="PARTIAL_GRANT",
        awarded_rating_pct=30,
        decided_on="2027-02-15",
    )
    return {
        "review_id": review["id"],
        "claim": revised,
        "veteran_id": base["veteran"]["id"],
        "application_id": application["id"],
        "program_id": program["id"],
        "officer_headers": ctx["officer_headers"],
    }


class TestAccreditationRevocationCascade:
    """Five hops from the roster row down to the examination site ledger."""

    def test_the_roster_row_is_revoked_and_its_load_falls_to_zero(
        self, api, revoked_accreditation
    ):
        """
        Before the revocation the representative held one designation worth a
        point and one claim in development worth three, since
        "Each of the representative's `ACTIVE` designations contributes 1 point."
        "**Hop one** sets `accreditation_status` to `REVOKED`, stores the reason".

        Design: Difficulty/transitive_cascade/accreditation_revocation_cascades_through_poa_claim_appointment_to_site_ledger
        """
        before = revoked_accreditation["before"]
        assert_caseload_weight(before["caseload_weight"], 4)
        assert_exact_whole(before["active_poa_count"], 1, "active_poa_count")
        after = read_representative(api, revoked_accreditation["rep"]["id"])
        assert after["accreditation_status"] == "REVOKED"
        assert after["revocation_reason"] == "Board sanction"
        assert_exact_whole(after["active_poa_count"], 0, "active_poa_count")
        assert_caseload_weight(after["caseload_weight"], 0)

    def test_the_assignment_and_the_designation_are_both_torn_down(
        self, api, revoked_accreditation
    ):
        """
        Hop one also "clears `assigned_representative_id` on every veteran whose case was assigned to this representative",
        and hop two moves the designation "to `REVOKED` with `revoked_reason` set to the literal string `REPRESENTATIVE_ACCREDITATION_REVOKED`".

        Design: Difficulty/transitive_cascade/accreditation_revocation_cascades_through_poa_claim_appointment_to_site_ledger
        """
        veteran = read_veteran(api, revoked_accreditation["veteran_id"])
        assert veteran["assigned_representative_id"] is None
        poa = validate_success(
            api.get_power_of_attorney(
                revoked_accreditation["poa_id"], SYSTEM_ADMIN_HEADERS
            )
        )
        assert poa["status"] == "REVOKED"
        assert poa["revoked_reason"] == "REPRESENTATIVE_ACCREDITATION_REVOKED"

    def test_the_open_claim_falls_back_to_draft_without_its_designation(
        self, api, revoked_accreditation
    ):
        """
        "**Hop three** follows from those designations having been revoked: every claim citing one of them whose `status` is `EVIDENCE_DEVELOPMENT`, `PEER_REVIEW` or `READY_TO_FILE` falls back to `DRAFT` with both `poa_id` and `peer_reviewed_by_representative_id` set to null".

        Design: Difficulty/transitive_cascade/accreditation_revocation_cascades_through_poa_claim_appointment_to_site_ledger
        """
        claim = read_claim(api, revoked_accreditation["claim_id"])
        assert claim["status"] == "DRAFT"
        assert claim["poa_id"] is None
        assert claim["peer_reviewed_by_representative_id"] is None

    def test_the_examination_is_cancelled_and_the_site_ledger_restored(
        self, api, revoked_accreditation
    ):
        """
        "**Hop four** follows from those claims having fallen back to `DRAFT`: every examination appointment belonging to one of them whose `status` is `SCHEDULED` moves to `CANCELLED` with `cancellation_reason` set to the literal string `REPRESENTATION_CASCADE`."

        Design: Difficulty/transitive_cascade/accreditation_revocation_cascades_through_poa_claim_appointment_to_site_ledger
        """
        appointment = validate_success(
            api.get_exam_appointment(
                revoked_accreditation["appointment_id"], SYSTEM_ADMIN_HEADERS
            )
        )
        assert appointment["status"] == "CANCELLED"
        assert appointment["cancellation_reason"] == "REPRESENTATION_CASCADE"
        site = read_exam_site(api, revoked_accreditation["site_id"])
        assert_exact_whole(site["booked_slot_count"], 0, "booked_slot_count")


class TestRevisedDecisionCascade:
    """A reopened claim re-decided lower drags the state award down with it."""

    def test_the_appeal_clock_is_derived_from_the_decision_notice(
        self, api, revised_decision
    ):
        """
        "`deadline_on` is `decision_notice_date` plus 365 days."
        "`days_remaining` is `deadline_on` minus the logical-clock date in whole days, and it is **re-derived on every read**, so moving the logical clock changes what a read reports without any write having occurred."

        Design: Difficulty/transitive_cascade/revised_decision_cascades_rating_reduction_through_application_to_program_pool
        """
        review = validate_success(
            api.get_decision_review(
                revised_decision["review_id"], revised_decision["officer_headers"]
            )
        )
        assert review["decision_notice_date"] == "2026-12-20"
        assert review["deadline_on"] == "2027-12-20"
        assert_exact_whole(review["days_remaining"], 308, "days_remaining")
        assert review["status"] == "FILED"

    def test_the_reopened_claim_records_the_revised_award(self, api, revised_decision):
        """
        Filing the review "reopens the underlying claim: that claim moves from `DECIDED` back to `FILED` and its `reopen_count` is incremented by 1",
        and the next decision recomputes the money from the same intent-to-file anchor.

        Design: Difficulty/transitive_cascade/revised_decision_cascades_rating_reduction_through_application_to_program_pool
        """
        claim = read_claim(
            api, revised_decision["claim"]["id"], revised_decision["officer_headers"]
        )
        assert claim["status"] == "DECIDED"
        assert claim["decision_outcome"] == "PARTIAL_GRANT"
        assert_exact_whole(claim["reopen_count"], 1, "reopen_count")
        assert claim["effective_date"] == "2025-09-15"
        assert_cents(claim["retro_award_cents"], 1191700)

    def test_the_veteran_rating_and_band_follow_the_revision_down(
        self, api, revised_decision
    ):
        """
        "**Hop two** follows from the claim now being `DECIDED`: the veteran's `combined_rating_pct` is recomputed and `priority_group` is re-derived from it."

        Design: Difficulty/transitive_cascade/revised_decision_cascades_rating_reduction_through_application_to_program_pool
        """
        veteran = read_veteran(api, revised_decision["veteran_id"])
        assert_combined_rating(veteran["combined_rating_pct"], 30)
        assert veteran["priority_group"] == "P2"

    def test_the_state_award_is_denied_and_the_pool_released(self, api, revised_decision):
        """
        "**Hop three** follows from the rating having changed: every state benefit application of that veteran whose `determination_status` is `APPROVED` and whose program's `min_rating_pct` now exceeds the new `combined_rating_pct` has its `determination_status` set to `DENIED` with `determination_reason` set to the literal string `RATING_REDUCED_BELOW_PROGRAM_MINIMUM`, and its `disbursement_status` set to `CLAWED_BACK`."

        Design: Difficulty/transitive_cascade/revised_decision_cascades_rating_reduction_through_application_to_program_pool
        """
        application = read_application(api, revised_decision["application_id"])
        assert application["determination_status"] == "DENIED"
        assert application["determination_reason"] == (
            "RATING_REDUCED_BELOW_PROGRAM_MINIMUM"
        )
        assert application["disbursement_status"] == "CLAWED_BACK"
        program = read_state_program(api, revised_decision["program_id"])
        assert_cents(program["allocated_cents"], 0)
