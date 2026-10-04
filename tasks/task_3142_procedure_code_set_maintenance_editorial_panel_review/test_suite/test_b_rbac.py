"""Corner coverage indexed under the role surface."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, LICENSING, TEST_USERS,
    api_client, set_clock, create_society, create_applicant, create_change,
    create_licence_and_territory,
)


class TestRoleDenials:
    @pytest.fixture
    def active_licence(self):
        """An active provider licence on a site-method territory."""
        set_clock("2026-09-01T00:00:00Z")
        licence, territory = create_licence_and_territory(
            territory_code="US-ALASKA", method="SITE", licensee_type="PROVIDER",
            licensee_name="Alaska Clinic", sales_unit_count=5, expected_users=7,
            activate=True,
        )
        return {"licence": licence, "territory": territory}

    def test_a_committee_reviewer_cannot_terminate_a_licence(self, api, active_licence):
        """PRD §2.1: "Termination is available from either ACTIVE or SUSPENDED and is
        terminal."
        PRD §2.1: "An acting role that is not permitted for the requested operation is
        rejected with ERR_UNAUTHORIZED at 403."

        Design: Corner/rbac/committee_reviewer_cannot_terminate_licence
        """
        licence = active_licence["licence"]
        response = api.terminate_licensing_agreement(
            licence["id"], {"reason": "Committee attempt"}, TEST_USERS["committee_reviewer_headers"])
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    def test_the_refused_termination_leaves_the_licence_active(self, api, active_licence):
        """PRD §3.9: "Activation moves it to ACTIVE. Suspension moves an ACTIVE licence
        to SUSPENDED."

        Design: Corner/rbac/committee_reviewer_cannot_terminate_licence
        """
        licence = active_licence["licence"]
        api.terminate_licensing_agreement(
            licence["id"], {"reason": "Committee attempt"}, TEST_USERS["committee_reviewer_headers"])
        row = validate_success(api.get_licensing_agreement(licence["id"], LICENSING))
        assert row["agreement_status"] == "ACTIVE"


class TestLicenseeListingScope:
    @pytest.fixture
    def active_licence(self):
        set_clock("2026-09-01T00:00:00Z")
        licence, territory = create_licence_and_territory(
            territory_code="US-SIERRA", method="SITE", licensee_type="PROVIDER",
            licensee_name="Sierra Clinic", sales_unit_count=5, expected_users=8,
            activate=True,
        )
        return {"licence": licence, "territory": territory}

    def test_a_licensee_cannot_list_the_code_change_collection(self, api, active_licence):
        """PRD §2.1: "An acting role that is not permitted for the requested operation
        is rejected with ERR_UNAUTHORIZED at 403."
        PRD §4: "GET | /cpt/code-changes | List code changes | EditorialStaff,
        EditorialPanelChair, CommitteeReviewer".

        Design: Corner/rbac/licensee_cannot_list_all_code_changes
        """
        licence = active_licence["licence"]
        headers = {"X-User-ID": licence["id"], "X-User-Role": "Licensee"}
        response = api.list_code_changes(headers)
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    def test_a_licensee_may_still_read_its_own_licence(self, api, active_licence):
        """PRD §2.1: "When X-User-Role is Licensee, X-User-ID is the id of the acting
        LicensingAgreement".
        PRD §4: "GET | /cpt/licensing-agreements/{id} | Read one licensing agreement |
        LicensingOfficer, EditorialStaff, Licensee".

        Design: Corner/rbac/licensee_cannot_list_all_code_changes
        """
        licence = active_licence["licence"]
        headers = {"X-User-ID": licence["id"], "X-User-Role": "Licensee"}
        row = validate_success(api.get_licensing_agreement(licence["id"], headers))
        assert row["licensee_name"] == "Sierra Clinic"


class TestUnauthenticatedRequest:
    def test_a_request_naming_no_role_is_rejected_before_any_lookup(self, api):
        """PRD §2.1: "Every request must carry two headers. X-User-ID identifies the
        acting user or organization, and X-User-Role names the capacity in which that
        identity is acting. A request that omits either header, that carries a
        malformed value, or that names a role outside the declared set is rejected
        before any business rule is consulted, and the rejection carries
        ERR_UNAUTHENTICATED with a 401 status."

        Design: Corner/rbac/unauthenticated_request_returns_401
        """
        set_clock("2026-09-01T00:00:00Z")
        response = api.list_code_changes({})
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestBodyForeignKeyIntegrity:
    def test_a_change_naming_an_unresolvable_applicant_is_refused(self, api):
        """PRD §2.6: "The same left-to-right rule governs body-supplied foreign keys: a
        referenced row that does not resolve produces ERR_NOT_FOUND rather than a
        validation error, and this check runs before business constraints are consulted."

        Design: Corner/rbac/app_linkage_owned_by_different_change
        """
        set_clock("2026-09-01T00:00:00Z")
        create_applicant("Integrity Applicant", "PHYSICIAN")
        response = api.create_code_change(
            {
                "code": "00101",
                "change_type": "ADDITION",
                "category": "CATEGORY_I",
                "code_family": "001",
                "applicant_id": "33333333-3333-4333-8333-333333333333",
                "clinical_evidence_tier": "TIER_II",
                "procedure_volume_threshold": 700,
                "descriptor_current": "Placeholder descriptor",
            },
            TEST_USERS["editorial_staff_headers"],
        )
        validate_error(response, ApiErrorId.ERR_NOT_FOUND, expected_status=404)