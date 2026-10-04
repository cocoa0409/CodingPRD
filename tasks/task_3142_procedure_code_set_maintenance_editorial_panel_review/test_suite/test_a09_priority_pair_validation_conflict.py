"""Priority-pair conflicts: which rule surfaces when two rules fail together."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, validate_paginated,
    CHAIR, STAFF, LICENSING, REVIEWER,
    api_client, set_clock, create_society, create_applicant, create_meeting,
    create_cycle, create_change, submit_into_cycle, create_licence_and_territory,
)


class TestUniquenessBeatsEvidenceTier:
    @pytest.fixture
    def descriptor_taken(self):
        """Descriptor 00007 already on file, plus a fresh applicant."""
        set_clock("2026-09-01T00:00:00Z")
        society = create_society("Eta Society", "ETA", seats=1)
        applicant = create_applicant("Eta Applicant", "MANUFACTURER",
                                     society_id=society["id"],
                                     is_entity_member=False, dues_paid_current=False)
        existing = create_change("00007", applicant["id"], society_id=society["id"],
                                 tier="TIER_I", evidence_index=60, volume=5000,
                                 organ_systems=2)
        return {"society": society, "applicant": applicant, "existing": existing}

    def test_duplicate_descriptor_is_reported_ahead_of_the_evidence_shortfall(
        self, api, descriptor_taken,
    ):
        """PRD §2.7: "Filing a second change bearing a descriptor number that already
        exists is rejected with ERR_CODE_ALREADY_EXISTS at 409, regardless of which
        applicant filed it or what kind of change it proposes."
        PRD §2.7: "A TIER_IV addition below that volume is rejected with
        ERR_EVIDENCE_INSUFFICIENT at 422."

        Design: Difficulty/priority_pair_validation_conflict/duplicate_code_beats_evidence_tier_conflict
        """
        applicant = descriptor_taken["applicant"]
        response = api.create_code_change(
            {
                "code": "00007",
                "change_type": "ADDITION",
                "category": "CATEGORY_I",
                "code_family": "000",
                "applicant_id": applicant["id"],
                "clinical_evidence_tier": "TIER_IV",
                "evidence_sufficiency_index": 10,
                "procedure_volume_threshold": 40,
                "descriptor_current": "Other descriptor",
                "descriptor_proposed": "Other descriptor revised",
                "guidelines": "None",
                "parenthetical_instructions": "None",
            },
            STAFF,
        )
        validate_error(response, ApiErrorId.ERR_CODE_ALREADY_EXISTS, expected_status=409)

    def test_refused_filing_leaves_a_single_row_for_that_descriptor(self, api, descriptor_taken):
        """PRD §2.7: "Descriptor numbers are unique across the entire code change corpus."

        Design: Difficulty/priority_pair_validation_conflict/duplicate_code_beats_evidence_tier_conflict
        """
        applicant = descriptor_taken["applicant"]
        api.create_code_change(
            {
                "code": "00007",
                "change_type": "ADDITION",
                "category": "CATEGORY_I",
                "code_family": "000",
                "applicant_id": applicant["id"],
                "clinical_evidence_tier": "TIER_IV",
                "evidence_sufficiency_index": 10,
                "procedure_volume_threshold": 40,
                "descriptor_current": "Other descriptor",
                "descriptor_proposed": "Other descriptor revised",
            },
            STAFF,
        )
        rows, meta = validate_paginated(api.list_code_changes(STAFF, {"code": "00007"}))
        assert meta["total_count"] == 1
        assert len(rows) == 1


class TestAuthorizationBeatsWorkflowState:
    @pytest.fixture
    def terminated_licence_and_change(self, api):
        """One terminated provider licence plus a draft change on file."""
        set_clock("2026-09-01T00:00:00Z")
        society = create_society("Iota Society", "IOT", seats=1)
        applicant = create_applicant("Iota Applicant", "PAYER", society_id=society["id"])
        licence, territory = create_licence_and_territory(
            territory_code="US-MIDWEST", method="SITE", licensee_type="PROVIDER",
            licensee_name="Midwest Clinic", sales_unit_count=12, expected_users=15,
            activate=True,
        )
        validate_success(api.terminate_licensing_agreement(
            licence["id"], {"reason": "Non-renewal"}, LICENSING))
        change = create_change("00009", applicant["id"], society_id=society["id"],
                               tier="TIER_I", evidence_index=50, volume=900,
                               organ_systems=2)
        return {"licence": licence, "change": change}

    def test_licensee_holding_no_posting_permission_fails_at_authorization(
        self, api, terminated_licence_and_change,
    ):
        """PRD §2.1: "Releasing the annual code set, publishing an errata notice and
        posting a change for public comment are reserved to EditorialStaff alone."
        PRD §2.1: "An acting role that is not permitted for the requested operation is
        rejected with ERR_UNAUTHORIZED at 403."
        PRD §4: "POST | /cpt/code-changes/{id}/postings | Post a change for public
        comment | EditorialStaff".

        Design: Difficulty/priority_pair_validation_conflict/action_permission_beats_workflow_state_conflict
        """
        licence = terminated_licence_and_change["licence"]
        change = terminated_licence_and_change["change"]
        response = api.post_code_change(
            change["id"],
            {"comment_period_open_at": "2026-09-01T00:00:00Z",
             "comment_period_close_at": "2026-09-20T00:00:00Z"},
            {"X-User-ID": licence["id"], "X-User-Role": "Licensee"},
        )
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    def test_refused_posting_leaves_the_change_unscreened(self, api, terminated_licence_and_change):
        """PRD §3.1: "administrative_review_status begins at UNDER_ADMIN_REVIEW,
        posting_state begins at NOT_POSTED, and review_status begins at DRAFT."

        Design: Difficulty/priority_pair_validation_conflict/action_permission_beats_workflow_state_conflict
        """
        licence = terminated_licence_and_change["licence"]
        change = terminated_licence_and_change["change"]
        api.post_code_change(
            change["id"],
            {"comment_period_open_at": "2026-09-01T00:00:00Z",
             "comment_period_close_at": "2026-09-20T00:00:00Z"},
            {"X-User-ID": licence["id"], "X-User-Role": "Licensee"},
        )
        row = validate_success(api.get_code_change(change["id"], STAFF))
        assert row["review_status"] == "DRAFT"
        assert row["posting_state"] == "NOT_POSTED"


class TestReviewReadinessBeatsSupportData:
    @pytest.fixture
    def tier_four_emerging_change(self):
        """A TIER_IV CATEGORY_III addition still under administrative review."""
        set_clock("2026-09-01T00:00:00Z")
        society = create_society("Theta Society", "THT", seats=2)
        applicant = create_applicant("Theta Applicant", "HIT_VENDOR",
                                     society_id=society["id"])
        change = create_change("00008", applicant["id"], society_id=society["id"],
                               category="CATEGORY_III", tier="TIER_IV",
                               evidence_index=15, volume=120, organ_systems=2)
        return {"society": society, "applicant": applicant, "change": change}

    def test_tier_four_change_is_not_reviewable_ahead_of_the_support_check(
        self, api, tier_four_emerging_change,
    ):
        """PRD §3.3: "The review may be opened only against a change whose
        clinical_evidence_tier is TIER_I, TIER_II or TIER_III — a TIER_IV change is not
        reviewable — and only while that change's administrative_review_status is still
        UNDER_ADMIN_REVIEW".
        PRD §3.3: "A review attempted outside those conditions is rejected with
        ERR_ADVISORY_REVIEW_NOT_READY at 409."

        Design: Difficulty/priority_pair_validation_conflict/admin_review_priority_beats_support_conflict
        """
        change = tier_four_emerging_change["change"]
        response = api.create_advisory_committee_review(
            {
                "change_id": change["id"],
                "committee_name": "CPT_ADVISOR",
                "quorum_met": False,
                "yes_votes": 0,
                "no_votes": 0,
            },
            REVIEWER,
        )
        validate_error(response, ApiErrorId.ERR_ADVISORY_REVIEW_NOT_READY, expected_status=409)

    def test_refused_review_does_not_enroll_the_change(self, api, tier_four_emerging_change):
        """PRD §3.3: "A review opens with decision at PENDING and review_status at OPEN,
        and its reviewed_at instant is left empty until the review closes."
        PRD §3.3: "The review may be opened only against a change whose
        clinical_evidence_tier is TIER_I, TIER_II or TIER_III — a TIER_IV change is not
        reviewable".

        Design: Difficulty/priority_pair_validation_conflict/admin_review_priority_beats_support_conflict
        """
        change = tier_four_emerging_change["change"]
        api.create_advisory_committee_review(
            {
                "change_id": change["id"],
                "committee_name": "CPT_ADVISOR",
                "quorum_met": False,
                "yes_votes": 0,
                "no_votes": 0,
            },
            REVIEWER,
        )
        reviews, meta = validate_paginated(
            api.list_change_committee_reviews(change["id"], STAFF))
        assert meta["total_count"] == 0
        assert reviews == []