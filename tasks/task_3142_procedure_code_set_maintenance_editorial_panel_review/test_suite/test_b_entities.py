"""Corner coverage indexed under the entity surface: defaults, 404s, listing meta."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, NON_EXISTENT_UUID,
    assert_specialty_society,
    STAFF,
    api_client, set_clock, create_society, create_applicant, create_change,
)


class TestCodeChangeDefaults:
    def test_omitted_optional_fields_return_declared_defaults(self, api):
        """PRD §3.1: "administrative_review_status begins at UNDER_ADMIN_REVIEW,
        posting_state begins at NOT_POSTED, and review_status begins at DRAFT."
        PRD §3.1: "the disposition determination (which begins at PENDING)".
        PRD §3.1: "organ_system_count, the number of organ systems the code addresses,
        which defaults to 1".
        PRD §3.1: "cycles_in_process records how many editorial panel meetings the
        change has already been carried forward, defaulting to 0."

        Design: Corner/entities/code_change_defaults_applied_when_optional_fields_omitted
        """
        set_clock("2026-09-01T00:00:00Z")
        applicant = create_applicant("Default Applicant", "PHYSICIAN")
        change = validate_success(api.create_code_change(
            {
                "code": "00050",
                "change_type": "ADDITION",
                "category": "CATEGORY_I",
                "code_family": "000",
                "applicant_id": applicant["id"],
                "clinical_evidence_tier": "TIER_II",
                "procedure_volume_threshold": 800,
                "descriptor_current": "Placeholder descriptor",
            },
            STAFF,
        ), 201)
        assert change["organ_system_count"] == 1
        assert change["cycles_in_process"] == 0
        assert change["determination"] == "PENDING"
        assert change["administrative_review_status"] == "UNDER_ADMIN_REVIEW"
        assert change["review_status"] == "DRAFT"


class TestUnresolvableIdentifier:
    def test_reading_an_unassigned_applicant_id_returns_not_found(self, api):
        """PRD §2.4: "Resolution of path-identified resources and of referenced body
        foreign keys is evaluated third, left to right, carrying ERR_NOT_FOUND."

        Design: Corner/entities/change_applicant_not_found_returns_404
        """
        set_clock("2026-09-01T00:00:00Z")
        response = api.get_applicant("22222222-2222-4222-8222-222222222222", STAFF)
        validate_error(response, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestSpecialtySocietyDefaults:
    def test_omitted_geographic_indices_default_to_national(self, api):
        """PRD §3.1: "Its geographic practice cost indices — gpci_work, gpci_pe and
        gpci_mp — each default to 1.0000 and are applied later when RVUs are converted
        to dollars."
        PRD §3.1: "it is initialized to 0 when the society is registered."

        Design: Corner/entities/specialty_society_default_gpci_is_national
        """
        set_clock("2026-09-01T00:00:00Z")
        society = validate_success(api.create_specialty_society(
            {"name": "National Society", "specialty_code": "NAT"}, STAFF), 201)
        assert society["gpci_work"] == 1.0000
        assert society["gpci_pe"] == 1.0000
        assert society["gpci_mp"] == 1.0000
        assert society["cea_credit_balance"] == 0
        assert_specialty_society(society)


class TestDescriptorFormat:
    def test_trailing_letter_outside_a_through_j_is_malformed(self, api):
        """PRD §2.7: "A descriptor number is supplied in the code field and must be
        exactly 5 characters long. When the final character of a descriptor is a letter
        rather than a digit, that letter must fall within A through J inclusive; a
        descriptor ending in K, or in any letter beyond that range, is malformed. A
        malformed descriptor is rejected with ERR_CODE_FORMAT_INVALID at 422."

        Design: Corner/entities/code_format_invalid_on_bad_trailing_letter
        """
        set_clock("2026-09-01T00:00:00Z")
        applicant = create_applicant("Format Applicant", "OTHER",
                                     is_entity_member=False, dues_paid_current=False)
        response = api.create_code_change(
            {
                "code": "0000Z",
                "change_type": "ADDITION",
                "category": "CATEGORY_I",
                "code_family": "000",
                "applicant_id": applicant["id"],
                "clinical_evidence_tier": "TIER_II",
                "procedure_volume_threshold": 900,
                "descriptor_current": "Placeholder descriptor",
            },
            STAFF,
        )
        validate_error(response, ApiErrorId.ERR_CODE_FORMAT_INVALID, expected_status=422)


class TestListEnvelope:
    def test_change_list_carries_the_declared_pagination_defaults(self, api):
        """PRD §2.3: "limit caps the number of records returned and defaults to 10; it
        may not be lower than 1 and may not exceed 100, and a value outside that range
        is rejected rather than clamped. offset skips that many leading records and
        defaults to 0."
        PRD §2.3: "total_count reflects the size of the full matching set before
        pagination is applied, and has_more is true whenever further pages remain
        beyond the current window."

        Design: Corner/entities/pagination_defaults_and_has_more_on_change_list
        """
        set_clock("2026-09-01T00:00:00Z")
        applicant = create_applicant("Page Applicant", "PAYER")
        create_change("00060", applicant["id"], volume=700)
        create_change("00061", applicant["id"], volume=700,
                      descriptor_current="Second placeholder")
        rows, meta = validate_paginated(api.list_code_changes(STAFF))
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert len(rows) == 2